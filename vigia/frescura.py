"""
vigia/frescura.py - ¿Tienen los datos el partido anterior de cada jugador?

Antes de apostar con el boton "Modus value" interesa que las estadisticas
con las que calcula el modelo ya incluyan el ultimo partido de cada jugador.
Se comprueba con la hoja de la jornada (funcion pura, sin red):

  1. Todos los partidos anteriores del jugador en la jornada (los que van
     antes en el cartel) tienen que estar terminados en la hoja.
  2. Las estadisticas de hoy del jugador (victorias + derrotas = n_partidos)
     tienen que contar todos esos partidos.
"""

from vigia.nombres import mismo_jugador


def _es(jugador, nombre):
    return bool(nombre) and mismo_jugador(jugador, nombre)


def _rival_y_marcador(p, jugador):
    if _es(jugador, p["j1"]):
        return p["j2"], f"{p['legs1']}-{p['legs2']}"
    return p["j1"], f"{p['legs2']}-{p['legs1']}"


def _stats(jugador, stats_hoy):
    for clave, d in (stats_hoy or {}).items():
        if _es(jugador, d.get("nombre_original") or clave):
            return d
    return None


def _juega(jugador, p):
    return _es(jugador, p["j1"]) or _es(jugador, p["j2"])


def partido_en_cartel(partidos, j1, j2):
    """El partido j1-j2 en el cartel de la jornada: el primero de la pareja
    sin terminar (si se repitiera la pareja), o el ultimo si ya estan todos
    terminados. None si no esta."""
    de_la_pareja = [p for p in partidos if _juega(j1, p) and _juega(j2, p)]
    pendientes = [p for p in de_la_pareja if p["estado"] != "terminado"]
    return (pendientes[0] if pendientes else de_la_pareja[-1]) if de_la_pareja else None


def partido_anterior(partidos, j1, j2, stats_hoy):
    """Para cada jugador del partido j1-j2, si los datos incluyen su partido
    anterior de la jornada.

    partidos  = modelo.datos.partidos_de_jornada(...) de la jornada en juego
    stats_hoy = jugadores de esa jornada ({nombre: {..., n_partidos}})

    Devuelve una lista (uno por jugador) de dicts con: jugador, ok (bool),
    texto (frase para mostrar), anterior (partido o None), jugados (partidos
    terminados de hoy) y en_datos (los que cuentan sus estadisticas).
    """
    p_actual = partido_en_cartel(partidos, j1, j2)
    actual = p_actual["orden"] if p_actual else None
    salida = []
    for jugador in (j1, j2):
        suyos = [p for p in partidos if _juega(jugador, p)]
        if actual is not None:
            previos = [p for p in suyos if p["orden"] < actual]
        else:
            # Partido fuera del cartel: los que ya han empezado
            previos = [p for p in suyos if p["estado"] != "pendiente"]
        terminados = [p for p in previos if p["estado"] == "terminado"]
        st = _stats(jugador, stats_hoy)
        en_datos = int(st.get("n_partidos") or 0) if st else 0
        r = {"jugador": jugador, "anterior": previos[-1] if previos else None,
             "jugados": len(terminados), "en_datos": en_datos, "ok": True}
        sin_terminar = [p for p in previos if p["estado"] != "terminado"]
        if sin_terminar:
            p = sin_terminar[-1]
            rival, _ = _rival_y_marcador(p, jugador)
            como = "en juego" if p["estado"] == "en_juego" else "sin empezar"
            r.update(ok=False, texto=f"su partido contra {rival} aún aparece {como} en "
                                     "la hoja de la jornada")
        elif not terminados:
            r["texto"] = "es su primer partido de hoy"
        elif en_datos < len(terminados):
            rival, marcador = _rival_y_marcador(terminados[-1], jugador)
            r.update(ok=False, texto=(f"sus estadísticas de hoy cuentan {en_datos} de sus "
                                      f"{len(terminados)} partidos: falta el último, "
                                      f"contra {rival} ({marcador})"))
        else:
            rival, marcador = _rival_y_marcador(terminados[-1], jugador)
            r["texto"] = f"incluyen su último partido, contra {rival} ({marcador})"
        salida.append(r)
    return salida


# ─────────────────────────────────────────────────────────────────────────────
# PARTIDOS PREVIOS EN LA COMPETICION (¿es fiable el partido?)
# ─────────────────────────────────────────────────────────────────────────────

def partidos_previos(semana, jugador, jornada=None, orden=None):
    """Partidos terminados del jugador en la semana ANTES de este: los de
    las jornadas anteriores y, de `jornada`, los que van antes de `orden`
    en el cartel (sin jornada, todos los terminados).

    semana: {jornada: partidos_de_jornada} de las jornadas de la semana
    hasta hoy, en orden (las de dias posteriores aun son de la semana pasada).
    """
    n = 0
    for j, partidos in semana.items():
        for p in partidos:
            if p["estado"] != "terminado" or not _juega(jugador, p):
                continue
            if j == jornada and orden is not None and p["orden"] >= orden:
                continue
            n += 1
        if j == jornada:
            break
    return n


def info_partido(semana, jornadas_hoy, j1, j2):
    """Jornada, numero de partido y partidos previos de cada jugador en la
    semana: {jornada, n_partido, previos_j1, previos_j2}. Si el partido no
    esta en el cartel de hoy, jornada y n_partido van vacios y los previos
    cuentan todos los terminados hasta ahora."""
    for j in jornadas_hoy:
        p = partido_en_cartel(semana.get(j, []), j1, j2)
        if p:
            return {"jornada": j, "n_partido": p["orden"] + 1,
                    "previos_j1": partidos_previos(semana, j1, j, p["orden"]),
                    "previos_j2": partidos_previos(semana, j2, j, p["orden"])}
    return {"jornada": "", "n_partido": "",
            "previos_j1": partidos_previos(semana, j1), "previos_j2": partidos_previos(semana, j2)}
