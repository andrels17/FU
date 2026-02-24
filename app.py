import streamlit as st
import unicodedata
st.set_page_config(
    page_title="Sistema de Follow-Up",
    layout="wide",
    page_icon="📊",
)

import importlib

def _call_page(mod_name: str, func_name: str, *args, **kwargs):
    """Importa a página sob demanda (evita import circular e mantém o app subindo)."""
    try:
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, func_name)
    except Exception as e:
        st.error(f"Erro ao importar {mod_name}.{func_name}: {e}")
        st.stop()
    return fn(*args, **kwargs)

# 🔑 Auth callback (robusto para diferentes estruturas de projeto)
try:
    # Se auth_flows.py estiver na raiz do projeto
    from auth_flows import handle_auth_callback  # type: ignore
except Exception:
    try:
        # Se estiver dentro do pacote src (ajuste comum em apps modularizados)
        from src.auth_flows import handle_auth_callback  # type: ignore
    except Exception:
        try:
            from src.core.auth_flows import handle_auth_callback  # type: ignore
        except Exception:
            # Fallback seguro: não quebra o app caso o módulo não exista
            def handle_auth_callback(*_args, **_kwargs):  # type: ignore
                return

from src.core.auth import verificar_autenticacao, exibir_login, fazer_logout

import json
import base64
import textwrap
import streamlit.components.v1 as components


from urllib.parse import urlencode
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import src.services.sistema_alertas as sa
import src.services.backup_auditoria as ba
from src.repositories.fornecedores import carregar_fornecedores
from src.core.config import configure_page  # noqa: F401
from src.core.db import init_supabase_admin, init_supabase_anon, get_supabase_user_client
from src.repositories.pedidos import carregar_pedidos
from src.utils.formatting import formatar_moeda_br
from src.ui.dashboard import exibir_dashboard
from src.ui.mapa import exibir_mapa
from src.ui.consulta import exibir_consulta_pedidos
from src.ui.ficha_material_page import exibir_ficha_material
from src.ui.gestao_usuarios import exibir_gestao_usuarios
from src.ui.admin_saas import exibir_admin_saas
from src.ui.landing_public import render_landing
from src.ui.home import exibir_home
from src.core.superadmin import is_superadmin
from src.ui.relatorios_whatsapp import render_relatorios_whatsapp
from src.ui.relatorios_gerenciais import render_relatorios_gerenciais
from src.ui.theme import apply_theme as apply_ui_theme
from src.services import observabilidade as obs


# --- Supabase clients (anon/admin) ---
# Necessários para login (anon) e operações administrativas (admin).
# Mantemos como singletons no módulo para uso em callbacks/funções auxiliares.
try:
    supabase_anon = init_supabase_anon()
except Exception:
    supabase_anon = None

try:
    supabase_admin = init_supabase_admin()
except Exception:
    supabase_admin = None

# Disponibiliza admin client para observabilidade/perf (best-effort)
try:
    st.session_state["_supabase_admin"] = supabase_admin
except Exception:
    pass

# Observabilidade: logger rotativo (best-effort)
try:
    obs.setup_logging()
except Exception:
    pass

if "fu_started_at" not in st.session_state:
    try:
        st.session_state.fu_started_at = datetime.now().isoformat()
    except Exception:
        st.session_state.fu_started_at = ""






# --- Sidebar fixa (sem modo colapsado) ---
if "fu_sidebar_hidden" not in st.session_state:
    st.session_state.fu_sidebar_hidden = False
else:
    st.session_state.fu_sidebar_hidden = False

