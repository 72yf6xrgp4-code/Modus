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
HOJA_WINAMAX = "cuotas_winamax"

COLUMNAS_ALERTAS = [
    "id", "fecha", "hora", "partido", "j1", "j2", "vol_j1", "vol_j2",
    "mercado", "seleccion", "cuota", "p_modelo", "edge", "margen", "verde",
    "importe", "tope_restante", "estado", "resultado", "beneficio",
    # Columnas tecnicas (al final)
    "tipo_aviso", "inicio", "match_id", "jornada", "orden_j1",
    "seleccion_json",
    # Lo que de verdad apostaste si cambiaste el importe a mano (vacio = el
    # recomendado). Al final para no descolocar las filas antiguas.
    "importe_real",
    # Numero de partido de la jornada (1, 2, ... 15), para ver si el modelo
    # acierta mas cuando los jugadores llevan mas partidos ese dia
    "n_partido",
]
COLUMNAS_LOG = ["fecha", "hora", "tipo", "partido", "detalle"]

# Una fila por seleccion de cada partido avisado por el vigia.
# cuota_min_aviso = edge 20 % (5 EUR); cuota_min_10 = edge 35 %;
# cuota_min_15 = edge 50 % (10 y 15 EUR solo si ademas es 🟢 y cuota <= 4);
# cuota_min_verde = la que hace la seleccion 🟢 (vacia en resultado exacto).
# edge_exigido = 20 %, o mas con volatilidad alta (vigia/reglas.py).
COLUMNAS_CUOTAS = [
    "fecha", "hora", "inicio_estimado", "jornada", "orden", "j1", "j2",
    "vol_j1", "vol_j2", "mercado", "seleccion", "p", "cuota_justa",
    "cuota_min_aviso", "cuota_min_10", "cuota_min_15", "cuota_min_verde",
    "edge_exigido",
]

