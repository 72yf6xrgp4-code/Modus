"""
stats_engine.py - Modelo matematico, simulacion de partidos y metricas.

Contiene el motor de probabilidades (modelo Elo de legs, simulacion Monte
Carlo de partidos al mejor de 7), calculo de handicaps, totales de legs,
180s, asi como la extraccion de head-to-head y ultimos partidos jugados.

Depende de: config (constantes Elo), helpers (sanitize_prob...), data_loading.
"""

import streamlit as st
import pandas as pd
import numpy as np
from scipy.stats import poisson
from functools import lru_cache

from config import (ELO_S, ELO_B, LEGS_PROMEDIO_REFERENCIA, URLS, CORTES,
                    MUESTRA_MIN_PARTIDOS)
from helpers import sanitize_prob, safe_float, _buscar_stat
from data_loading import cargar_todo



def medias_torneo():
    """Media de PR y de 180s por partido de los jugadores del Resumen
    Semanal (solo los que tienen datos). None si no se puede calcular."""
    try:
        from data_loading import cargar_jugadores_desde
        resumen = cargar_jugadores_desde("Resumen Semanal") or {}
    except Exception:
        return None
    prs = [j.get("PR", 0.0) for j in resumen.values() if j.get("PR", 0.0) > 0]
    l180 = [j.get("lam_180", 0.0) for j in resumen.values() if j.get("PR", 0.0) > 0]
    if len(prs) < 3:
        return None
    return {"PR": sum(prs) / len(prs), "lam_180": sum(l180) / len(l180)}


def ajustar_por_muestra(jugador, medias=None, n_min=None):
    """Devuelve una copia del jugador con PR y lam_180 acercados a la media
    del torneo cuando ha jugado pocos partidos (ver MUESTRA_MIN_PARTIDOS).

    peso = n_partidos / n_min  (1 partido de 6 -> 17 % su dato, 83 % la media)
    Jugadores sin el dato n_partidos, o con n_partidos >= n_min, no cambian.
    La copia lleva "_ajuste" = (n, PR original, PR ajustado) para mostrarlo.
    """
    n_min = MUESTRA_MIN_PARTIDOS if n_min is None else n_min
    n = jugador.get("n_partidos")
    if not n_min or not isinstance(n, (int, float)) or n <= 0 or n >= n_min:
        return jugador
    medias = medias if medias is not None else medias_torneo()
    if not medias:
        return jugador
    peso = n / n_min
    nuevo = dict(jugador)
    for campo in ("PR", "lam_180"):
        v = jugador.get(campo, 0.0)
        if v > 0:
            nuevo[campo] = peso * v + (1 - peso) * medias[campo]
    nuevo["_ajuste"] = (int(n), jugador.get("PR", 0.0), nuevo.get("PR", 0.0))
    return nuevo


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

def prob_180s(lam1, lam2, pr1=None, pr2=None, j1_saca_primero=True):
    """Mercados de 180s con Poisson. Si se pasan pr1, pr2 (PG de los jugadores),
    ajusta lambda multiplicando por (E[legs del partido] / LEGS_PROMEDIO_REFERENCIA)
    para que partidos más reñidos generen proporcionalmente más 180s.

    Si solo se pasan lam1, lam2, no aplica ajuste (lambda = T directamente).
    """
    factor = 1.0
    if pr1 is not None and pr2 is not None and pr1 > 0 and pr2 > 0:
        finales = simular_match(pr1, pr2, j1_saca_primero)
        E_legs = legs_esperados_desde_finales(finales)
        if E_legs > 0:
            factor = E_legs / LEGS_PROMEDIO_REFERENCIA

    # Suelo minimo de lambda: aunque un jugador no haya hecho ningun 180
    # en los datos, siempre tiene alguna probabilidad de hacerlo. Sin este
    # suelo, lambda=0 daria 0% exacto, lo cual es irreal.
    LAMBDA_MIN = 0.1
    lam1_aj = max(lam1 * factor, LAMBDA_MIN)
    lam2_aj = max(lam2 * factor, LAMBDA_MIN)
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
    factor = 1.0
    if pr1 is not None and pr2 is not None and pr1 > 0 and pr2 > 0:
        finales = simular_match(pr1, pr2, j1_saca_primero)
        E_legs = legs_esperados_desde_finales(finales)
        if E_legs > 0:
            factor = E_legs / LEGS_PROMEDIO_REFERENCIA
    # Suelo minimo de lambda (coherente con prob_180s).
    LAMBDA_MIN = 0.1
    lam1_aj = max(lam1 * factor, LAMBDA_MIN)
    lam2_aj = max(lam2 * factor, LAMBDA_MIN)

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

