"""
bundling.py — Algoritmo de Edge Bundling para efecto de confluencia de ríos
============================================================================

Implementa un algoritmo iterativo de agrupamiento de flujos que produce
el efecto visual de "confluencia de ríos": múltiples flujos individuales
(riachuelos) se van uniendo progresivamente en corredores compartidos
(arroyos) hasta formar cauces principales (ríos).

Analogía hidrológica:
    Riachuelo → Arroyo → Río → Caudal principal
    (origen)    (merge)   (trunk)   (destino)

Algoritmo:
    1. Calcular rutas iniciales (shortest path)
    2. Reducir el peso de aristas con flujo (hacerlas "más baratas")
    3. Recalcular rutas con pesos actualizados → rutas convergen
    4. Repetir N iteraciones → efecto de confluencia progresiva
    5. Reconstruir polilíneas continuas desde la malla
    6. Suavizar con Chaikin corner-cutting → curvas orgánicas

Funciones principales:
    - calcular_rutas_con_bundling(): Bundling iterativo
    - reconstruir_polylineas(): Traza cauces continuos
    - suavizar_chaikin(): Suavizado de polilíneas
"""

import numpy as np
import networkx as nx
import geopandas as gpd
from shapely.geometry import LineString
from typing import Dict, List, Tuple, Optional

from .config import FlowMapConfig


# ═══════════════════════════════════════════════════════════════
# 1. BÚSQUEDA DE NODO CERCANO
# ═══════════════════════════════════════════════════════════════

def _encontrar_nodo_cercano(G: nx.Graph, x: float, y: float) -> Optional[tuple]:
    """
    Encuentra el nodo del grafo más cercano a (x, y).
    Distancia euclidiana al cuadrado (suficiente para comparación).
    """
    if G.number_of_nodes() == 0:
        return None

    min_dist = float('inf')
    nodo_cercano = None
    for nodo, datos in G.nodes(data=True):
        pos = datos['pos']
        d = (pos[0] - x)**2 + (pos[1] - y)**2
        if d < min_dist:
            min_dist = d
            nodo_cercano = nodo
    return nodo_cercano


# ═══════════════════════════════════════════════════════════════
# 2. EDGE BUNDLING ITERATIVO
# ═══════════════════════════════════════════════════════════════

def calcular_rutas_con_bundling(
    G: nx.Graph,
    flujos: gpd.GeoDataFrame,
    config: FlowMapConfig,
) -> Tuple[Dict[tuple, float], Dict[int, list], int]:
    """
    Calcula rutas con agrupamiento iterativo (edge bundling).

    El algoritmo funciona en múltiples pasadas:
      Pasada 1: Calcula shortest paths normales → flujo disperso
      Pasada 2: Reduce pesos en aristas con flujo → rutas empiezan a converger
      Pasada 3+: Más convergencia → se forman "cauces" cada vez más gruesos

    La clave es que al reducir el peso de aristas ya usadas, las rutas
    subsecuentes prefieren pasar por esas mismas aristas, creando el
    efecto natural de confluencia de ríos.

    Fórmula de reducción de peso:
        nuevo_peso = peso_original * (1 - alpha * (flujo/max_flujo)^0.5)

    Donde alpha es el factor de atracción (0.0 = sin bundling, 0.9 = máximo).

    Args:
        G: Grafo espacial con restricciones aplicadas.
        flujos: GeoDataFrame con columnas orig_x, orig_y, dest_x, dest_y, volumen.
        config: Configuración con parámetros de bundling.

    Returns:
        Tupla (flujo_acumulado, rutas, rutas_fallidas)
    """
    n_iter = config.iteraciones_bundling
    alpha = config.factor_atraccion

    # Guardar pesos originales (para restaurar entre iteraciones)
    pesos_originales = {}
    for u, v, data in G.edges(data=True):
        pesos_originales[tuple(sorted([u, v]))] = data['weight']

    flujo_acumulado = {}
    rutas = {}
    rutas_fallidas = 0

    for iteracion in range(n_iter):
        # Reiniciar acumulación para esta iteración
        flujo_acumulado = {}
        rutas = {}
        rutas_fallidas = 0

        # Calcular shortest path para cada flujo
        for idx, fila in flujos.iterrows():
            nodo_orig = _encontrar_nodo_cercano(G, fila['orig_x'], fila['orig_y'])
            nodo_dest = _encontrar_nodo_cercano(G, fila['dest_x'], fila['dest_y'])

            if nodo_orig is None or nodo_dest is None or nodo_orig == nodo_dest:
                rutas_fallidas += 1
                continue

            try:
                ruta = nx.shortest_path(G, nodo_orig, nodo_dest, weight='weight')
                rutas[idx] = ruta

                vol = fila['volumen']
                for i in range(len(ruta) - 1):
                    arista = tuple(sorted([ruta[i], ruta[i + 1]]))
                    flujo_acumulado[arista] = flujo_acumulado.get(arista, 0) + vol

            except nx.NetworkXNoPath:
                rutas_fallidas += 1

        n_segmentos = len(flujo_acumulado)
        print(f"    Iteracion {iteracion + 1}/{n_iter}: "
              f"{len(rutas)} rutas, {n_segmentos} segmentos")

        # ── Actualizar pesos para la siguiente iteración ──
        if iteracion < n_iter - 1 and flujo_acumulado:
            max_flujo = max(flujo_acumulado.values())

            # Restaurar pesos originales primero
            for arista_key, peso in pesos_originales.items():
                u, v = arista_key
                if G.has_edge(u, v):
                    G[u][v]['weight'] = peso

            # Reducir peso en aristas con flujo (atracción)
            for arista, flujo in flujo_acumulado.items():
                u, v = arista
                if G.has_edge(u, v):
                    peso_orig = pesos_originales.get(arista, G[u][v]['weight'])
                    # Curva raíz cuadrada: diferencia sutil entre flujos bajos y altos
                    ratio = (flujo / max_flujo) ** 0.5
                    factor = 1.0 - alpha * ratio
                    factor = max(factor, 0.03)  # Piso mínimo: evitar peso cero
                    G[u][v]['weight'] = peso_orig * factor

    # Restaurar pesos originales (dejar el grafo limpio)
    for arista_key, peso in pesos_originales.items():
        u, v = arista_key
        if G.has_edge(u, v):
            G[u][v]['weight'] = peso

    # Resumen final
    if flujo_acumulado:
        vals = list(flujo_acumulado.values())
        print(f"  Bundling completado:")
        print(f"    Segmentos con flujo : {len(flujo_acumulado)}")
        print(f"    Rango flujo/segmento: {min(vals):,.0f} - {max(vals):,.0f}")

    return flujo_acumulado, rutas, rutas_fallidas


