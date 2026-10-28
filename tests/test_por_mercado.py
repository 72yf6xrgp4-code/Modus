import pytest

from vigia.registro import nivel_partido, por_mercado, por_mercado_y_volatilidad


def _f(mercado, importe, cuota, resultado, estado="apostada", vol=(7, 9), edge=0.25):
    return {"tipo_aviso": "apuesta", "mercado": mercado, "importe": importe,
            "cuota": cuota, "resultado": resultado, "estado": estado,
            "vol_j1": vol[0], "vol_j2": vol[1], "edge": edge}


FILAS = [
    _f("Ganador", 7.5, 2.0, "ganada"),                          # +7,5
    _f("Ganador", 5, 1.8, "perdida", estado="no apostada"),      # -5 (solo "todas")
    _f("Hándicap", 7.5, 2.2, "ganada", vol=(14, 8), edge=0.30),  # alta: exige 24 %, baja a 5
    _f("Hándicap", 2.5, 2.0, "perdida", vol=(14, 8), edge=0.22), # alta: no llega al 24 %
    _f("Más 180s", 2.5, 3.0, "ganada", vol=(19, 8)),             # > 18: fuera con volatilidad
    _f("Más 180s", 2.5, 3.0, "", vol=("", 8)),                   # sin liquidar, sin dato
    {"tipo_aviso": "revisar", "mercado": "Ganador", "importe": 0},
]


def _g(grupos, mercado):
    return next(g for g in grupos if g["mercado"] == mercado)


def test_sin_volatilidad_por_mercado():
    grupos, excluidas = por_mercado(FILAS)
    assert excluidas == 0
    gan = _g(grupos, "Ganador")
    assert gan["todas"]["liq"] == 2 and gan["todas"]["beneficio"] == pytest.approx(2.5)
    assert gan["reales"]["liq"] == 1 and gan["reales"]["beneficio"] == pytest.approx(7.5)
    assert gan["todas"]["acierto"] == 0.5
    total = grupos[-1]
    assert total["mercado"] == "TOTAL" and total["todas"]["n"] == 6
    assert total["todas"]["apostado"] == pytest.approx(7.5 + 5 + 7.5 + 2.5 + 2.5)


def test_con_volatilidad_aplica_la_regla_del_vigia():
    grupos, excluidas = por_mercado(FILAS, con_volatilidad=True)
    assert excluidas == 3            # handicap sin edge, > 18 y sin dato
    h = _g(grupos, "Hándicap")
    assert h["todas"]["n"] == 1
    assert h["todas"]["apostado"] == 5.0                     # 7,5 -> 5 por volatilidad alta
    assert h["todas"]["beneficio"] == pytest.approx(5.0 * 1.2)
    assert "Más 180s" not in [g["mercado"] for g in grupos]


def test_por_nivel_y_filas_antiguas_con_texto():
    assert nivel_partido({"vol_j1": "bajo", "vol_j2": "medio"}) == "baja/media"
    assert nivel_partido({"vol_j1": 13.2, "vol_j2": 5}) == "alta"
    assert nivel_partido({"vol_j1": "", "vol_j2": 5}) == "sin dato"
    n = por_mercado_y_volatilidad(FILAS)
    assert n[("Hándicap", "alta")]["liq"] == 2 and n[("Hándicap", "alta")]["ganadas"] == 1
    assert n[("Ganador", "baja/media")]["liq"] == 2
    # Fila antigua con el nivel en texto: 'medio' vale para la regla
    viejas = [_f("Ganador", 5, 2.0, "ganada", vol=("bajo", "medio"))]
    assert por_mercado(viejas, con_volatilidad=True)[1] == 0
