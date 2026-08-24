"""
config.py — Configuración centralizada del generador de flujos
==============================================================

Define la dataclass `FlowMapConfig` con todos los parámetros ajustables
del pipeline: campos de datos, resolución del grafo, estilo visual, etc.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FlowMapConfig:
    """
    Configuración centralizada para el pipeline de FlowMaps.

    Agrupa todos los parámetros en categorías lógicas para facilitar
    la configuración desde el notebook o línea de comandos.

    Atributos:
    ----------
    Proyecto:
        prefijo_proyecto : Prefijo para archivos de salida (ej. "mexico", "marruecos")
        nombre_destino : Etiqueta para el punto de destino en visualizaciones
        directorio_salida : Carpeta donde se escriben los entregables

    Datos de entrada:
        archivo_flujos : Ruta al archivo de flujos (GeoJSON, SHP, GPKG, GDB, CSV)
        archivo_restricciones : Ruta al archivo de restricciones (opcional)
        campo_orig_x : Nombre del campo con la longitud del origen
        campo_orig_y : Nombre del campo con la latitud del origen
        campo_dest_x : Nombre del campo con la longitud del destino
        campo_dest_y : Nombre del campo con la latitud del destino
        campo_volumen : Nombre del campo numérico para la proporción de líneas
        campo_etiqueta : Nombre del campo para etiquetas (opcional)
        magnitud_default : Valor por defecto si no existe campo de volumen
        crs : Sistema de coordenadas (por defecto EPSG:4326 = WGS84)

    Grafo espacial:
        resolucion_grafo : Número de divisiones en cada eje (mayor = más detalle)
        conexion_diagonal : Incluir conexiones diagonales (8-conectividad)
        buffer_restriccion : Buffer alrededor de polígonos de restricción

    Edge Bundling (confluencia de ríos):
        iteraciones_bundling : Pasadas de atracción iterativa (3-5 recomendado)
        factor_atraccion : Intensidad de la atracción (0.0=nulo, 0.9=máximo)
        suavizado_iteraciones : Pasadas de suavizado Chaikin (2-4 recomendado)

    Visualización estática:
        grosor_min : Grosor mínimo de línea (pt)
        grosor_max : Grosor máximo de línea (pt)
        colormap : Colormap de Matplotlib
        fondo_color : Color de fondo del mapa
        color_linea_unico : Color único para líneas (None = usar colormap)
        titulo : Título del mapa
        mostrar_etiquetas : Mostrar nombres de los puntos
        mostrar_grafo_base : Mostrar la malla del grafo (debug)
        guardar_como : Ruta para guardar la imagen

    Mapa interactivo:
        html_salida : Ruta para guardar el mapa HTML
        tiles : Proveedor de tiles para el mapa base
        color_flujo_html : Color de las líneas de flujo en el mapa HTML
        opacidad_flujo : Opacidad de las líneas (0.0 a 1.0)
    """

    # ── Proyecto ──
    prefijo_proyecto: str = ""           # Ej: "mexico", "marruecos"
    nombre_destino: str = "Destino"      # Etiqueta por defecto (se usa el nombre real de cada destino si existe)
    directorio_salida: str = "."         # Carpeta para PNG, HTML y GeoJSON

    # ── Datos de entrada ──
    archivo_flujos: str = ""
    archivo_restricciones: Optional[str] = None
    campo_orig_x: str = "long"
    campo_orig_y: str = "lat"
    campo_dest_x: str = "dest_x"
    campo_dest_y: str = "dest_y"
    campo_volumen: str = "Viaj_5a10"
    campo_etiqueta: Optional[str] = "Descripcio"
    magnitud_default: float = 1.0        # Valor si no existe campo de volumen
    crs: str = "EPSG:4326"

    # ── Grafo espacial ──
    resolucion_grafo: int = 100
    conexion_diagonal: bool = True
    buffer_restriccion: float = 0.0
    dibujar_restricciones: bool = False

    # ── Edge Bundling (efecto confluencia de ríos) ──
    iteraciones_bundling: int = 4       # Pasadas de atracción (3-5 recomendado)
    factor_atraccion: float = 0.65      # Intensidad: 0.0=nulo, 0.9=máximo
    suavizado_iteraciones: int = 3      # Pasadas Chaikin (2-4 recomendado)

    # ── Visualización estática (Matplotlib) ──
    grosor_min: float = 0.4
    grosor_max: float = 14.0
    colormap: str = "RdYlBu"
    fondo_color: str = "#1a1a2e"
    color_linea_unico: Optional[str] = None  # ej. "#00e5a0" para color fijo estilo referencia
    titulo: str = "Mapa de Flujos Distributivos"
    mostrar_etiquetas: bool = True
    mostrar_grafo_base: bool = False
    guardar_como: Optional[str] = None
    dpi: int = 200

    # ── Mapa interactivo (Folium/Leaflet) ──
    html_salida: Optional[str] = None
    tiles: str = "CartoDB dark_matter"
    color_flujo_html: str = "#00e5a0"
    opacidad_flujo: float = 0.75
    grosor_min_html: float = 1.0
    grosor_max_html: float = 18.0
    zoom_min_etiquetas: int = 13  # Zoom mínimo para mostrar etiquetas de origen

    def ruta_salida(self, nombre_base: str) -> str:
        """
        Genera nombre de archivo con prefijo de proyecto.

        Args:
            nombre_base: Nombre base del archivo (ej. "flujos_calculados.geojson")

        Returns:
            Ruta con directorio y prefijo. Ej:
            "outputs/mexico_flujos_calculados.geojson".
        """
        ruta = Path(nombre_base)

        if self.prefijo_proyecto:
            ruta = ruta.with_name(f"{self.prefijo_proyecto}_{ruta.name}")

        # Las rutas explícitas conservan su carpeta. Los nombres simples se
        # resuelven dentro de directorio_salida para mantener limpia la raíz.
        if ruta.parent == Path(".") and self.directorio_salida:
            ruta = Path(self.directorio_salida) / ruta

        return str(ruta)

    def resumen(self) -> str:
        """Retorna un resumen legible de la configuración."""
        lineas = [
            "=" * 55,
            "  CONFIGURACIÓN FlowMaps",
            "=" * 55,
            f"  Proyecto             : {self.prefijo_proyecto or '(sin prefijo)'}",
            f"  Nombre destino       : {self.nombre_destino}",
            f"  Directorio salida    : {self.directorio_salida}",
            f"  Archivo de flujos    : {self.archivo_flujos or '(demo)'}",
            f"  Restricciones        : {self.archivo_restricciones or '(ninguna)'}",
            f"  Campo volumen        : {self.campo_volumen}",
            f"  Magnitud default     : {self.magnitud_default}",
            f"  Campos origen        : ({self.campo_orig_x}, {self.campo_orig_y})",
            f"  Campos destino       : ({self.campo_dest_x}, {self.campo_dest_y})",
            f"  CRS                  : {self.crs}",
            f"  Resolución grafo     : {self.resolucion_grafo}",
            f"  Buffer restricción   : {self.buffer_restriccion}",
            f"  Bundling iteraciones : {self.iteraciones_bundling}",
            f"  Factor atracción     : {self.factor_atraccion}",
            f"  Suavizado Chaikin    : {self.suavizado_iteraciones} pasadas",
            f"  Grosor líneas        : {self.grosor_min} - {self.grosor_max}",
            f"  Colormap             : {self.colormap}",
            "=" * 55,
        ]
        return "\n".join(lineas)
