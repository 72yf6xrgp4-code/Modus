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
# Ultima lectura del boton "Modus value" de cada partido (los datos tal
# cual), para recuperar las cuotas en Value Bets hasta que se juegue
HOJA_LECTURAS = "lecturas_boton"
COLUMNAS_LECTURAS = ["fecha", "hora", "j1", "j2", "match_id", "lectura", "wm"]

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
    # Numero de partido de la jornada (1, 2, ... 15)
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
    # Partidos que cada jugador llevaba esta semana antes de este: solo se
    # guardan (y cuentan en las estadisticas) los partidos fiables
    "previos_j1", "previos_j2",
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


def banca_actual(filas):
    """Banca para el 1/4 de Kelly: la inicial (200 EUR) mas el beneficio
    real acumulado (tus apuestas liquidadas; si vas perdiendo, baja)."""
    from vigia.reglas import BANCA_INICIAL
    return max(0.0, BANCA_INICIAL + beneficio_real(filas))


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


def por_mercado(filas, con_volatilidad=False, todas=None):
    """Seguimiento de cada mercado por separado.

    Para cada mercado (y un TOTAL), dos bloques: 'todas' (por defecto, las
    apuestas de `filas`; o las de `todas`, p. ej. mejores_por_partido, con
    su importe recomendado) y 'reales' (las de `filas` marcadas 'apostada',
    con lo que de verdad apostaste).
    con_volatilidad=True aplica la regla de volatilidad del vigia: quita las
    que esa regla habria descartado y baja el importe con volatilidad alta.
    Devuelve (lista de dicts por mercado, n de 'todas' excluidas).
    """
    grupos, excluidas = {}, 0
    apuestas = [f for f in filas if f.get("tipo_aviso") == AVISO_APUESTA]
    if todas is None:
        todas = apuestas
    for bloque, lista in (("todas", todas),
                          ("reales", [f for f in apuestas if f.get("estado") == ESTADO_APOSTADA])):
        for f in lista:
            if f.get("tipo_aviso") != AVISO_APUESTA:
                continue
            imp = num(f.get("importe")) if bloque == "todas" else importe_apostado(f)
            if con_volatilidad:
                # simulacion de la regla: con el importe que daria la regla
                imp = _importe_con_volatilidad(f)
                if imp is None:
                    excluidas += bloque == "todas"
                    continue
            for clave in (f.get("mercado") or "?", "TOTAL"):
                g = grupos.setdefault(clave, {"todas": _vacio(), "reales": _vacio()})
                _acumular(g[bloque], f, imp)
    salida = []
    for mercado in sorted(grupos, key=lambda m: (m == "TOTAL", m)):
        g = grupos[mercado]
        salida.append({"mercado": mercado, "todas": _cerrar(g["todas"]),
                       "reales": _cerrar(g["reales"])})
    return salida, excluidas


# ─────────────────────────────────────────────────────────────────────────────
# PARTIDOS FIABLES Y "SI LAS HUBIERAS HECHO TODAS"
# ─────────────────────────────────────────────────────────────────────────────

# Un partido es fiable si los dos jugadores llevan al menos estos partidos
# esta semana antes de el (de cualquier dia): con menos, el modelo casi no
# tiene datos suyos.
MIN_PREVIOS = 3


def fiable(fila):
    """True si los dos jugadores llevaban MIN_PREVIOS partidos o mas."""
    previos = [str(fila.get(k, "")).strip() for k in ("previos_j1", "previos_j2")]
    return all(p != "" and num(p) >= MIN_PREVIOS for p in previos)


def mejores_por_partido(filas_winamax):
    """'Si las hubieras hecho todas': de cada partido fiable leido con el
    boton, la mejor apuesta (la de mas edge entre las que tu regla manda
    apostar, importe > 0) de la ultima lectura, con el importe que indicaba
    el modelo. Devuelve filas con la forma de las de 'alertas'."""
    partidos = {}
    for f in filas_winamax:
        if not fiable(f) or not f.get("seleccion_json"):
            continue
        clave = (f.get("fecha"), f.get("match_id") or f"{f.get('j1')}|{f.get('j2')}")
        partidos.setdefault(clave, []).append(f)
    mejores = []
    for fs in partidos.values():
        ultima = max(num(f.get("lectura")) for f in fs)
        candidatas = [f for f in fs if num(f.get("lectura")) == ultima and num(f.get("importe")) > 0]
        if candidatas:
            m = max(candidatas, key=lambda f: num(f.get("edge")))
            mejores.append(dict(m, tipo_aviso=AVISO_APUESTA, estado="",
                                partido=f"{m.get('j1')} vs {m.get('j2')}"))
    return sorted(mejores, key=lambda f: (str(f.get("fecha")), str(f.get("hora"))))


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

    Solo cuentan los partidos fiables (fiable(): 3 partidos previos o mas).
    """
    filas = _ultimas_lecturas([f for f in filas if fiable(f)])
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
    prec = {}
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

    return {"resumen": resumen, "margen": margen, "precision": precision,

            "tramos": [cerrar(t[2], tramos[t[2]]) for t in TRAMOS_EDGE],
            "mercados": [cerrar(m, g) for m, g in sorted(mercados.items())]}