def _jwt_claim_exp(token: str):
    """Extrai 'exp' (epoch seconds) do JWT sem validar assinatura."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        # base64url padding
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))
        return payload.get("exp")
    except Exception:
        return None


def _jwt_expirou() -> bool:
        exp = st.session_state.get("auth_expires_at")
        if not exp:
            token = st.session_state.get("auth_access_token")
            if token:
                exp = _jwt_claim_exp(token)
                # guarda pra próximas execuções
                if exp:
                    st.session_state.auth_expires_at = exp
            if not exp:
                # sem exp conhecido, tenta refresh preventivo
                return True
        try:
            return datetime.now(timezone.utc).timestamp() >= float(exp) - 30
        except Exception:
            return False


def _refresh_session() -> bool:
    """Tenta renovar a sessão usando refresh_token. Retorna True se renovou."""
    rt = st.session_state.get("auth_refresh_token")
    if not rt:
        return False
    try:
        res = supabase_anon.auth.refresh_session(rt)
        session = res.session
        st.session_state.auth_access_token = session.access_token
        st.session_state.auth_refresh_token = session.refresh_token
        st.session_state.auth_expires_at = session.expires_at
        return True
    except Exception:
        return False
def _safe_len(x) -> int:
    try:
        return int(len(x or []))
    except Exception:
        return 0


def _industrial_sidebar_css() -> None:
    """No-op: CSS now injected via theme.py apply_theme()."""
    pass


def _label_alertas(total_alertas: int) -> str:
    """Label visual de Alertas (sem emoji) com contagem quando houver."""
    try:
        n = int(total_alertas or 0)
    except Exception:
        n = 0
    if n > 0:
        return f"Alertas ({n})"
    return "Alertas"

# ===== Navegação: IDs internos (não dependem de label/emoji) =====
PAGE_LABELS = {
    "home": "Início",
    "dashboard": "Dashboard",
    "alerts": "Alertas",
    "orders_search": "Consultar pedidos",
    "profile": "Meu perfil",
    "material_sheet": "Ficha de material",
    "catalog_materials": "Catálogo de Materiais",
    "orders_manage": "Gestão de pedidos",
    "map": "Mapa",
    "users": "Gestão de usuários",
    "backup": "Backup",
    "saas_admin": "Admin do SaaS",
    "observability": "Observabilidade",
    "tenant_health": "Saúde por Tenant",
    "audit_logs": "Auditoria",
    "exec_metrics": "Métricas Executivas",
    "tenant_ranking": "Ranking de Tenants",
    "snapshots": "Snapshots",
    "reports_whatsapp": "Relatórios WhatsApp",
    "reports_gerenciais": "Relatórios Gerenciais",
    "reports": "Relatórios",
    "imports": "Importações",
    "dept_almox_config": "Vínculo Depto ↔ Almox",
}


LEGACY_PAGE_TO_ID = {

    "Início": "home",
    "Alertas": "alerts",
    "Consultar pedidos": "orders_search",
    "Consultar Pedidos": "orders_search",
    "Meu perfil": "profile",
    "Meu Perfil": "profile",
    "Ficha de material": "material_sheet",
    "Ficha de Material": "material_sheet",
    "Gestão de pedidos": "orders_manage",
    "Gestão de Pedidos": "orders_manage",
    "Mapa": "map",
    "Mapa Geográfico": "map",
    "Gestão de usuários": "users",
    "Gestão de Usuários": "users",
    "Backup": "backup",
    "Admin do SaaS": "saas_admin",
    "🏠 Início": "home",
    "Dashboard": "dashboard",
    "🔔 Alertas e Notificações": "alerts",
    "Consultar Pedidos": "orders_search",
    "Meu Perfil": "profile",
    "Ficha de Material": "material_sheet",
    "Gestão de Pedidos": "orders_manage",
    "Mapa Geográfico": "map",
    "👥 Gestão de Usuários": "users",
    "💾 Backup": "backup",
    "🧩 Admin do SaaS": "saas_admin",
    "Observabilidade": "observability",
    "Saúde por Tenant": "tenant_health",
    "Auditoria": "audit_logs",
    "Métricas Executivas": "exec_metrics",
    "Ranking de Tenants": "tenant_ranking",
    "Snapshots": "snapshots",
    "Relatórios": "reports",
    "Importações": "imports",
}

def page_label(page_id: str, total_alertas: int = 0) -> str:
    """Label visual da página (sem emoji)."""
    if page_id == "alerts":
        return _label_alertas(total_alertas)
    return PAGE_LABELS.get(page_id, page_id)

def _fu_glyph(icon_key: str) -> str:
    """SVG monocromático (controlado por CSS) para sidebar compacta."""
    icons = {
        "home": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l9 7v11a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V10l9-7z"/></glyph>',
        "dashboard": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M4 13h7V4H4v9zm9 7h7V11h-7v9zM4 20h7v-5H4v5zm9-16v5h7V4h-7z"/></glyph>',
        "bell": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22zM18 16v-5a6 6 0 1 0-12 0v5L4 18v1h16v-1l-2-2z"/></glyph>',
        "search": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M10 18a8 8 0 1 1 5.29-14.02A8 8 0 0 1 10 18zm11 3-6-6 1.41-1.41 6 6L21 21z"/></glyph>',
        "user": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M12 12a5 5 0 1 0-5-5 5 5 0 0 0 5 5zm0 2c-5 0-9 2.5-9 5.5V22h18v-2.5C21 16.5 17 14 12 14z"/></glyph>',
        "receipt": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2h12v20l-2-1-2 1-2-1-2 1-2-1-2 1V2zm3 5h6v2H9V7zm0 4h6v2H9v-2zm0 4h6v2H9v-2z"/></glyph>',
        "cart": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M7 18a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm10 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM6.2 6h15.1l-1.4 7.2a2 2 0 0 1-2 1.6H8.1a2 2 0 0 1-2-1.6L4.3 2H2v2h1l2.2 11.2A4 4 0 0 0 9.1 18H19v-2H9.1a2 2 0 0 1-2-1.6L6.8 13h11.1a4 4 0 0 0 3.9-3.2L23.6 6H6.2z"/></glyph>',
        "map": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 3.5 15 5.7 9 3 3.5 4.8A1 1 0 0 0 3 5.7v14.6a1 1 0 0 0 1.3.95L9 19.3l6 2.7 5.5-1.8a1 1 0 0 0 .7-.95V4.5a1 1 0 0 0-1.2-1zM9 17.6l-4 1.3V6.4l4-1.3v12.5zm6 1.3-4-1.8V4.6l4 1.8v12.5zm4-1.3-4 1.3V6.4l4-1.3v12.5z"/></glyph>',
        "whatsapp": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 0 0-8.5 15.3L2 22l4.8-1.5A10 10 0 1 0 12 2zm5.7 14.3c-.2.6-1.1 1.1-1.8 1.2-.5.1-1.2.2-3.9-.8-3.4-1.3-5.5-4.6-5.7-4.8-.2-.2-1.4-1.8-1.4-3.4 0-1.6.8-2.3 1.1-2.6.3-.3.6-.4.8-.4h.6c.2 0 .4 0 .6.5.2.5.8 1.9.9 2 .1.2.1.4 0 .6-.1.2-.2.4-.3.5l-.3.4c-.1.2-.3.4-.1.7.2.3.7 1.3 1.6 2.1 1.1 1 2 1.3 2.3 1.5.3.2.5.2.7 0l.9-1.1c.2-.3.5-.2.7-.1.2.1 1.6.8 1.9.9.3.1.5.2.6.4.1.2.1.7-.1 1.3z"/></glyph>',
        "chart": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19h16v2H2V3h2v16zm4-2H6V10h2v7zm5 0h-2V6h2v11zm5 0h-2v-5h2v5z"/></glyph>',
        "users": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M16 11a4 4 0 1 0-4-4 4 4 0 0 0 4 4zM8 11a4 4 0 1 0-4-4 4 4 0 0 0 4 4zm8 2c-2.7 0-8 1.3-8 4v3h16v-3c0-2.7-5.3-4-8-4zM8 13c-2.7 0-8 1.3-8 4v3h6v-3c0-1.6.9-2.9 2.2-3.8-.1-.1-.2-.2-.2-.2z"/></glyph>',
        "database": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2C7 2 3 3.8 3 6v12c0 2.2 4 4 9 4s9-1.8 9-4V6c0-2.2-4-4-9-4zm0 2c4.4 0 7 .1 7 2s-2.6 2-7 2-7-.1-7-2 2.6-2 7-2zm0 16c-4.4 0-7-.1-7-2v-2c1.6 1.1 4.7 1.7 7 1.7s5.4-.6 7-1.7v2c0 1.9-2.6 2-7 2zm0-6c-4.4 0-7-.1-7-2V10c1.6 1.1 4.7 1.7 7 1.7s5.4-.6 7-1.7v2c0 1.9-2.6 2-7 2z"/></glyph>',
        "puzzle": '<glyph viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2a2 2 0 0 1 2 2v2h2a2 2 0 0 1 2 2v3h-2a2 2 0 1 0 0 4h2v3a2 2 0 0 1-2 2h-2v-2a2 2 0 1 0-4 0v2H7a2 2 0 0 1-2-2v-3h2a2 2 0 1 0 0-4H5V8a2 2 0 0 1 2-2h6V4a2 2 0 0 1 2-2z"/></glyph>',
    }
    return icons.get(icon_key, icons["dashboard"])


def _fu_render_compact_sidebar(total_alertas: int, is_admin: bool, is_superadmin: bool) -> None:
    """Sidebar compacta robusta (SEM HTML/SVG): usa st.button com glyphs monocromáticos.
    - Padrão: ícone branco
    - Hover: vermelho
    - Ativo: fundo vermelho cheio + ícone branco
    """

    items: list[tuple[str, str, str]] = [
        ("⌂", "home", "Início"),
        ("▦", "dashboard", "Dashboard"),
        ("◎", "alerts", "Alertas"),
        ("⌕", "orders_search", "Consultar pedidos"),
        ("◉", "profile", "Meu perfil"),
        ("≣", "material_sheet", "Ficha de material"),
        ("▤", "orders_manage", "Gestão de pedidos"),
        ("⌖", "map", "Mapa"),
        ("◌", "reports_whatsapp", "Relatórios WhatsApp"),
        ("▧", "reports_gerenciais", "Relatórios Gerenciais"),
    ]

    if is_admin:
        items += [
            ("◍", "users", "Gestão de usuários"),
            ("▣", "backup", "Backup"),
        ]
        if is_superadmin:
            items += [
                ("⬚", "saas_admin", "Admin do SaaS"),
                ("◈", "observability", "Observabilidade"),
                ("▥", "tenant_health", "Saúde por Tenant"),
                ("▦", "tenant_ranking", "Ranking de Tenants"),
                ("▦", "audit_logs", "Auditoria"),
                ("▩", "exec_metrics", "Métricas Executivas"),
                ("▢", "snapshots", "Snapshots"),
            ]

    current = st.session_state.get("current_page") or "home"

    st.markdown('<div class="fu-compact-nav">', unsafe_allow_html=True)

    for glyph, page_id, tip in items:
        active = (page_id == current)

        st.markdown('<div class="fu-compact-row">', unsafe_allow_html=True)
        if active:
            st.markdown('<div class="fu-compact-active">', unsafe_allow_html=True)

        if st.button(glyph, help=tip, key=f"fu_nav_btn_{page_id}"):
            if page_id != st.session_state.get("current_page"):
                st.session_state.current_page = page_id
                st.session_state["_force_menu_sync"] = True
                st.rerun()

        if active:
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


def _sidebar_footer(supabase_client) -> None:
    """Renderiza Sair + créditos (sempre por último na sidebar)."""
    st.markdown("<div class=\"fu-sidebar-footer\">", unsafe_allow_html=True)
    st.markdown("---")
    if st.button("Sair", use_container_width=True, key="btn_logout_sidebar"):
        try:
            ba.registrar_acao(
                st.session_state.usuario,
                "Logout",
                {"timestamp": datetime.now().isoformat()},
                supabase_client,
            )
        except Exception:
            pass

        try:
            fazer_logout(supabase_anon)
        except Exception:
            pass
        st.rerun()

    # Oculta o rodapé no modo colapsado (evita ficar prensado)
    if st.session_state.get("fu_sidebar_hidden"):
        return

    st.markdown(
        """
        <div style="font-size:11px; opacity:0.6; margin-top:10px;">
            © Follow-up de Compras v3.0<br>
            Criado por André Luis e Yasmim Lima
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def _sync_empresa_nome(tenant_id: str | None, tenant_opts) -> None:
    """Mantém um nome de empresa legível no session_state (para Perfil / UI)."""
    try:
        if not tenant_id:
            return
        nome = None
        if tenant_opts and isinstance(tenant_opts, list):
            for t in tenant_opts:
                if isinstance(t, dict) and t.get("tenant_id") == tenant_id:
                    nome = t.get("nome") or t.get("name") or t.get("razao_social")
                    break
        nome_final = (str(nome).strip() if isinstance(nome, str) and nome.strip() else str(tenant_id))
        st.session_state["empresa_nome"] = nome_final
        # compat com chaves antigas
        st.session_state["empresa_atual"] = nome_final
    except Exception:
        pass


