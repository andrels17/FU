"""Tela: Ficha de material."""
from __future__ import annotations

from datetime import datetime

import re

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
def _carregar_pedidos_cache(_supabase):
    # Cache simples para deixar a página mais rápida e reduzir chamadas ao banco

    return carregar_pedidos(_supabase, st.session_state.get("tenant_id"))

@st.cache_data(ttl=600)
def _carregar_materiais_cache(_supabase):
    """Carrega catálogo de materiais (família/grupo) do tenant atual."""
    tenant_id = st.session_state.get("tenant_id")
    if not tenant_id:
        return pd.DataFrame()

    try:
        resp = (
            _supabase.table("materiais")
            .select("codigo_material,familia_descricao,grupo_descricao")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        data = getattr(resp, "data", None) if resp is not None else None
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        return df
    except Exception:
        return pd.DataFrame()


def _norm_code(x) -> str:
    """Normaliza códigos para casar pedidos(cod_material texto) com materiais(codigo_material bigint).
    - 857.0 / '857.0' / '857,0' -> '857'
    - remove não-dígitos
    - remove zeros à esquerda
    """
    if x is None:
        return ""
    # número (int/float)
    try:
        if isinstance(x, (int,)):
            s = str(x)
        elif isinstance(x, float):
            if pd.isna(x):
                return ""
            s = str(int(x))
        else:
            s = str(x).strip()
            # trata '857.0' / '857,0'
            m = re.fullmatch(r"\s*(\d+)[\.,]0+\s*", s)
            if m:
                s = m.group(1)
    except Exception:
        s = str(x).strip()

    s = re.sub(r"\D+", "", s)
    s = s.lstrip("0")
    return s or "0"

def _norm_txt(x) -> str:
    """Normaliza textos (família/grupo) para comparação resiliente.
    - remove NBSP e espaços duplicados
    - remove acentos
    - trata pontuação como separador (/, &, -, vírgulas, pontos)
    - UPPER
    """
    s = "" if x is None else str(x)
    s = s.replace("\u00a0", " ").strip()
    # remove acentos (ex.: ELÉTRICOS -> ELETRICOS)
    try:
        import unicodedata
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
    except Exception:
        pass
    s = s.upper()
    # pontuação -> espaço (ex.: "BATERIAS,PILHAS" -> "BATERIAS PILHAS")
    s = re.sub(r"[\/,&;\-_.()\[\]{}]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s



def _clean_label(x) -> str:
    """Converte valores para label exibível (sem 'nan')."""
    try:
        if x is None:
            return "—"
        import pandas as _pd
        if _pd.isna(x):
            return "—"
    except Exception:
        pass
    s = str(x).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return "—"
    return s



def _first_val(df_scope: pd.DataFrame, codn: str, col: str | None) -> object:
    """Primeiro valor não-vazio para um código no escopo."""
    if not col or df_scope is None or df_scope.empty or col not in df_scope.columns:
        return None
    s = df_scope.loc[df_scope.get('_cod_norm','') == codn, col]
    if s is None or len(s) == 0:
        return None
    # pega o primeiro e retorna (pode ser vazio)
    try:
        return s.iloc[0]
    except Exception:
        return None



    return carregar_pedidos(_supabase, st.session_state.get("tenant_id"))



def _coalesce_merge_suffix(df: pd.DataFrame, base: str) -> pd.DataFrame:
    """Após merge, garante que exista a coluna `base` mesmo quando houver sufixos (_x/_y).
    Mantém preferência pelo lado direito (_y).
    """
    if base in df.columns:
        return df
    by = f"{base}_y"
    bx = f"{base}_x"
    if by in df.columns:
        df[base] = df[by]
    elif bx in df.columns:
        df[base] = df[bx]
    return df

def _pick_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Retorna a primeira coluna existente no df dentre as candidatas."""
    for c in candidates:
        if c in df.columns:
            return c
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


    df_pedidos = _carregar_pedidos_cache(_supabase)

    if df_pedidos.empty:
        st.info("📭 Nenhum pedido cadastrado ainda")
        return

    # Normalizações leves (evitam bugs em filtros e cálculos)
    if "cod_material" in df_pedidos.columns:
        df_pedidos["cod_material"] = df_pedidos["cod_material"].astype(str).str.strip()

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
        # TAB 4: BUSCA POR FAMÍLIA & GRUPO (CATÁLOGO -> PEDIDOS)
        # ============================================================
        with tab4:
            st.markdown("### 🧩 Buscar por Família & Grupo")
            st.caption("Selecione uma **família** e/ou **grupo** do Catálogo para ver todos os pedidos relacionados.")

            df_mat = _carregar_materiais_cache(_supabase)
            if df_mat is None or df_mat.empty:
                st.warning("⚠️ Catálogo de materiais vazio para este tenant. Importe o Catálogo para habilitar Família/Grupo.")
            else:
                # Normalização de chave
                if "codigo_material" in df_mat.columns:
                    df_mat["_cod_norm"] = df_mat["codigo_material"].apply(_norm_code)
                else:
                    st.warning("⚠️ Coluna 'codigo_material' não encontrada na tabela materiais.")
                    df_mat["_cod_norm"] = ""

                dfp = df_pedidos.copy()
                if "cod_material" in dfp.columns:
                    dfp["_cod_norm"] = dfp["cod_material"].apply(_norm_code)
                else:
                    dfp["_cod_norm"] = ""

                # Enriquecer pedidos com família/grupo do catálogo
                dfp = dfp.merge(
                    df_mat[["_cod_norm", "familia_descricao", "grupo_descricao"]].drop_duplicates("_cod_norm"),
                    on="_cod_norm",
                    how="left",
                )
                # Coalesce: garante colunas finais sem sufixos (_x/_y) e evita "nan" em string
                for base in ("familia_descricao", "grupo_descricao"):
                    if base not in dfp.columns:
                        # Se o merge criou sufixos
                        bx = f"{base}_x" if f"{base}_x" in dfp.columns else None
                        by = f"{base}_y" if f"{base}_y" in dfp.columns else None
                        if by and bx:
                            dfp[base] = dfp[by].combine_first(dfp[bx])
                        elif by:
                            dfp[base] = dfp[by]
                        elif bx:
                            dfp[base] = dfp[bx]
                        else:
                            dfp[base] = ""
                    # Normaliza nulos para não virar string "nan"
                    dfp[base] = dfp[base].fillna("").astype(str).replace({"nan": "", "None": ""})
                # Alguns fluxos podem já ter colunas de família/grupo no df_pedidos; após merge, normalize nomes
                dfp = _coalesce_merge_suffix(dfp, 'familia_descricao')
                dfp = _coalesce_merge_suffix(dfp, 'grupo_descricao')
                # Normaliza textos (para evitar mismatch por espaços/capitalização)
                for _col in ["familia_descricao", "grupo_descricao"]:
                    if _col in df_mat.columns:
                        df_mat[_col] = df_mat[_col].fillna("").astype(str).str.replace("\u00a0", " ").str.strip()
                    if _col in dfp.columns:
                        dfp[_col] = dfp[_col].fillna("").astype(str).str.replace("\u00a0", " ").str.strip()

                df_mat["_fam_norm"] = df_mat.get("familia_descricao", pd.Series([], dtype=str)).apply(_norm_txt)
                df_mat["_grp_norm"] = df_mat.get("grupo_descricao", pd.Series([], dtype=str)).apply(_norm_txt)
                dfp["_fam_norm"] = dfp.get("familia_descricao", pd.Series([], dtype=str)).apply(_norm_txt)
                dfp["_grp_norm"] = dfp.get("grupo_descricao", pd.Series([], dtype=str)).apply(_norm_txt)



                fam_opts = sorted([x for x in df_mat.get("familia_descricao", pd.Series([], dtype=str)).dropna().astype(str).str.strip().unique().tolist() if str(x).strip()])
                grp_opts_all = sorted([x for x in df_mat.get("grupo_descricao", pd.Series([], dtype=str)).dropna().astype(str).str.strip().unique().tolist() if str(x).strip()])

                c1, c2, c3 = st.columns([2.2, 2.2, 1.2])
                with c1:
                    fam_sel = st.selectbox("Família", ["(Todas)"] + fam_opts, key="busca_fam_sel")
                with c2:
                    if fam_sel and fam_sel != "(Todas)":
                        fam_norm_sel = _norm_txt(fam_sel)
                        df_tmp = df_mat[df_mat["_fam_norm"] == fam_norm_sel]
                        grp_opts = sorted([x for x in df_tmp.get("grupo_descricao", pd.Series([], dtype=str)).dropna().astype(str).unique().tolist() if str(x).strip()])
                    else:
                        grp_opts = grp_opts_all
                    grp_sel = st.selectbox("Grupo", ["(Todos)"] + grp_opts, key="busca_grp_sel")
                with c3:
                    somente_pend = st.checkbox("Só pendentes", value=False, key="busca_famgrp_pend")

                df_scope = dfp.copy()
                if fam_sel and fam_sel != "(Todas)":
                    fam_norm_sel = _norm_txt(fam_sel)
                    df_scope = df_scope[df_scope["_fam_norm"] == fam_norm_sel]
                if grp_sel and grp_sel != "(Todos)":
                    grp_norm_sel = _norm_txt(grp_sel)
                    df_scope = df_scope[df_scope["_grp_norm"] == grp_norm_sel]

                # Fallback: se não encontrou nada com match exato (muito comum por variações de pontuação),
                # tenta um match "contém" usando o texto normalizado.
                if df_scope.empty and (fam_sel != "(Todas)" or grp_sel != "(Todos)"):
                    df_scope = dfp.copy()
                    if fam_sel and fam_sel != "(Todas)":
                        fam_norm_sel = _norm_txt(fam_sel)
                        df_scope = df_scope[df_scope["_fam_norm"].str.contains(re.escape(fam_norm_sel), na=False)]
                    if grp_sel and grp_sel != "(Todos)":
                        grp_norm_sel = _norm_txt(grp_sel)
                        df_scope = df_scope[df_scope["_grp_norm"].str.contains(re.escape(grp_norm_sel), na=False)]


                # Pendentes: heurística - não entregue OU qtde_pendente > 0
                if somente_pend:
                    if col_entregue and col_entregue in df_scope.columns:
                        mask = df_scope[col_entregue].fillna(False) == False
                        df_scope = df_scope[mask]
                    elif col_status and col_status in df_scope.columns:
                        df_scope = df_scope[df_scope[col_status].fillna("").astype(str).str.lower() != "entregue"]
                    elif col_qtd_pend and col_qtd_pend in df_scope.columns:
                        df_scope = df_scope[pd.to_numeric(df_scope[col_qtd_pend], errors="coerce").fillna(0) > 0]

                if df_scope.empty:
                    st.info("Nenhum pedido encontrado para a combinação selecionada.")
                else:
                    # KPIs
                    total_ped = int(len(df_scope))
                    mats = int(df_scope["_cod_norm"].nunique()) if "_cod_norm" in df_scope.columns else 0
                    v_total = float(pd.to_numeric(df_scope[col_total], errors="coerce").fillna(0).sum()) if col_total and col_total in df_scope.columns else 0.0
                    pend = 0
                    if col_qtd_pend and col_qtd_pend in df_scope.columns:
                        pend = int(pd.to_numeric(df_scope[col_qtd_pend], errors="coerce").fillna(0).gt(0).sum())
                    elif col_status and col_status in df_scope.columns:
                        pend = int(df_scope[col_status].fillna("").astype(str).str.lower().ne("entregue").sum())

                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("Pedidos", f"{total_ped}")
                    k2.metric("Materiais", f"{mats}")
                    k3.metric("Pendentes", f"{pend}")
                    k4.metric("Valor total", formatar_moeda_br(v_total))

                    
                    st.markdown("#### Materiais mais recorrentes (no escopo)")

                    # --- Quebras executivas (quando faz sentido)
                    with st.expander("📊 Consumo consolidado (por Família/Grupo)", expanded=False):
                        if "familia_descricao" in df_scope.columns:
                            fam_tmp = df_scope.copy()
                            fam_tmp["familia_descricao"] = fam_tmp["familia_descricao"].fillna("").astype(str)
                            fam_tmp["grupo_descricao"] = fam_tmp.get("grupo_descricao", "").fillna("").astype(str)
                            # Quando usuário não fixa uma família, vale mostrar por família
                            if fam_sel == "(Todas)":
                                g_fam = fam_tmp.groupby("familia_descricao", dropna=False).agg(
                                    pedidos=("id", "count") if "id" in fam_tmp.columns else ("_cod_norm", "count"),
                                    materiais=("_cod_norm", "nunique"),
                                    valor_total=(col_total, "sum") if col_total and col_total in fam_tmp.columns else ("_cod_norm", "count"),
                                ).reset_index().rename(columns={"familia_descricao": "Família"})
                                g_fam["Família"] = g_fam["Família"].apply(_clean_label)
                                g_fam = g_fam.sort_values("valor_total" if "valor_total" in g_fam.columns else "pedidos", ascending=False)
                                st.dataframe(g_fam.head(30), use_container_width=True, hide_index=True)
                            # Quando usuário fixa uma família mas não fixa grupo, vale mostrar por grupo
                            if fam_sel != "(Todas)" and grp_sel == "(Todos)" and "grupo_descricao" in fam_tmp.columns:
                                g_grp = fam_tmp.groupby("grupo_descricao", dropna=False).agg(
                                    pedidos=("id", "count") if "id" in fam_tmp.columns else ("_cod_norm", "count"),
                                    materiais=("_cod_norm", "nunique"),
                                    valor_total=(col_total, "sum") if col_total and col_total in fam_tmp.columns else ("_cod_norm", "count"),
                                ).reset_index().rename(columns={"grupo_descricao": "Grupo"})
                                g_grp["Grupo"] = g_grp["Grupo"].apply(_clean_label)
                                g_grp = g_grp.sort_values("valor_total" if "valor_total" in g_grp.columns else "pedidos", ascending=False)
                                st.dataframe(g_grp.head(30), use_container_width=True, hide_index=True)
                        else:
                            st.info("Sem dados de Família/Grupo no escopo atual.")

                    # Consolidado por material (ranking)
                    agg_cols = {
                        "descricao": ("descricao", "first") if "descricao" in df_scope.columns else ("_cod_norm", "first"),
                        "compras": ("id", "count") if "id" in df_scope.columns else ("_cod_norm", "count"),
                    }
                    if col_total and col_total in df_scope.columns:
                        agg_cols["valor_total"] = (col_total, "sum")

                    grp = df_scope.groupby(["_cod_norm"], dropna=False).agg(**agg_cols).reset_index()

                    # Se não há coluna de valor_total, usa compras como proxy (mantém compat)
                    if "valor_total" not in grp.columns:
                        grp["valor_total"] = 0.0

                    # Reanexa Família/Grupo a partir do Catálogo (mais confiável do que puxar do df_scope pós-groupby)
                    if df_mat is not None and not df_mat.empty and "_cod_norm" in df_mat.columns:
                        mats_lookup = df_mat[["_cod_norm", "familia_descricao", "grupo_descricao"]].drop_duplicates("_cod_norm")
                        grp = grp.merge(mats_lookup, on="_cod_norm", how="left")
                    else:
                        # fallback: tenta a partir do próprio df_scope
                        cols_fg = [c for c in ["familia_descricao", "grupo_descricao"] if c in df_scope.columns]
                        if cols_fg:
                            fg = df_scope[["_cod_norm"] + cols_fg].drop_duplicates("_cod_norm")
                            grp = grp.merge(fg, on="_cod_norm", how="left")

                    # Limpa labels (evita nan/None)
                    grp["familia_descricao"] = grp.get("familia_descricao", "").fillna("").astype(str).replace({"nan": "", "None": ""})
                    grp["grupo_descricao"] = grp.get("grupo_descricao", "").fillna("").astype(str).replace({"nan": "", "None": ""})

                    # Shares (representatividade no escopo)
                    total_itens_scope = float(grp["compras"].sum()) if "compras" in grp.columns else 0.0
                    total_val_scope = float(grp["valor_total"].sum()) if "valor_total" in grp.columns else 0.0
                    if total_itens_scope <= 0:
                        total_itens_scope = 1.0
                    if total_val_scope <= 0:
                        total_val_scope = 1.0

                    grp["share_itens"] = grp["compras"].astype(float) / total_itens_scope
                    grp["share_valor"] = grp["valor_total"].astype(float) / total_val_scope

                    # Controles do ranking
                    ctrl1, ctrl2 = st.columns([1.2, 1.0])
                    with ctrl1:
                        ordenar_por = st.selectbox("Ordenar por", ["Valor", "Compras"], index=0, key="busca_famgrp_ord")
                    with ctrl2:
                        show_n = st.slider("Mostrar", 5, 50, 15, 5, key="busca_famgrp_show")

                    sort_col = "valor_total" if ordenar_por == "Valor" else "compras"
                    grp = grp.sort_values(sort_col, ascending=False)

                    # Cards (executivo)
                    for _, r in grp.head(int(show_n)).iterrows():
                        codn = r.get("_cod_norm") or ""
                        desc = r.get("descricao") or ""
                        compras = int(r.get("compras") or 0)
                        vt = float(r.get("valor_total") or 0.0)

                        fam_lbl = _clean_label(r.get("familia_descricao"))
                        grp_lbl = _clean_label(r.get("grupo_descricao"))
                        sh_i = float(r.get("share_itens") or 0.0)
                        sh_v = float(r.get("share_valor") or 0.0)

                        cA, cB, cC = st.columns([3.8, 1.2, 1.4])
                        with cA:
                            st.markdown(f"**{codn} — {desc}**")
                            st.caption(f"Família: {fam_lbl}  •  Grupo: {grp_lbl}")
                            st.caption(f"Representatividade: **{sh_v:.1%}** do valor • **{sh_i:.1%}** dos itens")
                        with cB:
                            st.metric("Compras", compras)
                        with cC:
                            st.metric("Valor", formatar_moeda_br(vt))
                            if st.button("Ver Ficha", key=f"famgrp_ver_{codn}"):
                                st.session_state["material_fixo"] = {"cod": codn, "desc": desc}
                                st.session_state["tipo_busca_ficha"] = "familia_grupo"
                                st.session_state["equipamento_ctx"] = ""
                                st.session_state["departamento_ctx"] = ""
                                st.session_state["modo_ficha_material"] = True
                                st.rerun()
                        st.divider()
                    with st.expander("Ver pedidos detalhados do escopo", expanded=False):
                        # Lista estilo "ERP" (sem modal)
                        df_det = df_scope.copy()
                        if col_data and col_data in df_det.columns:
                            df_det["_dt"] = _safe_datetime_series(df_det[col_data])
                            df_det = df_det.sort_values("_dt", ascending=False).drop(columns=["_dt"], errors="ignore")

                        max_rows = st.slider("Linhas", 20, 300, 80, 20, key="busca_famgrp_det_rows")
                        df_det = df_det.head(int(max_rows))

                        # Header
                        h1, h2, h3, h4, h5, h6 = st.columns([1.1, 1.0, 1.0, 1.0, 1.0, 1.8])
                        h1.caption("Data")
                        h2.caption("OC")
                        h3.caption("Solic.")
                        h4.caption("Status")
                        h5.caption("Pend.")
                        h6.caption("Descrição / Valor")

                        for i, row in df_det.iterrows():
                            c1, c2, c3, c4, c5, c6 = st.columns([1.1, 1.0, 1.0, 1.0, 1.0, 1.8])
                            dtx = row.get(col_data) if col_data and col_data in df_det.columns else ""
                            ocx = row.get(col_oc) if col_oc and col_oc in df_det.columns else ""
                            solx = row.get(col_solic) if col_solic and col_solic in df_det.columns else ""
                            stx = row.get(col_status) if col_status and col_status in df_det.columns else ""
                            pendx = row.get(col_qtd_pend) if col_qtd_pend and col_qtd_pend in df_det.columns else ""
                            descx = row.get("descricao") if "descricao" in df_det.columns else row.get("_cod_norm","")
                            descx = str(descx) if descx is not None else ""
                            if len(descx) > 65:
                                descx = descx[:62] + "…"
                            vtx = row.get(col_total) if col_total and col_total in df_det.columns else None

                            c1.write(str(dtx)[:10] if dtx else "—")
                            c2.write(str(ocx) if ocx else "—")
                            c3.write(str(solx) if solx else "—")
                            c4.write(str(stx) if stx else "—")
                            c5.write(str(pendx) if str(pendx) != "" else "—")
                            if vtx is not None and col_total and col_total in df_det.columns:
                                try:
                                    vnum = float(pd.to_numeric(vtx, errors="coerce"))
                                except Exception:
                                    vnum = 0.0
                                c6.write(f"{descx}  •  {formatar_moeda_br(vnum)}")
                            else:
                                c6.write(descx)

                            st.divider()


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

    # Montar histórico (preferir cod_material quando existir)
    if material_selecionado_cod and "cod_material" in df_pedidos.columns:
        historico_material = df_pedidos[df_pedidos["cod_material"] == str(material_selecionado_cod)].copy()
    elif material_selecionado_desc and "descricao" in df_pedidos.columns:
        historico_material = df_pedidos[df_pedidos["descricao"] == str(material_selecionado_desc)].copy()

    if not historico_material.empty and (material_selecionado_desc or material_selecionado_cod):
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

        # Header com informações básicas
        cod_show = material_atual.get("cod_material", material_selecionado_cod) if "cod_material" in material_atual else material_selecionado_cod
        dep_show = material_atual.get(col_dep, "N/A") if col_dep else material_atual.get("departamento", "N/A")
        equip_show = material_atual.get(col_equip, "N/A") if col_equip else material_atual.get("cod_equipamento", "N/A")
        desc_show = material_selecionado_desc or material_atual.get("descricao", "Material")

        st.markdown(
            f"""
            <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
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

        # ============================================================
        # ABAS: FICHA TÉCNICA vs HISTÓRICO DETALHADO
        # ============================================================

        # ============================================================
        # ABAS (ERP FOLLOW-UP): Acompanhamento / Histórico / Fornecedores / Entregas / Preço
        # ============================================================
        tab_acomp, tab_hist, tab_forn, tab_ent, tab_preco = st.tabs(
            ["📌 Acompanhamento", "📦 Histórico", "🏷️ Fornecedores", "🚚 Entregas (SLA)", "📈 Preço & Insights"]
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
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("📦 Pedidos", int(len(df_mat)))
        k2.metric("⏳ Pendentes", int(df_mat["_pendente"].sum()))
        k3.metric("🔴 Atrasados", qtd_atrasados)
        k4.metric("💰 Valor pendente", formatar_moeda_br(valor_pendente))
        mais_antigo = df_mat.loc[df_mat["_pendente"], "_dias_aberto"].max()
        k5.metric("🧭 Mais antigo (dias)", f"{int(mais_antigo)}" if pd.notna(mais_antigo) else "—")

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
