import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import Fullscreen, MousePosition, LocateControl
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA (SIN BARRA LATERAL)
# ==========================================
st.set_page_config(
    page_title="MIAA - Sistema SCADA (Mapa)", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Ocultar completamente la barra lateral y elementos de navegación por CSS
st.markdown("""
    <style>
        [data-testid="stSidebar"], [data-testid="collapsedControl"], button[kind="headerNoPadding"], [data-testid="stSidebarCollapseButton"] {
            display: none !important;
        }
        header { visibility: hidden !important; height: 0px !important; }
        .stApp { background-color: #000000; color: white; }
        
        .block-container {
            padding-top: 0rem !important;
            padding-left: 0rem !important;
            padding-right: 0rem !important;
            margin-top: 0px !important;
            max-width: 100% !important;
        }
        
        .titulo-superior {
            position: absolute;
            top: 10px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 999;
            text-align: center;
            color: #00d4ff;
            font-size: 1.4rem;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 2px;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.8);
            pointer-events: none;
        }
    </style>
""", unsafe_allow_html=True)

count = st_autorefresh(interval=300000, limit=1000, key="scada_refresh")

# ==========================================
# 2. FUNCIONES DE CONEXIÓN
# ==========================================
@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        with engine.connect() as conn: pass 
        return engine
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: 
        conn = psycopg2.connect(**st.secrets["postgres"])
        return conn
    except Exception as e: 
        return None

# ==========================================
# 3. CARGA DE DATOS Y CAPAS
# ==========================================
@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        query = """
            SELECT sector, "Pozos_Sector", "Superficie", "Poblacion", 
                   ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo 
            FROM "Sectorizacion"."Sectores_hidr"
        """
        df = pd.read_sql(query, conn)
        return df.to_dict('records')
    except Exception as e:
        return []
    finally:
        if conn: conn.close()

@st.cache_data(ttl=300)
def cargar_incidencias_activas():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        query = """
            SELECT id, pozo, tipo_incidencia, descripcion, status, 
                   ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo 
            FROM "Incidencias"."vw_incidencias_en_pozos"
            WHERE status ILIKE 'activo%' OR status ILIKE 'en proceso%'
        """
        df = pd.read_sql(query, conn)
        return df.to_dict('records')
    except:
        return []
    finally:
        if conn: conn.close()

@st.cache_data(ttl=60) 
def cargar_mapa_pozos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_pozos"
        df_pozos = pd.read_sql(query, engine)
        nuevo_mapa = {}
        for _, row in df_pozos.iterrows():
            try:
                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                
                # Determinar estado de la bomba para el color
                bomba_estado = str(row.get('bomba', '')).strip().lower()
                if bomba_estado in ['1', 'true', 'on', 'encendido', 'operando']:
                    color = '#2ECC71'  # Verde operativo
                elif bomba_estado in ['0', 'false', 'off', 'apagado', 'fallo']:
                    color = '#E74C3C'  # Rojo apagado / falla
                else:
                    color = '#00d4ff'  # Azul por defecto
                    
                nuevo_mapa[row['Pozos']] = {
                    "coord": (lat, lon),
                    "bomba": row.get('bomba'),
                    "caudal": row.get('caudal'),
                    "presion": row.get('presion'),
                    "color": color
                }
            except: continue
        return nuevo_mapa
    except:
        return {}

# ==========================================
# 4. RENDERIZADO DEL MAPA COMPLETO
# ==========================================
st.markdown('<div class="titulo-superior">Sistema SCADA - Monitoreo Geográfico MIAA</div>', unsafe_allow_html=True)

# Crear mapa base centrado en Aguascalientes con capas de mosaicos personalizados
m = folium.Map(location=[21.8823, -102.2826], zoom_start=12, zoom_control=True, tiles=None)

# Añadir capas de mapas base seleccionables
folium.TileLayer('openstreetmap', name='OpenStreetMap', control=True).add_to(m)
folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Vista Satélite (Esri)',
    control=True
).add_to(m)
folium.TileLayer(
    tiles='https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    attr='CartoDB',
    name='Vista Nocturna',
    control=True,
    max_zoom=19
).add_to(m)

Fullscreen(position="topright").add_to(m)
MousePosition().add_to(m)
LocateControl(position="topleft").add_to(m)

# Grupos de capas (FeatureGroups) para controlar visibilidad con checkboxes en el mapa
fg_sectores = folium.FeatureGroup(name="Sectores Hidráulicos", overlay=True, control=True)
fg_pozos = folium.FeatureGroup(name="Pozos", overlay=True, control=True)
fg_incidencias = folium.FeatureGroup(name="Incidencias Activas", overlay=True, control=True)

# 1. Cargar y pintar sectores
sectores = cargar_sectores_poligonos()
for sec in sectores:
    try:
        geo_data = json.loads(sec['geo'])
        folium.GeoJson(
            geo_data,
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#0088cc', 'weight': 1.2, 'fillOpacity': 0.08},
            tooltip=f"<b>Sector:</b> {sec['sector']} | <b>Población:</b> {sec.get('Poblacion', 'N/A')}"
        ).add_to(fg_sectores)
    except:
        pass

# 2. Cargar y pintar pozos
pozos = cargar_mapa_pozos_desde_db()
for nombre_pozo, datos in pozos.items():
    coord = datos.get("coord")
    if coord:
        folium.CircleMarker(
            location=coord,
            radius=5,
            color=datos["color"],
            fill=True,
            fill_color=datos["color"],
            fill_opacity=0.9,
            popup=f"<b>Pozo:</b> {nombre_pozo}<br><b>Caudal:</b> {datos.get('caudal', 'N/A')} lps<br><b>Presión:</b> {datos.get('presion', 'N/A')} mca"
        ).add_to(fg_pozos)

# 3. Cargar y pintar incidencias con alertas visuales
incidencias = cargar_incidencias_activas()
for inc in incidencias:
    try:
        geo_data = json.loads(inc['geo'])
        folium.GeoJson(
            geo_data,
            style_function=lambda x: {'fillColor': '#FF4B4B', 'color': '#FF0000', 'weight': 2.5, 'fillOpacity': 0.4},
            tooltip=f"⚠️ <b>ALERTA:</b> {inc.get('tipo_incidencia', 'Falla')} | <b>Pozo:</b> {inc.get('pozo', 'N/A')}<br><b>Estado:</b> {inc.get('status', 'Activo')}"
        ).add_to(fg_incidencias)
    except:
        pass

# Agregar los grupos al mapa
fg_sectores.add_to(m)
fg_pozos.add_to(m)
fg_incidencias.add_to(m)

# Control de capas interactivo en pantalla
folium.LayerControl(collapsed=False, position="topright").add_to(m)

# Renderizar mapa a pantalla completa real
st_folium(m, width="100%", height=880, returned_objects=[])
