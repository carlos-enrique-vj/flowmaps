"""
ingesta.py — Ingesta polimórfica de datos y asignación por proximidad
======================================================================

Módulo de entrada flexible que soporta múltiples escenarios de ingesta
de datos Origen-Destino (OD):

  Escenario A1: Archivo de orígenes + coordenada de destino fija
  Escenario A2: Coordenada de origen fija + archivo de destinos
  Escenario B:  N orígenes × M destinos → vecino más cercano (BallTree/KDTree)
  Escenario C:  Archivo pre-calculado con pares OD (comportamiento legacy)

Formatos soportados:
  - Tabulares: CSV, Excel (.xlsx/.xls), TSV
  - Geoespaciales: Shapefile (.shp), GeoPackage (.gpkg), GeoJSON, GDB

Funciones principales:
  - cargar_puntos():           Lee cualquier formato y estandariza a GeoDataFrame
  - asignar_vecino_cercano():  Emparejamiento O-D optimizado (BallTree/KDTree/sjoin)
  - preparar_flujos():         Factory unificada para todos los escenarios
"""

import os
import warnings
from enum import Enum
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from .config import FlowMapConfig


# ═══════════════════════════════════════════════════════════════
# ENUMERACIÓN DE ESCENARIOS
# ═══════════════════════════════════════════════════════════════

class EscenarioFlujo(Enum):
    """
    Escenarios de entrada de datos soportados por el pipeline.

    Atributos:
        ASIMETRICO_DESTINO_FIJO (A1): Archivo de orígenes + coordenada destino fija.
        ASIMETRICO_ORIGEN_FIJO  (A2): Coordenada origen fija + archivo de destinos.
        PROXIMIDAD              (B):  N orígenes × M destinos → vecino más cercano.
        PRECALCULADO            (C):  Archivo con pares OD ya definidos.
    """
    ASIMETRICO_DESTINO_FIJO = "A1"
    ASIMETRICO_ORIGEN_FIJO = "A2"
    PROXIMIDAD = "B"
    PRECALCULADO = "C"


# ═══════════════════════════════════════════════════════════════
# FORMATOS SOPORTADOS
# ═══════════════════════════════════════════════════════════════

_FORMATOS_GEO = {
    '.shp': 'Shapefile',
    '.geojson': 'GeoJSON',
    '.json': 'GeoJSON',
    '.gpkg': 'GeoPackage',
    '.gdb': 'File Geodatabase',
    '.parquet': 'GeoParquet',
    '.geoparquet': 'GeoParquet',
}

_FORMATOS_TABLA = {
    '.csv': 'CSV',
    '.xlsx': 'Excel',
    '.xls': 'Excel',
    '.tsv': 'TSV',
}


def _detectar_formato(ruta: str) -> str:
    """Detecta el formato del archivo por su extensión."""
    ruta_str = str(ruta)
    ext = os.path.splitext(ruta_str)[1].lower()

    if ruta_str.lower().endswith('.gdb'):
        return 'gdb'
    if ext in _FORMATOS_GEO:
        return 'geo'
    if ext in _FORMATOS_TABLA:
        return 'tabla'
    raise ValueError(
        f"Formato no soportado: '{ext}'\n"
        f"Formatos geoespaciales: {list(_FORMATOS_GEO.keys())}\n"
        f"Formatos tabulares: {list(_FORMATOS_TABLA.keys())}"
    )


# ═══════════════════════════════════════════════════════════════
# CARGA DE PUNTOS (TABULAR + GEOESPACIAL)
# ═══════════════════════════════════════════════════════════════

