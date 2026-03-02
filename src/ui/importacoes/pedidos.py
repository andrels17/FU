"""Importação de pedidos (em massa) - Cloud-safe (v9).

Inclui:
- Deduplicação dentro do Excel por chave (nr_oc, cod_material, cod_equipamento)
- Comparador inteligente: só atualiza se mudou algum campo relevante
- Bulk UPSERT em lote (melhor performance em 5k+ linhas)
- Importa `valor_ultima_compra` (quando existir no arquivo)

Requisito recomendado no BD (para UPSERT em lote funcionar corretamente):
  Índices recomendados no BD:
  - UNIQUE INDEX parcial (com OC): (tenant_id, nr_oc, cod_material, cod_equipamento) WHERE nr_oc IS NOT NULL
  - UNIQUE INDEX parcial (sem OC): (tenant_id, nr_solicitacao, cod_material, cod_equipamento) WHERE nr_oc IS NULL AND nr_solicitacao IS NOT NULL

Obs: usamos `supabase_user` (contexto de auth) para não quebrar triggers/colunas NOT NULL baseadas em auth.uid().
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from src.ui import ux

from src.ui.theme import section_header


# -----------------------------
# Utilidades
# -----------------------------

def _norm_col(s: str) -> str:
    """Normaliza nomes de colunas vindos de Excel/CSV.

    - remove BOM e espaços invisíveis
    - remove acentos
    - padroniza separadores (espaço, hífen, /) para underscore
    - remove símbolos (inclui º/°)
    """
    import re
    import unicodedata

    if s is None:
        return ""
    s = str(s)

    # BOM + espaços invisíveis
    s = s.replace("\ufeff", "").strip()

    # unicode/acentos
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))

    s = s.lower()

    # separadores -> _
    s = re.sub(r"[\s\-\/]+", "_", s)

    # remove tudo que não seja [a-z0-9_]
    s = re.sub(r"[^a-z0-9_]", "", s)

    # colapsa underscores
    s = re.sub(r"_+", "_", s).strip("_")
    return s



def _get_current_user_id(supabase_user) -> str | None:
    usuario = st.session_state.get("usuario") or {}
    uid = usuario.get("user_id") or st.session_state.get("user_id")
    if uid:
        return str(uid)
    try:
        gu = supabase_user.auth.get_user()
        if gu and getattr(gu, "user", None) and getattr(gu.user, "id", None):
            return str(gu.user.id)
    except Exception:
        pass
    return None


def _safe_float(x: Any) -> Optional[float]:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        # aceita "1.234,56"
        if isinstance(x, str):
            s = x.strip().replace(".", "").replace(",", ".")
            return float(s) if s else None
        return float(x)
    except Exception:
        return None


def _safe_int(x: Any) -> Optional[int]:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        if isinstance(x, str):
            s = x.strip()
            if not s:
                return None
            return int(float(s.replace(".", "").replace(",", ".")))
        return int(x)
    except Exception:
        return None


def _safe_date(x: Any) -> Optional[str]:
    if x is None:
        return None

    # Pandas pode trazer datas como Timestamp/NaT; trate tudo que for "NA" como None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass

    # datetime/date
    if isinstance(x, (datetime, date)):
        return x.date().isoformat() if isinstance(x, datetime) else x.isoformat()

    # pandas Timestamp
    try:
        import pandas as _pd
        if isinstance(x, _pd.Timestamp):
            return x.date().isoformat()
    except Exception:
        pass

    # strings (inclui casos "NaT"/"nan")
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        sl = s.lower()
        if sl in ("nat", "nan", "none", "null"):
            return None
        # aceita dd/mm/aaaa
        if "/" in s:
            try:
                d, m, y = s.split("/")
                return date(int(y), int(m), int(d)).isoformat()
            except Exception:
                return None
        return s  # já pode vir ISO

    return None

def _norm_nr_oc(v: Any) -> Optional[str]:
    """Normaliza identificadores (OC / solicitação) vindos do Excel.

    - Trata números do Excel (ex.: 12345.0) removendo o sufixo .0 quando for inteiro
    - Remove espaços e BOM
    - Converte 0 / vazio / NaN / 'nan' para None
    """
    import re
    import math

    if v is None:
        return None

    # números
    if isinstance(v, int):
        return None if v == 0 else str(v).strip()

    if isinstance(v, float):
        if math.isnan(v):
            return None
        if v == 0.0:
            return None
        if float(v).is_integer():
            return str(int(v)).strip()
        s = str(v).strip()
        m = re.match(r"^([0-9]+)\.0+$", s)
        return m.group(1) if m else s

    s = str(v).replace("\ufeff", "").strip()
    sl = s.lower()

    if (not s) or sl in ("0", "0.0", "nan", "none", "null"):
        return None

    # remove sufixo .0 para strings numéricas (ex.: "12345.0")
    m = re.match(r"^([0-9]+)\.0+$", s)
    if m:
        return m.group(1)

    return s

def _make_key(nr_oc: Any, nr_solicitacao: Any, cod_material: Any, cod_equipamento: Any) -> str:
    """Chave lógica do item (com OC ou sem OC)."""
    oc = _norm_nr_oc(nr_oc)
    base = oc or str(nr_solicitacao or "").strip()
    return f"{base}|{str(cod_material or '').strip()}|{str(cod_equipamento or '').strip()}"



def _fetch_existing(_supabase, tenant_id: str, keys: List[str]) -> Dict[str, Dict[str, Any]]:
    """Busca registros existentes por tenant e retorna dict chave->row.

    Para performance, busca por tenant e depois filtra em memória (evita OR gigante).
    """
    # Se o tenant tem muitos pedidos, ideal seria paginação; aqui é suficiente para importações típicas.
    try:
        res = (
            _supabase.table("pedidos")
            .select(
                "id,tenant_id,nr_oc,nr_solicitacao,cod_material,cod_equipamento,departamento,descricao,qtde_solicitada,qtde_entregue,qtde_pendente,entregue,previsao_entrega,data_oc,data_solicitacao,status,valor_ultima_compra,valor_total,valor_ultima_compra,criado_por"
            )
            .eq("tenant_id", tenant_id)
            .limit(20000)
            .execute()
        )
        rows = res.data or []
        out: Dict[str, Dict[str, Any]] = {}
        wanted = set(keys)
        for r in rows:
            k = _make_key(r.get("nr_oc"), r.get("nr_solicitacao"), r.get("cod_material"), r.get("cod_equipamento"))
            if k in wanted:
                out[k] = r
        return out
    except Exception:
        return {}


def _make_sol_key(nr_solicitacao: Any, cod_material: Any, cod_equipamento: Any) -> str:
    """Chave por Solicitação (ignora nr_oc)."""
    sol = _norm_nr_oc(nr_solicitacao) or str(nr_solicitacao or "").strip()
    return f"{sol}|{str(cod_material or '').strip()}|{str(cod_equipamento or '').strip()}"


def _fetch_existing_by_sol(_supabase, tenant_id: str, sol_keys: List[str]) -> Dict[str, Dict[str, Any]]:
    """Busca registros existentes por chave de Solicitação (tenant + nr_solicitacao + material + equipamento).

    Necessário quando há UNIQUE que ignora nr_oc (ex.: pedidos_uq_sol_full),
    pois um item "com OC" pode colidir com um registro existente "sem OC".
    """
    if not sol_keys:
        return {}
    try:
        res = (
            _supabase.table("pedidos")
            .select(
                "id,tenant_id,nr_oc,nr_solicitacao,cod_material,cod_equipamento,departamento,descricao,qtde_solicitada,qtde_entregue,qtde_pendente,entregue,previsao_entrega,data_oc,data_solicitacao,status,valor_ultima_compra,valor_total,criado_por"
            )
            .eq("tenant_id", tenant_id)
            .limit(20000)
            .execute()
        )
        rows = res.data or []
        wanted = set(sol_keys)
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            if not r.get("nr_solicitacao"):
                continue
            sk = _make_sol_key(r.get("nr_solicitacao"), r.get("cod_material"), r.get("cod_equipamento"))
            if sk in wanted:
                out[sk] = r
        return out
    except Exception:
        return {}



def _fetch_fornecedores(_supabase, tenant_id: str, cods: List[int]) -> Dict[int, Dict[str, Any]]:
    """Busca fornecedores existentes do tenant por cod_fornecedor."""
    if not cods:
        return {}
    try:
        # PostgREST aceita in_ com lista
        res = (
            _supabase.table("fornecedores")
            .select("id,cod_fornecedor,nome,cidade,uf,endereco,tenant_id")
            .eq("tenant_id", tenant_id)
            .in_("cod_fornecedor", cods)
            .execute()
        )
        rows = res.data or []
        return {int(r["cod_fornecedor"]): r for r in rows if r.get("cod_fornecedor") is not None}
    except Exception:
        return {}


def _ensure_fornecedores(
    _supabase,
    tenant_id: str,
    itens: List[Dict[str, Any]],
    batch_size: int = 250,
) -> Tuple[Dict[int, str], int]:
    """Garante fornecedores (por cod_fornecedor) e retorna (map cod->id, criados_ou_atualizados).

    Usa UPSERT por (tenant_id, cod_fornecedor). Depende do UNIQUE INDEX:
      fornecedores_tenant_cod_unique (tenant_id, cod_fornecedor)
    """
    # coletar cods válidos (robusto contra NaN/strings)
    import re as _re

    def _to_int_cod(v: Any) -> Optional[int]:
        if v is None:
            return None
        # NaN do pandas/Excel
        try:
            if isinstance(v, float) and pd.isna(v):
                return None
        except Exception:
            pass
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return int(v)
        if isinstance(v, float):
            if float(v).is_integer():
                return int(v)
            try:
                return int(v)
            except Exception:
                return None
        s = str(v).replace("\ufeff", "").strip()
        if not s or s.lower() in ("nan", "none", "null"):
            return None
        # extrai apenas dígitos (ex.: "000123", "12345.0", "COD 123")
        m = _re.search(r"(\d+)", s)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    cods = sorted({c for c in (_to_int_cod(it.get("cod_fornecedor")) for it in itens) if c is not None})
    if not cods:
        return {}, 0

    # buscar existentes
    existing = _fetch_fornecedores(_supabase, tenant_id, cods)
    cod_to_id: Dict[int, str] = {c: str(r["id"]) for c, r in existing.items() if r.get("id")}

    # preparar missing (e também permitir atualizar nome/cidade/uf/endereco se vier preenchido)
    upsert_rows: List[Dict[str, Any]] = []
    for it in itens:
        cod = _to_int_cod(it.get("cod_fornecedor"))
        if cod is None:
            continue
        # Se já existe e o item não traz nenhuma info nova, pula
        nome = (it.get("fornecedor_nome") or it.get("fornecedor") or it.get("nome") or "").strip()
        cidade = (it.get("cidade") or "").strip()
        uf = (it.get("uf") or "").strip()
        endereco = (it.get("endereco") or it.get("endereço") or "").strip()

        if cod in existing:
            # atualizar somente se houver dado não-vazio
            if not (nome or cidade or uf or endereco):
                continue

        row = {
            "tenant_id": tenant_id,
            "cod_fornecedor": cod,
        }
        # `nome` é NOT NULL no schema; garantir um fallback.
        row["nome"] = nome or existing.get(cod, {}).get("nome") or f"Fornecedor {cod}"
        if cidade:
            row["cidade"] = cidade
        if uf:
            row["uf"] = uf
        if endereco:
            row["endereco"] = endereco

        upsert_rows.append(row)

    if not upsert_rows:
        return cod_to_id, 0

    changed = 0
    # UPSERT em lotes
    for j in range(0, len(upsert_rows), batch_size):
        batch = upsert_rows[j : j + batch_size]
        try:
            res = (
                _supabase.table("fornecedores")
                .upsert(batch, on_conflict="tenant_id,cod_fornecedor")
                .execute()
            )
            rows = res.data or []
            for r in rows:
                if r.get("cod_fornecedor") is not None and r.get("id"):
                    cod_to_id[int(r["cod_fornecedor"])] = str(r["id"])
            changed += len(batch)
        except Exception:
            # se o upsert não retornar representação, buscamos de novo
            pass

    # garantir ids (re-busca o que faltar)
    missing = [c for c in cods if c not in cod_to_id]
    if missing:
        fetched = _fetch_fornecedores(_supabase, tenant_id, missing)
        for c, r in fetched.items():
            if r.get("id"):
                cod_to_id[int(c)] = str(r["id"])

    return cod_to_id, changed

def _diff_payload(existing: Dict[str, Any], payload: Dict[str, Any], compare_fields: List[str]) -> Tuple[bool, Dict[str, Any]]:
    """Retorna (mudou?, payload_update) contendo apenas campos alterados."""
    changed = False
    upd: Dict[str, Any] = {}
    for f in compare_fields:
        if f not in payload:
            continue
        newv = payload.get(f)
        oldv = existing.get(f)
        # normalização simples
        if isinstance(newv, float) and newv is not None and isinstance(oldv, (int, float)) and oldv is not None:
            if abs(float(newv) - float(oldv)) < 1e-9:
                continue
        if (newv or None) != (oldv or None):
            changed = True
            upd[f] = newv
    return changed, upd


def _dedup_df(df: pd.DataFrame, keep: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Deduplica por chave lógica do item.

    Chave:
      - com OC: (nr_oc, cod_material, cod_equipamento)
      - sem OC: (nr_solicitacao, cod_material, cod_equipamento)
    """
    df2 = df.copy()

    nr_oc_norm = df2.get("nr_oc")
    nr_oc_norm = nr_oc_norm.astype(str).str.strip() if nr_oc_norm is not None else pd.Series([""] * len(df2))
    nr_oc_norm = nr_oc_norm.replace({"nan": "", "None": ""})
    nr_oc_norm = nr_oc_norm.mask(nr_oc_norm.eq("0"), "")

    nr_sol = df2.get("nr_solicitacao")
    nr_sol = nr_sol.astype(str).str.strip() if nr_sol is not None else pd.Series([""] * len(df2))
    nr_sol = nr_sol.replace({"nan": "", "None": ""})

    base = nr_oc_norm.where(nr_oc_norm.ne(""), nr_sol)

    cod_mat = df2.get("cod_material")
    cod_mat = cod_mat.astype(str).str.strip() if cod_mat is not None else pd.Series([""] * len(df2))
    cod_mat = cod_mat.replace({"nan": "", "None": ""})

    cod_eq = df2.get("cod_equipamento")
    cod_eq = cod_eq.astype(str).str.strip() if cod_eq is not None else pd.Series([""] * len(df2))
    cod_eq = cod_eq.replace({"nan": "", "None": ""})

    df2["_k"] = base + "|" + cod_mat + "|" + cod_eq

    dup_mask = df2.duplicated(subset=["_k"], keep=False)
    dups = df2.loc[dup_mask].drop(columns=["_k"]).copy()
    dedup = df2.drop_duplicates(subset=["_k"], keep=keep).drop(columns=["_k"]).copy()
    return dedup, dups



