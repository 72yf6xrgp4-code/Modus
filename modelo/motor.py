"""
modelo/motor.py - Motor de probabilidades (sin Streamlit).

Modelo Elo de legs: la probabilidad de ganar cada leg depende de la
Puntuacion Global (PG) de los dos jugadores y de quien saca; con ella se
calcula la distribucion EXACTA de marcadores del Bo7 (primero a 4 legs).
De esa distribucion salen ganador, handicaps y total de legs. Los 180s
usan Poisson con la media de cada jugador (acercada a la del torneo) y
escalada por los legs esperados del partido.

stats_engine.py reexporta estas funciones para la app; el vigia las usa
directamente. Por eso las dos dan los mismos numeros.
"""

from functools import lru_cache

from scipy.stats import poisson

from config import (ELO_S, ELO_B, LEGS_PROMEDIO_REFERENCIA,
                    MUESTRA_MIN_PARTIDOS, LAMBDA_180_PESO_JUGADOR,
                    LAMBDA_180_MEDIA_TORNEO)
from modelo.util import sanitize_prob


def pocos_partidos(jugador, n_min=None):
    """Numero de partidos si el jugador tiene menos de MUESTRA_MIN_PARTIDOS
    (para avisar de que sus datos son poco fiables); None si no hace falta
    avisar o no se sabe. No modifica ningun calculo."""
    n_min = MUESTRA_MIN_PARTIDOS if n_min is None else n_min
    n = jugador.get("n_partidos")
    if n_min and isinstance(n, (int, float)) and 0 < n < n_min:
        return int(n)
    return None


def lambda_180_calibrada(lam):
    """Media de 180s por partido que usa el modelo para un jugador: su dato
    de la semana acercado a la media del torneo (ver config.py)."""
    w = LAMBDA_180_PESO_JUGADOR
    return w * max(lam or 0.0, 0.0) + (1.0 - w) * LAMBDA_180_MEDIA_TORNEO


def prob_leg(pg1, pg2, j1_saca, S=ELO_S, B=ELO_B):
    """Probabilidad de que J1 gane UN leg, según quién saca.

    Modelo logístico tipo ELO: P = 1 / (1 + 10^((PG_oponente_efectivo - PG_propio_efectivo) / S))
    donde el saque añade B puntos al PG del que tiene el dardo.
    """
    if j1_saca:
        diff = pg2 - (pg1 + B)
    else:
        diff = (pg2 + B) - pg1
    return 1.0 / (1.0 + 10 ** (diff / S))

def _simular_bo7_un_inicio(pg1, pg2, j1_saca_primero, S, B):
    """Matriz de estados del Bo7. Estado = (legs_j1, legs_j2). Al inicio (0,0).
    En cada paso, el leg actual = l1+l2+1 (1-indexed):
        - leg impar  → saca el jugador inicial
        - leg par    → saca el otro
    El bucle ramifica las probabilidades hasta que cada estado llega a 4 legs.
    Devuelve dict {(l1, l2): prob} con TODOS los marcadores finales.
    """
    estados = {(0, 0): 1.0}
    finales = {}
    while estados:
        nuevos = {}
        for (l1, l2), p in estados.items():
            if l1 >= 4 or l2 >= 4:
                finales[(l1, l2)] = finales.get((l1, l2), 0.0) + p
                continue
            leg_actual = l1 + l2 + 1
            # Leg impar → saca el inicial; leg par → saca el otro
            j1_saca_este_leg = ((leg_actual % 2) == 1) == j1_saca_primero
            p_j1_gana = prob_leg(pg1, pg2, j1_saca_este_leg, S, B)
            nuevos[(l1 + 1, l2)] = nuevos.get((l1 + 1, l2), 0.0) + p * p_j1_gana
            nuevos[(l1, l2 + 1)] = nuevos.get((l1, l2 + 1), 0.0) + p * (1.0 - p_j1_gana)
        estados = nuevos
    return finales

@lru_cache(maxsize=512)
def _simular_match_cached(pg1, pg2, j1_saca_primero, S, B):
    """Simula el Bo7 sabiendo quién saca primero. La ventaja del TFA se aplica
    íntegramente al jugador que empieza (no se promedia con el escenario contrario).

    @lru_cache evita re-simular cuando la misma combinación se consulta varias
    veces dentro de un mismo render. Devuelve tupla ordenada (hashable).
    """
    finales = _simular_bo7_un_inicio(pg1, pg2, j1_saca_primero, S, B)
    return tuple(sorted(finales.items()))

