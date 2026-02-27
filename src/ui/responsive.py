"""Helpers de responsividade (toggle manual 'mobile_mode').

Uso:
    from src.ui.responsive import is_mobile, rcols

    c1, c2, c3, c4 = rcols([1.4, 1.1, 1.1, 1.4])
    # Desktop: 1 linha com 4 colunas
    # Mobile: quebra em múltiplas linhas com 2 colunas (preserva o unpack)
"""

from __future__ import annotations

from typing import List, Sequence, Union

import streamlit as st


def is_mobile() -> bool:
    """True quando o usuário ativou o toggle '📱 Modo mobile'."""

    return bool(st.session_state.get("mobile_mode", False))


def rcols(
    spec: Union[int, Sequence[float]],
    *,
    mobile_cols: int = 2,
    gap: str | None = None,
) -> List[st.delta_generator.DeltaGenerator]:
    """Columns responsivas preservando o número de containers.

    - spec int -> N colunas (peso 1)
    - spec sequência -> pesos
    - Em mobile, quando N > mobile_cols, quebra em múltiplas linhas com mobile_cols colunas.

    Isso mantém compatibilidade com código existente que faz unpack:
        a, b, c, d, e = rcols(5)
    """

    if isinstance(spec, int):
        weights: List[float] = [1.0] * int(spec)
    else:
        weights = [float(x) for x in spec]

    n = len(weights)
    if (not is_mobile()) or n <= mobile_cols:
        return list(st.columns(weights, gap=gap))

    out: List[st.delta_generator.DeltaGenerator] = []
    for i in range(0, n, mobile_cols):
        row_w = weights[i : i + mobile_cols]
        out.extend(list(st.columns(row_w, gap=gap)))
    return out
