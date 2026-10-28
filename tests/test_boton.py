"""Boton "Modus value": datos que llegan a la app y el propio marcador.

Las pruebas del marcador ejecutan boton/marcador.txt en Chromium (Playwright
de Node) sobre paginas locales que imitan winamax.es: todas las peticiones
se interceptan, no sale nada hacia Winamax. Si no hay Node con Playwright,
se saltan.

Pagina real: guarda la pagina de un partido con Ctrl+S como
tests/fixtures/winamax_partido.html (o cualquier winamax_*.html).
"""

import base64
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tests import winamax_sintetico as ws
from vigia.boton import DatosNoValidos, casilla, decodificar, preparar

RAIZ = Path(__file__).resolve().parent.parent
RUNNER = RAIZ / "tests" / "js" / "probar_marcador.js"
NOMBRES = ["Andy Baetens", "Cameron Menzies", "Self", "Ross Smith"]


def _wm(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


DATOS = {"v": 1, "id": "900", "c1": "Menzies, Cameron", "c2": "Baetens, Andy",
         "t": 2_000_000_000, "s": "PREMATCH", "h": 1, "m": [
             ["Ganador del partido", [["Menzies, Cameron", "1", 2.6], ["Baetens, Andy", "2", 1.5]]],
             ["Hándicap de legs", [["Baetens (-1,5)", "2", 2.1], ["Menzies (+1,5)", "1", 1.7]]],
             ["Total de legs", [["Más de 5,5", "", 1.9], ["Menos de 5,5", "", 1.9]]],
             ["Resultado exacto", [["4-2", "", 6.5]]],
             ["Primer 180 del partido", [["Baetens, Andy", "2", 1.8]]],
         ]}


def test_decodificar_y_preparar_con_cartel():
    d = decodificar(_wm(DATOS))
    r = preparar(d, NOMBRES, cartel=[("Andy Baetens", "Cameron Menzies")])
    assert (r["j1"], r["j2"], r["orden"]) == ("Andy Baetens", "Cameron Menzies", "cartel")
    sels = {json.dumps(s["sel"], sort_keys=True): s["cuota"] for s in r["selecciones"]}
    assert sels[json.dumps({"tipo": "ganador", "jugador": 1}, sort_keys=True)] == 1.5
    assert sels[json.dumps({"tipo": "ganador", "jugador": 2}, sort_keys=True)] == 2.6
    assert sels[json.dumps({"tipo": "handicap", "jugador": 1, "linea": -1.5}, sort_keys=True)] == 2.1
    # Winamax pone a Menzies primero: el 4-2 es de Menzies -> 2-4 para J1 Baetens
    assert sels[json.dumps({"tipo": "resultado", "legs1": 2, "legs2": 4}, sort_keys=True)] == 6.5
    assert r["sin_asignar"] == [("Primer 180 del partido", "Baetens, Andy", 1.8)]


def test_sin_cartel_manda_el_orden_de_winamax():
    r = preparar(decodificar(_wm(DATOS)), NOMBRES, cartel=[])
    assert (r["j1"], r["orden"]) == ("Cameron Menzies", "winamax")


@pytest.mark.parametrize("malo", [
    "", "%%%", _wm({"v": 2}), _wm(dict(DATOS, c1="")), _wm(dict(DATOS, m=[])),
    _wm(dict(DATOS, m=[["Ganador", [["X", "1", "abc"]]]])),
    _wm(dict(DATOS, m=[["Ganador", [["X", "1", 0.5]]]])),
])
def test_datos_malos_dan_error_nunca_cuotas(malo):
    with pytest.raises(DatosNoValidos):
        decodificar(malo)


def test_jugador_desconocido():
    with pytest.raises(DatosNoValidos):
        preparar(decodificar(_wm(dict(DATOS, c2="Desconocido, Fulano"))), NOMBRES)


def test_casillas_de_value_bets():
    assert casilla({"tipo": "ganador", "jugador": 2}) == "vic_j2"
    assert casilla({"tipo": "handicap", "jugador": 1, "linea": -1.5}) == "hcap_j1_neg_15"
    assert casilla({"tipo": "handicap", "jugador": 2, "linea": 2.5}) == "hcap_j2_pos_25"
    assert casilla({"tipo": "handicap", "jugador": 2, "linea": -3.5}) is None
    assert casilla({"tipo": "total_legs", "lado": "menos", "linea": 5.5}) == "legs_menos"
    assert casilla({"tipo": "total_legs", "lado": "mas", "linea": 6.5}) is None
    assert casilla({"tipo": "180_jugador", "jugador": 1, "lado": "menos", "linea": 0.5}) == "180_j1_neg05"
    assert casilla({"tipo": "180_total", "lado": "mas", "linea": 2.5}) == "180_ambos_25"
    assert casilla({"tipo": "mas_180", "quien": 0}) == "mas_emp"
    assert casilla({"tipo": "resultado", "legs1": 4, "legs2": 0}) is None


# ── el marcador de verdad, en un navegador ────────────────────────────────

def _hay_playwright():
    if not shutil.which("node"):
        return False
    r = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True)
    return r.returncode == 0


