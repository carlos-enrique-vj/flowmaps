"""
viz_static.py — Visualización estática con Matplotlib
======================================================

Renderiza el mapa de flujos con polilíneas suavizadas y gradiente
de color por distancia al destino más cercano (efecto hotspot). Cada segmento
de cada polilínea se colorea según su distancia al destino más próximo,
creando un degradado espacial continuo.

Función principal:
  - plot_mapa(): Genera la figura completa del flow map
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
import geopandas as gpd
from typing import Optional, List, Tuple

from .config import FlowMapConfig
from .viz_common import distancia_destino_mas_cercano, obtener_destinos

# ── Paleta de colores ──
COLOR_ORIGEN = '#FFD600'     # Amarillo para puntos de origen
COLOR_DESTINO = '#ff1744'    # Rojo para punto de destino


def plot_mapa(
    polylineas: List[Tuple[list, float]],
    restricciones: Optional[gpd.GeoDataFrame],
    puntos: gpd.GeoDataFrame,
    flujos: gpd.GeoDataFrame,
    config: FlowMapConfig,
) -> plt.Figure:
    """
    Renderiza el mapa de flujos con gradiente de color hotspot.

    Args:
        polylineas: Lista de (coords, flujo) del reconstructor de bundling.
        restricciones: GeoDataFrame de restricciones (puede ser None).
        puntos: GeoDataFrame de puntos (orígenes y destinos).
        flujos: GeoDataFrame original de flujos.
        config: Configuración visual.

    Returns:
        plt.Figure: Figura de Matplotlib generada.
    """
    fig, ax = plt.subplots(1, 1, figsize=(16, 14), facecolor=config.fondo_color)
    ax.set_facecolor(config.fondo_color)

    # Obtener todos los destinos para generar un hotspot alrededor de cada uno
    destinos = obtener_destinos(puntos, flujos)

    # ── Capa: Polígonos de restricción ──
    if getattr(config, 'dibujar_restricciones', False):
        _dibujar_restricciones(ax, restricciones)

    # ── Capa: Flujos con gradiente hotspot ──
    if polylineas:
        _dibujar_flujos_gradiente(ax, polylineas, destinos, config)

    # ── Capa: Puntos ──
    _dibujar_puntos(ax, puntos, config)

    # ── Layout y decoración ──
    _configurar_layout(ax, fig, flujos, polylineas, config)

    plt.tight_layout()

    # Guardar
    if config.guardar_como:
        fig.savefig(config.guardar_como, dpi=config.dpi, bbox_inches='tight',
                    facecolor=config.fondo_color, edgecolor='none')
        print(f"  Mapa guardado: {config.guardar_como}")

    return fig


def _dibujar_restricciones(ax, restricciones):
    """Dibuja polígonos de restricción con estilos diferenciados por tipo."""
    if restricciones is None or restricciones.empty:
        return

    colores = {'agua': '#1e3a5f', 'montaña': '#3d2b1f', 'pantano': '#2d4a3e'}
    bordes = {'agua': '#3a7bd5', 'montaña': '#8b6914', 'pantano': '#4a7a5a'}

    for _, fila in restricciones.iterrows():
        tipo = fila.get('tipo', 'default')
        color_fill = colores.get(tipo, '#2a2a3e')
        color_edge = bordes.get(tipo, '#555555')

        geoms = [fila.geometry] if fila.geometry.geom_type == 'Polygon' \
            else list(fila.geometry.geoms) if fila.geometry.geom_type == 'MultiPolygon' \
            else []

        for poly in geoms:
            xs, ys = poly.exterior.xy
            ax.fill(xs, ys, alpha=0.6, color=color_fill, zorder=2)
            ax.plot(xs, ys, color=color_edge, linewidth=1.2, alpha=0.8,
                    linestyle='--', zorder=3)


def _dibujar_flujos_gradiente(ax, polylineas, destinos, config):
    """
    Dibuja polilíneas con gradiente de color por distancia al destino.

    Cada polilínea se descompone en segmentos individuales (pares de puntos).
    Cada segmento se colorea según la distancia de su punto medio al destino
    más cercano:
      - Lejos del destino (max distancia) → extremo "caliente" del colormap
      - Cerca del destino (min distancia) → extremo "frío" del colormap

    Esto crea un efecto hotspot radiante centrado en cada destino.
    """
    cmap = plt.get_cmap(config.colormap)

    # ── Paso 1: Calcular rango global de distancias ──
    todas_distancias = []
    for coords, _ in polylineas:
        for x, y in coords:
            d = distancia_destino_mas_cercano(x, y, destinos)
            todas_distancias.append(d)

    dist_min = min(todas_distancias)
    dist_max = max(todas_distancias)
    dist_rango = dist_max - dist_min if dist_max != dist_min else 1.0

    # Normalización de volumen para grosor
    volumenes = [f for _, f in polylineas]
    vol_min, vol_max = min(volumenes), max(volumenes)
    vol_rango = vol_max - vol_min if vol_max != vol_min else 1.0

    # ── Paso 2: Descomponer cada polilínea en segmentos con color/grosor ──
    segmentos = []
    colores = []
    grosores = []

    for coords, flujo in polylineas:
        if len(coords) < 2:
            continue

        # Grosor basado en volumen acumulado
        vol_norm = (flujo - vol_min) / vol_rango
        vol_suave = np.power(vol_norm, 0.55)
        grosor = config.grosor_min + (config.grosor_max - config.grosor_min) * vol_suave

        # Cada par de puntos consecutivos = un segmento
        for i in range(len(coords) - 1):
            seg = [coords[i], coords[i + 1]]
            segmentos.append(seg)
            grosores.append(grosor)

            # Distancia del punto medio al destino más cercano
            mid_x = (coords[i][0] + coords[i + 1][0]) / 2
            mid_y = (coords[i][1] + coords[i + 1][1]) / 2
            dist = distancia_destino_mas_cercano(mid_x, mid_y, destinos)
            dist_norm = (dist - dist_min) / dist_rango

            # Mapear distancia a color (0=cerca/frío → 1=lejos/caliente)
            color = cmap(0.1 + 0.9 * dist_norm)
            colores.append(color)

    # ── Paso 3: Ordenar por grosor (gruesos primero = quedan abajo) ──
    indices = np.argsort(grosores)[::-1]
    seg_ord = [segmentos[i] for i in indices]
    gro_ord = [grosores[i] for i in indices]
    col_ord = [colores[i] for i in indices]

    # ── Capa glow exterior ──
    lc_glow = LineCollection(
        seg_ord,
        linewidths=[g * 3.0 for g in gro_ord],
        colors=[(c[0], c[1], c[2], 0.04) for c in col_ord],
        capstyle='round', joinstyle='round', zorder=4
    )
    ax.add_collection(lc_glow)

    # ── Capa glow intermedia ──
    lc_glow2 = LineCollection(
        seg_ord,
        linewidths=[g * 1.8 for g in gro_ord],
        colors=[(c[0], c[1], c[2], 0.10) for c in col_ord],
        capstyle='round', joinstyle='round', zorder=4
    )
    ax.add_collection(lc_glow2)

    # ── Capa principal ──
    lc_main = LineCollection(
        seg_ord, linewidths=gro_ord, colors=col_ord,
        capstyle='round', joinstyle='round', zorder=5, alpha=0.92
    )
    ax.add_collection(lc_main)

    # ── Colorbar de distancia ──
    norm = mcolors.Normalize(vmin=dist_min, vmax=dist_max)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.45, pad=0.02, aspect=30)
    etiqueta_distancia = (
        'Distancia al destino más cercano'
        if len(destinos) > 1
        else 'Distancia al destino'
    )
    cbar.set_label(etiqueta_distancia, fontsize=11,
                   color='white', fontweight='bold')
    cbar.ax.tick_params(colors='white', labelsize=9)


def _dibujar_puntos(ax, puntos, config):
    """Dibuja puntos de origen (amarillo) y destino (rojo estrella)."""
    if puntos is None or puntos.empty:
        return

    origenes = puntos[puntos['tipo'] == 'origen']
    destinos = puntos[puntos['tipo'] == 'destino']

    vol_max = puntos['volumen_total'].max() if 'volumen_total' in puntos.columns else 1
    if vol_max == 0:
        vol_max = 1

    # ── Destino: estrella roja con nombre parametrizado ──
    if not destinos.empty:
        sizes_d = 350
        ax.scatter(destinos.geometry.x, destinos.geometry.y,
                   c=COLOR_DESTINO, s=sizes_d, edgecolors='white', linewidths=2.5,
                   zorder=9, marker='*', label=f'{config.nombre_destino}')
        # Halo
        ax.scatter(destinos.geometry.x, destinos.geometry.y,
                   c=COLOR_DESTINO, s=sizes_d * 4, alpha=0.08, zorder=6)
        # Etiqueta del destino — usar nombre real si existe
        for _, d in destinos.iterrows():
            nombre_dest = d.get('etiqueta', '') or ''
            if not nombre_dest or str(nombre_dest) in ('', 'nan'):
                nombre_dest = config.nombre_destino
            ax.annotate(
                nombre_dest, (d.geometry.x, d.geometry.y),
                fontsize=11, color='white', fontweight='bold',
                alpha=0.95, zorder=10,
                xytext=(8, -12), textcoords='offset points',
                bbox=dict(boxstyle='round,pad=0.3',
                         facecolor=COLOR_DESTINO, edgecolor='white',
                         alpha=0.85),
            )

    # ── Orígenes: círculos amarillos proporcionales al volumen ──
    if not origenes.empty:
        if 'volumen_total' in origenes.columns:
            sizes_o = 15 + 120 * (origenes['volumen_total'] / vol_max)
        else:
            sizes_o = 50
        ax.scatter(origenes.geometry.x, origenes.geometry.y,
                   c=COLOR_ORIGEN, s=sizes_o, edgecolors='#886600',
                   linewidths=0.6, zorder=7, marker='o', label='Origenes')
        # Halo
        ax.scatter(origenes.geometry.x, origenes.geometry.y,
                   c=COLOR_ORIGEN, s=sizes_o * 2, alpha=0.08, zorder=6)

    # ── Etiquetas (solo puntos con volumen significativo) ──
    if config.mostrar_etiquetas:
        umbral_etiqueta = vol_max * 0.03
        for _, p in puntos.iterrows():
            etiq = p.get('etiqueta', '')
            vol = p.get('volumen_total', 0)
            if not etiq or str(etiq) in ('', 'nan'):
                continue
            if p['tipo'] == 'destino':
                continue  # ya etiquetado arriba
            if vol < umbral_etiqueta:
                continue

            fs = 5.0 + 4.0 * (vol / vol_max)

            ax.annotate(
                etiq, (p.geometry.x, p.geometry.y),
                fontsize=fs, color='white', fontweight='bold',
                alpha=0.85, zorder=9,
                xytext=(4, 4), textcoords='offset points',
                bbox=dict(boxstyle='round,pad=0.15',
                         facecolor=config.fondo_color,
                         edgecolor='#444444', alpha=0.65),
            )


def _configurar_layout(ax, fig, flujos, polylineas, config):
    """Configura título, leyenda, ejes y decoración del mapa."""
    ax.set_title(config.titulo, fontsize=18, fontweight='bold', color='white',
                 pad=20, fontfamily='sans-serif')

    # Leyenda
    cantidad_destinos = len(flujos[['dest_x', 'dest_y']].drop_duplicates())
    etiqueta_destinos = config.nombre_destino if cantidad_destinos == 1 else 'Destinos'
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor=COLOR_ORIGEN,
               markeredgecolor='#886600', markersize=10,
               label='Origenes', linestyle='None'),
        Line2D([0], [0], marker='*', color='w', markerfacecolor=COLOR_DESTINO,
               markersize=14, label=etiqueta_destinos, linestyle='None'),
    ]
    ax.legend(handles=legend_elements, loc='lower left', fontsize=9,
             facecolor=config.fondo_color, edgecolor='#555555',
             labelcolor='white', framealpha=0.8)

    # Ejes
    ax.grid(True, alpha=0.08, color='white', linestyle='-', linewidth=0.5)
    ax.tick_params(colors='#666666', labelsize=8)
    for spine in ax.spines.values():
        spine.set_color('#333333')

    ax.set_aspect('equal')
    ax.autoscale_view()

    # Info resumen
    n_flujos = len(flujos)
    vol_total = flujos['volumen'].sum()
    n_seg = len(polylineas) if polylineas else 0
    info = (f"Flujos: {n_flujos}  |  Volumen total: {vol_total:,.0f}  |  "
            f"Cauces: {n_seg}")
    ax.text(0.5, -0.015, info, transform=ax.transAxes, fontsize=8,
            ha='center', color='#777777', style='italic')