@st.cache_data(ttl=30, show_spinner=False)
def extraer_h2h_semanal(j1_nombre, j2_nombre):
    h2h_data = {
        "victorias_j1": 0,
        "victorias_j2": 0,
        "partidos": []
    }
    dias_semana = [
        "Grupo A Lunes", "Grupo A Martes", "Grupo A Miércoles",
        "Grupo C Jueves", "Grupo B Jueves",
        "Grupo C Viernes", "Grupo B Viernes",
        "Final Sábado"
    ]
    j1_lower = j1_nombre.lower().strip().replace("_", " ")
    j2_lower = j2_nombre.lower().strip().replace("_", " ")
    for dia in dias_semana:
        try:
            df_partidos, _ = cargar_todo(URLS[dia], dia, CORTES[dia])
            if df_partidos is None or len(df_partidos) < 2:
                continue
            for i in range(0, len(df_partidos) - 1, 2):
                fila_j1 = df_partidos.iloc[i]
                fila_j2 = df_partidos.iloc[i + 1]
                nombre_j1 = str(fila_j1.iloc[0]).strip().lower().replace("_", " ")
                nombre_j2 = str(fila_j2.iloc[0]).strip().lower().replace("_", " ")
                es_enfrentamiento = (
                    (j1_lower in nombre_j1 or nombre_j1 in j1_lower) and
                    (j2_lower in nombre_j2 or nombre_j2 in j2_lower)
                ) or (
                    (j2_lower in nombre_j1 or nombre_j1 in j2_lower) and
                    (j1_lower in nombre_j2 or nombre_j2 in j1_lower)
                )
                if es_enfrentamiento:
                    resultado_j1 = str(fila_j1.iloc[1]).strip() if len(fila_j1) > 1 else ""
                    resultado_j2 = str(fila_j2.iloc[1]).strip() if len(fila_j2) > 1 else ""
                    ganador = None
                    marcador = f"{resultado_j1}-{resultado_j2}"
                    if "4" in resultado_j1:
                        ganador = nombre_j1.title()
                        if j1_lower in nombre_j1 or nombre_j1 in j1_lower:
                            h2h_data["victorias_j1"] += 1
                        else:
                            h2h_data["victorias_j2"] += 1
                    elif "4" in resultado_j2:
                        ganador = nombre_j2.title()
                        if j1_lower in nombre_j2 or nombre_j2 in j1_lower:
                            h2h_data["victorias_j1"] += 1
                        else:
                            h2h_data["victorias_j2"] += 1
                    if ganador:
                        h2h_data["partidos"].append({
                            "dia": dia,
                            "jugador1": nombre_j1.title(),
                            "jugador2": nombre_j2.title(),
                            "marcador": marcador,
                            "ganador": ganador
                        })
        except Exception as e:
            continue
    return h2h_data

