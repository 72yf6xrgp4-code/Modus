"""Vigia con OddsPapi: espera a que los dos jugadores tengan su ultimo
partido terminado y contado en sus estadisticas, pide las cuotas reales,
guarda la lectura y avisa una vez, con un aviso claro."""

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from vigia.aviso import componer, nombre_corto, repartir_tope
from vigia.hoja import HojaMemoria
from vigia.nucleo import Vigia

M = ZoneInfo("Europe/Madrid")
F = Path(__file__).parent / "fixtures"
ODDS = json.loads((F / "oddspapi_odds.json").read_text(encoding="utf-8"))
PARTIDOS = json.loads((F / "oddspapi_partidos.json").read_text(encoding="utf-8"))
AJ = SimpleNamespace(app_url="https://modusapp.streamlit.app", aviso_min_antes=10)
J = "Grupo C Viernes"
DAVIES = {"nombre_original": "David Davies", "PR": 72.0, "lam_180": 1.1, "volatilidad": 7.0,
          "semanas_historico": 2}
VDP = {"nombre_original": "Benito van de Pas", "PR": 48.0, "lam_180": 0.9, "volatilidad": 9.0,
       "semanas_historico": 3}


def _p(orden, j1, j2, estado="pendiente"):
    return {"orden": orden, "j1": j1, "j2": j2, "estado": estado, "legs1": 4, "legs2": 2,
            "t180_1": 1, "t180_2": 0}


class Datos:
    def __init__(self):
        self.jugadores = {"david davies": DAVIES, "benito van de pas": VDP}
        self.calendario = {J: [
            _p(0, "Benito van de Pas", "X"), _p(1, "David Davies", "Y"),
            _p(2, "Y", "Benito van de Pas"), _p(3, "X", "David Davies"),
            _p(4, "David Davies", "Benito van de Pas"),
        ]}
        self.contados = {"David Davies": 1, "Benito van de Pas": 2}

    def refrescar(self, ahora, forzar=False):
        return False

    def edad(self):
        return 0

    def lineas(self, jornada):
        return []

    def stats_jornada(self, jornada):
        return {n.lower(): {"nombre_original": n, "n_partidos": k}
                for n, k in self.contados.items()}


class Api:
    casa = "winamax.es"

    def __init__(self, odds):
        self.odds, self.pedidas = odds, []

    def partidos(self, ahora):
        self.pedidas.append("partidos")
        return PARTIDOS

    def cuotas(self, fixture_id):
        self.pedidas.append(fixture_id)
        return self.odds


class Notif:
    def __init__(self):
        self.enviados = []

    def enviar(self, texto, urgente=False, enlace=None, titulo=None, acciones=None):
        self.enviados.append({"texto": texto, "titulo": titulo, "enlace": enlace,
                              "acciones": acciones, "urgente": urgente})
        return True


def _montar(odds=ODDS):
    datos = Datos()
    cal = datos.calendario[J]
    for p in cal[:4]:
        p["estado"] = "terminado"
    cal[3]["estado"] = "en_juego"            # Davies aun jugando su anterior
    hoja, notif, api = HojaMemoria(), Notif(), Api(odds)
    v = Vigia(hoja, notif, datos, AJ, reloj=RELOJ, api=api)
    RELOJ.t = datetime(2026, 10, 30, 17, 10, tzinfo=M)
    return v, datos, hoja, notif, api


class Reloj:
    t = None

    def __call__(self):
        return self.t

    def mas(self, minutos):
        self.t += timedelta(minutes=minutos)


RELOJ = Reloj()


def test_espera_al_ultimo_partido_y_a_sus_estadisticas_y_avisa_una_vez():
    v, datos, hoja, notif, api = _montar()
    v.ciclo()
    assert api.pedidas == [] and notif.enviados == []        # Davies aun juega
    assert "aún aparece en juego" in v._esperas[next(iter(v._esperas))]
    datos.calendario[J][3]["estado"] = "terminado"
    v.ciclo()
    assert api.pedidas == []                                 # la hoja aun no lo cuenta
    assert "falta el último" in next(iter(v._esperas.values()))
    datos.contados["David Davies"] = 2
    v.ciclo()
    assert api.pedidas == ["partidos", "id1903399476162502"]
    assert len(notif.enviados) == 1
    n = notif.enviados[0]
    assert n["titulo"] == "💰 Davies – van de Pas · 17:30" and n["urgente"]
    assert n["texto"].startswith("✅ Gana Davies → ")
    assert "cuota 1,56 · aguanta hasta " in n["texto"]
    assert "⏱️ Grupo C Viernes · partido 5 · previsto 17:30" in n["texto"]
    assert "💶 Quedan 50 € del tope de hoy" in n["texto"]
    assert n["acciones"][1] == ("Winamax", "https://www.winamax.es/apuestas-deportivas/match/76162502")
    assert [d["tipo"] for d in hoja.logs] == ["aviso"]
    # Lectura guardada para las estadisticas: fiable (2 partidos + historico)
    filas = hoja.filas_winamax()
    assert filas and {f["fuente"] for f in filas} == {"vigia"}
    assert filas[0]["previos_j1"] == 2 and filas[0]["n_partido"] == 5
    assert len([f for f in filas if f.get("p_modelo")]) == 5 and "Gana Davies" in {f["seleccion"] for f in filas}
    # Ya avisado: no se vuelve a pedir ni a avisar
    v.ciclo()
    assert len(api.pedidas) == 2 and len(notif.enviados) == 1


