from __future__ import annotations

import math
import io
import re
import datetime

import pandas as pd
import streamlit as st

# Repositórios (mantém compatibilidade com a estrutura do projeto)
try:
    from src.repositories.pedidos import carregar_pedidos
except Exception:  # pragma: no cover
    carregar_pedidos = None  # type: ignore

try:
    from src.repositories.pedidos import atualizar_status_pedido  # type: ignore
except Exception:  # pragma: no cover
    atualizar_status_pedido = None  # type: ignore


def _get_cached_pedidos(_supabase, tenant_id: str | None):
    """Cache leve em session_state para evitar refetch a cada rerun."""
    st.session_state.setdefault("_cache_pedidos", {})
    key = str(tenant_id or "default")
    entry = st.session_state["_cache_pedidos"].get(key)
    if entry and isinstance(entry, dict) and "df" in entry and "ts" in entry:
        # TTL 60s
        if (datetime.datetime.now().timestamp() - float(entry["ts"])) < 60:
            return entry["df"]
    df = carregar_pedidos(_supabase, tenant_id)  # type: ignore[misc]
    st.session_state["_cache_pedidos"][key] = {"df": df, "ts": datetime.datetime.now().timestamp()}
    return df

def _clear_cached_pedidos(tenant_id: str | None):
    st.session_state.setdefault("_cache_pedidos", {})
    key = str(tenant_id or "default")
    st.session_state["_cache_pedidos"].pop(key, None)




# Compat: st.popover existe só em versões mais novas do Streamlit.
# Este helper usa popover quando disponível e cai para expander quando não.
def _popover_or_expander(label: str, *, use_container_width: bool = True):
    if hasattr(st, "popover"):
        return st.popover(label, use_container_width=use_container_width)  # type: ignore[attr-defined]
    return st.expander(label, expanded=False)


def _to_str(x) -> str:
    """Converte valores para string sem 'nan/None'."""
    try:
        import pandas as pd
        if x is None or (isinstance(x, float) and pd.isna(x)) or pd.isna(x):
            return ""
    except Exception:
        if x is None:
            return ""
    return str(x)

def _badge_status(s: str) -> str:
    """Prefixa status com indicador visual (emoji)."""
    s = "" if s is None else str(s)
    s0 = s.strip().lower()

    if s0 in ["entregue", "entregues", "finalizado", "concluído", "concluido", "encerrado"]:
        return f"🟢 {s}"
    if s0 in ["tem oc", "com oc"]:
        return f"🟢 {s}"
    if s0 in ["em transporte", "transporte"]:
        return f"🟠 {s}"
    if s0 in ["sem oc", "sem pedido", "sem oc/sol", "sem oc/solicitação"]:
        return f"🔵 {s}"
    if s0 in ["atrasado", "vencido", "em atraso", "crítico", "critico"]:
        return f"🔴 {s}"
    if s0 in ["em aberto", "aberto", "pendente", "em andamento"]:
        return f"🟡 {s}"

    return f"⚪ {s}"


def _status_pill(status: str) -> str:
    """Badge HTML (cor real) para usar em st.markdown(unsafe_allow_html=True)."""
    s = "" if status is None else str(status).strip()
    s0 = s.lower()

    # cores (ajuste se necessário)
    if s0 in ["entregue", "entregues", "finalizado", "concluído", "concluido", "encerrado"]:
        bg, fg = "#103B1A", "#CFF7D6"  # verde
        dot = "🟢"
    elif s0 in ["em aberto", "aberto", "pendente", "em andamento", "em transporte", "transporte"]:
        bg, fg = "#3A2D0A", "#FFE6A7"  # amarelo
        dot = "🟡" if "transporte" not in s0 else "🟠"
    elif s0 in ["atrasado", "vencido", "em atraso", "crítico", "critico"]:
        bg, fg = "#3A1010", "#FFD0D0"  # vermelho
        dot = "🔴"
    elif s0 in ["sem oc", "sem pedido", "sem oc/sol", "sem oc/solicitação"]:
        bg, fg = "#1D2330", "#D7E3FF"  # azul/cinza
        dot = "🔵"
    else:
        bg, fg = "#22242A", "#E6E6E6"
        dot = "⚪"

    return (
        f"<span style='display:inline-flex;align-items:center;gap:.35rem;"
        f"padding:.2rem .55rem;border-radius:999px;background:{bg};color:{fg};"
        f"border:1px solid rgba(255,255,255,.08);font-size:.85rem;'>"
        f"<span style='font-size:.85rem'>{dot}</span><span>{s}</span></span>"
    )




def _status_html(status: str) -> str:
    """Retorna um pill HTML com cor (para usar com unsafe_allow_html=True)."""
    s = "" if status is None else str(status).strip()
    s0 = s.lower()

    if s0 in ["entregue", "entregues", "finalizado", "concluído", "concluido", "encerrado"]:
        cls = "st-pill st-pill-green"
    elif s0 in ["atrasado", "vencido", "em atraso", "crítico", "critico"]:
        cls = "st-pill st-pill-red"
    elif s0 in ["em transporte", "transporte"]:
        cls = "st-pill st-pill-orange"
    elif s0 in ["sem oc", "sem pedido", "sem oc/sol", "sem oc/solicitação"]:
        cls = "st-pill st-pill-blue"
    elif s0 in ["em aberto", "aberto", "pendente", "em andamento"]:
        cls = "st-pill st-pill-yellow"
    else:
        cls = "st-pill st-pill-neutral"

    return f"<span class='{cls}'>{s or '—'}</span>"