def simular_match(pg1, pg2, j1_saca_primero=True, S=ELO_S, B=ELO_B):
    """Devuelve dict {(legs_j1, legs_j2): probabilidad} para el Bo7. El parámetro
    `j1_saca_primero` indica quién tiene el dardo en el leg 1; los siguientes
    legs alternan automáticamente (par/impar)."""
    return dict(_simular_match_cached(
        float(pg1), float(pg2), bool(j1_saca_primero), float(S), float(B)
    ))

def legs_esperados_desde_finales(finales):
    """E[legs totales] = Σ legs * P(legs). Útil para ajustar lambda en 180s."""
    return sum((l1 + l2) * p for (l1, l2), p in finales.items())

def prob_victoria(pr1, pr2, j1_saca_primero=True):
    if pr1 <= 0 and pr2 <= 0:
        return 0.5, 0.5
    finales = simular_match(pr1, pr2, j1_saca_primero)
    p1 = sum(p for (l1, _l2), p in finales.items() if l1 >= 4)
    return sanitize_prob(p1), sanitize_prob(1.0 - p1)

def lambdas_180(lam1, lam2, pr1=None, pr2=None, j1_saca_primero=True):
    """Lambdas de 180s que usa el modelo para el partido: la media de cada
    jugador acercada a la del torneo (lambda_180_calibrada) y, si se pasan
    pr1 y pr2, escalada por E[legs del partido] / LEGS_PROMEDIO_REFERENCIA
    (partidos mas largos -> mas 180s). Con suelo minimo LAMBDA_MIN: aunque
    un jugador no haya hecho ningun 180 en los datos, siempre tiene alguna
    probabilidad de hacerlo (lambda=0 daria 0 % exacto, irreal)."""
    lam1, lam2 = lambda_180_calibrada(lam1), lambda_180_calibrada(lam2)
    factor = 1.0
    if pr1 is not None and pr2 is not None and pr1 > 0 and pr2 > 0:
        finales = simular_match(pr1, pr2, j1_saca_primero)
        E_legs = legs_esperados_desde_finales(finales)
        if E_legs > 0:
            factor = E_legs / LEGS_PROMEDIO_REFERENCIA
    LAMBDA_MIN = 0.1
    return max(lam1 * factor, LAMBDA_MIN), max(lam2 * factor, LAMBDA_MIN)

def prob_180s(lam1, lam2, pr1=None, pr2=None, j1_saca_primero=True):
    """Mercados de 180s con Poisson. lam1/lam2 son la media de 180s por partido
    de cada jugador; se ajustan con lambdas_180 (media del torneo y legs
    esperados del partido si se pasan pr1, pr2)."""
    lam1_aj, lam2_aj = lambdas_180(lam1, lam2, pr1, pr2, j1_saca_primero)
    lam_total = lam1_aj + lam2_aj
    ambos_05 = sanitize_prob((1 - poisson.cdf(0, lam1_aj)) * (1 - poisson.cdf(0, lam2_aj)))
    return {
        "J1 +0.5": sanitize_prob(1 - poisson.cdf(0, lam1_aj)),
        "J1 +1.5": sanitize_prob(1 - poisson.cdf(1, lam1_aj)),
        "J2 +0.5": sanitize_prob(1 - poisson.cdf(0, lam2_aj)),
        "J2 +1.5": sanitize_prob(1 - poisson.cdf(1, lam2_aj)),
        # "Ambos +0.5" = los DOS jugadores hacen al menos un 180.
        # "Total +1.5/+2.5" = 180s sumados entre los dos (antes se llamaban
        # "Ambos +1.5/+2.5", pero no exigen nada a cada jugador por separado).
        "Ambos +0.5": ambos_05,
        "Total +1.5": sanitize_prob(1 - poisson.cdf(1, lam_total)),
        "Total +2.5": sanitize_prob(1 - poisson.cdf(2, lam_total)),
    }

