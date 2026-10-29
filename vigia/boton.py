"""
vigia/boton.py - Lo que llega a la app desde el boton "Modus value".

El marcador lee las cuotas de la pagina de Winamax que tienes abierta y
abre la app con ?seccion=value&wm=<datos en base64url>. Aqui se decodifican
y validan esos datos (si algo no cuadra, error: nunca se inventan cuotas),
se emparejan los nombres con los de la hoja, se pone J1 = primero del
cartel y cada salida se asigna a una seleccion del modelo con
vigia/mercados.py. Sin Streamlit, para poder probarlo.
"""

import base64
import json

from vigia.mercados import asignar
from vigia.nombres import emparejar, mismo_jugador, nombre_winamax

MAX_WM = 60_000   # caracteres; una pagina de partido normal ocupa ~3-10 mil
# Version del marcador (VERSION en boton/modus_value.js). Si llega una mas
# vieja, la app pide reinstalarlo: el marcador guarda una copia del codigo.
VERSION_BOTON = 3


# Para abrir el partido en la app de Winamax del movil (boton de Value Bets).
# Solo un enlace: no inicia sesion, no toca el boleto y no apuesta.
WINAMAX_WEB = "https://www.winamax.es/apuestas-deportivas"
# Paquete Android de la app de Winamax (sin confirmar oficialmente: si no es
# este o no esta instalada, Chrome abre la web del partido)
PAQUETE_WINAMAX_ANDROID = "com.winamax.winajs"


def sistema_movil(user_agent):
    """'android', 'ios' o None (ordenador) segun el User-Agent."""
    ua = str(user_agent or "")
    if "Android" in ua:
        return "android"
    if any(m in ua for m in ("iPhone", "iPad", "iPod")):
        return "ios"
    return None


def enlace_app_winamax(match_id, sistema):
    """Enlace que abre el partido (o las apuestas, sin id) en la app de
    Winamax. Android: intent con el paquete y la web de reserva; iPhone: el
    enlace normal de winamax.es, que iOS pasa a la app si esta instalada."""
    web = f"{WINAMAX_WEB}/match/{match_id}" if match_id else WINAMAX_WEB
    if sistema != "android":
        return web
    from urllib.parse import quote
    return (f"intent://{web.split('://', 1)[1]}#Intent;scheme=https;"
            f"package={PAQUETE_WINAMAX_ANDROID};"
            f"S.browser_fallback_url={quote(web, safe='')};end")


class DatosNoValidos(ValueError):
    pass


def decodificar(wm):
    """base64url -> dict validado {id, c1, c2, t, s, h, m}."""
    if not wm or len(wm) > MAX_WM:
        raise DatosNoValidos("no han llegado cuotas (o son demasiadas)")
    try:
        crudo = base64.urlsafe_b64decode(wm + "=" * (-len(wm) % 4))
        d = json.loads(crudo.decode("utf-8"))
    except Exception:
        raise DatosNoValidos("los datos del botón están dañados")
    if not isinstance(d, dict) or d.get("v") != 1:
        raise DatosNoValidos("versión del botón desconocida: vuelve a instalarlo")
    if not str(d.get("c1") or "").strip() or not str(d.get("c2") or "").strip():
        raise DatosNoValidos("faltan los nombres de los jugadores")
    mercados = []
    for m in d.get("m") or []:
        if not (isinstance(m, list) and len(m) == 2 and isinstance(m[1], list)):
            raise DatosNoValidos("formato de mercados desconocido")
        salidas = []
        for s in m[1]:
            if not (isinstance(s, list) and len(s) == 3):
                raise DatosNoValidos("formato de cuotas desconocido")
            try:
                c = float(s[2])
            except (TypeError, ValueError):
                raise DatosNoValidos("hay una cuota que no es un número")
            if not 1.0 < c < 1000:
                raise DatosNoValidos(f"cuota fuera de rango: {s[2]}")
            salidas.append({"label": str(s[0]), "code": str(s[1]), "cuota": c})
        mercados.append({"titulo": str(m[0]), "salidas": salidas})
    if not mercados:
        raise DatosNoValidos("no han llegado cuotas")
    return {"id": str(d.get("id") or ""), "c1": str(d["c1"]).strip(),
            "c2": str(d["c2"]).strip(), "t": int(d.get("t") or 0),
            "s": str(d.get("s") or ""), "h": int(d.get("h") or 0),
            # "pagina": estado de la pagina + cuotas al dia de la pantalla;
            # "pantalla": solo lo que se veia (llegaste navegando)
            "f": str(d.get("f") or "pagina"),
            # version del marcador (los antiguos no la mandan: 1), segundos
            # desde que se cargo la pagina y mercados cuyas cuotas salen del
            # estado de carga (no se veian en pantalla)
            "b": _entero(d.get("b"), 1), "e": _entero(d.get("e"), 0),
            "ne": _entero(d.get("ne"), 0),
            "mercados": mercados}


