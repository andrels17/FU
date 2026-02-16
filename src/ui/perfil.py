from __future__ import annotations

import base64
import json
import mimetypes
from typing import Optional

import requests
import streamlit as st


def _jwt_sub(token: str | None) -> str | None:
    """Extrai o 'sub' do JWT (sem validar assinatura)."""
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
        raise RuntimeError("Sem auth_access_token na sessão (usuário não autenticado)." কাম)

    return {
        "Authorization": f"Bearer {token}",
        "apikey": anon,
    }


def _upload_object_rest(bucket: str, object_path: str, data: bytes, mime: str) -> None:
    """Upload via REST (garante Authorization no Storage).

    - Usa POST /storage/v1/object/<bucket>/<path>
    - upsert via header x-upsert: true
    """
    base_url = st.secrets.get("SUPABASE_URL")
    headers = _storage_headers()
    headers.update(
        {
            "Content-Type": mime,
            "x-upsert": "true",
        }
    )

    url = f"{base_url}/storage/v1/object/{bucket}/{object_path}"
    resp = requests.post(url, headers=headers, data=data, timeout=60)

    if resp.status_code not in (200, 201):
        # retorna corpo para você ver exatamente a causa
        raise RuntimeError(f"Storage upload falhou ({resp.status_code}): {resp.text}")


def _signed_url_rest(bucket: str, object_path: str, expires_in: int = 3600) -> Optional[str]:
    """Gera signed URL via REST para bucket privado.

    Endpoint: POST /storage/v1/object/sign/<bucket>/<path>
    Body: {"expiresIn": 3600}
    """
    base_url = st.secrets.get("SUPABASE_URL")
    headers = _storage_headers()
    headers.update({"Content-Type": "application/json"})

    url = f"{base_url}/storage/v1/object/sign/{bucket}/{object_path}"
    resp = requests.post(url, headers=headers, json={"expiresIn": int(expires_in)}, timeout=30)

    if resp.status_code == 404:
        return None  # arquivo ainda não existe
    if resp.status_code not in (200, 201):
        return None

    try:
        payload = resp.json()
    except Exception:
        return None

    signed = payload.get("signedURL") or payload.get("signedUrl") or payload.get("signed_url") or payload.get("url")
    if not signed:
        return None

    # O endpoint geralmente retorna uma URL relativa. Garantimos absoluta:
    if signed.startswith("/"):
        return f"{base_url}{signed}"
    if signed.startswith("http"):
        return signed
    return f"{base_url}/{signed.lstrip('/')}"


def exibir_perfil(supabase_db):
    """Meu Perfil (bucket privado + upload REST + signed URL REST)."""
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

    # Mantém session_state alinhado
    if isinstance(st.session_state.get("usuario"), dict):
        st.session_state.usuario["id"] = user_id

    st.title("👤 Meu Perfil")

    avatar_path = usuario.get("avatar_path") or f"{user_id}/avatar.png"
    avatar_display_url = _signed_url_rest("avatars", avatar_path, expires_in=3600) if avatar_path else None

    c1, c2 = st.columns([1, 2])
    with c1:
        if avatar_display_url:
            st.image(avatar_display_url, width=140)
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
        st.caption("🔒 Avatar em bucket privado (upload REST + signed URL).")


    st.divider()
    st.subheader("🖼 Atualizar avatar")
    st.caption("Envie PNG/JPG. O arquivo será salvo em: avatars/<user_id>/avatar.ext (privado).")


    arquivo = st.file_uploader("Escolher imagem", type=["png", "jpg", "jpeg"])
    if arquivo is None:
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
        st.stop()

    # Persiste o PATH no user_profiles
    try:
        supabase_db.table("user_profiles").update({"avatar_path": object_path}).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Avatar enviado, mas falhou ao salvar no perfil: {e}")
        st.stop()

    st.session_state.usuario["avatar_path"] = object_path
    st.success("✅ Avatar atualizado!")
    st.rerun()
