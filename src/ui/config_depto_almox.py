from __future__ import annotations

import streamlit as st
import pandas as pd

from src.ui.theme import section_header


def _fetch_departamentos(_supabase, tenant_id: str) -> list[str]:
    """Departamentos do TENANT.

    IMPORTANTE:
    Seu view `vw_stats_departamento` NÃO tem tenant_id (ele agrupa só por departamento),
    então filtrar por tenant_id nele sempre volta vazio.
    Por isso, aqui listamos departamentos diretamente da tabela `pedidos` filtrando por tenant_id.
    """
    try:
        res = (
            _supabase.table("pedidos")
            .select("departamento")
            .eq("tenant_id", tenant_id)
            .limit(20000)
            .execute()
        )
        rows = res.data or []
        deps = sorted(
            {
                str(r.get("departamento") or "").strip()
                for r in rows
                if str(r.get("departamento") or "").strip()
            }
        )
        return deps
    except Exception:
        return []


def _fetch_almoxarifados(_supabase, tenant_id: str) -> list[str]:
    """Almoxarifados (pelo view vw_almoxarifados)."""
    try:
        res = (
            _supabase.table("vw_almoxarifados")
            .select("almoxarifado, almoxarifado_display")
            .eq("tenant_id", tenant_id)
            .order("almoxarifado_display")
            .limit(5000)
            .execute()
        )
        rows = res.data or []
        nomes: list[str] = []
        for r in rows:
            disp = str(r.get("almoxarifado_display") or "").strip()
            raw = str(r.get("almoxarifado") or "").strip()
            nomes.append(disp or raw)
        return sorted({n for n in nomes if n})
    except Exception:
        return []


def _fetch_mapeamentos(_supabase, tenant_id: str) -> pd.DataFrame:
    """Carrega vínculos já existentes no BD."""
    try:
        res = (
            _supabase.table("depto_almox_map")
            .select("id,departamento,almoxarifado,created_at")
            .eq("tenant_id", tenant_id)
            .order("departamento")
            .limit(5000)
            .execute()
        )
        return pd.DataFrame(res.data or [])
    except Exception:
        return pd.DataFrame()


def _upsert_mapeamento(_supabase, tenant_id: str, departamento: str, almoxarifado: str) -> None:
    payload = {"tenant_id": tenant_id, "departamento": departamento, "almoxarifado": almoxarifado}
    _supabase.table("depto_almox_map").upsert(payload, on_conflict="tenant_id,departamento").execute()


def _delete_mapeamento(_supabase, tenant_id: str, row_id: int) -> None:
    _supabase.table("depto_almox_map").delete().eq("tenant_id", tenant_id).eq("id", row_id).execute()


def exibir_config_depto_almox(supabase_user, supabase_admin=None, tenant_id: str | None = None):
    tenant_id = str(tenant_id or st.session_state.get("tenant_id") or "").strip()
    if not tenant_id:
        st.error("❌ Não foi possível identificar o tenant.")
        return

    # Para escrita/leitura administrativa, preferir admin/service role quando disponível
    _supabase = supabase_admin or supabase_user

    section_header(
        "Vínculo Depto ↔ Almoxarifado",
        hint=(
            "Defina qual almoxarifado está associado a cada departamento. "
            "Na importação, departamentos sem vínculo apenas geram aviso (não bloqueia)."
        ),
        pill="Configuração",
    )

    deps = _fetch_departamentos(_supabase, tenant_id)
    almox = _fetch_almoxarifados(_supabase, tenant_id)
    df_map = _fetch_mapeamentos(_supabase, tenant_id)

    # mapa depto -> almox para auto-preencher
    map_dep_to_almox: dict[str, str] = {}
    if not df_map.empty and "departamento" in df_map.columns and "almoxarifado" in df_map.columns:
        map_dep_to_almox = {
            str(r["departamento"]).strip(): str(r["almoxarifado"]).strip()
            for _, r in df_map.iterrows()
            if str(r.get("departamento") or "").strip() and str(r.get("almoxarifado") or "").strip()
        }

    dep_key = "cfg_depto_almox__dep"
    almox_key = "cfg_depto_almox__almox"

    def _on_dep_change():
        dep = str(st.session_state.get(dep_key) or "").strip()
        vinc = map_dep_to_almox.get(dep)
        if vinc:
            st.session_state[almox_key] = vinc

    with st.container(border=True):
        c1, c2 = st.columns([1, 1])

        with c1:
            if deps:
                cur = str(st.session_state.get(dep_key) or "").strip()
                if not cur or cur not in deps:
                    st.session_state[dep_key] = deps[0]
                departamento = st.selectbox("Departamento", options=deps, key=dep_key, on_change=_on_dep_change)
            else:
                st.warning(
                    "Não encontrei departamentos para listar (do seu tenant). "
                    "Se você tem pedidos e mesmo assim aparece vazio, pode ser permissão/RLS na tabela `pedidos`."
                )
                departamento = st.text_input(
                    "Departamento",
                    key="cfg_depto_almox__dep_txt",
                    placeholder="Ex.: Oficina, Manutenção, Administrativo...",
                )

        with c2:
            dep_sel = str(st.session_state.get(dep_key) or "").strip()
            default_almox = map_dep_to_almox.get(dep_sel)

            if almox:
                if default_almox and default_almox in almox:
                    st.session_state[almox_key] = default_almox
                else:
                    cur_alx = str(st.session_state.get(almox_key) or "").strip()
                    if not cur_alx or cur_alx not in almox:
                        st.session_state[almox_key] = almox[0]
                almoxarifado = st.selectbox("Almoxarifado", options=almox, key=almox_key)
            else:
                st.warning("Não encontrei almoxarifados no view vw_almoxarifados.")
                almoxarifado = st.text_input(
                    "Almoxarifado",
                    key="cfg_depto_almox__almox_txt",
                    placeholder="Ex.: Almoxarifado Central",
                )

        if st.button("💾 Salvar vínculo", type="primary", use_container_width=True, key="cfg_depto_almox__save"):
            dep = (departamento or "").strip()
            alx = (almoxarifado or "").strip()
            if not dep or not alx:
                st.error("Preencha Departamento e Almoxarifado.")
            else:
                try:
                    _upsert_mapeamento(_supabase, tenant_id, dep, alx)
                    st.success("✅ Vínculo salvo.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Não foi possível salvar: {e}")

    st.markdown("---")
    st.subheader("Vínculos atuais")

    if df_map.empty:
        st.info("Nenhum vínculo cadastrado ainda.")
        return

    show = df_map[["departamento", "almoxarifado", "created_at", "id"]].copy()
    st.dataframe(show.drop(columns=["id"]), use_container_width=True, height=260)

    with st.expander("Remover vínculo", expanded=False):
        opt = st.selectbox(
            "Selecione um vínculo para remover",
            options=list(show["id"].astype(int)),
            format_func=lambda rid: (
                f'{show.loc[show["id"] == rid, "departamento"].iloc[0]} → '
                f'{show.loc[show["id"] == rid, "almoxarifado"].iloc[0]}'
            ),
            key="cfg_depto_almox__rm_sel",
        )
        if st.button("🗑️ Remover", use_container_width=True, key="cfg_depto_almox__rm"):
            try:
                _delete_mapeamento(_supabase, tenant_id, int(opt))
                st.success("✅ Removido.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Não foi possível remover: {e}")
