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


st.sidebar.title("🎯 MODUS SUPER SERIES")

# ── Estado de la jornada actual ─────────────────────────────────────────
# Mostramos un indicador del estado del torneo en este momento, para tener
# contexto sin necesidad de cambiar de seccion. Si la deteccion falla, no
# mostramos nada — no rompemos el sidebar por un error de carga.
try:
    from data_loading import estado_jornada_sidebar as _est
    _e = _est()
    if _e["estado"] == "ACTIVA":
        st.sidebar.success(f"📅 Hoy: **{_e['jornada']}**")
    elif _e["estado"] == "PENDIENTE":
        st.sidebar.warning(
            f"📅 Hoy: **{_e['jornada']}**\n\n"
            f"⏳ Esperando datos del Sheet..."
        )
    else:  # SIN_JORNADA
        st.sidebar.info(
            f"📅 Sin jornada activa\n\n"
            f"⏭️ Próxima: **{_e['proxima_nombre']}**\n\n"
            f"🕒 {_e['proxima_dia']} a las {_e['proxima_hora']}"
        )
except Exception:
    pass

st.sidebar.markdown("---")

# ── Menu de secciones: barra de botones arriba del todo ──────────────────
# Antes era un radio en la barra lateral: en el movil la barra tapaba la
# pagina y habia que cerrarla a mano cada vez. Ahora el menu va en la
# pagina, siempre visible. La barra lateral queda para el estado de la
# jornada, el refresco y el modo administrador.
SECCIONES = ["🔴 LIVE", "💰 VALUE BETS", "📊 RESULTADOS Y ESTADÍSTICAS",
             "📈 SEGUIMIENTO", "📚 HISTÓRICO", "🔔 ALERTAS"]
_CORTAS = {"🔴 LIVE": "🔴 Live", "💰 VALUE BETS": "💰 Value Bets",
           "📊 RESULTADOS Y ESTADÍSTICAS": "📊 Resultados",
           "📈 SEGUIMIENTO": "📈 Seguimiento", "📚 HISTÓRICO": "📚 Histórico",
           "🔔 ALERTAS": "🔔 Alertas"}
if st.session_state.get("seccion") not in SECCIONES:
    st.session_state["seccion"] = st.session_state.get("_ultima_seccion", SECCIONES[0])
opcion_principal = st.segmented_control(
    "Sección", SECCIONES, format_func=_CORTAS.get, key="seccion",
    label_visibility="collapsed",
)
# Pulsar la seccion ya activa la deselecciona: nos quedamos en la misma
if not opcion_principal:
    opcion_principal = st.session_state.get("_ultima_seccion", SECCIONES[0])
st.session_state["_ultima_seccion"] = opcion_principal

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Actualización")
st.sidebar.caption("Caché: 30 segundos")

if st.sidebar.button("♻️ Forzar Refresh", help="Recarga inmediata"):
    st.cache_data.clear()
    st.session_state.last_update = {}
    st.rerun()

st.sidebar.markdown("---")
render_acceso_admin()

SCRIPT_URL = "https://script.google.com/macros/s/AKfycbyF0-GxHiaX4NW55-2UJt39a9V_aJhGXahq5NL5z2szpbFd7RdtKtr5ww7r852RAm2f/exec"

if es_admin():
    st.sidebar.markdown("### ⚙️ Ejecutar Script")
if es_admin() and st.sidebar.button("▶️ Ejecutar Actualización", help="Ejecuta el script de actualización de datos"):
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

st.sidebar.divider()

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
        for player, stats in d2.items():
            player_display = f"👤 {player.title()}"
            with st.expander(player_display, expanded=False):
                # Racha: ultimos 5 partidos de la jornada activa
                jornada_para_racha = None if selected == "Resumen Semanal" else selected
                render_jugador_visual(
                    player, stats, stats_resumen_para_render, selected,
                    mostrar_tendencias=mostrar_tendencias_live,
                    mostrar_racha=True,
                    jornada_racha=jornada_para_racha
                )

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
    with st.expander("⚙️ Configuración", expanded=True):
        st.markdown("**📂 Selecciona jornada**")
        selected = selector_jornada("res", incluir_resumen=True,
                                    modo_forma_reciente=False)
    selected_url = URLS[selected]
    st.markdown("---")
    d1, d2 = cargar_todo(selected_url, selected, CORTES.get(selected, 2))
    
    if selected in st.session_state.last_update:
        tiempo = (datetime.now() - st.session_state.last_update[selected]).seconds
        st.caption(f"⏱️ Datos actualizados hace {tiempo} segundos")
    
    # ¿Hay datos de jugadores en esta jornada?
    hay_datos = d2 is not None and len(d2) > 0

    if hay_datos:
        st.subheader("📈 Estadísticas por Jugador")

        # Cargar resumen semanal solo si estamos viendo otra jornada
        stats_resumen = None
        mostrar_tendencias = selected != "Resumen Semanal"
        if mostrar_tendencias:
            _, stats_resumen = cargar_todo(URLS["Resumen Semanal"], "Resumen Semanal", CORTES.get("Resumen Semanal", 2))

        for player, stats in d2.items():
            player_display = f"👤 {player.title()}"
            with st.expander(player_display, expanded=False):
                # Racha: ultimos 5 partidos de la jornada seleccionada
                jornada_para_racha = None if selected == "Resumen Semanal" else selected
                render_jugador_visual(player, stats, stats_resumen, selected, mostrar_tendencias=mostrar_tendencias, mostrar_racha=True, jornada_racha=jornada_para_racha)

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
    from alertas_ui import render_seguimiento_apuestas
    render_seguimiento_apuestas()

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
