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
def _split_text_chunks(text, max_chars=240):
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

def _expand_rows_for_long_description(rows, header, desc_col='Descrição', max_chars=240, atraso_mask=None, desc_style=None):
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

    min_d = s_dt.min().date()
    max_d = s_dt.max().date()

    with col3:
        d_ini = st.date_input("Data inicial", value=min_d, min_value=min_d, max_value=max_d, disabled=not usar, key=f"ini_{label}")
    with col4:
        d_fim = st.date_input("Data final", value=max_d, min_value=min_d, max_value=max_d, disabled=not usar, key=f"fim_{label}")

    if usar:
        df_f = filtrar_por_periodo(df, d_ini, d_fim, coluna_data=coluna_escolhida)
        subt = f"{nomes_colunas.get(coluna_escolhida, coluna_escolhida)}: {d_ini.strftime('%d/%m/%Y')} a {d_fim.strftime('%d/%m/%Y')}"
        return df_f, f"Período: {subt}", coluna_escolhida

    return df, "", coluna_escolhida

    s = pd.to_datetime(df[coluna_data], errors='coerce').dropna()
    if s.empty:
        return df, ""

    min_d = s.min().date()
    max_d = s.max().date()

    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        usar = st.checkbox(f"Filtrar por {label}", value=False, key=f"filtro_{label}_{coluna_data}")
    with col2:
        d_ini = st.date_input("Data inicial", value=min_d, min_value=min_d, max_value=max_d, disabled=not usar, key=f"ini_{label}_{coluna_data}")
    with col3:
        d_fim = st.date_input("Data final", value=max_d, min_value=min_d, max_value=max_d, disabled=not usar, key=f"fim_{label}_{coluna_data}")

    if usar:
        df_f = filtrar_por_periodo(df, d_ini, d_fim, coluna_data=coluna_data)
        subt = f"Período: {d_ini.strftime('%d/%m/%Y')} a {d_fim.strftime('%d/%m/%Y')}"
        return df_f, subt

    return df, ""


