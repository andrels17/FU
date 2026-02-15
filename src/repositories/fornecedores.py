"""Repositório de dados: fornecedores (Supabase)."""
import pandas as pd
import streamlit as st

@st.cache_data(ttl=300)
def carregar_fornecedores(_supabase, tenant_id: str | None = None, incluir_inativos: bool = True) -> pd.DataFrame:
    """
    Carrega lista de fornecedores.

    Para alertas e histórico, é importante incluir inativos, pois pedidos antigos
    podem referenciar fornecedores desativados.
    """
    try:
        q = _supabase.table("fornecedores").select("*")
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        if not incluir_inativos:
            q = q.eq("ativo", True)

        resultado = q.execute()
        if resultado.data:
            return pd.DataFrame(resultado.data)

        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar fornecedores: {e}")
        return pd.DataFrame()
