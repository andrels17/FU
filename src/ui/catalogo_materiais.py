"""
UI - Catálogo de Materiais (SaaS / multiempresa)

Objetivo:
- Importar CSVs de catálogo (automotivo/irrigação) para a tabela `materiais`
- Upsert por (tenant_id, codigo_material)
- Consultar / filtrar / exportar
- Diagnósticos de qualidade (materiais faltantes / pedidos sem catálogo)

Pré-requisitos no Supabase:
- tabela public.materiais com PK (tenant_id, codigo_material)
- view vw_pedidos_completo incluindo colunas de materiais (almoxarifado etc.) — opcional para diagnóstico.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st


# -----------------------------
# Helpers
# -----------------------------
REQUIRED_COLS_MIN = ["Código", "Descrição Material"]  # mínimo para cadastrar
OPTIONAL_COLS = [
    "Unid.",
    "Família",
    "Descrição Família Material",
    "Grupo",
    "Descrição Grupo do Material",
    "Tipo Material",
    "Descrição Tipo Material",
    "Almoxarifado",
    "Descrição Almoxarifado",
]


# Normalizações comuns de cabeçalhos
COL_ALIASES = {
    "codigo": "Código",
    "código": "Código",
    "cod": "Código",
    "cod_material": "Código",
    "cód.": "Código",
    "cód": "Código",
    "codigo material": "Código",
    "descrição material": "Descrição Material",
    "descricao material": "Descrição Material",
    "descrição": "Descrição Material",
    "descricao": "Descrição Material",
    "unid": "Unid.",
    "unid.": "Unid.",
    "unidade": "Unid.",
    "familia": "Família",
    "família": "Família",
    "descricao família material": "Descrição Família Material",
    "descrição família material": "Descrição Família Material",
    "descricao grupo do material": "Descrição Grupo do Material",
    "descrição grupo do material": "Descrição Grupo do Material",
    "tipo material": "Tipo Material",
    "almoxarifado": "Almoxarifado",
    "grupo": "Grupo",

"cód. almox.": "Almoxarifado Codigo",
"cód. almox": "Almoxarifado Codigo",
"cod. almox.": "Almoxarifado Codigo",
"cod almox": "Almoxarifado Codigo",
"cód. tipo mat.": "Tipo Material Codigo",
"cód. tipo mat": "Tipo Material Codigo",
"cod. tipo mat.": "Tipo Material Codigo",
"descrição tipo material": "Tipo Material",
"descricao tipo material": "Tipo Material",
"descrição almoxarifado": "Almoxarifado",
"descricao almoxarifado": "Almoxarifado",
}


@dataclass
class ImportReport:
    total_lidos: int
    total_validos: int
    total_invalidos: int
    total_upsert: int
    invalid_samples: pd.DataFrame | None = None


def _try_read_csv(file) -> pd.DataFrame:
    """Lê CSV tentando delimitadores/encodings comuns."""
    # Tentativas: utf-8-sig e latin1
    raw = file.getvalue()
    for enc in ("utf-8-sig", "utf-8", "latin1"):
        for sep in (",", ";", "\t"):
            try:
                df = pd.read_csv(
                    pd.io.common.BytesIO(raw),
                    sep=sep,
                    encoding=enc,
                    dtype=str,
                    engine="python",
                )
                if df.shape[1] >= 2:
                    return df
            except Exception:
                continue
    # Última tentativa: padrão
    return pd.read_csv(file, dtype=str, engine="python")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = []
    for c in df.columns:
        key = str(c).strip()
        key_low = key.lower().strip()
        cols.append(COL_ALIASES.get(key_low, key))
    df = df.copy()
    df.columns = cols
    return df


def _coerce_int_safe(x: Any) -> int | None:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = str(x).strip()
    if not s:
        return None
    # mantém só dígitos
    import re
    digits = re.sub(r"\D+", "", s)
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _build_payload(df: pd.DataFrame, tenant_id: str, origem: str) -> tuple[list[dict], ImportReport]:
    df = _normalize_columns(df)

    # Garantir colunas mínimas
    missing = [c for c in REQUIRED_COLS_MIN if c not in df.columns]
    if missing:
        raise ValueError(f"CSV inválido. Colunas ausentes: {missing}")

    dfw = df.copy()

    # Código -> int
    dfw["codigo_material"] = dfw["Código"].apply(_coerce_int_safe)

    # Descrição
    dfw["descricao"] = dfw["Descrição Material"].astype(str).str.strip().replace({"nan": None, "None": None})

    # Unid
    if "Unid." in dfw.columns:
        dfw["unidade"] = dfw["Unid."].astype(str).str.strip().replace({"nan": None, "None": None})
    else:
        dfw["unidade"] = None

    # Família / Grupo / Tipo / Almox
    def _col(name: str) -> pd.Series:
        return dfw[name].astype(str).str.strip().replace({"nan": None, "None": None}) if name in dfw.columns else pd.Series([None] * len(dfw), index=dfw.index)

    dfw["familia_codigo"] = _col("Família")
    dfw["familia_descricao"] = _col("Descrição Família Material")
    dfw["grupo_codigo"] = _col("Grupo")
    dfw["grupo_descricao"] = _col("Descrição Grupo do Material")
    dfw["tipo_material"] = _col("Tipo Material")
    dfw["almoxarifado"] = _col("Almoxarifado")

    # Regras de validade
    invalid_mask = dfw["codigo_material"].isna() | dfw["descricao"].isna() | (dfw["descricao"].astype(str).str.strip() == "")
    invalid_df = dfw.loc[invalid_mask].copy()

    valid_df = dfw.loc[~invalid_mask].copy()

    # Deduplicar por código (mantém o último)
    valid_df = valid_df.drop_duplicates(subset=["codigo_material"], keep="last")

    # Monta payload
    records: list[dict] = []
    for _, r in valid_df.iterrows():
        records.append(
            {
                "tenant_id": tenant_id,
                "codigo_material": int(r["codigo_material"]),
                "descricao": r.get("descricao"),
                "unidade": r.get("unidade"),
                "familia_codigo": r.get("familia_codigo"),
                "familia_descricao": r.get("familia_descricao"),
                "grupo_codigo": r.get("grupo_codigo"),
                "grupo_descricao": r.get("grupo_descricao"),
                "tipo_material": r.get("tipo_material"),
                "almoxarifado": r.get("almoxarifado"),
                "origem": origem,
            }
        )

    rep = ImportReport(
        total_lidos=len(df),
        total_validos=len(valid_df),
        total_invalidos=len(invalid_df),
        total_upsert=0,
        invalid_samples=invalid_df.head(50) if len(invalid_df) else None,
    )
    return records, rep


def _chunk(iterable: list[dict], size: int = 500):
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def _upsert_materiais(supabase, records: list[dict]) -> int:
    """Upsert em lotes. Retorna quantidade processada (aprox.)."""
    if not records:
        return 0
    total = 0
    prog = st.progress(0)
    n = len(records)
    for i, batch in enumerate(_chunk(records, 500), start=1):
        supabase.table("materiais").upsert(batch, on_conflict="tenant_id,codigo_material").execute()
        total += len(batch)
        prog.progress(min(1.0, total / n))
    prog.empty()
    return total


@st.cache_data(ttl=120)
def _cached_list_materiais(_supabase, tenant_id: str) -> pd.DataFrame:
    try:
        res = (
            _supabase.table("materiais")
            .select("*")
            .eq("tenant_id", tenant_id)
            .limit(20000)
            .execute()
        )
        return pd.DataFrame(res.data or [])
    except Exception:
        return pd.DataFrame()


def _clear_cache():
    try:
        st.cache_data.clear()
    except Exception:
        pass


# -----------------------------
# UI
# -----------------------------
def exibir_catalogo_materiais(supabase, tenant_id: str):
    st.title("Catálogo de Materiais")

    if not tenant_id:
        st.error("Tenant não identificado.")
        return

    tabs = st.tabs(["Importar CSV", "Consultar", "Qualidade"])

    # =========================
    # TAB: Importar
    # =========================
    with tabs[0]:
        st.subheader("Importação do Catálogo (por empresa)")

        col1, col2 = st.columns([1, 1])
        with col1:
            origem = st.selectbox("Origem do catálogo", ["AUTOMOTIVO", "IRRIGACAO"], index=0)
        with col2:
            modo = st.selectbox("Modo", ["Upsert (recomendado)"], index=0, help="Upsert atualiza e insere sem apagar registros existentes.")

        up = st.file_uploader("Selecione o CSV", type=["csv"])
        st.caption("Dica: aceitamos separador `,` ou `;` e encoding `utf-8` / `latin1`.")

        if up:
            try:
                df = _try_read_csv(up)
                df = _normalize_columns(df)

                st.write("Pré-visualização (primeiras 20 linhas):")
                st.dataframe(df.head(20), use_container_width=True)

                st.write("Colunas detectadas:", list(df.columns))

                if st.button("Processar importação", type="primary"):
                    with st.spinner("Processando e validando..."):
                        records, rep = _build_payload(df, tenant_id=tenant_id, origem=origem)

                    if rep.total_invalidos:
                        st.warning(f"Foram encontrados {rep.total_invalidos} registros inválidos (mostrando amostra).")
                        if rep.invalid_samples is not None and len(rep.invalid_samples):
                            st.dataframe(rep.invalid_samples, use_container_width=True)

                    if not records:
                        st.error("Nenhum registro válido para importar.")
                    else:
                        with st.spinner("Enviando para o banco (upsert)..."):
                            total_upsert = _upsert_materiais(supabase, records)
                            rep.total_upsert = total_upsert

                        st.success(
                            f"Importação concluída!\n\n"
                            f"- Lidos: {rep.total_lidos}\n"
                            f"- Válidos: {rep.total_validos}\n"
                            f"- Inválidos: {rep.total_invalidos}\n"
                            f"- Processados (upsert): {rep.total_upsert}"
                        )

                        _clear_cache()

                        st.info("Agora você já pode testar o filtro global de Almoxarifado e relatórios por Família/Grupo.")
            except Exception as e:
                st.error(f"Erro ao importar: {e}")

    # =========================
    # TAB: Consultar
    # =========================
    with tabs[1]:
        st.subheader("Consultar catálogo")

        dfm = _cached_list_materiais(supabase, tenant_id)

        if dfm.empty:
            st.info("Nenhum material cadastrado para esta empresa ainda.")
        else:
            # filtros
            c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
            with c1:
                almox = st.selectbox("Almoxarifado", ["Todos"] + sorted([x for x in dfm.get("almoxarifado", []).dropna().unique().tolist()]))
            with c2:
                fam = st.selectbox("Família", ["Todos"] + sorted([x for x in dfm.get("familia_descricao", []).dropna().unique().tolist()]))
            with c3:
                grp = st.selectbox("Grupo", ["Todos"] + sorted([x for x in dfm.get("grupo_descricao", []).dropna().unique().tolist()]))
            with c4:
                q = st.text_input("Buscar (código ou descrição)", "")

            dff = dfm.copy()
            if almox != "Todos" and "almoxarifado" in dff.columns:
                dff = dff[dff["almoxarifado"].astype(str) == almox]
            if fam != "Todos" and "familia_descricao" in dff.columns:
                dff = dff[dff["familia_descricao"].astype(str) == fam]
            if grp != "Todos" and "grupo_descricao" in dff.columns:
                dff = dff[dff["grupo_descricao"].astype(str) == grp]
            if q:
                ql = q.strip().lower()
                mask = (
                    dff["codigo_material"].astype(str).str.contains(ql, na=False)
                    | dff.get("descricao", pd.Series([""] * len(dff))).astype(str).str.lower().str.contains(ql, na=False)
                )
                dff = dff[mask]

            st.caption(f"Registros: {len(dff)}")
            show_cols = [c for c in ["codigo_material","descricao","unidade","almoxarifado","familia_descricao","grupo_descricao","tipo_material","origem"] if c in dff.columns]
            st.dataframe(dff[show_cols].sort_values(by=["almoxarifado","familia_descricao","grupo_descricao","codigo_material"], na_position="last"), use_container_width=True)

            csv = dff.to_csv(index=False).encode("utf-8")
            st.download_button("Baixar CSV filtrado", csv, file_name="catalogo_materiais_filtrado.csv", mime="text/csv")

    # =========================
    # TAB: Qualidade
    # =========================
    with tabs[2]:
        st.subheader("Qualidade e consistência")

        dfm = _cached_list_materiais(supabase, tenant_id)

        if dfm.empty:
            st.info("Importe um CSV para começar.")
        else:
            # Materiais incompletos
            incompletos = dfm.copy()
            for col in ["almoxarifado", "familia_descricao", "grupo_descricao"]:
                if col in incompletos.columns:
                    incompletos[col] = incompletos[col].astype(str).replace({"None": "", "nan": ""}).str.strip()

            faltando = incompletos[
                (incompletos.get("almoxarifado", "") == "")
                | (incompletos.get("familia_descricao", "") == "")
                | (incompletos.get("grupo_descricao", "") == "")
            ]

            st.caption(f"Materiais com dados faltantes (almox/família/grupo): {len(faltando)}")
            if len(faltando):
                st.dataframe(
                    faltando[[c for c in ["codigo_material","descricao","almoxarifado","familia_descricao","grupo_descricao","origem"] if c in faltando.columns]].head(500),
                    use_container_width=True
                )

            # Pedidos sem correspondência no catálogo (depende da view já com material_descricao)
            st.divider()
            st.caption("Pedidos sem correspondência no catálogo (se a view expõe material_descricao):")
            try:
                res = (
                    supabase.table("vw_pedidos_completo")
                    .select("cod_material,material_descricao,tenant_id")
                    .eq("tenant_id", tenant_id)
                    .limit(20000)
                    .execute()
                )
                dfp = pd.DataFrame(res.data or [])
                if dfp.empty or "material_descricao" not in dfp.columns:
                    st.info("A view ainda não expõe material_descricao ou não há pedidos.")
                else:
                    sem_cat = dfp[dfp["material_descricao"].isna() | (dfp["material_descricao"].astype(str).str.strip() == "")]
                    st.caption(f"Pedidos com material não encontrado no catálogo: {len(sem_cat)}")
                    if len(sem_cat):
                        st.dataframe(sem_cat.head(500), use_container_width=True)
            except Exception as e:
                st.info(f"Não foi possível consultar pedidos para diagnóstico: {e}")

    # Rodapé
    st.caption("Dica: após importar, atualize/recarregue as páginas para refletir as novas dimensões (almox, família, grupo).")