def gerar_botoes_exportacao(df_pedidos, formatar_moeda_br):
    """Gera botões de exportação em múltiplos formatos"""
    
    st.markdown("### 📄 Exportar Relatório Completo")
    st.info("📊 Exporte todos os pedidos em formatos profissionais")
    

    # Filtro de período (opcional)
    df_pedidos, subtitulo_periodo, _ = ui_filtro_periodo(df_pedidos, coluna_data="data_oc", label="Período")
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
            label="📊 Download Excel",
            data=buffer.getvalue(),
            file_name=f"relatorio_pedidos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    with col3:
        if PDF_DISPONIVEL:
            if st.button("📑 PDF Premium", use_container_width=True, type="primary"):
                with st.spinner("🎨 Gerando PDF profissional..."):
                    pdf_buffer = gerar_pdf_completo_premium(df_pedidos, formatar_moeda_br)
                    if pdf_buffer:
                        st.success("✅ PDF gerado!")
                        st.download_button(
                            label="💾 Download PDF",
                            data=pdf_buffer.getvalue(),
                            file_name=f"relatorio_premium_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
        else:
            st.error("❌ PDF indisponível")
    
    # Estatísticas
    st.markdown("---")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("📦 Pedidos", f"{len(df_pedidos):,}".replace(',', '.'))
    
    with col2:
        st.metric("💰 Valor Total", formatar_moeda_br(df_pedidos['valor_total'].sum()))
    
    with col3:
        entregues = (df_pedidos['entregue'] == True).sum()
        st.metric("✅ Entregues", entregues)
    
    with col4:
        st.metric("⚠️ Atrasados", (df_pedidos['atrasado'] == True).sum())
    
    with col5:
        st.metric("🏭 Fornecedores", df_pedidos['fornecedor_nome'].nunique())


def criar_relatorio_executivo(df_pedidos, formatar_moeda_br):
    """Cria relatório executivo"""
    
    st.markdown("### 📊 Relatório Executivo Premium")
    

    # Filtro de período (opcional)
    df_pedidos, subtitulo_periodo, _ = ui_filtro_periodo(df_pedidos, coluna_data="data_oc", label="Período")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📦 Pedidos", len(df_pedidos))
    
    with col2:
        st.metric("💰 Valor Total", formatar_moeda_br(df_pedidos['valor_total'].sum()))
    
    with col3:
        taxa = (df_pedidos['entregue'] == True).sum() / len(df_pedidos) * 100 if len(df_pedidos) > 0 else 0
        st.metric("📈 Taxa Entrega", f"{taxa:.1f}%".replace('.', ','))
    
    with col4:
        ticket = df_pedidos['valor_total'].sum() / len(df_pedidos) if len(df_pedidos) > 0 else 0
        st.metric("🎯 Ticket Médio", formatar_moeda_br(ticket))
    
    st.markdown("---")
    st.markdown("#### 🏢 Análise por Departamento")
    
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
        st.download_button("📥 CSV", csv, f"exec_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
    
    with col2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_dept.to_excel(writer, index=False, sheet_name='Resumo')
        st.download_button("📊 Excel", buffer.getvalue(), f"exec_{datetime.now().strftime('%Y%m%d')}.xlsx", use_container_width=True)
    
    with col3:
        if PDF_DISPONIVEL and st.button("📑 PDF Premium", key="pdf_exec", use_container_width=True, type="primary"):
            with st.spinner("Gerando..."):
                pdf = gerar_pdf_executivo_premium(df_pedidos, df_dept, formatar_moeda_br)
                if pdf:
                    st.download_button("💾 Download", pdf.getvalue(), f"exec_{datetime.now().strftime('%Y%m%d')}.pdf", "application/pdf", use_container_width=True)


def gerar_relatorio_fornecedor(df_pedidos, fornecedor, formatar_moeda_br):
    """Relatório de fornecedor"""
    
    st.markdown(f"### 🏭 {fornecedor}")
    
    df_forn = df_pedidos[df_pedidos['fornecedor_nome'] == fornecedor]
    

    # Filtro de período (opcional)
    df_forn, subtitulo_periodo, _ = ui_filtro_periodo(df_forn, coluna_data='data_oc', label='Período')
    if df_forn.empty:
        st.warning("Nenhum pedido encontrado")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📦 Pedidos", len(df_forn))
    
    with col2:
        st.metric("💰 Valor", formatar_moeda_br(df_forn['valor_total'].sum()))
    
    with col3:
        st.metric("✅ Entregues", (df_forn['entregue'] == True).sum())
    
    with col4:
        st.metric("⚠️ Atrasados", (df_forn['atrasado'] == True).sum())
    
    st.markdown("---")
    st.dataframe(preparar_dados_exportacao(df_forn), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    df_export = preparar_dados_exportacao(df_forn)
    
    with col1:
        csv = df_export.to_csv(index=False, encoding='utf-8-sig', sep=';', decimal=',')
        st.download_button("📥 CSV", csv, f"forn_{datetime.now().strftime('%Y%m%d')}.csv", use_container_width=True)
    
    with col2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
        st.download_button("📊 Excel", buffer.getvalue(), f"forn_{datetime.now().strftime('%Y%m%d')}.xlsx", use_container_width=True)
    
    with col3:
        if PDF_DISPONIVEL and st.button("📑 PDF", key=f"pdf_f_{fornecedor}", use_container_width=True, type="primary"):
            with st.spinner("Gerando..."):
                pdf = gerar_pdf_fornecedor_premium(df_forn, fornecedor, formatar_moeda_br)
                if pdf:
                    st.download_button("💾 Download", pdf.getvalue(), f"forn_{datetime.now().strftime('%Y%m%d')}.pdf", use_container_width=True)


def gerar_relatorio_departamento(df_pedidos, departamento, formatar_moeda_br):
    """Relatório de departamento"""
    
    st.markdown(f"### 🏢 {departamento}")
    
    df_dept = df_pedidos[df_pedidos['departamento'] == departamento]
    

    # Filtro de período (opcional)
    df_dept, subtitulo_periodo, _ = ui_filtro_periodo(df_dept, coluna_data='data_oc', label='Período')
    if df_dept.empty:
        st.warning("Nenhum pedido encontrado")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📦 Pedidos", len(df_dept))
    
    with col2:
        st.metric("💰 Valor", formatar_moeda_br(df_dept['valor_total'].sum()))
    
    with col3:
        st.metric("🏭 Fornecedores", df_dept['fornecedor_nome'].nunique())
    
    with col4:
        st.metric("⚠️ Atrasados", (df_dept['atrasado'] == True).sum())
    
    st.markdown("---")
    st.dataframe(preparar_dados_exportacao(df_dept), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    df_export = preparar_dados_exportacao(df_dept)
    
    with col1:
        csv = df_export.to_csv(index=False, encoding='utf-8-sig', sep=';', decimal=',')
        st.download_button("📥 CSV", csv, f"dept_{datetime.now().strftime('%Y%m%d')}.csv", use_container_width=True)
    
    with col2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
        st.download_button("📊 Excel", buffer.getvalue(), f"dept_{datetime.now().strftime('%Y%m%d')}.xlsx", use_container_width=True)
    
    with col3:
        if PDF_DISPONIVEL and st.button("📑 PDF", key=f"pdf_d_{departamento}", use_container_width=True, type="primary"):
            with st.spinner("Gerando..."):
                pdf = gerar_pdf_departamento_premium(df_dept, departamento, formatar_moeda_br)
                if pdf:
                    st.download_button("💾 Download", pdf.getvalue(), f"dept_{datetime.now().strftime('%Y%m%d')}.pdf", use_container_width=True)


def preparar_dados_exportacao(df):
    """Prepara dados para exportação"""
    
    colunas = [
        'nr_oc', 'nr_solicitacao', 'departamento', 'descricao',
        'cod_material', 'cod_equipamento',
        'qtde_solicitada', 'qtde_entregue', 'qtde_pendente',
        'fornecedor_nome', 'fornecedor_cidade', 'fornecedor_uf',
        'data_solicitacao', 'data_oc', 'previsao_entrega',
        'status', 'valor_total'
    ]
    
    colunas_existentes = [c for c in colunas if c in df.columns]
    df_export = df[colunas_existentes].copy()
    
    rename = {
        'nr_oc': 'N° OC',
        'nr_solicitacao': 'N° Solicitação',
        'departamento': 'Departamento',
        'descricao': 'Descrição',
        'cod_material': 'Código',
        'cod_equipamento': 'Equipamento',
        'qtde_solicitada': 'Qtd Solicitada',
        'qtde_entregue': 'Qtd Entregue',
        'qtde_pendente': 'Qtd Pendente',
        'fornecedor_nome': 'Fornecedor',
        'fornecedor_cidade': 'Cidade',
        'fornecedor_uf': 'UF',
        'data_solicitacao': 'Data Solicitação',
        'data_oc': 'Data OC',
        'previsao_entrega': 'Previsão',
        'status': 'Status',
        'valor_total': 'Valor (R$)'
    }
    
    return df_export.rename(columns=rename)


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
    """Formata valores monetários e evita '0.0' poluindo o relatório."""
    try:
        if v is None:
            return "-"
        fv = float(v)
        if fv <= 0:
            return "-"
        return formatar_moeda_br(fv)
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
    """Monta tabela com repeatRows e estilo consistente, com destaque opcional para atrasados."""
    dados = [df_pdf.columns.tolist()] + df_pdf.values.tolist()
    t = Table(dados, colWidths=col_widths, repeatRows=1, hAlign='LEFT', splitByRow=1)

    estilo = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#764ba2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('WORDWRAP', (0, 0), (-1, -1), 'CJK'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        # mais respiro entre colunas longas (Descrição) e dinheiro
        ('RIGHTPADDING', (3, 0), (3, -1), 10),
        ('LEFTPADDING', (4, 0), (4, -1), 10),
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#faf5ff')]),
    ]

    if atraso_mask is not None:
        for i, is_atraso in enumerate(atraso_mask, start=1):
            if bool(is_atraso):
                estilo.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#fee2e2')))

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
    """PDF Premium - Relatório Executivo (com margens consistentes e cabeçalho/rodapé)."""
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

        # KPIs
        total = int(len(df_pedidos)) if df_pedidos is not None else 0
        valor = float(df_pedidos['valor_total'].sum()) if total > 0 and 'valor_total' in df_pedidos.columns else 0.0
        entregues = int((df_pedidos['entregue'] == True).sum()) if total > 0 and 'entregue' in df_pedidos.columns else 0
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
    """PDF Premium - Relatório Completo (V3: paginação, quebra de linha, anti-sobreposição)."""

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
            ['📦 Total de Pedidos', f'{total:,}'.replace(',', '.')],
            ['💰 Valor Total', _safe_money(valor, formatar_moeda_br)],
            ['✅ Pedidos Entregues', f'{entregues:,} ({(entregues/total*100 if total else 0):.1f}%)'.replace(',', '.')],
            ['⚠️ Pedidos Atrasados', f'{atrasados:,} ({(atrasados/total*100 if total else 0):.1f}%)'.replace(',', '.')],
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
        colunas_pdf = ['N° OC', 'Departamento', 'Fornecedor', 'Descrição', 'Valor (R$)', 'Status']
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
                    row.append(Paragraph(str(r[c]), desc_style))
                elif c == 'Fornecedor':
                    row.append(Paragraph(str(r[c]), forn_style))
                elif c == 'Valor (R$)':
                    row.append(_safe_money(r[c], formatar_moeda_br))
                else:
                    row.append(str(r[c]))
            rows.append(row)

        df_flow = pd.DataFrame(rows, columns=df_pdf.columns)


        # Evita linhas gigantes (descrição longa) que podem causar páginas em branco no ReportLab

        rows_list = df_flow.values.tolist()

        header = df_flow.columns.tolist()

        rows_list, atraso_mask_new = _expand_rows_for_long_description(

            rows_list, header, desc_col='Descrição', max_chars=240, atraso_mask=locals().get('atraso_mask'), desc_style=desc_style

        )

        atraso_mask = atraso_mask_new
        df_flow = pd.DataFrame(rows_list, columns=header)

        # Paginador (linhas por página)
        rows_per_page = 18
        col_widths = [3.0*cm, 3.6*cm, 5.0*cm, 10.5*cm, 3.2*cm, 3.2*cm]
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
    """PDF Premium - Fornecedor (V3)."""

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
        colunas = ['N° OC', 'Departamento', 'Fornecedor', 'Descrição', 'Valor (R$)', 'Status']
        cols = [c for c in colunas if c in df_export.columns]
        df_pdf = df_export[cols].copy()

        desc_style = ParagraphStyle('Desc', parent=styles['BodyText'], fontSize=8, leading=10, wordWrap='CJK', splitLongWords=1)
        forn_style = ParagraphStyle('Forn', parent=styles['BodyText'], fontSize=8, leading=10, wordWrap='CJK', splitLongWords=1)

        rows = []
        for _, r in df_pdf.iterrows():
            row = []
            for c in df_pdf.columns:
                if c == 'Descrição':
                    row.append(Paragraph(str(r[c]), desc_style))
                elif c == 'Fornecedor':
                    row.append(Paragraph(str(r[c]), forn_style))
                elif c == 'Valor (R$)':
                    row.append(_safe_money(r[c], formatar_moeda_br))
                else:
                    row.append(str(r[c]))
            rows.append(row)

        df_flow = pd.DataFrame(rows, columns=df_pdf.columns)


        # Evita linhas gigantes (descrição longa) que podem causar páginas em branco no ReportLab

        rows_list = df_flow.values.tolist()

        header = df_flow.columns.tolist()

        rows_list, atraso_mask_new = _expand_rows_for_long_description(

            rows_list, header, desc_col='Descrição', max_chars=240, atraso_mask=locals().get('atraso_mask'), desc_style=desc_style

        )

        atraso_mask = atraso_mask_new
        df_flow = pd.DataFrame(rows_list, columns=header)

        rows_per_page = 18
        col_widths = [3.0*cm, 3.6*cm, 5.0*cm, 10.5*cm, 3.2*cm, 3.2*cm]

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
    """PDF Premium - Departamento (V3: anti-sobreposição + paginação)."""

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
        colunas = ['N° OC', 'Fornecedor', 'Descrição', 'Valor (R$)', 'Status']
        cols = [c for c in colunas if c in df_export.columns]
        df_pdf = df_export[cols].copy()

        desc_style = ParagraphStyle('Desc', parent=styles['BodyText'], fontSize=8, leading=10, wordWrap='CJK', splitLongWords=1)
        forn_style = ParagraphStyle('Forn', parent=styles['BodyText'], fontSize=8, leading=10, wordWrap='CJK', splitLongWords=1)

        rows = []
        for _, r in df_pdf.iterrows():
            row = []
            for c in df_pdf.columns:
                if c == 'Descrição':
                    row.append(Paragraph(str(r[c]), desc_style))
                elif c == 'Fornecedor':
                    row.append(Paragraph(str(r[c]), forn_style))
                elif c == 'Valor (R$)':
                    row.append(_safe_money(r[c], formatar_moeda_br))
                else:
                    row.append(str(r[c]))
            rows.append(row)

        df_flow = pd.DataFrame(rows, columns=df_pdf.columns)


        # Evita linhas gigantes (descrição longa) que podem causar páginas em branco no ReportLab

        rows_list = df_flow.values.tolist()

        header = df_flow.columns.tolist()

        rows_list, atraso_mask_new = _expand_rows_for_long_description(

            rows_list, header, desc_col='Descrição', max_chars=240, atraso_mask=locals().get('atraso_mask'), desc_style=desc_style

        )

        atraso_mask = atraso_mask_new
        df_flow = pd.DataFrame(rows_list, columns=header)

        rows_per_page = 18
        col_widths = [3.0*cm, 6.0*cm, 12.0*cm, 3.4*cm, 3.0*cm]

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

