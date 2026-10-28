import json

import pytest

from modelo.motor import calcular_partido
from vigia.boton import casilla, seleccion_de_casilla
from vigia.cuotas import evaluar_cuotas, selecciones
from vigia.registro import estado_partido

CALC = calcular_partido({"PR": 63, "lam_180": 1.3}, {"PR": 55, "lam_180": 1.2})


def test_todas_las_casillas_tienen_seleccion():
    claves = ["vic_j1", "vic_j2", "legs_mas", "legs_menos", "mas_j1", "mas_emp", "mas_j2"]
    claves += [f"hcap_j{j}_{s}_{n}" for j in (1, 2) for s in ("pos", "neg") for n in (15, 25)]
    claves += [f"180_j{j}_{n}" for j in (1, 2) for n in ("05", "15", "neg05", "neg15")]
    claves += ["180_ambos_15", "180_ambos_25", "180_ambos_neg15", "180_ambos_neg25"]
    for k in claves:
        sel = seleccion_de_casilla(k)
        assert sel is not None and casilla(sel) == k, k
    assert seleccion_de_casilla("xyz") is None


def test_evaluar_cuotas_ordena_y_calcula_importe():
    p1 = CALC["p1"]
    cuotas = [({"tipo": "ganador", "jugador": 1}, round(1.25 / p1, 2), "casilla"),
              ({"tipo": "ganador", "jugador": 2}, 1.5, "casilla"),
              ({"tipo": "ganador", "jugador": 1}, 9.0, "winamax")]   # repetida: manda la 1a
    filas = evaluar_cuotas(CALC, cuotas, "Derek Coulson", "Andy Baetens")
    assert len(filas) == 2
    assert filas[0]["texto"] == "Gana Coulson" and filas[0]["ev"]["importe"] == 5.0
    assert filas[0]["origen"] == "casilla"
    assert filas[1]["ev"]["importe"] == 0


def test_estado_partido():
    sel = {"tipo": "ganador", "jugador": 1}
    filas = [
        {"fecha": "2026-11-05", "j1": "Andy Baetens", "j2": "Derek Coulson",
         "tipo_aviso": "apuesta", "estado": "no apostada",
         "seleccion_json": json.dumps({"tipo": "ganador", "jugador": 2})},
        {"fecha": "2026-11-05", "j1": "Andy Baetens", "j2": "Derek Coulson",
         "tipo_aviso": "apuesta", "estado": "apostada", "importe": 5,
         "seleccion_json": json.dumps(sel)},
        {"fecha": "2026-11-04", "j1": "Andy Baetens", "j2": "Derek Coulson",
         "tipo_aviso": "apuesta", "estado": "apostada",
         "seleccion_json": json.dumps(sel)},
    ]
    marcadas, apuesta = estado_partido(filas, "2026-11-05", "Derek Coulson", "Andy Baetens")
    assert marcadas == {json.dumps({"jugador": 2, "tipo": "ganador"}): "no apostada",
                        json.dumps(sel, sort_keys=True): "apostada"}
    assert apuesta is filas[1]
    assert estado_partido(filas, "2026-11-06", "Derek Coulson", "Andy Baetens") == ({}, None)
