import pytest

from modelo.motor import calcular_partido
from vigia import cuotas, reglas


def test_ejemplo_del_encargo():
    # p = 0,742: 1,10/p = 1,4825 -> 1,49 (redondeo hacia arriba: con 1,48
    # el edge seria 9,8 %); 🟢 ganador = 1/(0,742-0,06) = 1,466 -> 1,47
    c = reglas.cuotas_minimas("ganador", 0.742)
    assert c["aviso"] == 1.49
    assert c["verde"] == 1.47
    assert c["justa"] == 1.35
    assert c["eur_5"] == 1.55 and c["eur_7_5"] == 1.62


def test_la_cuota_minima_cumple_la_regla():
    for p in (0.12, 0.33, 0.5, 0.61, 0.742, 0.9):
        for edge in (0.10, 0.15, 0.20):
            c = reglas.cuota_minima(p, edge)
            assert p * c - 1 >= edge - 1e-12
            assert p * (c - 0.01) - 1 < edge


def test_verde_por_mercado():
    p = 0.60
    assert reglas.cuota_minima_verde("ganador", p) == reglas.redondear_arriba(1 / 0.54)
    assert reglas.cuota_minima_verde("total_legs", p) == reglas.redondear_arriba(1 / 0.52)
    assert reglas.cuota_minima_verde("handicap", p) == reglas.redondear_arriba(1 / 0.55)
    assert reglas.cuota_minima_verde("180s", p) == reglas.redondear_arriba(1 / 0.55)
    assert reglas.cuota_minima_verde("mas_180", p) == reglas.redondear_arriba(1 / 0.55)
    assert reglas.cuota_minima_verde("resultado", 0.30) is None   # nunca 🟢
    assert reglas.cuota_minima_verde("ganador", 0.05) is None      # p <= margen


def test_tabla_de_un_partido():
    calc = calcular_partido({"PR": 62, "lam_180": 1.2}, {"PR": 55, "lam_180": 0.9})
    filas = cuotas.tabla(calc, "Andy Baetens", "Cameron Menzies")
    assert len(filas) == len(cuotas.selecciones()) == 51
    tipos = {f["sel"]["tipo"] for f in filas}
    assert tipos == {"ganador", "handicap", "total_legs", "resultado",
                     "180_jugador", "180_total", "mas_180", "hcap_180"}
    for f in filas:
        assert f["aviso"] == reglas.cuota_minima(f["p"], 0.10)
        if f["mercado"] == "resultado":
            assert f["verde"] is None
    partes = cuotas.resumen_aviso(filas, "Andy Baetens", "Cameron Menzies")
    assert partes[0].startswith("Gana Baetens ≥") and partes[1].startswith("Baetens −1,5 ≥")
    assert "5,5 legs ≥" in partes[2]
