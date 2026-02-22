from __future__ import annotations

from datetime import date
import pandas as pd
import streamlit as st

from src.services.saas_metrics import (
    count_rows,
    list_tenants,
    period_bounds,
    sum_field,
    tenant_display_name,
)

from src.services.pdf_relatorio import gerar_pdf_executivo


def exibir_metricas_executivas(supabase_admin):
    st.title("Métricas Executivas")
    st.caption("Painel Superadmin: resumo por período (on-demand). Compatível com Streamlit Cloud.")

    period = st.selectbox("Período", ["Mês atual", "Últimos 7 dias", "Últimos 30 dias"], index=0)
    start, end = period_bounds(period)

    st.info(f"Período considerado: {start} até {end} (datas ISO).")

    tenants = list_tenants(supabase_admin)
    if not tenants:
        st.warning("Não foi possível listar tenants.")
        return

    # permite escolher um tenant ou 'Todos'
    opts = [("Todos", None)] + [(tenant_display_name(t), str(t.get("id"))) for t in tenants[:500]]
    label = st.selectbox("Empresa (opcional)", [o[0] for o in opts], index=0)
    tenant_id = None
    for n, tid in opts:
        if n == label:
            tenant_id = tid
            break

    date_field = st.selectbox(
        "Campo de data (pedidos)",
        ["atualizado_em", "criado_em", "data_oc", "data_solicitacao"],
        index=0,
        help="Escolha o campo que melhor representa o recorte temporal no seu banco.",
    )

    # KPIs gerais
    pedidos = count_rows(supabase_admin, "pedidos", tenant_id=tenant_id, date_field=date_field, start=start, end=end)
    pendentes = None
    try:
        q = supabase_admin.table("pedidos").select("id", count="exact")
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        q = q.eq("entregue", False)
        q = q.gte(date_field, start).lt(date_field, end)
        res = q.execute()
        pendentes = getattr(res, "count", None)
        if pendentes is None and hasattr(res, "data"):
            pendentes = len(res.data or [])
    except Exception:
        pendentes = None

    valor_total = sum_field(supabase_admin, "pedidos", "valor_total", tenant_id=tenant_id, date_field=date_field, start=start, end=end)

    c1, c2, c3 = st.columns(3)
    c1.metric("Pedidos", pedidos if pedidos is not None else "N/A")
    c2.metric("Pendentes", pendentes if pendentes is not None else "N/A")
    c3.metric("Valor total (soma)", f"{valor_total:,.2f}" if isinstance(valor_total, (int, float)) else "N/A")

    # PDF executivo (on-demand)
    with st.expander("📄 Exportar PDF executivo", expanded=False):
        st.caption("Gera um PDF simples com KPIs e (se disponível) a tabela de Top Departamentos. Cloud-safe.")
        pdf_nome = st.text_input(
            "Nome do arquivo",
            value=f"relatorio_executivo_{(tenant_id or 'todos')}_{start}_a_{end}.pdf".replace("/", "-"),
            key="exec_pdf_name",
        )
        if st.button("Gerar PDF", use_container_width=True, key="btn_exec_pdf"):
            # tenta reaproveitar agregação de departamentos (se existir no cache do expander abaixo)
            top_rows = st.session_state.get("_exec_top_dept_rows")
            top_header = st.session_state.get("_exec_top_dept_header")

            kpis = {
                "Empresa": label,
                "Período": f"{start} a {end}",
                "Pedidos": pedidos if pedidos is not None else "N/A",
                "Pendentes": pendentes if pendentes is not None else "N/A",
                "Valor total": f"{valor_total:,.2f}" if isinstance(valor_total, (int, float)) else "N/A",
                "Campo de data": date_field,
            }
            pdf_bytes = gerar_pdf_executivo(
                titulo="Relatório Executivo",
                subtitulo=f"{label} • {start} a {end}",
                kpis=kpis,
                tabela_header=top_header,
                tabela_linhas=top_rows,
            )
            st.download_button(
                "Baixar PDF",
                data=pdf_bytes,
                file_name=pdf_nome,
                mime="application/pdf",
                use_container_width=True,
                key="dl_exec_pdf",
            )

    st.markdown("---")
    st.subheader("Top Departamentos")
    st.caption("Agregação simples (best-effort). Se sua base for muito grande, considere criar uma view/RPC para agregados.")

    try:
        q = supabase_admin.table("pedidos").select("departamento, valor_total")
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        q = q.gte(date_field, start).lt(date_field, end).limit(10000)
        res = q.execute()
        data = res.data or []
        df = pd.DataFrame(data)
        if df.empty:
            st.info("Sem dados no período.")
        else:
            df["valor_total"] = pd.to_numeric(df.get("valor_total"), errors="coerce").fillna(0)
            g = df.groupby("departamento", dropna=False).agg(
                pedidos=("departamento", "size"),
                valor_total=("valor_total", "sum"),
            ).reset_index()
            g = g.sort_values(by="valor_total", ascending=False).head(15)
            st.dataframe(g, use_container_width=True, hide_index=True)

            # guarda para o PDF
            try:
                st.session_state["_exec_top_dept_header"] = ["Departamento", "Pedidos", "Valor total"]
                st.session_state["_exec_top_dept_rows"] = g[["departamento", "pedidos", "valor_total"]].values.tolist()
            except Exception:
                pass

            st.download_button(
                "Baixar CSV (departamentos)",
                data=g.to_csv(index=False).encode("utf-8"),
                file_name="exec_departamentos.csv",
                mime="text/csv",
                use_container_width=True,
            )
    except Exception as e:
        st.warning(f"Não foi possível gerar agregação por departamento: {e}")

    st.markdown("---")
    st.subheader("Exportar pedidos (amostra)")
    st.caption("Baixa um CSV com até 10.000 linhas do período (para análise externa).")

    try:
        q = supabase_admin.table("pedidos").select("*")
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        q = q.gte(date_field, start).lt(date_field, end).limit(10000)
        res = q.execute()
        dfp = pd.DataFrame(res.data or [])
        if dfp.empty:
            st.info("Sem pedidos no período.")
        else:
            st.dataframe(dfp.head(200), use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar CSV (pedidos)",
                data=dfp.to_csv(index=False).encode("utf-8"),
                file_name="exec_pedidos.csv",
                mime="text/csv",
                use_container_width=True,
            )
    except Exception as e:
        st.warning(f"Não foi possível exportar pedidos: {e}")
