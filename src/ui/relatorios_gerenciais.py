
from __future__ import annotations

import io
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st


# =============================================================================
# Utilitários (somente defs; nada executa no import)
# =============================================================================

def _col(df: pd.DataFrame, *cands: str) -> Optional[str]:
    if df is None or df.empty:
        return None
    cols = {c.lower(): c for c in df.columns}
    for c in cands:
        if c.lower() in cols:
            return cols[c.lower()]
    return None


def _to_num(s: pd.Series) -> pd.Series:
    try:
        return pd.to_numeric(s, errors="coerce").fillna(0.0)
    except Exception:
        return pd.Series([0.0] * len(s))


def _fmt_brl(v: float) -> str:
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"


def _iter_dict_records(x: Any) -> List[dict]:
    if x is None:
        return []
    try:
        if isinstance(x, pd.DataFrame):
            return x.to_dict("records")
    except Exception:
        pass
    if isinstance(x, dict):
        return [x]
    if isinstance(x, list):
        return [r for r in x if isinstance(r, dict)]
    return []


def _download_csv_button(df: pd.DataFrame, filename: str) -> None:
    if df is None or df.empty:
        st.caption("Sem dados para exportar.")
        return
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(
        "Baixar CSV",
        data=buf.getvalue().encode("utf-8"),
        file_name=f"{filename}.csv",
        mime="text/csv",
        use_container_width=True,
    )


