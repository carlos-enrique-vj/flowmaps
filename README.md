# FlowMaps

FlowMaps es una aplicación web y librería geoespacial diseñada para generar **mapas de flujos distributivos** a partir de datos de origen y destino. El pipeline interno crea una malla espacial, evita polígonos de restricción, agrupa rutas utilizando algoritmos de *edge bundling* (confluencia) y produce resultados listos para análisis y publicación.

![Ejemplo de mapa de flujos](image/logo_flowmaps.png)

*Interfaz de FlowMaps y resultados visuales*

---

## 🚀 Características Principales

*   **Entregables Múltiples:** Genera un mapa estático de alta resolución (PNG), un mapa web interactivo (HTML con Leaflet/Folium) y geometrías vectoriales (GeoJSON) para usar en tu software SIG preferido (QGIS, ArcGIS, etc).
*   **Gestión de Restricciones:** Capacidad para definir polígonos de exclusión espacial (por ejemplo, cuerpos de agua o áreas protegidas) que el algoritmo de enrutamiento evitará.
*   **Confluencia Inteligente:** Aplica algoritmos de atracción espacial (*edge bundling*) para revelar patrones principales de flujo y evitar el desorden visual típico del "efecto espagueti".
*   **Formatos Compatibles:** Soporta carga de datos en múltiples formatos: CSV, TSV, Excel, GeoJSON, GeoPackage y GeoParquet. (Para Shapefile o FileGDB, sube un archivo `.zip` con sus componentes).

## 📊 Tipos de Análisis Soportados

FlowMaps soporta cuatro arquitecturas de datos (Escenarios):

| Código | Escenario de Análisis | Entradas Requeridas |
|---|---|---|
| **A1** | Muchos orígenes hacia un destino fijo | Archivo de orígenes + Coordenada de destino (Lat/Lon) |
| **A2** | Un origen fijo hacia muchos destinos | Coordenada de origen (Lat/Lon) + Archivo de destinos |
| **B** | Cada origen hacia su destino más cercano | Archivo de orígenes + Archivo de destinos |
| **C** | Pares origen–destino precalculados | Un único archivo con las cuatro coordenadas (O y D) |

---

## ⚠️ Recomendaciones y Límites de Uso

Dado que el procesamiento de grafos espaciales y la rasterización son operaciones intensivas en memoria y CPU, la aplicación incluye las siguientes restricciones por diseño para asegurar su estabilidad, especialmente en entornos de nube (como Streamlit Community Cloud):

1. **Tamaño Máximo de Archivo:** No se permiten archivos mayores a **200 MB**. Si tus bases de datos exceden este límite, deberás preprocesarlas, filtrarlas o simplificar sus geometrías.
2. **Límite de Registros (Puntos):** La aplicación procesará un máximo de **50,000 registros (puntos/filas)** por análisis. Superar esta cifra provocaría la caída del servidor por falta de RAM y generaría un mapa ilegible por la alta densidad visual. 
3. **Resolución de Malla:** Utiliza resoluciones de malla bajas (ej. 50-80) para tus primeras pruebas. Una vez que valides que la salida es correcta, puedes aumentar la resolución (ej. 120-150) para la exportación final de alta calidad.

---

## 💻 Instalación y Despliegue Local

Para ejecutar FlowMaps en tu propio equipo sin los límites de la nube, sigue estos pasos:

1. Clona el repositorio:
   ```bash
   git clone https://github.com/carlos-enrique-vj/flowmaps.git
   cd flowmaps
   ```
2. Crea un entorno virtual e instala las dependencias:
   ```bash
   python -m venv .venv
   # Activa el entorno virtual:
   # En Windows: .venv\Scripts\activate
   # En macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Ejecuta la aplicación de Streamlit:
   ```bash
   streamlit run app.py
   ```

---

## 📂 Estructura del Repositorio

```text
flowmaps/
├── app.py                    # Aplicación web principal (Streamlit)
├── flowmaps/                 # Paquete núcleo con la lógica del pipeline
├── data/                     # Datos geoespaciales de muestra
├── docs/                     # Documentación técnica y de arquitectura
├── image/                    # Recursos visuales
└── requirements.txt          # Dependencias del proyecto
```

*(Nota: Los scripts experimentales, notebooks y tests han sido excluidos de la versión pública para mantener la herramienta enfocada únicamente en su uso de producción).*

## 📜 Autoría y Licencia

Desarrollado por [Carlos Enrique Vázquez Juárez](https://carlos-enrique.carto.mx/). 
El código se distribuye bajo la **Licencia MIT**: puede usarse, modificarse y redistribuirse libremente siempre y cuando se conserve el aviso de autoría y la fuente original.

[GitHub](https://github.com/carlos-enrique-vj/) · [LinkedIn](https://www.linkedin.com/in/carlos-enrique-vj/) · [Portafolio](https://carlos-enrique.carto.mx/)
