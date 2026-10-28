"""
vigia/horario.py - Ventanas de trabajo del vigia y estimacion de la hora
de cada partido (hora de Madrid).

Ventanas (las jornadas de INICIOS_JORNADAS, con margen para avisar antes):
    lunes a miercoles   10:00 - 16:00   (Grupo A 10:30)
    jueves y viernes    13:30 - 03:00   (Grupo C 14:00 y Grupo B 21:00)
    sabado              20:10 - 03:00   (Final 20:40)
De 00:00 a 03:00 cuenta como la jornada del dia anterior.

Los partidos no tienen hora fija: empiezan uno detras de otro, y Winamax
publica sus mercados poco antes. Por eso se avisa de un partido cuando pasa
a ser el SIGUIENTE: al terminar el anterior de su jornada (segun la hoja).
El primero de la jornada, y cualquiera que traiga hora, se avisa unos
minutos antes de esa hora (AVISO_MIN_ANTES).
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


def toca_avisar(partidos, idx, inicio, ahora, min_antes=10):
    """(avisar, hora) para el partido partidos[idx] de una jornada.

    partidos: lista en orden de juego con 'estado' ('pendiente', 'en_juego'
              o 'terminado') y, si el calendario la trae, 'hora' (datetime).
    inicio:   hora de inicio de la jornada (hora del primer partido).
    Se avisa de un partido pendiente:
      - cuando el partido anterior de la jornada ha terminado, o
      - si tiene hora (el primero de la jornada: la de inicio), cuando
        faltan min_antes minutos o menos.
    hora es la hora conocida del partido o None (no tiene hora fija).
    """
    p = partidos[idx]
    hora = p.get("hora") or (inicio if idx == 0 else None)
    if p["estado"] != "pendiente":
        return False, hora
    if hora is not None and ahora >= hora - timedelta(minutes=min_antes):
        return True, hora
    if idx > 0 and partidos[idx - 1]["estado"] == "terminado":
        return True, hora
    return False, hora
