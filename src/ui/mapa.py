from __future__ import annotations

from datetime import date
import re
import unicodedata
from typing import Optional, Tuple

import pandas as pd
import plotly.express as px
import streamlit as st

from src.repositories.pedidos import carregar_pedidos
from src.repositories.fornecedores import carregar_fornecedores


APP_TITULO = "🗺️ Mapa Geográfico de Fornecedores"

BR_STATES_GEOJSON_URL = (
    "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
)

# Centro aproximado por UF (fallback quando fornecedor não tem lat/long)
UF_CENTRO = {
    "AC": (-9.975, -67.824), "AL": (-9.649, -35.708), "AP": (0.035, -51.070), "AM": (-3.101, -60.025),
    "BA": (-12.971, -38.501), "CE": (-3.731, -38.526), "DF": (-15.793, -47.882), "ES": (-20.315, -40.312),
    "GO": (-16.686, -49.264), "MA": (-2.529, -44.302), "MT": (-15.601, -56.097), "MS": (-20.469, -54.620),
    "MG": (-19.916, -43.934), "PA": (-1.455, -48.490), "PB": (-7.119, -34.845), "PR": (-25.428, -49.273),
    "PE": (-8.047, -34.877), "PI": (-5.089, -42.801), "RJ": (-22.906, -43.172), "RN": (-5.794, -35.209),
    "RS": (-30.034, -51.229), "RO": (-8.761, -63.903), "RR": (2.823, -60.675), "SC": (-27.595, -48.548),
    "SP": (-23.550, -46.633), "SE": (-10.947, -37.073), "TO": (-10.184, -48.333),
}
VALID_UFS = set(UF_CENTRO.keys())

UF_BY_STATE_NAME = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM", "BAHIA": "BA", "CEARA": "CE",
    "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO", "MARANHAO": "MA", "MATO GROSSO": "MT",
    "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG", "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR",
    "PERNAMBUCO": "PE", "PIAUI": "PI", "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN",
    "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO", "RORAIMA": "RR", "SANTA CATARINA": "SC",
    "SAO PAULO": "SP", "SERGIPE": "SE", "TOCANTINS": "TO",
}


# ===========================
# Formatação PT-BR (hover/tabelas)
# ===========================
def fmt_moeda(v) -> str:
    try:
        x = float(v or 0)
    except Exception:
        x = 0.0
    s = f"{x:,.2f}"  # 1,234,567.89
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def fmt_int(v) -> str:
    try:
        n = int(v or 0)
    except Exception:
        n = 0
    return f"{n:,}".replace(",", ".")