def _entero(v, defecto):
    try:
        return int(v) if v is not None else defecto
    except (TypeError, ValueError):
        return defecto


def preparar(datos, nombres_db, cartel=()):
    """Empareja jugadores, decide J1 y asigna cada salida.

    nombres_db: nombres de la hoja (los del selector de Value Bets).
    cartel: [(j1, j2), ...] partidos del calendario en orden del cartel.
    Devuelve dict con j1, j2 (nombres de la hoja), orden ('cartel' o
    'winamax'), selecciones [{sel, nombre, titulo, label, cuota}] y
    sin_asignar [(titulo, label, cuota)]; o lanza DatosNoValidos.
    """
    n1 = emparejar(datos["c1"], nombres_db)
    n2 = emparejar(datos["c2"], nombres_db)
    if not n1 or not n2 or n1 == n2:
        falta = [nombre_winamax(c) for c, n in ((datos["c1"], n1), (datos["c2"], n2)) if not n]
        raise DatosNoValidos("no encuentro en los datos de la app a: "
                             + (", ".join(falta) or n1))
    invertido, orden = False, "winamax"
    for a, b in cartel:
        if mismo_jugador(a, n1) and mismo_jugador(b, n2):
            orden = "cartel"
            break
        if mismo_jugador(a, n2) and mismo_jugador(b, n1):
            invertido, orden = True, "cartel"
            break
    j1, j2 = (n2, n1) if invertido else (n1, n2)
    nombres = (datos["c1"], datos["c2"])
    selecciones, sin_asignar, vistas = [], [], set()
    for m in datos["mercados"]:
        for s in m["salidas"]:
            r = asignar(m["titulo"], s["label"], s["code"], nombres, invertido)
            if r is None:
                sin_asignar.append((m["titulo"], s["label"], s["cuota"]))
                continue
            sel, nombre = r
            clave = json.dumps(sel, sort_keys=True)
            if clave in vistas:      # la misma seleccion en dos mercados
                continue
            vistas.add(clave)
            selecciones.append({"sel": sel, "nombre": nombre, "titulo": m["titulo"],
                                "label": s["label"], "cuota": s["cuota"]})
    return {"j1": j1, "j2": j2, "orden": orden, "selecciones": selecciones,
            "sin_asignar": sin_asignar}


def casilla(sel):
    """Key de la casilla de cuota de Value Bets para una seleccion, o None
    si Value Bets no tiene casilla para esa linea."""
    t = sel["tipo"]
    if t == "ganador":
        return f"vic_j{sel['jugador']}"
    if t == "handicap":
        h = sel["linea"]
        if abs(h) in (1.5, 2.5):
            signo = "neg" if h < 0 else "pos"
            return f"hcap_j{sel['jugador']}_{signo}_{int(abs(h) * 10)}"
        return None
    if t == "total_legs":
        if sel["linea"] == 5.5:
            return "legs_mas" if sel["lado"] == "mas" else "legs_menos"
        return None
    if t == "180_jugador":
        if sel["linea"] in (0.5, 1.5):
            n = "05" if sel["linea"] == 0.5 else "15"
            return f"180_j{sel['jugador']}_{'' if sel['lado'] == 'mas' else 'neg'}{n}"
        return None
    if t == "180_total":
        if sel["linea"] in (1.5, 2.5):
            n = "15" if sel["linea"] == 1.5 else "25"
            return f"180_ambos_{'' if sel['lado'] == 'mas' else 'neg'}{n}"
        return None
    if t == "mas_180":
        return {1: "mas_j1", 0: "mas_emp", 2: "mas_j2"}[sel["quien"]]
    return None


def seleccion_de_casilla(key):
    """Inversa de casilla(): la seleccion del modelo de una casilla de cuota
    de Value Bets ('vic_j1', 'hcap_j2_neg_15'...), o None."""
    from vigia.cuotas import selecciones
    for sel in selecciones():
        if casilla(sel) == key:
            return sel
    return None
