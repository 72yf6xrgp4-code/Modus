"""Cuotas de Winamax por OddsPapi con respuestas reales (Davies - van de Pas,
Modus 30-10-2026, 17:30)."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vigia import oddspapi
from vigia.boton import decodificar, preparar

F = Path(__file__).parent / "fixtures"
ODDS = json.loads((F / "oddspapi_odds.json").read_text(encoding="utf-8"))
MERCADOS = json.loads((F / "oddspapi_mercados.json").read_text(encoding="utf-8"))
PARTIDOS = json.loads((F / "oddspapi_partidos.json").read_text(encoding="utf-8"))
NOMBRES_DB = ["David Davies", "Benito van de Pas", "Darren Beveridge", "Neil Duff"]
DAVIES = next(f for f in PARTIDOS if f["fixtureId"] == ODDS["fixtureId"])
AHORA = datetime(2026, 10, 30, 16, 25, tzinfo=timezone.utc).timestamp()


def _todas_activas():
    o = copy.deepcopy(ODDS)
    for m in o["bookmakerOdds"]["winamax.es"]["markets"].values():
        for s in m["outcomes"].values():
            s["players"]["0"]["active"] = True
    return o


def _selecciones(odds, cartel=(("David Davies", "Benito van de Pas"),)):
    datos = decodificar(oddspapi.codificar(oddspapi.traducir(odds, DAVIES, AHORA)))
    r = preparar(datos, NOMBRES_DB, cartel)
    return datos, r, {json.dumps(s["sel"], sort_keys=True): s["cuota"] for s in r["selecciones"]}


def _k(**sel):
    return json.dumps(sel, sort_keys=True)


def test_tabla_de_mercados_igual_que_el_catalogo():
    for m in MERCADOS:
        tipo, linea = oddspapi.mercado(m["marketId"])
        assert tipo == {"moneyline": "ganador", "moneyline-180s": "mas_180",
                        "totals": "total_legs", "spreads": "handicap"}[m["marketType"]]
        if linea is not None:
            assert linea == m["handicap"]
        # salida con el id del mercado = Over / jugador 1; la siguiente, Under / 2 / X
        nombre = {o["outcomeId"] - m["marketId"]: o["outcomeName"] for o in m["outcomes"]}
        esperado = {"totals": {0: "Over", 1: "Under"}, "moneyline-180s": {0: "1", 1: "X", 2: "2"}}
        assert nombre == esperado.get(m["marketType"], {0: "1", 1: "2"})
    assert oddspapi.mercado(12345) is None


def test_las_cuotas_suspendidas_no_se_usan():
    # En la respuesta real hándicaps y legs estaban suspendidos (a punto de empezar)
    datos, r, sel = _selecciones(ODDS)
    assert datos["f"] == "api" and datos["ns"] == 6 and datos["id"] == "76162502"
    assert datos["s"] == "PREMATCH" and r["orden"] == "cartel"
    assert sel == {_k(tipo="ganador", jugador=1): 1.56, _k(tipo="ganador", jugador=2): 2.25,
                   _k(tipo="mas_180", quien=1): 2.55, _k(tipo="mas_180", quien=0): 2.85,
                   _k(tipo="mas_180", quien=2): 2.55}


def test_los_cinco_mercados_y_el_handicap_de_180s():
    _, r, sel = _selecciones(_todas_activas())
    assert sel[_k(tipo="handicap", jugador=1, linea=-1.5)] == 1.94
    assert sel[_k(tipo="handicap", jugador=2, linea=1.5)] == 1.68
    # "Leg Handicap 0.5" de OddsPapi = Hándicap de 180 realizados de Winamax
    assert sel[_k(tipo="hcap_180", jugador=1, linea=0.5)] == 1.45
    assert sel[_k(tipo="hcap_180", jugador=2, linea=-0.5)] == 2.4
    assert sel[_k(tipo="total_legs", lado="mas", linea=5.5)] == 1.56
    assert sel[_k(tipo="total_legs", lado="menos", linea=5.5)] == 2.1
    assert len(sel) == 11 and not r["sin_asignar"]


def test_orden_del_cartel_al_reves():
    _, r, sel = _selecciones(_todas_activas(), cartel=(("Benito van de Pas", "David Davies"),))
    assert (r["j1"], r["j2"]) == ("Benito van de Pas", "David Davies")
    assert sel[_k(tipo="ganador", jugador=2)] == 1.56
    assert sel[_k(tipo="handicap", jugador=2, linea=-1.5)] == 1.94


def test_sin_cuotas_activas_o_sin_winamax():
    o = copy.deepcopy(ODDS)
    for m in o["bookmakerOdds"]["winamax.es"]["markets"].values():
        for s in m["outcomes"].values():
            s["players"]["0"]["active"] = False
    with pytest.raises(oddspapi.ErrorOddsPapi, match="suspendidas"):
        oddspapi.traducir(o, DAVIES, AHORA)
    with pytest.raises(oddspapi.ErrorOddsPapi, match="no tiene cuotas"):
        oddspapi.traducir(dict(ODDS, bookmakerOdds={}), DAVIES, AHORA)


def test_buscar_partido():
    assert oddspapi.buscar_partido(PARTIDOS, "Benito van de Pas", "David Davies") is DAVIES
    assert oddspapi.buscar_partido(PARTIDOS, "David Davies", "Neil Duff")["statusId"] == 2
    assert oddspapi.buscar_partido(PARTIDOS, "David Davies", "Archie Self") is None


def test_partidos_pide_la_modus_de_ayer_a_pasado_manana():
    pedido = {}

    def get(ruta, clave, **params):
        pedido.update(params, ruta=ruta)
        return PARTIDOS
    oddspapi.partidos("k", datetime(2026, 10, 30, 23, 0, tzinfo=timezone.utc), get=get)
    assert pedido == {"ruta": "fixtures", "tournamentId": 33994,
                      "from": "2026-10-29", "to": "2026-11-01"}


def test_juntar_con_la_lectura_del_boton():
    """La API no da 180s totales ni resultado exacto: se toman de la lectura
    anterior del boton del mismo partido, y se marcan para no contarlos en
    las estadisticas."""
    boton = {"f": "pagina", "c1": "Davies, David", "c2": "van de Pas, Benito", "h": 111,
             "mercados": [{"titulo": "Ganador", "salidas": [
                              {"label": "D. Davies", "code": "1", "cuota": 1.40},
                              {"label": "B. van de Pas", "code": "2", "cuota": 2.70}]},
                          {"titulo": "Total 180", "salidas": [
                              {"label": "Más de 2,5", "code": "", "cuota": 1.9},
                              {"label": "Menos de 2,5", "code": "", "cuota": 1.8}]}]}
    datos = oddspapi.juntar(oddspapi.traducir(ODDS, DAVIES, AHORA), boton)
    assert datos["bt"] == ["Total 180"] and datos["bh"] == 111
    d = decodificar(oddspapi.codificar(datos))
    assert d["bt"] == ["Total 180"]
    sel = {json.dumps(s["sel"], sort_keys=True): s["cuota"]
           for s in preparar(d, NOMBRES_DB, [("David Davies", "Benito van de Pas")])["selecciones"]}
    assert sel[_k(tipo="ganador", jugador=1)] == 1.56            # la de la API
    assert sel[_k(tipo="180_total", lado="mas", linea=2.5)] == 1.9
    # jugadores al reves: no se junta
    api = oddspapi.traducir(ODDS, DAVIES, AHORA)
    assert "bt" not in oddspapi.juntar(api, dict(boton, c1=boton["c2"], c2=boton["c1"]))
    # otra lectura de la API despues: arrastra solo lo que venia del boton
    otra = oddspapi.juntar(oddspapi.traducir(ODDS, DAVIES, AHORA + 60), d)
    assert otra["bt"] == ["Total 180"] and otra["bh"] == 111 and len(otra["m"]) == len(datos["m"])
    assert "bt" not in oddspapi.juntar(api, decodificar(oddspapi.codificar(api)))
