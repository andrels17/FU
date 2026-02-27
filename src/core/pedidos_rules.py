from __future__ import annotations

from dataclasses import dataclass

def _to_float(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default

def calc_pendente(qtde_solicitada, qtde_entregue) -> float:
    qs = _to_float(qtde_solicitada, 0.0)
    qe = _to_float(qtde_entregue, 0.0)
    return max(0.0, qs - qe)

def is_entregue(qtde_solicitada, qtde_entregue) -> bool:
    qs = _to_float(qtde_solicitada, 0.0)
    qe = _to_float(qtde_entregue, 0.0)
    return bool(qs > 0 and qe >= qs)

def is_pendente(qtde_solicitada, qtde_entregue) -> bool:
    return calc_pendente(qtde_solicitada, qtde_entregue) > 0

def clamp_entregue(qtde_solicitada, qtde_entregue) -> float:
    qs = _to_float(qtde_solicitada, 0.0)
    qe = _to_float(qtde_entregue, 0.0)
    if qs > 0:
        return min(max(0.0, qe), qs)
    return max(0.0, qe)