def quien_hace_mas_180s(lam1, lam2, pr1=None, pr2=None, j1_saca_primero=True, k_max=15):
    """Match 180s (H2H) usando bivariada de Poisson independientes.
    Si se pasan pr1, pr2, ajusta lambdas con el factor de legs esperados.

    Suma sobre la matriz P(i, j) = P(N1=i) * P(N2=j) las celdas donde:
        - i > j  → J1 hace más 180s
        - i < j  → J2 hace más 180s
        - i == j → empate

    k_max=15 cubre cómodamente los rangos típicos (lam ≈ 1-3, P(>15) < 1e-8).
    """
    lam1_aj, lam2_aj = lambdas_180(lam1, lam2, pr1, pr2, j1_saca_primero)

    if lam1_aj <= 0 and lam2_aj <= 0:
        return 1/3, 1/3, 1/3

    p_j1 = 0.0
    p_j2 = 0.0
    p_emp = 0.0
    pmf1 = [poisson.pmf(i, lam1_aj) for i in range(k_max + 1)]
    pmf2 = [poisson.pmf(j, lam2_aj) for j in range(k_max + 1)]
    for i in range(k_max + 1):
        for j in range(k_max + 1):
            p_ij = pmf1[i] * pmf2[j]
            if i > j:
                p_j1 += p_ij
            elif j > i:
                p_j2 += p_ij
            else:
                p_emp += p_ij
    return sanitize_prob(p_j1), sanitize_prob(p_emp), sanitize_prob(p_j2)

def handicaps_legs(pr1, pr2, j1_saca_primero=True):
    """Hándicaps de legs derivados de las probabilidades de marcador exacto del
    modelo ELO leg-a-leg. Mucho más fiel que la aproximación heurística previa.

    Marcadores favorables a J1: (4,0), (4,1), (4,2), (4,3).
    - J1 -1.5 (gana por ≥2 legs)  = P(4-0) + P(4-1) + P(4-2)
    - J1 -2.5 (gana por ≥3 legs)  = P(4-0) + P(4-1)
    - J1 +1.5 (no pierde por ≥2)  = 1 - [P(0-4) + P(1-4) + P(2-4)]
    - J1 +2.5 (no pierde por ≥3)  = 1 - [P(0-4) + P(1-4)]
    """
    if pr1 <= 0 and pr2 <= 0:
        return {k: 0.5 for k in ["J1 -1.5 Legs", "J1 -2.5 Legs", "J1 +1.5 Legs",
                                  "J1 +2.5 Legs", "J2 -1.5 Legs", "J2 -2.5 Legs",
                                  "J2 +1.5 Legs", "J2 +2.5 Legs"]}
    finales = simular_match(pr1, pr2, j1_saca_primero)
    p_4_0 = finales.get((4, 0), 0.0)
    p_4_1 = finales.get((4, 1), 0.0)
    p_4_2 = finales.get((4, 2), 0.0)
    p_0_4 = finales.get((0, 4), 0.0)
    p_1_4 = finales.get((1, 4), 0.0)
    p_2_4 = finales.get((2, 4), 0.0)
    return {
        "J1 -1.5 Legs": sanitize_prob(p_4_0 + p_4_1 + p_4_2),
        "J1 -2.5 Legs": sanitize_prob(p_4_0 + p_4_1),
        "J1 +1.5 Legs": sanitize_prob(1.0 - (p_0_4 + p_1_4 + p_2_4)),
        "J1 +2.5 Legs": sanitize_prob(1.0 - (p_0_4 + p_1_4)),
        "J2 -1.5 Legs": sanitize_prob(p_0_4 + p_1_4 + p_2_4),
        "J2 -2.5 Legs": sanitize_prob(p_0_4 + p_1_4),
        "J2 +1.5 Legs": sanitize_prob(1.0 - (p_4_0 + p_4_1 + p_4_2)),
        "J2 +2.5 Legs": sanitize_prob(1.0 - (p_4_0 + p_4_1)),
    }

def legs_totales(pr1, pr2, j1_saca_primero=True):
    """Total de legs (over/under 5.5) derivado del modelo ELO leg-a-leg.
    Bo7 → posibles totales: 4 (4-0/0-4), 5 (4-1/1-4), 6 (4-2/2-4), 7 (4-3/3-4).
    """
    if pr1 <= 0 and pr2 <= 0:
        return {"Más de 5.5": 0.5, "Menos de 5.5": 0.5}
    finales = simular_match(pr1, pr2, j1_saca_primero)
    p_4 = finales.get((4, 0), 0.0) + finales.get((0, 4), 0.0)  # 4 legs totales
    p_5 = finales.get((4, 1), 0.0) + finales.get((1, 4), 0.0)
    p_6 = finales.get((4, 2), 0.0) + finales.get((2, 4), 0.0)
    p_7 = finales.get((4, 3), 0.0) + finales.get((3, 4), 0.0)
    p_under = p_4 + p_5
    p_over = p_6 + p_7
    return {
        "Más de 5.5": sanitize_prob(p_over),
        "Menos de 5.5": sanitize_prob(p_under),
    }

def prob_a_cuota(p):
    p_safe = sanitize_prob(p)
    cuota = 1.0 / p_safe
    return max(1.01, min(999.0, cuota))