def _render_lista_erp_com_olho(page: pd.DataFrame, show_cols: list[str]) -> str | None:
    """Renderiza uma lista estilo ERP com botão 👁️ por linha (seleção única, intuitiva).
    Retorna o pid (id) quando o usuário clicar em 👁️, senão None.
    """
    if "id" not in page.columns:
        return None

    # CSS local: evita que descrições longas "invadam" outras colunas
    st.markdown(
        """
        <style>

          .fu-erp-list [data-testid="column"]{ min-width: 0 !important; }
          .fu-erp-list [data-testid="stHorizontalBlock"]{ gap: 0.5rem !important; }
          .fu-erp-list div[data-testid="stButton"]{ width: 100% !important; }
          .fu-erp-list div[data-testid="stButton"] > button{
            max-width: 100% !important;
            display: block !important;
          }
          .fu-erp-list div[data-testid="stButton"] > button *{
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            white-space: nowrap !important;
            max-width: 100% !important;
          }

          .fu-erp-list div[data-testid="stButton"] > button{
            width: 100% !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            white-space: nowrap !important;
            min-height: 38px !important;
          }
          .fu-erp-list [data-testid="stButton"]{ margin-bottom: 0 !important; }
          .fu-erp-list .fu-erp-sep hr{ margin: 6px 0 !important; opacity: .25; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="fu-erp-list">', unsafe_allow_html=True)

    # Cabeçalho (sticky-like por CSS fica complexo; aqui deixamos simples e limpo)
    header_cols = st.columns([0.6, 1.4, 3.6, 1.2, 1.1, 1.2, 1.2])
    header_cols[0].markdown("**Ver**")
    header_cols[1].markdown("**Equip.**")
    header_cols[2].markdown("**Descrição**")
    header_cols[3].markdown("**OC / SOL**")
    header_cols[4].markdown("**Depto**")
    header_cols[5].markdown("**Status**")
    header_cols[6].markdown("**Valor**")

    st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)

    for i, r in page.reset_index(drop=False).iterrows():
        # r contém a coluna "index" do df original (drop=False) — útil se precisar
        pid = str(r.get("id"))

        cod_eq = _to_str(r.get("cod_equipamento"))
        desc = _to_str(r.get("descricao"))
        oc = _to_str(r.get("nr_oc"))
        sol = _to_str(r.get("nr_solicitacao"))
        depto = _to_str(r.get("departamento"))
        status_txt = _badge_status(_to_str(r.get("status")))

        # valor
        val = r.get("valor_total")
        try:
            val_f = float(val) if val not in (None, "") else 0.0
            val_str = f"R$ {val_f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            val_str = _to_str(val)

        c = st.columns([0.6, 1.4, 3.6, 1.2, 1.1, 1.2, 1.2])

        with c[0]:
            if st.button("👁️", key=f"see_{pid}", help="Abrir ações deste pedido", use_container_width=True):
                return pid

        with c[1]:
            st.caption(cod_eq or "—")

        with c[2]:
            # descrição (curta) + botão de info (abre modal com texto completo)
            desc = str(desc or "").replace("\n", " ").replace("\r", " ").strip()
            desc = re.sub(r"\s+", " ", desc)

            MAX_DESC = 55  # limita visual para não invadir outras colunas
            short = (desc[: MAX_DESC - 1] + "…") if len(desc) > MAX_DESC else desc
            label = short or "—"
            if st.button(label, key=f"row_{pid}", help="Abrir ações deste pedido", use_container_width=True):
                return pid

        with c[3]:
            st.caption(f"{oc or '—'} / {sol or '—'}")

        with c[4]:
            st.caption(depto or "—")

        with c[5]:
            st.markdown(_status_html(_to_str(r.get('status'))), unsafe_allow_html=True)

        with c[6]:
            st.caption(val_str or "—")

        st.markdown('<div class="fu-erp-sep"><hr></div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)
    return None


def _render_tabela_selecao_unica(page: pd.DataFrame, show_cols: list[str]) -> str | None:
    """Compat: mantém assinatura antiga, mas renderiza lista ERP com botão 👁️."""
    return _render_lista_erp_com_olho(page, show_cols)
def _make_stamp(df: pd.DataFrame, col: str = "atualizado_em") -> tuple:
    if df is None or df.empty:
        return (0, "empty")
    mx = None
    if col in df.columns:
        mx = pd.to_datetime(df[col], errors="coerce").max()
    return (len(df), str(mx) if mx is not None else "none")

@st.cache_data(ttl=120)
def _prepare_search(stamp: tuple, df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza tipos e cria coluna de busca (cacheada)."""
    if df is None or df.empty:
        return df

    out = df.copy()

    cols = []
    for c in ["nr_oc", "nr_solicitacao", "descricao", "departamento", "fornecedor", "cod_material", "cod_equipamento"]:
        if c in out.columns:
            cols.append(out[c].fillna("").astype(str).str.lower())

    if cols:
        s = cols[0]
        for x in cols[1:]:
            s = s + " " + x
        out["__search__"] = s.str.replace(r"\s+", " ", regex=True).str.strip()
    else:
        out["__search__"] = ""

    for dc in ["data_solicitacao", "data_oc", "previsao_entrega", "data_entrega"]:
        if dc in out.columns:
            out[dc] = pd.to_datetime(out[dc], errors="coerce")

    for nc in ["qtde_solicitada", "qtde_entregue", "valor_total", "dias_atraso", "qtde_pendente"]:
        if nc in out.columns:
            out[nc] = pd.to_numeric(out[nc], errors="coerce")

    return out

def _is_atrasado(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series([], dtype=bool)
    if "dias_atraso" in df.columns:
        return pd.to_numeric(df["dias_atraso"], errors="coerce").fillna(0) > 0
    if "previsao_entrega" in df.columns:
        hoje = pd.Timestamp.now().normalize()
        if "status" in df.columns:
            status_ok = df["status"].fillna("").astype(str) != "Entregue"
        else:
            status_ok = True
        return df["previsao_entrega"].notna() & (df["previsao_entrega"] < hoje) & status_ok
    return pd.Series([False] * len(df), index=df.index)

def _apply_filters(
    df: pd.DataFrame,
    q: str,
    deptos: list[str],
    status_list: list[str],
    somente_atrasados: bool,
    cod_equip: str = "",
    cod_mat: str = "",
) -> pd.DataFrame:
    """Aplica filtros estáveis (multiselect) + busca + atrasados + códigos numéricos."""
    out = df

    if deptos and "departamento" in out.columns:
        out = out[out["departamento"].isin(deptos)]

    if status_list and "status" in out.columns:
        out = out[out["status"].isin(status_list)]

    # Código de equipamento (somente números): match exato ou prefixo (tolerante)
    if cod_equip and "cod_equipamento" in out.columns:
        ce = str(cod_equip).strip()
        out = out[out["cod_equipamento"].fillna("").astype(str).str.replace(r"\D", "", regex=True).str.startswith(ce)]

    # Código de material (somente números): match exato ou prefixo (tolerante)
    if cod_mat and "cod_material" in out.columns:
        cm = str(cod_mat).strip()
        out = out[out["cod_material"].fillna("").astype(str).str.replace(r"\D", "", regex=True).str.startswith(cm)]

    if q:
        qn = q.lower().strip()
        if "__search__" in out.columns:
            out = out[out["__search__"].str.contains(qn, na=False)]
        else:
            # fallback: busca em colunas texto comuns
            cols = [c for c in ["descricao", "fornecedor", "nr_oc", "nr_solicitacao", "cod_material", "cod_equipamento"] if c in out.columns]
            if cols:
                mask = False
                for c in cols:
                    mask = mask | out[c].fillna("").astype(str).str.lower().str.contains(qn)
                out = out[mask]

    if somente_atrasados:
        out = out[_is_atrasado(out)]

    return out

def _download_csv(df: pd.DataFrame, filename: str):
    csv = df.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("⬇️ CSV", csv, file_name=filename, mime="text/csv", use_container_width=True)

def _download_xlsx(df: pd.DataFrame, filename: str):
    """Download XLSX without requiring xlsxwriter (fallback to openpyxl)."""
    output = io.BytesIO()
    engine = "xlsxwriter"
    try:
        __import__("xlsxwriter")
    except Exception:
        engine = "openpyxl"

    with pd.ExcelWriter(output, engine=engine) as writer:
        df.to_excel(writer, index=False, sheet_name="Pedidos")

    st.download_button(
        "⬇️ XLSX",
        output.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

def _to_label(row: pd.Series) -> str:
    nr_oc = str(row.get("nr_oc") or "").strip()
    nr_sol = str(row.get("nr_solicitacao") or "").strip()
    dept = str(row.get("departamento") or "").strip()
    stt = str(row.get("status") or "").strip()
    desc = str(row.get("descricao") or "").strip().replace("\n", " ")
    if len(desc) > 70:
        desc = desc[:70] + "…"
    return f"OC: {nr_oc or '-'} | SOL: {nr_sol or '-'} | {stt} | {dept} — {desc}"

def _find_pid_by_key(df: pd.DataFrame, key: str) -> str | None:
    """Localiza um pedido pelo nr_oc ou nr_solicitacao (exato -> parcial)."""
    if df is None or df.empty or not key:
        return None
    k = str(key).strip()
    if not k:
        return None


def _numeric_autocomplete(label: str, series: pd.Series, key_prefix: str, max_suggestions: int = 30) -> str:
    """Autocomplete simples para códigos numéricos.
    - Usuário digita só números (limpamos tudo que não for dígito)
    - Mostra sugestões (starts/contains)
    - Retorna valor selecionado (string) ou "".
    """
    st.session_state.setdefault(f"{key_prefix}_q", "")
    st.session_state.setdefault(f"{key_prefix}_sel", "")

    raw = st.text_input(label, key=f"{key_prefix}_q", placeholder="Digite números…")
    q = re.sub(r"\D+", "", raw or "")
    if q != (raw or ""):
        st.session_state[f"{key_prefix}_q"] = q  # normaliza na UI

    # se já selecionou, mantém
    options = []
    if series is not None and not series.empty:
        vals = series.dropna().astype(str)
        vals = vals[vals.str.fullmatch(r"\d+")]  # só números
        uniq = sorted(vals.unique().tolist())
        if q:
            starts = [v for v in uniq if v.startswith(q)]
            contains = [v for v in uniq if (q in v and not v.startswith(q))]
            options = (starts + contains)[:max_suggestions]
        else:
            options = uniq[:max_suggestions]

    sel = st.selectbox(
        "Sugestões",
        [""] + options,
        key=f"{key_prefix}_sel",
        label_visibility="collapsed",
        help="Selecione um código sugerido (opcional).",
    )

    return sel or (q if q else "")
    if "nr_oc" in df.columns:
        m = df[df["nr_oc"].fillna("").astype(str).str.strip() == k]
        if not m.empty:
            return str(m.iloc[0].get("id") or "")
    if "nr_solicitacao" in df.columns:
        m = df[df["nr_solicitacao"].fillna("").astype(str).str.strip() == k]
        if not m.empty:
            return str(m.iloc[0].get("id") or "")

    if "nr_oc" in df.columns:
        m = df[df["nr_oc"].fillna("").astype(str).str.contains(k, na=False)]
        if not m.empty:
            return str(m.iloc[0].get("id") or "")
    if "nr_solicitacao" in df.columns:
        m = df[df["nr_solicitacao"].fillna("").astype(str).str.contains(k, na=False)]
        if not m.empty:
            return str(m.iloc[0].get("id") or "")

    return None


def _inject_consulta_css():
    st.markdown(
        """
<style>
/* Reduz poluição visual e melhora densidade */
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
h1, h2, h3 { letter-spacing: .2px; }
[data-testid="stMetric"] { padding: .6rem .75rem; border-radius: 14px; }
[data-testid="stMetric"] > div { gap: .1rem; }
div.stButton > button { border-radius: 12px; height: 2.6rem; }
div[data-testid="stHorizontalBlock"] { align-items: center; }
/* Fixar colunas principais no Data Editor (ERP-like v2) */
[data-testid="stDataEditor"] [role="columnheader"],
[data-testid="stDataEditor"] [role="gridcell"] { white-space: nowrap; }
[data-testid="stDataEditor"] [role="row"] > [role="gridcell"]:nth-child(1),
[data-testid="stDataEditor"] [role="row"] > [role="columnheader"]:nth-child(1) { position: sticky; left: 0px; z-index: 6; background: rgba(15,17,20,.98); }
[data-testid="stDataEditor"] [role="row"] > [role="gridcell"]:nth-child(2),
[data-testid="stDataEditor"] [role="row"] > [role="columnheader"]:nth-child(2) { position: sticky; left: 68px; z-index: 5; background: rgba(15,17,20,.98); }
[data-testid="stDataEditor"] [role="row"] > [role="gridcell"]:nth-child(3),
[data-testid="stDataEditor"] [role="row"] > [role="columnheader"]:nth-child(3) { position: sticky; left: 210px; z-index: 4; background: rgba(15,17,20,.98); }

[data-testid="stDataEditor"] div[role="grid"] [role="columnheader"],
[data-testid="stDataEditor"] div[role="grid"] [role="gridcell"] { white-space: nowrap; }
/* 1ª coluna (Abrir) */
[data-testid="stDataEditor"] div[role="grid"] [role="columnheader"]:nth-child(1),
[data-testid="stDataEditor"] div[role="grid"] [role="gridcell"]:nth-child(1) { position: sticky; left: 0; z-index: 5; background: rgba(15,17,20,.98); }
/* 2ª coluna (Cód. equipamento) */
[data-testid="stDataEditor"] div[role="grid"] [role="columnheader"]:nth-child(2),
[data-testid="stDataEditor"] div[role="grid"] [role="gridcell"]:nth-child(2) { position: sticky; left: 70px; z-index: 4; background: rgba(15,17,20,.98); }
/* 3ª coluna (Descrição) */
[data-testid="stDataEditor"] div[role="grid"] [role="columnheader"]:nth-child(3),
[data-testid="stDataEditor"] div[role="grid"] [role="gridcell"]:nth-child(3) { position: sticky; left: 220px; z-index: 3; background: rgba(15,17,20,.98); }

.small-muted { opacity: .8; font-size: .9rem; }
</style>
        """,
        unsafe_allow_html=True,
    )


def exibir_consulta_pedidos(_supabase):
    # Refresh vindo do header global (se existir)
    if st.session_state.pop("_consulta_force_refresh", False):
        _clear_cached_pedidos(st.session_state.get("tenant_id"))

    if carregar_pedidos is None:
        st.error("Função 'carregar_pedidos' não encontrada. Verifique o import em src.repositories.pedidos.")
        return

    _inject_consulta_css()

    # Topbar (mais limpa)
    topL, topR = st.columns([2.2, 1.3])
    with topL:
        st.title("Consultar Pedidos")

        # Estilo (lista ERP): pills, hover suave, compacto, fade-in
        st.markdown("""
        <style>
        @keyframes fuFadeIn { from {opacity: 0; transform: translateY(2px);} to {opacity: 1; transform: translateY(0);} }
        section.main > div.block-container { animation: fuFadeIn .15s ease-out; }

        .st-pill { display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600;
                  border: 1px solid rgba(255,255,255,.10); }
        .st-pill-green { background: rgba(46, 204, 113, .18); color: rgba(46, 204, 113, 1); }
        .st-pill-yellow{ background: rgba(241, 196, 15, .18); color: rgba(241, 196, 15, 1); }
        .st-pill-red   { background: rgba(231, 76, 60, .18); color: rgba(231, 76, 60, 1); }
        .st-pill-blue  { background: rgba(52, 152, 219, .18); color: rgba(52, 152, 219, 1); }
        .st-pill-orange{ background: rgba(230, 126, 34, .18); color: rgba(230, 126, 34, 1); }
        .st-pill-neutral{ background: rgba(255,255,255,.07); color: rgba(255,255,255,.80); }

        /* Modo compacto */
        [data-testid="stVerticalBlock"] .stCaption { margin-top: 0.15rem; margin-bottom: 0.15rem; }
        [data-testid="stButton"] button { padding-top: .35rem; padding-bottom: .35rem; }

        /* Hover highlight (no botão da descrição, que é a "linha clicável") */
        [data-testid="stButton"] button:hover { filter: brightness(1.05); }
        </style>
        """, unsafe_allow_html=True)
    st.caption("Busque, filtre e aja rápido sem poluir a tela.")
    st.caption("💡 Dica: os filtros ficam no menu lateral (🎛️ Filtros).")
    # Botões de ação ficam no header global do app (evita duplicação nesta página)

    tenant_id = st.session_state.get("tenant_id")
    df_raw = _get_cached_pedidos(_supabase, tenant_id)
    if df_raw is None or df_raw.empty:
        st.info("📭 Nenhum pedido cadastrado.")
        return

    df = _prepare_search(_make_stamp(df_raw), df_raw)
    # Status disponíveis no dataset (para filtro rápido executivo)
    try:
        if "status" in df.columns:
            st.session_state["consulta_status_opts"] = sorted(df["status"].dropna().astype(str).unique().tolist())
        else:
            st.session_state.setdefault("consulta_status_opts", [])
    except Exception:
        st.session_state.setdefault("consulta_status_opts", [])


    # -------------------- Estado padrão (filtros + seleção)
    st.session_state.setdefault("c_q", "")
    st.session_state.setdefault("c_deptos", [])
    st.session_state.setdefault("c_status_list", [])
    st.session_state.setdefault("c_cod_equip", "")
    st.session_state.setdefault("c_cod_mat", "")
    st.session_state.setdefault("c_atraso", False)
    st.session_state.setdefault("c_pp", 50)
    st.session_state.setdefault("c_pag", 1)
    st.session_state.setdefault("consulta_selected_pid", None)
    st.session_state.setdefault("consulta_auto_opened_pid", None)
    st.session_state.setdefault("consulta_selected_label", "")
    st.session_state.setdefault("go_key", "")
    # -------------------- Presets/Atalhos (robusto, evita StreamlitAPIException)
    # Regras:
    # - Callback (on_change/on_click) roda antes de renderizar widgets -> seguro para setar chaves
    # - Presets respeitam status disponíveis no dataset (quando aplicável)
    def _apply_preset(preset: str, status_opts: list[str] | None = None):
        preset = (preset or "—").strip()

        desired_by_preset = {
            "Sem OC": ["Sem OC"],
            "Transporte": ["Em Transporte"],
            "Em Transporte": ["Em Transporte"],
            "Entregues": ["Entregue"],
        }

        st.session_state["c_pag"] = 1

        if preset in ("—", "", "Todos"):
            # "Todos" volta ao estado neutro
            if preset == "Todos":
                st.session_state["c_atraso"] = False
                st.session_state["c_status_list"] = []
            return

        if preset == "Limpar":
            st.session_state["c_atraso"] = False
            st.session_state["c_status_list"] = []
            return

        if preset == "Atrasados":
            st.session_state["c_atraso"] = True
            st.session_state["c_status_list"] = []
            return

        wanted = desired_by_preset.get(preset, [])
        if status_opts:
            wanted = [s for s in wanted if s in status_opts]
        st.session_state["c_status_list"] = wanted
        st.session_state["c_atraso"] = False

    def _apply_preset_from_selectbox():
        preset = st.session_state.get("consulta_preset") or "—"
        status_opts_atual = st.session_state.get("consulta_status_opts") or None
        _apply_preset(preset, status_opts=status_opts_atual)

# =========================
    # -------------------- Tabs para reduzir poluição
    st.session_state.setdefault("consulta_tab", "Lista")
    st.session_state.setdefault("consulta_tab_target", None)

    # Se alguma ação pediu troca de aba (ex.: clique em linha), aplica ANTES de criar o widget st.radio
    target_tab = st.session_state.get("consulta_tab_target")
    if target_tab:
        st.session_state["consulta_tab"] = target_tab
        st.session_state["consulta_tab_target"] = None


    # Top controls (executivo): Navegação + Filtro rápido na mesma linha
    # =========================
    st.markdown(
        '''
        <style>
          /* Top controls: duas "segment bars" minimalistas (vermelho) */
          .fu-top-controls{ margin: 6px 0 6px 0; }
          .fu-top-controls .fu-segbar{ display:flex; align-items:center; }
          .fu-top-controls .fu-segbar [role="radiogroup"]{
            display:inline-flex !important;
            gap: 0 !important;
            padding: 4px !important;
            border-radius: 14px !important;
            border: 1px solid rgba(255,255,255,0.10) !important;
            background: rgba(255,255,255,0.03) !important;
            overflow: hidden !important;
          }
          .fu-top-controls .fu-segbar [role="radiogroup"] > label{ margin:0 !important; }
          .fu-top-controls .fu-segbar [role="radiogroup"] label{
            padding: 6px 12px !important;
            border-radius: 10px !important;
            border: 1px solid transparent !important;
            background: transparent !important;
            transition: background 120ms ease, border-color 120ms ease, transform 120ms ease;
            user-select:none;
            white-space: nowrap;
          }
          .fu-top-controls .fu-segbar [role="radiogroup"] label:hover{
            border-color: rgba(239,68,68,0.22) !important;
            background: rgba(239,68,68,0.08) !important;
          }
          .fu-top-controls .fu-segbar [role="radiogroup"] input:checked + div{
            border-radius: 10px !important;
            background: rgba(239,68,68,0.16) !important;
            box-shadow: inset 0 0 0 1px rgba(239,68,68,0.35) !important;
          }
          .fu-top-controls .fu-segbar [role="radiogroup"] label div{
            font-weight: 850 !important;
            font-size: 0.86rem !important;
            padding: 0 !important;
          }
          /* Esconde bolinha do radio (fica estilo tabs) */
          .fu-top-controls .fu-segbar [role="radiogroup"] label span:first-child{ display:none !important; }

          /* Alinhamento e responsividade */
          .fu-top-controls .fu-top-nav{ justify-content:flex-start; }
          .fu-top-controls .fu-top-quick{ justify-content:flex-end; }
          @media (max-width: 980px){
            .fu-top-controls .fu-top-nav{ justify-content:center; margin-bottom: 6px; }
            .fu-top-controls .fu-top-quick{ justify-content:center; }
          }
        </style>
        ''',
        unsafe_allow_html=True,
    )

    nav_col, quick_col = st.columns([1.3, 2.0])
    with nav_col:
        st.markdown('<div class="fu-top-controls"><div class="fu-segbar fu-top-nav">', unsafe_allow_html=True)
        tab_choice = st.radio(
            "",
            ["Lista", "Visão", "Ações"],
            horizontal=True,
            key="consulta_tab",
            label_visibility="collapsed",
        )
        st.markdown("</div></div>", unsafe_allow_html=True)

    with quick_col:
        # Segment control (filtro rápido) — usa status disponíveis no dataset
        status_opts_atual = st.session_state.get("consulta_status_opts") or []

        quick_opts = ["Todos", "Atrasados"]
        if "Sem OC" in status_opts_atual:
            quick_opts.append("Sem OC")
        if "Em Transporte" in status_opts_atual:
            quick_opts.append("Transporte")
        if "Entregue" in status_opts_atual:
            quick_opts.append("Entregues")

        st.session_state.setdefault("consulta_quick", "Todos")
        if st.session_state.get("consulta_quick") not in quick_opts:
            st.session_state["consulta_quick"] = "Todos"

        def _apply_quick_from_control():
            val = st.session_state.get("consulta_quick") or "Todos"
            _apply_preset(val, status_opts=status_opts_atual)

        st.markdown('<div class="fu-top-controls"><div class="fu-segbar fu-top-quick">', unsafe_allow_html=True)
        st.radio(
            "",
            options=quick_opts,
            horizontal=True,
            key="consulta_quick",
            label_visibility="collapsed",
            on_change=_apply_quick_from_control,
        )
        st.markdown("</div></div>", unsafe_allow_html=True)
    # =========================
    # TAB: LISTA (principal)
    # =========================
    if tab_choice == "Lista":
                # Barra superior: busca + filtros (executivo / clean)
        st.text_input(
            "Buscar",
            key="c_q",
            placeholder="OC, solicitação, descrição, fornecedor, código material/equipamento…",
            label_visibility="collapsed",
        )

        # Filtros completos ficam na sidebar (evita poluir a tela)
        with st.sidebar.expander("🎛️ Filtros", expanded=False):
            # Departamento
            if "departamento" in df.columns:
                dept_opts = sorted(df["departamento"].dropna().astype(str).unique().tolist())
                st.multiselect("Departamento", dept_opts, key="c_deptos", placeholder="Todos")
            else:
                st.multiselect("Departamento", [], key="c_deptos", placeholder="Todos")

            # Status
            if "status" in df.columns:
                status_opts = sorted(df["status"].dropna().astype(str).unique().tolist())
                st.session_state["consulta_status_opts"] = status_opts
                # Normaliza valores atuais para evitar erro se preset tiver valor inválido
                current_status = st.session_state.get("c_status_list", []) or []
                st.session_state["c_status_list"] = [s for s in current_status if s in status_opts]
                st.multiselect("Status", status_opts, key="c_status_list", placeholder="Todos")
            else:
                current_status = st.session_state.get("c_status_list", []) or []
                st.session_state["c_status_list"] = [s for s in current_status if s in STATUS_VALIDOS]
                st.session_state["consulta_status_opts"] = STATUS_VALIDOS
                st.multiselect("Status", STATUS_VALIDOS, key="c_status_list", placeholder="Todos")

            st.divider()
            st.markdown("**Códigos (somente números)**")

            c_eq = _numeric_autocomplete(
                "Cód. equipamento",
                df["cod_equipamento"] if "cod_equipamento" in df.columns else pd.Series([], dtype=str),
                "f_cod_equip",
            )
            c_mat = _numeric_autocomplete(
                "Cód. material",
                df["cod_material"] if "cod_material" in df.columns else pd.Series([], dtype=str),
                "f_cod_mat",
            )

            st.session_state["_tmp_cod_equip"] = c_eq
            st.session_state["_tmp_cod_mat"] = c_mat

            st.checkbox("Somente atrasados", key="c_atraso")
            st.selectbox("Itens por página", [25, 50, 100, 200, 500], key="c_pp")

            aF1, aF2 = st.columns(2)
            if aF1.button("Aplicar", use_container_width=True):
                st.session_state["c_cod_equip"] = st.session_state.get("_tmp_cod_equip", "")
                st.session_state["c_cod_mat"] = st.session_state.get("_tmp_cod_mat", "")
                st.session_state["c_pag"] = 1
                st.rerun()
            if aF2.button("Limpar", use_container_width=True):
                for k in ["c_q", "c_deptos", "c_status_list", "c_cod_equip", "c_cod_mat", "_tmp_cod_equip", "_tmp_cod_mat", "c_atraso", "c_pp", "c_pag", "consulta_selected_pid", "consulta_auto_opened_pid", "go_key"]:
                    st.session_state.pop(k, None)
                st.rerun()

        # Aplicar filtros (sem “fake rerun”)
        df_f = _apply_filters(
            df,
            st.session_state.get("c_q", ""),
            st.session_state.get("c_deptos", []),
            st.session_state.get("c_status_list", []),
            st.session_state.get("c_atraso", False),
            st.session_state.get("c_cod_equip", ""),
            st.session_state.get("c_cod_mat", ""),
        )

        # KPIs dinâmicos (baseado nos filtros)
        k1, k2, k3, k4 = st.columns(4)
        total_itens = int(len(df_f))
        atrasados = (
            int(df_f.get("dias_atraso", pd.Series([], dtype=float)).fillna(0).astype(float).gt(0).sum())
            if not df_f.empty
            else 0
        )
        sem_oc = (
            int(df_f.get("nr_oc", pd.Series([], dtype=str)).fillna("").astype(str).isin(["", "0"]).sum())
            if "nr_oc" in df_f.columns
            else 0
        )
        valor_total = (
            float(df_f.get("valor_total", pd.Series([], dtype=float)).fillna(0).astype(float).sum())
            if "valor_total" in df_f.columns
            else 0.0
        )
        k1.metric("Resultados", f"{total_itens}")
        k2.metric("Atrasados", f"{atrasados}")
        k3.metric("Sem OC", f"{sem_oc}")
        k4.metric("Valor", f"R$ {valor_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        st.markdown("---")
        st.caption("Legenda: 🟢 OK/Tem OC • 🟡 Em aberto • 🟠 Transporte • 🔴 Atrasado • 🔵 Sem OC")

        # Chips compactos
        chips = []
        if st.session_state.get("c_q"):
            chips.append(f"Busca: {st.session_state['c_q']}")
        if st.session_state.get("c_deptos"):
            d = st.session_state["c_deptos"]
            chips.append(f"Depto: {', '.join(d[:2])}{'…' if len(d)>2 else ''}")
        if st.session_state.get("c_status_list"):
            s = st.session_state["c_status_list"]
            chips.append(f"Status: {', '.join(s[:2])}{'…' if len(s)>2 else ''}")
        if st.session_state.get("c_atraso"):
            chips.append("Atrasados")
        if st.session_state.get("c_cod_equip"):
            chips.append(f"Eq: {st.session_state['c_cod_equip']}")
        if st.session_state.get("c_cod_mat"):
            chips.append(f"Mat: {st.session_state['c_cod_mat']}")
        if chips:
            st.caption(" | ".join(chips))

        # Paginação com setas (compacta)
        total = len(df_f)
        pp = int(st.session_state.get("c_pp", 50))
        total_pages = max(1, math.ceil(total / pp))
        st.session_state["c_pag"] = min(max(1, int(st.session_state.get("c_pag", 1))), total_pages)

        nav1, nav2, nav3 = st.columns([1, 2, 1])
        with nav1:
            if st.button("◀", disabled=st.session_state["c_pag"] <= 1, use_container_width=True):
                st.session_state["c_pag"] -= 1
                st.rerun()
        with nav2:
            st.markdown(
                f'<div style="text-align:center" class="small-muted">Página <b>{st.session_state["c_pag"]}</b> de <b>{total_pages}</b> • <b>{total}</b> itens</div>',
                unsafe_allow_html=True,
            )
        with nav3:
            if st.button("▶", disabled=st.session_state["c_pag"] >= total_pages, use_container_width=True):
                st.session_state["c_pag"] += 1
                st.rerun()

        ini = (st.session_state["c_pag"] - 1) * pp
        fim = ini + pp
        page = df_f.iloc[ini:fim].copy()

        # Tabela mais limpa: evita descrições enormes
        show_cols = []
        preferred = ["cod_equipamento", "descricao", "nr_oc", "nr_solicitacao", "departamento", "status", "cod_material", "valor_total", "dias_atraso"]
        for c in preferred:
            if c in page.columns:
                show_cols.append(c)
        if not show_cols:
            show_cols = page.columns.tolist()

        if "descricao" in page.columns:
            page["descricao"] = page["descricao"].fillna("").astype(str).str.slice(0, 90) + page["descricao"].fillna("").astype(str).apply(lambda x: "…" if len(x) > 90 else "")


        # Badge de status

        if "status" in page.columns:

            page["status"] = page["status"].astype(str).apply(_badge_status)


        # Tabela (modo responsivo): se data_editor existir, permite selecionar uma linha (checkbox)

        pid_editor = _render_tabela_selecao_unica(page, show_cols)

        if pid_editor:
            st.session_state["consulta_selected_pid"] = pid_editor
            st.session_state["consulta_tab_target"] = "Ações"
            st.rerun()
# =========================
    # TAB: VISÃO (KPIs + atalhos)
    # =========================
    if tab_choice == "Visão":
        atrasados = int(_is_atrasado(df).sum())
        sem_oc = int((df["status"] == "Sem OC").sum()) if "status" in df.columns else 0
        transporte = int((df["status"] == "Em Transporte").sum()) if "status" in df.columns else 0
        entregues = int((df["status"] == "Entregue").sum()) if "status" in df.columns else 0
        total = int(len(df))

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total", total)
        k2.metric("Atrasados", atrasados)
        k3.metric("Sem OC", sem_oc)
        k4.metric("Transporte", transporte)
        k5.metric("Entregues", entregues)

        st.markdown("##### Atalhos")
        a1, a2, a3, a4 = st.columns(4)
        if a1.button("📦 Atrasados", use_container_width=True):
            st.session_state.update({"c_atraso": True, "c_status_list": [], "c_pag": 1})
            st.rerun()
        if a2.button("🧾 Sem OC", use_container_width=True):
            st.session_state.update({"c_status_list": ["Sem OC"], "c_atraso": False, "c_pag": 1})
            st.rerun()
        if a3.button("🚚 Transporte", use_container_width=True):
            st.session_state.update({"c_status_list": ["Em Transporte"], "c_atraso": False, "c_pag": 1})
            st.rerun()
        if a4.button("✅ Entregues", use_container_width=True):
            st.session_state.update({"c_status_list": ["Entregue"], "c_atraso": False, "c_pag": 1})
            st.rerun()

        st.info("Dica: use os atalhos aqui e volte na aba **Lista** para ver o resultado sem poluir a tela.")

    # =========================
    # TAB: AÇÕES (operacional)
    # =========================
    if tab_choice == "Ações":
        st.markdown("#### Ações rápidas")
        st.caption("Localize um pedido por OC/Solicitação e abra diretamente na Gestão/Ficha.")

        aC1, aC2, aC3 = st.columns([2.4, 1.0, 2.0])
        with aC1:
            st.text_input("OC/SOL", key="go_key", placeholder="Ex: 181151 ou 433526", label_visibility="collapsed")
        with aC2:
            if st.button("Ir", use_container_width=True):
                pid = _find_pid_by_key(df, st.session_state.get("go_key", ""))
                if pid:
                    st.session_state["consulta_selected_pid"] = pid
                    st.success("Pedido localizado.")
                else:
                    st.warning("Não encontrei OC/SOL com esse valor.")

        pid = st.session_state.get("consulta_selected_pid")
        if not pid:
            st.info("Selecione um pedido na aba **Lista** ou use o campo acima.")
            return

        row = df[df["id"].astype(str) == str(pid)] if "id" in df.columns else pd.DataFrame()
        if row.empty and "nr_oc" in df.columns:
            row = df[df["nr_oc"].fillna("").astype(str) == str(pid)]
        if row.empty:
            st.warning("Pedido selecionado não foi encontrado no dataset atual.")
            return

        r = row.iloc[0]

        # Mini-card de resumo (responsiva)
        status_pill = _status_pill(_to_str(r.get('status')))
        cA, cB = st.columns([2, 1])
        with cA:
            st.markdown(
                f"""**Resumo**  
- **OC:** {_to_str(r.get('nr_oc'))} • **SOL:** {_to_str(r.get('nr_solicitacao'))}  
- **Status:** {status_pill} • **Depto:** {_to_str(r.get('departamento'))}  
- **Fornecedor:** {_to_str(r.get('fornecedor'))}  
- **Descrição:** {_to_str(r.get('descricao'))[:220]}{'…' if len(_to_str(r.get('descricao'))) > 220 else ''}  
"""
            , unsafe_allow_html=True)
        with cB:
            st.markdown("**Ações**")
            if st.button("Abrir na Gestão", use_container_width=True):
                st.session_state["pedido_selecionado"] = _to_str(r.get("id") or "")
                st.session_state["current_page"] = "orders_manage"
                st.rerun()
            if st.button("Ficha do Material", use_container_width=True):
                st.session_state["pedido_selecionado"] = _to_str(r.get("id") or "")
                st.session_state["current_page"] = "material_sheet"
                st.rerun()
            if st.button("Copiar OC/SOL", use_container_width=True):
                st.code(f"OC: {_to_str(r.get('nr_oc'))} | SOL: {_to_str(r.get('nr_solicitacao'))}")
