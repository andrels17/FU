"""
Módulo de Dashboard Avançado
Gráficos interativos e análises preditivas
"""


from __future__ import annotations
import streamlit as st
from src.ui.plotly_style import style_plotly, add_bar_labels
import datetime


import pandas as pd
# -------------------------------
# Mobile/cards-first helpers (polido)
# -------------------------------
def _is_cards_first() -> bool:
    # Use uma escolha explícita (funciona no desktop também)
    return bool(st.session_state.get("ui_cards_first", True))


def _pretty_label(col: str) -> str:
    col = str(col)
    mapping = {
        "nr_oc": "Nº OC",
        "nr_solicitacao": "Nº Solicitação",
        "cod_material": "Cód. Material",
        "cod_equipamento": "Equipamento",
        "qtde_solicitada": "Qtd. Solicitada",
        "qtde_entregue": "Qtd. Entregue",
        "pendente_calc": "Qtd. Pendente",
        "pendente_ui": "Qtd. Pendente",
        "valor_total": "Valor Total",
        "valor_unitario": "Valor Unitário",
        "departamento": "Departamento",
        "fornecedor": "Fornecedor",
        "uf": "UF",
        "status": "Status",
        "data_entrega_real": "Data Entrega",
        "data_oc": "Data OC",
        "criado_em": "Criado em",
        "atualizado_em": "Atualizado em",
    }
    if col in mapping:
        return mapping[col]
    return (
        col.replace("_", " ")
        .replace("qtde", "qtd")
        .title()
    )


def _fmt_date(v) -> str:
    if v is None:
        return "—"
    try:
        import pandas as _pd
        if isinstance(v, _pd.Timestamp):
            if _pd.isna(v):
                return "—"
            return v.strftime("%d/%m/%Y")
    except Exception:
        pass
    s = str(v).strip()
    if not s:
        return "—"
    # tenta ISO (datas)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.datetime.strptime(s[:len(fmt)], fmt)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            continue
    return s


def _fmt_money(v) -> str:
    try:
        x = float(v)
    except Exception:
        return "—" if v is None or str(v).strip() == "" else str(v)
    s = f"{x:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _fmt_value(col: str, v) -> str:
    if v is None:
        return "—"
    if col in ("valor_total", "valor_unitario", "preco", "valor"):
        return _fmt_money(v)
    if col.startswith("data_") or col.endswith("_em") or col.endswith("_real"):
        return _fmt_date(v)
    try:
        if isinstance(v, (int, float)) and col.startswith(("qtde", "qtd", "pendente")):
            return f"{float(v):g}"
    except Exception:
        pass
    s = str(v).strip()
    return s if s else "—"


def _badge(text: str) -> str:
    t = (text or "").strip()
    if not t or t == "—":
        return ""
    color = "var(--fu-muted)"
    tl = t.lower()
    if tl in ("entregue", "ok", "concluido", "concluído"):
        color = "var(--fu-success, #22c55e)"
    elif tl in ("pendente", "atrasado", "critico", "crítico"):
        color = "var(--fu-danger, #ef4444)"
    return (
        "<span style='padding:2px 10px;border:1px solid rgba(255,255,255,.10);"
        f"border-radius:999px;color:{color};font-size:0.82rem;'>{t}</span>"
    )


def _kv_grid(r: dict, cols: list[str], *, max_items: int = 8) -> None:
    show = [c for c in cols if c in r][:max_items]
    if not show:
        return
    grid = st.columns(2, gap="small")
    for i, c in enumerate(show):
        with grid[i % 2]:
            st.caption(_pretty_label(c))
            st.write(_fmt_value(c, r.get(c)))


def _detail_view(title: str, r: dict, *, primary: list[str], secondary: list[str]) -> None:
    st.markdown(f"### {title}")
    st.markdown(_badge(str(r.get("status") or "")), unsafe_allow_html=True)
    st.markdown("#### Resumo")
    _kv_grid(r, primary, max_items=8)
    if secondary:
        st.markdown("---")
        st.markdown("#### Detalhes")
        _kv_grid(r, secondary, max_items=14)


def _open_detail(title: str, r: dict, *, primary: list[str], secondary: list[str]) -> None:
    if hasattr(st, "dialog"):
        @st.dialog(title)
        def _d():
            _detail_view(title, r, primary=primary, secondary=secondary)
        _d()
    else:
        with st.expander(title, expanded=True):
            _detail_view(title, r, primary=primary, secondary=secondary)


