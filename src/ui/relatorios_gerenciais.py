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


def render_relatorios_gerenciais(_supabase, tenant_id: str):
    st.title("📈 Relatórios Gerenciais")
    st.caption("Gastos por Gestor, Frota (cód. equipamento) e Departamento — sem duplicar lógica do WhatsApp.")

    if not tenant_id:
        st.error("Tenant não identificado.")
        st.stop()

    # Usamos admin para leituras que podem sofrer RLS (mapa usuários / vínculos)
    try:
        supabase_admin = init_supabase_admin()
    except Exception:
        supabase_admin = None

    # === Filtros globais ===
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    dt_ini_def, dt_fim_def = _date_defaults()
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

    # Carregar pedidos base uma vez (reuso)
    with st.spinner("Carregando pedidos..."):
        df_pedidos = carregar_pedidos(_supabase, tenant_id=tenant_id)

    if df_pedidos is None or df_pedidos.empty:
        st.info("Nenhum pedido encontrado para este tenant.")
        st.stop()

    # Opções de filtro por dept/frota derivadas dos pedidos
    df_pedidos_tmp = df_pedidos.copy()
    for col in ["departamento", "cod_equipamento"]:
        if col not in df_pedidos_tmp.columns:
            df_pedidos_tmp[col] = ""
        df_pedidos_tmp[col] = df_pedidos_tmp[col].astype(str).fillna("").str.strip()

    departamentos = sorted([d for d in df_pedidos_tmp["departamento"].unique().tolist() if d])
    frotas = sorted([f for f in df_pedidos_tmp["cod_equipamento"].unique().tolist() if f])

    f1, f2 = st.columns([1, 1])
    with f1:
        sel_dept = st.multiselect("Departamentos (opcional)", departamentos, default=[], key="rg_dept")
    with f2:
        sel_frota = st.multiselect("Frotas / Equipamentos (cod_equipamento) (opcional)", frotas, default=[], key="rg_frota")

    filtros = FiltrosGastos(
        dt_ini=dt_ini,
        dt_fim=dt_fim,
        date_field=date_field,  # type: ignore
        entregue=entregue,
        departamentos=sel_dept or None,
        cod_equipamentos=sel_frota or None,
    )

    df_base = filtrar_pedidos_base(df_pedidos, filtros)

    # KPIs rápidos
    k1, k2, k3 = st.columns(3)
    total = float(df_base["valor_total"].sum()) if not df_base.empty and "valor_total" in df_base.columns else 0.0
    qtd = int(len(df_base)) if df_base is not None else 0
    k1.metric("Pedidos no filtro", qtd)
    k2.metric("Gasto total", formatar_moeda_br(total))
    k3.metric("Ticket médio", formatar_moeda_br(total / qtd) if qtd else formatar_moeda_br(0))

    st.divider()

    tab_gestor, tab_frota, tab_dept = st.tabs(["👤 Por Gestor", "🚜 Por Frota (equipamento)", "🏢 Por Departamento"])

    # ===== Por Gestor =====
    with tab_gestor:
        st.subheader("👤 Gastos por Gestor")
        st.caption("Atribuição via vínculo Departamento → Gestor (gestor_departamentos).")

        with st.spinner("Carregando vínculos e usuários..."):
            links = carregar_links_departamento_gestor(supabase_admin or _supabase, tenant_id)
            user_map = carregar_mapa_usuarios_tenant(supabase_admin or _supabase, tenant_id)

        df_g = gastos_por_gestor(df_base, links, user_map)

        if df_g.empty:
            st.info("Sem dados para exibir. Verifique se existem vínculos Departamento → Gestor e pedidos no período.")
        else:
            # Formatações
            df_show = df_g.copy()
            df_show["total"] = df_show["total"].apply(lambda x: formatar_moeda_br(float(x or 0)))
            st.dataframe(df_show, use_container_width=True, hide_index=True)

            csv = df_g.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Baixar CSV (Gestor)", csv, "gastos_por_gestor.csv", "text/csv")

    # ===== Por Frota =====
    with tab_frota:
        st.subheader("🚜 Gastos por Frota / Equipamento")
        st.caption("Agrupamento por cod_equipamento (proxy de frota).")

        df_f = gastos_por_frota(df_base)
        if df_f.empty:
            st.info("Sem dados para exibir com os filtros atuais.")
        else:
            df_show = df_f.copy()
            df_show["total"] = df_show["total"].apply(lambda x: formatar_moeda_br(float(x or 0)))
            st.dataframe(df_show, use_container_width=True, hide_index=True)

            csv = df_f.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Baixar CSV (Frota)", csv, "gastos_por_frota.csv", "text/csv")

    # ===== Por Departamento =====
    with tab_dept:
        st.subheader("🏢 Gastos por Departamento")
        df_d = gastos_por_departamento(df_base)
        if df_d.empty:
            st.info("Sem dados para exibir com os filtros atuais.")
        else:
            df_show = df_d.copy()
            df_show["total"] = df_show["total"].apply(lambda x: formatar_moeda_br(float(x or 0)))
            st.dataframe(df_show, use_container_width=True, hide_index=True)

            csv = df_d.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Baixar CSV (Departamento)", csv, "gastos_por_departamento.csv", "text/csv")
