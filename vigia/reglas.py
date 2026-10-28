"""
vigia/reglas.py - Reglas de apuesta (funciones puras, sin red).

  - Volatilidad del partido = la del jugador mas irregular de los dos.
    Hasta 12 (baja o media): edge minimo 10 %. Por encima de 12 (alta) no
    se descarta: se exige 2 puntos mas de edge por cada punto que pase de
    12 (13 -> 12 %, 15 -> 16 %, 17 -> 20 %) y el importe baja un escalon
    (7,5 -> 5; 5 -> 2,5). Por encima de 18, o sin dato, se descarta.
  - Edge = p_modelo * cuota - 1. Aviso si edge >= el minimo exigido.
  - Margen = p_modelo - 1/cuota. 🟢 si llega al margen del mercado (el
    mismo de la app: config.MARGENES_VALUE). Resultado exacto nunca 🟢.
  - Importe: edge 10-15 % -> 2,5 EUR; 15-20 % -> 5; >= 20 % -> 7,5. Solo
    pasa de 2,5 si es 🟢 y la cuota es <= 4,00.
  - Margen > 20 puntos -> "REVISAR": sin importe ni gasto de tope.
  - Tope diario: se recorta a lo que quede, en multiplos de 2,5.
  - Cuotas minimas: la cuota a partir de la cual se cumple cada regla,
    redondeada SIEMPRE hacia arriba (a 2 decimales) para que, si la casa
    da exactamente esa cuota, la regla se cumpla de verdad.
"""

import math

from modelo.value import calcular_yield, es_value, margen_mercado
from modelo.volatilidad import nivel_volatilidad

EDGE_MIN = 0.10
# Volatilidad alta: edge extra por punto por encima de VOL_ALTA y limite
VOL_ALTA = 12.0
VOL_EDGE_POR_PUNTO = 0.02
VOL_MAXIMA = 18.0
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
    "mas_180": "mas_180",
    "hcap_180": "mas_180",
}


def requisito_volatilidad(vol1, vol2):
    """Lo que exige el partido segun la volatilidad de sus jugadores.

    Devuelve dict con:
      ok        False si se descarta (falta un dato o pasa de VOL_MAXIMA)
      motivo    por que se descarta ('' si ok)
      vol       volatilidad del partido (la mayor de las dos)
      edge_min  edge minimo exigido (10 % hasta 12; +2 puntos por punto)
      rebaja    True con volatilidad alta: el importe baja un escalon
    """
    vals = []
    for v, quien in ((vol1, "J1"), (vol2, "J2")):
        if nivel_volatilidad(v) is None:
            return {"ok": False, "motivo": f"{quien} sin datos de volatilidad",
                    "vol": None, "edge_min": None, "rebaja": False}
        vals.append(float(str(v).replace("%", "").replace(",", ".").strip()))
    vol = max(vals)
    if vol > VOL_MAXIMA:
        quien = "J1" if vals[0] >= vals[1] else "J2"
        return {"ok": False,
                "motivo": f"{quien} volatilidad {vol:.1f} (más de {VOL_MAXIMA:g})",
                "vol": vol, "edge_min": None, "rebaja": False}
    extra = max(0.0, vol - VOL_ALTA) * VOL_EDGE_POR_PUNTO
    return {"ok": True, "motivo": "", "vol": vol,
            "edge_min": round(EDGE_MIN + extra, 6), "rebaja": vol > VOL_ALTA}


def partido_elegible(vol1, vol2):
    """(True, '') si el partido se puede evaluar; si no, (False, motivo)."""
    r = requisito_volatilidad(vol1, vol2)
    return r["ok"], r["motivo"]


