"""
vigia/reglas.py - Reglas de apuesta (funciones puras, sin red).

  - Partido valido: los DOS jugadores con volatilidad baja o media.
  - Edge = p_modelo * cuota - 1. Aviso si edge >= 10 %.
  - Margen = p_modelo - 1/cuota. 🟢 si llega al margen del mercado (el
    mismo de la app: config.MARGENES_VALUE). Resultado exacto nunca 🟢.
  - Importe: edge 10-15 % -> 2,5 EUR; 15-20 % -> 5; >= 20 % -> 7,5. Solo
    pasa de 2,5 si es 🟢 y la cuota es <= 4,00.
  - Margen > 20 puntos -> "REVISAR": sin importe ni gasto de tope.
  - Tope diario: se recorta a lo que quede, en multiplos de 2,5.
"""

import math

from modelo.value import calcular_yield, es_value
from modelo.volatilidad import nivel_volatilidad

EDGE_MIN = 0.10
UNIDAD = 2.5
CUOTA_MAX_SUBIR = 4.0
MARGEN_REVISAR = 0.20
TOPE_DIARIO = 50.0

# Tipo de seleccion (modelo.motor.probabilidad) -> mercado para el margen
MERCADO_DE_TIPO = {
    "ganador": "ganador",
    "handicap": "handicap",
    "total_legs": "total_legs",
    "resultado": "resultado",
    "180_jugador": "180s",
    "180_total": "180s",
    "mas_180": "180s",
}


def partido_elegible(vol1, vol2):
    """(True, '') si los dos jugadores tienen volatilidad baja o media;
    si no, (False, motivo). Sin datos de volatilidad -> descartado."""
    n1, n2 = nivel_volatilidad(vol1), nivel_volatilidad(vol2)
    for n, quien in ((n1, "J1"), (n2, "J2")):
        if n is None:
            return False, f"{quien} sin datos de volatilidad"
        if n == "alto":
            return False, f"{quien} volatilidad alta"
    return True, ""


def evaluar(mercado, p, cuota):
    """Evalua una seleccion. mercado: 'ganador', 'handicap', 'total_legs',
    'resultado' o '180s'. Devuelve dict con edge, margen, verde, revisar e
    importe (antes del tope; 0 si no hay aviso o es REVISAR)."""
    edge = calcular_yield(p, cuota)
    margen = p - 1.0 / cuota
    verde = mercado != "resultado" and es_value(edge, cuota, mercado=mercado)
    revisar = margen > MARGEN_REVISAR
    importe = 0.0
    if edge >= EDGE_MIN - 1e-9 and not revisar:
        if edge >= 0.20 - 1e-9:
            importe = 7.5
        elif edge >= 0.15 - 1e-9:
            importe = 5.0
        else:
            importe = 2.5
        if not (verde and cuota <= CUOTA_MAX_SUBIR):
            importe = min(importe, UNIDAD)
    return {"edge": edge, "margen": margen, "verde": verde,
            "revisar": revisar and edge >= EDGE_MIN - 1e-9,
            "importe": importe}


def importe(mercado, p, cuota):
    """Importe recomendado (sin tope) en euros."""
    return evaluar(mercado, p, cuota)["importe"]


def aplicar_tope(importe_eur, gastado, tope=TOPE_DIARIO):
    """Recorta el importe a lo que queda del tope, en multiplos de 2,5."""
    queda = max(0.0, tope - gastado)
    queda = math.floor(queda / UNIDAD + 1e-9) * UNIDAD
    return min(importe_eur, queda)


def acierta(sel, legs1, legs2, t180_1, t180_2):
    """True/False si la seleccion se cumplio con el resultado real (legs y
    180s de J1 y J2 en el orden de la seleccion); None si no se sabe."""
    t = sel.get("tipo")
    if t == "ganador":
        return (legs1 > legs2) if sel["jugador"] == 1 else (legs2 > legs1)
    if t == "handicap":
        h = sel["linea"]
        return (legs1 + h > legs2) if sel["jugador"] == 1 else (legs2 + h > legs1)
    if t == "total_legs":
        tot = legs1 + legs2
        return tot > sel["linea"] if sel["lado"] == "mas" else tot < sel["linea"]
    if t == "resultado":
        return (legs1, legs2) == (sel["legs1"], sel["legs2"])
    if t == "180_jugador":
        n = t180_1 if sel["jugador"] == 1 else t180_2
        return n > sel["linea"] if sel["lado"] == "mas" else n < sel["linea"]
    if t == "180_total":
        n = t180_1 + t180_2
        return n > sel["linea"] if sel["lado"] == "mas" else n < sel["linea"]
    if t == "mas_180":
        real = 1 if t180_1 > t180_2 else (2 if t180_2 > t180_1 else 0)
        return real == sel["quien"]
    return None


def invertir_seleccion(sel):
    """La misma seleccion vista con J1 y J2 intercambiados."""
    s = dict(sel)
    if "jugador" in s:
        s["jugador"] = 2 if s["jugador"] == 1 else 1
    if s.get("tipo") == "resultado":
        s["legs1"], s["legs2"] = s["legs2"], s["legs1"]
    if s.get("tipo") == "mas_180" and s["quien"] in (1, 2):
        s["quien"] = 2 if s["quien"] == 1 else 1
    return s
