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
from vigia.boton import VERSION_BOTON, DatosNoValidos, casilla, decodificar, preparar

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


def _ejecutar(tmp_path, html, url=URL_PARTIDO, borrar_global=False, navegada=""):
    subprocess.run(["python", str(RAIZ / "boton" / "construir.py")], check=True,
                   capture_output=True)
    f = tmp_path / "pagina.html"
    f.write_text(html, encoding="utf-8")
    r = subprocess.run(["node", str(RUNNER), str(f), url,
                        str(RAIZ / "boton" / "marcador.txt"), "1" if borrar_global else "0",
                        navegada],
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
    assert res["ventana"] == "modus_app"          # siempre la misma pestana de Modus
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
    assert res["url"] is None and "no encuentro las cuotas" in res["alerta"]


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


FIXTURES = RAIZ / "tests" / "fixtures"


def _cuotas_ganador(d):
    return [s["cuota"] for m in d["mercados"] if m["titulo"] == "Ganador" for s in m["salidas"]]


@necesita_navegador
def test_llegando_navegando_lee_la_pantalla(tmp_path):
    """Sin estado de la pagina (has entrado al partido navegando dentro de
    Winamax): lee lo que se ve en pantalla, sin recargar."""
    html = (FIXTURES / "winamax_pantalla_modus.html").read_text(encoding="utf-8")
    res = _ejecutar(tmp_path, html, url="https://www.winamax.es/apuestas-deportivas/match/75997616")
    assert res["alerta"] is None
    d = decodificar(parse_qs(urlparse(res["url"]).query)["wm"][0])
    assert (d["c1"], d["c2"], d["f"], d["id"]) == ("Derek Coulson", "Andy Baetens", "pantalla", "75997616")
    assert _cuotas_ganador(d) == [1.46, 2.5]
    r = preparar(d, ["Derek Coulson", "Andy Baetens"], cartel=[("Derek Coulson", "Andy Baetens")])
    tipos = {s["sel"]["tipo"] for s in r["selecciones"]}
    assert {"ganador", "handicap", "mas_180", "180_total", "180_jugador"} <= tipos


@necesita_navegador
def test_la_pantalla_manda_sobre_el_estado_de_carga(tmp_path):
    """Pagina cargada hace rato: el estado dice 1,48 pero en pantalla ya
    pone 1,46. Manda la pantalla, y el estado completa lo que no se ve."""
    pantalla = (FIXTURES / "winamax_pantalla_modus.html").read_text(encoding="utf-8")
    estado = (FIXTURES / "winamax_partido_modus.html").read_text(encoding="utf-8")
    script = estado[estado.index("<script"):estado.index("</script>") + 9]
    html = pantalla.replace("</body>", script + "</body>")
    res = _ejecutar(tmp_path, html, url="https://www.winamax.es/apuestas-deportivas/match/75997616")
    d = decodificar(parse_qs(urlparse(res["url"]).query)["wm"][0])
    assert d["f"] == "pagina"
    assert _cuotas_ganador(d) == [1.46, 2.5]
    titulos = [m["titulo"] for m in d["mercados"]]
    assert "1er set - Marcador exacto (en legs)" in titulos      # solo en el estado
    assert titulos.index("1er set - Hándicap de legs") < titulos.index("Hándicap de legs")
    r = preparar(d, ["Derek Coulson", "Andy Baetens"])
    h = [s for s in r["selecciones"] if s["sel"] == {"tipo": "handicap", "jugador": 1, "linea": -1.5}]
    assert h[0]["cuota"] == 2.0                                   # la de pantalla


@necesita_navegador
def test_navegando_desde_otra_pagina_no_usa_cuotas_viejas(tmp_path):
    """La pagina se cargo en otra direccion (lista de partidos) y has llegado
    al partido navegando: el estado de carga trae cuotas viejas de ese
    partido. Solo cuenta lo que se ve; el estado, solo para los nombres."""
    pantalla = (FIXTURES / "winamax_pantalla_modus.html").read_text(encoding="utf-8")
    estado = (FIXTURES / "winamax_partido_modus.html").read_text(encoding="utf-8")
    script = estado[estado.index("<script"):estado.index("</script>") + 9]
    html = pantalla.replace("</body>", script + "</body>")
    res = _ejecutar(tmp_path, html, url="https://www.winamax.es/apuestas-deportivas/sports/1",
                    navegada="/apuestas-deportivas/match/75997616")
    assert res["alerta"] is None
    d = decodificar(parse_qs(urlparse(res["url"]).query)["wm"][0])
    assert (d["f"], d["c1"], d["b"], d["ne"]) == ("pantalla", "Derek Coulson", VERSION_BOTON, 0)
    assert _cuotas_ganador(d) == [1.46, 2.5]
    assert "1er set - Marcador exacto (en legs)" not in [m["titulo"] for m in d["mercados"]]


@necesita_navegador
def test_manda_su_version_y_cuantos_mercados_salen_del_estado(tmp_path):
    pantalla = (FIXTURES / "winamax_pantalla_modus.html").read_text(encoding="utf-8")
    estado = (FIXTURES / "winamax_partido_modus.html").read_text(encoding="utf-8")
    script = estado[estado.index("<script"):estado.index("</script>") + 9]
    res = _ejecutar(tmp_path, pantalla.replace("</body>", script + "</body>"),
                    url="https://www.winamax.es/apuestas-deportivas/match/75997616")
    d = decodificar(parse_qs(urlparse(res["url"]).query)["wm"][0])
    assert d["b"] == VERSION_BOTON and d["ne"] > 0 and d["e"] >= 0


def test_botones_antiguos_llegan_como_version_1():
    import base64
    viejo = {"v": 1, "c1": "A", "c2": "B", "m": [["Ganador", [["A", "1", 1.5]]]]}
    wm = base64.urlsafe_b64encode(json.dumps(viejo).encode()).decode().rstrip("=")
    assert decodificar(wm)["b"] == 1 < VERSION_BOTON


def test_boton_app_winamax_en_el_movil():
    from vigia.boton import enlace_app_winamax, sistema_movil
    android = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/130 Mobile"
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
    pc = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Edg/130"
    assert [sistema_movil(u) for u in (android, iphone, pc, None)] == ["android", "ios", None, None]
    web = "https://www.winamax.es/apuestas-deportivas/match/75997616"
    assert enlace_app_winamax("75997616", "ios") == "shortcuts://run-shortcut?name=Abrir%20Winamax"
    from vigia.boton import enlace_web_winamax
    assert enlace_web_winamax("75997616") == web
    a = enlace_app_winamax("75997616", "android")
    assert a.startswith("intent://www.winamax.es/apuestas-deportivas/match/75997616#Intent;")
    assert "scheme=https;" in a and a.endswith(";end")
    assert "S.browser_fallback_url=https%3A%2F%2Fwww.winamax.es%2Fapuestas-deportivas%2Fmatch%2F75997616" in a
    assert enlace_web_winamax("") == "https://www.winamax.es/apuestas-deportivas"
