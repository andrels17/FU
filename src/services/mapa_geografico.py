"""
Módulo de Mapa Geográfico Interativo
Visualização de fornecedores em mapa real do Brasil com mapas coropléticos
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import json

# ============================================
# GEOJSON DO BRASIL
# ============================================

# GeoJSON simplificado dos estados brasileiros
BRASIL_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"id": "AC", "name": "Acre"}, "geometry": {"type": "Polygon", "coordinates": [[[-73.99,-7.35],[-73.99,-11.18],[-70.09,-11.18],[-70.09,-7.35],[-73.99,-7.35]]]}},
        {"type": "Feature", "properties": {"id": "AL", "name": "Alagoas"}, "geometry": {"type": "Polygon", "coordinates": [[[-35.20,-8.82],[-35.20,-10.50],[-36.99,-10.50],[-36.99,-8.82],[-35.20,-8.82]]]}},
        {"type": "Feature", "properties": {"id": "AP", "name": "Amapá"}, "geometry": {"type": "Polygon", "coordinates": [[[-50.03,2.25],[-50.03,-4.45],[-54.88,-4.45],[-54.88,2.25],[-50.03,2.25]]]}},
        {"type": "Feature", "properties": {"id": "AM", "name": "Amazonas"}, "geometry": {"type": "Polygon", "coordinates": [[[-56.08,-1.68],[-56.08,-9.82],[-73.79,-9.82],[-73.79,-1.68],[-56.08,-1.68]]]}},
        {"type": "Feature", "properties": {"id": "BA", "name": "Bahia"}, "geometry": {"type": "Polygon", "coordinates": [[[-37.33,-8.54],[-37.33,-18.35],[-46.61,-18.35],[-46.61,-8.54],[-37.33,-8.54]]]}},
        {"type": "Feature", "properties": {"id": "CE", "name": "Ceará"}, "geometry": {"type": "Polygon", "coordinates": [[[-37.24,-2.79],[-37.24,-7.86],[-41.40,-7.86],[-41.40,-2.79],[-37.24,-2.79]]]}},
        {"type": "Feature", "properties": {"id": "DF", "name": "Distrito Federal"}, "geometry": {"type": "Polygon", "coordinates": [[[-47.30,-15.50],[-47.30,-16.04],[-48.28,-16.04],[-48.28,-15.50],[-47.30,-15.50]]]}},
        {"type": "Feature", "properties": {"id": "ES", "name": "Espírito Santo"}, "geometry": {"type": "Polygon", "coordinates": [[[-39.69,-17.89],[-39.69,-21.30],[-41.88,-21.30],[-41.88,-17.89],[-39.69,-17.89]]]}},
        {"type": "Feature", "properties": {"id": "GO", "name": "Goiás"}, "geometry": {"type": "Polygon", "coordinates": [[[-45.90,-12.39],[-45.90,-19.48],[-53.24,-19.48],[-53.24,-12.39],[-45.90,-12.39]]]}},
        {"type": "Feature", "properties": {"id": "MA", "name": "Maranhão"}, "geometry": {"type": "Polygon", "coordinates": [[[-41.97,-1.04],[-41.97,-10.27],[-48.65,-10.27],[-48.65,-1.04],[-41.97,-1.04]]]}},
        {"type": "Feature", "properties": {"id": "MT", "name": "Mato Grosso"}, "geometry": {"type": "Polygon", "coordinates": [[[-50.22,-7.35],[-50.22,-18.04],[-61.62,-18.04],[-61.62,-7.35],[-50.22,-7.35]]]}},
        {"type": "Feature", "properties": {"id": "MS", "name": "Mato Grosso do Sul"}, "geometry": {"type": "Polygon", "coordinates": [[[-50.94,-17.16],[-50.94,-24.07],[-58.18,-24.07],[-58.18,-17.16],[-50.94,-17.16]]]}},
        {"type": "Feature", "properties": {"id": "MG", "name": "Minas Gerais"}, "geometry": {"type": "Polygon", "coordinates": [[[-39.86,-14.24],[-39.86,-22.92],[-51.05,-22.92],[-51.05,-14.24],[-39.86,-14.24]]]}},
        {"type": "Feature", "properties": {"id": "PA", "name": "Pará"}, "geometry": {"type": "Polygon", "coordinates": [[[-46.03,2.60],[-46.03,-13.69],[-59.74,-13.69],[-59.74,2.60],[-46.03,2.60]]]}},
        {"type": "Feature", "properties": {"id": "PB", "name": "Paraíba"}, "geometry": {"type": "Polygon", "coordinates": [[[-34.79,-6.00],[-34.79,-8.28],[-38.79,-8.28],[-38.79,-6.00],[-34.79,-6.00]]]}},
        {"type": "Feature", "properties": {"id": "PR", "name": "Paraná"}, "geometry": {"type": "Polygon", "coordinates": [[[-48.02,-22.51],[-48.02,-26.72],[-54.62,-26.72],[-54.62,-22.51],[-48.02,-22.51]]]}},
        {"type": "Feature", "properties": {"id": "PE", "name": "Pernambuco"}, "geometry": {"type": "Polygon", "coordinates": [[[-34.80,-7.16],[-34.80,-9.48],[-41.36,-9.48],[-41.36,-7.16],[-34.80,-7.16]]]}},
        {"type": "Feature", "properties": {"id": "PI", "name": "Piauí"}, "geometry": {"type": "Polygon", "coordinates": [[[-40.38,-2.74],[-40.38,-10.95],[-45.98,-10.95],[-45.98,-2.74],[-40.38,-2.74]]]}},
        {"type": "Feature", "properties": {"id": "RJ", "name": "Rio de Janeiro"}, "geometry": {"type": "Polygon", "coordinates": [[[-40.96,-20.76],[-40.96,-23.37],[-44.89,-23.37],[-44.89,-20.76],[-40.96,-20.76]]]}},
        {"type": "Feature", "properties": {"id": "RN", "name": "Rio Grande do Norte"}, "geometry": {"type": "Polygon", "coordinates": [[[-34.99,-4.83],[-34.99,-6.99],[-38.60,-6.99],[-38.60,-4.83],[-34.99,-4.83]]]}},
        {"type": "Feature", "properties": {"id": "RS", "name": "Rio Grande do Sul"}, "geometry": {"type": "Polygon", "coordinates": [[[-49.69,-27.08],[-49.69,-33.75],[-57.65,-33.75],[-57.65,-27.08],[-49.69,-27.08]]]}},
        {"type": "Feature", "properties": {"id": "RO", "name": "Rondônia"}, "geometry": {"type": "Polygon", "coordinates": [[[-59.78,-7.97],[-59.78,-13.69],[-66.85,-13.69],[-66.85,-7.97],[-59.78,-7.97]]]}},
        {"type": "Feature", "properties": {"id": "RR", "name": "Roraima"}, "geometry": {"type": "Polygon", "coordinates": [[[-59.08,2.24],[-59.08,-5.27],[-64.82,-5.27],[-64.82,2.24],[-59.08,2.24]]]}},
        {"type": "Feature", "properties": {"id": "SC", "name": "Santa Catarina"}, "geometry": {"type": "Polygon", "coordinates": [[[-48.55,-25.96],[-48.55,-29.35],[-53.84,-29.35],[-53.84,-25.96],[-48.55,-25.96]]]}},
        {"type": "Feature", "properties": {"id": "SP", "name": "São Paulo"}, "geometry": {"type": "Polygon", "coordinates": [[[-44.19,-19.77],[-44.19,-25.30],[-53.10,-25.30],[-53.10,-19.77],[-44.19,-19.77]]]}},
        {"type": "Feature", "properties": {"id": "SE", "name": "Sergipe"}, "geometry": {"type": "Polygon", "coordinates": [[[-36.42,-9.50],[-36.42,-11.58],[-38.24,-11.58],[-38.24,-9.50],[-36.42,-9.50]]]}},
        {"type": "Feature", "properties": {"id": "TO", "name": "Tocantins"}, "geometry": {"type": "Polygon", "coordinates": [[[-45.70,-5.17],[-45.70,-13.47],[-50.75,-13.47],[-50.75,-5.17],[-45.70,-5.17]]]}}
    ]
}

# Coordenadas aproximadas das cidades brasileiras
COORDENADAS_CIDADES = {
    "SAO PAULO": {"lat": -23.5505, "lon": -46.6333, "uf": "SP"},
    "RIO DE JANEIRO": {"lat": -22.9068, "lon": -43.1729, "uf": "RJ"},
    "BELO HORIZONTE": {"lat": -19.9167, "lon": -43.9345, "uf": "MG"},
    "BRASILIA": {"lat": -15.8267, "lon": -47.9218, "uf": "DF"},
    "SALVADOR": {"lat": -12.9714, "lon": -38.5014, "uf": "BA"},
    "FORTALEZA": {"lat": -3.7172, "lon": -38.5433, "uf": "CE"},
    "RECIFE": {"lat": -8.0476, "lon": -34.8770, "uf": "PE"},
    "CURITIBA": {"lat": -25.4284, "lon": -49.2733, "uf": "PR"},
    "PORTO ALEGRE": {"lat": -30.0346, "lon": -51.2177, "uf": "RS"},
    "MANAUS": {"lat": -3.1190, "lon": -60.0217, "uf": "AM"},
    "BELÉM": {"lat": -1.4558, "lon": -48.5039, "uf": "PA"},
    "GOIÂNIA": {"lat": -16.6869, "lon": -49.2648, "uf": "GO"},
    "CAMPINAS": {"lat": -22.9056, "lon": -47.0608, "uf": "SP"},
    "GUARULHOS": {"lat": -23.4538, "lon": -46.5333, "uf": "SP"},
    "SÃO BERNARDO DO CAMPO": {"lat": -23.6914, "lon": -46.5646, "uf": "SP"},
    "SANTO ANDRÉ": {"lat": -23.6739, "lon": -46.5422, "uf": "SP"},
    "OSASCO": {"lat": -23.5329, "lon": -46.7919, "uf": "SP"},
    "RIBEIRÃO PRETO": {"lat": -21.1704, "lon": -47.8103, "uf": "SP"},
    "SOROCABA": {"lat": -23.5015, "lon": -47.4526, "uf": "SP"},
    "NATAL": {"lat": -5.7945, "lon": -35.2110, "uf": "RN"},
    "JOÃO PESSOA": {"lat": -7.1195, "lon": -34.8450, "uf": "PB"},
    "MACEIÓ": {"lat": -9.6658, "lon": -35.7353, "uf": "AL"},
    "ARACAJU": {"lat": -10.9091, "lon": -37.0677, "uf": "SE"},
    "TERESINA": {"lat": -5.0892, "lon": -42.8019, "uf": "PI"},
    "SÃO LUÍS": {"lat": -2.5387, "lon": -44.2825, "uf": "MA"},
    "CUIABÁ": {"lat": -15.6014, "lon": -56.0979, "uf": "MT"},
    "CAMPO GRANDE": {"lat": -20.4428, "lon": -54.6464, "uf": "MS"},
    "FLORIANÓPOLIS": {"lat": -27.5954, "lon": -48.5480, "uf": "SC"},
    "VITÓRIA": {"lat": -20.3155, "lon": -40.3128, "uf": "ES"},
    "PORTO VELHO": {"lat": -8.7612, "lon": -63.9004, "uf": "RO"},
    "RIO BRANCO": {"lat": -9.9747, "lon": -67.8243, "uf": "AC"},
    "MACAPÁ": {"lat": 0.0349, "lon": -51.0694, "uf": "AP"},
    "BOA VISTA": {"lat": 2.8235, "lon": -60.6758, "uf": "RR"},
    "PALMAS": {"lat": -10.1689, "lon": -48.3317, "uf": "TO"},
}

def normalizar_cidade(cidade):
    """Normaliza nome da cidade para busca"""
    if pd.isna(cidade):
        return None
    cidade = str(cidade).upper().strip()
    cidade = cidade.replace('Á', 'A').replace('À', 'A').replace('Â', 'A').replace('Ã', 'A')
    cidade = cidade.replace('É', 'E').replace('Ê', 'E')
    cidade = cidade.replace('Í', 'I')
    cidade = cidade.replace('Ó', 'O').replace('Ô', 'O').replace('Õ', 'O')
    cidade = cidade.replace('Ú', 'U').replace('Ü', 'U')
    cidade = cidade.replace('Ç', 'C')
    return cidade

def obter_coordenadas(cidade, uf):
    """Obtém coordenadas de uma cidade"""
    cidade_norm = normalizar_cidade(cidade)
    
    if cidade_norm in COORDENADAS_CIDADES:
        coords = COORDENADAS_CIDADES[cidade_norm]
        if coords['uf'] == uf:
            return coords['lat'], coords['lon']
    
    for cidade_key, coords in COORDENADAS_CIDADES.items():
        if cidade_norm and cidade_norm in cidade_key and coords['uf'] == uf:
            return coords['lat'], coords['lon']
    
    COORDS_UF = {
        'SP': (-23.5, -46.6), 'RJ': (-22.9, -43.2), 'MG': (-19.9, -43.9),
        'BA': (-12.9, -38.5), 'PE': (-8.0, -34.9), 'CE': (-3.7, -38.5),
        'PR': (-25.4, -49.3), 'RS': (-30.0, -51.2), 'SC': (-27.6, -48.5),
        'GO': (-16.7, -49.3), 'DF': (-15.8, -47.9), 'ES': (-20.3, -40.3),
        'PA': (-1.5, -48.5), 'MA': (-2.5, -44.3), 'AM': (-3.1, -60.0),
        'RN': (-5.8, -35.2), 'PB': (-7.1, -34.8), 'AL': (-9.7, -35.7),
        'SE': (-10.9, -37.1), 'PI': (-5.1, -42.8), 'MT': (-15.6, -56.1),
        'MS': (-20.4, -54.6), 'RO': (-8.8, -63.9), 'AC': (-10.0, -67.8),
        'AP': (0.0, -51.1), 'RR': (2.8, -60.7), 'TO': (-10.2, -48.3)
    }
    
    if uf in COORDS_UF:
        return COORDS_UF[uf]
    
    return None, None

def formatar_numero_br(numero):
    """Formata número no padrão brasileiro"""
    try:
        if pd.isna(numero):
            return "0,00"
        return f"{float(numero):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "0,00"

def formatar_moeda_br(valor):
    """Formata valor monetário no padrão brasileiro"""
    try:
        if pd.isna(valor):
            return "R$ 0,00"
        return f"R$ {formatar_numero_br(valor)}"
    except:
        return "R$ 0,00"

def criar_mapa_coropletico_estados(df_pedidos):
    """Cria mapa coroplético dos estados brasileiros com métricas"""
    
    df_estados = df_pedidos.groupby('fornecedor_uf').agg({
        'id': 'count',
        'valor_total': 'sum',
        'fornecedor_nome': 'nunique',
        'entregue': lambda x: (x == True).sum()
    }).reset_index()
    
    df_estados.columns = ['UF', 'total_pedidos', 'valor_total', 'qtd_fornecedores', 'pedidos_entregues']
    df_estados['perc_entrega'] = (df_estados['pedidos_entregues'] / df_estados['total_pedidos'] * 100).round(1)
    
    df_estados['hover_text'] = df_estados.apply(
        lambda row: f"<b>{row['UF']}</b><br>" +
                    f"📦 Pedidos: {formatar_numero_br(row['total_pedidos']).split(',')[0]}<br>" +
                    f"💰 Valor: {formatar_moeda_br(row['valor_total'])}<br>" +
                    f"🏭 Fornecedores: {int(row['qtd_fornecedores'])}<br>" +
                    f"✅ Entregues: {int(row['pedidos_entregues'])} ({row['perc_entrega']:.0f}%)",
        axis=1
    )
    
    # Usar GeoJSON do Brasil hospedado online
    import requests
    try:
        geojson_url = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
        response = requests.get(geojson_url, timeout=5)
        brasil_geojson = response.json()
    except:
        # Fallback para o GeoJSON local simplificado
        brasil_geojson = BRASIL_GEOJSON
    
    fig = go.Figure(go.Choroplethmapbox(
        geojson=brasil_geojson,
        locations=df_estados['UF'],
        z=df_estados['valor_total'],
        featureidkey="properties.sigla",
        colorscale=[
            [0, '#1a202c'],
            [0.2, '#2d3748'],
            [0.4, '#4a5568'],
            [0.6, '#667eea'],
            [0.8, '#764ba2'],
            [1, '#f093fb']
        ],
        text=df_estados['hover_text'],
        hovertemplate='%{text}<extra></extra>',
        marker=dict(
            opacity=0.7,
            line=dict(width=1, color='#ffffff')
        ),
        colorbar=dict(
            title=dict(text="Valor Total (R$)", font=dict(color='white', size=14)),
            tickfont=dict(color='white', size=11),
            bgcolor='rgba(0,0,0,0.6)',
            bordercolor='white',
            borderwidth=2,
            thickness=20,
            len=0.7,
            x=1.02,
            tickformat=',.0f'
        ),
        showscale=True
    ))
    
    fig.update_layout(
        mapbox=dict(
            style='carto-darkmatter',
            zoom=3.2,
            center=dict(lat=-14, lon=-55)
        ),
        title={
            'text': '🗺️ Mapa de Calor - Compras por Estado',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 28, 'color': '#fafafa', 'family': 'Arial Black'}
        },
        height=700,
        margin=dict(l=0, r=0, t=70, b=0),
        paper_bgcolor='#0e1117',
        font=dict(color='#fafafa')
    )
    
    return fig, df_estados

def exibir_metricas_estados(df_estados):
    """Exibe métricas do mapa de estados"""
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total_estados = len(df_estados)
    total_pedidos = df_estados['total_pedidos'].sum()
    total_valor = df_estados['valor_total'].sum()
    total_fornecedores = df_estados['qtd_fornecedores'].sum()
    media_entrega = df_estados['perc_entrega'].mean()
    
    with col1:
        st.metric("📍 Estados Ativos", f"{int(total_estados)}/27")
    
    with col2:
        st.metric("📦 Total de Pedidos", formatar_numero_br(total_pedidos).split(',')[0])
    
    with col3:
        st.metric("💰 Valor Total", formatar_moeda_br(total_valor))
    
    with col4:
        st.metric("🏭 Fornecedores", f"{int(total_fornecedores)}")
    
    with col5:
        st.metric("✅ Taxa Entrega Média", f"{media_entrega:.1f}%".replace('.', ','))

def criar_mapa_fornecedores(df_pedidos):
    """Cria mapa interativo dos fornecedores com marcadores"""
    
    df_map = df_pedidos[df_pedidos['fornecedor_nome'].notna()].copy()
    
    if df_map.empty:
        st.warning("⚠️ Nenhum pedido com fornecedor cadastrado")
        return None, None
    
    df_fornecedores = df_map.groupby(['fornecedor_nome', 'fornecedor_cidade', 'fornecedor_uf']).agg({
        'id': 'count',
        'valor_total': 'sum',
        'entregue': lambda x: (x == True).sum()
    }).reset_index()
    
    df_fornecedores.columns = ['fornecedor', 'cidade', 'uf', 'total_pedidos', 'valor_total', 'pedidos_entregues']
    
    coordenadas = []
    for _, row in df_fornecedores.iterrows():
        lat, lon = obter_coordenadas(row['cidade'], row['uf'])
        coordenadas.append({'lat': lat, 'lon': lon})
    
    df_fornecedores = pd.concat([df_fornecedores, pd.DataFrame(coordenadas)], axis=1)
    df_fornecedores = df_fornecedores[df_fornecedores['lat'].notna()]
    
    if df_fornecedores.empty:
        st.warning("⚠️ Não foi possível geocodificar os fornecedores")
        return None, None
    
    df_fornecedores['hover_text'] = df_fornecedores.apply(
        lambda row: f"<b>{row['fornecedor']}</b><br>" +
                    f"📍 {row['cidade']}/{row['uf']}<br>" +
                    f"📦 {int(row['total_pedidos'])} pedidos<br>" +
                    f"💰 {formatar_moeda_br(row['valor_total'])}<br>" +
                    f"✅ {int(row['pedidos_entregues'])} entregues",
        axis=1
    )
    
    fig = go.Figure()
    
    fig.add_trace(go.Scattermapbox(
        lon=df_fornecedores['lon'],
        lat=df_fornecedores['lat'],
        text=df_fornecedores['hover_text'],
        mode='markers',
        marker=dict(
            size=df_fornecedores['total_pedidos'] * 2 + 12,
            color=df_fornecedores['valor_total'],
            colorscale=[
                [0, '#667eea'],
                [0.5, '#764ba2'],
                [1, '#f093fb']
            ],
            showscale=True,
            colorbar=dict(
                title=dict(text="Valor Total (R$)", font=dict(color='white', size=14)),
                tickfont=dict(color='white'),
                bgcolor='rgba(0,0,0,0.6)',
                bordercolor='white',
                borderwidth=2,
                x=1.02,
                thickness=20
            ),
            opacity=0.9
        ),
        hovertemplate='%{text}<extra></extra>',
        name=''
    ))
    
    fig.update_layout(
        mapbox=dict(
            style='carto-darkmatter',
            zoom=3.2,
            center=dict(lat=-14, lon=-55)
        ),
        title={
            'text': '📍 Localização de Fornecedores',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 28, 'color': '#fafafa', 'family': 'Arial Black'}
        },
        height=700,
        margin=dict(l=0, r=0, t=70, b=0),
        paper_bgcolor='#0e1117',
        font=dict(color='#fafafa')
    )
    
    return fig, df_fornecedores

def exibir_estatisticas_mapa(df_fornecedores):
    """Exibe estatísticas do mapa"""
    
    col1, col2, col3, col4 = st.columns(4)
    
    total_fornecedores = len(df_fornecedores)
    total_pedidos = df_fornecedores['total_pedidos'].sum()
    total_valor = df_fornecedores['valor_total'].sum()
    estados_atendidos = df_fornecedores['uf'].nunique()
    
    with col1:
        st.metric("🏭 Fornecedores", f"{int(total_fornecedores)}")
    
    with col2:
        st.metric("📦 Pedidos", formatar_numero_br(total_pedidos).split(',')[0])
    
    with col3:
        st.metric("💰 Valor Total", formatar_moeda_br(total_valor))
    
    with col4:
        st.metric("📍 Estados", f"{int(estados_atendidos)}")

def criar_ranking_fornecedores(df_fornecedores):
    """Cria ranking visual de fornecedores"""
    
    st.subheader("🏆 Ranking de Fornecedores")
    
    top_fornecedores = df_fornecedores.nlargest(10, 'valor_total')
    
    for idx, (index, row) in enumerate(top_fornecedores.iterrows()):
        if idx == 0:
            emoji = "🥇"
        elif idx == 1:
            emoji = "🥈"
        elif idx == 2:
            emoji = "🥉"
        else:
            emoji = "📍"
        
        max_valor = top_fornecedores['valor_total'].max()
        progresso = int((row['valor_total'] / max_valor) * 100)
        
        with st.container():
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.markdown(f"""
                **{emoji} {row['fornecedor']}**  
                📍 {row['cidade']}/{row['uf']} • 📦 {int(row['total_pedidos'])} pedidos • ✅ {int(row['pedidos_entregues'])} entregues
                """)
                st.progress(progresso / 100)
            
            with col2:
                st.metric("Valor Total", formatar_moeda_br(row['valor_total']))
            
            st.markdown("---")

def criar_graficos_analise(df_estados):
    """Cria gráficos de análise detalhada"""
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("💰 Top 10 Estados por Valor")
        
        df_top = df_estados.nlargest(10, 'valor_total')
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_top['UF'],
            y=df_top['valor_total'],
            marker=dict(
                color=df_top['valor_total'],
                colorscale=[[0, '#667eea'], [0.5, '#764ba2'], [1, '#f093fb']],
                showscale=False,
                line=dict(color='#667eea', width=2)
            ),
            text=[formatar_moeda_br(v) for v in df_top['valor_total']],
            textposition='outside',
            textfont=dict(color='white', size=11),
            hovertemplate='<b>%{x}</b><br>Valor: %{text}<br><extra></extra>'
        ))
        
        fig.update_layout(
            xaxis=dict(title='Estado', titlefont=dict(color='white'), tickfont=dict(color='white', size=12), showgrid=False),
            yaxis=dict(title='Valor Total (R$)', titlefont=dict(color='white'), tickfont=dict(color='white'), gridcolor='#2d3748', showgrid=True),
            height=400,
            showlegend=False,
            margin=dict(l=0, r=0, t=30, b=0),
            paper_bgcolor='#0e1117',
            plot_bgcolor='#1a1d29',
            font=dict(color='white')
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("📦 Distribuição de Pedidos")
        
        df_top_pedidos = df_estados.nlargest(5, 'total_pedidos')
        outros_pedidos = df_estados[~df_estados['UF'].isin(df_top_pedidos['UF'])]['total_pedidos'].sum()
        
        if outros_pedidos > 0:
            df_pizza = pd.concat([
                df_top_pedidos[['UF', 'total_pedidos']],
                pd.DataFrame({'UF': ['Outros'], 'total_pedidos': [outros_pedidos]})
            ])
        else:
            df_pizza = df_top_pedidos[['UF', 'total_pedidos']]
        
        fig = go.Figure(data=[go.Pie(
            labels=df_pizza['UF'],
            values=df_pizza['total_pedidos'],
            hole=0.4,
            marker=dict(
                colors=['#667eea', '#764ba2', '#f093fb', '#fa709a', '#fee140', '#30cfd0'],
                line=dict(color='#0e1117', width=3)
            ),
            textfont=dict(color='white', size=14),
            hovertemplate='<b>%{label}</b><br>Pedidos: %{value}<br>%{percent}<extra></extra>'
        )])
        
        fig.update_layout(
            height=400,
            margin=dict(l=20, r=20, t=30, b=20),
            paper_bgcolor='#0e1117',
            font=dict(color='white', size=12),
            showlegend=True,
            legend=dict(bgcolor='rgba(0,0,0,0.5)', bordercolor='white', borderwidth=1, font=dict(color='white'))
        )
        
        st.plotly_chart(fig, use_container_width=True)

def criar_tabela_detalhada(df_estados):
    """Cria tabela detalhada com todos os estados"""
    
    st.subheader("📊 Análise Detalhada por Estado")
    
    df_display = df_estados.copy()
    df_display = df_display.sort_values('valor_total', ascending=False)
    
    df_display['valor_total_fmt'] = df_display['valor_total'].apply(formatar_moeda_br)
    df_display['total_pedidos_fmt'] = df_display['total_pedidos'].apply(lambda x: formatar_numero_br(x).split(',')[0])
    df_display['perc_entrega_fmt'] = df_display['perc_entrega'].apply(lambda x: f"{x:.1f}%".replace('.', ','))
    
    st.dataframe(
        df_display[['UF', 'total_pedidos_fmt', 'valor_total_fmt', 'qtd_fornecedores', 'pedidos_entregues', 'perc_entrega_fmt']],
        use_container_width=True,
        hide_index=True,
        column_config={
            "UF": st.column_config.TextColumn("Estado", width="small"),
            "total_pedidos_fmt": st.column_config.TextColumn("Total de Pedidos", width="medium"),
            "valor_total_fmt": st.column_config.TextColumn("Valor Total", width="medium"),
            "qtd_fornecedores": st.column_config.NumberColumn("Fornecedores", format="%d", width="small"),
            "pedidos_entregues": st.column_config.NumberColumn("Entregues", format="%d", width="small"),
            "perc_entrega_fmt": st.column_config.TextColumn("% Entrega", width="small")
        },
        height=400
    )
