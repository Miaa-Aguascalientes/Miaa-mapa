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

def formato_hora(valor):
    try:
        return str(valor)
    except:
        return "N/A"

def get_blink_icon(color):
    return f"""
    <div style="background-color: {color}; width: 12px; height: 12px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 10px {color};"></div>
    """

# 4. CARGA DE CONFIGURACIÓN DE POZOS Y ESTADOS
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
dic_incidencias_activas = obtener_pozos_con_incidencias_hoy()

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

m = folium.Map(location=[21.8853, -102.2916], zoom_start=12, tiles=None)

# 2. Capas de Fondo (Vista Nocturna)
api_key = "cb1_26ji_1_864817f3cb73c0bdbe0daccd"
    
folium.TileLayer(
    tiles=f"https://{{s}}.basemaps.cartocdn.com/rastertiles/dark_all/{{z}}/{{x}}/{{y}}.png?key={api_key}",
    name="Vista Nocturna",
    attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains="abcd",
    max_zoom=20,
    overlay=False,
    control=True
).add_to(m)

Fullscreen().add_to(m)

ver_colonias = True
ver_pozos = True

# 9.6. RENDERIZADO DE POLÍGONOS DE COLONIAS __________________________________________________________________________________________________________________________________
if ver_colonias:
    gdf_colonias = get_todas_las_colonias()
    
    if gdf_colonias is not None and not gdf_colonias.empty:
        
        lista_incidencias_tooltip = []
        lista_afectacion_tooltip = []
        
        for idx, row in gdf_colonias.iterrows():
            suma_afec = 0.0
            descripciones_fallas = []
            
            for i in range(1, 11):
                pozo_col = row.get(f'Pozo_{i}')
                afectacion_col = row.get(f'Afectacion_{i}')
                
                if pd.notna(pozo_col):
                    id_p_limpio = str(pozo_col).strip().upper()
                    id_p_con_guion = re.sub(r'^([A-Z]+)(\d+)([A-Z]*)$', r'\1-\2\3', id_p_limpio)
                    id_p_sin_guion = id_p_limpio.replace('-', '')
                    
                    if (id_p_limpio in dic_incidencias_activas or 
                        id_p_con_guion in dic_incidencias_activas or 
                        id_p_sin_guion in dic_incidencias_activas):
                        
                        falla = (
                            dic_incidencias_activas.get(id_p_limpio) or 
                            dic_incidencias_activas.get(id_p_con_guion) or 
                            dic_incidencias_activas.get(id_p_sin_guion, 'Activa')
                        )
                        if isinstance(falla, dict):
                            falla_txt = falla.get('diagnostico', falla.get('motivo', 'Activa'))
                        else:
                            falla_txt = str(falla)
                            
                        descripciones_fallas.append(f"{pozo_col}: {falla_txt}")
                        
                        if pd.notna(afectacion_col):
                            try:
                                val_str = str(afectacion_col).replace('%', '').strip()
                                val_f = float(val_str)
                                suma_afec += val_f  
                            except:
                                pass
            
            if descripciones_fallas:
                lista_incidencias_tooltip.append(" | ".join(descripciones_fallas))
                lista_afectacion_tooltip.append(f"{int(suma_afec)}%" if suma_afec > 0 else "N/D")
            else:
                lista_incidencias_tooltip.append("Ninguna")
                lista_afectacion_tooltip.append("0%")

        gdf_colonias['Info_Incidencia'] = lista_incidencias_tooltip
        gdf_colonias['Info_Porcentaje'] = lista_afectacion_tooltip

        fg_colonias = folium.FeatureGroup(name="Colonias")
        
        def estilo_final(feature):
            props = feature.get('properties', {})
            nombre_actual = props.get('Col_atl')
            col_sel = st.session_state.get('colonia_resaltada')
            es_match = (col_sel is not None and nombre_actual == col_sel.get('Col_atl'))
            
            color_dinamico, afectacion_val = calcular_color_colonia(props, dic_incidencias_activas)
            fill_color_final = '#F1C40F' if es_match else color_dinamico
            
            if es_match:
                border_color_final = '#F39C12'
                weight_final = 3
                opacity_final = 0.5
            elif afectacion_val > 0:
                border_color_final = color_dinamico
                weight_final = 2.5
                opacity_final = 0.25
            else:
                border_color_final = '#2980B9'
                weight_final = 1
                opacity_final = 0.08
            
            return {
                'fillColor': fill_color_final,
                'color': border_color_final,
                'weight': weight_final,
                'fillOpacity': opacity_final
            }

        def estilo_hover(feature):
            return {'fillOpacity': 0.8, 'weight': 4, 'color': '#FFFFFF'}

        folium.GeoJson(
            gdf_colonias,
            name="Colonias",
            style_function=estilo_final,
            highlight_function=estilo_hover,
            tooltip=folium.GeoJsonTooltip(
                fields=['Col_atl', 'Pozos', 'Sector', 'Distrito', 'Info_Incidencia', 'Info_Porcentaje'],
                aliases=['Colonia:', 'Pozos:', 'Sector:', 'Distrito:', 'Incidencia:', 'Afectación:'],
                localize=True,
                sticky=True
            )
        ).add_to(fg_colonias)
        
        fg_colonias.add_to(m)
      
