"""
modelo/value.py - Yield y margen de seguridad (🟢) sin Streamlit.

helpers.py lo reexporta para la app; el vigia y el boton "Modus value" lo
usan para decidir si una apuesta es 🟢. Los margenes salen de
config.MARGEN_POR_MERCADO (claves = principio de la casilla de cuota de
Value Bets: 'vic_', 'legs_'...).
"""

from config import MARGEN_VALUE, MARGEN_POR_MERCADO

# Nombre de mercado del vigia -> prefijo de casilla de Value Bets
PREFIJO_DE_MERCADO = {
    "ganador": "vic_",
    "handicap": "hcap_",
    "total_legs": "legs_",
    "180s": "180_",
    "mas_180": "mas_",
}


def calcular_yield(prob, cuota_bookie):
    return (prob * cuota_bookie) - 1


def margen_mercado(mercado=None):
    """Margen de seguridad del value para un mercado (por la key de su
    casilla de cuota: 'vic_j1', 'legs_mas', '180_j1_05'... o por el nombre
    de mercado del vigia: 'ganador', 'handicap'...). El resultado exacto no
    tiene margen (None: nunca es 🟢). Si no se reconoce, el general
    MARGEN_VALUE."""
    if mercado == "resultado":
        return None
    if mercado:
        mercado = PREFIJO_DE_MERCADO.get(mercado, mercado)
        for prefijo, m in MARGEN_POR_MERCADO.items():
            if str(mercado).startswith(prefijo):
                return m
    return MARGEN_VALUE


def es_value(y, cuota, margen=None, mercado=None):
    """True si la apuesta es value con margen de seguridad.

    y = prob * cuota - 1. Exigir prob >= 1/cuota + margen equivale a
    y >= margen * cuota (a cuota alta hace falta mas yield, porque un error
    de unos puntos en la probabilidad pesa mas). El margen depende del
    mercado (MARGEN_POR_MERCADO en config.py).
    """
    m = margen_mercado(mercado) if margen is None else margen
    if m is None or y is None or not cuota:
        return False
    # 1e-9: que justo en el limite (p. ej. 58 % a cuota 2,00 con margen 8)
    # cuente como value pese al redondeo de los decimales
    return y > 0 and y >= m * cuota - 1e-9
