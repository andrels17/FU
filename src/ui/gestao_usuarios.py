"""Tela: Gestão de usuários (SaaS multi-tenant).

- auth.users: autenticação/convite
- public.tenant_users: vínculo usuário x empresa + role
- public.user_profiles: dados públicos (nome/email)

Regras:
- Convite / vínculo: SERVICE_ROLE (init_supabase_admin)
- Leitura geral do app: client do usuário (RLS)
- Nesta tela (admin), listagem de membros também usa SERVICE_ROLE para não depender de policies de SELECT.
"""

from __future__ import annotations

from typing import Any
import os

import pandas as pd
import streamlit as st

from src.core.db import init_supabase_admin


ROLE_OPTIONS = [
    ("admin", "Administrador"),
    ("gestor", "Gestor"),
    ("supervisor", "Supervisor"),
    ("operador", "Operador"),
    ("user", "Usuário"),
]


def _get_app_url() -> str:
    url = (st.secrets.get("APP_URL") or os.getenv("APP_URL") or "").strip()
    return url.rstrip("/")


def _get_current_user_id() -> str | None:
    return (
        st.session_state.get("auth_user_id")
        or st.session_state.get("user_id")
        or (st.session_state.get("usuario") or {}).get("id")
    )


def _get_current_tenant_id() -> str | None:
    return st.session_state.get("tenant_id")


