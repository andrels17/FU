from __future__ import annotations

import mimetypes
import streamlit as st


def _upload_avatar(supabase, bucket: str, object_path: str, data: bytes, mime: str) -> None:
    """Upload compatível com diferentes versões do supabase/storage.

    Evita erro de encode quando a lib não aceita boolean em options (upsert).
    """
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
                supabase.storage.from_(bucket).upload(
                    object_path,
                    data,
                    file_options=opt["file_options"],
                )
            else:
                supabase.storage.from_(bucket).upload(
                    object_path,
                    data,
                    opt["positional"],
                )
            return
        except TypeError as e:
            last_err = e
            continue
        except Exception as e:
            last_err = e
            continue

    raise last_err  # type: ignore


def _get_avatar_url_private(supabase, bucket: str, object_path: str, expires_in: int = 3600) -> str | None:
    """Gera URL assinada (bucket privado).

    Algumas libs retornam dict, outras string.
    """
    try:
        res = supabase.storage.from_(bucket).create_signed_url(object_path, expires_in)
    except TypeError:
        # algumas versões usam expires_in como kwarg
        res = supabase.storage.from_(bucket).create_signed_url(object_path, expires_in=expires_in)

    if isinstance(res, str):
        return res
    if isinstance(res, dict):
        # variações
        return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url") or res.get("url")
    # objeto com atributo
    return getattr(res, "signed_url", None) or getattr(res, "signedURL", None)


def exibir_perfil(supabase):
    """Página Meu Perfil (dados + avatar privado).

    Requisitos:
    - Storage bucket: avatars (PRIVADO)
    - Policies de storage.objects permitindo INSERT/UPDATE/SELECT no próprio path:
      avatars/<user_id>/...
    - Tabela public.user_profiles: user_id, nome, avatar_path (text, opcional), avatar_url (text, opcional)
    """

    usuario = st.session_state.get("usuario") or {}
    user_id = usuario.get("id") or st.session_state.get("auth_user_id")
    email = usuario.get("email") or st.session_state.get("auth_email")
    nome = usuario.get("nome") or "—"
    perfil = (usuario.get("perfil") or "user").upper()

    st.title("👤 Meu Perfil")

    # Determina o caminho salvo (recomendado) — persistimos o PATH (não a URL assinada)
    avatar_path = usuario.get("avatar_path") or f"{user_id}/avatar.png" if user_id else None

    c1, c2 = st.columns([1, 2])
    with c1:
        # Exibir avatar via URL assinada, se existir
        avatar_display_url = None
        if avatar_path and user_id:
            try:
                avatar_display_url = _get_avatar_url_private(supabase, "avatars", avatar_path, expires_in=3600)
            except Exception:
                avatar_display_url = None

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

    if not user_id:
        st.error("Não foi possível identificar o usuário logado.")
        return

    mime = arquivo.type or mimetypes.guess_type(arquivo.name)[0] or "image/png"
    ext = "png"
    if "jpeg" in mime or arquivo.name.lower().endswith((".jpg", ".jpeg")):
        ext = "jpg"

    object_path = f"{user_id}/avatar.{ext}"
    file_bytes = arquivo.getvalue()

    # Upload (privado)
    try:
        _upload_avatar(supabase, "avatars", object_path, file_bytes, mime)
    except Exception as e:
        st.error(f"Erro ao enviar para o Storage: {e}")
        return

    # Persiste SOMENTE o path (melhor prática)
    try:
        supabase.table("user_profiles").update({"avatar_url": None, "avatar_path": object_path}).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Avatar enviado, mas falhou ao salvar no perfil: {e}")
        return

    # Atualiza sessão (path)
    st.session_state.usuario["avatar_path"] = object_path

    # URL assinada para feedback imediato
    try:
        signed = _get_avatar_url_private(supabase, "avatars", object_path, expires_in=3600)
        if signed:
            st.image(signed, width=160, caption="Pré-visualização")
    except Exception:
        pass

    st.success("✅ Avatar atualizado (privado)!")
    st.rerun()
