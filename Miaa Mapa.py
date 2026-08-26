import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import psycopg2
import urllib.parse
from sqlalchemy import create_engine
import geopandas as gpd
from shapely import wkt
import re

st.set_page_config(
    page_title="Sistema Scada - Mapa", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(
            f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}",
            pool_recycle=3600,
            pool_pre_ping=True
        )
        return engine
    except Exception as e:
        st.error(f"⚠️ ERROR CRÍTICO DE CONEXIÓN: {e}")
        return None

# Función para cargar pozos desde la base de datos
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
                coords = (lat, lon)
            except: continue

            nuevo_mapa[row['Pozos']] = {
                "coord": coords,
                "bomba": row['bomba'],
                "caudal": row['caudal'],
                "presion": row['presion']
            }
        return nuevo_mapa
    except:
        return {}

# Inicializar mapa centrado en Aguascalientes
mapa_pozos_dict = cargar_mapa_pozos_desde_db()

st.markdown("<h2 style='text-align: center; color: #00d4ff;'>// MAPA DE MONITOREO SCADA</h2>", unsafe_allow_html=True)

# Crear mapa base con Folium
m = folium.Map(location=[21.8853, -102.2916], zoom_start=13, tiles="CartoDB dark_matter")

# Agregar marcadores de pozos
for id_pozo, info in mapa_pozos_dict.items():
    lat, lon = info["coord"]
    folium.CircleMarker(
        location=[lat, lon],
        radius=6,
        color="#00d4ff",
        fill=True,
        fill_color="#00d4ff",
        fill_opacity=0.8,
        popup=f"<b>Pozo:</b> {id_pozo}"
    ).add_to(m)

# Renderizar el mapa en Streamlit
st_folium(m, width="100%", height=650)
