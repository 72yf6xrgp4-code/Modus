"""
vigia/mercados.py - Asigna los mercados de una pagina de partido de Winamax
a selecciones del modelo.

Lo usa la app cuando llega desde el boton "Modus value" (el marcador del
navegador lee las cuotas de la pagina que TU tienes abierta; aqui no se
pide nada a Winamax). Cada apuesta (bet) tiene un titulo (betTitle) y unas
salidas (outcomes) con su etiqueta (label) y cuota. Aqui se traduce cada
salida a una seleccion de modelo.motor.probabilidad, con J1/J2 en el orden
del CARTEL (no el de Winamax).

Es deliberadamente conservador: lo que no se reconoce con seguridad se
ignora (devuelve None) y la app lo muestra como "sin asignar".
"""

import re

from modelo.util import normalizar_nombre
from vigia.nombres import nombre_winamax

_NUM = r"([+\-−–]?\s?\d+(?:[.,]\d+)?)"


def _num(txt):
    """'−1,5' -> -1.5"""
    t = txt.replace(" ", "").replace("−", "-").replace("–", "-").replace(",", ".")
    return float(t)


def _linea_x5(v):
    """Solo lineas x.5 (sin empate posible)."""
    return v is not None and abs(abs(v) % 1 - 0.5) < 1e-9


def _quien(texto, nombres):
    """1 o 2 si el texto menciona inequivocamente al J1 o al J2 (por nombre
    completo o apellido); None si no o si menciona a los dos."""
    t = f" {normalizar_nombre(texto)} "
    hits = set()
    for idx, nom in ((1, nombres[0]), (2, nombres[1])):
        n = normalizar_nombre(nombre_winamax(nom))
        if not n:
            continue
        palabras = n.split()
        if f" {n} " in t or f" {palabras[-1]} " in t:
            hits.add(idx)
    return hits.pop() if len(hits) == 1 else None


def _lado(texto):
    t = normalizar_nombre(texto)
    if re.match(r"^(mas|over|\+)\b", t) or " mas de " in f" {t} ":
        return "mas"
    if re.match(r"^(menos|under)\b", t) or " menos de " in f" {t} ":
        return "menos"
    return None


def _linea(*textos):
    for txt in textos:
        m = re.search(r"(\d+[.,]5)", txt or "")
        if m:
            return _num(m.group(1))
    return None


def tipo_mercado(titulo):
    """Clasifica el titulo de la apuesta: 'ganador', 'handicap',
    'total_legs', 'resultado', '180', o None (no reconocido)."""
    t = normalizar_nombre(titulo)
    if not t:
        return None
    # Mercados que NO son del partido completo: fuera
    if re.search(r"\b(set|leg [0-9]|1er leg|primer leg|leg 1|checkout|"
                 r"par impar|impar|primer 180|primero)\b", t):
        return None
    if "180" in t:
        return "180"
    if "exact" in t or "marcador" in t or "correct score" in t:
        return "resultado"
    if "handicap" in t:
        return "handicap"
    if "leg" in t and ("total" in t or "mas" in t or "menos" in t
                       or "numero" in t):
        return "total_legs"
    if t in ("ganador", "ganador del partido", "resultado del partido",
             "cara a cara", "vencedor", "1 2", "12", "partido",
             "quien ganara", "quien ganara el partido"):
        return "ganador"
    return None


