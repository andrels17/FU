"""Repositório de dados: fornecedores (Supabase)."""
import pandas as pd
import streamlit as st

try:
    from src.services import observabilidade as obs
except Exception:  # pragma: no cover
    obs = None  # type: ignore

@st.cache_data(max_entries=256, ttl=300)
def carregar_fornecedores(_supabase, tenant_id: str | None = None, incluir_inativos: bool = True) -> pd.DataFrame:
    """
    Carrega lista de fornecedores.

    Para alertas e histórico, é importante incluir inativos, pois pedidos antigos
    podem referenciar fornecedores desativados.
    """
    try:
        q = _supabase.table("fornecedores").select("*")
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        if not incluir_inativos:
            q = q.eq("ativo", True)

        if obs is not None:
            with obs.time_block(
                "repo.fornecedores.execute",
                context={"tenant_id": tenant_id, "incluir_inativos": incluir_inativos},
            ):
                resultado = q.execute()
        else:
            resultado = q.execute()
        if resultado.data:
            return pd.DataFrame(resultado.data)

        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar fornecedores: {e}")
        return pd.DataFrame()


def upsert_fornecedores(_supabase, df: pd.DataFrame, tenant_id: str | None = None) -> tuple[bool, int, int, list[dict]]:
    """Upsert de fornecedores.

    Compatível com ambientes que possuem (ou não) a coluna tenant_id.
    - Preferência de conflito: (tenant_id, cod_fornecedor)
    - Fallback: cod_fornecedor
    - Último fallback: loop update/insert
    """

    errors: list[dict] = []
    updated = 0
    inserted = 0

    if df is None or df.empty:
        return True, 0, 0, []

    # Seleciona colunas suportadas no payload
    cols_allowed = {
        "cod_fornecedor",
        "nome",
        "nome_fantasia",
        "cnpj",
        "cidade",
        "uf",
        "ie",
        "endereco",
        "latitude",
        "longitude",
        "ativo",
    }

    records: list[dict] = []
    for i, row in df.iterrows():
        try:
            rec = {k: row[k] for k in df.columns if k in cols_allowed}
            # normalizações
            if "cod_fornecedor" in rec:
                rec["cod_fornecedor"] = int(float(rec["cod_fornecedor"]))
            if tenant_id:
                rec["tenant_id"] = str(tenant_id)
            # remove NaN
            clean = {}
            for k, v in rec.items():
                if pd.isna(v):
                    continue
                clean[k] = v
            # obrigatórios
            if not clean.get("cod_fornecedor") or not str(clean.get("nome") or "").strip():
                raise ValueError("cod_fornecedor/nome inválidos")
            records.append(clean)
        except Exception as e:
            errors.append({"linha": int(i) + 2, "erro": str(e)})

    if not records:
        return False, 0, 0, errors

    # 1) tenta upsert com tenant_id + cod_fornecedor
    try:
        if obs is not None:
            with obs.time_block("repo.fornecedores.upsert", context={"tenant_id": tenant_id, "rows": len(records)}):
                res = _supabase.table("fornecedores").upsert(records, on_conflict="tenant_id,cod_fornecedor").execute()
        else:
            res = _supabase.table("fornecedores").upsert(records, on_conflict="tenant_id,cod_fornecedor").execute()
        # Supabase não retorna contagem confiável de insert/update; best-effort
        return True, updated, inserted, errors
    except Exception:
        pass

    # 2) tenta upsert só por cod_fornecedor
    try:
        rec2 = []
        for r in records:
            r = dict(r)
            r.pop("tenant_id", None)
            rec2.append(r)
        if obs is not None:
            with obs.time_block("repo.fornecedores.upsert", context={"tenant_id": None, "rows": len(rec2)}):
                _supabase.table("fornecedores").upsert(rec2, on_conflict="cod_fornecedor").execute()
        else:
            _supabase.table("fornecedores").upsert(rec2, on_conflict="cod_fornecedor").execute()
        return True, updated, inserted, errors
    except Exception:
        pass

    # 3) fallback seguro (lento): update se existir, senão insert
    ok_any = False
    for r in records:
        try:
            cod = r.get("cod_fornecedor")
            q = _supabase.table("fornecedores").select("id,cod_fornecedor")
            if tenant_id and "tenant_id" in r:
                q = q.eq("tenant_id", str(tenant_id))
            q = q.eq("cod_fornecedor", cod)
            found = q.execute().data or []
            if found:
                # update
                payload = dict(r)
                payload.pop("cod_fornecedor", None)
                _u = _supabase.table("fornecedores").update(payload)
                if tenant_id and "tenant_id" in r:
                    _u = _u.eq("tenant_id", str(tenant_id))
                _u = _u.eq("cod_fornecedor", cod)
                _u.execute()
                updated += 1
            else:
                _supabase.table("fornecedores").insert(r).execute()
                inserted += 1
            ok_any = True
        except Exception as e:
            errors.append({"cod_fornecedor": r.get("cod_fornecedor"), "erro": str(e)})

    return ok_any, updated, inserted, errors
