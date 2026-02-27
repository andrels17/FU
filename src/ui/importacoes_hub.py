"""Tela: Hub de Importações (Cloud-safe).

Motivação: evitar st.tabs() para fluxos pesados de importação, já que o Streamlit
executa o código de todas as tabs e isso tende a causar DuplicateWidgetID e custo
desnecessário.
"""

from __future__ import annotations

import streamlit as st

from src.ui import ux

from src.ui.theme import section_header


def exibir_importacoes_hub(supabase_user, supabase_admin=None, tenant_id: str | None = None):
    """Hub de importações.

    - Admin-only
    - Seleção via radio (horizontal) para renderizar apenas 1 fluxo por vez
    """

    # Permissão: importações afetam dados em massa (Admin)
    if (st.session_state.get("usuario") or {}).get("perfil") != "admin":
        st.error("⛔ Acesso negado. Apenas administradores podem realizar importações.")
        return

    section_header(
        "Importações",
        hint="Centralize uploads e sincronizações (pedidos, materiais e fornecedores).",
        pill="Operação",
    )

    with st.container(border=True):
        escolha = ux.segmented("", options=["Pedidos", "Materiais", "Fornecedores"], key="hub_imports__selector", default="Pedidos")

        st.markdown("---")

        if escolha == "Pedidos":
            from src.ui.importacoes.pedidos import exibir_importacao_pedidos

            exibir_importacao_pedidos(
                supabase_user=supabase_user,
                supabase_admin=supabase_admin,
                tenant_id=tenant_id,
                scope="imp_pedidos",
            )
            return

        if escolha == "Materiais":
            st.caption("A importação de materiais está no **Catálogo de Materiais** (Importar CSV).")

            is_admin = (st.session_state.get("usuario") or {}).get("perfil") == "admin"
            is_superadmin = bool(st.session_state.get("is_superadmin"))
            if not (is_admin or is_superadmin):
                ux.warn("Apenas Admin/Superadmin pode acessar o Catálogo de Materiais.")
                return

            if st.button("Abrir Catálogo de Materiais", use_container_width=True, key="hub_imports__go_catalog"):
                st.session_state.current_page = "catalog_materials"
                st.rerun()
            return

        # Fornecedores
        from src.ui.importacoes.fornecedores import exibir_importacao_fornecedores

        exibir_importacao_fornecedores(
            supabase_user=supabase_user,
            supabase_admin=supabase_admin,
            tenant_id=tenant_id,
            scope="imp_fornecedores",
        )
