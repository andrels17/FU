"""Tela: Gestão de pedidos."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import src.services.backup_auditoria as ba
import src.services.exportacao_relatorios as er  # noqa: F401  (pode estar sendo usado em outras partes)
import src.services.filtros_avancados as fa  # noqa: F401

from src.repositories.fornecedores import carregar_fornecedores
from src.repositories.pedidos import carregar_pedidos, registrar_entrega, salvar_pedido
from src.utils.formatting import formatar_moeda_br, formatar_numero_br  # noqa: F401
from src.ui.theme import apply_theme, section_header


# -------------------------------
# Helpers de performance / UX
# -------------------------------
def _make_df_stamp(df: pd.DataFrame, col: str = "atualizado_em") -> tuple:
    if df is None or df.empty:
        return (0, "empty")

    if col not in df.columns:
        return (int(len(df)), "none")

    serie = pd.to_datetime(df[col], errors="coerce", utc=True)
    mx = serie.max()

    return (int(len(df)), mx.isoformat() if pd.notna(mx) else "none")



@st.cache_data(ttl=120)
def _build_pedido_labels(stamp: tuple, df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Gera listas paralelas: labels (para UI) e ids (valor real)."""
    if df is None or df.empty:
        return [], []

    nr_oc = df.get("nr_oc", "").fillna("").astype(str)
    desc = (
        df.get("descricao", "")
        .fillna("")
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    dept = df.get("departamento", "").fillna("").astype(str)
    status = df.get("status", "").fillna("").astype(str)
    nr_sol = df.get("nr_solicitacao", "").fillna("").astype(str).str.strip()

    equip = df.get("cod_equipamento", "").fillna("").astype(str).str.strip()
    mat = df.get("cod_material", "").fillna("").astype(str).str.strip()

    # Chave principal (OC > Solicitação > ID curto)
    _oc = nr_oc.fillna("").astype(str).str.strip()
    _sol = nr_sol
    id_short = df["id"].astype(str).str.slice(0, 8)
    key_raw = _oc.where(_oc != "", _sol)
    prefix = pd.Series("OC", index=df.index).where(_oc != "", "SOL")
    prefix = prefix.where(key_raw != "", "ID")
    key = key_raw.where(key_raw != "", id_short)

    # Tags curtas para localizar rápido
    equip_tag = equip.where(equip == "", "EQ:" + equip)
    mat_tag = mat.where(mat == "", "MAT:" + mat)
    extra = (equip_tag + " " + mat_tag).str.replace(r"\s+", " ", regex=True).str.strip()
    extra_fmt = (" | " + extra).where(extra != "", "")

    labels = (prefix + ": " + key + " | " + status + " | " + dept + extra_fmt + " — " + desc.str.slice(0, 70)).tolist()
    ids = df["id"].astype(str).tolist()
    return labels, ids


@st.cache_data(ttl=300)
def _build_fornecedor_options(stamp: tuple, df_fornecedores: pd.DataFrame) -> tuple[list[str], dict[int, str]]:
    """Opções de fornecedor e mapa cod->id."""
    if df_fornecedores is None or df_fornecedores.empty:
        return [""], {}
    df = df_fornecedores.copy()
    df["cod_fornecedor"] = pd.to_numeric(df["cod_fornecedor"], errors="coerce").fillna(0).astype(int)
    df["nome"] = df.get("nome", "").fillna("").astype(str)

    options = [""] + (df["cod_fornecedor"].astype(str) + " - " + df["nome"]).tolist()
    mapa = {
        int(row["cod_fornecedor"]): str(row["id"])
        for _, row in df.iterrows()
        if int(row["cod_fornecedor"]) != 0
    }
    return options, mapa


def _download_df(df: pd.DataFrame, nome: str) -> None:
    """Botão de download CSV do dataframe."""
    if df is None or df.empty:
        return
    csv_bytes = df.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "⬇️ Baixar CSV",
        data=csv_bytes,
        file_name=nome,
        mime="text/csv",
        use_container_width=True,
    )


# -------------------------------
# Auditoria / Histórico (safety)
# -------------------------------
def _safe_insert_historico(_supabase, payload: dict) -> None:
    """Insere no historico_pedidos sem quebrar caso a tabela/colunas não existam."""
    if not payload:
        return

    # tentativa 1: payload completo
    try:
        _supabase.table("historico_pedidos").insert(payload).execute()
        return
    except Exception:
        pass

    # tentativa 2: payload mínimo (colunas mais prováveis)
    try:
        minimo = {
            "pedido_id": payload.get("pedido_id"),
            "tenant_id": payload.get("tenant_id"),
            "usuario_id": payload.get("usuario_id"),
            "campo": payload.get("campo"),
            "valor_anterior": payload.get("valor_anterior"),
            "valor_novo": payload.get("valor_novo"),
        }
        _supabase.table("historico_pedidos").insert(minimo).execute()
    except Exception:
        # se não existir tabela, só ignora
        return

DEPARTAMENTOS_VALIDOS = [
    "Estoque", "Caminhões", "Oficina Geral", "Borracharia",
    "Máquinas pesadas", "Veic. Leves", "Tratores", "Colhedoras",
    "Irrigação", "Reboques", "Carregadeiras"
]
STATUS_VALIDOS = ["Sem OC", "Tem OC", "Em Transporte", "Entregue"]


def _coerce_date(x):
    """Converte valor para YYYY-MM-DD ou None."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    dt = pd.to_datetime(x, errors="coerce")
    if pd.isna(dt):
        return None
    return dt.strftime("%Y-%m-%d")


def _coerce_float(x):
    """Converte números vindo de CSV/Excel (aceita vírgula) para float ou None."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        if isinstance(x, str):
            xs = x.strip().replace(".", "").replace(",", ".")  # PT-BR -> float
            if xs == "":
                return None
            return float(xs)
        return float(x)
    except Exception:
        return None


def _calc_valor_total_row(row: pd.Series) -> float:
    """Obtém valor_total informado no arquivo (normalizado).

    Observação: como o arquivo já traz o valor_total final, não recalculamos
    qtde * preço aqui. (Para materiais novos ou negociações, o valor_total do
    arquivo é a fonte de verdade.)
    """
    vt = _coerce_float(row.get("valor_total"))
    return float(vt or 0.0)


def _float_eq(a, b, tol: float = 0.005) -> bool:
    """Comparação de floats com tolerância (evita ruído de centavos por arredondamento)."""
    try:
        if a is None and b is None:
            return True
        if a is None:
            a = 0.0
        if b is None:
            b = 0.0
        return abs(float(a) - float(b)) <= float(tol)
    except Exception:
        return False


