"""
clasificacion.py - Clasificaciones de grupo y de la fase final.

Calcula las tablas de clasificacion semanal por grupo (A/B/C) y la
clasificacion de la fase final del sabado, con su renderizado coloreado.

Depende de: config, data_loading.
"""

import streamlit as st
import pandas as pd
import numpy as np

from config import URLS, CORTES, GRUPOS_DIAS, COLORES_CLASIFICACION
from data_loading import cargar_todo

def detectar_grupo(jornada):
    """Mapea el nombre de jornada a su grupo. Devuelve None para Final/Resumen."""
    if not jornada:
        return None
    if "Grupo A" in jornada:
        return "Grupo A"
    if "Grupo B" in jornada:
        return "Grupo B"
    if "Grupo C" in jornada:
        return "Grupo C"
    return None

def calcular_clasificacion_grupo(grupo):
    """Calcula la clasificación de un grupo sumando todos los partidos terminados
    de los días que lo componen.

    Estructura asumida del DataFrame de partidos (idéntica a la usada en h2h):
        - iloc[0] = nombre del jugador
        - iloc[1] = legs ganados (4 = ganador en formato first-to-4)
        - filas pares (i, i+1) son cada partido

    Reglas:
        - PJ: partidos jugados
        - V/D: victorias/derrotas
        - LF/LC: legs a favor / en contra
        - DIF: LF - LC
        - PTS: 2 × V (sistema estándar de round-robin)

    Orden: PTS desc → DIF desc → LF desc.
    Solo se cuentan partidos terminados (alguien llegó a 4 legs).
    """
    if grupo not in GRUPOS_DIAS:
        return None

    stats = {}  # key: nombre_lower → dict con stats
    for dia in GRUPOS_DIAS[grupo]:
        try:
            df, _ = cargar_todo(URLS[dia], dia, CORTES[dia])
            if df is None or len(df) < 2:
                continue
            for i in range(0, len(df) - 1, 2):
                fila1 = df.iloc[i]
                fila2 = df.iloc[i + 1]
                nombre1 = str(fila1.iloc[0]).strip()
                nombre2 = str(fila2.iloc[0]).strip()
                # Saltar filas vacías o 'nan'
                if (not nombre1 or not nombre2 or
                        nombre1.lower() in ('nan', '') or
                        nombre2.lower() in ('nan', '')):
                    continue

                # Parsear legs (robusto contra strings vacíos, comas decimales o 'nan')
                def _parse_legs(val):
                    try:
                        return int(float(str(val).replace(',', '.').strip()))
                    except:
                        return -1

                legs1 = _parse_legs(fila1.iloc[1]) if len(fila1) > 1 else -1
                legs2 = _parse_legs(fila2.iloc[1]) if len(fila2) > 1 else -1

                if legs1 < 0 or legs2 < 0:
                    continue
                # Solo cuentan partidos terminados (alguien llegó a 4 legs)
                if legs1 < 4 and legs2 < 4:
                    continue

                # Inicializar entrada si no existe (.title() para nombre legible)
                for n in (nombre1, nombre2):
                    k = n.lower()
                    if k not in stats:
                        stats[k] = {
                            "Jugador": n.title(),
                            "PJ": 0, "V": 0, "D": 0,
                            "LF": 0, "LC": 0,
                        }

                k1, k2 = nombre1.lower(), nombre2.lower()
                stats[k1]["PJ"] += 1
                stats[k2]["PJ"] += 1
                stats[k1]["LF"] += legs1
                stats[k1]["LC"] += legs2
                stats[k2]["LF"] += legs2
                stats[k2]["LC"] += legs1
                if legs1 > legs2:
                    stats[k1]["V"] += 1
                    stats[k2]["D"] += 1
                else:
                    stats[k2]["V"] += 1
                    stats[k1]["D"] += 1
        except Exception:
            continue

    if not stats:
        return None

    # Construir DataFrame y aplicar criterios de desempate
    rows = []
    for v in stats.values():
        v["DIF"] = v["LF"] - v["LC"]
        v["PTS"] = v["V"] * 2
        rows.append(v)

    df = pd.DataFrame(rows)
    if df.empty:
        return None

    # Filtrar jugadores sin partidos jugados (residuos de semanas pasadas o nombres
    # cargados sin haber disputado encuentros válidos esta semana).
    df = df[df["PJ"] > 0].copy()
    if df.empty:
        return None

    df = df.sort_values(
        by=["PTS", "DIF", "LF"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    # Posición con medalla para el podio
    def _pos_emoji(idx):
        if idx == 0:
            return "🥇 1"
        if idx == 1:
            return "🥈 2"
        if idx == 2:
            return "🥉 3"
        return str(idx + 1)

    df.insert(0, "Pos", [_pos_emoji(i) for i in range(len(df))])
    return df[["Pos", "Jugador", "PJ", "V", "D", "LF", "LC", "DIF", "PTS"]]

def render_clasificacion_grupo(grupo):
    """Renderiza la tabla de clasificación de un grupo aplicando los colores
    configurados en COLORES_CLASIFICACION (verdes desde arriba, rojos desde abajo).

    Si verdes + rojos > nº de jugadores, el verde tiene prioridad para evitar
    pintar la misma fila dos veces.
    """
    df = calcular_clasificacion_grupo(grupo)
    if df is None or df.empty:
        st.info(f"ℹ️ Aún no hay partidos terminados en {grupo}")
        return

    st.subheader(f"🏆 Clasificación {grupo}")

    n = len(df)
    config = COLORES_CLASIFICACION.get(grupo, {"verdes": 1, "rojos": 0})
    n_verdes = config["verdes"]
    n_rojos = config["rojos"]
    umbral_rojo = n - n_rojos  # filas con idx >= umbral_rojo van en rojo

    def estilo_fila(fila):
        idx = fila.name
        if idx < n_verdes:
            return ['background-color: rgba(40,167,69,0.18); font-weight: 600;'] * len(fila)
        if n_rojos > 0 and idx >= umbral_rojo:
            return ['background-color: rgba(220,53,69,0.12);'] * len(fila)
        return [''] * len(fila)

    styled = df.style.apply(estilo_fila, axis=1).set_properties(**{
        'text-align': 'center',
    }).set_table_styles([
        {'selector': 'th', 'props': [('text-align', 'center'), ('font-weight', 'bold')]},
        {'selector': 'th.col_heading', 'props': [('background-color', '#1f2937'), ('color', 'white')]},
    ])

    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption("💡 Orden: **PTS** (2 por victoria) → **DIF** (legs a favor − en contra) → **LF** (legs a favor)")

def _ranking_grupo_semana(grupo):
    """Devuelve la clasificación ordenada de un grupo semanal (lista de nombres
    en orden 1º, 2º, 3º...). Si no hay datos, devuelve []."""
    df = calcular_clasificacion_grupo(grupo)
    if df is None or df.empty:
        return []
    return df["Jugador"].tolist()

def construir_grupos_final():
    """Construye los dos grupos de la Final Sábado a partir de los resultados
    de la fase de grupos semanal.

    Composición:
        Final Grupo A:
            - 1º del Grupo A (Lun-Mar-Mié)
            - 2º del Grupo B (Jue-Vie)
            - 2º del Grupo C (Jue-Vie)
        Final Grupo B:
            - 1º del Grupo B (Jue-Vie)
            - 1º del Grupo C (Jue-Vie)
            - 3º del Grupo B (Jue-Vie)

    Devuelve dict {"Grupo A Final": [...], "Grupo B Final": [...]}, con cada
    valor siendo lista de dicts {jugador, procedencia}. Si falta algún rango
    en algún grupo, se omite ese hueco (la lista será más corta).
    """
    # Si la Final ya ha empezado (el Sheet tiene partidos), la composicion
    # sale de los PARTIDOS REALES y queda congelada (no cambia aunque el
    # ranking semanal se mueva por un resultado tardio). Si aun no ha
    # empezado, mostramos la composicion PREVISTA desde el ranking semanal.
    reales = _grupos_final_desde_sheet()
    if reales is not None:
        return reales
    return _grupos_final_previstos()


def _grupos_final_previstos():
    """Composicion PREVISTA de los grupos de la Final, calculada desde el
    ranking de la fase de grupos semanal. Se usa ANTES de que empiece la
    Final (cuando el Sheet aun no tiene partidos)."""
    rank_a = _ranking_grupo_semana("Grupo A")
    rank_b = _ranking_grupo_semana("Grupo B")
    rank_c = _ranking_grupo_semana("Grupo C")

    def _get(rank, idx):
        return rank[idx] if idx < len(rank) else None

    grupo_a_final = []
    for nombre, proc in [
        (_get(rank_a, 0), "1º Grupo A"),
        (_get(rank_b, 1), "2º Grupo B"),
        (_get(rank_c, 1), "2º Grupo C"),
    ]:
        if nombre:
            grupo_a_final.append({"jugador": nombre, "procedencia": proc})

    grupo_b_final = []
    for nombre, proc in [
        (_get(rank_b, 0), "1º Grupo B"),
        (_get(rank_c, 0), "1º Grupo C"),
        (_get(rank_b, 2), "3º Grupo B"),
    ]:
        if nombre:
            grupo_b_final.append({"jugador": nombre, "procedencia": proc})

    return {"Grupo A Final": grupo_a_final, "Grupo B Final": grupo_b_final}


def _grupos_final_desde_sheet():
    """Deduce la composicion REAL de los grupos de la Final a partir de los
    partidos ya escritos en la pestana 'Final Sábado'.

    En un round-robin, los jugadores de un mismo grupo solo se enfrentan
    entre si. Agrupamos por 'componentes conexas': si A juega contra B,
    estan en el mismo grupo.

    Devuelve el mismo formato que construir_grupos_final, o None si el Sheet
    aun no tiene partidos (la Final no ha empezado).

    Para asignar cual es 'Grupo A Final' y cual 'Grupo B Final' y la
    procedencia de cada jugador, se cruza con la prevision por ranking:
    el grupo reasl que mas coincide con la prevision A se etiqueta como A.
    """
    try:
        df, _ = cargar_todo(URLS["Final Sábado"], "Final Sábado",
                            CORTES["Final Sábado"])
    except Exception:
        return None
    if df is None or len(df) < 2:
        return None

    # Recoger los enfrentamientos (pares de nombres) que hay en el Sheet.
    # IMPORTANTE: solo los 6 PRIMEROS partidos son la fase de grupos
    # (3 por grupo). Los siguientes son semifinales/final, que CRUZAN
    # jugadores de ambos grupos y romperian la deteccion por componentes
    # conexas. Por eso nos limitamos a los primeros 6.
    enfrentamientos = []
    jugadores = set()
    MAX_PARTIDOS_GRUPOS = 6
    contador = 0
    for i in range(0, len(df) - 1, 2):
        if contador >= MAX_PARTIDOS_GRUPOS:
            break
        f1, f2 = df.iloc[i], df.iloc[i + 1]
        n1 = str(f1.iloc[0]).strip()
        n2 = str(f2.iloc[0]).strip()
        if (not n1 or not n2 or n1.lower() in ('nan', '')
                or n2.lower() in ('nan', '')):
            continue
        enfrentamientos.append((n1, n2))
        jugadores.add(n1)
        jugadores.add(n2)
        contador += 1

    if not enfrentamientos:
        return None

    # Componentes conexas (union-find sencillo)
    padre = {j: j for j in jugadores}

    def find(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            padre[ra] = rb

    for a, b in enfrentamientos:
        union(a, b)

    grupos_dict = {}
    for j in jugadores:
        grupos_dict.setdefault(find(j), []).append(j)

    componentes = list(grupos_dict.values())
    # Esperamos 2 grupos. Si solo hay 1 (la Final acaba de empezar y aun no
    # se ve la separacion), devolvemos None para seguir usando la prevision.
    if len(componentes) < 2:
        return None

    # Cruzar con la prevision para etiquetar A/B y procedencias
    prevista = _grupos_final_previstos()
    nombres_prev_a = {d["jugador"].lower()
                      for d in prevista.get("Grupo A Final", [])}
    proc_por_jugador = {}
    for g in ("Grupo A Final", "Grupo B Final"):
        for d in prevista.get(g, []):
            proc_por_jugador[d["jugador"].lower()] = d["procedencia"]

    # Elegir cual componente es A: la que mas solape con la prevision A
    def solape_con_a(comp):
        return sum(1 for j in comp if j.lower() in nombres_prev_a)

    componentes.sort(key=solape_con_a, reverse=True)
    comp_a = componentes[0]
    comp_b = componentes[1] if len(componentes) > 1 else []

    def _a_dicts(comp):
        out = []
        for j in comp:
            out.append({
                "jugador": j,
                "procedencia": proc_por_jugador.get(j.lower(), "Final"),
            })
        return out

    return {"Grupo A Final": _a_dicts(comp_a),
            "Grupo B Final": _a_dicts(comp_b)}

def calcular_clasificacion_final(jugadores_del_grupo):
    """Calcula la clasificación del grupo de Final Sábado a partir de los
    partidos disputados ESE día. Recibe la lista de jugadores que conforman
    el grupo (los que debe filtrar de Final Sábado) y devuelve un DataFrame
    con las mismas columnas que `calcular_clasificacion_grupo`.

    A diferencia de la clasificación semanal (que suma 3 o 2 días), esta solo
    lee la pestaña 'Final Sábado' y filtra para que el grupo solo refleje los
    partidos entre los 3 jugadores que componen ese grupo de la final.
    """
    if not jugadores_del_grupo:
        return None

    # `jugadores_del_grupo` puede llegar como lista de dicts {"jugador":..., "procedencia":...}
    # (caso normal desde construir_grupos_final) o, defensivamente, como lista de strings.
    # Normalizamos a lista de nombres (str) descartando vacíos / NaN.
    def _nombre_de(item):
        if isinstance(item, dict):
            return str(item.get("jugador", "")).strip()
        if item is None:
            return ""
        return str(item).strip()

    nombres_jugadores = [
        n for n in (_nombre_de(j) for j in jugadores_del_grupo)
        if n and n.lower() != 'nan'
    ]
    if not nombres_jugadores:
        return None

    nombres_grupo = {n.lower() for n in nombres_jugadores}

    stats = {}
    try:
        df, _ = cargar_todo(URLS["Final Sábado"], "Final Sábado", CORTES["Final Sábado"])
    except Exception:
        df = None
    if df is None or len(df) < 2:
        # Pre-rellenar para que aparezcan los 3 jugadores aunque aún no haya partidos
        for jugador in nombres_jugadores:
            k = jugador.lower()
            stats[k] = {"Jugador": jugador, "PJ": 0, "V": 0, "D": 0, "LF": 0, "LC": 0}
    else:
        # Pre-rellenar entradas de los jugadores del grupo para que aparezcan
        # aunque aún no hayan jugado ningún partido
        for jugador in nombres_jugadores:
            k = jugador.lower()
            stats[k] = {"Jugador": jugador, "PJ": 0, "V": 0, "D": 0, "LF": 0, "LC": 0}

        for i in range(0, len(df) - 1, 2):
            fila1 = df.iloc[i]
            fila2 = df.iloc[i + 1]
            nombre1 = str(fila1.iloc[0]).strip()
            nombre2 = str(fila2.iloc[0]).strip()
            if (not nombre1 or not nombre2 or
                    nombre1.lower() in ('nan', '') or
                    nombre2.lower() in ('nan', '')):
                continue

            # Filtro clave: el partido solo cuenta si AMBOS jugadores están en el grupo
            if nombre1.lower() not in nombres_grupo or nombre2.lower() not in nombres_grupo:
                continue

            def _parse_legs(val):
                try:
                    return int(float(str(val).replace(',', '.').strip()))
                except:
                    return -1

            legs1 = _parse_legs(fila1.iloc[1]) if len(fila1) > 1 else -1
            legs2 = _parse_legs(fila2.iloc[1]) if len(fila2) > 1 else -1
            if legs1 < 0 or legs2 < 0:
                continue
            if legs1 < 4 and legs2 < 4:
                continue

            k1, k2 = nombre1.lower(), nombre2.lower()
            stats[k1]["PJ"] += 1
            stats[k2]["PJ"] += 1
            stats[k1]["LF"] += legs1
            stats[k1]["LC"] += legs2
            stats[k2]["LF"] += legs2
            stats[k2]["LC"] += legs1
            if legs1 > legs2:
                stats[k1]["V"] += 1
                stats[k2]["D"] += 1
            else:
                stats[k2]["V"] += 1
                stats[k1]["D"] += 1

    rows = []
    for v in stats.values():
        v["DIF"] = v["LF"] - v["LC"]
        v["PTS"] = v["V"] * 2
        rows.append(v)

    df_out = pd.DataFrame(rows)
    if df_out.empty:
        return None

    df_out = df_out.sort_values(
        by=["PTS", "DIF", "LF"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    def _pos_emoji(idx):
        if idx == 0:
            return "🥇 1"
        if idx == 1:
            return "🥈 2"
        if idx == 2:
            return "🥉 3"
        return str(idx + 1)

    df_out.insert(0, "Pos", [_pos_emoji(i) for i in range(len(df_out))])
    return df_out[["Pos", "Jugador", "PJ", "V", "D", "LF", "LC", "DIF", "PTS"]]

def render_clasificacion_final(nombre_grupo, jugadores_del_grupo):
    """Renderiza la clasificación de uno de los grupos de la Final Sábado.

    Reglas de pintado (igual que pediste):
        - 2 primeros en verde (pasan a semifinales)
        - último (tercero) en rojo
    """
    df = calcular_clasificacion_final(jugadores_del_grupo)
    if df is None or df.empty:
        st.info(f"ℹ️ Aún no hay datos para {nombre_grupo}")
        return

    st.subheader(f"🏆 {nombre_grupo}")
    # Composición: tolerante a items dict o a strings sueltos.
    _trozos = []
    for j in jugadores_del_grupo:
        if isinstance(j, dict):
            nom = str(j.get("jugador", "")).strip()
            proc = str(j.get("procedencia", "")).strip()
            if nom:
                _trozos.append(f"**{nom}** ({proc})" if proc else f"**{nom}**")
        elif j:
            nom = str(j).strip()
            if nom and nom.lower() != 'nan':
                _trozos.append(f"**{nom}**")
    if _trozos:
        st.caption("Composición: " + " · ".join(_trozos))

    n = len(df)

    def estilo_fila(fila):
        idx = fila.name
        if idx < 2:
            return ['background-color: rgba(40,167,69,0.18); font-weight: 600;'] * len(fila)
        if idx == n - 1 and n >= 3:
            return ['background-color: rgba(220,53,69,0.12);'] * len(fila)
        return [''] * len(fila)

    styled = df.style.apply(estilo_fila, axis=1).set_properties(**{
        'text-align': 'center',
    }).set_table_styles([
        {'selector': 'th', 'props': [('text-align', 'center'), ('font-weight', 'bold')]},
        {'selector': 'th.col_heading', 'props': [('background-color', '#1f2937'), ('color', 'white')]},
    ])

    st.dataframe(styled, use_container_width=True, hide_index=True)


def _buscar_ganador_partido_final(nombre_a, nombre_b):
    """Busca en la pestana 'Final Sábado' si el partido entre nombre_a y
    nombre_b ya se jugo, y devuelve el nombre del ganador. None si aun no
    se ha jugado o no se encuentra."""
    na, nb = nombre_a.lower().strip(), nombre_b.lower().strip()
    try:
        df, _ = cargar_todo(URLS["Final Sábado"], "Final Sábado",
                            CORTES["Final Sábado"])
    except Exception:
        return None
    if df is None or len(df) < 2:
        return None

    def _legs(val):
        try:
            return int(float(str(val).replace(',', '.').strip()))
        except Exception:
            return -1

    for i in range(0, len(df) - 1, 2):
        f1, f2 = df.iloc[i], df.iloc[i + 1]
        n1 = str(f1.iloc[0]).strip().lower()
        n2 = str(f2.iloc[0]).strip().lower()
        if not n1 or not n2 or n1 in ('nan', '') or n2 in ('nan', ''):
            continue
        # ¿Es este el partido que buscamos (en cualquier orden)?
        if {n1, n2} != {na, nb}:
            continue
        l1 = _legs(f1.iloc[1]) if len(f1) > 1 else -1
        l2 = _legs(f2.iloc[1]) if len(f2) > 1 else -1
        if l1 >= 4 and l1 > l2:
            return str(f1.iloc[0]).strip()
        if l2 >= 4 and l2 > l1:
            return str(f2.iloc[0]).strip()
        return None  # encontrado pero sin terminar
    return None


def construir_bracket_final():
    """Construye el bracket completo de la Final Sábado:
      - 6 partidos de grupos (3 por grupo, round-robin)
      - 2 semifinales (1A vs 2B, 1B vs 2A) cuando los grupos terminen
      - 1 final (ganador SF1 vs ganador SF2) cuando las semis terminen

    Devuelve dict:
      {
        "grupos": {"Grupo A Final": [(j1,j2),...], "Grupo B Final": [...]},
        "semifinales": [(j1,j2)|None, (j1,j2)|None],
        "final": (j1,j2)|None,
        "diagnostico": str,
      }

    Cada emparejamiento es una tupla (jugador1, jugador2). Si una fase aun
    no se puede determinar (faltan resultados), su valor es None.
    """
    grupos = construir_grupos_final()
    ga = [d["jugador"] for d in grupos.get("Grupo A Final", [])]
    gb = [d["jugador"] for d in grupos.get("Grupo B Final", [])]

    resultado = {
        "grupos": {},
        "semifinales": [None, None],
        "final": None,
        "diagnostico": "",
    }

    # ── Partidos de grupos (round-robin, orden 1-3, 3-2, 2-1) ─────────────
    def _emparejamientos_grupo(jugadores):
        # jugadores en orden [1º, 2º, 3º] de la composicion
        if len(jugadores) < 3:
            # con menos de 3 no hay round-robin completo
            pares = []
            for a in range(len(jugadores)):
                for b in range(a + 1, len(jugadores)):
                    pares.append((jugadores[a], jugadores[b]))
            return pares
        p1, p2, p3 = jugadores[0], jugadores[1], jugadores[2]
        # Orden observado en la plataforma: 1-3, 3-2, 2-1
        return [(p1, p3), (p3, p2), (p2, p1)]

    resultado["grupos"]["Grupo A Final"] = _emparejamientos_grupo(ga)
    resultado["grupos"]["Grupo B Final"] = _emparejamientos_grupo(gb)

    # ── Semifinales: necesitan la clasificacion final de cada grupo ───────
    clas_a = calcular_clasificacion_final(grupos.get("Grupo A Final", []))
    clas_b = calcular_clasificacion_final(grupos.get("Grupo B Final", []))

    def _grupo_terminado(clas, n_jug):
        # round-robin de 3 -> 3 partidos -> cada jugador juega 2
        if clas is None or clas.empty:
            return False
        return int(clas["PJ"].sum()) >= n_jug  # 3 jugadores * 2 / 2 *... =3 partidos =>PJ suma 6
                                               # usamos suma de PJ >= 6 abajo

    # 1º y 2º de cada grupo (si la clasificacion existe)
    def _pos(clas, idx):
        if clas is None or clas.empty or idx >= len(clas):
            return None
        return clas.iloc[idx]["Jugador"]

    a_terminado = (clas_a is not None and not clas_a.empty
                   and int(clas_a["PJ"].sum()) >= 6)
    b_terminado = (clas_b is not None and not clas_b.empty
                   and int(clas_b["PJ"].sum()) >= 6)

    sf1 = sf2 = None
    if a_terminado and b_terminado:
        a1, a2 = _pos(clas_a, 0), _pos(clas_a, 1)
        b1, b2 = _pos(clas_b, 0), _pos(clas_b, 1)
        if a1 and b2:
            sf1 = (a1, b2)   # SF1: 1ºA vs 2ºB
        if b1 and a2:
            sf2 = (b1, a2)   # SF2: 1ºB vs 2ºA
        resultado["semifinales"] = [sf1, sf2]
        resultado["diagnostico"] = "Grupos terminados; semifinales definidas."
    else:
        resultado["diagnostico"] = (
            "Esperando a que terminen los grupos para definir semifinales.")

    # ── Final: ganadores de cada semifinal ────────────────────────────────
    if sf1 and sf2:
        g1 = _buscar_ganador_partido_final(sf1[0], sf1[1])
        g2 = _buscar_ganador_partido_final(sf2[0], sf2[1])
        if g1 and g2:
            resultado["final"] = (g1, g2)
            resultado["diagnostico"] = "Final definida."
        else:
            resultado["diagnostico"] = (
                "Semifinales definidas; esperando sus resultados para la final.")

    return resultado


def render_bracket_final():
    """Muestra el cuadro completo de la Final: semifinales y final, con los
    jugadores ya definidos o 'Por definir' si aun no se conocen."""
    bracket = construir_bracket_final()
    sf = bracket["semifinales"]
    final = bracket["final"]

    st.markdown("---")
    st.subheader("🥊 Cuadro Final (Semifinales y Final)")

    def _tarjeta(titulo, par, color):
        if par:
            cuerpo = (f"<span style='font-weight:700;'>{par[0]}</span>"
                      f"<span style='color:#94a3b8;margin:0 8px;'>vs</span>"
                      f"<span style='font-weight:700;'>{par[1]}</span>")
        else:
            cuerpo = "<span style='color:#94a3b8;'>Por definir</span>"
        return (
            f"<div style='background:white;border:1px solid #e2e8f0;"
            f"border-left:4px solid {color};border-radius:10px;"
            f"padding:12px 16px;margin-bottom:10px;'>"
            f"<div style='font-size:12px;color:#888;font-weight:600;"
            f"text-transform:uppercase;letter-spacing:0.04em;"
            f"margin-bottom:6px;'>{titulo}</div>"
            f"<div style='font-size:16px;'>{cuerpo}</div>"
            f"</div>"
        )

    html = (
        _tarjeta("Semifinal 1 · 1º Grupo A vs 2º Grupo B", sf[0], "#3b82f6")
        + _tarjeta("Semifinal 2 · 1º Grupo B vs 2º Grupo A", sf[1], "#3b82f6")
        + _tarjeta("🏆 Final · Ganador SF1 vs Ganador SF2", final, "#f59e0b")
    )
    html_compacto = " ".join(
        line.strip() for line in html.splitlines() if line.strip()
    )
    st.markdown(html_compacto, unsafe_allow_html=True)
    if bracket["diagnostico"]:
        st.caption("ℹ️ " + bracket["diagnostico"])


def obtener_campeon_semana():
    """Devuelve el nombre del campeon de la semana (ganador de la final de
    la Final Sábado) o None si la final aun no ha terminado.

    La final son los ganadores de cada semifinal. Se busca el resultado de
    ese partido en la pestana 'Final Sábado'.
    """
    bracket = construir_bracket_final()
    final = bracket.get("final")
    if not final:
        return None
    # final = (ganador_sf1, ganador_sf2); buscamos quien gano ese partido
    campeon = _buscar_ganador_partido_final(final[0], final[1])
    return campeon  # None si aun no ha terminado


def render_campeon_semana():
    """Muestra la tarjeta del campeon de la semana, SOLO si la final ha
    terminado. Si no, no muestra nada."""
    campeon = obtener_campeon_semana()
    if not campeon:
        return
    html = (
        "<div style='background:linear-gradient(135deg,#fef3c7 0%,"
        "#fde68a 100%);border:2px solid #f59e0b;border-radius:14px;"
        "padding:22px 26px;margin:18px 0;text-align:center;"
        "box-shadow:0 4px 14px rgba(245,158,11,0.25);'>"
        "<div style='font-size:13px;color:#92400e;font-weight:700;"
        "text-transform:uppercase;letter-spacing:0.08em;'>"
        "🏆 Campeón de la Semana</div>"
        f"<div style='font-size:30px;font-weight:900;color:#78350f;"
        f"margin-top:8px;'>{campeon}</div>"
        "</div>"
    )
    html_compacto = " ".join(
        line.strip() for line in html.splitlines() if line.strip()
    )
    st.markdown(html_compacto, unsafe_allow_html=True)
