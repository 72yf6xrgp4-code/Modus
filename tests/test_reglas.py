import pytest

from vigia import reglas


@pytest.mark.parametrize("mercado,p,cuota,esperado", [
    ("ganador", 0.70, 1.62, 2.5),
    ("ganador", 0.70, 1.70, 5.0),
    ("ganador", 0.70, 1.75, 7.5),
    ("ganador", 0.35, 3.40, 2.5),     # margen 5,6 < 6 -> no 🟢
    ("ganador", 0.40, 3.20, 7.5),
    ("resultado", 0.20, 6.50, 2.5),   # resultado exacto nunca 🟢
    ("handicap", 0.60, 1.95, 5.0),
    ("total_legs", 0.60, 1.90, 2.5),  # margen 7,4 < 8
    ("180s", 0.30, 4.50, 2.5),        # cuota > 4
])
def test_importe(mercado, p, cuota, esperado):
    assert reglas.importe(mercado, p, cuota) == esperado


def test_sin_edge_no_hay_importe():
    assert reglas.importe("ganador", 0.60, 1.80) == 0  # edge 8 %


def test_revisar_si_margen_mayor_de_20():
    ev = reglas.evaluar("ganador", 0.80, 2.00)  # margen 30 puntos
    assert ev["revisar"] and ev["importe"] == 0


def test_volatilidad():
    r = reglas.requisito_volatilidad
    assert r("9", "11,9") == {"ok": True, "motivo": "", "vol": 11.9,
                              "edge_min": 0.10, "rebaja": False}       # medio/medio
    assert r(5, 7.9)["edge_min"] == 0.10                                # bajo/bajo
    assert r(12, 5)["rebaja"] is False                                  # 12 aun es medio
    # Alta: +2 puntos de edge por punto por encima de 12 (la del mas irregular)
    assert r("13", "9")["edge_min"] == pytest.approx(0.12)
    assert r(9, 15)["edge_min"] == pytest.approx(0.16)
    assert r("17", 8)["edge_min"] == pytest.approx(0.20)
    assert r(18, 8)["edge_min"] == pytest.approx(0.22) and r(18, 8)["rebaja"]
    # Por encima de 18, o sin dato, se descarta
    assert r(18.1, 8)["ok"] is False and "J1 volatilidad 18.1" in r(18.1, 8)["motivo"]
    assert r(0, 7) == {"ok": False, "motivo": "J1 sin datos de volatilidad",
                       "vol": None, "edge_min": None, "rebaja": False}
    assert r(7, "")["motivo"] == "J2 sin datos de volatilidad"


def test_volatilidad_alta_exige_mas_edge_y_baja_un_escalon():
    # 0,70 @1,75: edge 22,5 % y 🟢 -> 7,5 EUR; con volatilidad alta, 5 EUR
    assert reglas.importe("ganador", 0.70, 1.75) == 7.5
    assert reglas.importe("ganador", 0.70, 1.75, edge_min=0.16, rebaja=True) == 5.0
    # 0,70 @1,70: edge 19 % -> 5 EUR; con volatilidad alta, 2,5 EUR
    assert reglas.importe("ganador", 0.70, 1.70, edge_min=0.12, rebaja=True) == 2.5
    # 2,5 EUR no baja de 2,5
    assert reglas.importe("ganador", 0.70, 1.62, edge_min=0.12, rebaja=True) == 2.5
    # No llega al edge exigido (13,4 % < 16 %): nada
    assert reglas.importe("ganador", 0.70, 1.62, edge_min=0.16, rebaja=True) == 0


def test_cuotas_minimas_con_volatilidad_alta():
    normal = reglas.cuotas_minimas("ganador", 0.742)
    alta = reglas.cuotas_minimas("ganador", 0.742, edge_min=0.16, rebaja=True)
    assert alta["aviso"] == reglas.cuota_minima(0.742, 0.16) > normal["aviso"]
    assert alta["eur_5"] == reglas.cuota_minima(0.742, 0.20)   # hace falta el escalon de 7,5
    assert alta["eur_7_5"] is None
    assert alta["verde"] == normal["verde"]


def test_tope():
    assert reglas.aplicar_tope(7.5, 47.5) == 2.5
    assert reglas.aplicar_tope(7.5, 50) == 0
    assert reglas.aplicar_tope(5, 46) == 2.5   # quedan 4 -> 2,5


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
