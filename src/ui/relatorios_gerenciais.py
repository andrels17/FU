
from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import streamlit as st


# =============================================================================
# Helpers (NUNCA execute lógica de relatório no import — apenas defs)
# =============================================================================

def _as_date(x: Any) -> Optional[date]:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        if isinstance(x, date) and not isinstance(x, datetime):
            return x
        if isinstance(x, datetime):
            return x.date()
        return pd.to_datetime(x, errors="coerce").date()
    except Exception:
        return None


def _col(df: pd.DataFrame, *cands: str) -> Optional[str]:
    if df is None or df.empty:
        return None
    cols = {c.lower(): c for c in df.columns}
    for c in cands:
        if c.lower() in cols:
            return cols[c.lower()]
    return None


def _to_num(s: pd.Series) -> pd.Series:
    try:
        return pd.to_numeric(s, errors="coerce").fillna(0.0)
    except Exception:
        return pd.Series([0.0] * len(s))


def _iter_links_safe(links: Any) -> List[dict]:
    """Itera links sem avaliar DataFrame em contexto booleano."""
    if links is None:
        return []
    try:
        if isinstance(links, pd.DataFrame):
            return links.to_dict("records")
    except Exception:
        pass
    if isinstance(links, dict):
        return [links]
    if isinstance(links, list):
        return [x for x in links if isinstance(x, dict)]
    return []


def _links_to_dept_map(links: Any) -> Dict[str, str]:
    """
    Converte 'links' (dict | list[dict] | DataFrame) em mapa:
        departamento -> gestor_user_id (string)
    """
    # dict já no formato desejado
    if isinstance(links, dict):
        out = {}
        for k, v in links.items():
            if k is None:
                continue
            kk = str(k).strip()
            vv = (str(v).strip() if v is not None else "")
            if kk and vv:
                out[kk] = vv
        return out

    out: Dict[str, str] = {}
    for row in _iter_links_safe(links):
        try:
            dept = (row.get("departamento") or row.get("dept") or row.get("department") or "").strip()
            gid = row.get("gestor_user_id") or row.get("gestor_id") or row.get("user_id") or row.get("gestor")
            gid = (str(gid).strip() if gid is not None else "")
            if dept and gid:
                out[dept] = gid
        except Exception:
            continue
    return out


def _download_csv_button(df: pd.DataFrame, filename_prefix: str) -> None:
    if df is None or df.empty:
        st.caption("Sem dados para exportar.")
        return
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(
        "Baixar CSV",
        data=buf.getvalue().encode("utf-8"),
        file_name=f"{filename_prefix}.csv",
        mime="text/csv",
        use_container_width=True,
    )


def _try_load_links(supabase, tenant_id: str) -> Any:
    """
    Tenta carregar vínculos departamento->gestor por diferentes caminhos.
    Retorna dict/list/df ou None. Se não existir no projeto, volta None sem quebrar.
    """
    # 1) Repositório dedicado (se existir)
    candidates = [
        ("src.repositories.departamentos", "carregar_links_departamentos"),
        ("src.repositories.dept_gestor_links", "carregar_links"),
        ("src.services.departamentos", "carregar_links_departamentos"),
    ]
    for mod_name, fn_name in candidates:
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name)
            return fn(supabase, tenant_id)
        except Exception:
            pass

    # 2) Tabela no Supabase (se existir) — tentativa “best effort”
    try:
        res = supabase.table("departamentos_gestores").select("*").eq("tenant_id", tenant_id).execute()
        data = getattr(res, "data", None)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    return None


def _try_load_user_map(supabase, tenant_id: str) -> Dict[str, str]:
    """
    Tenta carregar mapa user_id -> nome.
    """
    candidates = [
        ("src.repositories.usuarios", "carregar_mapa_usuarios_tenant"),
        ("src.repositories.users", "carregar_mapa_usuarios_tenant"),
        ("src.services.usuarios", "carregar_mapa_usuarios_tenant"),
    ]
    for mod_name, fn_name in candidates:
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name)
            m = fn(supabase, tenant_id)
            if isinstance(m, dict):
                return {str(k): str(v) for k, v in m.items()}
        except Exception:
            pass

    # fallback: tenta tabela 'usuarios'
    try:
        res = supabase.table("usuarios").select("id,nome,tenant_id").eq("tenant_id", tenant_id).execute()
        data = getattr(res, "data", None)
        if isinstance(data, list):
            return {str(r.get("id")): str(r.get("nome") or "").strip() for r in data if r.get("id")}
    except Exception:
        pass

    return {}


