from __future__ import annotations

import base64
import json
import mimetypes
import streamlit as st

try:
    from storage3.utils import StorageException  # type: ignore
except Exception:  # pragma: no cover
    StorageException = Exception  # type: ignore


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


def _get_storage_client():
    """Cria um client do Supabase com a sessão do usuário aplicada.

    Motivo: em alguns setups, o client usado para PostgREST está autenticado,
    mas o módulo de Storage não herda o Authorization header corretamente.
    Aqui garantimos que o Storage enxergue auth.uid() (JWT do usuário).
    """
    try:
        from supabase import create_client  # type: ignore
    except Exception as e:
        raise RuntimeError(f"supabase-py não está disponível: {e}") from e

    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Faltam SUPABASE_URL / SUPABASE_ANON_KEY em st.secrets.")

    sb = create_client(url, key)

    access = st.session_state.get("auth_access_token")
    refresh = st.session_state.get("auth_refresh_token")

    # aplica sessão (quando disponível)
    if access and refresh:
        try:
            sb.auth.set_session(access, refresh)
        except Exception:
            # fallback: algumas versões usam set_session(access_token=..., refresh_token=...)
            sb.auth.set_session(access_token=access, refresh_token=refresh)  # type: ignore

    return sb


def _upload_avatar(storage_client, bucket: str, object_path: str, data: bytes, mime: str) -> None:
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
                storage_client.storage.from_(bucket).upload(object_path, data, file_options=opt["file_options"])
            else:
                storage_client.storage.from_(bucket).upload(object_path, data, opt["positional"])
            return
        except TypeError as e:
            last_err = e
            continue
        except Exception as e:
            last_err = e
            continue
    raise last_err  # type: ignore


def _signed_url(storage_client, bucket: str, object_path: str, expires_in: int = 3600) -> str | None:
    try:
        try:
            res = storage_client.storage.from_(bucket).create_signed_url(object_path, expires_in)
        except TypeError:
            res = storage_client.storage.from_(bucket).create_signed_url(object_path, expires_in=expires_in)

        if isinstance(res, str):
            return res
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url") or res.get("url")
        return getattr(res, "signed_url", None) or getattr(res, "signedURL", None)
    except StorageException:
        return None
    except Exception:
        return None


def exibir_perfil(supabase_db):
    """Meu Perfil (avatar em bucket PRIVADO + URL assinada)."""
    # client dedicado pro Storage, com sessão aplicada
    try:
        supabase = _get_storage_client()
    except Exception as e:
        st.error(f"Falha ao inicializar Storage autenticado: {e}")
        return

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

    # mantém session_state alinhado
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
        st.caption("Se continuar dando RLS, confirme que as policies usam split_part(name,'/',1)=auth.uid()::text e que o upload usa token do usuário.")
        return

    # Persiste o PATH (melhor prática)
    try:
        supabase_db.table("user_profiles").update({"avatar_path": object_path}).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Avatar enviado, mas falhou ao salvar no perfil: {e}")
        return

    st.session_state.usuario["avatar_path"] = object_path
    st.success("✅ Avatar atualizado!")
    st.rerun()
