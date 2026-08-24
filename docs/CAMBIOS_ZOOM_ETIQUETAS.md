# Actualización: Control de Zoom para Etiquetas de Origen

## Cambios Realizados

Se ha implementado un sistema de **control dinámico de visibilidad de etiquetas** basado en el nivel de zoom del mapa interactivo.

### 📋 Archivos Modificados

#### 1. **flowmaps/config.py**
- ✨ Nuevo parámetro: `zoom_min_etiquetas` (int, default=13)
  - Define el nivel mínimo de zoom requerido para mostrar etiquetas de origen
  - Valor recomendado: 13 (zoom cercano)
  - Personalizable según preferencias del usuario

#### 2. **flowmaps/viz_interactive.py**
- ✨ Nueva función: `_agregar_control_zoom_etiquetas(m, config)`
  - Inyecta un script JavaScript en el mapa HTML
  - Monitorea eventos de zoom (`zoomend`) en Leaflet
  - Muestra/oculta dinámicamente la capa de etiquetas según el nivel de zoom

- 🔄 Modificación: `_agregar_etiquetas_html(m, puntos, config)`
  - La capa permanece disponible en el control de Leaflet
  - El CSS dinámico oculta o muestra las etiquetas cuando cambia el zoom

- 🔄 Modificación: `generar_mapa_html()`
  - Ahora llama a `_agregar_control_zoom_etiquetas()` después de agregar etiquetas
  - Instancia el control de visibilidad dinámico

## 🎯 Comportamiento

| Nivel de Zoom | Etiquetas |
|---|---|
| < 13 (alejado) | ❌ Ocultas |
| >= 13 (cercano) | ✅ Visibles |

## 🎮 Uso

### Configuración Predeterminada
```python
from flowmaps import FlowMapConfig, ejecutar_pipeline

config = FlowMapConfig(
    archivo_flujos="datos.geojson",
    # ... otros parámetros ...
    zoom_min_etiquetas=13,  # ← Control de zoom (valor predeterminado)
    html_salida="mapa.html",
)

mapa = ejecutar_pipeline(config, generar_html=True)
```

### Personalizar el Nivel de Zoom
```python
# Etiquetas visibles solo con zoom muy cercano
config.zoom_min_etiquetas = 14  # Más restrictivo

# Etiquetas visibles con menos zoom
config.zoom_min_etiquetas = 11  # Menos restrictivo
```

## ✨ Ventajas

- **Interfaz limpia a zoom alejado**: El mapa no se congestiona con etiquetas cuando se visualiza la región completa
- **Detalle a zoom cercano**: Las etiquetas de origen se muestran claramente cuando se examina el mapa en detalle
- **Configurable**: El usuario puede ajustar el umbral de zoom según sus necesidades
- **Rendimiento**: Reduce la cantidad de elementos DOM renderizados en zoom alejado

## 🧪 Prueba

Se incluye el script manual `tests/manual/run_zoom_labels_demo.py`:

```powershell
.\.venv\Scripts\python.exe tests\manual\run_zoom_labels_demo.py
```

Esto genera `outputs/manual/zoom_mapa_zoom_labels.html` con el siguiente comportamiento:
- Zoom OUT: Etiquetas desaparecen (zoom < 13)
- Zoom IN: Etiquetas aparecen (zoom >= 13)

## 📝 Notas Técnicas

### JavaScript
- Usa eventos nativos de Leaflet: `zoomend`
- Identifica etiquetas por sus características CSS (`text-shadow`, `white-space: nowrap`)
- Compatible con navegadores modernos (Chrome, Firefox, Safari, Edge)

### Compatibilidad
- ✅ Folium 0.12+
- ✅ Leaflet 1.6+
- ✅ Python 3.11+

## 🔧 Solución de Problemas

Si las etiquetas no desaparecen al hacer zoom out:
1. Verificar que `zoom_min_etiquetas` esté configurado correctamente
2. Abrir la consola del navegador (F12) y buscar errores JavaScript
3. Verificar que la capa "Etiquetas" esté visible en el control de capas

Si las etiquetas no aparecen al hacer zoom in:
1. Verificar que la capa "Etiquetas" no esté desactivada en el control de capas
2. Comprobar que hay etiquetas definidas en los datos (`campo_etiqueta` configurado)
3. Verificar el nivel actual de zoom en la consola del navegador
