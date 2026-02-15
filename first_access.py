"""
Tela dedicada: Primeiro acesso (definir senha).
Importe e chame `render_first_access(supabase_anon)` quando quiser.
"""

import streamlit as st
from auth_flows import tela_primeiro_acesso_definir_senha


def render_first_access(supabase_anon):
    st.title("👋 Primeiro acesso")
    tela_primeiro_acesso_definir_senha(supabase_anon)
