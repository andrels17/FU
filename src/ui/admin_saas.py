from __future__ import annotations

from typing import Any
import os

import streamlit as st

from src.ui import ux

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


def _pick_tenant_name_field(supabase_admin) -> str:
    """
    Descobre qual campo de nome existe em public.tenants.
    Tentamos 'nome' e depois 'name'.
    """
    for field in ("nome", "name"):
        try:
            supabase_admin.table("tenants").select(f"id,{field}").limit(1).execute()
            return field
        except Exception:
            continue
    # fallback: assume 'nome' (vai estourar com msg clara)
    return "nome"


def _list_tenants(supabase_admin) -> tuple[list[dict[str, Any]], str]:
    """
    Lista tenants tentando colunas com fallback (evita erro de tenants.codigo).
    Retorna (tenants, name_field).
    """
    name_field = _pick_tenant_name_field(supabase_admin)

    # tenta com codigo, se não existir cai para sem codigo
    try:
        res = (
            supabase_admin.table("tenants")
            .select(f"id,{name_field},codigo")
            .order(name_field)
            .execute()
        )
        return (res.data or []), name_field
    except Exception:
        res = (
            supabase_admin.table("tenants")
            .select(f"id,{name_field}")
            .order(name_field)
            .execute()
        )
        return (res.data or []), name_field


def _safe_invite_user_by_email(supabase_admin, email: str, nome: str | None = None) -> dict[str, Any]:
    """
    Envia convite por e-mail (Admin API) com compatibilidade entre versões.
    """
    app_url = _get_app_url()
    redirect_to = f"{app_url}/?auth_callback=1&type=invite" if app_url else None

    try:
        admin = supabase_admin.auth.admin
        fn = getattr(admin, "invite_user_by_email", None)
        if fn is None:
            return {"ok": False, "error": "Admin API não possui invite_user_by_email nesta versão."}

        # 1) tenta assinatura simples: (email, redirect_to=...)
        if redirect_to:
            try:
                fn(email=email, redirect_to=redirect_to)
                return {"ok": True}
            except TypeError:
                pass

        # 2) tenta com options (muito comum): options={"redirect_to":..., "data":...}
        options: dict[str, Any] = {}
        if redirect_to:
            options["redirect_to"] = redirect_to
        if nome:
            # em algumas versões é "data", em outras "user_metadata"
            options["data"] = {"nome": nome}
            options["user_metadata"] = {"nome": nome}

        if options:
            try:
                fn(email=email, options=options)
                return {"ok": True}
            except TypeError:
                pass

        # 3) fallback: só e-mail
        fn(email=email)
        return {"ok": True}

    except Exception as e:
        return {"ok": False, "error": str(e)}



def _safe_send_recovery_email(supabase_admin, email: str) -> dict[str, Any]:
    """
    Envia link de recuperação (recovery) para o usuário.
    Compatível com diferenças de versões do supabase-py/gotrue.
    """
    app_url = _get_app_url()
    redirect_to = f"{app_url}/?auth_callback=1&type=recovery" if app_url else None

    auth = getattr(supabase_admin, "auth", None)
    if auth is None:
        return {"ok": False, "error": "Cliente Supabase sem auth."}

    candidates = [
        getattr(auth, "reset_password_for_email", None),
        getattr(getattr(auth, "api", None), "reset_password_for_email", None),
        getattr(auth, "reset_password_email", None),
        getattr(getattr(auth, "api", None), "reset_password_email", None),
    ]

    last_err: Exception | None = None
    for fn in candidates:
        if fn is None:
            continue
        for kwargs in (
            {"redirect_to": redirect_to} if redirect_to else {},
            {"options": {"redirect_to": redirect_to}} if redirect_to else {},
            {"email_redirect_to": redirect_to} if redirect_to else {},
            {"options": {"email_redirect_to": redirect_to}} if redirect_to else {},
            {},
        ):
            try:
                try:
                    fn(email, **kwargs)
                except TypeError:
                    fn(email=email, **kwargs)
                return {"ok": True}
            except Exception as e:
                last_err = e
                continue

    return {"ok": False, "error": str(last_err) if last_err else "Falha desconhecida"}


