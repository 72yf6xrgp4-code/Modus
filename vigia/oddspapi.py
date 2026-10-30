"""
vigia/oddspapi.py - Cuotas de Winamax Espana por la API de OddsPapi
(oddspapi.io), un proveedor de cuotas de terceros: aqui no se pide nada a
Winamax, se piden a OddsPapi con tu clave (secreto ODDSPAPI_KEY).

De la Modus da 5 mercados de Winamax: ganador, numero de legs, handicap de
legs, mas 180 y handicap de 180s. Se traducen al formato del boton "Modus
value" (vigia/boton.py), asi que la app los trata igual que una lectura del
boton: casillas, lectura guardada hasta que empiece el partido y
estadisticas (con fuente 'api').

OddsPapi llama "Leg Handicap" +-0,5 al "Handicap de 180 realizados" de
Winamax (en Modus no hay empate en legs: un handicap de legs de 0,5 seria
el ganador, y sus cuotas no lo son). Por eso las lineas +-0,5 van como
handicap de 180s.

Cada lectura de un partido gasta 1 peticion (y la lista de partidos, 1 de
vez en cuando). El plan gratuito da unas 250 al mes. Sin Streamlit.
"""

import base64
import json
from datetime import datetime, timedelta

from vigia.boton import VERSION_BOTON
from vigia.nombres import mismo_jugador, nombre_winamax
from modelo.util import normalizar_nombre

BASE = "https://api.oddspapi.io/v4"
TORNEO_MODUS = 33994      # tournamentId de la Modus Super Series (dardos: sportId 19)
CASA = "winamax.es"


class ErrorOddsPapi(Exception):
    """definitivo=True: no se arregla reintentando enseguida (sin peticiones
    en el plan o clave no valida); el vigia vuelve a las cuotas minimas."""

    def __init__(self, mensaje, definitivo=False):
        super().__init__(mensaje)
        self.definitivo = definitivo


