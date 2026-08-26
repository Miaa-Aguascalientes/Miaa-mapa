import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import Fullscreen, MousePosition, LocateControl
import geopandas as gdp # O geopandas
from shapely import wkt
import re

# Asegúrate de que las funciones de carga de base de datos estén definidas previamente en tu entorno, 
# tales como: get_mysql_telemetria_engine, cargar_sectores_poligonos, cargar_mapa_pozos_desde_db,
# cargar_tanques_desde_db, cargar_rebombeos_desde_db, cargar_puntos_de_control_desde_db,
# cargar_puntos_criticos_desde_db, cargar_vrp_desde_db, cargar_medidores_desde_db, 
# obtener_pozos_con_incidencias_hoy, calcular_color_colonia, get_todas_las_colonias

# ==========================================
# 🗺️ GENERACIÓN Y CONFIGURACIÓN DEL MAPA
# ==========================================

def render_mapa_scada():
    # Coordenadas centrales de Aguascalientes
    centro_ags = [21.8853, -102.2916]
    
    # Inicializar mapa base con tema oscuro de CartoDB
    m = folium.Map(
        location=centro_ags,
        zoom_start=13,
        tiles="CartoDB dark_matter",
        control_scale=True
    )

    # Controles adicionales en el mapa
    Fullscreen(position="topright").add_to(m)
    MousePosition(position="bottomright", separator=" | ", prefix="Coordenadas:").add_to(m)
    LocateControl(position="topright", strings={"title": "Mi ubicación"}).add_to(m)

    # ==========================================
    # 1. CAPA DE COLONIAS Y AFECTACIONES
    # ==========================================
    pozos_incidencias = obtener_pozos_con_incidencias_hoy()
    gdf_colonias = get_todas_las_colonias()
    
    if gdf_colonias is not None and not gdf_colonias.empty:
        g_colonias = folium.FeatureGroup(name="🏠 Colonias y Afectaciones", overlay=True)
        
        for _, row in gdf_colonias.iterrows():
            geom = row['geometry']
            props = row.to_dict()
            color_hex, suma_afect = calcular_color_colonia(props, pozos_incidencias)
            
            # Popup informativo para colonias
            html_popup = f"""
            <div style="font-family:sans-serif; color:#000; min-width:200px;">
                <b style="color:#00d4ff;">Colonia / Asentamiento:</b> {props.get('Col_atl', 'S/N')}<br>
                <b>Sector:</b> {props.get('Sector', 'S/C')}<br>
                <b>Supervisor:</b> {props.get('Supervisor', 'S/N')}<br>
                <b>Afectación Acumulada:</b> {suma_afect}%
            </div>
            """
            
            folium.GeoJson(
                geom,
                style_function=lambda x, col=color_hex: {
                    'fillColor': col,
                    'color': '#ffffff',
                    'weight': 1,
                    'fillOpacity': 0.45
                },
                popup=folium.Popup(html_popup, max_width=300)
            ).add_to(g_colonias)
            
        g_colonias.add_to(m)

    # ==========================================
    # 2. CAPA DE SECTORES HIDRÁULICOS
    # ==========================================
    sectores = cargar_sectores_poligonos()
    if sectores:
        g_sectores = folium.FeatureGroup(name="⚡ Sectores Hidráulicos", overlay=True, show=False)
        for sec in sectores:
            try:
                geom_data = json.loads(sec['geo']) if isinstance(sec['geo'], str) else sec['geo']
                folium.GeoJson(
                    geom_data,
                    style_function=lambda x: {
                        'fillColor': '#00d4ff',
                        'color': '#00d4ff',
                        'weight': 1.5,
                        'fillOpacity': 0.1
                    },
                    tooltip=f"Sector: {sec.get('sector', 'N/A')}"
                ).add_to(g_sectores)
            except Exception:
                pass
        g_sectores.add_to(m)

    # ==========================================
    # 3. CAPA DE POZOS
    # ==========================================
    mapa_pozos = cargar_mapa_pozos_desde_db()
    if mapa_pozos:
        g_pozos = folium.FeatureGroup(name="💧 Pozos", overlay=True)
        for id_p, p_info in mapa_pozos.items():
            coord = p_info.get('coord')
            if not coord: continue
            
            color = p_info.get('color_final', '#00ff00')
            estado = p_info.get('status_label', 'OPERANDO')
            
            html_pozo = f"""
            <div style="font-family:sans-serif; color:#000; font-size:12px;">
                <b>Pozo / Sitio:</b> {id_p}<br>
                <b>Estado:</b> <span style="color:{color}; font-weight:bold;">{estado}</span><br>
                <a href="?graficar_pozo={id_p}&nombre={id_p}" target="_self" style="color:#00d4ff; font-weight:bold;">📊 Ver Gráficas y Variables</a>
            </div>
            """
            
            folium.CircleMarker(
                location=coord,
                radius=6,
                color=color,
                weight=1.5,
                fill=True,
                fill_color=color,
                fill_opacity=0.85,
                popup=folium.Popup(html_pozo, max_width=250),
                tooltip=f"Pozo: {id_p} ({estado})"
            ).add_to(g_pozos)
        g_pozos.add_to(m)

    # ==========================================
    # 4. CAPA DE TANQUES
    # ==========================================
    mapa_tanques = cargar_tanques_desde_db()
    if mapa_tanques:
        g_tanques = folium.FeatureGroup(name="🛢️ Tanques", overlay=True)
        for id_t, t_info in mapa_tanques.items():
            coord = t_info.get('coord')
            if not coord: continue
            nombre = t_info.get('nombre', id_t)
            tag_nivel = t_info.get('tag_nivel', '')
            
            html_tanque = f"""
            <div style="font-family:sans-serif; color:#000;">
                <b>Tanque:</b> {nombre}<br>
                <a href="?graficar_tanque={tag_nivel}&nombre={nombre}" target="_self" style="color:#00d4ff; font-weight:bold;">📊 Ver Análisis de Nivel</a>
            </div>
            """
            
            folium.Marker(
                location=coord,
                icon=folium.Icon(color="blue", icon="database", prefix="fa"),
                popup=folium.Popup(html_tanque, max_width=250),
                tooltip=f"Tanque: {nombre}"
            ).add_to(g_tanques)
        g_tanques.add_to(m)

    # ==========================================
    # 5. CAPA DE MACROMEDIDORES
    # ==========================================
    mapa_medidores = cargar_medidores_desde_db()
    if mapa_medidores:
        g_macrom = folium.FeatureGroup(name="📈 Macromedidores", overlay=True)
        for id_m, m_info in mapa_medidores.items():
            coord = m_info.get('coord')
            if not coord: continue
            nombre = m_info.get('nombre', id_m)
            
            html_macro = f"""
            <div style="font-family:sans-serif; color:#000;">
                <b>Macromedidor:</b> {nombre}<br>
                <a href="?ver_grafico={id_m}&nombre={nombre}&access=granted" target="_self" style="color:#00d4ff; font-weight:bold;">📊 Ver Gráficas de Macro</a>
            </div>
            """
            
            folium.CircleMarker(
                location=coord,
                radius=5,
                color="#00FFFF",
                fill=True,
                fill_color="#00FFFF",
                fill_opacity=0.9,
                popup=folium.Popup(html_macro, max_width=250),
                tooltip=f"Macro: {nombre}"
            ).add_to(g_macrom)
        g_macrom.add_to(m)

    # Control de capas de Folium
    folium.LayerControl(collapsed=False).add_to(m)

    return m

# Renderizar en la aplicación Streamlit
st.markdown("### 🗺️ Visualizador Geográfico SCADA")
mapa_renderizado = render_mapa_scada()
st_folium(mapa_renderizado, width="100%", height=750, returned_objects=[])
