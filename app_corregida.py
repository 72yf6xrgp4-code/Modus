"""
app_corregida.py - Punto de entrada de Modus Super Series App.

Configura la pagina, inicializa el estado de sesion y construye la interfaz
principal (barra lateral + las tres secciones: LIVE, VALUE BETS y RESULTADOS).

La logica esta repartida en modulos:
  - config.py         constantes y configuracion
  - helpers.py        utilidades de bajo nivel
  - data_loading.py   carga y parsing de Google Sheets
  - stats_engine.py   modelo matematico y simulacion
  - rendering.py      renderizado visual
  - clasificacion.py  tablas de clasificacion

Para que Streamlit Cloud lo despliegue, este archivo sigue siendo el main.
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
import html as html_mod
from datetime import datetime, timedelta

st.set_page_config(page_title="Modus Super Series App", layout="wide", page_icon="🎯")

# CSS global: rejilla de estadísticas responsive
# Desktop/tablet: 4 columnas | Móvil (<=768px): 2 columnas
st.markdown("""
<style>
.stats-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin: 10px 0 20px 0;
}
/* Menos hueco arriba y titulos que no ocupen dos lineas en el movil */
.block-container { padding-top: 3.9rem; }
/* Los bloques que solo cargan estilos no ocupan sitio (cada uno metia un hueco) */
[data-testid=stElementContainer]:has([data-testid=stMarkdownContainer] > style:only-child){display:none}
.block-container h1{padding-top:.25rem!important}
@media (max-width: 768px) {
    .block-container { padding-top: 3.9rem; padding-left: 1rem; padding-right: 1rem; }
    h1 { font-size: 1.75rem !important; }
    h2 { font-size: 1.4rem !important; }
    h3 { font-size: 1.2rem !important; }
}
@media (max-width: 768px) {
    .stats-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
    }
}
</style>
""", unsafe_allow_html=True)


# ---- Imports de los modulos de la app ----
from config import URLS, CORTES
from data_loading import cargar_todo, get_jornada_actual, get_proxima_jornada
from helpers import pintar_partidos, es_admin, render_acceso_admin
from rendering import (
    render_jugador_visual, render_value_bets, render_small_multiples,
    render_tarjetas_jugadores,
    selector_jornada, render_tracking_predicciones, render_historico,
)
from clasificacion import (
    detectar_grupo, construir_grupos_final,
    render_clasificacion_grupo, render_clasificacion_final,
)


# ---- Inicializacion del estado de sesion ----
if "vb_fuente" not in st.session_state:
    st.session_state.vb_fuente = "Resumen Semanal"
if "vb_j1" not in st.session_state:
    st.session_state.vb_j1 = None
if "vb_j2" not in st.session_state:
    st.session_state.vb_j2 = None
if "vb_calcular" not in st.session_state:
    st.session_state.vb_calcular = False
if "last_update" not in st.session_state:
    st.session_state.last_update = {}


# ── Barra lateral: marca, estado de la jornada y herramientas ──────────────
st.sidebar.markdown(
    "<div class='sb-marca'><span class='sb-logo'>🎯</span>Modus Super Series</div>",
    unsafe_allow_html=True)

# Estado del torneo en este momento (en juego / esperando datos / proxima
# jornada con cuenta atras). Si la deteccion falla, no se muestra nada.
try:
    from data_loading import estado_jornada_sidebar as _est
    from rendering import calcular_tiempo_restante as _faltan
    _e = _est()
    _esc = lambda x: html_mod.escape(str(x or ""))
    if _e["estado"] == "ACTIVA":
        _html_estado = (
            "<div class='sb-estado'><div class='sb-k'>"
            "<span class='sb-dot on'></span>En juego</div>"
            f"<div class='sb-j'>{_esc(_e['jornada'])}</div></div>")
    elif _e["estado"] == "PENDIENTE":
        _html_estado = (
            "<div class='sb-estado'><div class='sb-k'>"
            "<span class='sb-dot wait'></span>Hoy · esperando datos</div>"
            f"<div class='sb-j'>{_esc(_e['jornada'])}</div>"
            "<div class='sb-h'>El Sheet aún no tiene los partidos</div></div>")
    else:  # SIN_JORNADA
        _rest = _faltan(_e.get("proxima_dia"), _e.get("proxima_hora"))
        _html_estado = (
            "<div class='sb-estado'><div class='sb-k'>"
            "<span class='sb-dot'></span>Próxima jornada</div>"
            f"<div class='sb-j'>{_esc(_e.get('proxima_nombre'))}</div>"
            f"<div class='sb-h'>{_esc(_e.get('proxima_dia'))} · "
            f"{_esc(_e.get('proxima_hora'))}</div>"
            + (f"<span class='sb-falta'>Faltan {_esc(_rest)}</span>" if _rest else "")
            + "</div>")
    st.sidebar.markdown(_html_estado, unsafe_allow_html=True)
except Exception:
    pass

# ── Menu de secciones: barra de botones arriba del todo ──────────────────
# Antes era un radio en la barra lateral: en el movil la barra tapaba la
# pagina y habia que cerrarla a mano cada vez. Ahora el menu va en la
# pagina, siempre visible. La barra lateral queda para el estado de la
# jornada, el refresco y el modo administrador.
SECCIONES = ["🔴 LIVE", "💰 VALUE BETS", "📊 RESULTADOS Y ESTADÍSTICAS",
             "📈 SEGUIMIENTO", "📚 HISTÓRICO", "🔔 ALERTAS"]
# Etiquetas del menu: iconos sencillos (Material) en vez de emojis
_MENU = {"🔴 LIVE": ":material/sensors: Live",
         "💰 VALUE BETS": ":material/payments: Value Bets",
         "📊 RESULTADOS Y ESTADÍSTICAS": ":material/leaderboard: Resultados",
         "📈 SEGUIMIENTO": ":material/monitoring: Seguimiento",
         "📚 HISTÓRICO": ":material/history: Histórico",
         "🔔 ALERTAS": ":material/notifications: Alertas"}
# Enlaces del aviso del vigia y del boton "Modus value" (?seccion=value...)
from cuotas_url import aplicar_parametros_url
aplicar_parametros_url()
if st.session_state.get("seccion") not in SECCIONES:
    st.session_state["seccion"] = st.session_state.get("_ultima_seccion", SECCIONES[0])
opcion_principal = st.segmented_control(
    "Sección", SECCIONES, format_func=_MENU.get, key="seccion",
    label_visibility="collapsed",
)
# Pulsar la seccion ya activa la deselecciona: nos quedamos en la misma
if not opcion_principal:
    opcion_principal = st.session_state.get("_ultima_seccion", SECCIONES[0])
st.session_state["_ultima_seccion"] = opcion_principal

# Aspecto del menu: pildoras arriba, fijas al bajar por la pagina. En el movil,
# barra flotante abajo con las 5 secciones (icono encima del nombre) y la activa
# en una pildora roja.
st.markdown("""
<style>
[data-testid=stHeader]{background:#fff}
.st-key-seccion{width:100%!important;position:sticky;top:3.75rem;z-index:990;
  background:#fff;padding:.35rem 0 .55rem;margin-bottom:.25rem}
.st-key-seccion [data-testid=stButtonGroup]{width:100%}
.st-key-seccion [role=radiogroup]{display:flex;flex-wrap:nowrap;gap:.5rem;
  max-width:none!important;width:100%;overflow-x:auto;scrollbar-width:none}
.st-key-seccion [role=radiogroup]::-webkit-scrollbar{display:none}
.st-key-seccion button[role=radio]{flex:0 0 auto;border-radius:999px!important;
  border:1px solid #e2e8f0!important;background:#f8fafc!important;
  color:#334155!important;padding:.45rem 1.05rem!important;box-shadow:none!important}
.st-key-seccion button[role=radio] p{font-weight:600;white-space:nowrap}
.st-key-seccion button[role=radio] [data-testid=stIconMaterial]{font-size:1.2rem}
.st-key-seccion button[aria-checked=true]{background:#ff4b4b!important;
  border-color:#ff4b4b!important;color:#fff!important;
  box-shadow:0 3px 8px rgba(255,75,75,.30)!important}
@media (hover:hover){
  .st-key-seccion button[aria-checked=false]:hover{border-color:#cbd5e1!important;
    background:#f1f5f9!important}
}
/* ── Barra lateral ── */
.sb-marca{display:flex;align-items:center;gap:.5rem;font-weight:800;font-size:1.12rem;
  color:#0f172a;white-space:nowrap;letter-spacing:-.01em;margin:.1rem 0 .9rem}
.sb-logo{font-size:1.35rem}
.sb-estado{background:#fff;border:1px solid #e2e8f0;border-radius:14px;
  padding:.8rem .9rem;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.sb-k{display:flex;align-items:center;gap:.45rem;font-size:.68rem;font-weight:700;
  letter-spacing:.08em;text-transform:uppercase;color:#64748b}
.sb-dot{width:8px;height:8px;border-radius:50%;background:#94a3b8;flex:0 0 auto}
.sb-dot.on{background:#22c55e;box-shadow:0 0 0 3px rgba(34,197,94,.18)}
.sb-dot.wait{background:#f59e0b;box-shadow:0 0 0 3px rgba(245,158,11,.18)}
.sb-j{font-weight:700;font-size:1.02rem;color:#0f172a;margin-top:.3rem}
.sb-h{font-size:.84rem;color:#475569;margin-top:.1rem}
.sb-falta{display:inline-block;margin-top:.6rem;background:#fff1f1;color:#e11d48;
  font-weight:700;font-size:.78rem;border-radius:999px;padding:.18rem .65rem}
.sb-etq{font-size:.68rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  color:#94a3b8;margin:1.1rem 0 0!important}
/* botones de la barra a todo el ancho con CSS (el parametro width= de
   st.button no existe antes de Streamlit 1.47) */
.st-key-sb_refrescar,.st-key-sb_script{width:100%!important}
.st-key-sb_refrescar [data-testid=stButton],.st-key-sb_script [data-testid=stButton],
.st-key-sb_refrescar button,.st-key-sb_script button{width:100%}
/* ── Tarjetas de jugadores: toda la informacion a la vista, sin desplegable ── */
[class*="st-key-pcard_"]{border-radius:16px!important;border-color:#e2e8f0!important;
  background:#fff;padding:.85rem .95rem .9rem!important;gap:.35rem!important}
.pc-top{display:flex;align-items:center;gap:.6rem}
.pc-pos{width:1.65rem;height:1.65rem;border-radius:50%;background:#f1f5f9;color:#475569;
  font-weight:700;font-size:.8rem;display:flex;align-items:center;justify-content:center;
  flex:0 0 auto}
.pc-pos.top1{background:#fef3c7;color:#92400e}
.pc-nom{font-weight:700;font-size:1.02rem;color:#0f172a;flex:1 1 auto;min-width:0;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pc-pr{font-weight:800;font-size:.95rem;border-radius:999px;padding:.15rem .6rem;
  flex:0 0 auto;white-space:nowrap}
.pc-pr small{font-weight:700;font-size:.62rem;opacity:.7;margin-left:.25rem}
.pr-alto{background:#dcfce7;color:#166534}.pr-medio{background:#ecfccb;color:#3f6212}
.pr-bajo{background:#fef3c7;color:#92400e}.pr-muybajo{background:#fee2e2;color:#991b1b}
.pr-nd{background:#f1f5f9;color:#94a3b8}
/* dos filas de 4: promedio, 180s, checkout, V-D / legs, dif. legs,
   volatilidad, ultimos partidos */
.pc-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.35rem;
  margin-top:.7rem}
.pc-stats div{background:#f8fafc;border-radius:10px;padding:.45rem .15rem;text-align:center;
  min-width:0}
.pc-stats b{display:block;font-size:1rem;line-height:1.5rem;color:#0f172a;white-space:nowrap}
.pc-stats span{display:block;font-size:.66rem;color:#64748b;margin-top:1px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* flecha frente a la semana (jornadas diarias) y marca "sem" (dato de la
   semana porque el Sheet aun no lo tiene en la jornada) */
.pc-stats b i,.pc-pr i{font-style:normal;font-size:.75rem;font-weight:800;margin-left:1px;
  line-height:1}
.tu{color:#16a34a}.td{color:#dc2626}
.pc-stats b small{font-size:.58rem;font-weight:600;color:#94a3b8;margin-left:2px;line-height:1}
.pc-stats .pos{color:#15803d}.pc-stats .neg{color:#dc2626}
.v-bajo{color:#16a34a!important}.v-medio{color:#ca8a04!important}.v-alto{color:#dc2626!important}
/* ultimos partidos: un punto por partido, verde victoria y rojo derrota */
.pc-stats .pc-dots{display:inline-flex;gap:4px;align-items:center;height:1.5rem;
  vertical-align:top;overflow:visible;margin:0}
.pc-dots i{width:9px;height:9px;border-radius:50%;background:#22c55e;display:block}
.pc-dots i.l{background:#ef4444}
.pc-vacio{margin-top:.6rem;font-size:.85rem;color:#94a3b8}
/* misma separacion entre tarjetas en horizontal y en vertical (tambien
   apiladas en el movil) */
[data-testid=stHorizontalBlock]:has([class*="st-key-pcard_"]){gap:1rem!important}
/* st.markdown resta 1rem por debajo (pensado para el margen de los <p>);
   en estos bloques propios montaba la etiqueta sobre lo que tiene debajo */
[data-testid=stMarkdownContainer]:has(.pc),
[data-testid=stMarkdownContainer]:has(.modus-etq){margin-bottom:0!important}
[data-testid=stMarkdownContainer]:has(.sb-etq){margin-bottom:-.55rem!important}
/* ── Selector de jornada (Resultados y Value Bets) ── */
.st-key-res_jornada{background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;
  padding:.8rem 1rem .35rem;gap:.55rem!important;margin-bottom:.4rem}
.modus-etq{font-size:.72rem;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;color:#64748b;margin:0}
/* Grupos: control segmentado en una sola fila, el activo en blanco */
[class*="_seg_grupo_"]{width:100%!important}
[class*="_seg_grupo_"] [data-testid=stButtonGroup]{width:100%}
[class*="_seg_grupo_"] [role=radiogroup]{display:flex;flex-wrap:nowrap;width:100%;
  max-width:none!important;gap:2px;background:#e8edf4;border-radius:12px;padding:3px}
[class*="_seg_grupo_"] button[role=radio]{flex:1 1 0;min-width:0;border:0!important;
  border-radius:10px!important;background:transparent!important;color:#475569!important;
  padding:.42rem .2rem!important;box-shadow:none!important;min-height:2.4rem}
[class*="_seg_grupo_"] button[role=radio] p{font-weight:600;white-space:nowrap}
[class*="_seg_grupo_"] button[aria-checked=true]{background:#fff!important;
  color:#0f172a!important;box-shadow:0 1px 3px rgba(15,23,42,.18)!important}
[class*="_seg_grupo_"] button[aria-checked=true] [data-testid=stIconMaterial]{color:#f59e0b}
/* Dias: pestanas con linea roja en el activo */
[class*="_seg_dia_"]{width:100%!important}
[class*="_seg_dia_"] [role=radiogroup]{display:flex;gap:1.25rem;max-width:none!important;
  width:100%;border-bottom:1px solid #e2e8f0}
[class*="_seg_dia_"] button[role=radio]{border:0!important;border-radius:0!important;
  background:transparent!important;box-shadow:none!important;min-height:2.2rem;
  padding:.3rem .1rem!important;border-bottom:2px solid transparent!important;
  margin-bottom:-1px;color:#64748b!important}
[class*="_seg_dia_"] button[aria-checked=true]{color:#ff4b4b!important;
  border-bottom-color:#ff4b4b!important}
[class*="_seg_dia_"] button[aria-checked=true] p{font-weight:700}
@media (hover:hover){
  [class*="_seg_grupo_"] button[aria-checked=false]:hover{color:#0f172a!important;
    background:rgba(255,255,255,.55)!important}
  [class*="_seg_dia_"] button[aria-checked=false]:hover{color:#0f172a!important}
}
@media (max-width:640px){
  .st-key-res_jornada{padding:.7rem .7rem .3rem}
  [class*="_seg_grupo_"] button[role=radio] p{font-size:.8rem}
}
@media (max-width:640px){
  /* En el movil, barra flotante abajo, elevada por encima de los botones de
     Streamlit Cloud de la esquina inferior derecha (pegada al borde quedaba
     tapada por ellos). */
  .st-key-seccion{position:fixed!important;left:.6rem;right:.6rem;top:auto!important;
    bottom:3.75rem;width:auto!important;max-width:none!important;
    z-index:999990;margin:0!important;padding:.3rem!important;border-radius:22px;
    border:1px solid #e5e7eb;box-shadow:0 10px 30px rgba(15,23,42,.18);
    background:rgba(255,255,255,.97)}
  .st-key-seccion [role=radiogroup]{gap:.2rem;overflow:visible}
  .st-key-seccion button[role=radio]{flex:1 1 0;min-width:0;height:auto!important;
    min-height:3.1rem;padding:.3rem 0!important;border:0!important;
    background:transparent!important;color:#64748b!important;overflow:visible!important}
  .st-key-seccion button[role=radio] span[data-has-shortcut]{flex-direction:column;gap:1px}
  .st-key-seccion button[role=radio] p{font-size:.68rem}
  .st-key-seccion button[aria-checked=true]{background:#ff4b4b!important;
    color:#fff!important;border-radius:16px!important;
    box-shadow:0 3px 8px rgba(255,75,75,.30)!important}
  /* hueco al final para que la barra no tape lo ultimo de la pagina */
  .block-container{padding-bottom:9rem!important}
}
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("<p class='sb-etq'>Datos</p>", unsafe_allow_html=True)
if st.sidebar.button("Refrescar datos", icon=":material/refresh:",
                     key="sb_refrescar",
                     help="Recarga ya los datos del Sheet"):
    st.cache_data.clear()
    st.session_state.last_update = {}
    st.rerun()
st.sidebar.caption("Se refrescan al navegar, cada 30 s.")

render_acceso_admin()

SCRIPT_URL = "https://script.google.com/macros/s/AKfycbyF0-GxHiaX4NW55-2UJt39a9V_aJhGXahq5NL5z2szpbFd7RdtKtr5ww7r852RAm2f/exec"

if es_admin() and st.sidebar.button(
        "Ejecutar actualización", icon=":material/play_arrow:",
        key="sb_script",
        help="Lanza el script de Google que actualiza los datos del Sheet"):
    with st.sidebar.spinner("🔄 Ejecutando script..."):
        try:
            # Intentar con GET primero (más compatible con Apps Script)
            response = requests.get(SCRIPT_URL, timeout=120)
            if response.status_code == 200:
                st.sidebar.success("✅ Script ejecutado correctamente")
                st.sidebar.info("📊 Los datos se actualizarán en breve...")
                st.balloons()
                time.sleep(2)
                st.cache_data.clear()
                st.session_state.last_update = {}
                st.rerun()
            else:
                st.sidebar.warning(f"⚠️ Respuesta HTTP {response.status_code}")
                st.sidebar.info("💡 El script podría estar ejecutándose. Intenta refrescar en 5 segundos.")
        except requests.exceptions.Timeout:
            st.sidebar.warning("⏱️ Tiempo de espera agotado (>120s)")
            st.sidebar.info("💡 El script está ejecutándose en segundo plano. Los datos se actualizarán en breve.")
        except requests.exceptions.ConnectionError:
            st.sidebar.error("🔗 Error de conexión")
            st.sidebar.error("Verifica tu conexión a internet y que el script sea público")
        except Exception as e:
            st.sidebar.error(f"❌ Error: {str(e)}")
            st.sidebar.info("📝 Verifica que el script esté publicado como web app")

if "🔴 LIVE" in opcion_principal:
    st.title("🔴 LIVE")
    jornada_actual, url_actual, es_activa = get_jornada_actual()

    # Cargar Resumen Semanal (lo usaremos para tendencias y, sobre todo,
    # para la clasificacion que SIEMPRE queremos mostrar abajo si tiene datos).
    stats_resumen_live = None
    try:
        _, stats_resumen_live = cargar_todo(
            URLS["Resumen Semanal"], "Resumen Semanal",
            CORTES.get("Resumen Semanal", 2))
    except Exception:
        stats_resumen_live = None

    # Determinar qué jornada cargar:
    # - Si la jornada esta activa por hora, esa es la que toca.
    # - Si no, intentamos cargar la PROXIMA — porque puede tener datos
    #   pre-cargados aunque la hora oficial aun no haya llegado.
    if es_activa and jornada_actual:
        selected = jornada_actual
        selected_url = url_actual
        mostrar_tendencias_live = True
        stats_resumen_para_render = stats_resumen_live
    else:
        selected, selected_url = get_proxima_jornada()
        mostrar_tendencias_live = False
        stats_resumen_para_render = None

    # Cargar los datos
    try:
        d1, d2 = cargar_todo(selected_url, selected, CORTES.get(selected, 2))
    except Exception:
        d1, d2 = None, None

    # Comprobacion de FRESCURA: si hay datos cargados pero no estamos en
    # hora oficial, hay que distinguir entre:
    #   (a) datos pre-cargados de la proxima jornada que SI vienen al caso
    #   (b) datos viejos del lunes pasado que el script aun no ha borrado
    #
    # El script de Sheets limpia los datos cada lunes ~02:00. Por tanto
    # los datos son "frescos" si:
    #   - Estamos en hora oficial de la jornada (es_activa = True), o
    #   - La proxima jornada empieza HOY (mismo dia natural), o
    #   - La proxima jornada empieza MAÑANA y ya pasamos el lunes 10:00
    #     de esta semana del torneo (los datos viejos ya estan limpios).
    def _datos_son_frescos():
        if es_activa:
            return True
        try:
            from zoneinfo import ZoneInfo
            ahora = datetime.now(ZoneInfo("Europe/Madrid"))
        except Exception:
            ahora = datetime.now()
        wd = ahora.weekday()
        h = ahora.hour
        try:
            from data_loading import proxima_jornada as _prox
            _, _, prox_dia = _prox()
        except Exception:
            prox_dia = None

        # Caso A: la proxima jornada empieza HOY -> frescos
        if prox_dia == "Hoy":
            return True
        # Caso B: domingo o lunes antes de las 03:00 -> NO frescos
        # (el script de Sheets limpia los lunes a las 02:00; antes de
        # esa hora los datos pre-cargados son los viejos del lunes pasado)
        if wd == 6:  # domingo
            return False
        if wd == 0 and h < 3:  # lunes madrugada antes de las 03:00
            return False
        # Resto: la limpieza del lunes ya paso, los datos pre-cargados
        # son de esta semana del torneo
        return True

    hay_datos = (d2 is not None and len(d2) > 0 and _datos_son_frescos())

    # Cuatro casos:
    #   1) Hay datos + hora oficial activa   -> tablas normales (success arriba)
    #   2) Hay datos + antes de hora oficial -> burbuja de proxima + tablas
    #   3) Sin datos + antes de hora oficial -> empty state grande
    #   4) Sin datos + hora oficial activa   -> empty state "esperando datos"

    if hay_datos:
        from rendering import (render_banner_proxima_jornada,
                                calcular_tiempo_restante)
        from data_loading import proxima_jornada

        if es_activa and jornada_actual:
            # Caso 1: jornada activa de verdad
            st.success(f"✅ Jornada activa: **{selected}** "
                       f"(datos en tiempo real)")
        else:
            # Caso 2: datos cargados pero antes del inicio oficial
            try:
                prox_nom, prox_hora, prox_dia = proxima_jornada()
            except Exception:
                prox_nom = prox_hora = prox_dia = None
            tiempo_rest = calcular_tiempo_restante(prox_dia, prox_hora)
            if prox_nom:
                render_banner_proxima_jornada(
                    prox_nom, prox_hora, prox_dia, tiempo_rest)

        st.markdown("---")

        if selected in st.session_state.last_update:
            tiempo = (datetime.now() - st.session_state.last_update[selected]).seconds
            st.caption(f"⏱️ Datos actualizados hace {tiempo} segundos")

        st.subheader("📈 Estadísticas por Jugador")
        render_tarjetas_jugadores(
            d2, stats_resumen_para_render, selected,
            mostrar_tendencias=mostrar_tendencias_live,
            jornada_racha=None if selected == "Resumen Semanal" else selected,
            key_prefix="pcard_live")

        if d1 is not None:
            st.subheader("⚔️ Detalles")
            if selected not in ["Resumen Semanal", "Value Bets"]:
                st.dataframe(d1.style.apply(pintar_partidos, axis=1),
                             use_container_width=True, hide_index=True)
            else:
                st.dataframe(d1, use_container_width=True, hide_index=True)

        st.markdown("---")
        render_small_multiples(d2, titulo="📊 Ranking por Métrica")
    else:
        # Casos 3 y 4: empty state grande
        from rendering import (render_empty_state_live,
                                calcular_tiempo_restante)
        from data_loading import proxima_jornada
        try:
            prox_nom, prox_hora, prox_dia = proxima_jornada()
        except Exception:
            prox_nom = prox_hora = prox_dia = None

        if es_activa and jornada_actual:
            # Caso 4: jornada activa pero sin datos
            titulo = f"Esperando datos de {selected}"
            motivo = ("La jornada está activa pero los datos del Sheet "
                      "todavía no se han cargado. Vuelve en unos minutos.")
        else:
            # Caso 3: ni datos ni jornada activa
            titulo = "Sin partidos en directo ahora mismo"
            motivo = "No hay jornada activa en este momento."

        tiempo_rest = calcular_tiempo_restante(prox_dia, prox_hora)
        render_empty_state_live(
            titulo_principal=titulo,
            proxima_nombre=prox_nom,
            proxima_hora=prox_hora,
            proxima_dia=prox_dia,
            tiempo_restante=tiempo_rest,
            motivo=motivo,
        )

    # ── Clasificacion del grupo (si tiene datos Y la semana esta limpia) ──
    # La clasificacion viene del Resumen Semanal, que durante el domingo y
    # las primeras horas del lunes aun tiene los datos de la semana
    # PASADA (no se limpian hasta el lunes a las 02:00). Por eso solo
    # la mostramos cuando _datos_son_frescos() — misma condicion que
    # las tablas de LIVE.
    if _datos_son_frescos():
        grupo_actual_live = detectar_grupo(selected)
        if grupo_actual_live:
            st.markdown("---")
            render_clasificacion_grupo(grupo_actual_live)
        elif selected == "Final Sábado":
            # En Final Sábado renderizamos los DOS grupos de la final (A y B),
            # compuestos según los rankings de la fase de grupos.
            grupos_final = construir_grupos_final()
            st.markdown("---")
            st.subheader("🏆 Grupos de la Final")
            for nombre_grupo, jugadores in grupos_final.items():
                render_clasificacion_final(nombre_grupo, jugadores)
                st.markdown("")
            # Cuadro de semifinales y final
            from clasificacion import render_bracket_final, render_campeon_semana
            render_bracket_final()
            # Campeon de la semana (solo si la final ha terminado)
            render_campeon_semana()
        elif selected == "Resumen Semanal":
            # En Resumen Semanal seguimos mostrando las 3 clasificaciones semanales
            st.markdown("---")
            st.subheader("🏆 Clasificaciones por Grupo")
            for g in ("Grupo A", "Grupo B", "Grupo C"):
                render_clasificacion_grupo(g)
                st.markdown("")

elif "💰 VALUE BETS" in opcion_principal:
    render_value_bets()

elif "📊 RESULTADOS Y ESTADÍSTICAS" in opcion_principal:
    st.title("📊 RESULTADOS Y ESTADÍSTICAS")
    # Selector de jornada en una tarjeta compacta (antes iba dentro de un
    # desplegable "Configuración" con titulo propio y una linea debajo)
    caja_jornada = st.container(key="res_jornada")
    with caja_jornada:
        st.markdown("<p class='modus-etq'>Jornada</p>", unsafe_allow_html=True)
        selected = selector_jornada("res", incluir_resumen=True,
                                    modo_forma_reciente=False)
    selected_url = URLS[selected]
    d1, d2 = cargar_todo(selected_url, selected, CORTES.get(selected, 2))

    if selected in st.session_state.last_update:
        tiempo = (datetime.now() - st.session_state.last_update[selected]).seconds
        with caja_jornada:
            st.caption(f":material/schedule: Datos actualizados hace {tiempo} s")
    
    # ¿Hay datos de jugadores en esta jornada?
    hay_datos = d2 is not None and len(d2) > 0

    if hay_datos:
        st.subheader("📈 Estadísticas por Jugador")

        # Cargar resumen semanal solo si estamos viendo otra jornada
        stats_resumen = None
        mostrar_tendencias = selected != "Resumen Semanal"
        if mostrar_tendencias:
            _, stats_resumen = cargar_todo(URLS["Resumen Semanal"], "Resumen Semanal", CORTES.get("Resumen Semanal", 2))

        render_tarjetas_jugadores(
            d2, stats_resumen, selected,
            mostrar_tendencias=mostrar_tendencias,
            jornada_racha=None if selected == "Resumen Semanal" else selected,
            key_prefix="pcard_res")

        if d1 is not None:
            st.subheader("⚔️ Detalles")
            if selected not in ["Resumen Semanal", "Value Bets"]:
                st.dataframe(d1.style.apply(pintar_partidos, axis=1), use_container_width=True, hide_index=True)
            else:
                st.dataframe(d1, use_container_width=True, hide_index=True)

        # Ranking por métrica
        if len(d2) > 0:
            st.markdown("---")
            render_small_multiples(d2, titulo="📊 Ranking por Métrica")
    else:
        # Estado vacío limpio: jornada sin datos todavia
        empty_html = (
            "<div style='background:linear-gradient(135deg,#f8fafc 0%,"
            "#ffffff 100%);border:1px dashed #cbd5e1;border-radius:16px;"
            "padding:48px 24px;text-align:center;margin:8px 0 4px;'>"
            "<div style='font-size:46px;margin-bottom:12px;'>📊</div>"
            "<div style='font-size:19px;font-weight:700;color:#475569;'>"
            "Aún no hay datos de esta jornada</div>"
            "<div style='font-size:14px;color:#94a3b8;margin-top:8px;'>"
            "Los jugadores aparecerán aquí cuando comiencen a jugarse "
            "los partidos.</div>"
            "</div>"
        )
        empty_compacto = " ".join(
            line.strip() for line in empty_html.splitlines() if line.strip()
        )
        st.markdown(empty_compacto, unsafe_allow_html=True)

    # Clasificación del grupo (al final del todo)
    grupo_actual = detectar_grupo(selected)
    if grupo_actual:
        st.markdown("---")
        render_clasificacion_grupo(grupo_actual)
    elif selected == "Final Sábado":
        # En Final Sábado renderizamos los DOS grupos de la final (A y B),
        # compuestos según los rankings de la fase de grupos.
        grupos_final = construir_grupos_final()
        st.markdown("---")
        st.subheader("🏆 Grupos de la Final")
        for nombre_grupo, jugadores in grupos_final.items():
            render_clasificacion_final(nombre_grupo, jugadores)
            st.markdown("")
        # Cuadro de semis/final + campeon (solo si la final ha terminado)
        from clasificacion import render_bracket_final, render_campeon_semana
        render_bracket_final()
        render_campeon_semana()
    elif selected == "Resumen Semanal":
        # En Resumen Semanal mostramos las 3 clasificaciones semanales completas
        st.markdown("---")
        st.subheader("🏆 Clasificaciones por Grupo")
        for g in ("Grupo A", "Grupo B", "Grupo C"):
            render_clasificacion_grupo(g)
            st.markdown("")


elif "📈 SEGUIMIENTO" in opcion_principal:
    st.title("📈 Seguimiento del modelo")
    render_tracking_predicciones()

elif "🔔 ALERTAS" in opcion_principal:
    st.title("🔔 Alertas")
    from alertas_ui import render_alertas
    render_alertas()

elif "📚 HISTÓRICO" in opcion_principal:
    st.title("📚 Histórico de jugadores")
    # Jugadores del Resumen Semanal para el boton de guardar la semana.
    try:
        from data_loading import cargar_jugadores_desde
        jugadores_resumen_hist = cargar_jugadores_desde("Resumen Semanal")
    except Exception:
        jugadores_resumen_hist = None
    try:
        from predicciones import cargar_historico
        df_hist = cargar_historico()
    except Exception as e:
        df_hist = None
        st.error(f"No se pudo cargar el histórico: {e}")
    render_historico(df_hist, jugadores_resumen_hist)

    # ── Top 10 histórico por PR medio ─────────────────────────────────────
    from rendering import render_top10_pr_historico
    render_top10_pr_historico(df_hist)

    # ── Lista de campeones de cada semana ─────────────────────────────────
    st.markdown("---")
    st.subheader("🏆 Campeones de la Semana")
    try:
        from predicciones import cargar_campeones
        campeones = cargar_campeones()
    except Exception:
        campeones = []
    if campeones:
        filas_html = ""
        for i, c in enumerate(campeones):
            medalla = "🥇" if i == 0 else "🏆"
            filas_html += (
                f"<div style='display:flex;align-items:center;gap:14px;"
                f"padding:10px 16px;border-bottom:1px solid #f1f5f9;'>"
                f"<span style='font-size:20px;'>{medalla}</span>"
                f"<span style='font-size:13px;color:#94a3b8;min-width:110px;'>"
                f"{c['fecha']}</span>"
                f"<span style='font-size:16px;font-weight:700;color:#0f172a;'>"
                f"{html_mod.escape(str(c['campeon']))}</span>"
                f"</div>"
            )
        html = (
            "<div style='background:white;border:1px solid #e2e8f0;"
            "border-radius:12px;overflow:hidden;'>" + filas_html + "</div>"
        )
        html_compacto = " ".join(
            line.strip() for line in html.splitlines() if line.strip()
        )
        st.markdown(html_compacto, unsafe_allow_html=True)
    else:
        st.info("ℹ️ Aún no hay campeones registrados. Se añadirán "
                "automáticamente cada domingo al cerrar la semana.")