def _cards_first_list(
    df: pd.DataFrame,
    *,
    title_col: str,
    subtitle_cols: list[str],
    badge_col: str | None = None,
    key_prefix: str = "cf",
    primary_detail_cols: list[str] | None = None,
    secondary_detail_cols: list[str] | None = None,
) -> None:
    """Renderiza lista em cards (mobile-first) com detalhes em dialog."""
    if df is None or df.empty:
        st.info("Nada para exibir.")
        return

    cols_all = list(df.columns)
    primary_detail_cols = primary_detail_cols or [
        c for c in [
            title_col, "status", "nr_oc", "nr_solicitacao", "departamento",
            "cod_equipamento", "cod_material",
            "qtde_solicitada", "qtde_entregue", "pendente_calc", "pendente_ui",
            "valor_total", "valor_unitario", "data_entrega_real", "data_oc"
        ] if c in cols_all
    ]
    secondary_detail_cols = secondary_detail_cols or [
        c for c in cols_all
        if c not in set(primary_detail_cols + ["id", "tenant_id"])
        and not str(c).lower().endswith("_id")
    ]

    rows = df.to_dict("records")
    for i, r in enumerate(rows):
        rid = str(r.get("id") or r.get("pedido_id") or i)
        title_val = _fmt_value(title_col, r.get(title_col))
        badge_val = _fmt_value(badge_col, r.get(badge_col)) if badge_col else ""

        with st.container(border=True):
            if badge_col and badge_val != "—":
                st.markdown(
                    f"**{title_val}**  ·  {_badge(badge_val)}",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"**{title_val}**")

            _kv_grid(r, subtitle_cols, max_items=6)

            if st.button("Ver detalhes", key=f"{key_prefix}_detail_{rid}_{i}", use_container_width=True):
                _open_detail("Detalhes", r, primary=primary_detail_cols, secondary=secondary_detail_cols)


def _pretty_label(col: str) -> str:
    return (
        str(col)
        .replace("_", " ")
        .replace("qtde", "qtd")
        .replace("nr ", "nº ")
        .title()
    )


def _fmt_value(v):
    if v is None:
        return "—"
    try:
        # timestamps/dates
        import pandas as _pd
        if isinstance(v, (_pd.Timestamp,)):
            if _pd.isna(v):
                return "—"
            return v.strftime("%d/%m/%Y")
    except Exception:
        pass
    s = str(v).strip()
    return s if s else "—"


def _render_kv_grid(r: dict, cols: list[str], *, max_items: int = 6) -> None:
    show_cols = [c for c in cols if c in r][:max_items]
    if not show_cols:
        return
    grid = st.columns(2, gap="small")
    for i, c in enumerate(show_cols):
        with grid[i % 2]:
            st.caption(_pretty_label(c))
            st.write(_fmt_value(r.get(c)))


def _render_detail_dialog(title: str, r: dict, *, primary_cols: list[str], secondary_cols: list[str]) -> None:
    if hasattr(st, "dialog"):
        @st.dialog(title)
        def _d():
            st.markdown("#### Resumo")
            _render_kv_grid(r, primary_cols, max_items=6)
            if secondary_cols:
                st.markdown("---")
                st.markdown("#### Detalhes")
                _render_kv_grid(r, secondary_cols, max_items=12)
        _d()
    else:
        with st.expander("Detalhes", expanded=True):
            st.markdown("#### Resumo")
            _render_kv_grid(r, primary_cols, max_items=6)
            if secondary_cols:
                st.markdown("---")
                st.markdown("#### Detalhes")
                _render_kv_grid(r, secondary_cols, max_items=12)


