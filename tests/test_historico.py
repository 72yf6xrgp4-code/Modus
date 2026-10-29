from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from modelo.historico import (ajustar_jugadores, ajustar_volatilidad, combinar_con_historico,
                              referencia_volatilidad, resumen_historico, sabado_de_la_semana)
from modelo.volatilidad import nivel_volatilidad

M = ZoneInfo("Europe/Madrid")


def test_volatilidad_ajustada_por_tercios_de_tus_datos():
    # Casi todo por encima de 12 en la hoja: antes, todos "alto"
    valores = [14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25]
    assert all(nivel_volatilidad(v) == "alto" for v in valores)
    ref = referencia_volatilidad(valores + [0, "", "x"])   # sin datos: no cuentan
    p33, p67 = ref
    assert ajustar_volatilidad(p33, ref) == pytest.approx(8.0)
    assert ajustar_volatilidad(p67, ref) == pytest.approx(12.0)
    niveles = [nivel_volatilidad(ajustar_volatilidad(v, ref)) for v in valores]
    assert niveles.count("bajo") == niveles.count("medio") == niveles.count("alto") == 4
    assert ajustar_volatilidad(0, ref) == 0                 # sin datos sigue sin datos
    assert ajustar_volatilidad(17, None) == 17              # pocos datos: sin ajustar
    assert referencia_volatilidad([14, 15, 16]) is None


def test_ajustar_jugadores_guarda_el_valor_de_la_hoja():
    ref = (15.0, 20.0)
    j = ajustar_jugadores({"a": {"volatilidad": 20.0}}, ref)["a"]
    assert (j["volatilidad"], j["volatilidad_hoja"]) == (12.0, 20.0)
    # aplicarlo dos veces no ajusta lo ya ajustado
    assert ajustar_jugadores({"a": j}, ref)["a"]["volatilidad"] == 12.0


def _h(fecha, jugador, pr, partidos, vol="15", c180="0,8"):
    return {"Fecha sabado": fecha, "Jugador": jugador, "PR": pr, "Media 180s": c180,
            "Legs por partido": "5,9", "Promedio dardos": "92", "Checkout %": "38",
            "% Victorias": "50", "Volatilidad": vol, "Partidos jugados": partidos}


def test_resumen_historico_media_ponderada_y_sin_la_semana_actual():
    filas = [_h("2026-10-17", "Andy Baetens", "60", 10), _h("2026-10-24", "Andy Baetens", "66", 5),
             _h("2026-10-31", "Andy Baetens", "99", 5),        # esta semana: no cuenta
             _h("2026-10-24", "Self", "55", 0),                 # sin partidos: no cuenta
             _h("2026-10-24", "Ross Smith", "58", 5, c180="8")]  # coma perdida: 0,8
    h = resumen_historico(filas, antes_de="2026-10-31")
    b = h["andy baetens"]
    assert b["PR"] == pytest.approx((60 * 10 + 66 * 5) / 15) and b["n_historico"] == 15
    assert b["semanas"] == 2 and "self" not in h
    assert h["ross smith"]["lam_180"] == pytest.approx(0.8)


def test_el_historico_pesa_como_un_partido():
    hist = {"andy baetens": {"nombre_original": "Andy Baetens", "PR": 70.0, "lam_180": 1.0},
            "self": {"nombre_original": "Self", "PR": 50.0, "lam_180": 0.5}}
    semana = {"andy baetens": {"nombre_original": "Andy Baetens", "PR": 60.0, "lam_180": 0.0,
                               "n_partidos": 3},
              "cameron menzies": {"nombre_original": "Cameron Menzies", "PR": 55.0, "n_partidos": 4}}
    r = combinar_con_historico(semana, hist, nombres_extra=["Self", "Nadie"])
    b = r["andy baetens"]
    assert b["peso_historico"] == pytest.approx(0.25)                  # 1 / (1 + 3)
    assert b["PR"] == pytest.approx(0.25 * 70 + 0.75 * 60)
    assert b["lam_180"] == 1.0                                          # sin dato esta semana
    assert r["cameron menzies"]["peso_historico"] == 0 and r["cameron menzies"]["PR"] == 55
    s = r["self"]                                                       # solo historico
    assert s["solo_historico"] and s["PR"] == 50 and s["n_partidos"] == 0
    assert "nadie" not in r


def test_sabado_de_la_semana():
    assert sabado_de_la_semana(datetime(2026, 10, 26, tzinfo=M)) == "2026-10-31"   # lunes
    assert sabado_de_la_semana(datetime(2026, 10, 31, tzinfo=M)) == "2026-10-31"   # sabado
    assert sabado_de_la_semana(datetime(2026, 11, 1, tzinfo=M)) == "2026-10-31"    # domingo


def test_el_vigia_usa_el_historico(monkeypatch):
    """Lunes por la manana: el Resumen esta vacio (semana nueva). Con el
    historico, el vigia ya tiene datos de los jugadores del cartel."""
    import modelo.datos as md
    from vigia.nucleo import DatosSheet
    monkeypatch.setattr(md, "cargar_jugadores", lambda pestana: {})
    lineas = [[""]] * 6 + [["Andy Baetens", "", ""], ["Self", "", ""]]
    datos = DatosSheet(lector=lambda j: lineas,
                       historico=lambda: [_h("2026-10-31", "Andy Baetens", "62", 15),
                                          _h("2026-10-31", "Self", "57", 15),
                                          _h("2026-10-31", "Ross Smith", "50", 15)])
    datos.refrescar(datetime(2026, 11, 2, 10, 20, tzinfo=M), forzar=True)
    assert {v["nombre_original"] for v in datos.jugadores.values()} == {"Andy Baetens", "Self"}
    assert datos.jugadores["andy baetens"]["PR"] == pytest.approx(62)
