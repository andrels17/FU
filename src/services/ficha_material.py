"""
Ficha Técnica de Material (MVP)

Fornece funções visuais usadas por src/ui/ficha_material_page.py.
Implementações simples para manter a página funcionando.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.express as px


def criar_cards_kpis(df: pd.DataFrame, col_preco: str = "valor_total") -> None:
    if df is None or df.empty:
        st.info("Sem dados para KPIs.")
        return
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Compras", len(df))
    with col2:
        if col_preco in df.columns:
            st.metric("Valor total", float(pd.to_numeric(df[col_preco], errors="coerce").fillna(0).sum()))
    with col3:
        if col_preco in df.columns:
            st.metric("Valor médio", float(pd.to_numeric(df[col_preco], errors="coerce").fillna(0).mean()))


def criar_grafico_evolucao_precos(df: pd.DataFrame, col_data: str = "data_pedido", col_preco: str = "valor_total") -> None:
    if df is None or df.empty or col_data not in df.columns or col_preco not in df.columns:
        st.info("Sem dados suficientes para evolução de preços.")
        return
    d = df.copy()
    d[col_data] = pd.to_datetime(d[col_data], errors="coerce")
    d[col_preco] = pd.to_numeric(d[col_preco], errors="coerce")
    d = d.dropna(subset=[col_data, col_preco]).sort_values(col_data)
    if d.empty:
        st.info("Sem dados válidos para gráfico.")
        return
    fig = px.line(d, x=col_data, y=col_preco, markers=True, title="Evolução de valores")
    st.plotly_chart(fig, use_container_width=True)


def criar_timeline_compras(df: pd.DataFrame, col_data: str = "data_pedido") -> None:
    if df is None or df.empty or col_data not in df.columns:
        st.info("Sem dados para timeline.")
        return
    d = df.copy()
    d[col_data] = pd.to_datetime(d[col_data], errors="coerce").dt.date
    s = d[col_data].value_counts().sort_index()
    fig = px.bar(x=s.index, y=s.values, title="Compras por dia")
    st.plotly_chart(fig, use_container_width=True)


def criar_ranking_fornecedores_visual(df: pd.DataFrame, col_fornecedor: str = "fornecedor_nome", col_preco: str = "valor_total") -> None:
    if df is None or df.empty or col_fornecedor not in df.columns:
        st.info("Sem dados para ranking.")
        return
    d = df.copy()
    if col_preco in d.columns:
        d[col_preco] = pd.to_numeric(d[col_preco], errors="coerce").fillna(0)
        top = d.groupby(col_fornecedor)[col_preco].sum().sort_values(ascending=False).head(10).reset_index()
        fig = px.bar(top, x=col_preco, y=col_fornecedor, orientation="h", title="Top fornecedores (valor)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        top = d[col_fornecedor].value_counts().head(10)
        fig = px.bar(x=top.values, y=top.index, orientation="h", title="Top fornecedores (qtde)")
        st.plotly_chart(fig, use_container_width=True)


def criar_comparacao_visual_precos(df: pd.DataFrame) -> None:
    st.caption("Comparação visual (MVP)")
    if df is None or df.empty:
        st.info("Sem dados.")
        return
    st.dataframe(df.head(50), use_container_width=True, hide_index=True)


def criar_insights_automaticos(df: pd.DataFrame) -> None:
    st.caption("Insights automáticos (MVP)")
    if df is None or df.empty:
        st.info("Sem dados.")
        return
    st.write("• Avalie fornecedores com maior valor total e maior recorrência.")
    st.write("• Priorize itens com maiores atrasos e maiores impactos financeiros.")


def criar_mini_mapa_fornecedores(df: pd.DataFrame) -> None:
    st.caption("Mini mapa (MVP)")
    st.info("Mapa detalhado está na aba 'Mapa Geográfico'.")
