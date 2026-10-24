"""
comparativa.py - Modelo anterior (v1) frente al modelo calibrado (v2).

Dos comparaciones, las dos sobre las predicciones de la hoja 'Predicciones':

1) Retroactiva ("que habria dicho el modelo nuevo"): para cada partido ya
   verificado se reconstruyen los datos con los que se calculo (diferencia de
   PG entre los jugadores y media de 180s de cada uno) a partir de las
   probabilidades que guardo el modelo anterior, y se recalculan todos los
   mercados con el modelo nuevo. Asi se comparan los dos modelos sobre
   EXACTAMENTE los mismos partidos.
     - Diferencia de PG: se despeja de la probabilidad de victoria guardada
       (con S y B del modelo anterior). Solo importa la diferencia, no los PG.
     - 180s: de "J1 +0.5" (P de hacer al menos uno) sale la lambda que uso el
       modelo; se le quita el ajuste por legs esperados del modelo anterior.
   Las probabilidades del modelo anterior son las guardadas en la hoja (lo
   que de verdad se predijo), no recalculadas.

2) En vivo: las predicciones registradas desde el cambio llevan "v2" en la
   columna Modelo; se comparan sus metricas reales con las de las filas sin
   version (v1). Necesita unas semanas de datos para ser fiable.

Metricas (de cada linea de mercado, sobre el suceso de esa linea):
  - Acierto: % de veces que el lado que elige el modelo (prob >= 50 %) sale.
  - Brier: media de (prob - resultado)^2. Menor es mejor. 0,25 = moneda.
  - Log-loss: penaliza mucho fallar con mucha confianza. Menor es mejor.
"""

import math

import numpy as np
import pandas as pd

from config import MODELOS, LEGS_PROMEDIO_REFERENCIA
from stats_engine import (simular_match, legs_esperados_desde_finales,
                          prob_victoria, handicaps_legs, legs_totales,
                          prob_180s, quien_hace_mas_180s)

# PG "base" para reconstruir los partidos: el modelo solo depende de la
# diferencia de PG, asi que usamos 1000+d contra 1000.
_PG_BASE = 1000.0
_LAMBDA_MIN = 0.1

# Lineas binarias de 180s y su nombre en el modelo nuevo
_LINEAS_180 = {
    "J1 +0.5": "J1 +0.5", "J1 +1.5": "J1 +1.5",
    "J2 +0.5": "J2 +0.5", "J2 +1.5": "J2 +1.5",
    "Ambos +0.5": "Ambos +0.5",
    "Ambos +1.5": "Total +1.5", "Total +1.5": "Total +1.5",
    "Ambos +2.5": "Total +2.5", "Total +2.5": "Total +2.5",
}
_LINEAS_HANDICAP = ("J1 -1.5 Legs", "J1 -2.5 Legs", "J1 +1.5 Legs",
                    "J1 +2.5 Legs")
MERCADO_H2H = "Mas 180s (H2H)"


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def _prob(v):
    """Probabilidad de la hoja (texto con coma) -> float 0-1, o None."""
    try:
        x = float(str(v).strip().replace(",", "."))
    except Exception:
        return None
    if 0.0 <= x <= 1.0:
        return x
    for div in (100.0, 1000.0, 10000.0):   # residuos de comas perdidas
        if x <= div:
            return x / div
    return None


def _acierto(v):
    s = str(v).strip().lower()
    if s in ("1", "si", "sí", "true", "verdadero", "acierto", "ok"):
        return 1
    if s in ("0", "no", "false", "falso", "fallo"):
        return 0
    return None


def _p1_old(d, S, B):
    fin = simular_match(_PG_BASE + d, _PG_BASE, True, S, B)
    return sum(p for (a, _b), p in fin.items() if a >= 4)


def _despejar_d(p1, S, B):
    """Diferencia de PG que da P(gana J1) = p1 con S y B (biseccion)."""
    p1 = min(max(p1, 1e-4), 1 - 1e-4)
    lo, hi = -600.0, 600.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _p1_old(mid, S, B) < p1:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _factor_legs(d, S, B):
    fin = simular_match(_PG_BASE + d, _PG_BASE, True, S, B)
    e = legs_esperados_desde_finales(fin)
    return e / LEGS_PROMEDIO_REFERENCIA if e > 0 else 1.0


