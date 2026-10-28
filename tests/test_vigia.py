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
RYDZ = {"nombre_original": "Callan Rydz", "PR": 57.0, "lam_180": 1.1, "volatilidad": 19.0}

AJ = SimpleNamespace(app_url="https://modusapp.streamlit.app", aviso_min_antes=10,
                     tope_diario=50.0)


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
    v = Vigia(hoja, notif, Datos([BAETENS, MENZIES, SELF, SMITH, RYDZ], cal), AJ, reloj=reloj)
    return v, hoja, notif, reloj


def test_secuencia_de_una_jornada_un_aviso_al_terminar_el_anterior():
    """Grupo C jueves (14:00). El primero se avisa 10 min antes; cada uno
    de los demas cuando termina el anterior; ninguno dos veces."""
    cal = _cal(("Andy Baetens", "Cameron Menzies"), ("Cameron Menzies", "Andy Baetens"),
               ("Andy Baetens", "Cameron Menzies"))
    partidos = cal["Grupo C Jueves"]
    v, hoja, notif, reloj = montar(cal, datetime(2026, 11, 5, 13, 45, tzinfo=M))
    v.ciclo()
    assert notif.enviados == []                                  # faltan 15 min
    reloj.t = datetime(2026, 11, 5, 13, 50, tzinfo=M)
    v.ciclo()
    v.ciclo()
    assert len(notif.enviados) == 1
    texto, enlace = notif.enviados[0]
    assert texto.startswith("🎯 14:00 Baetens vs Menzies · Gana Baetens ≥") and len(texto) < 200
    assert enlace == ("https://modusapp.streamlit.app/?seccion=value"
                      "&j1=Andy%20Baetens&j2=Cameron%20Menzies")
    assert len(hoja.cuotas) == 51 and hoja.cuotas[0]["inicio_estimado"] == "14:00"

    # Empieza el 1.o: el 2.o aun no se avisa
    partidos[0]["estado"] = "en_juego"
    reloj.t = datetime(2026, 11, 5, 14, 5, tzinfo=M)
    v.ciclo()
    assert len(notif.enviados) == 1
    # Termina el 1.o: se avisa el 2.o (J1 = el del cartel), una sola vez
    partidos[0]["estado"] = "terminado"
    for minuto in (12, 13, 20):
        reloj.t = datetime(2026, 11, 5, 14, minuto, tzinfo=M)
        v.ciclo()
    assert len(notif.enviados) == 2
    assert notif.enviados[1][0].startswith("🎯 Siguiente: Menzies vs Baetens")
    # Aunque el 2.o se retrase mucho, no se repite; el 3.o espera a que acabe
    partidos[1]["estado"] = "en_juego"
    reloj.t = datetime(2026, 11, 5, 15, 0, tzinfo=M)
    v.ciclo()
    assert len(notif.enviados) == 2
    partidos[1]["estado"] = "terminado"
    v.ciclo()
    v.ciclo()
    assert len(notif.enviados) == 3


def test_partido_con_hora_se_avisa_aviso_min_antes():
    cal = _cal(("Andy Baetens", "Cameron Menzies"), ("Cameron Menzies", "Andy Baetens"),
               estados=["en_juego", "pendiente"])
    cal["Grupo C Jueves"][1]["hora"] = datetime(2026, 11, 5, 15, 0, tzinfo=M)
    v, hoja, notif, reloj = montar(cal, datetime(2026, 11, 5, 14, 49, tzinfo=M))
    v.ciclo()
    assert notif.enviados == []
    reloj.t = datetime(2026, 11, 5, 14, 50, tzinfo=M)
    v.ciclo()
    assert len(notif.enviados) == 1 and notif.enviados[0][0].startswith("🎯 15:00 ")


def test_reinicio_no_repite_avisos():
    cal = _cal(("Andy Baetens", "Cameron Menzies"))
    t = datetime(2026, 11, 5, 13, 55, tzinfo=M)
    v, hoja, notif, _ = montar(cal, t)
    v.ciclo()
    v2 = Vigia(hoja, notif, v.datos, AJ, reloj=lambda: t)   # mismo dia, misma hoja
    v2.ciclo()
    assert len(notif.enviados) == 1


def test_volatilidad_alta_exige_mas_edge_y_se_avisa():
    # Self tiene volatilidad 13: no se descarta, se exige un 22 % de edge
    cal = _cal(("Andy Baetens", "Self"))
    v, hoja, notif, _ = montar(cal, datetime(2026, 11, 5, 13, 55, tzinfo=M))
    v.ciclo()
    texto, _ = notif.enviados[0]
    assert texto.endswith("· ⚠️ vol 13,0: edge ≥22 %") and len(texto) < 200
    fila = next(f for f in hoja.cuotas if f["seleccion"] == "Gana Baetens")
    assert fila["edge_exigido"] == 0.22
    from vigia import reglas
    assert fila["cuota_min_aviso"] == reglas.cuota_minima(fila["p"], 0.22)
    assert fila["cuota_min_15"] == ""           # con volatilidad alta no hay 15