def _cards_first_list(
    df: pd.DataFrame,
    *,
    title_col: str,
    subtitle_cols: list[str],
    badge_col: str | None = None,
    key_prefix: str = "cf",
    primary_detail_cols: list[str] | None = None,
    secondary_detail_cols: list[str] | None = None,
) -> None:
    """Renderiza uma lista em modo cards-first com detalhes em dialog/expander."""
    if df is None or df.empty:
        st.info("Nada para exibir.")
        return

    primary_detail_cols = primary_detail_cols or subtitle_cols[:6]
    secondary_detail_cols = secondary_detail_cols or [c for c in df.columns if c not in set(primary_detail_cols + [title_col])]

    rows = df.to_dict("records")
    for i, r in enumerate(rows):
        rid = str(r.get("id") or r.get("pedido_id") or i)
        title_val = _fmt_value(r.get(title_col))
        badge_val = _fmt_value(r.get(badge_col)) if badge_col else ""
        with st.container(border=True):
            # Header
            if badge_col and badge_val != "—":
                st.markdown(
                    f"**{title_val}**  ·  <span style='color: var(--fu-muted);'>{badge_val}</span>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"**{title_val}**")

            # Body
            _render_kv_grid(r, subtitle_cols, max_items=6)

            # Action
            if st.button("Ver detalhes", key=f"{key_prefix}_detail_{rid}_{i}", use_container_width=True):
                _render_detail_dialog("Detalhes", r, primary_cols=primary_detail_cols, secondary_cols=secondary_detail_cols)



from src.ui import ux

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

def _go_consulta(*, q: str = "", depto: str = "Todos", status: str = "Todos", somente_atrasados: bool = False):
    """Drilldown: envia para a tela 'Consultar Pedidos' usando os filtros já existentes."""
    st.session_state.update(
        {
            "c_q": q or "",
            "c_depto": depto or "Todos",
            "c_status": status or "Todos",
            "c_atraso": bool(somente_atrasados),
            "c_pag": 1,
        }
    )
    st.session_state.current_page = "Consultar Pedidos"
    st.rerun()

def _fmt_int(n: int) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return str(n)

def _safe_col(df: pd.DataFrame, *cands: str) -> str | None:
    for c in cands:
        if c in df.columns:
            return c
    return None


def _ensure_datetime(s: pd.Series) -> pd.Series:
    try:
        if pd.api.types.is_datetime64_any_dtype(s):
            return s
        return pd.to_datetime(s, errors="coerce")
    except Exception:
        return pd.to_datetime(pd.Series([pd.NaT] * len(s)), errors="coerce")

def _normalize_bool(s: pd.Series) -> pd.Series:
    if s is None:
        return pd.Series([], dtype=bool)
    if pd.api.types.is_bool_dtype(s):
        return s.fillna(False)
    return (
        s.astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "sim", "yes", "y"])
        .fillna(False)
    )

def _has_cols(df: pd.DataFrame, cols: list[str]) -> bool:
    return all(c in df.columns for c in cols)

def criar_grafico_evolucao_temporal(df_pedidos, formatar_moeda_br):
    """Cria gráfico de linha com evolução de pedidos e valores ao longo do tempo"""
    
    st.subheader("Evolução Temporal de Pedidos e Valores")
    
    # Validar se há dados
    if df_pedidos.empty or 'data_solicitacao' not in df_pedidos.columns:
        ux.info("Dados insuficientes para gerar o gráfico de evolução temporal")
        return
    
    # Preparar dados
    df_temporal = df_pedidos.copy()
    
    # Remover valores nulos
    df_temporal = df_temporal[df_temporal['data_solicitacao'].notna()].copy()
    
    if df_temporal.empty:
        ux.info("📭 Não há pedidos com data de solicitação válida")
        return
    
    # Converter para datetime se ainda não for
    try:
        if not pd.api.types.is_datetime64_any_dtype(df_temporal['data_solicitacao']):
            df_temporal['data_solicitacao'] = _ensure_datetime(df_temporal['data_solicitacao'])
            # Remover valores que não puderam ser convertidos
            df_temporal = df_temporal[df_temporal['data_solicitacao'].notna()].copy()
            
        if df_temporal.empty:
            ux.info("📭 Não há pedidos com data de solicitação válida")
            return
    except Exception as e:
        st.error(f"Erro ao processar datas: {e}")
        return
    
    df_temporal['mes_ano'] = df_temporal['data_solicitacao'].dt.to_period('M')
    
    # Agrupar por mês
    df_agrupado = df_temporal.groupby('mes_ano').agg({
        'id': 'count',
        'valor_total': 'sum'
    }).reset_index()
    
    df_agrupado['mes_ano_str'] = df_agrupado['mes_ano'].astype(str)
    
    # Criar figura com dois eixos Y
    fig = go.Figure()
    
    # Linha de quantidade de pedidos
    fig.add_trace(go.Scatter(
        x=df_agrupado['mes_ano_str'],
        y=df_agrupado['id'],
        name='Quantidade de Pedidos',
        mode='lines+markers',
        line=dict(color='#667eea', width=3),
        marker=dict(size=10, color='#667eea'),
        yaxis='y',
        hovertemplate='<b>%{x}</b><br>Pedidos: %{y}<extra></extra>'
    ))
    
    # Linha de valor total
    fig.add_trace(go.Scatter(
        x=df_agrupado['mes_ano_str'],
        y=df_agrupado['valor_total'],
        name='Valor Total (R$)',
        mode='lines+markers',
        line=dict(color='#f093fb', width=3, dash='dot'),
        marker=dict(size=10, color='#f093fb', symbol='diamond'),
        yaxis='y2',
        hovertemplate='<b>%{x}</b><br>Valor: R$ %{y:,.2f}<extra></extra>'
    ))
    
    # Layout com dois eixos Y
    fig.update_layout(
        xaxis=dict(
            title='Mês/Ano',
            titlefont=dict(color='white'),
            tickfont=dict(color='white'),
            showgrid=True,
            gridcolor='#2d3748'
        ),
        yaxis=dict(
            title='Quantidade de Pedidos',
            titlefont=dict(color='#667eea'),
            tickfont=dict(color='#667eea'),
            showgrid=True,
            gridcolor='#2d3748'
        ),
        yaxis2=dict(
            title='Valor Total (R$)',
            titlefont=dict(color='#f093fb'),
            tickfont=dict(color='#f093fb'),
            overlaying='y',
            side='right',
            showgrid=False
        ),
        height=450,
        hovermode='x unified',
        paper_bgcolor='#0e1117',
        plot_bgcolor='#1a1d29',
        font=dict(color='white'),
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            bgcolor='rgba(0,0,0,0.5)',
            bordercolor='white',
            borderwidth=1
        )
    )
    
    style_plotly(fig)
    st.plotly_chart(fig, use_container_width=True)
    
    # Calcular tendências
    if len(df_agrupado) >= 2:
        variacao_pedidos = ((df_agrupado['id'].iloc[-1] - df_agrupado['id'].iloc[-2]) / df_agrupado['id'].iloc[-2] * 100)
        variacao_valor = ((df_agrupado['valor_total'].iloc[-1] - df_agrupado['valor_total'].iloc[-2]) / df_agrupado['valor_total'].iloc[-2] * 100)
        
        col1, col2 = st.columns(2)
        with col1:
            delta_pedidos = f"+{variacao_pedidos:.1f}%" if variacao_pedidos > 0 else f"{variacao_pedidos:.1f}%"
            st.metric(
                "📊 Variação de Pedidos (mês anterior)",
                f"{int(df_agrupado['id'].iloc[-1])} pedidos",
                delta=delta_pedidos.replace('.', ',')
            )
        
        with col2:
            delta_valor = f"+{variacao_valor:.1f}%" if variacao_valor > 0 else f"{variacao_valor:.1f}%"
            st.metric(
                "Variação de Valor (mês anterior)",
                formatar_moeda_br(df_agrupado['valor_total'].iloc[-1]),
                delta=delta_valor.replace('.', ',')
            )

