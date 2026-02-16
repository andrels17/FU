from __future__ import annotations

import base64
import json
import mimetypes
from typing import Optional, Dict, Any, List

import requests
import streamlit as st



# =========================
# Helpers UI / Formatting
# =========================
def _fmt_dt_br(x) -> str:
    """Formata datas para dd/mm/aaaa (best-effort)."""
    if not x:
        return ""
    try:
        from datetime import datetime
        s = str(x).strip()
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        # fallback simples
        s = str(x)
        return s

def _fmt_money_br(v) -> str:
    try:
        if v is None or v == "":
            return ""
        x = float(v)
        s = f"{x:,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(v) if v is not None else ""

def _status_pill(status: str) -> str:
    """Pill simples (HTML) para status."""
    s = "" if status is None else str(status)
    s0 = s.strip().lower()
    cls = "neutral"
    if s0 in ["entregue", "entregues", "finalizado", "concluído", "concluido", "encerrado", "tem oc", "com oc"]:
        cls = "green"
    elif s0 in ["em transporte", "transporte", "vencendo"]:
        cls = "orange"
    elif s0 in ["atrasado", "vencido", "em atraso", "crítico", "critico"]:
        cls = "red"
    elif s0 in ["em aberto", "aberto", "pendente", "em andamento", "sem oc", "sem pedido", "sem oc/sol", "sem oc/solicitação"]:
        cls = "yellow"
    return f'<span class="fu-pill fu-pill-{cls}">{s or "—"}</span>'
# =========================
# Helpers Auth / Headers
# =========================
def _jwt_sub(token: str | None) -> str | None:
    if not token or token.count(".") < 2:
        return None
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))
        return payload.get("sub")
    except Exception:
        return None


def _base_url() -> str:
    return str(st.secrets.get("SUPABASE_URL", "")).rstrip("/")


def _anon_key() -> str:
    return str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()


def _access_token() -> str:
    return str(st.session_state.get("auth_access_token", "")).strip()


def _storage_headers() -> dict:
    url = _base_url()
    anon = _anon_key()
    token = _access_token()

    if not url or not anon:
        raise RuntimeError("Faltam SUPABASE_URL / SUPABASE_ANON_KEY em st.secrets.")
    if not token:
        raise RuntimeError("Sem auth_access_token na sessão (usuário não autenticado).")

    return {"Authorization": f"Bearer {token}", "apikey": anon}


def _auth_headers() -> dict:
    anon = _anon_key()
    if not anon:
        raise RuntimeError("Falta SUPABASE_ANON_KEY em st.secrets.")
    h = {"apikey": anon, "Content-Type": "application/json"}
    tok = _access_token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _get_empresa_atual() -> str | None:
    # Preferência: chaves legadas
    for k in ("empresa", "empresa_selecionada", "empresa_atual", "empresa_nome"):
        v = st.session_state.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    for k in ("empresa", "empresa_selecionada", "empresa_atual"):
        v = st.session_state.get(k)
        if isinstance(v, dict):
            for kk in ("nome", "name", "razao_social"):
                nv = v.get(kk)
                if isinstance(nv, str) and nv.strip():
                    return nv.strip()

    # Fallback: tenant (SaaS)
    tid = st.session_state.get("tenant_id")
    opts = st.session_state.get("tenant_options", []) or []
    if tid and isinstance(opts, list):
        for t in opts:
            try:
                if isinstance(t, dict) and t.get("tenant_id") == tid:
                    nome = t.get("nome") or t.get("name") or t.get("razao_social")
                    if isinstance(nome, str) and nome.strip():
                        return nome.strip()
                    return str(tid)
            except Exception:
                continue
        return str(tid)

    return None