@st.cache_data(ttl=60)
def _fetch_almoxarifados_tenant(_supabase, tenant_id: str) -> list[str]:
    try:
        res = (
            _supabase
            .table("vw_almoxarifados")
            .select("almoxarifado")
            .eq("tenant_id", tenant_id)
            .limit(500)  # aqui pode ser baixo, pq já é distinct
            .execute()
        )

        rows = getattr(res, "data", None) or []
        vals = []
        for r in rows:
            v = (r or {}).get("almoxarifado")
            if v is None:
                continue
            v = str(v).strip()
            if v:
                vals.append(v)

        return vals  # já vem ordenado pela view

    except Exception as e:
        st.sidebar.warning(f"Erro carregando almoxarifados: {e}")
        return []


def selecionar_empresa_no_login() -> bool:
    """Após autenticar, força seleção do tenant quando houver mais de uma empresa."""

    # 🔥 Se já escolheu empresa, não mostra novamente
    if st.session_state.get("tenant_id"):
        return True

    tenant_opts = st.session_state.get("tenant_options", []) or []

    if not tenant_opts:
        return True

    if len(tenant_opts) == 1:
        st.session_state["tenant_id"] = tenant_opts[0]["tenant_id"]
        _sync_empresa_nome(st.session_state.get("tenant_id"), tenant_opts)
        return True

    st.title("🏢 Selecione a empresa")

    nomes = {t["tenant_id"]: (t.get("nome") or t["tenant_id"]) for t in tenant_opts}

    escolhido = st.selectbox(
        "Empresa",
        options=list(nomes.keys()),
        format_func=lambda x: nomes.get(x, x),
        key="select_tenant_login",
    )

    c1, c2 = st.columns([1, 1])

    if c1.button("Entrar", use_container_width=True):
        st.session_state["tenant_id"] = escolhido
        _sync_empresa_nome(escolhido, tenant_opts)
        st.rerun()

    if c2.button("Sair", use_container_width=True):
        try:
            fazer_logout(supabase_anon)
        except Exception:
            pass
        st.rerun()

    return False



@st.cache_data(ttl=120)
def _cached_carregar_pedidos(_supabase, tenant_id, almoxarifado):
    return carregar_pedidos(_supabase, tenant_id, almoxarifado)

@st.cache_data(ttl=120)
def _cached_carregar_fornecedores(_supabase, tenant_id):
    return carregar_fornecedores(_supabase, tenant_id, incluir_inativos=True)


@st.cache_data(ttl=60)
def _cached_alertas(df_pedidos, df_fornecedores):
    return sa.calcular_alertas(df_pedidos, df_fornecedores)



