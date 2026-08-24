"""
FlowMaps — Generador de Mapas de Flujos Distributivos
=====================================================

Paquete modular para crear mapas de flujo con enrutamiento espacial,
restricciones geográficas, edge bundling iterativo (confluencia de ríos)
y acumulación de volumen por segmento.

Módulos:
    - config: Configuración global y dataclass de parámetros
    - ingesta: Ingesta polimórfica de datos (escenarios A1, A2, B, C)
    - io_data: Lectura de datos geoespaciales (Shapefile, GeoJSON, GPKG, GDB, CSV)
    - graph: Creación del grafo espacial y aplicación de restricciones
    - bundling: Edge bundling iterativo + reconstrucción de polilíneas suavizadas
    - routing: Cálculo de rutas básico (sin bundling, para compatibilidad)
    - viz_static: Visualización estática con Matplotlib
    - viz_interactive: Mapa interactivo HTML con Folium/Leaflet
"""

__version__ = "0.5.0"
__author__ = "FlowMaps Project"

from .config import FlowMapConfig
from .ingesta import (
    EscenarioFlujo,
    cargar_puntos,
    asignar_vecino_cercano,
    preparar_flujos,
)
from .io_data import cargar_flujos, cargar_restricciones, preparar_datos
from .graph import crear_grafo_espacial, aplicar_restricciones, anclar_extremos_flujo
from .bundling import (
    calcular_rutas_con_bundling,
    reconstruir_polylineas,
    suavizar_chaikin,
    polylineas_a_geodataframe,
)
from .routing import calcular_rutas_acumuladas, generar_geometrias_flujo
from .viz_static import plot_mapa
from .viz_interactive import generar_mapa_html
from .pipeline import ejecutar_pipeline