def _apply_date_filter(df: pd.DataFrame, dt_ini: Optional[date], dt_fim: Optional[date]) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    c_date = _col(df, "criado_em", "created_at", "data", "data_pedido", "dt_pedido", "data_emissao")
    if not c_date:
        return df

    s = pd.to_datetime(df[c_date], errors="coerce").dt.date
    mask = pd.Series([True] * len(df))
    if dt_ini:
        mask &= (s >= dt_ini)
    if dt_fim:
        mask &= (s <= dt_fim)
    return df.loc[mask].copy()


def _ensure_columns(df: pd.DataFrame, dept_map: Dict[str, str]) -> pd.DataFrame:
    """Normaliza colunas mínimas e cria 'gestor_user_id' se possível via dept_map."""
    if df is None or df.empty:
        return df

    c_dept = _col(df, "departamento", "dept", "department")
    c_gestor = _col(df, "gestor_user_id", "gestor_id", "responsavel_id")

    if not c_gestor and c_dept and dept_map:
        df["gestor_user_id"] = df[c_dept].astype(str).map(lambda x: dept_map.get(str(x).strip(), "")).replace("", pd.NA)
    return df


def _group_sum(df: pd.DataFrame, key_col: str, val_col: str) -> pd.DataFrame:
    if df is None or df.empty or not key_col or not val_col:
        return pd.DataFrame(columns=[key_col, "total"])
    d = df.copy()
    d[key_col] = d[key_col].fillna("—").astype(str)
    d[val_col] = _to_num(d[val_col])
    out = d.groupby(key_col, dropna=False)[val_col].sum().reset_index().rename(columns={val_col: "total"})
    out = out.sort_values("total", ascending=False, kind="stable")
    return out


def _kpi_card_row(kpis: List[Tuple[str, str]]) -> None:
    cols = st.columns(len(kpis))
    for c, (label, value) in zip(cols, kpis):
        with c:
            st.metric(label, value)


# =============================================================================
# UI principal
# =============================================================================

