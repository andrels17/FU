import streamlit as st
from auth_flows import handle_auth_callback

import json
import base64
import textwrap
import streamlit.components.v1 as components
st.set_page_config(
    page_title="Sistema de Follow-Up",
    layout="wide",
    page_icon="📊",
)

from datetime import datetime, timezone

import src.services.sistema_alertas as sa
import src.services.backup_auditoria as ba
from src.repositories.fornecedores import carregar_fornecedores
from src.core.config import configure_page  # noqa: F401
from src.core.db import init_supabase_admin, init_supabase_anon, get_supabase_user_client

# Cliente ANON (RLS + Auth)
supabase_anon = init_supabase_anon()
# ✅ Consome links do Supabase (invite/magic/recovery) antes de checar login
handle_auth_callback(supabase_anon)


from src.core.auth import verificar_autenticacao, exibir_login, fazer_logout
from src.repositories.pedidos import carregar_pedidos
from src.utils.formatting import formatar_moeda_br

from src.ui.dashboard import exibir_dashboard
from src.ui.mapa import exibir_mapa
from src.ui.consulta import exibir_consulta_pedidos
from src.ui.gestao_pedidos import exibir_gestao_pedidos
from src.ui.ficha_material_page import exibir_ficha_material
from src.ui.gestao_usuarios import exibir_gestao_usuarios
from src.ui.admin_saas import exibir_admin_saas
from src.ui.landing_public import render_landing
from src.ui.home import exibir_home
from src.core.superadmin import is_superadmin


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
    """Tema corporativo industrial + barra lateral laranja no item ativo + animações suaves."""
    st.markdown(
        textwrap.dedent(r"""
        <style>
            :root {
                --fu-bg: #0b1220;
                --fu-card: rgba(255,255,255,0.06);
                --fu-border: rgba(255,255,255,0.10);
                --fu-text: rgba(255,255,255,0.92);
                --fu-muted: rgba(255,255,255,0.72);
                --fu-accent: #f59e0b;      /* industrial amber */
                --fu-accent2: #fb923c;     /* orange */
            }

            section[data-testid="stSidebar"] {
                background:
                    radial-gradient(1100px 420px at 15% 0%, rgba(245,158,11,0.12), transparent 55%),
                    radial-gradient(900px 380px at 80% 18%, rgba(59,130,246,0.10), transparent 55%),
                    var(--fu-bg);
            }

            section[data-testid="stSidebar"] > div { padding-top: 0.8rem; }

            .fu-card {
                background: var(--fu-card);
                border: 1px solid var(--fu-border);
                border-radius: 14px;
                padding: 12px 12px;
                margin-bottom: 10px;
                color: var(--fu-text);
                box-shadow: 0 10px 25px rgba(0,0,0,0.25);
            }

            .fu-user-label { font-size: 12px; opacity: .8; margin: 0 0 4px 0; }
            .fu-user-name { font-size: 16px; font-weight: 800; margin: 0; letter-spacing: .2px; }
            .fu-user-role { font-size: 12px; opacity: .75; margin: 4px 0 0 0; }

            /* Mini KPIs */
            .fu-kpi-row { display:flex; gap:8px; margin: 6px 0 12px 0; }
            .fu-kpi {
                flex: 1;
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
                padding: 10px 10px;
            }
            .fu-kpi-title { font-size: 11px; opacity: .78; margin: 0 0 2px 0; }
            .fu-kpi-value { font-size: 18px; font-weight: 900; margin: 0; }

            /* Menu radio */
            div[role="radiogroup"] label {
                padding: 10px 12px;
                border-radius: 12px;
                margin-bottom: 6px;
                transition: transform .12s ease, background-color .12s ease, border .12s ease;
                border: 1px solid transparent;
            }
            div[role="radiogroup"] label:hover {
                background-color: rgba(255,255,255,0.06);
                transform: translateX(2px);
                border: 1px solid rgba(245,158,11,0.22);
            }

            /* Item ativo: barra laranja + glow SaaS */
            div[role="radiogroup"] input:checked + div {
                background: linear-gradient(135deg, rgba(245,158,11,0.22), rgba(255,255,255,0.04));
                border-radius: 12px;
                box-shadow:
                  inset 4px 0 0 var(--fu-accent),
                  0 0 0 1px rgba(245,158,11,0.18),
                  0 10px 26px rgba(245,158,11,0.12);
            }

            /* Expanders */
            details {
                background: rgba(255,255,255,0.02);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 14px;
                padding: 6px 10px;
                margin-bottom: 10px;
            }
            summary { cursor: pointer; font-weight: 900; color: var(--fu-text); }

            /* Destaque do grupo ativo (wrapper dentro do expander) */
            .fu-expander-active {
                border: 1px solid rgba(245,158,11,0.35);
                background: linear-gradient(135deg, rgba(245,158,11,0.07), rgba(255,255,255,0.02));
                border-radius: 14px;
                padding: 6px 6px 2px 6px;
                margin-top: 6px;
            }

            /* Botões */
            button[kind="secondary"] {
                background-color: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.12);
                transition: transform .08s ease;
            }
            button[kind="secondary"]:hover { transform: translateY(-1px); }

            .fu-bar {
                height: 3px;
                border-radius: 999px;
                background: linear-gradient(90deg, var(--fu-accent), rgba(251,146,60,0.0));
                margin: 10px 0 8px 0;
                opacity: .9;
            }
        </style>
        """),
        unsafe_allow_html=True,
    )

