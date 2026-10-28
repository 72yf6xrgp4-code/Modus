"""
vigia/horario.py - Ventanas de trabajo del vigia y estimacion de la hora
de cada partido (hora de Madrid).

Ventanas (las jornadas de INICIOS_JORNADAS, con margen para avisar antes):
    lunes a miercoles   10:00 - 16:00   (Grupo A 10:30)
    jueves y viernes    13:30 - 03:00   (Grupo C 14:00 y Grupo B 21:00)
    sabado              20:10 - 03:00   (Final 20:40)
De 00:00 a 03:00 cuenta como la jornada del dia anterior.

Los partidos no tienen hora fija: empiezan uno detras de otro. La hora se
estima con la duracion media (10 min) desde el inicio de la jornada o desde
el ultimo partido que la hoja muestra empezado o terminado.
"""

from datetime import datetime, timedelta

from modelo.datos import INICIOS_JORNADAS

# dia de la semana -> (minuto de inicio, minuto de fin) desde las 00:00 del
# dia de jornada (fin > 1440 = madrugada del dia siguiente)
VENTANAS = {
    0: (10 * 60, 16 * 60),
    1: (10 * 60, 16 * 60),
    2: (10 * 60, 16 * 60),
    3: (13 * 60 + 30, 27 * 60),
    4: (13 * 60 + 30, 27 * 60),
    5: (20 * 60 + 10, 27 * 60),
}


def dia_jornada(ahora):
    """Medianoche del dia 'de jornada': de 00:00 a 03:00 es el dia
    anterior (igual que helpers.fecha_jornada_madrid)."""
    if ahora.hour * 60 + ahora.minute <= 3 * 60:
        ahora = ahora - timedelta(days=1)
    return ahora.replace(hour=0, minute=0, second=0, microsecond=0)


def fecha_jornada(ahora):
    return dia_jornada(ahora).strftime("%Y-%m-%d")


def ventana(ahora):
    """(inicio, fin) de la ventana en la que estamos, o None."""
    for dia in (dia_jornada(ahora), ahora.replace(hour=0, minute=0, second=0,
                                                  microsecond=0)):
        v = VENTANAS.get(dia.weekday())
        if not v:
            continue
        ini, fin = dia + timedelta(minutes=v[0]), dia + timedelta(minutes=v[1])
        if ini <= ahora < fin:
            return ini, fin
    return None


def proxima_ventana(ahora):
    """(inicio, fin) de la siguiente ventana que empieza despues de ahora."""
    base = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(0, 8):
        dia = base + timedelta(days=d)
        v = VENTANAS.get(dia.weekday())
        if v and dia + timedelta(minutes=v[0]) > ahora:
            return dia + timedelta(minutes=v[0]), dia + timedelta(minutes=v[1])
    return None


def inicio_jornada(nombre, dia):
    """Hora de inicio de una jornada ('Grupo C Jueves'...) en el dia dado."""
    for wd, h, m, n in INICIOS_JORNADAS:
        if n == nombre:
            return dia.replace(hour=h, minute=m, second=0, microsecond=0)
    return None


def estimar_inicios(partidos, inicio, ahora, vistos_en_juego, duracion_min=10):
    """Hora estimada de los partidos pendientes de una jornada.

    partidos: lista en orden de juego con 'orden' y 'estado' ('pendiente',
              'en_juego' o 'terminado'), como modelo.datos.partidos_de_jornada.
    inicio:   hora de inicio de la jornada.
    vistos_en_juego: {orden: datetime} cuando se vio cada partido en juego
              por primera vez.
    Devuelve {orden: datetime} solo de los pendientes posteriores al ultimo
    partido empezado.
    """
    dur = timedelta(minutes=duracion_min)
    empezados = [p for p in partidos if p["estado"] != "pendiente"]
    if not empezados:
        t = max(inicio, ahora)
        ultimo = -1
    else:
        u = empezados[-1]
        ultimo = u["orden"]
        if u["estado"] == "en_juego":
            visto = vistos_en_juego.get(u["orden"], ahora)
            t = max(ahora, visto + dur)
        else:
            t = ahora
        t = max(t, inicio)
    salida = {}
    for p in partidos:
        if p["orden"] > ultimo and p["estado"] == "pendiente":
            salida[p["orden"]] = t
            t = t + dur
    return salida
