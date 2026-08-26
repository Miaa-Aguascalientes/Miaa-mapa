import streamlit as st
import json
import geopandas as gpd
import pandas as pd
import folium
from streamlit_folium import st_folium
import psycopg2
import urllib.parse
from shapely import wkt

# Configuración de la página (DEBE ser la primera instrucción de Streamlit)
st.set_page_config(
    page_title="MIAA - Mapa SCADA", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Ocultar elementos de Streamlit para dejar exclusivamente el mapa
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .stApp { margin: 0; padding: 0; top: 0; bottom: 0; left: 0; right: 0; }
        .block-container { padding: 0 !important; margin: 0 !important; max-width: 100% !important; height: 100vh !important; }
        iframe { width: 100vw; height: 100vh; border: none; }
    </style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_postgres_conn():
    try: 
        conn = psycopg2.connect(**st.secrets["postgres"])
        return conn
    except Exception as e: 
        return None

# Cargar sectores y geometrías para mostrar en el mapa
@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        query = """
            SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo 
            FROM "Sectorizacion"."Sectores_hidr"
        """
        df = pd.read_sql(query, conn)
        return df.to_dict('records')
    except Exception:
        return []
    finally:
        if conn:
            conn.close()

# Crear mapa centrado en Aguascalientes
m = folium.Map(
    location=[21.8853, -102.2916], 
    zoom_start=12, 
    tiles="CartoDB dark_matter"
)

# Cargar sectores e iterar correctamente sobre los resultados
sectores = cargar_sectores_poligonos()

# Añadir polígonos de sectores al mapa
for sec in sectores:
    try:
        if sec.get('geo'):
            geo_json = json.loads(sec['geo'])
            folium.GeoJson(
                geo_json,
                style_function=lambda x: {
                    'fillColor': '#3498DB',
                    'color': '#2980B9',
                    'weight': 1.5,
                    'fillOpacity': 0.1
                },
                tooltip=f"Sector: {sec.get('sector')}"
            ).add_to(m)
    except Exception:
        continue

# Renderizar exclusivamente el mapa ocupando todo el espacio disponible
st_folium(m, width="100%", height=850, use_container_width=True)