def _lambda_de_p05(p):
    """Lambda (ya ajustada) a partir de P(al menos un 180)."""
    if p is None:
        return None
    p = min(max(p, 0.0), 0.9999)
    return -math.log(1.0 - p) if p > 0.0001 else 0.0


def _brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def _logloss(p, y):
    p = np.clip(np.asarray(p, dtype=float), 0.01, 0.99)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


# ─────────────────────────────────────────────────────────────────────────────
# 1) COMPARACION RETROACTIVA
# ─────────────────────────────────────────────────────────────────────────────

def _filas_partido(grupo):
    """{(mercado, linea): fila} de un partido."""
    out = {}
    for _, f in grupo.iterrows():
        out[(str(f.get("Mercado", "")).strip(),
             str(f.get("Linea", "")).strip())] = f
    return out


def _suceso(fila, lado_del_suceso):
    """1/0 si ocurrio el suceso de la linea. lado_del_suceso: True si la
    prediccion guardada apostaba por el suceso."""
    a = _acierto(fila.get("Acierto", ""))
    if a is None:
        return None
    return a if lado_del_suceso else 1 - a


def _resultado_h2h(filas, ev):
    """Quien hizo mas 180s ('J1'/'Empate'/'J2') a partir de los sucesos de las
    lineas de 180s verificadas; None si no se puede saber."""
    def cubo(j):
        a, b = ev.get(f"{j} +0.5"), ev.get(f"{j} +1.5")
        if a == 0:
            return 0
        if a == 1 and b == 0:
            return 1
        if a == 1 and b == 1:
            return 2  # 2 o mas
        return None
    c1, c2 = cubo("J1"), cubo("J2")
    if c1 is not None and c2 is not None and not (c1 == 2 and c2 == 2):
        return "J1" if c1 > c2 else ("J2" if c2 > c1 else "Empate")
    # Caso dudoso (los dos 2+): si el H2H registrado acerto, ese fue
    f = filas.get((MERCADO_H2H, "Quien hace mas 180s"))
    if f is not None and _acierto(f.get("Acierto", "")) == 1:
        pred = str(f.get("Prediccion", ""))
        return ("J1" if pred.startswith("J1") else
                "J2" if pred.startswith("J2") else "Empate")
    return None


