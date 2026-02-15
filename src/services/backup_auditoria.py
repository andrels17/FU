"""
Backup e Auditoria (MVP)

Este módulo fornece:
- registrar_acao: grava logs na tabela logs_auditoria (se existir)
- exibir_painel_auditoria: painel simples para consulta
- realizar_backup_manual: exporta tabelas essenciais para XLSX

Obs: Em produção, prefira migrations SQL no Supabase para garantir as tabelas.
"""
from __future__ import annotations

from datetime import datetime
import io
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st


def registrar_acao(usuario: Dict[str, Any], acao: str, detalhes: Dict[str, Any], supabase) -> None:
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
    except Exception as e:
        # Não bloquear o app por falha de log
        st.warning(f"⚠️ Não foi possível registrar auditoria: {e}")


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
    st.title("🔒 Painel de Auditoria e Logs")

    col1, col2 = st.columns([2, 1])
    with col1:
        filtro = st.selectbox("Tipo de Ação:", ["Todas", "Login", "Logout", "Criar Pedido", "Editar Pedido", "Excluir Pedido", "Registrar Entrega", "Exportar Dados"])
    with col2:
        limite = st.number_input("Limite:", min_value=10, max_value=1000, value=200, step=10)

    df = carregar_logs_auditoria(supabase, None if filtro == "Todas" else filtro, limite=int(limite))
    if df.empty:
        st.info("📭 Nenhum log encontrado (verifique se a tabela logs_auditoria existe e está acessível).")
        return

    # Formatação básica
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M:%S")

    cols = [c for c in ["timestamp","usuario_nome","usuario_email","acao","detalhes"] if c in df.columns]
    st.dataframe(df[cols] if cols else df, use_container_width=True, hide_index=True)


def realizar_backup_manual(supabase) -> None:
    st.subheader("💾 Backup Manual dos Dados")
    st.caption("Gera um XLSX com pedidos e fornecedores (quando disponíveis).")

    if st.button("🔄 Gerar Backup Completo", use_container_width=True):
        with st.spinner("Gerando backup..."):
            try:
                pedidos = supabase.table("pedidos").select("*").execute()
                fornecedores = supabase.table("fornecedores").select("*").execute()

                df_pedidos = pd.DataFrame(pedidos.data) if pedidos.data else pd.DataFrame()
                df_fornecedores = pd.DataFrame(fornecedores.data) if fornecedores.data else pd.DataFrame()

                output = io.BytesIO()
                # usar openpyxl (já está nas dependências)
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df_pedidos.to_excel(writer, sheet_name="Pedidos", index=False)
                    df_fornecedores.to_excel(writer, sheet_name="Fornecedores", index=False)

                output.seek(0)
                st.success("✅ Backup gerado com sucesso!")
                st.download_button(
                    "📥 Baixar Backup",
                    data=output,
                    file_name=f"backup_completo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"❌ Erro ao gerar backup: {e}")
