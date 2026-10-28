"""
modelo/volatilidad.py - Nivel de riesgo segun el Indice Volatilidad.

El indice lo calcula la hoja (irregularidad del rendimiento del jugador).
Umbrales alineados con el formato condicional de la hoja de calculo:
    < 8      -> bajo   (rendimiento estable)
    8 - 12   -> medio  (algo irregular)
    > 12     -> alto   (muy irregular)
Valor 0, vacio o no numerico -> None ("Sin datos": la hoja no lo calcula
hasta que el jugador lleva varios partidos).
"""

import numpy as np

UMBRAL_VOL_BAJO = 8
UMBRAL_VOL_ALTO = 12

ETIQUETAS_VOL = {"bajo": "Riesgo bajo", "medio": "Riesgo medio",
                 "alto": "Riesgo alto", None: "Sin datos"}


def nivel_volatilidad(valor):
    """'bajo' | 'medio' | 'alto' | None (sin datos)."""
    try:
        v = float(str(valor).replace('%', '').replace(',', '.').strip())
    except:
        return None
    if not np.isfinite(v) or v == 0:
        return None
    if v < UMBRAL_VOL_BAJO:
        return "bajo"
    if v <= UMBRAL_VOL_ALTO:
        return "medio"
    return "alto"