def criar_funil_conversao(df_pedidos: pd.DataFrame):
    """Cria gráfico de funil de conversão de pedidos (com validações)."""

    st.subheader("Funil de Conversão de Pedidos")

    if df_pedidos is None or df_pedidos.empty:
        ux.info("Sem dados para montar o funil.")
        return

    if not _has_cols(df_pedidos, ["status", "entregue"]):
        ux.info("📭 Dados insuficientes (colunas esperadas: status, entregue).")
        st.caption(f"Colunas disponíveis: {list(df_pedidos.columns)}")
        return

    total_pedidos = int(len(df_pedidos))
    em_transito = int((df_pedidos["status"].astype(str).str.strip() == "Em trânsito").sum())

    entregue = _normalize_bool(df_pedidos["entregue"])
    entregues = int(entregue.sum())

    if "atrasado" in df_pedidos.columns:
        atrasado = _normalize_bool(df_pedidos["atrasado"])
        no_prazo = int((entregue & (~atrasado)).sum())
    else:
        no_prazo = None

    y = ["Pedidos Realizados", "Em Trânsito", "Entregues"]
    x = [total_pedidos, em_transito, entregues]
    if no_prazo is not None:
        y.append("Entregues no Prazo")
        x.append(no_prazo)

    fig = go.Figure(
        go.Funnel(
            y=y,
            x=x,
            textposition="inside",
            textinfo="value+percent initial",
            connector=dict(line=dict(color="#2d3748", width=2)),
        )
    )
    fig.update_layout(height=380, paper_bgcolor="#0e1117", plot_bgcolor="#1a1d29", font=dict(color="white", size=14))
    style_plotly(fig)
    st.plotly_chart(fig, use_container_width=True)

    # KPIs
    c1, c2, c3 = st.columns(3)
    with c1:
        taxa_entrega = (entregues / total_pedidos * 100) if total_pedidos > 0 else 0
        st.metric("Taxa de Entrega", f"{taxa_entrega:.1f}%".replace(".", ","))

    with c2:
        if no_prazo is None:
            st.metric("Entregas no Prazo", "—")
        else:
            taxa_prazo = (no_prazo / entregues * 100) if entregues > 0 else 0
            st.metric("Entregas no Prazo", f"{taxa_prazo:.1f}%".replace(".", ","))

    with c3:
        taxa_transito = (em_transito / total_pedidos * 100) if total_pedidos > 0 else 0
        st.metric("Em Trânsito", f"{taxa_transito:.1f}%".replace(".", ","))

