from vigia import reglas

FECHA = "2026-11-05"


def _f(importe, estado="pendiente", j1="X", j2="Y", fecha=FECHA):
    return {"fecha": fecha, "j1": j1, "j2": j2, "importe": importe,
            "tipo_aviso": "apuesta", "estado": estado}


EV_75 = reglas.evaluar("ganador", 0.70, 1.75)   # 7,5 EUR


def test_tope_recorta_y_bloquea():
    previas = [_f(7.5, j1=f"A{i}") for i in range(6)] + [_f(2.5, j1="B")]   # 47,5
    assert reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_75) == (2.5, "")
    previas.append(_f(2.5, j1="C"))                                         # 50
    imp, motivo = reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_75)
    assert imp == 0 and "tope" in motivo


def test_no_apostada_devuelve_el_importe():
    previas = [_f(7.5, j1=f"A{i}") for i in range(6)] + [_f(7.5, "no apostada", j1="B")]
    assert reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_75) == (5.0, "")


def test_una_apuesta_por_partido():
    previas = [_f(2.5, j1="Self", j2="Andy Baetens")]
    imp, motivo = reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_75)
    assert imp == 0 and "ya hay" in motivo
    # Si se marco 'no apostada', se puede apuntar otra
    previas = [_f(2.5, "no apostada", j1="Self", j2="Andy Baetens")]
    assert reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_75)[0] == 7.5
    # Otro dia no cuenta
    previas = [_f(2.5, j1="Self", j2="Andy Baetens", fecha="2026-11-04")]
    assert reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_75)[0] == 7.5


def test_revisar_y_sin_edge():
    assert reglas.apuntar([], FECHA, "A", "B", reglas.evaluar("ganador", 0.8, 2.0))[0] == 0
    assert reglas.apuntar([], FECHA, "A", "B", reglas.evaluar("ganador", 0.6, 1.8))[0] == 0
