"""Tela: Ficha de material."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st
from src.services import ficha_material as fm
from src.repositories.pedidos import carregar_pedidos
from src.utils.formatting import formatar_moeda_br

import inspect

def _call_insights_automaticos(historico: pd.DataFrame, material_atual: dict) -> None:
    """Chama fm.criar_insights_automaticos de forma compatível com diferentes assinaturas."""
    fn = getattr(fm, "criar_insights_automaticos", None)
    if fn is None:
        return

    try:
        sig = inspect.signature(fn)
        params = [
            p for p in sig.parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        n = len(params)
    except Exception:
        n = 2

    try:
        if n >= 2:
            fn(historico, material_atual)
        elif n == 1:
            fn(historico)
        else:
            fn()
        return
    except TypeError:
        pass
    except Exception as e:
        st.warning(f"⚠️ Erro ao gerar insights automáticos: {e}")
        return

    for args in ((historico,), (material_atual,), ()):
        try:
            fn(*args)
            return
        except Exception:
            continue

    st.warning("⚠️ Não foi possível gerar insights automáticos (assinatura incompatível).")



@st.cache_data(ttl=300)
def _carregar_pedidos_cache(_supabase, tenant_id: str | None) -> pd.DataFrame:
    """Carrega pedidos do tenant com paginação para evitar retornos parciais.

    Observação: alguns helpers/repositórios aplicam LIMIT (ou filtros de período) por performance.
    Aqui garantimos que a aba "Buscar por Família & Grupo" opere sobre o conjunto completo (até um teto seguro).
    """
    # 0) Resolve tenant_id de forma robusta
    if not tenant_id:
        tenant_id = (
            st.session_state.get("tenant_id")
            or (st.session_state.get("usuario") or {}).get("tenant_id")
            or st.session_state.get("tenant")
            or st.session_state.get("tenant_uuid")
        )

    df_try: pd.DataFrame | None = None

    # 1) Tenta usar o repositório existente (pode ter filtros/limit)
    try:
        df_try = carregar_pedidos(_supabase, tenant_id)
        if isinstance(df_try, pd.DataFrame) and len(df_try) >= 50:
            return df_try
    except Exception:
        df_try = None

    # 2) Paginação direta no Supabase/PostgREST (tenta range; se falhar, tenta offset/limit)
    max_rows = 20000
    page_size = 1000
    rows: list[dict] = []

    def _base_query():
        q = _supabase.table("pedidos").select("*")
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        return q

    # 2a) Tenta com range()
    try:
        qbase = _base_query()
        offset = 0
        while offset < max_rows:
            res = qbase.range(offset, offset + page_size - 1).execute()
            batch = (getattr(res, "data", None) or [])
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
    except Exception:
        # 2b) fallback: offset/limit (compatibilidade com versões diferentes do client)
        try:
            qbase = _base_query()
            offset = 0
            while offset < max_rows:
                res = qbase.limit(page_size).offset(offset).execute()
                batch = (getattr(res, "data", None) or [])
                if not batch:
                    break
                rows.extend(batch)
                if len(batch) < page_size:
                    break
                offset += page_size
        except Exception:
            rows = []

    if rows:
        return pd.DataFrame(rows)

    # 3) Último fallback: devolve o que conseguir do helper (mesmo parcial)
    if isinstance(df_try, pd.DataFrame):
        return df_try
    return pd.DataFrame()
@st.cache_data(ttl=300)
def _carregar_catalogo_materiais_cache(_supabase, tenant_id: str | None) -> pd.DataFrame:
    """Carrega catálogo `materiais` do Supabase (por tenant) para enriquecer a ficha e permitir análise por família/grupo.

    Observação: em alguns bancos a coluna do código pode variar (ex.: codigo_material, cod_material, codigo).
    Aqui carregamos * e normalizamos para 'codigo_material' internamente.
    """
    if not tenant_id:
        tenant_id = (
            st.session_state.get("tenant_id")
            or (st.session_state.get("usuario") or {}).get("tenant_id")
            or st.session_state.get("tenant")
            or st.session_state.get("tenant_uuid")
        )
    try:
        q = _supabase.table("materiais").select("*").limit(20000)
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        res = q.execute()
        df = pd.DataFrame(res.data or [])

        # Normaliza coluna do código (pode variar entre projetos)
        code_col = None
        for c in ("codigo_material", "cod_material", "codigo"):
            if c in df.columns:
                code_col = c
                break
        if code_col and code_col != "codigo_material":
            df = df.rename(columns={code_col: "codigo_material"})

        return df
    except Exception:
        return pd.DataFrame()



def _norm_code(x) -> str:
    """Normaliza código para string numérica para casar pedidos <-> catálogo.

    Regras:
    - Converte numéricos (int/float) de forma segura (857.0 -> "857")
    - Para strings, remove não-dígitos e **remove zeros à esquerda** (000857 -> "857")
    - Evita o bug clássico: "857.0" virar "8570"
    """
    import re

    if x is None:
        return ""

    # Trata numéricos
    try:
        if isinstance(x, int):
            return str(int(x))
        if isinstance(x, float):
            if pd.notna(x) and float(x).is_integer():
                return str(int(x))
    except Exception:
        pass

    s = str(x).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""

    # Strings tipo "857.0" ou "857,0" → "857"
    s2 = s.replace(",", ".")
    if re.fullmatch(r"\d+\.0+", s2):
        s = s2.split(".")[0]

    digits = re.sub(r"\D+", "", s)
    if not digits:
        return ""

    # Remove zeros à esquerda (ex.: "000857" -> "857")
    try:
        return str(int(digits))
    except Exception:
        return digits.lstrip("0") or "0"


def _norm_txt(x) -> str:
    """Normaliza textos (família/grupo) para comparação tolerante.

    - remove acentos
    - troca pontuação por espaço
    - remove NBSP e espaços duplicados
    - UPPER
    """
    import re
    import unicodedata

    if x is None:
        return ""
    s = str(x).replace("\u00a0", " ").strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    # remove acentos
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = s.upper()
    # pontuação para espaço
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _pick_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Retorna a primeira coluna existente no df dentre as candidatas."""
    for c in candidates:
        if c in df.columns:
            return c
    return None



def _get_material_catalog_row(_supabase, tenant_id: str | None, cod_norm: str, df_cat: pd.DataFrame) -> dict | None:
    """Obtém a linha do catálogo (tabela materiais) para o código informado.

    Estratégia (robusta):
    1) tenta via df_cat (cache) comparando _cod_norm
    2) se não achar, tenta query direta no Supabase usando (tenant_id, codigo_material bigint)
    3) fallback: tenta query direta sem tenant_id (para diagnosticar mismatch de tenant)
    """
    if not cod_norm:
        return None

    # 1) cache
    try:
        if df_cat is not None and not df_cat.empty and "_cod_norm" in df_cat.columns:
            hit = df_cat[df_cat["_cod_norm"] == cod_norm]
            if not hit.empty:
                return hit.iloc[0].to_dict()
    except Exception:
        pass

    # 2) query direta por PK (tenant_id, codigo_material)
    try:
        cod_int = int(str(cod_norm).strip())
    except Exception:
        cod_int = None

    if cod_int is not None:
        try:
            q = _supabase.table("materiais").select("*")
            if tenant_id:
                q = q.eq("tenant_id", tenant_id)
            q = q.eq("codigo_material", cod_int).limit(1)
            res = q.execute()
            data = (res.data or [])
            if data:
                return dict(data[0])
        except Exception:
            pass

    # 3) fallback sem tenant (diagnóstico)
    if cod_int is not None:
        try:
            res = _supabase.table("materiais").select("*").eq("codigo_material", cod_int).limit(1).execute()
            data = (res.data or [])
            if data:
                # Retorna mesmo assim (melhor UX), mas sinaliza mismatch em outro ponto
                row = dict(data[0])
                row["_tenant_mismatch"] = True
                return row
        except Exception:
            pass

    return None

def _safe_datetime_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", dayfirst=True)


