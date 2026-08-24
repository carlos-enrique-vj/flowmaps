"""
graph.py — Creación del grafo espacial y restricciones
======================================================

Construye una malla regular (grid graph) sobre el bounding box de los datos
y elimina nodos/aristas que intersectan con polígonos de restricción.

Funciones principales:
  - crear_grafo_espacial(): Construye el grid graph con NetworkX
  - aplicar_restricciones(): Elimina nodos dentro de zonas restringidas
  - anclar_extremos_flujo(): Incorpora orígenes y destinos exactos al grafo
"""

import numpy as np
import networkx as nx
import geopandas as gpd
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely import prepared
from typing import Tuple, Optional

from .config import FlowMapConfig


def crear_grafo_espacial(
    bbox: Tuple[float, float, float, float],
    config: FlowMapConfig
) -> nx.Graph:
    """
    Construye una malla regular (grid graph) sobre el área de estudio.

    La malla cubre el Bounding Box con un margen del 5% en cada dirección.
    Cada nodo tiene un atributo 'pos' con sus coordenadas (x, y).
    Las aristas tienen peso 'weight' = distancia euclidiana entre nodos.

    Args:
        bbox: Tupla (minx, miny, maxx, maxy) del área de estudio.
        config: Configuración con resolución y tipo de conectividad.

    Returns:
        nx.Graph con nodos posicionados y aristas pesadas.
    """
    resolucion = config.resolucion_grafo
    minx, miny, maxx, maxy = bbox

    # Expandir bbox con margen
    margen_x = (maxx - minx) * 0.05
    margen_y = (maxy - miny) * 0.05
    minx -= margen_x
    miny -= margen_y
    maxx += margen_x
    maxy += margen_y

    # Crear coordenadas de la malla
    xs = np.linspace(minx, maxx, resolucion)
    ys = np.linspace(miny, maxy, resolucion)
    paso_x = xs[1] - xs[0] if len(xs) > 1 else 1.0
    paso_y = ys[1] - ys[0] if len(ys) > 1 else 1.0

    G = nx.Graph()

    # Añadir nodos
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            G.add_node((i, j), pos=(x, y))

    # Añadir aristas
    for i in range(len(xs)):
        for j in range(len(ys)):
            # Vecinos cardinales (4-conectividad)
            vecinos = []
            if i + 1 < len(xs):
                vecinos.append(((i + 1, j), paso_x))
            if j + 1 < len(ys):
                vecinos.append(((i, j + 1), paso_y))

            # Vecinos diagonales (8-conectividad)
            if config.conexion_diagonal:
                dist_diag = np.sqrt(paso_x**2 + paso_y**2)
                if i + 1 < len(xs) and j + 1 < len(ys):
                    vecinos.append(((i + 1, j + 1), dist_diag))
                if i + 1 < len(xs) and j - 1 >= 0:
                    vecinos.append(((i + 1, j - 1), dist_diag))

            for vecino, dist in vecinos:
                G.add_edge((i, j), vecino, weight=dist)

    print(f"  Grafo creado: {G.number_of_nodes()} nodos, "
          f"{G.number_of_edges()} aristas ({resolucion}x{resolucion})")

    return G


