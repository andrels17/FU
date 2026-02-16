"""Tela: Gestão de pedidos."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import src.services.backup_auditoria as ba
import src.services.exportacao_relatorios as er  # noqa: F401  (pode estar sendo usado em outras partes)
import src.services.filtros_avancados as fa  # noqa: F401

from src.repositories.fornecedores import carregar_fornecedores
from src.repositories.pedidos import carregar_pedidos, registrar_entrega, salvar_pedido
from src.utils.formatting import formatar_moeda_br, formatar_numero_br  # noqa: F401


# -------------------------------
# Helpers de performance / UX
# -------------------------------
def _make_df_stamp(df: pd.DataFrame, col: str = "atualizado_em") -> tuple:
    """Carimbo simples para invalidar caches quando os dados mudam."""
    if df is None or df.empty:
        return (0, "empty")
    mx = None
    if col in df.columns:
        try:
            mx = str(pd.to_datetime(df[col], errors="coerce").max())
        except Exception:
            mx = str(df[col].max())
    return (int(len(df)), mx or "none")


@st.cache_data(ttl=120)
def _build_pedido_labels(stamp: tuple, df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Gera listas paralelas: labels (para UI) e ids (valor real)."""
    if df is None or df.empty:
        return [], []

    nr_oc = df.get("nr_oc", "").fillna("").astype(str)
    desc = (
        df.get("descricao", "")
        .fillna("")
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    dept = df.get("departamento", "").fillna("").astype(str)
    status = df.get("status", "").fillna("").astype(str)

    labels = ("OC: " + nr_oc + " | " + status + " | " + dept + " — " + desc.str.slice(0, 70)).tolist()
    ids = df["id"].astype(str).tolist()
    return labels, ids


@st.cache_data(ttl=300)
def _build_fornecedor_options(stamp: tuple, df_fornecedores: pd.DataFrame) -> tuple[list[str], dict[int, str]]:
    """Opções de fornecedor e mapa cod->id."""
    if df_fornecedores is None or df_fornecedores.empty:
        return [""], {}
    df = df_fornecedores.copy()
    df["cod_fornecedor"] = pd.to_numeric(df["cod_fornecedor"], errors="coerce").fillna(0).astype(int)
    df["nome"] = df.get("nome", "").fillna("").astype(str)

    options = [""] + (df["cod_fornecedor"].astype(str) + " - " + df["nome"]).tolist()
    mapa = {
        int(row["cod_fornecedor"]): str(row["id"])
        for _, row in df.iterrows()
        if int(row["cod_fornecedor"]) != 0
    }
    return options, mapa


def _download_df(df: pd.DataFrame, nome: str) -> None:
    """Botão de download CSV do dataframe."""
    if df is None or df.empty:
        return
    csv_bytes = df.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "⬇️ Baixar CSV",
        data=csv_bytes,
        file_name=nome,
        mime="text/csv",
        use_container_width=True,
    )

DEPARTAMENTOS_VALIDOS = [
    "Estoque", "Caminhões", "Oficina Geral", "Borracharia",
    "Máquinas pesadas", "Veic. Leves", "Tratores", "Colhedoras",
    "Irrigação", "Reboques", "Carregadeiras"
]
STATUS_VALIDOS = ["Sem OC", "Tem OC", "Em Transporte", "Entregue"]


