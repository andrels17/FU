
from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

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
    c_date = _col(df, "criado_em", "created_at", "data", "data_pedido", "dt_pedido", "data_emissao")
    if not c_date:
        return df
    s = pd.to_datetime(df[c_date], errors="coerce").dt.date
    mask = pd.Series([True] * len(df))
    if dt_ini:
        mask &= (s >= dt_ini)
    if dt_fim:
        mask &= (s <= dt_fim)
    return df.loc[mask].copy()



def _supabase_admin():
    """Cria client SUPABASE com SERVICE_ROLE para leituras administrativas (bypass RLS).
    Requer SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY nos secrets/env.
    """
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

    # 3) tenta via env (Streamlit Cloud/GitHub)
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


def _fetch_user_profiles_admin(admin, user_ids: list[str]) -> dict[str, dict]:
    """Busca perfis (nome/email) de user_ids com tolerância a schema."""
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
                        "nome": r.get("nome") or r.get("name"),
                        "email": r.get("email"),
                        "whatsapp": r.get("whatsapp"),
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
                        "nome": r.get("nome") or r.get("name"),
                        "email": r.get("email"),
                        "whatsapp": r.get("whatsapp"),
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


def _safe_table_select(supabase, table: str, select_cols: str, tenant_id: str, limit: int = 5000):
    """Best-effort: tenta ler uma tabela no Supabase; se não existir/sem permissão, retorna None."""
    try:
        q = supabase.table(table).select(select_cols)
        # tenant_id pode se chamar tenant_id ou empresa_id; tentamos tenant_id primeiro
        try:
            q = q.eq("tenant_id", tenant_id)
        except Exception:
            pass
        return q.limit(limit).execute()
    except Exception:
        return None



def _try_load_links(supabase, tenant_id: str) -> Any:
    """
    Carrega vínculos dept -> gestor_user_id.

    Prioridade:
      1) Tabela padrão do projeto: gestor_departamentos (admin se possível)
      2) Fallbacks: outras tabelas comuns (admin se possível; senão, client do usuário)
      3) Repositórios/funções antigas (se existirem)
    """
    admin = _supabase_admin()

    # (1) gestor_departamentos (preferida)
    for client in (admin, supabase):
        if not client:
            continue
        try:
            rows = (
                client.table("gestor_departamentos")
                .select("id, departamento, gestor_user_id")
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

    # (3) tentativa via repositórios/funções (se existirem no projeto)
    candidates = [
        ("src.repositories.departamentos", "carregar_links_departamentos"),
        ("src.repositories.dept_gestor_links", "carregar_links"),
        ("src.services.departamentos", "carregar_links_departamentos"),
    ]
    for mod_name, fn_name in candidates:
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name)
            out = fn(supabase, tenant_id)
            # se veio algo útil, retorna
            if out is not None:
                if isinstance(out, (list, dict)) and len(out) > 0:
                    return out
                # DataFrame
                try:
                    import pandas as pd  # noqa
                    if isinstance(out, pd.DataFrame) and not out.empty:
                        return out
                except Exception:
                    pass
        except Exception:
            pass

    return None



