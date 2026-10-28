"""
vigia/registro.py - Esquema de las pestanas 'alertas' y 'vigia_log' y
calculos sobre ellas (sin red). Lo usan el vigia y la app (pestanas
Alertas y Seguimiento), asi que no importa nada pesado.
"""

import json

from modelo.util import safe_float

HOJA_ALERTAS = "alertas"
HOJA_LOG = "vigia_log"
HOJA_CUOTAS = "cuotas_minimas"

COLUMNAS_ALERTAS = [
    "id", "fecha", "hora", "partido", "j1", "j2", "vol_j1", "vol_j2",
    "mercado", "seleccion", "cuota", "p_modelo", "edge", "margen", "verde",
    "importe", "tope_restante", "estado", "resultado", "beneficio",
    # Columnas tecnicas (al final)
    "tipo_aviso", "inicio", "match_id", "jornada", "orden_j1",
    "seleccion_json",
]
COLUMNAS_LOG = ["fecha", "hora", "tipo", "partido", "detalle"]

# Una fila por seleccion de cada partido avisado por el vigia.
# cuota_min_aviso = edge 10 % (2,5 EUR); cuota_min_5 = edge 15 %;
# cuota_min_7_5 = edge 20 % (5 y 7,5 EUR solo si ademas es 🟢 y cuota <= 4);
# cuota_min_verde = la que hace la seleccion 🟢 (vacia en resultado exacto).
# edge_exigido = 10 %, o mas con volatilidad alta (vigia/reglas.py).
COLUMNAS_CUOTAS = [
    "fecha", "hora", "inicio_estimado", "jornada", "orden", "j1", "j2",
    "vol_j1", "vol_j2", "mercado", "seleccion", "p", "cuota_justa",
    "cuota_min_aviso", "cuota_min_5", "cuota_min_7_5", "cuota_min_verde",
    "edge_exigido",
]

ESTADO_PENDIENTE = "pendiente"
ESTADO_APOSTADA = "apostada"
ESTADO_NO_APOSTADA = "no apostada"
ESTADO_REVISAR = "revisar"

AVISO_APUESTA = "apuesta"
AVISO_REVISAR = "revisar"


def filas_a_dicts(valores):
    """get_all_values() -> lista de dicts (con '_fila' = n de fila 1-indexed
    en la hoja, para poder actualizar celdas)."""
    if not valores:
        return []
    cab = [c.strip() for c in valores[0]]
    salida = []
    for i, fila in enumerate(valores[1:], start=2):
        if not any(str(v).strip() for v in fila):
            continue
        d = {c: (fila[k] if k < len(fila) else "") for k, c in enumerate(cab)}
        d["_fila"] = i
        salida.append(d)
    return salida


def num(v):
    return safe_float(str(v).replace("%", "").replace("€", "").strip())


def seleccion(fila):
    try:
        return json.loads(fila.get("seleccion_json") or "{}")
    except ValueError:
        return {}


def gasta_tope(fila):
    """Una alerta gasta tope si es apuesta y no esta marcada 'no apostada'."""
    return (fila.get("tipo_aviso") == AVISO_APUESTA
            and fila.get("estado") != ESTADO_NO_APOSTADA)


def gastado_del_dia(filas, fecha):
    return sum(num(f.get("importe")) for f in filas
               if f.get("fecha") == fecha and gasta_tope(f))


def resumen_apuestas(filas, solo_apostadas):
    """Aciertos, beneficio y ROI de las alertas liquidadas.

    solo_apostadas=True  -> lo que de verdad se aposto (estado 'apostada').
    solo_apostadas=False -> 'si las hubiese hecho todas': todas las alertas
                            de apuesta con su importe recomendado.
    """
    sel = []
    for f in filas:
        if f.get("tipo_aviso") != AVISO_APUESTA:
            continue
        if solo_apostadas and f.get("estado") != ESTADO_APOSTADA:
            continue
        sel.append(f)
    liquidadas = [f for f in sel if f.get("resultado") in ("ganada", "perdida")]
    ganadas = sum(1 for f in liquidadas if f["resultado"] == "ganada")
    invertido = sum(num(f.get("importe")) for f in liquidadas)
    beneficio = sum(beneficio_fila(f) for f in liquidadas)
    return {
        "n": len(sel),
        "liquidadas": len(liquidadas),
        "pendientes": len(sel) - len(liquidadas),
        "ganadas": ganadas,
        "acierto": ganadas / len(liquidadas) if liquidadas else None,
        "invertido": invertido,
        "beneficio": beneficio,
        "roi": beneficio / invertido if invertido else None,
    }


def beneficio_fila(f):
    """Beneficio de una alerta liquidada con su importe recomendado."""
    imp = num(f.get("importe"))
    if f.get("resultado") == "ganada":
        return imp * (num(f.get("cuota")) - 1.0)
    if f.get("resultado") == "perdida":
        return -imp
    return 0.0