# =========================
# Storage REST (Privado)
# =========================
def _upload_object_rest(bucket: str, object_path: str, data: bytes, mime: str) -> None:
    base_url = _base_url()
    headers = _storage_headers()
    headers.update({"Content-Type": mime, "x-upsert": "true", "Accept": "application/json"})

    safe_path = requests.utils.requote_uri(object_path)
    url = f"{base_url}/storage/v1/object/{bucket}/{safe_path}"

    r1 = requests.put(url, headers=headers, data=data, timeout=60)
    if r1.status_code in (200, 201):
        return

    r2 = requests.post(url, headers=headers, data=data, timeout=60)
    if r2.status_code in (200, 201):
        return

    body = (r2.text or r1.text or "")[:800]
    raise RuntimeError(f"Storage upload falhou (PUT={r1.status_code}, POST={r2.status_code}): {body}")


def _delete_object_rest(bucket: str, object_path: str) -> None:
    base_url = _base_url()
    headers = _storage_headers()
    headers.update({"Accept": "application/json"})

    safe_path = requests.utils.requote_uri(object_path)
    url = f"{base_url}/storage/v1/object/{bucket}/{safe_path}"

    r = requests.delete(url, headers=headers, timeout=30)

    if r.status_code in (200, 204, 404):
        return

    # Alguns ambientes devolvem 400 com JSON dizendo 404 (Object not found)
    try:
        payload = r.json()
        status_code = str(payload.get("statusCode", "")).strip()
        err = str(payload.get("error", "")).strip().lower()
        msg = str(payload.get("message", "")).strip().lower()
        if status_code == "404" or err == "not_found" or "object not found" in msg:
            return
    except Exception:
        pass

    body = (r.text or "")[:800]
    raise RuntimeError(f"Storage delete falhou ({r.status_code}): {body}")


def _get_object_bytes_authenticated(bucket: str, object_path: str) -> Optional[bytes]:
    base_url = _base_url()
    headers = _storage_headers()

    safe_path = requests.utils.requote_uri(object_path)
    url = f"{base_url}/storage/v1/object/authenticated/{bucket}/{safe_path}"

    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200 and r.content:
            return r.content
        return None
    except Exception:
        return None


# =========================
# Supabase Auth REST extras
# =========================
def _send_password_recovery(email: str) -> None:
    """Envia email de recuperação de senha (Supabase Auth)."""
    base_url = _base_url()
    if not base_url:
        raise RuntimeError("SUPABASE_URL não configurada.")
    if not email or "@" not in email:
        raise RuntimeError("Email inválido para recuperação.")

    url = f"{base_url}/auth/v1/recover"
    resp = requests.post(url, headers=_auth_headers(), json={"email": email}, timeout=30)
    if resp.status_code in (200, 204):
        return

    body = (resp.text or "")[:800]
    raise RuntimeError(f"Falha ao enviar recuperação ({resp.status_code}): {body}")


def _change_password(new_password: str) -> None:
    """Troca senha do usuário logado via endpoint /auth/v1/user."""
    base_url = _base_url()
    if not base_url:
        raise RuntimeError("SUPABASE_URL não configurada.")
    if not new_password or len(new_password) < 8:
        raise RuntimeError("A senha deve ter pelo menos 8 caracteres.")

    url = f"{base_url}/auth/v1/user"
    resp = requests.put(url, headers=_auth_headers(), json={"password": new_password}, timeout=30)
    if resp.status_code in (200, 204):
        return

    body = (resp.text or "")[:800]
    raise RuntimeError(f"Falha ao trocar senha ({resp.status_code}): {body}")