def cargar_puntos(
    fuente: Union[str, Path],
    campo_x: str = "longitud",
    campo_y: str = "latitud",
    campo_etiqueta: Optional[str] = None,
    campo_magnitud: Optional[str] = None,
    crs: str = "EPSG:4326",
) -> gpd.GeoDataFrame:
    """
    Carga puntos desde cualquier formato tabular o geoespacial soportado.

    Para archivos tabulares (CSV, Excel, TSV), las coordenadas se leen
    de las columnas especificadas por campo_x y campo_y.

    Para archivos geoespaciales (SHP, GPKG, GeoJSON, GDB), se usa la
    geometría nativa del archivo. Si la geometría es de tipo Point, se
    extraen las coordenadas x/y directamente.

    Args:
        fuente: Ruta al archivo de datos.
        campo_x: Nombre del campo con la longitud (solo para tabulares).
        campo_y: Nombre del campo con la latitud (solo para tabulares).
        campo_etiqueta: Nombre del campo de etiqueta (opcional).
        campo_magnitud: Nombre del campo de magnitud/volumen (opcional).
        crs: Sistema de referencia de coordenadas.

    Returns:
        GeoDataFrame con columnas estandarizadas: x, y, etiqueta, magnitud.
    """
    ruta = str(fuente)
    formato = _detectar_formato(ruta)
    print(f"  Cargando puntos desde: {os.path.basename(ruta)} ({formato})")

    if formato in ('geo', 'gdb'):
        if Path(ruta).suffix.lower() in {'.parquet', '.geoparquet'}:
            gdf = gpd.read_parquet(ruta)
        else:
            gdf = gpd.read_file(ruta)

        # Extraer coordenadas de la geometría nativa
        if gdf.geometry.geom_type.iloc[0] == 'Point':
            gdf['x'] = gdf.geometry.x
            gdf['y'] = gdf.geometry.y
        elif campo_x in gdf.columns and campo_y in gdf.columns:
            gdf['x'] = gdf[campo_x].astype(float)
            gdf['y'] = gdf[campo_y].astype(float)
        else:
            # Usar centroide como fallback
            gdf['x'] = gdf.geometry.centroid.x
            gdf['y'] = gdf.geometry.centroid.y

        # Reproyectar si es necesario
        if gdf.crs and str(gdf.crs) != crs:
            gdf = gdf.to_crs(crs)
            gdf['x'] = gdf.geometry.x if gdf.geometry.geom_type.iloc[0] == 'Point' \
                else gdf.geometry.centroid.x
            gdf['y'] = gdf.geometry.y if gdf.geometry.geom_type.iloc[0] == 'Point' \
                else gdf.geometry.centroid.y

    elif formato == 'tabla':
        ext = os.path.splitext(ruta)[1].lower()
        if ext == '.csv':
            df = pd.read_csv(ruta)
        elif ext == '.tsv':
            df = pd.read_csv(ruta, sep='\t')
        else:
            df = pd.read_excel(ruta)

        # Verificar que existan las columnas de coordenadas
        for campo, nombre in [(campo_x, 'longitud (X)'), (campo_y, 'latitud (Y)')]:
            if campo not in df.columns:
                cols = ', '.join(df.columns.tolist())
                raise ValueError(
                    f"Campo '{campo}' ({nombre}) no encontrado.\n"
                    f"Columnas disponibles: {cols}"
                )

        df['x'] = df[campo_x].astype(float)
        df['y'] = df[campo_y].astype(float)

        geometry = [Point(x, y) for x, y in zip(df['x'], df['y'])]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)

    # ── Estandarizar columnas ──
    # Etiqueta
    if campo_etiqueta and campo_etiqueta in gdf.columns:
        gdf['etiqueta'] = gdf[campo_etiqueta].astype(str)
    else:
        gdf['etiqueta'] = ''

    # Magnitud
    if campo_magnitud and campo_magnitud in gdf.columns:
        gdf['magnitud'] = gdf[campo_magnitud].astype(float)
    else:
        gdf['magnitud'] = np.nan  # Se llenará con default más adelante

    # Eliminar filas sin coordenadas válidas
    n_antes = len(gdf)
    gdf = gdf.dropna(subset=['x', 'y'])
    n_eliminados = n_antes - len(gdf)
    if n_eliminados > 0:
        print(f"    -> {n_eliminados} registros eliminados (coordenadas inválidas)")

    print(f"    -> {len(gdf)} puntos cargados")
    return gdf


# ═══════════════════════════════════════════════════════════════
# ASIGNACIÓN DE VECINO MÁS CERCANO (OPTIMIZADA)
# ═══════════════════════════════════════════════════════════════