def criar_heatmap_pedidos(df_pedidos):
    """Cria heatmap de pedidos por dia da semana e hora"""
    
    st.subheader("Mapa de Calor - Pedidos por Dia e Período")
    
    df_heat = df_pedidos.copy()
    
    # Validar se há dados
    if df_heat.empty or 'data_solicitacao' not in df_heat.columns:
        ux.info("Dados insuficientes para gerar o mapa de calor")
        return
    
    # Remover valores nulos
    df_heat = df_heat[df_heat['data_solicitacao'].notna()].copy()
    
    if df_heat.empty:
        ux.info("Não há pedidos com data de solicitação válida")
        return
    
    # Converter para datetime se ainda não for
    try:
        if not pd.api.types.is_datetime64_any_dtype(df_heat['data_solicitacao']):
            df_heat['data_solicitacao'] = _ensure_datetime(df_heat['data_solicitacao'])
            # Remover valores que não puderam ser convertidos
            df_heat = df_heat[df_heat['data_solicitacao'].notna()].copy()
            
        if df_heat.empty:
            ux.info("Não há pedidos com data de solicitação válida")
            return
    except Exception as e:
        st.error(f"Erro ao processar datas: {e}")
        return
    
    df_heat['dia_semana'] = df_heat['data_solicitacao'].dt.day_name()
    df_heat['hora'] = df_heat['data_solicitacao'].dt.hour
    
    # Mapear dias para português
    dias_pt = {
        'Monday': 'Segunda',
        'Tuesday': 'Terça',
        'Wednesday': 'Quarta',
        'Thursday': 'Quinta',
        'Friday': 'Sexta',
        'Saturday': 'Sábado',
        'Sunday': 'Domingo'
    }
    df_heat['dia_semana'] = df_heat['dia_semana'].map(dias_pt)
    
    # Categorizar períodos do dia
    def categorizar_periodo(hora):
        if 6 <= hora < 12:
            return 'Manhã (6h-12h)'
        elif 12 <= hora < 18:
            return 'Tarde (12h-18h)'
        elif 18 <= hora < 24:
            return 'Noite (18h-24h)'
        else:
            return 'Madrugada (0h-6h)'
    
    df_heat['periodo'] = df_heat['hora'].apply(categorizar_periodo)
    
    # Agrupar
    heatmap_data = df_heat.groupby(['dia_semana', 'periodo']).size().reset_index(name='quantidade')
    
    # Pivot para matriz
    ordem_dias = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    ordem_periodos = ['Manhã (6h-12h)', 'Tarde (12h-18h)', 'Noite (18h-24h)', 'Madrugada (0h-6h)']
    
    pivot_data = heatmap_data.pivot(index='dia_semana', columns='periodo', values='quantidade').fillna(0)
    
    # Reindexar linhas (dias) e colunas (períodos) para garantir que todas existam
    pivot_data = pivot_data.reindex(index=ordem_dias, columns=ordem_periodos, fill_value=0)
    
    # Criar heatmap
    fig = go.Figure(data=go.Heatmap(
        z=pivot_data.values,
        x=pivot_data.columns,
        y=pivot_data.index,
        colorscale='Purples',
        text=pivot_data.values,
        texttemplate='%{text}',
        textfont=dict(size=14, color='white'),
        hovertemplate='<b>%{y}</b><br>%{x}<br>Pedidos: %{z}<extra></extra>',
        colorbar=dict(
            title='Pedidos',
            titlefont=dict(color='white'),
            tickfont=dict(color='white'),
            bgcolor='rgba(0,0,0,0.6)',
            bordercolor='white',
            borderwidth=2
        )
    ))
    
    fig.update_layout(
        height=400,
        xaxis=dict(title='Período do Dia', titlefont=dict(color='white'), tickfont=dict(color='white')),
        yaxis=dict(title='Dia da Semana', titlefont=dict(color='white'), tickfont=dict(color='white')),
        paper_bgcolor='#0e1117',
        plot_bgcolor='#1a1d29',
        font=dict(color='white')
    )
    
    style_plotly(fig)
    st.plotly_chart(fig, use_container_width=True)

