from __future__ import annotations

import json
from datetime import date

import pandas as pd
import streamlit as st

from src.services.snapshots import gerar_snapshot_por_tenant, listar_snapshots
from src.ui.theme import section_header


def exibir_snapshots(supabase_admin) -> None:
    section_header("Snapshots", hint="Geração manual (Cloud-safe) e histórico por tenant")

    st.caption(
        "No Streamlit Cloud não há scheduler confiável nativo. "
        "Aqui você gera snapshots sob demanda (ideal: 1x/dia) e grava no banco."
    )

    c1, c2 = st.columns([2, 1])
    with c1:
        snap_date = st.date_input("Data do snapshot", value=date.today(), key="snap_date")
    with c2:
        if st.button("Gerar snapshot do dia", use_container_width=True, key="btn_gen_snapshot"):
            with st.spinner("Gerando snapshots por tenant..."):
                rows = gerar_snapshot_por_tenant(supabase_admin, snapshot_date=snap_date.isoformat())
            if rows:
                st.success(f"Snapshot gerado para {len(rows)} tenants.")
            else:
                st.warning("Nenhum tenant encontrado para gerar snapshot.")

    st.markdown("---")
    st.subheader("Histórico")
    data = listar_snapshots(supabase_admin)
    if not data:
        st.info("Sem snapshots ainda.")
        return

    # normaliza
    rows = []
    for r in data:
        metrics = r.get("metrics")
        if isinstance(metrics, str):
            try:
                metrics = json.loads(metrics)
            except Exception:
                metrics = {}
        rows.append(
            {
                "snapshot_date": r.get("snapshot_date"),
                "tenant_id": r.get("tenant_id"),
                "created_at": r.get("created_at"),
                "pedidos": (metrics or {}).get("pedidos"),
                "pendentes": (metrics or {}).get("pendentes"),
                "fornecedores": (metrics or {}).get("fornecedores"),
                "usuarios": (metrics or {}).get("usuarios"),
                "valor_total": (metrics or {}).get("valor_total"),
            }
        )

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # export
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Baixar CSV",
        data=csv,
        file_name="saas_snapshots.csv",
        mime="text/csv",
        use_container_width=True,
        key="snapshots_csv",
    )