# ═══════════════════════════════════════════════════════════════
# 3. RECONSTRUCCIÓN DE POLILÍNEAS CONTINUAS
# ═══════════════════════════════════════════════════════════════

def reconstruir_polylineas(
    G: nx.Graph,
    flujo_acumulado: Dict[tuple, float],
    config: FlowMapConfig,
) -> List[Tuple[list, float]]:
    """
    Reconstruye polilíneas continuas desde las aristas del grafo con flujo.

    En lugar de renderizar miles de segmentos individuales de la malla,
    traza cauces continuos entre puntos de bifurcación, produciendo
    líneas suaves tipo río.

    Algoritmo:
    1. Construir subgrafo solo con aristas que tienen flujo
    2. Identificar nodos de bifurcación (grado != 2) y hojas (grado == 1)
    3. Trazar segmentos continuos entre bifurcaciones
    4. Asignar a cada segmento su flujo acumulado
    5. Suavizar cada segmento con Chaikin

    Args:
        G: Grafo espacial con atributo 'pos'.
        flujo_acumulado: Dict {arista: volumen_total}.
        config: Configuración con parámetros de suavizado.

    Returns:
        Lista de tuplas (coords, flujo):
        - coords: Lista de (x, y) formando la polilínea suavizada
        - flujo: Volumen acumulado del segmento
    """
    if not flujo_acumulado:
        return []

    pos = nx.get_node_attributes(G, 'pos')

    # ── Paso 1: Subgrafo de flujo ──
    flow_G = nx.Graph()
    for (u, v), vol in flujo_acumulado.items():
        if u in pos and v in pos:
            flow_G.add_edge(u, v, volumen=vol)

    if flow_G.number_of_nodes() == 0:
        return []

    # ── Paso 2: Identificar nodos de bifurcación ──
    # Bifurcación = nodo con grado != 2 (hoja, intersección o terminal)
    bifurcaciones = set()
    for nodo in flow_G.nodes():
        if flow_G.degree(nodo) != 2:
            bifurcaciones.add(nodo)

    # ── Paso 3: Trazar segmentos entre bifurcaciones ──
    aristas_visitadas = set()
    segmentos = []

    for nodo_inicio in bifurcaciones:
        for vecino in flow_G.neighbors(nodo_inicio):
            edge_key = tuple(sorted([nodo_inicio, vecino]))
            if edge_key in aristas_visitadas:
                continue

            # Trazar la cadena de nodos hasta la siguiente bifurcación
            cadena = [nodo_inicio]
            flujos_cadena = []
            actual = vecino
            previo = nodo_inicio

            aristas_visitadas.add(edge_key)
            flujos_cadena.append(flujo_acumulado.get(edge_key, 0))
            cadena.append(actual)

            # Avanzar mientras el nodo actual tenga grado 2 (no es bifurcación)
            while actual not in bifurcaciones:
                siguientes = [n for n in flow_G.neighbors(actual) if n != previo]
                if not siguientes:
                    break
                siguiente = siguientes[0]
                ek = tuple(sorted([actual, siguiente]))
                if ek in aristas_visitadas:
                    break
                aristas_visitadas.add(ek)
                flujos_cadena.append(flujo_acumulado.get(ek, 0))
                cadena.append(siguiente)
                previo = actual
                actual = siguiente

            # ── Paso 4: Convertir a coordenadas y asignar flujo ──
            coords = [pos[n] for n in cadena if n in pos]
            if len(coords) < 2:
                continue

            # El flujo del segmento = mínimo de la cadena (flujo "embotellado")
            flujo_seg = min(flujos_cadena) if flujos_cadena else 0

            # ── Paso 5: Suavizar ──
            n_suavizado = config.suavizado_iteraciones
            if n_suavizado > 0 and len(coords) >= 3:
                coords = suavizar_chaikin(coords, n_suavizado)

            segmentos.append((coords, flujo_seg))

    # Manejar posibles ciclos (aristas no visitadas en cadenas de grado 2)
    for (u, v), vol in flujo_acumulado.items():
        edge_key = tuple(sorted([u, v]))
        if edge_key not in aristas_visitadas and u in pos and v in pos:
            coords = [pos[u], pos[v]]
            segmentos.append((coords, vol))

    print(f"  Polylineas reconstruidas: {len(segmentos)} segmentos continuos")

    return segmentos


