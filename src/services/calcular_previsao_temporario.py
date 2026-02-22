"""
Cálculo temporário de previsão de entrega (MVP)

Usado quando a coluna previsao_entrega está toda nula.
Regra simples:
- se existir coluna 'data_pedido' (ou 'data_oc'), soma 7 dias
- senão, usa data atual + 7 dias
"""
from __future__ import annotations
from datetime import timedelta, date
import pandas as pd

def calcular_previsao_entrega_temporario(df: pd.DataFrame, dias_padrao: int = 7) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    dias_padrao = int(dias_padrao)
    base_col = None
    for c in ["data_pedido","data_oc","data_emissao","criado_em","created_at"]:
        if c in df.columns:
            base_col = c
            break
    if base_col:
        base = pd.to_datetime(df[base_col], errors="coerce")
    else:
        base = pd.to_datetime(pd.Series([date.today()] * len(df)), errors="coerce")
    df = df.copy()
    df["previsao_entrega"] = (base + pd.to_timedelta(dias_padrao, unit="D")).dt.date
    return df