def test_volatilidad_mayor_de_18_o_sin_dato_se_descarta_y_se_anota():
    cal = _cal(("Andy Baetens", "Callan Rydz"), ("Ross Smith", "Cameron Menzies"),
               estados=["pendiente", "pendiente"])
    cal["Grupo C Jueves"][1]["hora"] = datetime(2026, 11, 5, 14, 0, tzinfo=M)
    v, hoja, notif, _ = montar(cal, datetime(2026, 11, 5, 13, 55, tzinfo=M))
    v.ciclo()
    v.ciclo()
    assert notif.enviados == [] and hoja.cuotas == []
    desc = [l for l in hoja.logs if l["tipo"] == "descartado"]
    assert len(desc) == 2                              # una vez por partido
    assert "J2 volatilidad 19.0" in desc[0]["detalle"]
    assert "J1 sin datos de volatilidad" in desc[1]["detalle"]


def test_partidos_empezados_no_se_avisan():
    cal = _cal(("Andy Baetens", "Cameron Menzies"), ("Cameron Menzies", "Andy Baetens"),
               estados=["en_juego", "terminado"])
    v, _, notif, _ = montar(cal, datetime(2026, 11, 5, 14, 5, tzinfo=M))
    assert v.ciclo() == 0
    assert notif.enviados == []


def test_estado_de_los_partidos_por_la_api_y_csv_si_falla(monkeypatch):
    import modelo.datos as md
    from vigia.nucleo import DatosSheet
    filas_api = [[""]] * 6 + [["Andy Baetens", "4", "1"], ["Self", "2", "0"],
                              ["Ross Smith", "", ""], ["Callan Rydz", "", ""]]
    leidas = []

    def lector(jornada):
        leidas.append(jornada)
        return filas_api

    monkeypatch.setattr(md, "descargar_lineas", lambda j, timeout=8: [])
    monkeypatch.setattr(md, "cargar_jugadores", lambda j: {})
    datos = DatosSheet(lector=lector)
    jueves = datetime(2026, 11, 5, 14, 30, tzinfo=M)
    datos.refrescar(jueves, forzar=True)
    assert leidas == ["Grupo C Jueves", "Grupo B Jueves"] and datos.fuente == "API"
    estados = [p["estado"] for p in datos.calendario["Grupo C Jueves"]]
    assert estados == ["terminado", "pendiente"]
    # En cada vuelta se vuelve a leer el estado (los jugadores no)
    datos.refrescar(jueves)
    assert len(leidas) == 4

    def roto(jornada):
        raise RuntimeError("sin permiso")

    monkeypatch.setattr(md, "descargar_lineas", lambda j, timeout=8: filas_api)
    datos = DatosSheet(lector=roto)
    datos.refrescar(jueves, forzar=True)
    assert datos.fuente.startswith("CSV")
    assert len(datos.calendario["Grupo C Jueves"]) == 2


def test_dos_vigias_a_la_vez_no_repiten_aviso():
    """El del portatil y el de GitHub comparten vigia_log: si uno ya avisó
    (despues de que el otro arrancara), el otro no vuelve a avisar."""
    cal = _cal(("Andy Baetens", "Cameron Menzies"))
    t = datetime(2026, 11, 5, 13, 40, tzinfo=M)
    portatil, hoja, notif1, reloj1 = montar(cal, t)
    portatil.ciclo()                                   # arranca: aun no toca
    github = Vigia(hoja, Notif(), portatil.datos, AJ, reloj=Reloj(t + timedelta(minutes=12)))
    github.ciclo()                                     # GitHub avisa primero
    assert len(github.notif.enviados) == 1
    reloj1.t = t + timedelta(minutes=13)
    portatil.ciclo()
    assert notif1.enviados == []


def test_descarte_se_anota_una_sola_vez_aunque_se_relance():
    cal = _cal(("Callan Rydz", "Andy Baetens"))         # volatilidad 19: descarte
    t = datetime(2026, 11, 5, 13, 52, tzinfo=M)
    v, hoja, _, _ = montar(cal, t)
    v.ciclo()
    v._descartados.clear()                             # recarga de datos
    v.ciclo()
    otro = Vigia(hoja, Notif(), v.datos, AJ, reloj=Reloj(t))   # --una-vez de GitHub
    otro.ciclo()
    assert sum(1 for d in hoja.logs if d["tipo"] == "descartado") == 1
