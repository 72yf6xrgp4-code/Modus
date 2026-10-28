from datetime import datetime
from types import SimpleNamespace

import pytest

from modelo.motor import calcular_partido
from vigia.hoja import HojaMemoria
from vigia.nucleo import MADRID, Vigia
from vigia.registro import resumen_apuestas
from vigia.winamax import extraer_estado
from tests import winamax_sintetico as ws

AHORA = datetime(2026, 10, 29, 13, 0, tzinfo=MADRID)          # jueves
INICIO = int(datetime(2026, 10, 29, 14, 30, tzinfo=MADRID).timestamp())
FECHA = "2026-10-29"

BAETENS = {"nombre_original": "Andy Baetens", "PR": 62.0, "lam_180": 1.2, "volatilidad": 7.0}
MENZIES = {"nombre_original": "Cameron Menzies", "PR": 55.0, "lam_180": 0.9, "volatilidad": 9.5}


class Datos:
    def __init__(self, jugadores, calendario=None):
        self.jugadores = {v["nombre_original"].lower(): v for v in jugadores}
        self.calendario = calendario or {}
        self._hecho = False

    def refrescar(self, ahora, forzar=False):
        hecho, self._hecho = self._hecho, True
        return not hecho or forzar

    def partidos_calendario(self):
        for j, lista in self.calendario.items():
            for p in lista:
                yield j, p


class Cliente:
    """Winamax falso: devuelve siempre el mismo estado, pasando por el
    HTML para probar tambien extraer_estado."""
    def __init__(self, estado):
        self.html = ws.html(estado)
        self.pedidas = 0

    def estado_dardos(self):
        return extraer_estado(self.html)

    def estado_partido(self, match_id):
        self.pedidas += 1
        return extraer_estado(self.html)


class Notif:
    def __init__(self):
        self.textos = []

    def enviar(self, texto, urgente=False):
        self.textos.append(texto)
        return True


AJ = SimpleNamespace(torneo_palabras=["modus"], tope_diario=50.0, ventana_min=120)


def cuota_con_edge(p, edge):
    return round((1 + edge) / p, 2)


def montar(estado, alertas=None, jugadores=(BAETENS, MENZIES), calendario=None):
    hoja = HojaMemoria(alertas)
    notif = Notif()
    v = Vigia(Cliente(estado), hoja, notif, Datos(jugadores, calendario), AJ,
              reloj=lambda: AHORA)
    v.liquidar = lambda: 0
    return v, hoja, notif


def estado_ganador(edge=0.25, c1="Baetens, Andy", c2="Menzies, Cameron", **kw):
    p1 = calcular_partido(BAETENS, MENZIES)["p1"]
    cuota = cuota_con_edge(p1, edge)
    return ws.estado(c1=c1, c2=c2, inicio=INICIO, mercados_partido=[
        ("Ganador del partido", [(c1, "1", cuota if c1.startswith("Baetens") else 1.2),
                                 (c2, "2", cuota if c2.startswith("Baetens") else 1.2)]),
    ], **kw)


def test_un_solo_aviso_por_partido():
    v, hoja, notif = montar(estado_ganador())
    for _ in range(4):
        v.ciclo()
    alertas = hoja.alertas()
    assert len(alertas) == 1 and len(notif.textos) == 1
    a = alertas[0]
    assert a["seleccion"] == "Gana Baetens" and a["importe"] == 7.5
    assert a["estado"] == "pendiente" and a["verde"] == "🟢"
    assert notif.textos[0].startswith("🎯 14:30 Baetens vs Menzies · Gana Baetens @")
    assert "7,5 € · quedan 42,5 €" in notif.textos[0]
    assert len(notif.textos[0]) < 200


def _previa(importe, estado="pendiente", j1="A B", j2="C D"):
    return {"fecha": FECHA, "j1": j1, "j2": j2, "importe": importe,
            "tipo_aviso": "apuesta", "estado": estado, "resultado": ""}


def test_tope_recorta_a_lo_que_queda():
    previas = [_previa(7.5, j1=f"X{i}", j2=f"Y{i}") for i in range(6)] + [_previa(2.5)]
    v, hoja, notif = montar(estado_ganador(), previas)          # 47,5 gastados
    v.ciclo()
    nueva = hoja.alertas()[-1]
    assert nueva["importe"] == 2.5 and nueva["tope_restante"] == 0
    assert any("Tope" in t for t in notif.textos)               # aviso de tope


def test_con_tope_gastado_no_hay_aviso():
    previas = [_previa(7.5, j1=f"X{i}", j2=f"Y{i}") for i in range(6)] + [_previa(5)]
    v, hoja, notif = montar(estado_ganador(), previas)          # 50 gastados
    v.ciclo()
    v.ciclo()
    assert len(hoja.alertas()) == len(previas)
    assert notif.textos == ["🛑 Tope de 50 € alcanzado: no habrá más avisos hoy"]


def test_no_apostada_devuelve_su_importe_al_tope():
    previas = [_previa(7.5, j1=f"X{i}", j2=f"Y{i}") for i in range(6)] + \
              [_previa(5, estado="no apostada")]               # 45 gastados
    v, hoja, notif = montar(estado_ganador(), previas)
    v.ciclo()
    assert hoja.alertas()[-1]["importe"] == 5.0


