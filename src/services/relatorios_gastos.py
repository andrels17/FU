"""Serviços de relatórios gerenciais (gastos) para Follow-up SaaS.

Objetivo: centralizar filtros e agregações para evitar lógica duplicada nas UIs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

import pandas as pd
import streamlit as st


DateField = Literal["data_solicitacao", "data_oc", "data_entrega_real", "criado_em"]


@dataclass(frozen=True)
class FiltrosGastos:
    dt_ini: date
    dt_fim: date
    date_field: DateField = "data_solicitacao"
    entregue: Optional[bool] = None  # None=todos; True=entregues; False=pendentes
    departamentos: Optional[list[str]] = None
    cod_equipamentos: Optional[list[str]] = None


def _normalize_text_series(s: pd.Series) -> pd.Series:
    try:
        return s.astype(str).fillna("").str.strip()
    except Exception:
        return s


def _safe_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([0.0] * len(df), index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


@st.cache_data(ttl=60, show_spinner=False)
def carregar_links_departamento_gestor(_supabase, tenant_id: str) -> pd.DataFrame:
    """Carrega vínculos departamento -> gestor_user_id (tabela gestor_departamentos)."""
    try:
        res = (
            _supabase.table("gestor_departamentos")
            .select("departamento,gestor_user_id")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        df = pd.DataFrame(res.data or [])
    except Exception:
        df = pd.DataFrame()

    if df.empty:
        return pd.DataFrame(columns=["departamento", "gestor_user_id"])

    df["departamento"] = _normalize_text_series(df["departamento"])
    df = df[df["departamento"] != ""].copy()
    return df


@st.cache_data(ttl=60, show_spinner=False)
def carregar_mapa_usuarios_tenant(_supabase, tenant_id: str) -> pd.DataFrame:
    """Retorna user_id, nome, email, whatsapp para membros do tenant.

    Tenta RPC rpc_tenant_members; se não retornar nada, faz fallback via tabelas.
    """
    # 1) RPC
    try:
        r = _supabase.rpc("rpc_tenant_members", {"p_tenant_id": tenant_id}).execute()
        data = r.data or []
        df = pd.DataFrame(data)
    except Exception:
        df = pd.DataFrame()

    # Normaliza colunas esperadas (nomes variam conforme RPC)
    if not df.empty:
        # tenta detectar o campo de id
        if "user_id" not in df.columns and "id" in df.columns:
            df = df.rename(columns={"id": "user_id"})
        # garante colunas
        for c in ["user_id", "nome", "email", "whatsapp", "role"]:
            if c not in df.columns:
                df[c] = None
        return df[["user_id", "nome", "email", "whatsapp", "role"]].copy()

    # 2) Fallback: tenant_users + user_profiles (sem depender de RLS => caller decide qual client)
    try:
        tu = (
            _supabase.table("tenant_users")
            .select("user_id,role")
            .eq("tenant_id", tenant_id)
            .execute()
        ).data or []
        user_ids = [x.get("user_id") for x in tu if x.get("user_id")]
        if not user_ids:
            return pd.DataFrame(columns=["user_id", "nome", "email", "whatsapp", "role"])

        prof = (
            _supabase.table("user_profiles")
            .select("user_id,nome,email,whatsapp")
            .in_("user_id", user_ids)
            .execute()
        ).data or []

        dfp = pd.DataFrame(prof)
        dftu = pd.DataFrame(tu)

        if dfp.empty:
            dfp = pd.DataFrame(columns=["user_id", "nome", "email", "whatsapp"])
        if dftu.empty:
            dftu = pd.DataFrame(columns=["user_id", "role"])

        out = dftu.merge(dfp, on="user_id", how="left")
        for c in ["nome", "email", "whatsapp"]:
            if c not in out.columns:
                out[c] = None
        return out[["user_id", "nome", "email", "whatsapp", "role"]].copy()
    except Exception:
        return pd.DataFrame(columns=["user_id", "nome", "email", "whatsapp", "role"])


def filtrar_pedidos_base(df_pedidos: pd.DataFrame, filtros: FiltrosGastos) -> pd.DataFrame:
    """Aplica filtros comuns e retorna dataframe pronto para agregação."""
    if df_pedidos is None or df_pedidos.empty:
        return pd.DataFrame()

    df = df_pedidos.copy()

    # Campos esperados
    if "departamento" not in df.columns:
        df["departamento"] = ""
    if "cod_equipamento" not in df.columns:
        df["cod_equipamento"] = ""

    # Normalizações
    df["departamento"] = _normalize_text_series(df["departamento"])
    df["cod_equipamento"] = _normalize_text_series(df["cod_equipamento"])

    # Date field
    date_field = filtros.date_field
    if date_field not in df.columns:
        # fallback: tenta criado_em
        date_field = "criado_em" if "criado_em" in df.columns else filtros.date_field

    if date_field in df.columns:
        df[date_field] = pd.to_datetime(df[date_field], errors="coerce")
        dt_ini = pd.to_datetime(filtros.dt_ini)
        dt_fim = pd.to_datetime(filtros.dt_fim) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df[(df[date_field].notna()) & (df[date_field] >= dt_ini) & (df[date_field] <= dt_fim)].copy()

    # Entregue
    if filtros.entregue is not None and "entregue" in df.columns:
        df = df[df["entregue"].astype(bool) == bool(filtros.entregue)].copy()

    # Departamentos
    if filtros.departamentos:
        allowed = set([d.strip() for d in filtros.departamentos if str(d).strip()])
        df = df[df["departamento"].isin(allowed)].copy()

    # Frota (cod_equipamento)
    if filtros.cod_equipamentos:
        allowed = set([c.strip() for c in filtros.cod_equipamentos if str(c).strip()])
        df = df[df["cod_equipamento"].isin(allowed)].copy()

    # Valor
    if "valor_total" not in df.columns:
        # tenta fallback comum
        if "valor" in df.columns:
            df["valor_total"] = _safe_numeric(df, "valor")
        else:
            df["valor_total"] = 0.0
    else:
        df["valor_total"] = _safe_numeric(df, "valor_total")

    return df


def gastos_por_departamento(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["departamento", "qtd_pedidos", "total"])
    g = df.groupby("departamento", dropna=False).agg(
        qtd_pedidos=("id", "count") if "id" in df.columns else ("departamento", "size"),
        total=("valor_total", "sum"),
    ).reset_index()
    g = g[g["departamento"].astype(str).str.strip() != ""].copy()
    g = g.sort_values(["total"], ascending=False)
    return g


def gastos_por_frota(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["cod_equipamento", "qtd_pedidos", "total"])
    g = df.groupby("cod_equipamento", dropna=False).agg(
        qtd_pedidos=("id", "count") if "id" in df.columns else ("cod_equipamento", "size"),
        total=("valor_total", "sum"),
    ).reset_index()
    g = g[g["cod_equipamento"].astype(str).str.strip() != ""].copy()
    g = g.sort_values(["total"], ascending=False)
    return g


def gastos_por_gestor(df: pd.DataFrame, links_dept_gestor: pd.DataFrame, user_map: pd.DataFrame) -> pd.DataFrame:
    """Agrega por gestor_user_id a partir do vínculo departamento->gestor."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["gestor_user_id", "gestor_nome", "gestor_email", "qtd_pedidos", "total", "departamentos"])

    if links_dept_gestor is None or links_dept_gestor.empty:
        # Sem vínculo -> não consegue atribuir gestor
        return pd.DataFrame(columns=["gestor_user_id", "gestor_nome", "gestor_email", "qtd_pedidos", "total", "departamentos"])

    tmp = df.merge(
        links_dept_gestor[["departamento", "gestor_user_id"]],
        on="departamento",
        how="left",
    )
    tmp = tmp[tmp["gestor_user_id"].notna()].copy()

    if tmp.empty:
        return pd.DataFrame(columns=["gestor_user_id", "gestor_nome", "gestor_email", "qtd_pedidos", "total", "departamentos"])

    # Nome/email
    um = user_map.copy() if user_map is not None else pd.DataFrame()
    if not um.empty:
        if "user_id" in um.columns:
            um = um.rename(columns={"user_id": "gestor_user_id"})
        for c in ["gestor_user_id", "nome", "email"]:
            if c not in um.columns:
                um[c] = None
        tmp = tmp.merge(um[["gestor_user_id", "nome", "email"]].rename(columns={"nome": "gestor_nome", "email": "gestor_email"}), on="gestor_user_id", how="left")

    agg = tmp.groupby("gestor_user_id", dropna=False).agg(
        qtd_pedidos=("id", "count") if "id" in tmp.columns else ("departamento", "size"),
        total=("valor_total", "sum"),
        departamentos=("departamento", lambda s: ", ".join(sorted(set([str(x).strip() for x in s if str(x).strip()])))),
    ).reset_index()

    # adiciona nome/email se não veio no merge
    if "gestor_nome" not in agg.columns:
        agg["gestor_nome"] = None
    if "gestor_email" not in agg.columns:
        agg["gestor_email"] = None
    # Se veio pelo merge, preservar:
    if "gestor_nome" in tmp.columns:
        nm = tmp[["gestor_user_id", "gestor_nome", "gestor_email"]].drop_duplicates()
        agg = agg.merge(nm, on="gestor_user_id", how="left", suffixes=("", "_x"))
        # resolver duplicadas
        if "gestor_nome_x" in agg.columns:
            agg["gestor_nome"] = agg["gestor_nome"].fillna(agg["gestor_nome_x"])
            agg = agg.drop(columns=["gestor_nome_x"])
        if "gestor_email_x" in agg.columns:
            agg["gestor_email"] = agg["gestor_email"].fillna(agg["gestor_email_x"])
            agg = agg.drop(columns=["gestor_email_x"])

    agg = agg.sort_values(["total"], ascending=False)
    return agg