def estado_partido(filas, fecha, j1, j2):
    """Lo apuntado hoy para un partido: {clave_seleccion: estado} y la
    apuesta que cuenta (apostada o pendiente) si la hay, o None."""
    from modelo.util import normalizar_nombre
    par = {normalizar_nombre(j1), normalizar_nombre(j2)}
    marcadas, apuesta = {}, None
    for f in filas:
        if f.get("fecha") != fecha or f.get("tipo_aviso") != AVISO_APUESTA:
            continue
        if {normalizar_nombre(f.get("j1", "")), normalizar_nombre(f.get("j2", ""))} != par:
            continue
        clave = json.dumps(seleccion(f), sort_keys=True)
        marcadas[clave] = f.get("estado", "")
        if gasta_tope(f):
            apuesta = f
    return marcadas, apuesta


# ─────────────────────────────────────────────────────────────────────────────
# SEGUIMIENTO POR MERCADO (sin y con volatilidad)
# ─────────────────────────────────────────────────────────────────────────────

_NIVEL_TEXTO = {"bajo": 5.0, "medio": 10.0}   # suficientes para aplicar la regla


def _vol(v):
    """Volatilidad guardada en la fila: numero, o el nivel en texto de las
    filas antiguas ('bajo'/'medio' valen para la regla; 'alto' no)."""
    t = str(v or "").strip().lower()
    if t in _NIVEL_TEXTO:
        return _NIVEL_TEXTO[t]
    n = safe_float(t, None)
    return n if n else None


def nivel_partido(f):
    """'baja/media', 'alta' o 'sin dato' segun el mas irregular de los dos."""
    from modelo.volatilidad import nivel_volatilidad
    niveles = []
    for k in ("vol_j1", "vol_j2"):
        t = str(f.get(k) or "").strip().lower()
        niveles.append(t if t in ("bajo", "medio", "alto") else nivel_volatilidad(t))
    if None in niveles or "" in niveles:
        return "sin dato"
    return "alta" if "alto" in niveles else "baja/media"


def _importe_con_volatilidad(f):
    """Importe que habria tenido la apuesta con la regla de volatilidad del
    vigia, o None si esa regla la habria descartado (o no se puede saber)."""
    from vigia import reglas
    v1, v2 = _vol(f.get("vol_j1")), _vol(f.get("vol_j2"))
    if v1 is None or v2 is None:
        return None
    req = reglas.requisito_volatilidad(v1, v2)
    if not req["ok"] or num(f.get("edge")) < req["edge_min"] - 1e-9:
        return None
    imp = num(f.get("importe"))
    return max(reglas.UNIDAD, imp - reglas.UNIDAD) if req["rebaja"] else imp


def _acumular(g, f, imp):
    g["n"] += 1
    if f.get("resultado") in ("ganada", "perdida"):
        g["liq"] += 1
        g["apostado"] += imp
        if f["resultado"] == "ganada":
            g["ganadas"] += 1
            g["beneficio"] += imp * (num(f.get("cuota")) - 1.0)
        else:
            g["beneficio"] -= imp


def _cerrar(g):
    g["acierto"] = g["ganadas"] / g["liq"] if g["liq"] else None
    g["roi"] = g["beneficio"] / g["apostado"] if g["apostado"] else None
    return g


def por_mercado(filas, con_volatilidad=False):
    """Seguimiento de cada mercado por separado.

    Para cada mercado (y un TOTAL), dos bloques: 'todas' (todas las apuestas
    con value, con su importe) y 'reales' (solo las marcadas 'apostada').
    con_volatilidad=True aplica la regla de volatilidad del vigia: quita las
    que esa regla habria descartado y baja el importe con volatilidad alta.
    Devuelve (lista de dicts por mercado, n de apuestas excluidas).
    """
    vacio = lambda: {"n": 0, "liq": 0, "ganadas": 0, "apostado": 0.0, "beneficio": 0.0}  # noqa: E731
    grupos, excluidas = {}, 0
    for f in filas:
        if f.get("tipo_aviso") != AVISO_APUESTA:
            continue
        imp = num(f.get("importe"))
        if con_volatilidad:
            imp = _importe_con_volatilidad(f)
            if imp is None:
                excluidas += 1
                continue
        for clave in (f.get("mercado") or "?", "TOTAL"):
            g = grupos.setdefault(clave, {"todas": vacio(), "reales": vacio()})
            _acumular(g["todas"], f, imp)
            if f.get("estado") == ESTADO_APOSTADA:
                _acumular(g["reales"], f, imp)
    salida = []
    for mercado in sorted(grupos, key=lambda m: (m == "TOTAL", m)):
        g = grupos[mercado]
        salida.append({"mercado": mercado, "todas": _cerrar(g["todas"]),
                       "reales": _cerrar(g["reales"])})
    return salida, excluidas


def por_mercado_y_volatilidad(filas):
    """Todas las apuestas con value, por mercado y nivel de volatilidad del
    partido: {(mercado, nivel): acumulado}."""
    res = {}
    for f in filas:
        if f.get("tipo_aviso") != AVISO_APUESTA:
            continue
        clave = (f.get("mercado") or "?", nivel_partido(f))
        g = res.setdefault(clave, {"n": 0, "liq": 0, "ganadas": 0, "apostado": 0.0,
                                   "beneficio": 0.0})
        _acumular(g, f, num(f.get("importe")))
    return {k: _cerrar(v) for k, v in res.items()}