def _coerce_date(x):
    """Converte valor para YYYY-MM-DD ou None."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    dt = pd.to_datetime(x, errors="coerce")
    if pd.isna(dt):
        return None
    return dt.strftime("%Y-%m-%d")


def _validate_upload_df(df_upload: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df_upload is None or df_upload.empty:
        return df_upload, pd.DataFrame([{"linha": "-", "erro": "Arquivo vazio"}])

    df = df_upload.copy()

    # Normalizações básicas
    for c in ["descricao", "departamento", "status", "nr_oc", "nr_solicitacao", "cod_equipamento", "cod_material"]:
        if c in df.columns:
            df[c] = df[c].astype(str).where(df[c].notna(), None)
            df[c] = df[c].apply(lambda v: v.strip() if isinstance(v, str) else v)

    # Coerções numéricas
    if "qtde_solicitada" in df.columns:
        df["qtde_solicitada"] = pd.to_numeric(df["qtde_solicitada"], errors="coerce")
    if "qtde_entregue" in df.columns:
        df["qtde_entregue"] = pd.to_numeric(df["qtde_entregue"], errors="coerce").fillna(0)
    else:
        df["qtde_entregue"] = 0

    if "valor_total" in df.columns:
        df["valor_total"] = pd.to_numeric(df["valor_total"], errors="coerce").fillna(0)
    else:
        df["valor_total"] = 0

    # Datas (podem vir vazias)
    for c in ["data_solicitacao", "data_oc", "previsao_entrega"]:
        if c in df.columns:
            df[c] = df[c].apply(_coerce_date)
        else:
            df[c] = None

    # Fornecedor
    if "cod_fornecedor" in df.columns:
        df["cod_fornecedor"] = pd.to_numeric(df["cod_fornecedor"], errors="coerce")
    else:
        df["cod_fornecedor"] = None

    erros = []
    for i, r in df.iterrows():
        linha = int(i) + 2  # +2 = header + 1-index excel/csv

        # obrigatórios
        if "descricao" not in df.columns or r.get("descricao") is None or str(r.get("descricao")).strip() == "":
            erros.append({"linha": linha, "erro": "Descrição vazia"})
        if pd.isna(r.get("qtde_solicitada")) or float(r.get("qtde_solicitada") or 0) <= 0:
            erros.append({"linha": linha, "erro": "Quantidade solicitada inválida"})

        # domínio
        dept = r.get("departamento")
        if dept and dept not in DEPARTAMENTOS_VALIDOS:
            erros.append({"linha": linha, "erro": f"Departamento inválido: {dept}"})

        stt = r.get("status")
        if stt and stt not in STATUS_VALIDOS:
            erros.append({"linha": linha, "erro": f"Status inválido: {stt}"})

        # datas inválidas: se coluna tinha valor mas virou None após coerção
        for dc in ["data_solicitacao", "data_oc", "previsao_entrega"]:
            if dc in df_upload.columns:
                raw = df_upload.iloc[i].get(dc)

                # considera vazio se for None, NaN, NaT, string vazia
                vazio = (
                    raw is None
                    or (isinstance(raw, float) and pd.isna(raw))
                    or (isinstance(raw, pd.Timestamp) and pd.isna(raw))
                    or (str(raw).strip().lower() in ["", "nat", "none", "nan"])
                )

                if (not vazio) and (r.get(dc) is None):
                    erros.append({"linha": linha, "erro": f"Data inválida em {dc}: {raw}"})

        # fornecedor: se informado, precisa ser int
        if "cod_fornecedor" in df.columns and pd.notna(r.get("cod_fornecedor")):
            try:
                int(r.get("cod_fornecedor"))
            except Exception:
                erros.append({"linha": linha, "erro": f"cod_fornecedor inválido: {r.get('cod_fornecedor')}"})
    

    df_erros = pd.DataFrame(erros) if erros else pd.DataFrame(columns=["linha", "erro"])
    return df, df_erros


def _resolve_import_plan(_supabase, df: pd.DataFrame, tenant_id: str | None = None) -> tuple[int, int, int]:
    """
    Plano de importação unificado (UPSERT):
    - Se encontrar pelo nr_oc (preferencial) => update
    - Se não tiver nr_oc, tenta nr_solicitacao (somente quando no banco também não tem OC) => update
    - Caso contrário => insert
    Retorna (insere, atualiza, pula)
    """
    if df is None or df.empty:
        return 0, 0, 0

    _tid = str(tenant_id) if tenant_id else None

    # Prefetch OCs
    oc_to_id: dict[str, str] = {}
    if "nr_oc" in df.columns:
        ocs = df["nr_oc"].dropna().astype(str).str.strip()
        ocs = [x for x in ocs.tolist() if x]
        if ocs:
            try:
                q = _supabase.table("pedidos").select("id,nr_oc").in_("nr_oc", ocs)
                if _tid:
                    q = q.eq("tenant_id", _tid)
                res = q.execute()
                for r in (res.data or []):
                    nr = str(r.get("nr_oc") or "").strip()
                    if nr:
                        oc_to_id[nr] = str(r.get("id"))
            except Exception:
                oc_to_id = {}

    # Prefetch solicitações (somente linhas sem OC no arquivo)
    sol_to_id_sem_oc: dict[str, str] = {}
    sol_com_oc: set[str] = set()
    if "nr_solicitacao" in df.columns:
        mask_sem_oc = df.get("nr_oc", "").fillna("").astype(str).str.strip().eq("")
        sols = df.loc[mask_sem_oc, "nr_solicitacao"].dropna().astype(str).str.strip()
        sols = [x for x in sols.tolist() if x]
        if sols:
            try:
                q = _supabase.table("pedidos").select("id,nr_solicitacao,nr_oc").in_("nr_solicitacao", sols)
                if _tid:
                    q = q.eq("tenant_id", _tid)
                res = q.execute()
                for r in (res.data or []):
                    sol = str(r.get("nr_solicitacao") or "").strip()
                    oc = str(r.get("nr_oc") or "").strip()
                    if not sol:
                        continue
                    if oc:
                        sol_com_oc.add(sol)
                    else:
                        sol_to_id_sem_oc[sol] = str(r.get("id"))
            except Exception:
                sol_to_id_sem_oc = {}
                sol_com_oc = set()

    insere = atualiza = pula = 0
    for _, r in df.iterrows():
        nr_oc = str(r.get("nr_oc") or "").strip()
        nr_sol = str(r.get("nr_solicitacao") or "").strip()

        if nr_oc:
            if nr_oc in oc_to_id:
                atualiza += 1
            else:
                insere += 1
            continue

        if nr_sol:
            if nr_sol in sol_com_oc:
                pula += 1
            elif nr_sol in sol_to_id_sem_oc:
                atualiza += 1
            else:
                insere += 1
        else:
            pula += 1

    return insere, atualiza, pula
def _bulk_update(_supabase, ids: list[str], payload: dict) -> tuple[int, list[str]]:
    """
    Tenta atualizar em lote; se não suportar, faz loop.
    Retorna (qtd_ok, erros)
    """
    if not ids:
        return 0, []

    erros = []
    ok = 0

    # tenta batch com in_
    try:
        _supabase.table("pedidos").update(payload).in_("id", ids).execute()
        return len(ids), []
    except Exception:
        pass

    # fallback: update um a um
    for pid in ids:
        try:
            _supabase.table("pedidos").update(payload).eq("id", pid).execute()
            ok += 1
        except Exception as e:
            erros.append(f"{pid}: {e}")
    return ok, erros


def exibir_gestao_pedidos(_supabase):
    """Exibe página de gestão (criar/editar) pedidos - Apenas Admin"""

    if st.session_state.usuario["perfil"] != "admin":
        st.error("⛔ Acesso negado. Apenas administradores podem gerenciar pedidos.")
        return

    st.title("✏️ Gestão de Pedidos")

    tab1, tab2, tab3, tab4 = st.tabs(["➕ Novo Pedido", "📤 Upload em Massa", "📝 Editar Pedido", "⚡ Ações em Massa"])

    # ============================================
    # TAB 1: NOVO PEDIDO
    # ============================================
    with tab1:
        st.subheader("Cadastrar Novo Pedido")

        df_fornecedores = carregar_fornecedores(_supabase, st.session_state.get("tenant_id"))

        with st.form("form_novo_pedido"):
            col1, col2 = st.columns(2)

            with col1:
                nr_solicitacao = st.text_input("N° Solicitação")
                nr_oc = st.text_input("N° Ordem de Compra")
                departamento = st.selectbox(
                    "Departamento",
                    [
                        "Estoque",
                        "Caminhões",
                        "Oficina Geral",
                        "Borracharia",
                        "Máquinas pesadas",
                        "Veic. Leves",
                        "Tratores",
                        "Colhedoras",
                        "Irrigação",
                        "Reboques",
                        "Carregadeiras",
                    ],
                )
                cod_equipamento = st.text_input("Código Equipamento")
                cod_material = st.text_input("Código Material")

            with col2:
                descricao = st.text_area("Descrição do Material", height=100)
                qtde_solicitada = st.number_input("Quantidade Solicitada", min_value=0.0, step=1.0)

                if not df_fornecedores.empty:
                    stamp_f = _make_df_stamp(
                        df_fornecedores,
                        "updated_at" if "updated_at" in df_fornecedores.columns else "id",
                    )
                    forn_opts, _ = _build_fornecedor_options(stamp_f, df_fornecedores)
                    fornecedor_selecionado = st.selectbox("Fornecedor", forn_opts)
                else:
                    st.warning("⚠️ Nenhum fornecedor cadastrado")
                    fornecedor_selecionado = ""

            col3, col4 = st.columns(2)

            with col3:
                data_solicitacao = st.date_input("Data Solicitação", value=datetime.now())
                data_oc = st.date_input("Data OC")
                previsao_entrega = st.date_input("Previsão de Entrega")

            with col4:
                status = st.selectbox("Status", ["Sem OC", "Tem OC", "Em Transporte", "Entregue"])
                valor_total = st.number_input("Valor Total (R$)", min_value=0.0, step=0.01)
                observacoes = st.text_area("Observações")

            submitted = st.form_submit_button("💾 Salvar Pedido", use_container_width=True)

            if submitted:
                if not descricao:
                    st.error("⚠️ Descrição é obrigatória")
                elif qtde_solicitada <= 0:
                    st.error("⚠️ Quantidade deve ser maior que zero")
                else:
                    fornecedor_id = None
                    if fornecedor_selecionado and not df_fornecedores.empty:
                        try:
                            cod_forn = int(fornecedor_selecionado.split(" - ")[0])
                            fornecedor_id = (
                                df_fornecedores[df_fornecedores["cod_fornecedor"] == cod_forn]["id"].values[0]
                            )
                        except Exception:
                            fornecedor_id = None

                    pedido_data = {
                        "nr_solicitacao": nr_solicitacao or None,
                        "nr_oc": nr_oc or None,
                        "departamento": departamento,
                        "cod_equipamento": cod_equipamento or None,
                        "cod_material": cod_material or None,
                        "descricao": descricao,
                        "qtde_solicitada": qtde_solicitada,
                        "qtde_entregue": 0,
                        "data_solicitacao": data_solicitacao.isoformat(),
                        "data_oc": data_oc.isoformat() if data_oc else None,
                        "previsao_entrega": previsao_entrega.isoformat() if previsao_entrega else None,
                        "status": status,
                        "valor_total": valor_total,
                        "fornecedor_id": fornecedor_id,
                        "observacoes": observacoes or None,
                    }

                    sucesso, mensagem = salvar_pedido(pedido_data, _supabase)
                    if sucesso:
                        try:
                            ba.registrar_acao(
                                _supabase,
                                st.session_state.usuario.get("email"),
                                "criar_pedido",
                                {"nr_oc": nr_oc, "descricao": (descricao or "")[:120]},
                            )
                        except Exception:
                            pass
                        st.success(mensagem)
                        st.rerun()
                    else:
                        st.error(mensagem)

    # ============================================
    # TAB 2: UPLOAD EM MASSA
    # ============================================
    with tab2:
        st.subheader("📤 Importar Pedidos em Massa")

        st.info(
            """
