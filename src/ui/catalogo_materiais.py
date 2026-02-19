import pandas as pd
import streamlit as st

def exibir_catalogo_materiais(supabase, tenant_id):

    st.title("📦 Catálogo de Materiais")

    uploaded = st.file_uploader("Importar CSV de Materiais", type=["csv"])

    if uploaded:

        try:
            df = pd.read_csv(uploaded, sep=",", encoding="utf-8")

            st.write("Pré-visualização:")
            st.dataframe(df.head())

            if st.button("Processar Importação"):

                registros = df.to_dict(orient="records")

                inseridos = 0
                atualizados = 0

                for row in registros:

                    codigo = int(row["Código"])

                    payload = {
                        "tenant_id": tenant_id,
                        "codigo_material": codigo,
                        "descricao": row.get("Descrição Material"),
                        "unidade": row.get("Unid."),
                        "familia_codigo": row.get("Família"),
                        "familia_descricao": row.get("Descrição Família Material"),
                        "grupo_codigo": row.get("Grupo"),
                        "grupo_descricao": row.get("Descrição Grupo do Material"),
                        "tipo_material": row.get("Tipo Material"),
                        "almoxarifado": row.get("Almoxarifado"),
                    }

                    # UPSERT
                    resp = (
                        supabase
                        .table("materiais")
                        .upsert(payload, on_conflict="tenant_id,codigo_material")
                        .execute()
                    )

                    if resp.data:
                        inseridos += 1

                st.success(f"Importação concluída. {inseridos} registros processados.")

        except Exception as e:
            st.error(f"Erro ao importar: {e}")