# -----------------------------
# UI Principal
# -----------------------------

def exibir_importacao_pedidos(
    supabase_user,
    supabase_admin=None,
    tenant_id: str | None = None,
    scope: str = "user",
    **_kwargs,
):
    tenant_id = str(
        tenant_id
        or st.session_state.get("tenant_id")
        or (st.session_state.get("usuario") or {}).get("tenant_id")
        or ""
    ).strip()

    if not tenant_id:
        st.error("❌ Não foi possível identificar o tenant.")
        return

    # `scope` pode ser passado pelo hub de importações (ex.: scope="admin").
    # Esta tela usa o client do usuário por padrão (mantém auth.uid() e RLS coerentes).
    # Mantemos o parâmetro aqui para compatibilidade e para evitar que a página quebre.
    scope = str(scope or "user").strip().lower()

    user_id = _get_current_user_id(supabase_user)
    if not user_id:
        st.error("❌ Não foi possível identificar o usuário logado (user_id). Faça logout/login e tente novamente.")
        st.stop()

    # IMPORTANT: usar client do usuário para manter auth.uid() (se houver trigger) e RLS coerente
    _supabase = supabase_user

    section_header(
        "Importar Pedidos em Massa",
        hint="Importe pedidos (linhas) via Excel/CSV. Chave de UPSERT: (com OC) OC + Material + Equipamento; (sem OC) Solicitação + Material + Equipamento.",
        pill="Importação",
    )

    with st.container(border=True):
        st.caption("Dica: para melhor performance, mantenha OC, cod_material e cod_equipamento preenchidos.")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            dedup_on = st.checkbox("Detectar e deduplicar duplicadas", value=True, key="imp_ped_dedup_on")
        with c2:
            keep_opt = st.selectbox("Ao deduplicar, manter", options=["last", "first"], index=0, key="imp_ped_keep")
        with c3:
            batch_size = st.number_input("Tamanho do lote (UPSERT)", min_value=50, max_value=1000, value=250, step=50, key="imp_ped_batch")

    up = st.file_uploader("Selecione o arquivo Excel (.xlsx) ou CSV", type=["xlsx", "xls", "csv"], key="imp_ped_file")
    if not up:
        return

    # ---- Ler arquivo
    try:
        if up.name.lower().endswith(".csv"):
            df = pd.read_csv(up)
        else:
            df = pd.read_excel(up)
    except Exception as e:
        st.error(f"❌ Não foi possível ler o arquivo: {e}")
        return

    if df.empty:
        ux.warn("Arquivo vazio.")
        return

    # Normalizar colunas (mapeia variações)
    col_map = {_norm_col(c): c for c in df.columns}
    def _pick(*cands: str) -> Optional[str]:
        for c in cands:
            if c in col_map:
                return col_map[c]
        return None

    # Campos esperados (com variações)
    c_nr_oc = _pick("nr_oc", "nr oc", "n_oc", "n° oc", "nº oc", "no_oc", "no oc", "oc", "numero_oc", "numero oc", "numero da oc")
    c_nr_sol = _pick("nr_solicitacao", "nr solicitacao", "n_solicitacao", "n° solicitacao", "nº solicitacao", "solicitacao", "numero_solicitacao", "numero solicitacao")
    c_depto = _pick("departamento", "almoxarifado", "setor")
    c_cod_eq = _pick("cod_equipamento", "codigo equipamento", "equipamento", "cod equipamento")
    c_cod_mat = _pick("cod_material", "codigo material", "material", "cod material")
    c_desc = _pick("descricao", "descricacao", "descricao material", "material descricao")
    c_qsol = _pick("qtde_solicitada", "qtd solicitada", "quantidade solicitada", "qtde", "qtd")
    c_qent = _pick("qtde_entregue", "qtd entregue", "quantidade entregue")
    c_qpen = _pick("qtde_pendente", "qtd pendente", "quantidade pendente")
    c_entregue = _pick("entregue", "foi entregue")
    c_data_oc = _pick("data oc", "data_oc", "data da oc")
    c_prev = _pick("previsao_entrega", "previsao entrega", "prev entrega", "data previsao")
    c_data_sol = _pick("data solicitacao", "data_solicitacao", "data requisicao")
    c_status = _pick("status")
    c_vu = _pick("valor_ultima_compra", "valor unitario", "preco", "preco unitario")
    c_vt = _pick("valor_total", "valor total", "total")
    c_vuc = _pick("valor_ultima_compra", "valor ultima compra", "ultima compra", "vl ultima compra", "vl_ultima_compra")

    # Fornecedor (opcional) - resolve para fornecedor_id
    c_cod_forn = _pick("fornecedor_id", "cod_fornecedor", "cod fornecedor", "codigo fornecedor", "fornecedor codigo")
    c_forn_nome = _pick("fornecedor", "nome_fornecedor", "fornecedor_nome", "nome fornecedor", "razao_social", "razão_social")
    c_forn_cidade = _pick("cidade", "fornecedor_cidade", "cidade fornecedor")
    c_forn_uf = _pick("uf", "estado", "fornecedor_uf", "uf fornecedor")
    c_forn_end = _pick("endereco", "endereço", "endereco fornecedor", "endereço fornecedor")

    # Campos mínimos para chave
    if (not c_nr_oc and not c_nr_sol) or (not c_cod_mat) or (not c_cod_eq):
        st.error("❌ O arquivo precisa conter: cod_material, cod_equipamento e (nr_oc/OC ou nr_solicitacao).")
        ux.info(
            f"Encontrado: nr_oc={bool(c_nr_oc)}, nr_solicitacao={bool(c_nr_sol)}, cod_material={bool(c_cod_mat)}, cod_equipamento={bool(c_cod_eq)}"
        )
        return

    # Montar DF padronizado
    out_rows: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        nr_oc = r.get(c_nr_oc)
        cod_material = r.get(c_cod_mat)
        cod_equipamento = r.get(c_cod_eq)

        row = {
            "nr_oc": _norm_nr_oc(nr_oc),
            "nr_solicitacao": (_norm_nr_oc(r.get(c_nr_sol)) if c_nr_sol else None),
            "departamento": str(r.get(c_depto) or "").strip() if c_depto else None,
            "cod_equipamento": str(cod_equipamento or "").strip(),
            "cod_material": str(cod_material or "").strip(),
            "descricao": str(r.get(c_desc) or "").strip() if c_desc else None,
            "qtde_solicitada": _safe_float(r.get(c_qsol)) if c_qsol else None,
            "qtde_entregue": _safe_float(r.get(c_qent)) if c_qent else None,
            "qtde_pendente": _safe_float(r.get(c_qpen)) if c_qpen else None,
            "entregue": bool(r.get(c_entregue)) if c_entregue and pd.notna(r.get(c_entregue)) else None,
            "data_oc": _safe_date(r.get(c_data_oc)) if c_data_oc else None,
            "previsao_entrega": _safe_date(r.get(c_prev)) if c_prev else None,
            "data_solicitacao": _safe_date(r.get(c_data_sol)) if c_data_sol else None,
            "status": str(r.get(c_status) or "").strip() if c_status else None,
            "valor_total": _safe_float(r.get(c_vt)) if c_vt else None,
            "valor_ultima_compra": _safe_float(r.get(c_vuc)) if c_vuc else (_safe_float(r.get(c_vu)) if c_vu else None),
            "cod_fornecedor": _safe_int(r.get(c_cod_forn)) if c_cod_forn else None,
            "fornecedor_nome": str(r.get(c_forn_nome) or "").strip() if c_forn_nome else None,
            "cidade": str(r.get(c_forn_cidade) or "").strip() if c_forn_cidade else None,
            "uf": str(r.get(c_forn_uf) or "").strip() if c_forn_uf else None,
            "endereco": str(r.get(c_forn_end) or "").strip() if c_forn_end else None,
        }
        # chave vazia? ignora
        if (not row.get("cod_material")) or (not row.get("cod_equipamento")):
            continue
        if (row.get("nr_oc") is None) and (not str(row.get("nr_solicitacao") or "").strip()):
            continue
        out_rows.append(row)

    df2 = pd.DataFrame(out_rows)
    if df2.empty:
        ux.warn("Nenhuma linha válida encontrada (chave incompleta)." )
        return

    # Dedup no excel
    duplicadas_df = pd.DataFrame()
    if dedup_on:
        df2, duplicadas_df = _dedup_df(df2, keep=keep_opt)
        if not duplicadas_df.empty:
            with st.expander(f"⚠️ Duplicidades detectadas no arquivo ({len(duplicadas_df)})", expanded=False):
                st.dataframe(duplicadas_df.head(200), use_container_width=True)

    (st.toast(f"Arquivo carregado: {len(df2)} registros válidos") if hasattr(st,"toast") else ux.ok(f"Arquivo carregado: {len(df2)} registros válidos"))

    # Pré-visualização (editor read-only com tipagem/formatos)
    preview = df2.head(50).copy()


    # O Streamlit Data Editor valida compatibilidade entre o tipo configurado
    # (ex.: DateColumn) e o tipo real do dataframe (inferido via Arrow).
    # Em alguns cenários (principalmente quando a coluna vem como "object" com
    # strings misturadas), o schema pode ser inferido como STRING mesmo após uma
    # conversão simples.
    #
    # Como essa tabela é apenas uma prévia (read-only), fazemos uma conversão
    # mais "forçada" para garantir que **nenhum valor string** permaneça.
    if "data_oc" in preview.columns:
        _dt = pd.to_datetime(preview["data_oc"], errors="coerce")
        preview["data_oc"] = _dt.dt.date
        # Se ainda restou algum string (dtype object com mistura), força datetime.
        try:
            if preview["data_oc"].map(lambda x: isinstance(x, str)).any():
                preview["data_oc"] = _dt
        except Exception:
            pass
    cfg = {}
    if "data_oc" in preview.columns:
        # Se por algum motivo o Streamlit ainda inferir STRING, ele vai quebrar.
        # Então, fazemos um fallback seguro para TextColumn.
        try:
            cfg["data_oc"] = st.column_config.DateColumn("Data OC")
        except Exception:
            cfg["data_oc"] = st.column_config.TextColumn("Data OC")
    if "nr_oc" in preview.columns: cfg["nr_oc"] = st.column_config.TextColumn("N° OC")
    if "departamento" in preview.columns: cfg["departamento"] = st.column_config.TextColumn("Departamento")
    if "fornecedor" in preview.columns: cfg["fornecedor"] = st.column_config.TextColumn("Fornecedor")
    if "uf" in preview.columns: cfg["uf"] = st.column_config.TextColumn("UF", width="small")
    if "descricao" in preview.columns: cfg["descricao"] = st.column_config.TextColumn("Descrição", help="Descrição do material")
    if "qtde_solicitada" in preview.columns: cfg["qtde_solicitada"] = st.column_config.NumberColumn("Qtde. Solicitada")
    if "preco" in preview.columns: cfg["preco"] = st.column_config.NumberColumn("Preço", format="R$ %.2f")
    if hasattr(st, "data_editor"):
        st.data_editor(preview, use_container_width=True, hide_index=True, disabled=True, column_config=cfg)
    else:
        st.dataframe(preview, use_container_width=True, height=260)


    # Resolver fornecedor_id (opcional): cria fornecedor se não existir (por tenant_id + cod_fornecedor)
    fornecedor_cod_to_id: Dict[int, str] = {}
    fornecedores_changed = 0
    if "cod_fornecedor" in df2.columns and df2["cod_fornecedor"].notna().any():
        itens_f = df2[["cod_fornecedor", "fornecedor_nome", "cidade", "uf", "endereco"]].to_dict("records")
        fornecedor_cod_to_id, fornecedores_changed = _ensure_fornecedores(
            _supabase,
            tenant_id=tenant_id,
            itens=itens_f,
            batch_size=int(batch_size),
        )
        if fornecedores_changed:
            st.caption(f"✅ Fornecedores criados/atualizados automaticamente: {fornecedores_changed}")

        # Anexar fornecedor_id ao dataframe (somente para payload; não é campo obrigatório)
        def _map_fid(x):
            try:
                if x is None or (isinstance(x, float) and pd.isna(x)):
                    return None
                return fornecedor_cod_to_id.get(int(x))
            except Exception:
                return None

        df2["fornecedor_id"] = df2["cod_fornecedor"].apply(_map_fid)
    # Preparar chaves e buscar existentes
    keys = [_make_key(r["nr_oc"], r.get("nr_solicitacao"), r["cod_material"], r["cod_equipamento"]) for _, r in df2.iterrows()]
    existing = _fetch_existing(_supabase, tenant_id=tenant_id, keys=keys)

    # Alguns ambientes possuem UNIQUE por Solicitação (ignora nr_oc):
    # (tenant_id, nr_solicitacao, cod_material, cod_equipamento)
    # Para evitar 23505 em lotes "com OC", carregamos também o cache por SOL.
    sol_keys = []
    try:
        for _, r in df2.iterrows():
            if r.get("nr_solicitacao"):
                sol_keys.append(_make_sol_key(r.get("nr_solicitacao"), r.get("cod_material"), r.get("cod_equipamento")))
    except Exception:
        sol_keys = []
    existing_by_sol = _fetch_existing_by_sol(_supabase, tenant_id=tenant_id, sol_keys=list(set(sol_keys)))

    # Contadores
    will_insert = 0
    will_update = 0
    will_skip = 0


    # Campos realmente presentes no arquivo (para não sobrescrever com NULL quando a coluna não existir)
    provided_fields: List[str] = []
    if c_nr_sol: provided_fields.append("nr_solicitacao")
    if c_depto: provided_fields.append("departamento")
    if c_desc: provided_fields.append("descricao")
    if c_qsol: provided_fields.append("qtde_solicitada")
    if c_qent: provided_fields.append("qtde_entregue")
    if c_qpen: provided_fields.append("qtde_pendente")
    if c_entregue: provided_fields.append("entregue")
    if c_data_oc: provided_fields.append("data_oc")
    if c_prev: provided_fields.append("previsao_entrega")
    if c_data_sol: provided_fields.append("data_solicitacao")
    if c_status: provided_fields.append("status")
    if c_vu or c_vuc: provided_fields.append("valor_ultima_compra")
    if c_vt: provided_fields.append("valor_total")

    compare_fields = provided_fields



    # Detalhamento das atualizações (prévia e pós-importação)
    # Cada item representa um campo alterado (antes -> depois) para um registro existente.
    update_changes: List[Dict[str, Any]] = []
    update_rows_preview: List[Dict[str, Any]] = []

    # Montar payloads para upsert
    upsert_rows: List[Dict[str, Any]] = []

    for _, r in df2.iterrows():
        key = _make_key(r["nr_oc"], r.get("nr_solicitacao"), r["cod_material"], r["cod_equipamento"])
        base_payload: Dict[str, Any] = {
            "tenant_id": tenant_id,
            "nr_oc": r["nr_oc"],
            "cod_material": r["cod_material"],
            "cod_equipamento": r["cod_equipamento"],
            # resto
            **{f: r.get(f) for f in compare_fields if f in r.index},
            "atualizado_por": user_id,
        }

        if key not in existing:
            base_payload["criado_por"] = user_id
            will_insert += 1
            upsert_rows.append(base_payload)
        else:
            ex = existing[key]
            changed, upd = _diff_payload(ex, base_payload, compare_fields)
            if changed:
                # registrar quais campos mudaram (prévia)
                changed_fields = sorted(list(upd.keys()))
                update_rows_preview.append({
                    "nr_oc": base_payload.get("nr_oc"),
                    "nr_solicitacao": base_payload.get("nr_solicitacao"),
                    "cod_material": base_payload.get("cod_material"),
                    "cod_equipamento": base_payload.get("cod_equipamento"),
                    "campos_alterados": ", ".join(changed_fields),
                })
                for f, newv in upd.items():
                    update_changes.append({
                        "nr_oc": base_payload.get("nr_oc"),
                        "nr_solicitacao": base_payload.get("nr_solicitacao"),
                        "cod_material": base_payload.get("cod_material"),
                        "cod_equipamento": base_payload.get("cod_equipamento"),
                        "campo": f,
                        "antes": ex.get(f),
                        "depois": newv,
                    })

                # preservar criado_por existente
                base_payload["criado_por"] = ex.get("criado_por") or user_id
                will_update += 1
                upsert_rows.append(base_payload)
            else:
                will_skip += 1

    c1, c2, c3 = st.columns(3)
    c1.metric("Registros", len(df2))
    c2.metric("Novos", will_insert)
    c3.metric("Atualizações", will_update)

    if will_skip:
        st.caption(f"Sem alterações: {will_skip}")

    
    # Prévia do que será atualizado (antes de executar)
    if update_changes:
        with st.expander(
            f"🔎 Prévia das atualizações ({will_update} registro(s) / {len(update_changes)} campo(s) alterado(s))",
            expanded=False,
        ):
            df_prev = pd.DataFrame(update_rows_preview)
            st.dataframe(df_prev.head(300), use_container_width=True, height=260)

            df_det = pd.DataFrame(update_changes)
            # Resumo por campo
            resumo = (
                df_det.groupby("campo", dropna=False)
                .size()
                .reset_index(name="qtd_alteracoes")
                .sort_values("qtd_alteracoes", ascending=False)
            )
            st.caption("Resumo por campo alterado:")
            st.dataframe(resumo, use_container_width=True, height=220)

            csv_bytes = df_det.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇️ Baixar detalhamento (CSV)",
                data=csv_bytes,
                file_name="atualizacoes_previas.csv",
                mime="text/csv",
                use_container_width=True,
                key="imp_ped_prev_csv",
            )

    if st.button("🚀 Importar (UPSERT em lote)", type="primary", use_container_width=True, key="imp_ped_run"):
        prog = st.progress(0.0)
        status = st.empty()

        inserted = 0
        updated = 0
        errors = 0

        bulk_upsert_enabled = True  # desabilita automaticamente se o BD não tiver UNIQUE/INDEX p/ ON CONFLICT
        total = len(upsert_rows)
        if total == 0:
            ux.info("Nada para importar (sem mudanças)." )
            return
        # Batches (com OC / sem OC)
        oc_rows = [r for r in upsert_rows if r.get("nr_oc")]
        sem_oc_rows = [r for r in upsert_rows if not r.get("nr_oc")]

        done = 0
        def _process_batches(rows: List[Dict[str, Any]], on_conflict: str, label: str):
            nonlocal inserted, updated, errors, done, bulk_upsert_enabled

            # ------------------------------------------------------------
            # IMPORTANT: Alguns bancos têm também um UNIQUE por "SOL" (nr_solicitacao)
            # que pode colidir quando chega um item "com OC" mas já existe um registro
            # "sem OC" com a mesma solicitação/material/equipamento.
            #
            # Nesses casos, um UPSERT em lote mirando o índice "com OC" falha com 23505
            # (duplicate key) em "pedidos_uq_sol_full".
            #
            # Estratégia:
            # - Detecta esses casos usando o cache `existing` (carregado antes)
            # - Faz UPDATE linha-a-linha usando match por nr_solicitacao
            # - Remove do lote "com OC" para não derrubar o batch
            # ------------------------------------------------------------
            if label == "com OC":
                promote_updates: List[Dict[str, Any]] = []
                remaining: List[Dict[str, Any]] = []

                for r in rows:
                    nr_sol = r.get("nr_solicitacao")
                    if nr_sol:
                        sol_k = _make_sol_key(
                            nr_sol,
                            r.get("cod_material"),
                            r.get("cod_equipamento"),
                        )
                        # Se já existe um registro com a mesma SOL+material+equipamento,
                        # o lote "com OC" pode quebrar no UNIQUE pedidos_uq_sol_full.
                        # Nesses casos, fazemos update por SOL e tiramos do batch.
                        if sol_k in existing_by_sol:
                            promote_updates.append(r)
                            continue
                    remaining.append(r)

                # Executa os updates promovidos (por SOL) antes do lote
                for r in promote_updates:
                    try:
                        match = {
                            "tenant_id": r.get("tenant_id"),
                            "nr_solicitacao": r.get("nr_solicitacao"),
                            "cod_material": r.get("cod_material"),
                            "cod_equipamento": r.get("cod_equipamento"),
                        }
                        _supabase.table("pedidos").update(r).match(match).execute()
                        updated += 1

                        # Atualiza cache local (SOL e chave principal)
                        sol_k = _make_sol_key(
                            r.get("nr_solicitacao"),
                            r.get("cod_material"),
                            r.get("cod_equipamento"),
                        )
                        existing_by_sol[sol_k] = {**existing_by_sol.get(sol_k, {}), **r}

                        k = _make_key(
                            r.get("nr_oc"),
                            r.get("nr_solicitacao"),
                            r.get("cod_material"),
                            r.get("cod_equipamento"),
                        )
                        existing[k] = {**existing.get(k, {}), **r}
                    except Exception as ee:
                        errors += 1
                        status.error(f"❌ Erro ao promover update (com OC via SOL): {ee}")

                rows = remaining

            t = len(rows)
            if t == 0:
                return

            for j in range(0, t, int(batch_size)):
                batch = rows[j : j + int(batch_size)]

                # 1) Tenta UPSERT em lote (se habilitado)
                if bulk_upsert_enabled:
                    try:
                        _supabase.table("pedidos").upsert(
                            batch,
                            on_conflict=on_conflict,
                        ).execute()

                        # contabiliza e atualiza cache local "existing"
                        for row in batch:
                            k = _make_key(
                                row.get("nr_oc"),
                                row.get("nr_solicitacao"),
                                row.get("cod_material"),
                                row.get("cod_equipamento"),
                            )
                            if k in existing:
                                updated += 1
                                existing[k] = {**existing.get(k, {}), **row}
                            else:
                                inserted += 1
                                existing[k] = row

                    except Exception as e:
                        status.error(f"❌ Erro no lote ({label}) {j//int(batch_size)+1}: {e}")

                        err_txt = str(e)
                        # Caso clássico: ON CONFLICT sem UNIQUE/EXCLUSION constraint no BD
                        if ("42P10" in err_txt) or ("no unique or exclusion constraint" in err_txt.lower()):
                            if bulk_upsert_enabled:
                                bulk_upsert_enabled = False
                                status.warning(
                                    "⚠️ Seu banco não possui um índice/constraint UNIQUE compatível com ON CONFLICT. "
                                    "Continuando em modo seguro (linha-a-linha). "
                                    "Recomendação: crie UNIQUE INDEX parcial para habilitar UPSERT em lote."
                                )

                        # Fallback: processa linha-a-linha usando match pela chave lógica
                        for row in batch:
                            try:
                                k = _make_key(
                                    row.get("nr_oc"),
                                    row.get("nr_solicitacao"),
                                    row.get("cod_material"),
                                    row.get("cod_equipamento"),
                                )
                                has_oc = bool(row.get("nr_oc"))
                                match = {
                                    "tenant_id": row.get("tenant_id"),
                                    "cod_material": row.get("cod_material"),
                                    "cod_equipamento": row.get("cod_equipamento"),
                                }
                                # Se existir UNIQUE por SOL, pode haver registro com outra OC.
                                # Preferimos casar por SOL quando possível.
                                sol_k = None
                                if row.get("nr_solicitacao"):
                                    sol_k = _make_sol_key(
                                        row.get("nr_solicitacao"),
                                        row.get("cod_material"),
                                        row.get("cod_equipamento"),
                                    )
                                if sol_k and (sol_k in existing_by_sol):
                                    match["nr_solicitacao"] = row.get("nr_solicitacao")
                                elif has_oc:
                                    match["nr_oc"] = row.get("nr_oc")
                                else:
                                    match["nr_solicitacao"] = row.get("nr_solicitacao")

                                if k in existing:
                                    _supabase.table("pedidos").update(row).match(match).execute()
                                    updated += 1
                                    existing[k] = {**existing.get(k, {}), **row}
                                    if sol_k:
                                        existing_by_sol[sol_k] = {**existing_by_sol.get(sol_k, {}), **row}
                                else:
                                    _supabase.table("pedidos").insert(row).execute()
                                    inserted += 1
                                    existing[k] = row
                                    if sol_k:
                                        existing_by_sol[sol_k] = row

                            except Exception as ee:
                                errors += 1
                                status.error(f"❌ Erro na linha ({label}): {ee}")

                        done += len(batch)
                        prog.progress(min(1.0, done / total))
                        status.info(f"Processando {done}/{total}...")
                        continue

                # 2) Se bulk estiver desabilitado, vai direto em modo seguro
                else:
                    for row in batch:
                        try:
                            k = _make_key(
                                row.get("nr_oc"),
                                row.get("nr_solicitacao"),
                                row.get("cod_material"),
                                row.get("cod_equipamento"),
                            )
                            has_oc = bool(row.get("nr_oc"))
                            match = {
                                "tenant_id": row.get("tenant_id"),
                                "cod_material": row.get("cod_material"),
                                "cod_equipamento": row.get("cod_equipamento"),
                            }
                            if has_oc:
                                match["nr_oc"] = row.get("nr_oc")
                            else:
                                match["nr_solicitacao"] = row.get("nr_solicitacao")

                            if k in existing:
                                _supabase.table("pedidos").update(row).match(match).execute()
                                updated += 1
                                existing[k] = {**existing.get(k, {}), **row}
                            else:
                                _supabase.table("pedidos").insert(row).execute()
                                inserted += 1
                                existing[k] = row

                        except Exception as ee:
                            errors += 1
                            status.error(f"❌ Erro na linha ({label}): {ee}")

                done += len(batch)
                prog.progress(min(1.0, done / total))
                status.info(f"Processando {done}/{total}...")
        _process_batches(oc_rows, "tenant_id,nr_oc,cod_material,cod_equipamento", "com OC")
        _process_batches(sem_oc_rows, "tenant_id,nr_solicitacao,cod_material,cod_equipamento", "sem OC")

        if errors == 0:
            ux.ok(f"✅ Importação concluída — Inseridos: {inserted} | Atualizados: {updated} | Erros: {errors}")
        else:
            ux.warn(f"⚠️ Importação finalizada com erros — Inseridos: {inserted} | Atualizados: {updated} | Erros: {errors}")


        # Detalhamento do que foi atualizado (campo a campo)
        if updated and update_changes:
            with st.expander("📌 O que foi atualizado (detalhado)", expanded=False):
                df_det = pd.DataFrame(update_changes)

                # Resumo por campo (quantas mudanças por coluna)
                resumo = (
                    df_det.groupby("campo", dropna=False)
                    .size()
                    .reset_index(name="qtd_alteracoes")
                    .sort_values("qtd_alteracoes", ascending=False)
                )
                st.caption("Resumo por campo alterado:")
                st.dataframe(resumo, use_container_width=True, height=240)

                st.caption("Detalhamento (antes → depois):")
                st.dataframe(df_det.head(500), use_container_width=True, height=320)

                csv_bytes = df_det.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "⬇️ Baixar detalhamento das atualizações (CSV)",
                    data=csv_bytes,
                    file_name="atualizacoes_detalhadas.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="imp_ped_upd_csv",
                )
