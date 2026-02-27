
"""UX helpers (Streamlit) — compatível e estável.

Objetivo:
- Evitar popups inesperados durante render (mobile/desktop).
- Manter compatibilidade com chamadas antigas que passam icon=...

Convenções:
- ok()         -> toast (evento do usuário)
- toast()      -> toast explícito
- info()/warn()-> inline por padrão (st.info/st.warning)
- err()        -> st.error (inline)
"""

from __future__ import annotations
import streamlit as st
from typing import Any


def toast(msg: str, *, icon: str = "🔔") -> None:
    """Toast explícito (usar apenas para ações do usuário)."""
    if hasattr(st, "toast"):
        st.toast(msg, icon=icon)
    else:
        st.info(msg)


def ok(msg: str, *, icon: str = "✅") -> None:
    """Sucesso → toast."""
    toast(msg, icon=icon)


def info(msg: str, *, icon: str | None = None, toast_mode: bool = False, **_: Any) -> None:
    """Informação.

    - Por padrão: inline (não popup).
    - Se toast_mode=True: usa toast (quando disponível).
    - Aceita icon=... por compatibilidade (se toast_mode=True).
    """
    if toast_mode:
        toast(msg, icon=icon or "ℹ️")
    else:
        st.info(msg)


def warn(msg: str, *, icon: str | None = None, toast_mode: bool = False, **_: Any) -> None:
    """Aviso.

    - Por padrão: inline (não popup).
    - Se toast_mode=True: usa toast (quando disponível).
    - Aceita icon=... por compatibilidade.
    """
    if toast_mode:
        toast(msg, icon=icon or "⚠️")
    else:
        st.warning(msg)


def err(msg: str, *, icon: str | None = None, **_: Any) -> None:
    """Erro (inline). icon é ignorado (compat)."""
    st.error(msg)


def segmented(
    label: str,
    options: list[str],
    *,
    key: str,
    default: str | None = None,
    horizontal: bool = True,
):
    """Segmented control com fallback para radio."""
    if default is None and options:
        default = options[0]

    if hasattr(st, "segmented_control"):
        return st.segmented_control(
            label,
            options=options,
            default=default,
            key=key,
        )
    idx = options.index(default) if default in options else 0
    return st.radio(
        label,
        options=options,
        index=idx,
        key=key,
        horizontal=horizontal,
    )


def container(title: str | None = None, *, border: bool = True):
    """Container padronizado."""
    c = st.container(border=border)
    if title:
        with c:
            st.markdown(f"#### {title}")
    return c