def _links_to_dept_map(links: Any) -> Dict[str, str]:
    """
    Converte links em mapa departamento -> gestor_user_id (string).
    Aceita: dict | list[dict] | DataFrame.
    """
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
    Carrega mapa user_id -> {nome, email, role}.
    Preferência: tenant_users + user_profiles (admin se possível).
    """
    admin = _supabase_admin()

    # (1) via RPC (se existir) no client do usuário
    try:
        res = supabase.rpc("rpc_tenant_members", {"p_tenant_id": tenant_id}).execute()
        rows = res.data or []
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            uid = r.get("user_id")
            if uid:
                out[str(uid)] = {
                    "nome": r.get("nome") or r.get("name") or "",
                    "email": r.get("email") or "",
                    "role": r.get("role") or "",
                }
        if out:
            return out
    except Exception:
        pass

    # (2) via admin: tenant_users + user_profiles
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
        # remove vazios
        out = {k: v for k, v in out.items() if (v.get("nome") or v.get("email") or v.get("role"))}
        if out:
            return out

    # (3) fallback simples: tentar ler user_profiles filtrando por tenant_id (se existir coluna)
    for client in (admin, supabase):
        if not client:
            continue
        # user_profiles com user_id + nome + email
        for cols in ("user_id,nome,email,tenant_id", "user_id,nome,email", "user_id,name,email"):
            try:
                q = client.table("user_profiles").select(cols).limit(5000)
                try:
                    q = q.eq("tenant_id", tenant_id)  # se a coluna existir
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



def _ensure_gestor_cols(df: pd.DataFrame, dept_map: Dict[str, str], user_map: Dict[str, str]) -> pd.DataFrame:
    """
    Garante df["gestor_user_id"] e df["gestor_nome"] quando possível.
    Estratégia:
      1) Se já existe gestor_nome/gestor -> usa.
      2) Se existe gestor_user_id -> mapeia para nome usando user_map.
      3) Se não existe, tenta criar gestor_user_id via dept_map + departamento.
    """
    if df is None or df.empty:
        return df

    # 1) Se já existe nome do gestor na base de pedidos, use-o
    c_gestor_nome = _col(df, "gestor_nome", "gestor", "responsavel", "responsavel_nome", "comprador_nome", "buyer_name")
    if c_gestor_nome:
        df["gestor_nome"] = df[c_gestor_nome].astype(str).replace("nan", "").fillna("").apply(lambda x: x.strip() or "—")
        return df

    # 2) Se existe ID do gestor na base, mapear pra nome
    c_gid = _col(df, "gestor_user_id", "gestor_id", "responsavel_id", "buyer_id", "usuario_responsavel_id")
    if c_gid:
        df["gestor_user_id"] = df[c_gid].astype(str)
        if user_map:
            df["gestor_nome"] = df["gestor_user_id"].map(lambda x: (user_map.get(str(x)) or {}).get('nome','')).replace("", "—")
        else:
            df["gestor_nome"] = "—"
        return df

    # 3) Se não tem ID, tenta derivar do dept_map
    c_dept = _col(df, "departamento", "dept", "department")
    if c_dept and dept_map:
        df["gestor_user_id"] = df[c_dept].astype(str).map(lambda x: dept_map.get(str(x).strip(), "")).replace("", pd.NA)
        if user_map:
            df["gestor_nome"] = df["gestor_user_id"].map(lambda x: (user_map.get(str(x)) or {}).get('nome','')).replace("", "—")
        else:
            df["gestor_nome"] = df["gestor_user_id"].fillna("—").astype(str).replace("nan", "—")
        return df

    # fallback
    df["gestor_nome"] = "—"
    return df


def _group_sum(df: pd.DataFrame, key_col: str, val_col: str) -> pd.DataFrame:
    if df is None or df.empty or not key_col or not val_col:
        return pd.DataFrame(columns=[key_col, "total"])
    d = df.copy()
    d[key_col] = d[key_col].fillna("—").astype(str).replace("nan", "—")
    d[val_col] = _to_num(d[val_col])
    out = d.groupby(key_col, dropna=False)[val_col].sum().reset_index().rename(columns={val_col: "total"})
    out = out.sort_values("total", ascending=False, kind="stable")
    return out


def _debug_panel(df_base: pd.DataFrame, links: Any, dept_map: Dict[str, str], user_map: Dict[str, str]) -> None:
    with st.expander("🧪 Diagnóstico (admin/dev)", expanded=False):
        st.caption("Isso ajuda a confirmar se o mapeamento de gestor está vindo de pedidos, vínculos (dept→gestor) ou usuários.")
        st.write("Colunas em df_base:", list(df_base.columns))
        st.write("Tipo de links:", type(links).__name__)
        st.write("dept_map (tamanho):", len(dept_map))
        if len(dept_map) > 0:
            st.write("dept_map (amostra):", dict(list(dept_map.items())[:5]))
        st.write("user_map (tamanho):", len(user_map))
        if len(user_map) > 0:
            st.write("user_map (amostra):", dict(list(user_map.items())[:5]))


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

    # user_map pode falhar por RLS; ainda assim o app funciona (vai cair em '—')
    user_map = _try_load_user_map(supabase, tenant_id)

    # ---------- Filtros ----------
    with st.sidebar:
        st.markdown("### 🎛️ Filtros do relatório")
        hoje = date.today()
        dt_ini = st.date_input("Data inicial", value=hoje - timedelta(days=30), key="rg_dt_ini")
        dt_fim = st.date_input("Data final", value=hoje, key="rg_dt_fim")

    df = _apply_date_filter(df_base, dt_ini, dt_fim)

    # ---------- Colunas principais ----------
    c_val = _col(df, "valor_total", "valor", "total", "valor_pedido")
    if not c_val:
        df["valor_total"] = 0.0
        c_val = "valor_total"

    df = _ensure_gestor_cols(df, dept_map, user_map)

    # ---------- KPIs ----------
    total = float(_to_num(df[c_val]).sum())
    qtd = int(len(df))
    k1, k2 = st.columns(2)
    with k1:
        st.metric("Total (R$)", _fmt_brl(total))
    with k2:
        st.metric("Pedidos", str(qtd))

    # diagnóstico opcional
    # (mostra mesmo para user; se quiser limitar para admin, você pode checar perfil no session_state)
    _debug_panel(df_base=df_base, links=links, dept_map=dept_map, user_map=user_map)

    tab_g, tab_f, tab_d = st.tabs(["👤 Por Gestor", "🚜 Por Frota", "🏭 Por Departamento"])

    # ---------- Aba: Por Gestor ----------
    with tab_g:
        st.subheader("Gastos por Gestor")

        g = _group_sum(df, "gestor_nome", c_val)
        g["total"] = g["total"].astype(float)
        st.dataframe(g, use_container_width=True, hide_index=True)

        # gráfico simples (melhora leitura)
        if not g.empty:
            chart = g.set_index("gestor_nome")["total"]
            st.bar_chart(chart, height=260)

        _download_csv_button(g, "gastos_por_gestor")

        # drill-down
        with st.expander("🔎 Drill-down (selecionar gestor)", expanded=False):
            gestores = g["gestor_nome"].tolist() if not g.empty else []
            sel = st.selectbox("Gestor", options=["(selecione)"] + gestores, key="rg_drill_gestor")
            if sel and sel != "(selecione)":
                df_sel = df[df["gestor_nome"].astype(str) == sel].copy()
                st.caption(f"Pedidos do gestor: {sel} • {len(df_sel)} itens • Total R$ {_fmt_brl(float(_to_num(df_sel[c_val]).sum()))}")
                st.dataframe(df_sel, use_container_width=True, hide_index=True)
                _download_csv_button(df_sel, f"pedidos_gestor_{sel}".replace(" ", "_"))

        # alerta inteligente: quando tudo caiu em "—"
        if (len(g) == 1) and (str(g.iloc[0]["gestor_nome"]) == "—"):
            st.warning(
                "Nenhum gestor foi identificado nos dados. "
                "Isso normalmente acontece quando a base de pedidos não tem (gestor_nome / gestor_user_id) "
                "e os vínculos dept→gestor ou o mapa de usuários não estão acessíveis (RLS). "
                "Veja '🧪 Diagnóstico' acima para saber o que está faltando."
            )

    # ---------- Aba: Por Frota ----------
    with tab_f:
        st.subheader("Gastos por Frota")
        c_frota = _col(df, "frota", "equipamento", "maquina")
        if not c_frota:
            st.info("Não encontrei coluna de Frota/Equipamento na base de pedidos.")
        else:
            f = _group_sum(df, c_frota, c_val).rename(columns={c_frota: "frota"})
            f["total"] = f["total"].astype(float)
            st.dataframe(f, use_container_width=True, hide_index=True)
            if not f.empty:
                st.bar_chart(f.set_index("frota")["total"], height=260)
            _download_csv_button(f, "gastos_por_frota")

            with st.expander("🔎 Drill-down (selecionar frota)", expanded=False):
                frotas = f["frota"].tolist() if not f.empty else []
                sel = st.selectbox("Frota", options=["(selecione)"] + frotas, key="rg_drill_frota")
                if sel and sel != "(selecione)":
                    df_sel = df[df[c_frota].astype(str) == sel].copy()
                    st.caption(f"Pedidos da frota: {sel} • {len(df_sel)} itens • Total R$ {_fmt_brl(float(_to_num(df_sel[c_val]).sum()))}")
                    st.dataframe(df_sel, use_container_width=True, hide_index=True)
                    _download_csv_button(df_sel, f"pedidos_frota_{sel}".replace(" ", "_"))

    # ---------- Aba: Por Departamento ----------
    with tab_d:
        st.subheader("Gastos por Departamento")
        c_dept = _col(df, "departamento", "dept", "department")
        if not c_dept:
            st.info("Não encontrei coluna de Departamento na base de pedidos.")
        else:
            d = _group_sum(df, c_dept, c_val).rename(columns={c_dept: "departamento"})
            d["total"] = d["total"].astype(float)
            st.dataframe(d, use_container_width=True, hide_index=True)
            if not d.empty:
                st.bar_chart(d.set_index("departamento")["total"], height=260)
            _download_csv_button(d, "gastos_por_departamento")

            with st.expander("🔎 Drill-down (selecionar departamento)", expanded=False):
                depts = d["departamento"].tolist() if not d.empty else []
                sel = st.selectbox("Departamento", options=["(selecione)"] + depts, key="rg_drill_dept")
                if sel and sel != "(selecione)":
                    df_sel = df[df[c_dept].astype(str) == sel].copy()
                    st.caption(f"Pedidos do depto: {sel} • {len(df_sel)} itens • Total R$ {_fmt_brl(float(_to_num(df_sel[c_val]).sum()))}")
                    st.dataframe(df_sel, use_container_width=True, hide_index=True)
                    _download_csv_button(df_sel, f"pedidos_dept_{sel}".replace(" ", "_"))