def comparar_retroactivo(df, v_old="v1", v_new="v2"):
    """Recalcula con el modelo nuevo los partidos verificados del modelo
    anterior.

    Recibe el DataFrame ya limpio (predicciones.limpiar_predicciones). Usa
    solo las filas del modelo anterior (columna Modelo vacia o = v_old).

    Devuelve un DataFrame con una fila por (partido, linea):
      partido, semana, mercado, linea, p_old, p_new, y
    donde p_* es la probabilidad del SUCESO de la linea (gana J1, J1 gana por
    2+, mas de 5,5 legs, J1 hace un 180...) e y = 1 si ocurrio.
    El H2H de 180s va aparte con p_old/p_new del resultado que ocurrio.
    """
    cols = ["partido", "semana", "mercado", "linea", "p_old", "p_new", "y"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    d = df.copy()
    if "Modelo" in d.columns:
        mod = d["Modelo"].astype(str).str.strip()
        d = d[(mod == "") | (mod == v_old)]
    if d.empty:
        return pd.DataFrame(columns=cols)

    S_old, B_old = MODELOS[v_old]["S"], MODELOS[v_old]["B"]
    claves = ["Semana", "Jornada", "Jugador 1", "Jugador 2", "Fecha registro"]
    claves = [c for c in claves if c in d.columns]
    filas_out = []

    for clave, grupo in d.groupby(claves, sort=False):
        filas = _filas_partido(grupo)
        nombre = f"{clave[2]} vs {clave[3]}" if len(clave) >= 4 else str(clave)
        semana = clave[0] if clave else ""
        # Identificador unico del partido (la misma pareja puede jugar
        # varias semanas o en grupo y Final)
        nombre = nombre + " · " + " | ".join(str(c) for c in clave)

        # --- diferencia de PG desde el ganador guardado ---
        fg = filas.get(("Ganador", "Ganador del partido"))
        if fg is None:
            continue
        pg = _prob(fg.get("Probabilidad modelo"))
        if pg is None:
            continue
        pred_j1 = str(fg.get("Prediccion", "")).strip() == "Gana J1"
        p1_old = pg if pred_j1 else 1.0 - pg
        dpg = _despejar_d(p1_old, S_old, B_old)
        pr1, pr2 = _PG_BASE + dpg, _PG_BASE

        # --- modelo nuevo: ganador, handicaps y total de legs ---
        p1_new, _ = prob_victoria(pr1, pr2)
        hc_new = handicaps_legs(pr1, pr2)
        over_new = legs_totales(pr1, pr2)["Más de 5.5"]

        ev = {}  # sucesos de las lineas de 180s (para el H2H)

        y = _suceso(fg, pred_j1)
        if y is not None:
            filas_out.append([nombre, semana, "Ganador", "Gana J1",
                              p1_old, p1_new, y])

        for linea in _LINEAS_HANDICAP:
            f = filas.get(("Handicap legs", linea))
            if f is None:
                continue
            p_old = _prob(f.get("Probabilidad modelo"))
            si = str(f.get("Prediccion", "")).strip() == "Si"
            y = _suceso(f, si)
            if p_old is not None and y is not None:
                filas_out.append([nombre, semana, "Handicap legs", linea,
                                  p_old, hc_new[linea], y])

        f = filas.get(("Total legs", "Total de legs"))
        if f is not None:
            p = _prob(f.get("Probabilidad modelo"))
            over = str(f.get("Prediccion", "")).strip().startswith("Más")
            y = _suceso(f, over)
            if p is not None and y is not None:
                filas_out.append([nombre, semana, "Total legs", "Más de 5.5",
                                  p if over else 1.0 - p, over_new, y])

        # --- 180s: lambdas reconstruidas ---
        f1 = filas.get(("180s", "J1 +0.5"))
        f2 = filas.get(("180s", "J2 +0.5"))
        if f1 is None or f2 is None:
            continue
        fac_old = _factor_legs(dpg, S_old, B_old)
        l1 = _lambda_de_p05(_prob(f1.get("Probabilidad modelo")))
        l2 = _lambda_de_p05(_prob(f2.get("Probabilidad modelo")))
        if l1 is None or l2 is None:
            continue
        # Lambda "en bruto" del jugador (sin el ajuste por legs esperados)
        lam1, lam2 = l1 / fac_old, l2 / fac_old
        m180_new = prob_180s(lam1, lam2, pr1, pr2)

        for (mercado, linea), f in filas.items():
            if mercado != "180s" or linea not in _LINEAS_180:
                continue
            p_old = _prob(f.get("Probabilidad modelo"))
            si = str(f.get("Prediccion", "")).strip() == "Si"
            y = _suceso(f, si)
            if p_old is None or y is None:
                continue
            nueva = _LINEAS_180[linea]
            ev[nueva] = y
            filas_out.append([nombre, semana, "180s", nueva, p_old,
                              m180_new[nueva], y])

        # --- H2H de 180s (3 resultados) ---
        fh = filas.get((MERCADO_H2H, "Quien hace mas 180s"))
        res = _resultado_h2h(filas, ev)
        if fh is not None and res is not None:
            # Modelo anterior: Poisson sin acercar a la media, con su factor
            from scipy.stats import poisson
            a1 = max(l1, _LAMBDA_MIN)
            a2 = max(l2, _LAMBDA_MIN)
            pm1 = poisson.pmf(np.arange(16), a1)
            pm2 = poisson.pmf(np.arange(16), a2)
            mat = np.outer(pm1, pm2)
            old = {"J1": float(np.tril(mat, -1).sum()),
                   "Empate": float(np.trace(mat)),
                   "J2": float(np.triu(mat, 1).sum())}
            nj1, nemp, nj2 = quien_hace_mas_180s(lam1, lam2, pr1, pr2)
            new = {"J1": nj1, "Empate": nemp, "J2": nj2}
            fav_old = max(old, key=old.get)
            fav_new = max(new, key=new.get)
            filas_out.append([nombre, semana, MERCADO_H2H,
                              f"fav. {fav_old}|{fav_new}|{res}",
                              old[res], new[res], 1])

    return pd.DataFrame(filas_out, columns=cols)


def resumen_retroactivo(bt):
    """Tabla por mercado con las metricas de los dos modelos.

    Devuelve (tabla_mercados, global) donde tabla_mercados es un DataFrame:
      Mercado, Partidos/lineas, Acierto antes, Acierto ahora,
      Brier antes, Brier ahora, Log-loss antes, Log-loss ahora
    """
    if bt is None or bt.empty:
        return pd.DataFrame(), {}
    filas = []
    binario = bt[bt["mercado"] != MERCADO_H2H]

    def _fila(nombre, g):
        y = g["y"].values
        po, pn = g["p_old"].values, g["p_new"].values
        return {
            "Mercado": nombre,
            "N": len(g),
            "Acierto antes": 100 * np.mean((po >= 0.5) == (y == 1)),
            "Acierto ahora": 100 * np.mean((pn >= 0.5) == (y == 1)),
            "Brier antes": _brier(po, y),
            "Brier ahora": _brier(pn, y),
            "Log-loss antes": _logloss(po, y),
            "Log-loss ahora": _logloss(pn, y),
        }

    orden = [("Ganador", None), ("Handicap legs", None),
             ("Total legs", None), ("180s", None)]
    for mercado, _ in orden:
        g = binario[binario["mercado"] == mercado]
        if len(g):
            filas.append(_fila(mercado, g))
    for linea, g in binario[binario["mercado"] == "180s"].groupby("linea"):
        filas.append(_fila(f"   180s · {linea}", g))

    h = bt[bt["mercado"] == MERCADO_H2H]
    if len(h):
        partes = h["linea"].str.split("|", expand=True)
        fav_old = partes[0].str.replace("fav. ", "", regex=False)
        fav_new, real = partes[1], partes[2]
        filas.append({
            "Mercado": MERCADO_H2H,
            "N": len(h),
            "Acierto antes": 100 * float((fav_old == real).mean()),
            "Acierto ahora": 100 * float((fav_new == real).mean()),
            # Brier/log-loss de 3 resultados: solo log-loss es comparable
            "Brier antes": float("nan"),
            "Brier ahora": float("nan"),
            "Log-loss antes": float(-np.mean(np.log(np.clip(h["p_old"], .01, 1)))),
            "Log-loss ahora": float(-np.mean(np.log(np.clip(h["p_new"], .01, 1)))),
        })

    tabla = pd.DataFrame(filas)
    glob = {}
    if len(binario):
        y = binario["y"].values
        glob = {
            "partidos": int(bt["partido"].nunique()),
            "lineas": int(len(binario)),
            "brier_antes": _brier(binario["p_old"].values, y),
            "brier_ahora": _brier(binario["p_new"].values, y),
            "acierto_antes": 100 * np.mean((binario["p_old"].values >= .5) == (y == 1)),
            "acierto_ahora": 100 * np.mean((binario["p_new"].values >= .5) == (y == 1)),
        }
    return tabla, glob


def calibracion_retroactiva(bt, mercado, tramos=None):
    """Calibracion de los dos modelos para un mercado binario: por tramos de
    probabilidad del lado elegido, prob media frente a % real."""
    tramos = tramos or [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9),
                        (0.9, 1.01)]
    g = bt[bt["mercado"] == mercado]
    out = []
    for col, nombre in (("p_old", "Antes"), ("p_new", "Ahora")):
        p = g[col].values
        conf = np.where(p >= 0.5, p, 1 - p)            # confianza del lado
        ok = ((p >= 0.5) == (g["y"].values == 1)).astype(float)
        for lo, hi in tramos:
            m = (conf >= lo) & (conf < hi)
            if m.sum() == 0:
                continue
            out.append({"Modelo": nombre,
                        "Tramo": f"{int(lo*100)}-{int(min(hi,1)*100)}%",
                        "N": int(m.sum()),
                        "Predicho": 100 * float(conf[m].mean()),
                        "Real": 100 * float(ok[m].mean())})
    return pd.DataFrame(out)


# ─────────────────────────────────────────────────────────────────────────────
# 2) COMPARACION EN VIVO (por la columna Modelo)
# ─────────────────────────────────────────────────────────────────────────────

def separar_por_modelo(df):
    """{version: sub-DataFrame}. Filas sin version -> 'v1'."""
    if df is None or df.empty:
        return {}
    if "Modelo" not in df.columns:
        return {"v1": df}
    mod = df["Modelo"].astype(str).str.strip().replace("", "v1")
    return {v: df[mod == v] for v in sorted(mod.unique())}
