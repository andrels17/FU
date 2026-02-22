from __future__ import annotations

import io
import re
import unicodedata
from typing import Any

import pandas as pd
import streamlit as st

from src.repositories.fornecedores import upsert_fornecedores
from src.ui.theme import section_header


# =========================
# Helpers (robustos)
# =========================
def _norm_cnpj(x: object) -> str | None:
    """Normaliza CNPJ para apenas dígitos (ou None)."""
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    s = re.sub(r"\D", "", s)
    return s or None


def _norm_col(s: object) -> str:
    """Normaliza nome de coluna: remove acentos/símbolos, padroniza separadores e caixa."""
    if s is None:
        return ""
    s = str(s).replace("\ufeff", "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[\s\-\/]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _is_single_column_misparsed(df: pd.DataFrame) -> bool:
    """Detecta CSV lido com separador errado (tudo em 1 coluna com ; ou , no header)."""
    if df is None or df.empty:
        return False
    if len(df.columns) != 1:
        return False
    header = str(df.columns[0])
    return ("," in header) or (";" in header) or ("\t" in header)


def _read_upload(uploaded) -> pd.DataFrame:
    """Leitura inteligente de CSV/Excel. Evita o bug de 'ler errado mas não dar erro'."""
    name = (uploaded.name or "").lower()
    data = uploaded.getvalue()

    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(data))

    # CSV: autodetect com fallback. sep=None + engine="python" tenta inferir.
    for enc in ("utf-8-sig", "utf-8", "latin1"):
        try:
            df = pd.read_csv(io.BytesIO(data), encoding=enc, sep=None, engine="python")
            if _is_single_column_misparsed(df):
                # tenta vírgula e ponto-vírgula explicitamente
                for sep in (",", ";", "\t"):
                    try:
                        df2 = pd.read_csv(io.BytesIO(data), encoding=enc, sep=sep)
                        if len(df2.columns) > 1:
                            return df2
                    except Exception:
                        continue
            return df
        except Exception:
            continue

    raise ValueError("Não foi possível identificar o formato do arquivo (CSV/Excel).")


def _score_row_completude(row: pd.Series) -> int:
    """Pontua quão 'completa' é uma linha (para dedupe interno do upload)."""
    fields = [
        "nome",
        "nome_fantasia",
        "cnpj",
        "cidade",
        "uf",
        "ie",
        "endereco",
        "ativo",
    ]
    score = 0
    for f in fields:
        v = row.get(f, None)
        if v is None:
            continue
        if isinstance(v, float) and pd.isna(v):
            continue
        s = str(v).strip()
        if s and s.lower() not in {"nan", "none", "null"}:
            score += 1
    return score


