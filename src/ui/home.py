from __future__ import annotations

from datetime import datetime
import textwrap

import streamlit as st


def exibir_home(alertas: dict, usuario_nome: str = "Usuário") -> None:
    # -----------------------------
    # Saudação
    # -----------------------------
    hora = datetime.now().hour
    if hora < 12:
        saudacao = "Bom dia"
    elif hora < 18:
        saudacao = "Boa tarde"
    else:
        saudacao = "Boa noite"

    # -----------------------------
    # Empresa (tenant)
    # -----------------------------
    empresa_nome = ""
    tenants = st.session_state.get("tenant_options", []) or []
    tenant_id = st.session_state.get("tenant_id")

    for t in tenants:
        if isinstance(t, dict) and t.get("tenant_id") == tenant_id:
            empresa_nome = (t.get("nome") or t.get("name") or t.get("razao_social") or "").strip()
            break

    # -----------------------------
    # KPIs (corrigido)
    # - prioridade: listas do dict alertas (como seu app usa)
    # - fallback: chaves numéricas antigas (atrasados/criticos/vencendo)
    # -----------------------------
    def _safe_list_len(v) -> int:
        try:
            return int(len(v or []))
        except Exception:
            return 0

    atrasados = _safe_list_len(alertas.get("pedidos_atrasados"))
    criticos = _safe_list_len(alertas.get("pedidos_criticos"))
    vencendo = _safe_list_len(alertas.get("pedidos_vencendo"))

    if (atrasados == 0 and criticos == 0 and vencendo == 0):
        # compat com formatos antigos (números)
        try:
            atrasados = int(alertas.get("atrasados", 0) or 0)
        except Exception:
            atrasados = 0
        try:
            criticos = int(alertas.get("criticos", 0) or 0)
        except Exception:
            criticos = 0
        try:
            vencendo = int(alertas.get("vencendo", 0) or 0)
        except Exception:
            vencendo = 0

    total_pontos = int(atrasados + criticos + vencendo)

    # -----------------------------
    # Navegação
    # -----------------------------
    def _go(page: str) -> None:
        st.session_state.current_page = page
        st.rerun()

    # -----------------------------
    # CSS (SaaS internacional)
    # -----------------------------
    st.markdown(
        textwrap.dedent(
            """
            <style>
              .fu-wrap { max-width: 1200px; margin: 0 auto; }

              .fu-hero {
                border-radius: 22px;
                padding: 22px 22px;
                background:
                  radial-gradient(900px 420px at 12% 0%, rgba(245,158,11,0.18), transparent 60%),
                  radial-gradient(900px 420px at 85% 20%, rgba(59,130,246,0.14), transparent 60%),
                  rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08);
                box-shadow: 0 18px 55px rgba(0,0,0,0.35);
              }
              .fu-hero-top { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; }
              .fu-title { margin:0; font-size: 1.55rem; font-weight: 900; letter-spacing: 0.2px; }
              .fu-sub { margin:6px 0 0 0; opacity:.78; font-size: 0.98rem; line-height: 1.35; }
              .fu-chip {
                display:inline-flex; align-items:center; gap:8px;
                padding: 7px 12px;
                border-radius: 999px;
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.10);
                font-size: 0.85rem;
                opacity: .86;
                white-space: nowrap;
              }

              .fu-grid { margin-top: 14px; display:grid; grid-template-columns: repeat(12, 1fr); gap: 12px; }
              .fu-card {
                border-radius: 18px;
                padding: 16px 16px;
                background: rgba(255,255,255,0.035);
                border: 1px solid rgba(255,255,255,0.08);
                transition: transform .14s ease, border-color .14s ease, background-color .14s ease;
              }
              .fu-card:hover { transform: translateY(-2px); border-color: rgba(245,158,11,0.30); background: rgba(255,255,255,0.045); }
              .fu-kpi-num { margin:0; font-size: 30px; font-weight: 950; letter-spacing: 0.2px; }
              .fu-kpi-lbl { margin:2px 0 0 0; font-size: 12.5px; opacity: .75; }

              .fu-section-title { margin: 18px 0 10px 0; font-size: 1.05rem; font-weight: 900; opacity:.94; }
              .fu-note {
                border-radius: 18px;
                padding: 14px 16px;
                background: linear-gradient(135deg, rgba(245,158,11,0.10), rgba(255,255,255,0.03));
                border: 1px solid rgba(245,158,11,0.22);
              }
              .fu-note p { margin:0; opacity:.88; }

              .fu-actions .stButton button { border-radius: 14px; height: 44px; }
              .fu-muted { opacity: .72; font-size: 0.92rem; }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )

    # -----------------------------
    # Layout
    # -----------------------------
    st.markdown('<div class="fu-wrap">', unsafe_allow_html=True)

    # HERO
    empresa_txt = f"🏢 {empresa_nome}" if empresa_nome else "🏢 Multiempresa"
    st.markdown(
        f"""
        <div class="fu-hero">
          <div class="fu-hero-top">
            <div>
              <h2 class="fu-title">👋 {saudacao}, {usuario_nome}!</h2>
              <p class="fu-sub">
                Visão geral do seu dia no Follow-up.
                <span style="opacity:.92;"><b>{total_pontos}</b></span> ponto(s) de atenção entre atrasos, críticos e vencimentos.
              </p>
            </div>
            <div class="fu-chip">{empresa_txt}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # KPIs (cards)
    st.markdown('<div class="fu-grid">', unsafe_allow_html=True)

    # card 1
    st.markdown(
        f"""
        <div class="fu-card" style="grid-column: span 4;">
          <p class="fu-kpi-num">⚠️ {atrasados}</p>
          <p class="fu-kpi-lbl">Pedidos atrasados</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # card 2
    st.markdown(
        f"""
        <div class="fu-card" style="grid-column: span 4;">
          <p class="fu-kpi-num">🚨 {criticos}</p>
          <p class="fu-kpi-lbl">Pedidos críticos</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # card 3
    st.markdown(
        f"""
        <div class="fu-card" style="grid-column: span 4;">
          <p class="fu-kpi-num">⏰ {vencendo}</p>
          <p class="fu-kpi-lbl">Vencendo / próximos</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)  # end grid

    # Resumo operacional (inteligente)
    st.markdown('<div class="fu-section-title">📌 Resumo operacional</div>', unsafe_allow_html=True)

    if criticos > 0:
        msg = f"🚨 Você tem {criticos} pedido(s) crítico(s). Priorize follow-up imediato para evitar ruptura/atraso."
    elif atrasados > 0:
        msg = f"⚠️ Existem {atrasados} pedido(s) atrasado(s). Recomendado acionar fornecedor e atualizar status."
    elif vencendo > 0:
        msg = f"⏰ Você tem {vencendo} pedido(s) vencendo em breve. Vale revisar prazos e pendências."
    else:
        msg = "✅ Tudo sob controle por aqui. Sem críticos/atrasos/vencimentos relevantes agora."

    st.markdown(f'<div class="fu-note"><p>{msg}</p></div>', unsafe_allow_html=True)

    # Ações rápidas (SaaS)
    st.markdown('<div class="fu-section-title">⚡ Ações rápidas</div>', unsafe_allow_html=True)
    a1, a2, a3, a4 = st.columns(4)

    with a1:
        if st.button("📊 Dashboard", use_container_width=True):
            _go("Dashboard")
    with a2:
        if st.button("🔔 Alertas", use_container_width=True):
            _go("🔔 Alertas e Notificações")
    with a3:
        if st.button("➕ Novo pedido", use_container_width=True):
            _go("Gestão de Pedidos")
    with a4:
        if st.button("🗺️ Mapa", use_container_width=True):
            _go("Mapa Geográfico")

    st.markdown('<p class="fu-muted">Dica: use a busca rápida na barra lateral para navegar ainda mais rápido.</p>', unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)  # end wrap
