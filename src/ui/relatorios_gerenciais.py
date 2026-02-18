from __future__ import annotations

from datetime import date, timedelta

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


def render_relatorios_gerenciais(_supabase, tenant_id: str):
    st.title("📈 Relatórios Gerenciais")
    st.caption("Gastos por Gestor, Frota (cód. equipamento) e Departamento.")

    if not tenant_id:
        st.error("Tenant não identificado.")
        st.stop()

    # Admin (service role) para leituras que podem sofrer RLS
    try:
        supabase_admin = init_supabase_admin()
    except Exception:
        supabase_admin = None

    # ===== Filtros (card no topo) =====
    dt_ini_def, dt_fim_def = _date_defaults()

    with st.container(border=True):
        st.markdown("### 🔎 Filtros")
        with st.form("rg_filtros_form", clear_on_submit=False):
            c1, c2, c3, c4 = st.columns([1, 1, 1, 1])

            with c1:
                dt_ini = st.date_input("Data inicial", value=dt_ini_def, key="rg_dt_ini")
            with c2:
                dt_fim = st.date_input("Data final", value=dt_fim_def, key="rg_dt_fim")
            with c3:
                date_field_label = st.selectbox(
                    "Campo de data",
                    ["Solicitação", "OC", "Entrega real", "Criação"],
                    index=0,
                    key="rg_date_field",
                )
            with c4:
                entregue_opt = st.selectbox(
                    "Situação",
                    ["Todos", "Entregues", "Pendentes"],
                    index=0,
                    key="rg_entregue",
                )

            date_field_map = {
                "Solicitação": "data_solicitacao",
                "OC": "data_oc",
                "Entrega real": "data_entrega_real",
                "Criação": "criado_em",
            }
            date_field = date_field_map.get(date_field_label, "data_solicitacao")

            entregue = None
            if entregue_opt == "Entregues":
                entregue = True
            elif entregue_opt == "Pendentes":
                entregue = False

            # Carregar pedidos (para popular filtros de dept/frota)
            # Obs: carregamos aqui porque as opções dependem do DF
            with st.spinner("Carregando pedidos para montar filtros..."):
                df_pedidos = carregar_pedidos(_supabase, tenant_id=tenant_id)

            if df_pedidos is None or df_pedidos.empty:
                st.info("Nenhum pedido encontrado para este tenant.")
                st.stop()

            df_tmp = df_pedidos.copy()
            for col in ["departamento", "cod_equipamento"]:
                if col not in df_tmp.columns:
                    df_tmp[col] = ""
                df_tmp[col] = df_tmp[col].astype(str).fillna("").str.strip()

            departamentos = sorted([d for d in df_tmp["departamento"].unique().tolist() if d])
            frotas = sorted([f for f in df_tmp["cod_equipamento"].unique().tolist() if f])

            f1, f2 = st.columns([1, 1])
            with f1:
                sel_dept = st.multiselect("Departamentos (opcional)", departamentos, default=[], key="rg_dept")
            with f2:
                sel_frota = st.multiselect(
                    "Frotas / Equipamentos (cod_equipamento) (opcional)",
                    frotas,
                    default=[],
                    key="rg_frota",
                )

            apply = st.form_submit_button("✅ Aplicar filtros", use_container_width=True)

    # Para não rodar a página vazia, aplica automático na primeira vez
    if "rg_applied" not in st.session_state:
        st.session_state["rg_applied"] = True
        apply = True

    if not apply:
        st.info("Ajuste os filtros e clique em **Aplicar filtros**.")
        st.stop()

    # ===== Dataset base =====
    filtros = FiltrosGastos(
        dt_ini=dt_ini,
        dt_fim=dt_fim,
        date_field=date_field,  # type: ignore
        entregue=entregue,
        departamentos=sel_dept or None,
        cod_equipamentos=sel_frota or None,
    )

    df_base = filtrar_pedidos_base(df_pedidos, filtros)

    total_geral = _as_float(df_base.get("valor_total", pd.Series(dtype=float)).sum()) if df_base is not None and not df_base.empty else 0.0
    qtd_geral = int(len(df_base)) if df_base is not None else 0
    ticket = (total_geral / qtd_geral) if qtd_geral else 0.0

    with st.container(border=True):
        st.markdown("### 📌 Resumo do período")
        k1, k2, k3 = st.columns(3)
        k1.metric("Pedidos no filtro", qtd_geral)
        k2.metric("Gasto total", formatar_moeda_br(total_geral))
        k3.metric("Ticket médio", formatar_moeda_br(ticket))

    st.divider()

    tab_gestor, tab_frota, tab_dept = st.tabs(["👤 Por Gestor", "🚜 Por Frota (equipamento)", "🏢 Por Departamento"])

    # ===================== Por Gestor =====================
    with tab_gestor:
        st.subheader("👤 Gastos por Gestor")
        st.caption("Atribuição via vínculo Departamento → Gestor (gestor_departamentos).")

        top_n = st.selectbox("Mostrar", [10, 20, 50, "Todos"], index=0, key="rg_top_gestor")
        with st.spinner("Carregando vínculos e usuários..."):
            links = carregar_links_departamento_gestor(supabase_admin or _supabase, tenant_id)
            user_map = carregar_mapa_usuarios_tenant(supabase_admin or _supabase, tenant_id)

        df_g = gastos_por_gestor(df_base, links, user_map)

        if df_g.empty:
            st.info("Sem dados para exibir. Verifique se existem vínculos Departamento → Gestor e pedidos no período.")
        else:
            df_g = df_g.copy()
            df_g["total"] = pd.to_numeric(df_g["total"], errors="coerce").fillna(0.0)
            df_g["participacao_pct"] = df_g["total"].apply(lambda v: _share_percent(total_geral, float(v)))

            df_plot = df_g.sort_values("total", ascending=False)
            if top_n != "Todos":
                df_plot = df_plot.head(int(top_n))

            # gráfico
            chart_df = df_plot[["gestor_nome", "total"]].copy()
            chart_df["gestor_nome"] = chart_df["gestor_nome"].fillna("(Sem nome)").astype(str)
            chart_df = chart_df.set_index("gestor_nome")
            st.bar_chart(chart_df, height=280)

            # tabela
            df_show = df_g.copy()
            df_show["Gestor"] = df_show["gestor_nome"].fillna("(Sem nome)")
            df_show["Email"] = df_show["gestor_email"].fillna("")
            df_show["Pedidos"] = df_show["qtd_pedidos"].fillna(0).astype(int)
            df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(float(x or 0)))
            df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{float(x):.1f}%")
            df_show["Departamentos"] = df_show.get("departamentos", "").fillna("")
            df_show = df_show[["Gestor", "Email", "Pedidos", "Total", "% do total", "Departamentos"]]
            df_show = df_show.sort_values(by=["Pedidos"], ascending=False)
            st.dataframe(df_show, use_container_width=True, hide_index=True)

            csv = df_g.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Baixar CSV (Gestor)",
                csv,
                _download_name("gastos_por_gestor", dt_ini, dt_fim),
                "text/csv",
                use_container_width=True,
            )

    # ===================== Por Frota =====================
    with tab_frota:
        st.subheader("🚜 Gastos por Frota / Equipamento")
        st.caption("Agrupamento por cod_equipamento (proxy de frota).")

        top_n = st.selectbox("Mostrar", [10, 20, 50, "Todos"], index=0, key="rg_top_frota")

        df_f = gastos_por_frota(df_base)
        if df_f.empty:
            st.info("Sem dados para exibir com os filtros atuais.")
        else:
            df_f = df_f.copy()
            df_f["total"] = pd.to_numeric(df_f["total"], errors="coerce").fillna(0.0)
            df_f["participacao_pct"] = df_f["total"].apply(lambda v: _share_percent(total_geral, float(v)))

            df_plot = df_f.sort_values("total", ascending=False)
            if top_n != "Todos":
                df_plot = df_plot.head(int(top_n))

            chart_df = df_plot[["cod_equipamento", "total"]].copy()
            chart_df["cod_equipamento"] = chart_df["cod_equipamento"].fillna("(Sem código)").astype(str)
            chart_df = chart_df.set_index("cod_equipamento")
            st.bar_chart(chart_df, height=280)

            df_show = df_f.copy()
            df_show["Equipamento"] = df_show["cod_equipamento"].fillna("(Sem código)")
            df_show["Pedidos"] = df_show["qtd_pedidos"].fillna(0).astype(int)
            df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(float(x or 0)))
            df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{float(x):.1f}%")
            df_show = df_show[["Equipamento", "Pedidos", "Total", "% do total"]]
            df_show = df_show.sort_values(by=["Total"], ascending=False)
            st.dataframe(df_show, use_container_width=True, hide_index=True)

            csv = df_f.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Baixar CSV (Frota)",
                csv,
                _download_name("gastos_por_frota", dt_ini, dt_fim),
                "text/csv",
                use_container_width=True,
            )

    # ===================== Por Departamento =====================
    with tab_dept:
        st.subheader("🏢 Gastos por Departamento")
        st.caption("Agrupamento por departamento (derivado dos pedidos).")

        top_n = st.selectbox("Mostrar", [10, 20, 50, "Todos"], index=0, key="rg_top_dept")

        df_d = gastos_por_departamento(df_base)
        if df_d.empty:
            st.info("Sem dados para exibir com os filtros atuais.")
        else:
            df_d = df_d.copy()
            df_d["total"] = pd.to_numeric(df_d["total"], errors="coerce").fillna(0.0)
            df_d["participacao_pct"] = df_d["total"].apply(lambda v: _share_percent(total_geral, float(v)))

            df_plot = df_d.sort_values("total", ascending=False)
            if top_n != "Todos":
                df_plot = df_plot.head(int(top_n))

            chart_df = df_plot[["departamento", "total"]].copy()
            chart_df["departamento"] = chart_df["departamento"].fillna("(Sem dept)").astype(str)
            chart_df = chart_df.set_index("departamento")
            st.bar_chart(chart_df, height=280)

            df_show = df_d.copy()
            df_show["Departamento"] = df_show["departamento"].fillna("(Sem dept)")
            df_show["Pedidos"] = df_show["qtd_pedidos"].fillna(0).astype(int)
            df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(float(x or 0)))
            df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{float(x):.1f}%")
            df_show = df_show[["Departamento", "Pedidos", "Total", "% do total"]]
            df_show = df_show.sort_values(by=["Total"], ascending=False)
            st.dataframe(df_show, use_container_width=True, hide_index=True)

            csv = df_d.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Baixar CSV (Departamento)",
                csv,
                _download_name("gastos_por_departamento", dt_ini, dt_fim),
                "text/csv",
                use_container_width=True,
            )