def _apply_date_filter(df: pd.DataFrame, dt_ini: Optional[date], dt_fim: Optional[date]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    c_date = _col(df, "criado_em", "created_at", "data", "data_pedido", "dt_pedido", "data_emissao", "data_solicitacao")
    if not c_date:
        return df
    s = pd.to_datetime(df[c_date], errors="coerce").dt.date
    mask = pd.Series([True] * len(df))
    if dt_ini:
        mask &= (s >= dt_ini)
    if dt_fim:
        mask &= (s <= dt_fim)
    return df.loc[mask].copy()


# =============================================================================
# Supabase (admin) + loaders (alinhados com relatorios_whatsapp)
# =============================================================================

def _supabase_admin():
    """Cria client SUPABASE com SERVICE_ROLE para leituras administrativas (bypass RLS)."""
    # 1) tenta helper do projeto (se existir)
    try:
        from src.core.db import init_supabase_admin  # type: ignore
        admin = init_supabase_admin()
        if admin:
            return admin
    except Exception:
        pass

    # 2) tenta criar direto via secrets
    try:
        from supabase import create_client  # type: ignore
        url = st.secrets.get("SUPABASE_URL") if hasattr(st, "secrets") else None
        key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY") if hasattr(st, "secrets") else None
        if url and key:
            return create_client(url, key)
    except Exception:
        pass

    # 3) tenta via env
    try:
        from supabase import create_client  # type: ignore
        import os
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if url and key:
            return create_client(url, key)
    except Exception:
        pass

    return None


def _safe_table_select(supabase, table: str, select_cols: str, tenant_id: str, limit: int = 5000):
    try:
        q = supabase.table(table).select(select_cols)
        try:
            q = q.eq("tenant_id", tenant_id)
        except Exception:
            pass
        return q.limit(limit).execute()
    except Exception:
        return None


def _fetch_user_profiles_admin(admin, user_ids: list[str]) -> dict[str, dict]:
    if not admin or not user_ids:
        return {}

    # user_profiles (PK user_id)
    for cols in ["user_id, nome, email", "user_id, nome, email, whatsapp", "user_id, name, email"]:
        try:
            rows = (
                admin.table("user_profiles")
                .select(cols)
                .in_("user_id", user_ids)
                .limit(5000)
                .execute()
                .data
                or []
            )
            by = {}
            for r in rows:
                uid = r.get("user_id")
                if uid:
                    by[str(uid)] = {
                        "nome": r.get("nome") or r.get("name") or "",
                        "email": r.get("email") or "",
                        "whatsapp": r.get("whatsapp") or "",
                    }
            if by:
                return by
        except Exception:
            pass

    # usuarios (PK id)
    for cols in ["id, nome, email", "id, nome, email, whatsapp", "id, name, email"]:
        try:
            rows = (
                admin.table("usuarios")
                .select(cols)
                .in_("id", user_ids)
                .limit(5000)
                .execute()
                .data
                or []
            )
            by = {}
            for r in rows:
                uid = r.get("id")
                if uid:
                    by[str(uid)] = {
                        "nome": r.get("nome") or r.get("name") or "",
                        "email": r.get("email") or "",
                        "whatsapp": r.get("whatsapp") or "",
                    }
            if by:
                return by
        except Exception:
            pass

    return {}


def _load_tenant_users_admin(admin, tenant_id: str, roles: list[str] | None = None) -> list[dict]:
    if not admin or not tenant_id:
        return []
    q = admin.table("tenant_users").select("user_id, role").eq("tenant_id", tenant_id).limit(5000)
    if roles:
        try:
            q = q.in_("role", roles)
        except Exception:
            pass
    try:
        return q.execute().data or []
    except Exception:
        return []


def _try_load_links(supabase, tenant_id: str) -> Any:
    """
    Carrega vínculos dept -> gestor_user_id.

    Prioridade:
      1) gestor_departamentos (admin se possível)
      2) fallbacks de tabelas comuns
    """
    admin = _supabase_admin()

    # (1) gestor_departamentos (preferida)
    for client in (admin, supabase):
        if not client:
            continue
        try:
            rows = (
                client.table("gestor_departamentos")
                .select("id, tenant_id, departamento, gestor_user_id")
                .eq("tenant_id", tenant_id)
                .order("departamento")
                .limit(5000)
                .execute()
                .data
                or []
            )
            if rows:
                return rows
        except Exception:
            pass

    # (2) tentativa via tabelas comuns
    for table in ("departamentos_gestores", "dept_gestor_links", "departamento_gestor", "departamentos_usuarios"):
        for client in (admin, supabase):
            if not client:
                continue
            res = _safe_table_select(client, table, "*", tenant_id)
            data = getattr(res, "data", None) if res else None
            if isinstance(data, list) and len(data) > 0:
                return data

    return None


def _links_to_dept_map(links: Any) -> Dict[str, str]:
    """departamento -> gestor_user_id"""
    if isinstance(links, dict):
        out: Dict[str, str] = {}
        for k, v in links.items():
            if k is None or v is None:
                continue
            kk = str(k).strip()
            vv = str(v).strip()
            if kk and vv:
                out[kk] = vv
        return out

    out: Dict[str, str] = {}
    for r in _iter_dict_records(links):
        dept = (r.get("departamento") or r.get("dept") or r.get("department") or r.get("nome_departamento") or "").strip()
        gid = r.get("gestor_user_id") or r.get("gestor_id") or r.get("user_id") or r.get("usuario_id") or r.get("gestor")
        gid = (str(gid).strip() if gid is not None else "")
        if dept and gid:
            out[dept] = gid
    return out


def _try_load_user_map(supabase, tenant_id: str) -> Dict[str, Dict[str, str]]:
    """
    user_id -> {nome, email, role}
    Preferência: tenant_users + user_profiles via admin (bypass RLS).
    """
    admin = _supabase_admin()

    # (1) RPC opcional (se existir)
    try:
        res = supabase.rpc("rpc_tenant_members", {"p_tenant_id": tenant_id}).execute()
        rows = res.data or []
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            uid = r.get("user_id")
            if uid:
                out[str(uid)] = {
                    "nome": (r.get("nome") or r.get("name") or "").strip(),
                    "email": (r.get("email") or "").strip(),
                    "role": (r.get("role") or "").strip(),
                }
        if out:
            return out
    except Exception:
        pass

    # (2) admin: tenant_users + user_profiles
    tu_rows = _load_tenant_users_admin(admin, tenant_id) if admin else []
    if tu_rows:
        user_ids = [str(r.get("user_id")) for r in tu_rows if r.get("user_id")]
        prof = _fetch_user_profiles_admin(admin, user_ids) if user_ids else {}
        role_by = {str(r.get("user_id")): (r.get("role") or "") for r in tu_rows if r.get("user_id")}

        out: Dict[str, Dict[str, str]] = {}
        for uid in user_ids:
            p = prof.get(uid) or {}
            out[uid] = {
                "nome": (p.get("nome") or "").strip(),
                "email": (p.get("email") or "").strip(),
                "role": (role_by.get(uid) or "").strip(),
            }
        out = {k: v for k, v in out.items() if (v.get("nome") or v.get("email") or v.get("role"))}
        if out:
            return out

    # (3) fallback: user_profiles (sem role)
    for client in (admin, supabase):
        if not client:
            continue
        for cols in ("user_id,nome,email,tenant_id", "user_id,nome,email", "user_id,name,email"):
            try:
                q = client.table("user_profiles").select(cols).limit(5000)
                try:
                    q = q.eq("tenant_id", tenant_id)
                except Exception:
                    pass
                rows = q.execute().data or []
                out: Dict[str, Dict[str, str]] = {}
                for r in rows:
                    uid = r.get("user_id")
                    if uid:
                        out[str(uid)] = {
                            "nome": (r.get("nome") or r.get("name") or "").strip(),
                            "email": (r.get("email") or "").strip(),
                            "role": "",
                        }
                if out:
                    return out
            except Exception:
                pass

    return {}


# =============================================================================
# Identificação do gestor (ALINHADA ao seu schema: criado_por + dept_map)
# =============================================================================

def _ensure_gestor_cols(df: pd.DataFrame, dept_map: Dict[str, str], user_map: Dict[str, Dict[str, str]]) -> pd.DataFrame:
    """
    Garante df["gestor_user_id"], df["gestor_nome"], df["gestor_role"].

    Ordem:
      1) Se já existir nome direto no pedido -> usa.
      2) Se existir criado_por -> usa como gestor principal.
      3) Se não tiver criado_por, tenta vínculo por departamento (dept_map).
      4) fallback: "—"
    """
    if df is None or df.empty:
        return df

    # 1) nome direto no pedido (se algum dia existir)
    c_gestor_nome = _col(df, "gestor_nome", "gestor", "responsavel", "responsavel_nome", "comprador_nome", "buyer_name")
    if c_gestor_nome:
        df["gestor_user_id"] = pd.NA
        df["gestor_nome"] = (
            df[c_gestor_nome]
            .astype(str)
            .replace("nan", "")
            .fillna("")
            .apply(lambda x: x.strip() or "—")
        )
        df["gestor_role"] = "—"
        return df

    # 2) criado_por (seu caso atual)
    if "criado_por" in df.columns:
        df["gestor_user_id"] = df["criado_por"].astype(str)
        if user_map:
            df["gestor_nome"] = df["gestor_user_id"].map(lambda x: (user_map.get(str(x)) or {}).get("nome", "")).replace("", "—")
            df["gestor_role"] = df["gestor_user_id"].map(lambda x: (user_map.get(str(x)) or {}).get("role", "")).replace("", "—")
        else:
            df["gestor_nome"] = "—"
            df["gestor_role"] = "—"
        return df

    # 3) dept_map fallback
    c_dept = _col(df, "departamento", "dept", "department")
    if c_dept and dept_map:
        df["gestor_user_id"] = df[c_dept].astype(str).map(lambda x: dept_map.get(str(x).strip(), "")).replace("", pd.NA)
        if user_map:
            df["gestor_nome"] = df["gestor_user_id"].map(lambda x: (user_map.get(str(x)) or {}).get("nome", "")).replace("", "—")
            df["gestor_role"] = df["gestor_user_id"].map(lambda x: (user_map.get(str(x)) or {}).get("role", "")).replace("", "—")
        else:
            df["gestor_nome"] = "—"
            df["gestor_role"] = "—"
        return df

    df["gestor_user_id"] = pd.NA
    df["gestor_nome"] = "—"
    df["gestor_role"] = "—"
    return df


def _debug_panel(df_base: pd.DataFrame, links: Any, dept_map: Dict[str, str], user_map: Dict[str, Dict[str, str]]) -> None:
    with st.expander("🧪 Diagnóstico (admin/dev)", expanded=False):
        st.caption("Confirme as fontes: gestor_departamentos, tenant_users e user_profiles.")
        st.write("Colunas em df_base:", list(df_base.columns))
        st.write("Tipo de links:", type(links).__name__)
        st.write("dept_map (tamanho):", len(dept_map))
        if len(dept_map) > 0:
            st.write("dept_map (amostra):", dict(list(dept_map.items())[:5]))
        st.write("user_map (tamanho):", len(user_map))
        if len(user_map) > 0:
            # amostra com role
            sample = {k: user_map[k] for k in list(user_map.keys())[:5]}
            st.write("user_map (amostra):", sample)


# =============================================================================
# UI principal
# =============================================================================

def render_relatorios_gerenciais(supabase, tenant_id: str) -> None:
    st.title("📑 Relatórios Gerenciais")

    # ---------- Base (pedidos) ----------
    try:
        from src.repositories.pedidos import carregar_pedidos  # type: ignore
        df_base = carregar_pedidos(supabase, tenant_id)
    except Exception:
        df_base = pd.DataFrame()

    if df_base is None or not isinstance(df_base, pd.DataFrame) or df_base.empty:
        st.info("Sem pedidos para a empresa/período selecionado.")
        return

    # ---------- Links e usuários ----------
    links = _try_load_links(supabase, tenant_id)
    dept_map = _links_to_dept_map(links)
    user_map = _try_load_user_map(supabase, tenant_id)

    # ---------- Filtros ----------
    with st.sidebar:
        st.markdown("### 🎛️ Filtros do relatório")
        hoje = date.today()
        dt_ini = st.date_input("Data inicial", value=hoje - timedelta(days=30), key="rg_dt_ini")
        dt_fim = st.date_input("Data final", value=hoje, key="rg_dt_fim")

        st.markdown("---")
        st.markdown("### 👥 Filtro de Pessoas")
        role_opts = sorted({(v.get("role") or "").strip() for v in user_map.values() if (v.get("role") or "").strip()})
        default_roles = [r for r in role_opts if r in ("gestor", "admin")] or role_opts
        roles_sel = st.multiselect("Roles incluídos (aba Gestor)", options=role_opts, default=default_roles, key="rg_roles")
        busca_nome = st.text_input("Buscar gestor (nome/email)", value="", key="rg_busca_gestor")

        st.markdown("---")
        show_diag = st.checkbox("Mostrar diagnóstico", value=False, key="rg_show_diag")

    df = _apply_date_filter(df_base, dt_ini, dt_fim)

    # ---------- Colunas principais ----------
    c_val = _col(df, "valor_total", "valor", "total", "valor_pedido", "valor_ultima_compra")
    if not c_val:
        df["valor_total"] = 0.0
        c_val = "valor_total"

    df = _ensure_gestor_cols(df, dept_map, user_map)

    # ---------- KPIs gerais ----------
    total = float(_to_num(df[c_val]).sum())
    qtd = int(len(df))
    k1, k2, k3 = st.columns(3)
    with k1:
        st.metric("Total (R$)", _fmt_brl(total))
    with k2:
        st.metric("Pedidos", str(qtd))
    with k3:
        st.metric("Ticket médio (R$)", _fmt_brl(total / max(qtd, 1)))

    if show_diag:
        _debug_panel(df_base=df_base, links=links, dept_map=dept_map, user_map=user_map)

    tab_g, tab_f, tab_d = st.tabs(["👤 Por Gestor", "🚜 Por Frota", "🏭 Por Departamento"])

    # =============================================================================
    # Aba: Por Gestor (refeita)
    # =============================================================================
    with tab_g:
        st.subheader("Gastos por Gestor")

        dfg = df.copy()
        dfg[c_val] = _to_num(dfg[c_val])

        # aplica filtro de roles (se houver)
        if roles_sel:
            dfg = dfg[dfg["gestor_role"].astype(str).isin(set(roles_sel))].copy()

        # prepara texto de busca (nome/email)
        if busca_nome.strip():
            q = busca_nome.strip().lower()
            # cria coluna email do gestor via user_map (best effort)
            dfg["gestor_email"] = dfg["gestor_user_id"].map(lambda x: (user_map.get(str(x)) or {}).get("email", ""))
            mask = (
                dfg["gestor_nome"].astype(str).str.lower().str.contains(q, na=False)
                | dfg["gestor_email"].astype(str).str.lower().str.contains(q, na=False)
            )
            dfg = dfg[mask].copy()

        if dfg.empty:
            st.info("Sem dados para os filtros selecionados (roles/busca/período).")
        else:
            # tabela gerencial completa
            g = (
                dfg.groupby(["gestor_user_id", "gestor_nome", "gestor_role"], dropna=False)
                .agg(
                    pedidos=("id", "count"),
                    total=(c_val, "sum"),
                )
                .reset_index()
            )
            g["ticket_medio"] = (g["total"] / g["pedidos"].clip(lower=1)).astype(float)
            total_geral = float(g["total"].sum())
            g["%_do_total"] = (g["total"] / (total_geral if total_geral else 1.0)) * 100.0
            g = g.sort_values(["total", "pedidos"], ascending=[False, False], kind="stable")

            # formatação
            g_view = g.copy()
            g_view["total"] = g_view["total"].map(_fmt_brl)
            g_view["ticket_medio"] = g_view["ticket_medio"].map(_fmt_brl)
            g_view["%_do_total"] = g_view["%_do_total"].map(lambda x: f"{x:.1f}%")

            # KPIs da aba
            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.metric("Gestores", str(g.shape[0]))
            with k2:
                st.metric("Total (R$)", _fmt_brl(total_geral))
            with k3:
                st.metric("Pedidos", str(int(g["pedidos"].sum())))
            with k4:
                st.metric("Ticket médio (R$)", _fmt_brl(float(g["total"].sum()) / max(int(g["pedidos"].sum()), 1)))

            st.dataframe(
                g_view[["gestor_nome", "gestor_role", "pedidos", "total", "ticket_medio", "%_do_total"]],
                use_container_width=True,
                hide_index=True,
            )

            # gráfico Top N
            top_n = st.slider("Top N gestores (gráfico)", min_value=5, max_value=30, value=15, step=1, key="rg_topn")
            g_top = g.head(top_n).copy()
            st.bar_chart(g_top.set_index("gestor_nome")["total"], height=280)

            # export
            _download_csv_button(g, "gastos_por_gestor")

            # drilldown melhorado
            with st.expander("🔎 Drill-down (selecionar gestor)", expanded=False):
                options = g[["gestor_user_id", "gestor_nome", "gestor_role"]].copy()
                options["label"] = options.apply(lambda r: f"{r['gestor_nome']} ({r['gestor_role']})", axis=1)

                label_list = options["label"].tolist()
                label = st.selectbox("Gestor", options=["(selecione)"] + label_list, key="rg_drill_gestor")
                if label and label != "(selecione)":
                    sel_row = options[options["label"] == label].iloc[0]
                    uid = str(sel_row["gestor_user_id"])

                    df_sel = dfg[dfg["gestor_user_id"].astype(str) == uid].copy()
                    total_sel = float(df_sel[c_val].sum())
                    st.caption(f"Pedidos: {len(df_sel)} • Total R$ {_fmt_brl(total_sel)} • Ticket médio R$ {_fmt_brl(total_sel / max(len(df_sel), 1))}")

                    # tabela enxuta (campos mais úteis)
                    cols_pref = [
                        "nr_solicitacao", "nr_oc", "departamento", "cod_equipamento", "cod_material",
                        "descricao", "status", "prazo_entrega", "previsao_entrega", "data_entrega_real",
                        "valor_total", "fornecedor_nome", "criado_em"
                    ]
                    show_cols = [c for c in cols_pref if c in df_sel.columns]
                    if not show_cols:
                        show_cols = list(df_sel.columns)

                    st.dataframe(df_sel[show_cols], use_container_width=True, hide_index=True)
                    _download_csv_button(df_sel, f"pedidos_gestor_{sel_row['gestor_nome']}".replace(" ", "_"))

        # aviso inteligente quando tudo é "—"
        # (mesmo com filtros/roles, isso pode indicar que user_map não carregou por RLS/secrets)
        if "gestor_nome" in df.columns:
            only_dash = df["gestor_nome"].astype(str).nunique(dropna=False) == 1 and df["gestor_nome"].astype(str).iloc[0] == "—"
            if only_dash:
                st.warning(
                    "Ainda não foi possível resolver nomes de gestores. "
                    "Verifique se o app tem acesso a tenant_users e user_profiles (ideal: SERVICE_ROLE nos secrets)."
                )

    # =============================================================================
    # Aba: Por Frota
    # =============================================================================
    with tab_f:
        st.subheader("Gastos por Frota")
        c_frota = _col(df, "frota", "equipamento", "maquina", "cod_equipamento")
        if not c_frota:
            st.info("Não encontrei coluna de Frota/Equipamento na base de pedidos.")
        else:
            f = (
                df.assign(_v=_to_num(df[c_val]))
                .groupby(c_frota, dropna=False)["_v"]
                .sum()
                .reset_index()
                .rename(columns={c_frota: "frota", "_v": "total"})
                .sort_values("total", ascending=False, kind="stable")
            )
            f_view = f.copy()
            f_view["total"] = f_view["total"].map(_fmt_brl)
            st.dataframe(f_view, use_container_width=True, hide_index=True)
            st.bar_chart(f.set_index("frota")["total"].head(20), height=280)
            _download_csv_button(f, "gastos_por_frota")

            with st.expander("🔎 Drill-down (selecionar frota)", expanded=False):
                frotas = f["frota"].astype(str).tolist() if not f.empty else []
                sel = st.selectbox("Frota", options=["(selecione)"] + frotas, key="rg_drill_frota")
                if sel and sel != "(selecione)":
                    df_sel = df[df[c_frota].astype(str) == sel].copy()
                    total_sel = float(_to_num(df_sel[c_val]).sum())
                    st.caption(f"Pedidos: {len(df_sel)} • Total R$ {_fmt_brl(total_sel)}")
                    st.dataframe(df_sel, use_container_width=True, hide_index=True)
                    _download_csv_button(df_sel, f"pedidos_frota_{sel}".replace(" ", "_"))

    # =============================================================================
    # Aba: Por Departamento
    # =============================================================================
    with tab_d:
        st.subheader("Gastos por Departamento")
        c_dept = _col(df, "departamento", "dept", "department")
        if not c_dept:
            st.info("Não encontrei coluna de Departamento na base de pedidos.")
        else:
            d = (
                df.assign(_v=_to_num(df[c_val]))
                .groupby(c_dept, dropna=False)["_v"]
                .sum()
                .reset_index()
                .rename(columns={c_dept: "departamento", "_v": "total"})
                .sort_values("total", ascending=False, kind="stable")
            )
            d_view = d.copy()
            d_view["total"] = d_view["total"].map(_fmt_brl)
            st.dataframe(d_view, use_container_width=True, hide_index=True)
            st.bar_chart(d.set_index("departamento")["total"].head(20), height=280)
            _download_csv_button(d, "gastos_por_departamento")

            with st.expander("🔎 Drill-down (selecionar departamento)", expanded=False):
                depts = d["departamento"].astype(str).tolist() if not d.empty else []
                sel = st.selectbox("Departamento", options=["(selecione)"] + depts, key="rg_drill_dept")
                if sel and sel != "(selecione)":
                    df_sel = df[df[c_dept].astype(str) == sel].copy()
                    total_sel = float(_to_num(df_sel[c_val]).sum())
                    st.caption(f"Pedidos: {len(df_sel)} • Total R$ {_fmt_brl(total_sel)}")
                    st.dataframe(df_sel, use_container_width=True, hide_index=True)
                    _download_csv_button(df_sel, f"pedidos_dept_{sel}".replace(" ", "_"))
