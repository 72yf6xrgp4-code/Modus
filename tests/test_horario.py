from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from vigia.horario import estimar_inicios, fecha_jornada, proxima_ventana, ventana

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


def _p(orden, estado):
    return {"orden": orden, "estado": estado}


def test_estimacion_antes_de_empezar():
    inicio = d(2026, 11, 5, 14, 0)
    est = estimar_inicios([_p(i, "pendiente") for i in range(4)], inicio,
                          d(2026, 11, 5, 13, 40), {}, 10)
    assert [est[i].strftime("%H:%M") for i in range(4)] == ["14:00", "14:10", "14:20", "14:30"]


def test_estimacion_con_un_partido_en_juego():
    inicio = d(2026, 11, 5, 14, 0)
    lista = [_p(0, "terminado"), _p(1, "en_juego"), _p(2, "pendiente"), _p(3, "pendiente")]
    visto = {1: d(2026, 11, 5, 14, 12)}
    est = estimar_inicios(lista, inicio, d(2026, 11, 5, 14, 15), visto, 10)
    assert est == {2: d(2026, 11, 5, 14, 22), 3: d(2026, 11, 5, 14, 32)}
    # Si el partido en juego se alarga, los siguientes se corren
    est = estimar_inicios(lista, inicio, d(2026, 11, 5, 14, 30), visto, 10)
    assert est[2] == d(2026, 11, 5, 14, 30)


def test_estimacion_tras_un_terminado():
    lista = [_p(0, "terminado"), _p(1, "pendiente")]
    ahora = d(2026, 11, 2, 10, 50)
    assert estimar_inicios(lista, d(2026, 11, 2, 10, 30), ahora, {}, 10) == {1: ahora}