def fmt_pct(v) -> str:
    try:
        x = float(v or 0)
    except Exception:
        x = 0.0
    return f"{x:.1f}".replace(".", ",") + "%"


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_uf(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None

    m = re.search(r"\b([A-Z]{2})\b", s)
    if m and m.group(1) in VALID_UFS:
        return m.group(1)

    s2 = _strip_accents(s)
    s2 = re.sub(r"[^A-Z\s]", " ", s2)
    s2 = re.sub(r"\s+", " ", s2).strip()
    return UF_BY_STATE_NAME.get(s2)


def _to_dt(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def _load_data_cached(supabase, tenant_id: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Cache simples por sessão (não usa st.cache_data pois supabase client é unhashable)."""
    cache_key = f"mapa_cache::{tenant_id}"
    cached = st.session_state.get(cache_key)
    if isinstance(cached, tuple) and len(cached) == 2:
        return cached

    df_pedidos = carregar_pedidos(supabase, tenant_id)
    df_fornecedores = carregar_fornecedores(supabase, tenant_id)

    if df_pedidos is None:
        df_pedidos = pd.DataFrame()
    if df_fornecedores is None:
        df_fornecedores = pd.DataFrame()

    st.session_state[cache_key] = (df_pedidos, df_fornecedores)
    return df_pedidos, df_fornecedores


def _filters_form(df_pedidos: pd.DataFrame) -> dict:
    """Form de filtros com multiselect + ações rápidas (selecionar tudo / limpar)."""
    st.sidebar.markdown("## 🧭 Filtros do Mapa")
    ss = st.session_state

    # opções a partir dos dados
    dept_opts = sorted([x for x in df_pedidos.get("departamento", pd.Series(dtype=str)).dropna().astype(str).unique() if x.strip()])
    status_opts = sorted([x for x in df_pedidos.get("status", pd.Series(dtype=str)).dropna().astype(str).unique() if x.strip()])

    # defaults persistidos
    ign_default = bool(ss.get("mapa_f_ignorar_sem_fornecedor", True))
    pend_default = bool(ss.get("mapa_f_apenas_pendentes", False))
    min_default = float(ss.get("mapa_f_min_valor", 0.0))
    med_default = str(ss.get("mapa_f_medida_estado", "Valor total"))
    dept_default = list(ss.get("mapa_f_dept_sel", []))
    status_default = list(ss.get("mapa_f_status_sel", []))

    # período (se existir)
    has_data_sol = "data_solicitacao" in df_pedidos.columns and pd.to_datetime(df_pedidos["data_solicitacao"], errors="coerce").notna().any()
    dt_ini_default = ss.get("mapa_f_dt_ini", None)
    dt_fim_default = ss.get("mapa_f_dt_fim", None)
    if has_data_sol:
        dtmp = pd.to_datetime(df_pedidos["data_solicitacao"], errors="coerce")
        dmin = dtmp.min().date()
        dmax = dtmp.max().date()
        if dt_ini_default is None:
            dt_ini_default = dmin
        if dt_fim_default is None:
            dt_fim_default = dmax

    with st.sidebar.form("filtros_mapa_form", clear_on_submit=False):
        ignorar_sem_fornecedor = st.checkbox("Ignorar pedidos sem fornecedor", value=ign_default)
        apenas_pendentes = st.checkbox("Apenas pendentes (entregue = False)", value=pend_default)

        dept_sel = st.multiselect(
            "Departamento",
            options=dept_opts,
            default=[x for x in dept_default if x in dept_opts],
            help="Selecione um ou mais departamentos. Se vazio, considera todos.",
        )

        status_sel = st.multiselect(
            "Status",
            options=status_opts,
            default=[x for x in status_default if x in status_opts],
            help="Selecione um ou mais status. Se vazio, considera todos.",
        )

        c1, c2 = st.columns(2)
        with c1:
            btn_select_all = st.form_submit_button("✅ Selecionar todos", use_container_width=True)
        with c2:
            btn_clear = st.form_submit_button("🧹 Limpar seleção", use_container_width=True)

        min_valor = st.number_input("Valor mínimo (valor_total)", min_value=0.0, value=min_default, step=100.0)

        if has_data_sol:
            periodo = st.date_input("Período (data solicitação)", value=(dt_ini_default, dt_fim_default))
        else:
            periodo = None
            st.caption("Período indisponível (data_solicitacao ausente/vazia).")

        medida_estado = st.selectbox(
            "Cor do mapa (Estados)",
            options=["Valor total", "Quantidade de pedidos"],
            index=0 if med_default == "Valor total" else 1,
        )

        aplicar = st.form_submit_button("✅ Aplicar filtros", use_container_width=True)

    # ações rápidas
    if btn_select_all:
        ss["mapa_f_dept_sel"] = list(dept_opts)
        ss["mapa_f_status_sel"] = list(status_opts)
        st.rerun()

    if btn_clear:
        ss["mapa_f_dept_sel"] = []
        ss["mapa_f_status_sel"] = []
        st.rerun()

    # aplicar
    if aplicar:
        ss["mapa_f_ignorar_sem_fornecedor"] = bool(ignorar_sem_fornecedor)
        ss["mapa_f_apenas_pendentes"] = bool(apenas_pendentes)
        ss["mapa_f_dept_sel"] = list(dept_sel)
        ss["mapa_f_status_sel"] = list(status_sel)
        ss["mapa_f_min_valor"] = float(min_valor)
        ss["mapa_f_medida_estado"] = str(medida_estado)
        if has_data_sol and isinstance(periodo, tuple) and len(periodo) == 2:
            ss["mapa_f_dt_ini"] = periodo[0]
            ss["mapa_f_dt_fim"] = periodo[1]
        st.rerun()

    return {
        "ignorar_sem_fornecedor": bool(ss.get("mapa_f_ignorar_sem_fornecedor", ign_default)),
        "apenas_pendentes": bool(ss.get("mapa_f_apenas_pendentes", pend_default)),
        "dept_sel": list(ss.get("mapa_f_dept_sel", dept_default)),
        "status_sel": list(ss.get("mapa_f_status_sel", status_default)),
        "min_valor": float(ss.get("mapa_f_min_valor", min_default)),
        "medida_estado": str(ss.get("mapa_f_medida_estado", med_default)),
        "dt_ini": ss.get("mapa_f_dt_ini", dt_ini_default),
        "dt_fim": ss.get("mapa_f_dt_fim", dt_fim_default),
        "has_data_sol": has_data_sol,
    }


def exibir_mapa(supabase) -> None:
    st.title(APP_TITULO)
    st.caption("Mapa por Estado (coroplético), fornecedores (pontos), heatmap, rankings e exportação.")

    tenant_id = st.session_state.get("tenant_id")
    if not tenant_id:
        st.error("❌ Tenant não identificado.")
        return

    cbtn1, _ = st.columns([1, 4])
    with cbtn1:
        if st.button("🔄 Recarregar dados", use_container_width=True):
            st.session_state.pop(f"mapa_cache::{tenant_id}", None)
            st.rerun()

    df_pedidos, df_fornecedores = _load_data_cached(supabase, str(tenant_id))
    if df_pedidos.empty:
        st.info("📭 Sem pedidos para exibir.")
        return

    filtros = _filters_form(df_pedidos)

    df = df_pedidos.copy()
    if "fornecedor_id" not in df.columns:
        st.error("❌ Seus pedidos não possuem a coluna fornecedor_id (necessário para mapear UF/fornecedor).")
        return

    df["valor_total"] = pd.to_numeric(df.get("valor_total", 0.0), errors="coerce").fillna(0.0)

    for dcol in ("data_solicitacao", "previsao_entrega", "data_entrega_real"):
        if dcol in df.columns:
            df[dcol] = _to_dt(df[dcol])

    if "entregue" not in df.columns:
        df["entregue"] = False
    if "status" not in df.columns:
        df["status"] = "N/A"
    if "departamento" not in df.columns:
        df["departamento"] = ""

    df["fornecedor_id"] = df["fornecedor_id"].astype(str).replace({"None": pd.NA, "nan": pd.NA, "NaT": pd.NA, "": pd.NA})

    base = df[df["valor_total"] >= float(filtros["min_valor"])].copy()

    if filtros["ignorar_sem_fornecedor"]:
        base = base[base["fornecedor_id"].notna()].copy()

    if filtros["apenas_pendentes"]:
        base = base[base["entregue"] == False].copy()  # noqa: E712

    dept_sel = filtros.get("dept_sel", [])
    status_sel = filtros.get("status_sel", [])

    if dept_sel and "departamento" in base.columns:
        base = base[base["departamento"].astype(str).isin(dept_sel)].copy()

    if status_sel and "status" in base.columns:
        base = base[base["status"].astype(str).isin(status_sel)].copy()

    if filtros["has_data_sol"] and filtros["dt_ini"] and filtros["dt_fim"] and "data_solicitacao" in base.columns:
        base = base[(base["data_solicitacao"].dt.date >= filtros["dt_ini"]) & (base["data_solicitacao"].dt.date <= filtros["dt_fim"])].copy()

    if base.empty:
        st.warning("⚠️ Após filtros, não há pedidos suficientes para gerar os mapas.")
        return

    if df_fornecedores.empty:
        st.warning("⚠️ Não há fornecedores cadastrados para este tenant.")
        return

    forn = df_fornecedores.copy()
    if "id" not in forn.columns:
        st.error("❌ Fornecedores não possuem coluna id.")
        return

    for col in ("nome", "cidade", "uf", "latitude", "longitude"):
        if col not in forn.columns:
            forn[col] = None

    forn["id"] = forn["id"].astype(str)

    dfm = base.merge(
        forn[["id", "nome", "cidade", "uf", "latitude", "longitude"]],
        left_on="fornecedor_id",
        right_on="id",
        how="left",
    )

    dfm["uf_norm"] = dfm["uf"].apply(normalize_uf)

    hoje = pd.Timestamp(date.today())
    if "previsao_entrega" in dfm.columns:
        dfm["atrasado"] = (dfm["previsao_entrega"].notna()) & (dfm["previsao_entrega"] < hoje) & (dfm["entregue"] == False)  # noqa: E712
    else:
        dfm["atrasado"] = False

    total = len(dfm)
    com_forn = int(dfm["nome"].notna().sum())
    com_uf = int(dfm["uf_norm"].notna().sum())
    pendentes = int((dfm["entregue"] == False).sum())  # noqa: E712
    atrasados = int(dfm["atrasado"].sum())
    valor_total = float(dfm["valor_total"].sum())

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Pedidos", fmt_int(total))
    k2.metric("Com fornecedor", fmt_int(com_forn))
    k3.metric("Com UF válida", fmt_int(com_uf))
    k4.metric("Pendentes", fmt_int(pendentes))
    k5.metric("Atrasados", fmt_int(atrasados))
    st.caption(f"💰 Valor total (após filtros): **{fmt_moeda(valor_total)}**")

    if com_uf == 0:
        st.warning("⚠️ Nenhum pedido com UF válida (fornecedor sem UF ou sem vínculo).")
        return

    tab_est, tab_pts, tab_heat, tab_rank, tab_export = st.tabs(
        ["🗺️ Estados", "📍 Fornecedores (pontos)", "🔥 Heatmap", "🏆 Rankings", "📄 Exportar"]
    )

    with tab_est:
        est_base = dfm[dfm["uf_norm"].notna()].copy()
        agg = (
            est_base.groupby("uf_norm", dropna=False)
            .agg(
                pedidos=("fornecedor_id", "count"),
                valor=("valor_total", "sum"),
                pendentes=("entregue", lambda s: int((s == False).sum())),  # noqa: E712
                entregues=("entregue", lambda s: int((s == True).sum())),   # noqa: E712
                atrasados=("atrasado", "sum"),
            )
            .reset_index()
            .rename(columns={"uf_norm": "UF"})
        )
        agg["pct_entregue"] = (agg["entregues"] / agg["pedidos"]).fillna(0) * 100.0

        agg["hover"] = (
            "<b>" + agg["UF"].astype(str) + "</b><br>"
            + "📦 Pedidos: " + agg["pedidos"].apply(fmt_int) + "<br>"
            + "✅ Entregues: " + agg["entregues"].apply(fmt_int) + "<br>"
            + "🕗 Pendentes: " + agg["pendentes"].apply(fmt_int) + "<br>"
            + "⛔ Atrasados: " + agg["atrasados"].apply(fmt_int) + "<br>"
            + "📈 % Entregue: " + agg["pct_entregue"].apply(fmt_pct) + "<br>"
            + "💰 Valor total: " + agg["valor"].apply(fmt_moeda)
        )

        color_col = "valor" if filtros["medida_estado"] == "Valor total" else "pedidos"

        fig = px.choropleth_mapbox(
            agg,
            geojson=BR_STATES_GEOJSON_URL,
            locations="UF",
            featureidkey="properties.sigla",
            color=color_col,
            hover_name="UF",
            center={"lat": -14, "lon": -55},
            zoom=3.2,
            mapbox_style="carto-darkmatter",
            opacity=0.78,
        )
        fig.update_traces(customdata=agg[["hover"]].values, hovertemplate="%{customdata[0]}<extra></extra>")
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=720)
        st.plotly_chart(fig, use_container_width=True)

        t = agg.sort_values(color_col, ascending=False).copy()
        t["pedidos"] = t["pedidos"].apply(fmt_int)
        t["entregues"] = t["entregues"].apply(fmt_int)
        t["pendentes"] = t["pendentes"].apply(fmt_int)
        t["atrasados"] = t["atrasados"].apply(fmt_int)
        t["pct_entregue"] = t["pct_entregue"].apply(fmt_pct)
        t["valor"] = t["valor"].apply(fmt_moeda)
        st.dataframe(t, use_container_width=True, hide_index=True)

    with tab_pts:
        pts = dfm[dfm["uf_norm"].notna()].copy()
        pts["lat"] = pd.to_numeric(pts["latitude"], errors="coerce")
        pts["lon"] = pd.to_numeric(pts["longitude"], errors="coerce")

        miss = pts["lat"].isna() | pts["lon"].isna()
        if miss.any():
            pts.loc[miss, "lat"] = pts.loc[miss, "uf_norm"].map(lambda uf: UF_CENTRO.get(uf, (None, None))[0])
            pts.loc[miss, "lon"] = pts.loc[miss, "uf_norm"].map(lambda uf: UF_CENTRO.get(uf, (None, None))[1])

        agg_f = (
            pts.groupby(["nome", "cidade", "uf_norm", "lat", "lon"], dropna=False)
            .agg(
                pedidos=("fornecedor_id", "count"),
                valor=("valor_total", "sum"),
                pendentes=("entregue", lambda s: int((s == False).sum())),  # noqa: E712
                atrasados=("atrasado", "sum"),
            )
            .reset_index()
            .rename(columns={"uf_norm": "UF"})
            .sort_values(["pedidos", "valor"], ascending=False)
        )

        agg_f["hover"] = (
            "<b>" + agg_f["nome"].fillna("Fornecedor") + "</b><br>"
            + "🏙️ Cidade: " + agg_f["cidade"].fillna("-") + " / " + agg_f["UF"].fillna("-") + "<br>"
            + "📦 Pedidos: " + agg_f["pedidos"].apply(fmt_int) + "<br>"
            + "🕗 Pendentes: " + agg_f["pendentes"].apply(fmt_int) + "<br>"
            + "⛔ Atrasados: " + agg_f["atrasados"].apply(fmt_int) + "<br>"
            + "💰 Valor: " + agg_f["valor"].apply(fmt_moeda)
        )

        fig2 = px.scatter_mapbox(
            agg_f,
            lat="lat",
            lon="lon",
            size="pedidos",
            color="valor",
            hover_name="nome",
            center={"lat": -14, "lon": -55},
            zoom=3.2,
            mapbox_style="carto-darkmatter",
        )
        fig2.update_traces(customdata=agg_f[["hover"]].values, hovertemplate="%{customdata[0]}<extra></extra>")
        fig2.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=720)
        st.plotly_chart(fig2, use_container_width=True)

        t = agg_f.copy()
        t["pedidos"] = t["pedidos"].apply(fmt_int)
        t["pendentes"] = t["pendentes"].apply(fmt_int)
        t["atrasados"] = t["atrasados"].apply(fmt_int)
        t["valor"] = t["valor"].apply(fmt_moeda)
        st.dataframe(t.drop(columns=["hover"]), use_container_width=True, hide_index=True)

    with tab_heat:
        pts = dfm[dfm["uf_norm"].notna()].copy()
        pts["lat"] = pd.to_numeric(pts["latitude"], errors="coerce")
        pts["lon"] = pd.to_numeric(pts["longitude"], errors="coerce")

        miss = pts["lat"].isna() | pts["lon"].isna()
        if miss.any():
            pts.loc[miss, "lat"] = pts.loc[miss, "uf_norm"].map(lambda uf: UF_CENTRO.get(uf, (None, None))[0])
            pts.loc[miss, "lon"] = pts.loc[miss, "uf_norm"].map(lambda uf: UF_CENTRO.get(uf, (None, None))[1])

        fig3 = px.density_mapbox(
            pts,
            lat="lat",
            lon="lon",
            z="valor_total",
            radius=25,
            center={"lat": -14, "lon": -55},
            zoom=3.2,
            mapbox_style="carto-darkmatter",
        )
        fig3.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=720)
        st.plotly_chart(fig3, use_container_width=True)
        st.caption("Heatmap ponderado por **valor_total**.")

    with tab_rank:
        c1, c2 = st.columns(2)

        with c1:
            st.subheader("🏆 Top Fornecedores")
            pts = dfm[dfm["nome"].notna()].copy()
            top_f = (
                pts.groupby("nome", dropna=False)
                .agg(pedidos=("fornecedor_id", "count"), valor=("valor_total", "sum"), atrasados=("atrasado", "sum"))
                .reset_index()
                .sort_values(["valor", "pedidos"], ascending=False)
                .head(20)
            )
            top_f_show = top_f.copy()
            top_f_show["pedidos"] = top_f_show["pedidos"].apply(fmt_int)
            top_f_show["atrasados"] = top_f_show["atrasados"].apply(fmt_int)
            top_f_show["valor"] = top_f_show["valor"].apply(fmt_moeda)
            st.dataframe(top_f_show, use_container_width=True, hide_index=True)

        with c2:
            st.subheader("🗺️ Top Estados (UF)")
            est = dfm[dfm["uf_norm"].notna()].copy()
            top_uf = (
                est.groupby("uf_norm", dropna=False)
                .agg(pedidos=("fornecedor_id", "count"), valor=("valor_total", "sum"), atrasados=("atrasado", "sum"))
                .reset_index()
                .rename(columns={"uf_norm": "UF"})
                .sort_values(["valor", "pedidos"], ascending=False)
                .head(20)
            )
            top_uf_show = top_uf.copy()
            top_uf_show["pedidos"] = top_uf_show["pedidos"].apply(fmt_int)
            top_uf_show["atrasados"] = top_uf_show["atrasados"].apply(fmt_int)
            top_uf_show["valor"] = top_uf_show["valor"].apply(fmt_moeda)
            st.dataframe(top_uf_show, use_container_width=True, hide_index=True)

    with tab_export:
        st.subheader("📄 Exportar base do mapa")
        st.write("Baixe a base filtrada já enriquecida com fornecedor e UF normalizada.")

        export_df = dfm.copy()
        prefer = [
            "nr_solicitacao", "nr_oc", "departamento", "status", "descricao",
            "valor_total", "entregue", "atrasado",
            "nome", "cidade", "uf", "uf_norm",
            "previsao_entrega", "data_solicitacao", "data_entrega_real",
            "fornecedor_id",
        ]
        cols_first = [c for c in prefer if c in export_df.columns]
        rest = [c for c in export_df.columns if c not in cols_first]
        export_df = export_df[cols_first + rest]

        csv = export_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Baixar CSV (base do mapa)",
            data=csv,
            file_name="base_mapa_filtrada.csv",
            mime="text/csv",
            use_container_width=True,
        )
