from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet


def gerar_pdf_executivo(
    *,
    titulo: str,
    subtitulo: str,
    kpis: Dict[str, Any],
    tabela_linhas: Optional[List[List[Any]]] = None,
    tabela_header: Optional[List[str]] = None,
) -> bytes:
    """Gera um PDF executivo (bytes) para download no Streamlit Cloud."""

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title=titulo,
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(titulo, styles["Title"]))
    story.append(Paragraph(subtitulo, styles["Normal"]))
    story.append(Spacer(1, 10))

    # KPIs
    kpi_rows = [["Indicador", "Valor"]] + [[str(k), str(v)] for k, v in kpis.items()]
    kpi_table = Table(kpi_rows, hAlign="LEFT", colWidths=[8.5 * cm, 8.5 * cm])
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(kpi_table)
    story.append(Spacer(1, 14))

    # Tabela opcional
    if tabela_linhas:
        rows = []
        if tabela_header:
            rows.append([str(x) for x in tabela_header])
        rows.extend([[str(x) for x in r] for r in tabela_linhas])
        tbl = Table(rows, hAlign="LEFT")
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("PADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(Paragraph("Detalhamento", styles["Heading3"]))
        story.append(tbl)

    doc.build(story)
    return buf.getvalue()
