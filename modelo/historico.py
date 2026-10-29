"""
modelo/historico.py - Semanas anteriores (pestana 'Historico') y ajuste de
la volatilidad. Sin Streamlit: lo usan la app y el vigia.

1. Historico: para cada jugador, la media de sus semanas anteriores
   (ponderada por partidos jugados). Se mezcla con los datos de esta semana
   dandole muy poco peso: todo el historico vale como PESO_HISTORICO
   partidos de esta semana. Sin partidos esta semana se usa solo el
   historico; con 1 partido pesa el 50 %, con 3 el 25 %, con 9 el 10 %.

2. Volatilidad: el indice que calcula la hoja sale casi siempre por encima
   de 12 (alto). Se ajusta con la distribucion real de tus datos: el tercio
   mas estable queda por debajo de 8 (bajo), el del medio entre 8 y 12
   (medio) y el mas irregular por encima de 12 (alto). Asi las reglas de
   siempre (8/12 en la app; +edge por encima de 12 y descarte por encima de
   18 en el vigia) siguen valiendo. El valor de la hoja se guarda en
   'volatilidad_hoja'.
"""

from datetime import timedelta

import numpy as np

from modelo.util import normalizar_nombre

PESO_HISTORICO = 1.0
MIN_VALORES_REFERENCIA = 9   # menos datos de volatilidad: no se ajusta

# Columna de la pestana Historico -> campo del jugador, y maximo razonable
# (la hoja en espanol a veces pierde la coma: 0,48 -> 48; se rescata)
COLUMNAS = {
    "PR": ("PR", 100.0),
    "Media 180s": ("lam_180", 5.0),
    "Legs por partido": ("lam_legs", 10.0),
    "Promedio dardos": ("promedio_dardos", 120.0),
    "Checkout %": ("checkouts", 100.0),
    "% Victorias": ("pct_victorias", 100.0),
    "Volatilidad": ("volatilidad", 50.0),
}


def _numero(valor, maximo=None):
    try:
        x = float(str(valor).strip().replace(",", "."))
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(x):
        return 0.0
    if maximo is None or abs(x) <= maximo:
        return x
    for divisor in (10.0, 100.0, 1000.0, 10000.0):
        if abs(x / divisor) <= maximo:
            return x / divisor
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# VOLATILIDAD
# ─────────────────────────────────────────────────────────────────────────────

def referencia_volatilidad(valores):
    """(p33, p67) de los indices de volatilidad de la hoja (sin ceros), o
    None si hay pocos datos para ajustar."""
    v = [x for x in (_numero(a, 50.0) for a in valores) if x > 0]
    if len(v) < MIN_VALORES_REFERENCIA:
        return None
    p33, p67 = np.percentile(v, [100 / 3, 200 / 3])
    if p67 <= p33 or p33 <= 0:
        return None
    return float(p33), float(p67)


def ajustar_volatilidad(valor, ref):
    """Indice de la hoja -> escala de la app: p33 -> 8, p67 -> 12 (tramos
    lineales; por encima de p67 con la misma pendiente que entre p33 y p67).
    0 o sin dato se queda igual (sin datos)."""
    v = _numero(valor, 50.0)
    if not ref or v <= 0:
        return v
    p33, p67 = ref
    if v <= p33:
        return round(v * 8.0 / p33, 2)
    return round(8.0 + (v - p33) * 4.0 / (p67 - p33), 2)


def ajustar_jugadores(jugadores, ref):
    """Copia de {nombre: datos} con la volatilidad ajustada (la de la hoja
    queda en 'volatilidad_hoja')."""
    salida = {}
    for k, d in (jugadores or {}).items():
        d = dict(d)
        if "volatilidad_hoja" not in d:
            d["volatilidad_hoja"] = d.get("volatilidad", 0)
        d["volatilidad"] = ajustar_volatilidad(d["volatilidad_hoja"], ref)
        salida[k] = d
    return salida


# ─────────────────────────────────────────────────────────────────────────────
# HISTORICO
# ─────────────────────────────────────────────────────────────────────────────

def sabado_de_la_semana(fecha):
    """YYYY-MM-DD del sabado de la semana del torneo (la etiqueta de cada
    semana en la pestana Historico). El domingo cuenta como la semana que
    acaba de terminar (igual que predicciones._fecha_sabado_de_la_semana)."""
    wd = fecha.weekday()
    sabado = fecha - timedelta(days=1) if wd == 6 else fecha + timedelta(days=5 - wd)
    return sabado.strftime("%Y-%m-%d")


