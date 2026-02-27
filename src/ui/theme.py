"""Tema e componentes visuais base (UI System).

Objetivo: padronizar espaçamentos, cards, KPIs e tabelas sem depender de libs externas.

Use:
  from src.ui.theme import apply_theme, section_header, kpi_row
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

import streamlit as st


def apply_theme() -> None:
    """Injeta CSS global (dark-friendly)."""
    st.markdown(
        """
        <style>
          :root{
            --fu-card-bg: rgba(255,255,255,0.04);
            --fu-card-brd: rgba(255,255,255,0.10);
            --fu-muted: rgba(255,255,255,0.66);
            --fu-muted2: rgba(255,255,255,0.52);
            --fu-accent: rgba(239, 68, 68, 1);
            --fu-accent-soft: rgba(239, 68, 68, 0.15);
          }

          /* Layout */
          .block-container{ padding-top: 1.0rem !important; }

          /* Cards */
          .fu-card{
            background: var(--fu-card-bg);
            border: 1px solid var(--fu-card-brd);
            border-radius: 18px;
            padding: 14px 14px;
          }
          .fu-card h1,.fu-card h2,.fu-card h3{ margin-top: 0.1rem; }

          /* Section header */
          .fu-section{ display:flex; justify-content:space-between; align-items:flex-end; gap: 12px; }
          .fu-section .fu-title{ font-size: 1.18rem; font-weight: 700; }
          .fu-section .fu-hint{ font-size: 0.92rem; color: var(--fu-muted); margin-top: 2px; }
          .fu-pill{ display:inline-flex; align-items:center; gap: 6px; padding: 4px 10px; border-radius: 999px;
            border: 1px solid var(--fu-card-brd); background: rgba(255,255,255,0.03); color: var(--fu-muted);
            font-size: 0.82rem; white-space: nowrap;
          }
          .fu-pill--accent{ border-color: rgba(239,68,68,0.35); background: var(--fu-accent-soft); color: rgba(255,255,255,0.90); }

          /* KPI */
          .fu-kpi{ display:flex; flex-direction:column; gap: 6px; }
          .fu-kpi .fu-kpi-label{ color: var(--fu-muted2); font-size: 0.82rem; }
          .fu-kpi .fu-kpi-value{ font-size: 1.35rem; font-weight: 800; letter-spacing: -0.3px; }
          .fu-kpi .fu-kpi-sub{ color: var(--fu-muted); font-size: 0.84rem; }

          /* Tables */
          .dataframe thead tr th{ background: rgba(255,255,255,0.04) !important; }

          /* Reduce visual noise */
          .stMetric{ background: transparent !important; }

          /* =========================
             Mobile responsiveness
             ========================= */
          @media (max-width: 768px){
            .block-container{ padding-left: 0.65rem !important; padding-right: 0.65rem !important; }
            html, body{ font-size: 14px !important; }
            h1{ font-size: 1.35rem !important; }
            h2{ font-size: 1.15rem !important; }
            h3{ font-size: 1.02rem !important; }
            .stButton > button{ min-height: 44px; }
            [data-testid="stHorizontalBlock"]{ flex-wrap: wrap !important; gap: 0.65rem !important; }
            [data-testid="stColumn"]{ min-width: 280px !important; flex: 1 1 280px !important; }
            [data-testid="stMetricLabel"]{ font-size: 0.78rem !important; }
            [data-testid="stMetricValue"]{ font-size: 1.05rem !important; }
            .js-plotly-plot, .plotly{ width: 100% !important; }
          }

          @media (max-width: 768px){
            [data-testid="stDialog"] h1 { font-size: 1.1rem !important; }
            [data-testid="stDialog"] button { min-height: 44px; }
          }

          /* Dialog (modal) - compacto e mobile-friendly */
          @media (max-width: 768px){
            [data-testid="stDialog"]{ width: 96vw !important; max-width: 96vw !important; }
            [data-testid="stDialog"] [data-testid="stVerticalBlock"]{ gap: 0.6rem !important; }
            [data-testid="stDialog"] label{ font-size: 0.80rem !important; }
            [data-testid="stDialog"] input,
            [data-testid="stDialog"] textarea{ font-size: 0.95rem !important; padding-top: 0.55rem !important; padding-bottom: 0.55rem !important; }
            [data-testid="stNumberInputStepUp"],
            [data-testid="stNumberInputStepDown"]{ transform: scale(0.9); }
          }

          /* Modal polish: cards summary + discreet labels */
          [data-testid="stDialog"] [data-testid="stContainer"]{ border-radius: 16px !important; }
          [data-testid="stDialog"] [data-testid="stMetricLabel"]{ font-size: 0.78rem !important; }
          [data-testid="stDialog"] [data-testid="stMetricValue"]{ font-size: 1.05rem !important; }
          @media (max-width: 768px){
            [data-testid="stDialog"] [data-testid="stVerticalBlock"]{ gap: 0.55rem !important; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def section_header(
    title: str,
    *,
    hint: str | None = None,
    pill: str | None = None,
    accent: bool = False,
) -> None:
    pill_cls = "fu-pill fu-pill--accent" if accent else "fu-pill"
    st.markdown(
        f"""
        <div class='fu-section'>
          <div>
            <div class='fu-title'>{title}</div>
            {f"<div class='fu-hint'>{hint}</div>" if hint else ""}
          </div>
          {f"<div class='{pill_cls}'>{pill}</div>" if pill else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def card_open() -> None:
    st.markdown("<div class='fu-card'>", unsafe_allow_html=True)


def card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def kpi_row(items: Sequence[Tuple[str, str, Optional[str]]], *, cols: int = 4) -> None:
    """Renderiza KPIs padronizados.

    items: [(label, value, sub), ...]
    """
    cols = max(1, int(cols))
    grid = st.columns([1] * min(cols, len(items)))
    for i, (label, value, sub) in enumerate(items[: len(grid)]):
        with grid[i]:
            st.markdown(
                f"""
                <div class='fu-card fu-kpi'>
                  <div class='fu-kpi-label'>{label}</div>
                  <div class='fu-kpi-value'>{value}</div>
                  {f"<div class='fu-kpi-sub'>{sub}</div>" if sub else ""}
                </div>
                """,
                unsafe_allow_html=True,
            )