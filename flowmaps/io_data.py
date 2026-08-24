"""
io_data.py — Lectura y preparación de datos geoespaciales
==========================================================

Soporta la carga de múltiples formatos geoespaciales:
  - Shapefile (.shp)
  - GeoJSON (.geojson, .json)
  - GeoPackage (.gpkg)
  - File Geodatabase (.gdb)
  - CSV/Excel con columnas de coordenadas

Funciones principales:
  - cargar_flujos(): Lee el archivo de flujos y lo estandariza
  - cargar_restricciones(): Lee polígonos de restricción
  - preparar_datos(): Orquesta la carga y validación de datos
"""

import os
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from typing import Tuple, Optional

from .config import FlowMapConfig


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
    ext = os.path.splitext(ruta)[1].lower()

    # Los GDB son directorios, verificar por extensión de directorio
    if ruta.lower().endswith('.gdb'):
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
# CARGA DE DATOS
# ═══════════════════════════════════════════════════════════════

def cargar_flujos(config: FlowMapConfig) -> gpd.GeoDataFrame:
    """
    Carga el archivo de flujos desde cualquier formato geoespacial
    o tabular soportado.

    Para archivos geoespaciales (SHP, GeoJSON, GPKG, GDB):
        Lee directamente con GeoPandas. Las coordenadas de origen/destino
        se extraen de las columnas especificadas en la configuración.

    Para archivos tabulares (CSV, Excel):
        Lee con Pandas y convierte a GeoDataFrame usando las columnas
        de coordenadas especificadas.

    Args:
        config: Configuración con la ruta del archivo y nombres de campos.

    Returns:
        GeoDataFrame con columnas estandarizadas:
        orig_x, orig_y, dest_x, dest_y, volumen, y opcionalmente etiqueta.
    """
    ruta = config.archivo_flujos
    print(f"  Cargando flujos desde: {os.path.basename(ruta)}")

    formato = _detectar_formato(ruta)

    if formato == 'geo' or formato == 'gdb':
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

        # Crear geometría Point desde columnas de origen
        geometry = [
            Point(x, y)
            for x, y in zip(df[config.campo_orig_x], df[config.campo_orig_y])
        ]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=config.crs)

    # ── Estandarizar nombres de columnas ──
    gdf = _estandarizar_columnas(gdf, config)

    print(f"    -> {len(gdf)} registros cargados")
    print(f"    -> Rango de volumen: {gdf['volumen'].min():.0f} - {gdf['volumen'].max():.0f}")
    print(f"    -> CRS: {gdf.crs}")

    return gdf


def _estandarizar_columnas(gdf: gpd.GeoDataFrame, config: FlowMapConfig) -> gpd.GeoDataFrame:
    """
    Estandariza las columnas del GeoDataFrame para que el pipeline
    siempre trabaje con los mismos nombres internos.

    Mapeo:
        config.campo_orig_x  → orig_x
        config.campo_orig_y  → orig_y
        config.campo_dest_x  → dest_x
        config.campo_dest_y  → dest_y
        config.campo_volumen → volumen
        config.campo_etiqueta → etiqueta (opcional)
    """
    # Verificar que existan los campos de coordenadas requeridos
    campos_coord = {
        'campo_orig_x': config.campo_orig_x,
        'campo_orig_y': config.campo_orig_y,
        'campo_dest_x': config.campo_dest_x,
        'campo_dest_y': config.campo_dest_y,
    }

    for nombre_param, nombre_campo in campos_coord.items():
        if nombre_campo not in gdf.columns:
            cols_disponibles = ', '.join(gdf.columns.tolist())
            raise ValueError(
                f"Campo '{nombre_campo}' (parámetro: {nombre_param}) "
                f"no encontrado en los datos.\n"
                f"Columnas disponibles: {cols_disponibles}"
            )

    # Crear copia con columnas estandarizadas
    result = gdf.copy()
    result['orig_x'] = result[config.campo_orig_x].astype(float)
    result['orig_y'] = result[config.campo_orig_y].astype(float)
    result['dest_x'] = result[config.campo_dest_x].astype(float)
    result['dest_y'] = result[config.campo_dest_y].astype(float)

    # Campo de volumen (tolerante: usa magnitud_default si no existe)
    if config.campo_volumen in result.columns:
        result['volumen'] = result[config.campo_volumen].astype(float)
    else:
        print(f"    -> Campo '{config.campo_volumen}' no encontrado, "
              f"usando magnitud_default={config.magnitud_default}")
        result['volumen'] = config.magnitud_default

    # Campo de etiqueta (opcional)
    if config.campo_etiqueta and config.campo_etiqueta in result.columns:
        result['etiqueta'] = result[config.campo_etiqueta].astype(str)
    else:
        result['etiqueta'] = ''

    # Eliminar filas con coordenadas NaN
    n_antes = len(result)
    result = result.dropna(subset=['orig_x', 'orig_y', 'dest_x', 'dest_y'])

    # Asignar magnitud_default donde volumen sea NaN o <= 0
    mask_invalido = result['volumen'].isna() | (result['volumen'] <= 0)
    if mask_invalido.any():
        result.loc[mask_invalido, 'volumen'] = config.magnitud_default
        print(f"    -> {mask_invalido.sum()} registros con volumen inválido "
              f"→ asignado {config.magnitud_default}")

    n_eliminados = n_antes - len(result)
    if n_eliminados > 0:
        print(f"    -> {n_eliminados} registros eliminados (coordenadas NaN)")

    return result