def asignar_vecino_cercano(
    origenes: gpd.GeoDataFrame,
    destinos: gpd.GeoDataFrame,
    metodo: Literal["balltree", "kdtree", "sjoin"] = "balltree",
) -> gpd.GeoDataFrame:
    """
    Para cada origen, encuentra el destino más cercano y los empareja.

    Métodos disponibles:
      - balltree: BallTree con métrica Haversine. Ideal para coordenadas
                  geográficas WGS84. Complejidad O(N log M).
      - kdtree:   KDTree euclidiano (scipy.spatial). Requiere CRS proyectado
                  para resultados precisos. Complejidad O(N log M).
      - sjoin:    geopandas.sjoin_nearest. Automático y simple, usa un
                  índice espacial R-tree internamente.

    Args:
        origenes: GeoDataFrame de puntos de origen (debe tener columnas x, y).
        destinos: GeoDataFrame de puntos de destino (debe tener columnas x, y).
        metodo: Algoritmo de búsqueda a utilizar.

    Returns:
        GeoDataFrame con columnas estandarizadas: orig_x, orig_y, dest_x, dest_y,
        volumen, etiqueta, etiqueta_destino, distancia_km.
    """
    n_orig = len(origenes)
    n_dest = len(destinos)
    print(f"\n  [PROXIMIDAD] Emparejando {n_orig} orígenes con {n_dest} destinos")
    print(f"    Método: {metodo}")

    if metodo == "balltree":
        resultado = _nn_balltree(origenes, destinos)
    elif metodo == "kdtree":
        resultado = _nn_kdtree(origenes, destinos)
    elif metodo == "sjoin":
        resultado = _nn_sjoin(origenes, destinos)
    else:
        raise ValueError(f"Método no soportado: '{metodo}'. Use 'balltree', 'kdtree' o 'sjoin'.")

    print(f"    -> {len(resultado)} pares OD generados")
    if 'distancia_km' in resultado.columns:
        dists = resultado['distancia_km']
        print(f"    -> Distancias: min={dists.min():.2f} km, "
              f"max={dists.max():.2f} km, media={dists.mean():.2f} km")

    return resultado


