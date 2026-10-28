"""
data_loading.py - Carga y parsing de las hojas de calculo de Google Sheets.

Funciones para leer cada pestana del spreadsheet (jornadas diarias, Resumen
Semanal, Value Bets) y extraer las estadisticas de cada jugador.

Depende de: config (URLS, CORTES) y helpers (safe_float, _buscar_stat).
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
import re
from datetime import datetime, timedelta

from config import URLS, CORTES
from helpers import safe_float, _buscar_stat
# El parseo de las pestanas vive en modelo/datos.py (sin Streamlit) para que
# el vigia lea los datos igual que la app. Aqui se envuelve con la cache.
from modelo.datos import (  # noqa: F401
    arreglar_columnas, extraer_stats_diarias, extraer_stats_resumen_semanal,
    jugadores_desde_df, jornada_por_hora, combinar_forma_reciente,
)

@st.cache_data(ttl=30, show_spinner="Cargando datos del Sheet...")
def cargar_jugadores_desde(pestana: str):
    try:
        url = URLS.get(pestana, "")
        if not url:
            return {}
        df = pd.read_csv(url, header=None)
        st.session_state.last_update[pestana] = datetime.now()
        return jugadores_desde_df(pestana, df)
    except Exception as e:
        st.error(f"Error cargando {pestana}: {e}")
        return {}


# Pestanas de jornada candidatas a ser "la jornada de hoy", en orden
# cronologico del torneo (lunes -> sabado).
# Pestanas de jornada candidatas a ser "la jornada de hoy", en orden
# cronologico del torneo. IMPORTANTE: jueves y viernes el Grupo C juega
# por la manana y el Grupo B por la noche, asi que C va ANTES que B.
_JORNADAS_ORDEN = [
    "Grupo A Lunes", "Grupo A Martes", "Grupo A Miércoles",
    "Grupo C Jueves", "Grupo B Jueves",
    "Grupo C Viernes", "Grupo B Viernes",
    "Final Sábado",
]


def detectar_jornada_de_hoy(exigir_datos=True):
    """Detecta cual es la jornada activa AHORA segun el dia de la semana y
    la hora del dia. Reglas del torneo MODUS:

      Lun/Mar/Mie 10:00 - 23:59  -> Grupo A de ese dia
      Jue/Vie     14:00 - 22:59  -> Grupo C de ese dia
      Jue/Vie     23:00 - 23:59  -> Grupo B de ese dia
      Vie/Sab     00:00 - 03:00  -> Grupo B del dia ANTERIOR
                                    (la sesion de la noche se prolonga)
      Sab         14:00 - 23:59  -> Final Sabado

    Fuera de esos rangos -> None ("sin jornada activa").

    Despues de aplicar la regla horaria, comprueba que la pestana
    correspondiente tenga datos cargados. Si no los tiene, devuelve None
    (la app la considera no disponible todavia).
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    except Exception:
        # Si zoneinfo no esta disponible, caemos a hora local (peor pero
        # no rompe la app)
        ahora = datetime.now()
    jornada = jornada_por_hora(ahora)

    if jornada is None:
        return None

    # Comprobar que la pestana tenga datos cargados. Si todavia no, la
    # consideramos no disponible — SALVO que se pida lo contrario con
    # exigir_datos=False (LIVE quiere saber la jornada por hora aunque
    # los datos aun no esten cargados, para mostrar "esperando datos de
    # <jornada>" en vez de saltar a la proxima).
    if not exigir_datos:
        return jornada
    try:
        jug = cargar_jugadores_desde(jornada)
    except Exception:
        jug = {}
    if not jug:
        return None
    return jornada


