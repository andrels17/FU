from __future__ import annotations

import pandas as pd
import streamlit as st

from src.services import observabilidade as obs
from src.services.saas_metrics import (
    build_tenant_health_row,
    list_tenants,
    tenant_display_name,
)


def exibir_saude_tenants(supabase_admin):
    st.title("Saúde por Tenant")
    st.caption("Painel Superadmin: volume, usuários, pendências e valor total por empresa. (Best-effort)")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        filtro = st.text_input("Buscar empresa/tenant", value="")
    with col2:
        limite = st.number_input("Limite", min_value=10, max_value=500, value=100, step=10)
    with col3:
        if st.button("Atualizar", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=300)
    def _load_tenants():
        return list_tenants(supabase_admin)

    tenants = _load_tenants()
    if not tenants:
        st.warning("Não foi possível listar tenants (verifique a tabela `tenants` e permissões do SERVICE ROLE).")
        return

    # filtrar
    if filtro.strip():
        f = filtro.strip().lower()
        tenants = [t for t in tenants if f in tenant_display_name(t).lower() or f in str(t.get("id", "")).lower()]

    tenants = tenants[: int(limite)]

    rows = []
    prog = st.progress(0)
    for i, t in enumerate(tenants, start=1):
        tid = str(t.get("id"))
        with obs.time_block("saas.health.tenant", context={"tenant_id": tid}):
            r = build_tenant_health_row(supabase_admin, tid)
        r["empresa"] = tenant_display_name(t)
        rows.append(r)
        prog.progress(i / max(len(tenants), 1))

    df = pd.DataFrame(rows)
    if df.empty:
        st.info("Sem dados para exibir.")
        return

    # ordenar por volume de pedidos (desc)
    if "pedidos" in df.columns:
        df = df.sort_values(by="pedidos", ascending=False, na_position="last")

    # KPIs topo
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tenants", len(df))
    c2.metric("Pedidos (soma)", int(df["pedidos"].fillna(0).sum()) if "pedidos" in df.columns else "N/A")
    c3.metric("Pendentes (soma)", int(df["pendentes"].fillna(0).sum()) if "pendentes" in df.columns else "N/A")
    c4.metric("Usuários (soma)", int(df["usuarios"].fillna(0).sum()) if "usuarios" in df.columns else "N/A")

    st.dataframe(
        df[["empresa", "tenant_id", "usuarios", "pedidos", "pendentes", "fornecedores", "valor_total"]],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")
    st.subheader("Ações")
    st.caption("Exporta um snapshot do estado atual.")

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Baixar CSV",
        data=csv,
        file_name="saude_tenants.csv",
        mime="text/csv",
        use_container_width=True,
    )
