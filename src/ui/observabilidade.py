"""Tela de Observabilidade (Superadmin).

Mostra:
- Saúde do Supabase
- Logs recentes (arquivo local e tabela app_logs)
- Métricas de performance (session_state)
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st

from src.ui.theme import apply_theme, section_header, card_open, card_close
from src.services import observabilidade as obs


def _read_tail(path: str, max_lines: int = 200) -> str:
    if not os.path.exists(path):
        return "(arquivo de log ainda não existe)"
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:])
    except Exception as e:
        return f"(não foi possível ler log: {e})"


def exibir_observabilidade(*, supabase_admin=None, supabase_user=None) -> None:
    apply_theme()
    section_header(
        "Observabilidade",
        hint="Saúde, logs e performance (Streamlit Cloud friendly).",
        pill=f"{datetime.now().strftime('%d/%m/%Y %H:%M')}",
        accent=True,
    )

    # --- Saúde ---
    card_open()
    st.subheader("Saúde")
    col1, col2, col3 = st.columns(3)

    with col1:
        ok_admin = False
        if supabase_admin is None:
            st.error("Supabase ADMIN: não inicializado")
        else:
            try:
                # ping simples: listar 1 linha (best-effort)
                supabase_admin.table("tenants").select("id").limit(1).execute()
                ok_admin = True
                st.success("Supabase ADMIN: OK")
            except Exception as e:
                st.error(f"Supabase ADMIN: erro ({e})")

    with col2:
        if supabase_user is None:
            st.info("Supabase USER: n/a")
        else:
            try:
                supabase_user.table("tenants").select("id").limit(1).execute()
                st.success("Supabase USER: OK")
            except Exception as e:
                st.warning(f"Supabase USER: erro ({e})")

    with col3:
        st.caption("Registro de evento")
        if st.button("Registrar evento de teste", use_container_width=True):
            obs.log_event(
                "Evento de teste (Observabilidade)",
                event="test_event",
                context={"source": "observabilidade_ui"},
                supabase_admin=supabase_admin,
            )
            st.success("Evento registrado (log local + best-effort no banco).")
    card_close()

    st.divider()

    # --- Performance ---
    card_open()
    st.subheader("Performance (últimos eventos em memória)")
    perf = st.session_state.get("_fu_perf")
    if isinstance(perf, list) and perf:
        dfp = pd.DataFrame(perf)
        # últimos primeiro
        dfp = dfp.sort_values("ts", ascending=False)
        st.dataframe(
            dfp[["name", "ms", "ok", "page", "tenant_id", "user_id", "ts"]].head(100),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Sem métricas ainda. Navegue pelo app para coletar tempos de página/consultas.")
    card_close()

    st.divider()

    # --- Logs ---
    tab1, tab2 = st.tabs(["Log local", "Logs no banco (app_logs)"])

    with tab1:
        card_open()
        st.subheader("Log local (tail)")
        log_path = os.path.join("logs", "fu_app.log")
        st.code(_read_tail(log_path), language="text")
        card_close()

    with tab2:
        card_open()
        st.subheader("Últimos eventos em app_logs")
        if supabase_admin is None:
            st.warning("Supabase ADMIN não disponível. Configure SERVICE_ROLE no Streamlit Cloud secrets.")
        else:
            try:
                r = (
                    supabase_admin.table("app_logs")
                    .select("created_at,event,level,message,tenant_id,user_id,page")
                    .order("created_at", desc=True)
                    .limit(200)
                    .execute()
                )
                df = pd.DataFrame(r.data or [])
                if df.empty:
                    st.info("Sem registros ainda (ou tabela não criada).")
                else:
                    st.dataframe(df, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Não foi possível ler app_logs: {e}")
        card_close()