@st.cache_data(ttl=30, show_spinner=False)
def obtener_ultimos_partidos(jugador_nombre, n=3):
    """Devuelve los últimos n partidos jugados por un jugador a lo largo de la
    semana, en orden cronológico INVERSO (el más reciente primero).
    
    Recorre las pestañas en orden: Final Sábado → Viernes → Jueves → Mié → Mar → Lun
    y dentro de cada pestaña recorre los partidos también en orden inverso.
    
    Filtra partidos no terminados (ningún jugador llegó a 4 legs) y filas con
    datos corruptos / vacíos.
    
    Devuelve lista de dicts con:
        - dia:       nombre de la jornada (ej. "Grupo A Lunes")
        - rival:     nombre del oponente
        - marcador:  "X-Y" desde la perspectiva del jugador
        - ganador:   True si el jugador ganó
        - stats:     dict {nombre_columna: valor} con todas las stats del
                     jugador en ese partido (180s, promedio, checkout %, etc.)
    """
    dias_semana = [
        "Final Sábado",
        "Grupo B Viernes", "Grupo C Viernes",
        "Grupo B Jueves",  "Grupo C Jueves",
        "Grupo A Miércoles", "Grupo A Martes", "Grupo A Lunes",
    ]
    jug_lower = str(jugador_nombre).lower().strip().replace("_", " ")
    if not jug_lower:
        return []
    
    partidos = []
    
    def _parse_legs(val):
        try:
            return int(float(str(val).replace(',', '.').strip()))
        except:
            return -1
    
    for dia in dias_semana:
        if len(partidos) >= n:
            break
        try:
            df_partidos, _ = cargar_todo(URLS[dia], dia, CORTES[dia])
        except Exception:
            continue
        if df_partidos is None or len(df_partidos) < 2:
            continue
        
        # Iterar pares de filas (cada par = 1 partido) en orden INVERSO
        i = (len(df_partidos) - 1) // 2 * 2  # último índice par válido
        while i >= 0:
            if len(partidos) >= n:
                break
            if i + 1 >= len(df_partidos):
                i -= 2
                continue
            
            fila1 = df_partidos.iloc[i]
            fila2 = df_partidos.iloc[i + 1]
            nombre1 = str(fila1.iloc[0]).strip() if len(fila1) > 0 else ""
            nombre2 = str(fila2.iloc[0]).strip() if len(fila2) > 0 else ""
            
            if (not nombre1 or not nombre2 or
                    nombre1.lower() in ('nan', '') or
                    nombre2.lower() in ('nan', '')):
                i -= 2
                continue
            
            n1_lower = nombre1.lower().replace("_", " ")
            n2_lower = nombre2.lower().replace("_", " ")
            
            # Match difuso del nombre (igual que en H2H).
            # `jugador_primero` indica si nuestro jugador era la fila superior
            # del par (jugador 1 del partido) en el spreadsheet. Lo usamos
            # después en el render para preservar el orden real del partido
            # en lugar de mostrar siempre "jugador vs rival".
            if jug_lower in n1_lower or n1_lower in jug_lower:
                fila_jug, fila_riv = fila1, fila2
                rival = nombre2
                jugador_primero = True
            elif jug_lower in n2_lower or n2_lower in jug_lower:
                fila_jug, fila_riv = fila2, fila1
                rival = nombre1
                jugador_primero = False
            else:
                i -= 2
                continue
            
            # Parsear legs y filtrar partidos no terminados
            legs_jug = _parse_legs(fila_jug.iloc[1]) if len(fila_jug) > 1 else -1
            legs_riv = _parse_legs(fila_riv.iloc[1]) if len(fila_riv) > 1 else -1
            if legs_jug < 0 or legs_riv < 0:
                i -= 2
                continue
            # Al menos uno debe haber llegado a 4 legs para que el partido cuente
            if legs_jug < 4 and legs_riv < 4:
                i -= 2
                continue
            
            # Construir dict de stats del jugador en ese partido
            stats = {}
            for col in df_partidos.columns:
                val = fila_jug[col]
                if pd.notna(val) and str(val).strip() not in ('', 'nan'):
                    stats[str(col)] = val
            
            # Marcador con el orden original del partido (jugador 1 a la izquierda)
            if jugador_primero:
                marcador = f"{legs_jug}-{legs_riv}"
            else:
                marcador = f"{legs_riv}-{legs_jug}"
            
            partidos.append({
                "dia": dia,
                "rival": rival,
                "marcador": marcador,
                "ganador": legs_jug > legs_riv,
                "jugador_primero": jugador_primero,
                "stats": stats,
            })
            i -= 2
    
    return partidos[:n]

def _extraer_metricas_jugadores(stats_dict):
    """Helper común para heatmap y radar: extrae las 5 métricas clave de cada
    jugador y las devuelve como DataFrame ya saneado.

    Devuelve un DataFrame con columnas:
        Jugador | Media 180 | Promedio Puntos | Checkout % | % Victoria | Puntuación Global

    Maneja los sinónimos típicos de las jornadas diarias y del Resumen Semanal,
    y aplica la conversión defensiva 0-1 → 0-100 para Checkout y % Victoria.
    Filas con todas las métricas a None se eliminan.
    """
    metricas = [
        ("Media 180", ["media 180 por partida", "180 por partida", "180 por partido", "media 180"]),
        ("Promedio Puntos", ["promedio puntos total", "promedio puntos", "media puntos", "promedio dardos", "average"]),
        ("Checkout %", ["promedio checkouts", "promedio checkout", "checkouts", "checkout"]),
        ("% Victoria", ["porcentaje victoria", "porcentaje de victoria", "% victoria", "%victoria"]),
        ("Puntuación Global", ["puntiación global", "puntuación global", "puntacion global", "puntiación", "puntuación", "puntacion"]),
    ]

    def buscar_valor(stats, sinonimos, nombre_metrica):
        for syn in sinonimos:
            syn_lower = syn.lower()
            for k, v in stats.items():
                if syn_lower in str(k).lower():
                    try:
                        num = float(str(v).replace('%', '').replace(',', '.').strip())
                        if 0 < num <= 1 and ("checkout" in nombre_metrica.lower() or "victoria" in nombre_metrica.lower()):
                            num *= 100
                        return num
                    except:
                        continue
        return None

    rows = []
    for jugador, stats in stats_dict.items():
        fila = {"Jugador": str(jugador).title()}
        for nombre_metrica, sinonimos in metricas:
            fila[nombre_metrica] = buscar_valor(stats, sinonimos, nombre_metrica)
        rows.append(fila)

    df = pd.DataFrame(rows)
    if df.empty:
        return df, [m[0] for m in metricas]

    cols_metricas = [m[0] for m in metricas]
    df = df.dropna(how='all', subset=cols_metricas).reset_index(drop=True)
    return df, cols_metricas
