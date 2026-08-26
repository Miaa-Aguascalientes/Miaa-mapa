import streamlit as st
from streamlit_folium import st_folium
import folium
import pandas as pd
from sqlalchemy import create_engine
import datetime

# 1. Configuración de la página (Barra lateral colapsada/eliminada por defecto)
st.set_page_config(
    page_title="Monitoreo SCADA - MIAA", 
    page_icon="💧", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. Estilos CSS personalizados para celulares y eliminación total de la barra lateral
st.markdown("""
    <style>
        /* Ocultar completamente la barra lateral, botones de colapso y cabeceras nativas */
        [data-testid="stSidebar"], [data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"] {
            display: none !important;
            width: 0px !important;
        }
        header { visibility: hidden !important; height: 0px !important; }
        
        .stApp { background-color: #000000; color: white; }
        
        .block-container {
            padding-top: 0.5rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            padding-bottom: 1rem !important;
            max-width: 100% !important;
        }

        /* Títulos principales */
        .main-title {
            font-size: 1.1rem;
            font-weight: bold;
            color: #00ffff;
            text-align: center;
            margin-bottom: 8px;
            text-transform: uppercase;
        }

        /* Adaptar mapas y contenedores iframe a móviles */
        iframe { 
            width: 100% !important;
            height: 65vh !important;
            border-radius: 8px;
            border: 1px solid #1f4068 !important;
        }

        /* Tarjetas HUD de indicadores */
        .contenedor-indicadores {
           display: flex;
           flex-wrap: wrap;
           justify-content: space-between;
           gap: 6px;
           margin-bottom: 10px;
         }

        .card-indicador {
           flex: 1 1 45%;
           border: 1px solid #1f4068; 
           background: linear-gradient(180deg, rgba(11, 26, 41, 0.95) 0%, rgba(0, 0, 0, 1) 100%);
           padding: 8px 6px;
           text-align: center;
           border-radius: 6px; 
        }

        .card-label { color: #888888; font-size: 0.65rem; font-weight: bold; text-transform: uppercase; margin: 0; }
        .card-value { font-family: 'Courier New', monospace; font-size: 1.15rem; font-weight: bold; margin: 0; color: #ffffff; }
    </style>
""", unsafe_allow_html=True)

# 3. Encabezado optimizado para móvil
st.markdown('<div class="main-title">💧 SCADA MIAA - Monitoreo Móvil</div>', unsafe_allow_html=True)

# 4. Indicadores Rápidos (HUD)
st.markdown("""
    <div class="contenedor-indicadores">
        <div class="card-indicador">
            <p class="card-label">Pozo Activos</p>
            <p class="card-value" style="color: #00ff66;">142 / 150</p>
        </div>
        <div class="card-indicador">
            <p class="card-label">Alertas 3F</p>
            <p class="card-value" style="color: #ff3333;">3</p>
        </div>
        <div class="card-indicador">
            <p class="card-label">Caudal Total</p>
            <p class="card-value" style="color: #00ccff;">2,450 l/s</p>
        </div>
        <div class="card-indicador">
            <p class="card-label">Actualización</p>
            <p class="card-value" style="font-size: 0.9rem; color: #ffcc00;">""" + datetime.datetime.now().strftime("%H:%M:%S") + """</p>
        </div>
    </div>
""", unsafe_allow_html=True)

# 5. Generación del Mapa Georreferenciado (Folium) con Esri Satellite
# Coordenadas centradas en Aguascalientes, Ags.
mapa_scada = folium.Map(
    location=[21.8853, -102.2916], 
    zoom_start=12, 
    tiles='CartoDB dark_matter'
)

# Ejemplo de marcadores de pozos (puedes reemplazar esto con tu conexión a MySQL/PostgreSQL)
pozos_ejemplo = [
    {"nombre": "Pozo 01 - Centro", "lat": 21.8823, "lon": -102.2925, "estado": "Operando", "caudal": "18.5 l/s"},
    {"nombre": "Pozo 15 - Norte", "lat": 21.9105, "lon": -102.3012, "estado": "Alerta Eléctrica", "caudal": "0.0 l/s"},
    {"nombre": "Pozo 22 - Sur", "lat": 21.8541, "lon": -102.2810, "estado": "Operando", "caudal": "22.1 l/s"}
]

for pozo in pozos_ejemplo:
    color_marker = "green" if pozo["estado"] == "Operando" else "red"
    html_popup = f"""
    <div style="font-family:sans-serif; color:black; min-width:150px;">
        <b>{pozo['nombre']}</b><br>
        Estado: <b>{pozo['estado']}</b><br>
        Caudal: {pozo['caudal']}
    </div>
    """
    folium.CircleMarker(
        location=[pozo["lat"], pozo["lon"]],
        radius=8,
        color=color_marker,
        fill=True,
        fill_color=color_marker,
        fill_opacity=0.8,
        popup=folium.Popup(html_popup, max_width=200)
    ).add_to(mapa_scada)

# Renderizar el mapa ajustado al contenedor
st_folium(mapa_scada, use_container_width=True, height=450)

# 6. Sección de Botones de Control / Refresco Rápido
col1, col2 = st.columns(2)
with col1:
    if st.button("🔄 Actualizar Datos", use_container_width=True):
        st.rerun()
with col2:
    if st.button("⚠️ Ver Incidencias", use_container_width=True):
        st.toast("Cargando reporte de incidencias...", icon="🚨")
