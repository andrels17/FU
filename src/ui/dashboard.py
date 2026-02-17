"""Tela: Dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import src.services.dashboard_avancado as da
import src.services.exportacao_relatorios as er
import src.services.filtros_avancados as fa
import src.services.backup_auditoria as ba

from src.repositories.pedidos import carregar_pedidos, carregar_estatisticas_departamento
from src.repositories.fornecedores import carregar_fornecedores
from src.utils.formatting import formatar_moeda_br, formatar_numero_br

def _dt_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([pd.NaT] * len(df), index=df.index)
    return pd.to_datetime(df[col], errors="coerce")

def _compute_due_dates(df: pd.DataFrame) -> pd.Series:
    # Regra alinhada com src.services.sistema_alertas: previsao_entrega > prazo_entrega > data_oc + 30 dias
    prev = _dt_series(df, "previsao_entrega")
    prazo = _dt_series(df, "prazo_entrega")
    data_oc = _dt_series(df, "data_oc")
    fallback = data_oc + pd.to_timedelta(30, unit="D")
    due = prev.fillna(prazo).fillna(fallback)
    return due

def _normalize_bool_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().isin(["true", "1", "yes", "sim"])

def _apply_dashboard_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Filtros globais (um único lugar) + botão 'Gerar dashboard'.

    - Mantém os filtros em session_state
    - Só recalcula/atualiza df_view quando o usuário clica em 'Gerar'
    """
    # defaults
    if "dash_filters_applied" not in st.session_state:
        st.session_state.dash_filters_applied = False

    # Form recolhível para não poluir
    expanded = bool(st.session_state.get("dash_filters_expanded", not st.session_state.get("dash_filters_applied", False)))
    with st.expander("🔎 Filtros do Dashboard", expanded=expanded):
        with st.form("dash_filters_form", clear_on_submit=False):
            c1, c2, c3, c4, c5 = st.columns([1.2, 1.6, 1.6, 1.2, 1.2])

            # Período
            with c1:
                periodo = st.selectbox(
                    "Período",
                    ["30 dias", "60 dias", "90 dias", "Tudo"],
                    index=0,
                    key="dash_periodo",
                )

            # Departamento
            with c2:
                deptos = (
                    df.get("departamento", pd.Series(dtype=str))
                    .dropna().astype(str).str.strip()
                )
                deptos = sorted([d for d in deptos.unique().tolist() if d])
                dept_sel = st.multiselect("Departamento", deptos, default=st.session_state.get("dash_dept", []), key="dash_dept")

            # Fornecedor
            with c3:
                forn = (
                    df.get("fornecedor_nome", pd.Series(dtype=str))
                    .dropna().astype(str).str.strip()
                )
                forn = sorted([f for f in forn.unique().tolist() if f])
                forn_sel = st.multiselect("Fornecedor", forn, default=st.session_state.get("dash_forn", []), key="dash_forn")

            # Status + pendentes
            with c4:
                status = df.get("status", pd.Series(dtype=str)).dropna().astype(str).str.strip()
                status = sorted([s for s in status.unique().tolist() if s])
                status_sel = st.multiselect("Status", status, default=st.session_state.get("dash_status", []), key="dash_status")

            with c5:
                somente_pendentes = st.toggle("Somente pendentes", value=st.session_state.get("dash_only_pending", True), key="dash_only_pending")

            # Botões
            b1, b2 = st.columns([1, 1])
            with b1:
                gerar = st.form_submit_button("✅ Gerar dashboard", use_container_width=True)
            with b2:
                limpar = st.form_submit_button("🧹 Limpar filtros", use_container_width=True)

    # Limpar filtros
    if limpar:
        for k in ["dash_periodo", "dash_dept", "dash_forn", "dash_status", "dash_only_pending"]:
            if k in st.session_state:
                del st.session_state[k]
        st.session_state.dash_filters_applied = False
        st.session_state.pop("dash_df_view", None)
        st.rerun()

    # Se nunca aplicou e não clicou gerar, mostra vazio (UX: força intenção)
    if not st.session_state.dash_filters_applied and not gerar:
        st.info("Selecione os filtros e clique em **Gerar dashboard** para calcular os indicadores e gráficos.")
        return df.iloc[0:0].copy()

    # Aplicar (quando clicar Gerar, ou se já aplicado antes)
    if gerar or not st.session_state.get("dash_df_view_ready", False):
        out = df.copy()

        # Aplicar período com base em data_oc (se existir) senão previsao_entrega
        base_dt = _dt_series(out, "data_oc")
        if base_dt.isna().all():
            base_dt = _dt_series(out, "previsao_entrega")
        if not base_dt.isna().all() and st.session_state.get("dash_periodo", "30 dias") != "Tudo":
            dias = int(str(st.session_state.get("dash_periodo", "30 dias")).split()[0])
            ini = pd.Timestamp.now().normalize() - pd.Timedelta(days=dias)
            out = out.loc[base_dt >= ini]

        dept_sel = st.session_state.get("dash_dept", [])
        forn_sel = st.session_state.get("dash_forn", [])
        status_sel = st.session_state.get("dash_status", [])
        somente_pendentes = st.session_state.get("dash_only_pending", True)

        if dept_sel and "departamento" in out.columns:
            out = out[out["departamento"].astype(str).str.strip().isin(dept_sel)]
        if forn_sel and "fornecedor_nome" in out.columns:
            out = out[out["fornecedor_nome"].astype(str).str.strip().isin(forn_sel)]
        if status_sel and "status" in out.columns:
            out = out[out["status"].astype(str).str.strip().isin(status_sel)]

        if somente_pendentes and "entregue" in out.columns:
            entregue = _normalize_bool_series(out["entregue"])
            out = out[~entregue]

        st.session_state["dash_df_view"] = out
        st.session_state.dash_filters_applied = True
        st.session_state["dash_df_view_ready"] = True
        st.session_state["dash_last_generated"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        st.session_state["dash_filters_expanded"] = False

    return st.session_state.get("dash_df_view", df)


def exibir_dashboard(_supabase):
    """Exibe dashboard principal com KPIs e gráficos"""
    
    st.title("📊 Dashboard de Follow-up")
    
    # Carregar dados
    df_export = carregar_pedidos(_supabase, st.session_state.get("tenant_id"))
    
    if df_export.empty:
        st.info("📭 Nenhum pedido cadastrado ainda")
        return
    
    # Botão de diagnóstico (temporário para debug) - COMENTADO
    # if st.button("🔍 Diagnosticar Problema de Datas"):
    #     diagnostico_datas.diagnosticar_datas(df_export)

    
    # Aplicar filtros globais do dashboard
    df_view = _apply_dashboard_filters(df_export)

    if df_view.empty:
        st.info("🔍 Nenhum pedido encontrado com os filtros atuais.")
        return

    # =========================
    # KPIs (compacto + drilldown)
    # =========================
    hoje = pd.Timestamp.now().normalize()

    # Normalizações
    if "entregue" in df_view.columns:
        df_view["_entregue"] = _normalize_bool_series(df_view["entregue"])
    else:
        df_view["_entregue"] = False

    if "atrasado" in df_view.columns:
        df_view["_atrasado"] = _normalize_bool_series(df_view["atrasado"])
    else:
        df_view["_atrasado"] = False

    df_view["_due"] = _compute_due_dates(df_view)
    df_view["_valor"] = pd.to_numeric(df_view.get("valor_total", 0), errors="coerce").fillna(0.0)

    pendentes = df_view[~df_view["_entregue"]].copy()

    # Vencendo: até 3 dias (mesma regra do sistema de alertas)
    data_limite = hoje + pd.Timedelta(days=3)
    vencendo = pendentes[pendentes["_due"].notna() & (pendentes["_due"] >= hoje) & (pendentes["_due"] <= data_limite)]

    # Atrasados: due < hoje (ou flag atrasado)
    atrasados = pendentes[
        (pendentes["_atrasado"]) |
        (pendentes["_due"].notna() & (pendentes["_due"] < hoje))
    ]

    # Críticos: alto valor (>= P75) + vencendo (<= 3 dias)
    if len(pendentes) >= 4:
        valor_critico = float(pendentes["_valor"].quantile(0.75))
    else:
        valor_critico = float(pendentes["_valor"].max() if len(pendentes) else 0.0)
    criticos = vencendo[vencendo["_valor"] >= valor_critico]

    total_pedidos = len(df_view)
    pedidos_entregues = int(df_view["_entregue"].sum())
    pedidos_pendentes = int((~df_view["_entregue"]).sum())
    pedidos_atrasados = len(atrasados)
    pedidos_vencendo = len(vencendo)
    pedidos_criticos = len(criticos)

    valor_total = float(df_view["_valor"].sum())
    valor_em_risco = float(atrasados["_valor"].sum() + vencendo["_valor"].sum())

    # Linha principal (4 KPIs)
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("⏳ Pendentes", formatar_numero_br(pedidos_pendentes).split(",")[0])
    with k2:
        st.metric("⚠️ Atrasados", formatar_numero_br(pedidos_atrasados).split(",")[0], delta_color="inverse")
    with k3:
        st.metric("⏰ Vencendo (≤3d)", formatar_numero_br(pedidos_vencendo).split(",")[0])
    with k4:
        st.metric("💸 Valor em risco", formatar_moeda_br(valor_em_risco))

    # Ações rápidas (compactas)
    a1, a2, a3 = st.columns(3)
    with a1:
        if st.button("➡️ Atrasados", use_container_width=True, key="dash_go_atrasados"):
            st.session_state["quick_filter"] = {"tipo": "atrasados"}
            st.session_state.current_page = "Consultar Pedidos"
            st.rerun()
    with a2:
        if st.button("➡️ Vencendo", use_container_width=True, key="dash_go_vencendo"):
            st.session_state["quick_filter"] = {"tipo": "vencendo"}
            st.session_state.current_page = "Consultar Pedidos"
            st.rerun()
    with a3:
        if st.button("➡️ Críticos", use_container_width=True, key="dash_go_criticos"):
            st.session_state["quick_filter"] = {"tipo": "criticos"}
            st.session_state.current_page = "Consultar Pedidos"
            st.rerun()

    # Detalhes (só se o usuário abrir)
    with st.expander("📌 Detalhes (totais, entregues, críticos, valor total)", expanded=False):
        d1, d2, d3, d4 = st.columns(4)
        with d1:
            st.metric("📦 Total", formatar_numero_br(total_pedidos).split(",")[0])
        with d2:
            taxa_entrega = (pedidos_entregues / total_pedidos * 100) if total_pedidos > 0 else 0.0
            st.metric("✅ Entregues", formatar_numero_br(pedidos_entregues).split(",")[0], delta=f"{taxa_entrega:.1f}%".replace(".", ","))
        with d3:
            st.metric("🚨 Críticos", formatar_numero_br(pedidos_criticos).split(",")[0], delta_color="inverse" if pedidos_criticos > 0 else "normal")
        with d4:
            st.metric("💰 Valor total", formatar_moeda_br(valor_total))

    st.markdown("---")
    
    # Abas para diferentes visualizações
    # Abas controláveis (permite forçar "Exportação" via session_state)
    _tabs = ["Visão Geral", "Dashboard Avançado", "Exportação"]
    _force = st.session_state.pop("dash_force_tab", None)
    _default_idx = 0
    if _force == "Exportação":
        _default_idx = 2

    aba = st.radio(
        "",
        _tabs,
        index=_default_idx,
        horizontal=True,
        key="dash_active_tab",
    )

    tab1 = (aba == _tabs[0])
    tab2 = (aba == _tabs[1])
    tab3 = (aba == _tabs[2])
    if tab1:
        # Controles de densidade
        compacto = st.toggle("Modo compacto (mostrar só o essencial)", value=False, key="dash_compacto")

        st.subheader("Resumo acionável")

        # ⚙️ Personalização das seções
        with st.expander("Personalizar Dashboard", expanded=False):
            a, b, c = st.columns(3)
            with a:
                show_trend = st.checkbox("Tendência", value=True, key="dash_show_trend")
                show_rank = st.checkbox("Rankings", value=True, key="dash_show_rank")
            with b:
                show_aging = st.checkbox("Aging", value=True, key="dash_show_aging")
                show_action = st.checkbox("Aja agora", value=True, key="dash_show_action")
            with c:
                show_details = st.checkbox("KPIs detalhados", value=False, key="dash_show_details")

        # =========================
        # Tendência semanal
        # =========================
        if show_trend:
            st.markdown("#### Tendência (semanal)")
            df_trend = pendentes.copy()
            df_trend["_week"] = df_trend["_due"].dt.to_period("W").astype(str)
            df_trend["_is_atrasado"] = (df_trend["_due"].notna() & (df_trend["_due"] < hoje)) | (df_trend["_atrasado"])
            df_trend["_is_vencendo"] = df_trend["_due"].notna() & (df_trend["_due"] >= hoje) & (df_trend["_due"] <= data_limite)

            grp = df_trend.groupby("_week").agg(
                pendentes=("nr_oc", "count"),
                atrasados=("_is_atrasado", "sum"),
                vencendo=("_is_vencendo", "sum"),
                valor_pendente=("_valor", "sum"),
            ).reset_index()

            if not grp.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=grp["_week"], y=grp["atrasados"], mode="lines+markers", name="Atrasados"))
                fig.add_trace(go.Scatter(x=grp["_week"], y=grp["vencendo"], mode="lines+markers", name="Vencendo (<=3d)"))
                fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Semana", yaxis_title="Qtd")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("Sem dados suficientes para tendência.")

        # Seções pesadas: só quando não estiver em modo compacto
        if not compacto:
            # =========================
            # Rankings
            # =========================
            if show_rank:
                c1, c2 = st.columns(2)

                with c1:
                    st.markdown("#### Top fornecedores (valor em risco)")
                    if "fornecedor_nome" in pendentes.columns and not pendentes.empty:
                        tmp = atrasados.copy()
                        tmp["_bucket"] = "Atrasado"
                        tmp2 = vencendo.copy()
                        tmp2["_bucket"] = "Vencendo"
                        risk = pd.concat([tmp, tmp2], ignore_index=True)
                        if not risk.empty:
                            r = (risk.groupby("fornecedor_nome", dropna=False)["_valor"]
                                 .sum()
                                 .sort_values(ascending=False)
                                 .head(10))
                            fig_f = px.bar(x=r.values, y=r.index, orientation="h")
                            fig_f.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                                                xaxis_title="Valor", yaxis_title="")
                            st.plotly_chart(fig_f, use_container_width=True)
                        else:
                            st.caption("Sem pedidos em risco no recorte.")
                    else:
                        st.caption("Coluna fornecedor_nome ausente ou sem dados.")

                with c2:
                    st.markdown("#### Top departamentos (qtd em risco)")
                    if "departamento" in pendentes.columns and not pendentes.empty:
                        tmp = pd.concat([atrasados, vencendo], ignore_index=True)
                        if not tmp.empty:
                            d = (tmp["departamento"].astype(str).str.strip()
                                 .replace("", pd.NA).dropna()
                                 .value_counts().head(10))
                            fig_d = px.bar(x=d.values, y=d.index, orientation="h")
                            fig_d.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                                                xaxis_title="Quantidade", yaxis_title="")
                            st.plotly_chart(fig_d, use_container_width=True)
                        else:
                            st.caption("Sem pedidos em risco no recorte.")
                    else:
                        st.caption("Coluna departamento ausente ou sem dados.")

            # =========================
            # Aging
            # =========================
            if show_aging:
                st.markdown("#### Aging de atrasos")
                if not atrasados.empty:
                    dias_atraso = (hoje - atrasados["_due"]).dt.days.clip(lower=0)
                    bins = [-1, 7, 15, 30, 60, 10_000]
                    labels = ["0–7", "8–15", "16–30", "31–60", "60+"]
                    aging = pd.cut(dias_atraso, bins=bins, labels=labels).value_counts().reindex(labels).fillna(0).astype(int)
                    fig_a = px.bar(x=aging.index, y=aging.values)
                    fig_a.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                                        xaxis_title="Dias em atraso", yaxis_title="Quantidade")
                    st.plotly_chart(fig_a, use_container_width=True)
                else:
                    st.success("Sem pedidos atrasados no recorte atual.")

            # =========================
            # Aja agora
            # =========================
            if show_action:
                st.markdown("#### Aja agora (Top 20)")
                acao = pd.concat(
                    [criticos.assign(_prior=0), atrasados.assign(_prior=1), vencendo.assign(_prior=2)],
                    ignore_index=True,
                )
                if not acao.empty:
                    acao["_descricao"] = acao.get("descricao", "").astype(str).str.slice(0, 80)
                    acao["_due_str"] = acao["_due"].dt.strftime("%d/%m/%Y")
                    acao = acao.sort_values(["_prior", "_valor"], ascending=[True, False]).head(20)

                    view_cols = []
                    for col in ["nr_oc", "_descricao", "departamento", "fornecedor_nome", "_due_str", "_valor"]:
                        if col in acao.columns:
                            view_cols.append(col)

                    df_show = acao[view_cols].copy()
                    if "_valor" in df_show.columns:
                        df_show["_valor"] = df_show["_valor"].apply(formatar_moeda_br)

                    st.dataframe(
                        df_show,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "nr_oc": "N° OC",
                            "_descricao": "Descrição",
                            "departamento": "Departamento",
                            "fornecedor_nome": "Fornecedor",
                            "_due_str": "Previsão",
                            "_valor": "Valor",
                        },
                    )

                    if st.button("Abrir lista na Consulta", use_container_width=True, key="dash_go_acao"):
                        ocs = acao["nr_oc"].dropna().astype(str).unique().tolist() if "nr_oc" in acao.columns else []
                        st.session_state["quick_filter"] = {"tipo": "lista", "nro_ocs": ocs}
                        st.session_state.current_page = "Consultar Pedidos"
                        st.rerun()
                else:
                    st.caption("Nada para agir agora com os filtros atuais.")
        else:
            st.info("Modo compacto ativo: desative para ver Rankings, Aging e Aja agora.")

        # KPIs detalhados (opcional)
        if show_details:
            with st.expander("KPIs detalhados", expanded=True):
                d1, d2, d3, d4 = st.columns(4)
                with d1:
                    st.metric("Total", formatar_numero_br(total_pedidos).split(",")[0])
                with d2:
                    taxa_entrega = (pedidos_entregues / total_pedidos * 100) if total_pedidos > 0 else 0.0
                    st.metric("✅ Entregues", formatar_numero_br(pedidos_entregues).split(",")[0], delta=f"{taxa_entrega:.1f}%".replace(".", ","))
                with d3:
                    st.metric("🚨 Críticos", formatar_numero_br(pedidos_criticos).split(",")[0], delta_color="inverse" if pedidos_criticos > 0 else "normal")
                with d4:
                    st.metric("Valor total", formatar_moeda_br(valor_total))

    if tab2:
        # Dashboard avançado
        da.exibir_dashboard_avancado(df_view, formatar_moeda_br)
    
    if tab3:
    
        # Exportação usa o MESMO recorte do dashboard (filtros globais já aplicados)
    
        df_export = df_view.copy()
    
        st.caption("Exportação baseada nos filtros do Dashboard.")


        # Exportação de dados
        st.subheader("📥 Exportação de Relatórios")
        
        tipo_relatorio = st.selectbox(
            "Selecione o tipo de relatório:",
            ["Relatório Completo", "Relatório Executivo", "Por Fornecedor", "Por Departamento"]
        )
        
        if tipo_relatorio == "Relatório Completo":
            er.gerar_botoes_exportacao(df_export, formatar_moeda_br)
        
        elif tipo_relatorio == "Relatório Executivo":
            er.criar_relatorio_executivo(df_export, formatar_moeda_br)
        
        elif tipo_relatorio == "Por Fornecedor":
            fornecedor = st.selectbox(
                "Selecione o fornecedor:",
                sorted(df_export['fornecedor_nome'].dropna().unique())
            )
            if fornecedor:
                er.gerar_relatorio_fornecedor(df_export, fornecedor, formatar_moeda_br)
        
        elif tipo_relatorio == "Por Departamento":
            if "departamento" not in df_export.columns:
                st.error("Coluna 'departamento' não encontrada nos dados.")
                st.caption(f"Colunas disponíveis: {list(df_export.columns)}")
                return
        
            departamentos = (
                df_export["departamento"]
                .dropna()
                .astype(str)
                .str.strip()
                .loc[lambda s: s != ""]
                .unique()
                .tolist()
            )
            departamentos = sorted(departamentos)
        
            departamento = st.selectbox(
                "Selecione o departamento:",
                departamentos
            )
        
            if departamento:
                er.gerar_relatorio_departamento(df_export, departamento, formatar_moeda_br)


# ============================================
# PÁGINA DE MAPA GEOGRÁFICO (NOVA VERSÃO)
# ============================================

