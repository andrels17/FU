"""Tela: Dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta

import time

import pandas as pd
import plotly.express as px
from src.ui.plotly_style import style_plotly, add_bar_labels, ACCENT_COLOR
import plotly.graph_objects as go
import streamlit as st

try:
    from streamlit_plotly_events import plotly_events  # type: ignore
except Exception:  # pragma: no cover
    plotly_events = None  # type: ignore

from src.ui import ux
from src.ui.responsive import rcols, is_mobile

import src.services.dashboard_avancado as da
import src.services.filtros_avancados as fa
import src.services.backup_auditoria as ba

from src.repositories.pedidos import carregar_pedidos, carregar_estatisticas_departamento
from src.repositories.fornecedores import carregar_fornecedores
from src.utils.formatting import formatar_moeda_br, formatar_numero_br
from src.ui.theme import apply_theme, section_header, kpi_row


def _memo(name: str, key: str, compute_fn):
    """Cache leve em memória (session_state) para evitar recomputações em reruns.

    Evita problemas de hash com objetos (supabase client, dfs grandes) e ainda
    melhora bastante a performance percebida.
    """
    bucket = st.session_state.setdefault("_dash_memo", {})
    sk = f"{name}:{key}"
    if sk in bucket:
        return bucket[sk]
    val = compute_fn()
    bucket[sk] = val
    return val


def _fig_memo(name: str, key: str, build_fn):
    """Memoização para figuras Plotly.

    Criar figuras (especialmente com labels) custa caro e deixa o app "pesado"
    quando acontece rerun por scroll/expanders. Guardar a figura pronta deixa
    esses reruns praticamente instantâneos.
    """
    return _memo(f"fig:{name}", key, build_fn)

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





def _drill_to_consulta(*, dept: str | None = None, uf: str | None = None) -> None:
    """Navega para Consulta e pré-aplica filtros via session_state."""
    st.session_state.current_page = "orders_search"
    st.session_state["_force_menu_sync"] = True

    if dept:
        st.session_state["c_deptos"] = [str(dept).strip()]
    if uf:
        st.session_state["c_uf"] = [str(uf).strip().upper()]

    st.session_state["consulta_quick"] = True
    st.rerun()

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
    with st.expander("Filtros do Dashboard", expanded=expanded):
        with st.form("dash_filters_form", clear_on_submit=False):
            mobile = bool(st.session_state.get("mobile_mode", False))

            if mobile:
                # Layout mobile: filtros empilhados (mais legível em telas pequenas)
                periodo = st.selectbox(
                    "Período",
                    ["30 dias", "60 dias", "90 dias", "Tudo"],
                    index=0,
                    key="dash_periodo",
                )

                deptos = (
                    df.get("departamento", pd.Series(dtype=str))
                    .dropna().astype(str).str.strip()
                )
                deptos = sorted([d for d in deptos.unique().tolist() if d])
                dept_sel = st.multiselect("Departamento", deptos, default=st.session_state.get("dash_dept", []), key="dash_dept")

                uf_series = (
                    df.get("fornecedor_uf", pd.Series(dtype=str))
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .str.upper()
                )
                uf_counts = uf_series.value_counts()
                uf_sorted = uf_counts.index.tolist()
                uf_label = {uf: f"{uf} ({int(uf_counts[uf])} pedidos)" for uf in uf_sorted}
                options = [uf_label[uf] for uf in uf_sorted]
                default_ufs = st.session_state.get("dash_uf", [])
                default_labels = [uf_label[u] for u in default_ufs if u in uf_label]
                sel_labels = st.multiselect(
                    "Estado (UF)",
                    options,
                    default=default_labels,
                    key="dash_uf_labels",
                )
                uf_sel = [s.split(" ", 1)[0].strip().upper() for s in (sel_labels or []) if isinstance(s, str) and s.strip()]
                st.session_state["dash_uf"] = uf_sel

                status = df.get("status", pd.Series(dtype=str)).dropna().astype(str).str.strip()
                status = sorted([s for s in status.unique().tolist() if s])
                status_sel = st.multiselect("Status", status, default=st.session_state.get("dash_status", []), key="dash_status")

                somente_pendentes = st.toggle("Somente pendentes", value=st.session_state.get("dash_only_pending", True), key="dash_only_pending")

            else:
                c1, c2, c3, c4, c5 = rcols([1.2, 1.6, 1.6, 1.2, 1.2])

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
                # Estado (UF)
                with c3:
                    uf_series = (
                        df.get("fornecedor_uf", pd.Series(dtype=str))
                        .dropna()
                        .astype(str)
                        .str.strip()
                        .str.upper()
                    )
                    # Contagem por UF para exibir "SP (120 pedidos)" e ordenar por quantidade
                    uf_counts = uf_series.value_counts()
                    uf_sorted = uf_counts.index.tolist()  # já vem ordenado desc
                    uf_label = {uf: f"{uf} ({int(uf_counts[uf])} pedidos)" for uf in uf_sorted}

                    options = [uf_label[uf] for uf in uf_sorted]
                    # default guarda os códigos (["SP","MG"...]) para não quebrar se a contagem mudar
                    default_ufs = st.session_state.get("dash_uf", [])
                    default_labels = [uf_label[u] for u in default_ufs if u in uf_label]

                    sel_labels = st.multiselect(
                        "Estado (UF)",
                        options,
                        default=default_labels,
                        key="dash_uf_labels",
                    )

                    # Converter labels selecionados de volta para UF (antes do primeiro espaço)
                    uf_sel = [s.split(" ", 1)[0].strip().upper() for s in (sel_labels or []) if isinstance(s, str) and s.strip()]
                    st.session_state["dash_uf"] = uf_sel

                # Status + pendentes
                with c4:
                    status = df.get("status", pd.Series(dtype=str)).dropna().astype(str).str.strip()
                    status = sorted([s for s in status.unique().tolist() if s])
                    status_sel = st.multiselect("Status", status, default=st.session_state.get("dash_status", []), key="dash_status")

                with c5:
                    somente_pendentes = st.toggle("Somente pendentes", value=st.session_state.get("dash_only_pending", True), key="dash_only_pending")

            # Botões
            b1, b2 = rcols([1, 1])
            with b1:
                gerar = st.form_submit_button("Gerar dashboard", use_container_width=True)
            with b2:
                limpar = st.form_submit_button("Limpar filtros", use_container_width=True)

    # Limpar filtros
    if limpar:
        for k in ["dash_periodo", "dash_dept", "dash_uf", "dash_uf_labels", "dash_status", "dash_only_pending"]:
            if k in st.session_state:
                del st.session_state[k]
        st.session_state.dash_filters_applied = False
        st.session_state.pop("dash_df_view", None)
        st.session_state["dash_df_view_ready"] = False
        st.session_state["_dash_memo"] = {}
        st.rerun()

    # Se nunca aplicou e não clicou gerar, mostra vazio (UX: força intenção)
    if not st.session_state.dash_filters_applied and not gerar:
        ux.info("Selecione os filtros e clique em **Gerar dashboard** para calcular os indicadores e gráficos.")
        return df.iloc[0:0].copy()

    # Aplicar (quando clicar Gerar, ou se já aplicado antes)
    if gerar or not st.session_state.get("dash_df_view_ready", False):
        # Feedback leve (sem sleeps artificiais)
        if gerar:
            st.toast("Gerando dashboard…", icon="⏳")

        with st.spinner("Aplicando filtros…"):
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
            uf_sel = st.session_state.get("dash_uf", [])
            status_sel = st.session_state.get("dash_status", [])
            somente_pendentes = st.session_state.get("dash_only_pending", True)
            if dept_sel and "departamento" in out.columns:
                out = out[out["departamento"].astype(str).str.strip().isin(dept_sel)]
            if uf_sel and "fornecedor_uf" in out.columns:
                out = out[out["fornecedor_uf"].astype(str).str.strip().str.upper().isin(uf_sel)]
            if status_sel and "status" in out.columns:
                out = out[out["status"].astype(str).str.strip().isin(status_sel)]

            if somente_pendentes and "entregue" in out.columns:
                entregue = _normalize_bool_series(out["entregue"])
                out = out[~entregue]
            if gerar:
                st.toast("Dashboard atualizado ✅", icon="✅")

        st.session_state["dash_df_view"] = out
        st.session_state.dash_filters_applied = True
        st.session_state["dash_df_view_ready"] = True
        st.session_state["dash_last_generated"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        st.session_state["dash_filters_expanded"] = False

    return st.session_state.get("dash_df_view", df)


def exibir_dashboard(_supabase):
    """Exibe dashboard principal com KPIs e gráficos"""

    apply_theme()

    # Config padrão de renderização Plotly (pode ser sobrescrito por toggles no dashboard)
    turbo_global = bool(st.session_state.get("dash_turbo", True))
    fast_global = bool(st.session_state.get("dash_fast_charts", True))
    plot_config = {"displayModeBar": False, "responsive": True, "staticPlot": (turbo_global or fast_global)}

    tenant_id = st.session_state.get("tenant_id")
    section_header(
        "Dashboard",
        hint="Follow-up de pedidos, prazos e gastos.",
        pill=None,
        accent=True,
    )

    # Contexto técnico (evita poluir o header)
    if tenant_id:
        with st.expander("Contexto técnico", expanded=False):
            st.code(f"Tenant: {tenant_id}")
    
    # Carregar dados (cache curto para evitar consultas repetidas em reruns)
    ttl_s = 120
    cache = st.session_state.get("dash_pedidos_cache")
    now_ts = time.time()
    if isinstance(cache, dict) and (now_ts - float(cache.get("ts", 0))) < ttl_s:
        df_export = cache.get("df", pd.DataFrame()).copy()
    else:
        with st.spinner("Carregando pedidos…"):
            df_export = carregar_pedidos(_supabase, tenant_id)
        st.session_state["dash_pedidos_cache"] = {"ts": now_ts, "df": df_export.copy()}
    
    if df_export.empty:
        ux.info("📭 Nenhum pedido cadastrado ainda")
        return
    
    # Botão de diagnóstico (temporário para debug) - COMENTADO
    # if st.button("🔍 Diagnosticar Problema de Datas"):
    #     diagnostico_datas.diagnosticar_datas(df_export)

    
    # Aplicar filtros globais do dashboard
    df_view = _apply_dashboard_filters(df_export)

    if df_view.empty:
        ux.info("Nenhum pedido encontrado com os filtros atuais.")
        return

    # Chips de contexto (filtros ativos + última atualização)
    chips = []
    periodo = st.session_state.get("dash_periodo")
    if periodo and periodo != "Tudo":
        chips.append(f"Período: {periodo}")
    dept = st.session_state.get("dash_dept", [])
    if dept:
        chips.append(f"Depto: {', '.join(dept[:2])}{'…' if len(dept) > 2 else ''}")
    uf = st.session_state.get("dash_uf", [])
    if uf:
        chips.append(f"UF: {', '.join(uf)}")
    status = st.session_state.get("dash_status", [])
    if status:
        chips.append(f"Status: {', '.join(status[:2])}{'…' if len(status) > 2 else ''}")
    if st.session_state.get("dash_only_pending", True):
        chips.append("Somente pendentes")

    last_gen = st.session_state.get("dash_last_generated")
    if chips or last_gen:
        left, right = rcols([3, 1])
        with left:
            if chips:
                st.caption(" • ".join(chips))
        with right:
            if st.button("Atualizar dados", use_container_width=True, key="dash_refresh_data"):
                st.session_state.pop("dash_pedidos_cache", None)
                st.session_state.pop("dash_df_view", None)
                st.session_state["dash_df_view_ready"] = False
                st.session_state["_dash_memo"] = {}
                st.rerun()
            if last_gen:
                st.caption(f"Atualizado: {last_gen}")

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

    # KPIs clicáveis (menos poluição: o próprio KPI vira ação)
    st.markdown('<div class="fu-kpi-main-click">', unsafe_allow_html=True)
    c1, c2, c3, c4 = rcols(4)
    with c1:
        if st.button(f"Pendentes\n{formatar_numero_br(pedidos_pendentes).split(',')[0]}", use_container_width=True, key="dash_kpi_pendentes"):
            st.session_state["consulta_nav_mode"] = "pendentes"
            st.session_state.current_page = "orders_search"
            st.session_state["_force_menu_sync"] = True
            st.rerun()
    with c2:
        if st.button(f"Atrasados\n{formatar_numero_br(pedidos_atrasados).split(',')[0]}", use_container_width=True, key="dash_kpi_atrasados"):
            st.session_state["consulta_nav_mode"] = "atrasados"
            st.session_state.current_page = "orders_search"
            st.session_state["_force_menu_sync"] = True
            st.rerun()
    with c3:
        if st.button(f"Vencendo (≤3d)\n{formatar_numero_br(pedidos_vencendo).split(',')[0]}", use_container_width=True, key="dash_kpi_vencendo"):
            st.session_state["consulta_nav_mode"] = "vencendo"
            st.session_state.current_page = "orders_search"
            st.session_state["_force_menu_sync"] = True
            st.rerun()
    with c4:
        if st.button(f"Valor em risco\n{formatar_moeda_br(valor_em_risco)}", use_container_width=True, key="dash_kpi_risco"):
            st.session_state["consulta_nav_mode"] = "risco"
            st.session_state.current_page = "orders_search"
            st.session_state["_force_menu_sync"] = True
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # Detalhes (só se o usuário abrir)
    with st.expander("Detalhes", expanded=False):
        d1, d2, d3, d4 = rcols(4)
        with d1:
            st.metric("Total", formatar_numero_br(total_pedidos).split(",")[0])
        with d2:
            taxa_entrega = (pedidos_entregues / total_pedidos * 100) if total_pedidos > 0 else 0.0
            st.metric("Entregues", formatar_numero_br(pedidos_entregues).split(",")[0], delta=f"{taxa_entrega:.1f}%".replace(".", ","))
        with d3:
            st.metric("Críticos", formatar_numero_br(pedidos_criticos).split(",")[0], delta_color="inverse" if pedidos_criticos > 0 else "normal")
        with d4:
            st.metric("Valor total", formatar_moeda_br(valor_total))

    st.markdown("---")
    
    # Abas para diferentes visualizações
    # Abas controláveis (permite manter aba selecionada via session_state)
    _tabs = ["Visão Geral", "Dashboard Avançado"]
    _default_idx = 0

    aba = ux.segmented("", _tabs, key="dash_active_tab", default=_tabs[_default_idx])

    tab1 = (aba == _tabs[0])
    tab2 = (aba == _tabs[1])
    if tab1:
        mobile_now = is_mobile()

        # =========================
        # Controles (aplicar visual)
        # =========================
        
        # =========================
        # Performance: Modo turbo
        # =========================
        turbo = st.toggle(
            "⚡ Modo turbo (mais rápido)",
            value=bool(st.session_state.get("dash_turbo", True)),
            help="Reduz custo de renderização (desliga labels em barras e algumas visões secundárias).",
            key="dash_turbo_toggle",
        )
        st.session_state["dash_turbo"] = bool(turbo)

        fast_charts = st.toggle(
            "🚀 Gráficos leves (melhor performance)",
            value=bool(st.session_state.get("dash_fast_charts", True)),
            help="Desativa interações pesadas e labels em barras quando necessário. Ideal para deixar o scroll/expanders mais fluidos.",
            key="dash_fast_charts_toggle",
        )
        st.session_state["dash_fast_charts"] = bool(fast_charts)

        # Config padrão de renderização Plotly (staticPlot acelera bastante em dashboards densos)
        plot_config = {"displayModeBar": False, "responsive": True, "staticPlot": bool(turbo)}
        st.subheader("Resumo acionável")

        default_viz = {
            "compacto": bool(mobile_now) or bool(st.session_state.get("dash_turbo", True)),
            "show_trend": True,
            # Em modo turbo, reduzir visões secundárias para ficar mais leve
            "show_rank": (not bool(st.session_state.get("dash_turbo", True))),
            "show_aging": (not bool(st.session_state.get("dash_turbo", True))),
            "show_action": True,
            "show_details": False,
            "show_dist": True,
            "show_scatter": False,
        }
        viz = st.session_state.setdefault("dash_viz", default_viz.copy())
        # Garantir compat caso novos campos sejam adicionados
        for k, v in default_viz.items():
            viz.setdefault(k, v)

        with st.form("dash_viz_form", clear_on_submit=False):
            # Modo compacto default no mobile (melhor percepção e performance)
            compacto_tmp = st.toggle(
                "Modo compacto (mostrar só o essencial)",
                value=bool(viz.get("compacto", False)),
                key="dash_viz_compacto_tmp",
            )

            with st.expander("Personalizar Dashboard", expanded=False):
                a, b, c, d = rcols([1, 1, 1, 1])
                with a:
                    show_dist_tmp = st.checkbox("Distribuição", value=bool(viz.get("show_dist", True)), key="dash_viz_show_dist_tmp")
                    show_trend_tmp = st.checkbox("Tendência", value=bool(viz.get("show_trend", True)), key="dash_viz_show_trend_tmp")
                with b:
                    show_rank_tmp = st.checkbox("Rankings", value=bool(viz.get("show_rank", True)), key="dash_viz_show_rank_tmp")
                    show_aging_tmp = st.checkbox("Aging", value=bool(viz.get("show_aging", True)), key="dash_viz_show_aging_tmp")
                with c:
                    show_action_tmp = st.checkbox("Aja agora", value=bool(viz.get("show_action", True)), key="dash_viz_show_action_tmp")
                    show_scatter_tmp = st.checkbox("Dispersão (valor x prazo)", value=bool(viz.get("show_scatter", False)), key="dash_viz_show_scatter_tmp")
                with d:
                    show_details_tmp = st.checkbox("KPIs detalhados", value=bool(viz.get("show_details", False)), key="dash_viz_show_details_tmp")

            apply_viz = st.form_submit_button("Aplicar visual", use_container_width=True)

        if apply_viz:
            st.session_state["dash_viz"] = {
                "compacto": bool(compacto_tmp),
                "show_trend": bool(show_trend_tmp),
                "show_rank": bool(show_rank_tmp),
                "show_aging": bool(show_aging_tmp),
                "show_action": bool(show_action_tmp),
                "show_details": bool(show_details_tmp),
                "show_dist": bool(show_dist_tmp),
                "show_scatter": bool(show_scatter_tmp),
            }
            st.toast("Visual atualizado", icon="🎛️")

        viz = st.session_state.get("dash_viz", default_viz)
        compacto = bool(viz.get("compacto", False))
        show_trend = bool(viz.get("show_trend", True))
        show_rank = bool(viz.get("show_rank", True))
        show_aging = bool(viz.get("show_aging", True))
        show_action = bool(viz.get("show_action", True))
        show_details = bool(viz.get("show_details", False))
        show_dist = bool(viz.get("show_dist", True))
        show_scatter = bool(viz.get("show_scatter", False))

        # =========================
        # Distribuição (rápida, bem 'interessante')
        # =========================
        if show_dist:
            st.markdown("#### Distribuição das pendências")
            sig = st.session_state.get("dash_last_generated", "")
            def _calc_dist():
                total = int(len(pendentes))
                a = int(len(atrasados))
                v = int(len(vencendo))
                ok = max(total - a - v, 0)
                return pd.DataFrame(
                    {
                        "grupo": ["Atrasados", "Vencendo (≤3d)", "No prazo"],
                        "qtd": [a, v, ok],
                        "valor": [
                            float(atrasados["_valor"].sum()),
                            float(vencendo["_valor"].sum()),
                            float((pendentes.drop(atrasados.index, errors="ignore").drop(vencendo.index, errors="ignore")["_valor"].sum()) if total else 0.0),
                        ],
                    }
                )
            dist = _memo("dist", sig, _calc_dist)
            c1, c2 = rcols(2) if not mobile_now else rcols(1)
            with c1:
                def _build_pie():
                    fig = px.pie(dist, names="grupo", values="qtd", hole=0.55)
                    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), legend_title_text="")
                    return fig
                fig_p = _fig_memo("dist_pie", sig, _build_pie)
                st.plotly_chart(fig_p, use_container_width=True, config=plot_config)
            with c2:
                def _build_bar():
                    fig = px.bar(dist, x="grupo", y="valor")
                    add_bar_labels(fig, kind="money")
                    fig.update_layout(height=280, margin=dict(l=10, r=30, t=10, b=10), xaxis_title="", yaxis_title="Valor (R$)")
                    style_plotly(fig, kind="bar", height=280, force_single_color=True)
                    return fig
                fig_v = _fig_memo("dist_bar", sig, _build_bar)
                st.plotly_chart(fig_v, use_container_width=True, config=plot_config)

        # =========================

        # =========================
        # Drill-down: UF / Departamento (clicável)
        # =========================
        st.markdown("#### Onde está o risco (UF / Departamento)")

        metric_geo = st.radio(
            "Métrica",
            ["Valor (R$)", "Quantidade"],
            horizontal=True,
            key="dash_geo_metric",
        )

        col_uf, col_dept = rcols([1, 1])

        # Base cacheada: evita custo em reruns por scroll/expanders
        sig = st.session_state.get("dash_last_generated", "")
        df_base = _memo("geo_base", sig, lambda: pendentes.copy())
        df_base["fornecedor_uf"] = df_base.get("fornecedor_uf", "").fillna("").astype(str).str.strip().str.upper()
        df_base["departamento"] = df_base.get("departamento", "").fillna("").astype(str).str.strip()

        with col_uf:
            if "fornecedor_uf" in df_base.columns and df_base["fornecedor_uf"].str.len().gt(0).any():
                def _calc_uf():
                    return (
                        df_base[df_base["fornecedor_uf"].str.len().gt(0)]
                        .groupby("fornecedor_uf")
                        .agg(Valor=("_valor", "sum"), Qtd=("_valor", "size"))
                        .sort_values(by="Valor", ascending=False)
                        .head(12)
                        .reset_index()
                        .rename(columns={"fornecedor_uf": "UF"})
                    )
                g_uf = _memo("geo_uf", sig, _calc_uf)

                xcol = "Valor" if metric_geo.startswith("Valor") else "Qtd"
                x_title = "Valor (R$)" if xcol == "Valor" else "Quantidade (itens)"
                label_kind = "money" if xcol == "Valor" else "count"

                def _build_fig_uf():
                    fig = px.bar(
                        g_uf,
                        x=xcol,
                        y="UF",
                        orientation="h",
                        title="Top 12 por UF",
                        custom_data=["Valor", "Qtd"],
                    )
                    add_bar_labels(fig, kind=label_kind, position="outside")
                    style_plotly(fig, height=460, kind="bar", force_single_color=True)
                    fig.update_yaxes(autorange="reversed", title="")
                    fig.update_xaxes(title=x_title)
                    fig.update_traces(
                        hovertemplate="<b>%{y}</b>"
                        "<br>Valor: R$ %{customdata[0]:,.0f}"
                        "<br>Quantidade: %{customdata[1]}"
                        "<extra></extra>"
                    )
                    return fig

                fig_uf = _fig_memo("geo_uf", f"{sig}:{xcol}", _build_fig_uf)

                st.caption("Clique em uma barra para abrir a Consulta já filtrada pela UF.")
                if (plotly_events is not None) and (not bool(st.session_state.get('dash_turbo', True))) and (not bool(st.session_state.get('dash_fast_charts', True))):
                    sel = plotly_events(fig_uf, click_event=True, hover_event=False, select_event=False, key="dash_drill_uf")
                    if sel:
                        uf = sel[0].get("y") or sel[0].get("x")
                        if uf:
                            _drill_to_consulta(uf=str(uf))
                else:
                    st.plotly_chart(fig_uf, use_container_width=True, config=plot_config)
                    uf_pick = st.selectbox("Ir para Consulta (UF)", [""] + g_uf["UF"].astype(str).tolist(), key="dash_uf_pick")
                    if uf_pick:
                        _drill_to_consulta(uf=uf_pick)
            else:
                st.info("Sem dados de UF para gerar o gráfico.")

        with col_dept:
            if "departamento" in df_base.columns and df_base["departamento"].str.len().gt(0).any():
                def _calc_dep():
                    return (
                        df_base[df_base["departamento"].str.len().gt(0)]
                        .groupby("departamento")
                        .agg(Valor=("_valor", "sum"), Qtd=("_valor", "size"))
                        .sort_values(by="Valor", ascending=False)
                        .head(12)
                        .reset_index()
                        .rename(columns={"departamento": "Departamento"})
                    )
                g_dep = _memo("geo_dep", sig, _calc_dep)

                xcol = "Valor" if metric_geo.startswith("Valor") else "Qtd"
                x_title = "Valor (R$)" if xcol == "Valor" else "Quantidade (itens)"
                label_kind = "money" if xcol == "Valor" else "count"

                def _build_fig_dep():
                    fig = px.bar(
                        g_dep,
                        x=xcol,
                        y="Departamento",
                        orientation="h",
                        title="Top 12 por Departamento",
                        custom_data=["Valor", "Qtd"],
                    )
                    add_bar_labels(fig, kind=label_kind, position="outside")
                    style_plotly(fig, height=460, kind="bar", force_single_color=True)
                    fig.update_yaxes(autorange="reversed", title="")
                    fig.update_xaxes(title=x_title)
                    fig.update_traces(
                        hovertemplate="<b>%{y}</b>"
                        "<br>Valor: R$ %{customdata[0]:,.0f}"
                        "<br>Quantidade: %{customdata[1]}"
                        "<extra></extra>"
                    )
                    return fig

                fig_dep = _fig_memo("geo_dep", f"{sig}:{xcol}", _build_fig_dep)

                st.caption("Clique em uma barra para abrir a Consulta já filtrada pelo Departamento.")
                if (plotly_events is not None) and (not bool(st.session_state.get('dash_turbo', True))) and (not bool(st.session_state.get('dash_fast_charts', True))):
                    sel = plotly_events(fig_dep, click_event=True, hover_event=False, select_event=False, key="dash_drill_dept")
                    if sel:
                        dep = sel[0].get("y") or sel[0].get("x")
                        if dep:
                            _drill_to_consulta(dept=str(dep))
                else:
                    st.plotly_chart(fig_dep, use_container_width=True, config=plot_config)
                    dep_pick = st.selectbox("Ir para Consulta (Departamento)", [""] + g_dep["Departamento"].astype(str).tolist(), key="dash_dep_pick")
                    if dep_pick:
                        _drill_to_consulta(dept=dep_pick)
            else:
                st.info("Sem dados de departamento para gerar o gráfico.")

# Tendência semanal (melhorada)
                # =========================
                if show_trend:
                    st.markdown("#### Tendência (semanal)")
                    sig = st.session_state.get("dash_last_generated", "")
                    def _calc_trend():
                        df_trend = pendentes.copy()
                        df_trend["_week"] = df_trend["_due"].dt.to_period("W").astype(str)
                        df_trend["_is_atrasado"] = (df_trend["_due"].notna() & (df_trend["_due"] < hoje)) | (df_trend["_atrasado"])
                        df_trend["_is_vencendo"] = df_trend["_due"].notna() & (df_trend["_due"] >= hoje) & (df_trend["_due"] <= data_limite)
                        grp = (
                            df_trend.groupby("_week").agg(
                                pendentes=("nr_oc", "count"),
                                atrasados=("_is_atrasado", "sum"),
                                vencendo=("_is_vencendo", "sum"),
                                valor_pendente=("_valor", "sum"),
                            ).reset_index()
                        )
                        grp["no_prazo"] = (grp["pendentes"] - grp["atrasados"] - grp["vencendo"]).clip(lower=0)
                        return grp

                    grp = _memo("trend", sig, _calc_trend)

                    if not grp.empty:
                        # 1) barras empilhadas (qtd)
                        fig_q = go.Figure()
                        fig_q.add_trace(go.Bar(x=grp["_week"], y=grp["atrasados"], name="Atrasados"))
                        fig_q.add_trace(go.Bar(x=grp["_week"], y=grp["vencendo"], name="Vencendo (≤3d)"))
                        fig_q.add_trace(go.Bar(x=grp["_week"], y=grp["no_prazo"], name="No prazo"))
                        fig_q.update_layout(barmode="stack", height=320, margin=dict(l=10, r=10, t=10, b=10),
                                            xaxis_title="Semana", yaxis_title="Qtd")
                        style_plotly(fig_q, kind="bar", height=360)
                        st.plotly_chart(fig_q, use_container_width=True, config=plot_config)

                        # 2) linha de valor pendente (se não estiver em mobile/compacto)
                        if not mobile_now and not compacto:
                            fig_val = go.Figure()
                            fig_val.add_trace(go.Scatter(x=grp["_week"], y=grp["valor_pendente"], mode="lines+markers+text",
                                                         name="Valor pendente", text=grp["valor_pendente"].round(0), textposition="top center"))
                            fig_val.update_layout(height=260, margin=dict(l=10, r=30, t=10, b=10),
                                                  xaxis_title="Semana", yaxis_title="Valor (R$)")
                            style_plotly(fig_val, kind="bar", height=360)
                            st.plotly_chart(fig_val, use_container_width=True, config=plot_config)
                    else:
                        st.caption("Sem dados suficientes para tendência.")

                # =========================
                # Seções pesadas: só quando não estiver em modo compacto
                # =========================
                if not compacto:
                    # =========================
                    # Rankings (mais legível)
                    # =========================
                    if show_rank:
                        c1, c2 = rcols(2) if not mobile_now else rcols(1)

                        with c1:
                            st.markdown("#### Top fornecedores (valor em risco)")
                            if "fornecedor_nome" in pendentes.columns and not pendentes.empty:
                                sig = st.session_state.get("dash_last_generated", "")
                                def _calc_risk_forn():
                                    risk = pd.concat([atrasados, vencendo], ignore_index=True)
                                    if risk.empty:
                                        return None
                                    out = (
                                        risk.groupby("fornecedor_nome", dropna=False)["_valor"]
                                        .sum()
                                        .sort_values(ascending=False)
                                        .head(10)
                                    )
                                    return out

                                r = _memo("rank_forn", sig, _calc_risk_forn)
                                if r is not None and not r.empty:
                                    fig_f = px.bar(x=r.values, y=r.index, orientation="h")
                                    add_bar_labels(fig_f, kind="money")
                                    fig_f.update_traces(text=r.values.round(0), texttemplate="%{text}", textposition="outside", cliponaxis=False)
                                    fig_f.update_layout(height=360, margin=dict(l=10, r=40, t=10, b=10),
                                                        xaxis_title="Valor em risco (R$)", yaxis_title="")
                                    style_plotly(fig_f, kind="bar", height=360, force_single_color=True)
                                    st.plotly_chart(fig_f, use_container_width=True, config=plot_config)
                                else:
                                    st.caption("Sem pedidos em risco no recorte.")
                            else:
                                st.caption("Coluna fornecedor_nome ausente ou sem dados.")

                        with c2:
                            st.markdown("#### Top departamentos (qtd em risco)")
                            if "departamento" in pendentes.columns and not pendentes.empty:
                                sig = st.session_state.get("dash_last_generated", "")
                                def _calc_risk_dept():
                                    tmp = pd.concat([atrasados, vencendo], ignore_index=True)
                                    if tmp.empty:
                                        return None
                                    return (
                                        tmp["departamento"].astype(str).str.strip()
                                        .replace("", pd.NA).dropna()
                                        .value_counts().head(10)
                                    )

                                d = _memo("rank_dept", sig, _calc_risk_dept)
                                if d is not None and not d.empty:
                                    fig_d = px.bar(x=d.values, y=d.index, orientation="h")
                                    add_bar_labels(fig_d, kind="count")
                                    fig_d.update_traces(text=d.values, texttemplate="%{text}", textposition="outside", cliponaxis=False)
                                    fig_d.update_layout(height=360, margin=dict(l=10, r=40, t=10, b=10),
                                                        xaxis_title="Quantidade", yaxis_title="")
                                    st.plotly_chart(fig_d, use_container_width=True, config=plot_config)
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
                            sig = st.session_state.get("dash_last_generated", "")
                            def _calc_aging():
                                dias_atraso = (hoje - atrasados["_due"]).dt.days.clip(lower=0)
                                bins = [-1, 7, 15, 30, 60, 10_000]
                                labels = ["0–7", "8–15", "16–30", "31–60", "60+"]
                                return pd.cut(dias_atraso, bins=bins, labels=labels).value_counts().reindex(labels).fillna(0).astype(int)

                            aging = _memo("aging", sig, _calc_aging)
                            fig_a = px.bar(x=aging.index, y=aging.values)
                            add_bar_labels(fig_a, kind="count")
                            fig_a.update_traces(text=aging.values, texttemplate="%{text}", textposition="outside", cliponaxis=False)
                            fig_a.update_layout(height=320, margin=dict(l=10, r=40, t=10, b=10),
                                                xaxis_title="Dias em atraso", yaxis_title="Quantidade")
                            style_plotly(fig_a, kind="bar", height=320, force_single_color=True)
                            st.plotly_chart(fig_a, use_container_width=True, config=plot_config)
                        else:
                            ux.ok("Sem pedidos atrasados no recorte atual.")

                    # =========================
                    # Dispersão (valor x dias para vencimento)
                    # =========================
                    if show_scatter and not pendentes.empty:
                        st.markdown("#### Valor x Prazo (dispersão)")
                        sig = st.session_state.get("dash_last_generated", "")
                        def _calc_scatter():
                            tmp = pendentes.copy()
                            tmp["_dias_para_venc"] = (tmp["_due"] - hoje).dt.days
                            tmp["_grupo"] = "No prazo"
                            tmp.loc[tmp["_dias_para_venc"] < 0, "_grupo"] = "Atrasado"
                            tmp.loc[(tmp["_dias_para_venc"] >= 0) & (tmp["_dias_para_venc"] <= 3), "_grupo"] = "Vencendo"
                            return tmp[["_dias_para_venc", "_valor", "_grupo", "fornecedor_nome", "departamento", "nr_oc"]].copy()

                        sc = _memo("scatter", sig, _calc_scatter)
                        fig_s = px.scatter(sc, x="_dias_para_venc", y="_valor", color="_grupo", hover_data=["nr_oc", "fornecedor_nome", "departamento"])
                        fig_s.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                                            xaxis_title="Dias para vencimento (negativo = atraso)", yaxis_title="Valor (R$)")
                        style_plotly(fig_s, kind="bar")
                        st.plotly_chart(fig_s, use_container_width=True, config=plot_config)

                    # =========================
                    # Aja agora (paginado + ver mais)
                    # =========================
                    if show_action:
                        st.markdown("#### Aja agora")
                        acao = pd.concat(
                            [criticos.assign(_prior=0), atrasados.assign(_prior=1), vencendo.assign(_prior=2)],
                            ignore_index=True,
                        )
                        if not acao.empty:
                            acao["_descricao"] = acao.get("descricao", "").astype(str).str.slice(0, 80)
                            acao["_due_str"] = acao["_due"].dt.strftime("%d/%m/%Y")
                            acao = acao.sort_values(["_prior", "_valor"], ascending=[True, False])

                            # Controles de paginação
                            p1, p2, p3 = rcols([1, 1, 2]) if not mobile_now else rcols(1)
                            with p1:
                                page_size = st.selectbox("Itens por página", [10, 20, 50], index=1, key="dash_acao_page_size")
                            total_rows = int(len(acao))
                            max_pages = max((total_rows + int(page_size) - 1) // int(page_size), 1)
                            with p2:
                                page = st.number_input("Página", min_value=1, max_value=max_pages, value=min(int(st.session_state.get("dash_acao_page", 1)), max_pages), step=1, key="dash_acao_page")
                                st.session_state["dash_acao_page"] = int(page)
                            with p3:
                                st.caption(f"{total_rows} itens • {max_pages} páginas")

                            ini = (int(page) - 1) * int(page_size)
                            fim = ini + int(page_size)
                            acao_page = acao.iloc[ini:fim].copy()

                            view_cols = []
                            for col in ["nr_oc", "_descricao", "departamento", "fornecedor_nome", "_due_str", "_valor"]:
                                if col in acao_page.columns:
                                    view_cols.append(col)

                            df_show = acao_page[view_cols].copy()
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

                            if st.button("Abrir lista na Consulta (itens filtrados)", use_container_width=True, key="dash_go_acao"):
                                ocs = acao["nr_oc"].dropna().astype(str).unique().tolist() if "nr_oc" in acao.columns else []
                                st.session_state["quick_filter"] = {"tipo": "lista", "nro_ocs": ocs}
                                st.session_state.current_page = "Consultar Pedidos"
                                st.rerun()
                        else:
                            st.caption("Nada para agir agora com os filtros atuais.")
                else:
                    ux.info("Modo compacto ativo: desative para ver Rankings, Aging e Aja agora.")

                # KPIs detalhados (opcional)
                if show_details:
                    with st.expander("KPIs detalhados", expanded=True):
                        d1, d2, d3, d4 = rcols(4)
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
    
# ============================================
# PÁGINA DE MAPA GEOGRÁFICO (NOVA VERSÃO)
# ============================================
