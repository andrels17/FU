"""
Fluxos de autenticação (Supabase + Streamlit):
- Callback para convite/magic link (hash -> query -> set_session)
- Telas: Primeiro acesso (definir senha) e Redefinir senha (recovery)
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components


APP_URL = "https://followupdef.streamlit.app/"


def _clear_auth_params_keep_page(target_page: str = 'home') -> None:
    """Remove parâmetros de callback do Supabase sem usar st.query_params.clear().

    O Streamlit faz reruns enquanto o usuário digita; em alguns ambientes,
    usar clear() pode causar 1 rerun com querystring vazia e voltar para a landing.
    """
    # mantém rota estável mesmo se a query falhar em um rerun
    st.session_state['fu_route'] = target_page
    # Remove apenas parâmetros de callback/tokens
    for k in [
        'auth_callback','code','type','state','error','error_description',
        'access_token','refresh_token','expires_in','token_type',
        'provider_token','provider_refresh_token',
        'recovery','invite','redirect_to',
    ]:
        try:
            st.query_params.pop(k, None)
        except Exception:
            pass
    st.query_params['page'] = target_page


def _move_hash_to_query_once() -> None:
    """Move tokens do fragment (#...) para querystring (?...) porque Streamlit não lê hash no Python."""
    components.html(
        """
        <script>
          (function () {
            const hash = window.location.hash || "";
            if (!hash || hash.length < 2) return;
            if (!hash.includes("access_token=")) return;

            const qs = hash.substring(1); // remove '#'
            const url = new URL(window.location.href);

            // Evita loop
            if (url.searchParams.get("access_token")) return;

            // Move tokens do hash para query e recarrega
            window.location.replace(url.origin + url.pathname + "?" + qs);
          })();
        </script>
        """,
        height=0,
    )


def handle_auth_callback(supabase_anon) -> None:
    """
    Consome links do Supabase (invite/otp/recovery) e cria sessão no client.
    Compatível com:
    - Fluxo antigo: access_token/refresh_token no HASH (#...)
    - Fluxo novo (PKCE): ?code=... (precisa exchange_code_for_session)
    """
    qp = st.query_params

    # Só entra aqui se for callback explícito OU se já tiver tokens/código
    is_callback = qp.get("auth_callback") == "1" or qp.get("type") in ("invite", "recovery", "magiclink", "signup")
    has_tokens = bool(qp.get("access_token") and qp.get("refresh_token"))
    has_code = bool(qp.get("code"))

    if not (is_callback or has_tokens or has_code):
        return

    # Se tokens estiverem no hash, move para query
    _move_hash_to_query_once()

    qp = st.query_params
    access_token = qp.get("access_token")
    refresh_token = qp.get("refresh_token")
    code = qp.get("code")

    # 1) Fluxo novo: troca code por sessão
    if code and not (access_token and refresh_token):
        auth = getattr(supabase_anon, "auth", None)
        last_err = None
        # tenta em diferentes locais / nomes de método
        candidates = []
        if auth is not None:
            candidates += [
                getattr(auth, "exchange_code_for_session", None),
                getattr(getattr(auth, "api", None), "exchange_code_for_session", None),
                getattr(auth, "exchange_code_for_session", None),
            ]
        for fn in candidates:
            if fn is None:
                continue
            try:
                try:
                    fn(code)
                except TypeError:
                    fn(auth_code=code)
                # guardamos tipo do fluxo
                flow_type = qp.get("type")
                if flow_type:
                    st.session_state["auth_flow_type"] = flow_type
                _clear_auth_params_keep_page('home')
                st.success("✅ Autenticação concluída. Entrando…")
                st.rerun()
                return
            except Exception as e:
                last_err = e
                continue

        st.error(f"Falha ao finalizar autenticação (code): {last_err}")
        st.stop()

    # 2) Fluxo antigo: set_session com tokens
    if not access_token or not refresh_token:
        st.info("Finalizando autenticação… Se não avançar, feche e clique no link novamente.")
        st.stop()

    try:
        supabase_anon.auth.set_session(access_token, refresh_token)
    except Exception as e:
        st.error(f"Falha ao criar sessão: {e}")
        st.stop()

    # Guarda info do tipo de fluxo (recovery/invite/etc) para o app decidir a tela
    flow_type = qp.get("type") or ("recovery" if qp.get("recovery") else None)
    if flow_type:
        st.session_state["auth_flow_type"] = flow_type
    _clear_auth_params_keep_page('home')
    st.success("✅ Autenticação concluída. Entrando…")
    st.rerun()


def tela_primeiro_acesso_definir_senha(supabase_anon) -> None:
    """
    Tela opcional para primeiro acesso: usuário já está autenticado (via convite/magic link),
    e quer definir senha para poder entrar também por e-mail+senha.
    """
    st.subheader("🔐 Definir senha (primeiro acesso)")
    st.caption("Você já entrou pelo link. Aqui você pode definir uma senha para logins futuros (opcional).")

    s1, s2 = st.columns(2)
    with s1:
        nova = st.text_input("Nova senha", type="password")
    with s2:
        conf = st.text_input("Confirmar senha", type="password")

    if st.button("Salvar senha", type="primary", use_container_width=True):
        if not nova or len(nova) < 8:
            st.error("A senha deve ter pelo menos 8 caracteres.")
            return
        if nova != conf:
            st.error("As senhas não conferem.")
            return
        try:
            supabase_anon.auth.update_user({"password": nova})
            st.success("✅ Senha definida com sucesso! Você poderá entrar por e-mail e senha.")
            st.session_state["auth_flow_type"] = None
        except Exception as e:
            st.error(f"❌ Falha ao definir senha: {e}")


def enviar_link_redefinicao_senha(supabase_anon, email: str) -> tuple[bool, str]:
    """
    Envia e-mail de redefinição de senha (recovery).
    Compatível com diferentes versões do supabase-py / gotrue:
    - supabase_anon.auth.reset_password_for_email(...)
    - supabase_anon.auth.api.reset_password_for_email(...)
    - supabase_anon.auth.reset_password_email(...) / .api.reset_password_email(...)
    """
    if not email or "@" not in email:
        return False, "Informe um e-mail válido."

    redirect_to = f"{APP_URL}?auth_callback=1&type=recovery"

    # Lista de candidatos (objeto, nome_do_método, forma_de_chamada)
    candidates = []

    auth = getattr(supabase_anon, "auth", None)
    if auth is not None:
        candidates += [
            (auth, "reset_password_for_email"),
            (getattr(auth, "api", None), "reset_password_for_email"),
            (auth, "reset_password_email"),
            (getattr(auth, "api", None), "reset_password_email"),
        ]

    last_err = None

    for obj, method_name in candidates:
        if obj is None:
            continue
        fn = getattr(obj, method_name, None)
        if fn is None:
            continue

        # Tenta várias assinaturas comuns
        for kwargs in (
            {"redirect_to": redirect_to},
            {"options": {"redirect_to": redirect_to}},
            {"email_redirect_to": redirect_to},
            {"options": {"email_redirect_to": redirect_to}},
            {},
        ):
            try:
                # Algumas libs aceitam (email, **kwargs); outras (email=email, **kwargs)
                try:
                    fn(email, **kwargs)
                except TypeError:
                    fn(email=email, **kwargs)
                return True, "✅ Enviamos um link de redefinição para o seu e-mail."
            except Exception as e:
                last_err = e
                continue

    return False, f"❌ Falha ao enviar link: {last_err}"


def tela_redefinir_senha(supabase_anon) -> None:
    """
    Tela de redefinição de senha (recovery):
    - O usuário chega aqui via link recovery, já autenticado após handle_auth_callback().
    """
    st.subheader("♻️ Redefinir senha")
    st.caption("Defina uma nova senha para sua conta.")

    s1, s2 = st.columns(2)
    with s1:
        nova = st.text_input("Nova senha", type="password", key="reset_nova")
    with s2:
        conf = st.text_input("Confirmar senha", type="password", key="reset_conf")

    if st.button("Atualizar senha", type="primary", use_container_width=True):
        if not nova or len(nova) < 8:
            st.error("A senha deve ter pelo menos 8 caracteres.")
            return
        if nova != conf:
            st.error("As senhas não conferem.")
            return
        try:
            supabase_anon.auth.update_user({"password": nova})
            st.success("✅ Senha atualizada! Você já pode entrar com e-mail e senha.")
            st.session_state["auth_flow_type"] = None
        except Exception as e:
            st.error(f"❌ Falha ao atualizar senha: {e}")