def resumen_historico(filas, antes_de=None, ref=None):
    """Media de cada jugador en las semanas anteriores.

    filas: dicts con la cabecera de la pestana Historico ('Fecha sabado',
    'Jugador', 'PR', ..., 'Partidos jugados').
    antes_de: fecha del sabado de esta semana (YYYY-MM-DD): esa semana y
    las posteriores no cuentan (son los datos nuevos).
    ref: referencia_volatilidad para ajustar tambien la del historico.
    Devuelve {nombre_normalizado: {campos..., nombre_original,
    n_historico (partidos), semanas}}.
    """
    acum = {}
    for f in filas or []:
        fecha = str(f.get("Fecha sabado", "")).strip()
        nombre = str(f.get("Jugador", "")).strip()
        if not nombre or (antes_de and fecha >= antes_de):
            continue
        # Peso de la semana: sus partidos (o victorias + derrotas si la
        # columna viene vacia; si tampoco, 1, con tal de que tenga datos)
        n = _numero(f.get("Partidos jugados"))
        if n <= 0:
            n = _numero(f.get("Victorias")) + _numero(f.get("Derrotas"))
        if n <= 0:
            if _numero(f.get("PR"), 100.0) <= 0:
                continue
            n = 1.0
        a = acum.setdefault(normalizar_nombre(nombre),
                            {"nombre_original": nombre, "n": 0.0, "semanas": 0, "suma": {},
                             "peso": {}})
        a["n"] += n
        a["semanas"] += 1
        for col, (campo, maximo) in COLUMNAS.items():
            v = _numero(f.get(col), maximo)
            if v > 0:      # 0 = sin dato esa semana
                a["suma"][campo] = a["suma"].get(campo, 0.0) + v * n
                a["peso"][campo] = a["peso"].get(campo, 0.0) + n
    salida = {}
    for clave, a in acum.items():
        d = {"nombre_original": a["nombre_original"], "n_historico": int(a["n"]),
             "semanas": a["semanas"]}
        for campo in a["suma"]:
            d[campo] = a["suma"][campo] / a["peso"][campo]
        if "volatilidad" in d:
            d["volatilidad_hoja"] = d["volatilidad"]
            d["volatilidad"] = ajustar_volatilidad(d["volatilidad"], ref)
        salida[clave] = d
    return salida


def _buscar(nombre, historico, por_nombre):
    """Entrada del historico de un jugador: mismo nombre normalizado o, si
    no, el que empareja (mismo apellido, otro orden, inicial...)."""
    from vigia.nombres import emparejar
    h = historico.get(normalizar_nombre(nombre))
    if h:
        return h
    n = emparejar(nombre, list(por_nombre))
    return por_nombre.get(n) if n else None


def combinar_con_historico(jugadores, historico, nombres_extra=None, peso=PESO_HISTORICO):
    """Mezcla los datos de esta semana con el historico.

    jugadores: {nombre: datos} de esta semana (n_partidos = partidos de la
    semana). Para cada uno, el historico pesa peso / (peso + n_partidos).
    Los jugadores del historico que no estan esta semana se anaden solo con
    el (peso 100 %); con nombres_extra, solo esos.
    Cada jugador lleva 'peso_historico' (0 si no tiene historico),
    'semanas_historico' y 'n_historico'.
    """
    salida = {}
    campos = [c for c, _ in COLUMNAS.values()]
    por_nombre = {h["nombre_original"]: h for h in historico.values()}
    usados = set()
    for k, d in (jugadores or {}).items():
        d = dict(d)
        h = _buscar(d.get("nombre_original") or k, historico, por_nombre)
        if not h:
            d["peso_historico"] = 0.0
            salida[k] = d
            continue
        usados.add(h["nombre_original"])
        n = max(0.0, _numero(d.get("n_partidos")))
        w = peso / (peso + n)
        for campo in campos:
            vh = h.get(campo, 0.0)
            vs = _numero(d.get(campo))
            if vh <= 0:
                continue
            d[campo] = vh if vs <= 0 else w * vh + (1.0 - w) * vs
        d.update(peso_historico=w, semanas_historico=h.get("semanas", 0),
                 n_historico=h.get("n_historico", 0))
        salida[k] = d
    if nombres_extra is None:
        extra = [h for h in por_nombre.values() if h["nombre_original"] not in usados]
    else:
        extra = [h for h in (_buscar(n, historico, por_nombre) for n in nombres_extra)
                 if h and h["nombre_original"] not in usados]
    for h in extra:
        if h.get("PR", 0) <= 0 or h["nombre_original"] in usados:
            continue
        d = {c: h.get(c, 0.0) for c in campos}
        d.update(nombre_original=h["nombre_original"], n_partidos=0, victorias=0, derrotas=0,
                 volatilidad_hoja=h.get("volatilidad_hoja", 0.0), peso_historico=1.0,
                 solo_historico=True, semanas_historico=h.get("semanas", 0),
                 n_historico=h.get("n_historico", 0))
        salida[h["nombre_original"].lower()] = d
        usados.add(h["nombre_original"])
    return salida