def _nn_balltree(
    origenes: gpd.GeoDataFrame,
    destinos: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Búsqueda de vecino más cercano con BallTree + métrica Haversine.

    Ideal para datos en WGS84 (EPSG:4326) sin necesidad de reproyectar.
    La distancia Haversine calcula distancias geodésicas sobre la esfera terrestre.

    Complejidad: O(N log M) donde N = orígenes, M = destinos.
    """
    try:
        from sklearn.neighbors import BallTree
    except ImportError:
        warnings.warn(
            "scikit-learn no está instalado. Instalar con: pip install scikit-learn\n"
            "Usando fallback con sjoin_nearest."
        )
        return _nn_sjoin(origenes, destinos)

    # BallTree espera [lat, lon] en radianes
    dest_rad = np.deg2rad(destinos[['y', 'x']].values)
    orig_rad = np.deg2rad(origenes[['y', 'x']].values)

    tree = BallTree(dest_rad, metric='haversine')
    distancias, indices = tree.query(orig_rad, k=1)

    # Haversine retorna distancias en radianes → convertir a km
    RADIO_TIERRA_KM = 6_371.0
    distancias_km = distancias.flatten() * RADIO_TIERRA_KM
    indices_flat = indices.flatten()

    return _construir_resultado(origenes, destinos, indices_flat, distancias_km)


def _nn_kdtree(
    origenes: gpd.GeoDataFrame,
    destinos: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Búsqueda de vecino más cercano con KDTree euclidiano (scipy).

    Funciona con cualquier CRS pero es más preciso con CRS proyectado (UTM).
    Para WGS84, las distancias euclidianas son una aproximación.

    Complejidad: O(N log M) donde N = orígenes, M = destinos.
    """
    from scipy.spatial import cKDTree

    dest_coords = destinos[['x', 'y']].values
    orig_coords = origenes[['x', 'y']].values

    tree = cKDTree(dest_coords)
    distancias, indices = tree.query(orig_coords, k=1)

    # Para KDTree euclidiano, las distancias están en unidades del CRS
    # Estimación a km si es WGS84 (grados ≈ 111 km)
    distancias_km = distancias * 111.0  # Aproximación válida solo para WGS84

    return _construir_resultado(origenes, destinos, indices, distancias_km)


def _nn_sjoin(
    origenes: gpd.GeoDataFrame,
    destinos: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Búsqueda de vecino más cercano con geopandas.sjoin_nearest.

    Método más simple y automático. Usa un índice espacial R-tree
    internamente. Funciona con cualquier CRS.
    """
    # sjoin_nearest requiere versión de geopandas >= 0.10
    resultado = gpd.sjoin_nearest(
        origenes[['x', 'y', 'etiqueta', 'magnitud', 'geometry']],
        destinos[['x', 'y', 'etiqueta', 'magnitud', 'geometry']],
        how='left',
        distance_col='distancia',
        lsuffix='orig',
        rsuffix='dest',
    )

    # Estandarizar columnas
    gdf = gpd.GeoDataFrame({
        'orig_x': resultado['x_orig'],
        'orig_y': resultado['y_orig'],
        'dest_x': resultado['x_dest'],
        'dest_y': resultado['y_dest'],
        'volumen': resultado['magnitud_orig'],
        'etiqueta': resultado['etiqueta_orig'],
        'etiqueta_destino': resultado['etiqueta_dest'],
        'distancia_km': resultado['distancia'] * 111.0,
    })

    geometry = [
        Point(x, y) for x, y in zip(gdf['orig_x'], gdf['orig_y'])
    ]
    return gpd.GeoDataFrame(gdf, geometry=geometry, crs=origenes.crs)


def _construir_resultado(
    origenes: gpd.GeoDataFrame,
    destinos: gpd.GeoDataFrame,
    indices_destino: np.ndarray,
    distancias_km: np.ndarray,
) -> gpd.GeoDataFrame:
    """
    Construye el GeoDataFrame estandarizado de pares OD a partir
    de los índices de emparejamiento del vecino más cercano.
    """
    destinos_reset = destinos.reset_index(drop=True)
    origenes_reset = origenes.reset_index(drop=True)

    dest_seleccionados = destinos_reset.iloc[indices_destino]

    datos = {
        'orig_x': origenes_reset['x'].values,
        'orig_y': origenes_reset['y'].values,
        'dest_x': dest_seleccionados['x'].values,
        'dest_y': dest_seleccionados['y'].values,
        'volumen': origenes_reset['magnitud'].values,
        'etiqueta': origenes_reset['etiqueta'].values,
        'etiqueta_destino': dest_seleccionados['etiqueta'].values,
        'distancia_km': distancias_km,
    }

    geometry = [
        Point(x, y) for x, y in zip(datos['orig_x'], datos['orig_y'])
    ]

    return gpd.GeoDataFrame(datos, geometry=geometry, crs=origenes.crs)


# ═══════════════════════════════════════════════════════════════
# FACTORY PRINCIPAL — PREPARAR FLUJOS
# ═══════════════════════════════════════════════════════════════

def preparar_flujos(
    escenario: Union[str, EscenarioFlujo],
    *,
    archivo_origenes: Optional[Union[str, Path]] = None,
    archivo_destinos: Optional[Union[str, Path]] = None,
    archivo_flujos: Optional[Union[str, Path]] = None,
    coord_origen_fijo: Optional[Tuple[float, float]] = None,
    coord_destino_fijo: Optional[Tuple[float, float]] = None,
    etiqueta_origen_fijo: str = "Origen",
    etiqueta_destino_fijo: str = "Destino",
    campo_orig_x: str = "longitud",
    campo_orig_y: str = "latitud",
    campo_dest_x: str = "longitud",
    campo_dest_y: str = "latitud",
    campo_etiqueta_orig: Optional[str] = None,
    campo_etiqueta_dest: Optional[str] = None,
    campo_magnitud: Optional[str] = None,
    magnitud_default: float = 1.0,
    metodo_proximidad: Literal["balltree", "kdtree", "sjoin"] = "balltree",
    crs: str = "EPSG:4326",
) -> gpd.GeoDataFrame:
    """
    Punto de entrada único para la ingesta de datos OD.

    Factory que acepta cualquier combinación de entradas y devuelve un
    GeoDataFrame estandarizado con las 6 columnas que el pipeline espera:
    orig_x, orig_y, dest_x, dest_y, volumen, etiqueta.

    Escenarios:
        A1 (ASIMETRICO_DESTINO_FIJO):
            archivo_origenes + coord_destino_fijo (lat, lon)
            Cada origen apunta al mismo destino.

        A2 (ASIMETRICO_ORIGEN_FIJO):
            coord_origen_fijo (lat, lon) + archivo_destinos
            Todos los destinos salen del mismo origen.

        B (PROXIMIDAD):
            archivo_origenes + archivo_destinos
            Para cada origen, se calcula el destino más cercano.

        C (PRECALCULADO):
            archivo_flujos con columnas de origen y destino ya emparejadas.

    Args:
        escenario: Código del escenario ("A1", "A2", "B", "C") o EscenarioFlujo.
        archivo_origenes: Ruta al archivo de orígenes (A1, B).
        archivo_destinos: Ruta al archivo de destinos (A2, B).
        archivo_flujos: Ruta al archivo pre-calculado (C).
        coord_origen_fijo: Tupla (latitud, longitud) del origen fijo (A2).
        coord_destino_fijo: Tupla (latitud, longitud) del destino fijo (A1).
        etiqueta_origen_fijo: Etiqueta para el punto de origen fijo (A2).
        etiqueta_destino_fijo: Etiqueta para el punto de destino fijo (A1).
        campo_orig_x: Nombre del campo X en archivo de orígenes.
        campo_orig_y: Nombre del campo Y en archivo de orígenes.
        campo_dest_x: Nombre del campo X en archivo de destinos.
        campo_dest_y: Nombre del campo Y en archivo de destinos.
        campo_etiqueta_orig: Campo de etiqueta en archivo de orígenes.
        campo_etiqueta_dest: Campo de etiqueta en archivo de destinos.
        campo_magnitud: Campo numérico de magnitud/volumen.
        magnitud_default: Valor por defecto si no hay campo de magnitud.
        metodo_proximidad: Método de búsqueda para Escenario B.
        crs: Sistema de referencia de coordenadas.

    Returns:
        GeoDataFrame con columnas: orig_x, orig_y, dest_x, dest_y, volumen, etiqueta.

    Raises:
        ValueError: Si faltan parámetros requeridos para el escenario.
    """
    # Normalizar escenario
    if isinstance(escenario, str):
        escenario = EscenarioFlujo(escenario)

    print(f"\n[INGESTA] Escenario: {escenario.name} ({escenario.value})")
    print("-" * 50)

    # ── Despacho por escenario ──

    if escenario == EscenarioFlujo.ASIMETRICO_DESTINO_FIJO:
        # A1: Archivo de orígenes + destino fijo
        gdf = _escenario_a1(
            archivo_origenes=archivo_origenes,
            coord_destino_fijo=coord_destino_fijo,
            etiqueta_destino_fijo=etiqueta_destino_fijo,
            campo_x=campo_orig_x,
            campo_y=campo_orig_y,
            campo_etiqueta=campo_etiqueta_orig,
            campo_magnitud=campo_magnitud,
            crs=crs,
        )

    elif escenario == EscenarioFlujo.ASIMETRICO_ORIGEN_FIJO:
        # A2: Origen fijo + archivo de destinos
        gdf = _escenario_a2(
            coord_origen_fijo=coord_origen_fijo,
            etiqueta_origen_fijo=etiqueta_origen_fijo,
            archivo_destinos=archivo_destinos,
            campo_x=campo_dest_x,
            campo_y=campo_dest_y,
            campo_etiqueta=campo_etiqueta_dest,
            campo_magnitud=campo_magnitud,
            crs=crs,
        )

    elif escenario == EscenarioFlujo.PROXIMIDAD:
        # B: N orígenes × M destinos → vecino más cercano
        gdf = _escenario_b(
            archivo_origenes=archivo_origenes,
            archivo_destinos=archivo_destinos,
            campo_orig_x=campo_orig_x,
            campo_orig_y=campo_orig_y,
            campo_dest_x=campo_dest_x,
            campo_dest_y=campo_dest_y,
            campo_etiqueta_orig=campo_etiqueta_orig,
            campo_etiqueta_dest=campo_etiqueta_dest,
            campo_magnitud=campo_magnitud,
            metodo_proximidad=metodo_proximidad,
            crs=crs,
        )

    elif escenario == EscenarioFlujo.PRECALCULADO:
        # C: Archivo con pares OD pre-definidos
        gdf = _escenario_c(
            archivo_flujos=archivo_flujos,
            campo_orig_x=campo_orig_x,
            campo_orig_y=campo_orig_y,
            campo_dest_x=campo_dest_x,
            campo_dest_y=campo_dest_y,
            campo_etiqueta=campo_etiqueta_orig,
            campo_magnitud=campo_magnitud,
            crs=crs,
        )

    else:
        raise ValueError(f"Escenario no reconocido: {escenario}")

    # ── Asignar magnitud default donde falte ──
    if 'volumen' in gdf.columns:
        n_sin_mag = gdf['volumen'].isna().sum()
        if n_sin_mag > 0:
            gdf['volumen'] = gdf['volumen'].fillna(magnitud_default)
            print(f"  -> {n_sin_mag} registros sin magnitud → asignado default={magnitud_default}")
        # Asegurar que no haya ceros
        gdf.loc[gdf['volumen'] <= 0, 'volumen'] = magnitud_default

    # ── Resumen ──
    print(f"\n  Resultado de ingesta:")
    print(f"    Pares OD         : {len(gdf)}")
    print(f"    Rango volumen    : {gdf['volumen'].min():.1f} - {gdf['volumen'].max():.1f}")
    print(f"    CRS              : {gdf.crs}")

    return gdf


# ═══════════════════════════════════════════════════════════════
# IMPLEMENTACIÓN DE ESCENARIOS
# ═══════════════════════════════════════════════════════════════

def _escenario_a1(
    archivo_origenes, coord_destino_fijo, etiqueta_destino_fijo,
    campo_x, campo_y, campo_etiqueta, campo_magnitud, crs,
) -> gpd.GeoDataFrame:
    """Escenario A1: Múltiples orígenes → destino fijo."""
    if archivo_origenes is None:
        raise ValueError("Escenario A1 requiere 'archivo_origenes'.")
    if coord_destino_fijo is None:
        raise ValueError("Escenario A1 requiere 'coord_destino_fijo' como (lat, lon).")

    origenes = cargar_puntos(
        archivo_origenes, campo_x, campo_y,
        campo_etiqueta, campo_magnitud, crs,
    )

    dest_lat, dest_lon = coord_destino_fijo
    print(f"  Destino fijo: ({dest_lat}, {dest_lon}) — {etiqueta_destino_fijo}")

    datos = {
        'orig_x': origenes['x'].values,
        'orig_y': origenes['y'].values,
        'dest_x': np.full(len(origenes), dest_lon),
        'dest_y': np.full(len(origenes), dest_lat),
        'volumen': origenes['magnitud'].values,
        'etiqueta': origenes['etiqueta'].values,
        'etiqueta_destino': np.full(len(origenes), etiqueta_destino_fijo or ''),
    }

    geometry = [Point(x, y) for x, y in zip(datos['orig_x'], datos['orig_y'])]
    return gpd.GeoDataFrame(datos, geometry=geometry, crs=crs)


def _escenario_a2(
    coord_origen_fijo, etiqueta_origen_fijo, archivo_destinos,
    campo_x, campo_y, campo_etiqueta, campo_magnitud, crs,
) -> gpd.GeoDataFrame:
    """Escenario A2: Origen fijo → múltiples destinos."""
    if coord_origen_fijo is None:
        raise ValueError("Escenario A2 requiere 'coord_origen_fijo' como (lat, lon).")
    if archivo_destinos is None:
        raise ValueError("Escenario A2 requiere 'archivo_destinos'.")

    destinos = cargar_puntos(
        archivo_destinos, campo_x, campo_y,
        campo_etiqueta, campo_magnitud, crs,
    )

    orig_lat, orig_lon = coord_origen_fijo
    print(f"  Origen fijo: ({orig_lat}, {orig_lon}) — {etiqueta_origen_fijo}")

    datos = {
        'orig_x': np.full(len(destinos), orig_lon),
        'orig_y': np.full(len(destinos), orig_lat),
        'dest_x': destinos['x'].values,
        'dest_y': destinos['y'].values,
        'volumen': destinos['magnitud'].values,
        'etiqueta': np.full(len(destinos), etiqueta_origen_fijo or ''),
        'etiqueta_destino': destinos['etiqueta'].values,
    }

    geometry = [Point(x, y) for x, y in zip(datos['orig_x'], datos['orig_y'])]
    return gpd.GeoDataFrame(datos, geometry=geometry, crs=crs)


def _escenario_b(
    archivo_origenes, archivo_destinos,
    campo_orig_x, campo_orig_y, campo_dest_x, campo_dest_y,
    campo_etiqueta_orig, campo_etiqueta_dest, campo_magnitud,
    metodo_proximidad, crs,
) -> gpd.GeoDataFrame:
    """Escenario B: N orígenes × M destinos → vecino más cercano."""
    if archivo_origenes is None:
        raise ValueError("Escenario B requiere 'archivo_origenes'.")
    if archivo_destinos is None:
        raise ValueError("Escenario B requiere 'archivo_destinos'.")

    origenes = cargar_puntos(
        archivo_origenes, campo_orig_x, campo_orig_y,
        campo_etiqueta_orig, campo_magnitud, crs,
    )
    destinos = cargar_puntos(
        archivo_destinos, campo_dest_x, campo_dest_y,
        campo_etiqueta_dest, None, crs,
    )

    return asignar_vecino_cercano(origenes, destinos, metodo=metodo_proximidad)


def _escenario_c(
    archivo_flujos, campo_orig_x, campo_orig_y,
    campo_dest_x, campo_dest_y, campo_etiqueta, campo_magnitud, crs,
) -> gpd.GeoDataFrame:
    """
    Escenario C: Archivo pre-calculado con pares OD.

    Comportamiento legacy compatible con el pipeline original.
    Lee un archivo que ya contiene columnas de origen Y destino.
    """
    if archivo_flujos is None:
        raise ValueError("Escenario C requiere 'archivo_flujos'.")

    ruta = str(archivo_flujos)
    formato = _detectar_formato(ruta)
    print(f"  Cargando flujos pre-calculados desde: {os.path.basename(ruta)}")

    if formato in ('geo', 'gdb'):
        if Path(ruta).suffix.lower() in {'.parquet', '.geoparquet'}:
            gdf = gpd.read_parquet(ruta)
        else:
            gdf = gpd.read_file(ruta)
    elif formato == 'tabla':
        ext = os.path.splitext(ruta)[1].lower()
        if ext == '.csv':
            df = pd.read_csv(ruta)
        elif ext == '.tsv':
            df = pd.read_csv(ruta, sep='\t')
        else:
            df = pd.read_excel(ruta)
        geometry = [
            Point(x, y)
            for x, y in zip(df[campo_orig_x], df[campo_orig_y])
        ]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)

    # Estandarizar columnas de coordenadas
    for campo, nombre_std in [
        (campo_orig_x, 'orig_x'), (campo_orig_y, 'orig_y'),
        (campo_dest_x, 'dest_x'), (campo_dest_y, 'dest_y'),
    ]:
        if campo not in gdf.columns:
            cols = ', '.join(gdf.columns.tolist())
            raise ValueError(
                f"Campo '{campo}' no encontrado.\nColumnas disponibles: {cols}"
            )
        gdf[nombre_std] = gdf[campo].astype(float)

    # Volumen
    if campo_magnitud and campo_magnitud in gdf.columns:
        gdf['volumen'] = gdf[campo_magnitud].astype(float)
    else:
        gdf['volumen'] = np.nan

    # Etiqueta
    if campo_etiqueta and campo_etiqueta in gdf.columns:
        gdf['etiqueta'] = gdf[campo_etiqueta].astype(str)
    else:
        gdf['etiqueta'] = ''

    # Eliminar filas inválidas
    gdf = gdf.dropna(subset=['orig_x', 'orig_y', 'dest_x', 'dest_y'])

    print(f"    -> {len(gdf)} pares OD cargados")
    return gdf