def _label_alertas(total_alertas: int) -> str:
    if total_alertas and total_alertas > 0:
        return f"🔔 Alertas e Notificações  🔴 ({int(total_alertas)})"
    return "🔔 Alertas e Notificações"


def _sidebar_footer(supabase_client) -> None:
    """Renderiza Sair + créditos (sempre por último na sidebar)."""
    st.markdown("---")
    if st.button("🚪 Sair", use_container_width=True, key="btn_logout_sidebar"):
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

    st.markdown(
        """
        <div style="font-size:11px; opacity:0.6; margin-top:10px;">
            © Follow-up de Compras v3.0<br>
            Criado por André Luis e Yasmim Lima
        </div>
        """,
        unsafe_allow_html=True,
    )


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

    if c1.button("✅ Entrar", use_container_width=True):
        st.session_state["tenant_id"] = escolhido
        st.rerun()

    if c2.button("🚪 Sair", use_container_width=True):
        try:
            fazer_logout(supabase_anon)
        except Exception:
            pass
        st.rerun()

    return False



@st.cache_data(ttl=120)
def _cached_carregar_pedidos(_supabase, tenant_id):
    return carregar_pedidos(_supabase, tenant_id)

@st.cache_data(ttl=120)
def _cached_carregar_fornecedores(_supabase, tenant_id):
    return carregar_fornecedores(_supabase, tenant_id, incluir_inativos=True)


