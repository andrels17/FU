
from __future__ import annotations

import textwrap
import streamlit as st


def exibir_home(alertas: dict, usuario_nome: str = "Usuário") -> None:
    """Página inicial pós-login (atalhos + resumo)."""
    st.markdown(
        textwrap.dedent(
            """
            <style>
              .fu-home-hero{
                border: 1px solid rgba(255,255,255,0.08);
                background: linear-gradient(135deg, rgba(245,158,11,0.12), rgba(59,130,246,0.10));
                border-radius: 22px;
                padding: 18px 18px 14px 18px;
                box-shadow: 0 14px 40px rgba(0,0,0,0.28);
              }
              .fu-home-hero h2{ margin:0; font-size: 1.45rem; }
              .fu-home-hero p{ margin: 6px 0 0 0; color: rgba(255,255,255,0.72); }
              .fu-quick{
                border: 1px solid rgba(255,255,255,0.08);
                background: rgba(255,255,255,0.02);
                border-radius: 18px;
                padding: 14px 14px 10px 14px;
              }
              .fu-quick h3{ margin: 0 0 8px 0; font-size: 1.02rem; }
              div.stButton > button { border-radius: 14px; }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )

    atrasados = int(alertas.get("total_atrasados", alertas.get("atrasados", 0) or 0) or 0)
    criticos = int(alertas.get("total_criticos", alertas.get("criticos", 0) or 0) or 0)
    vencendo = int(alertas.get("total_vencendo", alertas.get("vencendo", 0) or 0) or 0)

    st.markdown(
        f"""
        <div class="fu-home-hero">
          <h2>👋 Bem-vindo, {usuario_nome}!</h2>
          <p>Escolha uma ação rápida abaixo ou use o menu lateral para navegar.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    k1, k2, k3 = st.columns(3)
    k1.metric("⚠️ Atrasados", atrasados)
    k2.metric("🚨 Críticos", criticos)
    k3.metric("⏰ Vencendo", vencendo)

    st.write("")
    a1, a2, a3, a4 = st.columns(4, gap="small")

    def _go(page_name: str) -> None:
        st.session_state.current_page = page_name
        # ajuda os expanders a abrirem o grupo certo
        if page_name in ["Dashboard", "Consultar Pedidos"] or "Alertas" in page_name:
            st.session_state.exp_ops_open = True
            st.session_state.exp_gestao_open = False
        else:
            st.session_state.exp_ops_open = False
            st.session_state.exp_gestao_open = True
        st.rerun()

    with a1:
        if st.button("📊 Dashboard", use_container_width=True):
            _go("Dashboard")
    with a2:
        if st.button("🔔 Alertas", use_container_width=True):
            # o label real pode ter número; o app ajusta depois
            _go("🔔 Alertas e Notificações")
    with a3:
        if st.button("📋 Consultar", use_container_width=True):
            _go("Consultar Pedidos")
    with a4:
        if st.button("🗺️ Mapa", use_container_width=True):
            _go("Mapa Geográfico")

    st.write("")
    st.markdown(
        """<div class="fu-quick"><h3>💡 Dicas</h3>
        <ul>
          <li>Use a <b>Busca rápida</b> na lateral para pular direto para uma tela.</li>
          <li>Nos filtros, prefira <b>select/multiselect</b> para evitar digitação.</li>
          <li>Se o token expirar, o app tenta renovar automaticamente.</li>
        </ul>
        </div>""",
        unsafe_allow_html=True,
    )