def exibir_ficha_material(_supabase):
    """Exibe ficha técnica completa e moderna do material"""

    st.title("📋 Ficha Técnica de Material")

    st.markdown(
        """
        <style>
        .fm-card{padding:14px 16px;border-radius:14px;border:1px solid rgba(255,255,255,0.08);background:rgba(255,255,255,0.03);}
        .fm-card.critical{border-left:6px solid #ff4b4b;background:rgba(255,75,75,0.10);}
        .fm-card.warning{border-left:6px solid #ffcc00;background:rgba(255,204,0,0.10);}
        .fm-card.ok{border-left:6px solid #3ddc97;background:rgba(61,220,151,0.08);}
        .fm-title{font-weight:700;font-size:16px;margin:0 0 6px 0;line-height:1.2;}
        .fm-sub{opacity:.9;font-size:12px;margin:0 0 10px 0;}
        .fm-kpis{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;opacity:.95;}
        .fm-kpi{min-width:120px}
        .fm-kpi b{font-size:16px;display:block;margin-top:2px}
        .fm-chipwrap{margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;}
        .fm-chip{font-size:11px;padding:3px 8px;border-radius:999px;background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.10);}
        </style>
        """,
        unsafe_allow_html=True,
    )

    modo_ficha = bool(st.session_state.get("modo_ficha_material", False))


    df_pedidos = _carregar_pedidos_cache(_supabase, st.session_state.get('tenant_id'))

    # Catálogo (dimensão) para enriquecer a ficha e permitir análises por Família/Grupo
    tenant_id = st.session_state.get("tenant_id")
    df_cat = _carregar_catalogo_materiais_cache(_supabase, tenant_id)
    if not df_cat.empty and "codigo_material" in df_cat.columns:
        df_cat = df_cat.copy()
        df_cat["_cod_norm"] = df_cat["codigo_material"].apply(_norm_code)
    else:
        df_cat = pd.DataFrame()


    if df_pedidos.empty:
        st.info("📭 Nenhum pedido cadastrado ainda")
        return

    # Normalizações leves (evitam bugs em filtros e cálculos)
    if "cod_material" in df_pedidos.columns:
        df_pedidos["cod_material"] = df_pedidos["cod_material"].astype(str).str.strip()

    df_pedidos["_cod_norm"] = df_pedidos["cod_material"].apply(_norm_code)

    if "descricao" in df_pedidos.columns:
        df_pedidos["descricao"] = df_pedidos["descricao"].astype(str).str.strip()

    # Colunas prováveis (para evitar quebrar se o schema variar)
    col_unit = _pick_col(df_pedidos, ["valor_unitario", "preco_unitario", "vl_unitario", "unitario"])
    col_fornecedor = _pick_col(df_pedidos, ["fornecedor", "nome_fornecedor", "razao_social", "fornec"])
    col_data = _pick_col(df_pedidos, ["data_oc", "data", "data_pedido", "dt_oc"])
    col_qtd = _pick_col(df_pedidos, ["qtde_solicitada", "quantidade", "qtd", "qtde"])
    col_total = _pick_col(df_pedidos, ["valor_total", "total", "vl_total"])
    col_status = _pick_col(df_pedidos, ["status"])
    col_entregue = _pick_col(df_pedidos, ["entregue", "entrega", "is_entregue"])
    col_equip = _pick_col(df_pedidos, ["cod_equipamento", "equipamento"])
    col_dep = _pick_col(df_pedidos, ["departamento", "setor"])

    col_prev = _pick_col(df_pedidos, ["previsao_entrega", "previsao", "dt_previsao"])  # data prevista
    col_prazo = _pick_col(df_pedidos, ["prazo_entrega", "prazo"])  # prazo informado
    col_entrega_real = _pick_col(df_pedidos, ["data_entrega_real", "dt_entrega_real", "entrega_real"])  # data real
    col_qtd_pend = _pick_col(df_pedidos, ["qtde_pendente", "qtd_pendente", "pendente"])  # quantidade pendente
    col_oc = _pick_col(df_pedidos, ["nr_oc", "oc", "numero_oc"])  # ordem de compra
    col_solic = _pick_col(df_pedidos, ["nr_solicitacao", "solicitacao", "nr_req"])  # solicitação
    if not modo_ficha:

        # ============================================================
        # SISTEMA DE ABAS PARA BUSCA
        # ============================================================
        tab1, tab2, tab3, tab4 = st.tabs(
            ["🔍 Buscar Material", "🔧 Buscar por Equipamento", "🏢 Buscar por Departamento", "🧩 Buscar por Família & Grupo"]
        )

        # Estado/Contexto (não deixar variável "sumir" fora das tabs)
        material_key = st.session_state.get("material_fixo", {"cod": None, "desc": None})
        material_selecionado_cod = material_key.get("cod")
        material_selecionado_desc = material_key.get("desc")
        tipo_busca = st.session_state.get("tipo_busca_ficha", None)
        equipamento_ctx = st.session_state.get("equipamento_ctx", "")
        departamento_ctx = st.session_state.get("departamento_ctx", "")

        historico_material = pd.DataFrame()

        # ============================================================
        # TAB 1: BUSCA POR MATERIAL (COM BARRA DE PESQUISA)
        # ============================================================
        with tab1:
            st.markdown("### 🔎 Buscar Material Específico")

            # Agrupar materiais (preferir por código + descrição)
            if "cod_material" in df_pedidos.columns:
                materiais_unicos = (
                    df_pedidos.groupby(["cod_material"], dropna=True)
                    .agg(
                        descricao=("descricao", "first"),
                        compras=("id", "count") if "id" in df_pedidos.columns else ("descricao", "count"),
                    )
                    .reset_index()
                )
                materiais_unicos = materiais_unicos.sort_values("compras", ascending=False)
            else:
                materiais_unicos = (
                    df_pedidos.groupby(["descricao"], dropna=True)
                    .agg(
                        compras=("id", "count") if "id" in df_pedidos.columns else ("descricao", "count"),
                    )
                    .reset_index()
                    .rename(columns={"descricao": "descricao"})
                    .sort_values("compras", ascending=False)
                )
                materiais_unicos["cod_material"] = None

            col1, col2 = st.columns([4, 1])

            with col1:
                busca_texto = st.text_input(
                    "Digite o código do material:",
                    placeholder="Ex: MAT001, 12345, FILT-200...",
                    help="Digite o código completo ou parcial do material para buscar",
                    key="busca_material",
                )

            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🔄 Limpar", key="limpar_material"):
                    st.session_state.pop("material_fixo", None)
                    st.session_state.pop("tipo_busca_ficha", None)
                    st.session_state.pop("equipamento_ctx", None)
                    st.session_state.pop("departamento_ctx", None)
                    st.rerun()

            if busca_texto:
                if "cod_material" in materiais_unicos.columns:
                    materiais_filtrados = materiais_unicos[
                        materiais_unicos["cod_material"]
                        .astype(str)
                        .str.contains(str(busca_texto).upper(), case=False, na=False)
                    ]
                else:
                    materiais_filtrados = materiais_unicos[
                        materiais_unicos["descricao"]
                        .astype(str)
                        .str.contains(str(busca_texto).upper(), case=False, na=False)
                    ]

                if materiais_filtrados.empty:
                    st.warning(f"⚠️ Nenhum material encontrado com código '{busca_texto}'")
                    st.info("💡 Tente códigos mais genéricos ou verifique se o código está correto")
                else:
                    st.success(f"✅ {len(materiais_filtrados)} material(is) encontrado(s)")
                    st.markdown("#### Selecione um material:")

                    for idx, row in materiais_filtrados.head(10).iterrows():
                        c1, c2, c3 = st.columns([3, 1, 1])

                        with c1:
                            cod = row.get("cod_material")
                            desc = row.get("descricao", "")
                            st.markdown(f"**Código:** {cod if pd.notna(cod) and str(cod).strip() else 'N/A'}")
                            if pd.notna(desc) and str(desc).strip():
                                st.caption(str(desc))

                        with c2:
                            st.metric("Compras", int(row.get("compras", 0)))

                        with c3:
                            if st.button("Ver Ficha", key=f"ver_{idx}"):
                                st.session_state["material_fixo"] = {
                                    "cod": row.get("cod_material"),
                                    "desc": row.get("descricao"),
                                }
                                st.session_state["tipo_busca_ficha"] = "material"
                                st.session_state["equipamento_ctx"] = ""
                                st.session_state["departamento_ctx"] = ""
                                st.session_state["modo_ficha_material"] = True
                                st.rerun()

                        st.markdown("---")

                    if len(materiais_filtrados) > 10:
                        st.info(
                            f"ℹ️ Mostrando 10 de {len(materiais_filtrados)} resultados. Refine sua busca para ver mais."
                        )
            else:
                st.info("💡 Digite o código do material no campo acima para começar a busca")

                st.markdown("#### 📊 Top 10 Materiais Mais Comprados")
                for idx, row in materiais_unicos.head(10).iterrows():
                    c1, c2, c3 = st.columns([3, 1, 1])

                    with c1:
                        desc = row.get("descricao", "")
                        cod = row.get("cod_material")
                        st.markdown(f"**{desc if pd.notna(desc) else 'Material'}**")
                        if pd.notna(cod) and str(cod).strip():
                            st.caption(f"Código: {cod}")

                    with c2:
                        st.metric("Compras", int(row.get("compras", 0)))

                    with c3:
                        if st.button("Ver Ficha", key=f"top_{idx}"):
                            st.session_state["material_fixo"] = {
                                "cod": row.get("cod_material"),
                                "desc": row.get("descricao"),
                            }
                            st.session_state["tipo_busca_ficha"] = "material"
                            st.session_state["equipamento_ctx"] = ""
                            st.session_state["departamento_ctx"] = ""
                            st.session_state["modo_ficha_material"] = True
                            st.rerun()

                    st.markdown("---")

        # ============================================================
        # TAB 2: BUSCA POR EQUIPAMENTO (BOXES + FOLLOW-UP)
        # ============================================================
        with tab2:
            st.markdown("### 🔧 Materiais por Equipamento")

            if not col_equip or col_equip not in df_pedidos.columns:
                st.warning("⚠️ Coluna de equipamento não encontrada nos pedidos")
            else:
                equipamentos_todos = df_pedidos[col_equip].dropna().astype(str).str.strip().unique().tolist()
                equipamentos_todos = sorted([eq for eq in equipamentos_todos if eq])

                if not equipamentos_todos:
                    st.warning("⚠️ Nenhum equipamento cadastrado nos pedidos")
                else:
                    # Busca rápida de equipamento
                    st.markdown("#### 🔍 Buscar Equipamento")
                    c1, c2 = st.columns([4, 1])

                    with c1:
                        busca_equipamento = st.text_input(
                            "Digite o código ou nome do equipamento:",
                            placeholder="Ex: TR-001, TRATOR, ESCAVADEIRA...",
                            help="Busca por código ou descrição do equipamento",
                            key="busca_equipamento",
                        )

                    with c2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("🔄 Limpar", key="limpar_busca_equipamento"):
                            st.session_state.pop("material_fixo", None)
                            st.session_state.pop("tipo_busca_ficha", None)
                            st.session_state.pop("equipamento_ctx", None)
                            st.session_state.pop("departamento_ctx", None)
                            st.session_state.pop("modo_ficha_material", None)
                            st.rerun()

                    if busca_equipamento:
                        equipamentos_filtrados = [eq for eq in equipamentos_todos if busca_equipamento.upper() in eq.upper()]
                        if not equipamentos_filtrados:
                            st.warning(f"⚠️ Nenhum equipamento encontrado com '{busca_equipamento}'")
                            equipamentos_filtrados = []
                        else:
                            st.success(f"✅ {len(equipamentos_filtrados)} equipamento(s) encontrado(s)")
                    else:
                        equipamentos_filtrados = equipamentos_todos

                    equipamento_selecionado = ""
                    if equipamentos_filtrados:
                        equipamento_selecionado = st.selectbox(
                            "Selecione o Equipamento:",
                            options=[""] + equipamentos_filtrados,
                            format_func=lambda x: "Selecione..." if x == "" else x,
                            key="select_equipamento",
                        )

                    if equipamento_selecionado:
                        df_equipamento = df_pedidos[df_pedidos[col_equip] == equipamento_selecionado].copy()
                        st.markdown("---")

                        # ------------------------------
                        # Filtros (mantendo o visual de boxes)
                        # ------------------------------
                        st.markdown("#### 🎛️ Filtros Avançados")
                        f1, f2, f3, f4 = st.columns([1.4, 1.1, 1.1, 1.4])

                        with f1:
                            status_options = df_equipamento[col_status].dropna().unique().tolist() if col_status and col_status in df_equipamento.columns else []
                            status_filtro_eq = st.multiselect(
                                "📊 Status",
                                options=status_options,
                                default=status_options,
                                key="status_eq",
                            )

                        with f2:
                            periodo_eq = st.selectbox(
                                "📅 Período",
                                ["Todos", "Último mês", "Últimos 3 meses", "Últimos 6 meses", "Último ano"],
                                key="periodo_eq",
                            )

                        with f3:
                            filtro_entrega_eq = st.selectbox(
                                "🚚 Entrega",
                                ["Todos", "Apenas Entregues", "Apenas Pendentes"],
                                key="entrega_eq",
                            )

                        with f4:
                            only_pend = st.toggle("Somente com pendência", value=False, help="Mostra apenas itens com pendência (follow-up).", key="only_pend_eq")

                        df_eq_filtrado = df_equipamento.copy()

                        # Status
                        if status_filtro_eq and col_status:
                            df_eq_filtrado = df_eq_filtrado[df_eq_filtrado[col_status].isin(status_filtro_eq)]

                        # Período
                        if periodo_eq != "Todos" and col_data and col_data in df_eq_filtrado.columns:
                            hoje_dt = datetime.now()
                            if periodo_eq == "Último mês":
                                data_limite = hoje_dt - pd.DateOffset(months=1)
                            elif periodo_eq == "Últimos 3 meses":
                                data_limite = hoje_dt - pd.DateOffset(months=3)
                            elif periodo_eq == "Últimos 6 meses":
                                data_limite = hoje_dt - pd.DateOffset(months=6)
                            else:
                                data_limite = hoje_dt - pd.DateOffset(years=1)

                            dt = _safe_datetime_series(df_eq_filtrado[col_data])
                            df_eq_filtrado = df_eq_filtrado[dt >= data_limite]

                        # Entrega
                        if col_entregue and col_entregue in df_eq_filtrado.columns:
                            if filtro_entrega_eq == "Apenas Entregues":
                                df_eq_filtrado = df_eq_filtrado[df_eq_filtrado[col_entregue] == True]
                            elif filtro_entrega_eq == "Apenas Pendentes":
                                df_eq_filtrado = df_eq_filtrado[df_eq_filtrado[col_entregue] == False]

                        # ------------------------------
                        # Follow-up: pendência, vencimento, atraso
                        # ------------------------------
                        hoje = pd.Timestamp.now().normalize()

                        # Data OC
                        if col_data and col_data in df_eq_filtrado.columns:
                            df_eq_filtrado["_data_oc"] = _safe_datetime_series(df_eq_filtrado[col_data])
                        else:
                            df_eq_filtrado["_data_oc"] = pd.NaT

                        # Due: previsão > prazo > data_oc + 30d
                        df_eq_filtrado["_prev"] = _safe_datetime_series(df_eq_filtrado[col_prev]) if col_prev and col_prev in df_eq_filtrado.columns else pd.NaT
                        df_eq_filtrado["_prazo"] = _safe_datetime_series(df_eq_filtrado[col_prazo]) if col_prazo and col_prazo in df_eq_filtrado.columns else pd.NaT
                        df_eq_filtrado["_due"] = df_eq_filtrado["_prev"]
                        df_eq_filtrado.loc[df_eq_filtrado["_due"].isna(), "_due"] = df_eq_filtrado.loc[df_eq_filtrado["_due"].isna(), "_prazo"]
                        df_eq_filtrado.loc[df_eq_filtrado["_due"].isna(), "_due"] = df_eq_filtrado.loc[df_eq_filtrado["_due"].isna(), "_data_oc"] + pd.Timedelta(days=30)

                        # Pendente: entregue False OU qtde_pendente > 0
                        pendente_flag = pd.Series([True] * len(df_eq_filtrado), index=df_eq_filtrado.index)
                        if col_entregue and col_entregue in df_eq_filtrado.columns:
                            pendente_flag = df_eq_filtrado[col_entregue] != True
                        if col_qtd_pend and col_qtd_pend in df_eq_filtrado.columns:
                            qtd_pend = pd.to_numeric(df_eq_filtrado[col_qtd_pend], errors="coerce").fillna(0)
                            pendente_flag = pendente_flag | (qtd_pend > 0)

                        df_eq_filtrado["_pendente"] = pendente_flag
                        df_eq_filtrado["_atrasado"] = df_eq_filtrado["_pendente"] & df_eq_filtrado["_due"].notna() & (df_eq_filtrado["_due"] < hoje)

                        # Valor total numérico (corrige "R$ 0,00" quando vem como texto)
                        if col_total and col_total in df_eq_filtrado.columns:
                            df_eq_filtrado["_valor_total"] = pd.to_numeric(df_eq_filtrado[col_total], errors="coerce").fillna(0.0)
                        else:
                            df_eq_filtrado["_valor_total"] = 0.0

                        # Se o usuário quiser ver só pendências
                        if only_pend:
                            df_eq_filtrado = df_eq_filtrado[df_eq_filtrado["_pendente"]]

                        st.markdown("---")

                        # ------------------------------
                        # KPIs (boxes)
                        # ------------------------------
                        k1, k2, k3, k4, k5 = st.columns(5)

                        k1.metric("📦 Total de Pedidos", int(len(df_eq_filtrado)))
                        k2.metric("🔧 Materiais Diferentes", int(df_eq_filtrado["descricao"].nunique()) if "descricao" in df_eq_filtrado.columns else 0)

                        valor_total_eq = float(df_eq_filtrado["_valor_total"].sum())
                        k3.metric("💰 Valor Total", formatar_moeda_br(valor_total_eq))

                        pendentes_eq = int(df_eq_filtrado["_pendente"].sum()) if "_pendente" in df_eq_filtrado.columns else 0
                        atrasados_eq = int(df_eq_filtrado["_atrasado"].sum()) if "_atrasado" in df_eq_filtrado.columns else 0
                        k4.metric("⏳ Pendentes", pendentes_eq)
                        k5.metric("🔴 Atrasados", atrasados_eq)

                        st.markdown("---")

                        # ------------------------------
                        # Lista em boxes (como você gosta)
                        # ------------------------------
                        if df_eq_filtrado.empty:
                            st.warning("⚠️ Nenhum material encontrado com os filtros aplicados")
                        else:
                            st.markdown(f"#### 📋 Materiais do Equipamento **{equipamento_selecionado}**")

                            # Campo para filtrar materiais dentro do equipamento
                            filtro_material_txt = st.text_input(
                                "Filtrar material dentro do equipamento (código ou descrição):",
                                placeholder="Digite para filtrar…",
                                key="filtro_material_eq",
                            ).strip()

                            group_cols = ["descricao"]
                            if "cod_material" in df_eq_filtrado.columns:
                                group_cols = ["cod_material", "descricao"]

                            materiais = (
                                df_eq_filtrado
                                .groupby(group_cols, dropna=False)
                                .agg(
                                    Pedidos=("id", "count") if "id" in df_eq_filtrado.columns else ("descricao", "size"),
                                    Valor=("_valor_total", "sum"),
                                    QtdSolic=(col_qtd, "sum") if (col_qtd and col_qtd in df_eq_filtrado.columns) else ("descricao", "size"),
                                    QtdPend=(col_qtd_pend, "sum") if (col_qtd_pend and col_qtd_pend in df_eq_filtrado.columns) else ("descricao", "size"),
                                    Pendentes=("_pendente", "sum"),
                                    Atrasados=("_atrasado", "sum"),
                                    Entregues=(col_entregue, lambda x: int((x == True).sum())) if (col_entregue and col_entregue in df_eq_filtrado.columns) else ("descricao", "size"),
                                )
                                .reset_index()
                            )

                            # Normalizar números
                            materiais["Valor"] = pd.to_numeric(materiais["Valor"], errors="coerce").fillna(0.0)
                            if "QtdPend" in materiais.columns:
                                materiais["QtdPend"] = pd.to_numeric(materiais["QtdPend"], errors="coerce").fillna(0.0)

                            # Filtro textual interno
                            if filtro_material_txt:
                                mask = materiais["descricao"].astype(str).str.contains(filtro_material_txt, case=False, na=False)
                                if "cod_material" in materiais.columns:
                                    mask = mask | materiais["cod_material"].astype(str).str.contains(filtro_material_txt, case=False, na=False)
                                materiais = materiais[mask]

                            materiais = materiais.sort_values(["Atrasados", "Pendentes", "Valor", "Pedidos"], ascending=[False, False, False, False])

                            st.caption(f"Mostrando {len(materiais)} material(is) • {len(df_eq_filtrado)} pedido(s) • Critério: atrasados → pendentes → valor")
                            max_rows = st.selectbox("Mostrar", [10, 20, 50, 100], index=1, key="limite_eq_boxes")
                            for idx, row in materiais.head(int(max_rows)).iterrows():
                                atras = int(row.get("Atrasados", 0))
                                pend = int(row.get("Pendentes", 0))
                                severity = "critical" if atras > 0 else ("warning" if pend > 0 else "ok")
                                
                                cod = row.get("cod_material") if "cod_material" in materiais.columns else None
                                desc = row.get("descricao", "")
                                
                                titulo = f"{desc}"
                                if pd.notna(cod) and str(cod).strip():
                                    titulo = f"{desc}  ·  ({cod})"
                                
                                chips = []
                                if atras > 0:
                                    chips.append("🔴 Atrasado")
                                if pend > 0:
                                    chips.append("⏳ Pendente")
                                
                                card_html = f"""
                                <div class="fm-card {severity}">
                                  <div class="fm-title">{titulo}</div>
                                  <div class="fm-sub">{(" • ".join(chips)) if chips else "🟢 Dentro do prazo"}</div>
                                  <div class="fm-kpis">
                                    <div class="fm-kpi">Pedidos<b>{int(row.get("Pedidos", 0))}</b></div>
                                    <div class="fm-kpi">Pendências<b>{pend}</b></div>
                                    <div class="fm-kpi">Valor<b>{formatar_moeda_br(float(row.get("Valor", 0.0)))}</b></div>
                                  </div>
                                </div>
                                """
                                
                                c_left, c_btn = st.columns([6, 1])
                                with c_left:
                                    st.markdown(card_html, unsafe_allow_html=True)
                                with c_btn:
                                    st.markdown("<br>", unsafe_allow_html=True)
                                    if st.button("Ver Ficha", key=f"eq_{idx}"):
                                        st.session_state["material_fixo"] = {"cod": cod, "desc": desc}
                                        st.session_state["tipo_busca_ficha"] = "equipamento"
                                        st.session_state["equipamento_ctx"] = equipamento_selecionado
                                        st.session_state["departamento_ctx"] = ""
                                        st.session_state["modo_ficha_material"] = True
                                        st.rerun()
                                
                                st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        # ============================================================
        # TAB 3: BUSCA POR DEPARTAMENTO (BOXES + FOLLOW-UP)
        # ============================================================
        with tab3:
            st.markdown("### 🏢 Materiais por Departamento")

            if not col_dep or col_dep not in df_pedidos.columns:
                st.warning("⚠️ Coluna de departamento não encontrada nos pedidos")
            else:
                departamentos = df_pedidos[col_dep].dropna().astype(str).str.strip().unique().tolist()
                departamentos = sorted([d for d in departamentos if d])

                if not departamentos:
                    st.warning("⚠️ Nenhum departamento cadastrado nos pedidos")
                else:
                    c1, c2 = st.columns([4, 1])

                    with c1:
                        departamento_selecionado = st.selectbox(
                            "Selecione o Departamento:",
                            options=[""] + departamentos,
                            format_func=lambda x: "Selecione..." if x == "" else x,
                            key="select_departamento",
                        )

                    with c2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("🔄 Limpar", key="limpar_departamento"):
                            st.session_state.pop("material_fixo", None)
                            st.session_state.pop("tipo_busca_ficha", None)
                            st.session_state.pop("equipamento_ctx", None)
                            st.session_state.pop("departamento_ctx", None)
                            st.session_state.pop("modo_ficha_material", None)
                            st.rerun()

                    if departamento_selecionado:
                        df_departamento = df_pedidos[df_pedidos[col_dep] == departamento_selecionado].copy()
                        st.markdown("---")

                        st.markdown("#### 🎛️ Filtros Avançados")
                        f1, f2, f3, f4, f5 = st.columns([1.4, 1.1, 1.1, 1.2, 1.4])

                        with f1:
                            status_options_dep = df_departamento[col_status].dropna().unique().tolist() if col_status and col_status in df_departamento.columns else []
                            status_filtro_dep = st.multiselect(
                                "📊 Status",
                                options=status_options_dep,
                                default=status_options_dep,
                                key="status_dep",
                            )

                        with f2:
                            periodo_dep = st.selectbox(
                                "📅 Período",
                                ["Todos", "Último mês", "Últimos 3 meses", "Últimos 6 meses", "Último ano"],
                                key="periodo_dep",
                            )

                        with f3:
                            filtro_entrega_dep = st.selectbox(
                                "🚚 Entrega",
                                ["Todos", "Apenas Entregues", "Apenas Pendentes"],
                                key="entrega_dep",
                            )

                        with f4:
                            # Filtro de equipamento dentro do depto (se existir)
                            if col_equip and col_equip in df_departamento.columns:
                                equipamentos_dep = ["Todos"] + sorted(df_departamento[col_equip].dropna().astype(str).unique().tolist())
                            else:
                                equipamentos_dep = ["Todos"]
                            filtro_equipamento_dep = st.selectbox("🔧 Equipamento", options=equipamentos_dep, key="equipamento_dep")

                        with f5:
                            only_pend_dep = st.toggle("Somente com pendência", value=False, help="Mostra apenas itens com pendência (follow-up).", key="only_pend_dep")

                        df_dep_filtrado = df_departamento.copy()

                        if status_filtro_dep and col_status:
                            df_dep_filtrado = df_dep_filtrado[df_dep_filtrado[col_status].isin(status_filtro_dep)]

                        if periodo_dep != "Todos" and col_data and col_data in df_dep_filtrado.columns:
                            hoje_dt = datetime.now()
                            if periodo_dep == "Último mês":
                                data_limite = hoje_dt - pd.DateOffset(months=1)
                            elif periodo_dep == "Últimos 3 meses":
                                data_limite = hoje_dt - pd.DateOffset(months=3)
                            elif periodo_dep == "Últimos 6 meses":
                                data_limite = hoje_dt - pd.DateOffset(months=6)
                            else:
                                data_limite = hoje_dt - pd.DateOffset(years=1)

                            dt = _safe_datetime_series(df_dep_filtrado[col_data])
                            df_dep_filtrado = df_dep_filtrado[dt >= data_limite]

                        if col_entregue and col_entregue in df_dep_filtrado.columns:
                            if filtro_entrega_dep == "Apenas Entregues":
                                df_dep_filtrado = df_dep_filtrado[df_dep_filtrado[col_entregue] == True]
                            elif filtro_entrega_dep == "Apenas Pendentes":
                                df_dep_filtrado = df_dep_filtrado[df_dep_filtrado[col_entregue] == False]

                        if filtro_equipamento_dep != "Todos" and col_equip and col_equip in df_dep_filtrado.columns:
                            df_dep_filtrado = df_dep_filtrado[df_dep_filtrado[col_equip].astype(str) == str(filtro_equipamento_dep)]

                        # ------------------------------
                        # Follow-up: pendência, vencimento, atraso
                        # ------------------------------
                        hoje = pd.Timestamp.now().normalize()

                        if col_data and col_data in df_dep_filtrado.columns:
                            df_dep_filtrado["_data_oc"] = _safe_datetime_series(df_dep_filtrado[col_data])
                        else:
                            df_dep_filtrado["_data_oc"] = pd.NaT

                        df_dep_filtrado["_prev"] = _safe_datetime_series(df_dep_filtrado[col_prev]) if col_prev and col_prev in df_dep_filtrado.columns else pd.NaT
                        df_dep_filtrado["_prazo"] = _safe_datetime_series(df_dep_filtrado[col_prazo]) if col_prazo and col_prazo in df_dep_filtrado.columns else pd.NaT
                        df_dep_filtrado["_due"] = df_dep_filtrado["_prev"]
                        df_dep_filtrado.loc[df_dep_filtrado["_due"].isna(), "_due"] = df_dep_filtrado.loc[df_dep_filtrado["_due"].isna(), "_prazo"]
                        df_dep_filtrado.loc[df_dep_filtrado["_due"].isna(), "_due"] = df_dep_filtrado.loc[df_dep_filtrado["_due"].isna(), "_data_oc"] + pd.Timedelta(days=30)

                        pendente_flag = pd.Series([True] * len(df_dep_filtrado), index=df_dep_filtrado.index)
                        if col_entregue and col_entregue in df_dep_filtrado.columns:
                            pendente_flag = df_dep_filtrado[col_entregue] != True
                        if col_qtd_pend and col_qtd_pend in df_dep_filtrado.columns:
                            qtd_pend = pd.to_numeric(df_dep_filtrado[col_qtd_pend], errors="coerce").fillna(0)
                            pendente_flag = pendente_flag | (qtd_pend > 0)

                        df_dep_filtrado["_pendente"] = pendente_flag
                        df_dep_filtrado["_atrasado"] = df_dep_filtrado["_pendente"] & df_dep_filtrado["_due"].notna() & (df_dep_filtrado["_due"] < hoje)

                        if col_total and col_total in df_dep_filtrado.columns:
                            df_dep_filtrado["_valor_total"] = pd.to_numeric(df_dep_filtrado[col_total], errors="coerce").fillna(0.0)
                        else:
                            df_dep_filtrado["_valor_total"] = 0.0

                        if only_pend_dep:
                            df_dep_filtrado = df_dep_filtrado[df_dep_filtrado["_pendente"]]

                        st.markdown("---")

                        # KPIs (boxes)
                        k1, k2, k3, k4, k5 = st.columns(5)
                        k1.metric("📦 Pedidos", int(len(df_dep_filtrado)))
                        k2.metric("🔧 Materiais", int(df_dep_filtrado["descricao"].nunique()) if "descricao" in df_dep_filtrado.columns else 0)

                        valor_total_dep = float(df_dep_filtrado["_valor_total"].sum())
                        k3.metric("💰 Valor Total", formatar_moeda_br(valor_total_dep))

                        pendentes_dep = int(df_dep_filtrado["_pendente"].sum()) if "_pendente" in df_dep_filtrado.columns else 0
                        atrasados_dep = int(df_dep_filtrado["_atrasado"].sum()) if "_atrasado" in df_dep_filtrado.columns else 0
                        k4.metric("⏳ Pendentes", pendentes_dep)
                        k5.metric("🔴 Atrasados", atrasados_dep)

                        st.markdown("---")

                        if df_dep_filtrado.empty:
                            st.warning("⚠️ Nenhum material encontrado com os filtros aplicados")
                        else:
                            st.markdown(f"#### 📋 Materiais do Departamento **{departamento_selecionado}**")

                            filtro_material_txt = st.text_input(
                                "Filtrar material dentro do departamento (código ou descrição):",
                                placeholder="Digite para filtrar…",
                                key="filtro_material_dep",
                            ).strip()

                            group_cols = ["descricao"]
                            if "cod_material" in df_dep_filtrado.columns:
                                group_cols = ["cod_material", "descricao"]

                            materiais = (
                                df_dep_filtrado
                                .groupby(group_cols, dropna=False)
                                .agg(
                                    Pedidos=("id", "count") if "id" in df_dep_filtrado.columns else ("descricao", "size"),
                                    Valor=("_valor_total", "sum"),
                                    Equipamentos=(col_equip, lambda x: sorted(set(x.dropna().astype(str).str.strip()))) if (col_equip and col_equip in df_dep_filtrado.columns) else ("descricao", "size"),
                                    Pendentes=("_pendente", "sum"),
                                    Atrasados=("_atrasado", "sum"),
                                )
                                .reset_index()
                            )

                            materiais["Valor"] = pd.to_numeric(materiais["Valor"], errors="coerce").fillna(0.0)

                            if filtro_material_txt:
                                mask = materiais["descricao"].astype(str).str.contains(filtro_material_txt, case=False, na=False)
                                if "cod_material" in materiais.columns:
                                    mask = mask | materiais["cod_material"].astype(str).str.contains(filtro_material_txt, case=False, na=False)
                                materiais = materiais[mask]

                            materiais = materiais.sort_values(["Atrasados", "Pendentes", "Valor", "Pedidos"], ascending=[False, False, False, False])

                            st.caption(f"Mostrando {len(materiais)} material(is) • {len(df_dep_filtrado)} pedido(s) • Critério: atrasados → pendentes → valor")
                            max_rows = st.selectbox("Mostrar", [10, 20, 50, 100], index=1, key="limite_dep_boxes")
                            for idx, row in materiais.head(int(max_rows)).iterrows():
                                atras = int(row.get("Atrasados", 0))
                                pend = int(row.get("Pendentes", 0))
                                severity = "critical" if atras > 0 else ("warning" if pend > 0 else "ok")

                                cod = row.get("cod_material") if "cod_material" in materiais.columns else None
                                desc = row.get("descricao", "")

                                titulo = f"{desc}"
                                if pd.notna(cod) and str(cod).strip():
                                    titulo = f"{desc}  ·  ({cod})"

                                chips = []
                                if atras > 0:
                                    chips.append("🔴 Atrasado")
                                if pend > 0:
                                    chips.append("⏳ Pendente")

                                equip_list = row.get("Equipamentos", []) if "Equipamentos" in row else []
                                if isinstance(equip_list, str):
                                    equip_list = [e.strip() for e in equip_list.split(",") if e.strip()]
                                elif not isinstance(equip_list, (list, tuple, set)):
                                    equip_list = [str(equip_list).strip()] if str(equip_list).strip() else []
                                equip_list = [str(e).strip() for e in equip_list if str(e).strip()]

                                show_max = 4
                                show = equip_list[:show_max]
                                rest = max(0, len(equip_list) - len(show))

                                equip_summary = "—"
                                if show:
                                    equip_summary = show[0] + (f" +{len(equip_list)-1}" if len(equip_list) > 1 else "")

                                equip_chips_html = ""
                                if show:
                                    equip_chips_html = "".join([f"<span class='fm-chip'>{e}</span>" for e in show])
                                    if rest > 0:
                                        equip_chips_html += f"<span class='fm-chip'>+{rest}</span>"

                                card_html = f"""
                                <div class="fm-card {severity}">
                                  <div class="fm-title">{titulo}</div>
                                  <div class="fm-sub">{(" • ".join(chips)) if chips else "🟢 Dentro do prazo"}</div>
                                  <div class="fm-kpis">
                                    <div class="fm-kpi">Pedidos<b>{int(row.get("Pedidos", 0))}</b></div>
                                    <div class="fm-kpi">Equip.<b>{equip_summary}</b></div>
                                    <div class="fm-kpi">Pendências<b>{pend}</b></div>
                                    <div class="fm-kpi">Valor<b>{formatar_moeda_br(float(row.get("Valor", 0.0)))}</b></div>
                                  </div>
                                  {f"<div class='fm-chipwrap'>{equip_chips_html}</div>" if equip_chips_html else ""}
                                </div>
                                """

                                c_left, c_btn = st.columns([6, 1])
                                with c_left:
                                    st.markdown(card_html, unsafe_allow_html=True)
                                with c_btn:
                                    st.markdown("<br>", unsafe_allow_html=True)
                                    if st.button("Ver Ficha", key=f"dep_{idx}"):
                                        st.session_state["material_fixo"] = {"cod": cod, "desc": desc}
                                        st.session_state["tipo_busca_ficha"] = "departamento"
                                        st.session_state["equipamento_ctx"] = (
                                            filtro_equipamento_dep if filtro_equipamento_dep != "Todos" else ""
                                        )
                                        st.session_state["departamento_ctx"] = departamento_selecionado
                                        st.session_state["modo_ficha_material"] = True
                                        st.rerun()

                                st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)



    
        # ============================================================
        # TAB 4: BUSCA POR FAMÍLIA & GRUPO (CLUSTER)
        # ============================================================
        with tab4:
            st.markdown("### 🧩 Buscar por Família & Grupo")
            st.caption("Selecione uma família e/ou grupo do **Catálogo** para ver todos os pedidos relacionados (cluster).")

            if df_cat.empty or ("familia_descricao" not in df_cat.columns and "grupo_descricao" not in df_cat.columns):
                st.info("Importe o **Catálogo de Materiais** (tabela `materiais`) com `familia_descricao` e `grupo_descricao` para habilitar esta busca.")
            else:
                dcat = df_cat.copy()
                if "_cod_norm" not in dcat.columns and "codigo_material" in dcat.columns:
                    dcat["_cod_norm"] = dcat["codigo_material"].apply(_norm_code)

                dcat["familia_descricao"] = dcat.get("familia_descricao", pd.Series([], dtype="object")).fillna("").astype(str)
                dcat["grupo_descricao"] = dcat.get("grupo_descricao", pd.Series([], dtype="object")).fillna("").astype(str)
                dcat["_fam_norm"] = dcat["familia_descricao"].apply(_norm_txt)
                dcat["_grp_norm"] = dcat["grupo_descricao"].apply(_norm_txt)

                fam_opts = sorted([f for f in dcat["familia_descricao"].dropna().astype(str).unique().tolist() if str(f).strip()])
                grp_all = sorted([g for g in dcat["grupo_descricao"].dropna().astype(str).unique().tolist() if str(g).strip()])

                csel1, csel2, csel3 = st.columns([2.2, 2.2, 1.2])
                with csel1:
                    fam_sel = st.selectbox("Família", options=["(Todas)"] + fam_opts, index=0, key="fm_busca_fam")
                with csel2:
                    if fam_sel != "(Todas)":
                        fam_n = _norm_txt(fam_sel)
                        grp_opts = sorted([
                            g for g in dcat.loc[dcat["_fam_norm"] == fam_n, "grupo_descricao"].dropna().astype(str).unique().tolist()
                            if str(g).strip()
                        ])
                    else:
                        grp_opts = grp_all
                    grp_sel = st.selectbox("Grupo", options=["(Todos)"] + grp_opts, index=0, key="fm_busca_grp")
                with csel3:
                    only_pend = st.toggle("Só pendentes", value=False, key="fm_busca_only_pend")

                scope = dcat
                if fam_sel != "(Todas)":
                    scope = scope[scope["_fam_norm"] == _norm_txt(fam_sel)]
                if grp_sel != "(Todos)":
                    scope = scope[scope["_grp_norm"] == _norm_txt(grp_sel)]

                codes = [c for c in scope.get("_cod_norm", pd.Series([], dtype=str)).astype(str).tolist() if c]
                codes = sorted(set(codes))
                if not codes:
                    st.warning("Nenhum material encontrado no catálogo para os filtros selecionados.")
                else:
                    df_scope = df_pedidos[df_pedidos.get("_cod_norm", pd.Series([], dtype=str)).isin(codes)].copy()

                    if df_scope.empty:
                        st.warning("Nenhum pedido encontrado para a família/grupo selecionados.")
                    else:
                        cat_small = dcat[["_cod_norm", "familia_descricao", "grupo_descricao"]].drop_duplicates("_cod_norm")
                        df_scope = df_scope.merge(cat_small, on="_cod_norm", how="left", suffixes=("", "_cat"))

                        if "familia_descricao" not in df_scope.columns:
                            for c in ("familia_descricao_cat", "familia_descricao_x", "familia_descricao_y"):
                                if c in df_scope.columns:
                                    df_scope["familia_descricao"] = df_scope[c]
                                    break
                        if "grupo_descricao" not in df_scope.columns:
                            for c in ("grupo_descricao_cat", "grupo_descricao_x", "grupo_descricao_y"):
                                if c in df_scope.columns:
                                    df_scope["grupo_descricao"] = df_scope[c]
                                    break

                        df_scope["familia_descricao"] = df_scope.get("familia_descricao", "").fillna("").astype(str)
                        df_scope["grupo_descricao"] = df_scope.get("grupo_descricao", "").fillna("").astype(str)

                        hoje = pd.Timestamp.now().normalize()

                        if col_data and col_data in df_scope.columns:
                            df_scope["_data_oc"] = _safe_datetime_series(df_scope[col_data])
                        else:
                            df_scope["_data_oc"] = pd.NaT

                        df_scope["_prev"] = _safe_datetime_series(df_scope[col_prev]) if col_prev and col_prev in df_scope.columns else pd.NaT
                        df_scope["_prazo"] = _safe_datetime_series(df_scope[col_prazo]) if col_prazo and col_prazo in df_scope.columns else pd.NaT

                        df_scope["_due"] = df_scope["_prev"]
                        df_scope.loc[df_scope["_due"].isna(), "_due"] = df_scope.loc[df_scope["_due"].isna(), "_prazo"]
                        df_scope.loc[df_scope["_due"].isna(), "_due"] = df_scope.loc[df_scope["_due"].isna(), "_data_oc"] + pd.Timedelta(days=30)

                        pendente_flag = pd.Series([True] * len(df_scope), index=df_scope.index)
                        if col_entregue and col_entregue in df_scope.columns:
                            pendente_flag = df_scope[col_entregue] != True
                        if col_qtd_pend and col_qtd_pend in df_scope.columns:
                            qtd_p = pd.to_numeric(df_scope[col_qtd_pend], errors="coerce").fillna(0)
                            pendente_flag = pendente_flag | (qtd_p > 0)

                        df_scope["_pendente"] = pendente_flag
                        df_scope["_atrasado"] = df_scope["_pendente"] & df_scope["_due"].notna() & (df_scope["_due"] < hoje)

                        if col_total and col_total in df_scope.columns:
                            df_scope["_valor_total"] = pd.to_numeric(df_scope[col_total], errors="coerce").fillna(0.0)
                        else:
                            df_scope["_valor_total"] = 0.0

                        if only_pend:
                            df_scope = df_scope[df_scope["_pendente"]]

                        k1, k2, k3, k4 = st.columns(4)
                        k1.metric("📦 Pedidos", int(len(df_scope)))
                        k2.metric("🧾 Materiais", int(df_scope["_cod_norm"].nunique()))
                        k3.metric("⏳ Pendentes", int(df_scope["_pendente"].sum()) if "_pendente" in df_scope.columns else 0)
                        k4.metric("💳 Valor total", formatar_moeda_br(float(df_scope["_valor_total"].sum())))

                        st.markdown("#### Materiais mais recorrentes (no escopo)")
                        c_r1, c_r2, c_r3 = st.columns([1.4, 1.2, 1.2])
                        ordenar = c_r1.selectbox("Ordenar por", ["Valor", "Compras"], index=0, key="fm_busca_ord")
                        limite = c_r2.slider("Mostrar", min_value=5, max_value=50, value=15, step=1, key="fm_busca_lim")
                        mostrar_pedidos = c_r3.toggle("Ver pedidos detalhados", value=False, key="fm_busca_det")

                        gcols = ["_cod_norm"]
                        if "cod_material" in df_scope.columns:
                            gcols.append("cod_material")
                        if "descricao" in df_scope.columns:
                            gcols.append("descricao")

                        df_rank = (
                            df_scope.groupby(gcols, dropna=False)
                            .agg(
                                compras=("id", "count") if "id" in df_scope.columns else ("_cod_norm", "size"),
                                valor=("_valor_total", "sum"),
                            )
                            .reset_index()
                        )

                        df_rank = df_rank.merge(cat_small, on="_cod_norm", how="left")
                        df_rank["familia_descricao"] = df_rank.get("familia_descricao", "").fillna("").astype(str)
                        df_rank["grupo_descricao"] = df_rank.get("grupo_descricao", "").fillna("").astype(str)

                        total_val = float(df_rank["valor"].sum()) if "valor" in df_rank.columns else 0.0
                        total_comp = float(df_rank["compras"].sum()) if "compras" in df_rank.columns else 0.0
                        df_rank["pct_valor"] = (df_rank["valor"] / total_val * 100.0).fillna(0.0) if total_val else 0.0
                        df_rank["pct_comp"] = (df_rank["compras"] / total_comp * 100.0).fillna(0.0) if total_comp else 0.0

                        if ordenar == "Valor":
                            df_rank = df_rank.sort_values(["valor", "compras"], ascending=[False, False])
                        else:
                            df_rank = df_rank.sort_values(["compras", "valor"], ascending=[False, False])

                        for i, row in df_rank.head(int(limite)).iterrows():
                            cod = row.get("cod_material") or row.get("_cod_norm") or ""
                            desc = row.get("descricao") or ""
                            fam_lbl = row.get("familia_descricao") or "—"
                            grp_lbl = row.get("grupo_descricao") or "—"
                            fam_lbl = fam_lbl.strip() if isinstance(fam_lbl, str) else str(fam_lbl)
                            grp_lbl = grp_lbl.strip() if isinstance(grp_lbl, str) else str(grp_lbl)
                            if not fam_lbl or fam_lbl.lower() == "nan":
                                fam_lbl = "—"
                            if not grp_lbl or grp_lbl.lower() == "nan":
                                grp_lbl = "—"

                            card = f"""
                            <div class="fm-card">
                              <div class="fm-title">{cod} — {desc}</div>
                              <div class="fm-sub">Família: {fam_lbl} • Grupo: {grp_lbl}</div>
                              <div class="fm-kpis">
                                <div class="fm-kpi">Compras<b>{int(row.get("compras", 0))}</b></div>
                                <div class="fm-kpi">% Compras<b>{float(row.get("pct_comp", 0.0)):.1f}%</b></div>
                                <div class="fm-kpi">Valor<b>{formatar_moeda_br(float(row.get("valor", 0.0)))}</b></div>
                                <div class="fm-kpi">% Valor<b>{float(row.get("pct_valor", 0.0)):.1f}%</b></div>
                              </div>
                            </div>
                            """
                            cL, cB = st.columns([6, 1])
                            with cL:
                                st.markdown(card, unsafe_allow_html=True)
                            with cB:
                                st.markdown("<br>", unsafe_allow_html=True)
                                if st.button("Ver Ficha", key=f"fg_rank_{i}"):
                                    st.session_state["material_fixo"] = {"cod": cod, "desc": desc}
                                    st.session_state["tipo_busca_ficha"] = "familia_grupo"
                                    st.session_state["equipamento_ctx"] = ""
                                    st.session_state["departamento_ctx"] = ""
                                    st.session_state["modo_ficha_material"] = True
                                    st.rerun()

                            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

                        with st.expander("📊 Consolidado do escopo (Família/Grupo)", expanded=False):
                            if fam_sel == "(Todas)":
                                df_cons = (
                                    df_scope.groupby("familia_descricao", dropna=False)
                                    .agg(Pedidos=("_cod_norm", "size"), Materiais=("_cod_norm", "nunique"), Valor=("_valor_total", "sum"))
                                    .reset_index()
                                    .rename(columns={"familia_descricao": "Família"})
                                    .sort_values("Valor", ascending=False)
                                )
                            elif grp_sel == "(Todos)":
                                df_cons = (
                                    df_scope.groupby("grupo_descricao", dropna=False)
                                    .agg(Pedidos=("_cod_norm", "size"), Materiais=("_cod_norm", "nunique"), Valor=("_valor_total", "sum"))
                                    .reset_index()
                                    .rename(columns={"grupo_descricao": "Grupo"})
                                    .sort_values("Valor", ascending=False)
                                )
                            else:
                                df_cons = (
                                    df_scope.groupby(["familia_descricao", "grupo_descricao"], dropna=False)
                                    .agg(Pedidos=("_cod_norm", "size"), Materiais=("_cod_norm", "nunique"), Valor=("_valor_total", "sum"))
                                    .reset_index()
                                    .rename(columns={"familia_descricao": "Família", "grupo_descricao": "Grupo"})
                                    .sort_values("Valor", ascending=False)
                                )

                            st.dataframe(
                                df_cons,
                                use_container_width=True,
                                hide_index=True,
                                column_config={"Valor": st.column_config.NumberColumn(format="R$ %.2f")},
                            )

                        if mostrar_pedidos:
                            st.markdown("#### Pedidos no escopo (detalhado)")
                            cols = []
                            for c in [col_data, col_oc, col_solic, col_fornecedor, col_status, col_total]:
                                if c and c in df_scope.columns:
                                    cols.append(c)
                            df_det = df_scope.sort_values("_data_oc", ascending=False)
                            st.dataframe(
                                df_det[cols],
                                use_container_width=True,
                                hide_index=True,
                                column_config={
                                    col_data: st.column_config.DateColumn("Data OC", format="DD/MM/YYYY") if col_data else None,
                                    col_total: st.column_config.NumberColumn("Valor Total", format="R$ %.2f") if col_total else None,
                                },
                            )


