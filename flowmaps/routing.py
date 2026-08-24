"""
routing.py — Cálculo de rutas y acumulación de flujo
=====================================================

Calcula el camino más corto entre cada par Origen-Destino a través
del grafo espacial y acumula el volumen de flujo en cada arista
compartida (efecto "tronco" o edge bundling).

Funciones principales:
  - calcular_rutas_acumuladas(): Dijkstra + acumulación por arista
  - generar_geometrias_flujo(): Convierte aristas acumuladas a LineStrings
"""

import numpy as np
import networkx as nx
import geopandas as gpd
from shapely.geometry import LineString, Point
from typing import Tuple, Dict, List, Optional

from .config import FlowMapConfig


def _encontrar_nodo_cercano(G: nx.Graph, x: float, y: float) -> Optional[tuple]:
    """
    Encuentra el nodo del grafo más cercano a las coordenadas (x, y).

    Para grafos muy grandes (>50k nodos), considerar usar scipy.spatial.KDTree
    para búsqueda más eficiente.

    Args:
        G: Grafo con atributo 'pos' en cada nodo.
        x, y: Coordenadas del punto a buscar.

    Returns:
        ID del nodo más cercano, o None si el grafo está vacío.
    """
    if G.number_of_nodes() == 0:
        return None

    min_dist = float('inf')
    nodo_cercano = None

    for nodo, datos in G.nodes(data=True):
        pos = datos['pos']
        dist = (pos[0] - x)**2 + (pos[1] - y)**2
        if dist < min_dist:
            min_dist = dist
            nodo_cercano = nodo

    return nodo_cercano


def calcular_rutas_acumuladas(
    G: nx.Graph,
    flujos: gpd.GeoDataFrame,
    config: FlowMapConfig
) -> Tuple[Dict[tuple, float], Dict[int, list], int]:
    """
    Calcula el camino más corto entre cada par Origen-Destino y acumula
    el volumen de flujo en cada arista compartida.

    Algoritmo:
    1. Para cada flujo, busca los nodos más cercanos al origen y destino.
    2. Calcula la ruta más corta (Dijkstra, peso = distancia euclidiana).
    3. Para cada arista en la ruta, suma el volumen del flujo.
    4. Aristas compartidas acumulan volumen → líneas más gruesas.

    Args:
        G: Grafo espacial con restricciones aplicadas.
        flujos: GeoDataFrame con columnas orig_x, orig_y, dest_x, dest_y, volumen.
        config: Configuración del pipeline.

    Returns:
        Tupla con:
        - flujo_acumulado: {(nodo_a, nodo_b): volumen_total}
        - rutas: {índice: [lista de nodos de la ruta]}
        - rutas_fallidas: Número de rutas sin camino posible
    """
    flujo_acumulado = {}
    rutas = {}
    rutas_fallidas = 0
    total = len(flujos)

    for idx, fila in flujos.iterrows():
        nodo_origen = _encontrar_nodo_cercano(G, fila['orig_x'], fila['orig_y'])
        nodo_destino = _encontrar_nodo_cercano(G, fila['dest_x'], fila['dest_y'])

        if nodo_origen is None or nodo_destino is None:
            rutas_fallidas += 1
            continue

        if nodo_origen == nodo_destino:
            continue

        try:
            ruta = nx.shortest_path(G, nodo_origen, nodo_destino, weight='weight')
            rutas[idx] = ruta

            volumen = fila['volumen']
            for i in range(len(ruta) - 1):
                arista = tuple(sorted([ruta[i], ruta[i + 1]]))
                flujo_acumulado[arista] = flujo_acumulado.get(arista, 0) + volumen

        except nx.NetworkXNoPath:
            rutas_fallidas += 1
            etiq = fila.get('etiqueta', '?')
            print(f"    SIN RUTA: {etiq}")

    print(f"  Rutas calculadas: {len(rutas)}/{total} exitosas"
          f"{f', {rutas_fallidas} fallidas' if rutas_fallidas else ''}")

    if flujo_acumulado:
        vals = list(flujo_acumulado.values())
        print(f"    Flujo por segmento: min={min(vals):.0f}, max={max(vals):.0f}")

    return flujo_acumulado, rutas, rutas_fallidas


def generar_geometrias_flujo(
    G: nx.Graph,
    flujo_acumulado: Dict[tuple, float],
    config: FlowMapConfig
) -> gpd.GeoDataFrame:
    """
    Convierte las aristas con flujo acumulado a un GeoDataFrame de LineStrings
    con atributos de volumen y grosor normalizado.

    Útil para exportar las rutas calculadas a formatos geoespaciales
    o para la visualización con Folium.

    Args:
        G: Grafo espacial con atributo 'pos'.
        flujo_acumulado: Dict de aristas con su volumen acumulado.
        config: Configuración del pipeline.

    Returns:
        GeoDataFrame con columnas: geometry (LineString), volumen, grosor_norm.
    """
    if not flujo_acumulado:
        return gpd.GeoDataFrame(columns=['geometry', 'volumen', 'grosor_norm'],
                                crs=config.crs)

    pos = nx.get_node_attributes(G, 'pos')
    volumenes = list(flujo_acumulado.values())
    vol_min = min(volumenes)
    vol_max = max(volumenes)
    rango = vol_max - vol_min if vol_max != vol_min else 1.0

    lineas = []
    vols = []
    grosores = []

    for arista, volumen in flujo_acumulado.items():
        nodo_a, nodo_b = arista
        if nodo_a in pos and nodo_b in pos:
            coord_a = pos[nodo_a]
            coord_b = pos[nodo_b]
            linea = LineString([coord_a, coord_b])
            lineas.append(linea)
            vols.append(volumen)

            # Normalización con curva suave
            vol_norm = (volumen - vol_min) / rango
            grosor_norm = np.power(vol_norm, 0.55)
            grosores.append(grosor_norm)

    gdf = gpd.GeoDataFrame({
        'volumen': vols,
        'grosor_norm': grosores,
    }, geometry=lineas, crs=config.crs)

    return gdf
