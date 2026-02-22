"""Importação de Fornecedores (wrapper).

Mantém o importador de fornecedores existente, mas expõe uma assinatura padrão
para o hub de importações e adiciona escopo de keys.
"""

from __future__ import annotations

import streamlit as st


def exibir_importacao_fornecedores(
    supabase_user,
    supabase_admin=None,
    tenant_id: str | None = None,
    scope: str = "imp_fornecedores",
):
    # Garantir um namespace de widgets
    with st.container():
        try:
            from src.ui.importador_fornecedores import exibir_importador_fornecedores

            exibir_importador_fornecedores(supabase_user, tenant_id=tenant_id)
        except Exception as e:
            st.error(f"❌ Não foi possível abrir o importador de fornecedores: {e}")
