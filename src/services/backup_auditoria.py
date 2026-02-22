"""src.services.backup_auditoria

Backup e Auditoria (MVP)

Este módulo fornece:
- registrar_acao: grava logs na tabela logs_auditoria (se existir)
- registrar_acao_before_after: helper para auditoria com before/after (JSONB)
- exibir_painel_auditoria: painel simples para consulta
- realizar_backup_manual: exporta tabelas essenciais para XLSX

Notas para Streamlit Cloud:
- Falhas de escrita em logs/auditoria NUNCA devem derrubar o app.
- Por isso, tudo aqui é *best-effort* (silencioso ou com aviso leve).

Obs: Em produção, prefira migrations SQL no Supabase para garantir as tabelas.
"""

from __future__ import annotations

from datetime import datetime
import io
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st


def registrar_acao(*args, **kwargs) -> None:
    """Registra ações do usuário em logs_auditoria.

    Compatível com duas assinaturas (para não quebrar chamadas antigas):

    1) Nova (recomendada):
        registrar_acao(usuario_dict, acao, detalhes_dict, supabase)

    2) Legada (encontrada em partes do app):
        registrar_acao(supabase, usuario_email, acao, detalhes_dict)

    Também aceita kwargs:
        registrar_acao(usuario=..., acao=..., detalhes=..., supabase=...)

    IMPORTANTE: esta função é best-effort. Se falhar, apenas retorna.
    """

    usuario: Dict[str, Any] = {}
    acao: str | None = None
    detalhes: Dict[str, Any] = {}
    supabase = None

    # kwargs (prioridade)
    if kwargs:
        usuario = kwargs.get("usuario") or {}
        acao = kwargs.get("acao")
        detalhes = kwargs.get("detalhes") or {}
        supabase = kwargs.get("supabase")

    # args
    if supabase is None and args:
        # assinatura legada: (supabase, email, acao, detalhes)
        if len(args) >= 3 and hasattr(args[0], "table") and isinstance(args[1], str):
            supabase = args[0]
            usuario = {"id": None, "nome": None, "email": args[1]}
            acao = str(args[2])
            detalhes = args[3] if len(args) >= 4 and isinstance(args[3], dict) else {}

        # assinatura nova: (usuario, acao, detalhes, supabase)
        elif len(args) >= 4 and isinstance(args[0], dict) and hasattr(args[3], "table"):
            usuario = args[0]
            acao = str(args[1])
            detalhes = args[2] if isinstance(args[2], dict) else {}
            supabase = args[3]

    if not supabase or not acao:
        return

    try:
        log_entry = {
            "usuario_id": usuario.get("id"),
            "usuario_nome": usuario.get("nome"),
            "usuario_email": usuario.get("email"),
            "acao": acao,
            "detalhes": detalhes,  # jsonb
            "timestamp": datetime.now().isoformat(),
            "ip_address": "N/A",
        }
        supabase.table("logs_auditoria").insert(log_entry).execute()
    except Exception:
        # Não bloquear o app por falha de auditoria
        return


def registrar_acao_before_after(
    supabase,
    usuario: Dict[str, Any] | None,
    acao: str,
    entidade: str,
    entidade_id: str | None,
    before: Dict[str, Any] | None,
    after: Dict[str, Any] | None,
    extras: Dict[str, Any] | None = None,
) -> None:
    """Auditoria com before/after (JSONB) — best-effort."""

    payload: Dict[str, Any] = {
        "entidade": entidade,
        "entidade_id": entidade_id,
        "before": before or {},
        "after": after or {},
    }
    if extras:
        payload["extras"] = extras

    registrar_acao(usuario or {}, acao, payload, supabase)


def carregar_logs_auditoria(supabase, filtro_acao: Optional[str] = None, limite: int = 200) -> pd.DataFrame:
    try:
        q = supabase.table("logs_auditoria").select("*").order("timestamp", desc=True).limit(int(limite))
        if filtro_acao:
            q = q.eq("acao", filtro_acao)
        res = q.execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar logs: {e}")
        return pd.DataFrame()


def exibir_painel_auditoria(supabase) -> None:
    st.title("Painel de Auditoria")
    st.caption("Consulta logs_auditoria (ações do usuário).")

    col1, col2 = st.columns([2, 1])
    with col1:
        filtro = st.text_input("Filtrar por ação (opcional)", value="")
    with col2:
        limite = st.number_input("Limite", min_value=10, max_value=2000, value=200, step=50)

    df = carregar_logs_auditoria(supabase, filtro_acao=(filtro.strip() or None), limite=int(limite))
    if df.empty:
        st.info("Nenhum log encontrado (verifique se a tabela logs_auditoria existe e está acessível).")
        return

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M:%S")

    # Colunas relevantes
    cols = [c for c in ["timestamp", "usuario_nome", "usuario_email", "acao", "detalhes"] if c in df.columns]

    # Render com expanders para before/after (quando existir)
    st.dataframe(df[cols] if cols else df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Detalhes (before/after)")
    st.caption("Selecione uma linha no dataframe acima e copie o JSON em `detalhes` se precisar.\n\n"
               "Dica: quando `detalhes` contém `before` e `after`, você consegue rastrear mudanças campo a campo.")


def realizar_backup_manual(supabase) -> None:
    st.subheader("Backup Manual dos Dados")
    st.caption("Gera um XLSX com pedidos e fornecedores (quando disponíveis).")

    if st.button("Gerar Backup Completo", use_container_width=True):
        with st.spinner("Gerando backup..."):
            try:
                pedidos = supabase.table("pedidos").select("*").execute()
                fornecedores = supabase.table("fornecedores").select("*").execute()

                df_pedidos = pd.DataFrame(pedidos.data) if pedidos.data else pd.DataFrame()
                df_fornecedores = pd.DataFrame(fornecedores.data) if fornecedores.data else pd.DataFrame()

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df_pedidos.to_excel(writer, sheet_name="Pedidos", index=False)
                    df_fornecedores.to_excel(writer, sheet_name="Fornecedores", index=False)

                output.seek(0)
                st.success("Backup gerado com sucesso!")
                st.download_button(
                    "📥 Baixar Backup",
                    data=output,
                    file_name=f"backup_completo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Erro ao gerar backup: {e}")