def anclar_extremos_flujo(
    G: nx.Graph,
    flujos: gpd.GeoDataFrame,
) -> nx.Graph:
    """Añade cada origen y destino como nodo exacto conectado a la malla.

    El enrutamiento usa una malla regular cuyos nodos rara vez coinciden con
    las coordenadas de entrada. Sin estos anclajes, los cauces terminan en el
    nodo de malla más cercano y pueden pasar visualmente junto al marcador sin
    tocarlo. Los identificadores negativos evitan colisiones con los nodos
    ``(i, j)`` de la malla y mantienen comparables las claves de las aristas.

    Los puntos repetidos comparten un único anclaje. Cada anclaje se conecta
    solamente al nodo original más cercano para no crear atajos artificiales
    entre puntos de entrada próximos.
    """
    if G.number_of_nodes() == 0 or flujos is None or flujos.empty:
        return G

    nodos_malla = [
        nodo for nodo, datos in G.nodes(data=True)
        if not datos.get('es_anclaje', False)
    ]
    if not nodos_malla:
        return G
    posiciones = nx.get_node_attributes(G, 'pos')
    coords_malla = np.asarray([posiciones[nodo] for nodo in nodos_malla], dtype=float)

    # La precisión de 12 decimales elimina duplicados numéricamente idénticos
    # sin desplazar las coordenadas que finalmente se dibujan.
    nodos_por_coordenada = {
        (round(float(x), 12), round(float(y), 12)): nodo
        for nodo, (x, y) in posiciones.items()
    }
    coordenadas = []
    for columnas in (('orig_x', 'orig_y'), ('dest_x', 'dest_y')):
        coordenadas.extend(
            (float(x), float(y))
            for x, y in flujos.loc[:, list(columnas)].itertuples(index=False, name=None)
            if np.isfinite(x) and np.isfinite(y)
        )

    agregados = 0
    reutilizados = 0
    indice_anclaje = 0
    for x, y in dict.fromkeys(coordenadas):
        clave = (round(x, 12), round(y, 12))
        if clave in nodos_por_coordenada:
            reutilizados += 1
            continue

        distancias_cuadradas = (coords_malla[:, 0] - x) ** 2 + (coords_malla[:, 1] - y) ** 2
        indice_cercano = int(np.argmin(distancias_cuadradas))
        nodo_cercano = nodos_malla[indice_cercano]
        distancia = float(np.sqrt(distancias_cuadradas[indice_cercano]))

        nodo_anclaje = (-1, indice_anclaje)
        while nodo_anclaje in G:
            indice_anclaje += 1
            nodo_anclaje = (-1, indice_anclaje)

        G.add_node(nodo_anclaje, pos=(x, y), es_anclaje=True)
        G.add_edge(
            nodo_anclaje,
            nodo_cercano,
            weight=distancia,
            es_anclaje=True,
        )
        nodos_por_coordenada[clave] = nodo_anclaje
        agregados += 1
        indice_anclaje += 1

    print(
        f"  Extremos anclados: {agregados} nodos exactos agregados, "
        f"{reutilizados} ya coincidentes con la malla"
    )
    return G


def aplicar_restricciones(
    G: nx.Graph,
    restricciones: Optional[gpd.GeoDataFrame],
    config: FlowMapConfig
) -> nx.Graph:
    """
    Elimina del grafo los nodos cuya posición intersecta con polígonos
    de restricción. Usa geometría preparada (prepared geometry) de Shapely
    para consultas espaciales rápidas.

    Args:
        G: Grafo espacial con atributo 'pos' en cada nodo.
        restricciones: GeoDataFrame con polígonos de zonas restringidas.
        config: Configuración con buffer de restricción.

    Returns:
        nx.Graph modificado sin nodos en zonas restringidas.
    """
    if restricciones is None or restricciones.empty:
        print("  Sin restricciones, grafo sin modificar")
        return G

    # Unir todos los polígonos
    zona_restringida = unary_union(restricciones.geometry)

    # Aplicar buffer
    if config.buffer_restriccion > 0:
        zona_restringida = zona_restringida.buffer(config.buffer_restriccion)

    # Geometría preparada para consultas rápidas
    zona_prep = prepared.prep(zona_restringida)

    # Identificar nodos a eliminar
    nodos_a_eliminar = [
        nodo for nodo, datos in G.nodes(data=True)
        if zona_prep.contains(Point(datos['pos']))
    ]

    G.remove_nodes_from(nodos_a_eliminar)

    print(f"  Restricciones aplicadas: {len(nodos_a_eliminar)} nodos eliminados")
    print(f"    -> {G.number_of_nodes()} nodos restantes, {G.number_of_edges()} aristas")

    return G
