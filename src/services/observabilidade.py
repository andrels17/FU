"""Observabilidade (Streamlit Cloud friendly).

Inclui:
- Log rotativo em arquivo (./logs/fu_app.log)
- Registro best-effort no Supabase (tabela app_logs)
- Métricas leves de performance (tempo por página/consulta) em session_state

Sem dependências extras.
"""

from __future__ import annotations

import json
import logging
import os
import time
import traceback
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional

import streamlit as st


LOGGER_NAME = "fu"


def setup_logging(log_dir: str = "logs", filename: str = "fu_app.log") -> None:
    """Inicializa logging rotativo.

    No Streamlit Cloud o filesystem é efêmero, mas isso ajuda muito em debug e na
    tela interna de Observabilidade.
    """
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)

    # Evita handlers duplicados em reruns
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return

    handler = RotatingFileHandler(
        os.path.join(log_dir, filename),
        maxBytes=2_000_000,  # ~2MB
        backupCount=3,
        encoding="utf-8",
    )
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)


def _logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def _safe_json(obj: Any) -> Any:
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except Exception:
        return str(obj)


def _append_perf(metric: Dict[str, Any]) -> None:
    """Buffer circular em session_state com últimas métricas."""
    try:
        st.session_state.setdefault("_fu_perf", [])
        buf = st.session_state.get("_fu_perf")
        if not isinstance(buf, list):
            buf = []
        buf.append(metric)
        st.session_state["_fu_perf"] = buf[-200:]
    except Exception:
        pass


@contextmanager
def time_block(name: str, *, context: Optional[Dict[str, Any]] = None):
    """Cronometra um bloco e salva métrica em memória + log."""
    t0 = time.perf_counter()
    exc: Optional[BaseException] = None
    try:
        yield
    except BaseException as e:
        exc = e
        raise
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        metric = {
            "type": "perf",
            "name": name,
            "ms": round(ms, 2),
            "ok": exc is None,
            "ts": time.time(),
            "page": st.session_state.get("current_page"),
            "tenant_id": st.session_state.get("tenant_id"),
            "user_id": (st.session_state.get("usuario") or {}).get("id"),
            "context": _safe_json(context or {}),
        }
        _append_perf(metric)
        try:
            _logger().info(
                "PERF %s | %sms | ok=%s | ctx=%s",
                name,
                metric["ms"],
                metric["ok"],
                metric["context"],
            )
        except Exception:
            pass

        # Streamlit Cloud: também registra performance no Supabase (best-effort)
        # para permitir ranking por tenant/latência no painel Superadmin.
        try:
            supabase_admin = st.session_state.get("_supabase_admin")
        except Exception:
            supabase_admin = None

        if supabase_admin is not None:
            try:
                log_event(
                    message=f"{name} | {metric['ms']}ms | ok={metric['ok']}",
                    level="info" if metric["ok"] else "error",
                    event="perf",
                    context={
                        "name": name,
                        "ms": metric["ms"],
                        "ok": metric["ok"],
                        "page": metric.get("page"),
                    },
                    supabase_admin=supabase_admin,
                )
            except Exception:
                pass


def log_event(
    message: str,
    *,
    level: str = "info",
    event: str = "event",
    context: Optional[Dict[str, Any]] = None,
    supabase_admin=None,
) -> None:
    payload = {
        "event": event,
        "message": message,
        "tenant_id": st.session_state.get("tenant_id"),
        "user_id": (st.session_state.get("usuario") or {}).get("id"),
        "page": st.session_state.get("current_page"),
        "context": _safe_json(context or {}),
    }

    try:
        getattr(_logger(), level.lower(), _logger().info)(
            json.dumps(payload, ensure_ascii=False)
        )
    except Exception:
        pass

    if supabase_admin is not None:
        try:
            # tenta o schema completo (recomendado)
            supabase_admin.table("app_logs").insert(
                {
                    "event": payload["event"],
                    "level": level.lower(),
                    "message": payload["message"],
                    "tenant_id": payload["tenant_id"],
                    "user_id": payload["user_id"],
                    "page": payload["page"],
                    "context": payload["context"],
                }
            ).execute()
        except Exception:
            # fallback: schema mínimo (event/level/message/context)
            try:
                supabase_admin.table("app_logs").insert(
                    {
                        "event": payload["event"],
                        "level": level.lower(),
                        "message": payload["message"],
                        "context": payload["context"],
                    }
                ).execute()
            except Exception:
                pass


def log_exception(
    exc: BaseException,
    *,
    event: str = "exception",
    context: Optional[Dict[str, Any]] = None,
    supabase_admin=None,
) -> None:
    tb = traceback.format_exc()
    log_event(
        f"{type(exc).__name__}: {exc}",
        level="error",
        event=event,
        context={"traceback": tb, **(context or {})},
        supabase_admin=supabase_admin,
    )
