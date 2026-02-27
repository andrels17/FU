import io
from datetime import datetime, time, timedelta, timezone
import json
import pandas as pd
import streamlit as st
from src.ui import ux

import streamlit.components.v1 as components
from supabase import create_client
import re
import urllib.parse


try:
    # storage3 é usado internamente pelo supabase-py (Streamlit Cloud)
    from storage3.utils import StorageException  # type: ignore
except Exception:  # pragma: no cover
    StorageException = Exception  # fallback

import urllib.parse

def _normalize_whatsapp(value: str) -> str:
    """Normaliza número WhatsApp para formato wa.me (somente dígitos com DDI).

    - Remove tudo que não for dígito
    - Se vier com 10/11 dígitos (padrão BR sem DDI), prefixa com 55
    - Aceita inputs como '+55 (84) 99999-9999' e retorna '5584999999999'
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    digits = re.sub(r"\D+", "", s)

    # remove zeros à esquerda comuns (ex.: 0DDI/0DDD)
    digits = digits.lstrip("0")

    # Se o usuário digitou só DDD+numero (10/11 dígitos), assume Brasil e adiciona 55
    if len(digits) in (10, 11) and not digits.startswith("55"):
        digits = "55" + digits

    # Se veio com +55 e etc já vira digits iniciando com 55 (ok)
    return digits

def _wa_me_link(phone_digits: str, text: str) -> str:
    """Monta link do WhatsApp Web com texto pré-preenchido (reutilizando a mesma aba)."""
    phone_digits = _normalize_whatsapp(phone_digits)
    q = urllib.parse.quote(text or "", safe="")
    return f"https://web.whatsapp.com/send?phone={phone_digits}&text={q}" if phone_digits else ""

def _copy_to_clipboard_button(label: str, text: str, key: str):
    """Botão de copiar via JS (cliente)."""
    import streamlit.components.v1 as components
    safe_text = (text or "").replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    html = f"""
    <button id="{key}" style="padding:0.35rem 0.6rem;border-radius:0.5rem;border:1px solid rgba(49,51,63,0.2);background:white;cursor:pointer;">
      {label}
    </button>
    <script>
      const btn = document.getElementById("{key}");
      if (btn) {{
        btn.onclick = async () => {{
          try {{
            await navigator.clipboard.writeText(`{safe_text}`);
            btn.innerText = "✅ Copiado";
            setTimeout(()=>btn.innerText="{label}", 1500);
          }} catch(e) {{
            btn.innerText = "⚠️ Falhou";
            setTimeout(()=>btn.innerText="{label}", 1500);
          }}
        }}
      }}
    </script>
    """
    components.html(html, height=45)


@st.cache_resource(show_spinner=False)
def _supabase_admin():
    """Client Supabase com SERVICE ROLE (bypass RLS). Use APENAS no backend (Streamlit)."""
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SERVICE_ROLE_KEY"],
    )

def _whatsapp_single_panel(phone_digits: str, text: str, key: str = "wa", label_prefix: str = ""):
    """Painel único (JS) para abrir WhatsApp Web em POPUP fixo e reutilizável.

    Importante:
    - Usamos POPUP + window.open(name, features) para aumentar a chance de reuso no Brave/COOP.
    - IDs HTML são sufixados com `key` para evitar colisão quando o Streamlit re-renderiza.
    """
    phone_digits = _normalize_whatsapp(phone_digits)
    if not phone_digits:
        ux.warn("Destinatário sem WhatsApp cadastrado.")
        return

    # Link WhatsApp Web com texto
    encoded_text = urllib.parse.quote(text or "", safe="")
    whatsapp_url = f"https://web.whatsapp.com/send?phone={phone_digits}&text={encoded_text}"

    # Escapar corretamente para JS
    url_js = json.dumps(whatsapp_url)
    msg_js = json.dumps(text or "")

    # IDs únicos por render
    fix_id = f"{key}_wa_fix"
    open_id = f"{key}_wa_open"
    copy_id = f"{key}_wa_copy"
    copy_open_id = f"{key}_wa_copy_open"
    status_id = f"{key}_wa_status"

    components.html(
        f"""
        <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
          <button id="{fix_id}"
            style="padding:10px 14px;border-radius:10px;border:1px solid #374151;background:#111827;color:#fff;font-weight:700;cursor:pointer;">
            📌 Fixar WhatsApp
          </button>

          <button id="{open_id}"
            style="padding:10px 14px;border-radius:10px;border:none;background:#25D366;color:#fff;font-weight:800;cursor:pointer;">
            🌐 {label_prefix} Abrir (popup fixo)
          </button>

          <button id="{copy_id}"
            style="padding:10px 14px;border-radius:10px;border:1px solid #374151;background:#1f2937;color:#fff;font-weight:800;cursor:pointer;">
            📋 Copiar
          </button>

          <button id="{copy_open_id}"
            style="padding:10px 14px;border-radius:10px;border:none;background:#0f172a;color:#fff;font-weight:800;cursor:pointer;">
            📋 Copiar + Abrir
          </button>

          <span id="{status_id}" style="font-weight:600;opacity:.85;"></span>
        </div>

        <script>
          const FEATS = "popup=yes,width=1200,height=900,left=80,top=60";
          const url = {url_js};
          const msg = {msg_js};
          const statusEl = document.getElementById("{status_id}");

          function setStatus(t) {{
            if (statusEl) statusEl.textContent = t || "";
            setTimeout(() => {{ if (statusEl) statusEl.textContent = ""; }}, 2500);
          }}

          function fixTab() {{
            window.open("https://web.whatsapp.com/", "whatsapp_tab", FEATS);
            setStatus("Popup fixado ✅");
          }}

          function openTab() {{
            window.open(url, "whatsapp_tab", FEATS);
            setStatus("Abrindo WhatsApp...");
          }}

          async function copyOnly() {{
            try {{
              await navigator.clipboard.writeText(msg);
              setStatus("Copiado ✅");
            }} catch (e) {{
              setStatus("Falha ao copiar");
            }}
          }}

          async function copyAndOpen() {{
            await copyOnly();
            openTab();
          }}

          document.getElementById("{fix_id}").onclick = fixTab;
          document.getElementById("{open_id}").onclick = openTab;
          document.getElementById("{copy_id}").onclick = copyOnly;
          document.getElementById("{copy_open_id}").onclick = copyAndOpen;
        </script>
        """,
        height=110,
    )


def _whatsapp_js_buttons(phone_digits: str, text: str, key: str = "", label_prefix: str = ""):
    """Compat: em vários pontos da tela a chamada está como _whatsapp_js_buttons(...).
    Mantemos esse nome chamando o painel único de popup.
    """
    k = key or "wa"
    _whatsapp_single_panel(phone_digits, text, key=k, label_prefix=label_prefix)

def _fetch_user_profiles_admin(admin, user_ids: list[str]):
    """Busca perfis dos usuários. Tenta tabelas/colunas comuns e é tolerante a schema.
    Retorna dict por user_id com chaves: nome, email, whatsapp.
    """
    if not user_ids:
        return {}

    # Tentativa 1: tabela user_profiles (PK = user_id)
    for cols in ["user_id, nome, email, whatsapp", "user_id, nome, email"]:
        try:
            rows = (
                admin.table("user_profiles")
                .select(cols)
                .in_("user_id", user_ids)
                .limit(5000)
                .execute()
                .data
                or []
            )
            by = {}
            for r in rows:
                uid = r.get("user_id")
                if uid:
                    by[uid] = {
                        "nome": r.get("nome"),
                        "email": r.get("email"),
                        "whatsapp": r.get("whatsapp"),
                    }
            if by:
                return by
            # Se consultou ok mas veio vazio, ainda pode tentar outras tabelas
        except Exception:
            pass

    # Tentativa 2: tabela usuarios (PK = id)
    for cols in ["id, nome, email, whatsapp", "id, nome, email"]:
        try:
            rows = (
                admin.table("usuarios")
                .select(cols)
                .in_("id", user_ids)
                .limit(5000)
                .execute()
                .data
                or []
            )
            by = {}
            for r in rows:
                uid = r.get("id")
                if uid:
                    by[uid] = {
                        "nome": r.get("nome"),
                        "email": r.get("email"),
                        "whatsapp": r.get("whatsapp"),
                    }
            if by:
                return by
        except Exception:
            pass

    return {}


def _update_user_whatsapp(supabase, uid: str, whatsapp_digits: str) -> bool:
    """Atualiza o WhatsApp do usuário (prioriza user_profiles) usando SERVICE ROLE.

    Motivo: em muitos projetos o update em user_profiles é bloqueado por RLS para o usuário logado.
    Aqui usamos o client admin (service role) para persistir com segurança no backend (Streamlit).
    """
    try:
        admin = _supabase_admin()
    except Exception:
        admin = None

    value = whatsapp_digits.strip() if isinstance(whatsapp_digits, str) else ""
    # Se vier vazio, grava NULL (melhor do que string vazia)
    payload = {"whatsapp": value or None}

    # 1) user_profiles (coluna user_id)
    try:
        client = admin or supabase
        client.table("user_profiles").update(payload).eq("user_id", uid).execute()
        return True
    except Exception:
        pass

    # 2) usuarios (coluna id) - fallback
    try:
        client = admin or supabase
        client.table("usuarios").update(payload).eq("id", uid).execute()
        return True
    except Exception:
        return False


def _signed_url_reports(storage_path: str, expires_in: int = 300) -> str | None:
    """Gera uma URL assinada para baixar um arquivo privado do bucket 'reports'."""
    if not storage_path:
        return None
    try:
        admin = _supabase_admin()
        # supabase-py/storage3: create_signed_url(path, expires_in)
        res = admin.storage.from_("reports").create_signed_url(storage_path, expires_in)
        # res pode ser dict com 'signedURL' ou 'signedUrl' dependendo da versão
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
        return None
    except Exception:
        return None


def _upload_csv_artifact_safe(supabase, tenant_id: str, job_id: str, csv_bytes: bytes) -> str | None:
    """Faz upload do CSV no bucket 'reports' usando SERVICE ROLE e registra em report_artifacts.

    - Bypass RLS no Storage (Service Role).
    - Usa upsert para evitar erro quando o arquivo já existe.
    - Não quebra o envio caso falhe (apenas mostra aviso).
    Retorna storage_path se ok, senão None.
    """
    if not csv_bytes:
        return None

    # proteção simples contra uploads enormes (evita crash por limites do Storage)
    if len(csv_bytes) > 8 * 1024 * 1024:
        ux.warn("CSV muito grande para upload automático. O envio foi enfileirado sem anexo.")
        return None

    storage_path = f"tenant/{tenant_id}/materiais_entregues/{job_id}.csv"
    try:
        admin = _supabase_admin()
        admin.storage.from_("reports").upload(
            storage_path,
            csv_bytes,
            {"content-type": "text/csv", "x-upsert": "true"},
        )

        # mantém o insert do artifact com o client normal (respeita RLS da sua tabela de app)
        supabase.table("report_artifacts").insert(
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "file_type": "csv",
                "storage_path": storage_path,
            }
        ).execute()
        return storage_path
    except Exception as e:
        ux.warn(
            "Falha ao anexar o CSV. O envio foi enfileirado mesmo assim. "
            f"Detalhe: {e}"
        )
        return None


def _find_csv_artifact_for_period(supabase, tenant_id: str, dt_ini_iso: str, dt_fim_iso: str, report_type: str = "materiais_entregues") -> str | None:
    """Tenta localizar um CSV já anexado para um período (reuso no reenviar e download no histórico)."""
    try:
        # pega jobs mais recentes do período
        jobs = (
            supabase.table("report_jobs")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("channel", "whatsapp")
            .eq("report_type", report_type)
            .eq("dt_ini", dt_ini_iso)
            .eq("dt_fim", dt_fim_iso)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
            .data
            or []
        )
        job_ids = [j.get("id") for j in jobs if j.get("id")]
        if not job_ids:
            return None

        arts = (
            supabase.table("report_artifacts")
            .select("storage_path, file_type, job_id")
            .eq("tenant_id", tenant_id)
            .eq("file_type", "csv")
            .in_("job_id", job_ids)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not arts:
            return None
        return arts[0].get("storage_path")
    except Exception:
        return None


def _attach_existing_csv_artifact(supabase, tenant_id: str, job_id: str, storage_path: str) -> None:
    """Anexa um CSV já existente ao job (sem reupload)."""
    if not storage_path:
        return
    try:
        supabase.table("report_artifacts").insert(
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "file_type": "csv",
                "storage_path": storage_path,
            }
        ).execute()
    except Exception:
        pass


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

    Fluxo:
    1) Tenta RPC (recomendado): public.rpc_tenant_members(p_tenant_id uuid)
    2) Se vier vazio (ou falhar), faz fallback via SERVICE ROLE:
       tenant_users (por tenant) + usuarios (nome/email/whatsapp)

    Observação: o fallback exige SUPABASE_SERVICE_ROLE_KEY nos secrets e deve rodar apenas no backend (Streamlit).
    """
    roles = roles  # None => todas as roles

    rows = []
    try:
        res = supabase.rpc("rpc_tenant_members", {"p_tenant_id": tenant_id}).execute()
        rows = res.data or []
    except Exception:
        rows = []

    # Fallback: se a RPC retornar vazio (muito comum em setups com RLS/tenants em formação)
    if not rows:
        try:
            admin = _supabase_admin()

            tu_rows = (
                admin.table("tenant_users")
                .select("user_id, role")
                .eq("tenant_id", tenant_id)
                .limit(5000)
                .execute()
                .data
                or []
            )
            user_ids = [r.get("user_id") for r in tu_rows if r.get("user_id")]
            if user_ids:
                u_by_id = _fetch_user_profiles_admin(admin, user_ids)

            role_by_uid = {r.get("user_id"): (r.get("role") or "") for r in (tu_rows or [])}

            rows = []
            for uid in user_ids:
                u = u_by_id.get(uid) or {}
                rows.append(
                    {
                        "user_id": uid,
                        "nome": u.get("nome"),
                        "email": u.get("email"),
                        "whatsapp": u.get("whatsapp"),
                        "role": role_by_uid.get(uid),
                    }
                )
        except Exception:
            rows = []

    if roles and rows:
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
    Relatórios via WhatsApp (Enterprise UI)

    Estrutura:
      - 📤 Envio: filtros, prévia, enfileiramento + envio assistido (WhatsApp Web)
      - 👥 Configuração: vínculos depto→destinatário + cadastro/edição de WhatsApp
      - 📚 Histórico: envios anteriores + download CSV assinado + reenvio (todos / somente falhas)
    Pré-requisitos:
      - tabela gestor_departamentos
      - tabela report_jobs e report_artifacts
      - bucket storage 'reports' (privado)
    """

    # -----------------------------
    # Tema (Enterprise): CSS leve
    # -----------------------------
    st.markdown(
        """
        <style>
          /* Layout */
          .fu-wrap {max-width: 1200px; margin: 0 auto;}
          .fu-hero {padding: 16px 18px; border-radius: 16px; border: 1px solid rgba(49,51,63,.16);
                    background: linear-gradient(135deg, rgba(17,24,39,.08), rgba(37,99,235,.06));}
          .fu-hero h1 {margin: 0; font-size: 1.55rem; letter-spacing: -0.02em;}
          .fu-hero p {margin: 6px 0 0 0; opacity: .9; color: #cbd5e1;}
          .fu-pill {display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border-radius:999px;
                    border:1px solid rgba(148,163,184,.18); background: rgba(15,23,42,.7); color:#e5e7eb; font-weight:600; font-size:.85rem;}
          .fu-sec {padding: 14px 14px; border-radius: 16px; border: 1px solid rgba(148,163,184,.16); background: rgba(15,23,42,.72); color:#e5e7eb;}
          .fu-sec h3 {margin: 0 0 8px 0; font-size: 1.05rem;}
          .fu-muted {opacity: .85; color:#cbd5e1;}
          /* Botões */
          .stButton>button {border-radius: 12px;}
          /* Métricas */
          div[data-testid="stMetric"]{
            border-radius: 16px;
            border: 1px solid rgba(49,51,63,.12);
            padding: 14px;
            background: rgba(2,6,23,.6); color:#e5e7eb;
          }
          /* Data editor / dataframe */
          div[data-testid="stDataFrame"] {border-radius: 14px; overflow: hidden; border: 1px solid rgba(148,163,184,.14);}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # -----------------------------
    # Cabeçalho
    # -----------------------------
    st.markdown('<div class="fu-wrap">', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="fu-hero">
          <h1>📲 Relatórios (WhatsApp)</h1>
          <p>Gere, revise e distribua relatórios de entregas por departamento — com fila, histórico e reenvio auditável.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # KPIs de fila no topo (rápido)
    try:
        m = _count_queue_metrics(supabase, tenant_id)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("⏳ Na fila", m.get("queued", 0))
        c2.metric("🔄 Em processamento", m.get("processing", 0))
        c3.metric("✅ Enviados", m.get("sent", 0))
        c4.metric("❌ Falhas", m.get("failed", 0))
        c5.metric("📦 Total", m.get("total", 0))
    except Exception:
        st.caption("Não foi possível calcular métricas da fila agora.")

    st.markdown("</div>", unsafe_allow_html=True)

    # -----------------------------
    # Dados comuns (gestores)
    # -----------------------------
    roles_destino = None  # None = todas as roles do tenant
    gestores = _load_gestores(supabase, tenant_id, roles=roles_destino)
    gestores_by_id = {g.get("user_id"): g for g in (gestores or []) if g.get("user_id")}
    labels_g = {
        g["user_id"]: f'{g.get("nome") or "Sem nome"} — {g.get("email") or ""}'
        + (f' | {g.get("whatsapp")}' if g.get("whatsapp") else "")
        for g in (gestores or [])
        if g.get("user_id")
    }

    # -----------------------------
    # Navegação principal
    # -----------------------------
    tab_send, tab_cfg, tab_hist = st.tabs(["📤 Envio", "👥 Configuração", "📚 Histórico"])

    # ==========================================================
    # TAB 1 — ENVIO
    # ==========================================================
    with tab_send:
        st.markdown("### 🧾 Gerar relatório de entregas")
        st.caption("Use os filtros para montar a prévia. Depois, enfileire o envio e/ou use o envio assistido via WhatsApp Web.")

        # Layout: filtros (esquerda) + prévia (direita)
        left, right = st.columns([1.05, 1.25], gap="large")

        with left:
            st.markdown('<div class="fu-sec">', unsafe_allow_html=True)
            st.markdown("<h3>🎯 Filtros</h3>", unsafe_allow_html=True)

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
                st.caption("Dica: selecione **Personalizado** para editar as datas livremente.")

            dt_ini, dt_fim = _dt_range_utc(d_ini, d_fim)

            deps = _load_departamentos_from_pedidos(supabase, tenant_id)
            if not deps:
                ux.info("Não encontrei departamentos em pedidos (coluna 'departamento').")
                deps_sel = []
            else:
                deps_sel = st.multiselect(
                    "Departamentos",
                    options=deps,
                    default=[],
                    key="rep_deps_sel",
                )

            # Resolve vínculos
            links = _load_links(supabase, tenant_id)
            mapa = _resolve_gestores_for_departamentos(links, deps_sel)

            faltando = [d for d, g in (mapa or {}).items() if not g]
            if faltando:
                ux.warn("Sem destinatário vinculado: " + ", ".join(faltando))

            # Ação principal: gerar prévia
            st.divider()
            gerar = st.button("👀 Gerar / Atualizar prévia", type="primary", use_container_width=True, key="rep_btn_preview")

            st.markdown("</div>", unsafe_allow_html=True)

        with right:
            st.markdown('<div class="fu-sec">', unsafe_allow_html=True)
            st.markdown("<h3>👀 Prévia</h3>", unsafe_allow_html=True)

            # Prévia atualiza automaticamente; mas o botão deixa explícito para o usuário (Enterprise UX)
            with st.spinner("Gerando prévia..."):
                df = _load_entregues(supabase, tenant_id, dt_ini, dt_fim, deps_sel)
                texto = _build_message(d_ini, d_fim, df, deps_sel)
                df_prev = _make_preview_df(df)
                partes = _split_text(texto, max_chars=3500)

            # KPIs da prévia
            k1, k2, k3 = st.columns(3)
            k1.metric("Itens entregues", int(len(df)) if isinstance(df, pd.DataFrame) else 0)
            k2.metric("Departamentos", int(len(deps_sel)) if deps_sel else 0)
            k3.metric("Mensagens", int(len(partes)) if partes else 1)

            # Armazena cache para ações abaixo (enfileirar / assistido)
            st.session_state["_rep_df"] = df
            st.session_state["_rep_texto"] = texto
            st.session_state["_rep_dt_ini"] = dt_ini.isoformat()
            st.session_state["_rep_dt_fim"] = dt_fim.isoformat()

            # Prévia detalhada
            t_prev, t_txt = st.tabs(["📋 Tabela", "💬 Texto WhatsApp"])

            with t_prev:
                st.dataframe(df_prev, use_container_width=True, hide_index=True, height=360)

                with st.expander("🔎 Dados completos (debug)", expanded=False):
                    st.dataframe(df, use_container_width=True, hide_index=True)

            with t_txt:
                if len(partes) == 1:
                    st.text_area("Mensagem", value=partes[0], height=280, key="rep_texto_full")
                else:
                    ux.info(f"O texto ficou grande e foi dividido em **{len(partes)}** mensagens.")
                    idx = st.selectbox(
                        "Escolha a parte",
                        options=list(range(1, len(partes) + 1)),
                        format_func=lambda i: f"Parte {i}/{len(partes)}",
                        key="rep_part_view",
                    ) - 1
                    st.text_area("Mensagem", value=partes[idx], height=280, key="rep_texto_part_view")

                with st.expander("🧾 Texto completo (debug)", expanded=False):
                    st.code(texto)

            st.markdown("</div>", unsafe_allow_html=True)

        # -----------------------------
        # Ações de envio (enfileirar + CSV)
        # -----------------------------
        st.markdown("### 🚀 Enfileirar envio (fila)")
        st.caption("Cria jobs na tabela **report_jobs** e anexa CSV no bucket privado **reports** (quando possível).")

        action_cols = st.columns([1.15, 1, 1], gap="large")

        with action_cols[0]:
            st.markdown('<div class="fu-sec">', unsafe_allow_html=True)
            st.markdown("<h3>📤 Enfileirar</h3>", unsafe_allow_html=True)

            if st.button("📤 Enfileirar envios + gerar CSV", use_container_width=True, type="primary", key="rep_enqueue"):
                df = st.session_state.get("_rep_df")
                texto = st.session_state.get("_rep_texto")
                if df is None or texto is None:
                    st.error("Gere a prévia primeiro.")
                else:
                    destinos = sorted({g for g in (mapa or {}).values() if g})

                    # Se não houver vínculos por departamento, permite escolher manualmente
                    if not destinos:
                        if not gestores:
                            st.error("Nenhum destinatário disponível (RPC/fallback vazio). Verifique roles / tenant_users.")
                            st.stop()

                        ux.warn("Nenhum vínculo de departamento encontrado. Selecione destinatários manualmente abaixo.")
                        destinos = st.multiselect(
                            "Enviar para",
                            options=[g["user_id"] for g in gestores],
                            format_func=lambda uid: labels_g.get(uid, uid),
                            key="rep_manual_destinos",
                        )
                        if not destinos:
                            st.error("Selecione ao menos um destinatário.")
                            st.stop()

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
                            job_id = (job.data or [{}])[0].get("id")

                            if job_id and idx_parte == 1:
                                _upload_csv_artifact_safe(supabase, tenant_id, job_id, csv_bytes)

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

                    ux.ok(f"{ok} destinatário(s) enfileirado(s).")

            st.markdown("</div>", unsafe_allow_html=True)

        with action_cols[1]:
            st.markdown('<div class="fu-sec">', unsafe_allow_html=True)
            st.markdown("<h3>📎 CSV local</h3>", unsafe_allow_html=True)
            st.caption("Gera o CSV localmente (download via Streamlit).")

            df = st.session_state.get("_rep_df")
            if isinstance(df, pd.DataFrame) and not df.empty:
                buf = io.StringIO()
                df.to_csv(buf, index=False)
                st.download_button(
                    "⬇️ Baixar CSV (local)",
                    data=buf.getvalue().encode("utf-8"),
                    file_name="materiais_entregues.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="rep_dl_local_csv",
                )
            else:
                st.button("⬇️ Baixar CSV (local)", disabled=True, use_container_width=True, key="rep_dl_local_csv_dis")

            st.markdown("</div>", unsafe_allow_html=True)

        with action_cols[2]:
            st.markdown('<div class="fu-sec">', unsafe_allow_html=True)
            st.markdown("<h3>🧭 Próximos passos</h3>", unsafe_allow_html=True)
            st.caption("Se houver avisos de vínculo faltando, corrija em **Configuração**.")

            ux.info("Dica: cadastre WhatsApp dos destinatários para habilitar o envio assistido.")
            st.markdown("</div>", unsafe_allow_html=True)

        # -----------------------------
        # Envio assistido (WhatsApp Web)
        # -----------------------------
        st.markdown("### 💬 Envio assistido (WhatsApp Web)")
        st.caption("Sem integração: abre o WhatsApp Web com a mensagem pronta. Você revisa e clica em enviar.")

        df_prev_cache = st.session_state.get("_rep_df")
        texto_cache = st.session_state.get("_rep_texto")

        with st.container(border=True):
            if df_prev_cache is None or texto_cache is None:
                ux.info("Gere a prévia acima para habilitar o envio assistido.")
            else:
                destinos_assist = sorted({g for g in (mapa or {}).values() if g}) or (st.session_state.get("rep_manual_destinos", []) or [])
                if not destinos_assist:
                    ux.warn("Nenhum destinatário definido (vincule departamentos ou selecione manualmente).")
                else:
                    partes_assist = _split_text(texto_cache, max_chars=3500)

                    options = []
                    for uid in destinos_assist:
                        g = gestores_by_id.get(uid, {}) if isinstance(gestores_by_id, dict) else {}
                        nome = g.get("nome") or g.get("email") or str(uid)
                        phone = g.get("whatsapp") or ""
                        phone_digits = _normalize_whatsapp(phone)
                        options.append(
                            {"user_id": uid, "nome": nome, "email": g.get("email") or "", "phone_digits": phone_digits, "raw_phone": phone}
                        )

                    with_wa = [o for o in options if o.get("phone_digits")]
                    without_wa = [o for o in options if not o.get("phone_digits")]

                    colsA, colsB = st.columns([1.1, 1])

                    with colsA:
                        if without_wa:
                            ux.warn("Sem WhatsApp cadastrado: " + ", ".join([o["nome"] for o in without_wa][:8]) + ("..." if len(without_wa) > 8 else ""))

                        if not with_wa:
                            st.error("Nenhum destinatário com WhatsApp cadastrado. Vá em **Configuração → Telefones WhatsApp**.")
                        else:
                            sel = st.selectbox(
                                "Destinatário",
                                with_wa,
                                format_func=lambda o: f"{o['nome']} — {o['phone_digits']}",
                                key="wa_assist_dest_select",
                            )

                            part_idx = st.selectbox(
                                "Parte da mensagem",
                                list(range(1, len(partes_assist) + 1)),
                                format_func=lambda i: f"Parte {i}/{len(partes_assist)}",
                                key="wa_assist_part_select",
                            ) - 1

                    with colsB:
                        if with_wa:
                            st.text_area("Mensagem (revisão)", value=partes_assist[part_idx], height=220, key="wa_assist_preview")

                    if with_wa:
                        _whatsapp_js_buttons(
                            sel["phone_digits"],
                            partes_assist[part_idx],
                            key=f"wa_panel_{sel['user_id']}_p{part_idx+1}",
                            label_prefix=f"Parte {part_idx+1}",
                        )

                        if st.button("✅ Marcar como enviado (manual)", use_container_width=True, key=f"mark_manual_{sel['user_id']}_{part_idx+1}"):
                            try:
                                admin = _supabase_admin()
                                admin.table("report_jobs").insert(
                                    {
                                        "tenant_id": tenant_id,
                                        "created_by": created_by,
                                        "channel": "whatsapp",
                                        "to_user_id": sel["user_id"],
                                        "report_type": "materiais_entregues",
                                        "dt_ini": st.session_state.get("rep_dt_ini"),
                                        "dt_fim": st.session_state.get("rep_dt_fim"),
                                        "message_text": partes_assist[part_idx],
                                        "status": "sent_manual",
                                    }
                                ).execute()
                                ux.ok("Marcado como enviado.")
                            except Exception as e:
                                ux.warn(f"Não consegui marcar como enviado: {e}")

    # ==========================================================
    # TAB 2 — CONFIGURAÇÃO (Vínculos + Telefones)
    # ==========================================================
    with tab_cfg:
        st.markdown("### 👥 Configuração de destinatários")
        st.caption("Cadastre WhatsApp e vincule departamentos a destinatários para automatizar envios.")

        sec1, sec2 = st.columns([1.05, 1.25], gap="large")

        # ---- Telefones WhatsApp
        with sec1:
            st.markdown('<div class="fu-sec">', unsafe_allow_html=True)
            st.markdown("<h3>📞 Telefones WhatsApp</h3>", unsafe_allow_html=True)
            st.caption("Atualize o WhatsApp dos destinatários para habilitar envio assistido e links wa.me.")

            df_users = pd.DataFrame(gestores or [])
            if df_users.empty:
                ux.info("Nenhum usuário retornado (RPC/fallback).")
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                if "user_id" not in df_users.columns and "id" in df_users.columns:
                    df_users = df_users.rename(columns={"id": "user_id"})
                for c in ["nome", "email", "role", "whatsapp"]:
                    if c not in df_users.columns:
                        df_users[c] = ""

                st.dataframe(
                    df_users[["user_id", "nome", "email", "role", "whatsapp"]],
                    use_container_width=True,
                    hide_index=True,
                    height=240,
                )

                st.divider()
                st.markdown("**Editar WhatsApp**")

                user_options = df_users["user_id"].tolist()

                def _fmt_user(uid: str) -> str:
                    row = df_users.loc[df_users["user_id"] == uid].head(1)
                    if row.empty:
                        return uid
                    nome = (row["nome"].iloc[0] or "Sem nome")
                    email = (row["email"].iloc[0] or "")
                    w = (row["whatsapp"].iloc[0] or "")
                    w_disp = f" | {w}" if w else ""
                    return f"{nome} — {email}{w_disp}"

                uid_sel = st.selectbox("Destinatário", options=user_options, format_func=_fmt_user, key="rep_whats_uid_sel")

                cur_digits = ""
                try:
                    cur_digits = _normalize_whatsapp(df_users.loc[df_users["user_id"] == uid_sel, "whatsapp"].iloc[0])
                except Exception:
                    cur_digits = ""

                # Defaults BR friendly
                ddi_def, ddd_def, num_def = "55", "", ""
                if cur_digits.startswith("55") and len(cur_digits) >= 12:
                    rest = cur_digits[2:]
                    ddd_def = rest[:2]
                    num_def = rest[2:]
                elif cur_digits:
                    ddi_def = cur_digits[:2]
                    rest = cur_digits[2:]
                    ddd_def = rest[:2] if len(rest) >= 2 else ""
                    num_def = rest[2:] if len(rest) > 2 else ""

                cddi, cddd, cnum = st.columns([0.6, 0.6, 1.2])
                with cddi:
                    ddi = st.text_input("DDI", value=ddi_def, max_chars=3, help="Ex.: 55 (Brasil)", key="rep_whats_ddi")
                with cddd:
                    ddd = st.text_input("DDD", value=ddd_def, max_chars=2, help="Ex.: 83", key="rep_whats_ddd")
                with cnum:
                    numero = st.text_input("Número", value=num_def, max_chars=12, help="Somente o número (8 ou 9 dígitos).", key="rep_whats_num")

                ddi_d = re.sub(r"\D+", "", ddi or "").strip() or "55"
                ddd_d = re.sub(r"\D+", "", ddd or "").strip()
                num_d = re.sub(r"\D+", "", numero or "").strip()

                full_digits = (ddi_d + ddd_d + num_d) if (ddd_d or num_d) else ""
                full_digits = full_digits.lstrip("0")

                valid, errs = True, []
                if full_digits:
                    if not ddi_d.isdigit() or len(ddi_d) not in (1, 2, 3):
                        valid = False; errs.append("DDI inválido")
                    if ddi_d == "55":
                        if len(ddd_d) != 2:
                            valid = False; errs.append("DDD deve ter 2 dígitos")
                        if len(num_d) not in (8, 9):
                            valid = False; errs.append("Número deve ter 8 ou 9 dígitos")
                    else:
                        if len(full_digits) < 10:
                            valid = False; errs.append("Número muito curto")

                def _fmt_preview(ddi_d: str, ddd_d: str, num_d: str) -> str:
                    if not (ddi_d and (ddd_d or num_d)):
                        return ""
                    if num_d:
                        if len(num_d) == 9:
                            num_fmt = f"{num_d[:5]}-{num_d[5:]}"
                        elif len(num_d) == 8:
                            num_fmt = f"{num_d[:4]}-{num_d[4:]}"
                        else:
                            num_fmt = num_d
                    else:
                        num_fmt = ""
                    mid = f"{ddd_d} {num_fmt}".strip()
                    return f"+{ddi_d} {mid}".strip()

                preview = _fmt_preview(ddi_d, ddd_d, num_d)
                if preview:
                    st.caption(f"Formato final: **{preview}**")
                    st.caption(f"WhatsApp Web: **https://web.whatsapp.com/send?phone={full_digits}**")

                if full_digits and not valid:
                    ux.warn("Ajuste: " + "; ".join(errs))

                csave, ctest, cclear = st.columns(3)
                with csave:
                    if st.button("Salvar", type="primary", use_container_width=True, key="rep_whats_save_one"):
                        if not full_digits:
                            st.error("Informe ao menos DDD e número.")
                        elif not valid:
                            st.error("Número inválido: " + "; ".join(errs))
                        else:
                            ok_upd = _update_user_whatsapp(supabase, uid_sel, full_digits)
                            if ok_upd:
                                ux.ok("WhatsApp salvo.")
                                st.rerun()
                            else:
                                st.error("Não consegui salvar (verifique coluna user_profiles.whatsapp e policies).")
                with ctest:
                    if full_digits:
                        st.link_button("Testar (wa.me)", url=f"https://wa.me/{full_digits}", use_container_width=True)
                    else:
                        st.button("Testar (wa.me)", disabled=True, use_container_width=True)
                with cclear:
                    if st.button("Limpar", use_container_width=True, key="rep_whats_clear_one"):
                        ok_upd = _update_user_whatsapp(supabase, uid_sel, "")
                        if ok_upd:
                            ux.ok("WhatsApp removido.")
                            st.rerun()
                        else:
                            st.error("Não consegui limpar (verifique policies).")

                st.markdown("</div>", unsafe_allow_html=True)

        # ---- Vínculos Dept → Destinatário
        with sec2:
            st.markdown('<div class="fu-sec">', unsafe_allow_html=True)
            st.markdown("<h3>🔗 Vínculos (Departamento → Destinatário)</h3>", unsafe_allow_html=True)
            st.caption("Esses vínculos determinam quem recebe o relatório quando você filtra por departamento.")

            deps = _load_departamentos_from_pedidos(supabase, tenant_id)
            if not deps:
                ux.info("Não encontrei departamentos em pedidos (coluna 'departamento').")
                st.caption("Cadastre ao menos um pedido com departamento preenchido para habilitar os vínculos.")
                st.markdown("</div>", unsafe_allow_html=True)
            elif not gestores:
                ux.warn("Nenhum destinatário encontrado para este tenant (RPC/fallback vazio).")
                st.caption("Se sua base usa roles específicas, ajuste roles_destino no código.")
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                links = _load_links(supabase, tenant_id)
                mapa_links = {l.get("departamento"): l.get("gestor_user_id") for l in (links or [])}

                st.markdown("**Vínculo individual**")
                c1, c2 = st.columns([1.1, 1.4])
                with c1:
                    dep = st.selectbox("Departamento", options=deps, key="rep_link_dep")
                with c2:
                    gestor_id = st.selectbox(
                        "Destinatário",
                        options=list(labels_g.keys()),
                        format_func=lambda uid: labels_g.get(uid, uid),
                        key="rep_link_gestor",
                    )

                if st.button("Salvar vínculo", type="primary", use_container_width=True, key="rep_link_save"):
                    dep_ok = (dep or "").strip()
                    if not dep_ok:
                        st.error("Departamento inválido (vazio).")
                    else:
                        _upsert_link(supabase, tenant_id, dep_ok, gestor_id)
                        ux.ok("Vínculo salvo.")
                        st.rerun()

                st.divider()
                st.markdown("**Vínculos existentes**")

                if links:
                    rows = []
                    for l in links:
                        dep_l = (l.get("departamento") or "").strip()
                        g_id = l.get("gestor_user_id")
                        g = gestores_by_id.get(g_id, {})
                        rows.append(
                            {
                                "id": l.get("id"),
                                "departamento": dep_l,
                                "gestor_user_id": g_id,
                                "destinatário": (g.get("nome") or g.get("email") or labels_g.get(g_id) or g_id),
                            }
                        )
                    df_links = pd.DataFrame(rows)

                    try:
                        edited = st.data_editor(
                            df_links,
                            use_container_width=True,
                            hide_index=True,
                            disabled=["id", "departamento", "destinatário"],
                            column_config={
                                "gestor_user_id": st.column_config.SelectboxColumn(
                                    "Destinatário",
                                    options=list(labels_g.keys()),
                                    format_func=lambda uid: labels_g.get(uid, uid),
                                    required=True,
                                ),
                            },
                            key="rep_links_editor",
                        )
                    except Exception:
                        st.dataframe(df_links[["departamento", "destinatário"]], use_container_width=True, hide_index=True)
                        edited = df_links

                    c_save, c_rm = st.columns(2)
                    with c_save:
                        if st.button("Salvar alterações do grid", use_container_width=True, key="rep_links_save_grid"):
                            changed = 0
                            for _, r in edited.iterrows():
                                dep_l = (r.get("departamento") or "").strip()
                                g_id = r.get("gestor_user_id")
                                if not dep_l:
                                    continue
                                if mapa_links.get(dep_l) != g_id:
                                    _upsert_link(supabase, tenant_id, dep_l, g_id)
                                    changed += 1
                            ux.ok(f"Alterações aplicadas: {changed}.")
                            st.rerun()

                    with c_rm:
                        rm_deps = st.multiselect(
                            "Remover vínculo(s) (por departamento)",
                            options=sorted([r["departamento"] for r in rows if r.get("departamento")]),
                            key="rep_links_rm_deps",
                        )
                        if st.button("Remover selecionados", use_container_width=True, key="rep_links_rm_btn"):
                            if not rm_deps:
                                ux.warn("Selecione ao menos um departamento para remover.")
                            else:
                                ids_to_rm = [l.get("id") for l in links if (l.get("departamento") or "").strip() in set(rm_deps)]
                                for lid in ids_to_rm:
                                    if lid:
                                        _delete_link(supabase, lid)
                                ux.ok(f"Removidos: {len(ids_to_rm)}.")
                                st.rerun()
                else:
                    st.caption("Nenhum vínculo cadastrado ainda.")

                st.divider()
                st.markdown("**Vincular todos os departamentos para um destinatário**")

                c_all1, c_all2 = st.columns([1.4, 0.9])
                with c_all1:
                    gestor_all = st.selectbox(
                        "Destinatário para todos",
                        options=list(labels_g.keys()),
                        format_func=lambda uid: labels_g.get(uid, uid),
                        key="rep_link_all_gestor",
                    )
                with c_all2:
                    aplicar_somente_faltantes = st.checkbox("Somente sem vínculo", value=True, key="rep_link_all_only_missing")

                if st.button("Aplicar em todos os departamentos", use_container_width=True, key="rep_link_all_btn"):
                    alvo = gestor_all
                    total = 0
                    for d in deps:
                        d_ok = (d or "").strip()
                        if not d_ok:
                            continue
                        if aplicar_somente_faltantes and mapa_links.get(d_ok):
                            continue
                        _upsert_link(supabase, tenant_id, d_ok, alvo)
                        total += 1
                    ux.ok(f"Vínculos atualizados: {total}.")
                    st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)

    # ==========================================================
    # TAB 3 — HISTÓRICO (logs + reenvio)
    # ==========================================================
    with tab_hist:
        st.markdown("### 📚 Histórico e reenvio")
        st.caption("Audite envios, baixe o CSV por link assinado (quando existir) e reenfileire para todos ou somente falhas.")

        # Carrega histórico
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
        except Exception:
            logs = []

        if not logs:
            ux.info("Sem envios registrados ainda.")
            return

        df_logs = pd.DataFrame(logs).rename(
            columns={"created_at": "criado_em", "total_itens": "itens", "total_mensagens": "msgs", "destinatarios": "destinatários"}
        )
        st.dataframe(df_logs, use_container_width=True, hide_index=True, height=260)

        st.divider()

        # Seleção
        df_sel = df_logs.copy()
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

        colA, colB = st.columns([1.6, 1], gap="large")
        with colA:
            escolhido = st.selectbox("Selecione um envio anterior", options=df_sel["label"].tolist(), key="rep_reenvio_select")

        row = df_sel[df_sel["label"] == escolhido].iloc[0]

        # Download CSV assinado (se existir)
        existing_storage_path = _find_csv_artifact_for_period(supabase, tenant_id, str(row["dt_ini"]), str(row["dt_fim"]))
        with colB:
            if existing_storage_path:
                url = _signed_url_reports(existing_storage_path, expires_in=600)
                if url:
                    try:
                        st.link_button("⬇️ Baixar CSV (10 min)", url, use_container_width=True)
                    except Exception:
                        st.markdown(f"[⬇️ Baixar CSV (10 min)]({url})")
                else:
                    st.caption("CSV encontrado, mas não consegui gerar URL assinada agora.")
            else:
                st.caption("Nenhum CSV anexado encontrado para este período.")

        # Controle de tentativas
        max_tentativas = st.number_input(
            "Limite de tentativas (quando suportado pela tabela report_jobs)",
            min_value=1,
            max_value=10,
            value=3,
            step=1,
            key="rep_reenvio_max_tentativas",
        )

        auto_retry = st.checkbox(
            "🔁 Auto-retry de falhas (reenfileira ao abrir esta seção, respeitando o limite quando possível)",
            value=False,
            key="rep_reenvio_auto",
        )

        # Carrega jobs e status por destinatário
        dt_ini_iso = str(row["dt_ini"])
        dt_fim_iso = str(row["dt_fim"])
        deps_sel = row.get("departamentos") or []
        destinos = row.get("destinatários") or []

        df_jobs = _load_jobs_for_period(supabase, tenant_id, dt_ini_iso, dt_fim_iso)
        df_latest = _latest_status_por_destinatario(df_jobs)

        if not df_latest.empty:
            df_show = df_latest.copy().rename(columns={"to_user_id": "destinatário"})
            st.caption("Status mais recente por destinatário (para este período).")
            st.dataframe(df_show, use_container_width=True, hide_index=True, height=260)
        else:
            st.caption("Não encontrei jobs para esse período (ou a tabela report_jobs não está acessível).")

        failed_users = []
        if not df_latest.empty and "status" in df_latest.columns:
            st_fail = df_latest["status"].astype(str).str.lower()
            failed_users = df_latest.loc[st_fail.isin(["failed", "error"]), "to_user_id"].tolist()

        def _enqueue_reenvio(destinos_alvo, somente_falhas: bool):
            dt_ini_pd = pd.to_datetime(dt_ini_iso, errors="coerce", utc=True)
            dt_fim_pd = pd.to_datetime(dt_fim_iso, errors="coerce", utc=True)

            df = _load_entregues(supabase, tenant_id, dt_ini_pd, dt_fim_pd, deps_sel)
            texto = _build_message(dt_ini_iso, dt_fim_iso, df, deps_sel)
            partes = _split_text(texto, max_chars=3500)

            buf = io.StringIO()
            (df if isinstance(df, pd.DataFrame) else pd.DataFrame()).to_csv(buf, index=False)
            csv_bytes = buf.getvalue().encode("utf-8")

            existing_storage_path = _find_csv_artifact_for_period(supabase, tenant_id, dt_ini_iso, dt_fim_iso)

            attempt_map = {}
            if not df_latest.empty and "attempt" in df_latest.columns:
                for _, rr in df_latest.iterrows():
                    try:
                        attempt_map[rr["to_user_id"]] = int(rr.get("attempt") or 0)
                    except Exception:
                        attempt_map[rr["to_user_id"]] = 0

            ok = 0
            for to_user_id in destinos_alvo:
                prev_attempt = attempt_map.get(to_user_id, 0)
                next_attempt = prev_attempt + 1

                if (to_user_id in attempt_map) and (next_attempt > int(max_tentativas)):
                    continue

                for idx_parte, parte in enumerate(partes, start=1):
                    parte_envio = f"Relatório de Entregas ({idx_parte}/{len(partes)})\n\n{parte}" if len(partes) > 1 else parte

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
                        "attempt": next_attempt,
                        "origin_log_id": str(row.get("criado_em") or ""),
                    }

                    job = _insert_report_job_safe(supabase, payload)
                    job_id = (job.data or [{}])[0].get("id")

                    if job_id and idx_parte == 1:
                        try:
                            if existing_storage_path:
                                _attach_existing_csv_artifact(supabase, tenant_id, job_id, existing_storage_path)
                            else:
                                _upload_csv_artifact_safe(supabase, tenant_id, job_id, csv_bytes)
                        except Exception:
                            pass

                ok += 1

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
            if failed_users:
                n = _enqueue_reenvio(failed_users, True)
                if n:
                    ux.ok(f"Auto-retry: {n} destinatário(s) reenfileirado(s).")
                else:
                    ux.info("Auto-retry: nada para reenfileirar (pode ter batido o limite de tentativas).")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("🔁 Reenviar para TODOS", use_container_width=True, key="rep_reenvio_all"):
                if not destinos:
                    st.error("Este log não possui lista de destinatários.")
                else:
                    n = _enqueue_reenvio(destinos, False)
                    ux.ok(f"{n} destinatário(s) reenfileirado(s).")
        with b2:
            if st.button("🔁 Reenviar SOMENTE falhas", use_container_width=True, key="rep_reenvio_failed"):
                if not destinos:
                    st.error("Este log não possui lista de destinatários.")
                elif not failed_users:
                    ux.info("Nenhuma falha detectada para reenviar.")
                else:
                    n = _enqueue_reenvio(failed_users, True)
                    ux.ok(f"{n} destinatário(s) com falha reenfileirado(s).")
