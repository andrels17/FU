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

    if r.data and r.data.get("primeiro_acesso"):
        return True

    return False

def tela_troca_senha_primeiro_acesso(supabase):
    st.title("🔐 Primeiro acesso - Definir nova senha")

    nova = st.text_input("Nova senha", type="password")
    confirmar = st.text_input("Confirmar senha", type="password")

    if st.button("Salvar nova senha"):
        if not nova or len(nova) < 6:
            st.error("Senha muito curta.")
            return

        if nova != confirmar:
            st.error("As senhas não coincidem.")
            return

        try:
            supabase.auth.update_user({"password": nova})

            supabase.table("user_profiles").update({
                "primeiro_acesso": False
            }).eq("user_id", st.session_state["auth_user_id"]).execute()

            st.success("Senha alterada com sucesso!")
            st.rerun()

        except Exception as e:
            st.error(f"Erro ao atualizar senha: {e}")


def _carregar_tenants_do_usuario(supabase_user) -> list[dict]:
    """Retorna lista de tenants vinculados ao usuário (tenant_users)."""
    # Política RLS recomendada: usuário pode ler apenas suas linhas em tenant_users.
    resp = (
        supabase_user.table("tenant_users")
        .select("tenant_id, role, tenants(nome)")
        .execute()
    )
    data = resp.data or []
    # normaliza
    tenants = []
    for row in data:
        tenants.append(
            {
                "tenant_id": row.get("tenant_id"),
                "role": row.get("role", "user"),
                "nome": (row.get("tenants") or {}).get("nome") if isinstance(row.get("tenants"), dict) else row.get("nome"),
            }
        )
    return [t for t in tenants if t.get("tenant_id")]


def fazer_login(email: str, senha: str, supabase_anon):
    """Login via Supabase Auth (JWT)."""
    try:
        auth_resp = supabase_anon.auth.sign_in_with_password({"email": email, "password": senha})
        # Dependendo da versão, o retorno pode ser dict/objeto.
        session = getattr(auth_resp, "session", None) or auth_resp.get("session")  # type: ignore
        user = getattr(auth_resp, "user", None) or auth_resp.get("user")  # type: ignore

        if not session or not user:
            return None

        access_token = getattr(session, "access_token", None) or session.get("access_token")  # type: ignore
        refresh_token = getattr(session, "refresh_token", None) or session.get("refresh_token")  # type: ignore
        user_id = getattr(user, "id", None) or user.get("id")  # type: ignore
        user_email = getattr(user, "email", None) or user.get("email")  # type: ignore

        if not access_token or not user_id:
            return None

        # guarda tokens
        st.session_state.auth_access_token = access_token
        st.session_state.auth_refresh_token = refresh_token
        st.session_state.auth_expires_at = getattr(session, "expires_at", None)
        st.session_state.auth_user_id = user_id
        st.session_state.auth_email = user_email

        # cria client do usuário (RLS ativo)
        supabase_user = get_supabase_user_client(access_token)

        tenants = _carregar_tenants_do_usuario(supabase_user)
        if not tenants:
            st.error("❌ Seu usuário não está vinculado a nenhuma empresa (tenant).")
            return None

        # tenant selecionado (se já havia seleção, mantém)
        selected = st.session_state.get("tenant_id") or tenants[0]["tenant_id"]
        # se seleção inválida, volta pro primeiro
        if selected not in [t["tenant_id"] for t in tenants]:
            selected = tenants[0]["tenant_id"]

        # role do tenant selecionado
        role = next((t["role"] for t in tenants if t["tenant_id"] == selected), "user")

        st.session_state.tenant_options = tenants
        st.session_state.tenant_id = selected

        # compatibilidade com seu app: st.session_state.usuario
        st.session_state.usuario = {
            "id": user_id,
            "email": user_email,
            "perfil": role,          # admin/user/buyer...
            "tenant_id": selected,
        }

        # auditoria
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
    """Logout (limpa sessão)."""
    try:
        supabase_anon.auth.sign_out()
    except Exception:
        pass

    for k in [
        "auth_access_token",
        "auth_refresh_token",
        "auth_user_id",
        "auth_email",
        "tenant_options",
        "tenant_id",
        "usuario",
    ]:
        if k in st.session_state:
            del st.session_state[k]


def exibir_login(supabase_anon):
    """Exibe tela de login."""
    st.markdown(
        """
        <style>
        .login-container {
            max-width: 420px;
            margin: 90px auto;
            padding: 2rem;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 📦 Follow-up de Compras")
        st.markdown("---")

        # ✅ Importante: usar st.form para evitar rerun a cada tecla digitada.
        # Isso impede que o roteamento volte para a landing durante o preenchimento.
        with st.form("fu_login_form", clear_on_submit=False):
            email = st.text_input("📧 Email", key="login_email")
            senha = st.text_input("🔒 Senha", type="password", key="login_senha")
            submit = st.form_submit_button("🚀 Entrar", use_container_width=True)

        if submit:
            if email and senha:
                usuario = fazer_login(email, senha, supabase_anon)
                if usuario:
                    st.success("✅ Login realizado com sucesso!")
                    st.rerun()
                else:
                    st.error("❌ Email ou senha incorretos (ou usuário sem tenant).")
            else:
                st.warning("⚠️ Preencha todos os campos")

        st.markdown("---")
        st.caption("💡 Primeira vez? Peça ao administrador para criar seu acesso.")

def criar_senha_hash(senha: str) -> str:
    """
    Mantida apenas para compatibilidade com gestao_usuarios.
    Caso esteja usando apenas Supabase Auth,
    essa função não interfere no login principal.
    """
    return hashlib.sha256(senha.encode("utf-8")).hexdigest()
