"""
Tela dedicada: Redefinir senha.
- `render_request_reset` envia e-mail com link de recovery
- `render_reset_password` aplica a nova senha (usuário chegou via link)
"""

import streamlit as st
from auth_flows import enviar_link_redefinicao_senha, tela_redefinir_senha


def render_request_reset(supabase_anon):
    st.title("🔑 Esqueci minha senha")
    email = st.text_input("Seu e-mail", key="reset_email")
    if st.button("Enviar link", type="primary", use_container_width=True):
        ok, msg = enviar_link_redefinicao_senha(supabase_anon, email)
        (st.success if ok else st.error)(msg)


def render_reset_password(supabase_anon):
    st.title("♻️ Redefinir senha")
    tela_redefinir_senha(supabase_anon)
