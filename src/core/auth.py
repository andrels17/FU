"""Autenticação e login (Supabase Auth) + Multi-tenant seguro."""
from __future__ import annotations

from datetime import datetime
import streamlit as st
import hashlib
import src.services.backup_auditoria as ba
from src.core.db import get_supabase_user_client


def verificar_autenticacao() -> bool:
    return bool(st.session_state.get("auth_access_token"))


def verificar_primeiro_acesso(supabase):
    user_id = st.session_state.get("auth_user_id")
    if not user_id:
        return False

    r = (
        supabase.table("user_profiles")
        .select("primeiro_acesso")
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    return bool(r.data and r.data.get("primeiro_acesso"))


def _carregar_tenants_do_usuario(supabase_user) -> list[dict]:
    resp = (
        supabase_user.table("tenant_users")
        .select("tenant_id, role, tenants(nome)")
        .execute()
    )

    data = resp.data or []
    tenants = []

    for row in data:
        tenants.append(
            {
                "tenant_id": row.get("tenant_id"),
                "role": row.get("role", "user"),
                "nome": (row.get("tenants") or {}).get("nome")
                if isinstance(row.get("tenants"), dict)
                else row.get("nome"),
            }
        )

    return [t for t in tenants if t.get("tenant_id")]


def fazer_login(email: str, senha: str, supabase_anon):
    try:
        auth_resp = supabase_anon.auth.sign_in_with_password(
            {"email": email, "password": senha}
        )

        session = getattr(auth_resp, "session", None)
        user = getattr(auth_resp, "user", None)

        if not session or not user:
            return None

        access_token = session.access_token
        refresh_token = session.refresh_token
        user_id = user.id
        user_email = user.email

        st.session_state.auth_access_token = access_token
        st.session_state.auth_refresh_token = refresh_token
        st.session_state.auth_user_id = user_id
        st.session_state.auth_email = user_email

        supabase_user = get_supabase_user_client(access_token)

        tenants = _carregar_tenants_do_usuario(supabase_user)
        if not tenants:
            st.error("❌ Seu usuário não está vinculado a nenhuma empresa.")
            return None

        selected = tenants[0]["tenant_id"]
        role = tenants[0]["role"]

        st.session_state.tenant_options = tenants
        st.session_state.tenant_id = selected

        # 🔥 BUSCAR NOME + AVATAR
        profile = (
            supabase_user.table("user_profiles")
            .select("nome, avatar_url")
            .eq("user_id", user_id)
            .single()
            .execute()
        )

        nome = None
        avatar = None

        if profile.data:
            nome = profile.data.get("nome")
            avatar = profile.data.get("avatar_url")

        st.session_state.usuario = {
            "id": user_id,
            "email": user_email,
            "perfil": role,
            "tenant_id": selected,
            "nome": nome if nome else user_email.split("@")[0],
            "avatar_url": avatar,
        }

        try:
            ba.registrar_acao(
                st.session_state.usuario,
                "Login",
                {"timestamp": datetime.now().isoformat()},
                supabase_user,
            )
        except Exception:
            pass

        return st.session_state.usuario

    except Exception as e:
        st.error(f"Erro ao fazer login: {e}")
        return None


def fazer_logout(supabase_anon):
    try:
        supabase_anon.auth.sign_out()
    except Exception:
        pass

    for k in list(st.session_state.keys()):
        if k.startswith("auth_") or k in [
            "tenant_options",
            "tenant_id",
            "usuario",
        ]:
            del st.session_state[k]


def exibir_login(supabase_anon):
    st.markdown("## 📦 Follow-up de Compras")
    st.markdown("---")

    with st.form("fu_login_form", clear_on_submit=False):
        email = st.text_input("📧 Email")
        senha = st.text_input("🔒 Senha", type="password")
        submit = st.form_submit_button("🚀 Entrar", use_container_width=True)

    if submit:
        if email and senha:
            usuario = fazer_login(email, senha, supabase_anon)
            if usuario:
                st.success("✅ Login realizado com sucesso!")
                st.rerun()
            else:
                st.error("❌ Email ou senha incorretos.")
        else:
            st.warning("⚠️ Preencha todos os campos")


def criar_senha_hash(senha: str) -> str:
    return hashlib.sha256(senha.encode("utf-8")).hexdigest()
