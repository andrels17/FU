"""src.services.saas_metrics

Métricas e saúde por tenant (SaaS / Superadmin)

Pensado para Streamlit Cloud:
- Evitar queries pesadas por padrão
- Usar contagens *best-effort* (count/head) com fallbacks

Este módulo NÃO depende de schema específico além dos nomes de tabelas.
Se alguma tabela não existir no banco do cliente, a função retorna "N/A".
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple


def _try_count(q) -> Optional[int]:
    """Tenta obter contagem via PostgREST.

    Supabase Python (postgrest) geralmente retorna res.count quando count='exact'.
    Como versões variam, esta função tenta múltiplas formas.
    """
    try:
        res = q.execute()
        # forma 1
        c = getattr(res, "count", None)
        if isinstance(c, int):
            return c
        # forma 2: alguns retornos expõem count dentro de dict
        if isinstance(res, dict) and isinstance(res.get("count"), int):
            return int(res["count"])
        # forma 3: fallback pelo tamanho do data (se veio)
        data = getattr(res, "data", None)
        if isinstance(data, list):
            return len(data)
    except Exception:
        return None
    return None


def count_rows(supabase_admin, table: str, tenant_id: str | None = None, date_field: str | None = None,
               start: str | None = None, end: str | None = None) -> Optional[int]:
    """Conta linhas (best-effort)."""
    try:
        q = supabase_admin.table(table).select("id", count="exact")
        # filtros
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        if date_field and start:
            q = q.gte(date_field, start)
        if date_field and end:
            q = q.lt(date_field, end)
        return _try_count(q)
    except Exception:
        return None


def sum_field(supabase_admin, table: str, field: str, tenant_id: str | None = None,
              date_field: str | None = None, start: str | None = None, end: str | None = None) -> Optional[float]:
    """Soma campo numérico (best-effort).

    Se não houver RPC/agg disponível, faz fallback trazendo poucas linhas e somando.
    (Não é perfeito, mas evita travar em bancos sem permissões para agregação custom.)
    """
    try:
        q = supabase_admin.table(table).select(field)
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        if date_field and start:
            q = q.gte(date_field, start)
        if date_field and end:
            q = q.lt(date_field, end)

        # tentar reduzir tráfego: limitar em 10k
        q = q.limit(10000)
        res = q.execute()
        data = getattr(res, "data", None) or []
        total = 0.0
        for row in data:
            try:
                v = row.get(field)
                if v is None:
                    continue
                total += float(v)
            except Exception:
                continue
        return total
    except Exception:
        return None


def list_tenants(supabase_admin) -> list[dict]:
    """Lista tenants com alguns campos comuns (id + nome/razao_social/name)."""
    try:
        res = supabase_admin.table("tenants").select("id,nome,name,razao_social,created_at").order("created_at", desc=True).limit(500).execute()
        return res.data or []
    except Exception:
        # schema diferente
        try:
            res = supabase_admin.table("tenants").select("*").limit(200).execute()
            return res.data or []
        except Exception:
            return []


def tenant_display_name(t: dict) -> str:
    for k in ("nome", "name", "razao_social"):
        v = t.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(t.get("id", "tenant"))


def build_tenant_health_row(supabase_admin, tenant_id: str) -> Dict[str, Any]:
    """Coleta métricas essenciais (rápidas) por tenant."""
    pedidos_total = count_rows(supabase_admin, "pedidos", tenant_id=tenant_id)
    pedidos_pendentes = None
    try:
        q = supabase_admin.table("pedidos").select("id", count="exact").eq("tenant_id", tenant_id).eq("entregue", False)
        pedidos_pendentes = _try_count(q)
    except Exception:
        pedidos_pendentes = None

    fornecedores_total = count_rows(supabase_admin, "fornecedores", tenant_id=tenant_id)
    usuarios_total = count_rows(supabase_admin, "tenant_users", tenant_id=tenant_id)

    valor_total = sum_field(supabase_admin, "pedidos", "valor_total", tenant_id=tenant_id)

    return {
        "tenant_id": tenant_id,
        "pedidos": pedidos_total,
        "pendentes": pedidos_pendentes,
        "fornecedores": fornecedores_total,
        "usuarios": usuarios_total,
        "valor_total": valor_total,
    }


def period_bounds(period: str) -> Tuple[str, str]:
    """Retorna (start_iso, end_iso) para períodos comuns."""
    today = date.today()
    if period == "Últimos 7 dias":
        start = today.toordinal() - 7
        d0 = date.fromordinal(start)
        return d0.isoformat(), (today.isoformat())
    if period == "Últimos 30 dias":
        start = today.toordinal() - 30
        d0 = date.fromordinal(start)
        return d0.isoformat(), (today.isoformat())
    # Mês atual
    d0 = today.replace(day=1)
    return d0.isoformat(), (today.isoformat())