def main():

    # 🔀 Rotas (sem multipage) — use:
    # - Primeiro acesso: ?page=first_access
    # - Esqueci a senha: ?page=reset_request
    # -----------------------------
    # Roteamento resiliente (state-first)
    # -----------------------------
    # O Streamlit faz reruns frequentes. Em alguns ambientes, st.query_params
    # pode ficar indisponível por 1 execução. Para evitar voltar para a landing
    # indevidamente, o roteamento principal usa session_state como fonte de verdade.

    qp_page = st.query_params.get("page")
    if qp_page:
        st.session_state["fu_route"] = qp_page

    route = st.session_state.get("fu_route") or "landing"

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
    if (route == "login") and (not verificar_autenticacao()):
        st.session_state["fu_route"] = "login"
        if st.query_params.get("page") != "login":
            st.query_params["page"] = "login"

    if not verificar_autenticacao():
        # Se chegou aqui sem auth, a única tela interna permitida é o login.
        # Mantemos a rota no session_state (fonte de verdade) e no URL, sem clear().
        st.session_state["fu_route"] = "login"
        if st.query_params.get("page") != "login":
            st.query_params["page"] = "login"

        # =========================
        # 🎨 Login (SaaS clean)
        # =========================
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
                background: rgba(255,255,255,0.03);
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
                background: rgba(255,255,255,0.03);
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
        exibir_login(supabase_anon)

        # Linha de ações (links + botão link mágico)
        left, right = st.columns([3, 2])
        with left:
            st.markdown(
                '''
                <div class="fu-links">
                  <a href="?page=reset_request">🔑 Esqueci minha senha</a>
                  <span class="fu-sep">•</span>
                  <a href="?page=first_access">👋 Primeiro acesso</a>
                </div>
                ''',
                unsafe_allow_html=True,
            )
        with right:
            if st.button("📩 Entrar por link", use_container_width=True):
                _open_magic_modal()

        st.markdown('</div></div>', unsafe_allow_html=True)

        # Modal (dialog) — fallback para expander se necessário
        if st.session_state.get("fu_magic_modal_open"):
            try:
                @st.dialog("📩 Entrar por link (sem senha)")
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
                            st.success("✅ Link enviado! Verifique seu e-mail.")
                            st.session_state["fu_magic_modal_open"] = False
                        except Exception as e:
                            st.error(f"❌ Falha ao enviar link: {e}")

                _magic_dialog()
            except Exception:
                with st.expander("📩 Entrar por link (sem senha)"):
                    email_magic = st.text_input("E-mail", key="magic_email_fallback")
                    if st.button("Enviar link de acesso", use_container_width=True):
                        try:
                            supabase_anon.auth.sign_in_with_otp({
                                "email": email_magic,
                                "options": {
                                    "email_redirect_to": "https://followupdef.streamlit.app/?auth_callback=1"
                                }
                            })
                            st.success("✅ Link enviado! Verifique seu e-mail.")
                        except Exception as e:
                            st.error(f"❌ Falha ao enviar link: {e}")

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
    handle_auth_callback(supabase)
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

    # Se o usuário tiver mais de uma empresa, permite escolher
    if tenant_opts and len(tenant_opts) > 1:
        with st.sidebar:

            nomes = {t["tenant_id"]: (t.get("nome") or t["tenant_id"]) for t in tenant_opts}
            current = st.session_state.get("tenant_id") or tenant_opts[0]["tenant_id"]
            ids = list(nomes.keys())
            idx = ids.index(current) if current in ids else 0
            escolhido = st.selectbox(
                "🏢 Empresa",
                options=ids,
                format_func=lambda x: nomes.get(x, x),
                index=idx,
            )

            if escolhido != current:
                st.session_state.tenant_id = escolhido
                # atualiza perfil conforme empresa selecionada
                role = next((t.get("role") for t in tenant_opts if t.get("tenant_id") == escolhido), "user")
                if "usuario" in st.session_state and isinstance(st.session_state.usuario, dict):
                    st.session_state.usuario["tenant_id"] = escolhido
                    st.session_state.usuario["perfil"] = role
                st.rerun()

    tenant_id = st.session_state.get("tenant_id") or tenant_id
    if not tenant_id:
        st.error("❌ Não foi possível determinar sua empresa (tenant).")
        return

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
        df_pedidos = _cached_carregar_pedidos(supabase, tenant_id)
        st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S")
    with st.spinner("🔄 Carregando fornecedores..."):
        df_fornecedores = _cached_carregar_fornecedores(supabase, tenant_id)

    alertas = sa.calcular_alertas(df_pedidos, df_fornecedores)
    total_alertas = int(alertas.get("total", 0) or 0)

    atrasados = _safe_len(alertas.get("pedidos_atrasados"))
    criticos = _safe_len(alertas.get("pedidos_criticos"))
    vencendo = _safe_len(alertas.get("pedidos_vencendo"))

    _industrial_sidebar_css()

    
    # ===== Sidebar topo + menus =====
    with st.sidebar:

        usuario = st.session_state.usuario
        nome = usuario.get("nome", "Usuário")
        perfil = usuario.get("perfil", "user").lower()
        avatar = usuario.get("avatar_url")

        from datetime import datetime
        hora = datetime.now().hour
        if hora < 12:
            saudacao = "Bom dia"
        elif hora < 18:
            saudacao = "Boa tarde"
        else:
            saudacao = "Boa noite"

        if perfil == "admin":
            badge_cor = "#ef4444"
        elif perfil == "buyer":
            badge_cor = "#3b82f6"
        else:
            badge_cor = "#10b981"

        st.markdown("### 👤 Usuário")

        if avatar:
            st.image(avatar, width=80)
        else:
            st.markdown(f'''
                <div style="
                    width:80px;height:80px;
                    border-radius:50%;
                    background:linear-gradient(135deg,#f59e0b,#3b82f6);
                    display:flex;align-items:center;justify-content:center;
                    font-size:32px;font-weight:bold;color:white;margin:0 auto;">
                    {nome[0].upper()}
                </div>
            ''', unsafe_allow_html=True)

        st.markdown(f"**{saudacao}, {nome}!**")
        st.markdown(f'''
            <span style="background:{badge_cor};padding:4px 10px;
            border-radius:12px;font-size:12px;color:white;">
            {perfil.upper()}</span>
        ''', unsafe_allow_html=True)

        with st.expander("⚙️ Conta"):
            if st.button("👤 Meu Perfil", use_container_width=True):
                st.session_state.current_page = "Meu Perfil"
                st.rerun()

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
                "alert": "🔔 Alertas e Notificações",
                "notific": "🔔 Alertas e Notificações",
                "consulta": "Consultar Pedidos",
                "pedido": "Consultar Pedidos",
                "ficha": "Ficha de Material",
                "material": "Ficha de Material",
                "gest": "Gestão de Pedidos",
                "mapa": "Mapa Geográfico",
                "usu": "👥 Gestão de Usuários",
                "usuario": "👥 Gestão de Usuários",
                "backup": "💾 Backup",
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
                        st.session_state.current_page = destino
                        st.rerun()

        st.markdown("---")

        if total_alertas > 0:
            st.markdown(
                textwrap.dedent(f"""<div class="fu-card" style="
  border: 1px solid rgba(245,158,11,0.35);
  background: linear-gradient(135deg, rgba(245,158,11,0.18), rgba(255,255,255,0.04));
">
  <div style="display:flex; align-items:center; justify-content:space-between;">
    <div style="font-weight:900;">🔔 Alertas</div>
    <div style="
      background: rgba(239,68,68,0.95);
      color: white;
      padding: 2px 10px;
      border-radius: 999px;
      font-weight: 900;
      font-size: 12px;
    ">{total_alertas}</div>
  </div>
  <div style="margin-top:6px; font-size: 12px; opacity: .82;">
    Revise atrasos, vencimentos e fornecedores.
  </div>
</div>
"""),
                unsafe_allow_html=True,
            )

        is_admin = st.session_state.usuario.get("perfil") == "admin"
        alertas_label = _label_alertas(total_alertas)

        # ✅ Controle de navegação (seleção única + expander inteligente)
        if "current_page" not in st.session_state:
            st.session_state.current_page = "🏠 Início"

        # Memoriza qual box ficou aberto por último
        if "exp_ops_open" not in st.session_state:
            st.session_state.exp_ops_open = False
        if "exp_gestao_open" not in st.session_state:
            st.session_state.exp_gestao_open = True

        # ---------- Operações ----------
        opcoes_ops = ["🏠 Início", "Dashboard", alertas_label, "Consultar Pedidos"]
        is_ops_page = st.session_state.current_page in opcoes_ops
        index_ops = opcoes_ops.index(st.session_state.current_page) if is_ops_page else None

        # ---------- Gestão ----------
        if is_admin:
            opcoes_gestao = [
                "Ficha de Material",
                "Gestão de Pedidos",
                "Mapa Geográfico",
                "👥 Gestão de Usuários",
                "💾 Backup",
            ] + (["🧩 Admin do SaaS"] if st.session_state.get("is_superadmin") else [])
        else:
            opcoes_gestao = ["Ficha de Material", "Mapa Geográfico"]

        is_gestao_page = st.session_state.current_page in opcoes_gestao
        index_gestao = opcoes_gestao.index(st.session_state.current_page) if is_gestao_page else None

        # Auto-abrir o box do grupo ativo (e lembrar o estado do último aberto)
        expanded_ops = True if is_ops_page else bool(st.session_state.exp_ops_open)
        expanded_gestao = True if is_gestao_page else bool(st.session_state.exp_gestao_open)

        # Renderiza expanders + menus
        with st.expander("📊 Operações", expanded=expanded_ops):
            if is_ops_page:
                st.markdown('<div class="fu-expander-active">', unsafe_allow_html=True)

            escolha_ops = st.radio(
                "",
                opcoes_ops,
                index=index_ops,
                label_visibility="collapsed",
                key="menu_ops",
            )

            if is_ops_page:
                st.markdown("</div>", unsafe_allow_html=True)

        with st.expander("🛠️ Gestão", expanded=expanded_gestao):
            if is_gestao_page:
                st.markdown('<div class="fu-expander-active">', unsafe_allow_html=True)

            escolha_gestao = st.radio(
                "",
                opcoes_gestao,
                index=index_gestao,
                label_visibility="collapsed",
                key="menu_gestao",
            )

            if is_gestao_page:
                st.markdown("</div>", unsafe_allow_html=True)

        # Atualiza página + estado dos expanders (garante seleção única)
        nova_pagina = None
        if escolha_ops in opcoes_ops and escolha_ops != st.session_state.current_page:
            nova_pagina = escolha_ops
            st.session_state.exp_ops_open = True
            st.session_state.exp_gestao_open = False

        if escolha_gestao in opcoes_gestao and escolha_gestao != st.session_state.current_page:
            nova_pagina = escolha_gestao
            st.session_state.exp_ops_open = False
            st.session_state.exp_gestao_open = True

        if nova_pagina:
            st.session_state.current_page = nova_pagina
            st.rerun()

        # Página atual (fonte de verdade)
        pagina = st.session_state.current_page

    # Normaliza label de alertas
    if pagina == alertas_label:
        pagina = "🔔 Alertas e Notificações"

    # ===== Página (pode adicionar filtros na sidebar aqui) =====
    # 🚀 Ações rápidas (sticky + funcionais)
    st.markdown(
        """
        <style>
          .fu-sticky-actions{
            position: sticky;
            top: 0;
            z-index: 999;
            background: rgba(10,12,16,0.92);
            backdrop-filter: blur(6px);
            padding: 0.35rem 0 0.25rem 0;
            margin: 0 0 0.75rem 0;
            border-bottom: 1px solid rgba(255,255,255,0.06);
          }
          .fu-sticky-actions .stButton button{
            width: 100%;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="fu-sticky-actions">', unsafe_allow_html=True)
    spacer, b1, b2, b3 = st.columns([7, 1.2, 1.2, 1.2])

    with b1:
        if st.button("🔄 Atualizar", use_container_width=True, key="qa_refresh", help="Limpa cache e recarrega"):
            st.cache_data.clear()
            st.rerun()

    with b2:
        if st.button("📤 Exportar", use_container_width=True, key="qa_export", help="Ir para Exportação"):
            st.session_state.current_page = "Dashboard"
            st.session_state["dash_force_tab"] = "Exportação"
            st.rerun()

    with b3:
        if st.button("➕ Novo", use_container_width=True, key="qa_new", help="Criar novo pedido"):
            st.session_state.current_page = "Gestão de Pedidos"
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    if pagina == "🏠 Início":
        exibir_home(alertas, usuario_nome=st.session_state.usuario.get("nome", "Usuário"))
    elif pagina == "Dashboard":
        exibir_dashboard(supabase)
    elif pagina == "🔔 Alertas e Notificações":
        sa.exibir_painel_alertas(alertas, formatar_moeda_br)
    elif pagina == "Consultar Pedidos":
        exibir_consulta_pedidos(supabase)
    elif pagina == "Ficha de Material":
        exibir_ficha_material(supabase)
    elif pagina == "Gestão de Pedidos":
        exibir_gestao_pedidos(supabase)
    elif pagina == "Mapa Geográfico":
        exibir_mapa(supabase)
    elif pagina == "👥 Gestão de Usuários":
        exibir_gestao_usuarios(supabase)
    elif pagina == "💾 Backup":
        ba.realizar_backup_manual(supabase)
    elif pagina == "🧩 Admin do SaaS":
        exibir_admin_saas(supabase)


    # ===== Rodapé da sidebar: sempre depois dos filtros =====
    with st.sidebar:

        _sidebar_footer(supabase)


if __name__ == "__main__":
    main()