def test_volatilidad_alta_descarta_el_partido():
    alto = dict(MENZIES, volatilidad=14.0)
    v, hoja, notif = montar(estado_ganador(), jugadores=(BAETENS, alto))
    v.ciclo()
    assert hoja.alertas() == [] and notif.textos == []
    assert any(l["tipo"] == "descartado" and "volatilidad alta" in l["detalle"]
               for l in hoja.logs)


def test_sin_edge_suficiente_no_avisa():
    v, hoja, notif = montar(estado_ganador(edge=0.05))
    v.ciclo()
    assert notif.textos == []


def test_otro_torneo_se_ignora():
    v, hoja, notif = montar(estado_ganador(torneo="Premier League"))
    v.ciclo()
    assert notif.textos == [] and v.cliente.pedidas == 0


def test_partido_empezado_o_lejano_no_se_mira():
    v, _, notif = montar(estado_ganador(status="LIVE"))
    v.ciclo()
    assert notif.textos == []
    lejos = ws.estado(inicio=INICIO + 6 * 3600, mercados_partido=[])
    v, _, _ = montar(lejos)
    v.ciclo()
    assert v.cliente.pedidas == 0


def test_j1_es_el_primero_del_cartel():
    # Winamax pone a Menzies primero, el cartel a Baetens
    cal = {"Grupo C Jueves": [{"j1": "Andy Baetens", "j2": "Cameron Menzies",
                               "estado": "pendiente"}]}
    v, hoja, notif = montar(estado_ganador(c1="Menzies, Cameron", c2="Baetens, Andy"),
                            calendario=cal)
    v.ciclo()
    a = hoja.alertas()[0]
    assert (a["j1"], a["j2"]) == ("Andy Baetens", "Cameron Menzies")
    assert a["orden_j1"] == "cartel" and a["jornada"] == "Grupo C Jueves"
    assert "J1 s/Winamax" not in notif.textos[0]


def test_fuera_del_calendario_se_usa_el_orden_de_winamax():
    v, hoja, notif = montar(estado_ganador(c1="Menzies, Cameron", c2="Baetens, Andy"))
    v.ciclo()
    a = hoja.alertas()[0]
    assert a["j1"] == "Cameron Menzies" and a["orden_j1"] == "winamax"
    assert notif.textos[0].endswith("J1 s/Winamax")


def test_margen_enorme_es_revisar_sin_importe():
    p1 = calcular_partido(BAETENS, MENZIES)["p1"]
    cuota = round(1 / (p1 - 0.25), 2)       # margen ~25 puntos
    est = ws.estado(inicio=INICIO, mercados_partido=[
        ("Ganador del partido", [("Baetens, Andy", "1", cuota), ("Menzies, Cameron", "2", 1.1)])])
    v, hoja, notif = montar(est)
    v.ciclo()
    a = hoja.alertas()[0]
    assert a["tipo_aviso"] == "revisar" and a["importe"] == 0
    assert notif.textos[0].startswith("⚠️ REVISAR")


def test_liquidar_y_resumen():
    import json
    sel = {"tipo": "handicap", "jugador": 1, "linea": -1.5}
    alertas = [
        {"fecha": FECHA, "j1": "Andy Baetens", "j2": "Cameron Menzies", "cuota": 2.0,
         "importe": 5.0, "tipo_aviso": "apuesta", "estado": "apostada", "resultado": "",
         "jornada": "Grupo C Jueves", "seleccion_json": json.dumps(sel)},
        {"fecha": FECHA, "j1": "Ross Smith", "j2": "Kai Gotthardt", "cuota": 1.8,
         "importe": 2.5, "tipo_aviso": "apuesta", "estado": "pendiente", "resultado": "",
         "jornada": "Grupo C Jueves",
         "seleccion_json": json.dumps({"tipo": "ganador", "jugador": 2})},
    ]
    hoja = HojaMemoria(alertas)
    v = Vigia(None, hoja, Notif(), Datos([]), AJ, reloj=lambda: AHORA)
    import modelo.datos as md
    lineas = [[""]] * 6 + [
        ["Cameron Menzies", "1", "0"], ["Andy Baetens", "4", "2"],   # cartel al reves
        ["Ross Smith", "4", "1"], ["Kai Gotthardt", "3", "0"],
    ]
    orig = md.descargar_lineas
    md.descargar_lineas = lambda j, timeout=8: lineas
    try:
        assert v.liquidar() == 2
    finally:
        md.descargar_lineas = orig
    a, b = hoja.alertas()
    assert a["resultado"] == "ganada" and a["beneficio"] == 5.0
    assert b["resultado"] == "perdida" and b["beneficio"] == -2.5
    real = resumen_apuestas(hoja.alertas(), solo_apostadas=True)
    todas = resumen_apuestas(hoja.alertas(), solo_apostadas=False)
    assert real["beneficio"] == 5.0 and real["roi"] == 1.0
    assert todas["beneficio"] == 2.5 and todas["acierto"] == 0.5
    assert todas["roi"] == pytest.approx(2.5 / 7.5)
