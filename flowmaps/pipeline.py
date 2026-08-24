"""
pipeline.py — Orquestación del pipeline completo
=================================================

Función principal que ejecuta todo el flujo de trabajo:
  Datos → Grafo → Restricciones → Bundling → Polilíneas → Visualización

Función principal:
  - ejecutar_pipeline(): Pipeline end-to-end
"""

import os
import time
import geopandas as gpd
from typing import Optional

from .config import FlowMapConfig
from .io_data import preparar_datos
from .graph import crear_grafo_espacial, aplicar_restricciones, anclar_extremos_flujo
from .bundling import (
    calcular_rutas_con_bundling,
    reconstruir_polylineas,
    polylineas_a_geodataframe,
)
from .viz_static import plot_mapa
from .viz_interactive import generar_mapa_html


def ejecutar_pipeline(
    config: FlowMapConfig,
    mostrar_matplotlib: bool = True,
    generar_html: bool = True,
    flujos_precargados: Optional[gpd.GeoDataFrame] = None,
    exportar_geojson: bool = True,
) -> dict:
    """
    Ejecuta el pipeline completo de generación de Flow Map.

    Pipeline:
        1. Carga y preparación de datos
        2. Creación del grafo espacial
        3. Aplicación de restricciones
        4. Edge bundling iterativo (confluencia de ríos)
        5. Reconstrucción de polilíneas suavizadas
        6. Visualización estática (Matplotlib)
        7. Mapa interactivo (Folium/HTML)
        8. Exportación de resultados (GeoJSON con prefijo)

    Args:
        config: Configuración centralizada del pipeline.
        mostrar_matplotlib: Si True, genera el mapa estático.
        generar_html: Si True, genera el mapa interactivo HTML.
        flujos_precargados: GeoDataFrame ya preparado desde ingesta.py.
            Si se provee, se usa directamente sin cargar desde archivo.
        exportar_geojson: Si True, exporta el GeoDataFrame de flujos
            calculados como GeoJSON con prefijo de proyecto.

    Returns:
        Dict con resultados del pipeline.
    """
    print(config.resumen())
    t_inicio = time.time()

    resultados = {}

    if config.directorio_salida:
        os.makedirs(config.directorio_salida, exist_ok=True)

    # ── Paso 1: Cargar datos ──
    flujos, restricciones, puntos = preparar_datos(
        config, flujos_precargados=flujos_precargados
    )
    resultados['flujos'] = flujos
    resultados['restricciones'] = restricciones
    resultados['puntos'] = puntos

    # ── Paso 2: Crear grafo espacial ──
    print(f"\n[GRAFO] Creando malla espacial (res={config.resolucion_grafo})...")
    print("-" * 50)

    todas_x = list(flujos['orig_x']) + list(flujos['dest_x'])
    todas_y = list(flujos['orig_y']) + list(flujos['dest_y'])
    bbox = (min(todas_x), min(todas_y), max(todas_x), max(todas_y))
    print(f"  BBox: lon=[{bbox[0]:.4f}, {bbox[2]:.4f}], lat=[{bbox[1]:.4f}, {bbox[3]:.4f}]")

    G = crear_grafo_espacial(bbox, config)
    resultados['grafo'] = G

    # ── Paso 3: Restricciones ──
    print(f"\n[RESTRICCIONES] Aplicando restricciones espaciales...")
    print("-" * 50)
    G = aplicar_restricciones(G, restricciones, config)

    # Anclar coordenadas reales después de retirar los nodos restringidos.
    # Así cada cauce comienza y termina exactamente en su marcador.
    G = anclar_extremos_flujo(G, flujos)
    resultados['grafo'] = G

    # ── Paso 4: Edge Bundling iterativo ──
    print(f"\n[BUNDLING] Enrutamiento con confluencia de rios "
          f"({config.iteraciones_bundling} iteraciones, "
          f"alpha={config.factor_atraccion})...")
    print("-" * 50)
    flujo_acumulado, rutas, fallidas = calcular_rutas_con_bundling(G, flujos, config)
    resultados['flujo_acumulado'] = flujo_acumulado
    resultados['rutas'] = rutas

    # ── Paso 5: Reconstrucción de polilíneas ──
    print(f"\n[POLYLINEAS] Reconstruyendo cauces suavizados "
          f"(Chaikin x{config.suavizado_iteraciones})...")
    print("-" * 50)
    polylineas = reconstruir_polylineas(G, flujo_acumulado, config)
    resultados['polylineas'] = polylineas

    # Generar GeoDataFrame exportable
    flujo_gdf = polylineas_a_geodataframe(polylineas, config)
    resultados['flujo_gdf'] = flujo_gdf

    # ── Paso 6: Visualización estática ──
    if mostrar_matplotlib:
        print(f"\n[VIZ] Generando mapa estatico (Matplotlib)...")
        print("-" * 50)

        # Aplicar prefijo a la ruta de guardado si existe
        guardar_como_original = config.guardar_como
        if config.guardar_como:
            config.guardar_como = config.ruta_salida(config.guardar_como)

        fig = plot_mapa(polylineas, restricciones, puntos, flujos, config)
        resultados['fig'] = fig
        if config.guardar_como:
            resultados['png_path'] = config.guardar_como

        # Restaurar ruta original
        config.guardar_como = guardar_como_original

    # ── Paso 7: Mapa interactivo ──
    if generar_html:
        print(f"\n[HTML] Generando mapa interactivo (Folium/Leaflet)...")
        print("-" * 50)

        # Aplicar prefijo a la ruta HTML si existe
        html_salida_original = config.html_salida
        if config.html_salida:
            config.html_salida = config.ruta_salida(config.html_salida)

        mapa = generar_mapa_html(polylineas, restricciones, puntos, flujos, config)
        resultados['mapa_html'] = mapa
        if config.html_salida:
            resultados['html_path'] = config.html_salida

        # Restaurar ruta original
        config.html_salida = html_salida_original

    # ── Paso 8: Exportar GeoJSON con prefijo ──
    if exportar_geojson and not flujo_gdf.empty:
        nombre_geojson = config.ruta_salida("flujos_calculados.geojson")
        flujo_gdf.to_file(nombre_geojson, driver="GeoJSON")
        print(f"\n[EXPORT] GeoJSON exportado: {nombre_geojson}")
        resultados['geojson_path'] = nombre_geojson

    # ── Resumen final ──
    t_total = time.time() - t_inicio
    print(f"\n{'=' * 55}")
    print(f"  Pipeline completado en {t_total:.2f} segundos")
    print(f"  Rutas: {len(rutas)}, Cauces: {len(polylineas)}")
    if flujo_acumulado:
        vmax = max(flujo_acumulado.values())
        print(f"  Flujo maximo por segmento: {vmax:,.0f}")
    if config.prefijo_proyecto:
        print(f"  Proyecto: {config.prefijo_proyecto}")
    print(f"{'=' * 55}")

    return resultados
