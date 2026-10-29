import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from vigia.hoja import HojaMemoria
from vigia.nucleo import Vigia
from vigia.registro import estadisticas_winamax, por_numero_partido, tramo_partido

GANA_1 = json.dumps({"tipo": "ganador", "jugador": 1})


def _ap(n, resultado, estado="apostada", p=0.6, importe=5, cuota=2.0, **extra):
    return dict({"tipo_aviso": "apuesta", "n_partido": n, "resultado": resultado,
                 "estado": estado, "p_modelo": p, "importe": importe, "cuota": cuota}, **extra)


def test_tramos():
    assert [tramo_partido({"n_partido": n}) for n in (1, 3, 4, 9, 12, 13, 15, "", None)] == [
        "1.º-3.º", "1.º-3.º", "4.º-6.º", "7.º-9.º", "10.º-12.º", "13.º o más", "13.º o más",
        "sin dato", "sin dato"]


def test_por_numero_de_partido():
    filas = [_ap(1, "perdida"), _ap(2, "ganada"), _ap(14, "ganada", p=0.7),
             _ap(15, "ganada", estado="no apostada", importe=10),
             _ap("", "ganada"), dict(_ap(5, ""), tipo_aviso="otra cosa")]
    res = {g["tramo"]: g for g in por_numero_partido(filas)}
    assert list(res) == ["1.º-3.º", "13.º o más", "sin dato"]          # en orden
    assert res["1.º-3.º"]["todas"]["acierto"] == 0.5 and res["1.º-3.º"]["p_media"] == 0.6
    ult = res["13.º o más"]
    assert ult["todas"]["beneficio"] == 5 + 10 and ult["reales"]["beneficio"] == 5
    assert abs(ult["p_media"] - 0.65) < 1e-9 and ult["todas"]["acierto"] == 1.0


def test_winamax_por_numero_de_partido():
    base = {"titulo": "Ganador", "mercado": "Ganador", "fecha": "2026-11-05", "j1": "A", "j2": "B"}
    filas = [dict(base, lectura="1", salida="A", cuota=2.5, p_modelo=0.5, edge=0.25,
                  resultado="ganada", n_partido=2),
             dict(base, lectura="1", salida="B", cuota=1.6, p_modelo=0.5, edge=-0.2,
                  resultado="perdida", n_partido=2),
             dict(base, lectura="2", j1="C", salida="A", cuota=2.0, p_modelo=0.6, edge=0.2,
                  resultado="perdida", n_partido=11),
             dict(base, lectura="2", j1="C", salida="B", cuota=2.0, p_modelo=0.4, edge=-0.2,
                  resultado="ganada", n_partido=11)]
    p = {g["tramo"]: g for g in estadisticas_winamax(filas)["partidos"]}
    assert p["1.º-3.º"]["n"] == 2 and p["1.º-3.º"]["apuestas"] == 1
    assert p["1.º-3.º"]["ap_roi"] == 1.5                                # 2,5 - 1
    assert p["10.º-12.º"]["ap_roi"] == -1.0 and p["10.º-12.º"]["acierto"] == 0.5


def test_el_vigia_rellena_el_numero_de_partido_de_filas_ya_liquidadas():
    """Filas de antes de esta version: ya tienen resultado pero no numero
    de partido. Si son de esta semana se rellena; las viejas, no."""
    jornada = [{"orden": i, "j1": a, "j2": b, "legs1": 4, "legs2": 1, "t180_1": 1, "t180_2": 0,
                "estado": "terminado"}
               for i, (a, b) in enumerate([("X", "Y"), ("Andy Baetens", "Self")])]
    datos = SimpleNamespace(lineas=lambda j: j)
    import modelo.datos as md
    original = md.partidos_de_jornada
    md.partidos_de_jornada = lambda lineas: jornada
    try:
        hoja = HojaMemoria(alertas=[
            {"fecha": "2026-11-05", "j1": "Self", "j2": "Andy Baetens", "tipo_aviso": "apuesta",
             "resultado": "perdida", "seleccion_json": GANA_1},
            {"fecha": "2026-10-20", "j1": "Self", "j2": "Andy Baetens", "tipo_aviso": "apuesta",
             "resultado": "perdida", "seleccion_json": GANA_1}])
        reloj = lambda: datetime(2026, 11, 7, 12, tzinfo=ZoneInfo("Europe/Madrid"))  # noqa: E731
        assert Vigia(hoja, None, datos, None, reloj=reloj).liquidar() == 0   # nada nuevo
    finally:
        md.partidos_de_jornada = original
    nueva, vieja = hoja.alertas()
    assert (nueva["n_partido"], nueva["jornada"], nueva["resultado"]) == (2, "Grupo C Jueves", "perdida")
    assert "n_partido" not in vieja