# ============================================================
    # EXIBIR FICHA DO MATERIAL SELECIONADO (COM ABAS)
    # ============================================================

    if modo_ficha:
        c1, c2 = st.columns([1, 7])
        with c1:
            if st.button("← Nova busca", use_container_width=True):
                st.session_state["modo_ficha_material"] = False
                st.session_state["material_fixo"] = {"cod": None, "desc": None}
                st.session_state["tipo_busca_ficha"] = None
                st.session_state["equipamento_ctx"] = ""
                st.session_state["departamento_ctx"] = ""
                st.rerun()

    material_key = st.session_state.get("material_fixo", {"cod": None, "desc": None})
    material_selecionado_cod = material_key.get("cod")
    material_selecionado_desc = material_key.get("desc")
    tipo_busca = st.session_state.get("tipo_busca_ficha", None)
    equipamento_ctx = st.session_state.get("equipamento_ctx", "")
    departamento_ctx = st.session_state.get("departamento_ctx", "")

        # Montar histórico (normalizando tipos para não “perder” matches)
    historico_material = pd.DataFrame()

    if (material_selecionado_cod is not None) and ("cod_material" in df_pedidos.columns):
        cod_norm = _norm_code(material_selecionado_cod)
        _ser_norm = df_pedidos["cod_material"].fillna("").astype(str).apply(_norm_code)
        historico_material = df_pedidos[_ser_norm == cod_norm].copy()

    elif material_selecionado_desc and ("descricao" in df_pedidos.columns):
        desc_key = str(material_selecionado_desc).strip()
        _ser_desc = df_pedidos["descricao"].fillna("").astype(str).str.strip()
        historico_material = df_pedidos[_ser_desc == desc_key].copy()

        # fallback: contains (para pequenas diferenças de espaçamento/case)
        if historico_material.empty and desc_key:
            historico_material = df_pedidos[
                df_pedidos["descricao"].fillna("").astype(str).str.contains(re.escape(desc_key), case=False, na=False)
            ].copy()

    # A ficha deve abrir mesmo que o histórico esteja vazio (ex.: material novo no catálogo)
    if (material_selecionado_desc or material_selecionado_cod):
        # Pedido mais recente para "material atual"
        if col_data and col_data in historico_material.columns:
            historico_material["_dt"] = _safe_datetime_series(historico_material[col_data])
            material_atual = (
                historico_material.sort_values("_dt", ascending=False)
                .drop(columns=["_dt"], errors="ignore")
                .iloc[0]
                .to_dict()
            )
        else:
            material_atual = historico_material.iloc[0].to_dict()

        st.markdown("---")

        # Contexto claro (histórico completo vs filtrado)
        contexto = "(histórico completo)" if tipo_busca == "material" else "(histórico filtrado)"
        detalhes = []
        if equipamento_ctx:
            detalhes.append(f"Equipamento: **{equipamento_ctx}**")
        if departamento_ctx:
            detalhes.append(f"Departamento: **{departamento_ctx}**")
        detalhes_txt = " • " + " • ".join(detalhes) if detalhes else ""

        st.info(
            f"📌 Exibindo ficha do material {contexto}{detalhes_txt}",
            icon="ℹ️",
        )

        if historico_material is None or historico_material.empty:
            st.warning("Não encontrei pedidos para este material na base atual. Vou mostrar os dados do catálogo e, na aba **Família & Grupo**, os pedidos do mesmo agrupamento (quando existirem).")

        # Header com informações básicas
        cod_show = material_atual.get("cod_material", material_selecionado_cod) if "cod_material" in material_atual else material_selecionado_cod
        dep_show = material_atual.get(col_dep, "N/A") if col_dep else material_atual.get("departamento", "N/A")
        equip_show = material_atual.get(col_equip, "N/A") if col_equip else material_atual.get("cod_equipamento", "N/A")
        desc_show = material_selecionado_desc or material_atual.get("descricao", "Material")

        
        st.markdown(
            f"""
            <div style='background: linear-gradient(135deg, #450a0a 0%, #b91c1c 100%);
                        padding: 25px; border-radius: 15px; color: white; margin-bottom: 20px;'>
                <h2 style='margin: 0; font-size: 28px;'>📦 {desc_show}</h2>
                <p style='margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;'>
                    Código: {cod_show if cod_show else 'N/A'} •
                    Departamento: {dep_show if dep_show else 'N/A'} •
                    Equipamento: {equip_show if equip_show else 'N/A'}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )


        # Enriquecimento pelo Catálogo (se disponível)
        cod_norm = _norm_code(cod_show)
        cat_row = _get_material_catalog_row(_supabase, tenant_id, cod_norm, df_cat)
        # KPIs executivos (usando o histórico bruto do material)
        _dt_hist = _safe_datetime_series(historico_material[col_data]) if (col_data and col_data in historico_material.columns) else pd.Series([pd.NaT] * len(historico_material), index=historico_material.index)
        first_dt = _dt_hist.min()
        last_dt = _dt_hist.max()

        # Preço unitário médio (quando existir coluna unit)
        preco_unit_medio = None
        if col_unit and col_unit in historico_material.columns:
            pu = pd.to_numeric(historico_material[col_unit], errors="coerce")
            if pu.notna().any():
                preco_unit_medio = float(pu.mean())

        a1, a2, a3, a4, a5, a6 = st.columns([1.2, 1.2, 1.2, 1.4, 1.4, 1.2])
        a1.metric("🧾 Código", cod_show if cod_show else "—")
        a2.metric("📅 1ª compra", first_dt.strftime("%d/%m/%Y") if pd.notna(first_dt) else "—")
        a3.metric("📅 Última", last_dt.strftime("%d/%m/%Y") if pd.notna(last_dt) else "—")
        a4.metric("💳 Preço unit. médio", formatar_moeda_br(preco_unit_medio) if preco_unit_medio is not None else "—")
        a5.metric("🏷️ Família", (cat_row or {}).get("familia_descricao") or "—")
        a6.metric("🧩 Grupo", (cat_row or {}).get("grupo_descricao") or "—")

        with st.expander("📚 Dados do Catálogo (dimensões do material)", expanded=False):
            if cat_row:
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Unidade:** {(cat_row.get('unidade') or '—')}")
                c1.write(f"**Almoxarifado:** {(cat_row.get('almoxarifado') or '—')}")
                c2.write(f"**Tipo Material:** {(cat_row.get('tipo_material') or '—')}")
                c2.write(f"**Origem:** {(cat_row.get('origem') or '—')}")
                c3.write(f"**Descrição catálogo:** {(cat_row.get('descricao') or '—')}")
            else:
                st.info("Sem correspondência no catálogo para este código (ou catálogo não importado).")

# ============================================================
        # ABAS: FICHA TÉCNICA vs HISTÓRICO DETALHADO
        # ============================================================

        # ============================================================
        # ABAS (ERP FOLLOW-UP): Acompanhamento / Histórico / Fornecedores / Entregas / Preço
        # ============================================================
        tab_acomp, tab_hist, tab_forn, tab_ent, tab_famgrp, tab_preco = st.tabs(
            ["📌 Acompanhamento", "📦 Histórico", "🏷️ Fornecedores", "🚚 Entregas (SLA)", "🧩 Família & Grupo", "📈 Preço & Insights"]
        )

        # Preparar dados para cálculos de follow-up
        df_mat = historico_material.copy()

        # Datas-base
        if col_data and col_data in df_mat.columns:
            df_mat["_data_oc"] = _safe_datetime_series(df_mat[col_data])
        else:
            df_mat["_data_oc"] = pd.NaT

        # Previsões/prazo e entrega real
        df_mat["_prev"] = _safe_datetime_series(df_mat[col_prev]) if col_prev and col_prev in df_mat.columns else pd.NaT
        df_mat["_prazo"] = _safe_datetime_series(df_mat[col_prazo]) if col_prazo and col_prazo in df_mat.columns else pd.NaT
        df_mat["_entrega_real"] = _safe_datetime_series(df_mat[col_entrega_real]) if col_entrega_real and col_entrega_real in df_mat.columns else pd.NaT

        hoje = pd.Timestamp.now().normalize()

        # Due date: previsao > prazo > data_oc + 30d
        df_mat["_due"] = df_mat["_prev"]
        df_mat.loc[df_mat["_due"].isna(), "_due"] = df_mat.loc[df_mat["_due"].isna(), "_prazo"]
        df_mat.loc[df_mat["_due"].isna(), "_due"] = df_mat.loc[df_mat["_due"].isna(), "_data_oc"] + pd.Timedelta(days=30)

        # Pendente: entregue False OU qtde_pendente > 0
        if col_entregue and col_entregue in df_mat.columns:
            pendente_flag = df_mat[col_entregue] != True
        else:
            pendente_flag = pd.Series([True] * len(df_mat), index=df_mat.index)

        if col_qtd_pend and col_qtd_pend in df_mat.columns:
            qtd_pend = pd.to_numeric(df_mat[col_qtd_pend], errors="coerce").fillna(0)
            pendente_flag = pendente_flag | (qtd_pend > 0)

        df_mat["_pendente"] = pendente_flag
        df_mat["_atrasado"] = df_mat["_pendente"] & df_mat["_due"].notna() & (df_mat["_due"] < hoje)

        # Dias em aberto
        df_mat["_dias_aberto"] = (hoje - df_mat["_data_oc"]).dt.days

        # Valor (para KPIs)
        if col_total and col_total in df_mat.columns:
            df_mat["_valor_total"] = pd.to_numeric(df_mat[col_total], errors="coerce").fillna(0.0)
        else:
            df_mat["_valor_total"] = 0.0

        # Score de criticidade simples (follow-up)
        qtd_atrasados = int(df_mat["_atrasado"].sum())
        valor_pendente = float(df_mat.loc[df_mat["_pendente"], "_valor_total"].sum())
        fornecedor_unico = 0
        if col_fornecedor and col_fornecedor in df_mat.columns:
            fornecedor_unico = int(df_mat[col_fornecedor].dropna().nunique() == 1)

        score = 0
        if qtd_atrasados > 0:
            score += 3
        if valor_pendente >= 50000:
            score += 2
        elif valor_pendente >= 15000:
            score += 1
        if fornecedor_unico:
            score += 2
        if len(df_mat) >= 15:
            score += 1

        if score >= 5:
            nivel = "🔴 CRÍTICO"
        elif score >= 3:
            nivel = "🟡 ATENÇÃO"
        else:
            nivel = "🟢 SAUDÁVEL"

        # KPI bar (ERP)
        # - Valor total: soma de todos os pedidos no escopo (família/grupo/material)
        # - Valor pendente: soma apenas dos itens ainda pendentes
        valor_total_escopo = float(df_mat["_valor_total"].sum())
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("📦 Pedidos", int(len(df_mat)))
        k2.metric("⏳ Pendentes", int(df_mat["_pendente"].sum()))
        k3.metric("🔴 Atrasados", qtd_atrasados)
        k4.metric("💳 Valor total", formatar_moeda_br(valor_total_escopo))
        k5.metric("💰 Valor pendente", formatar_moeda_br(valor_pendente))
        mais_antigo = df_mat.loc[df_mat["_pendente"], "_dias_aberto"].max()
        k6.metric("🧭 Mais antigo (dias)", f"{int(mais_antigo)}" if pd.notna(mais_antigo) else "—")

        st.caption(f"Criticidade do follow-up: **{nivel}** • Regra de atraso: previsão > prazo > OC + 30 dias")

        with tab_acomp:
            st.markdown("### 📌 Fila de Follow-up (pedidos pendentes)")

            f1, f2, f3, f4 = st.columns([1.2, 1.2, 1.2, 1.4])
            only_atrasados = f1.toggle("Só atrasados", value=False)
            only_pendentes = f2.toggle("Só pendentes", value=True)
            ordenar = f3.selectbox("Ordenar por", ["Prioridade", "Maior valor", "Mais antigo"], index=0)
            limite = f4.selectbox("Mostrar", [20, 50, 100, 200], index=0)

            df_work = df_mat.copy()
            if only_pendentes:
                df_work = df_work[df_work["_pendente"]]
            if only_atrasados:
                df_work = df_work[df_work["_atrasado"]]

            # Prioridade: atrasado, maior valor, mais antigo
            df_work["_prio_atraso"] = df_work["_atrasado"].astype(int)
            df_work["_prio_valor"] = df_work["_valor_total"]
            df_work["_prio_dias"] = df_work["_dias_aberto"].fillna(-1)

            if ordenar == "Prioridade":
                df_work = df_work.sort_values(
                    ["_prio_atraso", "_prio_valor", "_prio_dias"],
                    ascending=[False, False, False],
                )
            elif ordenar == "Maior valor":
                df_work = df_work.sort_values(["_valor_total"], ascending=[False])
            else:
                df_work = df_work.sort_values(["_dias_aberto"], ascending=[False])

            cols_show = []
            if col_oc and col_oc in df_work.columns:
                cols_show.append(col_oc)
            if col_solic and col_solic in df_work.columns:
                cols_show.append(col_solic)
            if col_fornecedor and col_fornecedor in df_work.columns:
                cols_show.append(col_fornecedor)
            if col_status and col_status in df_work.columns:
                cols_show.append(col_status)
            if col_qtd and col_qtd in df_work.columns:
                cols_show.append(col_qtd)
            if col_qtd_pend and col_qtd_pend in df_work.columns:
                cols_show.append(col_qtd_pend)

            cols_show += ["_due", "_dias_aberto", "_valor_total", "_atrasado"]

            df_view = df_work[cols_show].head(int(limite)).copy()

            rename = {"_due": "Vencimento", "_dias_aberto": "Dias em aberto", "_valor_total": "Valor Total", "_atrasado": "Atrasado?"}
            if col_oc:
                rename[col_oc] = "OC"
            if col_solic:
                rename[col_solic] = "Solicitação"
            if col_fornecedor:
                rename[col_fornecedor] = "Fornecedor"
            if col_status:
                rename[col_status] = "Status"
            if col_qtd:
                rename[col_qtd] = "Qtd Sol."
            if col_qtd_pend:
                rename[col_qtd_pend] = "Qtd Pend."

            df_view = df_view.rename(columns=rename)

            st.dataframe(
                df_view,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Vencimento": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "Valor Total": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Atrasado?": st.column_config.CheckboxColumn(),
                },
            )

            st.caption("Priorize os itens **atrasados** e/ou de **maior valor** para cobrar fornecedor e destravar entrega.")

        with tab_hist:
            st.markdown("### 📦 Histórico do material")
            st.caption("Auditoria e histórico completo (com filtros e exportação).")

            c1, c2, c3 = st.columns([1.2, 1.2, 1.6])
            filtro_status = None
            if col_status and col_status in df_mat.columns:
                status_opts = sorted(df_mat[col_status].dropna().astype(str).unique().tolist())
                filtro_status = c1.multiselect("Status", status_opts, default=status_opts)
            filtro_entrega = c2.selectbox("Entrega", ["Todos", "Entregues", "Pendentes"], index=0)
            janela = c3.selectbox("Período", ["Tudo", "Últimos 3 meses", "Últimos 6 meses", "Último ano"], index=0)

            dfh = df_mat.copy()
            if filtro_status is not None and col_status:
                dfh = dfh[dfh[col_status].astype(str).isin(filtro_status)]

            if filtro_entrega == "Entregues":
                dfh = dfh[~dfh["_pendente"]]
            elif filtro_entrega == "Pendentes":
                dfh = dfh[dfh["_pendente"]]

            if janela != "Tudo" and dfh["_data_oc"].notna().any():
                if janela == "Últimos 3 meses":
                    lim = hoje - pd.DateOffset(months=3)
                elif janela == "Últimos 6 meses":
                    lim = hoje - pd.DateOffset(months=6)
                else:
                    lim = hoje - pd.DateOffset(years=1)
                dfh = dfh[dfh["_data_oc"] >= lim]

            cols_core = []
            for c in [col_data, col_oc, col_solic, col_status, col_fornecedor, col_qtd, col_qtd_pend, col_total, col_entregue, col_prev, col_prazo, col_entrega_real, "observacoes"]:
                if c and c in dfh.columns and c not in cols_core:
                    cols_core.append(c)

            df_core = dfh.sort_values("_data_oc", ascending=False)
            st.dataframe(
                df_core[cols_core],
                use_container_width=True,
                hide_index=True,
                column_config={
                    col_data: st.column_config.DateColumn("Data OC", format="DD/MM/YYYY") if col_data else None,
                    col_total: st.column_config.NumberColumn("Valor Total", format="R$ %.2f") if col_total else None,
                },
            )

            with st.expander("🔎 Ver colunas completas (auditoria)"):
                cols_all = [c for c in historico_material.columns if c in dfh.columns]
                st.dataframe(df_core[cols_all], use_container_width=True, hide_index=True)

            csv_bytes = df_core.drop(columns=[c for c in df_core.columns if c.startswith("_")], errors="ignore").to_csv(index=False).encode("utf-8")
            nome = str(cod_show or "material").replace(" ", "_")
            st.download_button(
                "📥 Exportar histórico do material (CSV)",
                data=csv_bytes,
                file_name=f"historico_{nome}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with tab_forn:
            st.markdown("### 🏷️ Análise de fornecedores (follow-up)")
            if not (col_fornecedor and col_fornecedor in df_mat.columns):
                st.info("ℹ️ Não encontrei coluna de fornecedor nos pedidos para este material.")
            else:
                df_f = df_mat.copy()
                df_f["Fornecedor"] = df_f[col_fornecedor].astype(str)

                resumo = (
                    df_f.groupby("Fornecedor", dropna=False)
                    .agg(
                        Pedidos=("id", "count") if "id" in df_f.columns else ("Fornecedor", "size"),
                        Pendentes=("_pendente", "sum"),
                        Atrasados=("_atrasado", "sum"),
                        Valor=("_valor_total", "sum"),
                        DiasMedio=("_dias_aberto", "mean"),
                    )
                    .reset_index()
                )
                resumo["% Atraso"] = (resumo["Atrasados"] / resumo["Pedidos"]).fillna(0) * 100
                resumo = resumo.sort_values(["Atrasados", "Pendentes", "Valor"], ascending=[False, False, False])

                st.dataframe(
                    resumo,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                        "DiasMedio": st.column_config.NumberColumn("Dias em aberto (média)", format="%.0f"),
                        "% Atraso": st.column_config.NumberColumn(format="%.1f%%"),
                    },
                )

                st.caption("Use **% Atraso** e **Pendentes** para decidir onde cobrar primeiro.")

        with tab_ent:
            st.markdown("### 🚚 Entregas e SLA")
            st.caption("Baseado em vencimento (previsão/prazo) vs entrega real. Para pendentes, considera vencimento.")

            df_ent = df_mat.copy()
            entregues_mask = ~df_ent["_pendente"]
            df_done = df_ent[entregues_mask & df_ent["_entrega_real"].notna() & df_ent["_due"].notna()].copy()

            if df_done.empty:
                st.info("ℹ️ Não há entregas com datas suficientes (vencimento e entrega real) para calcular SLA.")
            else:
                df_done["_no_prazo"] = df_done["_entrega_real"] <= df_done["_due"]
                sla = float(df_done["_no_prazo"].mean() * 100)

                atraso_dias = (df_done["_entrega_real"] - df_done["_due"]).dt.days
                atraso_medio = float(atraso_dias[atraso_dias > 0].mean()) if (atraso_dias > 0).any() else 0.0

                a1, a2, a3 = st.columns(3)
                a1.metric("✅ SLA (no prazo)", f"{sla:.1f}%")
                a2.metric("⏱️ Atraso médio (dias)", f"{atraso_medio:.0f}")
                a3.metric("📦 Entregas analisadas", int(len(df_done)))

                view_cols = []
                for c in [col_oc, col_solic, col_fornecedor, col_status]:
                    if c and c in df_done.columns:
                        view_cols.append(c)
                view_cols += ["_due", "_entrega_real"]

                st.dataframe(
                    df_done[view_cols].rename(columns={"_due": "Vencimento", "_entrega_real": "Entrega real"}),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Vencimento": st.column_config.DateColumn(format="DD/MM/YYYY"),
                        "Entrega real": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    },
                )

        
        with tab_famgrp:
            st.markdown("### 🧩 Pedidos por Família / Grupo")
            st.caption("Visão consolidada para analisar o consumo e follow-up do *cluster* do material (família/grupo) usando o Catálogo.")

            if df_cat.empty:
                st.info("Importe o **Catálogo de Materiais** para habilitar Família/Grupo nesta tela.")
            elif not cat_row:
                st.info("Este material não foi encontrado no catálogo (ou o código não está padronizado).")
            
            else:
                if cat_row.get("_tenant_mismatch"):
                    st.warning("Encontrei o material no catálogo, mas em OUTRO tenant_id. Verifique se o material foi importado no tenant correto.")
                fam = (cat_row.get("familia_descricao") or "").strip()
                grp = (cat_row.get("grupo_descricao") or "").strip()

                ctop1, ctop2 = st.columns([2, 3])
                with ctop1:
                    scope = st.radio(
                        "Escopo",
                        ["Família", "Grupo", "Família + Grupo"],
                        horizontal=True,
                        key="fm_scope_famgrp",
                    )
                with ctop2:
                    st.markdown(
                        f"**Material atual:** Família: `{fam or '—'}`  ·  Grupo: `{grp or '—'}`"
                    )

                if scope == "Família":
                    if not fam:
                        st.warning("Este material está sem **Família** no catálogo.")
                        st.stop()
                    cat_scope = df_cat[df_cat.get("familia_descricao", "").astype(str).str.strip() == fam]
                    titulo_scope = f"Família: {fam}"
                elif scope == "Grupo":
                    if not grp:
                        st.warning("Este material está sem **Grupo** no catálogo.")
                        st.stop()
                    cat_scope = df_cat[df_cat.get("grupo_descricao", "").astype(str).str.strip() == grp]
                    titulo_scope = f"Grupo: {grp}"
                else:
                    if not fam and not grp:
                        st.warning("Este material está sem **Família** e **Grupo** no catálogo.")
                        st.stop()
                    cat_scope = df_cat.copy()
                    if fam:
                        cat_scope = cat_scope[cat_scope.get("familia_descricao", "").astype(str).str.strip() == fam]
                    if grp:
                        cat_scope = cat_scope[cat_scope.get("grupo_descricao", "").astype(str).str.strip() == grp]
                    titulo_scope = f"Família: {fam or '—'} + Grupo: {grp or '—'}"

                codes = set([c for c in cat_scope.get("_cod_norm", pd.Series([], dtype=str)).astype(str).tolist() if c])
                if not codes:
                    st.info("Nenhum material encontrado no catálogo para o escopo selecionado.")
                    st.stop()

                df_scope = df_pedidos[df_pedidos.get("_cod_norm", pd.Series([], dtype=str)).isin(codes)].copy()

                st.markdown(f"#### {titulo_scope}")
                st.caption(f"Materiais no escopo: **{len(codes)}**  ·  Pedidos no escopo: **{len(df_scope)}**")

                if df_scope.empty:
                    st.warning("Nenhum pedido encontrado para o escopo selecionado.")
                    st.stop()

                # ---- filtros executivos
                f1, f2, f3, f4 = st.columns([1.2, 1.2, 1.4, 1.2])
                only_pend = f1.toggle("Só pendentes", value=True, key="fm_fg_only_pend")
                only_atras = f2.toggle("Só atrasados", value=False, key="fm_fg_only_atras")
                janela = f3.selectbox("Período", ["Tudo", "Últimos 3 meses", "Últimos 6 meses", "Último ano"], index=0, key="fm_fg_janela")
                limite = f4.selectbox("Mostrar", [20, 50, 100, 200, 500], index=1, key="fm_fg_lim")

                # Datas
                if col_data and col_data in df_scope.columns:
                    df_scope["_data_oc"] = _safe_datetime_series(df_scope[col_data])
                else:
                    df_scope["_data_oc"] = pd.NaT

                hoje2 = pd.Timestamp.now().normalize()

                df_scope["_prev"] = _safe_datetime_series(df_scope[col_prev]) if col_prev and col_prev in df_scope.columns else pd.NaT
                df_scope["_prazo"] = _safe_datetime_series(df_scope[col_prazo]) if col_prazo and col_prazo in df_scope.columns else pd.NaT
                df_scope["_due"] = df_scope["_prev"]
                df_scope.loc[df_scope["_due"].isna(), "_due"] = df_scope.loc[df_scope["_due"].isna(), "_prazo"]
                df_scope.loc[df_scope["_due"].isna(), "_due"] = df_scope.loc[df_scope["_due"].isna(), "_data_oc"] + pd.Timedelta(days=30)

                # Pendente
                pend_flag = pd.Series([True] * len(df_scope), index=df_scope.index)
                if col_entregue and col_entregue in df_scope.columns:
                    pend_flag = df_scope[col_entregue] != True
                if col_qtd_pend and col_qtd_pend in df_scope.columns:
                    qtd_p = pd.to_numeric(df_scope[col_qtd_pend], errors="coerce").fillna(0)
                    pend_flag = pend_flag | (qtd_p > 0)
                df_scope["_pendente"] = pend_flag
                df_scope["_atrasado"] = df_scope["_pendente"] & df_scope["_due"].notna() & (df_scope["_due"] < hoje2)

                # Valor
                if col_total and col_total in df_scope.columns:
                    df_scope["_valor_total"] = pd.to_numeric(df_scope[col_total], errors="coerce").fillna(0.0)
                else:
                    df_scope["_valor_total"] = 0.0

                # janela
                if janela != "Tudo":
                    if janela == "Últimos 3 meses":
                        lim_dt = hoje2 - pd.DateOffset(months=3)
                    elif janela == "Últimos 6 meses":
                        lim_dt = hoje2 - pd.DateOffset(months=6)
                    else:
                        lim_dt = hoje2 - pd.DateOffset(years=1)
                    df_scope = df_scope[df_scope["_data_oc"] >= lim_dt]

                if only_pend:
                    df_scope = df_scope[df_scope["_pendente"]]
                if only_atras:
                    df_scope = df_scope[df_scope["_atrasado"]]

                # KPIs
                kk1, kk2, kk3, kk4, kk5 = st.columns(5)
                kk1.metric("📦 Pedidos", int(len(df_scope)))
                kk2.metric("🧾 Materiais", int(df_scope["_cod_norm"].nunique()) if "_cod_norm" in df_scope.columns else 0)
                kk3.metric("💰 Valor", formatar_moeda_br(float(df_scope["_valor_total"].sum())))
                kk4.metric("⏳ Pendentes", int(df_scope["_pendente"].sum()) if "_pendente" in df_scope.columns else 0)
                kk5.metric("🔴 Atrasados", int(df_scope["_atrasado"].sum()) if "_atrasado" in df_scope.columns else 0)

                # Consolidado por material
                group_cols = []
                if "cod_material" in df_scope.columns:
                    group_cols.append("cod_material")
                if "descricao" in df_scope.columns:
                    group_cols.append("descricao")
                if not group_cols:
                    group_cols = ["_cod_norm"]

                agg = (
                    df_scope.groupby(group_cols, dropna=False)
                    .agg(
                        Pedidos=("id", "count") if "id" in df_scope.columns else ("_valor_total", "size"),
                        Valor=("_valor_total", "sum"),
                        Pendentes=("_pendente", "sum"),
                        Atrasados=("_atrasado", "sum"),
                        Ultima=("_data_oc", "max"),
                    )
                    .reset_index()
                    .sort_values(["Atrasados", "Pendentes", "Valor", "Pedidos"], ascending=[False, False, False, False])
                )

                st.markdown("#### 📊 Materiais mais relevantes (no escopo)")

                view_fg = st.radio(
                    "Visualização",
                    ["Cards", "Tabela"],
                    horizontal=True,
                    key="fm_view_famgrp",
                    label_visibility="collapsed",
                )

                topn = agg.head(int(limite)).copy()

                if view_fg == "Tabela":
                    st.dataframe(
                        topn,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                            "Ultima": st.column_config.DateColumn(format="DD/MM/YYYY"),
                        },
                    )
                else:
                    st.markdown(
                        """<style>
                          .fg-grid { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
                          @media (max-width: 900px){ .fg-grid { grid-template-columns: 1fr; } }
                          .fg-card{
                            border: 1px solid rgba(255,255,255,.10);
                            background: rgba(255,255,255,.03);
                            border-radius: 16px;
                            padding: 12px 14px;
                          }
                          .fg-title{ font-weight: 900; font-size: .95rem; margin-bottom: 4px; }
                          .fg-sub{ opacity: .80; font-size: .82rem; margin-bottom: 10px; }
                          .fg-kpis{ display:flex; gap: 10px; flex-wrap: wrap; }
                          .fg-kpi{
                            background: rgba(0,0,0,.18);
                            border: 1px solid rgba(255,255,255,.08);
                            border-radius: 12px;
                            padding: 6px 10px;
                            font-size: .80rem;
                            line-height: 1.2;
                          }
                          .fg-kpi b{ display:block; font-size:.95rem; margin-top:2px; }
                        </style>""",
                        unsafe_allow_html=True,
                    )
                    st.markdown('<div class="fg-grid">', unsafe_allow_html=True)
                    for _i, _row in topn.reset_index(drop=True).iterrows():
                        cod = str(_row.get("cod_material") or _row.get("_cod_norm") or "—")
                        desc = str(_row.get("descricao") or "").strip()
                        if len(desc) > 90:
                            desc = desc[:89] + "…"
                        pedidos = int(_row.get("Pedidos", 0) or 0)
                        pend = int(_row.get("Pendentes", 0) or 0)
                        atr = int(_row.get("Atrasados", 0) or 0)
                        val = float(_row.get("Valor", 0.0) or 0.0)
                        ultima = _row.get("Ultima")
                        ultima_txt = ultima.strftime("%d/%m/%Y") if hasattr(ultima, "strftime") and pd.notna(ultima) else "—"

                        sev = "rgba(239,68,68,.22)" if atr > 0 else ("rgba(245,158,11,.18)" if pend > 0 else "rgba(34,197,94,.16)")
                        html = f"""<div class='fg-card' style='border-color:{sev}'>
                  <div class='fg-title'>{cod}</div>
                  <div class='fg-sub'>{desc or '—'}</div>
                  <div class='fg-kpis'>
                    <div class='fg-kpi'>Pedidos<b>{pedidos}</b></div>
                    <div class='fg-kpi'>Pendentes<b>{pend}</b></div>
                    <div class='fg-kpi'>Atrasados<b>{atr}</b></div>
                    <div class='fg-kpi'>Valor<b>{formatar_moeda_br(val)}</b></div>
                    <div class='fg-kpi'>Última<b>{ultima_txt}</b></div>
                  </div>
                </div>"""
                        st.markdown(html, unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
                csv_fg = agg.to_csv(index=False).encode("utf-8")
                st.download_button("Baixar CSV (consolidado)", data=csv_fg, file_name="pedidos_por_familia_grupo.csv", mime="text/csv")

                st.markdown("#### 🔎 Pedidos detalhados (no escopo)")
                cols_det = [c for c in [col_data, col_oc, col_solic, "cod_material", "descricao", col_dep, col_equip, col_fornecedor, col_status, col_qtd, col_qtd_pend, col_total] if c and c in df_scope.columns]
                df_det = df_scope.sort_values("_data_oc", ascending=False)
                st.dataframe(df_det[cols_det].head(int(limite)), use_container_width=True, hide_index=True)



        with tab_preco:
            st.markdown("### 📈 Preço e Insights")

            # Guard rails: só desenhar preço se houver dados
            if col_unit and col_unit in historico_material.columns and pd.to_numeric(historico_material[col_unit], errors="coerce").notna().sum() >= 2:
                col1, col2 = st.columns([2, 1])
                with col1:
                    fm.criar_grafico_evolucao_precos(historico_material)
                    st.markdown("<br>", unsafe_allow_html=True)
                    fm.criar_comparacao_visual_precos(historico_material)
                with col2:
                    fm.criar_mini_mapa_fornecedores(historico_material)

                st.markdown("---")
                fm.criar_ranking_fornecedores_visual(historico_material)
            else:
                st.info("📊 Ainda não há histórico suficiente de preço para gráficos comparativos.")

            st.markdown("---")
            fm.criar_timeline_compras(historico_material)

            st.markdown("---")
            _call_insights_automaticos(historico_material, material_atual)



        st.markdown("---")
        if st.button("← Voltar para Consulta", use_container_width=True):
            st.session_state.pagina = "Consultar Pedidos"
            st.rerun()
