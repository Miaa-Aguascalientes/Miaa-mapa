import streamlit as st
from streamlit_folium import st_folium
import folium
import pandas as pd
import geopandas as gpd
from sqlalchemy import create_engine
import datetime

# 1. Configuración de la página (Ocultar barra lateral por defecto)
st.set_page_config(
    page_title="SCADA MIAA - Monitoreo Móvil", 
    page_icon="💧", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. Estilos CSS personalizados para celulares y eliminación total de la barra lateral
st.markdown("""
    <style>
        /* Ocultar completamente la barra lateral y botones de despliegue */
        [data-testid="stSidebar"], [data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"] {
            display: none !important;
            width: 0px !important;
        }
        header { visibility: hidden !important; height: 0px !important; }
        
        .stApp { background-color: #000000; color: white; }
        
        .block-container {
            padding-top: 0.4rem !important;
            padding-left: 0.4rem !important;
            padding-right: 0.4rem !important;
            padding-bottom: 0.8rem !important;
            max-width: 100% !important;
        }

        .main-title {
            font-size: 1.05rem;
            font-weight: bold;
            color: #00ffff;
            text-align: center;
            margin-bottom: 6px;
            text-transform: uppercase;
        }

        /* Ajuste de contenedores del mapa */
        iframe { 
            width: 100% !important;
            height: 62vh !important;
            border-radius: 6px;
            border: 1px solid #1f4068 !important;
        }

        /* Tarjetas HUD de indicadores rápidos */
        .contenedor-indicadores {
           display: flex;
           flex-wrap: wrap;
           justify-content: space-between;
           gap: 4px;
           margin-bottom: 8px;
         }

        .card-indicador {
           flex: 1 1 23%;
           border: 1px solid #1f4068; 
           background: linear-gradient(180deg, rgba(11, 26, 41, 0.95) 0%, rgba(0, 0, 0, 1) 100%);
           padding: 6px 2px;
           text-align: center;
           border-radius: 5px; 
        }

        .card-label { color: #888888; font-size: 0.58rem; font-weight: bold; text-transform: uppercase; margin: 0; }
        .card-value { font-family: 'Courier New', monospace; font-size: 1.05rem; font-weight: bold; margin: 0; color: #ffffff; }
    </style>
""", unsafe_allow_html=True)

# 3. Encabezado
st.markdown('<div class="main-title">💧 MIAA - Monitoreo SCADA en Vivo</div>', unsafe_allow_html=True)

# 4. Indicadores Rápidos (HUD)
st.markdown("""
    <div class="contenedor-indicadores">
        <div class="card-indicador">
            <p class="card-label">Activos</p>
            <p class="card-value" style="color: #00ff66;">142</p>
        </div>
        <div class="card-indicador">
            <p class="card-label">Alarmas 3F</p>
            <p class="card-value" style="color: #ff3333;">3</p>
        </div>
        <div class="card-indicador">
            <p class="card-label">Caudal</p>
            <p class="card-value" style="color: #00ccff;">2.4k</p>
        </div>
        <div class="card-indicador">
            <p class="card-label">Hora</p>
            <p class="card-value" style="font-size: 0.8rem; color: #ffcc00;">""" + datetime.datetime.now().strftime("%H:%M") + """</p>
        </div>
    </div>
""", unsafe_allow_html=True)

# 5. Creación del Mapa base con temática Oscura (CartoDB dark_matter) y Esri Satellite opcional
mapa_scada = folium.Map(
    location=[21.8853, -102.2916], 
    zoom_start=12, 
    tiles='CartoDB dark_matter'
)

# Capa adicional: Esri World Imagery (Satélite)
folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Esri Satélite',
    overlay=False,
    control=True
).add_to(mapa_scada)

# -------------------------------------------------------------------------
# CONEXIÓN A BASE DE DATOS / CARGA DE DATOS (Ajusta tus credenciales o fuentes)
# -------------------------------------------------------------------------
# Ejemplo de carga de Capa de Colonias / Sectores (GeoJSON o PostGIS)
# sectors_gdf = gpd.read_postgis("SELECT * FROM sectores_hidraulicos", con=engine)
# folium.GeoJson(sectors_gdf, style_function=lambda x: {'color': '#1f4068', 'weight': 1, 'fillOpacity': 0.1}).add_to(mapa_scada)

# Grupo de capas para organizar elementos
capa_pozos = folium.FeatureGroup(name="Pozos y Estado").add_to(mapa_scada)

# Simulación de datos de pozos desde tu BD (MySQL/PostgreSQL)
pozos_db = [
    {"id": 1, "nombre": "Pozo 01 - Centro", "lat": 21.8823, "lon": -102.2925, "estado": "Operando", "caudal": 18.5, "nivel": 45.2},
    {"id": 2, "nombre": "Pozo 15 - Industrial", "lat": 21.9105, "lon": -102.3012, "estado": "Alerta Eléctrica", "caudal": 0.0, "nivel": 12.8},
    {"id": 3, "nombre": "Pozo 22 - Sur", "lat": 21.8541, "lon": -102.2810, "estado": "Operando", "caudal": 22.1, "nivel": 50.4},
    {"id": 4, "nombre": "Pozo 34 - Oriente", "lat": 21.8760, "lon": -102.2510, "estado": "Mantenimiento", "caudal": 0.0, "nivel": 0.0}
]

for pozo in pozos_db:
    # Color según estado operativo
    if pozo["estado"] == "Operando":
        color_marker = "#00ff66"
    elif pozo["estado"] == "Alerta Eléctrica":
        color_marker = "#ff3333"
    else:
        color_marker = "#ffcc00"

    html_popup = f"""
    <div style="font-family: 'Courier New', monospace; color: #000; font-size: 12px; min-width: 160px;">
        <b style="color: #0b1a29;">{pozo['nombre']}</b><hr style="margin: 4px 0;">
        <b>Estado:</b> <span style="color: {color_marker};">{pozo['estado']}</span><br>
        <b>Caudal:</b> {pozo['caudal']} l/s<br>
        <b>Nivel Dinámico:</b> {pozo['nivel']} m
    </div>
    """
    
    folium.CircleMarker(
        location=[pozo["lat"], pozo["lon"]],
        radius=9,
        color=color_marker,
        weight=2,
        fill=True,
        fill_color=color_marker,
        fill_opacity=0.85,
        popup=folium.Popup(html_popup, max_width=220)
    ).add_to(capa_pozos)

# Control de capas dentro del mapa
folium.LayerControl().add_to(mapa_scada)

# Renderizar el mapa en pantalla completa adaptado
st_folium(mapa_scada, use_container_width=True, height=430)

# 6. Botones de acción inferior optimizados para acceso rápido táctil
col1, col2 = st.columns(2)
with col1:
    if st.button("🔄 Refrescar", use_container_width=True):
        st.rerun()
with col2:
    if st.button("🚨 Incidencias Activas", use_container_width=True):
        st.toast("Actualizando panel de incidencias de pozos...", icon="⚠️")