def criar_comparativo_periodos(df_pedidos, formatar_moeda_br):
    """Cria comparativo entre períodos (mensal/trimestral)"""
    
    st.subheader("Comparativo de Períodos")
    
    # Validar se há dados
    if df_pedidos.empty or 'data_solicitacao' not in df_pedidos.columns:
        ux.info("Dados insuficientes para gerar o comparativo de períodos")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        tipo_periodo = st.selectbox(
            "Selecione o período:",
            ["Mensal", "Trimestral"],
            key="periodo_comparativo"
        )
    
    with col2:
        metrica = st.selectbox(
            "Métrica:",
            ["Quantidade de Pedidos", "Valor Total"],
            key="metrica_comparativo"
        )
    
    # Preparar dados
    df_comp = df_pedidos.copy()
    
    # Remover valores nulos
    df_comp = df_comp[df_comp['data_solicitacao'].notna()].copy()
    
    if df_comp.empty:
        ux.info("Não há pedidos com data de solicitação válida")
        return
    
    # Converter para datetime se ainda não for
    try:
        if not pd.api.types.is_datetime64_any_dtype(df_comp['data_solicitacao']):
            df_comp['data_solicitacao'] = _ensure_datetime(df_comp['data_solicitacao'])
            # Remover valores que não puderam ser convertidos
            df_comp = df_comp[df_comp['data_solicitacao'].notna()].copy()
            
        if df_comp.empty:
            ux.info("Não há pedidos com data de solicitação válida")
            return
    except Exception as e:
        st.error(f"Erro ao processar datas: {e}")
        return
    
    if tipo_periodo == "Mensal":
        df_comp['periodo'] = df_comp['data_solicitacao'].dt.to_period('M').astype(str)
    else:  # Trimestral
        df_comp['periodo'] = df_comp['data_solicitacao'].dt.to_period('Q').astype(str)
    
    if metrica == "Quantidade de Pedidos":
        df_agrupado = df_comp.groupby('periodo').size().reset_index(name='valor')
        titulo_y = 'Quantidade de Pedidos'
    else:
        df_agrupado = df_comp.groupby('periodo')['valor_total'].sum().reset_index(name='valor')
        titulo_y = 'Valor Total (R$)'
    
    # Criar gráfico de barras com comparação
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=df_agrupado['periodo'],
        y=df_agrupado['valor'],
        marker=dict(
            color=df_agrupado['valor'],
            colorscale='Purples',
            line=dict(color='#ffffff', width=2)
        ),
        text=df_agrupado['valor'].apply(lambda x: formatar_moeda_br(x) if metrica == "Valor Total" else f"{int(x)}"),
        textposition='outside',
        hovertemplate='<b>%{x}</b><br>' + titulo_y + ': %{text}<extra></extra>'
    ))
    
    # Adicionar linha de média
    media = df_agrupado['valor'].mean()
    fig.add_hline(
        y=media,
        line_dash="dash",
        line_color="#00d4ff",
        annotation_text=f"Média: {formatar_moeda_br(media) if metrica == 'Valor Total' else f'{int(media)}'}",
        annotation_position="right",
        annotation_font_color="#00d4ff"
    )
    
    fig.update_layout(
        xaxis=dict(title='Período', titlefont=dict(color='white'), tickfont=dict(color='white')),
        yaxis=dict(title=titulo_y, titlefont=dict(color='white'), tickfont=dict(color='white'), gridcolor='#2d3748'),
        height=450,
        showlegend=False,
        paper_bgcolor='#0e1117',
        plot_bgcolor='#1a1d29',
        font=dict(color='white')
    )
    
    style_plotly(fig)
    st.plotly_chart(fig, use_container_width=True)
    
    # Estatísticas do período
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Máximo", formatar_moeda_br(df_agrupado['valor'].max()) if metrica == "Valor Total" else f"{int(df_agrupado['valor'].max())}")
    
    with col2:
        st.metric("Mínimo", formatar_moeda_br(df_agrupado['valor'].min()) if metrica == "Valor Total" else f"{int(df_agrupado['valor'].min())}")
    
    with col3:
        st.metric("Média", formatar_moeda_br(df_agrupado['valor'].mean()) if metrica == "Valor Total" else f"{int(df_agrupado['valor'].mean())}")
    
    with col4:
        desvio = df_agrupado['valor'].std()
        st.metric("Desvio Padrão", formatar_moeda_br(desvio) if metrica == "Valor Total" else f"{int(desvio)}")

