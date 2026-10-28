from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from vigia.horario import fecha_jornada, proxima_ventana, toca_avisar, ventana

M = ZoneInfo("Europe/Madrid")


def d(*a):
    return datetime(*a, tzinfo=M)


# 2026-11-02 es lunes
def test_ventanas():
    assert ventana(d(2026, 11, 2, 9, 59)) is None
    assert ventana(d(2026, 11, 2, 10, 0)) == (d(2026, 11, 2, 10, 0), d(2026, 11, 2, 16, 0))
    assert ventana(d(2026, 11, 4, 15, 59)) is not None          # miercoles
    assert ventana(d(2026, 11, 4, 16, 0)) is None
    jue = ventana(d(2026, 11, 5, 17, 0))                        # entre C y B: sigue
    assert jue == (d(2026, 11, 5, 13, 30), d(2026, 11, 6, 3, 0))
    assert ventana(d(2026, 11, 5, 19, 30)) == jue
    assert ventana(d(2026, 11, 7, 20, 10)) == (d(2026, 11, 7, 20, 10), d(2026, 11, 8, 3, 0))
    assert ventana(d(2026, 11, 7, 12, 0)) is None               # sabado por la manana
    assert ventana(d(2026, 11, 8, 12, 0)) is None               # domingo


def test_madrugada_cuenta_como_el_dia_anterior():
    assert ventana(d(2026, 11, 6, 1, 30)) == (d(2026, 11, 5, 13, 30), d(2026, 11, 6, 3, 0))
    assert fecha_jornada(d(2026, 11, 6, 1, 30)) == "2026-11-05"
    assert ventana(d(2026, 11, 8, 2, 59)) == (d(2026, 11, 7, 20, 10), d(2026, 11, 8, 3, 0))
    assert fecha_jornada(d(2026, 11, 8, 2, 59)) == "2026-11-07"
    assert ventana(d(2026, 11, 3, 1, 0)) is None                # martes de madrugada
    assert ventana(d(2026, 11, 6, 3, 0)) is None


def test_proxima_ventana():
    assert proxima_ventana(d(2026, 11, 4, 17, 0))[0] == d(2026, 11, 5, 13, 30)
    assert proxima_ventana(d(2026, 11, 8, 12, 0))[0] == d(2026, 11, 9, 10, 0)


def _p(estado, hora=None):
    p = {"estado": estado}
    if hora:
        p["hora"] = hora
    return p


INICIO = d(2026, 11, 5, 14, 0)     # Grupo C jueves


def test_el_primero_se_avisa_minutos_antes_del_inicio():
    lista = [_p("pendiente"), _p("pendiente")]
    assert toca_avisar(lista, 0, INICIO, d(2026, 11, 5, 13, 49), 10) == (False, INICIO)
    assert toca_avisar(lista, 0, INICIO, d(2026, 11, 5, 13, 50), 10) == (True, INICIO)
    # Si el vigia arranca tarde, se avisa igual
    assert toca_avisar(lista, 0, INICIO, d(2026, 11, 5, 14, 20), 10)[0] is True


def test_los_demas_al_terminar_el_anterior():
    ahora = d(2026, 11, 5, 14, 5)
    assert toca_avisar([_p("en_juego"), _p("pendiente")], 1, INICIO, ahora) == (False, None)
    assert toca_avisar([_p("terminado"), _p("pendiente")], 1, INICIO, ahora) == (True, None)
    # El de despues del siguiente aun no
    assert toca_avisar([_p("terminado"), _p("pendiente"), _p("pendiente")], 2,
                       INICIO, ahora) == (False, None)
    # Partidos ya empezados o terminados nunca
    assert toca_avisar([_p("terminado"), _p("en_juego")], 1, INICIO, ahora)[0] is False


def test_partido_con_hora_en_el_calendario():
    hora = d(2026, 11, 5, 15, 30)
    lista = [_p("en_juego"), _p("pendiente", hora)]
    assert toca_avisar(lista, 1, INICIO, d(2026, 11, 5, 15, 19), 10) == (False, hora)
    assert toca_avisar(lista, 1, INICIO, d(2026, 11, 5, 15, 20), 10) == (True, hora)
    assert toca_avisar(lista, 1, INICIO, d(2026, 11, 5, 15, 25), 5) == (True, hora)
    assert toca_avisar(lista, 1, INICIO, d(2026, 11, 5, 15, 24), 5) == (False, hora)
