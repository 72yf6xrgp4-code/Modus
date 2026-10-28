import pytest

from vigia import reglas


@pytest.mark.parametrize("mercado,p,cuota,esperado", [
    ("ganador", 0.70, 1.70, 0),       # edge 19 %: no llega al 20 %
    ("ganador", 0.70, 1.75, 5.0),     # edge 22,5 % -> 5
    ("ganador", 0.70, 2.00, 10.0),    # edge 40 % y 🟢 -> 10
    ("ganador", 0.40, 3.80, 15.0),    # edge 52 % y 🟢, cuota <= 4 -> 15
    ("ganador", 0.30, 5.00, 5.0),     # edge 50 % pero cuota > 4 -> 5
    ("resultado", 0.20, 7.50, 5.0),   # edge 50 %: resultado exacto nunca 🟢 -> 5
    ("handicap", 0.55, 2.50, 10.0),   # edge 37,5 % y 🟢 -> 10
    ("total_legs", 0.50, 2.45, 5.0),  # edge 22,5 % -> 5
    ("180s", 0.25, 6.00, 5.0),        # edge 50 % pero cuota > 4 -> 5
])
def test_importe(mercado, p, cuota, esperado):
    assert reglas.importe(mercado, p, cuota) == esperado


def test_sin_edge_no_hay_importe():
    assert reglas.importe("ganador", 0.60, 1.95) == 0  # edge 17 %


def test_margen_grande_ya_no_es_revisar():
    # Caso real: Gana Self @2,00 con el modelo al 77,1 % (margen 27 puntos,
    # edge 54 %). Antes era "REVISAR" sin importe; ahora es apuesta de 15
    ev = reglas.evaluar("ganador", 0.771, 2.00)
    assert ev["revisar"] is False and ev["verde"] and ev["importe"] == 15.0


def test_volatilidad():
    r = reglas.requisito_volatilidad
    assert r("9", "11,9") == {"ok": True, "motivo": "", "vol": 11.9,
                              "edge_min": 0.20, "rebaja": False}       # medio/medio
    assert r(5, 7.9)["edge_min"] == 0.20                                # bajo/bajo
    assert r(12, 5)["rebaja"] is False                                  # 12 aun es medio
    # Alta: +2 puntos de edge por punto por encima de 12 (la del mas irregular)
    assert r("13", "9")["edge_min"] == pytest.approx(0.22)
    assert r(9, 15)["edge_min"] == pytest.approx(0.26)
    assert r("17", 8)["edge_min"] == pytest.approx(0.30)
    assert r(18, 8)["edge_min"] == pytest.approx(0.32) and r(18, 8)["rebaja"]
    # Por encima de 18, o sin dato, se descarta
    assert r(18.1, 8)["ok"] is False and "J1 volatilidad 18.1" in r(18.1, 8)["motivo"]
    assert r(0, 7) == {"ok": False, "motivo": "J1 sin datos de volatilidad",
                       "vol": None, "edge_min": None, "rebaja": False}
    assert r(7, "")["motivo"] == "J2 sin datos de volatilidad"


def test_volatilidad_alta_exige_mas_edge_y_baja_un_escalon():
    # 0,40 @3,80: edge 52 % y 🟢 -> 15; con volatilidad alta, 10
    assert reglas.importe("ganador", 0.40, 3.80, edge_min=0.26, rebaja=True) == 10.0
    # 0,70 @2,00: edge 40 % -> 10; con volatilidad alta, 5
    assert reglas.importe("ganador", 0.70, 2.00, edge_min=0.22, rebaja=True) == 5.0
    # 5 EUR no baja de 5
    assert reglas.importe("ganador", 0.70, 1.75, edge_min=0.22, rebaja=True) == 5.0
    # No llega al edge exigido (22,5 % < 26 %): nada
    assert reglas.importe("ganador", 0.70, 1.75, edge_min=0.26, rebaja=True) == 0
    # Importes antiguos (2,5 / 7,5) no suben al bajar de escalon
    assert reglas.bajar_escalon(2.5) == 2.5 and reglas.bajar_escalon(7.5) == 5.0


def test_cuotas_minimas_con_volatilidad_alta():
    normal = reglas.cuotas_minimas("ganador", 0.742)
    alta = reglas.cuotas_minimas("ganador", 0.742, edge_min=0.26, rebaja=True)
    assert alta["aviso"] == reglas.cuota_minima(0.742, 0.26) > normal["aviso"]
    assert alta["eur_10"] == reglas.cuota_minima(0.742, 0.50)   # hace falta el escalon de 15
    assert alta["eur_15"] is None
    assert alta["verde"] == normal["verde"]


def test_tope():
    assert reglas.aplicar_tope(15, 37.5) == 10     # quedan 12,5 -> 10
    assert reglas.aplicar_tope(15, 50) == 0
    assert reglas.aplicar_tope(10, 46) == 0         # quedan 4: menos de 5
    assert reglas.aplicar_tope(15, 40, tope=70) == 15


@pytest.mark.parametrize("sel,legs1,legs2,t1,t2,ok", [
    ({"tipo": "ganador", "jugador": 1}, 4, 2, 0, 0, True),
    ({"tipo": "ganador", "jugador": 2}, 4, 2, 0, 0, False),
    ({"tipo": "handicap", "jugador": 1, "linea": -1.5}, 4, 2, 0, 0, True),
    ({"tipo": "handicap", "jugador": 1, "linea": -1.5}, 4, 3, 0, 0, False),
    ({"tipo": "handicap", "jugador": 2, "linea": 1.5}, 4, 3, 0, 0, True),
    ({"tipo": "total_legs", "lado": "mas", "linea": 5.5}, 4, 2, 0, 0, True),
    ({"tipo": "total_legs", "lado": "menos", "linea": 5.5}, 4, 2, 0, 0, False),
    ({"tipo": "resultado", "legs1": 3, "legs2": 4}, 3, 4, 0, 0, True),
    ({"tipo": "180_jugador", "jugador": 2, "lado": "mas", "linea": 0.5}, 4, 0, 0, 1, True),
    ({"tipo": "180_total", "lado": "mas", "linea": 1.5}, 4, 0, 1, 0, False),
    ({"tipo": "mas_180", "quien": 0}, 4, 0, 1, 1, True),
])
def test_acierta(sel, legs1, legs2, t1, t2, ok):
    assert reglas.acierta(sel, legs1, legs2, t1, t2) is ok


def test_hcap_180():
    from modelo.motor import calcular_partido, probabilidad
    calc = calcular_partido({"PR": 60, "lam_180": 1.3}, {"PR": 55, "lam_180": 1.0})
    pj1, pemp, pj2 = calc["mas_180"]
    assert probabilidad(calc, {"tipo": "hcap_180", "jugador": 1, "linea": 0.5}) == pytest.approx(pj1 + pemp)
    assert probabilidad(calc, {"tipo": "hcap_180", "jugador": 2, "linea": -0.5}) == pj2
    assert reglas.acierta({"tipo": "hcap_180", "jugador": 1, "linea": 0.5}, 4, 0, 2, 2) is True
    assert reglas.acierta({"tipo": "hcap_180", "jugador": 2, "linea": -0.5}, 4, 0, 2, 2) is False