def exibir_dashboard_avancado(df_pedidos: pd.DataFrame, formatar_moeda_br):
    """Exibe o dashboard avançado completo (usando o mesmo recorte do Dashboard)."""

    st.title("Dashboard Avançado")

    # Se você está usando o fluxo "Gerar dashboard", respeita isso aqui também
    if st.session_state.get("dash_filters_applied") is False:
        ux.info("Selecione os filtros e clique em **Gerar dashboard** na aba principal para alimentar o Dashboard Avançado.")
        return

    if df_pedidos is None or df_pedidos.empty:
        ux.info("Nenhum pedido no recorte atual.")
        return

    # Seções visíveis (mesmo estilo do dashboard)
    with st.expander("Personalizar (avançado)", expanded=False):
        a, b, c = st.columns(3)
        with a:
            show_evol = st.checkbox("Evolução temporal", value=True, key="adv_show_evol")
            show_funil = st.checkbox("Funil de conversão", value=True, key="adv_show_funil")
        with b:
            show_heat = st.checkbox("Heatmap", value=True, key="adv_show_heat")
            show_comp = st.checkbox("Comparativo períodos", value=True, key="adv_show_comp")
        with c:
            st.caption(f"Linhas no recorte: **{len(df_pedidos):,}**".replace(",", "."))

    # =========================
    # Visão híbrida: Insights + ações (operacional)
    # =========================
    st.subheader("Insights do recorte")

    col_val = _safe_col(df_pedidos, "valor_total", "valor")
    col_for = _safe_col(df_pedidos, "fornecedor_nome", "fornecedor")
    col_dep = _safe_col(df_pedidos, "departamento")
    col_st  = _safe_col(df_pedidos, "status")

    dfi = df_pedidos.copy()
    if col_val:
        dfi["_valor"] = pd.to_numeric(dfi[col_val], errors="coerce").fillna(0.0)
    else:
        dfi["_valor"] = 0.0

    # atrasado (compatível com consulta)
    if "dias_atraso" in dfi.columns:
        dfi["_atraso"] = pd.to_numeric(dfi["dias_atraso"], errors="coerce").fillna(0) > 0
    elif "previsao_entrega" in dfi.columns:
        hoje = pd.Timestamp.now().normalize()
        prev = _ensure_datetime(dfi["previsao_entrega"])
        if col_st:
            ok = dfi[col_st].fillna("").astype(str) != "Entregue"
        else:
            ok = True
        dfi["_atraso"] = prev.notna() & (prev < hoje) & ok
    else:
        dfi["_atraso"] = False

    total = len(dfi)
    atrasados = int(dfi["_atraso"].sum())
    valor_total = float(dfi["_valor"].sum())
    valor_atraso = float(dfi.loc[dfi["_atraso"], "_valor"].sum())

    # concentração por fornecedor (top 3)
    top_for_txt = "—"
    if col_for and total:
        top_for = (
            dfi.groupby(col_for, dropna=False)["_valor"]
            .sum()
            .sort_values(ascending=False)
            .head(3)
        )
        if top_for.sum() > 0:
            share = (top_for.sum() / max(valor_total, 1e-9)) * 100
            top_for_txt = f"{share:.0f}% do valor está nos top 3 fornecedores"
        else:
            top_for_txt = "Top fornecedores sem valor definido"

    # depto mais impactado (qtd atrasos)
    top_dep_txt = "—"
    if col_dep:
        dep = dfi.loc[dfi["_atraso"], col_dep].fillna("N/D").astype(str).value_counts().head(1)
        if not dep.empty:
            top_dep_txt = f"Depto com mais atrasos: {dep.index[0]} ({int(dep.iloc[0])})"

    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Linhas no recorte", _fmt_int(total))
    i2.metric("Atrasados", _fmt_int(atrasados))
    i3.metric("Valor total", formatar_moeda_br(valor_total))
    i4.metric("Valor atrasado", formatar_moeda_br(valor_atraso))

    st.caption(f"• {top_for_txt}  |  • {top_dep_txt}")

    st.subheader("Ações rápidas (drilldown)")
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        if st.button("Ver atrasados", use_container_width=True, key="adv_go_atrasados"):
            _go_consulta(q="", depto="Todos", status="Todos", somente_atrasados=True)
    with a2:
        if st.button("Ver sem OC", use_container_width=True, key="adv_go_semoc"):
            _go_consulta(q="", depto="Todos", status="Sem OC", somente_atrasados=False)
    with a3:
        if st.button("Ver em transporte", use_container_width=True, key="adv_go_transp"):
            _go_consulta(q="", depto="Todos", status="Em Transporte", somente_atrasados=False)
    with a4:
        if st.button("Ver entregues", use_container_width=True, key="adv_go_entregues"):
            _go_consulta(q="", depto="Todos", status="Entregue", somente_atrasados=False)

    # Investigação guiada (híbrido): mantém gráficos, mas adiciona botões por fornecedor/depto
    with st.expander("Investigar (top fornecedores / deptos)", expanded=False):
        cL, cR = st.columns(2)

        with cL:
            st.markdown("**Top fornecedores (clique para filtrar na Consulta)**")
            if col_for:
                topF = (
                    dfi.groupby(col_for, dropna=False)["_valor"]
                    .sum()
                    .sort_values(ascending=False)
                    .head(10)
                )
                if topF.empty:
                    st.caption("Sem dados para fornecedores.")
                else:
                    for idx, (nm, v) in enumerate(topF.items()):
                        label = f"{str(nm)[:36]} — {formatar_moeda_br(float(v))}"
                        if st.button(label, use_container_width=True, key=f"adv_for_{idx}"):
                            _go_consulta(q=str(nm), depto="Todos", status="Todos", somente_atrasados=False)
            else:
                st.caption("Coluna de fornecedor não encontrada.")

        with cR:
            st.markdown("**Top departamentos (clique para filtrar na Consulta)**")
            if col_dep:
                topD = dfi[col_dep].fillna("N/D").astype(str).value_counts().head(10)
                if topD.empty:
                    st.caption("Sem dados para departamentos.")
                else:
                    for idx, (nm, qtd) in enumerate(topD.items()):
                        label = f"{str(nm)[:36]} — {_fmt_int(int(qtd))} itens"
                        if st.button(label, use_container_width=True, key=f"adv_dep_{idx}"):
                            _go_consulta(q="", depto=str(nm), status="Todos", somente_atrasados=False)
            else:
                st.caption("Coluna de departamento não encontrada.")
    # =====================================================
    # 📈 Performance & Inteligência (Gestão)
    # =====================================================
    st.subheader("Performance & Inteligência")

    dfp = df_pedidos.copy()
    hoje = pd.Timestamp.now().normalize()

    # 🔎 Detecta colunas possíveis
    col_prev = next((c for c in ["previsao_entrega", "data_prevista"] if c in dfp.columns), None)
    col_ent  = next((c for c in ["data_entrega", "entregue_em"] if c in dfp.columns), None)

    # ================= SLA =================
    if col_prev and col_ent:
        prev = _ensure_datetime(dfp[col_prev])
        ent  = _ensure_datetime(dfp[col_ent])
        no_prazo = (ent.notna()) & (prev.notna()) & (ent <= prev)
        sla = (no_prazo.sum() / max(ent.notna().sum(), 1)) * 100
    else:
        sla = 0.0

    # ================= Lead Time =================
    if col_ent and "data_oc" in dfp.columns:
        dt_oc  = _ensure_datetime(dfp["data_oc"])
        dt_ent = _ensure_datetime(dfp[col_ent])
        lead   = (dt_ent - dt_oc).dt.days
        lead_medio = lead[lead >= 0].mean()
    else:
        lead_medio = None

    # ================= Comparativo 30 dias =================
    if col_prev:
        prev_dt = _ensure_datetime(dfp[col_prev])
        atual = dfp[prev_dt >= (hoje - pd.Timedelta(days=30))]
        anterior = dfp[
            (prev_dt < (hoje - pd.Timedelta(days=30))) &
            (prev_dt >= (hoje - pd.Timedelta(days=60)))
        ]

        if "_atraso" in dfp.columns and len(anterior) > 0:
            atual_a = atual["_atraso"].sum()
            ant_a   = anterior["_atraso"].sum()
            var_atraso = ((atual_a - ant_a) / max(ant_a, 1)) * 100
        else:
            var_atraso = None
    else:
        var_atraso = None

    c1, c2, c3 = st.columns(3)
    c1.metric("SLA (no prazo)", f"{sla:.1f}%".replace(".", ","))
    c2.metric("Lead time médio", f"{lead_medio:.1f} dias".replace(".", ",") if lead_medio else "N/D")
    c3.metric("Variação atrasos (30d)", f"{var_atraso:+.1f}%".replace(".", ",") if var_atraso is not None else "N/D")

    # ================= Ranking eficiência =================
    if col_ent and "data_oc" in dfp.columns and "fornecedor_nome" in dfp.columns:
        dt_oc  = _ensure_datetime(dfp["data_oc"])
        dt_ent = _ensure_datetime(dfp[col_ent])
        dfp["_lead"] = (dt_ent - dt_oc).dt.days

        rank = (
            dfp[dfp["_lead"] >= 0]
            .groupby("fornecedor_nome")["_lead"]
            .mean()
            .sort_values()
            .head(5)
        )

        if not rank.empty:
            st.markdown("#### Fornecedores mais eficientes")
            for idx, (nm, v) in enumerate(rank.items()):
                st.write(f"{idx+1}. {nm} — {v:.1f} dias")


        st.markdown("---")
    # Evolução Temporal
    if show_evol:
        criar_grafico_evolucao_temporal(df_pedidos, formatar_moeda_br)
        st.markdown("---")

    # Funil de Conversão
    if show_funil:
        criar_funil_conversao(df_pedidos)
        st.markdown("---")

    # Heatmap
    if show_heat:
        criar_heatmap_pedidos(df_pedidos)
        st.markdown("---")

    # Comparativo de Períodos
    if show_comp:
        criar_comparativo_periodos(df_pedidos, formatar_moeda_br)
