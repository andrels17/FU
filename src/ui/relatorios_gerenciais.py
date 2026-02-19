from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Tuple


def _premium_tabs_style() -> None:
    st.markdown(
        """
        <style>
        div[data-baseweb="tab-list"] { gap: 8px; }
        button[role="tab"] {
            padding: 10px 14px;
            border-radius: 999px;
            border: 1px solid rgba(49,51,63,0.18);
            background: rgba(255,255,255,0.04);
        }
        button[role="tab"][aria-selected="true"] {
            border: 1px solid rgba(49,51,63,0.32);
            background: rgba(255,255,255,0.10);
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _reset_rg_filters() -> None:
    """Reseta filtros dos Relatórios Gerenciais (session_state)."""
    keys = [
        "rg_dt_ini", "rg_dt_fim", "rg_date_field_label", "rg_entregue_label",
        "rg_depts", "rg_frotas", "rg_roles_incluidos", "rg_busca_gestor",
        "rg_cmp_gestor", "rg_cmp_frota", "rg_cmp_dept",
        "rg_drill_gestor_nome", "rg_top_dept_insights", "rg_top_dept_tab",
        "rg_gestor_top", "rg_frota_top", "rg_dept_top",
        "rg_cmp_gestor", "rg_cmp_frota", "rg_cmp_dept",
        "rg_fg_familia", "rg_fg_grupo"
    ]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]


def _actions_bar(df_base: pd.DataFrame, dt_ini: date, dt_fim: date, prefix: str) -> None:
    """Barra de ações rápidas (export / reset)."""
    with st.container(border=True):
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            csv = df_base.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Exportar base filtrada",
                csv,
                _download_name(f"{prefix}_base_filtrada", dt_ini, dt_fim),
                "text/csv",
                use_container_width=True,
                key=f"{prefix}_export_base",
            )
        with c2:
            if st.button("♻️ Reset filtros", use_container_width=True, key=f"{prefix}_reset"):
                _reset_rg_filters()
                st.rerun()
        with c3:
            st.caption("Dica: use os filtros na lateral e exporte a base filtrada para análises externas.")

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
    return hoje - timedelta(days=30), hoje




def _cat_str(v: Any) -> str:
    """Força rótulo categórico (evita eixo numérico em ids como 1024, 5001)."""
    if v is None:
        return "(Sem código)"
    s = str(v).strip()
    return s if s else "(Sem código)"
def _as_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _share_percent(total: float, part: float) -> float:
    return (part / total * 100.0) if total else 0.0


def _download_name(prefix: str, dt_ini: date, dt_fim: date) -> str:
    return f"{prefix}_{dt_ini.isoformat()}_a_{dt_fim.isoformat()}.csv"


def _pill_style() -> None:
    st.markdown(
        """
        <style>
        div[data-baseweb="select"] > div { min-height: 38px; }
        </style>
        """,
        unsafe_allow_html=True,
    )



def _tabs_style() -> None:
    # Deixa as abas com visual mais premium (pills, borda, espaçamento)
    st.markdown(
        '''
        <style>
        /* Tabs container */
        div[data-baseweb="tab-list"]{
            gap: 10px;
            background: rgba(255,255,255,0.03);
            padding: 10px 10px 6px 10px;
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.06);
        }
        /* Tab */
        button[data-baseweb="tab"]{
            background: rgba(255,255,255,0.04);
            border-radius: 999px;
            padding: 10px 14px;
            border: 1px solid rgba(255,255,255,0.08);
            color: rgba(255,255,255,0.85);
            font-weight: 600;
        }
        /* Active tab */
        button[data-baseweb="tab"][aria-selected="true"]{
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.14);
        }
        /* Remove default underline indicator */
        div[data-baseweb="tab-highlight"]{ display:none; }
        </style>
        ''',
        unsafe_allow_html=True,
    )


def _plot_hbar_with_labels(df: pd.DataFrame, y_col: str, x_col: str, title: str, height: int = 420) -> None:
    """Gráfico de barras horizontal com rótulos (Plotly) e fallback."""
    if df is None or df.empty or y_col not in df.columns or x_col not in df.columns:
        st.caption("Sem dados para o gráfico.")
        return

    dfp = df.copy()
    # garante rótulos categóricos (evita eixo numérico para IDs)
    dfp[y_col] = dfp[y_col].astype(str)
    # rótulo BRL quando for total; senão, formata número simples
    if x_col == "total":
        dfp["_lbl"] = dfp[x_col].apply(lambda v: formatar_moeda_br(_as_float(v)))
    else:
        dfp["_lbl"] = dfp[x_col].apply(lambda v: f"{_as_float(v):,.0f}".replace(",", "."))

    try:
        import plotly.express as px  # type: ignore

        fig = px.bar(
            dfp,
            x=x_col,
            y=y_col,
            orientation="h",
            title=title,
            text="_lbl",
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        fig.update_yaxes(type="category")
        fig.update_layout(
            margin=dict(l=10, r=10, t=46, b=10),
            height=height,
            yaxis_title="",
            xaxis_title="",
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        st.bar_chart(dfp.set_index(y_col)[[x_col]], height=min(300, height))



def _init_filter_state() -> None:
    dt_ini_def, dt_fim_def = _date_defaults()
    st.session_state.setdefault("rg_dt_ini", dt_ini_def)
    st.session_state.setdefault("rg_dt_fim", dt_fim_def)
    st.session_state.setdefault("rg_date_field_label", "Solicitação")
    st.session_state.setdefault("rg_entregue_label", "Todos")
    st.session_state.setdefault("rg_depts", [])
    st.session_state.setdefault("rg_frotas", [])
    st.session_state.setdefault("rg_roles_incluidos", ["admin", "gestor"])
    st.session_state.setdefault("rg_busca_gestor", "")


def _build_filtros_from_state() -> Tuple[FiltrosGastos, date, date]:
    date_field_map = {
        "Solicitação": "data_solicitacao",
        "OC": "data_oc",
        "Entrega real": "data_entrega_real",
        "Criação": "criado_em",
    }
    dt_ini: date = st.session_state.get("rg_dt_ini")
    dt_fim: date = st.session_state.get("rg_dt_fim")
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
    if not dt_ini or not dt_fim or dt_fim < dt_ini:
        return dt_ini, dt_fim
    dias = (dt_fim - dt_ini).days
    dt_fim_prev = dt_ini - timedelta(days=1)
    dt_ini_prev = dt_fim_prev - timedelta(days=dias)
    return dt_ini_prev, dt_fim_prev


def _evolucao_semanal(df_base: pd.DataFrame, date_col: str) -> pd.DataFrame:
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
    return out.rename(columns={"_data": "data", "_valor": "total"})


def _cols_detail(df: pd.DataFrame, date_field: str) -> List[str]:
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
        "fornecedor_nome"
    ]
    return [c for c in prefer if c in df.columns]


def _top_selector(prefix: str) -> int | None:
    opt = st.radio(
        "Exibir",
        ["Top 10", "Top 20", "Top 50", "Todos"],
        horizontal=True,
        key=f"{prefix}_top",
        index=0,
    )
    return {"Top 10": 10, "Top 20": 20, "Top 50": 50}.get(opt, None)


def _render_common_actions(df_out: pd.DataFrame, filename_prefix: str, dt_ini: date, dt_fim: date) -> None:
    csv = df_out.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Baixar CSV",
        csv,
        _download_name(filename_prefix, dt_ini, dt_fim),
        "text/csv",
        use_container_width=True,
    )


def _links_to_dept_map_df(links: Any) -> pd.DataFrame:
    """
    Normaliza links para DataFrame com colunas: departamento, gestor_user_id.
    O serviço gastos_por_gestor exige DataFrame. 
    """
    if links is None:
        return pd.DataFrame(columns=["departamento", "gestor_user_id"])
    if isinstance(links, pd.DataFrame):
        if links.empty:
            return pd.DataFrame(columns=["departamento", "gestor_user_id"])
        cols = set(links.columns)
        if {"departamento", "gestor_user_id"}.issubset(cols):
            return links[["departamento", "gestor_user_id"]].copy()
        return pd.DataFrame(links.to_dict("records")).reindex(columns=["departamento", "gestor_user_id"])
    if isinstance(links, dict):
        rows = [{"departamento": str(k).strip(), "gestor_user_id": v} for k, v in links.items() if str(k).strip()]
        return pd.DataFrame(rows).reindex(columns=["departamento", "gestor_user_id"])
    if isinstance(links, list):
        rows = [r for r in links if isinstance(r, dict)]
        return pd.DataFrame(rows).reindex(columns=["departamento", "gestor_user_id"])
    return pd.DataFrame(columns=["departamento", "gestor_user_id"])


def _ensure_user_map_df(user_map: Any) -> pd.DataFrame:
    """
    Normaliza user_map para DataFrame com colunas:
      user_id, nome, email, whatsapp, role
    O serviço gastos_por_gestor usa .empty e merge, então precisa DF. 
    """
    if user_map is None:
        return pd.DataFrame(columns=["user_id", "nome", "email", "whatsapp", "role"])
    if isinstance(user_map, pd.DataFrame):
        df = user_map.copy()
        if "user_id" not in df.columns and "id" in df.columns:
            df = df.rename(columns={"id": "user_id"})
        for c in ["user_id", "nome", "email", "whatsapp", "role"]:
            if c not in df.columns:
                df[c] = None
        return df[["user_id", "nome", "email", "whatsapp", "role"]].copy()
    if isinstance(user_map, dict):
        rows = []
        for uid, v in user_map.items():
            if isinstance(v, dict):
                rows.append(
                    {
                        "user_id": uid,
                        "nome": v.get("nome") or v.get("name"),
                        "email": v.get("email"),
                        "whatsapp": v.get("whatsapp"),
                        "role": v.get("role"),
                    }
                )
            else:
                rows.append({"user_id": uid, "nome": str(v), "email": None, "whatsapp": None, "role": None})
        return pd.DataFrame(rows).reindex(columns=["user_id", "nome", "email", "whatsapp", "role"])
    if isinstance(user_map, list):
        rows = [r for r in user_map if isinstance(r, dict)]
        df = pd.DataFrame(rows)
        if "user_id" not in df.columns and "id" in df.columns:
            df = df.rename(columns={"id": "user_id"})
        for c in ["user_id", "nome", "email", "whatsapp", "role"]:
            if c not in df.columns:
                df[c] = None
        return df[["user_id", "nome", "email", "whatsapp", "role"]].copy()
    return pd.DataFrame(columns=["user_id", "nome", "email", "whatsapp", "role"])


def _safe_gastos_por_gestor(df_base: pd.DataFrame, links: Any, user_map: Any) -> pd.DataFrame:
    """
    Chama o serviço gastos_por_gestor com os tipos corretos (DataFrames). 
    """
    links_df = _links_to_dept_map_df(links)
    user_df = _ensure_user_map_df(user_map)
    return gastos_por_gestor(df_base, links_df, user_df)


def _add_prev_delta(df_now: pd.DataFrame, df_prev_group: pd.DataFrame, key_col: str) -> pd.DataFrame:
    if df_now is None or df_now.empty:
        return df_now
    if df_prev_group is None or df_prev_group.empty or key_col not in df_prev_group.columns:
        df_now["prev_total"] = 0.0
        df_now["delta_pct"] = 0.0
        return df_now

    prev = df_prev_group[[key_col, "total"]].copy().rename(columns={"total": "prev_total"})
    out = df_now.merge(prev, how="left", on=key_col)

    out["prev_total"] = pd.to_numeric(out.get("prev_total", 0), errors="coerce").fillna(0.0)
    out["total"] = pd.to_numeric(out.get("total", 0), errors="coerce").fillna(0.0)
    out["delta_pct"] = out.apply(
        lambda r: ((r["total"] - r["prev_total"]) / r["prev_total"] * 100.0) if r["prev_total"] else 0.0,
        axis=1,
    )
    return out




def _gastos_por_familia_grupo(df_base: pd.DataFrame) -> pd.DataFrame:
    """Agrupa gastos por família e grupo (usa colunas vindas do catálogo/material)."""
    if df_base is None or df_base.empty:
        return pd.DataFrame(columns=["familia_descricao", "grupo_descricao", "qtd_pedidos", "total"])

    fam_col = "familia_descricao" if "familia_descricao" in df_base.columns else None
    grp_col = "grupo_descricao" if "grupo_descricao" in df_base.columns else None

    if not fam_col and not grp_col:
        return pd.DataFrame(columns=["familia_descricao", "grupo_descricao", "qtd_pedidos", "total"])

    tmp = df_base.copy()
    if fam_col:
        tmp[fam_col] = tmp[fam_col].fillna("Sem família").astype(str).str.strip()
        tmp.loc[tmp[fam_col] == "", fam_col] = "Sem família"
    else:
        tmp["familia_descricao"] = "Sem família"
        fam_col = "familia_descricao"

    if grp_col:
        tmp[grp_col] = tmp[grp_col].fillna("Sem grupo").astype(str).str.strip()
        tmp.loc[tmp[grp_col] == "", grp_col] = "Sem grupo"
    else:
        tmp["grupo_descricao"] = "Sem grupo"
        grp_col = "grupo_descricao"

    tmp["_valor"] = pd.to_numeric(tmp.get("valor_total", 0), errors="coerce").fillna(0.0)

    out = (
        tmp.groupby([fam_col, grp_col])["_valor"]
        .agg(total="sum", qtd_pedidos="count")
        .reset_index()
        .rename(columns={fam_col: "familia_descricao", grp_col: "grupo_descricao"})
        .sort_values("total", ascending=False)
    )
    return out



def _materiais_mais_caros(df_base: pd.DataFrame, mode: str = "unit") -> pd.DataFrame:
    """Ranking de materiais.
    mode:
      - 'unit': maior valor_ultima_compra (ou proxy por valor_total/qtde_solicitada)
      - 'total': maior gasto total (soma valor_total)
    """
    if df_base is None or df_base.empty:
        return pd.DataFrame(columns=["cod_material", "descricao", "valor", "qtd_pedidos"])

    tmp = df_base.copy()

    tmp["cod_material"] = tmp.get("cod_material")
    tmp["descricao"] = tmp.get("descricao")

    v_unit = pd.to_numeric(tmp.get("valor_ultima_compra", None), errors="coerce")
    if v_unit is None or v_unit.isna().all():
        qt = pd.to_numeric(tmp.get("qtde_solicitada", 0), errors="coerce").replace(0, pd.NA)
        vtot = pd.to_numeric(tmp.get("valor_total", 0), errors="coerce")
        v_unit = (vtot / qt).astype(float)

    tmp["_v_unit"] = v_unit.fillna(0.0)
    tmp["_v_total"] = pd.to_numeric(tmp.get("valor_total", 0), errors="coerce").fillna(0.0)

    tmp["descricao"] = tmp["descricao"].fillna("").astype(str).str.strip()
    tmp["cod_material"] = tmp["cod_material"].fillna("").astype(str).str.strip()

    key_cols = ["cod_material", "descricao"]

    if mode == "total":
        out = (
            tmp.groupby(key_cols)["_v_total"]
            .agg(valor="sum", qtd_pedidos="count")
            .reset_index()
            .sort_values("valor", ascending=False)
        )
    else:
        out = (
            tmp.groupby(key_cols)["_v_unit"]
            .agg(valor="max", qtd_pedidos="count")
            .reset_index()
            .sort_values("valor", ascending=False)
        )

    return out

# ============================
# Main entry
# ============================

def render_relatorios_gerenciais(_supabase, tenant_id: str) -> None:
    st.title("📈 Relatórios Gerenciais")
    st.caption("Gestores por vínculo de departamento (gestor_departamentos) — não depende de quem lançou o pedido.")

    if not tenant_id:
        st.error("Tenant não identificado.")
        st.stop()

    _init_filter_state()
    _pill_style()

    _premium_tabs_style()
    _tabs_style()

    # Admin (service role) para leituras que podem sofrer RLS
    try:
        supabase_admin = init_supabase_admin()
    except Exception:
        supabase_admin = None

    # ===== Carregar pedidos =====
    with st.spinner("Carregando pedidos..."):
        df_pedidos = carregar_pedidos(_supabase, tenant_id=tenant_id)

    if df_pedidos is None or df_pedidos.empty:
        st.info("Nenhum pedido encontrado para este tenant.")
        st.stop()

    # opções para filtros
    df_tmp = df_pedidos.copy()
    for col in ["departamento", "cod_equipamento"]:
        if col in df_tmp.columns:
            df_tmp[col] = df_tmp[col].fillna("").astype(str).str.strip()
        else:
            df_tmp[col] = ""

    dept_opts = sorted([d for d in df_tmp["departamento"].unique().tolist() if d])
    frota_opts = sorted([f for f in df_tmp["cod_equipamento"].unique().tolist() if f])

    # ===== links + user_map (DataFrames, como o serviço espera) =====
    with st.spinner("Carregando vínculos e usuários..."):
        links_df = carregar_links_departamento_gestor(supabase_admin or _supabase, tenant_id=tenant_id)
        user_df = carregar_mapa_usuarios_tenant(supabase_admin or _supabase, tenant_id=tenant_id)

    links_df = _links_to_dept_map_df(links_df)
    user_df = _ensure_user_map_df(user_df)

    # dict dept->gestor para drilldown (rápido)
    dept_map: Dict[str, str] = {}
    if not links_df.empty:
        for _, r in links_df.iterrows():
            d = str(r.get("departamento") or "").strip()
            gid = r.get("gestor_user_id")
            if d and pd.notna(gid):
                dept_map[d] = str(gid)

    # ===== Sidebar =====
    with st.sidebar:
        st.markdown("### Filtros do relatório")

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
        st.markdown("### Filtro de Pessoas (aba Gestor)")

        roles = sorted([str(x).strip().lower() for x in user_df["role"].dropna().unique().tolist() if str(x).strip()]) if "role" in user_df.columns else []
        if not roles:
            roles = ["admin", "gestor", "user"]

        st.multiselect(
            "Roles incluídos",
            options=roles,
            default=[r for r in (st.session_state.get("rg_roles_incluidos") or []) if r in roles] or ["admin", "gestor"],
            key="rg_roles_incluidos",
        )
        st.text_input("Buscar gestor (nome/e-mail)", value=st.session_state.get("rg_busca_gestor", ""), key="rg_busca_gestor")

        st.caption(f"Deptos vinculados: {len(dept_map)} · Usuários no mapa: {len(user_df)}")

    # ===== Aplicar filtros =====
    filtros, dt_ini, dt_fim = _build_filtros_from_state()
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

    # ===== Menu de abas (no início) =====
    tab_resumo, tab_gestor, tab_frota, tab_dept, tab_materiais = st.tabs(["Resumo", "Gestor", "Frota", "Departamento", "Família & Grupo"])

    with tab_resumo:
        _actions_bar(df_base, dt_ini, dt_fim, prefix='rg_resumo')

        with st.container(border=True):
            st.markdown("### Resumo do período aplicado")
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
            st.markdown("### Evolução do gasto (semanal)")
            df_evol = _evolucao_semanal(df_base, filtros.date_field)
            if df_evol.empty:
                st.caption("Sem dados suficientes para a evolução semanal.")
            else:
                st.line_chart(df_evol.set_index("data")["total"])

        st.divider()

    
    
st.divider()

with st.container(border=True):
    st.markdown("### Materiais mais caros")
    c1, c2 = st.columns([2, 1])
    with c1:
        modo = st.radio(
            "Ranking por",
            ["Preço unitário (última compra)", "Gasto total (soma)"],
            index=0,
            horizontal=True,
            key="rg_caros_modo",
        )
    with c2:
        topn_caros = _top_selector("rg_caros")

    mode_key = "unit" if modo.startswith("Preço") else "total"
    df_caros = _materiais_mais_caros(df_base, mode=mode_key)

    if df_caros.empty:
        st.caption("Sem dados suficientes para ranquear materiais.")
    else:
        df_plot = df_caros.copy()
        df_plot["label"] = df_plot["cod_material"].astype(str) + " · " + df_plot["descricao"].astype(str)
        df_plot = df_plot.sort_values("valor", ascending=False)
        df_plot = df_plot.head(topn_caros) if topn_caros else df_plot

        titulo = "Top materiais por preço unitário" if mode_key == "unit" else "Top materiais por gasto total"
        _plot_hbar_with_labels(df_plot, y_col="label", x_col="valor", title=titulo, height=520)

        df_tbl = df_plot.copy()
        df_tbl["Valor"] = df_tbl["valor"].apply(lambda v: formatar_moeda_br(_as_float(v)))
        df_tbl["Pedidos"] = pd.to_numeric(df_tbl["qtd_pedidos"], errors="coerce").fillna(0).astype(int)

        st.dataframe(
            df_tbl[["cod_material", "descricao", "Pedidos", "Valor"]].rename(
                columns={"cod_material": "Cód. Material", "descricao": "Descrição"}
            ),
            use_container_width=True,
            hide_index=True,
        )

        # ===== Governança estrutural + Performance global =====
        with st.container(border=True):
            st.markdown("### Governança estrutural")
            # Departamentos presentes nos pedidos do período aplicado
            depts_base = set(df_base.get("departamento", pd.Series(dtype=str)).dropna().astype(str).str.strip().unique())
            depts_base = {d for d in depts_base if d}
            depts_vinculados = set(dept_map.keys())
            depts_sem_gestor = sorted(list(depts_base - depts_vinculados))

            # Gestores (no mapa) sem departamento vinculado
            gestores_ids = set(user_df.get("user_id", pd.Series(dtype=str)).dropna().astype(str).unique()) if "user_id" in user_df.columns else set()
            gestores_vinculados = set(str(v) for v in dept_map.values())
            gestores_sem_dept = sorted(list(gestores_ids - gestores_vinculados))

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Departamentos no período", len(depts_base))
            c2.metric("Deptos com gestor", len(depts_base & depts_vinculados))
            c3.metric("Deptos sem gestor", len(depts_sem_gestor))
            c4.metric("Gestores sem depto", len(gestores_sem_dept))

            colA, colB = st.columns(2)
            with colA:
                if depts_sem_gestor:
                    st.warning("Departamentos sem gestor vinculado")
                    st.dataframe(pd.DataFrame({"departamento": depts_sem_gestor}), use_container_width=True, hide_index=True)
                else:
                    st.success("Todos os departamentos do período têm gestor vinculado ")
            with colB:
                if gestores_sem_dept:
                    st.warning("Gestores no tenant sem departamento vinculado")
                    if "user_id" in user_df.columns:
                        df_gs = user_df[user_df["user_id"].astype(str).isin(gestores_sem_dept)].copy()
                        cols = [c for c in ["nome", "email", "role", "user_id"] if c in df_gs.columns]
                        st.dataframe(df_gs[cols], use_container_width=True, hide_index=True)
                    else:
                        st.write(gestores_sem_dept)
                else:
                    st.success("Sem gestores “órfãos” de departamento ")

        # Performance operacional (global)
        with st.container(border=True):
            st.markdown("### Performance operacional (visão geral)")
            col1, col2, col3 = st.columns(3)

            pct_atraso = None
            if "atrasado" in df_base.columns:
                s = pd.to_numeric(df_base["atrasado"], errors="coerce")
                if s.notna().any():
                    pct_atraso = float(s.fillna(0).mean() * 100)

            pct_pendente = None
            if "entregue" in df_base.columns:
                s = df_base["entregue"]
                # entregue pode vir bool, 't/f', 0/1…
                sb = s.apply(lambda x: bool(x) if isinstance(x, bool) else (str(x).strip().lower() in ("true","t","1","sim","s","yes")))
                pct_pendente = float((~sb).mean() * 100) if len(sb) else None

            # lead time (dias) se houver datas
            lt_med = None
            if "data_solicitacao" in df_base.columns and "data_entrega_real" in df_base.columns:
                ds = pd.to_datetime(df_base["data_solicitacao"], errors="coerce")
                de = pd.to_datetime(df_base["data_entrega_real"], errors="coerce")
                lt = (de - ds).dt.days
                lt = lt[lt.notna() & (lt >= 0)]
                if len(lt) > 0:
                    lt_med = float(lt.median())

            col1.metric("% Atraso", f"{pct_atraso:.1f}%" if pct_atraso is not None else "—")
            col2.metric("% Pendentes", f"{pct_pendente:.1f}%" if pct_pendente is not None else "—")
            col3.metric("Lead time mediano", f"{lt_med:.0f} dias" if lt_med is not None else "—")
        # (tabs moved to the beginning)
    

# ===== Aba Gestor =====
    with tab_gestor:
        _actions_bar(df_base, dt_ini, dt_fim, prefix='rg_gestor')

        st.subheader("Gastos por Coordenador")
        topn = _top_selector("rg_gestor")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_gestor")

        # Aqui é o ponto: usa vínculo dept->gestor (serviço) 
        df_g = _safe_gastos_por_gestor(df_base, links_df, user_df)

        if df_g.empty:
            st.info("Sem dados por Coordenador. Verifique se há vínculos em gestor_departamentos para os departamentos filtrados.")
            st.stop()

        # adiciona role via user_df
        um_role = user_df.copy()
        if "user_id" in um_role.columns:
            um_role = um_role.rename(columns={"user_id": "gestor_user_id"})
        if "role" not in um_role.columns:
            um_role["role"] = None
        df_g = df_g.merge(um_role[["gestor_user_id", "role"]].rename(columns={"role": "gestor_role"}), on="gestor_user_id", how="left")

        # filtro roles
        roles_incl = set([(r or "").lower() for r in (st.session_state.get("rg_roles_incluidos") or [])])
        if roles_incl and "gestor_role" in df_g.columns:
            df_g = df_g[df_g["gestor_role"].fillna("").astype(str).str.lower().isin(roles_incl)]

        # busca
        q = (st.session_state.get("rg_busca_gestor") or "").strip().lower()
        if q:
            df_g = df_g[
                df_g["gestor_nome"].fillna("").astype(str).str.lower().str.contains(q)
                | df_g["gestor_email"].fillna("").astype(str).str.lower().str.contains(q)
            ]

        if df_g.empty:
            st.warning("Nenhum coordenador após filtros de pessoas (roles/busca).")
            st.stop()

        # comparação
        if comparar:
            df_g_prev = _safe_gastos_por_gestor(df_prev, links_df, user_df) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if not df_g_prev.empty:
                df_g = _add_prev_delta(df_g, df_g_prev, "gestor_user_id")
            else:
                df_g["prev_total"] = 0.0
                df_g["delta_pct"] = 0.0
        else:
            df_g["prev_total"] = 0.0
            df_g["delta_pct"] = 0.0

        # KPIs
        with st.container(border=True):
            g1, g2, g3 = st.columns(3)
            g1.metric("Coordenadores no período", int(df_g["gestor_user_id"].nunique()))
            g2.metric("Gasto total", formatar_moeda_br(_as_float(df_g["total"].sum())))
            g3.metric("Pedidos", int(_as_float(df_g["qtd_pedidos"].sum())) if "qtd_pedidos" in df_g.columns else "-")

        df_g = df_g.copy()
        df_g["participacao_pct"] = df_g["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_g = df_g.sort_values("total", ascending=False)

        # ===== Gráfico principal =====
        df_plot = df_g.head(topn) if topn else df_g
        # garante uma coluna de rótulo para o eixo Y
        if "gestor_nome" not in df_plot.columns:
            if "gestor_email" in df_plot.columns:
                df_plot = df_plot.assign(gestor_nome=df_plot["gestor_email"].fillna("(Sem email)").astype(str))
            else:
                df_plot = df_plot.assign(gestor_nome=df_plot.get("gestor_user_id", "(Sem gestor)").astype(str))

        _plot_hbar_with_labels(
            df_plot,
            y_col="gestor_nome",
            x_col="total",
            title="Top Coordenadores por gasto",
            height=420,
        )

        with st.expander("Dados avançados", expanded=False):

            # ===== Inteligência gerencial (ranking + destaques) =====
            with st.container(border=True):
                st.markdown("### Ranking executivo")
                top3 = df_g.head(3).copy()
                cols = st.columns(3)

                for i in range(3):
                    if i >= len(top3):
                        cols[i].metric(f"#{i+1}", "—")
                        continue

                    r = top3.iloc[i]
                    delta_txt = None
                    if "delta_pct" in df_g.columns:
                        delta_txt = f"{_as_float(r.get('delta_pct')):.1f}%"

                    cols[i].metric(
                        f"#{i+1} {r.get('gestor_nome','(Sem nome)')}",
                        formatar_moeda_br(_as_float(r.get("total"))),
                        f"{_as_float(r.get('participacao_pct')):.1f}% do total"
                        + (f" · Δ {delta_txt}" if delta_txt else ""),
                    )

            # ===== Destaques (cresceu / caiu) =====
            if "delta_pct" in df_g.columns:
                alta = df_g[df_g["delta_pct"] > 20].copy()
                queda = df_g[df_g["delta_pct"] < -20].copy()

                if not alta.empty:
                    with st.container(border=True):
                        st.markdown("#### Crescimentos relevantes (> 20%)")
                        st.dataframe(
                            alta[["gestor_nome", "total", "prev_total", "delta_pct"]].assign(
                                total=lambda x: x["total"].map(lambda v: formatar_moeda_br(_as_float(v))),
                                prev_total=lambda x: x["prev_total"].map(lambda v: formatar_moeda_br(_as_float(v))),
                                delta_pct=lambda x: x["delta_pct"].map(lambda v: f"{_as_float(v):.1f}%"),
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                if not queda.empty:
                    with st.container(border=True):
                        st.markdown("#### Quedas relevantes (< -20%)")
                        st.dataframe(
                            queda[["gestor_nome", "total", "prev_total", "delta_pct"]].assign(
                                total=lambda x: x["total"].map(lambda v: formatar_moeda_br(_as_float(v))),
                                prev_total=lambda x: x["prev_total"].map(lambda v: formatar_moeda_br(_as_float(v))),
                                delta_pct=lambda x: x["delta_pct"].map(lambda v: f"{_as_float(v):.1f}%"),
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

            # ===== Insight automático =====
            try:
                top = df_g.iloc[0]
                st.info(
                    f"No período aplicado, **{top.get('gestor_nome','(Sem nome)')}** foi o coordenador com maior impacto, "
                    f"respondendo por **{_as_float(top.get('participacao_pct')):.1f}%** do gasto total."
                )
            except Exception:
                pass
            # (Top Departamentos movido para a aba Departamento)
        _render_common_actions(df_g, "gastos_por_gestor", dt_ini, dt_fim)

    # ===== Aba Frota =====
    with tab_frota:
        _actions_bar(df_base, dt_ini, dt_fim, prefix='rg_frota')

        st.subheader("Gastos por Frota (cód. equipamento)")
        topn = _top_selector("rg_frota")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_frota")

        df_f = gastos_por_frota(df_base)
        if df_f.empty:
            st.info("Sem dados para o agrupamento por Frota (cod_equipamento).")
            st.stop()

        if comparar:
            df_f_prev = gastos_por_frota(df_prev) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if not df_f_prev.empty and "cod_equipamento" in df_f.columns:
                df_f = _add_prev_delta(df_f, df_f_prev, "cod_equipamento")
            else:
                df_f["prev_total"] = 0.0
                df_f["delta_pct"] = 0.0
        else:
            df_f["prev_total"] = 0.0
            df_f["delta_pct"] = 0.0

        df_f = df_f.copy()
        df_f["participacao_pct"] = df_f["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_f = df_f.sort_values("total", ascending=False)

        df_plot = df_f.head(topn) if topn else df_f
        df_plot = df_plot.copy()
        if 'cod_equipamento' in df_plot.columns:
            df_plot['frota_label'] = df_plot['cod_equipamento'].map(_cat_str)
        else:
            df_plot['frota_label'] = '(Sem código)'
        _plot_hbar_with_labels(df_plot, y_col="frota_label", x_col="total", title="Top frotas por gasto", height=420)

        df_show = df_f.copy()
        df_show["Frota"] = df_show["cod_equipamento"].fillna("(Sem código)").astype(str)
        df_show["Pedidos"] = df_show.get("qtd_pedidos", 0).fillna(0).astype(int)
        df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
        df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{_as_float(x):.1f}%")

        cols = ["Frota", "Pedidos", "Total", "% do total"]
        if comparar:
            df_show["Anterior"] = df_show["prev_total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
            df_show["Δ%"] = df_show["delta_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
            cols = ["Frota", "Pedidos", "Total", "Anterior", "Δ%", "% do total"]

        st.dataframe(df_show[cols], use_container_width=True, hide_index=True)
        _render_common_actions(df_f, "gastos_por_frota", dt_ini, dt_fim)

    # ===== Aba Departamento =====
    with tab_dept:
        _actions_bar(df_base, dt_ini, dt_fim, prefix='rg_dept')

        st.subheader("Gastos por Departamento")

        with st.expander("Insights (Departamento)", expanded=False):
            with st.container(border=True):
                st.markdown("#### Top Departamentos (gasto)")
                tmp = df_base.copy()
                if "departamento" not in tmp.columns:
                    st.caption("Sem coluna 'departamento' na base.")
                else:
                    tmp["departamento"] = tmp["departamento"].fillna("").astype(str).str.strip()
                    tmp = tmp[tmp["departamento"].astype(str).str.strip() != ""]
                    tmp["_valor"] = pd.to_numeric(tmp.get("valor_total", 0), errors="coerce").fillna(0.0)

                    dept_total = tmp.groupby("departamento")["_valor"].sum().sort_values(ascending=False)
                    if dept_total.empty:
                        st.caption("Sem dados suficientes para listar departamentos.")
                    else:
                        top_n = st.slider("Top N departamentos", min_value=5, max_value=30, value=10, step=5, key="rg_top_dept_tab")
                        dept_top = dept_total.head(top_n).reset_index()
                        dept_top.columns = ["label", "total"]
                        dept_top["% do total"] = dept_top["total"].apply(lambda v: f"{_share_percent(total_geral, _as_float(v)):.1f}%")
                        dept_top["Total"] = dept_top["total"].apply(lambda v: formatar_moeda_br(_as_float(v)))

                        try:
                            _plot_hbar_with_labels(
                                dept_top,
                                y_col="label",
                                x_col="total",
                                title=f"Top {top_n} Departamentos — Gasto",
                                value_fmt="brl",
                            )
                        except Exception:
                            st.bar_chart(dept_top.set_index("label")[["total"]], height=260)

                        st.dataframe(
                            dept_top[["label", "Total", "% do total"]].rename(columns={"label": "Departamento"}),
                            use_container_width=True,
                            hide_index=True,
                        )

        topn = _top_selector("rg_dept")
        comparar = st.toggle("Comparar com período anterior", value=True, key="rg_cmp_dept")

        df_d = gastos_por_departamento(df_base)
        if df_d.empty:
            st.info("Sem dados para o agrupamento por Departamento.")
            st.stop()

        if comparar:
            df_d_prev = gastos_por_departamento(df_prev) if df_prev is not None and not df_prev.empty else pd.DataFrame()
            if not df_d_prev.empty and "departamento" in df_d.columns:
                df_d = _add_prev_delta(df_d, df_d_prev, "departamento")
            else:
                df_d["prev_total"] = 0.0
                df_d["delta_pct"] = 0.0
        else:
            df_d["prev_total"] = 0.0
            df_d["delta_pct"] = 0.0

        df_d = df_d.copy()
        df_d["participacao_pct"] = df_d["total"].apply(lambda v: _share_percent(total_geral, _as_float(v)))
        df_d = df_d.sort_values("total", ascending=False)

        df_plot = df_d.head(topn) if topn else df_d
        _plot_hbar_with_labels(df_plot, y_col="departamento", x_col="total", title="Top departamentos por gasto", height=420)

        df_show = df_d.copy()
        df_show["Departamento"] = df_show["departamento"].fillna("(Sem dept)").astype(str)
        df_show["Pedidos"] = df_show.get("qtd_pedidos", 0).fillna(0).astype(int)
        df_show["Total"] = df_show["total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
        df_show["% do total"] = df_show["participacao_pct"].apply(lambda x: f"{_as_float(x):.1f}%")

        cols = ["Departamento", "Pedidos", "Total", "% do total"]
        if comparar:
            df_show["Anterior"] = df_show["prev_total"].apply(lambda x: formatar_moeda_br(_as_float(x)))
            df_show["Δ%"] = df_show["delta_pct"].apply(lambda x: f"{_as_float(x):.1f}%")
            cols = ["Departamento", "Pedidos", "Total", "Anterior", "Δ%", "% do total"]

        st.dataframe(df_show[cols], use_container_width=True, hide_index=True)
        _render_common_actions(df_d, "gastos_por_departamento", dt_ini, dt_fim)
    # ===== Aba Família & Grupo =====

# ===== Aba Família & Grupo =====
with tab_materiais:
    _actions_bar(df_base, dt_ini, dt_fim, prefix="rg_familia_grupo")

    st.subheader("Gastos por Família e Grupo de Material")

    if ("familia_descricao" not in df_base.columns) and ("grupo_descricao" not in df_base.columns):
        st.info("Ainda não há colunas de Família/Grupo na base. Verifique se a view de pedidos já traz esses campos do catálogo de materiais.")
    else:
        df_scope = df_base.copy()

        with st.expander("Filtros adicionais (opcional)", expanded=False):
            c1, c2, c3 = st.columns([2, 2, 2])

            # Gestor (via vínculo dept->gestor)
            with c1:
                gestor_opts = [("Todos", "Todos")]
                if "gestor_user_id" in links_df.columns and "departamento" in links_df.columns:
                    gdf = links_df[["gestor_user_id"]].dropna().drop_duplicates()
                    if not gdf.empty and "user_id" in user_df.columns:
                        um = user_df.copy().rename(columns={"user_id": "gestor_user_id"})
                        gdf = gdf.merge(um[["gestor_user_id", "nome", "email"]], on="gestor_user_id", how="left")
                    for _, r in gdf.iterrows():
                        gid = r.get("gestor_user_id")
                        if gid is None:
                            continue
                        gid = str(gid)
                        nome = str(r.get("nome") or "").strip()
                        email = str(r.get("email") or "").strip()
                        label = nome or email or gid
                        gestor_opts.append((gid, label))

                gestor_sel = st.selectbox(
                    "Gestor",
                    options=gestor_opts,
                    index=0,
                    format_func=lambda x: x[1],
                    key="rg_fg_gestor",
                )

            # Departamento
            with c2:
                dept_opts = sorted([x for x in df_scope.get("departamento", pd.Series(dtype=str)).dropna().astype(str).str.strip().unique().tolist() if x])
                dept_sel = st.multiselect("Departamento", dept_opts, default=[], key="rg_fg_dept")

            # Frota (cód. equipamento)
            with c3:
                frota_opts = sorted([x for x in df_scope.get("cod_equipamento", pd.Series(dtype=str)).dropna().astype(str).str.strip().unique().tolist() if x])
                frota_sel = st.multiselect("Frota (cód. equipamento)", frota_opts, default=[], key="rg_fg_frota")

            # aplica gestor -> filtra por departamentos vinculados
            if gestor_sel and gestor_sel[0] != "Todos" and "departamento" in df_scope.columns and "gestor_user_id" in links_df.columns:
                depts_gestor = (
                    links_df[links_df["gestor_user_id"].astype(str) == str(gestor_sel[0])]
                    ["departamento"]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .tolist()
                )
                depts_gestor = [d for d in depts_gestor if d]
                if depts_gestor:
                    df_scope = df_scope[df_scope["departamento"].astype(str).isin(depts_gestor)]
                else:
                    df_scope = df_scope.iloc[0:0]

            if dept_sel and "departamento" in df_scope.columns:
                df_scope = df_scope[df_scope["departamento"].astype(str).isin([str(x) for x in dept_sel])]

            if frota_sel and "cod_equipamento" in df_scope.columns:
                df_scope = df_scope[df_scope["cod_equipamento"].astype(str).isin([str(x) for x in frota_sel])]

        vis = st.radio(
            "Visualização do gráfico",
            ["Junto (Família · Grupo)", "Separado (Famílias e Grupos)"],
            index=0,
            horizontal=True,
            key="rg_fg_vis",
        )

        df_fg = _gastos_por_familia_grupo(df_scope)
        if df_fg.empty:
            st.info("Sem dados para Família/Grupo no filtro atual.")
        else:
            c1, c2, c3 = st.columns([2, 2, 1])
            with c1:
                fam_opts = ["Todas"] + sorted([x for x in df_fg["familia_descricao"].dropna().unique().tolist()])
                fam_sel = st.selectbox("Família", fam_opts, index=0, key="rg_fg_familia")
            with c2:
                grp_base = df_fg.copy()
                if fam_sel != "Todas":
                    grp_base = grp_base[grp_base["familia_descricao"] == fam_sel]
                grp_opts = ["Todos"] + sorted([x for x in grp_base["grupo_descricao"].dropna().unique().tolist()])
                grp_sel = st.selectbox("Grupo", grp_opts, index=0, key="rg_fg_grupo")
            with c3:
                topn = _top_selector("rg_fg")

            df_show = df_fg.copy()
            if fam_sel != "Todas":
                df_show = df_show[df_show["familia_descricao"] == fam_sel]
            if grp_sel != "Todos":
                df_show = df_show[df_show["grupo_descricao"] == grp_sel]

            total_local = float(pd.to_numeric(df_show["total"], errors="coerce").fillna(0).sum())
            qtd_local = int(pd.to_numeric(df_show["qtd_pedidos"], errors="coerce").fillna(0).sum())

            k1, k2, k3 = st.columns(3)
            k1.metric("Gasto (seleção)", formatar_moeda_br(total_local))
            k2.metric("Pedidos (seleção)", f"{qtd_local:,}".replace(",", "."))
            k3.metric("Participação", f"{_share_percent(total_geral, total_local):.1f}%")

            st.divider()

            if vis.startswith("Junto"):
                df_plot = df_show.copy()
                df_plot["label"] = df_plot["familia_descricao"].astype(str) + " · " + df_plot["grupo_descricao"].astype(str)
                df_plot = df_plot.sort_values("total", ascending=False)
                df_plot = df_plot.head(topn) if topn else df_plot
                _plot_hbar_with_labels(df_plot, y_col="label", x_col="total", title="Top Família · Grupo por gasto", height=520)
            else:
                left, right = st.columns(2)
                with left:
                    df_fam = df_scope.copy()
                    df_fam["familia_descricao"] = df_fam.get("familia_descricao", "Sem família")
                    df_fam["familia_descricao"] = df_fam["familia_descricao"].fillna("Sem família").astype(str).str.strip()
                    df_fam["_valor"] = pd.to_numeric(df_fam.get("valor_total", 0), errors="coerce").fillna(0.0)
                    fam_agg = (
                        df_fam.groupby("familia_descricao")["_valor"]
                        .agg(total="sum", qtd_pedidos="count")
                        .reset_index()
                        .sort_values("total", ascending=False)
                    )
                    fam_agg = fam_agg.head(topn) if topn else fam_agg
                    _plot_hbar_with_labels(fam_agg, y_col="familia_descricao", x_col="total", title="Top Famílias por gasto", height=520)
                with right:
                    df_grp = df_scope.copy()
                    df_grp["grupo_descricao"] = df_grp.get("grupo_descricao", "Sem grupo")
                    df_grp["grupo_descricao"] = df_grp["grupo_descricao"].fillna("Sem grupo").astype(str).str.strip()
                    if fam_sel != "Todas":
                        df_grp["familia_descricao"] = df_grp.get("familia_descricao", "Sem família")
                        df_grp["familia_descricao"] = df_grp["familia_descricao"].fillna("Sem família").astype(str).str.strip()
                        df_grp = df_grp[df_grp["familia_descricao"] == fam_sel]
                    df_grp["_valor"] = pd.to_numeric(df_grp.get("valor_total", 0), errors="coerce").fillna(0.0)
                    grp_agg = (
                        df_grp.groupby("grupo_descricao")["_valor"]
                        .agg(total="sum", qtd_pedidos="count")
                        .reset_index()
                        .sort_values("total", ascending=False)
                    )
                    grp_agg = grp_agg.head(topn) if topn else grp_agg
                    _plot_hbar_with_labels(grp_agg, y_col="grupo_descricao", x_col="total", title="Top Grupos por gasto", height=520)

            df_tbl = df_show.copy()
            df_tbl["Total"] = df_tbl["total"].apply(lambda v: formatar_moeda_br(_as_float(v)))
            df_tbl["% do total"] = df_tbl["total"].apply(lambda v: f"{_share_percent(total_geral, _as_float(v)):.1f}%")
            df_tbl["Pedidos"] = pd.to_numeric(df_tbl["qtd_pedidos"], errors="coerce").fillna(0).astype(int)

            st.dataframe(
                df_tbl[["familia_descricao", "grupo_descricao", "Pedidos", "Total", "% do total"]].rename(
                    columns={"familia_descricao": "Família", "grupo_descricao": "Grupo"}
                ),
                use_container_width=True,
                hide_index=True,
            )

            _render_common_actions(df_show, "gastos_familia_grupo", dt_ini, dt_fim)
