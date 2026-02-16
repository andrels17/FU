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
    anon = st.secrets.get("SUPABASE_ANON_KEY")
    token = st.session_state.get("auth_access_token")

    if not st.secrets.get("SUPABASE_URL") or not anon:
        raise RuntimeError("Faltam SUPABASE_URL / SUPABASE_ANON_KEY em st.secrets.")
    if not token:
        raise RuntimeError("Sem auth_access_token na sessão (usuário não autenticado).")

    return {"Authorization": f"Bearer {token}", "apikey": anon}


def _upload_object_rest(bucket: str, object_path: str, data: bytes, mime: str) -> None:
    base_url = st.secrets.get("SUPABASE_URL").rstrip("/")
    headers = _storage_headers()
    headers.update({"Content-Type": mime, "x-upsert": "true", "Accept": "application/json"})

    safe_path = requests.utils.requote_uri(object_path)
    url = f"{base_url}/storage/v1/object/{bucket}/{safe_path}"

    # PUT costuma ser o método mais compatível
    r1 = requests.put(url, headers=headers, data=data, timeout=60)
    if r1.status_code in (200, 201):
        return

    # fallback POST
    r2 = requests.post(url, headers=headers, data=data, timeout=60)
    if r2.status_code in (200, 201):
        return

    body = (r2.text or r1.text or "")[:500]
    raise RuntimeError(f"Storage upload falhou (PUT={r1.status_code}, POST={r2.status_code}): {body}")


def _get_object_bytes_authenticated(bucket: str, object_path: str) -> Optional[bytes]:
    """Baixa objeto de bucket privado usando endpoint authenticated + Bearer token."""
    base_url = st.secrets.get("SUPABASE_URL").rstrip("/")
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


def exibir_perfil(supabase_db):
    """Meu Perfil (bucket privado) — upload REST + leitura via endpoint authenticated.

    Motivo: evita problemas de signed URL e CORS/preview no browser.
    """
    token = st.session_state.get("auth_access_token")
    uid = _jwt_sub(token)

    usuario = st.session_state.get("usuario") or {}
    user_id = uid or usuario.get("id") or st.session_state.get("auth_user_id")
    email = usuario.get("email") or st.session_state.get("auth_email")
    nome = usuario.get("nome") or "—"
    perfil = (usuario.get("perfil") or "user").upper()

    if not user_id:
        st.error("Não foi possível identificar o usuário logado.")
        return

    if isinstance(st.session_state.get("usuario"), dict):
        st.session_state.usuario["id"] = user_id

    st.title("👤 Meu Perfil")

    avatar_path = usuario.get("avatar_path") or f"{user_id}/avatar.png"
    avatar_bytes = _get_object_bytes_authenticated("avatars", avatar_path)

    c1, c2 = st.columns([1, 2])
    with c1:
        if avatar_bytes:
            st.image(avatar_bytes, width=140)
        else:
            inicial = (nome[:1] or "U").upper()
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
        st.markdown(f"**Nome:** {nome}")
        st.markdown(f"**Email:** {email}")
        st.markdown(f"**Perfil:** {perfil}")
        st.caption("🔒 Avatar em bucket privado (upload REST + leitura authenticated).")

    with st.expander("🧪 Debug Avatar (authenticated endpoint)", expanded=False):
        st.write("avatar_path:", avatar_path)
        base_url = st.secrets.get("SUPABASE_URL").rstrip("/")
        url_dbg = f"{base_url}/storage/v1/object/authenticated/avatars/{requests.utils.requote_uri(avatar_path)}"
        st.write("GET url:", url_dbg)
        try:
            r = requests.get(url_dbg, headers=_storage_headers(), timeout=10)
            st.write("GET status:", r.status_code)
            st.write("Content-Type:", r.headers.get("content-type"))
            st.write("Bytes:", len(r.content or b""))
        except Exception as e:
            st.write("GET erro:", str(e))

    st.divider()
    st.subheader("🖼 Atualizar avatar")
    st.caption("Envie PNG/JPG. O arquivo será salvo em: avatars/<user_id>/avatar.ext (privado).")

    if "avatar_uploader_key" not in st.session_state:
        st.session_state.avatar_uploader_key = 0

    arquivo = st.file_uploader(
        "Escolher imagem",
        type=["png", "jpg", "jpeg"],
        key=f"avatar_uploader_{st.session_state.avatar_uploader_key}",
    )

    salvar = st.button("💾 Salvar avatar", use_container_width=True, disabled=arquivo is None)

    if not salvar:
        return
    if arquivo is None:
        st.warning("Selecione uma imagem antes de salvar.")
        return

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
        return

    try:
        supabase_db.table("user_profiles").update({"avatar_path": object_path}).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Avatar enviado, mas falhou ao salvar no perfil: {e}")
        return

    st.session_state.usuario["avatar_path"] = object_path
    st.session_state.avatar_uploader_key += 1
    st.success("✅ Avatar atualizado!")
    st.rerun()
