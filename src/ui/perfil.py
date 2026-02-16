from __future__ import annotations

import base64
import json
import mimetypes
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


def _upload_avatar(supabase, bucket: str, object_path: str, data: bytes, mime: str) -> None:
    """Upload compatível com diferentes versões do supabase/storage."""
    candidates = [
        {"file_options": {"content-type": mime, "upsert": "true"}},
        {"file_options": {"contentType": mime, "upsert": "true"}},
        {"positional": {"content-type": mime, "upsert": "true"}},
        {"positional": {"contentType": mime, "upsert": "true"}},
    ]

    last_err = None
    for opt in candidates:
        try:
            if "file_options" in opt:
                supabase.storage.from_(bucket).upload(object_path, data, file_options=opt["file_options"])
            else:
                supabase.storage.from_(bucket).upload(object_path, data, opt["positional"])
            return
        except TypeError as e:
            last_err = e
            continue
        except Exception as e:
            last_err = e
            continue
    raise last_err  # type: ignore


def _signed_url(supabase, bucket: str, object_path: str, expires_in: int = 3600) -> str | None:
    try:
        res = supabase.storage.from_(bucket).create_signed_url(object_path, expires_in)
    except TypeError:
        res = supabase.storage.from_(bucket).create_signed_url(object_path, expires_in=expires_in)

    if isinstance(res, str):
        return res
    if isinstance(res, dict):
        return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url") or res.get("url")
    return getattr(res, "signed_url", None) or getattr(res, "signedURL", None)


def exibir_perfil(supabase):
    """Meu Perfil (avatar em bucket PRIVADO com URL assinada).

    Importante:
    - O RLS do storage.objects valida auth.uid() contra o PRIMEIRO segmento do path.
    - Para evitar mismatch, usamos o 'sub' do JWT como user_id de referência.
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

    # Mantém session_state alinhado com o uid do token (evita RLS falhar)
    if isinstance(st.session_state.get("usuario"), dict):
        st.session_state.usuario["id"] = user_id

    st.title("👤 Meu Perfil")

    avatar_path = usuario.get("avatar_path") or f"{user_id}/avatar.png"
    avatar_display_url = _signed_url(supabase, "avatars", avatar_path, expires_in=3600) if avatar_path else None

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
        st.caption("🔒 Avatar em bucket privado (URL assinada).")

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
        _upload_avatar(supabase, "avatars", object_path, file_bytes, mime)
    except Exception as e:
        st.error(f"Erro ao enviar para o Storage: {e}")
        # diagnóstico curto
        if uid and str(uid) != str(user_id):
            st.warning(f"Mismatch: jwt sub ({uid}) != user_id ({user_id}).")
        return

    # Persiste o PATH no user_profiles
    try:
        supabase.table("user_profiles").update({"avatar_path": object_path}).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Avatar enviado, mas falhou ao salvar no perfil: {e}")
        return

    st.session_state.usuario["avatar_path"] = object_path
    st.success("✅ Avatar atualizado!")
    st.rerun()
