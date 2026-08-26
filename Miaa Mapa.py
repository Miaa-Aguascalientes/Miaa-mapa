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

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="MIAA - Mapa de Operación y SCADA", 
    page_icon="https://www.miaa.mx/favicon.ico", 
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
        return '#00B4D8', 0  # Azul estilo interfaz SCADA

    if tiene_incidencia_activa and suma_afectacion == 0:
        return '#FF8800', 1  

    if 76 <= suma_afectacion <= 100:
        return '#FF0033', suma_afectacion  # Rojo alerta alta
    elif 51 <= suma_afectacion <= 75:
        return '#FFCC00', suma_afectacion  # Amarillo
    elif 31 <= suma_afectacion <= 50:
        return '#FF8800', suma_afectacion  # Naranja
    elif 1 <= suma_afectacion <= 30:
        return '#0077B6', suma_afectacion  
    else:
        return '#FF0033', suma_afectacion

# --- CREACIÓN DEL MAPA ESTILO OSCURO (CartoDB dark_matter) ---
m = folium.Map(location=[21.8853, -102.2916], zoom_start=13, tiles='CartoDB dark_matter')

# Grupos de Capas (LayerControl interactivo)
capa_colonias = folium.FeatureGroup(name='Colonias', show=True)
capa_pozos = folium.FeatureGroup(name='Pozos', show=True)
capa_etiquetas = folium.FeatureGroup(name='Etiquetas de Incidencias', show=True)

gdf_colonias = get_todas_las_colonias()
pozos_incidencias = obtener_pozos_con_incidencias_hoy()

# 1. Añadir Capa de Colonias
if gdf_colonias is not None:
    def style_function(feature):
        props = feature['properties']
        color, _ = calcular_color_colonia(props, pozos_incidencias)
        return {
            'fillColor': color,
            'color': '#0099FF',
            'weight': 0.8,
            'fillOpacity': 0.25
        }

    folium.GeoJson(
        gdf_colonias,
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=['Col_atl', 'Sector', 'Supervisor'],
            aliases=['Colonia:', 'Sector:', 'Supervisor:'],
            localize=True
        )
    ).add_to(capa_colonias)

# 2. Añadir Capa de Pozos y Etiquetas Flotantes Estilo SCADA
pozos_dict = cargar_mapa_pozos_desde_db()
for nombre_pozo, info in pozos_dict.items():
    coord = info.get("coord")
    if coord:
        tiene_inc = nombre_pozo in pozos_incidencias or nombre_pozo.replace('-', '') in [p.replace('-', '') for p in pozos_incidencias]
        diagnostico_texto = pozos_incidencias.get(nombre_pozo, pozos_incidencias.get(nombre_pozo.replace('-', ''), "INCIDENCIA ACTIVA"))
        
        color_punto = '#FF0033' if tiene_inc else '#00FF66'  # Verde brillante para pozos normales, rojo para incidencias
        
        # Marcador del pozo
        folium.CircleMarker(
            location=coord,
            radius=4,
            color=color_punto,
            fill=True,
            fill_color=color_punto,
            fill_opacity=0.9,
            popup=f"<b>Pozo:</b> {nombre_pozo}<br><b>Estado:</b> {'Con Incidencia: ' + diagnostico_texto if tiene_inc else 'Operando Normal'}"
        ).add_to(capa_pozos)
        
        # Etiqueta de texto verde con el nombre del pozo al lado (Estilo de la interfaz)
        folium.Marker(
            location=coord,
            icon=folium.DivIcon(
                html=f'<div style="font-size: 9pt; color: #00FF66; font-weight: bold; text-shadow: 1px 1px 2px black; white-space: nowrap; transform: translate(8px, -10px);">{nombre_pozo}</div>'
            )
        ).add_to(capa_pozos)

        # Si tiene incidencia activa, crear la caja flotante roja distintiva (como en la foto de referencia)
        if tiene_inc:
            html_etiqueta_alerta = f"""
            <div style="
                background-color: #111111; 
                border: 2px solid #FF0033; 
                color: white; 
                padding: 3px 8px; 
                border-radius: 4px; 
                font-family: sans-serif; 
                font-size: 10px; 
                font-weight: bold;
                box-shadow: 0px 0px 8px rgba(255, 0, 51, 0.8);
                white-space: nowrap;
            ">
                <span style="color: #FF0033; margin-right: 4px;">🔧</span> 
                <span style="color: #FFFFFF; margin-right: 6px;">{nombre_pozo}</span> 
                <span style="background-color: #FF0033; color: white; padding: 1px 4px; border-radius: 2px;">{diagnostico_texto.upper()}</span>
            </div>
            """
            folium.Marker(
                location=[coord[0] + 0.0012, coord[1] + 0.0015], # Desplazado ligeramente para no tapar el punto
                icon=folium.DivIcon(html=html_etiqueta_alerta)
            ).add_to(capa_etiquetas)

# Agregar capas al mapa
capa_colonias.add_to(m)
capa_pozos.add_to(m)
capa_etiquetas.add_to(m)

# Control de capas en la esquina superior derecha (idéntico a la referencia)
folium.LayerControl(collapsed=False).add_to(m)

# Renderizar en Streamlit
st.markdown("### Centro de Monitoreo MIAA - Estado General de Red")
st_map = st_folium(m, width="100%", height=780)