def proxima_jornada():
    """Devuelve (nombre_jornada, hora_inicio_str) de la PROXIMA jornada
    que va a empezar, desde el momento actual. Util para mostrar 'Sin
    jornada activa - proxima: Grupo A Lunes a las 10:00'.

    Si ya estamos en horario de jornada, devuelve None (significa que no
    procede mostrar 'proxima', porque ya hay una activa).

    Devuelve (None, None) si no hay proxima identificable.
    """
    from datetime import datetime, timedelta
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    except Exception:
        ahora = datetime.now()

    # Inicios de cada jornada (wd, hora, minuto, nombre) en orden
    # cronologico de la semana.
    INICIOS = [
        (0, 10, 30, "Grupo A Lunes"),
        (1, 10, 30, "Grupo A Martes"),
        (2, 10, 30, "Grupo A Miércoles"),
        (3, 14, 0, "Grupo C Jueves"),
        (3, 21, 0, "Grupo B Jueves"),
        (4, 14, 0, "Grupo C Viernes"),
        (4, 21, 0, "Grupo B Viernes"),
        (5, 20, 40, "Final Sábado"),
    ]
    DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves",
               "Viernes", "Sábado", "Domingo"]

    wd_hoy = ahora.weekday()
    h_hoy = ahora.hour
    m_hoy = ahora.minute

    # Buscar el proximo inicio que aun no ha llegado esta semana
    for wd, h, mi, nombre in INICIOS:
        # Comparar (wd, h, mi) vs (wd_hoy, h_hoy, m_hoy)
        if (wd, h, mi) > (wd_hoy, h_hoy, m_hoy):
            dias_falta = wd - wd_hoy
            dia_inicio = ahora + timedelta(days=dias_falta)
            etiqueta_dia = ("Hoy" if dias_falta == 0
                            else "Mañana" if dias_falta == 1
                            else f"{DIAS_ES[wd]} {dia_inicio.strftime('%d/%m')}")
            return nombre, f"{h:02d}:{mi:02d}", etiqueta_dia

    # No hay mas inicios esta semana -> el proximo es el lunes que viene
    dias_falta = (7 - wd_hoy) + 0
    dia_inicio = ahora + timedelta(days=dias_falta)
    etiqueta_dia = f"Lunes {dia_inicio.strftime('%d/%m')}"
    return "Grupo A Lunes", "10:30", etiqueta_dia


def jornada_mas_reciente():
    """Jornada que esta en juego o, si no hay ninguna, la ultima que ha
    empezado esta semana (hora de Madrid). Sirve de seleccion por defecto en
    Resultados: un sabado por la manana interesa el Grupo B del viernes, no
    el lunes. Antes del primer partido del lunes devuelve 'Grupo A Lunes'.
    """
    activa = detectar_jornada_de_hoy(exigir_datos=False)
    if activa:
        return activa
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    except Exception:
        ahora = datetime.now()
    INICIOS = [
        (0, 10, 30, "Grupo A Lunes"), (1, 10, 30, "Grupo A Martes"),
        (2, 10, 30, "Grupo A Miércoles"), (3, 14, 0, "Grupo C Jueves"),
        (3, 21, 0, "Grupo B Jueves"), (4, 14, 0, "Grupo C Viernes"),
        (4, 21, 0, "Grupo B Viernes"), (5, 20, 40, "Final Sábado"),
    ]
    actual = (ahora.weekday(), ahora.hour, ahora.minute)
    empezadas = [n for (wd, h, mi, n) in INICIOS if (wd, h, mi) <= actual]
    return empezadas[-1] if empezadas else "Grupo A Lunes"


