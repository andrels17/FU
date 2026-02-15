"""Utilitários de formatação (padrão brasileiro)."""

import pandas as pd

def formatar_numero_br(numero):
    """Formata número no padrão brasileiro (vírgula para decimal, ponto para milhar)"""
    try:
        if pd.isna(numero):
            return "0,00"
        return f"{float(numero):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "0,00"

def formatar_moeda_br(valor):
    """Formata valor monetário no padrão brasileiro"""
    try:
        if pd.isna(valor):
            return "R$ 0,00"
        return f"R$ {formatar_numero_br(valor)}"
    except:
        return "R$ 0,00"

# ============================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================


# ============================================
# CONEXÃO COM SUPABASE
# ============================================

