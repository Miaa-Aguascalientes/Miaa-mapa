import streamlit as st
import folium
from streamlit_folium import st_folium
import geopandas as gpd
import pandas as pd

def render_mapa_scada(df_pozos, df_tanques, gdf_sectores, gdf_colonias):
    """
    Renderiza el mapa interactivo de telemetría e infraestructura de MIAA.
    """
    st.subheader("🗺️ Monitoreo Geoespacial - Red Hidráulica")

    # Coordenadas centrales de Aguascalientes
    lat_centro, lon_centro = 21.88234, -102.28259
    
    # Inicializar mapa base con tema oscuro o estándar
    m = folium.Map(
        location=[lat_centro, lon_centro],
        zoom_start=12,
        tiles="CartoDB positron"
    )

    # 1. Capa de Sectores Hidráulicos
    if not gdf_sectores.empty:
        folium.GeoJson(
            gdf_sectores,
            name="Sectores Hidráulicos",
            style_function=lambda x: {
                'fillColor': '#3182bd',
                'color': '#08519c',
                'weight': 1.5,
                'fillOpacity': 0.1
            }
        ).add_to(m)

    # 2. Capa de Colonias (Afectaciones / Estados)
    if not gdf_colonias.empty:
        folium.GeoJson(
            gdf_colonias,
            name="Colonias",
            style_function=lambda x: {
                'fillColor': '#de2d26' if x['properties'].get('afectado', False) else '#74c476',
                'color': '#252525',
                'weight': 1,
                'fillOpacity': 0.4
            },
            tooltip=folium.GeoJsonTooltip(fields=['nombre'], aliases=['Colonia:'])
        ).add_to(m)

    # 3. Marcadores de Pozos
    fg_pozos = folium.FeatureGroup(name="Pozos")
    for _, row in df_pozos.iterrows():
        color_pozo = "red" if row.get('estatus', 1) == 0 else "green"
        popup_html = f"""
        <b>Pozo:</b> {row.get('nombre', 'N/D')}<br>
        <b>Estatus:</b> {'Operando' if color_pozo == 'green' else 'Detenido'}<br>
        <b>Caudal:</b> {row.get('caudal', 0)} lps<br>
        <b>Presión:</b> {row.get('presion', 0)} kg/cm²
        """
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=6,
            color=color_pozo,
            fill=True,
            fill_color=color_pozo,
            fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=300)
        ).add_to(fg_pozos)
    fg_pozos.add_to(m)

    # 4. Marcadores de Tanques
    fg_tanques = folium.FeatureGroup(name="Tanques")
    for _, row in df_tanques.iterrows():
        popup_html = f"""
        <b>Tanque:</b> {row.get('nombre', 'N/D')}<br>
        <b>Nivel Actual:</b> {row.get('nivel', 0)} m<br>
        <b>Porcentaje:</b> {row.get('porcentaje', 0)}%
        """
        folium.Marker(
            location=[row['lat'], row['lon']],
            icon=folium.Icon(color="blue", icon="tint", prefix="fa"),
            popup=folium.Popup(popup_html, max_width=300)
        ).add_to(fg_tanques)
    fg_tanques.add_to(m)

    # Control de capas
    folium.LayerControl().add_to(m)

    # Renderizar componente en Streamlit
    st_data = st_folium(m, width="100%", height=600)
    return st_data
