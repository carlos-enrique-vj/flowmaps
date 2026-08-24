# Arquitectura de FlowMaps

## Flujo de ejecución

```text
archivo(s) de entrada
        │
        ▼
ingesta.preparar_flujos       normaliza escenarios A1, A2, B y C
        │
        ▼
io_data.preparar_datos        crea puntos y carga restricciones
        │
        ▼
graph                         genera la malla, excluye obstáculos y ancla extremos exactos
        │
        ▼
bundling                      calcula rutas, confluencia y suavizado
        │
        ├──────────────┬───────────────────┐
        ▼              ▼                   ▼
viz_static          viz_interactive     GeoDataFrame
PNG                 HTML                GeoJSON
```

## Módulos

- `config.py`: parámetros del proyecto, cálculo y presentación. `directorio_salida` concentra los entregables sin cambiar los nombres históricos.
- `ingesta.py`: lectura polimórfica y normalización a `orig_x`, `orig_y`, `dest_x`, `dest_y`, `volumen` y `etiqueta`.
- `io_data.py`: compatibilidad con el cargador original, restricciones y puntos únicos.
- `graph.py`: malla espacial, eliminación de nodos/aristas restringidos y anclaje exacto de cada origen y destino para que los cauces intersecten sus marcadores.
- `routing.py`: enrutamiento básico conservado por compatibilidad.
- `bundling.py`: enrutamiento iterativo, acumulación, reconstrucción y suavizado de cauces.
- `viz_static.py`: render PNG con Matplotlib.
- `viz_interactive.py`: render HTML con Folium/Leaflet.
- `pipeline.py`: orquestación end-to-end y registro de rutas de salida.
- `ui_helpers.py`: materialización segura de cargas y previsualización para Streamlit.

## Entradas normalizadas

El contrato interno del pipeline es un `GeoDataFrame` con las siguientes columnas:

| Campo | Descripción |
|---|---|
| `orig_x`, `orig_y` | Coordenadas del origen |
| `dest_x`, `dest_y` | Coordenadas del destino |
| `volumen` | Magnitud del flujo |
| `etiqueta` | Nombre opcional del origen |
| `etiqueta_destino` | Nombre opcional del destino en A2/B |

La interfaz no reimplementa ese contrato: construye los argumentos de `preparar_flujos` y entrega el resultado directamente a `ejecutar_pipeline`.

## Salidas

`FlowMapConfig.ruta_salida()` agrega el prefijo del proyecto y conserva cualquier carpeta explícita. Cuando recibe sólo un nombre, lo resuelve dentro de `directorio_salida`. El pipeline devuelve `png_path`, `html_path` y `geojson_path` cuando cada artefacto fue solicitado.
