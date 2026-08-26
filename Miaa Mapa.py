import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import geopandas as gpd
import urllib.parse
from sqlalchemy import create_engine
import psycopg2
from shapely import wkt
import re
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="MIAA - Mapa de Pozos y Colonias", 
    page_icon="[https://www.miaa.mx/favicon.ico](https://www.miaa.mx/favicon.ico)", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CONEXIONES A BASE DE DATOS ---
@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except Exception as e:
        return None

@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: 
        return None

# --- FUNCIONES DE CARGA DE DATOS ---
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
            except: 
                continue

            nuevo_mapa[row['Pozos']] = {
                "coord": coords,
                "bomba": row['bomba'],
                "caudal": row['caudal'],
                "presion": row['presion'],
                "sumergencia": row['sumergencia'],
                "nivel_dinamico": row['nivel_dinamico'],
                "nivel_tanque": row['nivel_tanque'],
                "totalizado": row['totalizado']
            }
        return nuevo_mapa
    except:
        return {}

@st.cache_data(ttl=60)
def obtener_pozos_con_incidencias_hoy():
    engine = get_mysql_scada_engine()
    if engine is None:
        return {}
    try:
        query = """
            SELECT NUM_POZO, DIAGNOSTICO_FALLA, ESTATUS 
            FROM vw_incidencias_en_pozos 
            WHERE ESTATUS != 'CERRADA'
        """
        df_inc = pd.read_sql(query, engine)
        dic_incidencias = {}
        for _, row in df_inc.iterrows():
            val = row['NUM_POZO']
            if pd.notna(val):
                id_limpio = str(val).strip().upper()
                if id_limpio:
                    diagnostico = row['DIAGNOSTICO_FALLA'] or 'Sin diagnóstico'
                    dic_incidencias[id_limpio] = diagnostico
        return dic_incidencias
    except Exception as e:
        return {}

@st.cache_data(ttl=3600)
def get_todas_las_colonias():
    query = """
        SELECT ST_AsText(geom) as geom_wkt, Pozos, Col_atl, Sector, Distrito, Supervisor,
               Pozo_1, Afectacion_1, Pozo_2, Afectacion_2, 
               Pozo_3, Afectacion_3, Pozo_4, Afectacion_4, 
               Pozo_5, Afectacion_5, Pozo_6, Afectacion_6, 
               Pozo_7, Afectacion_7, Pozo_8, Afectacion_8, 
               Pozo_9, Afectacion_9, Pozo_10, Afectacion_10 
        FROM Diccionario_colonias
    """
    try:
        df = pd.read_sql(query, get_mysql_telemetria_engine())
        if not df.empty and df['geom_wkt'].iloc[0] is not None:
            df['geometry'] = df['geom_wkt'].apply(wkt.loads)
            gdf = gpd.GeoDataFrame(df, geometry='geometry')
            gdf.set_crs(epsg=32613, inplace=True)
            return gdf.to_crs(epsg=4326)
    except Exception as e:
        pass
    return None

def calcular_color_colonia(props, pozos_con_incidencia):
    suma_afectacion = 0.0
    tiene_incidencia_activa = False
    
    for i in range(1, 11):
        pozo_col = props.get(f'Pozo_{i}')
        afectacion_col = props.get(f'Afectacion_{i}')
        
        if pozo_col is not None:
            id_p_limpio = str(pozo_col).strip().upper()
            id_p_con_guion = re.sub(r'^([A-Z]+)(\d+)([A-Z]*)$', r'\1-\2\3', id_p_limpio)
            id_p_sin_guion = id_p_limpio.replace('-', '')
            
            if (id_p_limpio in pozos_con_incidencia or 
                id_p_con_guion in pozos_con_incidencia or 
                id_p_sin_guion in pozos_con_incidencia):
                
                tiene_incidencia_activa = True
                if pd.notna(afectacion_col):
                    try:
                        val_str = str(afectacion_col).replace('%', '').strip()
                        suma_afectacion += float(val_str)
                    except:
                        pass

    if not tiene_incidencia_activa:
        return '#3498DB', 0  # Azul para colonias sin afectación activa

    if tiene_incidencia_activa and suma_afectacion == 0:
        return '#FFA500', 1  

    if 76 <= suma_afectacion <= 100:
        return '#FF0000', suma_afectacion  # Rojo
    elif 51 <= suma_afectacion <= 75:
        return '#FFFF00', suma_afectacion  # Amarillo
    elif 31 <= suma_afectacion <= 50:
        return '#FFA500', suma_afectacion  # Naranja
    elif 1 <= suma_afectacion <= 30:
        return '#69ADDD', suma_afectacion  # Azul claro
    else:
        return '#FF0000', suma_afectacion

# --- CREACIÓN DEL MAPA ---
m = folium.Map(location=[21.8853, -102.2916], zoom_start=12, tiles='CartoDB dark_matter')

# 1. Capa de Colonias con polígonos pintados por incidencia
gdf_colonias = get_todas_las_colonias()
pozos_incidencias = obtener_pozos_con_incidencias_hoy()

if gdf_colonias is not None:
    def style_function(feature):
        props = feature['properties']
        color, suma_afec = calcular_color_colonia(props, pozos_incidencias)
        return {
            'fillColor': color,
            'color': color,
            'weight': 1,
            'fillOpacity': 0.4
        }

    folium.GeoJson(
        gdf_colonias,
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=['Col_atl', 'Sector', 'Supervisor'],
            aliases=['Colonia:', 'Sector:', 'Supervisor:'],
            localize=True
        )
    ).add_to(m)

# 2. Capa de Pozos
pozos_dict = cargar_mapa_pozos_desde_db()
for nombre_pozo, info in pozos_dict.items():
    coord = info.get("coord")
    if coord:
        tiene_inc = nombre_pozo in pozos_incidencias or nombre_pozo.replace('-', '') in [p.replace('-', '') for p in pozos_incidencias]
        color_pozo = 'red' if tiene_inc else 'blue'
        
        folium.CircleMarker(
            location=coord,
            radius=5,
            color=color_pozo,
            fill=True,
            fill_color=color_pozo,
            fill_opacity=0.8,
            popup=f"<b>Pozo:</b> {nombre_pozo}<br><b>Estado:</b> {'Con Incidencia' if tiene_inc else 'Operando'}"
        ).add_to(m)

# Renderizar mapa en Streamlit
st.markdown("### Mapa de Pozos y Colonias con Incidencias")
st_map = st_folium(m, width="100%", height=750)
