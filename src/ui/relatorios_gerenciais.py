from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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



def _safe_gastos_por_gestor(df_base, links, user_map):
    """Compatibilidade: tenta diferentes assinaturas de gastos_por_gestor()."""
    try:
        return gastos_por_gestor(df_base, links=links, user_map=user_map)
    except TypeError:
        pass
    try:
        return gastos_por_gestor(df_base, links, user_map)
    except TypeError:
        pass
    try:
        return gastos_por_gestor(df_base, links)
    except TypeError:
        pass
    # fallback: tenta passar só um dict dept->gestor se existir
    try:
        mapa = { (l.get("departamento") or "").strip(): l.get("gestor_user_id") for l in (links or []) if (l.get("departamento") or "").strip() }
        return gastos_por_gestor(df_base, mapa)
    except TypeError:
        # última tentativa: sem filtros adicionais
        return gastos_por_gestor(df_base)


def _date_defaults() -> tuple[date, date]:
    hoje = date.today()
    ini = hoje - timedelta(days=30)
    return ini, hoje


def _as_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _share_percent(total: float, part: float) -> float:
    if not total:
        return 0.0
    return (part / total) * 100.0


def _download_name(prefix: str, dt_ini: date, dt_fim: date) -> str:
    return f"{prefix}_{dt_ini.isoformat()}_a_{dt_fim.isoformat()}.csv"


def _init_filter_state():
    dt_ini_def, dt_fim_def = _date_defaults()
    st.session_state.setdefault("rg_dt_ini", dt_ini_def)
    st.session_state.setdefault("rg_dt_fim", dt_fim_def)
    st.session_state.setdefault("rg_date_field_label", "Solicitação")
    st.session_state.setdefault("rg_entregue_label", "Todos")
    st.session_state.setdefault("rg_depts", [])
    st.session_state.setdefault("rg_frotas", [])
    st.session_state.setdefault("rg_applied", False)


def _build_filtros_from_state() -> tuple[FiltrosGastos, date, date]:
    date_field_map = {
        "Solicitação": "data_solicitacao",
        "OC": "data_oc",
        "Entrega real": "data_entrega_real",
        "Criação": "criado_em",
    }
    dt_ini = st.session_state.get("rg_dt_ini")
    dt_fim = st.session_state.get("rg_dt_fim")
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


