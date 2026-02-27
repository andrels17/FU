from __future__ import annotations

from typing import Literal, Optional

import plotly.graph_objects as go  # type: ignore

try:
    import streamlit as st  # type: ignore
except Exception:  # pragma: no cover
    st = None  # type: ignore



# Cor padrão para gráficos (mantém o mesmo "padrão azul" usado no dashboard)
ACCENT_COLOR = "#7CC7FF"

# Paleta consistente para múltiplas séries (primeira cor = ACCENT)
COLORWAY = [
    ACCENT_COLOR,
    "#FF4B4B",  # vermelho (crítico)
    "#00C2A8",  # verde/teal
    "#FFA62B",  # âmbar
    "#A78BFA",  # roxo
    "#F472B6",  # rosa
]


def style_plotly(
    fig: go.Figure,
    *,
    height: Optional[int] = None,
    kind: Optional[Literal["bar", "line", "pie", "map", "generic"]] = "generic",
    force_single_color: bool = False,
    bargap: float = 0.38,
) -> go.Figure:
    """
    Aplica estilo consistente (dark, transparente, tipografia e grids) para Plotly.
    Não deve "quebrar" mapas/mapbox.
    """
    try:
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=10, r=10, t=45, b=10),
            font=dict(color="rgba(255,255,255,0.92)"),
            colorway=COLORWAY,
            separators='.,',  # pt-BR: milhar '.' e decimal ','
        )
        if height is not None:
            fig.update_layout(height=height)

        # Grids mais suaves
        fig.update_xaxes(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.10)",
            zeroline=False,
            linecolor="rgba(255,255,255,0.18)",
            tickfont=dict(color="rgba(255,255,255,0.88)"),
            titlefont=dict(color="rgba(255,255,255,0.88)"),
        )
        fig.update_yaxes(
            showgrid=False if kind in ("bar", "pie") else True,
            gridcolor="rgba(255,255,255,0.10)",
            zeroline=False,
            linecolor="rgba(255,255,255,0.18)",
            tickfont=dict(color="rgba(255,255,255,0.88)"),
            titlefont=dict(color="rgba(255,255,255,0.88)"),
            automargin=True,
        )

        if kind == "bar":
            fig.update_layout(bargap=bargap, uniformtext_minsize=10, uniformtext_mode="hide")

            # Hover pt-BR + (quando fizer sentido) prefixo de moeda
            try:
                x_title = (getattr(fig.layout.xaxis.title, "text", "") or "")
                y_title = (getattr(fig.layout.yaxis.title, "text", "") or "")
                is_money = ("R$" in x_title) or ("R$" in y_title) or ("Valor" in x_title) or ("Valor" in y_title)

                for tr in fig.data:
                    if getattr(tr, "type", None) != "bar":
                        continue
                    # Não sobrescreve hovertemplate customizado
                    if getattr(tr, "hovertemplate", None):
                        continue
                    orientation = getattr(tr, "orientation", None)
                    if orientation == "h":
                        # y = categoria, x = valor
                        tr.update(
                            hovertemplate=(
                                "<b>%{y}</b><br>"
                                + ("Valor: R$ %{x:,.0f}" if is_money else "Quantidade: %{x:,}")
                                + "<extra></extra>"
                            )
                        )
                    else:
                        # x = categoria, y = valor
                        tr.update(
                            hovertemplate=(
                                "<b>%{x}</b><br>"
                                + ("Valor: R$ %{y:,.0f}" if is_money else "Quantidade: %{y:,}")
                                + "<extra></extra>"
                            )
                        )
            except Exception:
                pass

        # Só força cor única quando explicitamente pedido (ex.: UF/Dept)
        if force_single_color:
            fig.update_traces(marker_color=ACCENT_COLOR)

        # Remover contorno padrão grosso em barras
        fig.update_traces(marker_line_width=0)
    except Exception:
        pass
    return fig


def add_bar_labels(
    fig: go.Figure,
    *,
    kind: Literal["money", "count"] = "money",
    position: Literal["outside", "inside"] = "outside",
) -> go.Figure:
    """Adiciona rótulos para todas as séries de barras no gráfico."""
    # Labels em barras são um dos maiores custos de renderização no Plotly.
    # Regras defensivas para manter o app responsivo:
    # - No mobile: nunca mostrar labels
    # - Respeita o toggle global
    # - Limite automático por quantidade de barras (hover já resolve acima disso)
    try:
        if st is not None:
            mobile = bool(st.session_state.get("mobile_mode", False))
            show_labels = bool(st.session_state.get("show_chart_labels", True))
            if mobile or (not show_labels):
                return fig
            # Em modo turbo do dashboard, forçar labels OFF (hover já cobre)
            if bool(st.session_state.get("dash_turbo", False)):
                return fig
            # Em "gráficos leves", desativar labels para ganhar performance
            if bool(st.session_state.get("dash_fast_charts", False)):
                return fig
    except Exception:
        pass

    MAX_BARS_FOR_LABELS = 25

    try:
        for tr in fig.data:
            if getattr(tr, "type", None) != "bar":
                continue

            # Conta barras (h: categorias em y, v: categorias em x)
            try:
                orientation = getattr(tr, "orientation", None)
                n_bars = 0
                if orientation == "h":
                    n_bars = len(getattr(tr, "y", []) or [])
                else:
                    n_bars = len(getattr(tr, "x", []) or [])
                if n_bars and n_bars > MAX_BARS_FOR_LABELS:
                    tr.update(text=None)
                    continue
            except Exception:
                pass

            # Descobre orientação para escolher eixo correto do texttemplate
            orientation = getattr(tr, "orientation", None)
            axis = "x" if orientation == "h" else "y"

            if kind == "money":
                tr.update(texttemplate=f"R$ %{{{axis}:,.0f}}", textposition=position, cliponaxis=False)
            else:
                tr.update(texttemplate=f"%{{{axis}}}", textposition=position, cliponaxis=False)

            # barras mais "finas" (melhor leitura de rótulos)
            # width é em unidades categóricas; 0.55 costuma ficar bom em listas Top 10/12
            try:
                tr.update(width=0.55)
            except Exception:
                pass

        fig.update_layout(uniformtext_minsize=10, uniformtext_mode="hide")
    except Exception:
        pass
    return fig