def _safe_set_temp_password(supabase_admin, user_id: str, new_password: str) -> dict[str, Any]:
    """
    Define uma senha diretamente via Admin API.
    Nem todas as versões suportam o mesmo método.
    """
    try:
        admin = supabase_admin.auth.admin

        # supabase-py mais novo
        if hasattr(admin, "update_user_by_id"):
            admin.update_user_by_id(user_id, {"password": new_password})
            return {"ok": True}

        # fallback genérico
        if hasattr(admin, "update_user"):
            admin.update_user(user_id, {"password": new_password})
            return {"ok": True}

        return {"ok": False, "error": "Admin API não suporta update_user_by_id/update_user nesta versão."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _link_user_to_tenant(
    supabase_admin,
    tenant_id: str,
    user_id: str,
    role: str,
) -> dict[str, Any]:
    """
    Cria/atualiza vínculo em tenant_users (Service Role).
    """
    try:
        # tenta upsert (se houver constraint), senão faz insert simples
        payload = {"tenant_id": tenant_id, "user_id": user_id, "role": role}

        try:
            supabase_admin.table("tenant_users").upsert(payload).execute()
            return {"ok": True}
        except Exception:
            supabase_admin.table("tenant_users").insert(payload).execute()
            return {"ok": True}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def _list_tenant_members(supabase_admin, tenant_id: str) -> list[dict[str, Any]]:
    """
    Lista membros do tenant (tenant_users + user_profiles).
    """
    res = (
        supabase_admin.table("tenant_users")
        .select("user_id,role")
        .eq("tenant_id", tenant_id)
        .execute()
    )
    links = res.data or []
    user_ids = [x.get("user_id") for x in links if x.get("user_id")]
    if not user_ids:
        return []

    # tenta buscar perfil público
    profiles_map: dict[str, dict[str, Any]] = {}
    try:
        pr = supabase_admin.table("user_profiles").select("user_id,email,nome").in_("user_id", user_ids).execute()
        for p in pr.data or []:
            profiles_map[p.get("user_id")] = p
    except Exception:
        # segue sem perfis
        pass

    out: list[dict[str, Any]] = []
    for l in links:
        uid = l.get("user_id")
        prof = profiles_map.get(uid, {})
        out.append(
            {
                "user_id": uid,
                "role": l.get("role"),
                "email": prof.get("email"),
                "nome": prof.get("nome"),
            }
        )
    return out


def exibir_admin_saas(supabase_user) -> None:
    """
    Tela Super Admin (SaaS):
    - Empresas: criar, listar, editar nome
    - Usuários por empresa: convidar, vincular, alterar role, reset senha
    """
    st.title("🧩 Admin do SaaS")

    # Service Role é obrigatório aqui
    try:
        supabase_admin = init_supabase_admin()
    except Exception as e:
        st.error(
            "❌ Não consegui inicializar o cliente ADMIN (SERVICE ROLE).\n\n"
            "Verifique SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY em st.secrets.\n\n"
            f"Detalhe: {e}"
        )
        return

    tenants, name_field = _list_tenants(supabase_admin)

    tab_emp, tab_users = st.tabs(["🏢 Empresas", "👥 Usuários por empresa"])

    # =========================
    # TAB: Empresas
    # =========================
    with tab_emp:
        st.subheader("➕ Criar empresa")

        with st.form("form_criar_empresa"):
            nome = st.text_input("Nome da empresa", key="saas_nome_empresa")
            codigo = st.text_input("Código (opcional)", key="saas_codigo_empresa")
            ok = st.form_submit_button("Criar", use_container_width=True)

            if ok:
                if not nome.strip():
                    st.error("Informe o nome da empresa.")
                else:
                    # tenta inserir com campo nome descoberto
                    payload = {name_field: nome.strip()}
                    if codigo.strip():
                        payload["codigo"] = codigo.strip()

                    try:
                        supabase_admin.table("tenants").insert(payload).execute()
                        ux.ok("✅ Empresa criada!")
                        st.rerun()
                    except Exception:
                        # fallback: sem codigo
                        try:
                            supabase_admin.table("tenants").insert({name_field: nome.strip()}).execute()
                            ux.ok("✅ Empresa criada (sem código)!")
                            st.rerun()
                        except Exception as e2:
                            st.error(f"Erro ao criar empresa: {e2}")

        st.divider()
        st.subheader("✏️ Editar empresa")

        if not tenants:
            ux.info("Nenhuma empresa cadastrada.")
        else:
            # select tenant
            def _label(t: dict[str, Any]) -> str:
                nm = t.get(name_field) or "Sem nome"
                cod = t.get("codigo")
                if cod:
                    return f"{nm} ({cod})"
                return f"{nm}"

            tenant_sel = st.selectbox(
                "Selecione a empresa",
                options=tenants,
                format_func=_label,
                key="saas_tenant_sel_emp",
            )

            if tenant_sel:
                tenant_id = tenant_sel.get("id")
                nome_atual = tenant_sel.get(name_field) or ""
                st.caption(f"ID: `{tenant_id}`")

                novo_nome = st.text_input("Nome", value=nome_atual, key="saas_edit_nome")

                c1, c2 = st.columns([1, 1])
                with c1:
                    if st.button("Salvar alterações", type="primary", use_container_width=True):
                        if not novo_nome.strip():
                            st.error("O nome não pode ficar vazio.")
                        else:
                            try:
                                supabase_admin.table("tenants").update(
                                    {name_field: novo_nome.strip()}
                                ).eq("id", tenant_id).execute()
                                ux.ok("✅ Empresa atualizada!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao atualizar empresa: {e}")

                with c2:
                    # opcional: ao criar empresa, vincular você como admin
                    if st.button("Vincular-me como admin desta empresa", use_container_width=True):
                        user_id = _get_current_user_id()
                        if not user_id:
                            st.error("Não consegui identificar seu user_id logado.")
                        else:
                            rr = _link_user_to_tenant(supabase_admin, tenant_id, user_id, "admin")
                            if rr.get("ok"):
                                ux.ok("✅ Você foi vinculado como admin.")
                            else:
                                st.error(f"Falha ao vincular: {rr.get('error')}")

    # =========================
    # TAB: Usuários por empresa
    # =========================
    with tab_users:
        st.subheader("👥 Gestão de usuários por empresa")

        if not tenants:
            ux.info("Crie uma empresa primeiro.")
        else:
            tenant_sel = st.selectbox(
                "Empresa",
                options=tenants,
                format_func=lambda t: (t.get(name_field) or "Sem nome"),
                key="saas_tenant_sel_users",
            )
            tenant_id = tenant_sel.get("id")

            st.divider()
            st.markdown("### ➕ Convidar usuário (e-mail) e vincular")

            with st.form("form_invite_link"):
                email = st.text_input("E-mail", key="saas_invite_email").strip().lower()
                nome = st.text_input("Nome (opcional)", key="saas_invite_nome").strip()
                role = st.selectbox("Perfil (role)", options=[r[0] for r in ROLE_OPTIONS], index=0, key="saas_invite_role")
                submit = st.form_submit_button("Enviar convite", use_container_width=True)

                if submit:
                    if not email or "@" not in email:
                        st.error("Informe um e-mail válido.")
                    else:
                        inv = _safe_invite_user_by_email(supabase_admin, email=email, nome=nome or None)
                        if not inv.get("ok"):
                            st.error(f"Falha ao enviar convite: {inv.get('error')}")
                        else:
                            ux.ok("✅ Convite enviado! Assim que o usuário aceitar, você poderá vinculá-lo abaixo.")

            st.divider()
            st.markdown("### 🔗 Vincular usuário existente ao tenant")

            with st.form("form_link_existing"):
                user_id = st.text_input("User ID (UUID do auth.users)", key="saas_link_userid").strip()
                role2 = st.selectbox(
                    "Role no tenant",
                    options=[r[0] for r in ROLE_OPTIONS],
                    index=0,
                    key="saas_link_role",
                )
                submit2 = st.form_submit_button("Vincular / Atualizar role", use_container_width=True)

                if submit2:
                    if not user_id:
                        st.error("Informe o User ID.")
                    else:
                        rr = _link_user_to_tenant(supabase_admin, tenant_id, user_id, role2)
                        if rr.get("ok"):
                            ux.ok("✅ Vínculo atualizado!")
                        else:
                            st.error(f"Falha: {rr.get('error')}")

            st.divider()
            st.markdown("### 📋 Membros da empresa")

            try:
                members = _list_tenant_members(supabase_admin, tenant_id)
                if not members:
                    ux.info("Nenhum usuário vinculado a esta empresa ainda.")
                else:
                    for m in members:
                        email_m = m.get("email") or "—"
                        nome_m = m.get("nome") or "—"
                        role_m = m.get("role") or "—"
                        uid_m = m.get("user_id") or "—"

                        with st.expander(f"{email_m} • {role_m}"):
                            st.write(f"**Nome:** {nome_m}")
                            st.write(f"**User ID:** `{uid_m}`")

                            # editar role rápido
                            new_role = st.selectbox(
                                "Alterar role",
                                options=[r[0] for r in ROLE_OPTIONS],
                                index=[r[0] for r in ROLE_OPTIONS].index(role_m) if role_m in [r[0] for r in ROLE_OPTIONS] else 0,
                                key=f"role_{uid_m}",
                            )
                            if st.button("Salvar role", key=f"save_role_{uid_m}", use_container_width=True):
                                rr = _link_user_to_tenant(supabase_admin, tenant_id, uid_m, new_role)
                                if rr.get("ok"):
                                    ux.ok("✅ Role atualizada!")
                                else:
                                    st.error(f"Falha: {rr.get('error')}")

                            st.divider()

                            st.markdown("#### 🔑 Senha do usuário")
                            c1, c2 = st.columns(2)

                            with c1:
                                if st.button("📧 Enviar link de redefinição (recomendado)", key=f"recovery_{uid_m}", use_container_width=True):
                                    if email_m == "—":
                                        st.error("Não tenho o e-mail desse usuário em user_profiles.")
                                    else:
                                        rr = _safe_send_recovery_email(supabase_admin, email_m)
                                        if rr.get("ok"):
                                            ux.ok("✅ Link de recuperação enviado!")
                                        else:
                                            st.error(f"Falha ao enviar: {rr.get('error')}")

                            with c2:
                                temp = st.text_input("Definir senha temporária", type="password", key=f"temp_{uid_m}")
                                if st.button("Salvar senha temporária", key=f"setpass_{uid_m}", use_container_width=True):
                                    if not temp or len(temp) < 8:
                                        st.error("A senha precisa ter pelo menos 8 caracteres.")
                                    else:
                                        rr = _safe_set_temp_password(supabase_admin, uid_m, temp)
                                        if rr.get("ok"):
                                            ux.ok("✅ Senha atualizada via Admin API.")
                                        else:
                                            st.error(f"Falha: {rr.get('error')}")
            except Exception as e:
                st.error(f"Erro ao listar membros: {e}")
