import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static, st_folium
from folium.plugins import Fullscreen, MousePosition, LocateControl
from sqlalchemy import create_engine, event
import psycopg2
import json
import urllib.parse
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import locale
from shapely import wkt
import geopandas as gpd
import re
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sqlalchemy.exc import OperationalError
import pytz

# 1. CONFIGURACIÓN DE PÁGINA Y PARÁMETROS
params = st.query_params
sector_seleccionado = params.get("sector", None)

if sector_seleccionado:
    titulo_pestaña = f"MIAA - Estado de Sector: {sector_seleccionado}"
else:
    titulo_pestaña = "MIAA - Estado de Pozos"

st.set_page_config(
    page_title=titulo_pestaña, 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# 2. FUNCIONES DE CONEXIÓN A BASES DE DATOS
@st.cache_resource
def get_postgres_conn():
    try: 
        conn = psycopg2.connect(**st.secrets["postgres"])
        return conn
    except Exception as e: 
        st.error(f"Error de conexión Postgres: {e}")
        return None

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
        st.error(f"⚠️ ERROR CRÍTICO DE CONEXIÓN TELEMETRÍA: {e}")
        return None

@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        
        @event.listens_for(engine, "connect")
        def set_big_selects(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("SET SESSION SQL_BIG_SELECTS=1;")
            cursor.close()
            
        with engine.connect() as conn: pass 
        return engine
    except Exception as e:
        st.error(f"Error al conectar a la BD SCADA: {e}")
        return None

# 3. FUNCIONES DE CARGA Y PROCESAMIENTO DE DATOS
def cargar_datos_scada(lista_tags):
    engine = get_mysql_scada_engine()
    if not engine or not lista_tags: return {}
    try:
        tags_str = "', '".join(lista_tags)
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA 
            FROM VfiTagNumHistory_Ultimo h 
            JOIN VfiTagRef r ON h.GATEID = r.GATEID 
            WHERE r.NAME IN ('{tags_str}') 
            AND h.FECHA = (SELECT MAX(FECHA) FROM VfiTagNumHistory_Ultimo WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%d/%m %H:%M') if row['FECHA'] else "N/A") for _, row in df.iterrows()}
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
        st.error(f"Error cargando polígonos: {e}")
    return None

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
                        val_afect = float(val_str)
                        suma_afectacion += val_afect
                    except:
                        pass

    if not tiene_incidencia_activa:
        return '#3498DB', 0

    if 76 <= suma_afectacion <= 100:
        return '#FF0000', suma_afectacion
    elif 51 <= suma_afectacion <= 75:
        return '#FFFF00', suma_afectacion
    elif 31 <= suma_afectacion <= 50:
        return '#FFA500', suma_afectacion
    elif 1 <= suma_afectacion <= 30:
        return '#69ADDD', suma_afectacion
    else:
        return '#FF0000', suma_afectacion

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
                "presion": row['presion'],
                "sumergencia": row['sumergencia'],
                "nivel_dinamico": row['nivel_dinamico'],
                "nivel_tanque": row['nivel_tanque'],
                "columna": row['columna'],
                "h_arranque": row['H_arranque'],
                "h_paro": row['H_paro'],
                "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']],
                "totalizado": row['totalizado']
            }
        return nuevo_mapa
    except:
        return {}

# 4. CARGA DE CONFIGURACIÓN DE POZOS Y ESTADOS
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
pozos_con_incidencia = obtener_pozos_con_incidencias_hoy()

tags_a_consultar = []
for p in mapa_pozos_dict.values():
    tags_a_consultar.extend([
        p['bomba'], p['caudal'], p['presion'], p['nivel_tanque'],
        p['nivel_dinamico'], p['sumergencia'], p['columna']
    ])
    tags_a_consultar.extend(p['voltajes_l'] + p['amperajes_l'])

tags_finales = list(set([str(t).strip() for t in tags_a_consultar if t and str(t) not in ['0', 'Sin telemetria', 'None']]))
data_scada = cargar_datos_scada(tags_finales)

ahora = datetime.utcnow() - timedelta(hours=6) 
pozos_on, pozos_off, pozos_sin_telemetria, pozos_falla_com = [], [], [], []

for id_p, info in mapa_pozos_dict.items():
    bomba_val = str(info['bomba']).strip()
    if bomba_val == "Sin telemetria":
        info.update({'status_label': 'SIN TELEMETRÍA', 'color_final': '#808080', 'blink': False})
        pozos_sin_telemetria.append(id_p)
        continue

    tag_l1 = info['voltajes_l'][0] if info['voltajes_l'] else None
    es_falla_com = False
    if tag_l1 and tag_l1 != 'N/A':
        _, fecha_str = data_scada.get(tag_l1, (0, "N/A"))
        if fecha_str != "N/A":
            try:
                fecha_dt = datetime.strptime(f"{ahora.year}/{fecha_str}", "%Y/%d/%m %H:%M")
                if (ahora - fecha_dt).total_seconds() / 3600 > 4: es_falla_com = True
            except: es_falla_com = True
        else: es_falla_com = True
    else:
        es_falla_com = True

    if es_falla_com:
        info.update({'status_label': 'FALLA COM.', 'color_final': '#FFA500', 'blink': True})
        pozos_falla_com.append(id_p)
    else:
        val_bba, _ = data_scada.get(info['bomba'], (0, "N/A"))
        if val_bba >= 1:
            info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
            pozos_on.append(id_p)
        else:
            info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
            pozos_off.append(id_p)

# 5. INTERFAZ PRINCIPAL - MAPA EXCLUSIVO CON COLONIAS Y POZOS
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        .block-container { padding-top: 1rem !important; }
    </style>
""", unsafe_allow_html=True)

st.title("🗺️ Monitoreo Operativo: Colonias, Pozos e Incidencias")

m = folium.Map(location=[21.8853, -102.2916], zoom_start=12, tiles='CartoDB dark_matter')

# 1. Dibujar Capa de Colonias con Popup Detallado
gdf_colonias = get_todas_las_colonias()
if gdf_colonias is not None and not gdf_colonias.empty:
    for _, row in gdf_colonias.iterrows():
        props = row.to_dict()
        color_colonia, afec_val = calcular_color_colonia(props, pozos_con_incidencia)
        
        # Construir detalle de pozos asociados e incidencias para el popup
        pozos_str = props.get('Pozos', 'N/A')
        sector_val = props.get('Sector', 'N/A')
        distrito_val = props.get('Distrito', 'N/A')
        col_atl = props.get('Col_atl', 'N/A')
        
        incidencias_colonia_html = ""
        for i in range(1, 11):
            p_val = props.get(f'Pozo_{i}')
            af_val = props.get(f'Afectacion_{i}')
            if p_val:
                p_limpio = str(p_val).strip().upper()
                if p_limpio in pozos_con_incidencia:
                    incidencias_colonia_html += f"<br>&nbsp;&nbsp;• <b>{p_limpio}:</b> {pozos_con_incidencia[p_limpio]} ({af_val}%)"

        popup_html = f"""
        <div style="font-family: sans-serif; font-size: 12px; color: #000; min-width: 220px;">
            <b>Colonia:</b> {col_atl}<br>
            <b>Pozos:</b> {pozos_str}<br>
            <b>Sector:</b> {sector_val}<br>
            <b>Distrito:</b> {distrito_val}
            {f"<br><b>Incidencias:</b> {incidencias_colonia_html}" if incidencias_colonia_html else ""}
            <br><b>Afectación Total:</b> {afec_val}%
        </div>
        """

        folium.GeoJson(
            row['geometry'].__geo_interface__,
            style_function=lambda x, col=color_colonia: {
                'fillColor': col,
                'color': '#2980B9',
                'weight': 1,
                'fillOpacity': 0.25 if col == '#3498DB' else 0.55
            },
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"<b>Colonia:</b> {col_atl} | Afectación: {afec_val}%"
        ).add_to(m)

# 2. Dibujar Pozos, Etiquetas de Número y Alerta de Incidencia Registrada
for id_p, info in mapa_pozos_dict.items():
    coord = info.get('coord')
    if coord:
        color_pozo = info.get('color_final', '#808080')
        
        folium.CircleMarker(
            location=coord,
            radius=5,
            color=color_pozo,
            fill=True,
            fill_color=color_pozo,
            fill_opacity=0.9,
            popup=folium.Popup(f"<b>Pozo:</b> {id_p}<br><b>Estado:</b> {info.get('status_label')}", max_width=300),
            tooltip=f"Pozo: {id_p} ({info.get('status_label')})"
        ).add_to(m)
        
        # Verificar si el pozo tiene una incidencia activa registrada hoy para mostrar la etiqueta flotante
        id_limpio = str(id_p).strip().upper()
        incidencia_texto = pozos_con_incidencia.get(id_limpio)
        
        if incidencia_texto:
            # Etiqueta flotante avanzada con estilo de alerta (Llave inglesa + Diagnóstico)
            html_etiqueta = f"""
                <div style="background-color: #C0392B; color: #FFFFFF; padding: 3px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; display: inline-flex; align-items: center; box-shadow: 2px 2px 5px rgba(0,0,0,0.5); white-space: nowrap; border: 1px solid #FFF;">
                    <span style="margin-right: 4px;">🔧</span> {id_p}: {incidencia_texto}
                </div>
            """
            folium.marker.Marker(
                location=coord,
                icon=folium.DivIcon(html=html_etiqueta, icon_size=(150, 30), icon_anchor=(-10, 15))
            ).add_to(m)
        else:
            # Etiqueta simple con el número del pozo al lado
            html_etiqueta = f"""
                <div style="font-size: 10px; font-weight: bold; color: #FFFFFF; text-shadow: 1px 1px 2px #000000; white-space: nowrap;">
                    {id_p}
                </div>
            """
            folium.marker.Marker(
                location=coord,
                icon=folium.DivIcon(html=html_etiqueta, icon_size=(50, 20), icon_anchor=(-8, 8))
            ).add_to(m)

# Renderizar el mapa en Streamlit
st_folium(m, width="100%", height=700)
