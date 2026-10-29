from vigia import reglas

FECHA = "2026-11-05"


def _f(importe, estado="pendiente", j1="X", j2="Y", fecha=FECHA):
    return {"fecha": fecha, "j1": j1, "j2": j2, "importe": importe,
            "tipo_aviso": "apuesta", "estado": estado}


EV_15 = reglas.evaluar("ganador", 0.70, 2.00)   # 1/4 de Kelly 20 EUR y 🟢: 15 EUR


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


def test_varias_apuestas_en_el_mismo_partido():
    # Ya no hay limite de una por partido: lo decides tu
    previas = [_f(2.5, j1="Self", j2="Andy Baetens")]
    assert reglas.apuntar(previas, FECHA, "Andy Baetens", "Self", EV_15) == (15.0, "")


def test_importe_cambiado_a_mano():
    from vigia.registro import (beneficio_real, gastado_del_dia, por_mercado,
                                resumen_apuestas)
    # Recomendado 5, apostaste 20: cuenta 20 en el tope y en lo real...
    f = dict(_f(5, "apostada", fecha="2026-11-04"), importe_real="20", cuota=2.0,
             resultado="ganada", mercado="Ganador")
    assert gastado_del_dia([f], "2026-11-04") == 20
    assert beneficio_real([f]) == 20
    real = resumen_apuestas([f], solo_apostadas=True)
    assert (real["invertido"], real["beneficio"]) == (20, 20)
    # ...pero las estadisticas del modelo siguen con el recomendado
    todas = resumen_apuestas([f], solo_apostadas=False)
    assert (todas["invertido"], todas["beneficio"]) == (5, 5)
    total = por_mercado([f])[0][-1]
    assert total["todas"]["beneficio"] == 5 and total["reales"]["beneficio"] == 20
    # Sin importe_real, lo apostado es el recomendado
    assert gastado_del_dia([dict(f, importe_real="")], "2026-11-04") == 5
    # Una 'no apostada' no gasta aunque tenga importe_real
    assert gastado_del_dia([dict(f, estado="no apostada")], "2026-11-04") == 0


def test_sin_edge_y_margen_grande():
    assert reglas.apuntar([], FECHA, "A", "B", reglas.evaluar("ganador", 0.6, 1.95))[0] == 0
    # Margen de mas de 20 puntos: ahora se apunta normal
    assert reglas.apuntar([], FECHA, "A", "B", reglas.evaluar("ganador", 0.771, 2.0)) == (15.0, "")
