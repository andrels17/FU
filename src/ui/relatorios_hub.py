import streamlit as st

from src.ui.theme import section_header


def exibir_relatorios_hub(supabase_user, supabase_admin=None, tenant_id: str | None = None):
    """Hub de relatórios.

    Nota importante (Streamlit): st.tabs executa o código de todas as abas.
    Para evitar conflitos de keys e custos desnecessários, aqui usamos st.radio
    (visual de abas) e renderizamos **somente** o relatório selecionado.
    """

    section_header(
        "Relatórios",
        hint="Executivo, gerenciais e integrações em um único lugar.",
        pill="Enterprise",
    )

    with st.container(border=True):
        opcoes = [
            "Exportação",
            "Gerenciais",
            "WhatsApp",
            "Mapa",
            "Executivo (Superadmin)",
        ]

        _force = st.session_state.pop("hub_reports_force", None)
        _default_idx = opcoes.index(_force) if _force in opcoes else 0

        escolha = st.radio(
            "",
            options=opcoes,
            index=_default_idx,
            horizontal=True,
            key="hub_reports__selector",
        )

        st.markdown("---")

        if escolha == "Exportação":
            import pandas as pd

            import src.services.exportacao_relatorios as er
            from src.repositories.pedidos import carregar_pedidos

            df_all = carregar_pedidos(supabase_user, tenant_id)

            if df_all.empty:
                st.info("📭 Nenhum pedido encontrado para exportação.")
                return

            # Reaproveita o último recorte do Dashboard (se o usuário tiver clicado em 'Gerar dashboard')
            usar_recorte_dashboard = st.toggle(
                "Usar filtros atuais do Dashboard",
                value=True,
                help="Se você já gerou o Dashboard com filtros, a exportação usa o mesmo recorte.",
                key="rep_export_use_dash_scope",
            )

            df_export = df_all
            if (
                usar_recorte_dashboard
                and bool(st.session_state.get("dash_filters_applied"))
                and isinstance(st.session_state.get("dash_df_view"), pd.DataFrame)
                and not st.session_state.get("dash_df_view").empty
            ):
                df_export = st.session_state["dash_df_view"].copy()
                st.caption("Exportação baseada no **último recorte** do Dashboard (após clicar em *Gerar dashboard*).")
            else:
                st.caption("Exportação baseada em **todos os pedidos** do tenant (sem recorte do Dashboard).")

            st.subheader("📥 Exportação de Relatórios")

            tipo_relatorio = st.selectbox(
                "Selecione o tipo de relatório:",
                ["Relatório Completo", "Relatório Executivo", "Por Fornecedor", "Por Departamento"],
                key="rep_export_tipo",
            )

            if tipo_relatorio == "Relatório Completo":
                from src.utils.formatting import formatar_moeda_br
                er.gerar_botoes_exportacao(df_export, formatar_moeda_br)

            elif tipo_relatorio == "Relatório Executivo":
                from src.utils.formatting import formatar_moeda_br
                er.criar_relatorio_executivo(df_export, formatar_moeda_br)

            elif tipo_relatorio == "Por Fornecedor":
                if "fornecedor_nome" not in df_export.columns:
                    st.error("Coluna 'fornecedor_nome' não encontrada nos dados.")
                    st.caption(f"Colunas disponíveis: {list(df_export.columns)}")
                    return
                fornecedores = sorted(df_export["fornecedor_nome"].dropna().astype(str).unique().tolist())
                fornecedor = st.selectbox("Selecione o fornecedor:", fornecedores, key="rep_export_fornecedor")
                if fornecedor:
                    from src.utils.formatting import formatar_moeda_br
                    er.gerar_relatorio_fornecedor(df_export, fornecedor, formatar_moeda_br)

            else:  # Por Departamento
                if "departamento" not in df_export.columns:
                    st.error("Coluna 'departamento' não encontrada nos dados.")
                    st.caption(f"Colunas disponíveis: {list(df_export.columns)}")
                    return
                departamentos = (
                    df_export["departamento"]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .loc[lambda s: s != ""]
                    .unique()
                    .tolist()
                )
                departamentos = sorted(departamentos)
                departamento = st.selectbox("Selecione o departamento:", departamentos, key="rep_export_departamento")
                if departamento:
                    from src.utils.formatting import formatar_moeda_br
                    er.gerar_relatorio_departamento(df_export, departamento, formatar_moeda_br)

            return

        if escolha == "Gerenciais":
            from src.ui.relatorios_gerenciais import render_relatorios_gerenciais

            render_relatorios_gerenciais(supabase_user, tenant_id=tenant_id)

        elif escolha == "WhatsApp":
            from src.ui.relatorios_whatsapp import render_relatorios_whatsapp

            usuario = st.session_state.get("usuario") or {}
            render_relatorios_whatsapp(
                supabase_user,
                tenant_id=tenant_id,
                created_by=usuario.get("id"),
            )

        elif escolha == "Mapa":
            from src.ui.mapa import exibir_mapa

            exibir_mapa(supabase_user)

        else:
            # Executivo (superadmin)
            if not bool(st.session_state.get("is_superadmin")):
                st.info("Relatórios executivos completos são visíveis apenas para Superadmin.")
                return
            if supabase_admin is None:
                st.error("Supabase admin não inicializado (SERVICE ROLE).")
                return
            from src.ui.metricas_executivas import exibir_metricas_executivas

            exibir_metricas_executivas(supabase_admin)
