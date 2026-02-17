import io
from datetime import datetime, time, timedelta, timezone

import pandas as pd
import streamlit as st


def _dt_range_utc(d_ini, d_fim):
    """Converte date -> UTC range [ini, fim+1d)."""
    dt_ini = datetime.combine(d_ini, time.min).replace(tzinfo=timezone.utc)
    dt_fim = datetime.combine(d_fim, time.min).replace(tzinfo=timezone.utc) + timedelta(days=1)
    return dt_ini, dt_fim


def _load_gestores(supabase, tenant_id: str):
    """
    Gestores = tenant_users.role='gestor' no tenant atual.
    Junta com user_profiles (nome/email/whatsapp_e164).
    """
    tus = (
        supabase.table("tenant_users")
        .select("user_id, role")
        .eq("tenant_id", tenant_id)
        .eq("role", "gestor")
        .execute()
        .data
        or []
    )
    ids = [r.get("user_id") for r in tus if r.get("user_id")]
    if not ids:
        return []

    prof = (
        supabase.table("user_profiles")
        .select("user_id, nome, email, whatsapp_e164")
        .in_("user_id", ids)
        .execute()
        .data
        or []
    )
    prof.sort(key=lambda x: (x.get("nome") or x.get("email") or ""))
    return prof


def _load_departamentos_from_pedidos(supabase, tenant_id: str):
    """
    Lê departamentos existentes a partir de pedidos (coluna: departamento).
    Mantém simples para o MVP. Se sua base for grande, dá para trocar por RPC/view.
    """
    res = (
        supabase.table("pedidos")
        .select("departamento")
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
    Carrega pedidos entregues por período, filtrando por departamentos se fornecido.
    Ajuste campos do select conforme seu schema.
    """
    q = (
        supabase.table("pedidos")
        .select(
            "id,numero_pedido,fornecedor,descricao,quantidade,valor_total,departamento,atualizado_em,entregue"
        )
        .eq("tenant_id", tenant_id)
        .eq("entregue", True)
        .gte("atualizado_em", dt_ini.isoformat())
        .lt("atualizado_em", dt_fim.isoformat())
    )
    if departamentos:
        q = q.in_("departamento", departamentos)

    res = q.execute()
    return pd.DataFrame(res.data or [])


def _build_message(d_ini, d_fim, df: pd.DataFrame, departamentos_sel) -> str:
    total_itens = int(len(df or []))
    if isinstance(df, pd.DataFrame) and (not df.empty) and ("quantidade" in df.columns):
        total_qtd = int(pd.to_numeric(df["quantidade"], errors="coerce").fillna(0).sum())
    else:
        total_qtd = 0

    deps_txt = ", ".join(departamentos_sel) if departamentos_sel else "Todos"
    return (
        f"📦 Entregues — {d_ini.strftime('%d/%m/%Y')} a {d_fim.strftime('%d/%m/%Y')}\n"
        f"• {total_itens} itens • {total_qtd} unidades\n"
        f"• Departamentos: {deps_txt}\n"
    )


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

    gestores = _load_gestores(supabase, tenant_id)
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
            return
        if not gestores:
            st.warning("Nenhum gestor encontrado (tenant_users.role='gestor').")
            return

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

        c1, c2 = st.columns([1, 1])
        with c1:
            d_ini = st.date_input("Data inicial", value=(datetime.now().date() - timedelta(days=7)), key="rep_dt_ini")
        with c2:
            d_fim = st.date_input("Data final", value=datetime.now().date(), key="rep_dt_fim")

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

        if st.button("Gerar prévia", type="primary", use_container_width=True, key="rep_preview"):
            df = _load_entregues(supabase, tenant_id, dt_ini, dt_fim, deps_sel)
            texto = _build_message(d_ini, d_fim, df, deps_sel)

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
            if not destinos:
                st.error("Nenhum destino encontrado. Vincule gestores aos departamentos primeiro.")
                return

            buf = io.StringIO()
            (df if isinstance(df, pd.DataFrame) else pd.DataFrame()).to_csv(buf, index=False)
            csv_bytes = buf.getvalue().encode("utf-8")

            ok = 0
            for to_user_id in destinos:
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
                            "message_text": texto,
                            "status": "queued",
                        }
                    )
                    .execute()
                )
                job_id = job.data[0]["id"]

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

            st.success(f"{ok} envio(s) enfileirado(s).")
