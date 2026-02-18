
from __future__ import annotations

import textwrap
import streamlit as st


def _set_page(page: str) -> None:
    """Navegação simples e estável.

    Inputs do Streamlit geram reruns enquanto o usuário digita. Em alguns cenários,
    o querystring pode levar 1 rerun para refletir no Python — o que pode fazer a
    tela "voltar" para a landing.

    Para evitar isso, persistimos também a rota em session_state.
    """
    st.session_state["fu_route"] = page
    # Streamlit 1.30+: st.query_params behaves like dict
    st.query_params["page"] = page
    st.rerun()


def render_landing() -> None:
    """Landing pública (antes do login)."""
    st.markdown(
        textwrap.dedent(
            """
            <style>
              section.main > div { padding-top: 2.0rem; }
              .block-container { max-width: 1120px; }

              .fu-hero{
                border: 1px solid rgba(255,255,255,0.08);
                background: radial-gradient(900px 380px at 15% 0%, rgba(245,158,11,0.12), transparent 55%),
                            radial-gradient(900px 380px at 85% 15%, rgba(59,130,246,0.10), transparent 55%),
                            rgba(255,255,255,0.02);
                border-radius: 16px;
                padding: 26px;
                box-shadow: 0 18px 55px rgba(0,0,0,0.35);
              }
              .fu-hero h1{
                font-size: 2.1rem;
                margin: 0 0 8px 0;
                font-weight: 850;
              }
              .fu-hero p{
                margin: 0;
                color: rgba(255,255,255,0.72);
                font-size: 1.05rem;
                line-height: 1.45;
              }
              .fu-badges{
                display:flex;
                flex-wrap:wrap;
                gap:10px;
                margin-top: 16px;
              }
              .fu-badge{
                border: 1px solid rgba(255,255,255,0.10);
                background: rgba(255,255,255,0.03);
                color: rgba(255,255,255,0.78);
                padding: 7px 11px;
                border-radius: 999px;
                font-size: 0.88rem;
              }
              .fu-card{
                border: 1px solid rgba(255,255,255,0.08);
                background: rgba(255,255,255,0.02);
                border-radius: 16px;
                padding: 18px 18px 14px 18px;
              }
              .fu-card h3{ margin: 0 0 6px 0; font-size: 1.05rem; }
              .fu-card p{ margin: 0; color: rgba(255,255,255,0.70); line-height: 1.4; }

              div.stButton > button { border-radius: 14px; padding: 0.65rem 1.0rem; }
              .st-emotion-cache-1c7y2kd a { text-decoration: none; }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([1.35, 1], gap="large")

    with col_left:
        st.markdown(
            """
            <div class="fu-hero">
              <h1>Sistema de Follow-Up</h1>
              <p>Controle de pedidos, prazos, fornecedores e alertas — com visão executiva, mapa geográfico e relatórios.</p>
              <div class="fu-badges">
                <span class="fu-badge">Alertas automáticos</span>
                <span class="fu-badge">Mapa por estado</span>
                <span class="fu-badge">Relatório executivo (PDF)</span>
                <span class="fu-badge">Gestão de usuários</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.write("")
        c1, c2, c3 = st.columns(3, gap="medium")
        with c1:
            st.markdown("""<div class="fu-card"><h3>Visão rápida</h3><p>KPIs, tendências e filtros para chegar no detalhe.</p></div>""", unsafe_allow_html=True)
        with c2:
            st.markdown("""<div class="fu-card"><h3>Operação</h3><p>Consulta de pedidos e acompanhamento do status.</p></div>""", unsafe_allow_html=True)
        with c3:
            st.markdown("""<div class="fu-card"><h3>Gestão</h3><p>Usuários, empresas, e processos com auditoria.</p></div>""", unsafe_allow_html=True)

    with col_right:
        st.subheader("Acesso")
        st.caption("Use sua conta para entrar. Se ainda não tem acesso, solicite o convite.")
        st.write("")

        if st.button("Entrar no sistema", use_container_width=True):
            _set_page("login")

        st.write("")
        cta1, cta2 = st.columns(2, gap="small")
        with cta1:
            if st.button("Primeiro acesso", use_container_width=True):
                _set_page("first_access")
        with cta2:
            if st.button("Esqueci minha senha", use_container_width=True):
                _set_page("reset_request")

        st.divider()
        st.caption("Dica: se você abriu um link de convite/recovery do Supabase, ele será processado automaticamente ao carregar o app.")