def _get(ruta, clave, **params):
    import requests
    params["apiKey"] = clave
    try:
        r = requests.get(f"{BASE}/{ruta}", params=params, timeout=20)
    except requests.RequestException as ex:
        raise ErrorOddsPapi(f"no se puede conectar ({type(ex).__name__})")
    if r.status_code in (401, 403):
        raise ErrorOddsPapi("la clave ODDSPAPI_KEY no es válida", definitivo=True)
    if r.status_code == 429:
        raise ErrorOddsPapi("has gastado las peticiones de tu plan (o demasiadas seguidas)",
                            definitivo=True)
    if r.status_code != 200:
        raise ErrorOddsPapi(f"error HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise ErrorOddsPapi("respuesta que no es JSON")


def partidos(clave, ahora, get=_get):
    """Partidos de la Modus de ayer a pasado manana (fechas UTC: las
    sesiones de noche acaban pasada la medianoche)."""
    d = ahora.date()
    lista = get("fixtures", clave, tournamentId=TORNEO_MODUS,
                **{"from": (d - timedelta(days=1)).isoformat(),
                   "to": (d + timedelta(days=2)).isoformat()})
    if not isinstance(lista, list):
        raise ErrorOddsPapi("lista de partidos con un formato desconocido")
    return lista


def cuotas(clave, fixture_id, casa=CASA, get=_get):
    return get("odds", clave, fixtureId=fixture_id, bookmakers=casa)


def nombres(fixture):
    return (nombre_winamax(fixture.get("participant1Name")),
            nombre_winamax(fixture.get("participant2Name")))


def buscar_partido(lista, j1, j2):
    """El partido j1-j2 (en cualquier orden): el proximo sin empezar o, si
    no hay, el ultimo. None si no esta."""
    suyos = []
    for f in lista or []:
        a, b = nombres(f)
        if ((mismo_jugador(a, j1) and mismo_jugador(b, j2))
                or (mismo_jugador(a, j2) and mismo_jugador(b, j1))):
            suyos.append(f)
    if not suyos:
        return None
    suyos.sort(key=lambda f: str(f.get("startTime") or ""))
    sin_empezar = [f for f in suyos if f.get("statusId") == 0]
    return sin_empezar[0] if sin_empezar else suyos[-1]


# ─────────────────────────────────────────────────────────────────────────────
# MERCADOS DE DARDOS (marketId de OddsPapi; ver tests/fixtures/oddspapi_mercados.json)
# ─────────────────────────────────────────────────────────────────────────────

def mercado(market_id):
    """(tipo, linea) de un mercado de dardos: ('ganador', None),
    ('mas_180', None), ('total_legs', 5.5), ('handicap', -1.5); o None.
    En los de dos salidas, la salida con el mismo id que el mercado es
    'Over' / jugador 1 y la siguiente 'Under' / jugador 2."""
    m = int(market_id)
    if m == 191:
        return "ganador", None
    if m == 193:
        return "mas_180", None
    if m == 196:
        return "total_legs", 3.5
    if m == 198:
        return "total_legs", 4.0
    if 1910 <= m <= 1948 and m % 2 == 0:
        return "total_legs", 4.5 + (m - 1910) / 4
    if 1950 <= m <= 1998 and m % 2 == 0:
        return "handicap", -6.0 + (m - 1950) / 4
    return None


def _coma(x):
    return f"{x:g}".replace(".", ",")


def _precio(o):
    """Cuota de una salida, o None si no hay; y si esta activa."""
    p = ((o or {}).get("players") or {}).get("0") or {}
    try:
        precio = float(p.get("price"))
    except (TypeError, ValueError):
        return None, False
    return (precio if precio > 1.0 else None), bool(p.get("active"))


def traducir(odds, fixture, ahora_ts, casa=CASA):
    """Respuesta de /odds -> datos con el formato del boton (sin codificar;
    ver codificar). Solo cuotas activas: las suspendidas se cuentan en 'ns'."""
    libro = ((odds or {}).get("bookmakerOdds") or {}).get(casa)
    if not libro:
        raise ErrorOddsPapi(f"{casa} no tiene cuotas de este partido todavía")
    if libro.get("suspended") or not libro.get("bookmakerIsActive", True):
        raise ErrorOddsPapi(f"{casa} tiene suspendido este partido")
    c1, c2 = nombres(fixture)
    salida, suspendidas = [], 0
    for mid, m in sorted((libro.get("markets") or {}).items(), key=lambda kv: int(kv[0])):
        info = mercado(mid)
        if info is None or not m.get("marketActive", True):
            continue
        tipo, h = info
        cuotas_m = []
        for oid, o in (m.get("outcomes") or {}).items():
            precio, activa = _precio(o)
            if precio is None:
                continue
            if not activa:
                suspendidas += 1
                continue
            lado = int(oid) - int(mid)          # 0 = Over / jugador 1; 1 = Under / jugador 2
            if tipo == "ganador":
                cuotas_m.append([(c1, c2)[lado], str(lado + 1), precio])
            elif tipo == "mas_180":
                cuotas_m.append([(c1, "Empate", c2)[lado], ("1", "X", "2")[lado], precio])
            elif tipo == "total_legs":
                cuotas_m.append([f"{('Más', 'Menos')[lado]} de {_coma(h)}", "", precio])
            else:
                linea = h if lado == 0 else -h
                cuotas_m.append([f"{(c1, c2)[lado]} {linea:+g}", str(lado + 1), precio])
        if not cuotas_m:
            continue
        if tipo == "ganador":
            titulo = "Ganador"
        elif tipo == "mas_180":
            titulo = "Más 180"
        elif tipo == "total_legs":
            titulo = "Número de legs"
        else:
            titulo = "Hándicap de 180 realizados" if abs(h) == 0.5 else "Hándicap de legs"
        salida.append([titulo, cuotas_m])
    if not salida:
        raise ErrorOddsPapi(
            f"{casa} tiene suspendidas todas las cuotas de este partido (¿ya ha empezado?)"
            if suspendidas else f"{casa} aún no tiene cuotas de este partido")
    try:
        inicio = int(datetime.fromisoformat(
            str(fixture.get("startTime")).replace("Z", "+00:00")).timestamp())
    except ValueError:
        inicio = 0
    estado = "PREMATCH" if fixture.get("statusId") == 0 else str(
        fixture.get("statusName") or "?").upper()
    return {"v": 1, "id": str(libro.get("bookmakerFixtureId") or ""), "c1": c1, "c2": c2,
            "t": inicio, "s": estado, "h": int(ahora_ts), "f": "api", "b": VERSION_BOTON,
            "ns": suspendidas, "m": salida}


def juntar(datos, anterior):
    """Anade a la lectura de la API los mercados de una lectura anterior del
    BOTON del mismo partido que la API no da (180s totales, de cada
    jugador, resultado exacto...). 'bt' = esos titulos y 'bh' = hora de
    esa lectura (no cuentan para las estadisticas: no son de ahora). Si la
    anterior es otra lectura de la API, se arrastran los que ella traia del
    boton. anterior: datos de vigia.boton.decodificar."""
    if (not anterior or not mismo_jugador(anterior["c1"], datos["c1"])
            or not mismo_jugador(anterior["c2"], datos["c2"])):
        return datos
    # Otra lectura de la API: solo se arrastra lo que ella ya traia del boton
    de_api = anterior.get("f") == "api"
    del_boton = set(anterior.get("bt") or []) if de_api else None
    ya = {normalizar_nombre(t) for t, _ in datos["m"]}
    extra = [[m["titulo"], [[s["label"], s["code"], s["cuota"]] for s in m["salidas"]]]
             for m in anterior["mercados"] if normalizar_nombre(m["titulo"]) not in ya
             and (del_boton is None or m["titulo"] in del_boton)]
    if not extra:
        return datos
    return dict(datos, m=datos["m"] + extra, bt=sorted({t for t, _ in extra}),
                bh=int((anterior.get("bh") if de_api else anterior.get("h")) or 0))


def codificar(datos):
    """datos -> base64url, como lo manda el boton."""
    crudo = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(crudo).decode("ascii").rstrip("=")


class Cliente:
    """Lo que usa el vigia: lista de partidos y cuotas de un partido, con
    la clave y la casa puestas. Cuenta las peticiones (para el log)."""

    PAUSA = 1.1   # OddsPapi pide 1 s entre llamadas al mismo endpoint

    def __init__(self, clave, casa=CASA, get=_get, dormir=None):
        import time
        if not clave:
            raise ValueError("Falta ODDSPAPI_KEY")
        self.clave, self.casa, self._get = clave, casa, get
        self._dormir = dormir or time.sleep
        self._ultima = {}
        self.peticiones = 0

    def _contar(self, ruta, clave, **params):
        import time
        espera = self.PAUSA - (time.monotonic() - self._ultima.get(ruta, -1e9))
        if espera > 0:
            self._dormir(espera)
        self.peticiones += 1
        try:
            return self._get(ruta, clave, **params)
        finally:
            self._ultima[ruta] = time.monotonic()

    def partidos(self, ahora):
        return partidos(self.clave, ahora, get=self._contar)

    def cuotas(self, fixture_id):
        return cuotas(self.clave, fixture_id, self.casa, get=self._contar)
