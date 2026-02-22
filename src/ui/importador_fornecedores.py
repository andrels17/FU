from __future__ import annotations

import io
import re

import pandas as pd
import streamlit as st

from src.repositories.fornecedores import upsert_fornecedores
from src.ui.theme import section_header


def _norm_cnpj(x: object) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    s = re.sub(r"\D", "", s)
    return s or None


def _read_upload(uploaded) -> pd.DataFrame:
    name = (uploaded.name or "").lower()
    data = uploaded.getvalue()

    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(data))

    # CSV
    for enc in ("utf-8-sig", "utf-8", "latin1"):
        for sep in (";", ","):
            try:
                return pd.read_csv(io.BytesIO(data), encoding=enc, sep=sep)
            except Exception:
                continue
    # fallback
    return pd.read_csv(io.BytesIO(data))


def exibir_importador_fornecedores(supabase, tenant_id: str | None = None):
    section_header(
        "Importar Fornecedores",
        hint="Upsert por código (e por empresa, quando aplicável).",
        pill="Novo",
    )

    st.info(
        "Preencha o arquivo com **cod_fornecedor** e **nome**. Os demais campos são opcionais.\n\n"
        "Você pode enviar CSV (\";\" ou \",\") ou Excel (.xlsx)."
    )

    template = pd.DataFrame(
        {
            "cod_fornecedor": [6691],
            "nome": ["Fornecedor Exemplo"],
            "nome_fantasia": ["Fornecedor Ex"],
            "cnpj": ["12.345.678/0001-90"],
            "cidade": ["São Paulo"],
            "uf": ["SP"],
            "ie": ["ISENTO"],
            "endereco": ["Rua Exemplo, 123"],
            "ativo": [True],
        }
    )
    st.download_button(
        "📥 Baixar modelo (CSV)",
        data=template.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig"),
        file_name="template_fornecedores.csv",
        mime="text/csv",
        use_container_width=True,
        key="imp_forn__dl_template",
    )

    up = st.file_uploader(
        "Selecione o arquivo",
        type=["csv", "xlsx", "xls"],
        key="imp_forn__uploader",
    )

    if not up:
        return

    try:
        df = _read_upload(up)
    except Exception as e:
        st.error(f"Não foi possível ler o arquivo: {e}")
        return

    # normaliza colunas
    df.columns = [str(c).strip().lower() for c in df.columns]
    rename = {
        "codigo": "cod_fornecedor",
        "código": "cod_fornecedor",
        "cod": "cod_fornecedor",
        "fornecedor": "nome",
        "razao_social": "nome",
        "razão_social": "nome",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    required = ["cod_fornecedor", "nome"]
    falt = [c for c in required if c not in df.columns]
    if falt:
        st.error(f"Colunas obrigatórias faltando: {', '.join(falt)}")
        st.stop()

    # limpeza básica
    df["cod_fornecedor"] = pd.to_numeric(df["cod_fornecedor"], errors="coerce")
    df["nome"] = df["nome"].astype(str).str.strip()
    if "cnpj" in df.columns:
        df["cnpj"] = df["cnpj"].apply(_norm_cnpj)
    if "uf" in df.columns:
        df["uf"] = df["uf"].astype(str).str.upper().str.strip().str[:2]
    if "ativo" in df.columns:
        # aceita 1/0, sim/nao, true/false
        df["ativo"] = df["ativo"].map(lambda x: str(x).strip().lower() in {"1", "true", "t", "sim", "s", "yes", "y"})

    df = df.dropna(subset=["cod_fornecedor"])
    df = df[df["nome"].str.len() > 0]

    if df.empty:
        st.error("Nenhuma linha válida após validação.")
        return

    st.write("Pré-visualização (20 primeiras linhas):")
    st.dataframe(df.head(20), use_container_width=True)

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        dry_run = st.checkbox("Simulação", value=False, key="imp_forn__dry")
    with col2:
        incluir_inativos = st.checkbox("Permitir ativo=False", value=True, key="imp_forn__inativos")
    with col3:
        st.caption(f"Linhas válidas: **{len(df)}**")

    if not incluir_inativos and "ativo" in df.columns:
        df = df[df["ativo"] == True]

    if st.button("🚀 Importar (Upsert)", type="primary", use_container_width=True, key="imp_forn__run"):
        if dry_run:
            st.info("Simulação ativa: nada foi gravado.\n\n" + f"Linhas que seriam processadas: {len(df)}")
            return

        with st.spinner("Enviando para o banco..."):
            ok, updated, inserted, errors = upsert_fornecedores(supabase, df, tenant_id=tenant_id)

        if errors:
            st.warning(f"Importação concluída com erros em {len(errors)} linha(s).")
            st.dataframe(pd.DataFrame(errors), use_container_width=True, height=280)
        if ok:
            st.success(f"Concluído! Inseridos: {inserted} | Atualizados: {updated}")
        else:
            st.error("Falha ao importar fornecedores. Veja os erros acima.")
