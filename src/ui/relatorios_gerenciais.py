from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from src.core.db import init_supabase_admin
from src.repositories.pedidos import carregar_pedidos
from src.utils.formatting import formatar_moeda_br
from src.services.relatorios_gastos import (
    FiltrosGastos,
    carregar_links_departamento_gestor,
    carregar_mapa_usuarios_tenant,
    filtrar_pedidos_base,
    gastos_por_departamento,
    gastos_por_frota,
    gastos_por_gestor,
)


# =========================
# Helpers (sem efeitos colaterais no import)
# =========================

def _safe_gastos_por_gestor(df_base: pd.DataFrame, links: Any, user_map: Any) -> pd.DataFrame:
    """Compatibilidade: tenta diferentes assinaturas de gastos_por_gestor()."""
    try:
        return gastos_por_gestor(df_base, links=links, user_map=user_map)
    except TypeError:
        pass
    try:
        return gastos_por_gestor(df_base, links, user_map)
    except TypeError:
        pass
    try:
        return gastos_por_gestor(df_base, links)
    except TypeError:
        pass
    try:
        return gastos_por_gestor(df_base, user_map=user_map)
    except TypeError:
        return gastos_por_gestor(df_base)


def _date_defaults() -> Tuple[date, date]:
    hoje = date.today()
    ini = hoje - timedelta(days=30)
    return ini, hoje


def _as_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _download_name(prefix: str, dt_ini: date, dt_fim: date) -> str:
    return f"{prefix}_{dt_ini.isoformat()}_a_{dt_fim.isoformat()}.csv"


def _periodo_anterior(dt_ini: date, dt_fim: date) -> Tuple[date, date]:
    if not dt_ini or not dt_fim or dt_fim < dt_ini:
        return dt_ini, dt_fim
    dias = (dt_fim - dt_ini).days
    dt_fim_prev = dt_ini - timedelta(days=1)
    dt_ini_prev = dt_fim_prev - timedelta(days=dias)
    return dt_ini_prev, dt_fim_prev


def _add_prev_delta(df_now: pd.DataFrame, df_prev_group: pd.DataFrame, key_col: str) -> pd.DataFrame:
    """Adiciona prev_total e delta_pct (total vs prev_total)."""
    if df_now is None or df_now.empty:
        return df_now
    if df_prev_group is None or df_prev_group.empty or key_col not in df_prev_group.columns:
        df_now = df_now.copy()
        df_now["prev_total"] = 0.0
        df_now["delta_pct"] = 0.0
        return df_now

    prev = df_prev_group[[key_col, "total"]].copy().rename(columns={"total": "prev_total"})
    out = df_now.merge(prev, how="left", on=key_col)
    out["prev_total"] = pd.to_numeric(out.get("prev_total", 0), errors="coerce").fillna(0.0)
    out["total"] = pd.to_numeric(out.get("total", 0), errors="coerce").fillna(0.0)

    def _delta(r):
        if r["prev_total"]:
            return ((r["total"] - r["prev_total"]) / r["prev_total"]) * 100.0
        return 0.0

    out["delta_pct"] = out.apply(_delta, axis=1)
    return out


def _cols_detail(df: pd.DataFrame, date_field: str) -> List[str]:
    prefer = [
        date_field,
        "id",
        "numero_pedido",
        "departamento",
        "cod_equipamento",
        "fornecedor_nome",
        "descricao",
        "status",
        "valor_total",
        "criado_em",
    ]
    return [c for c in prefer if c in (df.columns if df is not None else [])]


def _metric_row(total: float, qtd: float, ticket: float, delta_pct: Optional[float] = None):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gasto total", formatar_moeda_br(total), (f"{delta_pct:.1f}%" if delta_pct is not None else None))
    c2.metric("Pedidos", int(qtd))
    c3.metric("Ticket médio", formatar_moeda_br(ticket))
    c4.caption("*Δ% considera o total do período anterior, quando habilitado.")


# =========================
# Render principal
# =========================

