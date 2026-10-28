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