def asignar(titulo, label, code, nombres, invertido):
    """Traduce una salida de Winamax a una seleccion del modelo.

    titulo, label, code: de la apuesta y la salida de Winamax.
    nombres: (competitor1Name, competitor2Name) tal cual los da Winamax.
    invertido: True si el J1 del cartel es el competitor2 de Winamax.

    Devuelve (seleccion, descripcion) con J1/J2 del CARTEL, o None.
    """
    tipo = tipo_mercado(titulo)
    if tipo is None:
        return None
    label = str(label or "").strip()
    code = str(code or "").strip()

    def a_cartel(j_winamax):
        # j_winamax: 1/2 en el orden de Winamax -> orden del cartel
        if j_winamax in (1, 2) and invertido:
            return 2 if j_winamax == 1 else 1
        return j_winamax

    if tipo == "ganador":
        q = _quien(label, nombres)
        if q is None and code in ("1", "2"):
            q = int(code)
        if q is None:
            return None
        return {"tipo": "ganador", "jugador": a_cartel(q)}, "Ganador"

    if tipo == "handicap":
        q = _quien(label, nombres)
        if q is None and code in ("1", "2"):
            q = int(code)
        m = re.search(_NUM + r"\s*\)?\s*$", label) or re.search(r"\(" + _NUM, label)
        h = _num(m.group(1)) if m else None
        if q is None or not _linea_x5(h):
            return None
        return ({"tipo": "handicap", "jugador": a_cartel(q), "linea": h},
                "Hándicap")

    if tipo == "total_legs":
        lado = _lado(label)
        linea = _linea(label, titulo)
        if lado is None or not _linea_x5(linea):
            return None
        return ({"tipo": "total_legs", "lado": lado, "linea": linea},
                "Total de legs")

    if tipo == "resultado":
        m = re.search(r"\b([0-4])\s*[-:]\s*([0-4])\b", label)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2))
        if max(a, b) != 4 or a == b:
            return None
        # Si la etiqueta nombra a un jugador, el marcador es desde su lado
        q = _quien(label, nombres)
        if q == 2:
            a, b = b, a
        if invertido:
            a, b = b, a
        return {"tipo": "resultado", "legs1": a, "legs2": b}, "Resultado exacto"

    if tipo == "180":
        lado = _lado(label)
        linea = _linea(label, titulo)
        if lado is not None:
            if not _linea_x5(linea):
                return None
            q = _quien(titulo, nombres) or _quien(label, nombres)
            if q is None:
                return ({"tipo": "180_total", "lado": lado, "linea": linea},
                        "180s totales")
            return ({"tipo": "180_jugador", "jugador": a_cartel(q),
                     "lado": lado, "linea": linea}, "180s jugador")
        # Sin mas/menos: "quien hace mas 180s" (jugador o empate)
        t = normalizar_nombre(titulo)
        if not ("mas" in t or "quien" in t or "cara a cara" in t
                or "duelo" in t):
            return None
        lab = normalizar_nombre(label)
        if lab in ("empate", "x", "igualdad") or code.upper() == "X":
            return {"tipo": "mas_180", "quien": 0}, "Más 180s"
        q = _quien(label, nombres)
        if q is None and code in ("1", "2"):
            q = int(code)
        if q is None:
            return None
        return {"tipo": "mas_180", "quien": a_cartel(q)}, "Más 180s"
    return None


def texto_seleccion(sel, j1, j2):
    """Texto corto de la seleccion con los nombres del cartel."""
    ape = lambda n: n.split()[-1] if n else n  # noqa: E731
    nom = {1: ape(j1), 2: ape(j2)}
    t = sel["tipo"]

    def num(v):
        s = f"{v:+.1f}".replace(".", ",").replace("-", "−")
        return s

    if t == "ganador":
        return f"Gana {nom[sel['jugador']]}"
    if t == "handicap":
        return f"Hándicap {nom[sel['jugador']]} {num(sel['linea'])}"
    if t == "total_legs":
        lado = "Más" if sel["lado"] == "mas" else "Menos"
        return f"{lado} de {str(sel['linea']).replace('.', ',')} legs"
    if t == "resultado":
        return f"Resultado {sel['legs1']}-{sel['legs2']}"
    if t == "180_jugador":
        lado = "más" if sel["lado"] == "mas" else "menos"
        return f"180s {nom[sel['jugador']]} {lado} de {str(sel['linea']).replace('.', ',')}"
    if t == "180_total":
        lado = "Más" if sel["lado"] == "mas" else "Menos"
        return f"{lado} de {str(sel['linea']).replace('.', ',')} 180s"
    if t == "mas_180":
        return "Empate en 180s" if sel["quien"] == 0 else f"Más 180s {nom[sel['quien']]}"
    return str(sel)