def _is_tenant_admin(_supabase, tenant_id: str, user_id: str) -> bool:
    """Checa se o usuário logado é admin no tenant atual (via RLS do próprio usuário)."""
    try:
        res = (
            _supabase.table("tenant_users")
            .select("role")
            .eq("tenant_id", tenant_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        role = (res.data or [{}])[0].get("role")
        return role == "admin"
    except Exception:
        return False


def _is_admin_api_ready() -> tuple[bool, str]:
    """Verifica se o client admin realmente está com SERVICE_ROLE."""
    try:
        supabase_admin = init_supabase_admin()
        # chamada leve; se falhar, normalmente é key errada
        if hasattr(supabase_admin.auth.admin, "list_users"):
            supabase_admin.auth.admin.list_users(page=1, per_page=1)
        return True, ""
    except Exception as e:
        return False, str(e)


def _safe_invite_user_by_email(
    supabase_admin,
    email: str,
    nome: str | None = None,
) -> dict[str, Any]:
    """Envia convite por e-mail (magic link) com redirect para APP_URL.

    Compatível com variações de assinatura entre versões do supabase-py/gotrue.
    """
    app_url = _get_app_url()
    redirect_to = f"{app_url}/?auth_callback=1&type=invite" if app_url else None

    admin = getattr(getattr(supabase_admin, "auth", None), "admin", None)
    fn = getattr(admin, "invite_user_by_email", None)
    if fn is None:
        return {"ok": False, "error": "Admin API não possui invite_user_by_email nesta versão."}

    # 1) Tenta assinatura: invite_user_by_email(email=email, redirect_to=...)
    if redirect_to:
        try:
            res = fn(email=email, redirect_to=redirect_to)
            return {"ok": True, "res": res}
        except TypeError:
            pass
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # 2) Tenta assinatura: invite_user_by_email(email=email, options={...})
    options: dict[str, Any] = {}
    if redirect_to:
        options["redirect_to"] = redirect_to
    if nome:
        # algumas versões aceitam metadata via options.data ou options.user_metadata
        options["data"] = {"nome": nome}
        options["user_metadata"] = {"nome": nome}

    if options:
        try:
            res = fn(email=email, options=options)
            return {"ok": True, "res": res}
        except TypeError:
            pass
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # 3) Fallback: só email
    try:
        res = fn(email=email)
        return {"ok": True, "res": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _safe_send_recovery_email(supabase_admin, email: str) -> dict[str, Any]:
    """Envia e-mail de recuperação de senha via Admin API (usuário já existe)."""
    app_url = _get_app_url()
    options: dict[str, Any] = {}
    if app_url:
        options["redirectTo"] = f"{app_url}/"
        options["redirect_to"] = f"{app_url}/"

    # supabase-py v2 costuma expor generate_link
    try:
        payload: dict[str, Any] = {"type": "recovery", "email": email}
        if options:
            payload["options"] = options
        res = supabase_admin.auth.admin.generate_link(payload)
        return {"ok": True, "res": res}
    except TypeError:
        pass
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # fallback
    try:
        res = supabase_admin.auth.admin.generate_link(type="recovery", email=email, options=options or None)
        return {"ok": True, "res": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _safe_create_user_with_password(
    supabase_admin,
    email: str,
    password: str,
    nome: str | None = None,
) -> dict[str, Any]:
    """Cria usuário manualmente no Auth (Admin API) e retorna o objeto de resposta.

    Compatível com variações de versão:
    - admin.create_user(payload_dict)
    - admin.create_user(email=..., password=..., email_confirm=..., user_metadata=...)
    """
    email_norm = (email or "").strip().lower()
    if not email_norm or "@" not in email_norm:
        return {"ok": False, "error": "Informe um e-mail válido."}
    if not password or len(password) < 8:
        return {"ok": False, "error": "A senha deve ter pelo menos 8 caracteres."}

    meta: dict[str, Any] = {}
    if nome:
        meta["nome"] = (nome or "").strip()

    admin = supabase_admin.auth.admin
    fn = getattr(admin, "create_user", None)
    if fn is None:
        return {"ok": False, "error": "Admin API não possui create_user nesta versão."}

    payload: dict[str, Any] = {
        "email": email_norm,
        "password": password,
        "email_confirm": True,
    }
    if meta:
        payload["user_metadata"] = meta
        payload["data"] = meta

    # tentativa 1: payload dict
    try:
        res = fn(payload)
        return {"ok": True, "res": res}
    except TypeError:
        pass
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # tentativa 2: kwargs
    try:
        res = fn(email=email_norm, password=password, email_confirm=True, user_metadata=meta or None)
        return {"ok": True, "res": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}



def _safe_set_password_by_user_id(supabase_admin, user_id: str, new_password: str) -> dict[str, Any]:
    """Define senha diretamente via Admin API (SERVICE_ROLE)."""
    if not user_id:
        return {"ok": False, "error": "user_id não informado."}
    if not new_password or len(new_password) < 8:
        return {"ok": False, "error": "A senha deve ter pelo menos 8 caracteres."}

    try:
        admin = supabase_admin.auth.admin
        if hasattr(admin, "update_user_by_id"):
            admin.update_user_by_id(user_id, {"password": new_password})
            return {"ok": True}
        if hasattr(admin, "update_user"):
            admin.update_user(user_id, {"password": new_password})
            return {"ok": True}
        return {"ok": False, "error": "Admin API não suporta update_user_by_id/update_user nesta versão."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _extract_user_id(invite_res: Any) -> str | None:
    """Extrai user_id do retorno do convite (varia por versão)."""
    for path in [
        ("user", "id"),
        ("data", "id"),
        ("data", "user", "id"),
    ]:
        cur: Any = invite_res
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                cur = getattr(cur, k, None)
            if cur is None:
                ok = False
                break
        if ok and isinstance(cur, str):
            return cur
    if isinstance(invite_res, str):
        return invite_res
    return None


def _normalize_admin_user(obj: Any) -> dict[str, Any]:
    """Normaliza retorno do admin (supabase-py) para dict com user_id/email/nome."""
    if obj is None:
        return {}

    if isinstance(obj, dict):
        user = obj.get("user") or obj.get("data") or obj
    else:
        user = getattr(obj, "user", None) or getattr(obj, "data", None) or obj

    if isinstance(user, dict):
        uid = user.get("id") or user.get("user_id")
        email = user.get("email")
        meta = user.get("user_metadata") or user.get("raw_user_meta_data") or {}
    else:
        uid = getattr(user, "id", None) or getattr(user, "user_id", None)
        email = getattr(user, "email", None)
        meta = getattr(user, "user_metadata", None) or getattr(user, "raw_user_meta_data", None) or {}

    nome = ""
    if isinstance(meta, dict):
        nome = meta.get("nome") or meta.get("name") or ""
    else:
        nome = getattr(meta, "nome", None) or getattr(meta, "name", None) or ""

    out: dict[str, Any] = {}
    if uid:
        out["user_id"] = str(uid)
    if email:
        out["email"] = str(email)
    if nome:
        out["nome"] = str(nome)
    return out


@st.cache_data(ttl=300, show_spinner=False)
def _admin_fetch_users(user_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Busca e-mails/nomes via Admin API para IDs sem profile (evita tela vazia).

    Não recebe client como parâmetro para evitar UnhashableParamError no cache.
    """
    supabase_admin = init_supabase_admin()
    out: dict[str, dict[str, Any]] = {}
    for uid in user_ids or []:
        try:
            res = supabase_admin.auth.admin.get_user_by_id(uid)
            info = _normalize_admin_user(res)
            if info.get("user_id"):
                out[info["user_id"]] = info
        except Exception:
            continue
    return out


@st.cache_data(ttl=300, show_spinner=False)
def _admin_find_user_id_by_email(email: str) -> str | None:
    """Encontra user_id pelo email via Admin API (list_users + filtro)."""
    email_norm = (email or "").strip().lower()
    if not email_norm:
        return None

    supabase_admin = init_supabase_admin()
    try:
        page = 1
        per_page = 200
        for _ in range(1, 51):  # até 10k usuários
            res = supabase_admin.auth.admin.list_users(page=page, per_page=per_page)

            users = None
            if isinstance(res, dict):
                users = res.get("users") or (res.get("data") or {}).get("users")
            else:
                users = getattr(res, "users", None) or getattr(getattr(res, "data", None), "users", None)

            users = users or []
            if not users:
                break

            for u in users:
                info = _normalize_admin_user(u)
                if info.get("email", "").strip().lower() == email_norm:
                    return info.get("user_id")

            page += 1
    except Exception:
        return None

    return None


def _upsert_user_profile_admin(supabase_admin, user_id: str, email: str | None = None, nome: str | None = None) -> None:
    """Cria/atualiza user_profiles com tolerância a diferenças de schema/lib.

    - Usa SERVICE_ROLE (supabase_admin).
    - Não grava senha (apenas perfil).
    """
    if not user_id:
        return
    payload: dict[str, Any] = {"user_id": user_id}
    if email:
        payload["email"] = (email or "").strip().lower()
    if nome:
        payload["nome"] = (nome or "").strip() or None

    # supabase-py v2 costuma suportar on_conflict
    try:
        supabase_admin.table("user_profiles").upsert(payload, on_conflict="user_id").execute()
        return
    except TypeError:
        pass
    except Exception:
        # tenta fallback abaixo
        pass

    # fallback: tenta upsert simples
    try:
        supabase_admin.table("user_profiles").upsert(payload).execute()
        return
    except Exception:
        pass

    # último fallback: tenta update, se não existir faz insert
    try:
        q = supabase_admin.table("user_profiles").update(payload).eq("user_id", user_id).execute()
        if not getattr(q, "data", None):
            supabase_admin.table("user_profiles").insert(payload).execute()
    except Exception:
        pass


def _load_profiles_safe(_supabase, user_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Carrega perfis; se falhar, retorna dict vazio (não quebra a UI)."""
    if not user_ids:
        return {}
    try:
        res = (
            _supabase.table("user_profiles")
            .select("user_id, email, nome")
            .in_("user_id", user_ids)
            .execute()
        )
        profs = res.data or []
        return {p.get("user_id"): p for p in profs if p.get("user_id")}
    except Exception:
        return {}


def exibir_gestao_usuarios(_supabase):
    tenant_id = _get_current_tenant_id()
    user_id = _get_current_user_id()

    if not tenant_id:
        st.error("❌ Tenant não definido. Selecione uma empresa no menu lateral.")
        return
    if not user_id:
        st.error("❌ Usuário não identificado. Faça login novamente.")
        return

    if not _is_tenant_admin(_supabase, tenant_id, user_id):
        st.error("⛔ Acesso negado. Apenas administradores desta empresa podem gerenciar usuários.")
        return

    st.title("👥 Gestão de Usuários (Empresa)")

    admin_ok, admin_err = _is_admin_api_ready()
    if not admin_ok:
        st.warning(
            "⚠️ Admin API não está pronta (provável ausência da SERVICE_ROLE).\n\n"
            f"Detalhe: {admin_err}"
        )

    supabase_admin = init_supabase_admin()

    # --- Listagem de membros do tenant (via SERVICE_ROLE)
    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("Membros da empresa")
    with col2:
        if st.button("🔄 Atualizar", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    try:
        r = (
            supabase_admin.table("tenant_users")
            .select("user_id, role, created_at")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=False)
            .execute()
        )
        rows = r.data or []
    except Exception as e:
        st.error(f"❌ Falha ao carregar vínculos (tenant_users): {e}")
        return

    user_ids = [x.get("user_id") for x in rows if x.get("user_id")]

    profiles = _load_profiles_safe(_supabase, user_ids)

    missing_ids = [uid for uid in user_ids if uid not in profiles]
    admin_info: dict[str, dict[str, Any]] = {}
    if missing_ids and admin_ok:
        admin_info = _admin_fetch_users(missing_ids)

    table = []
    for x in rows:
        uid = x.get("user_id")
        role = x.get("role") or ""
        created_at = x.get("created_at")

        p = profiles.get(uid) or {}
        a = admin_info.get(uid) or {}

        email = p.get("email") or a.get("email") or ""
        nome = p.get("nome") or a.get("nome") or ""

        table.append(
            {"user_id": uid, "nome": nome, "email": email, "role": role, "created_at": created_at}
        )

    df = pd.DataFrame(table)
    if df.empty:
        st.info("Nenhum membro vinculado a esta empresa.")
    else:
        st.dataframe(
            df[["nome", "email", "role", "created_at", "user_id"]],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.subheader("⚙️ Gerenciar usuário da empresa")

    if not df.empty:
        usuario_sel = st.selectbox(
            "Selecione o usuário",
            options=df.to_dict("records"),
            format_func=lambda x: f"{(x.get('nome') or 'Sem nome')} • {x.get('email') or 'Sem e-mail'} • {x.get('role') or ''}",
        )

        if usuario_sel:
            uid_sel = usuario_sel.get("user_id")
            email_sel = (usuario_sel.get("email") or "").strip().lower()
            nome_sel = usuario_sel.get("nome") or ""
            role_sel = usuario_sel.get("role") or "user"

            st.markdown("### ✏️ Editar perfil e permissões")

            col_a, col_b = st.columns(2)
            novo_nome = col_a.text_input("Nome", value=nome_sel, key=f"edit_nome_{uid_sel}")
            novo_role = col_b.selectbox(
                "Papel (role)",
                options=[r[0] for r in ROLE_OPTIONS],
                index=[r[0] for r in ROLE_OPTIONS].index(role_sel)
                if role_sel in [r[0] for r in ROLE_OPTIONS]
                else 0,
                key=f"edit_role_{uid_sel}",
                format_func=lambda v: dict(ROLE_OPTIONS).get(v, v),
            )

            c1, c2 = st.columns(2)
            if c1.button("💾 Salvar alterações", key=f"btn_save_{uid_sel}", use_container_width=True):
                try:
                    # Atualiza role no vínculo do tenant
                    supabase_admin.table("tenant_users").update(
                        {"role": novo_role}
                    ).eq("tenant_id", tenant_id).eq("user_id", uid_sel).execute()

                    # Atualiza/insere profile (nome/email)
                    _upsert_user_profile_admin(
                        supabase_admin,
                        user_id=uid_sel,
                        email=email_sel or None,
                        nome=novo_nome or None,
                    )

                    st.success("✅ Usuário atualizado com sucesso!")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao atualizar usuário: {e}")

            if c2.button("🗑️ Remover da empresa", key=f"btn_remove_{uid_sel}", use_container_width=True):
                try:
                    supabase_admin.table("tenant_users").delete().eq(
                        "tenant_id", tenant_id
                    ).eq("user_id", uid_sel).execute()

                    st.success("✅ Usuário removido da empresa (vínculo apagado).")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao remover usuário da empresa: {e}")

            st.divider()
            
            st.divider()
            st.markdown("### 🔐 Senha do usuário")
            
            colA, colB = st.columns([1, 1])
            
            # (1) Link de redefinição (recomendado)
            with colA:
                if st.button(
                    "📧 Enviar link de redefinição (recomendado)",
                    key=f"btn_recovery_{uid_sel}",
                    use_container_width=True,
                ):
                    if not admin_ok:
                        st.error(
                            "❌ Admin API sem permissão (SERVICE_ROLE ausente). "
                            "Não é possível enviar recuperação."
                        )
                    elif not email_sel:
                        st.error("❌ E-mail não disponível para este usuário.")
                    else:
                        rr = _safe_send_recovery_email(supabase_admin, email_sel)
                        if rr.get("ok"):
                            st.success("✅ Link de redefinição enviado!")
                        else:
                            st.error(f"Falha ao enviar recovery: {rr.get('error')}")
            
            # (2) Definir senha diretamente (admin)
            with colB:
                with st.form(f"form_set_senha_{uid_sel}"):
                    st.caption("Definir senha diretamente (admin).")
                    nova_senha = st.text_input(
                        "Nova senha (mín. 8)",
                        type="password",
                        key=f"nova_senha_{uid_sel}",
                    )
                    confirmar = st.text_input(
                        "Confirmar senha",
                        type="password",
                        key=f"conf_senha_{uid_sel}",
                    )
                    ok_set = st.form_submit_button("🔑 Definir senha", use_container_width=True)
            
                    if ok_set:
                        if not nova_senha or len(nova_senha) < 8:
                            st.error("A senha deve ter pelo menos 8 caracteres.")
                        elif nova_senha != confirmar:
                            st.error("As senhas não conferem.")
                        else:
                            rr = _safe_set_password_by_user_id(supabase_admin, uid_sel, nova_senha)
                            if rr.get("ok"):
                                st.success("✅ Senha atualizada com sucesso.")
                            else:
                                st.error(f"Falha ao atualizar senha: {rr.get('error')}")
            
            
                # --- Recuperação de senha
                st.markdown("#### 🔐 Recuperação de senha (usuário já cadastrado)")
                st.caption("Use quando o usuário já existe e precisa redefinir a senha para entrar.")
            
                emails_disponiveis = [e for e in (df["email"].tolist() if not df.empty else []) if isinstance(e, str) and e.strip()]
                if emails_disponiveis:
                    c1, c2 = st.columns([3, 1])
                    email_reset = c1.selectbox("Selecione o usuário (email)", options=sorted(set(emails_disponiveis)))
                    if c2.button("📧 Enviar link", use_container_width=True):
                        if not admin_ok:
                            st.error(
                                "❌ Admin API sem permissão. Não é possível enviar recuperação.\n\n"
                                "Verifique SUPABASE_SERVICE_ROLE_KEY e reinicie o app."
                            )
                        else:
                            rr = _safe_send_recovery_email(supabase_admin, email_reset)
                            if rr.get("ok"):
                                st.success("✅ Link de recuperação enviado! Oriente o usuário a verificar o e-mail.")
                            else:
                                st.error(f"❌ Falha ao enviar recuperação: {rr.get('error')}")
                else:
                    st.info("Nenhum e-mail disponível na lista para enviar recuperação.")
            
                st.divider()
            
                # --- Convidar usuário / vincular existente
            
                st.divider()
    st.subheader("➕ Adicionar usuário")

    tab_invite, tab_manual = st.tabs(["📨 Por convite (recomendado)", "🧑‍💻 Manual (com senha)"])

    with tab_invite:
        st.caption("Envia convite por e-mail (magic link) e tenta vincular na empresa automaticamente.")

        with st.form("form_convidar_usuario", clear_on_submit=False):
            c1, c2, c3 = st.columns([2, 2, 2])
            email = c1.text_input("Email", placeholder="usuario@empresa.com").strip()
            nome = c2.text_input("Nome (opcional)", placeholder="Nome do usuário").strip()
            role = c3.selectbox(
                "Papel",
                options=[r[0] for r in ROLE_OPTIONS],
                format_func=lambda v: dict(ROLE_OPTIONS).get(v, v),
            )
            submitted = st.form_submit_button("📨 Enviar convite / Vincular", use_container_width=True)

        if submitted:
            if not email or "@" not in email:
                st.error("❌ Informe um e-mail válido.")
            elif not admin_ok:
                st.error(
                    "❌ Falha ao convidar: Admin API sem permissão.\n\n"
                    "Isso acontece quando o client admin está usando ANON key ao invés da SERVICE_ROLE.\n"
                    "Verifique SUPABASE_SERVICE_ROLE_KEY nos secrets/variáveis do Streamlit e reinicie o app."
                )
            else:
                invite = _safe_invite_user_by_email(supabase_admin, email=email, nome=nome or None)

                if not invite.get("ok"):
                    err = invite.get("error", "erro desconhecido")

                    # Caso: já existe no Auth -> apenas vincular/atualizar vínculo
                    if "already been registered" in err.lower() or "already registered" in err.lower():
                        existing_user_id = _admin_find_user_id_by_email(email)
                        if not existing_user_id:
                            st.error(
                                "⚠️ O e-mail já existe no sistema, mas não consegui localizar o usuário pelo Admin API.\n\n"
                                "Confirme se o usuário foi criado neste mesmo projeto Supabase e tente novamente."
                            )
                        else:
                            try:
                                existing_link = (
                                    supabase_admin.table("tenant_users")
                                    .select("user_id, role")
                                    .eq("tenant_id", tenant_id)
                                    .eq("user_id", existing_user_id)
                                    .limit(1)
                                    .execute()
                                )

                                if existing_link.data:
                                    supabase_admin.table("tenant_users").update({"role": role}).eq(
                                        "tenant_id", tenant_id
                                    ).eq("user_id", existing_user_id).execute()
                                    st.success("✅ Usuário já existia. Vínculo encontrado e perfil atualizado na empresa!")
                                else:
                                    supabase_admin.table("tenant_users").insert(
                                        {"tenant_id": tenant_id, "user_id": existing_user_id, "role": role}
                                    ).execute()
                                    st.success("✅ Usuário já existia. Agora ele foi vinculado à empresa!")

                                _upsert_user_profile_admin(
                                    supabase_admin, existing_user_id, email=email, nome=nome or None
                                )

                                st.info(
                                    "ℹ️ Como o usuário já existia, ele deve entrar pelo login normal.\n"
                                    "Se não lembrar a senha, use a opção de recuperação de senha acima."
                                )
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Falha ao vincular/atualizar usuário existente no tenant_users: {e}")
                    else:
                        st.error(f"❌ Falha ao convidar: {err}")
                else:
                    invited_user_id = _extract_user_id(invite.get("res"))
                    if not invited_user_id:
                        st.success("✅ Convite enviado (não foi possível extrair o user_id do retorno).")
                    else:
                        try:
                            supabase_admin.table("tenant_users").insert(
                                {"tenant_id": tenant_id, "user_id": invited_user_id, "role": role}
                            ).execute()
                        except Exception as e:
                            st.warning(
                                "Convite enviado, mas falhou ao vincular o usuário na empresa (tenant_users).\n\n"
                                f"Detalhe: {e}"
                            )
                        else:
                            _upsert_user_profile_admin(
                                supabase_admin, invited_user_id, email=email, nome=nome or None
                            )
                            st.success("✅ Convite enviado e usuário vinculado à empresa!")
                            st.cache_data.clear()
                            st.rerun()

    with tab_manual:
        st.caption(
            "Cria o usuário diretamente no Auth (Admin API) e já vincula nesta empresa. "
            "Use uma senha temporária e, se necessário, mande o link de redefinição."
        )

        with st.form("form_criar_usuario_manual", clear_on_submit=False):
            c1, c2, c3 = st.columns([2, 2, 2])
            email_m = c1.text_input("Email", key="manual_email", placeholder="usuario@empresa.com").strip().lower()
            nome_m = c2.text_input("Nome (opcional)", key="manual_nome").strip()
            role_m = c3.selectbox(
                "Papel",
                options=[r[0] for r in ROLE_OPTIONS],
                format_func=lambda v: dict(ROLE_OPTIONS).get(v, v),
                key="manual_role",
            )

            senha_m = st.text_input("Senha temporária (mín. 8)", type="password", key="manual_pass")
            criar = st.form_submit_button("Criar e vincular", use_container_width=True)

            forcar_troca = st.checkbox("Forçar troca de senha (enviar recovery após criar)", value=True, key="manual_force_recovery")

        if criar:
            if not admin_ok:
                st.error(
                    "❌ Admin API sem permissão (SERVICE_ROLE ausente/errada). "
                    "Configure SUPABASE_SERVICE_ROLE_KEY e reinicie o app."
                )
            else:
                cr = _safe_create_user_with_password(
                    supabase_admin, email=email_m, password=senha_m, nome=nome_m or None
                )
                if not cr.get("ok"):
                    st.error(f"❌ Falha ao criar usuário: {cr.get('error')}")
                else:
                    info = _normalize_admin_user(cr.get("res"))
                    new_uid = info.get("user_id")

                    if not new_uid:
                        st.warning(
                            "Usuário criado, mas não consegui extrair o user_id do retorno. "
                            "Verifique no Supabase Auth."
                        )
                    else:
                        try:
                            supabase_admin.table("tenant_users").upsert(
                                {"tenant_id": tenant_id, "user_id": new_uid, "role": role_m},
                                on_conflict="tenant_id,user_id",
                            ).execute()
                        except TypeError:
                            try:
                                supabase_admin.table("tenant_users").upsert(
                                    {"tenant_id": tenant_id, "user_id": new_uid, "role": role_m}
                                ).execute()
                            except Exception:
                                supabase_admin.table("tenant_users").insert(
                                    {"tenant_id": tenant_id, "user_id": new_uid, "role": role_m}
                                ).execute()

                        _upsert_user_profile_admin(
                            supabase_admin, user_id=new_uid, email=email_m, nome=nome_m or None
                        )

                        st.success("✅ Usuário criado e vinculado à empresa!")

                        if forcar_troca and email_m:
                            rr = _safe_send_recovery_email(supabase_admin, email_m)
                            if rr.get("ok"):
                                st.info("📧 Enviamos um link de redefinição para o usuário trocar a senha.")
                            else:
                                st.warning(f"Usuário criado, mas falhou ao enviar recovery: {rr.get('error')}")

                        st.cache_data.clear()
                        st.rerun()
