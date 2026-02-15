import streamlit as st
import pandas as pd
import re
import html
from datetime import datetime, timedelta


def calcular_alertas(df_pedidos: pd.DataFrame, df_fornecedores: pd.DataFrame | None = None):
    """Calcula todos os tipos de alertas do sistema.

    Compatível com chamadas antigas (apenas df_pedidos) e novas (df_pedidos, df_fornecedores).
    Regra de vencimento/atraso: previsao_entrega > prazo_entrega > data_oc + 30 dias.
    """
    hoje = pd.Timestamp.now().normalize()

    alertas = {
        "pedidos_atrasados": [],
        "pedidos_vencendo": [],
        "fornecedores_baixa_performance": [],
        "pedidos_criticos": [],
        "total": 0,
    }

    if df_pedidos is None or df_pedidos.empty:
        return alertas

    df = df_pedidos.copy()

    # ============================
    # Normalizações e tipos
    # ============================
    if "entregue" in df.columns:
        df["entregue"] = df["entregue"].astype(str).str.lower().isin(["true", "1", "yes", "sim"])
    else:
        df["entregue"] = False

    if "qtde_pendente" in df.columns:
        df["_qtd_pendente"] = pd.to_numeric(df["qtde_pendente"], errors="coerce").fillna(0)
    else:
        df["_qtd_pendente"] = 0

    df["_pendente"] = (~df["entregue"]) | (df["_qtd_pendente"] > 0)

    if "valor_total" in df.columns:
        df["_valor_total"] = pd.to_numeric(df["valor_total"], errors="coerce").fillna(0.0)
    else:
        df["_valor_total"] = 0.0

    def _dt(col: str) -> pd.Series:
        if col not in df.columns:
            return pd.Series([pd.NaT] * len(df), index=df.index)
        return pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    data_oc = _dt("data_oc")
    prev = _dt("previsao_entrega")
    prazo = _dt("prazo_entrega")

    due = prev.combine_first(prazo)
    fallback_due = data_oc + pd.to_timedelta(30, unit="D")
    df["_due"] = due.combine_first(fallback_due)

    df["_atrasado"] = df["_pendente"] & df["_due"].notna() & (df["_due"] < hoje)

        # ============================
    # Fornecedor: tentar manter nome já vindo da view (vw_pedidos_completo),
    # e usar df_fornecedores apenas como complemento.
    # ============================
    if "fornecedor_id" in df.columns:
        df["fornecedor_id"] = df["fornecedor_id"].astype(str).str.strip()
    else:
        df["fornecedor_id"] = ""

    # Nome base (quando já vem da view)
    if "fornecedor_nome" in df.columns:
        df["_fornecedor_nome_base"] = (
            df["fornecedor_nome"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace({"nan": "", "None": "", "null": ""})
        )
    elif "fornecedor" in df.columns:
        # fallback: algumas fontes usam 'fornecedor' como nome
        df["_fornecedor_nome_base"] = (
            df["fornecedor"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace({"nan": "", "None": "", "null": ""})
        )
    else:
        df["_fornecedor_nome_base"] = ""

    df_f = None
    if df_fornecedores is not None and not df_fornecedores.empty:
        df_f = df_fornecedores.copy()
        df_f.columns = [c.strip().lower() for c in df_f.columns]
        if "id" in df_f.columns:
            df_f["id"] = df_f["id"].astype(str).str.strip()
        else:
            df_f = None

    if df_f is not None:
        # Procurar a coluna de nome (com múltiplas tentativas)
        nome_col = None
        for possivel_nome in ["nome_fantasia", "nome", "razao_social"]:
            if possivel_nome in df_f.columns:
                nome_col = possivel_nome
                break

        cols_keep = ["id"]
        if nome_col:
            cols_keep.append(nome_col)

        df = df.merge(
            df_f[cols_keep],
            left_on="fornecedor_id",
            right_on="id",
            how="left",
            suffixes=("", "_forn"),
        )

        # Nome vindo da tabela de fornecedores
        if nome_col and nome_col in df.columns:
            df["_fornecedor_nome_merge"] = df[nome_col].fillna("").astype(str).str.strip()
        else:
            df["_fornecedor_nome_merge"] = ""

        # Prioridade:
        # 1) nome da tabela fornecedores (merge)
        # 2) nome já vindo da view (base)
        # 3) fallback "Fornecedor <id>"
        df["fornecedor_nome"] = df.apply(
            lambda row: (
                row["_fornecedor_nome_merge"]
                if row["_fornecedor_nome_merge"]
                else (
                    row["_fornecedor_nome_base"]
                    if row["_fornecedor_nome_base"]
                    else (
                        f"Fornecedor {row['fornecedor_id']}"
                        if row.get("fornecedor_id") and str(row.get("fornecedor_id")).strip()
                        else "N/A"
                    )
                )
            ),
            axis=1,
        )

        # Limpeza
        df.drop(columns=["id", "_fornecedor_nome_merge"], inplace=True, errors="ignore")
    else:
        # Sem tabela de fornecedores: usar o nome base da view, e por último o id
        df["fornecedor_nome"] = df.apply(
            lambda row: (
                row["_fornecedor_nome_base"]
                if row["_fornecedor_nome_base"]
                else (
                    f"Fornecedor {row['fornecedor_id']}"
                    if row.get("fornecedor_id") and str(row.get("fornecedor_id")).strip()
                    else "N/A"
                )
            ),
            axis=1,
        )

    df.drop(columns=["_fornecedor_nome_base"], inplace=True, errors="ignore")

    df_atrasados = df[df["_atrasado"]].copy()
    if not df_atrasados.empty:
        for _, pedido in df_atrasados.iterrows():
            due_dt = pedido.get("_due")
            dias_atraso = int((hoje - due_dt).days) if pd.notna(due_dt) else 0

            alertas["pedidos_atrasados"].append({
                "id": pedido.get("id", pedido.get("id_x")),
                "nr_oc": pedido.get("nr_oc"),
                "descricao": pedido.get("descricao", ""),
                "fornecedor": pedido.get("fornecedor_nome", "N/A"),
                "dias_atraso": dias_atraso,
                "valor": float(pedido.get("_valor_total", 0.0)),
                "departamento": pedido.get("departamento", "N/A"),
            })

    
    data_limite = hoje + timedelta(days=3)
    df_vencendo = df[
        df["_pendente"] &
        df["_due"].notna() &
        (df["_due"] >= hoje) &
        (df["_due"] <= data_limite)
    ].copy()

    if not df_vencendo.empty:
        for _, pedido in df_vencendo.iterrows():
            dias_restantes = int((pedido.get("_due") - hoje).days) if pd.notna(pedido.get("_due")) else 0
            alertas["pedidos_vencendo"].append({
                "id": pedido.get("id", pedido.get("id_x")),
                "nr_oc": pedido.get("nr_oc"),
                "descricao": pedido.get("descricao", ""),
                "fornecedor": pedido.get("fornecedor_nome", "N/A"),
                "dias_restantes": dias_restantes,
                "valor": float(pedido.get("_valor_total", 0.0)),
                "previsao": pedido.get("previsao_entrega") or pedido.get("prazo_entrega"),
            })

    # ============================
    # 3) Fornecedores com Baixa Performance
    # ============================
    if "fornecedor_nome" in df.columns and df["fornecedor_nome"].notna().any():
        id_col = "id" if "id" in df.columns else ("id_x" if "id_x" in df.columns else df.columns[0])

        grp = df.groupby("fornecedor_nome", dropna=False).agg(
            total_pedidos=(id_col, "count"),
            entregues=("entregue", "sum"),
            atrasados=("_atrasado", "sum"),
        ).reset_index()

        grp["taxa_sucesso"] = ((grp["entregues"] - grp["atrasados"]) / grp["total_pedidos"] * 100).fillna(0)

        baixa = grp[(grp["taxa_sucesso"] < 70) & (grp["total_pedidos"] >= 5)]
        for _, f in baixa.iterrows():
            alertas["fornecedores_baixa_performance"].append({
                "fornecedor": f["fornecedor_nome"],
                "taxa_sucesso": float(f["taxa_sucesso"]),
                "total_pedidos": int(f["total_pedidos"]),
                "atrasados": int(f["atrasados"]),
            })

    # ============================
    # 4) Pedidos Críticos (Alto valor + urgente)
    # ============================
    valor_critico = df["_valor_total"].quantile(0.75) if len(df) >= 4 else df["_valor_total"].max()
    df_criticos = df[
        df["_pendente"] &
        (df["_valor_total"] >= float(valor_critico)) &
        df["_due"].notna() &
        (df["_due"] <= data_limite)
    ].copy()

    if not df_criticos.empty:
        for _, pedido in df_criticos.iterrows():
            alertas["pedidos_criticos"].append({
                "id": pedido.get("id", pedido.get("id_x")),
                "nr_oc": pedido.get("nr_oc"),
                "descricao": pedido.get("descricao", ""),
                "valor": float(pedido.get("_valor_total", 0.0)),
                "fornecedor": pedido.get("fornecedor_nome", "N/A"),
                "previsao": pedido.get("previsao_entrega") or pedido.get("prazo_entrega"),
                "departamento": pedido.get("departamento", "N/A"),
            })

    # Total
    alertas["total"] = (
        len(alertas["pedidos_atrasados"])
        + len(alertas["pedidos_vencendo"])
        + len(alertas["pedidos_criticos"])
        + len(alertas["fornecedores_baixa_performance"])
    )

    return alertas

def exibir_badge_alertas(alertas: dict):
    total = alertas.get("total", 0)

    if total == 0:
        return

    st.markdown(
        f"""
        <div style="
            background: linear-gradient(135deg,#7c3aed,#2563eb);
            padding: 12px;
            border-radius: 12px;
            text-align: center;
            font-weight: 600;
            color: white;
            margin-bottom: 10px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        ">
            🔔 {total} Alertas Pendentes
        </div>
        """,
        unsafe_allow_html=True,
    )

def exibir_painel_alertas(alertas: dict, formatar_moeda_br):
    """Alias para compatibilidade com o app.py."""
    return exibir_alertas_completo(alertas, formatar_moeda_br)

def criar_card_pedido(pedido: dict, tipo: str, formatar_moeda_br):
    """Renderiza um card de pedido (atrasado, vencendo ou crítico)."""
    
    def safe_text(txt):
        """Previne problemas com HTML."""
        if not txt:
            return ""
        return html.escape(str(txt))
    
    nr_oc_txt = safe_text(pedido.get("nr_oc", "N/A"))
    desc_txt = safe_text(pedido.get("descricao", ""))
    fornecedor_txt = safe_text(pedido.get("fornecedor", "N/A"))
    valor = pedido.get("valor", 0.0)
    
    # Card de acordo com o tipo
    if tipo == "atrasado":
        dias = pedido.get("dias_atraso", 0)
        dept = safe_text(pedido.get("departamento", "N/A"))
        
        with st.container():
            st.markdown(
                f"""
                <div style='border-left: 4px solid #dc2626; padding: 12px; margin-bottom: 10px; background-color: rgba(220, 38, 38, 0.10); border-radius: 10px;'>
                    <p style='margin: 0; font-size: 14px; color: #dc2626; font-weight: 600;'>🔴 OC: {nr_oc_txt}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Descrição:</strong> {desc_txt}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Fornecedor:</strong> {fornecedor_txt}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Departamento:</strong> {dept}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Valor:</strong> {formatar_moeda_br(valor)}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: #dc2626; font-weight: 600;'><strong>⏰ Atrasado há {dias} dia(s)</strong></p>
                </div>
                """,
                unsafe_allow_html=True
            )
    
    elif tipo == "vencendo":
        dias = pedido.get("dias_restantes", 0)
        prev = safe_text(pedido.get("previsao", "N/A"))
        
        with st.container():
            st.markdown(
                f"""
                <div style='border-left: 4px solid #f59e0b; padding: 12px; margin-bottom: 10px; background-color: rgba(245, 158, 11, 0.10); border-radius: 10px;'>
                    <p style='margin: 0; font-size: 14px; color: #f59e0b; font-weight: 600;'>⏰ OC: {nr_oc_txt}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Descrição:</strong> {desc_txt}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Fornecedor:</strong> {fornecedor_txt}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Valor:</strong> {formatar_moeda_br(valor)}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Previsão:</strong> {prev}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: #f59e0b; font-weight: 600;'><strong>⏳ Vence em {dias} dia(s)</strong></p>
                </div>
                """,
                unsafe_allow_html=True
            )
    
    elif tipo == "critico":
        prev = safe_text(pedido.get("previsao", "N/A"))
        dept = safe_text(pedido.get("departamento", "N/A"))
        
        with st.container():
            st.markdown(
                f"""
                <div style='border-left: 4px solid #7c3aed; padding: 12px; margin-bottom: 10px; background-color: rgba(124, 58, 237, 0.10); border-radius: 10px;'>
                    <p style='margin: 0; font-size: 14px; color: #7c3aed; font-weight: 600;'>🚨 OC: {nr_oc_txt}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Descrição:</strong> {desc_txt}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Fornecedor:</strong> {fornecedor_txt}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Departamento:</strong> {dept}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Previsão:</strong> {prev}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: #7c3aed; font-weight: 600;'><strong>💰 Valor: {formatar_moeda_br(valor)}</strong></p>
                </div>
                """,
                unsafe_allow_html=True
            )


def criar_card_fornecedor(fornecedor: dict, formatar_moeda_br):
    """Renderiza um card de fornecedor com baixa performance."""
    
    def safe_text(txt):
        """Previne problemas com HTML."""
        if not txt:
            return ""
        return html.escape(str(txt))
    
    nome = safe_text(fornecedor.get("fornecedor", "N/A"))
    taxa = max(0, min(100, fornecedor.get("taxa_sucesso", 0)))
    total = fornecedor.get("total_pedidos", 0)
    atrasados = fornecedor.get("atrasados", 0)
    
    # Determinar cor e nível de acordo com a taxa
    if taxa < 40:
        cor = "#dc2626"
        nivel = "CRÍTICO"
        bg_color = "rgba(220, 38, 38, 0.10)"
    elif taxa < 55:
        cor = "#f59e0b"
        nivel = "GRAVE"
        bg_color = "rgba(245, 158, 11, 0.10)"
    else:
        cor = "#eab308"
        nivel = "ATENÇÃO"
        bg_color = "rgba(234, 179, 8, 0.10)"
    
    with st.container():
        st.markdown(
            f"""
            <div style='border-left: 4px solid {cor}; padding: 12px; margin-bottom: 10px; background-color: {bg_color}; border-radius: 10px;'>
                <p style='margin: 0; font-size: 14px; color: {cor}; font-weight: 600;'>📉 {nome}</p>
                <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Nível de Risco:</strong> <span style='color: {cor}; font-weight: 600;'>{nivel}</span></p>
                <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Taxa de Sucesso:</strong> {taxa:.1f}%</p>
                <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Total de Pedidos:</strong> {total}</p>
                <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Pedidos Atrasados:</strong> {atrasados}</p>
            </div>
            """,
            unsafe_allow_html=True
        )


def exibir_alertas_completo(alertas: dict, formatar_moeda_br):
    """Exibe a página completa de alertas com filtros e tabs."""

    def safe_text(txt):
        """Previne problemas com HTML e valores None/NaN."""
        if txt is None or (isinstance(txt, float) and pd.isna(txt)):
            return "N/A"
        txt_str = str(txt).strip()
        if not txt_str or txt_str.lower() in ["nan", "none", "null"]:
            return "N/A"
        txt_str = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]", "", txt_str)
        return html.escape(txt_str)

    st.title("🔔 Central de Notificações e Alertas")

    # CSS (PRECISA ficar dentro da função)
    st.markdown(
        """
        <style>
          .fu-kpi {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 14px;
            padding: 14px 14px;
            margin-bottom: 6px;
          }
          .fu-kpi-title {
            font-size: 13px;
            opacity: 0.9;
            margin: 0 0 6px 0;
          }
          .fu-kpi-value {
            font-size: 30px;
            font-weight: 800;
            line-height: 1.1;
            margin: 0;
          }
          .fu-kpi-sub {
            font-size: 12px;
            opacity: 0.85;
            margin: 6px 0 0 0;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Resumo geral no topo
    a = len(alertas.get("pedidos_atrasados", []))
    v = len(alertas.get("pedidos_vencendo", []))
    c = len(alertas.get("pedidos_criticos", []))
    f = len(alertas.get("fornecedores_baixa_performance", []))

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            f"""
            <div class="fu-kpi">
              <p class="fu-kpi-title">⚠️ Atrasados</p>
              <p class="fu-kpi-value">{a}</p>
              <p class="fu-kpi-sub">{'⏰ Quanto maior, pior' if a else '✅ Tudo em dia'}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <div class="fu-kpi">
              <p class="fu-kpi-title">⏰ Vencendo em 3 dias</p>
              <p class="fu-kpi-value">{v}</p>
              <p class="fu-kpi-sub">{'⚡ Atenção' if v else '✅ Sem urgências'}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            f"""
            <div class="fu-kpi">
              <p class="fu-kpi-title">🚨 Pedidos Críticos</p>
              <p class="fu-kpi-value">{c}</p>
              <p class="fu-kpi-sub">{'💰 Alto valor / urgente' if c else '✅ Ok'}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col4:
        st.markdown(
            f"""
            <div class="fu-kpi">
              <p class="fu-kpi-title">📦 Fornecedores Problema</p>
              <p class="fu-kpi-value">{f}</p>
              <p class="fu-kpi-sub">{'📉 Baixa performance' if f else '✅ Ok'}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(
        [
            f"⚠️ Atrasados ({len(alertas['pedidos_atrasados'])})",
            f"⏰ Vencendo ({len(alertas['pedidos_vencendo'])})",
            f"🚨 Críticos ({len(alertas['pedidos_criticos'])})",
            f"📉 Fornecedores ({len(alertas['fornecedores_baixa_performance'])})",
        ]
    )

    # TAB 1: Pedidos Atrasados
    with tab1:
        st.subheader("⚠️ Pedidos Atrasados")

        if alertas["pedidos_atrasados"]:
            departamentos = sorted(
                list({safe_text(p.get("departamento", "N/A")) for p in alertas["pedidos_atrasados"]})
            )
            fornecedores = sorted(
                list({safe_text(p.get("fornecedor", "N/A")) for p in alertas["pedidos_atrasados"]})
            )

            col_filtro1, col_filtro2, col_filtro3 = st.columns(3)

            with col_filtro1:
                ordem = st.selectbox(
                    "Ordenar por:",
                    [
                        "Dias de Atraso (maior primeiro)",
                        "Dias de Atraso (menor primeiro)",
                        "Valor (maior primeiro)",
                        "Valor (menor primeiro)",
                    ],
                    key="filtro_atrasados_ordem",
                )

            with col_filtro2:
                dept_filtro = st.multiselect(
                    "Filtrar por Departamento:",
                    options=departamentos,
                    default=[],
                    key="filtro_atrasados_dept",
                )

            with col_filtro3:
                fornecedor_filtro = st.multiselect(
                    "Filtrar por Fornecedor:",
                    options=fornecedores,
                    default=[],
                    key="filtro_atrasados_fornecedor",
                )

            if "Dias de Atraso (maior primeiro)" in ordem:
                pedidos_filtrados = sorted(alertas["pedidos_atrasados"], key=lambda x: x.get("dias_atraso", 0), reverse=True)
            elif "Dias de Atraso (menor primeiro)" in ordem:
                pedidos_filtrados = sorted(alertas["pedidos_atrasados"], key=lambda x: x.get("dias_atraso", 0))
            elif "Valor (maior primeiro)" in ordem:
                pedidos_filtrados = sorted(alertas["pedidos_atrasados"], key=lambda x: x.get("valor", 0), reverse=True)
            elif "Valor (menor primeiro)" in ordem:
                pedidos_filtrados = sorted(alertas["pedidos_atrasados"], key=lambda x: x.get("valor", 0))
            else:
                pedidos_filtrados = alertas["pedidos_atrasados"]

            if dept_filtro:
                pedidos_filtrados = [p for p in pedidos_filtrados if safe_text(p.get("departamento", "N/A")) in dept_filtro]

            if fornecedor_filtro:
                pedidos_filtrados = [p for p in pedidos_filtrados if safe_text(p.get("fornecedor", "N/A")) in fornecedor_filtro]

            st.caption(f"📊 Mostrando {len(pedidos_filtrados)} de {len(alertas['pedidos_atrasados'])} pedidos atrasados")

            if pedidos_filtrados:
                for pedido in pedidos_filtrados:
                    criar_card_pedido(pedido, "atrasado", formatar_moeda_br)
            else:
                st.info("📭 Nenhum pedido atrasado corresponde aos filtros selecionados")
        else:
            st.success("✅ Nenhum pedido atrasado!")

    # TAB 2: Pedidos Vencendo
    with tab2:
        st.subheader("⏰ Pedidos Vencendo nos Próximos 3 Dias")

        if alertas["pedidos_vencendo"]:
            fornecedores_venc = sorted(
                list({safe_text(p.get("fornecedor", "N/A")) for p in alertas["pedidos_vencendo"]})
            )

            col_filtro1, col_filtro2 = st.columns(2)

            with col_filtro1:
                ordem_venc = st.selectbox(
                    "Ordenar por:",
                    [
                        "Dias Restantes (menor primeiro)",
                        "Dias Restantes (maior primeiro)",
                        "Valor (maior primeiro)",
                        "Valor (menor primeiro)",
                    ],
                    key="filtro_vencendo_ordem",
                )

            with col_filtro2:
                fornecedor_venc_filtro = st.multiselect(
                    "Filtrar por Fornecedor:",
                    options=fornecedores_venc,
                    default=[],
                    key="filtro_vencendo_fornecedor",
                )

            if "Dias Restantes (menor primeiro)" in ordem_venc:
                pedidos_filtrados = sorted(alertas["pedidos_vencendo"], key=lambda x: x.get("dias_restantes", 0))
            elif "Dias Restantes (maior primeiro)" in ordem_venc:
                pedidos_filtrados = sorted(alertas["pedidos_vencendo"], key=lambda x: x.get("dias_restantes", 0), reverse=True)
            elif "Valor (maior primeiro)" in ordem_venc:
                pedidos_filtrados = sorted(alertas["pedidos_vencendo"], key=lambda x: x.get("valor", 0), reverse=True)
            elif "Valor (menor primeiro)" in ordem_venc:
                pedidos_filtrados = sorted(alertas["pedidos_vencendo"], key=lambda x: x.get("valor", 0))
            else:
                pedidos_filtrados = alertas["pedidos_vencendo"]

            if fornecedor_venc_filtro:
                pedidos_filtrados = [p for p in pedidos_filtrados if safe_text(p.get("fornecedor", "N/A")) in fornecedor_venc_filtro]

            st.caption(f"📊 Mostrando {len(pedidos_filtrados)} de {len(alertas['pedidos_vencendo'])} pedidos vencendo")

            if pedidos_filtrados:
                for pedido in pedidos_filtrados:
                    criar_card_pedido(pedido, "vencendo", formatar_moeda_br)
            else:
                st.info("📭 Nenhum pedido vencendo corresponde aos filtros selecionados")
        else:
            st.info("📭 Nenhum pedido vencendo nos próximos 3 dias")
    
    with tab3:
        st.subheader("🚨 Pedidos Críticos (Alto Valor + Urgente)")
        
        if alertas['pedidos_criticos']:
            # Extrair departamentos e fornecedores únicos
            departamentos_crit = sorted(list(set(
                [safe_text(p.get('departamento', 'N/A')) for p in alertas['pedidos_criticos']]
            )))
            
            fornecedores_crit = sorted(list(set(
                [safe_text(p.get('fornecedor', 'N/A')) for p in alertas['pedidos_criticos']]
            )))
            
            # Filtros
            col_filtro1, col_filtro2, col_filtro3 = st.columns(3)
            
            with col_filtro1:
                ordem_crit = st.selectbox(
                    "Ordenar por:",
                    ["Valor (maior primeiro)", "Valor (menor primeiro)", 
                     "Previsão (próxima primeiro)"],
                    key="filtro_criticos_ordem"
                )
            
            with col_filtro2:
                dept_crit_filtro = st.multiselect(
                    "Filtrar por Departamento:",
                    options=departamentos_crit,
                    default=[],
                    key="filtro_criticos_dept"
                )
            
            with col_filtro3:
                fornecedor_crit_filtro = st.multiselect(
                    "Filtrar por Fornecedor:",
                    options=fornecedores_crit,
                    default=[],
                    key="filtro_criticos_fornecedor"
                )
            
            # Aplicar ordenação
            if "Valor (maior primeiro)" in ordem_crit:
                pedidos_filtrados = sorted(alertas['pedidos_criticos'], key=lambda x: x.get('valor', 0), reverse=True)
            elif "Valor (menor primeiro)" in ordem_crit:
                pedidos_filtrados = sorted(alertas['pedidos_criticos'], key=lambda x: x.get('valor', 0))
            elif "Previsão (próxima primeiro)" in ordem_crit:
                pedidos_filtrados = sorted(alertas['pedidos_criticos'], 
                                          key=lambda x: pd.to_datetime(x.get('previsao', '')) if x.get('previsao') else pd.Timestamp.max)
            else:
                pedidos_filtrados = alertas['pedidos_criticos']
            
            # Aplicar filtros de departamento
            if dept_crit_filtro:
                pedidos_filtrados = [p for p in pedidos_filtrados if safe_text(p.get('departamento', 'N/A')) in dept_crit_filtro]
            
            # Aplicar filtros de fornecedor
            if fornecedor_crit_filtro:
                pedidos_filtrados = [p for p in pedidos_filtrados if safe_text(p.get('fornecedor', 'N/A')) in fornecedor_crit_filtro]
            
            # Mostrar contador
            st.caption(f"📊 Mostrando {len(pedidos_filtrados)} de {len(alertas['pedidos_criticos'])} pedidos críticos")
            
            if pedidos_filtrados:
                st.warning("⚠️ Pedidos de alto valor com previsão de entrega próxima")
                
                for pedido in pedidos_filtrados:
                    criar_card_pedido(pedido, "critico", formatar_moeda_br)
            else:
                st.info("📭 Nenhum pedido crítico corresponde aos filtros selecionados")
        else:
            st.success("✅ Nenhum pedido crítico no momento")
    
    with tab4:
        st.subheader("📉 Fornecedores com Baixa Performance")
        
        if alertas['fornecedores_baixa_performance']:
            # Extrair nomes de fornecedores únicos
            nomes_fornecedores = sorted(list(set(
                [safe_text(f.get('fornecedor', 'N/A')) for f in alertas['fornecedores_baixa_performance']]
            )))
            
            # Filtros
            col_filtro1, col_filtro2, col_filtro3 = st.columns(3)
            
            with col_filtro1:
                ordem_forn = st.selectbox(
                    "Ordenar por:",
                    ["Taxa de Sucesso (menor primeiro)", "Taxa de Sucesso (maior primeiro)",
                     "Atrasados (maior primeiro)", "Total Pedidos (maior primeiro)"],
                    key="filtro_fornecedores_ordem"
                )
            
            with col_filtro2:
                nivel_filtro = st.multiselect(
                    "Filtrar por Nível de Risco:",
                    options=["CRÍTICO", "GRAVE", "ATENÇÃO"],
                    default=["CRÍTICO", "GRAVE", "ATENÇÃO"],
                    key="filtro_fornecedores_nivel"
                )
            
            with col_filtro3:
                fornecedor_nome_filtro = st.multiselect(
                    "Filtrar por Fornecedor:",
                    options=nomes_fornecedores,
                    default=[],
                    key="filtro_fornecedores_nome"
                )
            
            # Aplicar filtro de nível
            fornecedores_filtrados = []
            for fornecedor in alertas['fornecedores_baixa_performance']:
                taxa = max(0, min(100, fornecedor['taxa_sucesso']))
                
                # Verificar nível
                nivel_correspondente = False
                if taxa < 40 and "CRÍTICO" in nivel_filtro:
                    nivel_correspondente = True
                elif taxa < 55 and "GRAVE" in nivel_filtro:
                    nivel_correspondente = True
                elif taxa >= 55 and "ATENÇÃO" in nivel_filtro:
                    nivel_correspondente = True
                
                # Verificar nome do fornecedor
                nome_correspondente = True
                if fornecedor_nome_filtro:
                    nome_correspondente = safe_text(fornecedor.get('fornecedor', 'N/A')) in fornecedor_nome_filtro
                
                if nivel_correspondente and nome_correspondente:
                    fornecedores_filtrados.append(fornecedor)
            
            # Aplicar ordenação
            if "Taxa de Sucesso (menor primeiro)" in ordem_forn:
                fornecedores_filtrados = sorted(fornecedores_filtrados, key=lambda x: x['taxa_sucesso'])
            elif "Taxa de Sucesso (maior primeiro)" in ordem_forn:
                fornecedores_filtrados = sorted(fornecedores_filtrados, key=lambda x: x['taxa_sucesso'], reverse=True)
            elif "Atrasados (maior primeiro)" in ordem_forn:
                fornecedores_filtrados = sorted(fornecedores_filtrados, key=lambda x: x['atrasados'], reverse=True)
            elif "Total Pedidos (maior primeiro)" in ordem_forn:
                fornecedores_filtrados = sorted(fornecedores_filtrados, key=lambda x: x['total_pedidos'], reverse=True)
            
            # Mostrar contador
            st.caption(f"📊 Mostrando {len(fornecedores_filtrados)} de {len(alertas['fornecedores_baixa_performance'])} fornecedores")
            
            if fornecedores_filtrados:
                st.warning("⚠️ Fornecedores com taxa de sucesso abaixo de 70%")
                
                for fornecedor in fornecedores_filtrados:
                    criar_card_fornecedor(fornecedor, formatar_moeda_br)
            else:
                st.info("📭 Nenhum fornecedor corresponde aos filtros selecionados")
        else:
            st.success("✅ Todos os fornecedores com boa performance!")

