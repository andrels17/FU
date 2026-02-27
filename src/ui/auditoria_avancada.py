from __future__ import annotations

import json
import pandas as pd
import streamlit as st

from src.ui import ux

from src.services import backup_auditoria as ba


def _safe_json(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        try:
            return str(obj)
        except Exception:
            return ""


def exibir_auditoria_avancada(supabase_admin):
    st.title("Auditoria (Before/After)")
    st.caption("Painel Superadmin. Exibe logs_auditoria com suporte a mudanças before/after e filtros.")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        acao = st.text_input("Filtrar por ação (ex.: editar_pedido, excluir_pedido)", value="")
    with col2:
        limite = st.number_input("Limite", min_value=50, max_value=2000, value=300, step=50)
    with col3:
        compact = st.checkbox("Modo compacto", value=True)

    df = ba.carregar_logs_auditoria(supabase_admin, filtro_acao=(acao.strip() or None), limite=int(limite))
    if df.empty:
        ux.info("Sem logs (ou a tabela logs_auditoria não existe).")
        return

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    cols = [c for c in ["timestamp", "usuario_email", "acao"] if c in df.columns]
    if not compact and "detalhes" in df.columns:
        cols.append("detalhes")

    st.dataframe(df[cols] if cols else df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Inspeção de mudanças")
    st.caption("Abra um item para ver before/after (quando presente em `detalhes`).")

    # Mostra últimos N com expander
    show_n = min(30, len(df))
    df2 = df.sort_values(by="timestamp", ascending=False).head(show_n) if "timestamp" in df.columns else df.head(show_n)

    for _, row in df2.iterrows():
        ts = row.get("timestamp")
        ts_s = ts.strftime("%d/%m/%Y %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
        user = row.get("usuario_email") or row.get("usuario_nome") or "(sem usuário)"
        ac = row.get("acao") or "(sem ação)"
        detalhes = row.get("detalhes") or {}

        title = f"{ts_s} • {ac} • {user}"
        with st.expander(title, expanded=False):
            if isinstance(detalhes, str):
                st.code(detalhes)
                continue

            before = detalhes.get("before") if isinstance(detalhes, dict) else None
            after = detalhes.get("after") if isinstance(detalhes, dict) else None

            if before is not None or after is not None:
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Antes**")
                    st.code(_safe_json(before or {}), language="json")
                with c2:
                    st.markdown("**Depois**")
                    st.code(_safe_json(after or {}), language="json")
            else:
                st.markdown("**Detalhes**")
                st.code(_safe_json(detalhes), language="json")

    st.markdown("---")
    st.subheader("Exportação")
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Baixar CSV", data=csv, file_name="logs_auditoria.csv", mime="text/csv", use_container_width=True)
