import os
import streamlit as st
from supabase import create_client

# ------------------------------------------------------------
# Supabase/HTTP timeouts (Streamlit Cloud)
#
# Em importações em lote, uma chamada PostgREST pode demorar e o app
# aparenta ficar "Running" indefinidamente caso o cliente fique sem timeout.
# A biblioteca supabase-py suporta ClientOptions em algumas versões.
# Mantemos compatibilidade com versões onde ClientOptions não existe.
# ------------------------------------------------------------
try:
    # supabase-py >= 1.x
    from supabase.lib.client_options import ClientOptions  # type: ignore
except Exception:  # pragma: no cover
    try:
        from supabase.client import ClientOptions  # type: ignore
    except Exception:  # pragma: no cover
        ClientOptions = None  # type: ignore


def _create_client(url: str, key: str):
    """Cria client Supabase com timeout maior para evitar travas em Cloud."""
    if ClientOptions is None:
        return create_client(url, key)

    # Aumenta timeout do PostgREST (UPSERT/UPDATE em lote)
    # Nota: nome do parâmetro pode variar por versão; mantemos fallback.
    try:
        opts = ClientOptions(postgrest_client_timeout=120)
        return create_client(url, key, options=opts)
    except Exception:
        return create_client(url, key)


def _get_secret(name: str) -> str | None:
    """Busca primeiro no st.secrets e depois em variável de ambiente."""
    if name in st.secrets:
        return st.secrets.get(name)
    return os.getenv(name)


@st.cache_resource
def init_supabase_admin():
    """Cliente Supabase com SERVICE ROLE (bypass RLS)."""
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_SERVICE_ROLE_KEY")

    if not url:
        raise RuntimeError("SUPABASE_URL não configurado.")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY não configurado (obrigatória para convites).")

    return _create_client(url, key)


@st.cache_resource
def init_supabase_anon():
    """Cliente Supabase com ANON KEY (respeita RLS)."""
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_ANON_KEY")

    if not url:
        raise RuntimeError("SUPABASE_URL não configurado.")
    if not key:
        raise RuntimeError("SUPABASE_ANON_KEY não configurado.")

    return _create_client(url, key)


def get_supabase_user_client(access_token: str):
    """
    Cria um client Supabase autenticado com JWT do usuário (RLS ativo).
    """
    supa = init_supabase_anon()

    try:
        supa.postgrest.auth(access_token)
    except Exception:
        try:
            supa.auth.set_session(access_token, "")  # compatibilidade versões antigas
        except Exception:
            pass

    return supa
