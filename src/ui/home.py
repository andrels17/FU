from __future__ import annotations
import streamlit as st
from datetime import datetime
import textwrap


def exibir_home(alertas: dict, usuario_nome: str = "Usuário") -> None:

    hora = datetime.now().hour
    if hora < 12:
        saudacao = "Bom dia"
    elif hora < 18:
        saudacao = "Boa tarde"
    else:
        saudacao = "Boa noite"

    atrasados = int(alertas.get("atrasados", 0) or 0)
    criticos = int(alertas.get("criticos", 0) or 0)
    vencendo = int(alertas.get("vencendo", 0) or 0)

    empresa_nome = ""
    tenants = st.session_state.get("tenant_options", [])
    tenant_id = st.session_state.get("tenant_id")

    for t in tenants:
        if t["tenant_id"] == tenant_id:
            empresa_nome = t.get("nome", "")
            break

    st.markdown(
        textwrap.dedent(
            """
            <style>
            .hero {
                border-radius: 20px;
                padding: 20px;
                background: linear-gradient(135deg, rgba(245,158,11,0.15), rgba(59,130,246,0.12));
                border: 1px solid rgba(255,255,255,0.08);
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="hero">
            <h2>👋 {saudacao}, {usuario_nome}!</h2>
            <p>Bem-vindo ao sistema de Follow-up.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if empresa_nome:
        st.caption(f"🏢 Empresa: {empresa_nome}")

    st.write("")
    c1, c2, c3 = st.columns(3)
    c1.metric("⚠️ Atrasados", atrasados)
    c2.metric("🚨 Críticos", criticos)
    c3.metric("⏰ Vencendo", vencendo)

    st.write("")
    a1, a2, a3, a4 = st.columns(4)

    def _go(page):
        st.session_state.current_page = page
        st.rerun()

    if a1.button("📊 Dashboard", use_container_width=True):
        _go("Dashboard")

    if a2.button("🔔 Alertas", use_container_width=True):
        _go("🔔 Alertas e Notificações")

    if a3.button("📋 Consultar", use_container_width=True):
        _go("Consultar Pedidos")

    if a4.button("🗺️ Mapa", use_container_width=True):
        _go("Mapa Geográfico")
