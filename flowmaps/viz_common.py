"""Cálculos compartidos por las visualizaciones estática e interactiva."""

from __future__ import annotations

import numpy as np


def obtener_destinos(puntos, flujos) -> np.ndarray:
    """Devuelve las coordenadas únicas ``(x, y)`` de todos los destinos."""
    destinos = puntos[puntos['tipo'] == 'destino'] if puntos is not None else None
    if destinos is not None and not destinos.empty:
        coordenadas = np.column_stack(
            (destinos.geometry.x.to_numpy(), destinos.geometry.y.to_numpy())
        )
    else:
        coordenadas = flujos[['dest_x', 'dest_y']].to_numpy(dtype=float)

    coordenadas = np.asarray(coordenadas, dtype=float)
    coordenadas = coordenadas[np.isfinite(coordenadas).all(axis=1)]
    if coordenadas.size == 0:
        raise ValueError("No hay coordenadas de destino válidas para calcular el gradiente.")
    return np.unique(coordenadas, axis=0)


def distancia_destino_mas_cercano(
    x: float,
    y: float,
    destinos: np.ndarray,
) -> float:
    """Calcula la distancia euclidiana desde un punto al destino más cercano."""
    diferencias = destinos - np.asarray([x, y], dtype=float)
    return float(np.sqrt(np.sum(diferencias * diferencias, axis=1)).min())
