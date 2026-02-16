import streamlit as st

import pandas as pd
import re
import html
from datetime import datetime, timedelta
import math


# ============================
# Status de alerta (persistência em sessão)
# ============================
def _ensure_alert_status_store() -> None:
    if "alert_status" not in st.session_state:
        st.session_state["alert_status"] = {}  # {alert_id: status}

def get_alert_status(alert_id: str) -> str:
    _ensure_alert_status_store()
    return str(st.session_state["alert_status"].get(str(alert_id), "Novo"))

def set_alert_status(alert_id: str, status: str) -> None:
    _ensure_alert_status_store()
    st.session_state["alert_status"][str(alert_id)] = str(status)

def badge_alert_status(status: str) -> str:
    s = (status or "Novo").lower().strip()
    if s.startswith("res"):
        bg = "rgba(16,185,129,0.18)"; bd="rgba(16,185,129,0.35)"; fg="#10b981"; label = "Resolvido"
    elif s.startswith("em"):
        bg = "rgba(245,158,11,0.18)"; bd="rgba(245,158,11,0.35)"; fg="#f59e0b"; label = "Em andamento"
    else:
        bg = "rgba(147,197,253,0.18)"; bd="rgba(147,197,253,0.35)"; fg="#93c5fd"; label = "Novo"
    return f"""<span style="display:inline-block;padding:2px 10px;border-radius:999px;background:{bg};border:1px solid {bd};color:{fg};font-weight:800;font-size:12px;">{label}</span>"""



