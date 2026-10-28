"""
modelo/util.py - Utilidades numericas y de nombres sin dependencias de
Streamlit. helpers.py las reexporta para el resto de la app.
"""

import unicodedata

import numpy as np


def safe_float(val, default=0.0):
    try:
        v = float(str(val).replace(',', '.').strip())
        if not np.isfinite(v):
            return default
        return v
    except:
        return default


def sanitize_prob(p):
    if not np.isfinite(p) or p <= 0:
        return 0.0001
    if p >= 1:
        return 0.9999
    return max(0.0001, min(0.9999, p))


def _buscar_stat(stats_dict, keywords):
    for k, v in stats_dict.items():
        if any(kw in k.lower() for kw in keywords):
            return v
    return 0.0


def normalizar_nombre(nombre):
    """Quita tildes, pasa a minusculas, quita puntuacion comun y colapsa
    espacios. 'Baetens, Andy' -> 'baetens andy'."""
    if not nombre:
        return ""
    s = str(nombre).strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    for ch in (".", ",", "'", "`", "´", "-"):
        s = s.replace(ch, " ")
    return " ".join(s.split())
