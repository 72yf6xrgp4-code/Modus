"""
vigia/winamax.py - Lectura de cuotas de Winamax (SOLO lectura, sin sesion).

Las paginas de winamax.es traen el estado completo en el HTML:
    var PRELOADED_STATE = {...};
con sports, tournaments, matches, bets, outcomes y odds.

  - Dardos:  /apuestas-deportivas/sports/22
  - Partido: /apuestas-deportivas/match/{matchId}

Se pide con timeout y reintentos con espera creciente. Si Winamax responde
403 o 429 se lanza Bloqueado y el vigia para (no se insiste).
"""

import json
import logging
import random
import time

import requests

log = logging.getLogger(__name__)

BASE = "https://www.winamax.es/apuestas-deportivas"
URL_DARDOS = f"{BASE}/sports/22"
URL_PARTIDO = BASE + "/match/{}"

CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}


class Bloqueado(Exception):
    """Winamax ha respondido 403/429: hay que parar."""


class ClienteWinamax:
    def __init__(self, timeout=15, reintentos=3, pausa_min=1.5):
        self.sesion = requests.Session()
        self.sesion.headers.update(CABECERAS)
        self.timeout = timeout
        self.reintentos = reintentos
        self.pausa_min = pausa_min
        self._ultima = 0.0

    def _get(self, url):
        espera = 2.0
        for intento in range(1, self.reintentos + 1):
            # No encadenar peticiones: pausa minima (con algo de azar)
            hueco = self.pausa_min + random.uniform(0, 1) - (time.time() - self._ultima)
            if hueco > 0:
                time.sleep(hueco)
            self._ultima = time.time()
            try:
                r = self.sesion.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                log.warning("Winamax %s: %s (intento %d)", url, e, intento)
            else:
                if r.status_code in (403, 429):
                    raise Bloqueado(f"HTTP {r.status_code} en {url}")
                if r.status_code == 200:
                    return r.text
                log.warning("Winamax %s: HTTP %s (intento %d)", url,
                            r.status_code, intento)
            if intento < self.reintentos:
                time.sleep(espera)
                espera *= 2
        raise ConnectionError(f"Winamax no responde: {url}")

    def estado_dardos(self):
        return extraer_estado(self._get(URL_DARDOS))

    def estado_partido(self, match_id):
        return extraer_estado(self._get(URL_PARTIDO.format(match_id)))

    def html_partido(self, match_id):
        return self._get(URL_PARTIDO.format(match_id))


def extraer_estado(html):
    """Saca el JSON de `var PRELOADED_STATE = {...};` del HTML."""
    marca = "PRELOADED_STATE"
    i = html.find(marca)
    if i < 0:
        raise ValueError("El HTML no trae PRELOADED_STATE")
    ini = html.find("{", i)
    if ini < 0:
        raise ValueError("PRELOADED_STATE sin JSON")
    estado, _fin = json.JSONDecoder().raw_decode(html[ini:])
    return estado


def _nombre(d):
    if not isinstance(d, dict):
        return ""
    for k in ("tournamentName", "name", "title", "label", "categoryName"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _por_id(coleccion, id_):
    if not isinstance(coleccion, dict) or id_ is None:
        return None
    return coleccion.get(str(id_)) or coleccion.get(id_)


def partidos(estado):
    """Partidos del estado: [{id, c1, c2, status, inicio, outright,
    torneo_id, torneo}]."""
    torneos = estado.get("tournaments") or {}
    categorias = estado.get("categories") or {}
    salida = []
    for mid, m in (estado.get("matches") or {}).items():
        if not isinstance(m, dict):
            continue
        tid = m.get("tournamentId")
        t = _por_id(torneos, tid) or {}
        nombre_torneo = _nombre(t)
        cat = _por_id(categorias, t.get("categoryId") or m.get("categoryId"))
        if cat and _nombre(cat):
            nombre_torneo = f"{_nombre(cat)} · {nombre_torneo}".strip(" ·")
        salida.append({
            "id": str(m.get("matchId") or mid),
            "c1": str(m.get("competitor1Name") or "").strip(),
            "c2": str(m.get("competitor2Name") or "").strip(),
            "status": str(m.get("status") or ""),
            "inicio": int(m.get("matchStart") or 0),
            "outright": bool(m.get("isOutright")),
            "torneo_id": tid,
            "torneo": nombre_torneo,
            "sport_id": m.get("sportId"),
        })
    return salida


def _cuota(v):
    if isinstance(v, dict):
        v = v.get("odds") or v.get("value")
    try:
        c = float(v)
    except (TypeError, ValueError):
        return None
    return c if c > 1.0 else None


def mercados(estado, match_id):
    """Mercados de un partido: [{bet_id, titulo, tipo, disponible,
    salidas: [{id, label, code, cuota}]}]."""
    m = _por_id(estado.get("matches") or {}, match_id) or {}
    bets = estado.get("bets") or {}
    outcomes = estado.get("outcomes") or {}
    odds = estado.get("odds") or {}
    salida = []
    for bid in m.get("bets") or []:
        b = _por_id(bets, bid)
        if not isinstance(b, dict):
            continue
        salidas = []
        for oid in b.get("outcomes") or []:
            o = _por_id(outcomes, oid) or {}
            salidas.append({
                "id": str(oid),
                "label": str(o.get("label") or ""),
                "code": str(o.get("code") or ""),
                "cuota": _cuota(_por_id(odds, oid)),
            })
        salida.append({
            "bet_id": str(bid),
            "titulo": str(b.get("betTitle") or ""),
            "tipo": str(b.get("betTypeName") or ""),
            "disponible": b.get("available", True) is not False,
            "salidas": salidas,
        })
    return salida