# Una fila por cuota leida con el boton "Modus value" (tambien las que el
# modelo no cubre, para medir el margen de Winamax). 'lectura' identifica
# cada pulsacion del boton; 'resultado' (ganada/perdida) lo apunta el vigia.
COLUMNAS_WINAMAX = [
    "fecha", "hora", "lectura", "match_id", "inicio", "j1", "j2", "vol_j1",
    "vol_j2", "titulo", "salida", "mercado", "seleccion", "cuota", "p_modelo",
    "cuota_justa", "edge", "verde", "importe", "fuente", "resultado",
    "seleccion_json",
    "jornada", "n_partido",
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


def importe_apostado(fila):
    """Lo que de verdad apostaste: el importe cambiado a mano (importe_real)
    o, si no lo cambiaste, el recomendado (importe)."""
    real = str(fila.get("importe_real") or "").strip()
    return num(real) if real else num(fila.get("importe"))


def beneficio_real(filas, hasta=None):
    """Beneficio acumulado de las apuestas marcadas 'apostada' ya liquidadas
    (de fechas anteriores a `hasta`, si se indica), con lo que apostaste."""
    return sum(beneficio_fila(f, real=True) for f in filas
               if f.get("tipo_aviso") == AVISO_APUESTA
               and f.get("estado") == ESTADO_APOSTADA
               and f.get("resultado") in ("ganada", "perdida")
               and (hasta is None or str(f.get("fecha", "")) < hasta))


def tope_del_dia(filas, base=None):
    """Tope de la jornada: la base (50 EUR) mas el beneficio real acumulado.
    Si vas en perdidas, se queda en la base."""
    from vigia.reglas import TOPE_DIARIO
    base = TOPE_DIARIO if base is None else base
    return base + max(0.0, beneficio_real(filas))


def gastado_del_dia(filas, fecha):
    return sum(importe_apostado(f) for f in filas
               if f.get("fecha") == fecha and gasta_tope(f))


def resumen_apuestas(filas, solo_apostadas):
    """Aciertos, beneficio y ROI de las alertas liquidadas.

    solo_apostadas=True  -> lo que de verdad se aposto (estado 'apostada'),
                            con el importe apostado (importe_real si se cambio).
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
    importe = importe_apostado if solo_apostadas else (lambda f: num(f.get("importe")))
    invertido = sum(importe(f) for f in liquidadas)
    beneficio = sum(beneficio_fila(f, real=solo_apostadas) for f in liquidadas)
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


def beneficio_fila(f, real=False):
    """Beneficio de una alerta liquidada con su importe recomendado (o, con
    real=True, con lo que de verdad apostaste)."""
    imp = importe_apostado(f) if real else num(f.get("importe"))
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
    return reglas.bajar_escalon(imp) if req["rebaja"] else imp


def _vacio():
    return {"n": 0, "liq": 0, "ganadas": 0, "apostado": 0.0, "beneficio": 0.0}


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
    con value, con su importe recomendado) y 'reales' (solo las marcadas
    'apostada', con lo que de verdad apostaste).
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
                # Sin volatilidad, lo que de verdad apostaste; con volatilidad
                # es una simulacion de la regla y va con el importe simulado
                _acumular(g["reales"], f, imp if con_volatilidad else importe_apostado(f))
    salida = []
    for mercado in sorted(grupos, key=lambda m: (m == "TOTAL", m)):
        g = grupos[mercado]
        salida.append({"mercado": mercado, "todas": _cerrar(g["todas"]),
                       "reales": _cerrar(g["reales"])})
    return salida, excluidas


# ─────────────────────────────────────────────────────────────────────────────
# POR NUMERO DE PARTIDO DE LA JORNADA
# ─────────────────────────────────────────────────────────────────────────────

# Cada jornada tiene 15 partidos (6 jugadores, todos contra todos): en los
# primeros, la forma de hoy casi no tiene datos; en los ultimos, cada
# jugador lleva 3-4 partidos ese dia.
TRAMOS_PARTIDO = [(1, 3, "1.º-3.º"), (4, 6, "4.º-6.º"), (7, 9, "7.º-9.º"),
                  (10, 12, "10.º-12.º"), (13, None, "13.º o más")]
SIN_NUMERO = "sin dato"


def tramo_partido(fila):
    """Tramo de TRAMOS_PARTIDO del numero de partido de la fila."""
    n = int(num(fila.get("n_partido")) or 0)
    for desde, hasta, nombre in TRAMOS_PARTIDO:
        if n >= desde and (hasta is None or n <= hasta):
            return nombre
    return SIN_NUMERO


def _orden_tramos(grupos):
    return [t[2] for t in TRAMOS_PARTIDO if t[2] in grupos] + (
        [SIN_NUMERO] if SIN_NUMERO in grupos else [])


def por_numero_partido(filas):
    """Apuestas con value por numero de partido de la jornada: 'todas' (con
    el importe recomendado), 'reales' (las apostadas, con lo apostado) y
    'p_media' (lo que daba el modelo de media en las liquidadas, para
    compararlo con el acierto real: cuanto mas cerca, mas fiable)."""
    grupos = {}
    for f in filas:
        if f.get("tipo_aviso") != AVISO_APUESTA:
            continue
        g = grupos.setdefault(tramo_partido(f), {"todas": _vacio(), "reales": _vacio(), "p": 0.0})
        _acumular(g["todas"], f, num(f.get("importe")))
        if f.get("resultado") in ("ganada", "perdida"):
            g["p"] += num(f.get("p_modelo"))
        if f.get("estado") == ESTADO_APOSTADA:
            _acumular(g["reales"], f, importe_apostado(f))
    salida = []
    for t in _orden_tramos(grupos):
        g = grupos[t]
        liq = g["todas"]["liq"]
        salida.append({"tramo": t, "todas": _cerrar(g["todas"]), "reales": _cerrar(g["reales"]),
                       "p_media": g["p"] / liq if liq else None})
    return salida


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


# ─────────────────────────────────────────────────────────────────────────────
# ESTADISTICAS DE LAS CUOTAS DE WINAMAX
# ─────────────────────────────────────────────────────────────────────────────

TRAMOS_EDGE = [(None, 0.0, "negativo"), (0.0, 0.10, "0-10 %"), (0.10, 0.20, "10-20 %"),
               (0.20, 0.35, "20-35 %"), (0.35, 0.50, "35-50 %"), (0.50, None, "más de 50 %")]


def _ultimas_lecturas(filas):
    """Si el mismo partido se leyo varias veces, la ultima lectura de cada
    salida (la mas cercana al inicio)."""
    ultimas = {}
    for f in filas:
        clave = (f.get("fecha"), f.get("match_id") or f"{f.get('j1')}|{f.get('j2')}",
                 f.get("titulo"), f.get("salida"))
        if clave not in ultimas or num(f.get("lectura")) >= num(ultimas[clave].get("lectura")):
            ultimas[clave] = f
    return list(ultimas.values())


def estadisticas_winamax(filas):
    """Comparacion de las cuotas de Winamax con el modelo.

    Devuelve dict con:
      resumen    lecturas, cuotas, liquidadas
      margen     por mercado: margen medio de Winamax (suma de 1/cuota - 1)
      precision  por mercado (liquidadas): Brier del modelo y de Winamax
                 (menor = mejor) y quien acierta mas
      tramos     por tramo de edge: apuestas de 1 EUR a todas, aciertos, ROI
      mercados   por mercado, solo con edge >= 20 % (tu regla): n, ROI
      partidos   por numero de partido de la jornada (liquidadas): Brier del
                 modelo y de Winamax, probabilidad media del modelo frente al
                 acierto real, y 1 EUR a las de edge >= 20 %
    """
    filas = _ultimas_lecturas(filas)
    resumen = {"lecturas": len({f.get("lectura") for f in filas}),
               "cuotas": len(filas),
               "liquidadas": sum(1 for f in filas if f.get("resultado") in ("ganada", "perdida"))}

    # Margen de Winamax: grupos (lectura, titulo) con 2 o mas salidas
    grupos = {}
    for f in filas:
        if num(f.get("cuota")) > 1:
            grupos.setdefault((f.get("lectura"), f.get("titulo")), []).append(f)
    margen, prob_winamax = {}, {}
    for (lect, tit), fs in grupos.items():
        inversa = sum(1.0 / num(f["cuota"]) for f in fs)
        for f in fs:   # probabilidad de Winamax sin su margen
            prob_winamax[id(f)] = (1.0 / num(f["cuota"])) / inversa if len(fs) > 1 else None
        if len(fs) >= 2:
            m = fs[0].get("mercado") or tit
            margen.setdefault(m, []).append(inversa - 1.0)
    margen = [{"mercado": m, "mercados": len(v), "margen": sum(v) / len(v)}
              for m, v in sorted(margen.items())]

    # Precision: Brier del modelo y de Winamax en las liquidadas
    prec, por_n = {}, {}
    for f in filas:
        if f.get("resultado") not in ("ganada", "perdida") or f.get("p_modelo") in ("", None):
            continue
        q = prob_winamax.get(id(f))
        if q is None:
            continue
        y = 1.0 if f["resultado"] == "ganada" else 0.0
        for m in (f.get("mercado") or "?", "TOTAL"):
            g = prec.setdefault(m, {"n": 0, "modelo": 0.0, "winamax": 0.0})
            g["n"] += 1
            g["modelo"] += (num(f["p_modelo"]) - y) ** 2
            g["winamax"] += (q - y) ** 2
        g = por_n.setdefault(tramo_partido(f), {"n": 0, "modelo": 0.0, "winamax": 0.0,
                                                "p": 0.0, "ganadas": 0,
                                                "ap": 0, "ap_ganadas": 0, "ap_beneficio": 0.0})
        g["n"] += 1
        g["modelo"] += (num(f["p_modelo"]) - y) ** 2
        g["winamax"] += (q - y) ** 2
        g["p"] += num(f["p_modelo"])
        g["ganadas"] += int(y)
        if num(f.get("edge")) >= 0.20:   # tu regla: apostar 1 EUR
            g["ap"] += 1
            g["ap_ganadas"] += int(y)
            g["ap_beneficio"] += (num(f["cuota"]) - 1.0) if y else -1.0
    precision = []
    for m in sorted(prec, key=lambda k: (k == "TOTAL", k)):
        g = prec[m]
        bm, bw = g["modelo"] / g["n"], g["winamax"] / g["n"]
        precision.append({"mercado": m, "n": g["n"], "brier_modelo": bm, "brier_winamax": bw,
                          "mejor": "modelo" if bm < bw else ("Winamax" if bw < bm else "igual")})

    # Apostar 1 EUR a todas, por tramo de edge y (edge >= 20 %) por mercado
    def acumula(g, f):
        g["n"] += 1
        if f["resultado"] == "ganada":
            g["ganadas"] += 1
            g["beneficio"] += num(f["cuota"]) - 1.0
        else:
            g["beneficio"] -= 1.0

    tramos = {t[2]: {"n": 0, "ganadas": 0, "beneficio": 0.0} for t in TRAMOS_EDGE}
    mercados = {}
    for f in filas:
        if f.get("resultado") not in ("ganada", "perdida") or f.get("edge") in ("", None):
            continue
        e = num(f["edge"])
        for desde, hasta, nombre in TRAMOS_EDGE:
            if (desde is None or e >= desde) and (hasta is None or e < hasta):
                acumula(tramos[nombre], f)
                break
        if e >= 0.20:
            acumula(mercados.setdefault(f.get("mercado") or "?",
                                        {"n": 0, "ganadas": 0, "beneficio": 0.0}), f)

    def cerrar(nombre, g):
        return {"nombre": nombre, "n": g["n"], "ganadas": g["ganadas"],
                "beneficio": g["beneficio"], "roi": g["beneficio"] / g["n"] if g["n"] else None}

    partidos = []
    for t in _orden_tramos(por_n):
        g = por_n[t]
        partidos.append({"tramo": t, "n": g["n"], "brier_modelo": g["modelo"] / g["n"],
                         "brier_winamax": g["winamax"] / g["n"], "p_media": g["p"] / g["n"],
                         "acierto": g["ganadas"] / g["n"], "apuestas": g["ap"],
                         "ap_ganadas": g["ap_ganadas"], "ap_beneficio": g["ap_beneficio"],
                         "ap_roi": g["ap_beneficio"] / g["ap"] if g["ap"] else None})

    return {"resumen": resumen, "margen": margen, "precision": precision,
            "partidos": partidos,
            "tramos": [cerrar(t[2], tramos[t[2]]) for t in TRAMOS_EDGE],
            "mercados": [cerrar(m, g) for m, g in sorted(mercados.items())]}
