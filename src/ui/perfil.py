
import streamlit as st

def exibir_perfil():
    usuario = st.session_state.usuario
    st.title("👤 Meu Perfil")

    st.write("### Informações")
    st.write(f"**Nome:** {usuario.get('nome')}")
    st.write(f"**Email:** {usuario.get('email')}")
    st.write(f"**Perfil:** {usuario.get('perfil')}")

    st.write("---")
    st.subheader("🖼 Alterar Avatar")

    arquivo = st.file_uploader("Envie uma imagem", type=["png","jpg","jpeg"])

    if arquivo:
        try:
            supabase = st.session_state.get("supabase_client")
            file_bytes = arquivo.read()
            file_name = f"avatar_{usuario.get('id')}.png"

            supabase.storage.from_("avatars").upload(
                file_name,
                file_bytes,
                {"upsert": True}
            )

            public_url = supabase.storage.from_("avatars").get_public_url(file_name)
            st.session_state.usuario["avatar_url"] = public_url
            st.success("Avatar atualizado!")
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao enviar avatar: {e}")
