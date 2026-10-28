from vigia import reglas

FECHA = "2026-11-05"


def _f(importe, estado="pendiente", j1="X", j2="Y", fecha=FECHA):
    return {"fecha": fecha, "j1": j1, "j2": j2, "importe": importe,
            "tipo_aviso": "apuesta", "estado": estado}


EV_15 = reglas.evaluar("ganador", 0.40, 3.80)   # edge 52 % y 🟢: 15 EUR


def test_tope_recorta_y_bloquea():
    previas = [_f(5, j1=f"A{i}") for i in range(9)]                       # 45
    assert reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_15) == (5.0, "")
    previas.append(_f(5, j1="C"))                                          # 50
    imp, motivo = reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_15)
    assert imp == 0 and "tope" in motivo


def test_el_tope_crece_con_el_beneficio_real():
    from vigia.registro import tope_del_dia
    ganada = dict(_f(10, "apostada", j1="X", fecha="2026-11-04"), cuota=3.0, resultado="ganada")
    assert tope_del_dia([ganada]) == 70.0                                  # 50 + 20
    perdida = dict(_f(10, "apostada", j1="Y", fecha="2026-11-04"), cuota=2.0, resultado="perdida")
    assert tope_del_dia([perdida]) == 50.0                                 # en perdidas: 50
    no_apostada = dict(ganada, estado="no apostada")
    assert tope_del_dia([no_apostada]) == 50.0                             # solo lo real
    hoy = [ganada] + [_f(5, j1=f"A{i}") for i in range(10)]                # 50 gastados
    assert reglas.apuntar(hoy, FECHA, "Andy Baetens", "Self", EV_15) == (15.0, "")


def test_no_apostada_devuelve_el_importe():
    previas = [_f(5, j1=f"A{i}") for i in range(8)] + [_f(10, "no apostada", j1="B")]
    assert reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_15) == (10.0, "")


def test_una_apuesta_por_partido():
    previas = [_f(2.5, j1="Self", j2="Andy Baetens")]
    imp, motivo = reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_15)
    assert imp == 0 and "ya hay" in motivo
    # Si se marco 'no apostada', se puede apuntar otra
    previas = [_f(2.5, "no apostada", j1="Self", j2="Andy Baetens")]
    assert reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_15)[0] == 15
    # Otro dia no cuenta
    previas = [_f(2.5, j1="Self", j2="Andy Baetens", fecha="2026-11-04")]
    assert reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_15)[0] == 15


def test_revisar_y_sin_edge():
    assert reglas.apuntar([], FECHA, "A", "B", reglas.evaluar("ganador", 0.8, 2.0))[0] == 0
    assert reglas.apuntar([], FECHA, "A", "B", reglas.evaluar("ganador", 0.6, 1.95))[0] == 0
