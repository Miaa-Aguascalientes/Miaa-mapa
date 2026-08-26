import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static, st_folium
from folium.plugins import Fullscreen, MousePosition, LocateControl
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh
import re
from shapely import wkt
import geopandas as gpd

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
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            margin-top: 10px !important;
            max-width: 100% !important;
        }
        
        .titulo-superior {
            text-align: center;
            color: #00d4ff;
            font-size: 1.8rem;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-bottom: 10px;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
        }
    </style>
""", unsafe_allow_html=True)

count = st_autorefresh(interval=300000, limit=1000, key="scada_refresh")

# ==========================================
# 2. FUNCIONES DE CONEXIÓN Y DATOS
# ==========================================
@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        with engine.connect() as conn: pass 
        return engine
    except Exception as e:
        return None

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
# 3. CARGA DE CATÁLOGOS Y MAPA
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

@st.cache_data(ttl=3600) 
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
                nuevo_mapa[row['Pozos']] = {
                    "coord": (lat, lon),
                    "bomba": row.get('bomba'),
                    "caudal": row.get('caudal'),
                    "presion": row.get('presion')
                }
            except: continue
        return nuevo_mapa
    except:
        return {}

# ==========================================
# 4. RENDERIZADO DEL MAPA PRINCIPAL
# ==========================================
st.markdown('<div class="titulo-superior">Sistema SCADA - Monitoreo Geográfico MIAA</div>', unsafe_allow_html=True)

# Coordenadas centrales de Aguascalientes
m = folium.Map(location=[21.8823, -102.2826], zoom_start=12, tiles='CartoDB dark_matter')

Fullscreen(position="topright").add_to(m)
MousePosition().add_to(m)
LocateControl(position="topleft").add_to(m)

# Cargar y pintar sectores en el mapa (CORREGIDO)
sectores = cargar_sectores_poligonos()
for sec in sectores:
    try:
        geo_data = json.loads(sec['geo'])
        folium.GeoJson(
            geo_data,
            style_function=lambda x: {'fillColor': '#3498DB', 'color': '#2980B9', 'weight': 1.5, 'fillOpacity': 0.1},
            tooltip=f"Sector: {sec['sector']} | Población: {sec.get('Poblacion', 'N/A')}"
        ).add_to(m)
    except:
        pass

# Cargar pozos y agregarlos al mapa
pozos = cargar_mapa_pozos_desde_db()
for nombre_pozo, datos in pozos.items():
    coord = datos.get("coord")
    if coord:
        folium.CircleMarker(
            location=coord,
            radius=5,
            color='#00d4ff',
            fill=True,
            fill_color='#00d4ff',
            fill_opacity=0.8,
            popup=f"<b>Pozo: {nombre_pozo}</b>"
        ).add_to(m)

# Mostrar el mapa ocupando todo el ancho disponible
st_folium(m, width="100%", height=820, returned_objects=[])
