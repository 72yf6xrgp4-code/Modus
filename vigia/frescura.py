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


def partido_anterior(partidos, j1, j2, stats_hoy):
    """Para cada jugador del partido j1-j2, si los datos incluyen su partido
    anterior de la jornada.

    partidos  = modelo.datos.partidos_de_jornada(...) de la jornada en juego
    stats_hoy = jugadores de esa jornada ({nombre: {..., n_partidos}})

    Devuelve una lista (uno por jugador) de dicts con: jugador, ok (bool),
    texto (frase para mostrar), anterior (partido o None), jugados (partidos
    terminados de hoy) y en_datos (los que cuentan sus estadisticas).
    """
    def juega(jugador, p):
        return _es(jugador, p["j1"]) or _es(jugador, p["j2"])

    # El partido en el cartel: el primero de la pareja sin terminar (si se
    # repite la pareja), o el ultimo si ya estan todos terminados
    de_la_pareja = [p for p in partidos if juega(j1, p) and juega(j2, p)]
    pendientes = [p for p in de_la_pareja if p["estado"] != "terminado"]
    actual = (pendientes[0] if pendientes else de_la_pareja[-1])["orden"] if de_la_pareja else None
    salida = []
    for jugador in (j1, j2):
        suyos = [p for p in partidos if juega(jugador, p)]
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
