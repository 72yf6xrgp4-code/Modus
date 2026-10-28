import pytest

from modelo import motor

DIST = {(4, 0): 0.149, (4, 1): 0.265, (4, 2): 0.187, (4, 3): 0.185,
        (3, 4): 0.074, (2, 4): 0.085, (1, 4): 0.036, (0, 4): 0.017}


def test_derivados_del_resultado_exacto():
    assert motor.prob_handicap(DIST, 1, -1.5) == pytest.approx(0.601)
    assert motor.prob_total_legs(DIST, 5.5, mas=True) == pytest.approx(0.531)
    assert motor.prob_total_legs(DIST, 6.5, mas=True) == pytest.approx(0.259)
    assert motor.prob_total_legs(DIST, 4.5, mas=False) == pytest.approx(0.166)


J1 = {"PR": 62.0, "lam_180": 1.4}
J2 = {"PR": 55.0, "lam_180": 0.8}


def test_probabilidad_coincide_con_las_funciones_de_la_app():
    """El vigia (probabilidad) y Value Bets (funciones de la app) dan lo
    mismo para las lineas que tiene la app."""
    calc = motor.calcular_partido(J1, J2)
    pr1, pr2, l1, l2 = J1["PR"], J2["PR"], J1["lam_180"], J2["lam_180"]
    v1, v2 = motor.prob_victoria(pr1, pr2)
    assert motor.probabilidad(calc, {"tipo": "ganador", "jugador": 1}) == v1
    assert motor.probabilidad(calc, {"tipo": "ganador", "jugador": 2}) == v2
    hc = motor.handicaps_legs(pr1, pr2)
    for jug in (1, 2):
        for h in (-1.5, -2.5, 1.5, 2.5):
            p = motor.probabilidad(calc, {"tipo": "handicap", "jugador": jug, "linea": h})
            assert p == pytest.approx(hc[f"J{jug} {h:+.1f} Legs"], abs=1e-12)
    lt = motor.legs_totales(pr1, pr2)
    assert motor.probabilidad(calc, {"tipo": "total_legs", "lado": "mas", "linea": 5.5}) \
        == pytest.approx(lt["Más de 5.5"], abs=1e-12)
    m = motor.prob_180s(l1, l2, pr1=pr1, pr2=pr2)
    assert motor.probabilidad(calc, {"tipo": "180_jugador", "jugador": 1, "lado": "mas", "linea": 0.5}) \
        == pytest.approx(m["J1 +0.5"], abs=1e-12)
    assert motor.probabilidad(calc, {"tipo": "180_jugador", "jugador": 2, "lado": "mas", "linea": 1.5}) \
        == pytest.approx(m["J2 +1.5"], abs=1e-12)
    assert motor.probabilidad(calc, {"tipo": "180_total", "lado": "mas", "linea": 2.5}) \
        == pytest.approx(m["Total +2.5"], abs=1e-12)
    pj1, pemp, pj2 = motor.quien_hace_mas_180s(l1, l2, pr1=pr1, pr2=pr2)
    assert motor.probabilidad(calc, {"tipo": "mas_180", "quien": 0}) == pemp
    assert sum(calc["dist"].values()) == pytest.approx(1.0)


def test_ventaja_de_saque_para_j1():
    a = motor.calcular_partido(J1, J2, j1_saca_primero=True)["p1"]
    b = motor.calcular_partido(J1, J2, j1_saca_primero=False)["p1"]
    assert a > b


def test_valores_de_referencia():
    """Fija los numeros actuales del modelo: si alguien cambia el motor o
    las constantes, este test avisa."""
    v1, _ = motor.prob_victoria(60, 50)
    assert v1 == pytest.approx(0.75504, abs=1e-5)
