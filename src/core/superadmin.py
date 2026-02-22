"""Helpers para Super Admin (admin do SaaS).

Evite "senha mestre". Use um usuário (ou mais) com permissão global (superadmin).
A checagem pode ser feita por:
- tabela public.superadmins (recomendado)
- fallback de bootstrap via st.secrets / env: SUPERADMIN_EMAILS (lista separada por vírgula)
"""

from __future__ import annotations

import os
import streamlit as st


def _get_current_user() -> tuple[str | None, str | None]:
    user_id = (
        st.session_state.get("auth_user_id")
        or st.session_state.get("user_id")
        or (st.session_state.get("usuario") or {}).get("id")
    )
    email = (
        st.session_state.get("auth_email")
        or st.session_state.get("email")
        or (st.session_state.get("usuario") or {}).get("email")
    )
    return user_id, email


def _bootstrap_email_allows(email: str | None) -> bool:
    if not email:
        return False
    raw = (st.secrets.get("SUPERADMIN_EMAILS") or os.getenv("SUPERADMIN_EMAILS") or "").strip()
    if not raw:
        return False
    allowed = [e.strip().lower() for e in raw.split(",") if e.strip()]
    return email.strip().lower() in allowed


def is_superadmin(supabase_user) -> bool:
    """Retorna True se o usuário atual é superadmin.

    Tenta a tabela public.superadmins (com RLS: select apenas a própria linha).
    Se não existir (ou der erro), faz fallback por lista de bootstrap em secrets/env.
    """
    user_id, email = _get_current_user()
    if not user_id:
        return False

    # 1) caminho principal: tabela superadmins
    try:
        res = (
            supabase_user.table("superadmins")
            .select("user_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if (getattr(res, "data", None) or []):
            return True
    except Exception:
        pass

    # 2) fallback bootstrap por e-mail (secrets/env)
    return _bootstrap_email_allows(email)