def estado_jornada_sidebar():
    """Estado de la jornada para mostrar en el sidebar.

    A diferencia de detectar_jornada_de_hoy(), distingue tres casos:
      - ACTIVA: la jornada que toca por hora YA tiene datos cargados.
      - PENDIENTE: estamos en horario de jornada pero la pestana del Sheet
        aun no tiene jugadores cargados (suele pasar al principio del
        horario, antes de que el Sheet recoja los datos del partido).
      - SIN_JORNADA: estamos fuera del horario de cualquier jornada.

    Devuelve un dict con:
      estado: "ACTIVA" | "PENDIENTE" | "SIN_JORNADA"
      jornada: nombre de la jornada (None si SIN_JORNADA)
      proxima_nombre, proxima_hora, proxima_dia: solo si SIN_JORNADA
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    except Exception:
        ahora = datetime.now()
    # Regla horaria SIN comprobar datos (al contrario que
    # detectar_jornada_de_hoy, que devuelve None si la pestana esta vacia).
    jornada_horaria = jornada_por_hora(ahora)

    if jornada_horaria is None:
        # Fuera de horario: SIN_JORNADA + proxima
        nom, hora, dia = proxima_jornada()
        return {
            "estado": "SIN_JORNADA",
            "jornada": None,
            "proxima_nombre": nom,
            "proxima_hora": hora,
            "proxima_dia": dia,
        }

    # En horario: comprobar si la pestana tiene datos
    try:
        jug = cargar_jugadores_desde(jornada_horaria)
    except Exception:
        jug = {}
    if jug:
        return {"estado": "ACTIVA", "jornada": jornada_horaria}
    else:
        return {"estado": "PENDIENTE", "jornada": jornada_horaria}


def cargar_forma_reciente():
    """Construye la fuente de datos 'Forma reciente'.

    Combina, para cada jugador, sus estadisticas de DOS fuentes:
      - La jornada de hoy (lo mas reciente).
      - El Resumen Semanal (el acumulado de toda la semana).

    El peso de 'hoy' es DINAMICO segun cuantos partidos lleve hoy ese
    jugador: con pocos partidos pesa poco (un solo partido no debe
    distorsionar la valoracion), y con la jornada avanzada lo reciente
    domina. Pesos: 1 partido -> 30%, 2 -> 45%, 3 -> 60%, 4 -> 65%,
    5 -> 70%, y a partir de ahi sube suave hasta un tope del 85%.

    Para cada estadistica numerica:
        valor_final = peso_hoy * valor_hoy + (1 - peso_hoy) * valor_resumen

    Si un jugador no aparece en la jornada de hoy (aun no ha jugado),
    se usan directamente sus datos del Resumen Semanal.

    Devuelve un dict {nombre_lower: {...stats...}} con la misma forma que
    cargar_jugadores_desde, para que el resto de la app no note diferencia.
    """
    resumen = cargar_jugadores_desde("Resumen Semanal")
    if not resumen:
        # Sin Resumen no hay base: devolvemos lo que haya de hoy, o vacio.
        jornada_hoy = detectar_jornada_de_hoy()
        return cargar_jugadores_desde(jornada_hoy) if jornada_hoy else {}

    jornada_hoy = detectar_jornada_de_hoy()
    if not jornada_hoy:
        # No hay jornada con datos: la forma reciente es solo el Resumen.
        return resumen
    datos_hoy = cargar_jugadores_desde(jornada_hoy)

    return combinar_forma_reciente(resumen, datos_hoy)


@st.cache_data(ttl=30, show_spinner="Cargando datos del Sheet...")
def cargar_todo(url, opcion, cortes):
    try:
        df = pd.read_csv(url, header=None)
        st.session_state.last_update[opcion] = datetime.now()
        if opcion == "Resumen Semanal":
            stats = extraer_stats_resumen_semanal(df)
            df_list = []
            for nombre_lower, stat_dict in stats.items():
                fila = {"Jugador": nombre_lower}
                orden_columnas = [
                    "legs por partido", "media 180 por partida", "promedio puntos",
                    "diferencia legs", "promedio checkouts", "número victorias",
                    "número derrotas", "porcentaje victoria"
                ]
                for col in orden_columnas:
                    for k, v in stat_dict.items():
                        if col in k.lower():
                            fila[k] = v
                for k, v in stat_dict.items():
                    if "puntuación" in k.lower() or "puntacion" in k.lower():
                        fila[k] = v
                # Añadir el índice de volatilidad al final
                for k, v in stat_dict.items():
                    if "volatilidad" in k.lower():
                        fila[k] = v
                df_list.append(fila)
            df_display = pd.DataFrame(df_list) if df_list else pd.DataFrame()
            return df_display, stats
        elif opcion == "Value Bets":
            f, c = cortes["unica_filas"], cortes["unica_cols"]
            res = df.iloc[f[0]:f[1], c[0]:c[1]]
            res.columns = res.iloc[0]; res = res[1:]
            return arreglar_columnas(res.dropna(how='all')), None
        else:
            f, c = cortes["izq_filas"], cortes["izq_cols"]
            izq = df.iloc[f[0]:f[1], c[0]:c[1]]
            izq.columns = izq.iloc[0]; izq = izq[1:]
            s = extraer_stats_diarias(df, cortes["der_nombres"], cortes["der_cols"])
            return arreglar_columnas(izq.dropna(how='all')), s
    except Exception as e:
        st.error(f"Error cargando {opcion}: {e}")
        return None, None


def get_jornada_actual():
    """Devuelve (nombre, url, es_activa) de la jornada activa AHORA.

    es_activa es True si la jornada esta activa POR HORA, aunque la pestana
    del Sheet aun no tenga datos cargados. Asi LIVE muestra "esperando datos
    de <jornada>" en vez de saltar a la proxima jornada cuando los datos
    todavia no estan disponibles.
    """
    jornada = detectar_jornada_de_hoy(exigir_datos=False)
    if jornada is None:
        return None, None, False
    url = URLS.get(jornada, "")
    return jornada, url, True


def get_proxima_jornada():
    """Devuelve (nombre, url) de la proxima jornada que va a empezar.

    Delega en proxima_jornada() (que usa zona horaria Madrid y las reglas
    horarias actualizadas).
    """
    try:
        nombre, _hora, _dia = proxima_jornada()
    except Exception:
        nombre = "Grupo A Lunes"
    url = URLS.get(nombre, "")
    return nombre, url


# ─────────────────────────────────────────────────────────────────────────────
# HISTORIAL W/L Y RACHA SEMANAL
# ─────────────────────────────────────────────────────────────────────────────

# Orden cronologico de las jornadas durante la semana
JORNADAS_SEMANA_ORDEN = [
    "Grupo A Lunes",
    "Grupo A Martes",
    "Grupo A Miércoles",
    "Grupo C Jueves",
    "Grupo B Jueves",
    "Grupo C Viernes",
    "Grupo B Viernes",
    "Final Sábado",
]

FILA_INICIO_PARTIDOS = 7   # fila 1-indexed donde empiezan los partidos


def _normalizar_nombre_hist(n):
    """Quita tildes, pasa a minusculas y colapsa espacios."""
    import unicodedata
    n = unicodedata.normalize("NFD", str(n))
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return " ".join(n.lower().split())


@st.cache_data(ttl=120, show_spinner=False)
def cargar_historial_semana(nombre_jugador: str) -> list:
    """Devuelve la lista de resultados del jugador en la semana actual,
    en orden cronologico, como booleans: True = victoria, False = derrota.

    Recorre TODAS las jornadas (A, B, C y Final) y extrae los partidos
    donde aparece el jugador. Para cada partido de 2 filas, el ganador
    es el que tiene 4 legs. Si ambas filas estan vacias, el partido no
    se ha jugado y se ignora.

    Devuelve una lista con hasta 15 elementos (max partidos por semana).
    Lista vacia si no se encuentra el jugador en ninguna jornada.
    """
    nombre_norm = _normalizar_nombre_hist(nombre_jugador)
    resultados = []

    for jornada in JORNADAS_SEMANA_ORDEN:
        lineas = _descargar_csv_jornada(jornada)
        if not lineas:
            continue

        idx_inicio = FILA_INICIO_PARTIDOS - 1  # 0-indexed
        filas_partidos = lineas[idx_inicio:]

        # Recorrer en pares: fila_j1 + fila_j2 = un partido
        i = 0
        while i + 1 < len(filas_partidos):
            fila1 = filas_partidos[i]
            fila2 = filas_partidos[i + 1]
            i += 2

            nombre1 = fila1[0].strip() if len(fila1) > 0 else ""
            nombre2 = fila2[0].strip() if len(fila2) > 0 else ""
            if not nombre1 or not nombre2:
                continue  # hueco (nombres aun sin cargar): seguir buscando

            # ¿Aparece nuestro jugador en alguna de las dos filas?
            norm1 = _normalizar_nombre_hist(nombre1)
            norm2 = _normalizar_nombre_hist(nombre2)
            es_j1 = (nombre_norm in norm1 or norm1 in nombre_norm)
            es_j2 = (nombre_norm in norm2 or norm2 in nombre_norm)
            if not es_j1 and not es_j2:
                continue  # este partido no le involucra

            # Legs de cada jugador (columna B, indice 1)
            def _legs(fila):
                try:
                    v = str(fila[1]).strip().replace(",", ".")
                    return int(float(v)) if v else 0
                except Exception:
                    return 0

            legs1 = _legs(fila1)
            legs2 = _legs(fila2)

            # Si ninguno tiene legs, el partido no se ha jugado todavia
            if legs1 == 0 and legs2 == 0:
                # Comprobar si hay algun dato en otras columnas
                datos1 = any(
                    str(fila1[c]).strip() not in ("", "0", "0,00%", "0%")
                    for c in range(1, min(5, len(fila1)))
                )
                datos2 = any(
                    str(fila2[c]).strip() not in ("", "0", "0,00%", "0%")
                    for c in range(1, min(5, len(fila2)))
                )
                if not datos1 and not datos2:
                    continue  # partido no jugado aun

            # Determinar ganador (quien llego a 4)
            if legs1 >= 4:
                gano_j1 = True
            elif legs2 >= 4:
                gano_j1 = False
            else:
                continue  # partido en curso o datos incompletos

            victoria = (es_j1 and gano_j1) or (es_j2 and not gano_j1)
            resultados.append(victoria)

    return resultados


def calcular_racha(resultados: list) -> tuple:
    """A partir de la lista de resultados (True=W, False=L) calcula
    la racha actual del jugador.

    Devuelve (longitud, tipo) donde tipo es 'W', 'L' o None (sin datos).
    Ejemplo: (3, 'W') significa que lleva 3 victorias seguidas.
    """
    if not resultados:
        return 0, None
    ultimo = resultados[-1]
    racha = 1
    for r in reversed(resultados[:-1]):
        if r == ultimo:
            racha += 1
        else:
            break
    return racha, ("W" if ultimo else "L")



@st.cache_data(ttl=60, show_spinner=False)
def obtener_proximos_partidos_csv(limite=5) -> dict:
    """Devuelve los proximos partidos NO empezados leyendo el CSV de la
    jornada que toca (activa o, si no hay activa, la proxima), en ORDEN
    DE JUEGO REAL.

    No usa la API de MODUS (igamemedia, abandonada): se basa solo en el
    CSV de la jornada correcta.

    Reglas:
      - Jornada activa con datos -> sus partidos no empezados.
      - Sin jornada activa pero proxima con datos -> los de la proxima.
      - Ningun CSV con datos -> lista vacia (no se muestra nada).

    Un partido esta "no empezado" si ninguna de sus 2 filas tiene datos
    de juego en las columnas B-E (legs, 180s, promedio, checkout).

    DEVUELVE dict:
      {"partidos": [{id, j1, j2, etiqueta}], "diagnostico": str}
    """
    # 1) Elegir la jornada: activa primero, luego proxima
    jornada = detectar_jornada_de_hoy()
    origen = "activa"
    if not jornada:
        try:
            nombre_prox, _h, _d = proxima_jornada()
        except Exception:
            nombre_prox = None
        jornada = nombre_prox
        origen = "proxima"

    if not jornada:
        return {"partidos": [],
                "diagnostico": "No hay jornada activa ni proxima identificable."}

    # 2) Leer el CSV (descarga centralizada y cacheada)
    lineas = _descargar_csv_jornada(jornada)
    if not lineas:
        return {"partidos": [],
                "diagnostico": f"No se pudo leer el CSV de {jornada}."}
    idx_inicio = FILA_INICIO_PARTIDOS - 1
    filas = lineas[idx_inicio:]

    def _celda_dato(v):
        t = str(v).strip().lower()
        return t not in ("", "none", "null", "-", "0", "0.0", "0,0",
                          "0-0", "0,00%", "0%", "00:00")

    def _legs(v):
        try:
            return int(float(str(v).strip().replace(",", ".")))
        except Exception:
            return 0

    proximos = []
    i = 0
    while i + 1 < len(filas):
        fila1 = filas[i]
        fila2 = filas[i + 1]
        i += 2
        j1 = fila1[0].strip() if len(fila1) > 0 else ""
        j2 = fila2[0].strip() if len(fila2) > 0 else ""
        if not j1 or not j2:
            continue  # hueco

        celdas1 = fila1[1:5] if len(fila1) >= 5 else fila1[1:]
        celdas2 = fila2[1:5] if len(fila2) >= 5 else fila2[1:]
        legs1 = _legs(fila1[1] if len(fila1) > 1 else "")
        legs2 = _legs(fila2[1] if len(fila2) > 1 else "")

        terminado = (legs1 >= 4 or legs2 >= 4)
        algun_dato = (any(_celda_dato(c) for c in celdas1) or
                      any(_celda_dato(c) for c in celdas2))

        if terminado or algun_dato:
            continue  # ya empezado o terminado -> no es "proximo"

        proximos.append({
            "id": f"{j1}-{j2}",
            "j1": j1,
            "j2": j2,
            "etiqueta": f"{j1} vs {j2}",
        })

    # ── Final Sábado: anadir semifinales y final al desplegable ───────────
    # Las semis/final no estan en el CSV (se calculan), pero queremos poder
    # predecirlas con antelacion en cuanto se conozcan los jugadores.
    if jornada == "Final Sábado":
        try:
            from clasificacion import construir_bracket_final
            bracket = construir_bracket_final()
            extra = []
            sf = bracket.get("semifinales", [None, None])
            etiquetas_sf = ["Semifinal 1", "Semifinal 2"]
            for par, etq in zip(sf, etiquetas_sf):
                if par:
                    extra.append({
                        "id": f"{par[0]}-{par[1]}",
                        "j1": par[0], "j2": par[1],
                        "etiqueta": f"[{etq}] {par[0]} vs {par[1]}",
                    })
            fin = bracket.get("final")
            if fin:
                extra.append({
                    "id": f"{fin[0]}-{fin[1]}",
                    "j1": fin[0], "j2": fin[1],
                    "etiqueta": f"[Final] {fin[0]} vs {fin[1]}",
                })
            # Las semis/final van al principio (mas relevantes para apostar)
            if extra:
                proximos = extra + proximos
        except Exception:
            pass

    # Final Sábado sin nombres aun en el Sheet: ofrecemos los cruces de los
    # grupos de la Final ya conocidos por la clasificacion semanal (todos
    # contra todos dentro de cada grupo), para poder predecirlos antes.
    if jornada == "Final Sábado" and not proximos:
        try:
            from itertools import combinations
            from clasificacion import construir_grupos_final
            for nombre_g, jugs in construir_grupos_final().items():
                nombres = [d["jugador"] for d in jugs if d.get("jugador")]
                etq = nombre_g.replace(" Final", "")
                for a_, b_ in combinations(nombres, 2):
                    proximos.append({
                        "id": f"{a_}-{b_}", "j1": a_, "j2": b_,
                        "etiqueta": f"[Final · {etq}] {a_} vs {b_}",
                    })
        except Exception:
            pass

    # En Final Sábado mostramos mas partidos (grupos + 2 semis + final),
    # asi que ampliamos el limite para esa jornada.
    if jornada == "Final Sábado":
        limite = max(limite, 10)

    if not proximos:
        return {"partidos": [],
                "diagnostico": f"La jornada {jornada} aun no tiene partidos "
                               f"pendientes con datos."}

    return {"partidos": proximos[:limite], "diagnostico": ""}


@st.cache_data(ttl=120, show_spinner=False)
def cargar_historial_jornada(nombre_jugador: str, jornada: str) -> list:
    """Como cargar_historial_semana pero SOLO de una jornada concreta.

    Devuelve lista de booleans (True=victoria, False=derrota) de los
    partidos del jugador en esa jornada, en orden de juego. Lista vacia
    si el jugador no aparece o la jornada no tiene datos.
    """
    nombre_norm = _normalizar_nombre_hist(nombre_jugador)
    resultados = []

    lineas = _descargar_csv_jornada(jornada)
    if not lineas:
        return []
    idx_inicio = FILA_INICIO_PARTIDOS - 1
    filas = lineas[idx_inicio:]

    i = 0
    while i + 1 < len(filas):
        fila1 = filas[i]
        fila2 = filas[i + 1]
        i += 2
        n1 = fila1[0].strip() if len(fila1) > 0 else ""
        n2 = fila2[0].strip() if len(fila2) > 0 else ""
        if not n1 or not n2:
            continue
        norm1 = _normalizar_nombre_hist(n1)
        norm2 = _normalizar_nombre_hist(n2)
        es_j1 = (nombre_norm in norm1 or norm1 in nombre_norm)
        es_j2 = (nombre_norm in norm2 or norm2 in nombre_norm)
        if not es_j1 and not es_j2:
            continue

        def _legs(fila):
            try:
                v = str(fila[1]).strip().replace(",", ".")
                return int(float(v)) if v else 0
            except Exception:
                return 0

        legs1 = _legs(fila1)
        legs2 = _legs(fila2)
        if legs1 >= 4:
            gano_j1 = True
        elif legs2 >= 4:
            gano_j1 = False
        else:
            continue  # en curso / no jugado

        victoria = (es_j1 and gano_j1) or (es_j2 and not gano_j1)
        resultados.append(victoria)

    return resultados


@st.cache_data(ttl=60, show_spinner=False)
def _descargar_csv_jornada(jornada: str) -> list:
    """Descarga el CSV de una jornada UNA SOLA VEZ (cacheado 60s) y devuelve
    las filas parseadas como lista de listas.

    Todas las funciones de historial/racha/orden/proximos usan esta funcion
    para evitar descargar el mismo CSV varias veces (antes, cada jugador
    descargaba su propia copia: 6 jugadores x 8 jornadas = 48 peticiones;
    ahora maximo 8, una por jornada).
    """
    import io
    import csv as csv_mod
    import urllib.request

    url = URLS.get(jornada)
    if not url:
        return []
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            texto = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return []
    return list(csv_mod.reader(io.StringIO(texto)))
