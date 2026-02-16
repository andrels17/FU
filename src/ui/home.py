from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import textwrap
from collections import defaultdict
import streamlit as st


def exibir_home(alertas: dict, usuario_nome: str = "Usuário") -> None:
    # -----------------------------
    # Saudação (timezone correto)
    # -----------------------------
    hora = datetime.now(ZoneInfo("America/Fortaleza")).hour
    if hora < 12:
        saudacao = "Bom dia"
    elif hora < 18:
        saudacao = "Boa tarde"
    else:
        saudacao = "Boa noite"

    # -----------------------------
    # Empresa (tenant)
    # -----------------------------
    empresa_nome = ""
    tenants = st.session_state.get("tenant_options", []) or []
    tenant_id = st.session_state.get("tenant_id")
    for t in tenants:
        if isinstance(t, dict) and t.get("tenant_id") == tenant_id:
            empresa_nome = (t.get("nome") or t.get("name") or t.get("razao_social") or "").strip()
            break

    # -----------------------------
    # KPIs (corrigidos)
    # Seu alertas é baseado em listas: pedidos_atrasados/criticos/vencendo :contentReference[oaicite:2]{index=2}
    # -----------------------------
    def _safe_list_len(v) -> int:
        try:
            return int(len(v or []))
        except Exception:
            return 0

    atrasados = _safe_list_len(alertas.get("pedidos_atrasados"))
    criticos = _safe_list_len(alertas.get("pedidos_criticos"))
    vencendo = _safe_list_len(alertas.get("pedidos_vencendo"))

    # Fallback compat (se algum dia vier como número)
    if (atrasados == 0 and criticos == 0 and vencendo == 0):
        try:
            atrasados = int(alertas.get("atrasados", 0) or 0)
        except Exception:
            atrasados = 0
        try:
            criticos = int(alertas.get("criticos", 0) or 0)
        except Exception:
            criticos = 0
        try:
            vencendo = int(alertas.get("vencendo", 0) or 0)
        except Exception:
            vencendo = 0

    total_pontos = int(atrasados + criticos + vencendo)

    # -----------------------------
    # Navegação
    # -----------------------------
    def _go(page: str) -> None:
        st.session_state.current_page = page
        st.rerun()

    # -----------------------------
    # Helpers para lista "Top 5"
    # -----------------------------
    def _top_n(lista: list, n: int = 5):
        return list(lista or [])[:n]

    def _as_float(x, default=0.0):
        try:
            return float(x or 0.0)
        except Exception:
            return float(default)

    def _as_int(x, default=0):
        try:
            return int(x or 0)
        except Exception:
            return int(default)

    def _safe_str(x, default="N/A"):
        s = str(x).strip() if x is not None else ""
        return s if s else default

    def _moeda_br(v: float) -> str:
        # Formata "1234567.89" -> "1.234.568" (sem centavos pra ficar executivo)
        s = f"{float(v):,.0f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")

    # Listas vindas do seu cálculo de alertas :contentReference[oaicite:3]{index=3}
    lista_criticos = list(alertas.get("pedidos_criticos", []) or [])
    lista_atrasados = list(alertas.get("pedidos_atrasados", []) or [])
    lista_vencendo = list(alertas.get("pedidos_vencendo", []) or [])

    # Ordenações executivas
    criticos_top = sorted(lista_criticos, key=lambda p: _as_float((p or {}).get("valor", 0)), reverse=True)
    atrasados_top = sorted(lista_atrasados, key=lambda p: _as_int((p or {}).get("dias_atraso", 0)), reverse=True)
    vencendo_top = sorted(lista_vencendo, key=lambda p: _as_int((p or {}).get("dias_restantes", 0)))

    # -----------------------------
    # CSS (SaaS internacional)
    # -----------------------------
    st.markdown(
        textwrap.dedent(
            """
            <style>
              .fu-wrap { max-width: 1200px; margin: 0 auto; }

              .fu-hero {
                border-radius: 22px;
                padding: 22px 22px;
                background:
                  radial-gradient(900px 420px at 12% 0%, rgba(245,158,11,0.18), transparent 60%),
                  radial-gradient(900px 420px at 85% 20%, rgba(59,130,246,0.14), transparent 60%),
                  rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08);
                box-shadow: 0 18px 55px rgba(0,0,0,0.35);
              }
              .fu-hero-top { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; }
              .fu-title { margin:0; font-size: 1.55rem; font-weight: 900; letter-spacing: 0.2px; }
              .fu-sub { margin:6px 0 0 0; opacity:.78; font-size: 0.98rem; line-height: 1.35; }
              .fu-chip {
                display:inline-flex; align-items:center; gap:8px;
                padding: 7px 12px;
                border-radius: 999px;
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.10);
                font-size: 0.85rem;
                opacity: .86;
                white-space: nowrap;
              }

              .fu-grid { margin-top: 14px; display:grid; grid-template-columns: repeat(12, 1fr); gap: 12px; }
              .fu-card {
                border-radius: 18px;
                padding: 16px 16px;
                background: rgba(255,255,255,0.035);
                border: 1px solid rgba(255,255,255,0.08);
                transition: transform .14s ease, border-color .14s ease, background-color .14s ease;
              }
              .fu-card:hover { transform: translateY(-2px); border-color: rgba(245,158,11,0.30); background: rgba(255,255,255,0.045); }
              .fu-kpi-num { margin:0; font-size: 30px; font-weight: 950; letter-spacing: 0.2px; }
              .fu-kpi-lbl { margin:2px 0 0 0; font-size: 12.5px; opacity: .75; }

              .fu-section-title { margin: 18px 0 10px 0; font-size: 1.05rem; font-weight: 900; opacity:.94; }
              .fu-note {
                border-radius: 18px;
                padding: 14px 16px;
                background: linear-gradient(135deg, rgba(245,158,11,0.10), rgba(255,255,255,0.03));
                border: 1px solid rgba(245,158,11,0.22);
              }
              .fu-note p { margin:0; opacity:.88; }

              .fu-actions .stButton button { border-radius: 14px; height: 44px; }
              .fu-muted { opacity: .72; font-size: 0.92rem; }

              .fu-mini {
                border-radius: 16px;
                padding: 14px 14px;
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08);
              }
              .fu-mini h4 { margin:0 0 8px 0; font-size: 0.98rem; }
              .fu-item {
                padding: 10px 10px;
                border-radius: 12px;
                border: 1px solid rgba(255,255,255,0.06);
                background: rgba(255,255,255,0.02);
                margin-bottom: 8px;
              }
              .fu-item:last-child { margin-bottom: 0; }
              .fu-item-top { display:flex; align-items:center; justify-content:space-between; gap:10px; }
              .fu-item-oc { font-weight: 900; }
              .fu-pill {
                padding: 2px 10px;
                border-radius: 999px;
                font-size: 11px;
                font-weight: 900;
                border: 1px solid rgba(255,255,255,0.10);
                background: rgba(255,255,255,0.03);
                opacity: .9;
                white-space: nowrap;
              }
              .fu-item-desc { margin: 6px 0 0 0; opacity: .78; font-size: 12.5px; line-height: 1.25; }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )

    # -----------------------------
    # Layout
    # -----------------------------
    st.markdown('<div class="fu-wrap">', unsafe_allow_html=True)

    # HERO
    empresa_txt = f"🏢 {empresa_nome}" if empresa_nome else "🏢 Multiempresa"
    st.markdown(
        f"""
        <div class="fu-hero">
          <div class="fu-hero-top">
            <div>
              <h2 class="fu-title">👋 {saudacao}, {usuario_nome}!</h2>
              <p class="fu-sub">
                Visão geral do seu dia no Follow-up.
                <span style="opacity:.92;"><b>{total_pontos}</b></span> ponto(s) de atenção entre atrasos, críticos e vencimentos.
              </p>
            </div>
            <div class="fu-chip">{empresa_txt}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # KPIs
    st.markdown('<div class="fu-grid">', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="fu-card" style="grid-column: span 4;">
          <p class="fu-kpi-num">⚠️ {atrasados}</p>
          <p class="fu-kpi-lbl">Pedidos atrasados</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="fu-card" style="grid-column: span 4;">
          <p class="fu-kpi-num">🚨 {criticos}</p>
          <p class="fu-kpi-lbl">Pedidos críticos</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="fu-card" style="grid-column: span 4;">
          <p class="fu-kpi-num">⏰ {vencendo}</p>
          <p class="fu-kpi-lbl">Vencendo / próximos</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)  # end grid

    # Resumo operacional
    st.markdown('<div class="fu-section-title">📌 Resumo operacional</div>', unsafe_allow_html=True)
    if criticos > 0:
        msg = f"🚨 Você tem {criticos} pedido(s) crítico(s). Priorize follow-up imediato."
    elif atrasados > 0:
        msg = f"⚠️ Existem {atrasados} pedido(s) atrasado(s). Recomendado acionar fornecedor e atualizar status."
    elif vencendo > 0:
        msg = f"⏰ Você tem {vencendo} pedido(s) vencendo em breve. Vale revisar prazos e pendências."
    else:
        msg = "✅ Tudo sob controle. Sem críticos/atrasos/vencimentos relevantes agora."
    st.markdown(f'<div class="fu-note"><p>{msg}</p></div>', unsafe_allow_html=True)

    # Prioridades do dia (Top 5)
    st.markdown('<div class="fu-section-title">🎯 Prioridades do dia</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown('<div class="fu-mini"><h4>🚨 Críticos (Top 5)</h4>', unsafe_allow_html=True)
        if criticos_top:
            for p in _top_n(criticos_top, 5):
                nr = _safe_str((p or {}).get("nr_oc"))
                forn = _safe_str((p or {}).get("fornecedor"))
                desc = _safe_str((p or {}).get("descricao"), default="")
                valor = _moeda_br(_as_float((p or {}).get("valor", 0)))
                st.markdown(
                    f"""
                    <div class="fu-item">
                      <div class="fu-item-top">
                        <div class="fu-item-oc">OC {nr}</div>
                        <div class="fu-pill">R$ {valor}</div>
                      </div>
                      <div class="fu-item-desc">{forn}<br>{(desc[:90] + "…") if len(desc) > 90 else desc}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.caption("✅ Sem críticos agora.")
        st.markdown("</div>", unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="fu-mini"><h4>⚠️ Atrasados (Top 5)</h4>', unsafe_allow_html=True)
        if atrasados_top:
            for p in _top_n(atrasados_top, 5):
                nr = _safe_str((p or {}).get("nr_oc"))
                forn = _safe_str((p or {}).get("fornecedor"))
                dias = _as_int((p or {}).get("dias_atraso", 0))
                dept = _safe_str((p or {}).get("departamento"), default="—")
                st.markdown(
                    f"""
                    <div class="fu-item">
                      <div class="fu-item-top">
                        <div class="fu-item-oc">OC {nr}</div>
                        <div class="fu-pill">{dias} dia(s)</div>
                      </div>
                      <div class="fu-item-desc">{forn}<br>{dept}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.caption("✅ Sem atrasos agora.")
        st.markdown("</div>", unsafe_allow_html=True)

    with c3:
        st.markdown('<div class="fu-mini"><h4>⏰ Vencendo (Top 5)</h4>', unsafe_allow_html=True)
        if vencendo_top:
            for p in _top_n(vencendo_top, 5):
                nr = _safe_str((p or {}).get("nr_oc"))
                forn = _safe_str((p or {}).get("fornecedor"))
                dias = _as_int((p or {}).get("dias_restantes", 0))
                prev = _safe_str((p or {}).get("previsao"), default="—")
                st.markdown(
                    f"""
                    <div class="fu-item">
                      <div class="fu-item-top">
                        <div class="fu-item-oc">OC {nr}</div>
                        <div class="fu-pill">{dias} dia(s)</div>
                      </div>
                      <div class="fu-item-desc">{forn}<br>Prev.: {prev}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.caption("✅ Sem vencimentos próximos.")
        st.markdown("</div>", unsafe_allow_html=True)

    def _sum_valor(lista: list[dict]) -> float:
        total = 0.0
        for p in (lista or []):
            try:
                total += float((p or {}).get("valor") or 0.0)
            except Exception:
                pass
        return float(total)
    
    def _group_count(lista: list[dict], key: str) -> dict[str, int]:
        acc = defaultdict(int)
        for p in (lista or []):
            k = str((p or {}).get(key) or "").strip()
            if not k:
                k = "Não informado"
            acc[k] += 1
        return dict(acc)
    
    def _group_sum_valor(lista: list[dict], key: str) -> dict[str, float]:
        acc = defaultdict(float)
        for p in (lista or []):
            k = str((p or {}).get(key) or "").strip()
            if not k:
                k = "Não informado"
            try:
                acc[k] += float((p or {}).get("valor") or 0.0)
            except Exception:
                pass
        return dict(acc)
    
    def _top_item(d: dict, by_value=True):
        if not d:
            return None, 0
        if by_value:
            k = max(d, key=lambda x: float(d.get(x) or 0))
            return k, float(d.get(k) or 0)
        else:
            k = max(d, key=lambda x: int(d.get(x) or 0))
            return k, int(d.get(k) or 0)
    
    def _pct(part: float, total: float) -> int:
        if total <= 0:
            return 0
        try:
            return int(round((part / total) * 100))
        except Exception:
            return 0
    
    # Reusa as listas que você já montou acima
    # lista_criticos, lista_atrasados, lista_vencendo
    
    valor_critico = _sum_valor(lista_criticos)
    valor_atrasado = _sum_valor(lista_atrasados)
    valor_risco_total = valor_critico + valor_atrasado
    
    # Concentração por departamento (atrasados)
    dept_counts = _group_count(lista_atrasados, "departamento")
    dept_top, dept_top_qtd = _top_item(dept_counts, by_value=False)
    dept_pct = _pct(dept_top_qtd, sum(dept_counts.values()) if dept_counts else 0)
    
    # Fornecedor mais crítico (por valor em risco = críticos + atrasados)
    forn_val = _group_sum_valor((lista_criticos or []) + (lista_atrasados or []), "fornecedor")
    forn_top, forn_top_valor = _top_item(forn_val, by_value=True)
    
    # Maior atraso observado
    maior_atraso = 0
    try:
        maior_atraso = max([int((p or {}).get("dias_atraso") or 0) for p in (lista_atrasados or [])] or [0])
    except Exception:
        maior_atraso = 0
    
    # “Vencendo em 48h”
    vencendo_48h = 0
    try:
        vencendo_48h = sum(1 for p in (lista_vencendo or []) if int((p or {}).get("dias_restantes") or 9999) <= 2)
    except Exception:
        vencendo_48h = 0
    
    st.markdown('<div class="fu-section-title">🧠 Insights</div>', unsafe_allow_html=True)
    
    i1, i2, i3 = st.columns(3)
    
    with i1:
        st.markdown(
            f"""
            <div class="fu-card" style="grid-column: span 4;">
              <p class="fu-kpi-num">💰 R$ {_moeda_br(valor_risco_total)}</p>
              <p class="fu-kpi-lbl">Risco financeiro (críticos + atrasados)</p>
              <p class="fu-item-desc" style="margin-top:8px;">
                Críticos: <b>R$ {_moeda_br(valor_critico)}</b> •
                Atrasados: <b>R$ {_moeda_br(valor_atrasado)}</b>
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    with i2:
        if dept_top and sum(dept_counts.values()) > 0:
            st.markdown(
                f"""
                <div class="fu-card" style="grid-column: span 4;">
                  <p class="fu-kpi-num">🏭 {dept_pct}%</p>
                  <p class="fu-kpi-lbl">{dept_top} concentra {dept_pct}% dos atrasos</p>
                  <p class="fu-item-desc" style="margin-top:8px;">
                    {dept_top_qtd} de {sum(dept_counts.values())} pedido(s) atrasado(s)
                  </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div class="fu-card" style="grid-column: span 4;">
                  <p class="fu-kpi-num">🏭 —</p>
                  <p class="fu-kpi-lbl">Sem atrasos para calcular concentração</p>
                  <p class="fu-item-desc" style="margin-top:8px;">Quando houver atrasos, mostramos o depto dominante.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    
    with i3:
        if forn_top and forn_top_valor > 0:
            st.markdown(
                f"""
                <div class="fu-card" style="grid-column: span 4;">
                  <p class="fu-kpi-num">🏢 {forn_top}</p>
                  <p class="fu-kpi-lbl">Fornecedor com maior valor em risco</p>
                  <p class="fu-item-desc" style="margin-top:8px;">
                    Em risco: <b>R$ {_moeda_br(forn_top_valor)}</b> • Maior atraso: <b>{maior_atraso} dia(s)</b>
                  </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
                <div class="fu-card" style="grid-column: span 4;">
                  <p class="fu-kpi-num">✅ OK</p>
                  <p class="fu-kpi-lbl">Sem valor em risco relevante agora</p>
                  <p class="fu-item-desc" style="margin-top:8px;">
                    Vencendo em 48h: <b>{vencendo_48h}</b>
                  </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    
    # Insight adicional curto (linha única)
    if vencendo_48h > 0:
        st.info(f"⏰ Atenção: {vencendo_48h} pedido(s) vencendo em até 48h. Pode valer um follow-up preventivo.")
    elif maior_atraso >= 10:
        st.warning(f"⚠️ Maior atraso observado: {maior_atraso} dia(s). Recomendo priorizar tratativa com fornecedor.")

    # Ações rápidas
    st.markdown('<div class="fu-section-title">⚡ Ações rápidas</div>', unsafe_allow_html=True)
    a1, a2, a3, a4 = st.columns(4)

    with a1:
        if st.button("📊 Dashboard", use_container_width=True):
            _go("Dashboard")
    with a2:
        if st.button("🔔 Alertas", use_container_width=True):
            _go("🔔 Alertas e Notificações")
    with a3:
        if st.button("➕ Novo pedido", use_container_width=True):
            _go("Gestão de Pedidos")
    with a4:
        if st.button("🗺️ Mapa", use_container_width=True):
            _go("Mapa Geográfico")

    st.markdown('<p class="fu-muted">Dica: use a busca rápida na barra lateral para navegar instantaneamente.</p>', unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)  # end wrap