def _norm_txt(s: str) -> str:
    """Normaliza texto para comparação (remove acentos, espaços, caixa)."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s

def _nav_button_row(page_id: str, group: str, total_alertas: int = 0) -> None:
    """Linha de navegação (HTML link) com destaque ativo via CSS.

    Renderiza como <a href='?nav=...'> para permitir estilo consistente e navegação
    por query param (já tratado no main()).
    """
    current = st.session_state.get("current_page") or "home"
    active = (page_id == current)

    # Badge separado (evita "quebrar" o retângulo quando o label cresce)
    badge_html = ""
    label_text = PAGE_LABELS.get(page_id, page_id)

    if page_id == "alerts":
        try:
            n = int(total_alertas or 0)
        except Exception:
            n = 0
        label_text = "Alertas"
        if n > 0:
            badge_html = f"<span class='fu-nav-badge'>{n}</span>"

    # Mantém grupo apenas para rastreio futuro (logs/telemetria)
    _ = group

    cls = "fu-nav-item fu-nav-item--active" if active else "fu-nav-item"
    st.markdown(
        f"<a class='{cls}' href='?nav={page_id}'><span class='fu-nav-label'>{label_text}</span>{badge_html}</a>",
        unsafe_allow_html=True,
    )


def main():

    # 🔒 Garante estrutura mínima de sessão (evita AttributeError)
    if "usuario" not in st.session_state or not isinstance(st.session_state.get("usuario"), dict):
        st.session_state.usuario = {}
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    # UI System (CSS padronizado): não conflita com o CSS existente
    try:
        apply_ui_theme()
    except Exception:
        pass

    # Sidebar SaaS polish (menus + cards)
    st.markdown('''
    <style>
    /* ==== Sidebar containers (enterprise) ==== */
    section[data-testid="stSidebar"] .stExpander {
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        background: rgba(255,255,255,0.035);
        overflow: hidden;
        margin: 10px 0;
    }
    section[data-testid="stSidebar"] .stExpander > details > summary {
        padding: 12px 14px;
        font-weight: 700;
        color: rgba(255,255,255,0.92);
        background: rgba(255,255,255,0.02);
    }
    section[data-testid="stSidebar"] .stExpander > details[open] > summary {
        background: rgba(255,255,255,0.04);
    }

    /* ==== "Ficha resumo" (top summary card) ==== */
    section[data-testid="stSidebar"] .fu-sum-card{
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 18px;
        background: rgba(255,255,255,0.035);
        padding: 14px 14px 12px 14px;
        margin: 8px 0 12px 0;
        box-shadow: 0 14px 34px rgba(0,0,0,0.30);
    }
    section[data-testid="stSidebar"] .fu-sum-title{
        font-size: 12px;
        font-weight: 750;
        color: rgba(226,232,240,0.92);
        margin: 0 0 8px 0;
    }
    section[data-testid="stSidebar"] .fu-sum-rule{
        height: 2px;
        width: 44px;
        border-radius: 999px;
        background: rgba(239,68,68,0.90);
        margin: 6px 0 12px 0;
    }
    section[data-testid="stSidebar"] .fu-sum-user{
        display:flex;
        align-items:center;
        gap:10px;
        margin-bottom: 10px;
    }
    section[data-testid="stSidebar"] .fu-sum-avatar{
        width: 44px; height: 44px;
        border-radius: 999px;
        display:flex; align-items:center; justify-content:center;
        font-weight: 900;
        color: rgba(15,23,42,0.95);
        background: linear-gradient(135deg, rgba(251,191,36,0.95), rgba(245,158,11,0.95));
        box-shadow: 0 10px 24px rgba(0,0,0,0.30);
        flex: 0 0 auto;
    }
    section[data-testid="stSidebar"] .fu-sum-name{
        font-size: 16px;
        font-weight: 850;
        color: rgba(255,255,255,0.94);
        line-height: 1.05;
        margin:0;
    }
    section[data-testid="stSidebar"] .fu-sum-sub{
        display:flex;
        align-items:center;
        gap:8px;
        margin-top: 4px;
        color: rgba(148,163,184,0.95);
        font-size: 12px;
        font-weight: 650;
    }
    section[data-testid="stSidebar"] .fu-sum-pill{
        font-size: 11px;
        font-weight: 900;
        padding: 3px 8px;
        border-radius: 999px;
        border: 1px solid rgba(239,68,68,0.35);
        background: rgba(239,68,68,0.10);
        color: rgba(255,255,255,0.90);
    }

    /* KPI buttons inside the summary card (estilo ficha, 2x2) */
    section[data-testid="stSidebar"] .fu-sum-kpis div.stButton > button{
        width: 100%;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.08);
        background: rgba(15,23,42,0.35);
        color: rgba(255,255,255,0.95);
        font-weight: 800;
        padding: 14px 12px;
        line-height: 1.15;
        text-align: left;
        box-shadow: 0 8px 20px rgba(0,0,0,0.25);
        white-space: pre-line;
        transition: all 140ms ease;
    }
    section[data-testid="stSidebar"] .fu-sum-kpis div.stButton > button:hover{
        border-color: rgba(239,68,68,0.45);
        background: rgba(239,68,68,0.12);
        transform: translateY(-1px);
    }

    /* ==== Navigation buttons (like your last screenshot) ==== */
    section[data-testid="stSidebar"] .fu-nav-area div.stButton > button {
        width: 100%;
        height: 44px;
        border-radius: 12px;
        padding: 10px 12px;
        border: 1px solid rgba(255,255,255,0.10);
        background: rgba(255,255,255,0.02);
        color: rgba(226,232,240,0.95);
        font-weight: 750;
        text-align: center;
        transition: all 140ms ease;
    }
    section[data-testid="stSidebar"] .fu-nav-area div.stButton > button:hover {
        border-color: rgba(239,68,68,0.45);
        background: rgba(239,68,68,0.10);
        transform: translateY(-1px);
    }
    section[data-testid="stSidebar"] .fu-nav-area div.stButton > button[kind="primary"] {
        border-color: rgba(239,68,68,0.55);
        background: linear-gradient(90deg, rgba(127,29,29,0.90), rgba(153,27,27,0.90));
        color: #fff;
        box-shadow: 0 10px 24px rgba(0,0,0,0.35);
    }

    section[data-testid="stSidebar"] a { color: inherit !important; text-decoration: none !important; }
    </style>
    ''', unsafe_allow_html=True)


    # Navegação via query param (usado pelos ícones monocromáticos da sidebar compacta)
    nav = st.query_params.get("nav")
    if nav:
        try:
            nav = str(nav)
        except Exception:
            nav = None
        if nav:
            st.session_state.current_page = nav
            try:
                del st.query_params["nav"]
            except Exception:
                pass
            st.rerun()

    # Filtro de alertas via query param (usado pelos cards clicáveis do resumo)
    af = st.query_params.get("af")
    if af is not None:
        try:
            af = str(af)
        except Exception:
            af = None
        if af:
            allowed = {"atrasados", "criticos", "vencendo", "all"}
            if af in allowed:
                st.session_state["alerts_filter"] = None if af == "all" else af
            try:
                del st.query_params["af"]
            except Exception:
                pass




    qp_page = st.query_params.get("page")
    if qp_page:
        st.session_state["fu_route"] = qp_page

    route = st.session_state.get("fu_route") or "landing"



    # 🧪 Debug rápido (ative com ?debug=1)
    if st.query_params.get("debug") in ("1", "true", "yes"):
        st.sidebar.markdown("### 🧪 Debug (sessão)")
        st.sidebar.json({
            "route": st.session_state.get("fu_route"),
            "page_param": st.query_params.get("page"),
            "auth_ok": bool(verificar_autenticacao()),
            "tenant_id": st.session_state.get("tenant_id"),
            "tenant_opts_len": len(st.session_state.get("tenant_options", []) or []),
            "has_tokens": bool(st.session_state.get("auth_access_token")),
            "usuario_keys": list((st.session_state.get("usuario") or {}).keys()) if isinstance(st.session_state.get("usuario"), dict) else str(type(st.session_state.get("usuario"))),
        })
    # Se já estiver autenticado, não mantenha "page=login" (isso prende o app no modo login em todo rerun)
    if verificar_autenticacao():
        if st.query_params.get("page") in ("login", "landing"):
            try:
                del st.query_params["page"]
            except Exception:
                pass
            st.session_state["fu_route"] = "app"
            route = "app"

    if route == "first_access":
        from first_access import render_first_access
        render_first_access(supabase_anon)
        st.stop()

    if route == "reset_request":
        from reset_password import render_request_reset
        render_request_reset(supabase_anon)
        st.stop()

    # Se veio de um link de recovery (redefinição), renderiza a tela automaticamente
    if st.session_state.get("auth_flow_type") == "recovery":
        from reset_password import render_reset_password
        render_reset_password(supabase_anon)
        st.stop()

    # 🌐 Landing pública (antes do login)
    # Padrão para usuários não autenticados: landing
    if (route == "landing") and (not verificar_autenticacao()):
        render_landing()
        st.stop()

    # Rota explícita de login (antes do app)
    if not verificar_autenticacao():
        st.session_state["fu_route"] = "login"
        if st.query_params.get("page") != "login":
            st.query_params["page"] = "login"

        st.markdown(
            '''
            <style>
              /* Esconde espaços extras do Streamlit em telas pequenas */
              section.main > div { padding-top: 1.5rem; }
              .block-container { max-width: 980px; }

              /* Card clean */
              .fu-auth-wrap{ max-width: 820px; margin: 0 auto; }
              .fu-card{
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 22px;
                padding: 22px 22px 18px 22px;
                background: rgba(255,255,255,0.035);
                box-shadow: 0 14px 40px rgba(0,0,0,0.35);
              }
              .fu-header{
                display:flex;
                align-items:center;
                justify-content:space-between;
                gap:12px;
                margin-bottom: 10px;
              }
              .fu-brand{
                display:flex;
                align-items:center;
                gap:10px;
              }
              .fu-brand h1{
                font-size: 1.35rem;
                margin:0;
                padding:0;
                font-weight: 750;
              }
              .fu-brand p{
                margin:2px 0 0 0;
                color: rgba(255,255,255,0.62);
                font-size: 0.92rem;
              }
              .fu-chip{
                font-size: 0.82rem;
                padding: 6px 10px;
                border-radius: 999px;
                border: 1px solid rgba(255,255,255,0.10);
                color: rgba(255,255,255,0.70);
                background: rgba(255,255,255,0.035);
              }
              /* Links discretos */
              .fu-links{
                display:flex;
                gap:14px;
                align-items:center;
                font-size:0.90rem;
                opacity:0.88;
              }
              .fu-links a{
                text-decoration:none;
                color: rgba(255,255,255,0.72);
                padding: 4px 8px;
                border-radius: 10px;
                transition: all 120ms ease-in-out;
              }
              .fu-links a:hover{
                color: rgba(255,255,255,0.92);
                background: rgba(255,255,255,0.06);
              }
              .fu-sep{ color: rgba(255,255,255,0.22); }
              /* Botões mais “SaaS” */
              div.stButton > button{ border-radius: 14px; }
              @media (max-width: 720px){
                .fu-header{ flex-direction:column; align-items:flex-start; }
                .fu-links{ justify-content:flex-start; flex-wrap:wrap; }
              }
            </style>
            ''',
            unsafe_allow_html=True,
        )

        # Modal state
        if "fu_magic_modal_open" not in st.session_state:
            st.session_state["fu_magic_modal_open"] = False

        def _open_magic_modal():
            st.session_state["fu_magic_modal_open"] = True

        st.markdown('<div class="fu-auth-wrap"><div class="fu-card">', unsafe_allow_html=True)

        # Header (compacto)
        st.markdown(
            '''
            <div class="fu-header">
              <div class="fu-brand">
                <div style="font-size:1.35rem;">📦</div>
                <div>
                  <h1>Follow-up de Compras</h1>
                  <p>Acesse sua conta para continuar.</p>
                </div>
              </div>
              <span class="fu-chip">Secure • Multiempresa</span>
            </div>
            ''',
            unsafe_allow_html=True,
        )

        # Form principal (e-mail + senha)
        if supabase_anon is None:
            st.error("Supabase (anon) não inicializou. Verifique seus secrets/env no Streamlit Cloud.")
        else:
            exibir_login(supabase_anon)

        # Linha de ações (links + botão link mágico)
        left, right = st.columns([3, 2])
        with left:
            st.markdown(
                '''
                <div class="fu-links">
                  <a href="?page=reset_request">Esqueci minha senha</a>
                  <span class="fu-sep">•</span>
                  <a href="?page=first_access">Primeiro acesso</a>
                </div>
                ''',
                unsafe_allow_html=True,
            )
        with right:
            if st.button("Entrar por link", use_container_width=True):
                _open_magic_modal()

        st.markdown('</div></div>', unsafe_allow_html=True)

        # Modal (dialog) — fallback para expander se necessário
        if st.session_state.get("fu_magic_modal_open"):
            try:
                @st.dialog("Entrar por link (sem senha)")
                def _magic_dialog():
                    st.caption("Digite seu e-mail e enviaremos um link de acesso.")
                    email_magic = st.text_input("E-mail", key="magic_email_modal")

                    csend, ccancel = st.columns([1, 1])
                    with csend:
                        enviar = st.button("Enviar link", type="primary", use_container_width=True)
                    with ccancel:
                        cancelar = st.button("Cancelar", use_container_width=True)

                    if cancelar:
                        st.session_state["fu_magic_modal_open"] = False
                        st.rerun()

                    if enviar:
                        if not email_magic or "@" not in email_magic:
                            st.error("Informe um e-mail válido.")
                            st.stop()
                        try:
                            supabase_anon.auth.sign_in_with_otp({
                                "email": email_magic,
                                "options": {
                                    "email_redirect_to": "https://followupdef.streamlit.app/?auth_callback=1"
                                }
                            })
                            st.success("Link enviado! Verifique seu e-mail.")
                            st.session_state["fu_magic_modal_open"] = False
                        except Exception as e:
                            st.error(f"Falha ao enviar link: {e}")

                _magic_dialog()
            except Exception:
                with st.expander("Entrar por link (sem senha)"):
                    email_magic = st.text_input("E-mail", key="magic_email_fallback")
                    if st.button("Enviar link de acesso", use_container_width=True):
                        try:
                            supabase_anon.auth.sign_in_with_otp({
                                "email": email_magic,
                                "options": {
                                    "email_redirect_to": "https://followupdef.streamlit.app/?auth_callback=1"
                                }
                            })
                            st.success("Link enviado! Verifique seu e-mail.")
                        except Exception as e:
                            st.error(f"Falha ao enviar link: {e}")

        return

    # Seleção obrigatória de empresa (quando houver mais de uma)
    if not selecionar_empresa_no_login():
        return

    # Client do usuário autenticado (RLS ativo)
    # Renova JWT automaticamente se expirou

    if _jwt_expirou():

        ok = _refresh_session()

        if not ok:

            st.warning("Sessão expirada. Faça login novamente.")

            try:

                fazer_logout(supabase_anon)

            except Exception:

                pass

            st.rerun()


    supabase = get_supabase_user_client(st.session_state.auth_access_token)
    st.session_state["supabase_client"] = supabase
    handle_auth_callback(supabase)
    # --- Garantir user_id na sessão (necessário para criado_por NOT NULL) ---
    try:
        u = supabase.auth.get_user()
        uid = getattr(getattr(u, "user", None), "id", None) or getattr(u, "id", None)
        if uid:
            st.session_state["user_id"] = str(uid)
            if isinstance(st.session_state.get("usuario"), dict):
                st.session_state["usuario"]["user_id"] = str(uid)
    except Exception:
        # fallback: decodifica JWT (sub)
        try:
            tok = st.session_state.get("auth_access_token") or ""
            parts = tok.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))
                uid = payload.get("sub")
                if uid:
                    st.session_state["user_id"] = str(uid)
                    if isinstance(st.session_state.get("usuario"), dict):
                        st.session_state["usuario"]["user_id"] = str(uid)
        except Exception:
            pass
    # Super Admin (SaaS)
    try:
        st.session_state.is_superadmin = bool(is_superadmin(supabase))
    except Exception:
        st.session_state.is_superadmin = False
    # Seleção de empresa (se o usuário tiver mais de uma)
    tenant_opts = st.session_state.get("tenant_options", []) or []
    tenant_id = st.session_state.get("tenant_id")

    # Define padrão
    if not tenant_id and tenant_opts:
        tenant_id = tenant_opts[0]["tenant_id"]
        st.session_state.tenant_id = tenant_id
        _sync_empresa_nome(tenant_id, tenant_opts)

    # Se o usuário tiver mais de uma empresa, permite escolher
    if tenant_opts and len(tenant_opts) > 1:
        with st.sidebar:
            nomes = {t["tenant_id"]: (t.get("nome") or t["tenant_id"]) for t in tenant_opts}
            current = st.session_state.get("tenant_id") or tenant_opts[0]["tenant_id"]
            ids = list(nomes.keys())
            idx = ids.index(current) if current in ids else 0
            escolhido = st.selectbox(
                "Empresa",
                options=ids,
                format_func=lambda x: nomes.get(x, x),
                index=idx,
            )

            if escolhido != current:
                st.session_state.tenant_id = escolhido
                _sync_empresa_nome(escolhido, tenant_opts)
                # atualiza perfil conforme empresa selecionada
                role = next((t.get("role") for t in tenant_opts if t.get("tenant_id") == escolhido), "user")
                if "usuario" in st.session_state and isinstance(st.session_state.usuario, dict):
                    st.session_state.usuario["tenant_id"] = escolhido
                    st.session_state.usuario["perfil"] = role
                st.rerun()

    tenant_id = st.session_state.get("tenant_id") or tenant_id
    _sync_empresa_nome(tenant_id, tenant_opts)
    if not tenant_id:
        st.error("Não foi possível determinar sua empresa (tenant).")
        return

    # ===== Contexto global: Almoxarifado (filtro global) =====
    if "almox_ctx" not in st.session_state:
        st.session_state["almox_ctx"] = "Todos"

    # ===== Filtro global por Almoxarifado (contexto do app) =====
    # Mostra apenas quando a sidebar está expandida (evita “prensar” no modo compacto/mobile).
    if True:
        with st.sidebar:
            st.markdown("### Contexto")
            almox_list = _fetch_almoxarifados_tenant(supabase, tenant_id)
            options_almox = ["Todos"] + almox_list

            current_almox = st.session_state.get("almox_ctx") or "Todos"
            if current_almox not in options_almox:
                current_almox = "Todos"
                st.session_state["almox_ctx"] = "Todos"

            selecionado = st.selectbox(
                "Almoxarifado",
                options=options_almox,
                index=options_almox.index(current_almox),
                help="Filtro global: ao selecionar, o sistema passa a mostrar apenas pedidos deste almoxarifado (quando disponível no catálogo).",
            )

            if selecionado != st.session_state.get("almox_ctx"):
                st.session_state["almox_ctx"] = selecionado
                st.rerun()

    # 🔐 Primeiro acesso: força troca de senha (se implementado em src.core.auth)
    try:
        from src.core.auth import verificar_primeiro_acesso, tela_troca_senha_primeiro_acesso
        if verificar_primeiro_acesso(supabase):
            tela_troca_senha_primeiro_acesso(supabase)
            return
    except Exception:
        # Se ainda não implementou as funções, segue o fluxo normal
        pass

    with st.spinner("🔄 Carregando pedidos..."):
        df_pedidos = _cached_carregar_pedidos(supabase, tenant_id, st.session_state.get('almox_ctx'))
        st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S")


        # Aplica contexto global de almoxarifado (se o dataframe já contiver a coluna).
        # Comparação normalizada (remove acentos, espaços, caixa) para evitar divergências
        # como "IRRIGAÇÃO" vs "IRRIGACAO".
        almox_ctx = st.session_state.get("almox_ctx") or "Todos"
        if almox_ctx != "Todos":
            for col in ("almoxarifado", "Almoxarifado"):
                if col in df_pedidos.columns:
                    alvo = _norm_txt(almox_ctx)
                    serie = df_pedidos[col].astype(str).fillna("").map(_norm_txt)
                    df_pedidos = df_pedidos[serie == alvo]
                    break
    with st.spinner("🔄 Carregando fornecedores..."):
        df_fornecedores = _cached_carregar_fornecedores(supabase, tenant_id)

    alertas = _cached_alertas(df_pedidos, df_fornecedores)
    total_alertas = int(alertas.get("total", 0) or 0)
    alertas_label = _label_alertas(total_alertas)
    atrasados = _safe_len(alertas.get("pedidos_atrasados"))
    criticos = _safe_len(alertas.get("pedidos_criticos"))
    vencendo = _safe_len(alertas.get("pedidos_vencendo"))

    _industrial_sidebar_css()

    # ===== Sidebar topo + menus (SEM botão sair/creditos aqui) =====
    with st.sidebar:

        usuario = st.session_state.get("usuario") or {}
        perfil = (usuario.get("perfil") or "").lower()
        is_admin = perfil == "admin"

        if True:
            usuario = st.session_state.get("usuario") or {}
            nome = usuario.get("nome", "Usuário")
            perfil = (usuario.get("perfil") or "user").lower()
            avatar_url = usuario.get("avatar_url")

            # saudação
            hora = datetime.now(ZoneInfo("America/Fortaleza")).hour
            if hora < 12:
                saudacao = "Bom dia"
            elif hora < 18:
                saudacao = "Boa tarde"
            else:
                saudacao = "Boa noite"

            # badge por perfil
            if perfil == "admin":
                badge_cor = "#ef4444"
            elif perfil == "buyer":
                badge_cor = "#3b82f6"
            else:
                badge_cor = "#10b981"


            # ── Ficha de resumo (topo) ──────────────────────────────────────────
            st.markdown(
                f'''
                <div class="fu-sum-card">
                  <div class="fu-sum-title">Sistema de Follow-Up</div>
                  <div class="fu-sum-rule"></div>

                  <div class="fu-sum-user">
                    <div class="fu-sum-avatar">{(nome[:1].upper() if nome else "U")}</div>
                    <div>
                      <div class="fu-sum-name">{nome}</div>
                      <div class="fu-sum-sub">
                        <span class="fu-sum-pill">{perfil.upper()}</span>
                        <span>{saudacao}</span>
                      </div>
                    </div>
                  </div>
                ''',
                unsafe_allow_html=True,
            )

            st.markdown('<div class="fu-sum-kpis">', unsafe_allow_html=True)

            # KPIs estilo "ficha" (2x2) — clicáveis, sem abrir nova guia
            c1, c2 = st.columns(2, gap="small")

            with c1:
                if st.button(f"⚠️  Atrasados\n{atrasados}", use_container_width=True, key="kpi_atrasados"):
                    st.session_state.current_page = "alerts"
                    st.session_state["alerts_filter"] = "atrasados"
                    st.rerun()

                if st.button(f"⏳  Vencendo\n{vencendo}", use_container_width=True, key="kpi_vencendo"):
                    st.session_state.current_page = "alerts"
                    st.session_state["alerts_filter"] = "vencendo"
                    st.rerun()

            with c2:
                if st.button(f"🚨  Críticos\n{criticos}", use_container_width=True, key="kpi_criticos"):
                    st.session_state.current_page = "alerts"
                    st.session_state["alerts_filter"] = "criticos"
                    st.rerun()

                if st.button(f"🔔  Alertas\n{total_alertas}", use_container_width=True, key="kpi_total"):
                    st.session_state.current_page = "alerts"
                    st.session_state["alerts_filter"] = None
                    st.rerun()

            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)  # end fu-sum-card


            # 🔎 Busca rápida (navegação)
            busca = st.text_input(
                "🔎 Busca rápida",
                key="global_search_sidebar",
                placeholder="Ex.: dashboard, alertas, ficha, mapa..."
            )

            if busca:
                termo = busca.strip().lower()

                mapa_paginas = {
                    "dash": "Dashboard",
                    "dashboard": "Dashboard",
                    "alert": "alerts",
                    "notific": "alerts",
                    "consulta": "Consultar Pedidos",
                    "pedido": "Consultar Pedidos",
                    "ficha": "Ficha de Material",
                    "material": "Ficha de Material",
                    "gest": "Gestão de Pedidos",
                    "mapa": "Mapa Geográfico",
                    "relat": "Relatórios",
                    "relatorio": "Relatórios",
                    "import": "Importações",
                    "importacao": "Importações",
                    "usu": "Gestão de Usuários",
                    "usuario": "Gestão de Usuários",
                    "backup": "Backup",
                }

                sugestoes = []
                for chave, destino in mapa_paginas.items():
                    if chave in termo:
                        sugestoes.append(destino)

                sugestoes = list(dict.fromkeys(sugestoes))

                if sugestoes:
                    st.caption("Sugestões:")
                    for destino in sugestoes[:8]:
                        if st.button(f"➡️ Ir para {destino}", key=f"goto_{destino}", use_container_width=True):
                            st.session_state.current_page = LEGACY_PAGE_TO_ID.get(destino, destino)
                            st.rerun()

            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

            usuario = st.session_state.get("usuario") or {}
            perfil = (usuario.get("perfil") or "").lower()
            is_admin = perfil == "admin"
                                    # ✅ Navegação (colapsável + padrão SaaS — sem links azuis/HTML)
            if "current_page" not in st.session_state:
                st.session_state.current_page = "home"

            pagina_atual = st.session_state.get("current_page") or "home"

            def _nav_btn(pid: str, label: str) -> None:
                active = (st.session_state.get("current_page") == pid)
                btn_type = "primary" if active else "secondary"
                if st.button(label, use_container_width=True, key=f"nav_{pid}", type=btn_type):
                    if pid != st.session_state.get("current_page"):
                        st.session_state.current_page = pid
                        st.rerun()

            dashboards = ["dashboard", "map", "alerts"]
            operacoes = ["orders_search", "material_sheet", "orders_manage"]
            dados = ["reports"] + (["catalog_materials", "imports"] if is_admin else [])
            conta = (["users", "profile", "backup", "dept_almox_config"] if is_admin else ["profile"])
            if (not is_admin) and bool(st.session_state.get("is_superadmin")):
                conta = ["profile", "dept_almox_config"]

            superadmin_pages: list[str] = []
            if bool(st.session_state.get("is_superadmin")):
                superadmin_pages = ["saas_admin","observability","tenant_health","tenant_ranking","audit_logs","exec_metrics","snapshots"]

            st.markdown('<div class="fu-nav-area">', unsafe_allow_html=True)
            _nav_btn("home", "Início")

            with st.expander("Dashboards", expanded=(pagina_atual in dashboards)):
                _nav_btn("dashboard", "Dashboard")
                _nav_btn("map", "Mapa")
                _nav_btn("alerts", f"Alertas ({total_alertas})" if total_alertas else "Alertas")

            with st.expander("Operações", expanded=(pagina_atual in operacoes)):
                _nav_btn("orders_search", "Consultar pedidos")
                _nav_btn("material_sheet", "Ficha de material")
                _nav_btn("orders_manage", "Gestão de pedidos")

            with st.expander("Dados", expanded=(pagina_atual in dados)):
                _nav_btn("reports", "Relatórios")
                if is_admin:
                    _nav_btn("catalog_materials", "Catálogo de Materiais")
                    _nav_btn("imports", "Importações")

            with st.expander("Conta", expanded=(pagina_atual in conta)):
                for _pid in conta:
                    _nav_btn(_pid, PAGE_LABELS.get(_pid, _pid))

            if superadmin_pages:
                with st.expander("Superadmin", expanded=(pagina_atual in superadmin_pages)):
                    for _pid in superadmin_pages:
                        _nav_btn(_pid, PAGE_LABELS.get(_pid, _pid))

            st.markdown('</div>', unsafe_allow_html=True)


    # Página atual (fonte de verdade)
    pagina = st.session_state.current_page
    # Normaliza (caso ainda exista valor antigo por label/emoji)
    if isinstance(pagina, str) and pagina.startswith("Alertas"):
        pagina = "alerts"
        st.session_state.current_page = pagina
    elif "LEGACY_PAGE_TO_ID" in globals() and pagina in LEGACY_PAGE_TO_ID:
        pagina = LEGACY_PAGE_TO_ID[pagina]
        st.session_state.current_page = pagina

    # ── Topbar: breadcrumb + ações rápidas ───────────────────────────────────
    pagina_label_display = PAGE_LABELS.get(st.session_state.get("current_page","home"), "—")
    _now_fo = datetime.now(ZoneInfo("America/Fortaleza"))
    ts_display = _now_fo.strftime("%H:%M") + " (Fortaleza)"
    ts_html = f'<span class="fu-topbar-ts">⟳ {ts_display}</span>' if ts_display else ""
    st.markdown(
        f'''<div class="fu-topbar">
          <div class="fu-topbar-left">
            <span class="fu-topbar-page">Follow-up de Compras</span>
            <span class="fu-topbar-sep">/</span>
            <span class="fu-topbar-sub">{pagina_label_display}</span>
          </div>
          <div class="fu-topbar-right">
            {ts_html}
          </div>
        </div>''',
        unsafe_allow_html=True,
    )

    # Quick-action buttons (compactos, direita alinhada)
    _qa_spacer, _qa1, _qa2, _qa3 = st.columns([7, 1.1, 1.1, 1.1])
    with _qa1:
        if st.button("🔄 Atualizar", use_container_width=True, key="qa_refresh", help="Limpa cache e recarrega"):
            st.cache_data.clear()
            st.rerun()
    with _qa2:
        if st.button("📤 Relatórios", use_container_width=True, key="qa_export", help="Relatórios / Exportação"):
            st.session_state.current_page = "reports"
            st.session_state["hub_reports_force"] = "Exportação"
            st.rerun()
    with _qa3:
        if st.button("➕ Novo", use_container_width=True, key="qa_new", help="Criar novo pedido"):
            st.session_state.current_page = "orders_manage"
            st.rerun()

    try:
        with obs.time_block(f"page.{pagina}"):
            if pagina == "home":
                usuario = st.session_state.get("usuario") or {}
                exibir_home(alertas, usuario_nome=usuario.get("nome", "Usuário"))
            elif pagina == "dashboard":
                exibir_dashboard(supabase)
            elif pagina == "alerts":
                sa.exibir_painel_alertas(alertas, formatar_moeda_br)
            elif pagina == "orders_search":
                exibir_consulta_pedidos(supabase)
            elif pagina == "material_sheet":
                exibir_ficha_material(supabase)
            elif pagina == "orders_manage":
                _call_page('src.ui.gestao_pedidos','exibir_gestao_pedidos', supabase)
            elif pagina == "map":
                exibir_mapa(supabase)
            elif pagina == "users":
                exibir_gestao_usuarios(supabase)
            elif pagina == "backup":
                ba.realizar_backup_manual(supabase)
            elif pagina == "catalog_materials":
                from src.ui.catalogo_materiais import exibir_catalogo_materiais
                exibir_catalogo_materiais(supabase, tenant_id=tenant_id)
            elif pagina == "reports_whatsapp":
                usuario = st.session_state.get("usuario") or {}
                render_relatorios_whatsapp(
                    supabase,
                    tenant_id=tenant_id,
                    created_by=usuario.get("id"),
                )
            elif pagina == "reports_gerenciais":
                render_relatorios_gerenciais(
                    supabase,
                    tenant_id=tenant_id,
                )
            elif pagina == "reports":
                from src.ui.relatorios_hub import exibir_relatorios_hub
                exibir_relatorios_hub(supabase_user=supabase, supabase_admin=supabase_admin, tenant_id=tenant_id)
            elif pagina == "imports":
                from src.ui.importacoes_hub import exibir_importacoes_hub
                exibir_importacoes_hub(supabase_user=supabase, supabase_admin=supabase_admin, tenant_id=tenant_id)
            elif pagina == "profile":
                from src.ui.perfil import exibir_perfil
                exibir_perfil(supabase)
            elif pagina == "dept_almox_config":
                from src.ui.config_depto_almox import exibir_config_depto_almox
                usuario = st.session_state.get("usuario") or {}
                perfil = (usuario.get("perfil") or "").lower()
                if perfil != "admin" and not bool(st.session_state.get("is_superadmin")):
                    st.error("Acesso restrito.")
                else:
                    exibir_config_depto_almox(supabase_user=supabase, supabase_admin=supabase_admin, tenant_id=tenant_id)
            elif pagina == "saas_admin":
                exibir_admin_saas(supabase)
            elif pagina == "observability":
                from src.ui.observabilidade import exibir_observabilidade
                if not bool(st.session_state.get("is_superadmin")):
                    st.error("Acesso restrito.")
                elif supabase_admin is None:
                    st.error("Supabase admin não inicializado (SERVICE ROLE).")
                else:
                    exibir_observabilidade(supabase_admin=supabase_admin, supabase_user=supabase)
            elif pagina == "tenant_health":
                from src.ui.saude_tenants import exibir_saude_tenants
                if not bool(st.session_state.get("is_superadmin")):
                    st.error("Acesso restrito.")
                elif supabase_admin is None:
                    st.error("Supabase admin não inicializado (SERVICE ROLE).")
                else:
                    exibir_saude_tenants(supabase_admin)
            elif pagina == "tenant_ranking":
                from src.ui.ranking_tenants import exibir_ranking_tenants
                if not bool(st.session_state.get("is_superadmin")):
                    st.error("Acesso restrito.")
                elif supabase_admin is None:
                    st.error("Supabase admin não inicializado (SERVICE ROLE).")
                else:
                    exibir_ranking_tenants(supabase_admin)
            elif pagina == "audit_logs":
                from src.ui.auditoria_avancada import exibir_auditoria_avancada
                if not bool(st.session_state.get("is_superadmin")):
                    st.error("Acesso restrito.")
                elif supabase_admin is None:
                    st.error("Supabase admin não inicializado (SERVICE ROLE).")
                else:
                    exibir_auditoria_avancada(supabase_admin)
            elif pagina == "exec_metrics":
                from src.ui.metricas_executivas import exibir_metricas_executivas
                if not bool(st.session_state.get("is_superadmin")):
                    st.error("Acesso restrito.")
                elif supabase_admin is None:
                    st.error("Supabase admin não inicializado (SERVICE ROLE).")
                else:
                    exibir_metricas_executivas(supabase_admin)
            elif pagina == "snapshots":
                from src.ui.snapshots import exibir_snapshots
                if not bool(st.session_state.get("is_superadmin")):
                    st.error("Acesso restrito.")
                elif supabase_admin is None:
                    st.error("Supabase admin não inicializado (SERVICE ROLE).")
                else:
                    exibir_snapshots(supabase_admin)
            else:
                # fallback
                st.session_state.current_page = "home"
                st.rerun()

    except Exception as e:
        usuario = st.session_state.get("usuario") or {}
        obs.log_exception(
            e,
            event="page_render_error",
            context={
                "page": pagina,
                "tenant_id": st.session_state.get("tenant_id"),
                "user_id": usuario.get("id"),
                "email": usuario.get("email"),
            },
            supabase_admin=supabase_admin,
        )
        st.error("Ocorreu um erro ao renderizar esta página. O evento foi registrado em Observabilidade.")
        st.exception(e)

    # ===== Rodapé da sidebar: sempre depois dos filtros =====
    with st.sidebar:
        _sidebar_footer(supabase)


if __name__ == "__main__":
    main()