def _dedupe_upload(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Remove duplicadas dentro do próprio arquivo (por cod_fornecedor) mantendo a linha mais completa."""
    info: dict[str, Any] = {"dedupe_cod_removed": 0}

    if "cod_fornecedor" not in df.columns or df.empty:
        return df, info

    # Mantém a melhor linha por cod_fornecedor
    df2 = df.copy()
    df2["_score"] = df2.apply(_score_row_completude, axis=1)
    df2 = df2.sort_values(["cod_fornecedor", "_score"], ascending=[True, False])
    before = len(df2)
    df2 = df2.drop_duplicates(subset=["cod_fornecedor"], keep="first").drop(columns=["_score"])
    info["dedupe_cod_removed"] = max(0, before - len(df2))
    return df2, info


def _fetch_fornecedores_existentes(supabase, tenant_id: str | None) -> pd.DataFrame:
    """Carrega fornecedores existentes (mínimo necessário) para pré-análise."""
    if not tenant_id:
        return pd.DataFrame()
    try:
        resp = (
            supabase.table("fornecedores")
            .select("id,cod_fornecedor,cnpj,ativo")
            .eq("tenant_id", tenant_id)
            .limit(100000)
            .execute()
        )
        data = resp.data or []
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()


def _apply_anti_duplicidade_cnpj(
    df: pd.DataFrame, existentes: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Evita criar fornecedor duplicado por CNPJ:
    - Se o CNPJ do upload já existe no BD com outro cod_fornecedor, reescreve cod_fornecedor
      para o cod existente (assim vira update ao invés de insert).
    Retorna (df_ajustado, conflitos_report).
    """
    if df.empty or "cnpj" not in df.columns or existentes.empty or "cnpj" not in existentes.columns:
        return df, pd.DataFrame()

    ex = existentes.copy()
    ex["cnpj"] = ex["cnpj"].apply(_norm_cnpj)
    ex = ex.dropna(subset=["cnpj"])
    if ex.empty:
        return df, pd.DataFrame()

    cnpj_to_cod = {}
    for _, r in ex.iterrows():
        cnpj_to_cod[str(r["cnpj"])] = r.get("cod_fornecedor")

    df2 = df.copy()
    conflitos = []
    for idx, row in df2.iterrows():
        cnpj = row.get("cnpj")
        if not cnpj:
            continue
        cnpj = _norm_cnpj(cnpj)
        if not cnpj:
            continue
        cod_exist = cnpj_to_cod.get(cnpj)
        if cod_exist is None:
            continue
        cod_row = row.get("cod_fornecedor")
        try:
            cod_row_int = int(cod_row) if cod_row is not None and not (isinstance(cod_row, float) and pd.isna(cod_row)) else None
        except Exception:
            cod_row_int = None
        try:
            cod_exist_int = int(cod_exist) if cod_exist is not None and not (isinstance(cod_exist, float) and pd.isna(cod_exist)) else None
        except Exception:
            cod_exist_int = None

        if cod_exist_int is not None and cod_row_int is not None and cod_exist_int != cod_row_int:
            conflitos.append(
                {
                    "linha": int(idx) + 2,  # +2 (header + 1-based)
                    "cnpj": cnpj,
                    "cod_no_arquivo": cod_row_int,
                    "cod_existente_bd": cod_exist_int,
                    "acao": "Usado cod existente do BD (evita duplicidade por CNPJ)",
                }
            )
            df2.at[idx, "cod_fornecedor"] = cod_exist_int

    return df2, pd.DataFrame(conflitos)


def exibir_importador_fornecedores(supabase, tenant_id: str | None = None):
    section_header(
        "Importar Fornecedores",
        hint="Upsert por código (e prevenção de duplicidade por CNPJ).",
        pill="Enterprise",
    )

    st.info(
        "Preencha o arquivo com **cod_fornecedor** e **nome**. Os demais campos são opcionais.\n\n"
        "Você pode enviar CSV (\";\" ou \",\") ou Excel (.xlsx).\n"
        "Esta tela também tenta evitar duplicidade por **CNPJ** (quando disponível)."
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

    # -------- leitura robusta
    try:
        df = _read_upload(up)
    except Exception as e:
        st.error(f"Não foi possível ler o arquivo: {e}")
        return

    # -------- normaliza colunas
    df.columns = [_norm_col(c) for c in df.columns]

    # aliases comuns
    rename = {
        "codigo": "cod_fornecedor",
        "cod": "cod_fornecedor",
        "fornecedor": "nome",
        "razao_social": "nome",
        "razaosocial": "nome",
        "razao": "nome",
        "endereco": "endereco",
        "enderecos": "endereco",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    # required
    required = ["cod_fornecedor", "nome"]
    falt = [c for c in required if c not in df.columns]
    if falt:
        st.error(f"Colunas obrigatórias faltando: {', '.join(falt)}")
        st.caption(f"Colunas lidas: {list(df.columns)}")
        st.stop()

    # -------- limpeza básica
    df["cod_fornecedor"] = pd.to_numeric(df["cod_fornecedor"], errors="coerce")
    df["cod_fornecedor"] = df["cod_fornecedor"].dropna().astype("int64", errors="ignore")

    df["nome"] = df["nome"].astype(str).str.strip()

    if "cnpj" in df.columns:
        df["cnpj"] = df["cnpj"].apply(_norm_cnpj)

    if "uf" in df.columns:
        df["uf"] = df["uf"].astype(str).str.upper().str.strip().str[:2]

    if "ativo" in df.columns:
        # aceita 1/0, sim/nao, true/false
        df["ativo"] = df["ativo"].map(
            lambda x: str(x).strip().lower() in {"1", "true", "t", "sim", "s", "yes", "y"}
        )

    # remove inválidos
    df = df.dropna(subset=["cod_fornecedor"])
    df = df[df["nome"].str.len() > 0]

    if df.empty:
        st.error("Nenhuma linha válida após validação.")
        return

    # -------- dedupe dentro do arquivo
    df, dedupe_info = _dedupe_upload(df)

    # -------- pré-análise com base no BD
    existentes = _fetch_fornecedores_existentes(supabase, tenant_id)
    existentes_cols = set(existentes.columns) if isinstance(existentes, pd.DataFrame) else set()

    usar_anti_cnpj = st.toggle(
        "Evitar duplicidade por CNPJ (recomendo manter ligado)",
        value=True,
        help="Se o CNPJ já existe no seu banco com outro código, o importador usa o código existente e atualiza, evitando criar um fornecedor duplicado.",
        key="imp_forn__anti_cnpj",
    )

    conflitos_cnpj = pd.DataFrame()
    if usar_anti_cnpj and "cnpj" in df.columns and {"cnpj", "cod_fornecedor"} <= set(df.columns) and {"cnpj", "cod_fornecedor"} <= existentes_cols:
        df, conflitos_cnpj = _apply_anti_duplicidade_cnpj(df, existentes)

    # -------- resumo antes de importar
    st.subheader("Resumo")
    colA, colB, colC, colD = st.columns([1, 1, 1, 1])

    if not existentes.empty and "cod_fornecedor" in existentes.columns:
        ex_cod = set(pd.to_numeric(existentes["cod_fornecedor"], errors="coerce").dropna().astype(int).tolist())
        up_cod = set(pd.to_numeric(df["cod_fornecedor"], errors="coerce").dropna().astype(int).tolist())
        previstos_atualizar = len(up_cod & ex_cod)
        previstos_inserir = len(up_cod - ex_cod)
    else:
        previstos_atualizar = None
        previstos_inserir = None

    with colA:
        st.metric("Linhas válidas", len(df))
    with colB:
        st.metric("Duplicadas removidas (arquivo)", int(dedupe_info.get("dedupe_cod_removed", 0)))
    with colC:
        st.metric("Conflitos CNPJ", 0 if conflitos_cnpj.empty else len(conflitos_cnpj))
    with colD:
        if previstos_inserir is not None and previstos_atualizar is not None:
            st.metric("Previsto: inserir / atualizar", f"{previstos_inserir} / {previstos_atualizar}")
        else:
            st.caption("Prévia inserir/atualizar: indisponível (tenant_id não informado ou sem acesso).")

    if not conflitos_cnpj.empty:
        with st.expander("Conflitos de CNPJ (ação aplicada automaticamente)"):
            st.dataframe(conflitos_cnpj, use_container_width=True, height=220)

    # Preview
    st.subheader("Pré-visualização")
    st.dataframe(df.head(30), use_container_width=True, height=320)

    # Controles
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        dry_run = st.checkbox("Simulação (não grava)", value=False, key="imp_forn__dry")
    with col2:
        incluir_inativos = st.checkbox("Permitir ativo=False", value=True, key="imp_forn__inativos")
    with col3:
        st.caption(f"Linhas válidas: **{len(df)}**")

    if not incluir_inativos and "ativo" in df.columns:
        df = df[df["ativo"] == True]

    if st.button("Importar (Upsert)", type="primary", use_container_width=True, key="imp_forn__run"):
        if dry_run:
            st.info("Simulação ativa: nada foi gravado.\n\n" + f"Linhas que seriam processadas: {len(df)}")
            return

        with st.spinner("Enviando para o banco..."):
            ok, updated, inserted, errors = upsert_fornecedores(supabase, df, tenant_id=tenant_id)

        # Pós-resultado
        if errors:
            st.warning(f"Importação concluída com erros em {len(errors)} linha(s).")
            st.dataframe(pd.DataFrame(errors), use_container_width=True, height=280)
        if ok:
            st.success(f"Concluído! Inseridos: {inserted} | Atualizados: {updated}")
            if not conflitos_cnpj.empty:
                st.info(
                    "Anti-duplicidade por CNPJ: algumas linhas tiveram o **cod_fornecedor** ajustado para o código existente no BD.\n"
                    "Veja o expander de conflitos para auditoria."
                )
        else:
            st.error("Falha ao importar fornecedores. Veja os erros acima.")
