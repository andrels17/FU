"""
Módulo de Exportação de Relatórios - VERSÃO PREMIUM
PDFs profissionais com design avançado, gráficos e análises detalhadas
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import io

# Importações para PDF
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import (
    KeepInFrame,
        SimpleDocTemplate, Table, TableStyle, Paragraph, 
        Spacer, PageBreak, KeepTogether
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm, mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from reportlab.platypus.flowables import HRFlowable
    from reportlab.graphics.shapes import Drawing, Rect
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics import renderPDF
    PDF_DISPONIVEL = True
except ImportError:
    PDF_DISPONIVEL = False
    st.warning("⚠️ Para exportar em PDF Premium, instale: pip install reportlab")


# --- Anti páginas em branco: quebra descrições longas em múltiplas linhas ---
def _split_text_chunks(text, max_chars=180):
    if text is None:
        return [""]
    s = str(text).strip()
    if not s:
        return [""]
    if len(s) <= max_chars:
        return [s]
    chunks = []
    start = 0
    while start < len(s):
        end = min(len(s), start + max_chars)
        if end < len(s):
            sp = s.rfind(" ", start, end)
            if sp > start + int(max_chars * 0.6):
                end = sp
        chunks.append(s[start:end].strip())
        start = end
    return chunks or [s]

def _expand_rows_for_long_description(rows, header, desc_col='Descrição', max_chars=180, atraso_mask=None, desc_style=None):
    if not rows:
        return rows, atraso_mask
    try:
        desc_idx = header.index(desc_col)
    except ValueError:
        return rows, atraso_mask

    expanded = []
    atraso_exp = [] if atraso_mask is not None else None

    for i, row in enumerate(rows):
        desc = row[desc_idx]
        try:
            desc_txt = desc.getPlainText()
        except Exception:
            desc_txt = str(desc)

        parts = _split_text_chunks(desc_txt, max_chars=max_chars)

        for j, part in enumerate(parts):
            new_row = list(row)
            if j > 0:
                for k in range(len(new_row)):
                    if k != desc_idx:
                        new_row[k] = ""
            # mantém quebra/wordwrap: se veio Paragraph no input e você quer preservar,
            # reconstrói como Paragraph usando o mesmo style
            if desc_style is not None:
                try:
                    new_row[desc_idx] = Paragraph(str(part), desc_style)
                except Exception:
                    new_row[desc_idx] = str(part)
            else:
                new_row[desc_idx] = part
            expanded.append(new_row)
            if atraso_exp is not None:
                atraso_exp.append(atraso_mask[i])

    return expanded, atraso_exp

# ============================================
# FUNÇÕES DE INTERFACE (STREAMLIT)
# ============================================

def filtrar_por_periodo(df, data_inicio=None, data_fim=None, coluna_data='data_oc'):
    """Filtra dataframe por período (inclusive) usando uma coluna de data."""
    if df is None or df.empty:
        return df
    if coluna_data not in df.columns:
        return df

    s = pd.to_datetime(df[coluna_data], errors='coerce')
    out = df.copy()
    out['_dt_filter'] = s

    if data_inicio is not None:
        di = pd.to_datetime(data_inicio)
        out = out[out['_dt_filter'] >= di]
    if data_fim is not None:
        dfim = pd.to_datetime(data_fim) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        out = out[out['_dt_filter'] <= dfim]

    return out.drop(columns=['_dt_filter'])

def ui_filtro_periodo(
    df,
    coluna_data=None,
    colunas_data=('data_oc', 'data_solicitacao', 'previsao_entrega'),
    nomes_colunas=None,
    label='Período'
):
    """Componente Streamlit para filtro de período com seletor de coluna de data.

    Backward compatible:
    - se coluna_data for informado, ele vira o padrão e aparece como primeira opção.

    Retorna: (df_filtrado, texto_subtitulo, coluna_escolhida)
    """
    if df is None or df.empty:
        return df, "", None

    if nomes_colunas is None:
        nomes_colunas = {
            'data_oc': 'Data OC',
            'data_solicitacao': 'Data Solicitação',
            'previsao_entrega': 'Previsão de Entrega',
        }

    # Monta lista de colunas candidatas respeitando coluna_data (se vier)
    candidatos = list(colunas_data)
    if coluna_data:
        # coloca a escolhida em primeiro sem duplicar
        candidatos = [coluna_data] + [c for c in candidatos if c != coluna_data]

    # Mantém apenas colunas existentes no df
    colunas_existentes = [c for c in candidatos if c in df.columns]
    if not colunas_existentes:
        return df, "", None

    col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
    with col1:
        usar = st.checkbox(f"Filtrar por {label}", value=False, key=f"filtro_{label}")

    with col2:
        opcoes = [nomes_colunas.get(c, c) for c in colunas_existentes]
        nome_escolhido = st.selectbox("Base de data", opcoes, index=0, disabled=not usar, key=f"col_{label}")
        coluna_escolhida = colunas_existentes[opcoes.index(nome_escolhido)]
    s_dt = pd.to_datetime(df[coluna_escolhida], errors='coerce').dropna()
    if s_dt.empty:
        return df, "", coluna_escolhida

    dt_min = s_dt.min().date()
    dt_max = s_dt.max().date()

    with col3:
        dt_ini = st.date_input("Início", value=dt_min, min_value=dt_min, max_value=dt_max, disabled=not usar, key=f"dt_ini_{label}")
    with col4:
        dt_fim = st.date_input("Fim", value=dt_max, min_value=dt_min, max_value=dt_max, disabled=not usar, key=f"dt_fim_{label}")

    if not usar:
        return df, "", coluna_escolhida

    if dt_ini and dt_fim and dt_ini > dt_fim:
        dt_ini, dt_fim = dt_fim, dt_ini

    s_all = pd.to_datetime(df[coluna_escolhida], errors='coerce')
    mask = (s_all.dt.date >= dt_ini) & (s_all.dt.date <= dt_fim)
    df_filtrado = df.loc[mask].copy()

    nome_col = nomes_colunas.get(coluna_escolhida, coluna_escolhida)
    subtitulo = f"{nome_col}: {dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}"
    return df_filtrado, subtitulo, coluna_escolhida


# ============================================
# FILTROS (MESMO PADRÃO DO DASHBOARD)
# ============================================

_PTBR_MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

def _normalize_bool_series(s: pd.Series) -> pd.Series:
    """Normaliza booleanos vindos do banco/CSV/Excel."""
    try:
        return s.astype(str).str.lower().isin(["true", "1", "yes", "sim"])
    except Exception:
        return pd.Series([False] * len(s), index=getattr(s, "index", None))

def _dt_series(df: pd.DataFrame, col: str) -> pd.Series:
    if df is None or df.empty or col not in df.columns:
        return pd.Series([pd.NaT] * (len(df) if df is not None else 0))
    return pd.to_datetime(df[col], errors="coerce")

def _month_label(p: pd.Period) -> str:
    try:
        m = int(p.month)
        y = int(p.year)
        return f"{_PTBR_MONTHS[m-1]}/{y}"
    except Exception:
        return str(p)

def ui_filtros_exportacao_estilo_dashboard(
    df: pd.DataFrame,
    *,
    prefix: str = "exp",
    default_periodo: str = "30 dias",
    default_only_pending: bool = True,
    base_data_default: str = "data_oc",
) -> tuple[pd.DataFrame, dict]:
    """Renderiza filtros no mesmo estilo/semântica do Dashboard e aplica no df.

    Retorna: (df_filtrado, filtros_dict)
    """
    if df is None or df.empty:
        return df, {}

    # Base de data: usa data_oc se existir, senão data_solicitacao, senão previsao_entrega
    base_dt_col = base_data_default if base_data_default in df.columns else None
    if base_dt_col is None:
        for c in ["data_oc", "data_solicitacao", "previsao_entrega"]:
            if c in df.columns:
                base_dt_col = c
                break

    # Expander compacto (igual ao dashboard)
    with st.expander("Filtros da Exportação", expanded=True):
        c1, c2, c3, c4, c5 = st.columns([1.2, 1.6, 1.6, 1.2, 1.2])

        # Período (inclui "Por mês")
        with c1:
            periodo = st.selectbox(
                "Período",
                ["30 dias", "60 dias", "90 dias", "Tudo", "Por mês"],
                index=["30 dias", "60 dias", "90 dias", "Tudo", "Por mês"].index(
                    st.session_state.get(f"{prefix}_periodo", default_periodo)
                    if st.session_state.get(f"{prefix}_periodo") in ["30 dias", "60 dias", "90 dias", "Tudo", "Por mês"]
                    else default_periodo
                ),
                key=f"{prefix}_periodo",
            )

        # Departamento
        with c2:
            deptos = (
                df.get("departamento", pd.Series(dtype=str))
                .dropna().astype(str).str.strip()
            )
            deptos = sorted([d for d in deptos.unique().tolist() if d])
            dept_sel = st.multiselect(
                "Departamento",
                deptos,
                default=st.session_state.get(f"{prefix}_dept", []),
                key=f"{prefix}_dept",
            )

        # Estado (UF) com contagem no label
        with c3:
            uf_series = (
                df.get("fornecedor_uf", pd.Series(dtype=str))
                .dropna().astype(str).str.strip().str.upper()
            )
            uf_counts = uf_series.value_counts()
            uf_sorted = uf_counts.index.tolist()
            uf_label = {uf: f"{uf} ({int(uf_counts[uf])} pedidos)" for uf in uf_sorted}

            options = [uf_label[uf] for uf in uf_sorted]
            default_ufs = st.session_state.get(f"{prefix}_uf", [])
            default_labels = [uf_label[u] for u in default_ufs if u in uf_label]

            sel_labels = st.multiselect(
                "Estado (UF)",
                options,
                default=default_labels,
                key=f"{prefix}_uf_labels",
            )
            uf_sel = [s.split(" ", 1)[0].strip().upper() for s in (sel_labels or []) if isinstance(s, str) and s.strip()]
            st.session_state[f"{prefix}_uf"] = uf_sel

        # Status
        with c4:
            status = df.get("status", pd.Series(dtype=str)).dropna().astype(str).str.strip()
            status = sorted([s for s in status.unique().tolist() if s])
            status_sel = st.multiselect(
                "Status",
                status,
                default=st.session_state.get(f"{prefix}_status", []),
                key=f"{prefix}_status",
            )

        # Pendentes
        with c5:
            somente_pendentes = st.toggle(
                "Somente pendentes",
                value=bool(st.session_state.get(f"{prefix}_only_pending", default_only_pending)),
                key=f"{prefix}_only_pending",
            )

        # Se escolher "Por mês": seletor de mês/ano
        mes_period = None
        if periodo == "Por mês":
            base_dt = _dt_series(df, base_dt_col) if base_dt_col else pd.Series([pd.NaT]*len(df))
            per = base_dt.dropna().dt.to_period("M")
            meses = per.value_counts().sort_index().index.tolist() if not per.empty else []
            if meses:
                labels = [_month_label(p) for p in meses]
                default_label = st.session_state.get(f"{prefix}_mes_label", labels[-1])
                if default_label not in labels:
                    default_label = labels[-1]
                mes_label = st.selectbox("Mês", labels, index=labels.index(default_label), key=f"{prefix}_mes_label")
                mes_period = meses[labels.index(mes_label)]

    # Aplicar filtros
    out = df.copy()

    # Período
    if base_dt_col:
        base_dt = _dt_series(out, base_dt_col)
        if periodo in ["30 dias", "60 dias", "90 dias"]:
            dias = int(str(periodo).split()[0])
            ini = pd.Timestamp.now().normalize() - pd.Timedelta(days=dias)
            out = out.loc[base_dt >= ini]
        elif periodo == "Por mês" and mes_period is not None:
            out = out.loc[base_dt.dt.to_period("M") == mes_period]
        # "Tudo" não filtra

    # Departamento
    if dept_sel and "departamento" in out.columns:
        out = out[out["departamento"].astype(str).str.strip().isin(dept_sel)]

    # UF
    uf_sel = st.session_state.get(f"{prefix}_uf", [])
    if uf_sel and "fornecedor_uf" in out.columns:
        out = out[out["fornecedor_uf"].astype(str).str.strip().str.upper().isin(uf_sel)]

    # Status
    if status_sel and "status" in out.columns:
        out = out[out["status"].astype(str).str.strip().isin(status_sel)]

    # Pendentes
    if somente_pendentes and "entregue" in out.columns:
        entregue = _normalize_bool_series(out["entregue"])
        out = out[~entregue]

    filtros = {
        "periodo": periodo,
        "mes": str(mes_period) if mes_period is not None else None,
        "base_data": base_dt_col,
        "departamentos": dept_sel,
        "ufs": uf_sel,
        "status": status_sel,
        "somente_pendentes": somente_pendentes,
    }
    return out, filtros

def gerar_botoes_exportacao(df_pedidos, formatar_moeda_br):
    """Gera botões de exportação em múltiplos formatos"""
    
    st.markdown("### Exportar Relatório Completo")
    st.info("Exporte todos os pedidos em formatos profissionais")
    

    # Filtros completos (mesmo padrão do Dashboard) + opção Por mês
    df_pedidos, filtros = ui_filtros_exportacao_estilo_dashboard(df_pedidos, prefix="exp")
    col1, col2, col3 = st.columns(3)
    
    df_export = preparar_dados_exportacao(df_pedidos)
    
    with col1:
        csv = df_export.to_csv(index=False, encoding='utf-8-sig', sep=';', decimal=',')
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name=f"relatorio_pedidos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Pedidos')
        
        st.download_button(
            label="Download Excel",
            data=buffer.getvalue(),
            file_name=f"relatorio_pedidos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    with col3:
        if PDF_DISPONIVEL:
            if st.button("PDF", use_container_width=True, type="primary"):
                with st.spinner("Gerando PDF profissional..."):
                    pdf_buffer = gerar_pdf_completo_premium(df_pedidos, formatar_moeda_br)
                    if pdf_buffer:
                        st.success("PDF gerado!")
                        st.download_button(
                            label="Download PDF",
                            data=pdf_buffer.getvalue(),
                            file_name=f"relatorio_premium_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
        else:
            st.error("PDF indisponível")
    
    # Estatísticas
    st.markdown("---")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Pedidos", f"{len(df_pedidos):,}".replace(',', '.'))
    
    with col2:
        st.metric("Valor Total", formatar_moeda_br(df_pedidos['valor_total'].sum()))
    
    with col3:
        entregues = (df_pedidos['entregue'] == True).sum()
        st.metric("Entregues", entregues)
    
    with col4:
        st.metric("Atrasados", (df_pedidos['atrasado'] == True).sum())
    
    with col5:
        st.metric("Fornecedores", df_pedidos['fornecedor_nome'].nunique())


def criar_relatorio_executivo(df_pedidos, formatar_moeda_br):
    """Cria relatório executivo"""
    
    st.markdown("### Relatório Executivo")
    

    # Filtros completos (mesmo padrão do Dashboard) + opção Por mês
    df_pedidos, filtros = ui_filtros_exportacao_estilo_dashboard(df_pedidos, prefix="exp")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Pedidos", len(df_pedidos))
    
    with col2:
        st.metric("Valor Total", formatar_moeda_br(df_pedidos['valor_total'].sum()))
    
    with col3:
        taxa = (df_pedidos['entregue'] == True).sum() / len(df_pedidos) * 100 if len(df_pedidos) > 0 else 0
        st.metric("Taxa Entrega", f"{taxa:.1f}%".replace('.', ','))
    
    with col4:
        ticket = df_pedidos['valor_total'].sum() / len(df_pedidos) if len(df_pedidos) > 0 else 0
        st.metric("Ticket Médio", formatar_moeda_br(ticket))
    
    st.markdown("---")
    st.markdown("#### Análise por Departamento")
    
    df_dept = df_pedidos.groupby('departamento').agg({
        'id': 'count',
        'valor_total': 'sum',
        'entregue': lambda x: (x == True).sum(),
        'atrasado': lambda x: (x == True).sum()
    }).reset_index()
    
    df_dept.columns = ['Departamento', 'Pedidos', 'Valor Total', 'Entregues', 'Atrasados']
    df_dept['Taxa (%)'] = (df_dept['Entregues'] / df_dept['Pedidos'] * 100).round(1)
    df_dept = df_dept.sort_values('Valor Total', ascending=False)
    
    st.dataframe(df_dept, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        csv = df_dept.to_csv(index=False, encoding='utf-8-sig', sep=';', decimal=',')
        st.download_button("CSV", csv, f"exec_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
    
    with col2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_dept.to_excel(writer, index=False, sheet_name='Resumo')
        st.download_button("Excel", buffer.getvalue(), f"exec_{datetime.now().strftime('%Y%m%d')}.xlsx", use_container_width=True)
    
    with col3:
        if PDF_DISPONIVEL and st.button("PDF", key="pdf_exec", use_container_width=True, type="primary"):
            with st.spinner("Gerando..."):
                pdf = gerar_pdf_executivo_premium(df_pedidos, df_dept, formatar_moeda_br)
                if pdf:
                    st.download_button("Download", pdf.getvalue(), f"exec_{datetime.now().strftime('%Y%m%d')}.pdf", "application/pdf", use_container_width=True)


def gerar_relatorio_fornecedor(df_pedidos, fornecedor, formatar_moeda_br):
    """Relatório de fornecedor"""
    
    st.markdown(f"### {fornecedor}")
    
    df_forn = df_pedidos[df_pedidos['fornecedor_nome'] == fornecedor]
    

    # Filtros completos (mesmo padrão do Dashboard) + opção Por mês
    df_forn, filtros = ui_filtros_exportacao_estilo_dashboard(df_forn, prefix="forn")
    if df_forn.empty:
        st.warning("Nenhum pedido encontrado")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Pedidos", len(df_forn))
    
    with col2:
        st.metric("Valor", formatar_moeda_br(df_forn['valor_total'].sum()))
    
    with col3:
        st.metric("Entregues", (df_forn['entregue'] == True).sum())
    
    with col4:
        st.metric("Atrasados", (df_forn['atrasado'] == True).sum())
    
    st.markdown("---")
    st.dataframe(preparar_dados_exportacao(df_forn), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    df_export = preparar_dados_exportacao(df_forn)
    
    with col1:
        csv = df_export.to_csv(index=False, encoding='utf-8-sig', sep=';', decimal=',')
        st.download_button("CSV", csv, f"forn_{datetime.now().strftime('%Y%m%d')}.csv", use_container_width=True)
    
    with col2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
        st.download_button("Excel", buffer.getvalue(), f"forn_{datetime.now().strftime('%Y%m%d')}.xlsx", use_container_width=True)
    
    with col3:
        if PDF_DISPONIVEL and st.button("PDF", key=f"pdf_f_{fornecedor}", use_container_width=True, type="primary"):
            with st.spinner("Gerando..."):
                pdf = gerar_pdf_fornecedor_premium(df_forn, fornecedor, formatar_moeda_br)
                if pdf:
                    st.download_button("Download", pdf.getvalue(), f"forn_{datetime.now().strftime('%Y%m%d')}.pdf", use_container_width=True)


def gerar_relatorio_departamento(df_pedidos, departamento, formatar_moeda_br):
    """Relatório de departamento"""
    
    st.markdown(f"### {departamento}")
    
    df_dept = df_pedidos[df_pedidos['departamento'] == departamento]
    

    # Filtros completos (mesmo padrão do Dashboard) + opção Por mês
    df_dept, filtros = ui_filtros_exportacao_estilo_dashboard(df_dept, prefix="dept")
    if df_dept.empty:
        st.warning("Nenhum pedido encontrado")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Pedidos", len(df_dept))
    
    with col2:
        st.metric("Valor", formatar_moeda_br(df_dept['valor_total'].sum()))
    
    with col3:
        st.metric("Fornecedores", df_dept['fornecedor_nome'].nunique())
    
    with col4:
        st.metric("Atrasados", (df_dept['atrasado'] == True).sum())
    
    st.markdown("---")
    st.dataframe(preparar_dados_exportacao(df_dept), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    df_export = preparar_dados_exportacao(df_dept)
    
    with col1:
        csv = df_export.to_csv(index=False, encoding='utf-8-sig', sep=';', decimal=',')
        st.download_button("CSV", csv, f"dept_{datetime.now().strftime('%Y%m%d')}.csv", use_container_width=True)
    
    with col2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
        st.download_button("Excel", buffer.getvalue(), f"dept_{datetime.now().strftime('%Y%m%d')}.xlsx", use_container_width=True)
    
    with col3:
        if PDF_DISPONIVEL and st.button("PDF", key=f"pdf_d_{departamento}", use_container_width=True, type="primary"):
            with st.spinner("Gerando..."):
                pdf = gerar_pdf_departamento_premium(df_dept, departamento, formatar_moeda_br)
                if pdf:
                    st.download_button("Download", pdf.getvalue(), f"dept_{datetime.now().strftime('%Y%m%d')}.pdf", use_container_width=True)


def preparar_dados_exportacao(df):
    """Prepara dados para exportação (tolerante a df cru ou pré-formatado)."""
    if df is None or getattr(df, "empty", True):
        return df

    base = df.copy()

    # Caso "cru" (colunas do banco)
    if ("nr_oc" in base.columns) or ("valor_total" in base.columns) or ("status" in base.columns):
        colunas = [
            'nr_oc', 'departamento', 'descricao',
            'cod_equipamento', 'fornecedor_nome', 'fornecedor_uf',
            'qtde_pendente', 'data_oc', 'valor_total'
        ]
        colunas_existentes = [c for c in colunas if c in base.columns]
        df_export = base[colunas_existentes].copy()

        rename = {
            'data_oc': 'Data OC',
            'nr_oc': 'N° OC',
            'cod_equipamento': 'Frota',
            'departamento': 'Departamento',
            'fornecedor_nome': 'Fornecedor',
            'fornecedor_uf': 'UF',
            'descricao': 'Descrição',
            'qtde_pendente': 'Q. Pendente',
            'valor_total': 'Preço',
        }
        df_export = df_export.rename(columns=rename)
    else:
        # Caso pré-formatado: tenta padronizar nomes comuns
        rename2 = {
            'data_oc': 'Data OC',
            'Data OC': 'Data OC',
            'nr_oc': 'N° OC',
            'N° OC': 'N° OC',
            'Equipamento': 'Frota',
            'cod_equipamento': 'Frota',
            'Frota': 'Frota',
            'departamento': 'Departamento',
            'Departamento': 'Departamento',
            'fornecedor_nome': 'Fornecedor',
            'Fornecedor': 'Fornecedor',
            'fornecedor_uf': 'UF',
            'UF': 'UF',
            'descricao': 'Descrição',
            'Descrição': 'Descrição',
            'qtde_pendente': 'Q. Pendente',
            'Q. Pendente': 'Q. Pendente',
            'Q. Pendente': 'Q. Pendente',
            'valor_total': 'Preço',
            'Valor (R$)': 'Preço',
            'Preço': 'Preço',
        }
        df_export = base.rename(columns=rename2)

    ordem = ['Data OC', 'N° OC', 'Frota', 'Departamento', 'Fornecedor', 'UF', 'Descrição', 'Q. Pendente', 'Preço']
    cols = [c for c in ordem if c in df_export.columns]
    extras = [c for c in df_export.columns if c not in cols]
    return df_export[cols + extras].copy()



# ============================================
# FUNÇÕES PDF PREMIUM
# ============================================

class CabecalhoRodape:
    """Cabeçalho e rodapé premium (sem sobreposição com o conteúdo).

    Importante: o espaço do cabeçalho/rodapé deve ser reservado via topMargin/bottomMargin
    ao criar o SimpleDocTemplate (veja DEFAULT_DOC_KW).
    """

    HEADER_H = 2.6 * cm
    FOOTER_H = 1.6 * cm

    def __init__(self, titulo, subtitulo=""):
        self.titulo = titulo
        self.subtitulo = subtitulo or ""

    def _draw_header(self, canvas_obj):
        page_w, page_h = canvas_obj._pagesize

        # Fundo do cabeçalho (dentro da área de margem superior)
        canvas_obj.setFillColorRGB(0.4, 0.49, 0.92)  # #667eea
        canvas_obj.rect(0, page_h - self.HEADER_H, page_w, self.HEADER_H, fill=1, stroke=0)

        # Título
        canvas_obj.setFillColorRGB(1, 1, 1)
        canvas_obj.setFont('Helvetica-Bold', 18)
        canvas_obj.drawString(2 * cm, page_h - 1.15 * cm, self.titulo)

        # Subtítulo
        if self.subtitulo:
            canvas_obj.setFont('Helvetica', 10.5)
            canvas_obj.drawString(2 * cm, page_h - 1.85 * cm, self.subtitulo)

    def _draw_footer(self, canvas_obj):
        page_w, _ = canvas_obj._pagesize

        # Linha decorativa
        y = self.FOOTER_H + 0.45 * cm
        canvas_obj.setStrokeColorRGB(0.4, 0.49, 0.92)
        canvas_obj.setLineWidth(1.2)
        canvas_obj.line(2 * cm, y, page_w - 2 * cm, y)

        # Textos
        canvas_obj.setFillColorRGB(0.3, 0.3, 0.3)
        canvas_obj.setFont('Helvetica', 9)
        canvas_obj.drawString(2 * cm, 0.9 * cm, f"Follow-up de Compras © {datetime.now().year}")
        canvas_obj.drawRightString(page_w - 2 * cm, 0.9 * cm, f"Página {canvas_obj.getPageNumber()}")

    def on_page(self, canvas_obj, doc):
        canvas_obj.saveState()
        self._draw_header(canvas_obj)
        self._draw_footer(canvas_obj)
        canvas_obj.restoreState()

    # Compatibilidade com versões antigas: algumas chamadas usam 'cabecalho'
    def cabecalho(self, canvas_obj, doc):
        return self.on_page(canvas_obj, doc)


# ============================================
# HELPERS DE LAYOUT (ANTI-SOBREPOSIÇÃO)
# ============================================

# Margens padrão (reservam espaço real para cabeçalho/rodapé do CabecalhoRodape)
DEFAULT_DOC_KW = dict(
    topMargin=CabecalhoRodape.HEADER_H + 1.0 * cm,
    bottomMargin=CabecalhoRodape.FOOTER_H + 1.0 * cm,
    leftMargin=2.0 * cm,
    rightMargin=2.0 * cm,
)

def _safe_page_break(elements):
    """Adiciona PageBreak apenas quando faz sentido (evita páginas em branco)."""
    try:
        if not elements:
            return
        if isinstance(elements[-1], PageBreak):
            return
        # Remove Spacers finais insignificantes antes de quebrar
        while elements and isinstance(elements[-1], Spacer):
            elements.pop()
        if not elements or isinstance(elements[-1], PageBreak):
            return
        elements.append(PageBreak())
    except Exception:
        # fallback: comportamento antigo
        elements.append(PageBreak())

def _safe_money(v, formatar_moeda_br):
    """Formata valores monetários de forma tolerante.

    Aceita:
    - números (int/float/Decimal)
    - strings já formatadas (ex.: 'R$ 1.234,56') -> retorna como está
    - strings numéricas com vírgula/ponto -> tenta converter
    """
    try:
        if v is None:
            return "-"
        # Já formatado?
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return "-"
            if "R$" in s:
                return s
            # tenta converter '1.234,56' ou '1234,56'
            s2 = s.replace(" ", "").replace("R$", "")
            # se tem vírgula, assume decimal PT-BR
            if "," in s2:
                s2 = s2.replace(".", "").replace(",", ".")
            fv = float(s2)
        else:
            fv = float(v)

        if fv <= 0:
            return "-"
        return formatar_moeda_br(fv)
    except Exception:
        return "-"
        fv = float(v)
        if fv <= 0:
            return "-"
        return formatar_moeda_br(fv)
    except Exception:
        return "-"

def _truncate_text(s: str, max_chars: int = 110) -> str:
    try:
        s = (s or "").strip()
        if len(s) <= max_chars:
            return s
        return s[: max_chars - 1].rstrip() + "…"
    except Exception:
        return str(s)[:max_chars]

def _safe_date(v):
    """Formata datas (aceita datetime/date/str) em dd/mm/aaaa."""
    try:
        if v is None:
            return "-"
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return "-"
            dt = pd.to_datetime(s, errors='coerce')
        else:
            dt = pd.to_datetime(v, errors='coerce')
        if pd.isna(dt):
            return "-"
        return dt.strftime('%d/%m/%Y')
    except Exception:
        return "-"

def _chunk_df(df, rows_per_page):
    for i in range(0, len(df), rows_per_page):
        yield df.iloc[i:i+rows_per_page]

def criar_grafico_barras_fornecedores(df, doc_width_cm=24, max_itens=8):
    """Cria um gráfico de barras (Top fornecedores por valor) com tamanho previsível."""
    try:
        if df is None or df.empty:
            return None

        base = (
            df.groupby('fornecedor_nome', dropna=False)['valor_total']
            .sum()
            .sort_values(ascending=False)
            .head(max_itens)
        )

        if base.empty:
            return None

        labels = [str(x)[:18] + ('…' if len(str(x)) > 18 else '') for x in base.index]
        values = [float(v) for v in base.values]

        width = doc_width_cm * cm
        height = 6 * cm

        d = Drawing(width, height)
        bc = VerticalBarChart()
        bc.x = 1 * cm
        bc.y = 0.8 * cm
        bc.width = width - 2 * cm
        bc.height = height - 1.6 * cm

        bc.data = [values]
        bc.categoryAxis.categoryNames = labels
        bc.barWidth = 0.4 * cm
        bc.groupSpacing = 0.4 * cm
        bc.barSpacing = 0.15 * cm

        bc.valueAxis.labels.fontSize = 7
        bc.categoryAxis.labels.fontSize = 7
        bc.categoryAxis.labels.angle = 35
        bc.categoryAxis.labels.boxAnchor = 'ne'

        bc.strokeColor = colors.HexColor('#94a3b8')
        d.add(bc)
        return d
    except Exception:
        return None


def criar_tabela_kpi(dados, cores=True):
    """Cria tabela de KPIs estilizada"""
    
    table = Table(dados, colWidths=[8*cm, 6*cm])
    
    estilo = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 13),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
    ]
    
    if cores:
        estilo.append(('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f8fafc'), colors.white]))
    
    table.setStyle(TableStyle(estilo))
    return table

def _tabela_detalhamento(df_pdf, col_widths, atraso_mask=None):
    """Monta tabela com repeatRows e estilo consistente, com destaque opcional para atrasados.
    Melhorias:
    - Alinhamentos por coluna (valor à direita, datas/UF/status centralizados)
    - Paddings mais compactos
    - Destaque de STATUS em estilo "pill" (cor de fundo por status)
    """
    header = df_pdf.columns.tolist()
    dados = [header] + df_pdf.values.tolist()

    t = Table(dados, colWidths=col_widths, repeatRows=1, hAlign='LEFT', splitByRow=1)

    def _idx(col_name: str):
        try:
            return header.index(col_name)
        except Exception:
            return None

    idx_valor = _idx('Valor (R$)')
    idx_status = _idx('Status')
    idx_data_oc = _idx('Data OC')
    idx_oc = _idx('N° OC')
    idx_frota = _idx('Frota')
    idx_uf = _idx('UF')

    estilo = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#764ba2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8.5),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('WORDWRAP', (0, 0), (-1, -1), 'CJK'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#faf5ff')]),
    ]

    if idx_valor is not None:
        estilo.append(('ALIGN', (idx_valor, 1), (idx_valor, -1), 'RIGHT'))
        estilo.append(('RIGHTPADDING', (idx_valor, 0), (idx_valor, -1), 8))
        estilo.append(('LEFTPADDING', (idx_valor, 0), (idx_valor, -1), 8))

    for idx in [idx_data_oc, idx_oc, idx_frota, idx_uf, idx_status]:
        if idx is not None:
            estilo.append(('ALIGN', (idx, 0), (idx, -1), 'CENTER'))

    if atraso_mask is not None:
        for i, is_atraso in enumerate(atraso_mask, start=1):
            if bool(is_atraso):
                estilo.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#fee2e2')))

    if idx_status is not None:
        estilo.append(('FONTNAME', (idx_status, 1), (idx_status, -1), 'Helvetica-Bold'))
        estilo.append(('TEXTCOLOR', (idx_status, 1), (idx_status, -1), colors.HexColor('#0f172a')))
        estilo.append(('LEFTPADDING', (idx_status, 1), (idx_status, -1), 6))
        estilo.append(('RIGHTPADDING', (idx_status, 1), (idx_status, -1), 6))

        status_colors = {
            'entregue': colors.HexColor('#dcfce7'),
            'entregues': colors.HexColor('#dcfce7'),
            'em transporte': colors.HexColor('#ffedd5'),
            'transporte': colors.HexColor('#ffedd5'),
            'sem oc': colors.HexColor('#dbeafe'),
            'atrasado': colors.HexColor('#fee2e2'),
            'atrasados': colors.HexColor('#fee2e2'),
        }

        for r_i in range(1, len(dados)):
            raw = dados[r_i][idx_status]
            try:
                s = str(raw)
            except Exception:
                s = ""
            s_norm = s.strip().lower()
            bg = None
            for key, color in status_colors.items():
                if key in s_norm:
                    bg = color
                    break
            if bg is not None:
                estilo.append(('BACKGROUND', (idx_status, r_i), (idx_status, r_i), bg))
                estilo.append(('BOX', (idx_status, r_i), (idx_status, r_i), 0.6, colors.HexColor('#cbd5e1')))

    t.setStyle(TableStyle(estilo))
    return t



def _build_table_from_rows(header, rows, col_widths, atraso_mask=None):
    """Cria a tabela (com repeatRows) a partir de header + rows já preparados."""
    df_pdf = pd.DataFrame(rows, columns=header)
    return _tabela_detalhamento(df_pdf, col_widths, atraso_mask=atraso_mask)

def _paginate_rows_by_height(doc, header, rows, col_widths, atraso_mask=None, heading_flowables=None, min_last_rows=3):
    """Paginação inteligente baseada em altura real (evita páginas com 1 linha 'perdida')."""
    if heading_flowables is None:
        heading_flowables = []

    used_h = 0
    for fl in heading_flowables:
        try:
            _, h = fl.wrap(doc.width, doc.height)
            used_h += h
        except Exception:
            if hasattr(fl, 'height'):
                used_h += float(fl.height)

    avail_h = max(1, doc.height - used_h - 0.2 * cm)
    avail_w = doc.width

    pages = []
    i = 0
    n = len(rows)

    while i < n:
        lo, hi = 1, n - i
        best = 1

        while lo <= hi:
            mid = (lo + hi) // 2
            sub = rows[i:i+mid]
            t = _build_table_from_rows(header, sub, col_widths,
                                       atraso_mask=None if atraso_mask is None else atraso_mask[i:i+mid])
            _, h = t.wrap(avail_w, avail_h)
            if h <= avail_h:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1

        if best < 1:
            best = 1

        pages.append((i, best))
        i += best

    # Ajuste final: evita última página com poucas linhas
    if len(pages) >= 2:
        start_last, len_last = pages[-1]
        if len_last < min_last_rows:
            start_prev, len_prev = pages[-2]
            move = min(min_last_rows - len_last, max(0, len_prev - min_last_rows))
            if move > 0:
                pages[-2] = (start_prev, len_prev - move)
                pages[-1] = (start_last - move, len_last + move)

    # Sanitização: remove páginas vazias (defensivo)
    pages = [(a, b) for (a, b) in pages if b and b > 0]
    pages = [(a, min(b, n - a)) for (a, b) in pages if a < n and (n - a) > 0]

    return pages

def gerar_pdf_executivo_premium(df_pedidos, df_resumo, formatar_moeda_br):
    """PDF - Relatório Executivo (com margens consistentes e cabeçalho/rodapé)."""
    if not PDF_DISPONIVEL:
        return None

    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, **DEFAULT_DOC_KW)

        elements = []
        styles = getSampleStyleSheet()

        titulo_style = ParagraphStyle(
            'TituloExec',
            parent=styles['Heading1'],
            fontSize=22,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold',
            spaceAfter=14
        )

        elements.append(Paragraph("Relatório Executivo", titulo_style))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#667eea'), spaceAfter=12))

        # KPIs (tolerante a df cru ou pré-formatado)
        total = int(len(df_pedidos)) if df_pedidos is not None else 0

        def _get_col(df, candidates):
            for c in candidates:
                if df is not None and hasattr(df, "columns") and c in df.columns:
                    return c
            return None

        # Coluna de valor
        col_val = _get_col(df_pedidos, ["valor_total", "Preço", "Valor (R$)", "Valor", "valor"])
        valor = 0.0
        if total > 0 and col_val:
            try:
                s = df_pedidos[col_val]
                if getattr(s, "dtype", None) == object:
                    s2 = s.astype(str).str.replace("R$", "", regex=False).str.replace(" ", "", regex=False)
                    s2 = s2.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
                    valor = float(pd.to_numeric(s2, errors="coerce").fillna(0).sum())
                else:
                    valor = float(pd.to_numeric(s, errors="coerce").fillna(0).sum())
            except Exception:
                valor = 0.0

        # Entregues: tenta bool 'entregue' senão inferir por Status
        entregues = 0
        col_entregue = _get_col(df_pedidos, ["entregue", "Entregue"])
        col_status = _get_col(df_pedidos, ["status", "Status"])
        if total > 0 and col_entregue:
            try:
                entregues = int((df_pedidos[col_entregue] == True).sum())
            except Exception:
                entregues = 0
        elif total > 0 and col_status:
            try:
                entregues = int(df_pedidos[col_status].astype(str).str.lower().str.contains("entreg").sum())
            except Exception:
                entregues = 0

        taxa = (entregues / total * 100) if total > 0 else 0.0

        kpi_dados = [
            ['INDICADOR', 'VALOR'],
            ['Total de Pedidos', f'{total:,}'.replace(',', '.')],
            ['Valor Total', formatar_moeda_br(valor)],
            ['Taxa de Entrega', f'{taxa:.1f}%'],
            ['Ticket Médio', formatar_moeda_br(valor / total if total > 0 else 0)]
        ]

        elements.append(criar_tabela_kpi(kpi_dados))
        elements.append(Spacer(1, 0.6*cm))

        # Departamentos
        elements.append(Paragraph("Análise por Departamento", ParagraphStyle('SubExec', parent=styles['Heading2'], fontSize=15, spaceAfter=10)))

        dept_dados = [['Departamento', 'Pedidos', 'Valor', 'Taxa (%)']]
        if df_resumo is not None and not df_resumo.empty:
            for _, row in df_resumo.iterrows():
                dept_dados.append([
                    str(row.get('Departamento', '')),
                    str(int(row.get('Pedidos', 0))),
                    formatar_moeda_br(float(row.get('Valor Total', 0) or 0)),
                    f"{float(row.get('Taxa (%)', 0) or 0):.1f}%"
                ])

        dept_table = Table(
            dept_dados,
            colWidths=[6*cm, 3*cm, 4*cm, 3*cm],
            repeatRows=1,
            hAlign='LEFT',
            splitByRow=1
        )
        dept_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#764ba2')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#faf5ff')])
        ]))

        elements.append(dept_table)

        cab = CabecalhoRodape("Relatório Executivo", f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}")
        doc.build(elements, onFirstPage=cab.cabecalho, onLaterPages=cab.cabecalho)

        buffer.seek(0)
        return buffer

    except Exception as e:
        st.error(f"Erro: {e}")
        return None

def gerar_pdf_completo_premium(df_pedidos, formatar_moeda_br):
    """PDF - Relatório Completo (V3: paginação, quebra de linha, anti-sobreposição)."""

    if not PDF_DISPONIVEL:
        return None

    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            **DEFAULT_DOC_KW
        )

        elements = []
        styles = getSampleStyleSheet()

        titulo_style = ParagraphStyle(
            'Titulo',
            parent=styles['Heading1'],
            fontSize=22,
            textColor=colors.HexColor('#1e293b'),
            spaceAfter=10,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("Relatório Completo de Pedidos", titulo_style))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#667eea'), spaceAfter=12))

        # KPIs
        total = len(df_pedidos)
        valor = df_pedidos['valor_total'].sum() if 'valor_total' in df_pedidos.columns else 0
        entregues = (df_pedidos['entregue'] == True).sum() if 'entregue' in df_pedidos.columns else 0
        atrasados = (df_pedidos['atrasado'] == True).sum() if 'atrasado' in df_pedidos.columns else 0

        kpi_dados = [
            ['INDICADOR', 'VALOR'],
            ['Total de Pedidos', f'{total:,}'.replace(',', '.')],
            ['Valor Total', _safe_money(valor, formatar_moeda_br)],
            ['Pedidos Entregues', f'{entregues:,} ({(entregues/total*100 if total else 0):.1f}%)'.replace(',', '.')],
            ['Pedidos Atrasados', f'{atrasados:,} ({(atrasados/total*100 if total else 0):.1f}%)'.replace(',', '.')],
        ]
        elements.append(criar_tabela_kpi(kpi_dados))
        elements.append(Spacer(1, 0.6 * cm))

        # Gráfico (Top fornecedores)
        graf = criar_grafico_barras_fornecedores(df_pedidos, doc_width_cm=24, max_itens=8)
        if graf is not None:
            elements.append(KeepTogether([
            Paragraph("Top Fornecedores por Valor (R$)", ParagraphStyle('Sub', parent=styles['Heading2'], fontSize=14, spaceAfter=6)),
            graf,
            Spacer(1, 0.6 * cm)
        ]))

        # Detalhamento
        # Para evitar sobreposição (gráfico x tabela), inicia detalhamento em nova página
        elements.append(PageBreak())

        # Detalhamento com paginação
        # Detalhamento (paginação inteligente)

        df_export = preparar_dados_exportacao(df_pedidos)
        # Colunas padrão
        colunas_pdf = ['Data OC', 'N° OC', 'Frota', 'Departamento', 'Fornecedor', 'UF', 'Descrição', 'Q. Pendente', 'Preço']
        cols = [c for c in colunas_pdf if c in df_export.columns]
        df_pdf = df_export[cols].copy()

        # Estilos de parágrafo (quebra de linha)
        desc_style = ParagraphStyle('Desc', parent=styles['BodyText'], fontSize=8, leading=10, wordWrap='CJK', splitLongWords=1)
        forn_style = ParagraphStyle('Forn', parent=styles['BodyText'], fontSize=8, leading=10, wordWrap='CJK', splitLongWords=1)

        # Converter para flowables
        rows = []
        for _, r in df_pdf.iterrows():
            row = []
            for c in df_pdf.columns:
                if c == 'Descrição':
                    row.append(Paragraph(_truncate_text(str(r[c]), 135), desc_style))
                elif c == 'Fornecedor':
                    row.append(Paragraph(_truncate_text(str(r[c]), 60), forn_style))
                elif c == 'Data OC':
                    row.append(_safe_date(r[c]))
                elif c == 'Q. Pendente':
                    try:
                        q = r[c]
                        if q is None or str(q).strip() == "" or str(q).lower() == "nan":
                            row.append("-")
                        else:
                            row.append(str(int(float(str(q).replace(",", ".")))))
                    except Exception:
                        row.append(str(r[c]))
                elif c == 'Preço':
                    row.append(_safe_money(r[c], formatar_moeda_br))
                else:
                    row.append(str(r[c]))
            rows.append(row)

        df_flow = pd.DataFrame(rows, columns=df_pdf.columns)


        # Evita linhas gigantes (descrição longa) que podem causar páginas em branco no ReportLab

        rows_list = df_flow.values.tolist()

        header = df_flow.columns.tolist()

        rows_list, atraso_mask_new = _expand_rows_for_long_description(

            rows_list, header, desc_col='Descrição', max_chars=180, atraso_mask=locals().get('atraso_mask'), desc_style=desc_style

        )

        atraso_mask = atraso_mask_new
        df_flow = pd.DataFrame(rows_list, columns=header)

        # Paginador (linhas por página)
        rows_per_page = 18
        col_widths = [2.1*cm, 2.1*cm, 2.0*cm, 3.0*cm, 4.0*cm, 1.2*cm, 7.2*cm, 2.2*cm, 1.9*cm]
        # Larguras para limitar altura de células longas
        try:
            idx_desc = colunas_pdf.index('Descrição') if 'colunas_pdf' in locals() else colunas.index('Descrição')
            idx_forn = colunas_pdf.index('Fornecedor') if 'colunas_pdf' in locals() else colunas.index('Fornecedor')
            desc_w = col_widths[idx_desc]
            forn_w = col_widths[idx_forn]
        except Exception:
            desc_w = None
            forn_w = None
        atraso_mask = None
        if 'atrasado' in df_pedidos.columns:
            # tenta alinhar por índice; fallback sem destaque se não casar
            try:
                atraso_mask = df_pedidos['atrasado'].astype(bool).tolist()
            except Exception:
                atraso_mask = None
        # Paginação inteligente por altura (evita páginas com 1 linha 'perdida')
        # Em vez de paginar manualmente (o que pode deixar páginas com muito espaço sobrando),
        # deixamos o ReportLab quebrar a tabela naturalmente entre páginas.
        # repeatRows=1 já repete o cabeçalho e splitByRow=1 permite corte por linha.
        elements.append(Paragraph("Detalhamento de Pedidos", ParagraphStyle('Sub2', parent=styles['Heading2'], fontSize=14, spaceAfter=8)))
        elements.append(_build_table_from_rows(df_flow.columns.tolist(), df_flow.values.tolist(), col_widths, atraso_mask=atraso_mask))

        cab = CabecalhoRodape("Follow-up de Compras", f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}" + (f" | {subtitulo_periodo}" if "subtitulo_periodo" in locals() and subtitulo_periodo else ""))
        doc.build(elements, onFirstPage=cab.on_page, onLaterPages=cab.on_page)

        buffer.seek(0)
        return buffer

    except Exception as e:
        st.error(f"Erro ao gerar PDF: {e}")
        return None


def gerar_pdf_fornecedor_premium(df_fornecedor, fornecedor, formatar_moeda_br):
    """PDF - Fornecedor."""

    if not PDF_DISPONIVEL:
        return None

    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            **DEFAULT_DOC_KW
        )

        elements = []
        styles = getSampleStyleSheet()

        elements.append(Paragraph(f"Relatório: {fornecedor}", ParagraphStyle('T', parent=styles['Heading1'], fontSize=20, alignment=TA_CENTER, fontName='Helvetica-Bold', spaceAfter=10)))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#667eea'), spaceAfter=10))

        stats_dados = [
            ['MÉTRICA', 'VALOR'],
            ['Pedidos', f'{len(df_fornecedor):,}'.replace(',', '.')],
            ['Valor Total', _safe_money(df_fornecedor['valor_total'].sum() if 'valor_total' in df_fornecedor.columns else 0, formatar_moeda_br)],
            ['Entregues', f"{(df_fornecedor['entregue'] == True).sum() if 'entregue' in df_fornecedor.columns else 0:,}".replace(',', '.')],
            ['Atrasados', f"{(df_fornecedor['atrasado'] == True).sum() if 'atrasado' in df_fornecedor.columns else 0:,}".replace(',', '.')],
        ]
        elements.append(criar_tabela_kpi(stats_dados))
        elements.append(Spacer(1, 0.6 * cm))

        # Gráfico (Top itens por valor dentro do fornecedor) – opcional
        graf = criar_grafico_barras_fornecedores(df_fornecedor, doc_width_cm=24, max_itens=6)
        if graf is not None:
            elements.append(KeepTogether([
            Paragraph("Top (por valor) dentro do fornecedor", ParagraphStyle('Sub', parent=styles['Heading2'], fontSize=14, spaceAfter=6)),
            graf,
            Spacer(1, 0.6 * cm)
        ]))

        # Para evitar sobreposição (gráfico x tabela), inicia detalhamento em nova página
        elements.append(PageBreak())

        # Detalhamento
        # Detalhamento (paginação inteligente)

        df_export = preparar_dados_exportacao(df_fornecedor)
        colunas = ['Data OC', 'N° OC', 'Frota', 'Departamento', 'Fornecedor', 'UF', 'Descrição', 'Q. Pendente', 'Preço']
        cols = [c for c in colunas if c in df_export.columns]
        df_pdf = df_export[cols].copy()

        desc_style = ParagraphStyle('Desc', parent=styles['BodyText'], fontSize=8, leading=10, wordWrap='CJK', splitLongWords=1)
        forn_style = ParagraphStyle('Forn', parent=styles['BodyText'], fontSize=8, leading=10, wordWrap='CJK', splitLongWords=1)

        rows = []
        for _, r in df_pdf.iterrows():
            row = []
            for c in df_pdf.columns:
                if c == 'Descrição':
                    row.append(Paragraph(_truncate_text(str(r[c]), 135), desc_style))
                elif c == 'Fornecedor':
                    row.append(Paragraph(_truncate_text(str(r[c]), 60), forn_style))
                elif c == 'Data OC':
                    row.append(_safe_date(r[c]))
                elif c == 'Qtde. Pendente':
                    try:
                        q = r[c]
                        if q is None or str(q).strip() == "" or str(q).lower() == "nan":
                            row.append("-")
                        else:
                            row.append(str(int(float(str(q).replace(",", ".")))))
                    except Exception:
                        row.append(str(r[c]))
                elif c == 'Preço':
                    row.append(_safe_money(r[c], formatar_moeda_br))
                else:
                    row.append(str(r[c]))
            rows.append(row)

        df_flow = pd.DataFrame(rows, columns=df_pdf.columns)


        # Evita linhas gigantes (descrição longa) que podem causar páginas em branco no ReportLab

        rows_list = df_flow.values.tolist()

        header = df_flow.columns.tolist()

        rows_list, atraso_mask_new = _expand_rows_for_long_description(

            rows_list, header, desc_col='Descrição', max_chars=180, atraso_mask=locals().get('atraso_mask'), desc_style=desc_style

        )

        atraso_mask = atraso_mask_new
        df_flow = pd.DataFrame(rows_list, columns=header)

        rows_per_page = 18
        col_widths = [2.1*cm, 2.1*cm, 2.0*cm, 3.0*cm, 4.0*cm, 1.2*cm, 7.2*cm, 2.2*cm, 1.9*cm]
        # Larguras para limitar altura de células longas
        try:
            idx_desc = colunas_pdf.index('Descrição') if 'colunas_pdf' in locals() else colunas.index('Descrição')
            idx_forn = colunas_pdf.index('Fornecedor') if 'colunas_pdf' in locals() else colunas.index('Fornecedor')
            desc_w = col_widths[idx_desc]
            forn_w = col_widths[idx_forn]
        except Exception:
            desc_w = None
            forn_w = None
        atraso_mask = None
        if 'atrasado' in df_fornecedor.columns:
            try:
                atraso_mask = df_fornecedor['atrasado'].astype(bool).tolist()
            except Exception:
                atraso_mask = None
        # Paginação inteligente por altura (evita páginas com 1 linha 'perdida')
        # Em vez de paginar manualmente (o que pode deixar páginas com muito espaço sobrando),
        # deixamos o ReportLab quebrar a tabela naturalmente entre páginas.
        # repeatRows=1 já repete o cabeçalho e splitByRow=1 permite corte por linha.
        elements.append(Paragraph("Detalhamento de Pedidos", ParagraphStyle('Sub2', parent=styles['Heading2'], fontSize=14, spaceAfter=8)))
        elements.append(_build_table_from_rows(df_flow.columns.tolist(), df_flow.values.tolist(), col_widths, atraso_mask=atraso_mask))

        cab = CabecalhoRodape(f"Fornecedor: {fornecedor}", f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}" + (f" | {subtitulo_periodo}" if "subtitulo_periodo" in locals() and subtitulo_periodo else ""))
        doc.build(elements, onFirstPage=cab.on_page, onLaterPages=cab.on_page)

        buffer.seek(0)
        return buffer

    except Exception as e:
        st.error(f"Erro: {e}")
        return None


def gerar_pdf_departamento_premium(df_dept, departamento, formatar_moeda_br):
    """PDF - Departamento."""

    if not PDF_DISPONIVEL:
        return None

    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            **DEFAULT_DOC_KW
        )

        elements = []
        styles = getSampleStyleSheet()

        elements.append(Paragraph(f"Departamento: {departamento}", ParagraphStyle('T', parent=styles['Heading1'], fontSize=20, alignment=TA_CENTER, fontName='Helvetica-Bold', spaceAfter=10)))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#667eea'), spaceAfter=10))

        stats_dados = [
            ['MÉTRICA', 'VALOR'],
            ['Pedidos', f'{len(df_dept):,}'.replace(',', '.')],
            ['Valor Total', _safe_money(df_dept['valor_total'].sum() if 'valor_total' in df_dept.columns else 0, formatar_moeda_br)],
            ['Fornecedores', f"{df_dept['fornecedor_nome'].nunique() if 'fornecedor_nome' in df_dept.columns else 0:,}".replace(',', '.')],
            ['Atrasados', f"{(df_dept['atrasado'] == True).sum() if 'atrasado' in df_dept.columns else 0:,}".replace(',', '.')],
        ]
        elements.append(criar_tabela_kpi(stats_dados))
        elements.append(Spacer(1, 0.6 * cm))

        # Gráfico fixo com tamanho previsível + KeepTogether
        graf = criar_grafico_barras_fornecedores(df_dept, doc_width_cm=24, max_itens=8)
        if graf is not None:
            elements.append(KeepTogether([
            Paragraph("Top Fornecedores por Valor (R$)", ParagraphStyle('Sub', parent=styles['Heading2'], fontSize=14, spaceAfter=6)),
            graf,
            Spacer(1, 0.4 * cm)
        ]))

        # Para evitar sobreposição (gráfico x tabela), inicia detalhamento em nova página
        elements.append(PageBreak())

        # Começa detalhamento sempre em nova página (evita colidir com gráfico)
        # Detalhamento (paginação inteligente)

        df_export = preparar_dados_exportacao(df_dept)
        colunas = ['Data OC', 'N° OC', 'Frota', 'Departamento', 'Fornecedor', 'UF', 'Descrição', 'Q. Pendente', 'Preço']
        cols = [c for c in colunas if c in df_export.columns]
        df_pdf = df_export[cols].copy()

        desc_style = ParagraphStyle('Desc', parent=styles['BodyText'], fontSize=8, leading=10, wordWrap='CJK', splitLongWords=1)
        forn_style = ParagraphStyle('Forn', parent=styles['BodyText'], fontSize=8, leading=10, wordWrap='CJK', splitLongWords=1)

        rows = []
        for _, r in df_pdf.iterrows():
            row = []
            for c in df_pdf.columns:
                if c == 'Descrição':
                    row.append(Paragraph(_truncate_text(str(r[c]), 135), desc_style))
                elif c == 'Fornecedor':
                    row.append(Paragraph(_truncate_text(str(r[c]), 60), forn_style))
                elif c == 'Data OC':
                    row.append(_safe_date(r[c]))
                elif c == 'Qtde. Pendente':
                    try:
                        q = r[c]
                        if q is None or str(q).strip() == "" or str(q).lower() == "nan":
                            row.append("-")
                        else:
                            row.append(str(int(float(str(q).replace(",", ".")))))
                    except Exception:
                        row.append(str(r[c]))
                elif c == 'Preço':
                    row.append(_safe_money(r[c], formatar_moeda_br))
                else:
                    row.append(str(r[c]))
            rows.append(row)

        df_flow = pd.DataFrame(rows, columns=df_pdf.columns)


        # Evita linhas gigantes (descrição longa) que podem causar páginas em branco no ReportLab

        rows_list = df_flow.values.tolist()

        header = df_flow.columns.tolist()

        rows_list, atraso_mask_new = _expand_rows_for_long_description(

            rows_list, header, desc_col='Descrição', max_chars=180, atraso_mask=locals().get('atraso_mask'), desc_style=desc_style

        )

        atraso_mask = atraso_mask_new
        df_flow = pd.DataFrame(rows_list, columns=header)

        rows_per_page = 18
        col_widths = [2.1*cm, 2.1*cm, 2.0*cm, 3.0*cm, 4.0*cm, 1.2*cm, 7.2*cm, 2.2*cm, 1.9*cm]
        # Larguras para limitar altura de células longas
        try:
            idx_desc = colunas_pdf.index('Descrição') if 'colunas_pdf' in locals() else colunas.index('Descrição')
            idx_forn = colunas_pdf.index('Fornecedor') if 'colunas_pdf' in locals() else colunas.index('Fornecedor')
            desc_w = col_widths[idx_desc]
            forn_w = col_widths[idx_forn]
        except Exception:
            desc_w = None
            forn_w = None
        atraso_mask = None
        if 'atrasado' in df_dept.columns:
            try:
                atraso_mask = df_dept['atrasado'].astype(bool).tolist()
            except Exception:
                atraso_mask = None
        # Paginação inteligente por altura (evita páginas com 1 linha 'perdida')
        # Em vez de paginar manualmente (o que pode deixar páginas com muito espaço sobrando),
        # deixamos o ReportLab quebrar a tabela naturalmente entre páginas.
        # repeatRows=1 já repete o cabeçalho e splitByRow=1 permite corte por linha.
        elements.append(Paragraph("Detalhamento de Pedidos", ParagraphStyle('Sub2', parent=styles['Heading2'], fontSize=14, spaceAfter=8)))
        elements.append(_build_table_from_rows(df_flow.columns.tolist(), df_flow.values.tolist(), col_widths, atraso_mask=atraso_mask))

        cabecalho_rodape = CabecalhoRodape(f"Departamento: {departamento}", f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}" + (f" | {subtitulo_periodo}" if "subtitulo_periodo" in locals() and subtitulo_periodo else ""))
        doc.build(elements, onFirstPage=cabecalho_rodape.on_page, onLaterPages=cabecalho_rodape.on_page)

        buffer.seek(0)
        return buffer

    except Exception as e:
        st.error(f"Erro: {e}")
        return None

