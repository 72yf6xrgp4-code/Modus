"""
stats_engine.py - Modelo matematico, simulacion de partidos y metricas.

Reexporta el motor de probabilidades de modelo/motor.py (modelo Elo de
legs, distribucion exacta del Bo7, handicaps, totales de legs y 180s) y
contiene la extraccion de head-to-head y ultimos partidos jugados.

Depende de: modelo.motor, config, helpers, data_loading.
"""

import streamlit as st
import pandas as pd
import numpy as np

from config import URLS, CORTES
from helpers import safe_float
from data_loading import cargar_todo



# El motor de probabilidades vive en modelo/motor.py (sin Streamlit) para
# que el vigia use exactamente el mismo calculo. Se reexporta aqui con los
# mismos nombres para el resto de la app.
from modelo.motor import (  # noqa: F401
    pocos_partidos, lambda_180_calibrada, prob_leg, _simular_bo7_un_inicio,
    _simular_match_cached, simular_match, legs_esperados_desde_finales,
    prob_victoria, lambdas_180, prob_180s, quien_hace_mas_180s,
    handicaps_legs, legs_totales, prob_a_cuota,
)

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
