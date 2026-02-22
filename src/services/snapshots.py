from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from src.services.saas_metrics import build_tenant_health_row, list_tenants


def _iso_today() -> str:
    return date.today().isoformat()


def gerar_snapshot_por_tenant(supabase_admin, snapshot_date: str | None = None) -> List[Dict[str, Any]]:
    """Gera métricas rápidas por tenant e persiste em saas_snapshots (best-effort).

    - snapshot_date: YYYY-MM-DD (default hoje)
    - grava uma linha por tenant, com metrics em JSON
    """

    snap = snapshot_date or _iso_today()
    tenants = list_tenants(supabase_admin)
    rows: List[Dict[str, Any]] = []

    for t in tenants:
        tid = t.get("id")
        if not tid:
            continue
        metrics = build_tenant_health_row(supabase_admin, str(tid))
        rows.append(
            {
                "snapshot_date": snap,
                "tenant_id": str(tid),
                "metrics": metrics,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    if not rows:
        return []

    # Persistência best-effort
    try:
        # Supabase python geralmente suporta upsert
        supabase_admin.table("saas_snapshots").upsert(
            rows,
            on_conflict="snapshot_date,tenant_id",
        ).execute()
    except Exception:
        try:
            supabase_admin.table("saas_snapshots").insert(rows).execute()
        except Exception:
            pass

    return rows


def listar_snapshots(supabase_admin, days: int = 30):
    """Lista snapshots recentes (best-effort)."""
    try:
        # pega últimos N dias (server-side). Se falhar, retorna últimos 500.
        res = (
            supabase_admin.table("saas_snapshots")
            .select("snapshot_date,tenant_id,metrics,created_at")
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        return res.data or []
    except Exception:
        return []