# ═══════════════════════════════════════════════════════════════
# 4. SUAVIZADO CHAIKIN (CORNER-CUTTING)
# ═══════════════════════════════════════════════════════════════

def suavizar_chaikin(
    coords: List[tuple],
    iteraciones: int = 3
) -> List[tuple]:
    """
    Algoritmo de Chaikin (corner-cutting) para suavizar polilíneas.

    Transforma caminos angulares de la malla en curvas orgánicas
    similares a cauces de río. Cada iteración:
      - Inserta dos puntos nuevos por cada segmento (al 25% y 75%)
      - Preserva los extremos (origen y destino exactos)

    Resultado: una curva B-spline cuadrática aproximada, sin dependencias
    externas (no requiere scipy).

    Args:
        coords: Lista de tuplas (x, y) de la polilínea original.
        iteraciones: Número de pasadas de suavizado (2-4 recomendado).

    Returns:
        Lista de tuplas (x, y) de la polilínea suavizada.
    """
    for _ in range(iteraciones):
        if len(coords) < 3:
            return coords

        # Preservar primer y último punto
        nueva = [coords[0]]
        for i in range(len(coords) - 1):
            p0x, p0y = coords[i]
            p1x, p1y = coords[i + 1]
            # Punto Q al 25% del segmento
            qx = 0.75 * p0x + 0.25 * p1x
            qy = 0.75 * p0y + 0.25 * p1y
            # Punto R al 75% del segmento
            rx = 0.25 * p0x + 0.75 * p1x
            ry = 0.25 * p0y + 0.75 * p1y
            nueva.append((qx, qy))
            nueva.append((rx, ry))
        nueva.append(coords[-1])
        coords = nueva

    return coords


# ═══════════════════════════════════════════════════════════════
# 5. GENERACIÓN DE GEODATAFRAME DE FLUJO
# ═══════════════════════════════════════════════════════════════

def polylineas_a_geodataframe(
    polylineas: List[Tuple[list, float]],
    config: FlowMapConfig,
) -> gpd.GeoDataFrame:
    """
    Convierte las polilíneas reconstruidas a un GeoDataFrame exportable.

    Útil para cargar las rutas calculadas en QGIS, ArcGIS u otro SIG.

    Args:
        polylineas: Lista de (coords, flujo) del reconstructor.
        config: Configuración con CRS.

    Returns:
        GeoDataFrame con columnas: geometry, volumen, grosor_norm.
    """
    if not polylineas:
        return gpd.GeoDataFrame(
            columns=['geometry', 'volumen', 'grosor_norm'], crs=config.crs
        )

    volumenes = [f for _, f in polylineas]
    vol_min = min(volumenes)
    vol_max = max(volumenes)
    rango = vol_max - vol_min if vol_max != vol_min else 1.0

    lineas = []
    vols = []
    grosores = []

    for coords, flujo in polylineas:
        if len(coords) >= 2:
            linea = LineString(coords)
            lineas.append(linea)
            vols.append(flujo)
            vol_norm = (flujo - vol_min) / rango
            grosores.append(np.power(vol_norm, 0.55))

    return gpd.GeoDataFrame(
        {'volumen': vols, 'grosor_norm': grosores},
        geometry=lineas, crs=config.crs
    )