📋 **Instruções:**
1. Baixe o template abaixo
2. Preencha com os dados dos pedidos
3. Faça upload do arquivo preenchido
4. Revise os dados antes de importar

💡 **Dica:** Se o fornecedor não existir, o sistema pode criá-lo automaticamente!
"""
        )

        template_data = {
            "nr_solicitacao": ["123456"],
            "nr_oc": ["OC-2024-001"],
            "departamento": ["Estoque"],
            "cod_equipamento": ["EQ-001"],
            "cod_material": ["MAT-001"],
            "descricao": ["Exemplo de material"],
            "qtde_solicitada": [10],
            "cod_fornecedor": [6691],
            "nome_fornecedor": ["Nome do Fornecedor (opcional)"],
            "cidade_fornecedor": ["São Paulo (opcional)"],
            "uf_fornecedor": ["SP (opcional)"],
            "data_solicitacao": ["2024-01-15"],
            "data_oc": ["2024-01-16"],
            "previsao_entrega": ["2024-02-15"],
            "status": ["Tem OC"],
            "valor_total": [1500.00],
        }

        df_template = pd.DataFrame(template_data)
        csv_template = df_template.to_csv(index=False, encoding="utf-8-sig", sep=";", decimal=",")

        st.download_button(
            label="📥 Baixar Template",
            data=csv_template,
            file_name="template_importacao_pedidos.csv",
            mime="text/csv",
        )

        st.markdown("---")
        with st.expander("🗑️ Ferramentas de Limpeza de Banco", expanded=False):
            st.warning("⚠️ **ATENÇÃO:** Esta ferramenta permite limpar completamente o banco de dados de pedidos. Use com extremo cuidado!")
            
            col_limpar1, col_limpar2 = st.columns([3, 1])
            
            with col_limpar1:
                st.markdown("""
                **Quando usar:**
                - Antes de importar uma nova base completa de dados
                - Para resetar o sistema durante testes
                - Para corrigir erros massivos de dados
                
                **O que será deletado:**
                - ✅ Todos os pedidos existentes no banco
                - ✅ Histórico e registros antigos
                - ❌ **NÃO** afeta fornecedores, usuários ou configurações
                """)
            
            with col_limpar2:
                confirmacao_limpeza = st.checkbox(
                    "Confirmo que entendo os riscos",
                    key="confirmar_limpeza_banco",
                    help="Marque esta caixa para habilitar o botão de limpeza"
                )
            
            if confirmacao_limpeza:
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
                
                with col_btn2:
                    if st.button("🗑️ LIMPAR BANCO DE DADOS", type="primary", use_container_width=True):
                        # Confirmação final com input de texto
                        confirmacao_final = st.text_input(
                            "Digite 'CONFIRMAR' para prosseguir com a limpeza:",
                            key="confirmacao_texto_limpeza"
                        )
                        
                        if confirmacao_final == "CONFIRMAR":
                            try:
                                with st.spinner("🗑️ Limpando banco de dados..."):
                                    # Contar registros antes
                                    try:
                                        count_antes = _supabase.table("pedidos").select("id", count="exact").execute()
                                        total_antes = count_antes.count if hasattr(count_antes, 'count') else 0
                                    except:
                                        total_antes = 0
                                    
                                    # Executar limpeza
                                    tenant_id = st.session_state.get("tenant_id")
                                    
                                    _supabase.table("pedidos").delete().eq("tenant_id", tenant_id).execute()
                                    
                                    # Limpar cache
                                    st.cache_data.clear()
                                    
                                    # Registrar auditoria
                                    try:
                                        ba.registrar_acao(
                                            _supabase,
                                            st.session_state.usuario.get("email"),
                                            "limpar_banco",
                                            {"registros_deletados": total_antes}
                                        )
                                    except:
                                        pass
                                    
                                    st.success(f"✅ Banco limpo com sucesso! {total_antes} registros foram removidos.")
                                    st.balloons()
                                    
                                    # Limpar confirmação
                                    if 'confirmacao_texto_limpeza' in st.session_state:
                                        del st.session_state['confirmacao_texto_limpeza']
                                    
                                    # Esperar 2 segundos e recarregar
                                    import time
                                    time.sleep(2)
                                    st.rerun()
                                    
                            except Exception as e_limpeza:
                                st.error(f"❌ Erro ao limpar banco: {e_limpeza}")
                                st.error("Por favor, tente novamente ou contate o administrador.")
                        
                        elif confirmacao_final and confirmacao_final != "CONFIRMAR":
                            st.warning("⚠️ Texto de confirmação incorreto. Digite exatamente 'CONFIRMAR' (em maiúsculas).")
            else:
                st.info("ℹ️ Marque a caixa de confirmação acima para habilitar a limpeza do banco.")

        st.markdown("---")

        # Upload em massa: evita 'resquícios' de arquivos anteriores
        if "upload_massa_key" not in st.session_state:
            st.session_state["upload_massa_key"] = 0
        uploader_key = f"upload_massa_{st.session_state['upload_massa_key']}"

        arquivo_upload = st.file_uploader(
            "Selecione o arquivo Excel ou CSV",
            type=["xlsx", "xls", "csv"],
            help="Arquivo deve seguir o template fornecido",
            key=uploader_key,
        )

        if arquivo_upload:
            try:
                # Ler arquivo
                if arquivo_upload.name.endswith(".csv"):
                    try:
                        df_upload = pd.read_csv(arquivo_upload, sep=";", decimal=",", encoding="utf-8-sig")
                    except Exception:
                        try:
                            df_upload = pd.read_csv(arquivo_upload, encoding="utf-8-sig")
                        except Exception:
                            df_upload = pd.read_csv(arquivo_upload, encoding="latin1")
                else:
                    df_upload = pd.read_excel(arquivo_upload)

                st.success(f"✅ Arquivo carregado: {len(df_upload)} registros encontrados")

                st.subheader("👀 Preview dos Dados")
                st.dataframe(df_upload.head(10), use_container_width=True)

                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    st.markdown("**Modo:** Importar / Sincronizar (UPSERT automático por OC → Solicitação)")
                    atualizacao_conservadora = st.checkbox(
                        "🛡️ Atualização conservadora (recomendado)",
                        value=True,
                        help="Atualiza apenas status/datas/quantidades/valor/observações. Desmarque para atualizar todos os campos recebidos.",
                    )
                    pular_duplicados = st.checkbox("⛔ Pular se já existir (OC/SOL)", value=False)

                with col2:
                    criar_fornecedores = st.checkbox(
                        "Criar fornecedores automaticamente",
                        value=True,
                        help="Se marcado, fornecedores não encontrados serão criados automaticamente",
                    )

                with col3:
                    modo_simulacao = st.checkbox(
                        "🔎 Modo simulação",
                        value=False,
                        help="Valida e mostra o resumo sem inserir/atualizar registros.",
                    )

                with col4:
                    limpar_antes = st.checkbox(
                        "🗑️ Limpar banco antes da importação",
                        value=False,
                        help="⚠️ Remove todos os pedidos existentes ANTES de importar os novos dados.",
                        key="limpar_antes_upload"
                    )

                if limpar_antes:
                    st.error(
                        "🚨 **ATENÇÃO CRÍTICA:** Ao marcar esta opção, TODOS os pedidos existentes "
                        "serão **PERMANENTEMENTE DELETADOS** antes da importação dos novos dados. "
                        "Esta ação **NÃO PODE SER DESFEITA**!"
                    )
                    
                    # Adicionar confirmação extra
                    confirmar_delecao = st.text_input(
                        "Digite 'LIMPAR' para confirmar a exclusão de todos os dados:",
                        key="confirmar_delecao_upload"
                    )
                    
                    if confirmar_delecao != "LIMPAR":
                        st.warning("⚠️ Você precisa digitar 'LIMPAR' para habilitar a importação com limpeza prévia.")
                        # Desabilitar o botão de importação se não confirmou
                        if 'pode_importar_com_limpeza' in st.session_state:
                            del st.session_state['pode_importar_com_limpeza']
                    else:
                        st.session_state['pode_importar_com_limpeza'] = True

                if limpar_antes:
                    st.warning(
                        "⚠️ **ATENÇÃO:** Todos os pedidos existentes serão **deletados** antes da importação. "
                        "Esta ação não pode ser desfeita!"
                    )
                
                
                # ----------------------------
                # Validação + Prévia + Duplicidade
                # ----------------------------
                df_norm, df_erros = _validate_upload_df(df_upload)

                if not df_erros.empty:
                    st.error(f"❌ Foram encontrados {len(df_erros)} erros no arquivo.")
                    st.dataframe(df_erros, use_container_width=True, height=260)
                    _download_df(df_erros, "erros_validacao_importacao.csv")
                    st.stop()
                else:
                    st.success("✅ Validação OK (sem erros).")

                # Checagem de duplicidade por nr_oc (mesmo no modo 'Adicionar')
                duplicados_oc = 0
                existentes: set[str] = set()

                if "nr_oc" in df_norm.columns:
                    ocs = df_norm["nr_oc"].dropna().astype(str).str.strip()
                    ocs = [x for x in ocs.tolist() if x]
                    if ocs:
                        try:
                            q = _supabase.table("pedidos").select("nr_oc").in_("nr_oc", ocs)
                            _tid = st.session_state.get("tenant_id")
                            if _tid:
                                q = q.eq("tenant_id", str(_tid))
                            res = q.execute()
                            existentes = set([r["nr_oc"] for r in (res.data or []) if r.get("nr_oc")])
                            duplicados_oc = sum(1 for oc in ocs if oc in existentes)
                        except Exception:
                            existentes = set()
                            duplicados_oc = 0

                if duplicados_oc > 0:
                    st.warning(
                        f"⚠️ Encontradas **{duplicados_oc}** OCs do arquivo que já existem no banco. "
                        f"Se você importar como **Adicionar**, pode duplicar registros."
                    )

                # Pular duplicados (se marcado)
                if pular_duplicados and duplicados_oc > 0 and existentes and "nr_oc" in df_norm.columns:
                    df_norm = df_norm[~df_norm["nr_oc"].fillna("").astype(str).str.strip().isin(existentes)]

                # Pré-visualização do que vai acontecer
                insere_prev, atualiza_prev, pula_prev = _resolve_import_plan(_supabase, df_norm, tenant_id=st.session_state.get("tenant_id"))
                cprev1, cprev2, cprev3, cprev4 = st.columns(4)
                cprev1.metric("Registros válidos", len(df_norm))
                cprev2.metric("Previsão inserir", int(insere_prev))
                cprev3.metric("Previsão atualizar", int(atualiza_prev))
                cprev4.metric("Previsão pular", int(pula_prev))

                if modo_simulacao:
                    st.info("🔎 Modo simulação ativado: nada será gravado no banco.")
                    st.dataframe(df_norm.head(30), use_container_width=True, height=320)
                    st.stop()

                if limpar_antes:
                    pode_importar = st.session_state.get("pode_importar_com_limpeza", False)
                else:
                    pode_importar = True  # se não vai limpar, pode importar normalmente
                
                if st.button(
                    "🚀 Importar Dados",
                    type="primary",
                    use_container_width=True,
                    disabled=not pode_importar,
                ):
                    if limpar_antes and not pode_importar:
                        st.error("⚠️ Confirme a limpeza do banco digitando 'LIMPAR' antes de importar.")
                        st.stop()
                    
                    with st.spinner("Processando importação..."):

                        # Tenant atual (sempre definido antes do processamento)
                        tenant_id = st.session_state.get("tenant_id")

                        # Guardrails (server-side): aqui o insert roda com credenciais do backend,
                        # então precisamos enviar tenant_id explicitamente (triggers com auth.uid()
                        # podem vir NULL). Também impede o erro clássico de tenant_id = user_id.
                        if not tenant_id:
                            st.error(
                                "❌ tenant_id não definido na sessão. Faça login/seleciona a empresa novamente."
                            )
                            st.stop()
                        tenant_id = str(tenant_id)

                        uid = str((st.session_state.get("usuario") or {}).get("id") or "")
                        if uid and tenant_id == uid:
                            st.error(
                                "❌ ERRO DE CONFIGURAÇÃO: tenant_id está igual ao user_id. "
                                "Isso corrompe o multiempresa. Verifique onde você seta st.session_state['tenant_id']."
                            )
                            st.stop()

                        # ----------------------------
                        # Simulação (dry-run)
                        # ----------------------------
                        if modo_simulacao:
                            obrig = ["descricao", "qtde_solicitada", "departamento", "status"]
                            faltantes = [c for c in obrig if c not in df_upload.columns]
                            if faltantes:
                                st.error(f"❌ Colunas obrigatórias faltando: {', '.join(faltantes)}")
                                st.stop()

                            df_sim = df_upload.copy()
                            df_sim["qtde_solicitada"] = pd.to_numeric(df_sim.get("qtde_solicitada"), errors="coerce")

                            erros_sim: list[dict] = []
                            for i, r in df_sim.iterrows():
                                if pd.isna(r.get("descricao")) or str(r.get("descricao")).strip() == "":
                                    erros_sim.append({"linha": int(i) + 2, "erro": "Descrição vazia"})
                                if pd.isna(r.get("qtde_solicitada")) or float(r.get("qtde_solicitada") or 0) <= 0:
                                    erros_sim.append({"linha": int(i) + 2, "erro": "Quantidade inválida"})

                            st.info("🔎 Simulação concluída. Nenhum dado foi gravado.")
                            c1, c2 = st.columns(2)
                            c1.metric("Registros no arquivo", len(df_sim))
                            c2.metric("Erros de validação", len(erros_sim))

                            if erros_sim:
                                df_er = pd.DataFrame(erros_sim)
                                st.dataframe(df_er, use_container_width=True, height=260)
                                _download_df(df_er, "erros_validacao_importacao.csv")
                            else:
                                st.success("✅ Arquivo válido para importação.")
                            st.stop()

                        # Limpeza do banco
                        if limpar_antes:
                            try:
                                with st.spinner("🗑️ Limpando banco de dados..."):
                                    tenant_id = st.session_state.get("tenant_id")
                                    _supabase.table("pedidos").delete().eq("tenant_id", tenant_id).execute()
                                    res = _supabase.rpc("reset_tenant_data").execute()
                                    st.success(f"✅ Limpeza concluída: {res.data}")
                                    st.cache_data.clear()
                            except Exception as e_limpeza:
                                st.error(f"❌ Erro ao limpar banco: {e_limpeza}")
                                st.stop()

                        df_fornecedores = carregar_fornecedores(_supabase, st.session_state.get("tenant_id"))
                        mapa_fornecedores = {
                            int(f["cod_fornecedor"]): f["id"] for _, f in df_fornecedores.iterrows()
                            if pd.notna(f.get("cod_fornecedor"))
                        }

                        registros_processados = 0
                        registros_inseridos = 0
                        registros_atualizados = 0
                        registros_erro = 0
                        fornecedores_criados = 0
                        erros: list[str] = []
                        avisos: list[str] = []

                        total_rows = int(len(df_norm))
                        progress_bar = st.progress(0)
                        status_txt = st.empty()

                        
                        registros_pulados_dup = 0

                        # Prefetch para idempotência (OC > Solicitação)
                        oc_to_id: dict[str, str] = {}
                        sol_to_id_sem_oc: dict[str, str] = {}
                        sol_com_oc: set[str] = set()

                        # 1) OCs existentes no banco (para update/pulo)
                        if "nr_oc" in df_norm.columns:
                            ocs = df_norm["nr_oc"].dropna().astype(str).str.strip()
                            ocs = [x for x in ocs.tolist() if x]
                            if ocs:
                                try:
                                    res_oc = _supabase.table("pedidos").select("id,nr_oc").eq("tenant_id", tenant_id).in_("nr_oc", ocs).execute()
                                    for r in (res_oc.data or []):
                                        nr_oc_db = str(r.get("nr_oc") or "").strip()
                                        if nr_oc_db:
                                            oc_to_id[nr_oc_db] = str(r.get("id"))
                                except Exception:
                                    oc_to_id = {}

                        # 2) Solicitações existentes (somente para linhas sem OC)
                        if "nr_solicitacao" in df_norm.columns:
                            mask_sem_oc = df_norm.get("nr_oc", "").fillna("").astype(str).str.strip().eq("")
                            sols = df_norm.loc[mask_sem_oc, "nr_solicitacao"].dropna().astype(str).str.strip()
                            sols = [x for x in sols.tolist() if x]
                            if sols:
                                try:
                                    res_sol = _supabase.table("pedidos").select("id,nr_solicitacao,nr_oc").eq("tenant_id", tenant_id).in_("nr_solicitacao", sols).execute()
                                    for r in (res_sol.data or []):
                                        sol_db = str(r.get("nr_solicitacao") or "").strip()
                                        oc_db = str(r.get("nr_oc") or "").strip()
                                        if not sol_db:
                                            continue
                                        if oc_db:
                                            sol_com_oc.add(sol_db)
                                        else:
                                            sol_to_id_sem_oc[sol_db] = str(r.get("id"))
                                except Exception:
                                    sol_to_id_sem_oc = {}
                                    sol_com_oc = set()

                        for idx, row in df_norm.iterrows():
                            try:
                                # -------------------------------------------------
                                # Idempotência (evita duplicar / garante update)
                                # - Se tiver nr_oc e já existir: atualiza
                                # - Se NÃO tiver nr_oc e tiver nr_solicitacao:
                                #     * se solicitação já tem OC no banco: pula (não sobrescreve)
                                #     * se solicitação existir sem OC: atualiza
                                # -------------------------------------------------
                                pedido_id_existente = None

                                nr_oc_row = str(row.get("nr_oc") or "").strip()
                                nr_sol_row = str(row.get("nr_solicitacao") or "").strip()
                                # UPSERT unificado (OC > Solicitação)
                                # 1) Se OC existe no banco:
                                #    - se pular_duplicados => pula
                                #    - senão => atualiza por ID
                                # 2) Se não tem OC e tem Solicitação:
                                #    - se a solicitação já tem OC no banco => pula (evita sobrescrever)
                                #    - se existir sem OC => atualiza por ID
                                # 3) Caso contrário => insere
                                if nr_oc_row and nr_oc_row in oc_to_id:
                                    if pular_duplicados:
                                        avisos.append(f"Linha {idx + 2}: OC {nr_oc_row} já existe — pulado")
                                        registros_pulados_dup += 1
                                        registros_processados += 1
                                        if total_rows and (registros_processados % 10 == 0 or registros_processados == total_rows):
                                            progress_bar.progress(min(1.0, registros_processados / total_rows))
                                            status_txt.caption(f"Processando {registros_processados}/{total_rows}...")
                                        continue
                                    pedido_id_existente = oc_to_id[nr_oc_row]

                                elif (not nr_oc_row) and nr_sol_row:
                                    if nr_sol_row in sol_com_oc:
                                        avisos.append(
                                            f"Linha {idx + 2}: Solicitação {nr_sol_row} já possui OC no banco — ignorado para evitar sobrescrita"
                                        )
                                        registros_pulados_dup += 1
                                        registros_processados += 1
                                        if total_rows and (registros_processados % 10 == 0 or registros_processados == total_rows):
                                            progress_bar.progress(min(1.0, registros_processados / total_rows))
                                            status_txt.caption(f"Processando {registros_processados}/{total_rows}...")
                                        continue
                                    if nr_sol_row in sol_to_id_sem_oc:
                                        if pular_duplicados:
                                            avisos.append(f"Linha {idx + 2}: SOL {nr_sol_row} já existe — pulado")
                                            registros_pulados_dup += 1
                                            registros_processados += 1
                                            if total_rows and (registros_processados % 10 == 0 or registros_processados == total_rows):
                                                progress_bar.progress(min(1.0, registros_processados / total_rows))
                                                status_txt.caption(f"Processando {registros_processados}/{total_rows}...")
                                            continue
                                        pedido_id_existente = sol_to_id_sem_oc[nr_sol_row]

                                fornecedor_id = None

                                if "cod_fornecedor" in row and pd.notna(row["cod_fornecedor"]):
                                    cod_forn = int(row["cod_fornecedor"])

                                    if cod_forn not in mapa_fornecedores:
                                        if criar_fornecedores:
                                            try:
                                                busca_forn = (
                                                    _supabase.table("fornecedores")
                                                    .select("id")
                                                    .eq("tenant_id", tenant_id)
                                                    .eq("cod_fornecedor", cod_forn)
                                                    .execute()
                                                )
                                                if busca_forn.data and len(busca_forn.data) > 0:
                                                    fornecedor_id = busca_forn.data[0]["id"]
                                                    mapa_fornecedores[cod_forn] = fornecedor_id
                                                    avisos.append(
                                                        f"Linha {idx + 2}: Fornecedor {cod_forn} já existia (cache atualizado)"
                                                    )
                                                else:
                                                    novo_fornecedor = {
                                                        "cod_fornecedor": cod_forn,
                                                        "nome": str(row.get("nome_fornecedor", f"Fornecedor {cod_forn}")),
                                                        "cidade": str(row.get("cidade_fornecedor", "Não informado")),
                                                        "uf": str(row.get("uf_fornecedor", "SP"))[:2].upper(),
                                                        "ativo": True,
                                                    }
                                                    novo_fornecedor["tenant_id"] = tenant_id
                                                    resultado_forn = (
                                                        _supabase.table("fornecedores").insert(novo_fornecedor).execute()
                                                    )
                                                    if resultado_forn.data:
                                                        fornecedor_id = resultado_forn.data[0]["id"]
                                                        mapa_fornecedores[cod_forn] = fornecedor_id
                                                        fornecedores_criados += 1
                                                        avisos.append(
                                                            f"Linha {idx + 2}: Fornecedor {cod_forn} criado automaticamente"
                                                        )
                                            except Exception as e_forn:
                                                erro_str = str(e_forn)
                                                if "duplicate key" in erro_str or "23505" in erro_str:
                                                    busca_forn = (
                                                        _supabase.table("fornecedores")
                                                        .select("id")
                                                        .eq("tenant_id", tenant_id)
                                                        .eq("cod_fornecedor", cod_forn)
                                                        .execute()
                                                    )
                                                    if busca_forn.data and len(busca_forn.data) > 0:
                                                        fornecedor_id = busca_forn.data[0]["id"]
                                                        mapa_fornecedores[cod_forn] = fornecedor_id
                                                        avisos.append(
                                                            f"Linha {idx + 2}: Fornecedor {cod_forn} recuperado após conflito"
                                                        )
                                                    else:
                                                        raise ValueError(f"Erro ao criar fornecedor {cod_forn}: {erro_str}")
                                                else:
                                                    raise ValueError(f"Erro ao criar fornecedor {cod_forn}: {erro_str}")
                                        else:
                                            raise ValueError(
                                                f"Fornecedor {cod_forn} não encontrado. "
                                                "Ative 'Criar fornecedores automaticamente'."
                                            )
                                    else:
                                        fornecedor_id = mapa_fornecedores[cod_forn]

                                # validações obrigatórias
                                if not row.get("descricao") or pd.isna(row.get("descricao")):
                                    raise ValueError("Campo 'descricao' é obrigatório e não pode estar vazio")
                                if not row.get("qtde_solicitada") or pd.isna(row.get("qtde_solicitada")):
                                    raise ValueError("Campo 'qtde_solicitada' é obrigatório e não pode estar vazio")

                                pedido_data = {
                                    "nr_solicitacao": str(row["nr_solicitacao"]).strip()
                                    if pd.notna(row.get("nr_solicitacao")) and str(row.get("nr_solicitacao")).strip()
                                    else None,
                                    "nr_oc": str(row["nr_oc"]).strip()
                                    if pd.notna(row.get("nr_oc")) and str(row.get("nr_oc")).strip()
                                    else None,
                                    "departamento": str(row["departamento"]).strip()
                                    if pd.notna(row.get("departamento")) and str(row.get("departamento")).strip()
                                    else None,
                                    "cod_equipamento": str(row["cod_equipamento"]).strip()
                                    if pd.notna(row.get("cod_equipamento")) and str(row.get("cod_equipamento")).strip()
                                    else None,
                                    "cod_material": str(row["cod_material"]).strip()
                                    if pd.notna(row.get("cod_material")) and str(row.get("cod_material")).strip()
                                    else None,
                                    "descricao": str(row["descricao"]).strip(),
                                    "qtde_solicitada": float(row["qtde_solicitada"]),
                                    "qtde_entregue": float(row.get("qtde_entregue", 0) or 0),
                                    "data_solicitacao": pd.to_datetime(row["data_solicitacao"]).strftime("%Y-%m-%d")
                                    if pd.notna(row.get("data_solicitacao"))
                                    else None,
                                    "data_oc": pd.to_datetime(row["data_oc"]).strftime("%Y-%m-%d")
                                    if pd.notna(row.get("data_oc"))
                                    else None,
                                    "previsao_entrega": pd.to_datetime(row["previsao_entrega"]).strftime("%Y-%m-%d")
                                    if pd.notna(row.get("previsao_entrega"))
                                    else None,
                                    "status": str(row.get("status", "Sem OC")).strip(),
                                    "valor_total": float(row.get("valor_total", 0) or 0),
                                    "fornecedor_id": fornecedor_id,
                                }

                                # remove Nones (mas preserva campos numéricos)
                                pedido_data = {
                                    k: v
                                    for k, v in pedido_data.items()
                                    if v is not None or k in ["qtde_entregue", "valor_total"]
                                }


                                # Atualização conservadora: evita sobrescrever descrições/códigos
                                if pedido_id_existente and atualizacao_conservadora:
                                    allow = {
                                        "status",
                                        "data_solicitacao",
                                        "data_oc",
                                        "previsao_entrega",
                                        "data_entrega",
                                        "qtde_solicitada",
                                        "qtde_entregue",
                                        "valor_total",
                                        "fornecedor_id",
                                        "departamento",
                                    }
                                    pedido_data = {k: v for k, v in pedido_data.items() if k in allow or k in ("nr_oc", "nr_solicitacao")}

                                # -------------------------------------------------
                                # APPLY: update (por id) ou insert
                                # -------------------------------------------------
                                if pedido_id_existente:
                                    # Atualiza por ID (mais seguro e rápido)
                                    _supabase.table("pedidos").update(pedido_data).eq("id", pedido_id_existente).eq("tenant_id", tenant_id).execute()
                                    registros_atualizados += 1
                                else:
                                    pedido_data["tenant_id"] = tenant_id
                                    _supabase.table("pedidos").insert(pedido_data).execute()
                                    registros_inseridos += 1

                                registros_processados += 1
                                if total_rows and (registros_processados % 10 == 0 or registros_processados == total_rows):
                                    progress_bar.progress(min(1.0, registros_processados / total_rows))
                                    status_txt.caption(f"Processando {registros_processados}/{total_rows}...")

                            except Exception as e:
                                registros_erro += 1
                                erros.append(f"Linha {idx + 2}: {str(e)}")

                        st.cache_data.clear()

                        # Limpa arquivo do uploader após importar
                        st.session_state["upload_massa_key"] += 1

                        if registros_erro == 0:
                            st.success(
                                f"""