# ============================
# Configurações de Alertas
# ============================
ALERT_CONFIG = {
    "dias_vencendo": 3,                 # Janela para "vencendo"
    "min_pedidos_fornecedor": 5,        # Mínimo de pedidos p/ avaliar fornecedor
    "taxa_sucesso_min": 70.0,           # Abaixo disso, entra em "baixa performance"
    "valor_critico_min": 0.0,           # Piso opcional (0 = desativado)
    "risk_score_weights": {             # Pesos p/ índice de risco
        "atrasados": 3,
        "criticos": 2,
        "vencendo": 1,
        "fornecedores": 1,
    },
}


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

    data_entrega = _dt("data_entrega")

    due = prev.combine_first(prazo)
    fallback_due = data_oc + pd.to_timedelta(30, unit="D")
    df["_due"] = due.combine_first(fallback_due)

    df["_atrasado"] = df["_pendente"] & df["_due"].notna() & (df["_due"] < hoje)


    def _pedido_id(pedido, fallback_idx=None):
        """Retorna um identificador estável para o pedido, mesmo quando 'id' vem vazio."""
        for key in ("id", "id_x", "pedido_id", "pedidoid", "oc_id", "nr_oc"):
            if key in pedido:
                val = pedido.get(key)
                if val is None:
                    continue
                try:
                    if isinstance(val, float) and pd.isna(val):
                        continue
                except Exception:
                    pass
                s = str(val).strip()
                if s and s.lower() not in ("nan", "none", "null"):
                    return s
        return f"row-{fallback_idx}" if fallback_idx is not None else None

    # Entregue em atraso (se existir data_entrega). Mantém compatibilidade: se não existir, tudo False.
    df["_entregue_tarde"] = df["entregue"] & df["_due"].notna() & data_entrega.notna() & (data_entrega > df["_due"])

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
        for i, (_, pedido) in enumerate(df_atrasados.iterrows()):
            due_dt = pedido.get("_due")
            dias_atraso = int((hoje - due_dt).days) if pd.notna(due_dt) else 0

            alertas["pedidos_atrasados"].append({
                "id": _pedido_id(pedido, i),
                "nr_oc": pedido.get("nr_oc"),
                "cod_material": pedido.get("cod_material"),
                "descricao": pedido.get("descricao", ""),
                "fornecedor": pedido.get("fornecedor_nome", "N/A"),
                "dias_atraso": dias_atraso,
                "valor": float(pedido.get("_valor_total", 0.0)),
                "departamento": pedido.get("departamento", "N/A"),
            })

    
    data_limite = hoje + timedelta(days=int(ALERT_CONFIG.get('dias_vencendo', 3)))
    df_vencendo = df[
        df["_pendente"] &
        df["_due"].notna() &
        (df["_due"] >= hoje) &
        (df["_due"] <= data_limite)
    ].copy()

    if not df_vencendo.empty:
        for i, (_, pedido) in enumerate(df_vencendo.iterrows()):
            dias_restantes = int((pedido.get("_due") - hoje).days) if pd.notna(pedido.get("_due")) else 0
            alertas["pedidos_vencendo"].append({
                "id": _pedido_id(pedido, i),
                "nr_oc": pedido.get("nr_oc"),
                "cod_material": pedido.get("cod_material"),
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
            atrasados_pendentes=("_atrasado", "sum"),
            entregues_tarde=("_entregue_tarde", "sum"),
        ).reset_index()

        # Atraso total: pendentes vencidos + entregues após o prazo (se houver data_entrega)
        grp["atrasos_total"] = (grp["atrasados_pendentes"] + grp["entregues_tarde"]).fillna(0)
        grp["taxa_sucesso"] = (100 - (grp["atrasos_total"] / grp["total_pedidos"] * 100)).clip(lower=0, upper=100).fillna(0)

        taxa_min = float(ALERT_CONFIG.get("taxa_sucesso_min", 70.0))
        min_ped = int(ALERT_CONFIG.get("min_pedidos_fornecedor", 5))
        baixa = grp[(grp["taxa_sucesso"] < taxa_min) & (grp["total_pedidos"] >= min_ped)]
        for _, f in baixa.iterrows():
            alertas["fornecedores_baixa_performance"].append({
                "fornecedor": f["fornecedor_nome"],
                "taxa_sucesso": float(f["taxa_sucesso"]),
                "total_pedidos": int(f["total_pedidos"]),
                "atrasados": int(f["atrasos_total"]),
            })

    # ============================
    # 4) Pedidos Críticos (Alto valor + urgente)
    # ============================
    valor_critico_base = df["_valor_total"].quantile(0.75) if len(df) >= 4 else df["_valor_total"].max()
    piso = float(ALERT_CONFIG.get("valor_critico_min", 0.0) or 0.0)
    valor_critico = max(float(valor_critico_base), piso)
    df_criticos = df[
        df["_pendente"] &
        (df["_valor_total"] >= float(valor_critico)) &
        df["_due"].notna() &
        (df["_due"] <= data_limite)
    ].copy()

    if not df_criticos.empty:
        for i, (_, pedido) in enumerate(df_criticos.iterrows()):
            alertas["pedidos_criticos"].append({
                "id": _pedido_id(pedido, i),
                "nr_oc": pedido.get("nr_oc"),
                "cod_material": pedido.get("cod_material"),
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
    total = int(alertas.get("total", 0) or 0)
    if total == 0:
        return

    a = len(alertas.get("pedidos_atrasados", []))
    v = len(alertas.get("pedidos_vencendo", []))
    c = len(alertas.get("pedidos_criticos", []))
    f = len(alertas.get("fornecedores_baixa_performance", []))

    w = ALERT_CONFIG.get("risk_score_weights", {})
    score = (
        a * int(w.get("atrasados", 3))
        + c * int(w.get("criticos", 2))
        + v * int(w.get("vencendo", 1))
        + f * int(w.get("fornecedores", 1))
    )

    # Faixas simples de severidade
    if score >= 16:
        label = "CRÍTICO"
        grad = "linear-gradient(135deg,#dc2626,#991b1b)"
    elif score >= 6:
        label = "ATENÇÃO"
        grad = "linear-gradient(135deg,#f59e0b,#b45309)"
    else:
        label = "ESTÁVEL"
        grad = "linear-gradient(135deg,#10b981,#059669)"

    st.markdown(
        f"""
        <div style="
            background: {grad};
            padding: 12px;
            border-radius: 12px;
            text-align: center;
            font-weight: 700;
            color: white;
            margin-bottom: 10px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.25);
        ">
            🔔 {total} alertas — <span style='opacity:0.95'>{label}</span> <span style='opacity:0.85'>(score {score})</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

def exibir_painel_alertas(alertas: dict, formatar_moeda_br):
    """Alias para compatibilidade com o app.py."""
    return exibir_alertas_completo(alertas, formatar_moeda_br)

def criar_card_pedido(pedido: dict, tipo: str, formatar_moeda_br, idx: int = 0, status: str = "Novo"):
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
    status_badge = badge_alert_status(status)
    
    # Card de acordo com o tipo
    if tipo == "atrasado":
        dias = pedido.get("dias_atraso", 0)
        dept = safe_text(pedido.get("departamento", "N/A"))
        
        with st.container():
            csel, cbox, cbtn1, cbtn2 = st.columns([2.4, 9.6, 2, 2])
            with cbox:
                st.markdown(
                f"""
                <div class='fu-card' style='border-left: 4px solid #dc2626;'>
                    <p class='fu-oc'>🔴 OC: {nr_oc_txt} &nbsp; {status_badge}</p>
                    <p class='fu-desc'><b>Descrição:</b> {desc_txt}</p>
                    <p class='fu-meta'><b>Fornecedor:</b> {fornecedor_txt}</p>
                    <p class='fu-meta'><b>Departamento:</b> {dept}</p>
                    <p class='fu-meta'><b>Valor:</b> {formatar_moeda_br(valor)}</p>
                    <p class='fu-meta'><b>⏰ Atraso:</b> {dias} dia(s)</p>
                </div>
                """,
                unsafe_allow_html=True
            )

            # Seleção + status (por item)
            base_key = f"{tipo}_{pedido.get('id','')}_{pedido.get('nr_oc','')}_{idx}"
            with csel:
                # checkbox (seleção para lote)
                _chk_key = f"sel_{base_key}"
                st.checkbox("", key=_chk_key)

                # status (sincroniza UI <- store para não "desfazer" lote)
                _status_key = f"status_{base_key}"
                _stored = get_alert_status(str(pedido.get("id", "")) or str(pedido.get("nr_oc", "")) or str(idx))

                # garante que o widget reflita o status armazenado (inclusive após ação em lote)
                if st.session_state.get(_status_key) != _stored:
                    st.session_state[_status_key] = _stored

                novo_status = st.selectbox(
                    "",
                    options=["Novo", "Em andamento", "Resolvido"],
                    key=_status_key,
                    label_visibility="collapsed",
                )
                if novo_status != _stored:
                    set_alert_status(str(pedido.get("id", "")) or str(pedido.get("nr_oc", "")) or str(idx), novo_status)

            # Ações rápidas (híbrido: operacional + executivo)
            with cbtn1:
                if st.button("🔎 Ver Ficha", key=f"alerta_ver_ficha_{base_key}"):
                    _ir_para_ficha_material_do_alerta(pedido)
            with cbtn2:
                if st.button("📋 Copiar OC", key=f"alerta_copiar_oc_{base_key}"):
                    st.session_state["oc_copiada"] = str(pedido.get("nr_oc", "") or "")
                    try:
                        st.toast("OC copiada.", icon="📋")
                    except Exception:
                        st.info("OC copiada.")

    
    elif tipo == "vencendo":
        dias = pedido.get("dias_restantes", 0)
        prev = safe_text(pedido.get("previsao", "N/A"))
        
        with st.container():
            csel, cbox, cbtn1, cbtn2 = st.columns([2.4, 9.6, 2, 2])
            with cbox:
                st.markdown(
                f"""
                <div class='fu-card' style='border-left: 4px solid #f59e0b;'>
                    <p class='fu-oc'>⏰ OC: {nr_oc_txt} &nbsp; {status_badge}</p>
                    <p class='fu-desc'><b>Descrição:</b> {desc_txt}</p>
                    <p class='fu-meta'><b>Fornecedor:</b> {fornecedor_txt}</p>
                    <p class='fu-meta'><b>Valor:</b> {formatar_moeda_br(valor)}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Previsão:</strong> {prev}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: #f59e0b; font-weight: 600;'><strong>⏳ Vence em {dias} dia(s)</strong></p>
                </div>
                """,
                unsafe_allow_html=True
            )

            # Ações rápidas (híbrido: operacional + executivo)
            base_key = f"{tipo}_{pedido.get('id','')}_{pedido.get('nr_oc','')}_{idx}"
            with cbtn1:
                if st.button("🔎 Ver Ficha", key=f"alerta_ver_ficha_{base_key}"):
                    _ir_para_ficha_material_do_alerta(pedido)
            with cbtn2:
                if st.button("📋 Copiar OC", key=f"alerta_copiar_oc_{base_key}"):
                    st.session_state["oc_copiada"] = str(pedido.get("nr_oc", "") or "")
                    try:
                        st.toast("OC copiada.", icon="📋")
                    except Exception:
                        st.info("OC copiada.")

    
    elif tipo == "critico":
        prev = safe_text(pedido.get("previsao", "N/A"))
        dept = safe_text(pedido.get("departamento", "N/A"))
        
        with st.container():
            csel, cbox, cbtn1, cbtn2 = st.columns([2.4, 9.6, 2, 2])
            with cbox:
                st.markdown(
                f"""
                <div class='fu-card' style='border-left: 4px solid #7c3aed;'>
                    <p class='fu-oc'>🚨 OC: {nr_oc_txt} &nbsp; {status_badge}</p>
                    <p class='fu-desc'><b>Descrição:</b> {desc_txt}</p>
                    <p class='fu-meta'><b>Fornecedor:</b> {fornecedor_txt}</p>
                    <p class='fu-meta'><b>Departamento:</b> {dept}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: rgba(229,231,235,0.92);'><strong>Previsão:</strong> {prev}</p>
                    <p style='margin: 4px 0; font-size: 13px; color: #7c3aed; font-weight: 600;'><strong>💰 Valor: {formatar_moeda_br(valor)}</strong></p>
                </div>
                """,
                unsafe_allow_html=True
            )

            # Ações rápidas (híbrido: operacional + executivo)
            base_key = f"{tipo}_{pedido.get('id','')}_{pedido.get('nr_oc','')}_{idx}"
            with cbtn1:
                if st.button("🔎 Ver Ficha", key=f"alerta_ver_ficha_{base_key}"):
                    _ir_para_ficha_material_do_alerta(pedido)
            with cbtn2:
                if st.button("📋 Copiar OC", key=f"alerta_copiar_oc_{base_key}"):
                    st.session_state["oc_copiada"] = str(pedido.get("nr_oc", "") or "")
                    try:
                        st.toast("OC copiada.", icon="📋")
                    except Exception:
                        st.info("OC copiada.")



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




def _ir_para_ficha_material_do_alerta(pedido: dict) -> None:
    """Navega para a Ficha de Material usando o contexto do alerta.

    Compatível com a página ficha_material_page (usa st.session_state).
    """
    try:
        cod = pedido.get("cod_material") or pedido.get("codigo_material") or pedido.get("material_cod")
        desc = pedido.get("descricao") or pedido.get("material_desc") or pedido.get("material")

        # Contexto mínimo para a ficha
        st.session_state["material_fixo"] = {"cod": cod, "desc": desc}
        st.session_state["tipo_busca_ficha"] = "alerta"
        st.session_state["equipamento_ctx"] = ""
        st.session_state["departamento_ctx"] = pedido.get("departamento", "") or ""
        st.session_state["modo_ficha_material"] = True

        # Se seu app usa navegação por st.session_state.pagina, tentamos direcionar.

        # Navegação no app (fonte de verdade): current_page
        st.session_state["current_page"] = "Ficha de Material"
        # Mantém o rádio sincronizado no próximo rerun
        st.session_state["_force_menu_sync"] = True
        return
    except Exception as e:
        st.warning(f"⚠️ Não foi possível abrir a ficha do material: {e}")

def exibir_alertas_completo(alertas: dict, formatar_moeda_br):

    # Reset de filtros globais (executa ANTES de instanciar widgets)
    if st.session_state.get("__clear_global_filters"):
        st.session_state["__clear_global_filters"] = False
        # Reset multiselects
        st.session_state["alertas_global_dept"] = []
        st.session_state["alertas_global_forn"] = []
        # Reset slider para range total (se possível)
        try:
            # 'valores' será calculado mais abaixo; então usamos um fallback neutro aqui.
            # Atribuímos um placeholder e recalculamos após ter 'valores' usando um segundo flag.
            st.session_state["__reset_valor_range"] = True
        except Exception:
            pass

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


    def _paginate(itens: list, key_prefix: str, per_page_default: int = 10):
        """Paginação compacta com navegação (prev/next) e indicador de página."""
        if not itens:
            return [], 0, 0, per_page_default

        per_page_opts = [10, 20, 30, 50]
        per_page = st.selectbox(
            "Itens por página",
            options=per_page_opts,
            index=per_page_opts.index(per_page_default) if per_page_default in per_page_opts else 0,
            key=f"{key_prefix}_per_page",
            label_visibility="collapsed",
        )

        total = len(itens)
        total_pages = max(1, int(math.ceil(total / per_page)))

        page_key = f"{key_prefix}_page"
        page = int(st.session_state.get(page_key, 1))
        page = max(1, min(total_pages, page))

        # Barra compacta
        nav_l, nav_m, nav_r = st.columns([2, 6, 2])

        with nav_l:
            c1, c2 = st.columns([1, 1])
            with c1:
                if st.button("◀", key=f"{key_prefix}_prev", disabled=(page <= 1), use_container_width=True):
                    page -= 1
            with c2:
                if st.button("▶", key=f"{key_prefix}_next", disabled=(page >= total_pages), use_container_width=True):
                    page += 1

        with nav_m:
            st.markdown(
                f"""
                <div style="
                    text-align:center;
                    padding: 4px 10px;
                    border-radius: 12px;
                    background: rgba(255,255,255,0.05);
                    border: 1px solid rgba(255,255,255,0.10);
                    font-weight: 800;
                    opacity: 0.92;
                ">
                    Página {page} de {total_pages}
                    <span style="opacity:0.75; font-weight:700;"> • </span>
                    <span style="opacity:0.78; font-weight:700;">{total} itens</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with nav_r:
            st.markdown(
                f"""
                <div style="
                    text-align:right;
                    padding-top: 2px;
                    opacity: 0.82;
                    font-size: 12px;
                ">
                    Exibindo {min(total, (page-1)*per_page+1)}–{min(total, page*per_page)}
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.session_state[page_key] = int(page)

        start = (page - 1) * per_page
        end = start + per_page
        return itens[start:end], total, total_pages, per_page

    # ============================
    # Status de alerta (persistência em sessão)
    # ============================
    if "alert_status" not in st.session_state:
        st.session_state["alert_status"] = {}  # {alert_id: status}

    def get_alert_status(alert_id: str) -> str:
        return str(st.session_state["alert_status"].get(str(alert_id), "Novo"))

    def set_alert_status(alert_id: str, status: str) -> None:
        st.session_state["alert_status"][str(alert_id)] = str(status)

    def _badge_status(status: str) -> str:
        s = (status or "Novo").lower().strip()
        if s.startswith("res"):
            bg = "rgba(16,185,129,0.18)"; bd="rgba(16,185,129,0.35)"; fg="#10b981"
            label = "Resolvido"
        elif s.startswith("em"):
            bg = "rgba(245,158,11,0.18)"; bd="rgba(245,158,11,0.35)"; fg="#f59e0b"
            label = "Em andamento"
        else:
            bg = "rgba(147,197,253,0.18)"; bd="rgba(147,197,253,0.35)"; fg="#93c5fd"
            label = "Novo"
        return f"""<span style="display:inline-block;padding:2px 10px;border-radius:999px;background:{bg};border:1px solid {bd};color:{fg};font-weight:800;font-size:12px;">{label}</span>"""


    st.markdown("<div class='fu-header'><h1>🔔 Central de Notificações e Alertas</h1><div class='fu-sub'>Visão executiva + ações rápidas</div></div>", unsafe_allow_html=True)

    # CSS (PRECISA ficar dentro da função)
    st.markdown(
        """
        <style>
          /* === Clean Dark SaaS (menos poluição) === */
          .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
          div[data-testid="stVerticalBlock"] { gap: 0.8rem; }

          /* Header */
          .fu-header h1 { margin: 0; font-size: 26px; font-weight: 900; }
          .fu-sub { opacity: .78; margin-top: 4px; font-size: 13px; }

          /* Filters bar */
          .fu-bar {
            padding: 10px 12px;
            border-radius: 14px;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.08);
          }

          /* KPI slim */
          .fu-kpi {
            padding: 10px 12px;
            border-radius: 14px;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.08);
          }
          .fu-kpi-title { font-size: 12px; opacity: 0.85; margin: 0 0 6px 0; }
          .fu-kpi-value { font-size: 24px; font-weight: 900; line-height: 1.05; margin: 0; }
          .fu-kpi-sub { font-size: 12px; opacity: 0.75; margin: 6px 0 0 0; }

          /* Toolbar */
          .fu-toolbar {
            padding: 8px 10px;
            border-radius: 14px;
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(255,255,255,0.06);
          }

          /* Slim cards */
          .fu-card {
            padding: 12px 12px;
            border-radius: 14px;
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(255,255,255,0.06);
            margin-bottom: 10px;
          }
          .fu-card p { margin: 0; }
          .fu-line1 { display:flex; gap:10px; align-items:center; }
          .fu-oc { font-size: 13px; font-weight: 900; }
          .fu-desc { font-size: 13px; opacity: .92; margin-top: 6px; }
          .fu-meta { font-size: 12px; opacity: .76; margin-top: 6px; }
          .fu-meta b { opacity: .95; }

          /* Reduce widget vertical spacing a bit */
          div[data-testid="stSelectbox"], div[data-testid="stMultiSelect"], div[data-testid="stSlider"] { margin-bottom: -6px; }
        
          /* Toolbar controls */
          div[data-testid="stButton"] > button {
            white-space: nowrap !important;
            height: 36px !important;
            padding: 0 12px !important;
            border-radius: 12px !important;
            font-weight: 900 !important;
          }
          div[data-testid="stSelectbox"] div[role="combobox"] {
            min-height: 36px !important;
            border-radius: 12px !important;
          }
          div[data-testid="stTextInput"] input {
            min-height: 36px !important;
            border-radius: 12px !important;
          }

        
          /* Global filter row: remove big container look */
          .fu-bar { background: transparent !important; border: none !important; padding: 0 !important; }
          .fu-sep { height: 1px; background: rgba(255,255,255,0.06); margin: 10px 0 8px 0; border-radius: 999px; }

          /* Slider: less noisy numbers */
          div[data-testid="stSlider"] { padding-top: 0px; }
          div[data-testid="stSlider"] [data-baseweb="slider"] { padding-top: 0px; }

        
          /* Global bar inputs */
          div[data-testid="stNumberInput"] input { min-height: 36px !important; border-radius: 12px !important; }

        
          /* Global bar text inputs */
          div[data-testid="stTextInput"] input { font-weight: 800; }

        </style>
        """,
        unsafe_allow_html=True,
    )


    # ============================
    # Filtros globais (afetam KPIs e todas as abas)
    # ============================
    pedidos_todos = (
        list(alertas.get("pedidos_atrasados", []))
        + list(alertas.get("pedidos_vencendo", []))
        + list(alertas.get("pedidos_criticos", []))
    )

    # Opções de filtros
    departamentos_opts = sorted(
        {safe_text(p.get("departamento", "N/A")) for p in pedidos_todos if p.get("departamento") is not None}
    )
    fornecedores_opts = sorted(
        {
            safe_text(x.get("fornecedor", "N/A"))
            for x in (pedidos_todos + list(alertas.get("fornecedores_baixa_performance", [])))
            if x is not None
        }
    )

    # Faixa de valor (somente para pedidos)
    valores = [float(p.get("valor", 0.0) or 0.0) for p in pedidos_todos]
    vmin = float(min(valores)) if valores else 0.0
    vmax = float(max(valores)) if valores else 0.0
    # Se o usuário pediu "Limpar", agora que temos vmin/vmax, resetamos o slider
    if st.session_state.get("__reset_valor_range"):
        st.session_state["__reset_valor_range"] = False
        st.session_state["alertas_global_valor_min_txt"] = str(int(vmin))
        st.session_state["alertas_global_valor_max_txt"] = str(int(vmax))

    colg1, colg2, colg3, colg4 = st.columns([4,4,3.5,1.5])
    with colg1:
        dept_global = st.multiselect(
            "Departamento",
            options=departamentos_opts,
            default=[],
            key="alertas_global_dept",
            label_visibility="collapsed",
            placeholder="Todos",
        )
    with colg2:
        forn_global = st.multiselect(
            "Fornecedor",
            options=fornecedores_opts,
            default=[],
            key="alertas_global_forn",
            label_visibility="collapsed",
        )
    with colg3:
        if vmax > 0:
            
            
            # Faixa de valor (BR): inputs texto (R$) para evitar visual "técnico"
            def _fmt_br_int(x: float) -> str:
                try:
                    return f"{int(round(float(x))):,}".replace(",", "X").replace(".", ",").replace("X", ".")
                except Exception:
                    return "0"

            def _parse_br_num(s: str) -> float:
                s = (s or "").strip().lower()
                s = s.replace("r$", "").replace(" ", "")
                s = s.replace(".", "").replace(",", ".")
                try:
                    return float(s)
                except Exception:
                    return 0.0

            cmin, cmax = st.columns([1, 1])
            with cmin:
                raw_min = st.text_input(
                    "",
                    value=st.session_state.get("alertas_global_valor_min_txt", _fmt_br_int(vmin)),
                    key="alertas_global_valor_min_txt",
                    placeholder="Mín (ex: 1.000)",
                    label_visibility="collapsed",
                )
            with cmax:
                raw_max = st.text_input(
                    "",
                    value=st.session_state.get("alertas_global_valor_max_txt", _fmt_br_int(vmax)),
                    key="alertas_global_valor_max_txt",
                    placeholder="Máx (ex: 50.000)",
                    label_visibility="collapsed",
                )

            vmin_in = _parse_br_num(raw_min)
            vmax_in = _parse_br_num(raw_max)

            # Normaliza e limita ao intervalo real
            lo = float(max(vmin, min(vmax, min(vmin_in, vmax_in))))
            hi = float(max(vmin, min(vmax, max(vmin_in, vmax_in))))
            faixa_valor = (lo, hi)
            st.markdown(f"<div style='text-align:right;font-size:12px;opacity:.75;margin-top:4px;'>R$ {faixa_valor[0]:,.0f} — R$ {faixa_valor[1]:,.0f}</div>".replace(',', 'X').replace('.', ',').replace('X','.'), unsafe_allow_html=True)
        else:
            faixa_valor = (0.0, 0.0)
            st.caption("Valor (global): sem dados")


        with colg4:
            st.markdown("<div style='font-size:12px;opacity:.75;margin-bottom:2px;text-align:right;'>Ações<br><span style='opacity:.65;font-size:11px;'>Limpa filtros</span></div>", unsafe_allow_html=True)
            if st.button("🧹 Limpar", key="alertas_global_clear", use_container_width=True):
                st.session_state["__clear_global_filters"] = True

    def _filtrar_pedidos(lista: list[dict]) -> list[dict]:
        if not lista:
            return []
        out = []
        for p in lista:
            dept_ok = True
            if dept_global:
                dept_ok = safe_text(p.get("departamento", "N/A")) in dept_global

            forn_ok = True
            if forn_global:
                forn_ok = safe_text(p.get("fornecedor", "N/A")) in forn_global

            val = float(p.get("valor", 0.0) or 0.0)
            val_ok = True
            if vmax > 0:
                val_ok = faixa_valor[0] <= val <= faixa_valor[1]

            if dept_ok and forn_ok and val_ok:
                out.append(p)
        return out

    def _filtrar_fornecedores(lista: list[dict]) -> list[dict]:
        if not lista:
            return []
        if not forn_global:
            return lista
        return [f for f in lista if safe_text(f.get("fornecedor", "N/A")) in forn_global]

    # Aplicar filtros globais
    alertas = {
        "pedidos_atrasados": _filtrar_pedidos(alertas.get("pedidos_atrasados", [])),
        "pedidos_vencendo": _filtrar_pedidos(alertas.get("pedidos_vencendo", [])),
        "pedidos_criticos": _filtrar_pedidos(alertas.get("pedidos_criticos", [])),
        "fornecedores_baixa_performance": _filtrar_fornecedores(alertas.get("fornecedores_baixa_performance", [])),
    }
    alertas["total"] = (
        len(alertas["pedidos_atrasados"])
        + len(alertas["pedidos_vencendo"])
        + len(alertas["pedidos_criticos"])
        + len(alertas["fornecedores_baixa_performance"])
    )

    # ============================
    # Resumo geral no topo (já filtrado)
    # ============================
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


    # ============================
    # Filtros Globais (aplicam em todas as abas)
    # ============================
    pedidos_all = (
        list(alertas.get("pedidos_atrasados", []))
        + list(alertas.get("pedidos_vencendo", []))
        + list(alertas.get("pedidos_criticos", []))
    )

    deps_all = sorted(list({safe_text(p.get("departamento", "N/A")) for p in pedidos_all if p is not None}))
    forns_all = sorted(list({safe_text(p.get("fornecedor", "N/A")) for p in pedidos_all if p is not None}))
    # incluir fornecedores da aba de performance também
    forns_perf = sorted(list({safe_text(p.get("fornecedor", "N/A")) for p in alertas.get("fornecedores_baixa_performance", [])}))
    forns_all = sorted(list(set(forns_all + forns_perf)))

    vals = [float(p.get("valor", 0) or 0) for p in pedidos_all if p is not None]
    vmin = float(min(vals)) if vals else 0.0
    vmax = float(max(vals)) if vals else 0.0

    def _apply_global_pedidos(lista):
        if not lista:
            return []
        out = lista

        if dept_global:
            out = [p for p in out if safe_text(p.get("departamento", "N/A")) in dept_global]

        if forn_global:
            out = [p for p in out if safe_text(p.get("fornecedor", "N/A")) in forn_global]

        if vmax > 0:
            lo, hi = faixa_valor
            out = [p for p in out if lo <= float(p.get("valor", 0) or 0) <= hi]

        return out

    def _apply_global_fornecedores(lista):
        if not lista:
            return []
        out = lista
        if forn_global:
            out = [f for f in out if safe_text(f.get("fornecedor", "N/A")) in forn_global]
        return out


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

        pedidos_base = _apply_global_pedidos(alertas.get("pedidos_atrasados", []))

        if pedidos_base:

            # Ranking rápido por departamento (após filtro global)
            try:
                df_rank = pd.DataFrame(pedidos_base)
                if "departamento" in df_rank.columns and not df_rank.empty:
                    rank = (
                        df_rank.groupby("departamento", dropna=False)
                        .agg(qtde=("departamento", "size"), valor_total=("valor", "sum"))
                        .sort_values(["qtde", "valor_total"], ascending=False)
                        .head(10)
                        .reset_index()
                    )
                    with st.expander("🏷️ Top departamentos com atrasos", expanded=False):
                        st.dataframe(rank, use_container_width=True, hide_index=True)
            except Exception:
                pass
            col_filtro1, col_filtro2 = st.columns([3, 5])
            with col_filtro1:
                ordem = st.selectbox(
                    "Ordenar",
                    [
                        "Dias (maior)",
                        "Dias (menor)",
                        "Valor (maior)",
                        "Valor (menor)",
                    ],
                    key="filtro_atrasados_ordem",
                    label_visibility="collapsed",
                )
            with col_filtro2:
                busca = st.text_input("Buscar (OC/descrição/fornecedor)", value="", key="filtro_atrasados_busca", label_visibility="collapsed")

            if "Dias (maior)" in ordem:
                pedidos_filtrados = sorted(pedidos_base, key=lambda x: x.get("dias_atraso", 0), reverse=True)
            elif "Dias (menor)" in ordem:
                pedidos_filtrados = sorted(pedidos_base, key=lambda x: x.get("dias_atraso", 0))
            elif "Valor (maior)" in ordem:
                pedidos_filtrados = sorted(pedidos_base, key=lambda x: x.get("valor", 0), reverse=True)
            elif "Valor (menor)" in ordem:
                pedidos_filtrados = sorted(pedidos_base, key=lambda x: x.get("valor", 0))
            else:
                pedidos_filtrados = pedidos_base

            # Busca simples (usa filtros globais já aplicados)
            if busca:
                b = busca.strip().lower()
                def _hit(p):
                    return (b in str(p.get('nr_oc','')).lower() or b in str(p.get('descricao','')).lower() or b in str(p.get('fornecedor','')).lower())
                pedidos_filtrados = [p for p in pedidos_filtrados if _hit(p)]
            st.caption(f"📊 Mostrando {len(pedidos_filtrados)} de {len(pedidos_base)} (após filtro global) pedidos atrasados")

                        # Toolbar (paginação + lote) — compacto
            t1, t2, t3, t4, t5, t6 = st.columns([2, 1.1, 1.4, 1.1, 2.3, 6.1])
            with t1:
                per_page = st.selectbox("Por pág.", [10, 20, 30, 50], index=0, key="tab_criticos_pp", label_visibility="collapsed")
            with t2:
                prev = st.button("◀", key="tab_criticos_prev2", use_container_width=True, disabled=int(st.session_state.get("tab_criticos_page", 1)) <= 1)
            with t3:
                st.markdown(
                    f"<div style='text-align:center; padding:4px 10px; border-radius:12px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); font-weight:900;'>{int(st.session_state.get('tab_criticos_page',1))}</div>",
                    unsafe_allow_html=True
                )
            with t4:
                nextb = st.button("▶", key="tab_criticos_next2", use_container_width=True)
            with t5:
                bulk_status = st.selectbox("Status", ["Novo", "Em andamento", "Resolvido"], key="tab_criticos_bulk_status", label_visibility="collapsed")
            with t6:
                cA, cB, cC = st.columns([2.6, 1.6, 1.8])
                with cA:
                    marcar_pagina = st.button("✅ Sel. pág.", key="tab_criticos_sel_page", use_container_width=True)
                with cB:
                    limpar_sel = st.button("🧹 Limpar", key="tab_criticos_clear_sel", use_container_width=True)
                with cC:
                    aplicar_lote = st.button("⚡ Aplicar", key="tab_criticos_apply_bulk", use_container_width=True)

            # Paginação (estado)
            total = len(pedidos_filtrados)
            total_pages = max(1, int(math.ceil(total / per_page)))
            page_key = "tab_criticos_page"
            page = int(st.session_state.get(page_key, 1))
            if prev:
                page -= 1
            if nextb:
                page += 1
            page = max(1, min(total_pages, page))
            st.session_state[page_key] = int(page)

            start_i = (page - 1) * per_page
            end_i = start_i + per_page
            pagina_itens = pedidos_filtrados[start_i:end_i]

            st.caption(f"📄 Página {page}/{total_pages} — exibindo {len(pagina_itens)} de {total}")

            if marcar_pagina or limpar_sel:
                for _i, _p in enumerate(pagina_itens):
                    _aid = str(_p.get("id") or _p.get("nr_oc") or f"row{_i}")
                    _nr = str(_p.get("nr_oc", "") or "")
                    _base_key = f"critico_{_aid}_{_nr}_{_i}"
                    st.session_state[f"sel_{_base_key}"] = bool(marcar_pagina)

            if aplicar_lote:
                for _i, _p in enumerate(pagina_itens):
                    _aid = str(_p.get("id") or _p.get("nr_oc") or f"row{_i}")
                    _nr = str(_p.get("nr_oc", "") or "")
                    _base_key = f"critico_{_aid}_{_nr}_{_i}"
                    if bool(st.session_state.get(f"sel_{_base_key}", False)):
                        set_alert_status(_aid, bulk_status)

            if pagina_itens:
                st.warning("⚠️ Pedidos de alto valor com previsão de entrega próxima")
                
                for i, pedido in enumerate(pagina_itens):
                    aid = str(pedido.get('id') or pedido.get('nr_oc') or f'row{i}')
                    pedido['id'] = aid
                    criar_card_pedido(pedido, "critico", formatar_moeda_br, idx=i, status=get_alert_status(aid))
            else:
                st.info("📭 Nenhum pedido crítico corresponde aos filtros selecionados")
        else:
            st.success("✅ Nenhum pedido crítico no momento")
    
    with tab4:
        st.subheader("📉 Fornecedores com Baixa Performance")

        fornecedores_base = _apply_global_fornecedores(alertas.get('fornecedores_baixa_performance', []))

        if fornecedores_base:
            # Extrair nomes de fornecedores únicos
            nomes_fornecedores = sorted(list(set(
                [safe_text(f.get('fornecedor', 'N/A')) for f in fornecedores_base]
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
            for fornecedor in fornecedores_base:
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
            st.caption(f"📊 Mostrando {len(fornecedores_filtrados)} de {len(fornecedores_base)} (após filtro global) fornecedores")
            
            if fornecedores_filtrados:
                st.warning("⚠️ Fornecedores com taxa de sucesso abaixo de 70%")
                
                for fornecedor in fornecedores_filtrados:
                    criar_card_fornecedor(fornecedor, formatar_moeda_br)
            else:
                st.info("📭 Nenhum fornecedor corresponde aos filtros selecionados")
        else:
            st.success("✅ Todos os fornecedores com boa performance!")