# =========================
# DB helpers (tolerantes)
# =========================
def _safe_get_profile(supabase_db, user_id: str) -> Dict[str, Any]:
    try:
        res = (
            supabase_db.table("user_profiles")
            .select("user_id,email,nome,avatar_path,avatar_url")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if hasattr(res, "data"):
            return res.data or {}
        return res.get("data") or {}
    except Exception:
        return {}


def _safe_stats_pedidos(supabase_db, user_id: str) -> Dict[str, int]:
    stats: Dict[str, int] = {}

    # Total
    try:
        r = supabase_db.table("pedidos").select("id", count="exact").eq("criado_por", user_id).execute()
        total = getattr(r, "count", None)
        if total is None and isinstance(r, dict):
            total = r.get("count")
        if total is not None:
            stats["Meus pedidos"] = int(total)
    except Exception:
        pass

    # Em aberto (tentativa)
    try:
        r = (
            supabase_db.table("pedidos")
            .select("id", count="exact")
            .eq("criado_por", user_id)
            .not_.in_("status", ["Concluído", "Finalizado", "Cancelado"])
            .execute()
        )
        total = getattr(r, "count", None)
        if total is None and isinstance(r, dict):
            total = r.get("count")
        if total is not None:
            stats["Em aberto"] = int(total)
    except Exception:
        pass

    return stats


def _safe_last_pedidos(supabase_db, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Tenta buscar os últimos pedidos do usuário.

    Faz best-effort com diferentes nomes de colunas comuns.
    """
    # seleção ampla; se alguma coluna não existir, pode falhar -> cai no except e tenta outra seleção
    selections = [
        "id,numero,status,departamento,criado_em,atualizado_em,descricao,valor_total",
        "id,status,departamento,criado_em,descricao,valor_total",
        "id,status,criado_em,descricao",
        "id,criado_em",
    ]

    for sel in selections:
        try:
            q = supabase_db.table("pedidos").select(sel).eq("criado_por", user_id)
            # tenta ordenar por atualizado_em, senão criado_em
            try:
                q = q.order("atualizado_em", desc=True)
            except Exception:
                q = q.order("criado_em", desc=True)
            res = q.limit(limit).execute()
            data = getattr(res, "data", None)
            if data is None and isinstance(res, dict):
                data = res.get("data")
            return data or []
        except Exception:
            continue
    return []


def _logout_clear_session():
    for k in [
        "auth_access_token",
        "auth_refresh_token",
        "auth_user_id",
        "auth_email",
        "usuario",
        "token",
        "menu_ops",
        "menu_gestao",
    ]:
        if k in st.session_state:
            del st.session_state[k]


# =========================
# UI
# =========================
def exibir_perfil(supabase_db):
    """Aba Meu Perfil (v3)."""
    DEBUG = str(st.secrets.get("DEBUG", "false")).lower() in ("1", "true", "yes", "y")

    # CSS leve (pills / compacto)
    st.markdown("""
    <style>
      .fu-pill{display:inline-block; padding:2px 10px; border-radius:999px; font-size:.78rem; font-weight:700;
              border:1px solid rgba(255,255,255,.10);}
      .fu-pill-green{background:rgba(46,204,113,.18); color:rgba(46,204,113,1);}
      .fu-pill-yellow{background:rgba(241,196,15,.18); color:rgba(241,196,15,1);}
      .fu-pill-red{background:rgba(231,76,60,.18); color:rgba(231,76,60,1);}
      .fu-pill-orange{background:rgba(230,126,34,.18); color:rgba(230,126,34,1);}
      .fu-pill-neutral{background:rgba(255,255,255,.07); color:rgba(255,255,255,.82);}
    </style>
    """, unsafe_allow_html=True)

    uid = _jwt_sub(st.session_state.get("auth_access_token"))
    usuario = st.session_state.get("usuario") or {}
    user_id = uid or usuario.get("id") or st.session_state.get("auth_user_id")

    if not user_id:
        st.error("Não foi possível identificar o usuário logado.")
        return

    if isinstance(st.session_state.get("usuario"), dict):
        st.session_state.usuario["id"] = user_id

    profile_row = _safe_get_profile(supabase_db, user_id)

    email = (profile_row.get("email") or usuario.get("email") or st.session_state.get("auth_email") or "—").strip()
    nome_db = (profile_row.get("nome") or usuario.get("nome") or "—").strip()
    role = (usuario.get("perfil") or "user").upper()
    empresa = _get_empresa_atual()

    avatar_path = profile_row.get("avatar_path") or usuario.get("avatar_path") or f"{user_id}/avatar.png"
    avatar_bytes = _get_object_bytes_authenticated("avatars", avatar_path) if avatar_path else None

    # Header
    st.markdown("## 👤 Meu Perfil")
    c1, c2 = st.columns([1, 2])

    with c1:
        if avatar_bytes:
            st.image(avatar_bytes, width=140)
        else:
            inicial = (str(nome_db)[:1] or "U").upper()
            st.markdown(
                f"""
                <div style="
                    width:140px;height:140px;border-radius:50%;
                    background:linear-gradient(135deg,#f59e0b,#3b82f6);
                    display:flex;align-items:center;justify-content:center;
                    font-size:54px;font-weight:900;color:white;">
                    {inicial}
                </div>
                """,
                unsafe_allow_html=True,
            )

    with c2:
        st.markdown(f"**Nome:** {nome_db}")
        st.markdown(f"**Email:** {email}")
        st.markdown(f"**Perfil:** {role}")
        if empresa:
            st.markdown(f"**Empresa:** {empresa}")
        st.caption("🔒 Avatar em bucket privado (REST + leitura authenticated).")

        col_h1, col_h2, col_h3 = st.columns([1, 1, 1])
        with col_h1:
            st.code(user_id, language="text")
        with col_h2:
            if st.button("🔄 Atualizar", key="perfil_refresh_btn", use_container_width=True):
                st.rerun()
        with col_h3:
            if st.button("🚪 Sair", key="perfil_logout_btn_header", use_container_width=True):
                _logout_clear_session()
                st.success("Você saiu da conta.")
                st.rerun()

    # KPIs (se conseguir)
    stats = _safe_stats_pedidos(supabase_db, user_id)
    if stats:
        cols = st.columns(min(4, len(stats)))
        for i, (k, v) in enumerate(stats.items()):
            cols[i % len(cols)].metric(k, v)

    tabs = st.tabs(["🏠 Visão geral", "📝 Perfil", "🖼 Avatar", "🔐 Segurança"])

    # =========================
    # Tab: Visão Geral
    # =========================
    with tabs[0]:
        st.subheader("🏠 Visão geral")
        st.caption("Resumo da sua conta e atalhos.")

        cA, cB, cC = st.columns([1, 1, 1])
        with cA:
            st.info("💡 Dica: personalize seu nome e avatar para aparecerem na sidebar.")
        with cB:
            st.success("✅ Sessão ativa")
            st.caption(f"User ID: `{user_id}`")
        with cC:
            st.warning("🏢 Empresa")
            st.caption(empresa or "Nenhuma selecionada (se aplicável).")

        st.divider()
        st.markdown("### 🧾 Meus últimos pedidos")
        last = _safe_last_pedidos(supabase_db, user_id, limit=5)
        if not last:
            st.caption("Nenhum pedido encontrado (ou não foi possível ler a tabela/colunas).")
        else:
            st.caption("Clique em **Abrir** para ir direto para a aba de ações do pedido.")
            # Render compacto (lista ERP) com ação
            for p in last:
                pid = p.get("id")
                numero = p.get("numero") or ""
                status = p.get("status") or ""
                depto = p.get("departamento") or ""
                descricao = (p.get("descricao") or "").strip()
                criado_em = _fmt_dt_br(p.get("criado_em"))
                valor = _fmt_money_br(p.get("valor_total"))

                cA, cB, cC, cD, cE, cF = st.columns([0.9, 2.6, 1.2, 1.1, 1.1, 1.0])
                with cA:
                    if st.button("🔎 Abrir", key=f"perfil_open_{pid}", use_container_width=True):
                        # Navega para Consulta > Ações
                        st.session_state["current_page"] = "Consultar Pedidos"
                        st.session_state["_force_menu_sync"] = True
                        st.session_state["consulta_selected_pid"] = str(pid or "")
                        st.session_state["consulta_tab_target"] = "⚡ Ações"
                        st.rerun()
                with cB:
                    # Mostra a descrição do material (quando existir) em vez do ID
                    if descricao:
                        short = descricao if len(descricao) <= 60 else (descricao[:57] + "…")
                        st.markdown(f"**{short}**")
                        if numero:
                            st.caption(f"Material · Nº {numero}")
                        else:
                            st.caption("Material")
                    else:
                        st.markdown(f"**{numero or str(pid)[:8]}**")
                        st.caption("Nº" if numero else "ID")
                with cC:
                    st.markdown(_status_pill(status), unsafe_allow_html=True)
                    st.caption("Status")
                with cD:
                    st.write(depto or "—")
                    st.caption("Depto")
                with cE:
                    st.write(criado_em or "—")
                    st.caption("Criado")
                with cF:
                    st.write(valor or "—")
                    st.caption("Valor")

                # linha suave
                st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)

        st.divider()
        st.markdown("### 📦 Exportar meus dados")
        st.caption("Baixa um JSON com os dados básicos do seu perfil (sem informações sensíveis).")

        export_obj = {
            "user_id": user_id,
            "email": email,
            "nome": nome_db,
            "perfil": role,
            "empresa": empresa,
            "avatar_path": avatar_path if avatar_path else None,
        }
        st.download_button(
            "⬇️ Baixar JSON do perfil",
            data=json.dumps(export_obj, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="meu_perfil.json",
            mime="application/json",
            key="perfil_download_json_btn",
            use_container_width=True,
        )

    # =========================
    # Tab: Perfil
    # =========================
    with tabs[1]:
        st.subheader("📝 Dados do perfil")
        novo_nome = st.text_input(
            "Nome",
            value=nome_db or "",
            placeholder="Seu nome completo",
            key="perfil_nome_input",
        )

        col_a, col_b = st.columns([1, 3])
        with col_a:
            salvar_nome = st.button("💾 Salvar dados", use_container_width=True, key="perfil_salvar_dados_btn")
        with col_b:
            st.caption("Atualiza apenas o nome (sem campos extras).")

        if salvar_nome:
            nn = (novo_nome or "").strip()
            if not nn:
                st.warning("Informe um nome válido.")
            else:
                try:
                    supabase_db.table("user_profiles").update({"nome": nn}).eq("user_id", user_id).execute()
                    if isinstance(st.session_state.get("usuario"), dict):
                        st.session_state.usuario["nome"] = nn
                    st.success("✅ Perfil atualizado!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Falha ao salvar: {e}")

    # =========================
    # Tab: Avatar
    # =========================
    with tabs[2]:
        st.subheader("🖼 Avatar")
        st.caption("Use PNG/JPG. O arquivo fica em `avatars/<user_id>/avatar.ext` (privado).")

        if "avatar_uploader_key" not in st.session_state:
            st.session_state.avatar_uploader_key = 0

        arquivo = st.file_uploader(
            "Escolher imagem",
            type=["png", "jpg", "jpeg"],
            key=f"perfil_avatar_uploader_{st.session_state.avatar_uploader_key}",
        )

        if arquivo is not None:
            st.caption("Pré-visualização:")
            st.image(arquivo.getvalue(), width=180)

        b1, b2 = st.columns([1, 1])
        with b1:
            salvar_avatar = st.button(
                "💾 Salvar avatar",
                use_container_width=True,
                disabled=arquivo is None,
                key="perfil_salvar_avatar_btn",
            )
        with b2:
            remover_avatar = st.button(
                "🗑️ Remover avatar",
                use_container_width=True,
                disabled=not bool(avatar_bytes),
                key="perfil_remover_avatar_btn",
            )

        if salvar_avatar:
            raw = arquivo.getvalue()
            if len(raw) > 2 * 1024 * 1024:
                st.error("A imagem é muito grande. Limite: 2MB.")
                st.stop()

            mime = arquivo.type or mimetypes.guess_type(arquivo.name)[0] or "image/png"
            ext = "png"
            if "jpeg" in mime or arquivo.name.lower().endswith((".jpg", ".jpeg")):
                ext = "jpg"

            object_path = f"{user_id}/avatar.{ext}"

            try:
                _upload_object_rest("avatars", object_path, raw, mime)
            except Exception as e:
                st.error(f"Erro ao enviar para o Storage: {e}")
                st.stop()

            try:
                supabase_db.table("user_profiles").update({"avatar_path": object_path}).eq("user_id", user_id).execute()
            except Exception as e:
                st.error(f"Avatar enviado, mas falhou ao salvar no perfil: {e}")
                st.stop()

            if isinstance(st.session_state.get("usuario"), dict):
                st.session_state.usuario["avatar_path"] = object_path

            st.session_state.avatar_uploader_key += 1
            st.success("✅ Avatar atualizado!")
            st.rerun()

        if remover_avatar:
            try:
                if avatar_path:
                    _delete_object_rest("avatars", avatar_path)
            except Exception as e:
                st.error(f"Falha ao remover no Storage: {e}")
                st.stop()

            try:
                supabase_db.table("user_profiles").update({"avatar_path": None}).eq("user_id", user_id).execute()
            except Exception as e:
                st.error(f"Removeu do Storage, mas falhou ao limpar no perfil: {e}")
                st.stop()

            if isinstance(st.session_state.get("usuario"), dict):
                st.session_state.usuario["avatar_path"] = None

            st.success("✅ Avatar removido!")
            st.rerun()

    # =========================
    # Tab: Segurança
    # =========================
    with tabs[3]:
        st.subheader("🔐 Segurança")
        st.caption("Ações rápidas da conta.")

        st.markdown("### 🔁 Trocar senha (logado)")
        cP1, cP2 = st.columns([1, 1])
        with cP1:
            nova = st.text_input("Nova senha", type="password", key="perfil_nova_senha")
        with cP2:
            confirmar = st.text_input("Confirmar nova senha", type="password", key="perfil_confirmar_senha")

        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            if st.button("✅ Trocar senha", use_container_width=True, key="perfil_trocar_senha_btn"):
                if not nova or len(nova) < 8:
                    st.error("A senha deve ter pelo menos 8 caracteres.")
                elif nova != confirmar:
                    st.error("A confirmação não confere.")
                else:
                    try:
                        _change_password(nova)
                        st.success("✅ Senha atualizada!")
                        st.caption("Se você usa regras de senha no Supabase, elas podem exigir complexidade.")
                    except Exception as e:
                        st.error(f"Falha ao trocar senha: {e}")

        with col_btn2:
            if st.button("🚪 Sair", use_container_width=True, key="perfil_logout_btn_security"):
                _logout_clear_session()
                st.success("Você saiu da conta.")
                st.rerun()

        st.divider()
        st.markdown("### 📩 Recuperação por email")
        st.caption("Envia um link para redefinir senha (útil se preferir fluxo por email).")
        if st.button("📩 Enviar link de redefinição", use_container_width=True, key="perfil_recover_btn"):
            try:
                _send_password_recovery(email)
                st.success("✅ Link enviado! Verifique seu email.")
                st.caption("Se não chegar, verifique Spam e as Redirect URLs no Supabase Auth.")
            except Exception as e:
                st.error(f"Falha ao enviar: {e}")

        st.divider()
        st.markdown("### ℹ️ Informações")
        st.write(f"**User ID:** `{user_id}`")
        st.write(f"**Email:** `{email}`")

    if DEBUG:
        with st.expander("🧪 Debug (interno)", expanded=False):
            st.write("empresa:", empresa)
            st.write("avatar_path:", avatar_path)
            st.write("has_avatar_bytes:", bool(avatar_bytes))
