import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from vigia.frescura import info_partido, partidos_previos
from vigia.hoja import HojaMemoria
from vigia.nucleo import Vigia
from vigia.registro import fiable, mejores_por_partido, por_mercado, resumen_apuestas

GANA_1 = json.dumps({"tipo": "ganador", "jugador": 1})


def _p(orden, j1, j2, estado="terminado"):
    return {"orden": orden, "j1": j1, "j2": j2, "legs1": 4, "legs2": 1,
            "t180_1": 1, "t180_2": 0, "estado": estado}


# Grupo A: martes con 2 partidos de Baetens el lunes; Self solo juega el martes
SEMANA = {
    "Grupo A Lunes": [_p(0, "Andy Baetens", "X"), _p(1, "Y", "Andy Baetens"), _p(2, "X", "Y")],
    "Grupo A Martes": [_p(0, "Self", "X"), _p(1, "Andy Baetens", "Y"), _p(2, "Self", "Y"),
                       _p(3, "Self", "Z"),
                       _p(4, "Andy Baetens", "Self", "pendiente"),
                       _p(5, "Self", "X", "pendiente")],
}


def test_partidos_previos_cuentan_toda_la_semana_hasta_este_partido():
    assert partidos_previos(SEMANA, "Andy Baetens", "Grupo A Martes", 4) == 3   # 2 lunes + 1
    assert partidos_previos(SEMANA, "Self", "Grupo A Martes", 4) == 3
    assert partidos_previos(SEMANA, "Self", "Grupo A Martes", 2) == 1           # antes del 3.º
    info = info_partido(SEMANA, ["Grupo A Martes"], "Self", "Andy Baetens")
    assert info == {"jornada": "Grupo A Martes", "n_partido": 5, "previos_j1": 3, "previos_j2": 3}
    # fuera del cartel: todos los terminados hasta ahora
    assert info_partido(SEMANA, ["Grupo A Martes"], "Self", "Q")["previos_j1"] == 3


def test_fiable():
    assert fiable({"previos_j1": 3, "previos_j2": 7})
    assert not fiable({"previos_j1": 2, "previos_j2": 7})
    assert not fiable({"previos_j1": "", "previos_j2": 7})      # sin dato: no cuenta
    assert not fiable({})


def _wm(match, lectura, salida, edge, importe, resultado, cuota=2.0, previos=(3, 3), **extra):
    return dict({"fecha": "2026-11-03", "hora": "11:00", "match_id": match, "lectura": lectura,
                 "j1": "A", "j2": "B", "salida": salida, "mercado": "Ganador", "edge": edge,
                 "importe": importe, "cuota": cuota, "resultado": resultado,
                 "seleccion_json": GANA_1, "previos_j1": previos[0], "previos_j2": previos[1]},
                **extra)


def test_si_las_hubieras_hecho_todas_la_mejor_de_cada_partido_fiable():
    filas = [
        # Partido 1: lectura vieja (no cuenta) y la ultima con dos con value
        _wm("1", 100, "vieja", 0.9, 15, "ganada"),
        _wm("1", 200, "A", 0.25, 5, "perdida"),
        _wm("1", 200, "B", 0.40, 10, "ganada", cuota=3.0),
        _wm("1", 200, "C", 0.60, 0, "perdida"),          # mas edge pero tu regla: 0 EUR
        # Partido 2: poco fiable (un jugador con 2 previos) -> fuera
        _wm("2", 300, "A", 0.8, 15, "ganada", previos=(2, 5)),
        # Partido 3: ninguna con importe -> sin apuesta
        _wm("3", 400, "A", 0.1, 0, "ganada"),
    ]
    mejores = mejores_por_partido(filas)
    assert [(m["match_id"], m["salida"]) for m in mejores] == [("1", "B")]
    r = resumen_apuestas(mejores, solo_apostadas=False)
    assert (r["n"], r["invertido"], r["beneficio"]) == (1, 10, 20)   # 10 EUR a 3,0
    # en el seguimiento por mercado: 'todas' de la simulacion, 'reales' tus apuestas
    mia = {"tipo_aviso": "apuesta", "estado": "apostada", "mercado": "Ganador", "importe": 5,
           "importe_real": 7, "cuota": 2.0, "resultado": "perdida"}
    total = por_mercado([mia], todas=mejores)[0][-1]
    assert total["todas"]["beneficio"] == 20 and total["reales"]["beneficio"] == -7


def test_el_vigia_rellena_jornada_numero_y_previos_de_filas_ya_guardadas():
    """Filas de antes de esta version: sin numero de partido ni previos. Si
    son de esta semana se rellenan; las viejas, no."""
    import modelo.datos as md
    original = md.partidos_de_jornada
    md.partidos_de_jornada = lambda lineas: SEMANA.get(lineas, [])
    try:
        datos = SimpleNamespace(lineas=lambda j: j)
        sel_baetens = {"fecha": "2026-11-03", "j1": "Andy Baetens", "j2": "Y",
                       "resultado": "ganada", "seleccion_json": GANA_1}
        hoja = HojaMemoria(alertas=[dict(sel_baetens, tipo_aviso="apuesta")],
                           winamax=[sel_baetens, dict(sel_baetens, fecha="2026-10-20")])
        reloj = lambda: datetime(2026, 11, 4, 12, tzinfo=ZoneInfo("Europe/Madrid"))  # noqa: E731
        assert Vigia(hoja, None, datos, None, reloj=reloj).liquidar() == 0   # nada nuevo
    finally:
        md.partidos_de_jornada = original
    alerta = hoja.alertas()[0]
    assert (alerta["jornada"], alerta["n_partido"]) == ("Grupo A Martes", 2)
    nueva, vieja = hoja.filas_winamax()
    assert (nueva["n_partido"], nueva["previos_j1"], nueva["previos_j2"]) == (2, 2, 2)
    assert "previos_j1" not in vieja


def test_cuenta_la_ultima_lectura_que_pasaba_el_filtro_y_explica_el_resto():
    from vigia.registro import simulacion_todas
    filas = [
        _wm("4", 500, "A", 0.30, 10, "ganada"),         # pasaba el filtro...
        _wm("4", 600, "A", 0.05, 0, "ganada"),          # ...y en la ultima ya no
        _wm("5", 700, "A", 0.10, 0, "perdida"),         # nunca paso
        _wm("6", 800, "A", 0.40, 15, "", previos=(1, 4)),
        _wm("7", 900, "A", 0.40, 15, "", previos=("", "")),
    ]
    mejores, detalle = simulacion_todas(filas)
    assert [(m["match_id"], m["lectura"]) for m in mejores] == [("4", 500)]
    motivos = {d["partido"] + d["fecha"] + str(i): d["motivo"] for i, d in enumerate(detalle)}
    assert sum(d["cuenta"] for d in detalle) == 1 and len(detalle) == 4
    textos = " | ".join(motivos.values())
    assert "ninguna cuota llegaba" in textos and "poco fiable (1 y 4" in textos
    assert "sin dato de partidos previos" in textos
