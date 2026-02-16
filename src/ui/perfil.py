from __future__ import annotations

import mimetypes
import uuid
import streamlit as st


def exibir_perfil(supabase):
    """Página Meu Perfil (dados + avatar).

    Requisitos no Supabase:
    - Bucket Storage: avatars
    - Políticas permitindo o usuário gravar no próprio arquivo (ver instruções).
    - Tabela public.user_profiles com colunas: user_id (uuid), nome (text), avatar_url (text)
    """

    usuario = st.session_state.get("usuario") or {}
    user_id = usuario.get("id") or st.session_state.get("auth_user_id")
    email = usuario.get("email") or st.session_state.get("auth_email")
    nome = usuario.get("nome") or "—"
    perfil = (usuario.get("perfil") or "user").upper()

    st.title("👤 Meu Perfil")

    c1, c2 = st.columns([1, 2], vertical_alignment="top")
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

    st.caption("Envie uma imagem (PNG/JPG). O avatar será salvo no Storage e persistido em user_profiles.avatar_url.")

    arquivo = st.file_uploader("Escolher imagem", type=["png", "jpg", "jpeg"])

    if arquivo is None:
        return

    if not user_id:
        st.error("Não foi possível identificar o usuário logado.")
        return

    # define extensão e content-type
    mime = arquivo.type or mimetypes.guess_type(arquivo.name)[0] or "image/png"
    ext = "png"
    if "jpeg" in mime or arquivo.name.lower().endswith((".jpg", ".jpeg")):
        ext = "jpg"

    # Caminho: avatars/<user_id>/avatar.<ext>
    object_path = f"{user_id}/avatar.{ext}"

    file_bytes = arquivo.getvalue()

    try:
        # Upload (upsert=True)
        supabase.storage.from_("avatars").upload(
            object_path,
            file_bytes,
            file_options={"content-type": mime, "upsert": True},
        )
    except Exception as e:
        st.error(f"Erro ao enviar para o Storage: {e}")
        st.stop()

    try:
        public_url = supabase.storage.from_("avatars").get_public_url(object_path)
    except Exception:
        # fallback (algumas versões retornam dict)
        public_url = None

    if isinstance(public_url, dict):
        public_url = public_url.get("publicUrl") or public_url.get("public_url")

    if not public_url:
        st.warning("Upload OK, mas não consegui obter URL pública. Verifique se o bucket está público ou ajuste as policies.")
        return

    # Persiste no user_profiles
    try:
        supabase.table("user_profiles").update({"avatar_url": public_url}).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Avatar enviado, mas falhou ao salvar no perfil: {e}")
        st.stop()

    # Atualiza sessão
    st.session_state.usuario["avatar_url"] = public_url
    st.success("✅ Avatar atualizado!")
    st.rerun()
