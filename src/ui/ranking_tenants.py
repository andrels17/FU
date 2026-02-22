from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pandas as pd
import streamlit as st

from src.ui.theme import section_header


def _to_dt_iso(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    # Postgres timestamp comparison costuma aceitar ISO com timezone
    return dt.isoformat()


def _coerce_ctx(ctx: Any) -> Dict[str, Any]:
    if isinstance(ctx, dict):
        return ctx
    if isinstance(ctx, str):
        try:
            return json.loads(ctx)
        except Exception:
            return {}
    return {}


def exibir_ranking_tenants(supabase_admin) -> None:
    """Ranking por erros e latência (Superadmin).

    Usa app_logs:
      - erros: level='error' OU event='exception'
      - latência: event='perf' com context.ms

    Observação: funciona best-effort. Se app_logs não existir ou não tiver tenant_id,
    a tela mostra orientação e não quebra.
    """

    section_header("Ranking de Tenants", hint="Erros e latência com base em app_logs")

    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        periodo = st.selectbox(
            "Período",
            ["Últimos 7 dias", "Últimos 30 dias", "Últimas 24h"],
            index=0,
            key="rank_periodo",
        )
    with c2:
        topn = st.number_input("Top N", min_value=5, max_value=100, value=25, step=5, key="rank_topn")
    with c3:
        only_with_errors = st.checkbox("Mostrar apenas com erros", value=False, key="rank_only_errors")

    days = 7
    if periodo == "Últimos 30 dias":
        days = 30
    if periodo == "Últimas 24h":
        days = 1

    start_iso = _to_dt_iso(days)

    try:
        # tenta schema completo
        res = (
            supabase_admin.table("app_logs")
            .select("timestamp,level,event,message,tenant_id,page,context")
            .gte("timestamp", start_iso)
            .order("timestamp", desc=True)
            .limit(5000)
            .execute()
        )
        rows = res.data or []
    except Exception:
        # fallback schema mínimo
        try:
            res = (
                supabase_admin.table("app_logs")
                .select("timestamp,level,event,message,context")
                .gte("timestamp", start_iso)
                .order("timestamp", desc=True)
                .limit(5000)
                .execute()
            )
            rows = res.data or []
        except Exception:
            rows = []

    if not rows:
        st.info(
            "Não encontrei dados em **app_logs** para esse período. "
            "Se você acabou de ativar a observabilidade, gere um evento de teste em Observabilidade "
            "e navegue entre páginas para registrar métricas de performance."
        )
        return

    df = pd.DataFrame(rows)
    if "tenant_id" not in df.columns:
        st.warning(
            "Sua tabela **app_logs** não possui a coluna **tenant_id**. "
            "Para ranking por tenant, execute o SQL de upgrade (database_setup.sql) "
            "ou adicione as colunas tenant_id/user_id/page."
        )
        return

    df["tenant_id"] = df["tenant_id"].fillna("(sem tenant)")
    df["level"] = df.get("level", "info").fillna("info")
    df["event"] = df.get("event", "").fillna("")
    df["context"] = df.get("context", {}).apply(_coerce_ctx)

    # erros
    df_err = df[(df["level"].str.lower() == "error") | (df["event"].str.lower() == "exception")]

    # perf/latência
    df_perf = df[df["event"].str.lower() == "perf"].copy()
    if not df_perf.empty:
        df_perf["ms"] = df_perf["context"].apply(lambda c: c.get("ms"))
        df_perf["ms"] = pd.to_numeric(df_perf["ms"], errors="coerce")

    # agregações
    agg = pd.DataFrame({"tenant_id": df["tenant_id"].unique()})
    agg["eventos"] = agg["tenant_id"].map(df.groupby("tenant_id").size()).fillna(0).astype(int)
    agg["erros"] = agg["tenant_id"].map(df_err.groupby("tenant_id").size()).fillna(0).astype(int)

    if not df_perf.empty and "ms" in df_perf.columns:
        g = df_perf.dropna(subset=["ms"]).groupby("tenant_id")["ms"]
        agg["lat_media_ms"] = agg["tenant_id"].map(g.mean()).round(2)
        agg["lat_p95_ms"] = agg["tenant_id"].map(g.quantile(0.95)).round(2)
    else:
        agg["lat_media_ms"] = None
        agg["lat_p95_ms"] = None

    if only_with_errors:
        agg = agg[agg["erros"] > 0]

    # score simples: prioriza erros, depois p95
    agg["score"] = (agg["erros"] * 1000) + agg["lat_p95_ms"].fillna(0)
    agg = agg.sort_values(["score", "erros", "lat_p95_ms"], ascending=False).head(int(topn))

    st.caption("Dica: clique no tenant_id para filtrar logs na tela de Observabilidade.")
    st.dataframe(agg.drop(columns=["score"]), use_container_width=True, hide_index=True)

    # drilldown
    tenant_sel = st.selectbox(
        "Ver detalhes do tenant",
        ["(selecione)"] + agg["tenant_id"].astype(str).tolist(),
        index=0,
        key="rank_tenant_sel",
    )
    if tenant_sel and tenant_sel != "(selecione)":
        dff = df[df["tenant_id"].astype(str) == str(tenant_sel)].copy()
        cols = [c for c in ["timestamp", "level", "event", "page", "message"] if c in dff.columns]
        st.dataframe(dff[cols].head(300), use_container_width=True, hide_index=True)