def _pill_style():
    # micro UX: compacta multiselects
    st.markdown(
        """
        <style>
        div[data-baseweb="select"] > div { min-height: 38px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_relatorios_gerenciais(_supabase, tenant_id: str):
    st.title("📈 Relatórios Gerenciais")
    st.caption("Visão de gastos por Gestor, Frota (cód. equipamento) e Departamento.")

    if not tenant_id:
        st.error("Tenant não identificado.")
        st.stop()

    _init_filter_state()
    _pill_style()

    # Admin (service role) para leituras que podem sofrer RLS
    try:
        supabase_admin = init_supabase_admin()
    except Exception:
        supabase_admin = None

    # ===== Carregar pedidos uma vez (base para filtros + análise) =====
    with st.spinner("Carregando pedidos..."):
        df_pedidos = carregar_pedidos(_supabase, tenant_id=tenant_id)

    if df_pedidos is None or df_pedidos.empty:
        st.info("Nenhum pedido encontrado para este tenant.")
        st.stop()

    # Opções de filtros (evita repetir)
    df_tmp = df_pedidos.copy()
    for col in ["departamento", "cod_equipamento"]:
        if col in df_tmp.columns:
            df_tmp[col] = df_tmp[col].fillna("").astype(str).str.strip()
        else:
            df_tmp[col] = ""

    dept_opts = sorted([d for d in df_tmp["departamento"].unique().tolist() if d])
    frota_opts = sorted([f for f in df_tmp["cod_equipamento"].unique().tolist() if f])

    # ===== Carregar vínculos e mapa de usuários (1x) =====
    with st.spinner("Carregando vínculos e usuários..."):
        links = carregar_links_departamento_gestor(supabase_admin or _supabase, tenant_id=tenant_id)
        user_map = carregar_mapa_usuarios_tenant(supabase_admin or _supabase, tenant_id=tenant_id)

    # ===== Aplicar filtros (estado aplicado) =====
    filtros, dt_ini, dt_fim = _build_filtros_from_state()

    # Dataset base já filtrado (serve para KPIs + abas)
    df_base = filtrar_pedidos_base(df_pedidos, filtros=filtros)

    total_geral = _as_float(df_base.get("valor_total", pd.Series(dtype=float)).fillna(0).sum()) if not df_base.empty else 0.0
    qtd_geral = int(len(df_base)) if not df_base.empty else 0
    ticket = (total_geral / qtd_geral) if qtd_geral else 0.0

    # ===== Resumo primeiro (como você pediu) =====
    with st.container(border=True):
        st.markdown("### 📌 Resumo do período aplicado")
        a1, a2, a3 = st.columns(3)
        a1.metric("Pedidos", qtd_geral)
        a2.metric("Gasto total", formatar_moeda_br(total_geral))
        a3.metric("Ticket médio", formatar_moeda_br(ticket))

        st.caption(
            f"Período: **{dt_ini.strftime('%d/%m/%Y')}** a **{dt_fim.strftime('%d/%m/%Y')}** · "
            f"Data: **{filtros.date_field}** · Situação: **{st.session_state.get('rg_entregue_label','Todos')}**"
        )

    # ===== Filtros abaixo do resumo (sempre visíveis) =====
    with st.container(border=True):
        st.markdown("### 🔎 Filtros")
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        with c1:
            st.date_input("Data inicial", value=st.session_state["rg_dt_ini"], key="rg_dt_ini")
        with c2:
            st.date_input("Data final", value=st.session_state["rg_dt_fim"], key="rg_dt_fim")
        with c3:
            st.selectbox(
                "Campo de data",
                ["Solicitação", "OC", "Entrega real", "Criação"],
                index=["Solicitação", "OC", "Entrega real", "Criação"].index(st.session_state.get("rg_date_field_label", "Solicitação")),
                key="rg_date_field_label",
            )
        with c4:
            st.selectbox(
                "Situação",
                ["Todos", "Entregues", "Pendentes"],
                index=["Todos", "Entregues", "Pendentes"].index(st.session_state.get("rg_entregue_label", "Todos")),
                key="rg_entregue_label",
            )

        d1, d2, d3 = st.columns([2, 2, 1])
        with d1:
            st.multiselect(
                "Departamentos",
                options=dept_opts,
                default=[x for x in (st.session_state.get("rg_depts") or []) if x in dept_opts],
                key="rg_depts",
            )
        with d2:
            st.multiselect(
                "Frotas (cód. equipamento)",
                options=frota_opts,
                default=[x for x in (st.session_state.get("rg_frotas") or []) if x in frota_opts],
                key="rg_frotas",
            )
        with d3:
            aplicar = st.button("✅ Aplicar filtros", use_container_width=True)
            limpar = st.button("🧹 Limpar", use_container_width=True)

        if limpar:
            dt_ini_def, dt_fim_def = _date_defaults()
            st.session_state["rg_dt_ini"] = dt_ini_def
            st.session_state["rg_dt_fim"] = dt_fim_def
            st.session_state["rg_date_field_label"] = "Solicitação"
            st.session_state["rg_entregue_label"] = "Todos"
            st.session_state["rg_depts"] = []
            st.session_state["rg_frotas"] = []
            st.session_state["rg_applied"] = True
            st.rerun()

        if aplicar:
            st.session_state["rg_applied"] = True
            st.rerun()

    # Micro-UX: aviso quando não há dados
    if df_base.empty:
        st.warning("Nenhum pedido no filtro atual. Ajuste o período/filtros.")
        st.stop()

    st.divider()

    # ===== Abas =====
    tab_gestor, tab_frota, tab_dept = st.tabs(["👤 Por Gestor", "🚜 Por Frota", "🏢 Por Departamento"])

    def _top_selector(prefix: str) -> int | None:
        opt = st.radio(
            "Exibir",
            ["Top 10", "Top 20", "Top 50", "Todos"],
            horizontal=True,
            key=f"{prefix}_top",
            index=0,
        )
        if opt == "Top 10":
            return 10
        if opt == "Top 20":
            return 20
        if opt == "Top 50":
            return 50
        return None

    def _render_common_actions(df_out: pd.DataFrame, filename_prefix: str):
        csv = df_out.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Baixar CSV",
            csv,
            _download_name(filename_prefix, dt_ini, dt_fim),
            "text/csv",
            use_container_width=True,
        )

    # ===== Aba Gestor =====
    with tab_gestor:
        st.subheader("Gastos por Gestor")
        topn = _top_selector("rg_gestor")

        df_g = _safe_gastos_por_gestor(df_base, links, user_map)
        if df_g is None or df_g.empty:
            st.info("Sem dados para o agrupamento por Gestor (verifique vínculos de departamento → gestor).")
            st.stop()

        # KPIs da aba
        with st.container(border=True):
            g1, g2, g3 = st.columns(3)
            g1.metric("Gestores no período", int(df_g["gestor_user_id"].nunique()) if "gestor_user_id" in df_g.columns else len(df_g))
            g2.metric("Gasto total", formatar_moeda_br(_as_float(df_g["total"].sum())))
            g3.metric("Pedidos", int(_as_float(df_g["qtd_pedidos"].sum())))

        df_g = df_g.copy()
        df_g["participacao_pct"] = df_g["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_g = df_g.sort_values("total", ascending=False)
        if topn:
            df_plot = df_g.head(topn)
        else:
            df_plot = df_g

        st.bar_chart(df_plot.set_index("gestor_nome")[["total"]], height=280)

        # UX: busca rápida
        q = st.text_input("Buscar gestor", value="", key="rg_busca_gestor", placeholder="Digite parte do nome ou e-mail…")
        df_show = df_g.copy()
        df_show["Gestor"] = df_show["gestor_nome"].fillna("(Sem nome)")
        df_show["E-mail"] = df_show.get("gestor_email", pd.Series([""] * len(df_show))).fillna("")
        if q.strip():
            qq = q.strip().lower()
            df_show = df_show[df_show["Gestor"].str.lower().str.contains(qq) | df_show["E-mail"].str.lower().str.contains(qq)]

        df_show["Pedidos"] = df_show["qtd_pedidos"].fillna(0).astype(int)
        df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
        df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
        cols = ["Gestor", "E-mail", "Pedidos", "Total", "% do total"]
        st.dataframe(df_show[cols], use_container_width=True, hide_index=True)

        _render_common_actions(df_g, "gastos_por_gestor")

    # ===== Aba Frota =====
    with tab_frota:
        st.subheader("Gastos por Frota (cód. equipamento)")
        topn = _top_selector("rg_frota")

        df_f = gastos_por_frota(df_base)
        if df_f is None or df_f.empty:
            st.info("Sem dados para o agrupamento por Frota (cod_equipamento).")
            st.stop()

        with st.container(border=True):
            f1, f2, f3 = st.columns(3)
            f1.metric("Frotas no período", int(df_f["cod_equipamento"].nunique()) if "cod_equipamento" in df_f.columns else len(df_f))
            f2.metric("Gasto total", formatar_moeda_br(_as_float(df_f["total"].sum())))
            f3.metric("Pedidos", int(_as_float(df_f["qtd_pedidos"].sum())))

        df_f = df_f.copy()
        df_f["participacao_pct"] = df_f["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_f = df_f.sort_values("total", ascending=False)
        df_plot = df_f.head(topn) if topn else df_f

        chart_df = df_plot.set_index("cod_equipamento")[["total"]]
        st.bar_chart(chart_df, height=280)

        q = st.text_input("Buscar frota (cód.)", value="", key="rg_busca_frota", placeholder="Digite parte do código…")
        df_show = df_f.copy()
        df_show["Frota"] = df_show["cod_equipamento"].fillna("(Sem código)")
        if q.strip():
            qq = q.strip().lower()
            df_show = df_show[df_show["Frota"].astype(str).str.lower().str.contains(qq)]

        df_show["Pedidos"] = df_show["qtd_pedidos"].fillna(0).astype(int)
        df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
        df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
        st.dataframe(df_show[["Frota", "Pedidos", "Total", "% do total"]], use_container_width=True, hide_index=True)

        _render_common_actions(df_f, "gastos_por_frota")

    # ===== Aba Departamento =====
    with tab_dept:
        st.subheader("Gastos por Departamento")
        topn = _top_selector("rg_dept")

        df_d = gastos_por_departamento(df_base)
        if df_d is None or df_d.empty:
            st.info("Sem dados para o agrupamento por Departamento.")
            st.stop()

        with st.container(border=True):
            d1, d2, d3 = st.columns(3)
            d1.metric("Departamentos", int(df_d["departamento"].nunique()) if "departamento" in df_d.columns else len(df_d))
            d2.metric("Gasto total", formatar_moeda_br(_as_float(df_d["total"].sum())))
            d3.metric("Pedidos", int(_as_float(df_d["qtd_pedidos"].sum())))

        df_d = df_d.copy()
        df_d["participacao_pct"] = df_d["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_d = df_d.sort_values("total", ascending=False)
        df_plot = df_d.head(topn) if topn else df_d
        chart_df = df_plot.set_index("departamento")[["total"]]
        st.bar_chart(chart_df, height=280)

        q = st.text_input("Buscar departamento", value="", key="rg_busca_dept", placeholder="Digite parte do nome…")
        df_show = df_d.copy()
        df_show["Departamento"] = df_show["departamento"].fillna("(Sem dept)").astype(str)
        if q.strip():
            qq = q.strip().lower()
            df_show = df_show[df_show["Departamento"].str.lower().str.contains(qq)]

        df_show["Pedidos"] = df_show["qtd_pedidos"].fillna(0).astype(int)
        df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
        df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
        st.dataframe(df_show[["Departamento", "Pedidos", "Total", "% do total"]], use_container_width=True, hide_index=True)

        _render_common_actions(df_d, "gastos_por_departamento")