def _prever_qtd_valor_atualiza(_supabase, df: pd.DataFrame, tenant_id: str) -> int:
    """Conta quantos registros (que serão UPDATE por OC/SOL) terão mudança real em valor_total."""
    if df is None or df.empty or not tenant_id:
        return 0

    # Coleta chaves do arquivo
    ocs: list[str] = []
    sols: list[str] = []

    if "nr_oc" in df.columns:
        ocs_series = df["nr_oc"].fillna("").astype(str).str.strip()
        ocs = [x for x in ocs_series.tolist() if x]

    if "nr_solicitacao" in df.columns:
        mask_sem_oc = df.get("nr_oc", "").fillna("").astype(str).str.strip().eq("")
        sols_series = df.loc[mask_sem_oc, "nr_solicitacao"].fillna("").astype(str).str.strip()
        sols = [x for x in sols_series.tolist() if x]

    # Prefetch banco
    oc_map: dict[str, float] = {}          # OC -> valor_total
    sol_map: dict[str, float] = {}         # SOL (sem OC no banco) -> valor_total
    sol_com_oc: set[str] = set()           # SOL que já tem OC no banco (não deve sobrescrever)

    if ocs:
        try:
            res = (
                _supabase.table("pedidos")
                .select("nr_oc,valor_total")
                .eq("tenant_id", tenant_id)
                .in_("nr_oc", ocs)
                .execute()
            )
            for r in (res.data or []):
                k = str(r.get("nr_oc") or "").strip()
                if k:
                    oc_map[k] = float(r.get("valor_total") or 0)
        except Exception:
            pass

    if sols:
        try:
            res = (
                _supabase.table("pedidos")
                .select("nr_solicitacao,nr_oc,valor_total")
                .eq("tenant_id", tenant_id)
                .in_("nr_solicitacao", sols)
                .execute()
            )
            for r in (res.data or []):
                sol = str(r.get("nr_solicitacao") or "").strip()
                oc = str(r.get("nr_oc") or "").strip()
                if not sol:
                    continue
                if oc:
                    sol_com_oc.add(sol)
                else:
                    sol_map[sol] = float(r.get("valor_total") or 0)
        except Exception:
            pass

    count = 0
    for _, row in df.iterrows():
        nr_oc = str(row.get("nr_oc") or "").strip()
        nr_sol = str(row.get("nr_solicitacao") or "").strip()

        old_val = None
        if nr_oc and nr_oc in oc_map:
            old_val = oc_map[nr_oc]
        elif (not nr_oc) and nr_sol and (nr_sol not in sol_com_oc) and (nr_sol in sol_map):
            old_val = sol_map[nr_sol]
        else:
            continue  # não é update (ou é pulado)

        new_val = _calc_valor_total_row(row)
        if not _float_eq(new_val, old_val):
            count += 1

    return int(count)


