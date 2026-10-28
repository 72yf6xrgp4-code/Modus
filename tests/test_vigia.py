from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from vigia.hoja import HojaMemoria
from vigia.nucleo import Vigia

M = ZoneInfo("Europe/Madrid")
BAETENS = {"nombre_original": "Andy Baetens", "PR": 62.0, "lam_180": 1.2, "volatilidad": 7.0}
MENZIES = {"nombre_original": "Cameron Menzies", "PR": 55.0, "lam_180": 0.9, "volatilidad": 9.5}
SELF = {"nombre_original": "Self", "PR": 58.0, "lam_180": 1.0, "volatilidad": 13.0}
SMITH = {"nombre_original": "Ross Smith", "PR": 50.0, "lam_180": 1.0, "volatilidad": 0}

AJ = SimpleNamespace(app_url="https://modusapp.streamlit.app", duracion_partido_min=10,
                     aviso_min_antes=45, tope_diario=50.0)


class Datos:
    def __init__(self, jugadores, calendario):
        self.jugadores = {v["nombre_original"].lower(): v for v in jugadores}
        self.calendario = calendario

    def refrescar(self, ahora, forzar=False):
        return False


class Notif:
    def __init__(self):
        self.enviados = []

    def enviar(self, texto, urgente=False, enlace=None):
        self.enviados.append((texto, enlace))
        return True


class Reloj:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _cal(*pares, estados=None):
    estados = estados or ["pendiente"] * len(pares)
    return {"Grupo C Jueves": [
        {"orden": i, "j1": a, "j2": b, "estado": e, "legs1": 0, "legs2": 0,
         "t180_1": 0, "t180_2": 0}
        for i, ((a, b), e) in enumerate(zip(pares, estados))]}


def montar(cal, t):
    reloj = Reloj(t)
    hoja, notif = HojaMemoria(), Notif()
    v = Vigia(hoja, notif, Datos([BAETENS, MENZIES, SELF, SMITH], cal), AJ, reloj=reloj)
    return v, hoja, notif, reloj


def test_un_aviso_por_partido_entre_30_y_45_minutos_antes():
    cal = _cal(("Andy Baetens", "Cameron Menzies"), ("Cameron Menzies", "Andy Baetens"))
    # Jueves 2026-11-05, Grupo C a las 14:00
    v, hoja, notif, reloj = montar(cal, datetime(2026, 11, 5, 13, 0, tzinfo=M))
    v.ciclo()
    assert notif.enviados == []                       # faltan 60 min
    reloj.t = datetime(2026, 11, 5, 13, 15, tzinfo=M)  # faltan 45
    for _ in range(3):
        v.ciclo()
    textos = [t for t, _ in notif.enviados]
    assert len(textos) == 1
    texto, enlace = notif.enviados[0]
    assert texto.startswith("🎯 ~14:00 Baetens vs Menzies · Gana Baetens ≥")
    assert len(texto) < 200
    assert enlace == ("https://modusapp.streamlit.app/?seccion=value"
                      "&j1=Andy%20Baetens&j2=Cameron%20Menzies")
    assert len(hoja.cuotas) == 51 and hoja.cuotas[0]["j1"] == "Andy Baetens"
    # El segundo partido (14:10) entra en la ventana 10 min despues
    reloj.t = datetime(2026, 11, 5, 13, 25, tzinfo=M)
    v.ciclo()
    assert len(notif.enviados) == 2
    assert notif.enviados[1][0].startswith("🎯 ~14:10 Menzies vs Baetens")  # J1 = cartel


def test_reinicio_no_repite_avisos():
    cal = _cal(("Andy Baetens", "Cameron Menzies"))
    t = datetime(2026, 11, 5, 13, 20, tzinfo=M)
    v, hoja, notif, _ = montar(cal, t)
    v.ciclo()
    v2 = Vigia(hoja, notif, v.datos, AJ, reloj=lambda: t)   # mismo dia, misma hoja
    v2.ciclo()
    assert len(notif.enviados) == 1


def test_volatilidad_alta_o_sin_dato_se_descarta_y_se_anota():
    cal = _cal(("Andy Baetens", "Self"), ("Ross Smith", "Cameron Menzies"))
    v, hoja, notif, _ = montar(cal, datetime(2026, 11, 5, 13, 30, tzinfo=M))
    v.ciclo()
    v.ciclo()
    assert notif.enviados == [] and hoja.cuotas == []
    desc = [l for l in hoja.logs if l["tipo"] == "descartado"]
    assert len(desc) == 2                              # una vez por partido
    assert "J2 volatilidad alta" in desc[0]["detalle"]
    assert "J1 sin datos de volatilidad" in desc[1]["detalle"]


def test_partidos_empezados_no_se_avisan():
    cal = _cal(("Andy Baetens", "Cameron Menzies"), ("Cameron Menzies", "Andy Baetens"),
               estados=["en_juego", "terminado"])
    v, _, notif, _ = montar(cal, datetime(2026, 11, 5, 14, 5, tzinfo=M))
    assert v.ciclo() == 0
    assert notif.enviados == []
