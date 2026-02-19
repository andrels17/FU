from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Tuple

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


# ============================
# Helpers (safe / formatting)
# ============================

def _date_defaults() -> Tuple[date, date]:
    hoje = date.today()
    ini = hoje - timedelta(days=30)
    return ini, hoje


def _as_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _share_percent(total: float, part: float) -> float:
    if not total:
        return 0.0
    return (part / total) * 100.0


def _download_name(prefix: str, dt_ini: date, dt_fim: date) -> str:
    return f"{prefix}_{dt_ini.isoformat()}_a_{dt_fim.isoformat()}.csv"


def _pill_style() -> None:
    # micro UX: compacta multiselects
    st.markdown(
        """
        <style>
        div[data-baseweb="select"] > div { min-height: 38px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _init_filter_state() -> None:
    dt_ini_def, dt_fim_def = _date_defaults()
    st.session_state.setdefault("rg_dt_ini", dt_ini_def)
    st.session_state.setdefault("rg_dt_fim", dt_fim_def)
    st.session_state.setdefault("rg_date_field_label", "Solicitação")
    st.session_state.setdefault("rg_entregue_label", "Todos")
    st.session_state.setdefault("rg_depts", [])
    st.session_state.setdefault("rg_frotas", [])
    st.session_state.setdefault("rg_applied", False)

    # aba gestor
    st.session_state.setdefault("rg_roles_incluidos", ["admin", "gestor"])
    st.session_state.setdefault("rg_busca_gestor", "")


def _build_filtros_from_state() -> Tuple[FiltrosGastos, date, date]:
    date_field_map = {
        "Solicitação": "data_solicitacao",
        "OC": "data_oc",
        "Entrega real": "data_entrega_real",
        "Criação": "criado_em",
    }
    dt_ini = st.session_state.get("rg_dt_ini")
    dt_fim = st.session_state.get("rg_dt_fim")
    date_field = date_field_map.get(st.session_state.get("rg_date_field_label", "Solicitação"), "data_solicitacao")

    entregue_opt = st.session_state.get("rg_entregue_label", "Todos")
    entregue = None
    if entregue_opt == "Entregues":
        entregue = True
    elif entregue_opt == "Pendentes":
        entregue = False

    filtros = FiltrosGastos(
        dt_ini=dt_ini,
        dt_fim=dt_fim,
        date_field=date_field,
        entregue=entregue,
        departamentos=list(st.session_state.get("rg_depts") or []),
        cod_equipamentos=list(st.session_state.get("rg_frotas") or []),
    )
    return filtros, dt_ini, dt_fim


def _periodo_anterior(dt_ini: date, dt_fim: date) -> Tuple[date, date]:
    """Retorna (dt_ini_prev, dt_fim_prev) com o mesmo número de dias do período atual."""
    if not dt_ini or not dt_fim or dt_fim < dt_ini:
        return dt_ini, dt_fim
    dias = (dt_fim - dt_ini).days
    dt_fim_prev = dt_ini - timedelta(days=1)
    dt_ini_prev = dt_fim_prev - timedelta(days=dias)
    return dt_ini_prev, dt_fim_prev


def _evolucao_semanal(df_base: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """Soma valor_total por semana (freq=W)."""
    if df_base is None or df_base.empty or date_col not in df_base.columns:
        return pd.DataFrame(columns=["data", "total"])

    s = pd.to_datetime(df_base[date_col], errors="coerce")
    tmp = df_base.copy()
    tmp["_data"] = s
    tmp = tmp.dropna(subset=["_data"])
    if tmp.empty:
        return pd.DataFrame(columns=["data", "total"])

    tmp["_valor"] = pd.to_numeric(tmp.get("valor_total", 0), errors="coerce").fillna(0)
    out = tmp.groupby(pd.Grouper(key="_data", freq="W"))["_valor"].sum().reset_index()
    out = out.rename(columns={"_data": "data", "_valor": "total"})
    return out


def _cols_detail(df: pd.DataFrame, date_field: str) -> List[str]:
    """Colunas sugeridas para drill-down (apenas as que existirem)."""
    prefer = [
        date_field,
        "id",
        "nr_solicitacao",
        "nr_oc",
        "departamento",
        "cod_equipamento",
        "cod_material",
        "descricao",
        "qtde_solicitada",
        "qtde_entregue",
        "qtde_pendente",
        "status",
        "entregue",
        "valor_total",
        "fornecedor_nome",
    ]
    return [c for c in prefer if c in df.columns]


def _download_df(df: pd.DataFrame, prefix: str, dt_ini: date, dt_fim: date) -> Tuple[bytes, str]:
    csv = df.to_csv(index=False).encode("utf-8")
    return csv, _download_name(prefix, dt_ini, dt_fim)


def _top_selector(prefix: str) -> int | None:
    opt = st.radio(
        "Exibir",
        ["Top 10", "Top 20", "Top 50", "Todos"],
        horizontal=True,
        key=f"{prefix}_top",
        index=0,
    )
    if opt == "Top 10":
        return 10
    if opt == "Top 20":
        return 20
    if opt == "Top 50":
        return 50
    return None


def _render_common_actions(df_out: pd.DataFrame, filename_prefix: str, dt_ini: date, dt_fim: date) -> None:
    csv = df_out.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Baixar CSV",
        csv,
        _download_name(filename_prefix, dt_ini, dt_fim),
        "text/csv",
        use_container_width=True,
    )


def _links_to_dept_map(_links: Any) -> Dict[str, str]:
    """Normaliza links para dict: {departamento: gestor_user_id}."""
    if _links is None:
        return {}

    # Se vier DataFrame, transforma em registros
    if isinstance(_links, pd.DataFrame):
        if _links.empty:
            return {}
        records = _links.to_dict("records")
        _links = records

    if isinstance(_links, dict):
        return {str(k).strip(): str(v) for k, v in _links.items() if str(k).strip()}

    out: Dict[str, str] = {}
    if isinstance(_links, list):
        for l in _links:
            try:
                if not isinstance(l, dict):
                    continue
                dept = (l.get("departamento") or "").strip()
                gid = l.get("gestor_user_id")
                if dept and gid:
                    out[dept] = str(gid)
            except Exception:
                continue
    return out


def _add_prev_delta(df_now: pd.DataFrame, df_prev_group: pd.DataFrame, key_col: str) -> pd.DataFrame:
    """Adiciona colunas prev_total e delta_pct (total vs prev_total) se possível."""
    if df_now is None or df_now.empty:
        return df_now
    if df_prev_group is None or df_prev_group.empty or key_col not in df_prev_group.columns:
        df_now["prev_total"] = 0.0
        df_now["delta_pct"] = 0.0
        return df_now

    prev = df_prev_group[[key_col, "total"]].copy()
    prev = prev.rename(columns={"total": "prev_total"})
    out = df_now.merge(prev, how="left", on=key_col)

    out["prev_total"] = pd.to_numeric(out.get("prev_total", 0), errors="coerce").fillna(0.0)
    out["total"] = pd.to_numeric(out.get("total", 0), errors="coerce").fillna(0.0)
    out["delta_pct"] = out.apply(
        lambda r: ((r["total"] - r["prev_total"]) / r["prev_total"] * 100.0) if r["prev_total"] else 0.0,
        axis=1,
    )
    return out


def _safe_gastos_por_gestor(df_base: pd.DataFrame, links: Any, user_map: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
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
    # fallback: tenta passar só um dict dept->gestor se existir
    try:
        mapa = { (l.get("departamento") or "").strip(): l.get("gestor_user_id") for l in (links or []) if isinstance(l, dict) and (l.get("departamento") or "").strip() }
        return gastos_por_gestor(df_base, mapa)
    except TypeError:
        return gastos_por_gestor(df_base)


def _normalize_user_map(user_map: Any) -> Dict[str, Dict[str, Any]]:
    """
    Garante formato:
      {user_id: {"nome": ..., "email": ..., "role": ...}}
    """
    if user_map is None:
        return {}
    if isinstance(user_map, dict):
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in user_map.items():
            if not k:
                continue
            if isinstance(v, dict):
                out[str(k)] = {
                    "nome": v.get("nome") or v.get("name") or v.get("full_name") or "",
                    "email": v.get("email") or "",
                    "role": (v.get("role") or v.get("perfil") or v.get("cargo") or "").lower(),
                }
            else:
                out[str(k)] = {"nome": str(v), "email": "", "role": ""}
        return out
    # Se vier list[dict]
    if isinstance(user_map, list):
        out = {}
        for r in user_map:
            if not isinstance(r, dict):
                continue
            uid = r.get("user_id") or r.get("id")
            if not uid:
                continue
            out[str(uid)] = {
                "nome": r.get("nome") or r.get("name") or "",
                "email": r.get("email") or "",
                "role": (r.get("role") or r.get("perfil") or "").lower(),
            }
        return out
    return {}


# ============================
# Main entry
# ============================

def render_relatorios_gerenciais(_supabase, tenant_id: str) -> None:
    st.title("📈 Relatórios Gerenciais")
    st.caption("Visão de gastos por Gestor, Frota (cód. equipamento) e Departamento.")

    if not tenant_id:
        st.error("Tenant não identificado.")
        st.stop()

    _init_filter_state()
    _pill_style()

    # Admin (service role) para leituras que podem sofrer RLS
    try:
        supabase_admin = init_supabase_admin()
    except Exception:
        supabase_admin = None

    # ===== Carregar pedidos uma vez (base para filtros + análise) =====
    with st.spinner("Carregando pedidos..."):
        df_pedidos = carregar_pedidos(_supabase, tenant_id=tenant_id)

    if df_pedidos is None or df_pedidos.empty:
        st.info("Nenhum pedido encontrado para este tenant.")
        st.stop()

    # Opções de filtros (evita repetir)
    df_tmp = df_pedidos.copy()
    for col in ["departamento", "cod_equipamento"]:
        if col in df_tmp.columns:
            df_tmp[col] = df_tmp[col].fillna("").astype(str).str.strip()
        else:
            df_tmp[col] = ""

    dept_opts = sorted([d for d in df_tmp["departamento"].unique().tolist() if d])
    frota_opts = sorted([f for f in df_tmp["cod_equipamento"].unique().tolist() if f])

    # ===== Carregar vínculos e mapa de usuários (1x) =====
    with st.spinner("Carregando vínculos e usuários..."):
        links = carregar_links_departamento_gestor(supabase_admin or _supabase, tenant_id=tenant_id)
        user_map_raw = carregar_mapa_usuarios_tenant(supabase_admin or _supabase, tenant_id=tenant_id)

    user_map = _normalize_user_map(user_map_raw)
    dept_map = _links_to_dept_map(links)

    # ===== Filtros do relatório (sidebar) =====
    with st.sidebar:
        st.markdown("### 🧾 Filtros do relatório")

        # presets
        p1, p2, p3, p4 = st.columns(4)
        if p1.button("7d", use_container_width=True):
            hoje = date.today()
            st.session_state["rg_dt_ini"] = hoje - timedelta(days=6)
            st.session_state["rg_dt_fim"] = hoje
        if p2.button("30d", use_container_width=True):
            hoje = date.today()
            st.session_state["rg_dt_ini"] = hoje - timedelta(days=29)
            st.session_state["rg_dt_fim"] = hoje
        if p3.button("90d", use_container_width=True):
            hoje = date.today()
            st.session_state["rg_dt_ini"] = hoje - timedelta(days=89)
            st.session_state["rg_dt_fim"] = hoje
        if p4.button("Mês", use_container_width=True):
            hoje = date.today()
            st.session_state["rg_dt_ini"] = hoje.replace(day=1)
            st.session_state["rg_dt_fim"] = hoje

        st.date_input("Data inicial", value=st.session_state["rg_dt_ini"], key="rg_dt_ini")
        st.date_input("Data final", value=st.session_state["rg_dt_fim"], key="rg_dt_fim")

        st.selectbox(
            "Campo de data",
            ["Solicitação", "OC", "Entrega real", "Criação"],
            index=["Solicitação", "OC", "Entrega real", "Criação"].index(st.session_state.get("rg_date_field_label", "Solicitação")),
            key="rg_date_field_label",
        )

        st.selectbox(
            "Situação",
            ["Todos", "Entregues", "Pendentes"],
            index=["Todos", "Entregues", "Pendentes"].index(st.session_state.get("rg_entregue_label", "Todos")),
            key="rg_entregue_label",
        )

        st.multiselect(
            "Departamentos",
            options=dept_opts,
            default=[x for x in (st.session_state.get("rg_depts") or []) if x in dept_opts],
            key="rg_depts",
        )

        st.multiselect(
            "Frotas (cód. equipamento)",
            options=frota_opts,
            default=[x for x in (st.session_state.get("rg_frotas") or []) if x in frota_opts],
            key="rg_frotas",
        )

        st.divider()
        st.markdown("### 👥 Filtro de Pessoas (aba Gestor)")
        roles = sorted(list({(v.get("role") or "").lower() for v in user_map.values()} - {""}))
        if not roles:
            roles = ["admin", "gestor", "user"]
        st.multiselect(
            "Roles incluídos",
            options=roles,
            default=[r for r in (st.session_state.get("rg_roles_incluidos") or []) if r in roles] or ["admin", "gestor"],
            key="rg_roles_incluidos",
        )
        st.text_input("Buscar gestor (nome/e-mail)", value=st.session_state.get("rg_busca_gestor", ""), key="rg_busca_gestor")

        st.caption(f"Deptos vinculados: {len(dept_map)} · Usuários no mapa: {len(user_map)}")

    # ===== Aplicar filtros (estado aplicado) =====
    filtros, dt_ini, dt_fim = _build_filtros_from_state()

    # Dataset base já filtrado (serve para KPIs + abas)
    df_base = filtrar_pedidos_base(df_pedidos, filtros=filtros)

    if df_base is None or df_base.empty:
        st.warning("Nenhum pedido no filtro atual. Ajuste o período/filtros.")
        st.stop()

    total_geral = _as_float(df_base.get("valor_total", pd.Series(dtype=float)).fillna(0).sum())
    qtd_geral = int(len(df_base))
    ticket = (total_geral / qtd_geral) if qtd_geral else 0.0

    # Período anterior (comparação)
    dt_ini_prev, dt_fim_prev = _periodo_anterior(dt_ini, dt_fim)
    filtros_prev = FiltrosGastos(
        dt_ini=dt_ini_prev,
        dt_fim=dt_fim_prev,
        date_field=filtros.date_field,
        entregue=filtros.entregue,
        departamentos=filtros.departamentos,
        cod_equipamentos=filtros.cod_equipamentos,
    )
    df_prev = filtrar_pedidos_base(df_pedidos, filtros=filtros_prev)
    total_prev = _as_float(df_prev.get("valor_total", pd.Series(dtype=float)).fillna(0).sum()) if df_prev is not None and not df_prev.empty else 0.0
    delta_pct = ((total_geral - total_prev) / total_prev * 100.0) if total_prev else 0.0

    # ===== Resumo =====
    with st.container(border=True):
        st.markdown("### 📌 Resumo do período aplicado")
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Pedidos", qtd_geral)
        a2.metric("Gasto total", formatar_moeda_br(total_geral), f"{delta_pct:.1f}% vs anterior" if total_prev else None)
        a3.metric("Período anterior", formatar_moeda_br(total_prev))
        a4.metric("Ticket médio", formatar_moeda_br(ticket))
        st.caption(
            f"Período: **{dt_ini.strftime('%d/%m/%Y')}** a **{dt_fim.strftime('%d/%m/%Y')}** · "
            f"Data: **{filtros.date_field}** · Situação: **{st.session_state.get('rg_entregue_label','Todos')}**"
        )

    with st.container(border=True):
        st.markdown("### 📈 Evolução do gasto (semanal)")
        df_evol = _evolucao_semanal(df_base, filtros.date_field)
        if df_evol is None or df_evol.empty:
            st.caption("Sem dados suficientes para a evolução semanal.")
        else:
            st.line_chart(df_evol.set_index("data")["total"])

    st.divider()

    # ===== Abas =====
    tab_gestor, tab_frota, tab_dept = st.tabs(["👤 Por Gestor", "🚜 Por Frota", "🏢 Por Departamento"])

    # ===== Aba Gestor =====
    with tab_gestor:
        st.subheader("Gastos por Gestor")
        topn = _top_selector("rg_gestor")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_gestor")

        # Calcula agrupamento de gestores baseado em vínculos departamento->gestor (NÃO por criado_por)
        df_g = _safe_gastos_por_gestor(df_base, links, user_map)

        if df_g is None or df_g.empty:
            st.info("Sem dados para o agrupamento por Gestor (verifique vínculos de departamento → gestor).")
            st.stop()

        # Enriquecer com role a partir do user_map (quando faltar)
        if "gestor_user_id" in df_g.columns and "gestor_role" not in df_g.columns:
            df_g["gestor_role"] = df_g["gestor_user_id"].astype(str).map(lambda uid: (user_map.get(str(uid)) or {}).get("role", ""))

        # Filtro por roles incluídos (sidebar)
        roles_incl = set([(r or "").lower() for r in (st.session_state.get("rg_roles_incluidos") or [])])
        if roles_incl and "gestor_role" in df_g.columns:
            df_g = df_g[df_g["gestor_role"].fillna("").astype(str).str.lower().isin(roles_incl)]

        # Busca (sidebar)
        q = (st.session_state.get("rg_busca_gestor") or "").strip().lower()
        if q:
            nome_col = "gestor_nome" if "gestor_nome" in df_g.columns else None
            email_col = "gestor_email" if "gestor_email" in df_g.columns else None
            if nome_col and email_col:
                df_g = df_g[
                    df_g[nome_col].fillna("").astype(str).str.lower().str.contains(q)
                    | df_g[email_col].fillna("").astype(str).str.lower().str.contains(q)
                ]
            elif nome_col:
                df_g = df_g[df_g[nome_col].fillna("").astype(str).str.lower().str.contains(q)]

        if df_g.empty:
            st.warning("Nenhum gestor após os filtros de pessoas (roles/busca).")
            st.stop()

        # Comparação
        if comparar:
            df_g_prev = _safe_gastos_por_gestor(df_prev, links, user_map) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if df_g_prev is not None and not df_g_prev.empty and "gestor_user_id" in df_g.columns:
                df_g = _add_prev_delta(df_g, df_g_prev, "gestor_user_id")
            else:
                df_g["prev_total"] = 0.0
                df_g["delta_pct"] = 0.0
        else:
            df_g["prev_total"] = 0.0
            df_g["delta_pct"] = 0.0

        with st.container(border=True):
            g1, g2, g3 = st.columns(3)
            g1.metric("Gestores no período", int(df_g["gestor_user_id"].nunique()) if "gestor_user_id" in df_g.columns else len(df_g))
            g2.metric("Gasto total", formatar_moeda_br(_as_float(df_g["total"].sum())))
            g3.metric("Pedidos", int(_as_float(df_g.get("qtd_pedidos", pd.Series(dtype=float)).sum())))

        df_g = df_g.copy()
        df_g["participacao_pct"] = df_g["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_g = df_g.sort_values("total", ascending=False)

        df_plot = df_g.head(topn) if topn else df_g
        if "gestor_nome" in df_plot.columns:
            st.bar_chart(df_plot.set_index("gestor_nome")[["total"]], height=280)
        else:
            st.bar_chart(df_plot.set_index("gestor_user_id")[["total"]], height=280)

        # Tabela
        df_show = df_g.copy()
        df_show["Gestor"] = df_show.get("gestor_nome", pd.Series(["(Sem nome)"] * len(df_show))).fillna("(Sem nome)")
        df_show["Role"] = df_show.get("gestor_role", pd.Series([""] * len(df_show))).fillna("")
        df_show["E-mail"] = df_show.get("gestor_email", pd.Series([""] * len(df_show))).fillna("")
        df_show["Pedidos"] = df_show.get("qtd_pedidos", 0).fillna(0).astype(int)
        df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
        df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{_as_float(x):.1f}%")

        if comparar:
            df_show["Anterior"] = df_show["prev_total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
            df_show["Δ%"] = df_show["delta_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
            cols = ["Gestor", "Role", "E-mail", "Pedidos", "Total", "Anterior", "Δ%", "% do total"]
        else:
            cols = ["Gestor", "Role", "E-mail", "Pedidos", "Total", "% do total"]

        st.dataframe(df_show[cols], use_container_width=True, hide_index=True)

        with st.expander("🔎 Ver pedidos de um gestor", expanded=False):
            opt_names = sorted(list(set(df_show["Gestor"].tolist())))
            sel_nome = st.selectbox("Gestor", options=opt_names, key="rg_drill_gestor_nome")

            sel_gid = None
            try:
                # tenta achar gid pelo nome na base original df_g (não formatada)
                sel_row = df_g[df_g.get("gestor_nome", "").fillna("(Sem nome)") == sel_nome].head(1)
                if not sel_row.empty and "gestor_user_id" in sel_row.columns:
                    sel_gid = sel_row["gestor_user_id"].iloc[0]
            except Exception:
                sel_gid = None

            if not sel_gid:
                st.info("Selecione um gestor válido.")
            else:
                # departamentos ligados ao gestor e pedidos filtrados por esses departamentos
                deptos = [d for d, gid in dept_map.items() if str(gid) == str(sel_gid)]
                st.caption(f"Departamentos vinculados: {', '.join(deptos) if deptos else '(nenhum)'}")
                df_det = df_base[df_base.get("departamento", "").astype(str).isin(deptos)].copy() if deptos else df_base.iloc[0:0].copy()

                if df_det.empty:
                    st.warning("Sem pedidos para este gestor no período aplicado.")
                else:
                    cols_det = _cols_detail(df_det, filtros.date_field)
                    st.dataframe(df_det[cols_det], use_container_width=True, hide_index=True)
                    csv_det, name_det = _download_df(df_det[cols_det], "pedidos_gestor", dt_ini, dt_fim)
                    st.download_button("⬇️ Baixar pedidos (gestor)", csv_det, name_det, "text/csv", use_container_width=True)

        _render_common_actions(df_g, "gastos_por_gestor", dt_ini, dt_fim)

    # ===== Aba Frota =====
    with tab_frota:
        st.subheader("Gastos por Frota (cód. equipamento)")
        topn = _top_selector("rg_frota")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_frota")

        df_f = gastos_por_frota(df_base)
        if df_f is None or df_f.empty:
            st.info("Sem dados para o agrupamento por Frota (cod_equipamento).")
            st.stop()

        if comparar:
            df_f_prev = gastos_por_frota(df_prev) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if df_f_prev is not None and not df_f_prev.empty and "cod_equipamento" in df_f.columns:
                df_f = _add_prev_delta(df_f, df_f_prev, "cod_equipamento")
            else:
                df_f["prev_total"] = 0.0
                df_f["delta_pct"] = 0.0
        else:
            df_f["prev_total"] = 0.0
            df_f["delta_pct"] = 0.0

        with st.container(border=True):
            f1, f2, f3 = st.columns(3)
            f1.metric("Frotas no período", int(df_f["cod_equipamento"].nunique()) if "cod_equipamento" in df_f.columns else len(df_f))
            f2.metric("Gasto total", formatar_moeda_br(_as_float(df_f["total"].sum())))
            f3.metric("Pedidos", int(_as_float(df_f.get("qtd_pedidos", pd.Series(dtype=float)).sum())))

        df_f = df_f.copy()
        df_f["participacao_pct"] = df_f["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_f = df_f.sort_values("total", ascending=False)

        df_plot = df_f.head(topn) if topn else df_f
        st.bar_chart(df_plot.set_index("cod_equipamento")[["total"]], height=280)

        q = st.text_input("Buscar frota (cód.)", value="", key="rg_busca_frota", placeholder="Digite parte do código…")
        df_show = df_f.copy()
        df_show["Frota"] = df_show["cod_equipamento"].fillna("(Sem código)").astype(str)
        if q.strip():
            qq = q.strip().lower()
            df_show = df_show[df_show["Frota"].astype(str).str.lower().str.contains(qq)]

        df_show["Pedidos"] = df_show.get("qtd_pedidos", 0).fillna(0).astype(int)
        df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
        df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
        if comparar:
            df_show["Anterior"] = df_show["prev_total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
            df_show["Δ%"] = df_show["delta_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
            cols = ["Frota", "Pedidos", "Total", "Anterior", "Δ%", "% do total"]
        else:
            cols = ["Frota", "Pedidos", "Total", "% do total"]
        st.dataframe(df_show[cols], use_container_width=True, hide_index=True)

        with st.expander("🔎 Ver pedidos de uma frota (cód. equipamento)", expanded=False):
            sel_frota = st.selectbox(
                "Frota (cód.)",
                options=df_f["cod_equipamento"].fillna("(Sem código)").astype(str).tolist(),
                key="rg_drill_frota",
            )
            df_det = df_base[df_base.get("cod_equipamento", "").astype(str) == str(sel_frota)].copy()
            if df_det.empty:
                st.warning("Sem pedidos para esta frota no período aplicado.")
            else:
                cols_det = _cols_detail(df_det, filtros.date_field)
                st.dataframe(df_det[cols_det], use_container_width=True, hide_index=True)
                csv_det, name_det = _download_df(df_det[cols_det], "pedidos_frota", dt_ini, dt_fim)
                st.download_button("⬇️ Baixar pedidos (frota)", csv_det, name_det, "text/csv", use_container_width=True)

        _render_common_actions(df_f, "gastos_por_frota", dt_ini, dt_fim)

    # ===== Aba Departamento =====
    with tab_dept:
        st.subheader("Gastos por Departamento")
        topn = _top_selector("rg_dept")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_dept")

        df_d = gastos_por_departamento(df_base)
        if df_d is None or df_d.empty:
            st.info("Sem dados para o agrupamento por Departamento.")
            st.stop()

        if comparar:
            df_d_prev = gastos_por_departamento(df_prev) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if df_d_prev is not None and not df_d_prev.empty and "departamento" in df_d.columns:
                df_d = _add_prev_delta(df_d, df_d_prev, "departamento")
            else:
                df_d["prev_total"] = 0.0
                df_d["delta_pct"] = 0.0
        else:
            df_d["prev_total"] = 0.0
            df_d["delta_pct"] = 0.0

        with st.container(border=True):
            d1, d2, d3 = st.columns(3)
            d1.metric("Departamentos", int(df_d["departamento"].nunique()) if "departamento" in df_d.columns else len(df_d))
            d2.metric("Gasto total", formatar_moeda_br(_as_float(df_d["total"].sum())))
            d3.metric("Pedidos", int(_as_float(df_d.get("qtd_pedidos", pd.Series(dtype=float)).sum())))

        df_d = df_d.copy()
        df_d["participacao_pct"] = df_d["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_d = df_d.sort_values("total", ascending=False)
        df_plot = df_d.head(topn) if topn else df_d
        st.bar_chart(df_plot.set_index("departamento")[["total"]], height=280)

        q = st.text_input("Buscar departamento", value="", key="rg_busca_dept", placeholder="Digite parte do nome…")
        df_show = df_d.copy()
        df_show["Departamento"] = df_show["departamento"].fillna("(Sem dept)").astype(str)
        if q.strip():
            qq = q.strip().lower()
            df_show = df_show[df_show["Departamento"].str.lower().str.contains(qq)]

        df_show["Pedidos"] = df_show.get("qtd_pedidos", 0).fillna(0).astype(int)
        df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
        df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
        if comparar:
            df_show["Anterior"] = df_show["prev_total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
            df_show["Δ%"] = df_show["delta_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
            cols = ["Departamento", "Pedidos", "Total", "Anterior", "Δ%", "% do total"]
        else:
            cols = ["Departamento", "Pedidos", "Total", "% do total"]

        st.dataframe(df_show[cols], use_container_width=True, hide_index=True)

        with st.expander("🔎 Ver pedidos de um departamento", expanded=False):
            sel_dept = st.selectbox(
                "Departamento",
                options=df_d["departamento"].fillna("(Sem dept)").astype(str).tolist(),
                key="rg_drill_dept",
            )
            df_det = df_base[df_base.get("departamento", "").astype(str) == str(sel_dept)].copy()
            if df_det.empty:
                st.warning("Sem pedidos para este departamento no período aplicado.")
            else:
                cols_det = _cols_detail(df_det, filtros.date_field)
                st.dataframe(df_det[cols_det], use_container_width=True, hide_index=True)
                csv_det, name_det = _download_df(df_det[cols_det], "pedidos_departamento", dt_ini, dt_fim)
                st.download_button("⬇️ Baixar pedidos (departamento)", csv_det, name_det, "text/csv", use_container_width=True)

        _render_common_actions(df_d, "gastos_por_departamento", dt_ini, dt_fim)