def _validate_upload_df(df_upload: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df_upload is None or df_upload.empty:
        return df_upload, pd.DataFrame([{"linha": "-", "erro": "Arquivo vazio"}])

    df = df_upload.copy()

    # Normalizações básicas
    for c in ["descricao", "departamento", "status", "nr_oc", "nr_solicitacao", "cod_equipamento", "cod_material"]:
        if c in df.columns:
            df[c] = df[c].astype(str).where(df[c].notna(), None)
            df[c] = df[c].apply(lambda v: v.strip() if isinstance(v, str) else v)

    # Coerções numéricas
    if "qtde_solicitada" in df.columns:
        df["qtde_solicitada"] = pd.to_numeric(df["qtde_solicitada"], errors="coerce")
    if "qtde_entregue" in df.columns:
        df["qtde_entregue"] = pd.to_numeric(df["qtde_entregue"], errors="coerce").fillna(0)
    else:
        df["qtde_entregue"] = 0

    if "valor_total" in df.columns:
        df["valor_total"] = pd.to_numeric(df["valor_total"], errors="coerce").fillna(0)
    else:
        df["valor_total"] = 0

    # Preços auxiliares (opcionais) para cálculo automático do valor_total
    # (aceita PT-BR com vírgula e também valores já numéricos)
    for c in ["valor_unitario", "valor_ultima_compra", "valor_ultima"]:
        if c in df.columns:
            df[c] = df[c].apply(_coerce_float)

    # Datas (podem vir vazias)
    for c in ["data_solicitacao", "data_oc", "previsao_entrega"]:
        if c in df.columns:
            df[c] = df[c].apply(_coerce_date)
        else:
            df[c] = None

    # Fornecedor
    if "cod_fornecedor" in df.columns:
        df["cod_fornecedor"] = pd.to_numeric(df["cod_fornecedor"], errors="coerce")
    else:
        df["cod_fornecedor"] = None

    erros = []
    for i, r in df.iterrows():
        linha = int(i) + 2  # +2 = header + 1-index excel/csv

        # obrigatórios
        if "descricao" not in df.columns or r.get("descricao") is None or str(r.get("descricao")).strip() == "":
            erros.append({"linha": linha, "erro": "Descrição vazia"})
        if pd.isna(r.get("qtde_solicitada")) or float(r.get("qtde_solicitada") or 0) <= 0:
            erros.append({"linha": linha, "erro": "Quantidade solicitada inválida"})

        # domínio
        dept = r.get("departamento")
# Não bloqueia mais por lista fixa — se o departamento não existir no BD,
        # ele será criado automaticamente durante a importação.
        if dept:
            df.at[i, "departamento"] = str(dept).strip()
        stt = r.get("status")
        if stt and stt not in STATUS_VALIDOS:
            erros.append({"linha": linha, "erro": f"Status inválido: {stt}"})

        # datas inválidas: se coluna tinha valor mas virou None após coerção
        for dc in ["data_solicitacao", "data_oc", "previsao_entrega"]:
            if dc in df_upload.columns:
                raw = df_upload.iloc[i].get(dc)

                # considera vazio se for None, NaN, NaT, string vazia
                vazio = (
                    raw is None
                    or (isinstance(raw, float) and pd.isna(raw))
                    or (isinstance(raw, pd.Timestamp) and pd.isna(raw))
                    or (str(raw).strip().lower() in ["", "nat", "none", "nan"])
                )

                if (not vazio) and (r.get(dc) is None):
                    erros.append({"linha": linha, "erro": f"Data inválida em {dc}: {raw}"})

        # fornecedor: se informado, precisa ser int
        if "cod_fornecedor" in df.columns and pd.notna(r.get("cod_fornecedor")):
            try:
                int(r.get("cod_fornecedor"))
            except Exception:
                erros.append({"linha": linha, "erro": f"cod_fornecedor inválido: {r.get('cod_fornecedor')}"})
    

    df_erros = pd.DataFrame(erros) if erros else pd.DataFrame(columns=["linha", "erro"])
    return df, df_erros


@st.cache_data(ttl=600)
def _table_supports_column(_supabase, table: str, col: str) -> bool:
    """Detecta se uma coluna existe (best-effort) consultando 1 linha."""
    try:
        _supabase.table(table).select(col).limit(1).execute()
        return True
    except Exception:
        return False


def _get_or_create_departamento_id(_supabase, tenant_id: str, nome: str) -> str | None:
    """Busca ou cria departamento e retorna o ID (best-effort)."""
    nome = (nome or "").strip()
    if not nome:
        return None

    # 1) busca
    try:
        r = (
            _supabase.table("departamentos")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("nome", nome)
            .limit(1)
            .execute()
        )
        if r.data:
            return str(r.data[0]["id"])
    except Exception:
        # se a tabela não existir ou RLS bloquear, não quebra a importação
        return None

    # 2) cria
    try:
        payload = {"tenant_id": tenant_id, "nome": nome, "ativo": True}
        ins = _supabase.table("departamentos").insert(payload).execute()
        if ins.data:
            return str(ins.data[0]["id"])
        return None
    except Exception:
        # Pode ter criado em paralelo (duplicidade). Tenta buscar novamente.
        try:
            r2 = (
                _supabase.table("departamentos")
                .select("id")
                .eq("tenant_id", tenant_id)
                .eq("nome", nome)
                .limit(1)
                .execute()
            )
            if r2.data:
                return str(r2.data[0]["id"])
        except Exception:
            pass
        return None



def _resolve_import_plan(_supabase, df: pd.DataFrame, tenant_id: str | None = None) -> tuple[int, int, int]:
    """
    Plano de importação unificado (UPSERT):
    - Se encontrar pelo nr_oc (preferencial) => update
    - Se não tiver nr_oc, tenta nr_solicitacao (somente quando no banco também não tem OC) => update
    - Caso contrário => insert
    Retorna (insere, atualiza, pula)
    """
    if df is None or df.empty:
        return 0, 0, 0

    _tid = str(tenant_id) if tenant_id else None

    # Prefetch OCs
    oc_to_id: dict[str, str] = {}
    if "nr_oc" in df.columns:
        ocs = df["nr_oc"].dropna().astype(str).str.strip()
        ocs = [x for x in ocs.tolist() if x]
        if ocs:
            try:
                q = _supabase.table("pedidos").select("id,nr_oc").in_("nr_oc", ocs)
                if _tid:
                    q = q.eq("tenant_id", _tid)
                res = q.execute()
                for r in (res.data or []):
                    nr = str(r.get("nr_oc") or "").strip()
                    if nr:
                        oc_to_id[nr] = str(r.get("id"))
            except Exception:
                oc_to_id = {}

    # Prefetch solicitações (somente linhas sem OC no arquivo)
    sol_to_id_sem_oc: dict[str, str] = {}
    sol_com_oc: set[str] = set()
    if "nr_solicitacao" in df.columns:
        mask_sem_oc = df.get("nr_oc", "").fillna("").astype(str).str.strip().eq("")
        sols = df.loc[mask_sem_oc, "nr_solicitacao"].dropna().astype(str).str.strip()
        sols = [x for x in sols.tolist() if x]
        if sols:
            try:
                q = _supabase.table("pedidos").select("id,nr_solicitacao,nr_oc").in_("nr_solicitacao", sols)
                if _tid:
                    q = q.eq("tenant_id", _tid)
                res = q.execute()
                for r in (res.data or []):
                    sol = str(r.get("nr_solicitacao") or "").strip()
                    oc = str(r.get("nr_oc") or "").strip()
                    if not sol:
                        continue
                    if oc:
                        sol_com_oc.add(sol)
                    else:
                        sol_to_id_sem_oc[sol] = str(r.get("id"))
            except Exception:
                sol_to_id_sem_oc = {}
                sol_com_oc = set()

    insere = atualiza = pula = 0
    for _, r in df.iterrows():
        nr_oc = str(r.get("nr_oc") or "").strip()
        nr_sol = str(r.get("nr_solicitacao") or "").strip()

        if nr_oc:
            if nr_oc in oc_to_id:
                atualiza += 1
            else:
                insere += 1
            continue

        if nr_sol:
            if nr_sol in sol_com_oc:
                pula += 1
            elif nr_sol in sol_to_id_sem_oc:
                atualiza += 1
            else:
                insere += 1
        else:
            pula += 1

    return insere, atualiza, pula
def _bulk_update(_supabase, ids: list[str], payload: dict) -> tuple[int, list[str]]:
    """
    Tenta atualizar em lote; se não suportar, faz loop.
    Retorna (qtd_ok, erros)
    """
    if not ids:
        return 0, []

    erros = []
    ok = 0

    # tenta batch com in_
    try:
        _supabase.table("pedidos").update(payload).in_("id", ids).execute()
        return len(ids), []
    except Exception:
        pass

    # fallback: update um a um
    for pid in ids:
        try:
            _supabase.table("pedidos").update(payload).eq("id", pid).execute()
            ok += 1
        except Exception as e:
            erros.append(f"{pid}: {e}")
    return ok, erros


def exibir_gestao_pedidos(_supabase):
    """Exibe página de gestão (criar/editar) pedidos - Apenas Admin"""

    if st.session_state.usuario["perfil"] != "admin":
        st.error("⛔ Acesso negado. Apenas administradores podem gerenciar pedidos.")
        return

    apply_theme()
    section_header(
        "Gestão de Pedidos",
        hint="Crie e edite pedidos.",
        pill=f"Tenant: {st.session_state.get('tenant_id')}" if st.session_state.get('tenant_id') else None,
        accent=True,
    )

    tab1, tab2, tab3 = st.tabs(["Novo pedido", "Editar pedido", "Ações em massa"])

    # ============================================
    # TAB 1: NOVO PEDIDO
    # ============================================
    with tab1:
        st.subheader("Cadastrar Novo Pedido")

        df_fornecedores = carregar_fornecedores(_supabase, st.session_state.get("tenant_id"))

        with st.form("form_novo_pedido"):
            col1, col2 = st.columns(2)

            with col1:
                nr_solicitacao = st.text_input("N° Solicitação")
                nr_oc = st.text_input("N° Ordem de Compra")
                departamento = st.selectbox(
                    "Departamento",
                    [
                        "Estoque",
                        "Caminhões",
                        "Oficina Geral",
                        "Borracharia",
                        "Máquinas pesadas",
                        "Veic. Leves",
                        "Tratores",
                        "Colhedoras",
                        "Irrigação",
                        "Reboques",
                        "Carregadeiras",
                    ],
                )
                cod_equipamento = st.text_input("Código Equipamento")
                cod_material = st.text_input("Código Material")

            with col2:
                descricao = st.text_area("Descrição do Material", height=100)
                qtde_solicitada = st.number_input("Quantidade Solicitada", min_value=0.0, step=1.0)

                if not df_fornecedores.empty:
                    stamp_f = _make_df_stamp(
                        df_fornecedores,
                        "updated_at" if "updated_at" in df_fornecedores.columns else "id",
                    )
                    forn_opts, _ = _build_fornecedor_options(stamp_f, df_fornecedores)
                    fornecedor_selecionado = st.selectbox("Fornecedor", forn_opts)
                else:
                    st.warning("⚠️ Nenhum fornecedor cadastrado")
                    fornecedor_selecionado = ""

            col3, col4 = st.columns(2)

            with col3:
                data_solicitacao = st.date_input("Data Solicitação", value=datetime.now())
                data_oc = st.date_input("Data OC")
                previsao_entrega = st.date_input("Previsão de Entrega")

            with col4:
                status = st.selectbox("Status", ["Sem OC", "Tem OC", "Em Transporte", "Entregue"])
                valor_total = st.number_input("Valor Total (R$)", min_value=0.0, step=0.01)
                observacoes = st.text_area("Observações")

            submitted = st.form_submit_button("💾 Salvar Pedido", use_container_width=True)

            if submitted:
                if not descricao:
                    st.error("⚠️ Descrição é obrigatória")
                elif qtde_solicitada <= 0:
                    st.error("⚠️ Quantidade deve ser maior que zero")
                else:
                    fornecedor_id = None
                    if fornecedor_selecionado and not df_fornecedores.empty:
                        try:
                            cod_forn = int(fornecedor_selecionado.split(" - ")[0])
                            fornecedor_id = (
                                df_fornecedores[df_fornecedores["cod_fornecedor"] == cod_forn]["id"].values[0]
                            )
                        except Exception:
                            fornecedor_id = None

                    pedido_data = {
                        "nr_solicitacao": nr_solicitacao or None,
                        "nr_oc": nr_oc or None,
                        "departamento": departamento,
                        "cod_equipamento": cod_equipamento or None,
                        "cod_material": cod_material or None,
                        "descricao": descricao,
                        "qtde_solicitada": qtde_solicitada,
                        "qtde_entregue": 0,
                        "data_solicitacao": data_solicitacao.isoformat(),
                        "data_oc": data_oc.isoformat() if data_oc else None,
                        "previsao_entrega": previsao_entrega.isoformat() if previsao_entrega else None,
                        "status": status,
                        "valor_total": valor_total,
                        "fornecedor_id": fornecedor_id,
                        "observacoes": observacoes or None,
                    }

                    sucesso, mensagem = salvar_pedido(pedido_data, _supabase)
                    if sucesso:
                        try:
                            ba.registrar_acao(
                                _supabase,
                                st.session_state.usuario.get("email"),
                                "criar_pedido",
                                {"nr_oc": nr_oc, "descricao": (descricao or "")[:120]},
                            )
                        except Exception:
                            pass
                        
                        # --------------------------------------------
                        # 📜 Histórico de criação (best-effort)
                        # --------------------------------------------
                        try:
                            _tid = st.session_state.get("tenant_id")
                            _tid = str(_tid) if _tid else None

                            pid = None
                            # tenta achar por OC, senão por Solicitação (dentro do tenant)
                            if _tid:
                                if str(nr_oc or "").strip():
                                    r = (
                                        _supabase.table("pedidos")
                                        .select("id")
                                        .eq("tenant_id", _tid)
                                        .eq("nr_oc", str(nr_oc).strip())
                                        .order("criado_em", desc=True)
                                        .limit(1)
                                        .execute()
                                    )
                                    if r.data:
                                        pid = str(r.data[0].get("id"))
                                elif str(nr_solicitacao or "").strip():
                                    r = (
                                        _supabase.table("pedidos")
                                        .select("id")
                                        .eq("tenant_id", _tid)
                                        .eq("nr_solicitacao", str(nr_solicitacao).strip())
                                        .order("criado_em", desc=True)
                                        .limit(1)
                                        .execute()
                                    )
                                    if r.data:
                                        pid = str(r.data[0].get("id"))

                            if pid:
                                _safe_insert_historico(
                                    _supabase,
                                    {
                                        "pedido_id": pid,
                                        "tenant_id": _tid,
                                        "usuario_id": st.session_state.usuario.get("id"),
                                        "usuario_email": st.session_state.usuario.get("email"),
                                        "acao": "criar",
                                        "campo": "__pedido__",
                                        "valor_anterior": "",
                                        "valor_novo": "criado",
                                        "motivo": None,
                                    },
                                )
                        except Exception:
                            pass

                        st.success(mensagem)
                        st.rerun()
                    else:
                        st.error(mensagem)

    # ============================================
    # TAB 2: EDITAR PEDIDO
    # ============================================

    
    # ============================================
    # TAB 2: EDITAR PEDIDO
    # ============================================
    with tab2:
        st.subheader("📝 Editar Pedido")

        tenant_id = st.session_state.get("tenant_id")
        df_pedidos = carregar_pedidos(_supabase, tenant_id)

        # Ponte vinda da Consulta: pré-seleciona pedido para edição
        pedido_pre = st.session_state.pop("gp_open_pedido_id", None)
        if pedido_pre and not df_pedidos.empty and "id" in df_pedidos.columns:
            try:
                alvo = df_pedidos[df_pedidos["id"].astype(str) == str(pedido_pre)]
                if not alvo.empty:
                    st.session_state["edit_busca"] = str(
                        alvo.iloc[0].get("nr_oc") or alvo.iloc[0].get("nr_solicitacao") or ""
                    )
            except Exception:
                pass

        if df_pedidos.empty:
            st.info("📭 Nenhum pedido cadastrado ainda")
            return

        # --------------------------------------------
        # Busca e filtros (para localizar rápido)
        # --------------------------------------------
        with st.form("filtro_edicao"):
            colf1, colf2, colf3 = st.columns([2, 1, 1])
            with colf1:
                busca_txt = st.text_input(
                    "Buscar (OC, Solicitação, descrição, depto)",
                    value=st.session_state.get("edit_busca", ""),
                )
            with colf2:
                status_f = st.selectbox(
                    "Status",
                    ["Todos"] + STATUS_VALIDOS,
                    index=0,
                )
            with colf3:
                limite = st.selectbox("Itens", [100, 200, 500], index=1)

            aplicar_busca = st.form_submit_button("Aplicar")

        if aplicar_busca:
            st.session_state["edit_busca"] = busca_txt

        df_lista = df_pedidos.copy()

        if status_f != "Todos" and "status" in df_lista.columns:
            df_lista = df_lista[df_lista["status"] == status_f]

        q = str(st.session_state.get("edit_busca", "")).strip().lower()
        if q:
            cols = []
            for c in ["nr_oc", "nr_solicitacao", "descricao", "departamento", "cod_equipamento", "cod_material"]:
                if c in df_lista.columns:
                    cols.append(df_lista[c].fillna("").astype(str).str.lower())
            if cols:
                mask = cols[0].str.contains(q, na=False)
                for s in cols[1:]:
                    mask = mask | s.str.contains(q, na=False)
                df_lista = df_lista[mask]

        df_lista = df_lista.head(int(limite))
        labels, ids = _build_pedido_labels(_make_df_stamp(df_lista), df_lista)

        if not ids:
            st.warning("Nenhum pedido encontrado com os filtros atuais.")
            return

        idx_escolhido = st.selectbox(
            "Selecione o pedido para editar",
            options=list(range(len(ids))),
            format_func=lambda i: labels[i] if i < len(labels) else "",
        )
        pedido_editar = ids[idx_escolhido]
        pedido_atual = df_pedidos[df_pedidos["id"].astype(str) == str(pedido_editar)].iloc[0].to_dict()

        # Helpers de datas
        def _to_date(v):
            try:
                dt = pd.to_datetime(v, errors="coerce")
                if pd.isna(dt):
                    return None
                return dt.date()
            except Exception:
                return None

        st.markdown("---")

        # --------------------------------------------
        # Carrega fornecedores p/ select
        # --------------------------------------------
        df_fornecedores = carregar_fornecedores(_supabase, tenant_id)
        fornecedor_options = [""]
        fornecedor_mapa_cod_to_id = {}
        fornecedor_id_to_label = {}

        if df_fornecedores is not None and not df_fornecedores.empty:
            stamp_f = _make_df_stamp(
                df_fornecedores,
                "updated_at" if "updated_at" in df_fornecedores.columns else "id",
            )
            fornecedor_options, fornecedor_mapa_cod_to_id = _build_fornecedor_options(stamp_f, df_fornecedores)

            try:
                df_tmp = df_fornecedores.copy()
                df_tmp["cod_fornecedor"] = pd.to_numeric(df_tmp["cod_fornecedor"], errors="coerce").fillna(0).astype(int)
                df_tmp["nome"] = df_tmp.get("nome", "").fillna("").astype(str)
                for _, r in df_tmp.iterrows():
                    fid = str(r.get("id"))
                    cod = int(r.get("cod_fornecedor") or 0)
                    nm = str(r.get("nome") or "").strip()
                    if fid and cod:
                        fornecedor_id_to_label[fid] = f"{cod} - {nm}"
            except Exception:
                fornecedor_id_to_label = {}

        # valor inicial do fornecedor no select
        forn_label_default = ""
        forn_id_atual = str(pedido_atual.get("fornecedor_id") or "")
        if forn_id_atual and forn_id_atual in fornecedor_id_to_label:
            forn_label_default = fornecedor_id_to_label[forn_id_atual]

        # --------------------------------------------
        # Regras de bloqueio por status
        # --------------------------------------------
        status_atual = str(pedido_atual.get("status") or "")
        bloqueado = (status_atual == "Entregue")
        st.caption("💡 Dica: use a busca acima para localizar rápido por OC/descrição/equipamento.")
        if bloqueado:
            st.info("🔒 Este pedido está **Entregue**. Por padrão, a edição é bloqueada para evitar inconsistências.")

        override_edicao = False
        if bloqueado:
            override_edicao = st.checkbox(
                "Sou admin e quero liberar edição mesmo assim (não recomendado)",
                value=False,
            )

        desabilitar = bloqueado and not override_edicao

        # --------------------------------------------
        # Formulário (em blocos)
        # --------------------------------------------
        with st.form("form_editar_pedido_v2"):
            st.markdown("### 📌 Identificação")
            c1, c2, c3 = st.columns([1, 1, 1])
            with c1:
                nr_solicitacao = st.text_input(
                    "Nº Solicitação",
                    value=str(pedido_atual.get("nr_solicitacao") or ""),
                    disabled=desabilitar,
                )
            with c2:
                nr_oc = st.text_input(
                    "Nº OC",
                    value=str(pedido_atual.get("nr_oc") or ""),
                    disabled=desabilitar,
                )
            with c3:
                departamento = st.selectbox(
                    "Departamento",
                    options=DEPARTAMENTOS_VALIDOS,
                    index=DEPARTAMENTOS_VALIDOS.index(pedido_atual.get("departamento"))
                    if pedido_atual.get("departamento") in DEPARTAMENTOS_VALIDOS
                    else 0,
                    disabled=desabilitar,
                )

            st.markdown("### 📦 Material")
            m1, m2 = st.columns([1, 1])
            with m1:
                cod_material = st.text_input(
                    "Código Material",
                    value=str(pedido_atual.get("cod_material") or ""),
                    disabled=desabilitar,
                )
                cod_equipamento = st.text_input(
                    "Código Equipamento",
                    value=str(pedido_atual.get("cod_equipamento") or ""),
                    disabled=desabilitar,
                )
            with m2:
                descricao = st.text_area(
                    "Descrição do Material",
                    value=str(pedido_atual.get("descricao") or ""),
                    height=120,
                    disabled=desabilitar,
                )

            st.markdown("### 🏭 Fornecedor")
            if df_fornecedores is None or df_fornecedores.empty:
                st.warning("⚠️ Nenhum fornecedor cadastrado.")
                fornecedor_sel = ""
            else:
                try:
                    idx_f = fornecedor_options.index(forn_label_default) if forn_label_default in fornecedor_options else 0
                except Exception:
                    idx_f = 0

                fornecedor_sel = st.selectbox(
                    "Fornecedor",
                    options=fornecedor_options,
                    index=idx_f,
                    disabled=desabilitar,
                )

            st.markdown("### 📅 Datas")
            d1, d2, d3 = st.columns(3)
            with d1:
                data_solicitacao = st.date_input(
                    "Data Solicitação",
                    value=_to_date(pedido_atual.get("data_solicitacao")) or datetime.now().date(),
                    disabled=desabilitar,
                )
            with d2:
                data_oc = st.date_input(
                    "Data OC",
                    value=_to_date(pedido_atual.get("data_oc")) or datetime.now().date(),
                    disabled=desabilitar,
                )
            with d3:
                previsao_entrega = st.date_input(
                    "Previsão de Entrega",
                    value=_to_date(pedido_atual.get("previsao_entrega")) or datetime.now().date(),
                    disabled=desabilitar,
                )

            st.markdown("### 📦 Quantidades e status")
            q1, q2, q3, q4 = st.columns([1, 1, 1, 1])
            with q1:
                qtde_solicitada = st.number_input(
                    "Qtd. Solicitada",
                    value=float(pedido_atual.get("qtde_solicitada") or 0),
                    min_value=0.0,
                    step=1.0,
                    disabled=desabilitar,
                )
            with q2:
                qtde_entregue = st.number_input(
                    "Qtd. Entregue",
                    value=float(pedido_atual.get("qtde_entregue") or 0),
                    min_value=0.0,
                    step=1.0,
                    disabled=desabilitar,
                )
            with q3:
                status = st.selectbox(
                    "Status",
                    options=STATUS_VALIDOS,
                    index=STATUS_VALIDOS.index(status_atual) if status_atual in STATUS_VALIDOS else 0,
                    disabled=desabilitar,
                )
            with q4:
                valor_total = st.number_input(
                    "Valor Total (R$)",
                    value=float(pedido_atual.get("valor_total") or 0),
                    min_value=0.0,
                    step=0.01,
                    disabled=desabilitar,
                )

            st.markdown("### 📝 Observações")
            observacoes = st.text_area(
                "Observações",
                value=str(pedido_atual.get("observacoes") or ""),
                height=90,
                disabled=desabilitar,
            )

            motivo_alteracao = st.text_input(
                "Motivo da alteração (opcional)",
                value="",
                disabled=desabilitar,
                help="Opcional, mas recomendado para auditoria (ex.: 'correção OC', 'ajuste quantidade', 'material trocado').",
            )

            submitted_edit = st.form_submit_button("💾 Salvar Alterações", use_container_width=True, disabled=desabilitar)

        # --------------------------------------------
        # Salvar
        # --------------------------------------------
        if submitted_edit:
            # validações mínimas
            if not descricao.strip():
                st.error("⚠️ A descrição do material é obrigatória.")
                st.stop()
            if qtde_solicitada <= 0:
                st.error("⚠️ A quantidade solicitada deve ser maior que zero.")
                st.stop()

            # ------------------------------
            # 🔒 Validações estruturais (regras de negócio)
            # ------------------------------
            try:
                qe_antiga = float(pedido_atual.get("qtde_entregue") or 0)
            except Exception:
                qe_antiga = 0.0

            if float(qtde_entregue) > float(qtde_solicitada):
                st.error("❌ Quantidade entregue não pode ser maior que a solicitada.")
                st.stop()

            if float(qtde_solicitada) < float(qe_antiga):
                st.error(
                    f"❌ Não é permitido reduzir a quantidade solicitada abaixo da já entregue ({qe_antiga:g})."
                )
                st.stop()

            # Status coerente com OC
            if status == "Sem OC" and str(nr_oc or "").strip():
                st.error("❌ Status 'Sem OC' não pode ter número de OC preenchido.")
                st.stop()

            if status == "Tem OC" and not str(nr_oc or "").strip():
                st.error("❌ Status 'Tem OC' exige número de OC.")
                st.stop()

            # Status coerente com entrega
            pendente_calc = float(qtde_solicitada) - float(qtde_entregue)
            if status == "Entregue" and pendente_calc > 0:
                st.error("❌ Não é possível marcar como Entregue se ainda há quantidade pendente.")
                st.stop()


            # valida OC duplicada (dentro do mesmo tenant)
            nr_oc_new = str(nr_oc or "").strip()
            nr_oc_old = str(pedido_atual.get("nr_oc") or "").strip()
            if nr_oc_new and nr_oc_new != nr_oc_old and "nr_oc" in df_pedidos.columns:
                dup = df_pedidos[
                    (df_pedidos["nr_oc"].fillna("").astype(str).str.strip() == nr_oc_new)
                    & (df_pedidos["id"].astype(str) != str(pedido_editar))
                ]
                if not dup.empty:
                    st.error(f"❌ Já existe um pedido com a OC **{nr_oc_new}** nesta empresa.")
                    st.stop()

            # resolve fornecedor_id
            fornecedor_id = None
            if fornecedor_sel:
                try:
                    cod = int(str(fornecedor_sel).split(" - ")[0])
                    fornecedor_id = fornecedor_mapa_cod_to_id.get(cod)
                except Exception:
                    fornecedor_id = None

            pedido_atualizado = {
                "id": pedido_editar,
                "nr_solicitacao": nr_solicitacao.strip() or None,
                "nr_oc": nr_oc_new or None,
                "departamento": departamento,
                "cod_material": cod_material.strip() or None,
                "cod_equipamento": cod_equipamento.strip() or None,
                "descricao": descricao.strip(),
                "qtde_solicitada": float(qtde_solicitada),
                "qtde_entregue": float(qtde_entregue),
                "status": status,
                "valor_total": float(valor_total),
                "fornecedor_id": fornecedor_id,
                "data_solicitacao": data_solicitacao.isoformat() if data_solicitacao else None,
                "data_oc": data_oc.isoformat() if data_oc else None,
                "previsao_entrega": previsao_entrega.isoformat() if previsao_entrega else None,
                "observacoes": observacoes.strip() or None,
            }

            # Auto-regra: se quantidade entregue >= solicitada, considerar como Entregue e registrar data_entrega
            try:
                qs = float(pedido_atualizado.get('qtde_solicitada') or 0)
                qe = float(pedido_atualizado.get('qtde_entregue') or 0)
            except Exception:
                qs, qe = 0.0, 0.0

            if qs > 0 and qe >= qs:
                pedido_atualizado['status'] = 'Entregue'
                # registra data_entrega se ainda não existir
                if not (pedido_atual.get('data_entrega') or pedido_atualizado.get('data_entrega')):
                    pedido_atualizado['data_entrega'] = datetime.now().date().isoformat()



            sucesso, mensagem = salvar_pedido(pedido_atualizado, _supabase)
            if sucesso:
                try:
                    ba.registrar_acao(
                        _supabase,
                        st.session_state.usuario.get("email"),
                        "editar_pedido",
                        {"id": pedido_editar, "nr_oc": nr_oc_new, "status": status},
                    )
                except Exception:
                    pass
                
                # --------------------------------------------
                # 📜 Histórico campo-a-campo (audit trail)
                # --------------------------------------------
                try:
                    campos_auditaveis = [
                        "nr_solicitacao",
                        "nr_oc",
                        "departamento",
                        "cod_material",
                        "cod_equipamento",
                        "descricao",
                        "qtde_solicitada",
                        "qtde_entregue",
                        "status",
                        "valor_total",
                        "fornecedor_id",
                        "data_solicitacao",
                        "data_oc",
                        "previsao_entrega",
                        "data_entrega",
                        "observacoes",
                    ]

                    for campo in campos_auditaveis:
                        ant = pedido_atual.get(campo)
                        novo = pedido_atualizado.get(campo)

                        # normaliza para string para comparação estável
                        ant_s = "" if ant is None else str(ant)
                        novo_s = "" if novo is None else str(novo)

                        if ant_s != novo_s:
                            payload = {
                                "pedido_id": pedido_editar,
                                "tenant_id": tenant_id,
                                "usuario_id": st.session_state.usuario.get("id"),
                                "usuario_email": st.session_state.usuario.get("email"),
                                "acao": "editar",
                                "campo": campo,
                                "valor_anterior": ant_s,
                                "valor_novo": novo_s,
                                "motivo": (motivo_alteracao or "").strip() or None,
                            }
                            _safe_insert_historico(_supabase, payload)
                except Exception:
                    pass

                st.success(mensagem)
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(mensagem)

        # --------------------------------------------
        # Ações avançadas (perigosas)
        # --------------------------------------------
        with st.expander("⚠️ Ações avançadas", expanded=False):
            st.caption("Use com cuidado. Essas ações são registradas na auditoria (se habilitada).")
            colx1, colx2 = st.columns(2)
            with colx1:
                confirmar_exclusao = st.checkbox("Confirmo que quero excluir este pedido", value=False)
                motivo_exclusao = st.text_input("Motivo da exclusão (opcional)", value="")
            with colx2:
                if st.button(
                    "🗑️ Excluir Pedido",
                    type="secondary",
                    use_container_width=True,
                    disabled=not confirmar_exclusao,
                ):
                    try:
                        
                        # histórico antes de excluir (mantém rastreabilidade mesmo após delete)
                        try:
                            _safe_insert_historico(
                                _supabase,
                                {
                                    "pedido_id": pedido_editar,
                                    "tenant_id": tenant_id,
                                    "usuario_id": st.session_state.usuario.get("id"),
                                    "usuario_email": st.session_state.usuario.get("email"),
                                    "acao": "excluir",
                                    "campo": "__pedido__",
                                    "valor_anterior": "existente",
                                    "valor_novo": "excluido",
                                    "motivo": (motivo_exclusao or "").strip() or None,
                                },
                            )
                        except Exception:
                            pass

                        _supabase.table("pedidos").delete().eq("id", pedido_editar).eq("tenant_id", tenant_id).execute()
                        try:
                            ba.registrar_acao(
                                _supabase,
                                st.session_state.usuario.get("email"),
                                "excluir_pedido",
                                {"id": pedido_editar},
                            )
                        except Exception:
                            pass
                        st.success("✅ Pedido excluído.")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e_del:
                        st.error(f"❌ Erro ao excluir: {e_del}")

        
        # --------------------------------------------
        # Controle de Entregas (unificado)
        # --------------------------------------------
        st.markdown("---")
        st.subheader("📦 Controle de Entregas")

        qtde_solicitada_atual = float(pedido_atual.get("qtde_solicitada") or 0)
        qtde_entregue_atual = float(pedido_atual.get("qtde_entregue") or 0)
        qtde_pendente = max(0.0, qtde_solicitada_atual - qtde_entregue_atual)

        # Resumo + progresso
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Solicitada", f"{qtde_solicitada_atual:g}")
        r2.metric("Entregue", f"{qtde_entregue_atual:g}")
        r3.metric("Pendente", f"{qtde_pendente:g}")
        frac = 0.0
        try:
            frac = (qtde_entregue_atual / qtde_solicitada_atual) if qtde_solicitada_atual > 0 else 0.0
        except Exception:
            frac = 0.0
        r4.progress(min(1.0, max(0.0, float(frac))))

        # Sugestão automática de status (não força, mas ajuda)
        if qtde_solicitada_atual > 0 and qtde_pendente <= 0 and str(pedido_atual.get("status") or "") != "Entregue":
            st.info("ℹ️ Este pedido está 100% entregue. Você pode ajustar o status para **Entregue** na edição acima (ou registrar uma entrega extra somente se necessário).")

        # Histórico de entregas (se existir tabela)
        tenant_id = str(st.session_state.get("tenant_id") or "")
        historico_rows = []
        for tb in ["historico_pedidos", "historico", "entregas_pedidos", "entregas"]:
            try:
                qh = _supabase.table(tb).select("*").eq("pedido_id", pedido_editar)
                if tenant_id:
                    try:
                        qh = qh.eq("tenant_id", tenant_id)
                    except Exception:
                        pass
                try:
                    qh = qh.order("criado_em", desc=True)
                except Exception:
                    pass
                rh = qh.limit(50).execute()
                if rh.data:
                    historico_rows = rh.data
                    break
            except Exception:
                continue

        if historico_rows:
            with st.expander(f"🧾 Histórico de entregas ({len(historico_rows)})", expanded=False):
                try:
                    df_hist = pd.DataFrame(historico_rows)

                    # tenta normalizar nomes mais comuns
                    col_map = {}
                    if "qtde" in df_hist.columns and "qtde_entregue" not in df_hist.columns:
                        col_map["qtde"] = "qtde_entregue"
                    if "observacao" in df_hist.columns and "observacoes" not in df_hist.columns:
                        col_map["observacao"] = "observacoes"
                    if col_map:
                        df_hist = df_hist.rename(columns=col_map)

                    # escolhe colunas relevantes, se existirem
                    cols_pref = ["criado_em", "data_entrega", "qtde_entregue", "observacoes", "usuario_id"]
                    cols_show = [c for c in cols_pref if c in df_hist.columns]
                    if cols_show:
                        df_show = df_hist[cols_show].copy()
                    else:
                        df_show = df_hist.copy()

                    # formata datas
                    for c in ["criado_em", "data_entrega"]:
                        if c in df_show.columns:
                            df_show[c] = pd.to_datetime(df_show[c], errors="coerce").dt.strftime("%d/%m/%Y")
                    st.dataframe(df_show, use_container_width=True, hide_index=True, height=240)
                except Exception:
                    st.info("Histórico encontrado, mas não foi possível exibir com formatação.")

        # Registrar nova entrega
        if qtde_pendente > 0:
            with st.form("form_registrar_entrega"):
                c1, c2, c3 = st.columns([1, 1, 2])
                with c1:
                    qtde_entrega = st.number_input(
                        f"Quantidade a entregar (pendente: {qtde_pendente:g})",
                        min_value=0.0,
                        max_value=float(qtde_pendente),
                        step=1.0,
                    )
                with c2:
                    data_entrega = st.date_input("Data da entrega", value=datetime.now().date())
                with c3:
                    obs_entrega = st.text_input("Observação (opcional)")

                auto_entregue = st.checkbox(
                    "Marcar status como **Entregue** ao zerar pendência",
                    value=True,
                    help="Se esta entrega completar 100%, o status será ajustado para Entregue automaticamente.",
                )

                submitted_ent = st.form_submit_button("✅ Registrar entrega", use_container_width=True)

            if submitted_ent:
                if qtde_entrega <= 0:
                    st.warning("⚠️ Informe uma quantidade maior que zero.")
                elif qtde_entrega > qtde_pendente:
                    st.error("❌ A quantidade informada é maior que a pendente.")
                else:
                    try:
                        sucesso, mensagem = registrar_entrega(
                            pedido_editar,
                            float(qtde_entrega),
                            str(data_entrega),
                            obs_entrega,
                            _supabase=_supabase,
                        )
                        if sucesso:
                            # Ajusta status para Entregue automaticamente quando completar
                            if auto_entregue and (qtde_pendente - float(qtde_entrega) <= 0.0):
                                try:
                                    salvar_pedido({"id": pedido_editar, "status": "Entregue", "data_entrega": str(data_entrega)}, _supabase)
                                except Exception:
                                    pass

                            try:
                                ba.registrar_acao(
                                    _supabase,
                                    st.session_state.usuario.get("email"),
                                    "registrar_entrega",
                                    {"id": pedido_editar, "qtde": float(qtde_entrega), "data": str(data_entrega)},
                                )
                            except Exception:
                                pass

                            st.success(mensagem)
                            try:
                                antes = float(qtde_pendente)
                                depois = max(0.0, antes - float(qtde_entrega))
                                st.caption(f"📌 Pendente: {antes:g} → {depois:g}")
                            except Exception:
                                pass

                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(mensagem)
                    except Exception as e_ent:
                        st.error(f"❌ Erro ao registrar entrega: {e_ent}")
        else:
            st.success("✅ Pedido totalmente entregue!")

        # --------------------------------------------
        # 📜 Histórico do pedido (auditoria)
        # --------------------------------------------
        st.markdown("---")
        with st.expander("📜 Histórico do Pedido", expanded=False):
            try:
                qh = (
                    _supabase.table("historico_pedidos")
                    .select("*")
                    .eq("pedido_id", pedido_editar)
                    .eq("tenant_id", tenant_id)
                    .order("criado_em", desc=True)
                    .limit(500)
                    .execute()
                )
                rows = qh.data or []
                if not rows:
                    st.info("Nenhuma alteração registrada ainda.")
                else:
                    dfh = pd.DataFrame(rows)

                    # tenta resolver nome/email do usuário
                    if "usuario_email" not in dfh.columns:
                        dfh["usuario_email"] = None

                    if dfh["usuario_email"].isna().all() and "usuario_id" in dfh.columns:
                        try:
                            uids = [str(x) for x in dfh["usuario_id"].dropna().astype(str).unique().tolist() if x]
                            if uids:
                                # tenta 'usuarios' e depois 'users'
                                mapa = {}
                                for tb_user in ["usuarios", "users"]:
                                    try:
                                        ru = _supabase.table(tb_user).select("id,email,nome").in_("id", uids).execute()
                                        for r in (ru.data or []):
                                            uid = str(r.get("id") or "")
                                            nm = str(r.get("nome") or "").strip()
                                            em = str(r.get("email") or "").strip()
                                            mapa[uid] = (nm or em or uid)
                                        if mapa:
                                            break
                                    except Exception:
                                        continue
                                dfh["usuario"] = dfh["usuario_id"].astype(str).map(lambda x: mapa.get(str(x), str(x)))
                            else:
                                dfh["usuario"] = ""
                        except Exception:
                            dfh["usuario"] = dfh.get("usuario_id", "").astype(str)
                    else:
                        dfh["usuario"] = dfh["usuario_email"].fillna(dfh.get("usuario_id", "")).astype(str)

                    # colunas amigáveis
                    for c in ["acao", "campo", "valor_anterior", "valor_novo", "motivo", "criado_em"]:
                        if c not in dfh.columns:
                            dfh[c] = ""

                    df_show = dfh[["criado_em", "usuario", "acao", "campo", "valor_anterior", "valor_novo", "motivo"]].copy()
                    st.dataframe(df_show, use_container_width=True, hide_index=True)
            except Exception:
                st.caption("Histórico não disponível (tabela historico_pedidos não encontrada ou sem permissão).")



    with tab3:
        st.subheader("⚡ Ações em Massa")
        st.caption("Atualize vários pedidos de uma vez (status / previsão / fornecedor). Use filtros para selecionar o conjunto.")
    
        df_pedidos = carregar_pedidos(_supabase, st.session_state.get("tenant_id"))
        if df_pedidos.empty:
            st.info("📭 Nenhum pedido cadastrado.")
            return
    
        # Filtros e seleção (form para evitar rerun a cada clique)
        with st.form("form_mass_actions"):
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                depto = st.selectbox("Departamento", ["Todos"] + DEPARTAMENTOS_VALIDOS, index=0)
            with f2:
                status_atual = st.selectbox("Status atual", ["Todos"] + STATUS_VALIDOS, index=0)
            with f3:
                fornecedor_txt = st.text_input("Fornecedor contém (opcional)", value="")
            with f4:
                busca = st.text_input("Buscar (OC/descrição)", value="")
    
            lim = st.selectbox("Limite de seleção", [200, 500, 1000, 2000], index=1)
    
            aplicar = st.form_submit_button("Aplicar filtros")
    
        # aplica filtros
        df_sel = df_pedidos.copy()
    
        if depto != "Todos" and "departamento" in df_sel.columns:
            df_sel = df_sel[df_sel["departamento"] == depto]
    
        if status_atual != "Todos" and "status" in df_sel.columns:
            df_sel = df_sel[df_sel["status"] == status_atual]
    
        if fornecedor_txt.strip() and "fornecedor" in df_sel.columns:
            qf = fornecedor_txt.strip().lower()
            df_sel = df_sel[df_sel["fornecedor"].fillna("").astype(str).str.lower().str.contains(qf, na=False)]
    
        if busca.strip():
            qb = busca.strip().lower()
            cols = []
            for c in ["nr_oc", "descricao", "nr_solicitacao"]:
                if c in df_sel.columns:
                    cols.append(df_sel[c].fillna("").astype(str).str.lower())
            if cols:
                m = cols[0].str.contains(qb, na=False)
                for s in cols[1:]:
                    m = m | s.str.contains(qb, na=False)
                df_sel = df_sel[m]
    
        df_sel = df_sel.head(int(lim))
    
        st.write(f"🔎 Selecionados (após filtros): **{len(df_sel)}**")
    
        if df_sel.empty:
            st.warning("Nenhum pedido encontrado com os filtros.")
            return
    
        # multiselect por ID (mais leve)
        labels, ids = _build_pedido_labels(_make_df_stamp(df_sel), df_sel)
        id_to_label = dict(zip(ids, labels))  # evita ids.index() (O(n²))
        selecionados = st.multiselect(
            "Escolha os pedidos para aplicar a ação",
            options=ids,
            default=[],
            format_func=lambda pid: id_to_label.get(pid, pid),
        )
    
        if not selecionados:
            st.info("Selecione pelo menos 1 pedido.")
            return
    
        st.markdown("---")
        st.subheader("Ações")
    
        a1, a2, a3 = st.columns(3)
    
        # 1) Status em massa
        with a1:
            st.markdown("### 🏷️ Status")
            novo_status = st.selectbox("Novo status", STATUS_VALIDOS, index=0, key="mass_status")
            if st.button("Aplicar status", use_container_width=True):
                ok, errs = _bulk_update(_supabase, selecionados, {"status": novo_status})
                if errs:
                    st.warning(f"Atualizados: {ok}/{len(selecionados)}")
                    st.text("\n".join(errs[:30]))
                else:
                    st.success(f"✅ Status atualizado em {ok} pedidos.")
                try:
                    ba.registrar_acao(_supabase, st.session_state.usuario.get("email"), "mass_update_status",
                                      {"qtd": len(selecionados), "status": novo_status})
                except Exception:
                    pass
                st.cache_data.clear()
                st.rerun()
    
        # 2) Previsão em massa
        with a2:
            st.markdown("### 📅 Previsão")
            nova_prev = st.date_input("Nova previsão", value=datetime.now(), key="mass_prev")
            if st.button("Aplicar previsão", use_container_width=True):
                payload = {"previsao_entrega": nova_prev.isoformat()}
                ok, errs = _bulk_update(_supabase, selecionados, payload)
                if errs:
                    st.warning(f"Atualizados: {ok}/{len(selecionados)}")
                    st.text("\n".join(errs[:30]))
                else:
                    st.success(f"✅ Previsão atualizada em {ok} pedidos.")
                try:
                    ba.registrar_acao(_supabase, st.session_state.usuario.get("email"), "mass_update_previsao",
                                      {"qtd": len(selecionados), "previsao": nova_prev.isoformat()})
                except Exception:
                    pass
                st.cache_data.clear()
                st.rerun()
    
        # 3) Fornecedor em massa
        with a3:
            st.markdown("### 🏭 Fornecedor")
            df_fornecedores = carregar_fornecedores(_supabase, st.session_state.get("tenant_id"))
            if df_fornecedores is None or df_fornecedores.empty:
                st.warning("Sem fornecedores cadastrados.")
            else:
                stamp_f = _make_df_stamp(df_fornecedores, "updated_at" if "updated_at" in df_fornecedores.columns else "id")
                forn_opts, mapa = _build_fornecedor_options(stamp_f, df_fornecedores)
    
                forn_sel = st.selectbox("Fornecedor", forn_opts, index=0, key="mass_forn")
                if st.button("Aplicar fornecedor", use_container_width=True, disabled=(not forn_sel)):
                    try:
                        cod = int(str(forn_sel).split(" - ")[0])
                        forn_id = mapa.get(cod)
                        if not forn_id:
                            st.error("Fornecedor não encontrado no mapa.")
                        else:
                            ok, errs = _bulk_update(_supabase, selecionados, {"fornecedor_id": forn_id})
                            if errs:
                                st.warning(f"Atualizados: {ok}/{len(selecionados)}")
                                st.text("\n".join(errs[:30]))
                            else:
                                st.success(f"✅ Fornecedor atualizado em {ok} pedidos.")
                            try:
                                ba.registrar_acao(_supabase, st.session_state.usuario.get("email"), "mass_update_fornecedor",
                                                  {"qtd": len(selecionados), "cod_fornecedor": cod})
                            except Exception:
                                pass
                            st.cache_data.clear()
                            st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao aplicar fornecedor: {e}")

