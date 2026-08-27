"""Interfaz web local para ejecutar y previsualizar el pipeline FlowMaps."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import time
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import streamlit as st

from flowmaps import FlowMapConfig, ejecutar_pipeline, preparar_flujos
from flowmaps.ui_helpers import (
    FORMATOS_CARGA,
    FORMATOS_RESTRICCION,
    VistaArchivo,
    inspeccionar_archivo,
    materializar_archivo,
    normalizar_prefijo,
)


RAIZ = Path(__file__).resolve().parent
ESCENARIOS = {
    "OD definidos": "C",
    "Destino fijo": "A1",
    "Origen fijo": "A2",
    "Más cercano": "B",
}
DESCRIPCIONES_ESCENARIO = {
    "C": "Archivo con pares origen–destino.",
    "A1": "Varios orígenes convergen en un destino.",
    "A2": "Un origen distribuye flujo a varios destinos.",
    "B": "Cada origen usa el destino más cercano.",
}


def _inicializar_sesion() -> Path:
    if "flowmaps_workspace" not in st.session_state:
        st.session_state.flowmaps_workspace = tempfile.mkdtemp(prefix="flowmaps_ui_")
    return Path(st.session_state.flowmaps_workspace)


def _archivo_cargado(label: str, key: str, carpeta: Path, tipos: list[str]):
    carga = st.file_uploader(label, type=tipos, key=key)
    if carga is None:
        return None, None
    try:
        ruta = materializar_archivo(carga.name, carga.getbuffer(), carpeta, key)
        vista = inspeccionar_archivo(ruta)
        
        # Límite de registros para evitar problemas de rendimiento/memoria
        MAX_REGISTROS = 50000
        if vista.total_registros > MAX_REGISTROS:
            st.error(f"El archivo **{carga.name}** tiene {vista.total_registros:,} registros, lo cual excede el límite de {MAX_REGISTROS:,} para esta aplicación web. Por favor reduce el tamaño de tus datos.")
            return None, None
            
        return ruta, vista
    except Exception as exc:
        st.error(f"No fue posible leer **{carga.name}**: {exc}")
        return None, None


def _mostrar_vista(nombre: str, vista: VistaArchivo | None) -> None:
    if vista is None:
        return
    with st.expander(f"Vista previa · {nombre} ({vista.total_registros:,})"):
        st.dataframe(vista.muestra.head(20), width="stretch", hide_index=True, height=180)


def _indice_sugerido(columnas: tuple[str, ...], sugerencias: tuple[str, ...]) -> int:
    minusculas = [columna.lower() for columna in columnas]
    for sugerencia in sugerencias:
        if sugerencia.lower() in minusculas:
            return minusculas.index(sugerencia.lower())
    return 0


def _campo(
    etiqueta: str,
    columnas: tuple[str, ...],
    key: str,
    sugerencias: tuple[str, ...],
) -> str:
    if not columnas:
        return ""
    return st.selectbox(
        etiqueta,
        columnas,
        index=_indice_sugerido(columnas, sugerencias),
        key=key,
    )


def _campo_opcional(
    etiqueta: str,
    columnas: tuple[str, ...],
    key: str,
    sugerencias: tuple[str, ...],
) -> str | None:
    opciones = ("Sin campo",) + columnas
    sugerido = _indice_sugerido(columnas, sugerencias) + 1 if columnas else 0
    if columnas and not any(s.lower() in [c.lower() for c in columnas] for s in sugerencias):
        sugerido = 0
    valor = st.selectbox(etiqueta, opciones, index=sugerido, key=key)
    return None if valor == "Sin campo" else valor


def _nombre_entrada(argumentos: dict, escenario: str) -> str:
    clave = {
        "C": "archivo_flujos",
        "A1": "archivo_origenes",
        "A2": "archivo_destinos",
        "B": "archivo_origenes",
    }[escenario]
    ruta = argumentos.get(clave)
    return Path(ruta).stem if ruta else "flowmap"


def _configurar_datos(
    escenario: str, carpeta: Path
) -> tuple[dict, list[str], dict[str, bool]]:
    argumentos: dict = {"escenario": escenario}
    errores: list[str] = []
    extremos_unicos = {
        "origen": escenario == "A2",
        "destino": escenario == "A1",
    }

    usar_demo = False
    if escenario == "C":
        usar_demo = st.toggle(
            "Usar ejemplo CDMX",
            value=True,
            help="Desactívalo para cargar un archivo propio.",
        )

    if escenario == "C":
        if usar_demo:
            ruta = RAIZ / "data" / "examples" / "demo_cdmx.geojson"
            vista = inspeccionar_archivo(ruta)
        else:
            ruta, vista = _archivo_cargado(
                "Archivo de pares OD", "flujos", carpeta, FORMATOS_CARGA
            )
        if ruta is None or vista is None:
            errores.append("Carga un archivo con pares origen–destino.")
            return argumentos, errores, extremos_unicos
        argumentos["archivo_flujos"] = str(ruta)
        columnas = vista.columnas
        with st.expander("▦ Campos detectados · revisar"):
            c1, c2 = st.columns(2)
            with c1:
                argumentos["campo_orig_x"] = _campo(
                    "X origen", columnas, "c_orig_x", ("orig_x", "long", "longitud", "lon")
                )
                argumentos["campo_dest_x"] = _campo(
                    "X destino", columnas, "c_dest_x", ("dest_x", "long_dest", "dest_lon")
                )
                argumentos["campo_magnitud"] = _campo_opcional(
                    "Volumen", columnas, "c_magnitud", ("volumen", "Viaj_5a10", "viajes", "magnitud")
                )
            with c2:
                argumentos["campo_orig_y"] = _campo(
                    "Y origen", columnas, "c_orig_y", ("orig_y", "lat", "latitud")
                )
                argumentos["campo_dest_y"] = _campo(
                    "Y destino", columnas, "c_dest_y", ("dest_y", "lat_dest", "dest_lat")
                )
                argumentos["campo_etiqueta_orig"] = _campo_opcional(
                    "Etiqueta", columnas, "c_etiqueta", ("etiqueta", "Descripcio", "nombre", "name")
                )
            _mostrar_vista("pares OD", vista)
        extremos_unicos["origen"] = vista.coordenada_es_unica(
            argumentos["campo_orig_x"], argumentos["campo_orig_y"]
        )
        extremos_unicos["destino"] = vista.coordenada_es_unica(
            argumentos["campo_dest_x"], argumentos["campo_dest_y"]
        )
        return argumentos, errores, extremos_unicos

    if escenario in {"A1", "B"}:
        ruta_origen, vista_origen = _archivo_cargado(
            "Archivo de orígenes", "origenes", carpeta, FORMATOS_CARGA
        )
        if ruta_origen is None or vista_origen is None:
            errores.append("Carga el archivo de orígenes.")
        else:
            argumentos["archivo_origenes"] = str(ruta_origen)
            cols = vista_origen.columnas
            with st.expander("▦ Campos de origen · revisar"):
                c1, c2 = st.columns(2)
                with c1:
                    argumentos["campo_orig_x"] = _campo(
                        "X origen", cols, "orig_x", ("longitud", "long", "lon", "x")
                    )
                    argumentos["campo_magnitud"] = _campo_opcional(
                        "Volumen", cols, "orig_mag", ("volumen", "viajes", "magnitud", "alum_t")
                    )
                with c2:
                    argumentos["campo_orig_y"] = _campo(
                        "Y origen", cols, "orig_y", ("latitud", "lat", "y")
                    )
                    argumentos["campo_etiqueta_orig"] = _campo_opcional(
                        "Etiqueta", cols, "orig_label", ("etiqueta", "nombre", "name", "Descripcio")
                    )
                _mostrar_vista("orígenes", vista_origen)
            extremos_unicos["origen"] = vista_origen.coordenada_es_unica(
                argumentos["campo_orig_x"], argumentos["campo_orig_y"]
            )

    if escenario in {"A2", "B"}:
        ruta_destino, vista_destino = _archivo_cargado(
            "Archivo de destinos", "destinos", carpeta, FORMATOS_CARGA
        )
        if ruta_destino is None or vista_destino is None:
            errores.append("Carga el archivo de destinos.")
        else:
            argumentos["archivo_destinos"] = str(ruta_destino)
            cols = vista_destino.columnas
            with st.expander("▦ Campos de destino · revisar"):
                c1, c2 = st.columns(2)
                with c1:
                    argumentos["campo_dest_x"] = _campo(
                        "X destino", cols, "dest_x", ("longitud", "long", "lon", "x")
                    )
                with c2:
                    argumentos["campo_dest_y"] = _campo(
                        "Y destino", cols, "dest_y", ("latitud", "lat", "y")
                    )
                argumentos["campo_etiqueta_dest"] = _campo_opcional(
                    "Etiqueta destino", cols, "dest_label", ("etiqueta", "nombre", "name", "NOM_LOC")
                )
                if escenario == "A2":
                    argumentos["campo_magnitud"] = _campo_opcional(
                        "Volumen", cols, "dest_mag", ("volumen", "viajes", "magnitud")
                    )
                _mostrar_vista("destinos", vista_destino)
            extremos_unicos["destino"] = vista_destino.coordenada_es_unica(
                argumentos["campo_dest_x"], argumentos["campo_dest_y"]
            )

    if escenario == "A1":
        st.caption("Coordenada del destino")
        c1, c2 = st.columns(2)
        argumentos["coord_destino_fijo"] = (
            c1.number_input("Latitud", value=19.359000, format="%.6f", key="dest_lat_fijo"),
            c2.number_input("Longitud", value=-99.263000, format="%.6f", key="dest_lon_fijo"),
        )
    elif escenario == "A2":
        st.caption("Coordenada del origen")
        c1, c2 = st.columns(2)
        argumentos["coord_origen_fijo"] = (
            c1.number_input("Latitud", value=19.432600, format="%.6f", key="orig_lat_fijo"),
            c2.number_input("Longitud", value=-99.133200, format="%.6f", key="orig_lon_fijo"),
        )

    return argumentos, errores, extremos_unicos


def _panel_vacio() -> None:
    st.markdown('<div class="result-title">Resultados</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="empty-state">
          <div class="empty-icon">⌁</div>
          <h2>El mapa aparecerá aquí</h2>
          <p>Selecciona el tipo de análisis, revisa los datos de entrada y ejecuta FlowMaps.</p>
          <div class="empty-steps"><span>1&nbsp; Análisis</span><span>2&nbsp; Datos</span><span>3&nbsp; Ejecutar</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _mostrar_resultados(resultado: dict) -> None:
    encabezado, descargas = st.columns([3.6, 2.4], vertical_alignment="center")
    with encabezado:
        st.markdown('<div class="result-title">Resultados</div>', unsafe_allow_html=True)
        st.caption(f"{resultado['escenario']} · última ejecución")
    with descargas:
        artefactos = resultado["artefactos"]
        columnas_descarga = st.columns([0.42] + [1] * max(1, len(artefactos)), vertical_alignment="center")
        columnas_descarga[0].markdown(
            '<div class="download-cue" title="Descargar archivos">⇩</div>',
            unsafe_allow_html=True,
        )
        for columna, (clave, contenido) in zip(columnas_descarga[1:], artefactos.items()):
            mime = {
                "png": "image/png",
                "html": "text/html",
                "geojson": "application/geo+json",
            }[clave]
            columna.download_button(
                f"↓ {clave.upper()}",
                contenido["datos"],
                contenido["nombre"],
                mime,
                width="stretch",
            )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pares OD", f"{resultado['pares']:,}")
    m2.metric("Rutas", f"{resultado['rutas']:,}")
    m3.metric("Cauces", f"{resultado['cauces']:,}")
    m4.metric("Tiempo", f"{resultado['segundos']:.1f} s")

    pestanas = st.tabs(["⌁ Mapa interactivo", "▧ Mapa estático", "◇ Datos", "≡ Registro"])
    with pestanas[0]:
        html = artefactos.get("html")
        if html:
            st.iframe(html["texto"], height=600)
        else:
            st.info("El HTML no fue seleccionado para esta ejecución.")
    with pestanas[1]:
        png = artefactos.get("png")
        if png:
            st.image(png["datos"], width="stretch")
        else:
            st.info("El PNG no fue seleccionado para esta ejecución.")
    with pestanas[2]:
        geojson = artefactos.get("geojson")
        if geojson:
            contenido = json.loads(geojson["datos"])
            propiedades = [entidad.get("properties", {}) for entidad in contenido.get("features", [])]
            st.dataframe(propiedades, width="stretch", hide_index=True, height=400)
        else:
            st.info("El GeoJSON no fue seleccionado para esta ejecución.")
    with pestanas[3]:
        st.code(resultado["registro"], language="text", height=400)


def main() -> None:
    st.set_page_config(
        page_title="FlowMaps",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if "ui_theme" not in st.session_state:
        st.session_state.ui_theme = "dark"
    tema_oscuro = st.session_state.ui_theme == "dark"
    paleta = {
        "app": "#10131A" if tema_oscuro else "#F5F7FA",
        "sidebar": "#181D27" if tema_oscuro else "#FFFFFF",
        "surface": "#181D27" if tema_oscuro else "#FFFFFF",
        "surface_soft": "#121720" if tema_oscuro else "#F8FAFC",
        "text": "#F3F5F7" if tema_oscuro else "#172033",
        "muted": "#9BA8BB" if tema_oscuro else "#667085",
        "subtle": "#AEB8C9" if tema_oscuro else "#536176",
        "line": "rgba(145,164,190,.18)" if tema_oscuro else "rgba(45,65,90,.15)",
        "accent": "#42D6A4" if tema_oscuro else "#0B9F78",
        "accent_soft": "rgba(66,214,164,.07)" if tema_oscuro else "rgba(11,159,120,.08)",
    }
    tokens_tema = f"""
        <style>
        :root {{
          --app-bg:{paleta['app']}; --sidebar-bg:{paleta['sidebar']};
          --surface:{paleta['surface']}; --surface-soft:{paleta['surface_soft']};
          --text:{paleta['text']}; --muted:{paleta['muted']}; --subtle:{paleta['subtle']};
          --line:{paleta['line']}; --accent:{paleta['accent']}; --accent-soft:{paleta['accent_soft']};
        }}
    """
    st.markdown(
        tokens_tema
        + """
        html, body, [data-testid="stAppViewContainer"] {overflow: hidden;}
        [data-testid="stAppViewContainer"], .stApp {background:var(--app-bg); color:var(--text);}
        [data-testid="stHeader"], [data-testid="stToolbar"] {display:none !important;}
        [data-testid="stAppViewContainer"] > .main {height:100vh; overflow:hidden;}
        [data-testid="stToolbarActions"], [data-testid="stMainMenu"],
        [data-testid="stAppDeployButton"] {display:none;}
        [data-testid="stElementContainer"]:has(style) {display:none;}
        .block-container {padding:.65rem 1.4rem .75rem; max-width:none; height:100vh; overflow:hidden;}
        [data-testid="stSidebar"] {min-width:350px; max-width:350px; border-right:1px solid var(--line); background:var(--sidebar-bg); color:var(--text);}
        [data-testid="stSidebarHeader"] {display:none !important;}
        [data-testid="stSidebarContent"] {padding-top:0 !important;}
        [data-testid="stSidebarUserContent"] {padding-top:.65rem !important;}
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap:.48rem;}
        [data-testid="stSidebar"] .stImage {margin:0;}
        [data-testid="stSidebar"] .stImage img {width:100%; height:50px; object-fit:contain; border-radius:.55rem; background:#10131a; border:1px solid var(--line);}
        [data-testid="stSidebar"] h1 {font-size:1.42rem; margin:0; letter-spacing:-.02em; color:var(--text);}
        [data-testid="stSidebar"] h3 {font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; color:#aeb8c9; margin:.25rem 0 0;}
        [data-testid="stSidebar"] p, [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {color:var(--text);}
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {font-size:.76rem; margin-bottom:.1rem;}
        [data-testid="stSidebar"] .stSelectbox, [data-testid="stSidebar"] .stFileUploader,
        [data-testid="stSidebar"] .stMultiSelect, [data-testid="stSidebar"] .stTextInput,
        [data-testid="stSidebar"] .stNumberInput {margin-bottom:-.15rem;}
        [data-testid="stSidebar"] [data-testid="stExpander"] {border:1px solid var(--line); border-radius:.55rem; background:var(--surface);}
        [data-testid="stSidebar"] [data-baseweb="select"] > div,
        [data-testid="stSidebar"] [data-baseweb="input"] > div {background:var(--surface-soft); color:var(--text); border-color:var(--line);}
        [data-testid="stSidebar"] .stMultiSelect .react-aria-ComboBox > div {background:var(--surface-soft) !important; border-color:var(--line) !important;}
        [data-testid="stSidebar"] .stMultiSelect input {background:transparent !important; color:var(--text) !important;}
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {background:var(--surface-soft); border-color:var(--line);}
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {padding:.55rem; min-height:0;}
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] > div > span {font-size:.72rem;}
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] > div > small {display:none;}
        [data-testid="stSidebar"] [data-baseweb="tab-list"] {gap:.22rem;}
        [data-testid="stSidebar"] button[data-baseweb="tab"] {height:2.35rem; padding:.2rem .45rem; font-size:.72rem;}
        [data-testid="stMetric"] {background:var(--surface); border:1px solid var(--line); padding:.55rem .75rem; border-radius:.65rem;}
        [data-testid="stMetric"] * {color:var(--text);}
        [data-testid="stMetricLabel"] {font-size:.72rem;}
        [data-testid="stMetricValue"] {font-size:1.35rem;}
        .sidebar-lead {font-size:.78rem; color:var(--muted) !important; margin:0 0 .2rem;}
        .section-label {display:flex; gap:.55rem; align-items:center; font-size:.84rem; font-weight:750; text-transform:uppercase; letter-spacing:.085em; color:var(--subtle); margin:.8rem 0 .38rem;}
        .section-icon {color:var(--accent); font-size:1.02rem; width:1.1rem; text-align:center;}
        .analysis-help {font-size:.72rem; color:var(--muted) !important; margin:.25rem 0 .25rem; line-height:1.35;}
        .result-title {font-size:1.3rem; font-weight:700; color:var(--text); letter-spacing:-.02em; margin:.1rem 0 0;}
        .empty-state {height:calc(100vh - 6.4rem); display:flex; flex-direction:column; align-items:center; justify-content:center; border:1px dashed var(--line); border-radius:.9rem; background:radial-gradient(circle at 50% 42%, var(--accent-soft), transparent 31%), var(--surface-soft); text-align:center;}
        .empty-icon {color:var(--accent); font-size:3.4rem; line-height:1;}
        .empty-state h2 {font-size:1.25rem; color:var(--text); margin:.7rem 0 .25rem;}
        .empty-state p {font-size:.83rem; color:var(--muted); max-width:430px; margin:0;}
        .empty-steps {display:flex; gap:.65rem; margin-top:1rem;}
        .empty-steps span {font-size:.7rem; color:var(--subtle); background:var(--surface); border:1px solid var(--line); border-radius:1rem; padding:.3rem .65rem;}
        [data-testid="stSidebar"] [role="radiogroup"] {display:grid; grid-template-columns:1fr 1fr; gap:.35rem; width:100%;}
        [data-testid="stSidebar"] [role="radiogroup"] button {width:100%; min-height:2.15rem; border:1px solid var(--line); background:var(--surface-soft); color:var(--text);}
        [data-testid="stSidebar"] [role="radiogroup"] button[aria-checked="true"] {background:var(--accent); color:white; border-color:var(--accent);}
        .st-key-theme_toggle button {min-height:2.1rem; padding:.25rem .55rem; border:1px solid var(--line); background:var(--surface); color:var(--text); white-space:nowrap;}
        .stTabs [data-baseweb="tab-list"] {gap:.35rem;}
        .stTabs [data-testid="stTab"] {height:2.45rem; font-size:.78rem; color:var(--muted) !important; opacity:1 !important;}
        .stTabs [data-testid="stTab"] * {color:inherit !important; opacity:1 !important;}
        .stTabs [data-testid="stTab"][aria-selected="true"] {color:var(--accent) !important;}
        .stTabs [data-baseweb="tab-highlight"] {background:var(--accent) !important;}
        .stTabs [data-testid="stTabPanel"] {padding-top:.55rem; height:calc(100vh - 18rem); overflow:hidden;}
        .stDownloadButton button {background:var(--surface) !important; color:var(--text) !important; border:1px solid var(--line) !important; box-shadow:none !important;}
        .stDownloadButton button:hover {background:var(--accent-soft) !important; color:var(--accent) !important; border-color:var(--accent) !important;}
        .stDownloadButton button * {color:inherit !important; opacity:1 !important;}
        .download-cue {width:2.15rem; height:2.15rem; display:flex; align-items:center; justify-content:center; color:var(--accent); background:var(--accent-soft); border:1px solid var(--line); border-radius:.55rem; font-size:1.25rem; font-weight:700;}
        [data-testid="stDataFrame"], [data-testid="stCode"] {background:var(--surface); border:1px solid var(--line); border-radius:.55rem;}
        div[data-testid="stImage"] img {max-height:calc(100vh - 19rem); width:100%; object-fit:contain; object-position:top center;}
        iframe[data-testid="stIFrame"] {height:calc(100vh - 19rem) !important; min-height:320px;}
        .credits {margin-top:.25rem; padding:.58rem .1rem 0; border-top:1px solid var(--line); font-size:.67rem; color:var(--muted); line-height:1.4;}
        .credits strong {color:var(--text); font-size:.7rem;}
        .credits a {color:var(--accent); text-decoration:none; margin-right:.55rem; font-weight:650;}
        .credits a:hover {text-decoration:underline;}
        .credits-license {display:block; margin-top:.16rem; color:var(--muted);}
        </style>
        """,
        unsafe_allow_html=True,
    )
    carpeta = _inicializar_sesion()

    with st.sidebar:
        marca, tema = st.columns([2.25, 0.9], vertical_alignment="center")
        with marca:
            st.image(RAIZ / "image" / "logo_flowmaps.png")
        with tema:
            etiqueta_tema = "☀ Light" if tema_oscuro else "☾ Dark"
            if st.button(
                etiqueta_tema,
                key="theme_toggle",
                help="Cambiar el tema de la interfaz",
                width="stretch",
            ):
                st.session_state.ui_theme = "light" if tema_oscuro else "dark"
                st.rerun()
        st.markdown(
            '<p class="sidebar-lead">Configura el análisis y genera tus mapas.</p>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="section-label"><span class="section-icon">⇄</span>Tipo de análisis</div>',
            unsafe_allow_html=True,
        )
        etiqueta_escenario = st.segmented_control(
            "Tipo de análisis",
            tuple(ESCENARIOS),
            default="OD definidos",
            selection_mode="single",
            width="stretch",
            label_visibility="collapsed",
        )
        escenario = ESCENARIOS[etiqueta_escenario]
        st.markdown(
            f'<p class="analysis-help">{DESCRIPCIONES_ESCENARIO[escenario]}</p>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="section-label"><span class="section-icon">⇩</span>Datos de entrada</div>',
            unsafe_allow_html=True,
        )
        argumentos_ingesta, errores, extremos_unicos = _configurar_datos(escenario, carpeta)

        with st.expander("⌁ Restricciones · opcional"):
            ruta_restriccion, vista_restriccion = _archivo_cargado(
                "Polígonos de exclusión", "restricciones", carpeta, FORMATOS_RESTRICCION
            )
            st.caption("SHP o GDB: carga un ZIP con sus componentes.")
            _mostrar_vista("restricciones", vista_restriccion)

        st.markdown(
            '<div class="section-label"><span class="section-icon">⇧</span>Salida</div>',
            unsafe_allow_html=True,
        )
        formatos = st.multiselect(
            "Entregables",
            ("PNG", "HTML", "GeoJSON"),
            default=("PNG", "HTML", "GeoJSON"),
            label_visibility="collapsed",
        )

        with st.expander("⚙ Ajustes avanzados"):
            general, trazado, apariencia = st.tabs(["General", "Trazado", "Estilo"])
            with general:
                titulo = st.text_input("Título del mapa", value="Mapa de flujos distributivos")
                if extremos_unicos["origen"] or extremos_unicos["destino"]:
                    st.caption("Nombres de los puntos únicos")
                if extremos_unicos["origen"]:
                    nombre_origen_unico = st.text_input(
                        "Nombre del origen único",
                        value="Origen",
                        key=f"nombre_origen_unico_{escenario}",
                    )
                else:
                    nombre_origen_unico = "Origen"
                if extremos_unicos["destino"]:
                    nombre_destino_unico = st.text_input(
                        "Nombre del destino único",
                        value="Destino",
                        key=f"nombre_destino_unico_{escenario}",
                    )
                else:
                    nombre_destino_unico = "Destino"
                crs = st.text_input("CRS", value="EPSG:4326")
                magnitud_default = st.number_input(
                    "Magnitud por defecto", min_value=0.01, value=1.0, step=1.0
                )
                metodo_proximidad = st.selectbox(
                    "Método de proximidad",
                    ("balltree", "kdtree", "sjoin"),
                    disabled=escenario != "B",
                    help="Sólo se aplica al análisis de destino más cercano.",
                )
            with trazado:
                resolucion = st.slider("Resolución de malla", 30, 200, 80, 10)
                iteraciones = st.slider("Bundling", 0, 8, 4)
                factor_atraccion = st.slider("Atracción", 0.0, 0.9, 0.65, 0.05)
                suavizado = st.slider("Suavizado", 0, 6, 3)
                buffer_restriccion = st.number_input(
                    "Buffer de restricción", min_value=0.0, value=0.0, format="%.6f"
                )
            with apariencia:
                colormap = st.selectbox(
                    "Paleta de flujos", ("RdYlBu", "YlOrRd", "plasma", "inferno", "viridis")
                )
                fondo = st.color_picker("Fondo del PNG", "#1a1a2e")
                tiles = st.selectbox(
                    "Mapa base HTML",
                    ("Esri Dark Gray", "CartoDB positron", "OpenStreetMap"),
                )
                zoom_etiquetas = st.slider("Zoom de etiquetas", 1, 20, 13)
                dpi = st.slider("Resolución PNG (DPI)", 100, 300, 200, 25)
                mostrar_etiquetas = st.toggle("Etiquetas en PNG", value=True)
                dibujar_restricciones = st.toggle("Dibujar restricciones", value=False)

        if escenario == "B":
            argumentos_ingesta["metodo_proximidad"] = metodo_proximidad
        elif escenario == "A1":
            argumentos_ingesta["etiqueta_destino_fijo"] = nombre_destino_unico.strip() or "Destino"
        elif escenario == "A2":
            argumentos_ingesta["etiqueta_origen_fijo"] = nombre_origen_unico.strip() or "Origen"

        if not formatos:
            errores.append("Selecciona por lo menos un entregable.")
        for error in errores:
            st.warning(error)

        ejecutar = st.button(
            "▶  Ejecutar FlowMaps",
            type="primary",
            width="stretch",
            disabled=bool(errores),
        )
        st.markdown(
            """
            <div class="credits">
              <strong>© 2026 Carlos Enrique Vázquez Juárez</strong><br>
              <a href="https://github.com/carlos-enrique-vj/" target="_blank">GitHub ↗</a>
              <a href="https://www.linkedin.com/in/carlos-enrique-vj/" target="_blank">LinkedIn ↗</a>
              <a href="https://carlos-enrique.carto.mx/" target="_blank">Portafolio ↗</a>
              <span class="credits-license">MIT · Libre uso con atribución. Conserva autoría y fuente.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if ejecutar:
        nombre_base = _nombre_entrada(argumentos_ingesta, escenario)
        prefijo = normalizar_prefijo(nombre_base)
        salida = carpeta / "salidas" / f"{prefijo}_{time.time_ns()}"
        salida.mkdir(parents=True, exist_ok=True)
        argumentos_ingesta.update(crs=crs, magnitud_default=magnitud_default)

        config = FlowMapConfig(
            prefijo_proyecto=prefijo,
            nombre_destino=(
                nombre_destino_unico.strip() or "Destino"
                if extremos_unicos["destino"]
                else "Destino"
            ),
            directorio_salida=str(salida),
            archivo_restricciones=str(ruta_restriccion) if ruta_restriccion else None,
            crs=crs,
            resolucion_grafo=resolucion,
            conexion_diagonal=True,
            buffer_restriccion=buffer_restriccion,
            dibujar_restricciones=dibujar_restricciones,
            iteraciones_bundling=iteraciones,
            factor_atraccion=factor_atraccion,
            suavizado_iteraciones=suavizado,
            grosor_min=0.4,
            grosor_max=14.0,
            colormap=colormap,
            fondo_color=fondo,
            titulo=titulo,
            mostrar_etiquetas=mostrar_etiquetas,
            guardar_como="mapa_flujos.png" if "PNG" in formatos else None,
            dpi=dpi,
            html_salida="mapa_flujos.html" if "HTML" in formatos else None,
            tiles=tiles,
            zoom_min_etiquetas=zoom_etiquetas,
        )

        registro = io.StringIO()
        inicio = time.perf_counter()
        try:
            with st.spinner("Calculando rutas y generando entregables…"):
                with contextlib.redirect_stdout(registro), contextlib.redirect_stderr(registro):
                    flujos = preparar_flujos(**argumentos_ingesta)
                    if extremos_unicos["origen"]:
                        flujos["etiqueta"] = nombre_origen_unico.strip() or "Origen"
                    if extremos_unicos["destino"]:
                        flujos["etiqueta_destino"] = (
                            nombre_destino_unico.strip() or "Destino"
                        )
                    resultados = ejecutar_pipeline(
                        config,
                        mostrar_matplotlib="PNG" in formatos,
                        generar_html="HTML" in formatos,
                        flujos_precargados=flujos,
                        exportar_geojson="GeoJSON" in formatos,
                    )

            artefactos = {}
            for clave, ruta_clave, modo in (
                ("png", "png_path", "bytes"),
                ("html", "html_path", "text"),
                ("geojson", "geojson_path", "bytes"),
            ):
                ruta = resultados.get(ruta_clave)
                if not ruta:
                    continue
                archivo = Path(ruta)
                datos = archivo.read_bytes()
                artefactos[clave] = {"nombre": archivo.name, "datos": datos}
                if modo == "text":
                    artefactos[clave]["texto"] = datos.decode("utf-8")

            if resultados.get("fig") is not None:
                plt.close(resultados["fig"])

            st.session_state.flowmaps_last_run = {
                "escenario": etiqueta_escenario,
                "pares": len(flujos),
                "rutas": len(resultados.get("rutas", [])),
                "cauces": len(resultados.get("polylineas", [])),
                "segundos": time.perf_counter() - inicio,
                "artefactos": artefactos,
                "registro": registro.getvalue(),
            }
            st.toast("FlowMaps terminó correctamente")
        except Exception as exc:
            st.error(f"La ejecución no pudo completarse: {exc}")
            with st.expander("Detalle técnico"):
                st.code(registro.getvalue() + "\n" + traceback.format_exc(), language="text")

    if "flowmaps_last_run" in st.session_state:
        _mostrar_resultados(st.session_state.flowmaps_last_run)
    else:
        _panel_vacio()


if __name__ == "__main__":
    main()