# 9.7. RENDERIZADO DE POZOS EN EL MAPA PRINCIPAL  ___________________________________________________________________________________________________________________________________
if ver_pozos:  
    fg_pozos = folium.FeatureGroup(name="Pozos", overlay=True, control=True)

    for id_p, info in mapa_pozos_dict.items():
        d = lambda tag: data_scada.get(tag, (0, "N/A"))
        is_st = (info['status_label'] == 'SIN TELEMETRÍA')
        q, f_q = d(info['caudal']) if not is_st else (0.0, "N/A")
        p, f_p = d(info['presion']) if not is_st else (0.0, "N/A")
        sumer, f_s = d(info['sumergencia']) if not is_st else (0.0, "N/A")
        dinam, f_d = d(info['nivel_dinamico']) if not is_st else (0.0, "N/A")
        tanq, f_t = d(info['nivel_tanque']) if not is_st else (0.0, "N/A")
        col, f_col = d(info['columna']) if not is_st else (0.0, "N/A")
        h_arr_val, f_h_arr = d(info['h_arranque']) if not is_st else (0.0, "N/A")
        h_par_val, f_h_par = d(info['h_paro']) if not is_st else (0.0, "N/A")
        h_arr_fmt = formato_hora(h_arr_val)
        h_par_fmt = formato_hora(h_par_val)
        v = [d(t) for t in info['voltajes_l']] if not is_st else [(0.0, "N/A")]*3
        a = [d(t) for t in info['amperajes_l']] if not is_st else [(0.0, "N/A")]*3

        id_p_limpio = str(id_p).strip().upper()
        id_p_con_guion = re.sub(r'^([A-Z]+)(\d+)([A-Z]*)$', r'\1-\2\3', id_p_limpio)
        id_p_sin_guion = id_p_limpio.replace('-', '')
        
        tiene_incidencia_activa = (
            id_p_limpio in dic_incidencias_activas or 
            id_p_con_guion in dic_incidencias_activas or 
            id_p_sin_guion in dic_incidencias_activas
        )

        rol_actual = st.session_state.get('rol', 'usuario')
        nombre_codificado = urllib.parse.quote(id_p)
        url_pozo_graf = f"?graficar_pozo={id_p}&nombre={nombre_codificado}&access=granted&role={rol_actual}"

        html_popup = f"""
            <div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 380px; border: 1px solid {info['color_final']}; font-family: sans-serif;">
                <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 10px;">
                    <b style="color: #00d4ff; font-size: 16px;">POZO {id_p}</b>
                    <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
                </div>
                
                <div style="margin-bottom: 12px;">
                    <div style="font-size: 10px; color: #888; margin-bottom: 4px;">HIDRÁULICA</div>
                    <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>💧 Caudal: <b>{q:.2f} L/s</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_q}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px;">
                        <span>🚀 Presión: <b>{p:.2f} kg</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_p}</span>
                    </div>
                </div>

                <div style="margin-bottom: 12px;">
                    <div style="font-size: 10px; color: #888; margin-bottom: 4px;">NIVELES</div>
                    <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>🔋 Nivel de Tanque:<b>{tanq:.2f} mts</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_t}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>📉 Nivel Dinámico/Estatico: <b>{dinam:.2f} m</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_d}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>📏 Sumergencia: <b>{sumer:.2f} m</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_s}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px;">
                        <span>🏗️ Longitud de Columna: <b>{col:.2f} m</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_col}</span>
                    </div>
                </div>

                <div style="margin-bottom: 12px;">
                    <div style="font-size: 10px; color: #888; margin-bottom: 4px;">ELÉCTRICO</div>
                    <table style="width: 100%; font-size: 10px; border-collapse: collapse; margin-bottom: 8px;">
                        <tr style="color: #00d4ff; border-bottom: 1px solid #333; text-align: left;">
                            <th style="padding: 4px;">Fase</th>
                            <th style="padding: 4px;">Voltaje / Act.</th>
                            <th style="padding: 4px;">Amp / Act.</th>
                        </tr>
                        <tr style="border-bottom: 1px solid #222;">
                            <td style="padding: 6px 4px;">L1-L2</td>
                            <td><b>{v[0][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[0][1]}</span></td>
                            <td><b>{a[0][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[0][1]}</span></td>
                        </tr>
                        <tr style="border-bottom: 1px solid #222;">
                            <td style="padding: 6px 4px;">L2-L3</td>
                            <td><b>{v[1][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[1][1]}</span></td>
                            <td><b>{a[1][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[1][1]}</span></td>
                        </tr>
                        <tr>
                            <td style="padding: 6px 4px;">L1-L3</td>
                            <td><b>{v[2][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[2][1]}</span></td>
                            <td><b>{a[2][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[2][1]}</span></td>
                        </tr>
                    </table>
                    <div style="font-size: 10px; color: #888; margin-bottom: 4px; border-top: 1px solid #222; paddingTop: 5px;">HORARIOS</div>
                    <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>▶️ Arranque: <b>{h_arr_fmt}</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_h_arr}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px;">
                        <span>⏹️ Paro: <b>{h_par_fmt}</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_h_par}</span>
                    </div>

                    <div style="border-top: 1px solid #333; padding-top: 10px;">
                    <a href="{url_pozo_graf}" target="_blank" style="text-decoration: none;">
                        <div style="background: #00d4ff; color: #050a10; text-align: center; padding: 10px; border-radius: 6px; font-weight: bold; font-size: 12px;">
                            📊 VER ANÁLISIS HISTÓRICO
                        </div>
                    </a>
                </div>
            </div>
            """

        # 1. Etiqueta de texto del pozo
        folium.Marker(
            location=info['coord'],
            icon=folium.DivIcon(
                icon_size=(150,36),
                icon_anchor=(-12, 6),
                html=f'<div style="font-size: 9px; font-weight: bold; color: {info["color_final"]}; white-space: nowrap; text-shadow: 1px 1px #000; pointer-events: none;">{id_p}</div>'
            )
        ).add_to(fg_pozos)

        # 2. MARCADOR CONDICIONAL (GLOBO DESPLAZADO MÁS A LA DERECHA)
        if tiene_incidencia_activa:
            info_incidencia = (
                dic_incidencias_activas.get(id_p_limpio) or 
                dic_incidencias_activas.get(id_p_con_guion) or 
                dic_incidencias_activas.get(id_p_sin_guion, {})
            )
            
            if isinstance(info_incidencia, dict):
                diagnostico_falla = info_incidencia.get('diagnostico', info_incidencia.get('motivo', 'FALLA'))
            else:
                diagnostico_falla = str(info_incidencia)
            
            html_globo_incidencia = f"""
            <div style="position: relative; width: 350px; height: 80px; pointer-events: none; font-family: sans-serif;">
                <svg style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; overflow: visible;">
                    <line x1="15" y1="65" x2="75" y2="35" stroke="#ff4d4d" stroke-width="2" />
                    <circle cx="15" cy="65" r="4" fill="#ffffff" stroke="#ff4d4d" stroke-width="2" />
                </svg>
                
                <div style="
                    position: absolute;
                    top: 0px;
                    left: 75px;
                    display: inline-flex;
                    align-items: center;
                    background: #000000;
                    border: 2px solid #ff4d4d;
                    border-radius: 6px;
                    padding: 4px 8px;
                    white-space: nowrap;
                    box-shadow: 0 4px 8px rgba(0,0,0,0.6);
                    pointer-events: auto;">
                    <span style="font-size: 14px; margin-right: 6px;">🛠️</span>
                    <span style="font-size: 11px; font-weight: bold; color: #ffffff; margin-right: 8px;">{id_p}</span>
                    <span style="font-size: 10px; font-weight: bold; color: #ffffff; background: #c0392b; padding: 2px 6px; border-radius: 4px;">{diagnostico_falla.upper()}</span>
                </div>
            </div>
            """
            
            folium.Marker(
                location=info['coord'],
                icon=folium.DivIcon(
                    icon_size=(350, 80),
                    icon_anchor=(15, 65),
                    html=html_globo_incidencia
                ),
                popup=folium.Popup(html_popup, max_width=450),
                tooltip=f"⚠️ POZO {id_p} - {diagnostico_falla}"
            ).add_to(fg_pozos)
            
        elif info.get('blink'):
            folium.Marker(
                location=info['coord'],
                icon=folium.DivIcon(html=get_blink_icon(info['color_final'])),
                popup=folium.Popup(html_popup, max_width=450)
            ).add_to(fg_pozos)
        else:
            folium.CircleMarker(
                location=info['coord'],
                radius=2,
                color=info['color_final'],
                fill=True,
                fill_color=info['color_final'],
                fill_opacity=1,
                popup=folium.Popup(html_popup, max_width=450)
            ).add_to(fg_pozos)

    fg_pozos.add_to(m)

# Renderizar el mapa en Streamlit sin recargas innecesarias
st_folium(m, width="100%", height=700, returned_objects=[])
