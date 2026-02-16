from __future__ import annotations

import base64
import json
import mimetypes
from typing import Optional

import requests
import streamlit as st


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


def _storage_headers() -> dict:
    url = st.secrets.get("SUPABASE_URL")
    anon = st.secrets.get("SUPABASE_ANON_KEY")
    token = st.session_state.get("auth_access_token")

    if not url or not anon:
        raise RuntimeError("Faltam SUPABASE_URL / SUPABASE_ANON_KEY em st.secrets.")
    if not token:
        raise RuntimeError("Sem auth_access_token na sessão (usuário não autenticado).")

    return {"Authorization": f"Bearer {token}", "apikey": anon}


def _base_url() -> str:
    return str(st.secrets.get("SUPABASE_URL")).rstrip("/")


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


def _get_empresa_atual() -> str | None:
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

    return None


def exibir_perfil(supabase_db):
    DEBUG = str(st.secrets.get("DEBUG", "false")).lower() in ("1", "true", "yes", "y")

    token = st.session_state.get("auth_access_token")
    uid = _jwt_sub(token)

    usuario = st.session_state.get("usuario") or {}
    user_id = uid or usuario.get("id") or st.session_state.get("auth_user_id")
    if not user_id:
        st.error("Não foi possível identificar o usuário logado.")
        return

    if isinstance(st.session_state.get("usuario"), dict):
        st.session_state.usuario["id"] = user_id

    email = usuario.get("email") or st.session_state.get("auth_email") or "—"
    nome_sessao = usuario.get("nome") or "—"
    role = (usuario.get("perfil") or "user").upper()

    try:
        prof = (
            supabase_db.table("user_profiles")
            .select("user_id,email,nome,avatar_path,avatar_url")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        profile_row = (prof.data or {}) if hasattr(prof, "data") else (prof.get("data") or {})
    except Exception:
        profile_row = {}

    nome_db = profile_row.get("nome") or nome_sessao
    avatar_path = profile_row.get("avatar_path") or usuario.get("avatar_path") or f"{user_id}/avatar.png"

    st.markdown("## 👤 Meu Perfil")
    empresa = _get_empresa_atual()

    avatar_bytes = _get_object_bytes_authenticated("avatars", avatar_path) if avatar_path else None

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
        st.caption("🔒 Avatar em bucket privado (upload REST + leitura authenticated).")

    tabs = st.tabs(["📝 Perfil", "🖼 Avatar", "🔐 Segurança"])

    # ---- Perfil ----
    with tabs[0]:
        st.subheader("📝 Dados do perfil")
        novo_nome = st.text_input("Nome", value=nome_db or "", placeholder="Seu nome completo", key="perfil_nome_input")

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

    # ---- Avatar ----
    with tabs[1]:
        st.subheader("🖼 Avatar")

        if "avatar_uploader_key" not in st.session_state:
            st.session_state.avatar_uploader_key = 0

        arquivo = st.file_uploader(
            "Escolher imagem (PNG/JPG)",
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
            mime = arquivo.type or mimetypes.guess_type(arquivo.name)[0] or "image/png"
            ext = "png"
            if "jpeg" in mime or arquivo.name.lower().endswith((".jpg", ".jpeg")):
                ext = "jpg"

            object_path = f"{user_id}/avatar.{ext}"
            file_bytes = arquivo.getvalue()

            try:
                _upload_object_rest("avatars", object_path, file_bytes, mime)
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
                _delete_object_rest("avatars", f"{user_id}/avatar.png")
                _delete_object_rest("avatars", f"{user_id}/avatar.jpg")
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

    # ---- Segurança ----
    with tabs[2]:
        st.subheader("🔐 Segurança")
        st.caption("Ações rápidas da conta.")

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("🚪 Sair", use_container_width=True, key="perfil_logout_btn"):
                for k in [
                    "auth_access_token",
                    "auth_refresh_token",
                    "auth_user_id",
                    "auth_email",
                    "usuario",
                    "token",
                ]:
                    if k in st.session_state:
                        del st.session_state[k]
                st.success("Você saiu da conta.")
                st.rerun()

        with col2:
            st.info("Posso adicionar aqui o botão “Enviar link de troca de senha” (depende do seu fluxo de auth).")

    if DEBUG:
        with st.expander("🧪 Debug (interno)", expanded=False):
            st.write("user_id:", user_id)
            st.write("avatar_path:", avatar_path)
            st.write("empresa:", empresa)
