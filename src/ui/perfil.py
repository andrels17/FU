from __future__ import annotations

import mimetypes
import streamlit as st


def _upload_avatar(supabase, bucket: str, object_path: str, data: bytes, mime: str) -> None:
    """Upload compatível com diferentes versões do supabase/storage.

    O erro `'bool' object has no attribute 'encode'` normalmente acontece quando
    a lib tenta fazer `.encode()` em algum valor de options (ex.: upsert=True).
    Então, aqui garantimos que options sejam strings.
    """

    # Algumas versões aceitam file_options=..., outras aceitam options/dict posicional.
    # Também variam as chaves: content-type vs contentType.
    candidates = [
        # storage3 / supabase-py (file_options)
        {"file_options": {"content-type": mime, "upsert": "true"}},
        {"file_options": {"contentType": mime, "upsert": "true"}},
        # dict posicional (options)
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
            # assinatura diferente -> tenta próximo formato
            last_err = e
            continue
        except Exception as e:
            last_err = e
            continue

    raise last_err  # type: ignore


def exibir_perfil(supabase):
    """Página Meu Perfil (dados + avatar).

    Requisitos no Supabase:
    - Storage bucket: avatars
    - Tabela public.user_profiles com colunas: user_id (uuid), nome (text), avatar_url (text)
    """

    usuario = st.session_state.get("usuario") or {}
    user_id = usuario.get("id") or st.session_state.get("auth_user_id")
    email = usuario.get("email") or st.session_state.get("auth_email")
    nome = usuario.get("nome") or "—"
    perfil = (usuario.get("perfil") or "user").upper()

    st.title("👤 Meu Perfil")

    c1, c2 = st.columns([1, 2])
    with c1:
        avatar_url = usuario.get("avatar_url")
        if avatar_url:
            st.image(avatar_url, width=140)
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

    st.divider()
    st.subheader("🖼 Avatar")
    st.caption("Envie uma imagem (PNG/JPG). O avatar será salvo no Storage e o link persistido em user_profiles.avatar_url.")

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

    try:
        _upload_avatar(supabase, "avatars", object_path, file_bytes, mime)
    except Exception as e:
        st.error(f"Erro ao enviar para o Storage: {e}")
        return

    # URL pública (se bucket público). Se bucket privado, você pode trocar por create_signed_url.
    public_url = supabase.storage.from_("avatars").get_public_url(object_path)
    if isinstance(public_url, dict):
        public_url = public_url.get("publicUrl") or public_url.get("public_url") or public_url.get("publicURL")  # variações

    if not public_url:
        st.warning("Upload OK, mas não consegui obter URL pública. Verifique se o bucket está público ou ajuste as policies.")
        return

    # Persiste no user_profiles
    try:
        supabase.table("user_profiles").update({"avatar_url": public_url}).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Avatar enviado, mas falhou ao salvar no perfil: {e}")
        return

    st.session_state.usuario["avatar_url"] = public_url
    st.success("✅ Avatar atualizado!")
    st.rerun()
