"""Repositório de dados: pedidos e entregas (Supabase)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

@st.cache_data(ttl=60)
def carregar_pedidos(_supabase, tenant_id: str | None = None, almoxarifado: str | None = None):
    """
    Carrega todos os pedidos com informações do fornecedor
    VERSÃO CORRIGIDA com diagnóstico automático de datas
    """
    try:
        q = _supabase.table('vw_pedidos_completo').select('*')
        if tenant_id:
            q = q.eq('tenant_id', tenant_id)
        resultado = q.execute()
        if resultado.data:
            df = pd.DataFrame(resultado.data)

            # ===== Filtro global por Almoxarifado =====
            if almoxarifado and almoxarifado != "Todos":
                if "almoxarifado" in df.columns:
                    df = df[
                        df["almoxarifado"]
                        .astype(str)
                        .fillna("")
                        .str.strip() == str(almoxarifado)
                    ]

            
            # Converter datas com MÚLTIPLAS TENTATIVAS
            date_columns = ['data_solicitacao', 'data_oc', 'previsao_entrega', 'data_entrega_real', 'criado_em', 'atualizado_em']
            
            for col in date_columns:
                if col in df.columns:
                    # Tentar múltiplos formatos
                    if df[col].dtype == 'object':
                        # Método 1: Conversão padrão
                        df[col] = pd.to_datetime(df[col], errors='coerce')
                        
                        # Se não funcionou, tentar formato específico
                        if df[col].isna().all():
                            # Método 2: Formato ISO
                            df[col] = pd.to_datetime(df[col], format='ISO8601', errors='coerce')
                        
                        # Se ainda não funcionou, tentar formato brasileiro
                        if df[col].isna().all():
                            # Método 3: Formato brasileiro
                            df[col] = pd.to_datetime(df[col], format='%d/%m/%Y', errors='coerce')
                    else:
                        # Já é datetime ou timestamp
                        df[col] = pd.to_datetime(df[col], errors='coerce')
            
            # Garantir tipos booleanos corretos
            bool_columns = ['entregue', 'atrasado']
            for col in bool_columns:
                if col in df.columns:
                    # Converter para booleano tratando diversos formatos
                    if df[col].dtype == 'object':
                        # Mapear strings possíveis
                        df[col] = df[col].astype(str).str.lower().map({
                            'true': True, 
                            'false': False, 
                            't': True, 
                            'f': False,
                            '1': True,
                            '0': False,
                            'yes': True,
                            'no': False,
                            'sim': True,
                            'não': False,
                            'nao': False
                        })
                    
                    # Garantir tipo booleano
                    df[col] = df[col].fillna(False).astype(bool)
            
            # RECALCULAR coluna 'atrasado' (CRÍTICO!)
            # Isso garante que mesmo se o Supabase estiver errado, o cálculo será correto
            if 'previsao_entrega' in df.columns and 'entregue' in df.columns:
                hoje = pd.Timestamp.now().normalize()
                
                # Criar coluna temporária para não perder a original
                df['previsao_dt_calc'] = pd.to_datetime(df['previsao_entrega'], errors='coerce')
                
                # Calcular atrasado
                df['atrasado'] = (
                    (df['entregue'] == False) & 
                    (df['previsao_dt_calc'] < hoje) &
                    (df['previsao_dt_calc'].notna())
                )
                
                # Remover coluna temporária
                df = df.drop('previsao_dt_calc', axis=1)
            
            # Garantir que valores numéricos estão corretos
            numeric_columns = ['qtde_solicitada', 'qtde_entregue', 'valor_total', 'valor_ultima_compra']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            # LIMPEZA DE HTML - Remover qualquer HTML dos campos de texto
            import html
            import re
            
            def limpar_html(texto):
                """Remove HTML de um texto"""
                if pd.isna(texto) or texto is None:
                    return texto
                
                texto_str = str(texto)
                # Decodificar entidades HTML
                texto_str = html.unescape(texto_str)
                # Remover tags HTML
                texto_str = re.sub(r'<[^>]+>', '', texto_str)
                # Limpar espaços extras
                texto_str = re.sub(r'\s+', ' ', texto_str).strip()
                
                return texto_str if texto_str else None
            
            # Aplicar limpeza em campos de texto
            text_columns = ['descricao', 'nr_oc', 'nr_solicitacao', 'departamento', 
                          'cod_equipamento', 'cod_material', 'fornecedor_nome', 
                          'fornecedor_cidade', 'status', 'observacoes']
            
            for col in text_columns:
                if col in df.columns:
                    df[col] = df[col].apply(limpar_html)
            
            # SOLUÇÃO TEMPORÁRIA: Calcular previsão se estiver tudo NULL
            if 'previsao_entrega' in df.columns and df['previsao_entrega'].isna().all():
                import calcular_previsao_temporario as cpt
                df = cpt.calcular_previsao_entrega_temporario(df)
            
            return df
            
        return pd.DataFrame()
        
    except Exception as e:
        st.error(f"❌ Erro ao carregar pedidos: {e}")
        import traceback
        st.error("Detalhes do erro:")
        st.code(traceback.format_exc())
        return pd.DataFrame()

@st.cache_data(ttl=300)
def carregar_fornecedores(_supabase, tenant_id: str | None = None):
    """Carrega lista de fornecedores (compat)."""
    try:
        q = _supabase.table('fornecedores').select('*').eq('ativo', True)
        if tenant_id:
            q = q.eq('tenant_id', tenant_id)
        resultado = q.execute()
        if resultado.data:
            return pd.DataFrame(resultado.data)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar fornecedores: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def carregar_estatisticas_departamento(_supabase):
    """Carrega estatísticas por departamento"""
    try:
        resultado = _supabase.table('vw_stats_departamento').select('*').execute()
        if resultado.data:
            return pd.DataFrame(resultado.data)
        return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

def salvar_pedido(pedido_data, _supabase):
    """Salva ou atualiza um pedido"""
    try:
        pedido_data['atualizado_por'] = st.session_state.usuario['id']
        
        if 'id' in pedido_data and pedido_data['id']:
            # Atualizar
            resultado = _supabase.table('pedidos').update(pedido_data).eq('id', pedido_data['id']).execute()
        else:
            # Inserir novo
            pedido_data['criado_por'] = st.session_state.usuario['id']
            resultado = _supabase.table('pedidos').insert(pedido_data).execute()
        
        st.cache_data.clear()
        return True, "Pedido salvo com sucesso!"
    except Exception as e:
        return False, f"Erro ao salvar pedido: {e}"

def registrar_entrega(pedido_id, qtde_entregue, data_entrega, observacoes="", _supabase=None):
    if _supabase is None:
        raise ValueError("Supabase client não informado")
    """Registra uma entrega parcial ou total"""
    try:
        # Buscar pedido atual
        tenant_id = st.session_state.get('tenant_id')
        q_p = _supabase.table('pedidos').select('*').eq('id', pedido_id)
        if tenant_id:
            q_p = q_p.eq('tenant_id', tenant_id)
        pedido = q_p.execute()
        
        if not pedido.data:
            return False, "Pedido não encontrado"
        
        pedido_atual = pedido.data[0]
        nova_qtde_entregue = pedido_atual['qtde_entregue'] + qtde_entregue
        
        # Atualizar pedido
        _supabase.table('pedidos').update({
            'qtde_entregue': nova_qtde_entregue,
            'data_entrega_real': data_entrega if nova_qtde_entregue >= pedido_atual['qtde_solicitada'] else None,
            'atualizado_por': st.session_state.usuario['id']
        }).eq('id', pedido_id).execute()
        
        # Registrar no histórico
        _supabase.table('historico_entregas').insert({
            'pedido_id': pedido_id,
            'qtde_entregue': qtde_entregue,
            'data_entrega': data_entrega,
            'observacoes': observacoes,
            'usuario_id': st.session_state.usuario['id'],
            'tenant_id': pedido_atual.get('tenant_id')
        }).execute()
        
        st.cache_data.clear()
        return True, "Entrega registrada com sucesso!"
    except Exception as e:
        return False, f"Erro ao registrar entrega: {e}"

# ============================================
# DASHBOARD PRINCIPAL
# ============================================