necesita_navegador = pytest.mark.skipif(not _hay_playwright(),
                                        reason="sin Node + Playwright")
URL_PARTIDO = "https://www.winamax.es/apuestas-deportivas/match/900"


def _ejecutar(tmp_path, html, url=URL_PARTIDO, borrar_global=False):
    subprocess.run(["python", str(RAIZ / "boton" / "construir.py")], check=True,
                   capture_output=True)
    f = tmp_path / "pagina.html"
    f.write_text(html, encoding="utf-8")
    r = subprocess.run(["node", str(RUNNER), str(f), url,
                        str(RAIZ / "boton" / "marcador.txt"), "1" if borrar_global else "0"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _estado():
    return ws.estado(match_id="900", c1="Menzies, Cameron", c2="Baetens, Andy",
                     mercados_partido=[
                         ("Ganador del partido", [("Menzies, Cameron", "1", 2.6),
                                                  ("Baetens, Andy", "2", 1.5)]),
                         ("Total de legs", [("Más de 5,5", "", 1.9), ("Menos de 5,5", "", 1.9)]),
                     ])


@necesita_navegador
@pytest.mark.parametrize("borrar_global", [False, True])
def test_marcador_lee_las_cuotas_de_la_pagina(tmp_path, borrar_global):
    res = _ejecutar(tmp_path, ws.html(_estado()), borrar_global=borrar_global)
    assert res["alerta"] is None
    q = parse_qs(urlparse(res["url"]).query)
    assert res["url"].startswith("https://modusapp.streamlit.app/?seccion=value&wm=")
    d = decodificar(q["wm"][0])
    assert (d["c1"], d["c2"], d["id"]) == ("Menzies, Cameron", "Baetens, Andy", "900")
    assert d["mercados"][0]["salidas"][1] == {"label": "Baetens, Andy", "code": "2", "cuota": 1.5}
    r = preparar(d, NOMBRES, cartel=[("Andy Baetens", "Cameron Menzies")])
    assert r["j1"] == "Andy Baetens" and len(r["selecciones"]) == 4


@necesita_navegador
def test_marcador_sin_cuotas_avisa_y_no_envia(tmp_path):
    res = _ejecutar(tmp_path, "<html><body>Winamax ha cambiado</body></html>")
    assert res["url"] is None and "no encuentro las cuotas" in res["alerta"]
    sin_cuotas = _estado()
    sin_cuotas["odds"] = {}
    res = _ejecutar(tmp_path, ws.html(sin_cuotas))
    assert res["url"] is None and "ninguna cuota" in res["alerta"]


PAGINAS_REALES = sorted((RAIZ / "tests" / "fixtures").glob("winamax_*.htm*"))


@necesita_navegador
@pytest.mark.skipif(not PAGINAS_REALES, reason="falta una página de Winamax guardada con Ctrl+S")
@pytest.mark.parametrize("ruta", PAGINAS_REALES, ids=[p.name for p in PAGINAS_REALES])
def test_pagina_real_guardada(tmp_path, ruta):
    # La pagina guardada no lleva el /match/ID en la direccion: el marcador
    # usa el unico partido con apuestas.
    res = _ejecutar(tmp_path, ruta.read_text(encoding="utf-8", errors="ignore"),
                    url="https://www.winamax.es/pagina-guardada")
    assert res["alerta"] is None, res["alerta"]
    d = decodificar(parse_qs(urlparse(res["url"]).query)["wm"][0])
    tipos = {s["sel"]["tipo"] for s in preparar(d, [d["c1"], d["c2"]])["selecciones"]}
    assert "ganador" in tipos
