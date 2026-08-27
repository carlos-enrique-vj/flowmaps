"""
viz_interactive.py — Mapa interactivo HTML con Folium/Leaflet
=============================================================

Genera un mapa interactivo con gradiente de color hotspot por distancia
al destino más cercano. Incluye etiquetas visibles, puntos proporcionales al volumen,
y popups informativos.

Función principal:
  - generar_mapa_html(): Crea y guarda el mapa interactivo
"""

import html

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import geopandas as gpd
from typing import Optional, List, Tuple

from .config import FlowMapConfig
from .viz_common import distancia_destino_mas_cercano, obtener_destinos


# ── Paleta de colores ──
COLOR_ORIGEN = '#FFD600'
COLOR_DESTINO = '#ff1744'


def generar_mapa_html(
    polylineas: List[Tuple[list, float]],
    restricciones: Optional[gpd.GeoDataFrame],
    puntos: gpd.GeoDataFrame,
    flujos: gpd.GeoDataFrame,
    config: FlowMapConfig,
) -> object:
    """
    Genera un mapa interactivo HTML con gradiente hotspot.

    Args:
        polylineas: Lista de (coords, flujo) del bundling.
        restricciones: GeoDataFrame de restricciones (puede ser None).
        puntos: GeoDataFrame con puntos únicos.
        flujos: GeoDataFrame de flujos originales.
        config: Configuración del mapa.

    Returns:
        Objeto folium.Map generado.
    """
    try:
        import folium
        from folium.plugins import MiniMap
    except ImportError:
        print("  ERROR: Instalar folium: pip install folium")
        return None

    # Centro del mapa
    todos_y = list(flujos['orig_y']) + list(flujos['dest_y'])
    todos_x = list(flujos['orig_x']) + list(flujos['dest_x'])
    centro_lat = np.mean(todos_y)
    centro_lon = np.mean(todos_x)

    # Coordenadas de todos los destinos. Cada segmento se colorea respecto
    # al más cercano para soportar correctamente análisis multidestino.
    destinos = obtener_destinos(puntos, flujos)

    m = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=11,
        tiles=None,
        attr='FlowMaps',
        control_scale=True,
    )

    # ── Capas base ──
    MAPAS_BASE = {
        'Esri Dark Gray': {
            'tiles': 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
            'attr': 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
        },
        'CartoDB positron': {
            'tiles': 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
            'attr': '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        },
        'OpenStreetMap': {
            'tiles': 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            'attr': '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        },
        'CartoDB dark_matter': {
            'tiles': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
            'attr': '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        }
    }
    
    if config.tiles in MAPAS_BASE:
        mb = MAPAS_BASE[config.tiles]
        folium.TileLayer(
            tiles=mb['tiles'],
            attr=mb['attr'],
            name=config.tiles,
            show=True
        ).add_to(m)
    else:
        folium.TileLayer(config.tiles, name=config.tiles, show=True).add_to(m)
    
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='ArcGIS Satélite',
        show=False
    ).add_to(m)
    
    folium.TileLayer(
        tiles='http://mt0.google.com/vt/lyrs=y&hl=es&x={x}&y={y}&z={z}',
        attr='Google',
        name='Satélite Híbrido',
        show=False
    ).add_to(m)
    
    folium.TileLayer('OpenStreetMap', name='OpenStreetMap', show=False).add_to(m)

    # ── Capa: Flujos con gradiente hotspot ──
    if polylineas:
        _agregar_flujos_gradiente(m, polylineas, destinos, config)

    # ── Capa: Restricciones ──
    if getattr(config, 'dibujar_restricciones', False) and restricciones is not None and not restricciones.empty:
        _agregar_restricciones_html(m, restricciones)

    # ── Capa: Puntos con etiquetas visibles ──
    _agregar_puntos_html(m, puntos, config)

    # ── Capa: Etiquetas controladas por zoom ──
    _agregar_etiquetas_html(m, puntos, config)

    # ── Script para controlar visibilidad de etiquetas según zoom ──
    _agregar_control_zoom_etiquetas(m, config)

    # Título flotante
    titulo_seguro = html.escape(str(config.titulo))
    titulo_html = f'''
    <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
                z-index: 1000; background: rgba(20,20,35,0.9); color: white;
                padding: 12px 24px; border-radius: 8px; font-family: 'Segoe UI', Arial;
                font-size: 16px; font-weight: bold; border: 1px solid rgba(255,215,0,0.3);
                box-shadow: 0 4px 15px rgba(0,0,0,0.5);">
        {titulo_seguro}
        <div style="font-size: 10px; font-weight: normal; opacity: 0.7; margin-top: 4px;">
            {len(flujos)} flujos | Volumen total: {flujos['volumen'].sum():,.0f}
        </div>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(titulo_html))

    # Leyenda
    _agregar_leyenda_html(m, polylineas, config, len(destinos))

    # Mini mapa
    if config.tiles in MAPAS_BASE:
        mb = MAPAS_BASE[config.tiles]
        import folium
        minimap_layer = folium.TileLayer(
            tiles=mb['tiles'],
            attr=mb['attr']
        )
    else:
        minimap_layer = config.tiles

    MiniMap(tile_layer=minimap_layer, toggle_display=True,
            position='bottomleft', width=150, height=150).add_to(m)

    # Control de capas
    folium.LayerControl(collapsed=True).add_to(m)

    # Guardar
    if config.html_salida:
        m.save(config.html_salida)
        print(f"  Mapa HTML guardado: {config.html_salida}")

    return m


def _agregar_flujos_gradiente(m, polylineas, destinos, config):
    """
    Agrega polilíneas con gradiente de color hotspot al mapa Folium.

    Cada polilínea se divide en sub-segmentos coloreados por distancia
    al destino más cercano, creando un degradado espacial continuo y un
    hotspot independiente alrededor de cada destino.
    """
    import folium

    cmap = plt.get_cmap(config.colormap)

    # Calcular rango global de distancias
    todas_dist = []
    for coords, _ in polylineas:
        for x, y in coords:
            d = distancia_destino_mas_cercano(x, y, destinos)
            todas_dist.append(d)
    dist_min = min(todas_dist)
    dist_max = max(todas_dist)
    dist_rango = dist_max - dist_min if dist_max != dist_min else 1.0

    # Normalización de volumen para grosor
    volumenes = [f for _, f in polylineas]
    vol_min, vol_max = min(volumenes), max(volumenes)
    vol_rango = vol_max - vol_min if vol_max != vol_min else 1.0

    fg_flujos = folium.FeatureGroup(name='Flujos', show=True)

    # Ordenar por volumen (gruesos primero)
    polylineas_ord = sorted(polylineas, key=lambda x: x[1])

    for coords, flujo in polylineas_ord:
        if len(coords) < 2:
            continue

        vol_norm = (flujo - vol_min) / vol_rango
        vol_suave = np.power(vol_norm, 0.55)
        grosor = config.grosor_min_html + \
            (config.grosor_max_html - config.grosor_min_html) * vol_suave

        # Dividir la polilínea en grupos de ~5-8 puntos para el gradiente
        # (balance entre calidad visual y rendimiento)
        paso = max(1, len(coords) // 12)

        for i in range(0, len(coords) - 1, paso):
            fin = min(i + paso + 1, len(coords))
            sub_coords = coords[i:fin]

            if len(sub_coords) < 2:
                continue

            # Distancia del punto medio al destino geográficamente más próximo
            mid_idx = len(sub_coords) // 2
            mid_x, mid_y = sub_coords[mid_idx]
            dist = distancia_destino_mas_cercano(mid_x, mid_y, destinos)
            dist_norm = (dist - dist_min) / dist_rango

            # Color del colormap
            color_rgba = cmap(0.1 + 0.9 * dist_norm)
            color_hex = mcolors.to_hex(color_rgba)

            opacidad = 0.45 + 0.45 * vol_suave

            # Coordenadas (x,y) → (lat, lon)
            coords_latlon = [[c[1], c[0]] for c in sub_coords]

            folium.PolyLine(
                coords_latlon,
                weight=grosor,
                color=color_hex,
                opacity=opacidad,
                tooltip=f"Flujo: {flujo:,.0f}",
                smooth_factor=1.5,
            ).add_to(fg_flujos)

    fg_flujos.add_to(m)


def _agregar_restricciones_html(m, restricciones):
    """Agrega polígonos de restricción al mapa Folium."""
    import folium

    fg_rest = folium.FeatureGroup(name='Restricciones', show=True)

    colores = {'agua': '#1e3a5f', 'montaña': '#8b6914', 'pantano': '#2d4a3e'}

    for _, fila in restricciones.iterrows():
        tipo = fila.get('tipo', 'default')
        color = colores.get(tipo, '#555555')
        nombre = html.escape(str(fila.get('nombre', tipo)))

        folium.GeoJson(
            fila.geometry.__geo_interface__,
            style_function=lambda x, c=color: {
                'fillColor': c, 'color': c,
                'fillOpacity': 0.4, 'weight': 1.5,
            },
            tooltip=nombre,
        ).add_to(fg_rest)

    fg_rest.add_to(m)


def _agregar_puntos_html(m, puntos, config):
    """
    Agrega marcadores circulares: amarillos (orígenes) y rojos (destino).
    Tamaño proporcional al volumen.
    """
    import folium

    fg_puntos = folium.FeatureGroup(name='Puntos', show=True)

    if puntos is None or puntos.empty:
        fg_puntos.add_to(m)
        return

    vol_max = puntos['volumen_total'].max() if 'volumen_total' in puntos.columns else 1
    if vol_max == 0:
        vol_max = 1

    origenes = puntos[puntos['tipo'] == 'origen']
    destinos = puntos[puntos['tipo'] == 'destino']

    # ── Orígenes: círculos amarillos proporcionales al volumen ──
    for _, p in origenes.iterrows():
        lat, lon = p.geometry.y, p.geometry.x
        etiqueta = p.get('etiqueta', '')
        etiqueta_segura = html.escape(str(etiqueta))
        vol = p.get('volumen_total', 0)

        # Radio proporcional al volumen
        radio = 3 + 14 * (vol / vol_max)

        popup_html = f"""
        <div style="font-family: 'Segoe UI', Arial; min-width: 180px;">
            <b style="font-size: 13px; color: {COLOR_ORIGEN};">{etiqueta_segura}</b><br>
            <hr style="margin: 4px 0; border-color: #444;">
            <b>Tipo:</b> Origen<br>
            <b>Volumen:</b> {vol:,.0f}<br>
            <b>Coords:</b> {lat:.5f}, {lon:.5f}
        </div>
        """

        folium.CircleMarker(
            location=[lat, lon],
            radius=radio,
            color='#886600',
            weight=1.0,
            fill=True,
            fill_color=COLOR_ORIGEN,
            fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"{etiqueta_segura} ({vol:,.0f})",
        ).add_to(fg_puntos)

    # ── Destino: marcador rojo grande con nombre individual ──
    for _, p in destinos.iterrows():
        lat, lon = p.geometry.y, p.geometry.x
        vol = p.get('volumen_total', 0)
        # Usar la etiqueta real del destino si existe, sino config.nombre_destino
        nombre_dest = p.get('etiqueta', '') or ''
        if not nombre_dest or str(nombre_dest) in ('', 'nan'):
            nombre_dest = config.nombre_destino
        nombre_dest_seguro = html.escape(str(nombre_dest))

        popup_html = f"""
        <div style="font-family: 'Segoe UI', Arial; min-width: 180px;">
            <b style="font-size: 14px; color: {COLOR_DESTINO};">{nombre_dest_seguro}</b><br>
            <hr style="margin: 4px 0; border-color: #444;">
            <b>Tipo:</b> Destino<br>
            <b>Volumen total recibido:</b> {vol:,.0f}<br>
            <b>Coords:</b> {lat:.5f}, {lon:.5f}
        </div>
        """

        folium.CircleMarker(
            location=[lat, lon],
            radius=14,
            color='white',
            weight=2.5,
            fill=True,
            fill_color=COLOR_DESTINO,
            fill_opacity=0.9,
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"{nombre_dest_seguro} (Destino: {vol:,.0f})",
        ).add_to(fg_puntos)

    fg_puntos.add_to(m)


def _agregar_etiquetas_html(m, puntos, config):
    """
    Agrega etiquetas de texto controladas por zoom sobre el mapa.
    Usa DivIcon para mostrar el campo_etiqueta de forma fija.
    Tamaño de fuente proporcional al volumen.
    Las etiquetas solo se muestran cuando el zoom es >= zoom_min_etiquetas.
    """
    import folium

    # show=True para que los marcadores estén en el DOM; JS los ocultará si zoom < umbral
    fg_labels = folium.FeatureGroup(name='Etiquetas', show=True)

    if puntos is None or puntos.empty:
        fg_labels.add_to(m)
        return

    vol_max = puntos['volumen_total'].max() if 'volumen_total' in puntos.columns else 1
    if vol_max == 0:
        vol_max = 1

    for _, p in puntos.iterrows():
        etiqueta = p.get('etiqueta', '')
        if not etiqueta or str(etiqueta) in ('', 'nan'):
            continue

        lat, lon = p.geometry.y, p.geometry.x
        vol = p.get('volumen_total', 0)
        es_destino = p['tipo'] == 'destino'

        # Texto y estilo según tipo
        if es_destino:
            # Usar la etiqueta real del destino si existe
            nombre_dest = p.get('etiqueta', '') or ''
            if not nombre_dest or str(nombre_dest) in ('', 'nan'):
                nombre_dest = config.nombre_destino
            texto = nombre_dest
            font_size = 13
            font_color = COLOR_DESTINO
            font_weight = 'bold'
            bg = 'rgba(255,23,68,0.0)'
            offset_y = -5
            css_class = 'label-destino'
        else:
            texto = etiqueta
            # Tamaño proporcional al volumen
            font_size = max(8, int(8 + 5 * (vol / vol_max)))
            font_color = '#FFD600'
            font_weight = 'normal'
            bg = 'rgba(20,20,35,0.7)'
            offset_y = -2
            css_class = 'label-origen-zoom'

        texto_seguro = html.escape(str(texto))
        label_html = f'''
        <div style="
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: {font_size}px;
            font-weight: {font_weight};
            color: {font_color};
            text-shadow: 0 0 4px rgba(0,0,0,0.9), 0 0 8px rgba(0,0,0,0.6);
            white-space: nowrap;
            background: {bg};
            padding: 1px 5px;
            border-radius: 3px;
        ">{texto_seguro}</div>
        '''

        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(
                html=label_html,
                icon_size=(200, 25),
                icon_anchor=(0, offset_y),
                class_name=css_class,
            ),
        ).add_to(fg_labels)

    fg_labels.add_to(m)


def _agregar_control_zoom_etiquetas(m, config):
    """
    Agrega script JavaScript que controla la visibilidad de la capa de etiquetas
    según el nivel de zoom del mapa. Solo muestra etiquetas cuando zoom >= zoom_min_etiquetas.
    """
    import folium

    zoom_min = config.zoom_min_etiquetas

    script_js = f"""
    <script>
    // Inyectar CSS que oculta etiquetas de origen por defecto
    (function() {{
        var style = document.createElement('style');
        style.id = 'label-zoom-style';
        style.textContent = '.label-origen-zoom {{ display: none !important; }}';
        document.head.appendChild(style);
    }})();

    function setupLabelZoomControl() {{
        // Folium guarda el mapa como window.map_XXXX, no como propiedad del DOM
        var mapObj = null;
        for (var key in window) {{
            if (window[key] && typeof window[key].getZoom === 'function' &&
                typeof window[key].on === 'function') {{
                mapObj = window[key];
                break;
            }}
        }}
        if (!mapObj) {{
            setTimeout(setupLabelZoomControl, 200);
            return;
        }}

        var styleEl = document.getElementById('label-zoom-style');

        function toggleLabels(zoom) {{
            if (zoom >= {zoom_min}) {{
                styleEl.textContent = '';
            }} else {{
                styleEl.textContent = '.label-origen-zoom {{ display: none !important; }}';
            }}
        }}

        // Estado inicial
        toggleLabels(mapObj.getZoom());

        // Actualizar al cambiar zoom
        mapObj.on('zoomend', function() {{
            toggleLabels(mapObj.getZoom());
        }});
    }}

    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', setupLabelZoomControl);
    }} else {{
        setupLabelZoomControl();
    }}
    </script>
    """

    m.get_root().html.add_child(folium.Element(script_js))


def _agregar_leyenda_html(m, polylineas, config, cantidad_destinos=1):
    """Agrega leyenda HTML flotante con gradiente de distancia."""
    import folium

    if not polylineas:
        return

    volumenes = [f for _, f in polylineas]
    vol_min = min(volumenes)
    vol_max = max(volumenes)

    # Obtener colores extremos del colormap para la leyenda
    cmap = plt.get_cmap(config.colormap)
    color_cerca = mcolors.to_hex(cmap(0.1))
    color_medio = mcolors.to_hex(cmap(0.5))
    color_lejos = mcolors.to_hex(cmap(0.95))

    nombre_destino_seguro = html.escape(str(config.nombre_destino))
    titulo_distancia = (
        'Distancia al destino más cercano'
        if cantidad_destinos > 1
        else 'Distancia al destino'
    )
    etiqueta_cerca = (
        'Cerca (destino más próximo)'
        if cantidad_destinos > 1
        else f'Cerca ({nombre_destino_seguro})'
    )
    etiqueta_destinos = 'Destinos' if cantidad_destinos > 1 else nombre_destino_seguro
    leyenda_html = f'''
    <div style="position: fixed; bottom: 30px; right: 15px; z-index: 1000;
                background: rgba(20,20,35,0.92); color: white; padding: 14px 18px;
                border-radius: 8px; font-family: 'Segoe UI', Arial; font-size: 11px;
                border: 1px solid rgba(255,255,255,0.15);
                box-shadow: 0 4px 15px rgba(0,0,0,0.4); max-width: 220px;">
        <b style="font-size: 12px;">{titulo_distancia}</b>
        <div style="margin-top: 8px;">
            <div style="display: flex; align-items: center; margin: 4px 0;">
                <div style="width: 40px; height: 8px; background: {color_cerca};
                            border-radius: 2px;"></div>
                <span style="margin-left: 8px;">{etiqueta_cerca}</span>
            </div>
            <div style="display: flex; align-items: center; margin: 4px 0;">
                <div style="width: 40px; height: 8px; background: {color_medio};
                            border-radius: 2px;"></div>
                <span style="margin-left: 8px;">Intermedio</span>
            </div>
            <div style="display: flex; align-items: center; margin: 4px 0;">
                <div style="width: 40px; height: 8px; background: {color_lejos};
                            border-radius: 2px;"></div>
                <span style="margin-left: 8px;">Lejos (origenes)</span>
            </div>
        </div>
        <hr style="border-color: rgba(255,255,255,0.1); margin: 8px 0;">
        <b style="font-size: 11px;">Grosor = Volumen acumulado</b>
        <div style="margin-top: 5px;">
            <div style="display: flex; align-items: center; margin: 3px 0;">
                <div style="width: 40px; height: 2px; background: #888;
                            border-radius: 2px;"></div>
                <span style="margin-left: 8px; opacity: 0.7;">Min: {vol_min:,.0f}</span>
            </div>
            <div style="display: flex; align-items: center; margin: 3px 0;">
                <div style="width: 40px; height: 12px; background: #888;
                            border-radius: 2px;"></div>
                <span style="margin-left: 8px;">Max: {vol_max:,.0f}</span>
            </div>
        </div>
        <hr style="border-color: rgba(255,255,255,0.1); margin: 8px 0;">
        <div style="display: flex; align-items: center; margin: 3px 0;">
            <div style="width: 10px; height: 10px; border-radius: 50%;
                        background: {COLOR_ORIGEN}; margin-right: 8px;"></div>
            Origenes
        </div>
        <div style="display: flex; align-items: center; margin: 3px 0;">
            <div style="width: 10px; height: 10px; border-radius: 50%;
                        background: {COLOR_DESTINO}; margin-right: 8px;"></div>
            {etiqueta_destinos}
        </div>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(leyenda_html))
