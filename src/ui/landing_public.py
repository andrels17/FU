
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

  /* Hero */
  .fu-hero{
    border: 1px solid rgba(148,163,184,0.12);
    background:
      radial-gradient(900px 380px at 12% 0%, rgba(59,130,246,0.16), transparent 55%),
      radial-gradient(900px 380px at 88% 10%, rgba(16,185,129,0.10), transparent 55%),
      linear-gradient(135deg, rgba(2,6,23,0.72), rgba(15,23,42,0.72));
    border-radius: 18px;
    padding: 26px;
    box-shadow: 0 18px 55px rgba(0,0,0,0.45);
  }
  .fu-hero h1{
    font-size: 2.05rem;
    margin: 0 0 8px 0;
    font-weight: 850;
    letter-spacing: -0.02em;
    color: rgba(226,232,240,0.98);
  }
  .fu-hero p{
    margin: 0;
    color: rgba(226,232,240,0.78);
    font-size: 1.03rem;
    line-height: 1.55;
  }

  .fu-trust{
    margin-top: 14px;
    color: rgba(148,163,184,0.82);
    font-size: 0.90rem;
    letter-spacing: .01em;
  }

  /* Value props */
  .fu-grid{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    margin-top: 18px;
  }
  .fu-vcard{
    border: 1px solid rgba(148,163,184,0.12);
    background: rgba(2,6,23,0.46);
    border-radius: 16px;
    padding: 16px 16px 14px 16px;
  }
  .fu-vcard h3{
    margin: 0 0 6px 0;
    font-size: 1.02rem;
    color: rgba(226,232,240,0.95);
    letter-spacing: -0.01em;
  }
  .fu-vcard p{
    margin: 0;
    color: rgba(148,163,184,0.86);
    line-height: 1.45;
    font-size: 0.95rem;
  }

  /* Right card */
  .fu-side{
    border: 1px solid rgba(148,163,184,0.12);
    background: rgba(2,6,23,0.42);
    border-radius: 18px;
    padding: 18px;
  }

  /* Buttons */
  div.stButton > button { border-radius: 14px; padding: 0.70rem 1.0rem; font-weight: 650; }
  div.stButton > button[kind="secondary"] { background: rgba(2,6,23,0.0); border: 1px solid rgba(148,163,184,0.22); }
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
  <p>Acompanhe pedidos, prazos e entregas com rastreabilidade, visibilidade executiva e operação orientada a SLAs.</p>
  <div class="fu-trust">Controle por tenant • Auditoria • Exportação PDF/CSV • Filtros avançados</div>

  <div class="fu-grid">
    <div class="fu-vcard">
      <h3>Visão executiva</h3>
      <p>KPIs, tendências e relatórios para acompanhamento gerencial em poucos cliques.</p>
    </div>
    <div class="fu-vcard">
      <h3>Operação no detalhe</h3>
      <p>Consulta e evolução de pedidos com histórico e consistência de dados.</p>
    </div>
    <div class="fu-vcard">
      <h3>Alertas e prioridades</h3>
      <p>Sinalize atrasos e riscos rapidamente, com indicadores objetivos.</p>
    </div>
    <div class="fu-vcard">
      <h3>Governança</h3>
      <p>Gestão de usuários, permissões e processos com segurança e auditoria.</p>
    </div>
  </div>
</div>

            """,
            unsafe_allow_html=True,
        )

        st.write("")
with col_right:
        st.markdown('<div class="fu-side">', unsafe_allow_html=True)
        st.subheader("Acesso")
        st.caption("Use sua conta para entrar. Se ainda não tem acesso, solicite o convite.")
        st.write("")

        if st.button("Entrar no sistema", use_container_width=True, type="primary"):
            _set_page("login")

        st.write("")
        cta1, cta2 = st.columns(2, gap="small")
        with cta1:
            if st.button("Primeiro acesso", use_container_width=True, type="secondary"):
                _set_page("first_access")
        with cta2:
            if st.button("Esqueci minha senha", use_container_width=True, type="secondary"):
                _set_page("reset_request")

        st.divider()
        st.caption("Dica: se você abriu um link de convite/recovery do Supabase, ele será processado automaticamente ao carregar o app.")
        st.markdown("</div>", unsafe_allow_html=True)

