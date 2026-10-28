"""
modelo/value.py - Yield y margen de seguridad (🟢) sin Streamlit.

helpers.py lo reexporta para la app; el vigia lo usa para decidir si una
apuesta es 🟢.
"""

from config import MARGEN_VALUE, MARGENES_VALUE


def calcular_yield(prob, cuota_bookie):
    return (prob * cuota_bookie) - 1


def margen_mercado(mercado=None):
    """Margen exigido a un mercado ('ganador', 'total_legs', 'handicap',
    '180s'). None si el mercado no admite 🟢 ('resultado'). Sin mercado,
    el margen general MARGEN_VALUE."""
    if mercado is None:
        return MARGEN_VALUE
    return MARGENES_VALUE.get(mercado)


def es_value(y, cuota, margen=None, mercado=None):
    """True si la apuesta es value con margen de seguridad.

    y = prob * cuota - 1. Exigir prob >= 1/cuota + margen equivale a
    y >= margen * cuota (a cuota alta hace falta mas yield, porque un error
    de unos puntos en la probabilidad pesa mas). El margen sale de
    `margen` si se pasa; si no, del mercado (MARGENES_VALUE).
    """
    m = margen if margen is not None else margen_mercado(mercado)
    if m is None or y is None or not cuota:
        return False
    # Pequena tolerancia para que un margen justo en el limite cuente
    return y > 0 and y >= m * cuota - 1e-9