def render_relatorios_gerenciais(supabase=None, tenant_id: str | None = None, **_kwargs):
    """Relatórios Gerenciais v3+ (v5 fix): nada roda no import, tudo roda aqui."""

    st.title("📑 Relatórios Gerenciais")

    # Supabase
    if supabase is None:
        supabase = init_supabase_admin()

    # Carregar base
    df_pedidos = carregar_pedidos(supabase, tenant_id)
    if df_pedidos is None or df_pedidos.empty:
        st.info("📭 Nenhum pedido encontrado.")
        return

    # Tenant / usuários / vínculos
    # Essas funções podem depender do tenant. Mantemos try/except para não quebrar o app.
    try:
        links = carregar_links_departamento_gestor(supabase)
    except Exception:
        links = []
    try:
        user_map = carregar_mapa_usuarios_tenant(supabase)
    except Exception:
        user_map = {}

    # =========================
    # Filtros (topo)
    # =========================
    dt_ini_def, dt_fim_def = _date_defaults()

    with st.container(border=True):
        st.subheader("Filtros")

        c1, c2, c3 = st.columns([1, 1, 1])
        dt_ini = c1.date_input("Data inicial", value=dt_ini_def, key="rg_dt_ini")
        dt_fim = c2.date_input("Data final", value=dt_fim_def, key="rg_dt_fim")

        date_field_label = c3.selectbox(
            "Campo de data",
            ["Solicitação", "OC", "Entrega real", "Criação"],
            index=0,
            key="rg_date_field_label",
        )

        c4, c5, c6 = st.columns([1, 1, 1])
        entregue_label = c4.selectbox("Entregue", ["Todos", "Entregues", "Pendentes"], index=0, key="rg_entregue_label")

        # opções para multiselect (só se existirem colunas)
        dept_opts = sorted([d for d in df_pedidos.get("departamento", pd.Series(dtype=str)).dropna().astype(str).unique().tolist() if d.strip()])
        frota_opts = sorted([f for f in df_pedidos.get("cod_equipamento", pd.Series(dtype=str)).dropna().astype(str).unique().tolist() if str(f).strip()])

        departamentos = c5.multiselect("Departamentos", dept_opts, default=[], key="rg_depts")
        frotas = c6.multiselect("Frotas", frota_opts, default=[], key="rg_frotas")

        # montar filtros
        date_field_map = {
            "Solicitação": "data_solicitacao",
            "OC": "data_oc",
            "Entrega real": "data_entrega_real",
            "Criação": "criado_em",
        }
        date_field = date_field_map.get(date_field_label, "data_solicitacao")

        entregue = None
        if entregue_label == "Entregues":
            entregue = True
        elif entregue_label == "Pendentes":
            entregue = False

        filtros = FiltrosGastos(
            dt_ini=dt_ini,
            dt_fim=dt_fim,
            date_field=date_field,
            entregue=entregue,
            departamentos=list(departamentos or []),
            cod_equipamentos=list(frotas or []),
        )

    # Base filtrada (período atual e anterior)
    df_base = filtrar_pedidos_base(df_pedidos, filtros)
    if df_base is None or df_base.empty:
        st.warning("Sem dados para os filtros selecionados.")
        return

    dt_ini_prev, dt_fim_prev = _periodo_anterior(dt_ini, dt_fim)
    filtros_prev = FiltrosGastos(
        dt_ini=dt_ini_prev,
        dt_fim=dt_fim_prev,
        date_field=date_field,
        entregue=entregue,
        departamentos=list(departamentos or []),
        cod_equipamentos=list(frotas or []),
    )
    df_prev = filtrar_pedidos_base(df_pedidos, filtros_prev)

    # KPIs gerais
    total = pd.to_numeric(df_base.get("valor_total", 0), errors="coerce").fillna(0).sum()
    qtd = float(len(df_base))
    ticket = (total / qtd) if qtd else 0.0

    total_prev = 0.0
    delta_total = None
    if df_prev is not None and not df_prev.empty:
        total_prev = pd.to_numeric(df_prev.get("valor_total", 0), errors="coerce").fillna(0).sum()
        if total_prev:
            delta_total = ((total - total_prev) / total_prev) * 100.0
        else:
            delta_total = 0.0

    with st.container(border=True):
        st.subheader("Resumo do período")
        _metric_row(float(total), float(qtd), float(ticket), delta_total)

    # =========================
    # Abas
    # =========================
    tab_gestor, tab_frota, tab_dept = st.tabs(["👤 Gestor", "🚜 Frota", "🏭 Departamento"])

    # ===== Aba Gestor =====
    with tab_gestor:
        st.subheader("Gastos por Gestor")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_gestor")

        df_g = _safe_gastos_por_gestor(df_base, links, user_map)
        if df_g is None or df_g.empty:
            st.info("Sem dados para o agrupamento por Gestor (verifique vínculos dept → gestor).")
            return

        if comparar:
            df_g_prev = _safe_gastos_por_gestor(df_prev, links, user_map) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if df_g_prev is not None and not df_g_prev.empty and "gestor_user_id" in df_g.columns:
                df_g = _add_prev_delta(df_g, df_g_prev, "gestor_user_id")
            else:
                df_g = df_g.copy()
                df_g["prev_total"] = 0.0
                df_g["delta_pct"] = 0.0
        else:
            df_g = df_g.copy()
            df_g["prev_total"] = 0.0
            df_g["delta_pct"] = 0.0

        df_g = df_g.sort_values("total", ascending=False)

        st.dataframe(df_g, use_container_width=True)

        with st.expander("Drill-down por Gestor", expanded=False):
            key_col = "gestor_user_id" if "gestor_user_id" in df_g.columns else df_g.columns[0]
            choices = df_g[key_col].dropna().astype(str).unique().tolist()
            escolhido = st.selectbox("Selecione", choices, key="rg_gestor_sel")
            if escolhido:
                # tentar mapear gestor → departamentos via links quando possível
                depts = []
                if isinstance(links, list):
                    for l in links:
                        try:
                            if str(l.get("gestor_user_id")) == str(escolhido):
                                d = (l.get("departamento") or "").strip()
                                if d:
                                    depts.append(d)
                        except Exception:
                            continue
                depts = sorted(list(set(depts)))
                df_det = df_base.copy()
                if depts and "departamento" in df_det.columns:
                    df_det = df_det[df_det["departamento"].astype(str).isin(depts)]
                cols = _cols_detail(df_det, date_field)
                st.dataframe(df_det[cols] if cols else df_det, use_container_width=True)
                st.download_button(
                    "Baixar CSV (Gestor)",
                    data=(df_det.to_csv(index=False).encode("utf-8")),
                    file_name=_download_name("drill_gestor", dt_ini, dt_fim),
                    mime="text/csv",
                )

    # ===== Aba Frota =====
    with tab_frota:
        st.subheader("Gastos por Frota")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_frota")

        df_f = gastos_por_frota(df_base)
        if df_f is None or df_f.empty:
            st.info("Sem dados para Frota.")
            return

        if comparar:
            df_f_prev = gastos_por_frota(df_prev) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if df_f_prev is not None and not df_f_prev.empty and "cod_equipamento" in df_f.columns:
                df_f = _add_prev_delta(df_f, df_f_prev, "cod_equipamento")
            else:
                df_f = df_f.copy()
                df_f["prev_total"] = 0.0
                df_f["delta_pct"] = 0.0
        else:
            df_f = df_f.copy()
            df_f["prev_total"] = 0.0
            df_f["delta_pct"] = 0.0

        df_f = df_f.sort_values("total", ascending=False)
        st.dataframe(df_f, use_container_width=True)

        with st.expander("Drill-down por Frota", expanded=False):
            key_col = "cod_equipamento" if "cod_equipamento" in df_f.columns else df_f.columns[0]
            choices = df_f[key_col].dropna().astype(str).unique().tolist()
            escolhido = st.selectbox("Selecione", choices, key="rg_frota_sel")
            if escolhido and "cod_equipamento" in df_base.columns:
                df_det = df_base[df_base["cod_equipamento"].astype(str) == str(escolhido)].copy()
                cols = _cols_detail(df_det, date_field)
                st.dataframe(df_det[cols] if cols else df_det, use_container_width=True)
                st.download_button(
                    "Baixar CSV (Frota)",
                    data=(df_det.to_csv(index=False).encode("utf-8")),
                    file_name=_download_name("drill_frota", dt_ini, dt_fim),
                    mime="text/csv",
                )

    # ===== Aba Departamento =====
    with tab_dept:
        st.subheader("Gastos por Departamento")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_dept")

        df_d = gastos_por_departamento(df_base)
        if df_d is None or df_d.empty:
            st.info("Sem dados para Departamento.")
            return

        if comparar:
            df_d_prev = gastos_por_departamento(df_prev) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if df_d_prev is not None and not df_d_prev.empty and "departamento" in df_d.columns:
                df_d = _add_prev_delta(df_d, df_d_prev, "departamento")
            else:
                df_d = df_d.copy()
                df_d["prev_total"] = 0.0
                df_d["delta_pct"] = 0.0
        else:
            df_d = df_d.copy()
            df_d["prev_total"] = 0.0
            df_d["delta_pct"] = 0.0

        df_d = df_d.sort_values("total", ascending=False)
        st.dataframe(df_d, use_container_width=True)

        with st.expander("Drill-down por Departamento", expanded=False):
            key_col = "departamento" if "departamento" in df_d.columns else df_d.columns[0]
            choices = df_d[key_col].dropna().astype(str).unique().tolist()
            escolhido = st.selectbox("Selecione", choices, key="rg_dept_sel")
            if escolhido and "departamento" in df_base.columns:
                df_det = df_base[df_base["departamento"].astype(str) == str(escolhido)].copy()
                cols = _cols_detail(df_det, date_field)
                st.dataframe(df_det[cols] if cols else df_det, use_container_width=True)
                st.download_button(
                    "Baixar CSV (Departamento)",
                    data=(df_det.to_csv(index=False).encode("utf-8")),
                    file_name=_download_name("drill_departamento", dt_ini, dt_fim),
                    mime="text/csv",
                )
