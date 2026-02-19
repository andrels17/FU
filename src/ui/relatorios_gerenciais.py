from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st

from src.core.db import init_supabase_admin
from src.repositories.pedidos import carregar_pedidos
from src.utils.formatting import formatar_moeda_br
from src.services.relatorios_gastos import (
    FiltrosGastos,
    carregar_links_departamento_gestor,
    carregar_mapa_usuarios_tenant,
    filtrar_pedidos_base,
    gastos_por_departamento,
    gastos_por_frota,
    gastos_por_gestor,
)


# ============================
# Helpers (safe / formatting)
# ============================

def _date_defaults() -> Tuple[date, date]:
    hoje = date.today()
    return hoje - timedelta(days=30), hoje




def _cat_str(v: Any) -> str:
    """Força rótulo categórico (evita eixo numérico em ids como 1024, 5001)."""
    if v is None:
        return "(Sem código)"
    s = str(v).strip()
    return s if s else "(Sem código)"
def _as_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _share_percent(total: float, part: float) -> float:
    return (part / total * 100.0) if total else 0.0


def _download_name(prefix: str, dt_ini: date, dt_fim: date) -> str:
    return f"{prefix}_{dt_ini.isoformat()}_a_{dt_fim.isoformat()}.csv"


def _pill_style() -> None:
    st.markdown(
        """
        <style>
        div[data-baseweb="select"] > div { min-height: 38px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _premium_tabs_style() -> None:
    # premium tabs
    st.markdown(
        """
        <style>
        /* premium tabs */
        div[data-baseweb="tab-list"] { gap: 8px; }
        button[role="tab"] {
            padding: 10px 14px;
            border-radius: 999px;
            border: 1px solid rgba(49,51,63,0.18);
            background: rgba(255,255,255,0.04);
        }
        button[role="tab"][aria-selected="true"] {
            border: 1px solid rgba(49,51,63,0.32);
            background: rgba(255,255,255,0.10);
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _tabs_style() -> None:
    # Deixa as abas com visual mais premium (pills, borda, espaçamento)
    st.markdown(
        '''
        <style>
        /* Tabs container */
        div[data-baseweb="tab-list"]{
            gap: 10px;
            background: rgba(255,255,255,0.03);
            padding: 10px 10px 6px 10px;
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.06);
        }
        /* Tab */
        button[data-baseweb="tab"]{
            background: rgba(255,255,255,0.04);
            border-radius: 999px;
            padding: 10px 14px;
            border: 1px solid rgba(255,255,255,0.08);
            color: rgba(255,255,255,0.85);
            font-weight: 600;
        }
        /* Active tab */
        button[data-baseweb="tab"][aria-selected="true"]{
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.14);
        }
        /* Remove default underline indicator */
        div[data-baseweb="tab-highlight"]{ display:none; }
        </style>
        ''',
        unsafe_allow_html=True,
    )


def _plot_hbar_with_labels(df: pd.DataFrame, y_col: str, x_col: str, title: str, height: int = 420) -> None:
    """Gráfico de barras horizontal com rótulos (Plotly) e fallback."""
    if df is None or df.empty or y_col not in df.columns or x_col not in df.columns:
        st.caption("Sem dados para o gráfico.")
        return

    dfp = df.copy()
    # garante rótulos categóricos (evita eixo numérico para IDs)
    dfp[y_col] = dfp[y_col].astype(str)
    # rótulo BRL quando for total; senão, formata número simples
    if x_col == "total":
        dfp["_lbl"] = dfp[x_col].apply(lambda v: formatar_moeda_br(_as_float(v)))
    else:
        dfp["_lbl"] = dfp[x_col].apply(lambda v: f"{_as_float(v):,.0f}".replace(",", "."))

    try:
        import plotly.express as px  # type: ignore

        fig = px.bar(
            dfp,
            x=x_col,
            y=y_col,
            orientation="h",
            title=title,
            text="_lbl",
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        fig.update_yaxes(type="category")
        fig.update_layout(
            margin=dict(l=10, r=10, t=46, b=10),
            height=height,
            yaxis_title="",
            xaxis_title="",
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        st.bar_chart(dfp.set_index(y_col)[[x_col]], height=min(300, height))




def _reset_rg_filters() -> None:
    """Reseta filtros dos Relatórios Gerenciais (session_state)."""
    keys = [
        "rg_dt_ini", "rg_dt_fim", "rg_date_field_label", "rg_entregue_label",
        "rg_depts", "rg_frotas", "rg_roles_incluidos", "rg_busca_gestor",
        "rg_cmp_gestor", "rg_cmp_frota", "rg_cmp_dept",
        "rg_busca_frota", "rg_busca_dept",
        "rg_drill_gestor_nome", "rg_drill_frota", "rg_drill_dept",
        "rg_top_dept_insights",
    ]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]


def _actions_bar(df_base: pd.DataFrame, dt_ini: date, dt_fim: date, prefix: str = "relatorio") -> None:
    """Barra de ações rápidas (export / reset)."""
    with st.container(border=True):
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            csv = df_base.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Exportar base filtrada",
                csv,
                _download_name(f"{prefix}_base_filtrada", dt_ini, dt_fim),
                "text/csv",
                use_container_width=True,
                key=f"{prefix}_export_base",
            )
        with c2:
            if st.button("♻️ Reset filtros", use_container_width=True, key=f"{prefix}_reset"):
                _reset_rg_filters()
                st.rerun()
        with c3:
            st.caption("Dica: use os filtros na lateral e exporte a base filtrada para análises externas.")
def _init_filter_state() -> None:
    dt_ini_def, dt_fim_def = _date_defaults()
    st.session_state.setdefault("rg_dt_ini", dt_ini_def)
    st.session_state.setdefault("rg_dt_fim", dt_fim_def)
    st.session_state.setdefault("rg_date_field_label", "Solicitação")
    st.session_state.setdefault("rg_entregue_label", "Todos")
    st.session_state.setdefault("rg_depts", [])
    st.session_state.setdefault("rg_frotas", [])
    st.session_state.setdefault("rg_roles_incluidos", ["admin", "gestor"])
    st.session_state.setdefault("rg_busca_gestor", "")


def _build_filtros_from_state() -> Tuple[FiltrosGastos, date, date]:
    date_field_map = {
        "Solicitação": "data_solicitacao",
        "OC": "data_oc",
        "Entrega real": "data_entrega_real",
        "Criação": "criado_em",
    }
    dt_ini: date = st.session_state.get("rg_dt_ini")
    dt_fim: date = st.session_state.get("rg_dt_fim")
    date_field = date_field_map.get(st.session_state.get("rg_date_field_label", "Solicitação"), "data_solicitacao")

    entregue_opt = st.session_state.get("rg_entregue_label", "Todos")
    entregue = None
    if entregue_opt == "Entregues":
        entregue = True
    elif entregue_opt == "Pendentes":
        entregue = False

    filtros = FiltrosGastos(
        dt_ini=dt_ini,
        dt_fim=dt_fim,
        date_field=date_field,
        entregue=entregue,
        departamentos=list(st.session_state.get("rg_depts") or []),
        cod_equipamentos=list(st.session_state.get("rg_frotas") or []),
    )
    return filtros, dt_ini, dt_fim


def _periodo_anterior(dt_ini: date, dt_fim: date) -> Tuple[date, date]:
    if not dt_ini or not dt_fim or dt_fim < dt_ini:
        return dt_ini, dt_fim
    dias = (dt_fim - dt_ini).days
    dt_fim_prev = dt_ini - timedelta(days=1)
    dt_ini_prev = dt_fim_prev - timedelta(days=dias)
    return dt_ini_prev, dt_fim_prev


def _evolucao_semanal(df_base: pd.DataFrame, date_col: str) -> pd.DataFrame:
    if df_base is None or df_base.empty or date_col not in df_base.columns:
        return pd.DataFrame(columns=["data", "total"])

    s = pd.to_datetime(df_base[date_col], errors="coerce")
    tmp = df_base.copy()
    tmp["_data"] = s
    tmp = tmp.dropna(subset=["_data"])
    if tmp.empty:
        return pd.DataFrame(columns=["data", "total"])

    tmp["_valor"] = pd.to_numeric(tmp.get("valor_total", 0), errors="coerce").fillna(0)
    out = tmp.groupby(pd.Grouper(key="_data", freq="W"))["_valor"].sum().reset_index()
    return out.rename(columns={"_data": "data", "_valor": "total"})


def _cols_detail(df: pd.DataFrame, date_field: str) -> List[str]:
    prefer = [
        date_field,
        "id",
        "nr_solicitacao",
        "nr_oc",
        "departamento",
        "cod_equipamento",
        "cod_material",
        "descricao",
        "qtde_solicitada",
        "qtde_entregue",
        "qtde_pendente",
        "status",
        "entregue",
        "valor_total",
        "fornecedor_nome",
    ]
    return [c for c in prefer if c in df.columns]


def _top_selector(prefix: str) -> int | None:
    opt = st.radio(
        "Exibir",
        ["Top 10", "Top 20", "Top 50", "Todos"],
        horizontal=True,
        key=f"{prefix}_top",
        index=0,
    )
    return {"Top 10": 10, "Top 20": 20, "Top 50": 50}.get(opt, None)


def _render_common_actions(df_out: pd.DataFrame, filename_prefix: str, dt_ini: date, dt_fim: date) -> None:
    csv = df_out.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Baixar CSV",
        csv,
        _download_name(filename_prefix, dt_ini, dt_fim),
        "text/csv",
                use_container_width=True,
                key=f"{prefix}_export_base",
            )


def _links_to_dept_map_df(links: Any) -> pd.DataFrame:
    """
    Normaliza links para DataFrame com colunas: departamento, gestor_user_id.
    O serviço gastos_por_gestor exige DataFrame. 
    """
    if links is None:
        return pd.DataFrame(columns=["departamento", "gestor_user_id"])
    if isinstance(links, pd.DataFrame):
        if links.empty:
            return pd.DataFrame(columns=["departamento", "gestor_user_id"])
        cols = set(links.columns)
        if {"departamento", "gestor_user_id"}.issubset(cols):
            return links[["departamento", "gestor_user_id"]].copy()
        return pd.DataFrame(links.to_dict("records")).reindex(columns=["departamento", "gestor_user_id"])
    if isinstance(links, dict):
        rows = [{"departamento": str(k).strip(), "gestor_user_id": v} for k, v in links.items() if str(k).strip()]
        return pd.DataFrame(rows).reindex(columns=["departamento", "gestor_user_id"])
    if isinstance(links, list):
        rows = [r for r in links if isinstance(r, dict)]
        return pd.DataFrame(rows).reindex(columns=["departamento", "gestor_user_id"])
    return pd.DataFrame(columns=["departamento", "gestor_user_id"])


def _ensure_user_map_df(user_map: Any) -> pd.DataFrame:
    """
    Normaliza user_map para DataFrame com colunas:
      user_id, nome, email, whatsapp, role
    O serviço gastos_por_gestor usa .empty e merge, então precisa DF. 
    """
    if user_map is None:
        return pd.DataFrame(columns=["user_id", "nome", "email", "whatsapp", "role"])
    if isinstance(user_map, pd.DataFrame):
        df = user_map.copy()
        if "user_id" not in df.columns and "id" in df.columns:
            df = df.rename(columns={"id": "user_id"})
        for c in ["user_id", "nome", "email", "whatsapp", "role"]:
            if c not in df.columns:
                df[c] = None
        return df[["user_id", "nome", "email", "whatsapp", "role"]].copy()
    if isinstance(user_map, dict):
        rows = []
        for uid, v in user_map.items():
            if isinstance(v, dict):
                rows.append(
                    {
                        "user_id": uid,
                        "nome": v.get("nome") or v.get("name"),
                        "email": v.get("email"),
                        "whatsapp": v.get("whatsapp"),
                        "role": v.get("role"),
                    }
                )
            else:
                rows.append({"user_id": uid, "nome": str(v), "email": None, "whatsapp": None, "role": None})
        return pd.DataFrame(rows).reindex(columns=["user_id", "nome", "email", "whatsapp", "role"])
    if isinstance(user_map, list):
        rows = [r for r in user_map if isinstance(r, dict)]
        df = pd.DataFrame(rows)
        if "user_id" not in df.columns and "id" in df.columns:
            df = df.rename(columns={"id": "user_id"})
        for c in ["user_id", "nome", "email", "whatsapp", "role"]:
            if c not in df.columns:
                df[c] = None
        return df[["user_id", "nome", "email", "whatsapp", "role"]].copy()
    return pd.DataFrame(columns=["user_id", "nome", "email", "whatsapp", "role"])


def _safe_gastos_por_gestor(df_base: pd.DataFrame, links: Any, user_map: Any) -> pd.DataFrame:
    """
    Chama o serviço gastos_por_gestor com os tipos corretos (DataFrames). 
    """
    links_df = _links_to_dept_map_df(links)
    user_df = _ensure_user_map_df(user_map)
    return gastos_por_gestor(df_base, links_df, user_df)


def _add_prev_delta(df_now: pd.DataFrame, df_prev_group: pd.DataFrame, key_col: str) -> pd.DataFrame:
    if df_now is None or df_now.empty:
        return df_now
    if df_prev_group is None or df_prev_group.empty or key_col not in df_prev_group.columns:
        df_now["prev_total"] = 0.0
        df_now["delta_pct"] = 0.0
        return df_now

    prev = df_prev_group[[key_col, "total"]].copy().rename(columns={"total": "prev_total"})
    out = df_now.merge(prev, how="left", on=key_col)

    out["prev_total"] = pd.to_numeric(out.get("prev_total", 0), errors="coerce").fillna(0.0)
    out["total"] = pd.to_numeric(out.get("total", 0), errors="coerce").fillna(0.0)
    out["delta_pct"] = out.apply(
        lambda r: ((r["total"] - r["prev_total"]) / r["prev_total"] * 100.0) if r["prev_total"] else 0.0,
        axis=1,
    )
    return out


# ============================
# Main entry
# ============================

def render_relatorios_gerenciais(_supabase, tenant_id: str) -> None:
    st.title("📈 Relatórios Gerenciais")
    st.caption("Gestores por vínculo de departamento (gestor_departamentos) — não depende de quem lançou o pedido.")

    if not tenant_id:
        st.error("Tenant não identificado.")
        st.stop()

    _init_filter_state()
    _pill_style()
    _tabs_style()

    # Admin (service role) para leituras que podem sofrer RLS
    try:
        supabase_admin = init_supabase_admin()
    except Exception:
        supabase_admin = None

    # ===== Carregar pedidos =====
    with st.spinner("Carregando pedidos..."):
        df_pedidos = carregar_pedidos(_supabase, tenant_id=tenant_id)

    if df_pedidos is None or df_pedidos.empty:
        st.info("Nenhum pedido encontrado para este tenant.")
        st.stop()

    # opções para filtros
    df_tmp = df_pedidos.copy()
    for col in ["departamento", "cod_equipamento"]:
        if col in df_tmp.columns:
            df_tmp[col] = df_tmp[col].fillna("").astype(str).str.strip()
        else:
            df_tmp[col] = ""

    dept_opts = sorted([d for d in df_tmp["departamento"].unique().tolist() if d])
    frota_opts = sorted([f for f in df_tmp["cod_equipamento"].unique().tolist() if f])

    # ===== links + user_map (DataFrames, como o serviço espera) =====
    with st.spinner("Carregando vínculos e usuários..."):
        links_df = carregar_links_departamento_gestor(supabase_admin or _supabase, tenant_id=tenant_id)
        user_df = carregar_mapa_usuarios_tenant(supabase_admin or _supabase, tenant_id=tenant_id)

    links_df = _links_to_dept_map_df(links_df)
    user_df = _ensure_user_map_df(user_df)

    # dict dept->gestor para drilldown (rápido)
    dept_map: Dict[str, str] = {}
    if not links_df.empty:
        for _, r in links_df.iterrows():
            d = str(r.get("departamento") or "").strip()
            gid = r.get("gestor_user_id")
            if d and pd.notna(gid):
                dept_map[d] = str(gid)

    # ===== Sidebar =====
    with st.sidebar:
        st.markdown("### 🧾 Filtros do relatório")

        p1, p2, p3, p4 = st.columns(4)
        if p1.button("7d", use_container_width=True):
            hoje = date.today()
            st.session_state["rg_dt_ini"] = hoje - timedelta(days=6)
            st.session_state["rg_dt_fim"] = hoje
        if p2.button("30d", use_container_width=True):
            hoje = date.today()
            st.session_state["rg_dt_ini"] = hoje - timedelta(days=29)
            st.session_state["rg_dt_fim"] = hoje
        if p3.button("90d", use_container_width=True):
            hoje = date.today()
            st.session_state["rg_dt_ini"] = hoje - timedelta(days=89)
            st.session_state["rg_dt_fim"] = hoje
        if p4.button("Mês", use_container_width=True):
            hoje = date.today()
            st.session_state["rg_dt_ini"] = hoje.replace(day=1)
            st.session_state["rg_dt_fim"] = hoje

        st.date_input("Data inicial", value=st.session_state["rg_dt_ini"], key="rg_dt_ini")
        st.date_input("Data final", value=st.session_state["rg_dt_fim"], key="rg_dt_fim")

        st.selectbox(
            "Campo de data",
            ["Solicitação", "OC", "Entrega real", "Criação"],
            index=["Solicitação", "OC", "Entrega real", "Criação"].index(st.session_state.get("rg_date_field_label", "Solicitação")),
            key="rg_date_field_label",
        )

        st.selectbox(
            "Situação",
            ["Todos", "Entregues", "Pendentes"],
            index=["Todos", "Entregues", "Pendentes"].index(st.session_state.get("rg_entregue_label", "Todos")),
            key="rg_entregue_label",
        )

        st.multiselect(
            "Departamentos",
            options=dept_opts,
            default=[x for x in (st.session_state.get("rg_depts") or []) if x in dept_opts],
            key="rg_depts",
        )

        st.multiselect(
            "Frotas (cód. equipamento)",
            options=frota_opts,
            default=[x for x in (st.session_state.get("rg_frotas") or []) if x in frota_opts],
            key="rg_frotas",
        )

        st.divider()
        st.markdown("### 👥 Filtro de Pessoas (aba Gestor)")

        roles = sorted([str(x).strip().lower() for x in user_df["role"].dropna().unique().tolist() if str(x).strip()]) if "role" in user_df.columns else []
        if not roles:
            roles = ["admin", "gestor", "user"]

        st.multiselect(
            "Roles incluídos",
            options=roles,
            default=[r for r in (st.session_state.get("rg_roles_incluidos") or []) if r in roles] or ["admin", "gestor"],
            key="rg_roles_incluidos",
        )
        st.text_input("Buscar gestor (nome/e-mail)", value=st.session_state.get("rg_busca_gestor", ""), key="rg_busca_gestor")

        st.caption(f"Deptos vinculados: {len(dept_map)} · Usuários no mapa: {len(user_df)}")

    # ===== Aplicar filtros =====
    filtros, dt_ini, dt_fim = _build_filtros_from_state()
    df_base = filtrar_pedidos_base(df_pedidos, filtros=filtros)

    if df_base is None or df_base.empty:
        st.warning("Nenhum pedido no filtro atual. Ajuste o período/filtros.")
        st.stop()

    total_geral = _as_float(df_base.get("valor_total", pd.Series(dtype=float)).fillna(0).sum())
    qtd_geral = int(len(df_base))
    ticket = (total_geral / qtd_geral) if qtd_geral else 0.0

    # Período anterior (comparação)
    dt_ini_prev, dt_fim_prev = _periodo_anterior(dt_ini, dt_fim)
    filtros_prev = FiltrosGastos(
        dt_ini=dt_ini_prev,
        dt_fim=dt_fim_prev,
        date_field=filtros.date_field,
        entregue=filtros.entregue,
        departamentos=filtros.departamentos,
        cod_equipamentos=filtros.cod_equipamentos,
    )
    df_prev = filtrar_pedidos_base(df_pedidos, filtros=filtros_prev)
    total_prev = _as_float(df_prev.get("valor_total", pd.Series(dtype=float)).fillna(0).sum()) if df_prev is not None and not df_prev.empty else 0.0
    delta_pct = ((total_geral - total_prev) / total_prev * 100.0) if total_prev else 0.0

    # ===== Menu de abas (no início) =====
    tab_resumo, tab_gestor, tab_frota, tab_dept = st.tabs(["📌 Resumo", "👤 Gestor", "🚜 Frota", "🏢 Departamento"]) 


    with tab_resumo:
        _actions_bar(df_base, dt_ini, dt_fim, prefix='rg_resumo')


            # ===== Resumo =====
            with st.container(border=True):
                st.markdown("### 📌 Resumo do período aplicado")
                a1, a2, a3, a4 = st.columns(4)
                a1.metric("Pedidos", qtd_geral)
                a2.metric("Gasto total", formatar_moeda_br(total_geral), f"{delta_pct:.1f}% vs anterior" if total_prev else None)
                a3.metric("Período anterior", formatar_moeda_br(total_prev))
                a4.metric("Ticket médio", formatar_moeda_br(ticket))
                st.caption(
                    f"Período: **{dt_ini.strftime('%d/%m/%Y')}** a **{dt_fim.strftime('%d/%m/%Y')}** · "
                    f"Data: **{filtros.date_field}** · Situação: **{st.session_state.get('rg_entregue_label','Todos')}**"
                )

            with st.container(border=True):
                st.markdown("### 📈 Evolução do gasto (semanal)")
                df_evol = _evolucao_semanal(df_base, filtros.date_field)
                if df_evol.empty:
                    st.caption("Sem dados suficientes para a evolução semanal.")
                else:
                    st.line_chart(df_evol.set_index("data")["total"])

            st.divider()

    
    # ===== Governança estrutural + Performance global =====
    with st.container(border=True):
        st.markdown("### 🧭 Governança estrutural")
        # Departamentos presentes nos pedidos do período aplicado
        depts_base = set(df_base.get("departamento", pd.Series(dtype=str)).dropna().astype(str).str.strip().unique())
        depts_base = {d for d in depts_base if d}
        depts_vinculados = set(dept_map.keys())
        depts_sem_gestor = sorted(list(depts_base - depts_vinculados))

        # Gestores (no mapa) sem departamento vinculado
        gestores_ids = set(user_df.get("user_id", pd.Series(dtype=str)).dropna().astype(str).unique()) if "user_id" in user_df.columns else set()
        gestores_vinculados = set(str(v) for v in dept_map.values())
        gestores_sem_dept = sorted(list(gestores_ids - gestores_vinculados))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Departamentos no período", len(depts_base))
        c2.metric("Deptos com gestor", len(depts_base & depts_vinculados))
        c3.metric("Deptos sem gestor", len(depts_sem_gestor))
        c4.metric("Gestores sem depto", len(gestores_sem_dept))

        colA, colB = st.columns(2)
        with colA:
            if depts_sem_gestor:
                st.warning("Departamentos sem gestor vinculado")
                st.dataframe(pd.DataFrame({"departamento": depts_sem_gestor}), use_container_width=True, hide_index=True)
            else:
                st.success("Todos os departamentos do período têm gestor vinculado ✅")
        with colB:
            if gestores_sem_dept:
                st.warning("Gestores no tenant sem departamento vinculado")
                if "user_id" in user_df.columns:
                    df_gs = user_df[user_df["user_id"].astype(str).isin(gestores_sem_dept)].copy()
                    cols = [c for c in ["nome", "email", "role", "user_id"] if c in df_gs.columns]
                    st.dataframe(df_gs[cols], use_container_width=True, hide_index=True)
                else:
                    st.write(gestores_sem_dept)
            else:
                st.success("Sem gestores “órfãos” de departamento ✅")

    # Performance operacional (global)
    with st.container(border=True):
        st.markdown("### ⚙️ Performance operacional (visão geral)")
        col1, col2, col3 = st.columns(3)

        pct_atraso = None
        if "atrasado" in df_base.columns:
            s = pd.to_numeric(df_base["atrasado"], errors="coerce")
            if s.notna().any():
                pct_atraso = float(s.fillna(0).mean() * 100)

        pct_pendente = None
        if "entregue" in df_base.columns:
            s = df_base["entregue"]
            # entregue pode vir bool, 't/f', 0/1…
            sb = s.apply(lambda x: bool(x) if isinstance(x, bool) else (str(x).strip().lower() in ("true","t","1","sim","s","yes")))
            pct_pendente = float((~sb).mean() * 100) if len(sb) else None

        # lead time (dias) se houver datas
        lt_med = None
        if "data_solicitacao" in df_base.columns and "data_entrega_real" in df_base.columns:
            ds = pd.to_datetime(df_base["data_solicitacao"], errors="coerce")
            de = pd.to_datetime(df_base["data_entrega_real"], errors="coerce")
            lt = (de - ds).dt.days
            lt = lt[lt.notna() & (lt >= 0)]
            if len(lt) > 0:
                lt_med = float(lt.median())

        col1.metric("% Atraso", f"{pct_atraso:.1f}%" if pct_atraso is not None else "—")
        col2.metric("% Pendentes", f"{pct_pendente:.1f}%" if pct_pendente is not None else "—")
        col3.metric("Lead time mediano", f"{lt_med:.0f} dias" if lt_med is not None else "—")
    # (tabs moved to the beginning)
    # ===== Aba Gestor =====
    with tab_gestor:
        _actions_bar(df_base, dt_ini, dt_fim, prefix='rg_gestor')

        st.subheader("Gastos por Gestor")
        topn = _top_selector("rg_gestor")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_gestor")

        # Aqui é o ponto: usa vínculo dept->gestor (serviço) 
        df_g = _safe_gastos_por_gestor(df_base, links_df, user_df)

        if df_g.empty:
            st.info("Sem dados por Gestor. Verifique se há vínculos em gestor_departamentos para os departamentos filtrados.")
            st.stop()

        # adiciona role via user_df
        um_role = user_df.copy()
        if "user_id" in um_role.columns:
            um_role = um_role.rename(columns={"user_id": "gestor_user_id"})
        if "role" not in um_role.columns:
            um_role["role"] = None
        df_g = df_g.merge(um_role[["gestor_user_id", "role"]].rename(columns={"role": "gestor_role"}), on="gestor_user_id", how="left")

        # filtro roles
        roles_incl = set([(r or "").lower() for r in (st.session_state.get("rg_roles_incluidos") or [])])
        if roles_incl and "gestor_role" in df_g.columns:
            df_g = df_g[df_g["gestor_role"].fillna("").astype(str).str.lower().isin(roles_incl)]

        # busca
        q = (st.session_state.get("rg_busca_gestor") or "").strip().lower()
        if q:
            df_g = df_g[
                df_g["gestor_nome"].fillna("").astype(str).str.lower().str.contains(q)
                | df_g["gestor_email"].fillna("").astype(str).str.lower().str.contains(q)
            ]

        if df_g.empty:
            st.warning("Nenhum gestor após filtros de pessoas (roles/busca).")
            st.stop()

        # comparação
        if comparar:
            df_g_prev = _safe_gastos_por_gestor(df_prev, links_df, user_df) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if not df_g_prev.empty:
                df_g = _add_prev_delta(df_g, df_g_prev, "gestor_user_id")
            else:
                df_g["prev_total"] = 0.0
                df_g["delta_pct"] = 0.0
        else:
            df_g["prev_total"] = 0.0
            df_g["delta_pct"] = 0.0

        # KPIs
        with st.container(border=True):
            g1, g2, g3 = st.columns(3)
            g1.metric("Gestores no período", int(df_g["gestor_user_id"].nunique()))
            g2.metric("Gasto total", formatar_moeda_br(_as_float(df_g["total"].sum())))
            g3.metric("Pedidos", int(_as_float(df_g["qtd_pedidos"].sum())) if "qtd_pedidos" in df_g.columns else "-")

        df_g = df_g.copy()
        df_g["participacao_pct"] = df_g["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_g = df_g.sort_values("total", ascending=False)


        with st.expander("🧠 Insights avançados", expanded=False):
            # ===== Inteligência gerencial (ranking + destaques) =====
            with st.container(border=True):
                st.markdown("### 🏆 Ranking executivo")
                top3 = df_g.head(3).copy()
                cols = st.columns(3)

                for i in range(3):
                    if i >= len(top3):
                        cols[i].metric(f"#{i+1}", "—")
                        continue

                    r = top3.iloc[i]
                    delta_txt = None
                    if "delta_pct" in df_g.columns:
                        delta_txt = f"{_as_float(r.get('delta_pct')):.1f}%"

                    cols[i].metric(
                        f"#{i+1} {r.get('gestor_nome','(Sem nome)')}",
                        formatar_moeda_br(_as_float(r.get("total"))),
                        f"{_as_float(r.get('participacao_pct')):.1f}% do total"
                        + (f" · Δ {delta_txt}" if delta_txt else ""),
                    )

            # ===== Destaques (cresceu / caiu) =====
            if "delta_pct" in df_g.columns:
                alta = df_g[df_g["delta_pct"] > 20].copy()
                queda = df_g[df_g["delta_pct"] < -20].copy()

                if not alta.empty:
                    with st.container(border=True):
                        st.markdown("#### 📈 Crescimentos relevantes (> 20%)")
                        st.dataframe(
                            alta[["gestor_nome", "total", "prev_total", "delta_pct"]].assign(
                                total=lambda x: x["total"].map(lambda v: formatar_moeda_br(_as_float(v))),
                                prev_total=lambda x: x["prev_total"].map(lambda v: formatar_moeda_br(_as_float(v))),
                                delta_pct=lambda x: x["delta_pct"].map(lambda v: f"{_as_float(v):.1f}%"),
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                if not queda.empty:
                    with st.container(border=True):
                        st.markdown("#### 📉 Quedas relevantes (< -20%)")
                        st.dataframe(
                            queda[["gestor_nome", "total", "prev_total", "delta_pct"]].assign(
                                total=lambda x: x["total"].map(lambda v: formatar_moeda_br(_as_float(v))),
                                prev_total=lambda x: x["prev_total"].map(lambda v: formatar_moeda_br(_as_float(v))),
                                delta_pct=lambda x: x["delta_pct"].map(lambda v: f"{_as_float(v):.1f}%"),
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

            # ===== Insight automático =====
            try:
                top = df_g.iloc[0]
                st.info(
                    f"🧠 No período aplicado, **{top.get('gestor_nome','(Sem nome)')}** foi o gestor com maior impacto, "
                    f"respondendo por **{_as_float(top.get('participacao_pct')):.1f}%** do gasto total."
                )
            except Exception:
                pass
            # (Top Departamentos movido para a aba Departamento)
        _render_common_actions(df_g, "gastos_por_gestor", dt_ini, dt_fim)

    # ===== Aba Frota =====
    with tab_frota:
        _actions_bar(df_base, dt_ini, dt_fim, prefix='rg_frota')

        st.subheader("Gastos por Frota (cód. equipamento)")
        topn = _top_selector("rg_frota")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_frota")

        df_f = gastos_por_frota(df_base)
        if df_f.empty:
            st.info("Sem dados para o agrupamento por Frota (cod_equipamento).")
            st.stop()

        if comparar:
            df_f_prev = gastos_por_frota(df_prev) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if not df_f_prev.empty and "cod_equipamento" in df_f.columns:
                df_f = _add_prev_delta(df_f, df_f_prev, "cod_equipamento")
            else:
                df_f["prev_total"] = 0.0
                df_f["delta_pct"] = 0.0
        else:
            df_f["prev_total"] = 0.0
            df_f["delta_pct"] = 0.0

        df_f = df_f.copy()
        df_f["participacao_pct"] = df_f["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_f = df_f.sort_values("total", ascending=False)

        df_plot = df_f.head(topn) if topn else df_f
        df_plot = df_plot.copy()
        if 'cod_equipamento' in df_plot.columns:
            df_plot['frota_label'] = df_plot['cod_equipamento'].map(_cat_str)
        else:
            df_plot['frota_label'] = '(Sem código)'
        _plot_hbar_with_labels(df_plot, y_col="frota_label", x_col="total", title="Top frotas por gasto", height=420)

        df_show = df_f.copy()
        df_show["Frota"] = df_show["cod_equipamento"].fillna("(Sem código)").astype(str)
        df_show["Pedidos"] = df_show.get("qtd_pedidos", 0).fillna(0).astype(int)
        df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
        df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{_as_float(x):.1f}%")

        cols = ["Frota", "Pedidos", "Total", "% do total"]
        if comparar:
            df_show["Anterior"] = df_show["prev_total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
            df_show["Δ%"] = df_show["delta_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
            cols = ["Frota", "Pedidos", "Total", "Anterior", "Δ%", "% do total"]

        st.dataframe(df_show[cols], use_container_width=True, hide_index=True)
        _render_common_actions(df_f, "gastos_por_frota", dt_ini, dt_fim)

    # ===== Aba Departamento =====
    with tab_dept:
        _actions_bar(df_base, dt_ini, dt_fim, prefix='rg_dept')

        st.subheader("Gastos por Departamento")

        with st.expander("🧠 Insights (Departamento)", expanded=False):
            with st.container(border=True):
                st.markdown("#### 🏢 Top Departamentos (gasto)")
                tmp = df_base.copy()
                if "departamento" not in tmp.columns:
                    st.caption("Sem coluna 'departamento' na base.")
                else:
                    tmp["departamento"] = tmp["departamento"].fillna("").astype(str).str.strip()
                    tmp = tmp[tmp["departamento"].astype(str).str.strip() != ""]
                    tmp["_valor"] = pd.to_numeric(tmp.get("valor_total", 0), errors="coerce").fillna(0.0)
                    dept_total = tmp.groupby("departamento")["_valor"].sum().sort_values(ascending=False)
                    if dept_total.empty:
                        st.caption("Sem dados suficientes para listar departamentos.")
                    else:
                        top_n = st.slider("Top N departamentos", min_value=5, max_value=30, value=10, step=5, key="rg_top_dept_tab")
                        dept_top = dept_total.head(top_n).reset_index()
                        dept_top.columns = ["label", "total"]
                        dept_top["% do total"] = dept_top["total"].apply(lambda v: f"{_share_percent(total_geral, _as_float(v)):.1f}%")
                        dept_top["Total"] = dept_top["total"].apply(lambda v: formatar_moeda_br(_as_float(v)))

                        try:
                            _plot_hbar_with_labels(
                                dept_top,
                                y_col="label",
                                x_col="total",
                                title=f"Top {top_n} Departamentos — Gasto",
                                value_fmt="brl",
                            )
                        except Exception:
                            st.bar_chart(dept_top.set_index("label")[["total"]], height=260)

                        st.dataframe(
                            dept_top[["label", "Total", "% do total"]].rename(columns={"label": "Departamento"}),
                            use_container_width=True,
                            hide_index=True,
                        )

        topn = _top_selector("rg_dept")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_dept")

        df_d = gastos_por_departamento(df_base)
        if df_d.empty:
            st.info("Sem dados para o agrupamento por Departamento.")
            st.stop()

        if comparar:
            df_d_prev = gastos_por_departamento(df_prev) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if not df_d_prev.empty and "departamento" in df_d.columns:
                df_d = _add_prev_delta(df_d, df_d_prev, "departamento")
            else:
                df_d["prev_total"] = 0.0
                df_d["delta_pct"] = 0.0
        else:
            df_d["prev_total"] = 0.0
            df_d["delta_pct"] = 0.0

        df_d = df_d.copy()
        df_d["participacao_pct"] = df_d["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_d = df_d.sort_values("total", ascending=False)

        df_plot = df_d.head(topn) if topn else df_d
        _plot_hbar_with_labels(df_plot, y_col="departamento", x_col="total", title="Top departamentos por gasto", height=420)

        df_show = df_d.copy()
        df_show["Departamento"] = df_show["departamento"].fillna("(Sem dept)").astype(str)
        df_show["Pedidos"] = df_show.get("qtd_pedidos", 0).fillna(0).astype(int)
        df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
        df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{_as_float(x):.1f}%")

        cols = ["Departamento", "Pedidos", "Total", "% do total"]
        if comparar:
            df_show["Anterior"] = df_show["prev_total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
            df_show["Δ%"] = df_show["delta_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
            cols = ["Departamento", "Pedidos", "Total", "Anterior", "Δ%", "% do total"]

        st.dataframe(df_show[cols], use_container_width=True, hide_index=True)
        _render_common_actions(df_d, "gastos_por_departamento", dt_ini, dt_fim)