def evaluar(mercado, p, cuota, edge_min=EDGE_MIN, rebaja=False):
    """Evalua una seleccion. mercado: 'ganador', 'handicap', 'total_legs',
    'resultado', '180s' o 'mas_180'. edge_min y rebaja salen de
    requisito_volatilidad. Devuelve dict con edge, margen, verde, revisar
    e importe (antes del tope; 0 si no llega al edge exigido o es REVISAR)."""
    edge = calcular_yield(p, cuota)
    margen = p - 1.0 / cuota
    verde = mercado != "resultado" and es_value(edge, cuota, mercado=mercado)
    revisar = margen > MARGEN_REVISAR
    importe = 0.0
    if edge >= edge_min - 1e-9 and not revisar:
        if edge >= 0.20 - 1e-9:
            importe = 7.5
        elif edge >= 0.15 - 1e-9:
            importe = 5.0
        else:
            importe = 2.5
        if not (verde and cuota <= CUOTA_MAX_SUBIR):
            importe = min(importe, UNIDAD)
        if rebaja:
            importe = max(UNIDAD, importe - UNIDAD)
    return {"edge": edge, "margen": margen, "verde": verde,
            "revisar": revisar and edge >= edge_min - 1e-9,
            "importe": importe}


def importe(mercado, p, cuota, edge_min=EDGE_MIN, rebaja=False):
    """Importe recomendado (sin tope) en euros."""
    return evaluar(mercado, p, cuota, edge_min, rebaja)["importe"]


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
    if t == "hcap_180":
        h = sel["linea"]
        return (t180_1 + h > t180_2) if sel["jugador"] == 1 else (t180_2 + h > t180_1)
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


# ─────────────────────────────────────────────────────────────────────────────
# CUOTAS MINIMAS
# ─────────────────────────────────────────────────────────────────────────────

def redondear_arriba(cuota):
    """2 decimales hacia arriba: 1,4825 -> 1,49 (1,48 daria edge 9,8 %)."""
    return math.ceil(cuota * 100 - 1e-6) / 100


def cuota_minima(p, edge):
    """Cuota a partir de la cual p * cuota - 1 >= edge."""
    if not p or p <= 0:
        return None
    return redondear_arriba((1.0 + edge) / p)


def cuota_minima_verde(mercado, p):
    """Cuota a partir de la cual la seleccion es 🟢: p - 1/cuota >= margen.
    None si el mercado no admite 🟢 (resultado exacto) o p <= margen."""
    m = margen_mercado(mercado)
    if m is None or p <= m:
        return None
    return redondear_arriba(1.0 / (p - m))


def cuotas_minimas(mercado, p, edge_min=EDGE_MIN, rebaja=False):
    """Todas las cuotas de referencia de una seleccion.

    aviso    la que llega al edge exigido (2,5 EUR)
    eur_5    la que da 5 EUR si ademas es 🟢 y cuota <= 4 (edge 15 %; con
             volatilidad alta hace falta el escalon de 7,5 -> edge 20 %)
    eur_7_5  la que da 7,5 EUR (edge 20 %); None con volatilidad alta
    verde    la que la hace 🟢 (None en resultado exacto)
    """
    e5 = 0.20 if rebaja else 0.15
    return {
        "justa": round(1.0 / p, 2) if p > 0 else None,
        "aviso": cuota_minima(p, edge_min),
        "eur_5": cuota_minima(p, max(e5, edge_min)),
        "eur_7_5": None if rebaja else cuota_minima(p, max(0.20, edge_min)),
        "verde": cuota_minima_verde(mercado, p),
    }


def apuntar(alertas, fecha, j1, j2, ev, tope=TOPE_DIARIO):
    """Importe con el que se puede apuntar una apuesta desde la app y, si
    es 0, el motivo. Reglas: una apuesta por partido y dia (las marcadas
    'no apostada' no cuentan), sin importe si es REVISAR o no llega al 10 %
    de edge, y recortada al tope que quede del dia."""
    from modelo.util import normalizar_nombre
    from vigia import registro
    par = {normalizar_nombre(j1), normalizar_nombre(j2)}
    for f in alertas:
        if (f.get("fecha") == fecha and registro.gasta_tope(f)
                and {normalizar_nombre(f.get("j1", "")),
                     normalizar_nombre(f.get("j2", ""))} == par):
            return 0.0, "ya hay una apuesta apuntada en este partido"
    if ev["revisar"]:
        return 0.0, "⚠️ REVISAR: margen de más de 20 puntos, sin importe"
    if ev["importe"] <= 0:
        return 0.0, "no llega al edge exigido"
    importe = aplicar_tope(ev["importe"], registro.gastado_del_dia(alertas, fecha), tope)
    if importe <= 0:
        return 0.0, f"tope de {tope:g} € de la jornada alcanzado"
    return importe, ""
