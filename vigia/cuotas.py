"""
vigia/cuotas.py - Lista de selecciones del modelo y tabla de cuotas
minimas de un partido (sin red).
"""

from modelo.motor import MARCADORES, probabilidad
from vigia import reglas
from vigia.mercados import texto_seleccion

NOMBRE_MERCADO = {
    "ganador": "Ganador", "handicap": "Hándicap", "total_legs": "Total de legs",
    "resultado": "Resultado exacto", "180_jugador": "180s jugador",
    "180_total": "180s totales", "mas_180": "Más 180s",
    "hcap_180": "Hándicap 180s",
}


def selecciones():
    """Todas las selecciones que cubre el modelo, con J1/J2 del cartel."""
    sel = [{"tipo": "ganador", "jugador": j} for j in (1, 2)]
    sel += [{"tipo": "handicap", "jugador": j, "linea": h}
            for j in (1, 2) for h in (-1.5, -2.5, -3.5, 1.5, 2.5, 3.5)]
    sel += [{"tipo": "total_legs", "lado": lado, "linea": l}
            for l in (4.5, 5.5, 6.5) for lado in ("mas", "menos")]
    sel += [{"tipo": "resultado", "legs1": a, "legs2": b} for a, b in MARCADORES]
    sel += [{"tipo": "180_jugador", "jugador": j, "lado": lado, "linea": l}
            for j in (1, 2) for l in (0.5, 1.5, 2.5) for lado in ("mas", "menos")]
    sel += [{"tipo": "180_total", "lado": lado, "linea": l}
            for l in (0.5, 1.5, 2.5) for lado in ("mas", "menos")]
    sel += [{"tipo": "mas_180", "quien": q} for q in (1, 0, 2)]
    sel += [{"tipo": "hcap_180", "jugador": j, "linea": 0.5} for j in (1, 2)]
    return sel


def tabla(calc, j1, j2, edge_min=reglas.EDGE_MIN, rebaja=False, banca=reglas.BANCA_INICIAL):
    """Filas con p, cuota justa y cuotas minimas de cada seleccion (con el
    edge exigido y la rebaja de importe de reglas.requisito_volatilidad)."""
    filas = []
    for sel in selecciones():
        p = probabilidad(calc, sel)
        mercado = reglas.MERCADO_DE_TIPO[sel["tipo"]]
        filas.append({
            "sel": sel, "mercado": mercado,
            "nombre_mercado": NOMBRE_MERCADO[sel["tipo"]],
            "texto": texto_seleccion(sel, j1, j2), "p": p,
            **reglas.cuotas_minimas(mercado, p, edge_min, rebaja, banca),
        })
    return filas


def _num(v):
    return f"{v:.2f}".replace(".", ",")


def resumen_aviso(filas, j1, j2):
    """Las 3 referencias del aviso: ganador favorito, su handicap -1,5 y el
    lado mas probable del total de 5,5 legs (cuota minima para avisar)."""
    def buscar(**k):
        return next(f for f in filas if all(f["sel"].get(a) == b for a, b in k.items()))

    g1, g2 = buscar(tipo="ganador", jugador=1), buscar(tipo="ganador", jugador=2)
    fav = 1 if g1["p"] >= g2["p"] else 2
    ganador = g1 if fav == 1 else g2
    hcap = buscar(tipo="handicap", jugador=fav, linea=-1.5)
    mas = buscar(tipo="total_legs", lado="mas", linea=5.5)
    menos = buscar(tipo="total_legs", lado="menos", linea=5.5)
    legs = mas if mas["p"] >= menos["p"] else menos
    ape = j1.split()[-1] if fav == 1 else j2.split()[-1]
    lado = "Más" if legs is mas else "Menos"
    return [f"Gana {ape} ≥{_num(ganador['aviso'])}",
            f"{ape} −1,5 ≥{_num(hcap['aviso'])}",
            f"{lado} 5,5 legs ≥{_num(legs['aviso'])}"]


def evaluar_cuotas(calc, cuotas_sel, j1, j2, banca=reglas.BANCA_INICIAL):
    """Evalua con tus reglas una lista de cuotas [(sel, cuota, origen)].

    Para APUNTAR la volatilidad no cuenta (20 % de edge e importe normal).
    Si la misma seleccion llega dos veces (casilla y boton), manda la
    primera. Devuelve filas ordenadas por edge con sel, texto,
    nombre_mercado, cuota, p, justa, ev (de reglas.evaluar) y origen.
    """
    import json
    vistas, filas = set(), []
    for sel, cuota, origen in cuotas_sel:
        k = json.dumps(sel, sort_keys=True)
        if k in vistas or not cuota or cuota <= 1:
            continue
        vistas.add(k)
        p = probabilidad(calc, sel)
        if p is None:
            continue
        mercado = reglas.MERCADO_DE_TIPO[sel["tipo"]]
        filas.append({"sel": sel, "clave": k, "texto": texto_seleccion(sel, j1, j2),
                      "nombre_mercado": NOMBRE_MERCADO[sel["tipo"]],
                      "cuota": float(cuota), "p": p, "justa": 1.0 / p,
                      "ev": reglas.evaluar(mercado, p, float(cuota), banca=banca),
                      "origen": origen})
    filas.sort(key=lambda f: f["ev"]["edge"], reverse=True)
    return filas
