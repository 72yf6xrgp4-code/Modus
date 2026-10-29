import json
from types import SimpleNamespace

import pytest

from vigia.hoja import HojaMemoria
from vigia.nucleo import Vigia
from vigia.registro import estadisticas_winamax


def _f(lectura, titulo, salida, cuota, p=None, edge=None, resultado="", mercado="Ganador",
       sel=None, j1="Andy Baetens", j2="Derek Coulson", previos=(3, 4)):
    return {"fecha": "2026-11-05", "lectura": lectura, "match_id": "900", "j1": j1, "j2": j2,
            "previos_j1": previos[0], "previos_j2": previos[1],
            "titulo": titulo, "salida": salida, "cuota": cuota, "mercado": mercado,
            "p_modelo": "" if p is None else p, "edge": "" if edge is None else edge,
            "resultado": resultado, "seleccion_json": json.dumps(sel) if sel else ""}


def test_estadisticas():
    filas = [
        # Primera lectura (se descarta: la del mismo partido mas reciente manda)
        _f(100, "Ganador", "A. Baetens", 1.9, 0.55, 0.045, "ganada"),
        _f(100, "Ganador", "D. Coulson", 1.9, 0.45, -0.145, "perdida"),
        # Ultima lectura
        _f(200, "Ganador", "A. Baetens", 2.0, 0.65, 0.30, "ganada"),
        _f(200, "Ganador", "D. Coulson", 1.8, 0.35, -0.37, "perdida"),
        _f(200, "Total 180", "Más de 2,5", 1.6, 0.70, 0.12, "perdida", mercado="180s totales"),
        _f(200, "Total 180", "Menos de 2,5", 2.3, 0.30, -0.31, "ganada", mercado="180s totales"),
        _f(200, "1er leg", "Rojo", 1.4, mercado=""),             # sin asignar: solo margen
        _f(200, "1er leg", "Verde", 2.55, mercado=""),
    ]
    # Partido poco fiable (un jugador con 2 partidos previos): no cuenta
    filas.append(dict(_f(300, "Ganador", "R. Smith", 3.0, 0.5, 0.5, "ganada", previos=(2, 5)),
                      match_id="901"))
    e = estadisticas_winamax(filas)
    assert e["resumen"] == {"lecturas": 1, "cuotas": 6, "liquidadas": 4}
    margen = {m["mercado"]: m["margen"] for m in e["margen"]}
    assert margen["Ganador"] == pytest.approx(1 / 2.0 + 1 / 1.8 - 1)
    assert margen["1er leg"] == pytest.approx(1 / 1.4 + 1 / 2.55 - 1)
    prec = {p["mercado"]: p for p in e["precision"]}
    q = (1 / 2.0) / (1 / 2.0 + 1 / 1.8)     # probabilidad de Winamax sin margen
    assert prec["Ganador"]["brier_modelo"] == pytest.approx(((0.65 - 1) ** 2 + 0.35 ** 2) / 2)
    assert prec["Ganador"]["brier_winamax"] == pytest.approx(((q - 1) ** 2 + (1 - q) ** 2) / 2)
    assert prec["Ganador"]["mejor"] == "modelo" and prec["TOTAL"]["n"] == 4
    tramos = {t["nombre"]: t for t in e["tramos"]}
    assert tramos["20-35 %"]["n"] == 1 and tramos["20-35 %"]["beneficio"] == pytest.approx(1.0)
    assert tramos["10-20 %"]["beneficio"] == -1.0 and tramos["negativo"]["n"] == 2
    assert [m["nombre"] for m in e["mercados"]] == ["Ganador"]


def test_el_vigia_apunta_el_resultado_de_las_cuotas_guardadas():
    gana_baetens = {"tipo": "ganador", "jugador": 1}
    mas_180 = {"tipo": "180_total", "lado": "mas", "linea": 2.5}
    filas = [_f(1, "Ganador", "A. Baetens", 2.0, 0.6, 0.2, sel=gana_baetens),
             _f(1, "Total 180", "Más de 2,5", 1.7, 0.5, -0.15, sel=mas_180),
             _f(1, "1er leg", "Rojo", 1.4, mercado=""),                       # sin asignar: no se toca
             _f(1, "Ganador", "R. Smith", 2.0, 0.5, 0.0, sel=gana_baetens,
                j1="Ross Smith", j2="Self")]                          # sin terminar
    hoja = HojaMemoria(winamax=filas)
    lineas = [[""]] * 6 + [["Derek Coulson", "2", "1"], ["Andy Baetens", "4", "1"],
                           ["Ross Smith", "1", "0"], ["Self", "1", "0"]]
    datos = SimpleNamespace(lineas=lambda j: lineas)
    v = Vigia(hoja, None, datos, SimpleNamespace(), reloj=lambda: None)
    v._log = lambda *a, **k: None
    assert v.liquidar() == 2
    res = [f["resultado"] for f in hoja.filas_winamax()]
    assert res == ["ganada", "perdida", "", ""]
