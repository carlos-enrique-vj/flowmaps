"""Utilidades de entrada/salida para la interfaz Streamlit de FlowMaps."""

from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd


FORMATOS_CARGA = [
    "csv",
    "tsv",
    "xlsx",
    "xls",
    "geojson",
    "json",
    "gpkg",
    "parquet",
    "geoparquet",
    "zip",
]

FORMATOS_RESTRICCION = ["geojson", "json", "gpkg", "zip"]


@dataclass(frozen=True)
class VistaArchivo:
    """Resumen ligero de un archivo de entrada."""

    columnas: tuple[str, ...]
    total_registros: int
    muestra: pd.DataFrame
    es_geoespacial: bool
    conteos_unicos: dict[str, int]

    def coordenada_es_unica(self, campo_x: str, campo_y: str) -> bool:
        """Indica si todas las filas comparten un mismo par de coordenadas."""
        if self.total_registros == 1:
            return True
        return (
            bool(campo_x and campo_y)
            and self.conteos_unicos.get(campo_x) == 1
            and self.conteos_unicos.get(campo_y) == 1
        )


def normalizar_prefijo(valor: str) -> str:
    """Convierte el nombre de proyecto en un prefijo de archivo seguro."""
    limpio = re.sub(r"[^0-9A-Za-záéíóúÁÉÍÓÚñÑ_-]+", "_", valor.strip())
    return limpio.strip("._-") or "flowmap"


def materializar_archivo(
    nombre: str,
    contenido: bytes | bytearray | memoryview,
    carpeta_sesion: Path,
    rol: str,
) -> Path:
    """Guarda una carga de Streamlit y resuelve ZIP de SHP/GDB de forma segura."""
    datos = bytes(contenido)
    huella = hashlib.sha256(datos).hexdigest()[:16]
    carpeta = carpeta_sesion / "entradas" / f"{rol}_{huella}"
    carpeta.mkdir(parents=True, exist_ok=True)

    nombre_seguro = Path(nombre).name
    destino = carpeta / nombre_seguro
    if not destino.exists():
        destino.write_bytes(datos)

    if destino.suffix.lower() != ".zip":
        return destino

    carpeta_extraida = carpeta / "extraido"
    if not carpeta_extraida.exists():
        carpeta_extraida.mkdir()
        _extraer_zip_seguro(destino, carpeta_extraida)

    candidatos_gdb = sorted(
        p for p in carpeta_extraida.rglob("*") if p.is_dir() and p.suffix.lower() == ".gdb"
    )
    candidatos = candidatos_gdb or sorted(
        p
        for p in carpeta_extraida.rglob("*")
        if p.is_file()
        and p.suffix.lower()
        in {".shp", ".gpkg", ".geojson", ".json", ".parquet", ".geoparquet", ".csv", ".tsv", ".xlsx", ".xls"}
    )

    if not candidatos:
        raise ValueError(
            "El ZIP no contiene un SHP, GDB, GPKG, GeoJSON, GeoParquet o archivo tabular compatible."
        )
    if len(candidatos) > 1:
        nombres = ", ".join(str(p.relative_to(carpeta_extraida)) for p in candidatos[:5])
        raise ValueError(f"El ZIP contiene varias fuentes de datos ({nombres}). Incluye sólo una.")
    return candidatos[0]


def _extraer_zip_seguro(archivo_zip: Path, destino: Path) -> None:
    """Extrae un ZIP rechazando rutas absolutas y recorridos ``..``."""
    raiz = destino.resolve()
    with zipfile.ZipFile(archivo_zip) as comprimido:
        for info in comprimido.infolist():
            nombre = info.filename.replace("\\", "/")
            if not nombre or nombre.startswith("/"):
                continue
            ruta = (raiz / nombre).resolve()
            if raiz != ruta and raiz not in ruta.parents:
                raise ValueError("El ZIP contiene una ruta no segura.")
            if info.is_dir():
                ruta.mkdir(parents=True, exist_ok=True)
                continue
            ruta.parent.mkdir(parents=True, exist_ok=True)
            with comprimido.open(info) as origen, ruta.open("wb") as salida:
                shutil.copyfileobj(origen, salida)


def inspeccionar_archivo(ruta: str | Path, limite: int = 100) -> VistaArchivo:
    """Lee columnas, conteo y una muestra sin alterar el archivo original."""
    ruta = Path(ruta)
    extension = ruta.suffix.lower()
    es_geo = ruta.is_dir() and extension == ".gdb"
    es_geo = es_geo or extension in {
        ".shp",
        ".geojson",
        ".json",
        ".gpkg",
        ".parquet",
        ".geoparquet",
    }

    if es_geo:
        if extension in {".parquet", ".geoparquet"}:
            datos = gpd.read_parquet(ruta)
        else:
            datos = gpd.read_file(ruta)
    elif extension == ".csv":
        datos = pd.read_csv(ruta)
    elif extension == ".tsv":
        datos = pd.read_csv(ruta, sep="\t")
    elif extension in {".xlsx", ".xls"}:
        datos = pd.read_excel(ruta)
    else:
        raise ValueError(f"No se puede previsualizar el formato '{extension}'.")

    columnas = tuple(str(columna) for columna in datos.columns if columna != "geometry")
    datos_tabulares = pd.DataFrame(datos.drop(columns="geometry", errors="ignore"))
    conteos_unicos = {}
    for columna in columnas:
        serie = datos_tabulares[columna]
        try:
            conteos_unicos[columna] = int(serie.nunique(dropna=True))
        except TypeError:
            conteos_unicos[columna] = int(serie.astype(str).nunique(dropna=True))
    muestra = datos_tabulares.head(limite)
    return VistaArchivo(columnas, len(datos), muestra, es_geo, conteos_unicos)