def test_sin_value_guarda_la_lectura_una_vez_y_sigue_mirando_hasta_que_empiece():
    caras = copy.deepcopy(ODDS)
    for m in caras["bookmakerOdds"]["winamax.es"]["markets"].values():
        for s in m["outcomes"].values():
            s["players"]["0"]["price"] = 1.05
    v, datos, hoja, notif, api = _montar(caras)
    datos.calendario[J][3]["estado"] = "terminado"
    datos.contados["David Davies"] = 2
    v.ciclo()
    RELOJ.mas(1)
    v.ciclo()                                   # cada 3 minutos, no cada vuelta
    assert notif.enviados == [] and api.pedidas.count("id1903399476162502") == 1
    RELOJ.mas(2)
    v.ciclo()
    assert api.pedidas.count("id1903399476162502") == 2
    n_filas = len(hoja.filas_winamax())
    assert n_filas > 0
    # Empieza: OddsPapi lo marca en juego y ya no se pide
    caras["statusId"] = 1
    for _ in range(3):
        RELOJ.mas(3)
        v.ciclo()
    assert api.pedidas.count("id1903399476162502") == 3
    assert len(hoja.filas_winamax()) == n_filas
    assert api.pedidas.count("partidos") == 1   # la lista, una vez


def test_como_mucho_seis_lecturas_por_partido_y_solo_de_los_dos_siguientes():
    caras = copy.deepcopy(ODDS)
    for m in caras["bookmakerOdds"]["winamax.es"]["markets"].values():
        for s in m["outcomes"].values():
            s["players"]["0"]["price"] = 1.05
    v, datos, hoja, notif, api = _montar(caras)
    cal = datos.calendario[J]
    # Tres partidos sin empezar antes del suyo: aun no se piden sus cuotas
    for p in cal[:4]:
        p["estado"] = "pendiente"
    datos.contados = {"David Davies": 0, "Benito van de Pas": 0}
    cal[4].update(j1="David Davies", j2="Benito van de Pas")
    cal[:4] = [dict(p, j1="A" + str(i), j2="B" + str(i)) for i, p in enumerate(cal[:4])]
    v.ciclo()
    assert "id1903399476162502" not in api.pedidas
    assert "más de dos partidos" in v._esperas["David Davies vs Benito van de Pas (Grupo C Viernes, 5)"]
    for p in cal[:3]:
        p["estado"] = "terminado"
    for _ in range(10):
        v.ciclo()
        RELOJ.mas(3)
    assert api.pedidas.count("id1903399476162502") == 6


def test_empieza_sin_llegar_a_avisar_queda_en_el_log():
    v, datos, hoja, notif, api = _montar()
    v.ciclo()
    datos.calendario[J][4]["estado"] = "en_juego"
    v.ciclo()
    assert hoja.logs[-1]["tipo"] == "sin aviso"
    assert "en juego" in hoja.logs[-1]["detalle"]


def test_aviso_claro_con_tope_volatilidad_y_poco_fiable():
    ev = {"edge": 0.3, "verde": True, "importe": 15.0}
    apuestas = [{"texto": "Gana Davies", "cuota": 2.1, "p": 0.62, "ev": ev},
                {"texto": "Más de 5,5 legs", "cuota": 1.9, "p": 0.64,
                 "ev": dict(ev, edge=0.22, verde=False, importe=5.0)}]
    titulo, texto = componer("David Davies", "Benito van de Pas", apuestas, 0.22, "17:30",
                             "Grupo C Viernes", 13, queda=15, vol=13.0, rebaja=True,
                             info={"previos_j1": 1, "previos_j2": 4})
    assert titulo == "💰 Davies – van de Pas · 17:30"
    lineas = texto.split("\n")
    assert lineas[0] == "✅ Gana Davies → 15 €"
    assert lineas[1] == "cuota 2,10 · aguanta hasta 1,97 · edge +30 % 🟢"
    assert lineas[2] == "✅ Más de 5,5 legs → 0 € (tope)"
    assert "⛔ Tope de hoy alcanzado" not in texto and "💶 Quedan 15 €" in texto
    assert "⚠️ Volatilidad alta (13,0): edge exigido 22 %" in texto
    assert "⚠️ Poco fiable (David Davies: 1 partidos esta semana" in texto
    assert repartir_tope([10, 10], 12.5) == [10, 0]
    assert nombre_corto("Self") == "Self"