# ─────────────────────────────────────────────────────────────────────────────
# MERCADOS PARA CUALQUIER LINEA (los usa el vigia)
# ─────────────────────────────────────────────────────────────────────────────

# Los 8 marcadores posibles del Bo7, desde el punto de vista de J1.
MARCADORES = [(4, 0), (4, 1), (4, 2), (4, 3), (3, 4), (2, 4), (1, 4), (0, 4)]


def prob_handicap(dist, jugador, h):
    """P(el jugador gana con handicap h): J1 gana si legs1 + h > legs2
    (J2 igual al reves). dist = {(legs1, legs2): prob}."""
    if jugador == 1:
        p = sum(pr for (l1, l2), pr in dist.items() if l1 + h > l2)
    else:
        p = sum(pr for (l1, l2), pr in dist.items() if l2 + h > l1)
    return sanitize_prob(p)


def prob_total_legs(dist, linea, mas=True):
    """P(mas de / menos de `linea` legs en total)."""
    if mas:
        p = sum(pr for (l1, l2), pr in dist.items() if l1 + l2 > linea)
    else:
        p = sum(pr for (l1, l2), pr in dist.items() if l1 + l2 < linea)
    return sanitize_prob(p)


def prob_poisson_linea(lam, linea, mas=True):
    """P(N > linea) o P(N < linea) con N ~ Poisson(lam), linea x.5."""
    k = int(linea)  # 1.5 -> 1: "mas de 1.5" = N >= 2 = 1 - P(N <= 1)
    p_hasta_k = poisson.cdf(k, lam)
    return sanitize_prob(1 - p_hasta_k if mas else p_hasta_k)


def calcular_partido(j1, j2, j1_saca_primero=True):
    """Todas las probabilidades de un partido, igual que Value Bets.

    j1, j2: dicts de jugador con 'PR' y 'lam_180' (como los devuelve
    datos.cargar_jugadores / cargar_forma_reciente).

    Devuelve dict con:
      p1, p2        P(gana J1), P(gana J2)
      dist          {(legs1, legs2): prob} de los 8 marcadores
      lam1, lam2    lambdas de 180s ya ajustadas
      mas_180       (P J1 hace mas, P empate, P J2 hace mas)
    """
    pr1, pr2 = j1["PR"], j2["PR"]
    lam1, lam2 = j1["lam_180"], j2["lam_180"]
    p1, p2 = prob_victoria(pr1, pr2, j1_saca_primero)
    dist = simular_match(pr1, pr2, j1_saca_primero)
    lam1_aj, lam2_aj = lambdas_180(lam1, lam2, pr1, pr2, j1_saca_primero)
    return {
        "p1": p1, "p2": p2,
        "dist": {m: dist.get(m, 0.0) for m in MARCADORES},
        "lam1": lam1_aj, "lam2": lam2_aj,
        "mas_180": quien_hace_mas_180s(lam1, lam2, pr1=pr1, pr2=pr2,
                                       j1_saca_primero=j1_saca_primero),
    }


def probabilidad(calc, sel):
    """Probabilidad del modelo para una seleccion.

    calc: resultado de calcular_partido.
    sel:  dict con 'tipo' y sus parametros:
      ganador      jugador (1/2)
      handicap     jugador, linea (p. ej. -1.5)
      total_legs   lado ('mas'/'menos'), linea
      resultado    legs1, legs2
      180_jugador  jugador, lado, linea
      180_total    lado, linea
      mas_180      quien (1 = J1, 0 = empate, 2 = J2)
    Devuelve None si el tipo no se reconoce.
    """
    t = sel["tipo"]
    if t == "ganador":
        return calc["p1"] if sel["jugador"] == 1 else calc["p2"]
    if t == "handicap":
        return prob_handicap(calc["dist"], sel["jugador"], sel["linea"])
    if t == "total_legs":
        return prob_total_legs(calc["dist"], sel["linea"], sel["lado"] == "mas")
    if t == "resultado":
        return sanitize_prob(calc["dist"].get((sel["legs1"], sel["legs2"]), 0.0))
    if t == "180_jugador":
        lam = calc["lam1"] if sel["jugador"] == 1 else calc["lam2"]
        return prob_poisson_linea(lam, sel["linea"], sel["lado"] == "mas")
    if t == "180_total":
        return prob_poisson_linea(calc["lam1"] + calc["lam2"], sel["linea"],
                                  sel["lado"] == "mas")
    if t == "mas_180":
        pj1, pemp, pj2 = calc["mas_180"]
        return {1: pj1, 0: pemp, 2: pj2}[sel["quien"]]
    return None