def render_relatorios_gerenciais(supabase, tenant_id: str) -> None:
    """
    Relatórios Gerenciais — v3/v4 (robusto)
    - ZERO execução no import
    - Trata links como DataFrame/list/dict
    - Evita NameError por variáveis fora da função
    """
    st.title("📑 Relatórios Gerenciais")

    # ---------- Carregar base ----------
    try:
        from src.repositories.pedidos import carregar_pedidos  # type: ignore
        df_base = carregar_pedidos(supabase, tenant_id)
    except Exception:
        df_base = pd.DataFrame()

    if df_base is None or not isinstance(df_base, pd.DataFrame) or df_base.empty:
        st.info("Sem dados de pedidos para o período/empresa selecionada.")
        return

    # ---------- Carregar vínculos e mapa de usuários ----------
    links = _try_load_links(supabase, tenant_id)
    dept_map = _links_to_dept_map(links)
    user_map = _try_load_user_map(supabase, tenant_id)

    df_base = _ensure_columns(df_base, dept_map)

    # ---------- Filtros ----------
    with st.sidebar:
        st.markdown("### 🎛️ Filtros do relatório")
        hoje = date.today()
        pad_ini = hoje - timedelta(days=30)
        dt_ini = st.date_input("Data inicial", value=pad_ini, key="rg_dt_ini")
        dt_fim = st.date_input("Data final", value=hoje, key="rg_dt_fim")

        # filtros textuais simples
        c_status = _col(df_base, "status", "situacao")
        c_dept = _col(df_base, "departamento", "dept", "department")
        c_frota = _col(df_base, "frota", "equipamento", "maquina")

        status_sel = None
        if c_status:
            opts = sorted([x for x in df_base[c_status].dropna().astype(str).unique().tolist() if x.strip()])
            status_sel = st.multiselect("Status", opts, default=[], key="rg_status")

        dept_sel = None
        if c_dept:
            opts = sorted([x for x in df_base[c_dept].dropna().astype(str).unique().tolist() if x.strip()])
            dept_sel = st.multiselect("Departamento", opts, default=[], key="rg_dept")

        frota_sel = None
        if c_frota:
            opts = sorted([x for x in df_base[c_frota].dropna().astype(str).unique().tolist() if x.strip()])
            frota_sel = st.multiselect("Frota", opts, default=[], key="rg_frota")

    # ---------- Aplicar filtros ----------
    df = _apply_date_filter(df_base, _as_date(dt_ini), _as_date(dt_fim))

    if c_status and status_sel:
        df = df[df[c_status].astype(str).isin(set(status_sel))].copy()
    if c_dept and dept_sel:
        df = df[df[c_dept].astype(str).isin(set(dept_sel))].copy()
    if c_frota and frota_sel:
        df = df[df[c_frota].astype(str).isin(set(frota_sel))].copy()

    # ---------- Colunas base ----------
    c_val = _col(df, "valor_total", "valor", "total", "valor_pedido")
    if not c_val:
        # cria valor 0 se não houver, para não quebrar
        df["valor_total"] = 0.0
        c_val = "valor_total"

    # nome gestor
    if "gestor_user_id" in df.columns:
        df["gestor_nome"] = df["gestor_user_id"].astype(str).map(lambda x: user_map.get(str(x), "")).replace("", "—")
    else:
        df["gestor_nome"] = "—"

    # ---------- KPIs ----------
    total = float(_to_num(df[c_val]).sum())
    qtd = int(len(df))
    _kpi_card_row([
        ("Total (R$)", f"{total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")),
        ("Pedidos", str(qtd)),
    ])

    st.markdown("")

    tab_g, tab_f, tab_d = st.tabs(["👤 Por Gestor", "🚜 Por Frota", "🏭 Por Departamento"])

    # ---------- Por Gestor ----------
    with tab_g:
        st.subheader("Gastos por Gestor")
        g = _group_sum(df, "gestor_nome", c_val)
        st.dataframe(g, use_container_width=True, hide_index=True)
        _download_csv_button(g, "gastos_por_gestor")

        with st.expander("🔎 Drill-down (selecionar gestor)"):
            gestores = g["gestor_nome"].tolist() if not g.empty else []
            sel = st.selectbox("Gestor", options=["(selecione)"] + gestores, key="rg_drill_gestor")
            if sel and sel != "(selecione)":
                df_sel = df[df["gestor_nome"].astype(str) == sel].copy()
                st.dataframe(df_sel, use_container_width=True, hide_index=True)
                _download_csv_button(df_sel, f"pedidos_gestor_{sel}".replace(" ", "_"))

    # ---------- Por Frota ----------
    with tab_f:
        st.subheader("Gastos por Frota")
        c_frota2 = _col(df, "frota", "equipamento", "maquina")
        if not c_frota2:
            st.info("Não encontrei coluna de Frota/Equipamento na base.")
        else:
            f = _group_sum(df, c_frota2, c_val).rename(columns={c_frota2: "frota"})
            st.dataframe(f, use_container_width=True, hide_index=True)
            _download_csv_button(f, "gastos_por_frota")

            with st.expander("🔎 Drill-down (selecionar frota)"):
                frotas = f["frota"].tolist() if not f.empty else []
                sel = st.selectbox("Frota", options=["(selecione)"] + frotas, key="rg_drill_frota")
                if sel and sel != "(selecione)":
                    df_sel = df[df[c_frota2].astype(str) == sel].copy()
                    st.dataframe(df_sel, use_container_width=True, hide_index=True)
                    _download_csv_button(df_sel, f"pedidos_frota_{sel}".replace(" ", "_"))

    # ---------- Por Departamento ----------
    with tab_d:
        st.subheader("Gastos por Departamento")
        c_dept2 = _col(df, "departamento", "dept", "department")
        if not c_dept2:
            st.info("Não encontrei coluna de Departamento na base.")
        else:
            d = _group_sum(df, c_dept2, c_val).rename(columns={c_dept2: "departamento"})
            st.dataframe(d, use_container_width=True, hide_index=True)
            _download_csv_button(d, "gastos_por_departamento")

            with st.expander("🔎 Drill-down (selecionar departamento)"):
                depts = d["departamento"].tolist() if not d.empty else []
                sel = st.selectbox("Departamento", options=["(selecione)"] + depts, key="rg_drill_dept")
                if sel and sel != "(selecione)":
                    df_sel = df[df[c_dept2].astype(str) == sel].copy()
                    st.dataframe(df_sel, use_container_width=True, hide_index=True)
                    _download_csv_button(df_sel, f"pedidos_dept_{sel}".replace(" ", "_"))
