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
        raise RuntimeError("Sem auth_access_token na sessão (usuário não autenticado)." )

    return {
        "Authorization": f"Bearer {token}",
        "apikey": anon,
    }


def _upload_object_rest(bucket: str, object_path: str, data: bytes, mime: str) -> None:
    """Upload via REST (garante Authorization no Storage)."""
    base_url = st.secrets.get("SUPABASE_URL")
    headers = _storage_headers()
    headers.update({"Content-Type": mime, "x-upsert": "true"})

    url = f"{base_url}/storage/v1/object/{bucket}/{object_path}"
    resp = requests.post(url, headers=headers, data=data, timeout=60)

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Storage upload falhou ({resp.status_code}): {resp.text}")


def _signed_url_rest(bucket: str, object_path: str, expires_in: int = 3600) -> Optional[str]:
    """Signed URL via REST para bucket privado."""
    base_url = st.secrets.get("SUPABASE_URL")
    headers = _storage_headers()
    headers.update({"Content-Type": "application/json"})

    url = f"{base_url}/storage/v1/object/sign/{bucket}/{object_path}"
    resp = requests.post(url, headers=headers, json={"expiresIn": int(expires_in)}, timeout=30)

    if resp.status_code == 404:
        return None
    if resp.status_code not in (200, 201):
        return None

    try:
        payload = resp.json()
    except Exception:
        return None

    signed = payload.get("signedURL") or payload.get("signedUrl") or payload.get("signed_url") or payload.get("url")
    if not signed:
        return None

    # Normalmente vem como URL relativa (/storage/v1/...)
    if signed.startswith("/"):
        return f"{base_url}{signed}"
    if signed.startswith("http"):
        return signed
    return f"{base_url}/{signed.lstrip('/')}"


def exibir_perfil(supabase_db):
    """Meu Perfil (bucket privado + upload REST + signed URL REST).

    IMPORTANTE:
    - O upload NÃO deve rodar automaticamente a cada rerun (file_uploader mantém o arquivo).
    - Por isso usamos um botão "Salvar avatar" + key dinâmica para limpar o uploader após sucesso.
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


    # --- Exibição do avatar atual ---
    avatar_path = usuario.get("avatar_path") or f"{user_id}/avatar.png"

    # cache curto para evitar múltiplas chamadas
    if st.session_state.get("_avatar_signed_for") == avatar_path and st.session_state.get("_avatar_signed_url"):
        avatar_display_url = st.session_state.get("_avatar_signed_url")
    else:
        avatar_display_url = _signed_url_rest("avatars", avatar_path, expires_in=3600)
        st.session_state["_avatar_signed_for"] = avatar_path
        st.session_state["_avatar_signed_url"] = avatar_display_url

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


    if "avatar_uploader_key" not in st.session_state:
        st.session_state.avatar_uploader_key = 0

    arquivo = st.file_uploader(
        "Escolher imagem",
        type=["png", "jpg", "jpeg"],
        key=f"avatar_uploader_{st.session_state.avatar_uploader_key}",
    )

    col_a, col_b = st.columns([1, 3])
    with col_a:
        salvar = st.button("💾 Salvar avatar", use_container_width=True, disabled=arquivo is None)

    with col_b:
        st.caption("Dica: clique em **Salvar avatar** após escolher a imagem (evita loop de rerun).")


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

    # Persiste o PATH no user_profiles
    try:
        supabase_db.table("user_profiles").update({"avatar_path": object_path}).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Avatar enviado, mas falhou ao salvar no perfil: {e}")
        return

    # Atualiza sessão e limpa cache do signed url
    st.session_state.usuario["avatar_path"] = object_path
    st.session_state["_avatar_signed_for"] = None
    st.session_state["_avatar_signed_url"] = None

    # limpa uploader (muda a key)
    st.session_state.avatar_uploader_key += 1

    st.success("✅ Avatar atualizado!")
    st.rerun()
