import io
from datetime import datetime, time, timedelta, timezone

import pandas as pd
import streamlit as st



def _split_text(texto: str, max_chars: int = 3500) -> list[str]:
    """Divide um texto grande em partes <= max_chars, tentando quebrar por linhas."""
    if not texto:
        return [""]
    if len(texto) <= max_chars:
        return [texto]

    linhas = texto.splitlines()
    partes: list[str] = []
    atual: list[str] = []
    tamanho = 0

    for ln in linhas:
        add = len(ln) + (1 if atual else 0)
        if tamanho + add > max_chars and atual:
            partes.append("\n".join(atual))
            atual = [ln]
            tamanho = len(ln)
        else:
            tamanho += add
            atual.append(ln)

    if atual:
        partes.append("\n".join(atual))

    partes_fix: list[str] = []
    for p in partes:
        if len(p) <= max_chars:
            partes_fix.append(p)
        else:
            for i in range(0, len(p), max_chars):
                partes_fix.append(p[i:i+max_chars])
    return partes_fix


def _make_preview_df(df: pd.DataFrame) -> pd.DataFrame:
    """Monta um dataframe de prévia com colunas mais relevantes (tolerante ao schema)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["item", "descrição", "qtde entregue", "cód. equipamento", "cód. material", "departamento"])

    def pick(cands):
        for c in cands:
            if c in df.columns:
                return c
        return None

    col_desc = pick(["descricao", "descrição", "item_descricao", "material_descricao"])
    col_qtd = pick(["qtde_entregue", "quantidade_entregue", "qtd_entregue", "quantidade", "qtde"])
    col_equip = pick(["cod_equipamento", "codigo_equipamento", "equipamento", "equipamento_codigo"])
    col_mat = pick(["cod_material", "codigo_material", "material", "material_codigo", "cod_item"])
    col_dep = pick(["departamento"])

    cols = [c for c in [col_desc, col_qtd, col_equip, col_mat, col_dep] if c]
    prev = df[cols].copy() if cols else df.copy()

    prev.insert(0, "item", range(1, len(prev) + 1))

    rename_map = {}
    if col_desc: rename_map[col_desc] = "descrição"
    if col_qtd: rename_map[col_qtd] = "qtde entregue"
    if col_equip: rename_map[col_equip] = "cód. equipamento"
    if col_mat: rename_map[col_mat] = "cód. material"
    if col_dep: rename_map[col_dep] = "departamento"
    prev = prev.rename(columns=rename_map)

    ordem = ["item", "descrição", "qtde entregue", "cód. equipamento", "cód. material", "departamento"]
    return prev[[c for c in ordem if c in prev.columns]]

def _dt_range_utc(d_ini, d_fim):
    """Converte date -> UTC range [ini, fim+1d)."""
    dt_ini = datetime.combine(d_ini, time.min).replace(tzinfo=timezone.utc)
    dt_fim = datetime.combine(d_fim, time.min).replace(tzinfo=timezone.utc) + timedelta(days=1)
    return dt_ini, dt_fim


def _load_jobs_for_period(supabase, tenant_id: str, dt_ini_iso: str, dt_fim_iso: str, report_type: str = "materiais_entregues"):
    """
    Carrega jobs do report_jobs para um período (dt_ini/dt_fim).
    Tolerante ao schema: tenta trazer colunas extras como 'attempt' se existirem.
    """
    cols_base = "id, to_user_id, status, created_at, dt_ini, dt_fim"
    cols_attempt = cols_base + ", attempt"
    # Tentamos com attempt; se falhar, caímos no básico.
    try:
        res = (
            supabase.table("report_jobs")
            .select(cols_attempt)
            .eq("tenant_id", tenant_id)
            .eq("channel", "whatsapp")
            .eq("report_type", report_type)
            .eq("dt_ini", dt_ini_iso)
            .eq("dt_fim", dt_fim_iso)
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        rows = res.data or []
    except Exception:
        res = (
            supabase.table("report_jobs")
            .select(cols_base)
            .eq("tenant_id", tenant_id)
            .eq("channel", "whatsapp")
            .eq("report_type", report_type)
            .eq("dt_ini", dt_ini_iso)
            .eq("dt_fim", dt_fim_iso)
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        rows = res.data or []
    return pd.DataFrame(rows)


def _latest_status_por_destinatario(df_jobs: pd.DataFrame) -> pd.DataFrame:
    """
    Para cada to_user_id, pega o job mais recente (por created_at) e retorna status/attempt.
    """
    if df_jobs is None or df_jobs.empty:
        return pd.DataFrame(columns=["to_user_id", "status", "created_at", "attempt"])
    df = df_jobs.copy()
    if "created_at" in df.columns:
        df["_created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
        df = df.sort_values("_created_at", ascending=False, kind="mergesort")
    else:
        df["_created_at"] = pd.NaT
    cols = ["to_user_id", "status", "created_at"]
    if "attempt" in df.columns:
        cols.append("attempt")
    out = df.groupby("to_user_id", as_index=False).first()
    return out[cols]


def _count_queue_metrics(supabase, tenant_id: str):
    """
    Contador simples (compatível) para jobs WhatsApp do tenant.
    """
    try:
        rows = (
            supabase.table("report_jobs")
            .select("status")
            .eq("tenant_id", tenant_id)
            .eq("channel", "whatsapp")
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
            .data
            or []
        )
    except Exception:
        return {"queued": 0, "processing": 0, "sent": 0, "failed": 0, "total": 0}

    status_list = [(r.get("status") or "").lower().strip() for r in rows]
    def c(*names):
        return sum(1 for s in status_list if s in names)

    return {
        "queued": c("queued"),
        "processing": c("processing", "sending", "in_progress"),
        "sent": c("sent", "delivered", "done", "success"),
        "failed": c("failed", "error"),
        "total": len(status_list),
    }


def _insert_report_job_safe(supabase, payload: dict):
    """
    Insere em report_jobs com tolerância a colunas opcionais.
    """
    # tenta direto
    try:
        return supabase.table("report_jobs").insert(payload).execute()
    except Exception:
        # remove chaves possivelmente inexistentes e tenta de novo
        slim = payload.copy()
        for k in ["attempt", "metadata", "origin_log_id", "retry_of_job_id"]:
            slim.pop(k, None)
        return supabase.table("report_jobs").insert(slim).execute()

def _load_gestores(supabase, tenant_id: str, roles=None):
    """
    Destinatários = membros do tenant (todas as roles por padrão).
    Para evitar problemas com RLS (usuário vendo só a si mesmo), usa RPC SECURITY DEFINER.
    Requer criar a função no Supabase: public.rpc_tenant_members(p_tenant_id uuid).
    """
    roles = roles  # None => todas as roles

    res = supabase.rpc("rpc_tenant_members", {"p_tenant_id": tenant_id}).execute()
    rows = res.data or []

    if roles:
        roles_set = set(roles)
        rows = [r for r in rows if (r.get("role") in roles_set)]

    rows.sort(key=lambda x: (x.get("nome") or x.get("email") or ""))
    return rows


def _load_departamentos_from_pedidos(supabase, tenant_id: str):
    """
    Lê departamentos existentes a partir de pedidos (coluna: departamento).
    Mantém simples para o MVP. Se sua base for grande, dá para trocar por RPC/view.
    """
    res = (
        supabase.table("pedidos")
        .select("*")
        .eq("tenant_id", tenant_id)
        .limit(5000)
        .execute()
    )
    rows = res.data or []
    deps = sorted(
        {
            (r.get("departamento") or "").strip()
            for r in rows
            if (r.get("departamento") or "").strip()
        }
    )
    return deps


def _load_links(supabase, tenant_id: str):
    return (
        supabase.table("gestor_departamentos")
        .select("id, departamento, gestor_user_id")
        .eq("tenant_id", tenant_id)
        .order("departamento")
        .execute()
        .data
        or []
    )


def _upsert_link(supabase, tenant_id: str, departamento: str, gestor_user_id: str):
    # requer unique(tenant_id, departamento) OU on_conflict correspondente
    return (
        supabase.table("gestor_departamentos")
        .upsert(
            {
                "tenant_id": tenant_id,
                "departamento": departamento,
                "gestor_user_id": gestor_user_id,
            },
            on_conflict="tenant_id,departamento",
        )
        .execute()
    )


def _delete_link(supabase, link_id: str):
    return supabase.table("gestor_departamentos").delete().eq("id", link_id).execute()


def _resolve_gestores_for_departamentos(links, departamentos_sel):
    mapa = {l.get("departamento"): l.get("gestor_user_id") for l in (links or [])}
    return {dep: mapa.get(dep) for dep in (departamentos_sel or [])}


def _load_entregues(supabase, tenant_id: str, dt_ini, dt_fim, departamentos=None) -> pd.DataFrame:
    """
    Carrega pedidos entregues por período.

    Observação:
    - Se o PostgREST estiver falhando nos filtros de datetime (APIError), evitamos filtrar no servidor por 'atualizado_em'
      e filtramos no pandas. Isso mantém o app funcional sem depender do tipo exato da coluna (timestamp/timestamptz/text).
    - Para evitar carregar demais, aplicamos limit e ordenação.
    """
    # Base query sem filtro de datetime (mais compatível)
    q = (
        supabase.table("pedidos")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("entregue", True)
        .order("atualizado_em", desc=True)
        .limit(5000)
    )
    if departamentos:
        q = q.in_("departamento", departamentos)

    res = q.execute()
    df = pd.DataFrame(res.data or [])

    if df.empty or "atualizado_em" not in df.columns:
        return df

    # Converte atualizado_em para datetime (tolerante a formatos)
    dt_col = pd.to_datetime(df["atualizado_em"], errors="coerce", utc=True)
    # dt_ini/dt_fim podem vir com tz; normalizamos para UTC e tratamos fim exclusivo
    try:
        dt_ini_u = pd.to_datetime(dt_ini, utc=True)
    except Exception:
        dt_ini_u = pd.to_datetime(str(dt_ini), errors="coerce", utc=True)
    try:
        dt_fim_u = pd.to_datetime(dt_fim, utc=True)
    except Exception:
        dt_fim_u = pd.to_datetime(str(dt_fim), errors="coerce", utc=True)

    mask = (dt_col >= dt_ini_u) & (dt_col < dt_fim_u)
    df = df.loc[mask].copy()
    return df


def _build_message(d_ini, d_fim, df: pd.DataFrame, departamentos_sel) -> str:
    """Monta mensagem agrupada por departamento, ordenada por equipamento (sem valores e sem emojis)."""
    deps_sel = departamentos_sel  # compatibilidade

    if df is None or df.empty:
        return f"Relatório de Entregas\nPeríodo: {d_ini} a {d_fim}\n\nNenhum item entregue no período."

    def pick(cands):
        for c in cands:
            if c in df.columns:
                return c
        return None

    col_desc = pick(["descricao", "descrição"])
    col_qtd = pick(["qtde_entregue", "quantidade_entregue", "qtde", "quantidade"])
    col_equip = pick(["cod_equipamento", "equipamento", "codigo_equipamento"])
    col_mat = pick(["cod_material", "material", "codigo_material"])
    col_dep = pick(["departamento"])

    # ordenar por equipamento se existir
    if col_equip:
        try:
            df = df.sort_values(by=col_equip, kind="mergesort")
        except Exception:
            pass

    total_geral = int(len(df))

    cabecalho = (
        "Relatório de Entregas\n"
        f"Período: {d_ini} a {d_fim}\n"
        f"Departamentos: {', '.join(deps_sel) if deps_sel else 'Todos'}\n"
        f"Total geral de itens: {total_geral}\n\n"
    )

    linhas: list[str] = []

    if col_dep:
        for dep, grupo in df.groupby(col_dep, sort=False):
            linhas.append(f"Departamento: {dep}")
            linhas.append(f"Total no departamento: {int(len(grupo))}")
            for i, (_, row) in enumerate(grupo.iterrows(), start=1):
                partes = []
                if col_desc:
                    partes.append(str(row.get(col_desc, "")))
                if col_qtd:
                    partes.append(f"Qtd: {row.get(col_qtd, '')}")
                if col_equip:
                    partes.append(f"Eqp: {row.get(col_equip, '')}")
                if col_mat:
                    partes.append(f"Mat: {row.get(col_mat, '')}")
                linhas.append(f"  {i}. " + " | ".join(partes))
            linhas.append("")
    else:
        for i, (_, row) in enumerate(df.iterrows(), start=1):
            partes = []
            if col_desc:
                partes.append(str(row.get(col_desc, "")))
            if col_qtd:
                partes.append(f"Qtd: {row.get(col_qtd, '')}")
            if col_equip:
                partes.append(f"Eqp: {row.get(col_equip, '')}")
            if col_mat:
                partes.append(f"Mat: {row.get(col_mat, '')}")
            linhas.append(f"{i}. " + " | ".join(partes))

    return cabecalho + "\n".join(linhas)

def render_relatorios_whatsapp(supabase, tenant_id: str, created_by: str):
    """
    Tela única com 2 abas:
    - Enviar relatório (sob demanda): gera preview + enfileira jobs + salva CSV no storage
    - Vincular gestores: mapeia departamento -> gestor
    Pré-requisitos:
      - tabela gestor_departamentos
      - tabela report_jobs e report_artifacts
      - bucket storage 'reports' (privado)
    """
    st.header("📲 Relatórios (WhatsApp)")

    tab_send, tab_link = st.tabs(["Enviar relatório", "Vincular gestores"])

    roles_destino = None  # None = todas as roles do tenant

    gestores = _load_gestores(supabase, tenant_id, roles=roles_destino)
    gestores_by_id = {g["user_id"]: g for g in gestores}
    labels_g = {
        g["user_id"]: f'{g.get("nome") or "Sem nome"} — {g.get("email") or ""}'
        for g in gestores
    }

    with tab_link:
        st.subheader("Vincular gestor por departamento")
        deps = _load_departamentos_from_pedidos(supabase, tenant_id)

        if not deps:
            st.info("Não encontrei departamentos em pedidos (coluna 'departamento').")
            st.caption("Cadastre ao menos um pedido com departamento preenchido para habilitar os vínculos.")
        elif not gestores:
            st.warning(
                "Nenhum destinatário encontrado para este tenant. "
                "Não encontrei nenhum usuário retornado pela RPC rpc_tenant_members para este tenant."
            )
            st.caption("Se seu sistema usa outro nome de role (ex.: 'manager'), ajuste roles_destino no código.")
        else:

            c1, c2 = st.columns([1.2, 1])
            with c1:
                dep = st.selectbox("Departamento", options=deps, key="rep_link_dep")
            with c2:
                gestor_id = st.selectbox(
                    "Gestor",
                    options=list(labels_g.keys()),
                    format_func=lambda uid: labels_g.get(uid, uid),
                    key="rep_link_gestor",
                )

            if st.button("Salvar vínculo", type="primary", use_container_width=True, key="rep_link_save"):
                _upsert_link(supabase, tenant_id, dep, gestor_id)
                st.success("Vínculo salvo.")
                st.rerun()

            st.divider()
            links = _load_links(supabase, tenant_id)

            if links:
                rows = []
                for l in links:
                    g = gestores_by_id.get(l["gestor_user_id"], {})
                    rows.append(
                        {
                            "departamento": l["departamento"],
                            "gestor": g.get("nome") or g.get("email") or l["gestor_user_id"],
                            "id": l["id"],
                        }
                    )
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

                rm_id = st.selectbox(
                    "Remover vínculo",
                    options=[r["id"] for r in rows],
                    format_func=lambda x: next((r["departamento"] for r in rows if r["id"] == x), x),
                    key="rep_link_rm",
                )
                if st.button("Remover", use_container_width=True, key="rep_link_rm_btn"):
                    _delete_link(supabase, rm_id)
                    st.success("Removido.")
                    st.rerun()
            else:
                st.caption("Nenhum vínculo cadastrado ainda.")
    with tab_send:
        st.subheader("Enviar relatório de entregues (sob demanda)")

        st.caption("Destinatários: todos os usuários do tenant (todas as roles).")

        # Períodos rápidos (padrão: últimos 7 dias)
        periodo = st.radio(
            "Período",
            options=["Últimos 7 dias", "Hoje", "Mês atual", "Personalizado"],
            horizontal=True,
            key="rep_periodo",
        )

        hoje = datetime.now().date()
        if periodo == "Últimos 7 dias":
            st.session_state["rep_dt_ini"] = hoje - timedelta(days=7)
            st.session_state["rep_dt_fim"] = hoje
        elif periodo == "Hoje":
            st.session_state["rep_dt_ini"] = hoje
            st.session_state["rep_dt_fim"] = hoje
        elif periodo == "Mês atual":
            st.session_state["rep_dt_ini"] = hoje.replace(day=1)
            st.session_state["rep_dt_fim"] = hoje

        c_dt1, c_dt2 = st.columns(2)
        with c_dt1:
            d_ini = st.date_input(
                "Data inicial",
                value=st.session_state.get("rep_dt_ini", hoje - timedelta(days=7)),
                key="rep_dt_ini",
            )
        with c_dt2:
            d_fim = st.date_input(
                "Data final",
                value=st.session_state.get("rep_dt_fim", hoje),
                key="rep_dt_fim",
            )

        if periodo != "Personalizado":
            st.caption("Dica: selecione 'Personalizado' para editar as datas livremente.")

        dt_ini, dt_fim = _dt_range_utc(d_ini, d_fim)

        deps = _load_departamentos_from_pedidos(supabase, tenant_id)
        deps_sel = st.multiselect(
            "Departamentos",
            options=deps,
            default=deps[:3] if len(deps) >= 3 else deps,
            key="rep_deps_sel",
        )

        links = _load_links(supabase, tenant_id)
        mapa = _resolve_gestores_for_departamentos(links, deps_sel)

        faltando = [d for d, g in mapa.items() if not g]
        if faltando:
            st.warning("Sem gestor vinculado: " + ", ".join(faltando))

        with st.spinner("Gerando prévia..."):


            # Prévia atualiza automaticamente quando você muda os filtros
            df = _load_entregues(supabase, tenant_id, dt_ini, dt_fim, deps_sel)
            texto = _build_message(d_ini, d_fim, df, deps_sel)


            # Prévia (tabela 1:1 com o texto)

            st.markdown("### Prévia")

            df_prev = _make_preview_df(df)

            st.dataframe(df_prev, use_container_width=True, hide_index=True)


            # Texto final (WhatsApp) + divisão automática se ficar grande

            st.markdown("### Texto (WhatsApp)")

            partes = _split_text(texto, max_chars=3500)


            if len(partes) == 1:

                st.text_area("Mensagem", value=partes[0], height=260, key="rep_texto_full")

            else:

                st.info(f"O texto ficou grande e foi dividido em {len(partes)} mensagens.")

                for i, p in enumerate(partes, start=1):

                    st.text_area(f"Mensagem {i}/{len(partes)}", value=p, height=220, key=f"rep_texto_{i}")
            st.session_state["_rep_df"] = df
            st.session_state["_rep_texto"] = texto
            st.session_state["_rep_dt_ini"] = dt_ini.isoformat()
            st.session_state["_rep_dt_fim"] = dt_fim.isoformat()

            st.code(texto)
            st.dataframe(df, use_container_width=True)

        if st.button("Enfileirar envios + CSV", use_container_width=True, key="rep_enqueue"):
            df = st.session_state.get("_rep_df")
            texto = st.session_state.get("_rep_texto")
            if df is None or texto is None:
                st.error("Gere a prévia primeiro.")
                return

            destinos = sorted({g for g in mapa.values() if g})

            # Se não houver vínculos por departamento, permite escolher manualmente (se houver destinatários)
            if not destinos:
                if not gestores:
                    st.error(
                        "Nenhum destinatário disponível. Verifique roles em tenant_users "
                        "(RPC não retornou usuários)."
                    )
                    return

                st.warning("Nenhum vínculo de departamento encontrado. Selecione destinatários manualmente abaixo.")
                destinos = st.multiselect(
                    "Enviar para",
                    options=[g["user_id"] for g in gestores],
                    format_func=lambda uid: labels_g.get(uid, uid),
                    key="rep_manual_destinos",
                )
                if not destinos:
                    st.error("Selecione ao menos um destinatário.")
                    return

            buf = io.StringIO()
            (df if isinstance(df, pd.DataFrame) else pd.DataFrame()).to_csv(buf, index=False)
            csv_bytes = buf.getvalue().encode("utf-8")

            ok = 0
            partes = _split_text(texto, max_chars=3500)
            total_itens = int(len(df)) if isinstance(df, pd.DataFrame) else 0

            for to_user_id in destinos:
                for idx_parte, parte in enumerate(partes, start=1):
                    if len(partes) > 1:
                        parte_envio = f"Relatório de Entregas ({idx_parte}/{len(partes)})\n\n" + parte
                    else:
                        parte_envio = parte

                    job = (
                        supabase.table("report_jobs")
                        .insert(
                            {
                                "tenant_id": tenant_id,
                                "created_by": created_by,
                                "channel": "whatsapp",
                                "to_user_id": to_user_id,
                                "report_type": "materiais_entregues",
                                "dt_ini": st.session_state.get("_rep_dt_ini"),
                                "dt_fim": st.session_state.get("_rep_dt_fim"),
                                "message_text": parte_envio,
                                "status": "queued",
                            }
                        )
                        .execute()
                    )
                    job_id = job.data[0]["id"]

                    if idx_parte == 1:
                        path = f"tenant/{tenant_id}/materiais_entregues/{job_id}.csv"
                        supabase.storage.from_("reports").upload(path, csv_bytes, {"content-type": "text/csv"})
                        supabase.table("report_artifacts").insert(
                            {
                                "job_id": job_id,
                                "tenant_id": tenant_id,
                                "file_type": "csv",
                                "storage_path": path,
                            }
                        ).execute()

                ok += 1

            try:
                supabase.table("whatsapp_relatorios_log").insert(
                    {
                        "tenant_id": tenant_id,
                        "created_by": created_by,
                        "dt_ini": st.session_state.get("_rep_dt_ini"),
                        "dt_fim": st.session_state.get("_rep_dt_fim"),
                        "departamentos": deps_sel or [],
                        "destinatarios": destinos,
                        "total_itens": total_itens,
                        "total_mensagens": len(partes),
                    }
                ).execute()
            except Exception:
                pass

            st.success(f"{ok} envio(s) enfileirado(s).")


        st.markdown("---")

        st.subheader("Histórico de envios")

        try:

            logs = (

                supabase.table("whatsapp_relatorios_log")

                .select("created_at, dt_ini, dt_fim, total_itens, total_mensagens, destinatarios, departamentos")

                .eq("tenant_id", tenant_id)

                .order("created_at", desc=True)

                .limit(20)

                .execute()

                .data

                or []

            )

            if not logs:

                st.caption("Sem envios registrados ainda.")

            else:

                df_logs = pd.DataFrame(logs).rename(

                    columns={

                        "created_at": "criado_em",

                        "total_itens": "itens",

                        "total_mensagens": "msgs",

                        "destinatarios": "destinatários",

                    }

                )

                st.dataframe(df_logs, use_container_width=True, hide_index=True)

        except Exception:

            st.caption("Não foi possível carregar o histórico (verifique a tabela/policies).")


        st.markdown("### 📊 Situação da fila (WhatsApp)")
        try:
            m = _count_queue_metrics(supabase, tenant_id)
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("⏳ Queued", m.get("queued", 0))
            c2.metric("🔄 Processando", m.get("processing", 0))
            c3.metric("✅ Enviados", m.get("sent", 0))
            c4.metric("❌ Falhas", m.get("failed", 0))
            c5.metric("📦 Total", m.get("total", 0))
        except Exception:
            st.caption("Não foi possível calcular métricas da fila.")

        st.markdown("---")
        st.markdown("### 🔁 Reenviar um relatório do histórico")

        if "df_logs" not in locals() or df_logs is None or df_logs.empty:
            st.caption("Carregue o histórico acima para habilitar o reenviar.")
            return

        # Monta labels para seleção
        df_sel = df_logs.copy()

        # Normaliza colunas esperadas
        if "criado_em" not in df_sel.columns and "created_at" in df_sel.columns:
            df_sel = df_sel.rename(columns={"created_at": "criado_em"})
        if "destinatários" not in df_sel.columns and "destinatarios" in df_sel.columns:
            df_sel = df_sel.rename(columns={"destinatarios": "destinatários"})

        df_sel["label"] = (
            df_sel["criado_em"].astype(str)
            + " | "
            + df_sel["dt_ini"].astype(str)
            + " → "
            + df_sel["dt_fim"].astype(str)
            + " | "
            + df_sel.get("msgs", pd.Series(["?"] * len(df_sel))).astype(str)
            + " msg(s)"
        )

        escolhido = st.selectbox(
            "Selecione um envio anterior",
            options=df_sel["label"].tolist(),
            key="rep_reenvio_select",
        )

        row = df_sel[df_sel["label"] == escolhido].iloc[0]

        # Controle de tentativas (se a coluna existir na tabela report_jobs, usamos; senão, só informativo)
        max_tentativas = st.number_input(
            "Limite de tentativas (quando suportado pela tabela report_jobs)",
            min_value=1,
            max_value=10,
            value=3,
            step=1,
            key="rep_reenvio_max_tentativas",
        )

        auto_retry = st.checkbox(
            "🔁 Auto-retry de falhas (tenta reenfileirar ao abrir esta seção, respeitando o limite acima quando possível)",
            value=False,
            key="rep_reenvio_auto",
        )

        # Carrega jobs do período selecionado (para status por destinatário)
        dt_ini_iso = str(row["dt_ini"])
        dt_fim_iso = str(row["dt_fim"])
        deps_sel = row.get("departamentos") or []
        destinos = row.get("destinatários") or []

        df_jobs = _load_jobs_for_period(supabase, tenant_id, dt_ini_iso, dt_fim_iso)
        df_latest = _latest_status_por_destinatario(df_jobs)

        # Tabela resumida por destinatário
        if not df_latest.empty:
            df_show = df_latest.copy()
            # deixa mais legível
            df_show = df_show.rename(columns={"to_user_id": "destinatário"})
            st.caption("Status mais recente por destinatário (para este período).")
            st.dataframe(df_show, use_container_width=True, hide_index=True)
        else:
            st.caption("Não encontrei jobs para esse período (ou a tabela report_jobs não está acessível).")

        # Define falhas com base no último status
        failed_users = []
        if not df_latest.empty and "status" in df_latest.columns:
            st_fail = df_latest["status"].astype(str).str.lower()
            failed_users = df_latest.loc[st_fail.isin(["failed", "error"]), "to_user_id"].tolist()

        if destinos and not failed_users:
            st.info("Não há falhas detectadas no período (ou não foi possível verificar).")

        def _enqueue_reenvio(destinos_alvo, somente_falhas: bool):
            # Recarrega entregues e regenera conteúdo
            dt_ini_pd = pd.to_datetime(dt_ini_iso, errors="coerce", utc=True)
            dt_fim_pd = pd.to_datetime(dt_fim_iso, errors="coerce", utc=True)

            df = _load_entregues(supabase, tenant_id, dt_ini_pd, dt_fim_pd, deps_sel)
            texto = _build_message(dt_ini_iso, dt_fim_iso, df, deps_sel)
            partes = _split_text(texto, max_chars=3500)

            buf = io.StringIO()
            (df if isinstance(df, pd.DataFrame) else pd.DataFrame()).to_csv(buf, index=False)
            csv_bytes = buf.getvalue().encode("utf-8")

            ok = 0

            # tenta pegar attempts atuais (se existir)
            attempt_map = {}
            if not df_latest.empty and "attempt" in df_latest.columns:
                for _, rr in df_latest.iterrows():
                    try:
                        attempt_map[rr["to_user_id"]] = int(rr.get("attempt") or 0)
                    except Exception:
                        attempt_map[rr["to_user_id"]] = 0

            for to_user_id in destinos_alvo:
                prev_attempt = attempt_map.get(to_user_id, 0)
                next_attempt = prev_attempt + 1

                # se temos attempt, respeita limite
                if (to_user_id in attempt_map) and (next_attempt > int(max_tentativas)):
                    continue

                for idx_parte, parte in enumerate(partes, start=1):
                    parte_envio = (
                        f"Relatório de Entregas ({idx_parte}/{len(partes)})\n\n{parte}"
                        if len(partes) > 1 else parte
                    )

                    payload = {
                        "tenant_id": tenant_id,
                        "created_by": created_by,
                        "channel": "whatsapp",
                        "to_user_id": to_user_id,
                        "report_type": "materiais_entregues",
                        "dt_ini": dt_ini_iso,
                        "dt_fim": dt_fim_iso,
                        "message_text": parte_envio,
                        "status": "queued",
                        # opcionais:
                        "attempt": next_attempt,
                        "origin_log_id": str(row.get("criado_em") or ""),
                    }

                    job = _insert_report_job_safe(supabase, payload)
                    job_id = (job.data or [{}])[0].get("id")

                    if job_id and idx_parte == 1:
                        try:
                            path = f"tenant/{tenant_id}/materiais_entregues/{job_id}.csv"
                            supabase.storage.from_("reports").upload(path, csv_bytes, {"content-type": "text/csv"})
                            supabase.table("report_artifacts").insert(
                                {"job_id": job_id, "tenant_id": tenant_id, "file_type": "csv", "storage_path": path}
                            ).execute()
                        except Exception:
                            pass

                ok += 1

            # tenta logar reenfileiramento
            try:
                supabase.table("whatsapp_relatorios_log").insert(
                    {
                        "tenant_id": tenant_id,
                        "created_by": created_by,
                        "dt_ini": dt_ini_iso,
                        "dt_fim": dt_fim_iso,
                        "departamentos": deps_sel or [],
                        "destinatarios": destinos_alvo,
                        "total_itens": int(len(df)) if isinstance(df, pd.DataFrame) else 0,
                        "total_mensagens": len(partes),
                        "reenviado_de": str(row.get("criado_em") or ""),
                        "somente_falhas": bool(somente_falhas),
                    }
                ).execute()
            except Exception:
                pass

            return ok

        # Auto retry (opcional)
        if auto_retry and destinos:
            alvos = failed_users if failed_users else []
            if alvos:
                n = _enqueue_reenvio(alvos, True)
                if n:
                    st.success(f"Auto-retry: {n} destinatário(s) reenfileirado(s).")
                else:
                    st.info("Auto-retry: nada para reenfileirar (pode ter batido o limite de tentativas).")

        cbtn1, cbtn2 = st.columns(2)
        with cbtn1:
            if st.button("🔁 Reenviar para TODOS os destinatários", use_container_width=True, key="rep_reenvio_all"):
                if not destinos:
                    st.error("Este log não possui lista de destinatários.")
                else:
                    n = _enqueue_reenvio(destinos, False)
                    st.success(f"{n} destinatário(s) reenfileirado(s).")

        with cbtn2:
            if st.button("🔁 Reenviar SOMENTE falhas", use_container_width=True, key="rep_reenvio_failed"):
                alvos = failed_users
                if not destinos:
                    st.error("Este log não possui lista de destinatários.")
                elif not alvos:
                    st.info("Nenhuma falha detectada para reenviar.")
                else:
                    n = _enqueue_reenvio(alvos, True)
                    st.success(f"{n} destinatário(s) com falha reenfileirado(s).")