✅ **Importação Concluída com Sucesso!**
- ✅ Processados: {registros_processados}
- ➕ Inseridos: {registros_inseridos}
- 🔄 Atualizados: {registros_atualizados}
- 🏭 Fornecedores criados: {fornecedores_criados}
- ⛔ Duplicados (OC) pulados: {registros_pulados_dup}
"""
                            )
                        else:
                            st.warning(
                                f"""
⚠️ **Importação Concluída com Erros**
- ✅ Processados: {registros_processados}
- ➕ Inseridos: {registros_inseridos}
- 🔄 Atualizados: {registros_atualizados}
- 🏭 Fornecedores criados: {fornecedores_criados}
- ⛔ Duplicados (OC) pulados: {registros_pulados_dup}
- ❌ Erros: {registros_erro}
"""
                            )

                        if avisos:
                            with st.expander(f"ℹ️ Ver avisos ({len(avisos)})"):
                                for aviso in avisos[:50]:
                                    st.info(aviso)

                        if erros:
                            with st.expander(f"⚠️ Ver erros ({len(erros)})"):
                                for erro in erros[:50]:
                                    st.error(erro)
                                if len(erros) > 50:
                                    st.warning(f"... e mais {len(erros) - 50} erros não exibidos")

                        try:
                            _supabase.table("log_importacoes").insert(
                                {
                                    "usuario_id": st.session_state.usuario["id"],
                                    "nome_arquivo": arquivo_upload.name,
                                    "registros_processados": registros_processados,
                                    "registros_inseridos": registros_inseridos,
                                    "registros_atualizados": registros_atualizados,
                                    "registros_erro": registros_erro,
                                    "detalhes_erro": "\n".join(erros[:100]) if erros else None,
                                }
                            ).execute()
                        except Exception:
                            pass

            except Exception as e:
                st.error(f"❌ Erro ao processar arquivo: {e}")
                st.info("💡 Verifique se o arquivo está no formato correto e contém todas as colunas necessárias")

    # ============================================
    # TAB 3: EDITAR PEDIDO
    # ============================================
    with tab3:
        st.subheader("Editar Pedido Existente")

        df_pedidos = carregar_pedidos(_supabase, st.session_state.get("tenant_id"))
        # Ponte vinda da Consulta: pré-seleciona pedido para edição
        pedido_pre = st.session_state.pop("gp_open_pedido_id", None)
        if pedido_pre and not df_pedidos.empty and "id" in df_pedidos.columns:
            try:
                alvo = df_pedidos[df_pedidos["id"].astype(str) == str(pedido_pre)]
                if not alvo.empty:
                    st.session_state["edit_busca"] = str(alvo.iloc[0].get("nr_oc") or alvo.iloc[0].get("nr_solicitacao") or "")
            except Exception:
                pass

        if df_pedidos.empty:
            st.info("📭 Nenhum pedido cadastrado ainda")
            return

        # Filtros rápidos para localizar pedido
        with st.form("filtro_edicao"):
            colf1, colf2, colf3 = st.columns([2, 1, 1])
            with colf1:
                busca_txt = st.text_input(
                    "Buscar (OC, descrição, depto)",
                    value=st.session_state.get("edit_busca", ""),
                )
            with colf2:
                status_f = st.selectbox(
                    "Status",
                    ["Todos", "Sem OC", "Tem OC", "Em Transporte", "Entregue"],
                    index=0,
                )
            with colf3:
                limite = st.selectbox("Itens", [100, 200, 500], index=1)
            aplicar_busca = st.form_submit_button("Aplicar")

        if aplicar_busca:
            st.session_state["edit_busca"] = busca_txt

        df_lista = df_pedidos.copy()

        if status_f != "Todos" and "status" in df_lista.columns:
            df_lista = df_lista[df_lista["status"] == status_f]

        q = str(st.session_state.get("edit_busca", "")).strip().lower()
        if q:
            cols = []
            for c in ["nr_oc", "descricao", "departamento", "nr_solicitacao"]:
                if c in df_lista.columns:
                    cols.append(df_lista[c].fillna("").astype(str).str.lower())
            if cols:
                mask = cols[0].str.contains(q, na=False)
                for s in cols[1:]:
                    mask = mask | s.str.contains(q, na=False)
                df_lista = df_lista[mask]

        df_lista = df_lista.head(int(limite))
        labels, ids = _build_pedido_labels(_make_df_stamp(df_lista), df_lista)

        if not ids:
            st.warning("Nenhum pedido encontrado com os filtros atuais.")
            return

        idx_escolhido = st.selectbox(
            "Selecione o pedido para editar",
            options=list(range(len(ids))),
            format_func=lambda i: labels[i] if i < len(labels) else "",
        )
        pedido_editar = ids[idx_escolhido]

        pedido_atual = df_pedidos[df_pedidos["id"].astype(str) == str(pedido_editar)].iloc[0]

        st.markdown("---")

        with st.form("form_editar_pedido"):
            col1, col2 = st.columns(2)

            with col1:
                st.text_input("N° Solicitação", value=pedido_atual.get("nr_solicitacao") or "", key="edit_nr_sol")
                st.text_input("N° OC", value=pedido_atual.get("nr_oc") or "", key="edit_nr_oc")
                st.text_input("Departamento", value=pedido_atual.get("departamento") or "", key="edit_dept")
                st.text_area("Descrição", value=pedido_atual.get("descricao") or "", key="edit_desc")

            with col2:
                st.number_input("Qtd. Solicitada", value=float(pedido_atual.get("qtde_solicitada") or 0), key="edit_qtd_sol")
                st.number_input("Qtd. Entregue", value=float(pedido_atual.get("qtde_entregue") or 0), key="edit_qtd_ent")
                status_opts = ["Sem OC", "Tem OC", "Em Transporte", "Entregue"]
                st.selectbox(
                    "Status",
                    status_opts,
                    index=status_opts.index(pedido_atual.get("status")) if pedido_atual.get("status") in status_opts else 0,
                    key="edit_status",
                )
                st.number_input("Valor Total", value=float(pedido_atual.get("valor_total") or 0), key="edit_valor")

            submitted_edit = st.form_submit_button("💾 Salvar Alterações", use_container_width=True)

        if submitted_edit:
            pedido_atualizado = {
                "id": pedido_editar,
                "nr_solicitacao": st.session_state.edit_nr_sol or None,
                "nr_oc": st.session_state.edit_nr_oc or None,
                "departamento": st.session_state.edit_dept,
                "descricao": st.session_state.edit_desc,
                "qtde_solicitada": st.session_state.edit_qtd_sol,
                "qtde_entregue": st.session_state.edit_qtd_ent,
                "status": st.session_state.edit_status,
                "valor_total": st.session_state.edit_valor,
            }

            sucesso, mensagem = salvar_pedido(pedido_atualizado, _supabase)
            if sucesso:
                st.success(mensagem)
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(mensagem)

        # Ações perigosas
        with st.expander("⚠️ Ações avançadas", expanded=False):
            st.caption("Use com cuidado. Essas ações são registradas na auditoria (se habilitada).")
            colx1, colx2 = st.columns(2)
            with colx1:
                confirmar_exclusao = st.checkbox("Confirmo que quero excluir este pedido", value=False)
            with colx2:
                if st.button(
                    "🗑️ Excluir Pedido",
                    type="secondary",
                    use_container_width=True,
                    disabled=not confirmar_exclusao,
                ):
                    try:
                        _supabase.table("pedidos").delete().eq("id", pedido_editar).execute()
                        try:
                            ba.registrar_acao(
                                _supabase,
                                st.session_state.usuario.get("email"),
                                "excluir_pedido",
                                {"id": pedido_editar},
                            )
                        except Exception:
                            pass
                        st.success("✅ Pedido excluído.")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e_del:
                        st.error(f"❌ Erro ao excluir: {e_del}")

        # Registrar entrega
        st.markdown("---")
        st.subheader("📦 Registrar Entrega")

        qtde_pendente = float(pedido_atual.get("qtde_pendente") or 0)

        if qtde_pendente > 0:
            c1, c2 = st.columns(2)
            with c1:
                qtde_entrega = st.number_input(
                    f"Quantidade entregue (Pendente: {qtde_pendente})",
                    min_value=0.0,
                    max_value=float(qtde_pendente),
                    step=1.0,
                )
                data_entrega = st.date_input("Data da entrega", value=datetime.now())
            with c2:
                obs_entrega = st.text_area("Observações da entrega")

            if st.button("✅ Registrar Entrega", type="primary"):
                if qtde_entrega > 0:
                    sucesso, mensagem = registrar_entrega(
                        pedido_editar,
                        qtde_entrega,
                        data_entrega.isoformat(),
                        obs_entrega,
                        _supabase=_supabase,
                    )
                    if sucesso:
                        st.success(mensagem)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(mensagem)
                else:
                    st.warning("⚠️ Informe a quantidade entregue")
        else:
            st.success("✅ Pedido totalmente entregue!")

    with tab4:
        st.subheader("⚡ Ações em Massa")
        st.caption("Atualize vários pedidos de uma vez (status / previsão / fornecedor). Use filtros para selecionar o conjunto.")
    
        df_pedidos = carregar_pedidos(_supabase, st.session_state.get("tenant_id"))
        if df_pedidos.empty:
            st.info("📭 Nenhum pedido cadastrado.")
            return
    
        # Filtros e seleção (form para evitar rerun a cada clique)
        with st.form("form_mass_actions"):
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                depto = st.selectbox("Departamento", ["Todos"] + DEPARTAMENTOS_VALIDOS, index=0)
            with f2:
                status_atual = st.selectbox("Status atual", ["Todos"] + STATUS_VALIDOS, index=0)
            with f3:
                fornecedor_txt = st.text_input("Fornecedor contém (opcional)", value="")
            with f4:
                busca = st.text_input("Buscar (OC/descrição)", value="")
    
            lim = st.selectbox("Limite de seleção", [200, 500, 1000, 2000], index=1)
    
            aplicar = st.form_submit_button("Aplicar filtros")
    
        # aplica filtros
        df_sel = df_pedidos.copy()
    
        if depto != "Todos" and "departamento" in df_sel.columns:
            df_sel = df_sel[df_sel["departamento"] == depto]
    
        if status_atual != "Todos" and "status" in df_sel.columns:
            df_sel = df_sel[df_sel["status"] == status_atual]
    
        if fornecedor_txt.strip() and "fornecedor" in df_sel.columns:
            qf = fornecedor_txt.strip().lower()
            df_sel = df_sel[df_sel["fornecedor"].fillna("").astype(str).str.lower().str.contains(qf, na=False)]
    
        if busca.strip():
            qb = busca.strip().lower()
            cols = []
            for c in ["nr_oc", "descricao", "nr_solicitacao"]:
                if c in df_sel.columns:
                    cols.append(df_sel[c].fillna("").astype(str).str.lower())
            if cols:
                m = cols[0].str.contains(qb, na=False)
                for s in cols[1:]:
                    m = m | s.str.contains(qb, na=False)
                df_sel = df_sel[m]
    
        df_sel = df_sel.head(int(lim))
    
        st.write(f"🔎 Selecionados (após filtros): **{len(df_sel)}**")
    
        if df_sel.empty:
            st.warning("Nenhum pedido encontrado com os filtros.")
            return
    
        # multiselect por ID (mais leve)
        labels, ids = _build_pedido_labels(_make_df_stamp(df_sel), df_sel)
        id_to_label = dict(zip(ids, labels))  # evita ids.index() (O(n²))
        selecionados = st.multiselect(
            "Escolha os pedidos para aplicar a ação",
            options=ids,
            default=[],
            format_func=lambda pid: id_to_label.get(pid, pid),
        )
    
        if not selecionados:
            st.info("Selecione pelo menos 1 pedido.")
            return
    
        st.markdown("---")
        st.subheader("Ações")
    
        a1, a2, a3 = st.columns(3)
    
        # 1) Status em massa
        with a1:
            st.markdown("### 🏷️ Status")
            novo_status = st.selectbox("Novo status", STATUS_VALIDOS, index=0, key="mass_status")
            if st.button("Aplicar status", use_container_width=True):
                ok, errs = _bulk_update(_supabase, selecionados, {"status": novo_status})
                if errs:
                    st.warning(f"Atualizados: {ok}/{len(selecionados)}")
                    st.text("\n".join(errs[:30]))
                else:
                    st.success(f"✅ Status atualizado em {ok} pedidos.")
                try:
                    ba.registrar_acao(_supabase, st.session_state.usuario.get("email"), "mass_update_status",
                                      {"qtd": len(selecionados), "status": novo_status})
                except Exception:
                    pass
                st.cache_data.clear()
                st.rerun()
    
        # 2) Previsão em massa
        with a2:
            st.markdown("### 📅 Previsão")
            nova_prev = st.date_input("Nova previsão", value=datetime.now(), key="mass_prev")
            if st.button("Aplicar previsão", use_container_width=True):
                payload = {"previsao_entrega": nova_prev.isoformat()}
                ok, errs = _bulk_update(_supabase, selecionados, payload)
                if errs:
                    st.warning(f"Atualizados: {ok}/{len(selecionados)}")
                    st.text("\n".join(errs[:30]))
                else:
                    st.success(f"✅ Previsão atualizada em {ok} pedidos.")
                try:
                    ba.registrar_acao(_supabase, st.session_state.usuario.get("email"), "mass_update_previsao",
                                      {"qtd": len(selecionados), "previsao": nova_prev.isoformat()})
                except Exception:
                    pass
                st.cache_data.clear()
                st.rerun()
    
        # 3) Fornecedor em massa
        with a3:
            st.markdown("### 🏭 Fornecedor")
            df_fornecedores = carregar_fornecedores(_supabase, st.session_state.get("tenant_id"))
            if df_fornecedores is None or df_fornecedores.empty:
                st.warning("Sem fornecedores cadastrados.")
            else:
                stamp_f = _make_df_stamp(df_fornecedores, "updated_at" if "updated_at" in df_fornecedores.columns else "id")
                forn_opts, mapa = _build_fornecedor_options(stamp_f, df_fornecedores)
    
                forn_sel = st.selectbox("Fornecedor", forn_opts, index=0, key="mass_forn")
                if st.button("Aplicar fornecedor", use_container_width=True, disabled=(not forn_sel)):
                    try:
                        cod = int(str(forn_sel).split(" - ")[0])
                        forn_id = mapa.get(cod)
                        if not forn_id:
                            st.error("Fornecedor não encontrado no mapa.")
                        else:
                            ok, errs = _bulk_update(_supabase, selecionados, {"fornecedor_id": forn_id})
                            if errs:
                                st.warning(f"Atualizados: {ok}/{len(selecionados)}")
                                st.text("\n".join(errs[:30]))
                            else:
                                st.success(f"✅ Fornecedor atualizado em {ok} pedidos.")
                            try:
                                ba.registrar_acao(_supabase, st.session_state.usuario.get("email"), "mass_update_fornecedor",
                                                  {"qtd": len(selecionados), "cod_fornecedor": cod})
                            except Exception:
                                pass
                            st.cache_data.clear()
                            st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao aplicar fornecedor: {e}")