def cargar_restricciones(config: FlowMapConfig) -> Optional[gpd.GeoDataFrame]:
    """
    Carga polígonos de restricción desde archivo geoespacial.

    Los polígonos de restricción representan áreas donde no se permite
    el trazado de rutas (lagos, mares, montañas, zonas protegidas, etc.).

    Args:
        config: Configuración con la ruta del archivo de restricciones.

    Returns:
        GeoDataFrame con polígonos, o None si no hay archivo configurado.
    """
    if not config.archivo_restricciones:
        print("  Sin archivo de restricciones configurado")
        return None

    ruta = config.archivo_restricciones
    print(f"  Cargando restricciones desde: {os.path.basename(ruta)}")

    gdf = gpd.read_file(ruta)

    # Asegurar que sean polígonos
    tipos_validos = {'Polygon', 'MultiPolygon'}
    tipos_encontrados = set(gdf.geometry.geom_type)
    tipos_invalidos = tipos_encontrados - tipos_validos

    if tipos_invalidos:
        print(f"    ADVERTENCIA: Se encontraron geometrías no poligonales: {tipos_invalidos}")
        print(f"    Solo se usarán polígonos como restricciones.")
        gdf = gdf[gdf.geometry.geom_type.isin(tipos_validos)]

    # Reproyectar al CRS de los flujos si es diferente
    if gdf.crs and str(gdf.crs) != config.crs:
        print(f"    Reproyectando de {gdf.crs} a {config.crs}")
        gdf = gdf.to_crs(config.crs)

    print(f"    -> {len(gdf)} polígonos de restricción cargados")

    return gdf


def preparar_datos(
    config: FlowMapConfig,
    flujos_precargados: Optional[gpd.GeoDataFrame] = None,
) -> Tuple[gpd.GeoDataFrame, Optional[gpd.GeoDataFrame], gpd.GeoDataFrame]:
    """
    Función orquestadora que carga y prepara todos los datos necesarios.

    Args:
        config: Configuración centralizada.
        flujos_precargados: GeoDataFrame ya preparado desde ingesta.py.
            Si se provee, se usa directamente sin cargar desde archivo.

    Returns:
        Tupla con:
        - flujos_gdf: GeoDataFrame de flujos estandarizado
        - restricciones_gdf: GeoDataFrame de restricciones (o None)
        - puntos_gdf: GeoDataFrame con todos los puntos únicos (orígenes + destinos)
    """
    print("\n[DATOS] Cargando datos de entrada...")
    print("-" * 45)

    # Cargar flujos (desde archivo o pre-cargados)
    if flujos_precargados is not None:
        print("  Usando flujos pre-cargados desde ingesta.py")
        flujos_gdf = flujos_precargados
        # Asegurar que existan las columnas estandarizadas
        for col in ['orig_x', 'orig_y', 'dest_x', 'dest_y', 'volumen']:
            if col not in flujos_gdf.columns:
                raise ValueError(
                    f"Columna estandarizada '{col}' no encontrada en flujos_precargados. "
                    f"Asegúrese de usar ingesta.preparar_flujos() para generar los datos."
                )
        if 'etiqueta' not in flujos_gdf.columns:
            flujos_gdf['etiqueta'] = ''
    else:
        flujos_gdf = cargar_flujos(config)

    # Cargar restricciones
    restricciones_gdf = cargar_restricciones(config)

    # Crear GeoDataFrame de puntos únicos
    puntos_gdf = _extraer_puntos_unicos(flujos_gdf)

    print(f"\n  Resumen de datos:")
    print(f"    Flujos totales      : {len(flujos_gdf)}")
    print(f"    Volumen total       : {flujos_gdf['volumen'].sum():,.0f}")
    print(f"    Puntos únicos       : {len(puntos_gdf)} ({(puntos_gdf['tipo']=='origen').sum()} orígenes, "
          f"{(puntos_gdf['tipo']=='destino').sum()} destinos)")
    if restricciones_gdf is not None:
        print(f"    Restricciones       : {len(restricciones_gdf)} polígonos")

    return flujos_gdf, restricciones_gdf, puntos_gdf


def _extraer_puntos_unicos(flujos: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Extrae puntos únicos de orígenes y destinos del GeoDataFrame de flujos.

    Agrega el volumen total por punto para dimensionar los marcadores.
    """
    # Orígenes
    origenes = flujos[['orig_x', 'orig_y', 'etiqueta', 'volumen']].copy()
    origenes = origenes.rename(columns={'orig_x': 'x', 'orig_y': 'y'})
    origenes_agr = origenes.groupby(['x', 'y']).agg(
        etiqueta=('etiqueta', 'first'),
        volumen_total=('volumen', 'sum')
    ).reset_index()
    origenes_agr['tipo'] = 'origen'

    # Destinos — no reutilizar la etiqueta del origen cuando el destino no tiene nombre.
    destinos = flujos[['dest_x', 'dest_y', 'volumen']].copy()
    destinos = destinos.rename(columns={'dest_x': 'x', 'dest_y': 'y'})
    destinos['etiqueta'] = (
        flujos['etiqueta_destino'].fillna('').astype(str).values
        if 'etiqueta_destino' in flujos.columns
        else ''
    )
    destinos_agr = destinos.groupby(['x', 'y']).agg(
        etiqueta=('etiqueta', 'first'),
        volumen_total=('volumen', 'sum')
    ).reset_index()
    destinos_agr['tipo'] = 'destino'

    # Combinar
    todos = pd.concat([origenes_agr, destinos_agr], ignore_index=True)
    geometry = [Point(x, y) for x, y in zip(todos['x'], todos['y'])]

    return gpd.GeoDataFrame(todos, geometry=geometry, crs="EPSG:4326")
