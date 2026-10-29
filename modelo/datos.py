"""
modelo/datos.py - Lectura y parseo de las pestanas del Google Sheet SIN
Streamlit.

data_loading.py envuelve estas funciones con st.cache_data para la app; el
vigia las llama directamente (con su propia recarga cada pocos minutos).

Depende de: config (URLS, CORTES) y modelo.util.
"""

import csv
import io
import logging
import urllib.request

import pandas as pd

from config import URLS, CORTES
from modelo.util import safe_float, _buscar_stat

log = logging.getLogger(__name__)

# fila 1-indexed donde empiezan los partidos en las pestanas de jornada
FILA_INICIO_PARTIDOS = 7

# Orden de las jornadas de la semana y hora de inicio (Madrid)
INICIOS_JORNADAS = [
    (0, 10, 30, "Grupo A Lunes"),
    (1, 10, 30, "Grupo A Martes"),
    (2, 10, 30, "Grupo A Miércoles"),
    (3, 14, 0, "Grupo C Jueves"),
    (3, 21, 0, "Grupo B Jueves"),
    (4, 14, 0, "Grupo C Viernes"),
    (4, 21, 0, "Grupo B Viernes"),
    (5, 20, 40, "Final Sábado"),
]


def arreglar_columnas(df):
    nuevas_cols = []
    for i, col in enumerate(df.columns):
        nombre = str(col)
        if nombre == 'nan' or nombre.strip() == '':
            nombre = f"Dato_{i}"
        while nombre in nuevas_cols:
            nombre = f"{nombre}_{i}"
        nuevas_cols.append(nombre)
    df.columns = nuevas_cols
    return df

def extraer_stats_diarias(df, fila_n, col_rango):
    """Extrae estadísticas por jugador desde la sección derecha de cada pestaña diaria.
    
    Estructura del spreadsheet:
        col_rango[0] (ej. col G): contiene TANTO los títulos de stats (filas pares)
                                  COMO los valores del PRIMER jugador (filas impares).
        col_rango[0]+1, +2, ... : valores de los jugadores 2, 3, ...
    
    Por esa razón, al construir el set de títulos para evitar capturar un título
    como falso valor, hay que filtrar usando una heurística que distinga:
        - Títulos:  texto con varias letras (ej. "Media 180 por partida")
        - Valores:  números o porcentajes (ej. "2,0", "89,88", "42%", "#DIV/0!")
    
    Robustez añadida vs. versión original:
    - Rango ampliado de 35 → 60 filas (Grupo C Jueves tiene más separadores).
    - Set de títulos para anular el fallback `val_fila2` cuando captura erróneamente
      otro título (bug que mostraba "Legs por partido" como valor de Puntuación Global).
    - Fallback con secuencia canónica de títulos: si una pestaña tiene celdas
      combinadas/vacías que ocultan los títulos en CSV (caso Grupo B Jueves donde
      sólo se leen los 3-4 primeros), se completa con los títulos esperados en orden
      basándose en filas de valores numéricos huérfanas.
    """
    
    # Secuencia canónica de títulos (orden FIJO del spreadsheet, según se ve en
    # la captura del sheet real de Grupo C/B Jueves):
    #   Media 180 → Promedio puntos → Diferencia de legs → Promedio Checkouts →
    #   Número victorias → Número derrotas → Porcentaje victoria →
    #   PUNTIACIÓN GLOBAL → Legs por partido (al final, no al principio)
    SECUENCIA_TITULOS = [
        "Media 180 por partida",
        "Promedio puntos total",
        "Diferencia de legs",
        "Promedio Checkouts",
        "Número victorias",
        "Número derrotas",
        "Porcentaje victoria",
        "PUNTIACIÓN GLOBAL (0-100)",
        "Legs por partido",
        "Índice Volatilidad",
    ]
    
    def parece_titulo(s):
        """Distingue títulos vs valores numéricos.
        
        Un título debe:
        - Tener al menos 5 caracteres
        - Contener al menos 3 letras alfabéticas
        - No empezar con '#' (descarta errores tipo #DIV/0!)
        """
        s = s.strip()
        if len(s) < 5:
            return False
        if s.startswith('#'):
            return False
        letras = sum(1 for c in s if c.isalpha())
        return letras >= 3
    
    def parece_valor(s):
        """Detecta si la cadena parece un valor numérico (no un título).
        Acepta números con coma/punto decimal, porcentajes, enteros y errores #DIV/0!.
        """
        s = s.strip()
        if not s or s.lower() == 'nan':
            return False
        if s.startswith('#'):  # #DIV/0!, #N/A, etc.
            return True
        # Limpiar % y convertir coma a punto para intentar parsear como float
        try:
            float(s.replace('%', '').replace(',', '.').strip())
            return True
        except:
            return False
    
    try:
        nombres = df.iloc[fila_n, col_rango[0]:col_rango[1]].values
        jugadores = [str(n).strip() for n in nombres if str(n).strip() not in ['nan', '']]
        
        # Rango ampliado para cubrir pestañas con más separadores
        limite = min(len(df), fila_n + 60)
        
        # Pre-recolectar SOLO strings que parezcan títulos reales en col_rango[0]
        # (la columna donde van los títulos de stats en el sheet).
        titulos_set = set()
        for f in range(fila_n + 1, limite):
            t = str(df.iloc[f, col_rango[0]]).strip()
            if t and t.lower() != 'nan' and parece_titulo(t):
                titulos_set.add(t.lower())
        
        # PRIMER PASE: identificar la estructura real del bloque
        # Recorremos filas y clasificamos cada una como TÍTULO, VALORES o VACÍA.
        estructura = []  # lista de (fila_idx, tipo, dato)
        for f in range(fila_n + 1, limite):
            t = str(df.iloc[f, col_rango[0]]).strip()
            es_titulo_explicito = t and t.lower() != 'nan' and parece_titulo(t)
            
            # ¿Hay valores en las columnas de los jugadores 2..N?
            hay_valores_otros_jugadores = False
            for i in range(1, len(jugadores)):
                col = col_rango[0] + i
                if col < df.shape[1]:
                    v = str(df.iloc[f, col]).strip()
                    if parece_valor(v):
                        hay_valores_otros_jugadores = True
                        break
            
            # ¿La col_rango[0] tiene un valor numérico (valor del primer jugador)?
            col0_es_valor = parece_valor(t)
            
            if es_titulo_explicito:
                estructura.append((f, 'titulo', t))
            elif hay_valores_otros_jugadores or col0_es_valor:
                estructura.append((f, 'valores', None))
            # filas completamente vacías se ignoran
        
        # SEGUNDO PASE: emparejar títulos con sus valores.
        # Buscamos patrones (titulo) + (valores) y, cuando falte un título antes
        # de unos valores huérfanos, deducimos el título por la posición canónica.
        idx_secuencia = 0  # qué título canónico nos toca esperar
        pares = []  # lista de (titulo_resuelto, fila_de_valores)
        i = 0
        while i < len(estructura):
            f, tipo, dato = estructura[i]
            if tipo == 'titulo':
                # Sincronizar la secuencia canónica con este título explícito
                titulo_lower = dato.lower()
                for k, esp in enumerate(SECUENCIA_TITULOS):
                    if esp.lower() in titulo_lower or titulo_lower in esp.lower():
                        idx_secuencia = k + 1
                        break
                else:
                    idx_secuencia += 1
                # Buscar la siguiente fila de valores
                if i + 1 < len(estructura) and estructura[i + 1][1] == 'valores':
                    pares.append((dato, estructura[i + 1][0]))
                    i += 2
                    continue
                i += 1
            elif tipo == 'valores':
                # Valores huérfanos: usar el siguiente título canónico
                if idx_secuencia < len(SECUENCIA_TITULOS):
                    titulo_deducido = SECUENCIA_TITULOS[idx_secuencia]
                    pares.append((titulo_deducido, f))
                    idx_secuencia += 1
                i += 1
            else:
                i += 1
        
        # TERCER PASE: extraer los valores de cada par para cada jugador.
        # Para el PRIMER jugador (i=0), si su celda principal en la fila de valores
        # está vacía pero los demás jugadores SÍ tienen valor en esa fila, asumimos
        # que el primer jugador tiene 0 (la stat existe pero no la ha logrado).
        # Esto cubre el caso de Grupo B Jueves donde celdas combinadas dejan vacía
        # la columna del primer jugador en algunas filas (Número victorias, etc.).
        data_final = {}
        for i, j in enumerate(jugadores):
            stats = {}
            for titulo, fila_valores in pares:
                col = col_rango[0] + i
                v = ''
                if col < df.shape[1]:
                    v = str(df.iloc[fila_valores, col]).strip()
                    if v.lower() in titulos_set:
                        v = ''
                
                # Fallback solo para el primer jugador: si su celda está vacía pero
                # los demás jugadores tienen valor, asumir 0.
                if i == 0 and (not v or v.lower() == 'nan'):
                    otros_tienen_valor = False
                    for k in range(1, len(jugadores)):
                        col_otro = col_rango[0] + k
                        if col_otro < df.shape[1]:
                            v_otro = str(df.iloc[fila_valores, col_otro]).strip()
                            if v_otro and v_otro.lower() != 'nan' and parece_valor(v_otro):
                                otros_tienen_valor = True
                                break
                    if otros_tienen_valor:
                        # Detectar si la stat es porcentaje para mantener formato
                        ejemplo_val = str(df.iloc[fila_valores, col_rango[0] + 1]).strip()
                        v = '0%' if '%' in ejemplo_val else '0'
                
                if v and v.lower() != 'nan':
                    stats[titulo] = v
            data_final[j] = stats
        return data_final
    except:
        return {}

def extraer_stats_resumen_semanal(df):
    try:
        headers = [str(v).strip() for v in df.iloc[5].values if str(v).strip() not in ['', 'nan']]
        data = df.iloc[6:].copy()
        jugadores = {}
        for idx, row in data.iterrows():
            nombre = str(row.iloc[1]).strip() if len(row) > 1 else ""
            if nombre in ['nan', '', '=']:
                continue
            stats = {}
            col_idx = 2
            header_idx = 1
            while col_idx < len(row) and header_idx < len(headers):
                valor = row.iloc[col_idx]
                header = headers[header_idx]
                if header.strip() == '=':
                    col_idx += 1
                    header_idx += 1
                    continue
                if str(valor).strip() not in ['nan', '', '=']:
                    stats[header.lower().strip()] = valor
                col_idx += 1
                header_idx += 1
            if stats:
                jugadores[nombre.lower()] = stats
        return jugadores
    except Exception as e:
        log.error("Error extrayendo Resumen Semanal: %s", e)
        return {}


def jugadores_desde_df(pestana, df):
    """Jugadores de una pestana ya descargada (DataFrame con header=None).

    Devuelve {nombre_lower: {nombre_original, PR, lam_180, lam_legs,
    promedio_dardos, checkouts, pct_victorias, volatilidad, n_partidos}}.
    Lanza excepcion si el formato no se puede leer (el que llama decide).
    """
    # Caso especial: Resumen Semanal tiene formato tabla horizontal
    # (jugadores en filas, stats en columnas), distinto del resto.
    if pestana == "Resumen Semanal":
        stats_dict = extraer_stats_resumen_semanal(df)
        jugadores = {}
        for nombre_lower, s in stats_dict.items():
            pr       = safe_float(_buscar_stat(s, ["puntiación global", "puntuación global", "puntacion global", "puntuación", "puntiación"]))
            lam_180  = safe_float(_buscar_stat(s, ["media 180", "180 por partida", "180 por partido"]))
            lam_legs = safe_float(_buscar_stat(s, ["legs totales", "total legs", "legs por partido", "promedio legs", "leg por partido"]))
            promedio_dardos = safe_float(_buscar_stat(s, ["promedio puntos", "average", "promedio dardos", "ppd", "media puntos"]))

            # Checkout: en Resumen Semanal puede venir como decimal (0,3077) o como porcentaje (30,77%).
            # Si está entre 0 y 1, asumimos que es ratio decimal y convertimos a porcentaje.
            raw_checkout = str(_buscar_stat(s, ["checkout"])).replace("%", "").replace(",", ".").strip()
            checkouts = safe_float(raw_checkout)
            if 0 < checkouts <= 1:
                checkouts *= 100

            # Porcentaje victoria: misma lógica defensiva
            raw_pct = str(_buscar_stat(s, ["porcentaje victoria", "% victoria"])).replace("%", "").replace(",", ".").strip()
            pct_vic = safe_float(raw_pct)
            if 0 < pct_vic <= 1:
                pct_vic *= 100

            # Índice de volatilidad (irregularidad del rendimiento)
            volatilidad = safe_float(_buscar_stat(s, ["índice volatilidad", "indice volatilidad", "índice de volatilidad", "volatilidad"]))

            # Numero de partidos jugados = victorias + derrotas.
            # Se usa para ponderar la fuente "Forma reciente".
            n_vic = safe_float(_buscar_stat(s, ["número victorias", "numero victorias", "victorias"]))
            n_der = safe_float(_buscar_stat(s, ["número derrotas", "numero derrotas", "derrotas"]))
            n_partidos = int(n_vic) + int(n_der)

            jugadores[nombre_lower] = {
                "nombre_original": nombre_lower.title(),
                "PR": pr, "lam_180": lam_180, "lam_legs": lam_legs,
                "promedio_dardos": promedio_dardos,
                "checkouts": checkouts, "pct_victorias": pct_vic,
                "volatilidad": volatilidad,
                "n_partidos": n_partidos,
                "victorias": int(n_vic),
                "derrotas": int(n_der),
            }
        return jugadores

    fila_header = None
    for i, row in df.iterrows():
        if any(str(v).strip().lower() == "jugador" for v in row.values):
            fila_header = i
            break
    if fila_header is None:
        corte = CORTES.get(pestana, {})
        if "der_nombres" in corte:
            der_f  = corte["der_nombres"]
            der_c  = corte["der_cols"]
            stats  = extraer_stats_diarias(df, der_f, der_c)
            jugadores = {}
            for nombre, s in stats.items():
                pr       = safe_float(_buscar_stat(s, ["global", "puntuación", "puntuacion"]))
                lam_180  = safe_float(_buscar_stat(s, ["media 180", "180 por partida", "180 por partido"]))
                lam_legs = safe_float(_buscar_stat(s, ["legs totales", "total legs", "legs por partido", "promedio legs", "leg por partido"]))
                promedio_dardos = safe_float(_buscar_stat(s, ["promedio puntos", "average", "promedio dardos", "ppd", "media puntos"]))

                # Checkout: defensivo contra ratio decimal (0,46 → 46%)
                raw_ck = str(_buscar_stat(s, ["checkout"])).replace("%", "").replace(",", ".").strip()
                checkouts = safe_float(raw_ck)
                if 0 < checkouts <= 1:
                    checkouts *= 100

                # Porcentaje victoria: misma lógica
                raw_pv = str(_buscar_stat(s, ["porcentaje victoria", "% victoria"])).replace("%", "").replace(",", ".").strip()
                pct_vic = safe_float(raw_pv)
                if 0 < pct_vic <= 1:
                    pct_vic *= 100

                # Índice de volatilidad (irregularidad del rendimiento)
                volatilidad = safe_float(_buscar_stat(s, ["índice volatilidad", "indice volatilidad", "índice de volatilidad", "volatilidad"]))

                # Numero de partidos jugados = victorias + derrotas.
                n_vic = safe_float(_buscar_stat(s, ["número victorias", "numero victorias", "victorias"]))
                n_der = safe_float(_buscar_stat(s, ["número derrotas", "numero derrotas", "derrotas"]))
                n_partidos = int(n_vic) + int(n_der)

                jugadores[nombre.lower()] = {
                    "nombre_original": nombre,
                    "PR": pr, "lam_180": lam_180, "lam_legs": lam_legs,
                    "promedio_dardos": promedio_dardos,
                    "checkouts": checkouts, "pct_victorias": pct_vic,
                    "volatilidad": volatilidad,
                    "n_partidos": n_partidos,
                }
            return jugadores
        return {}
    headers = [str(v).strip() for v in df.iloc[fila_header].values]
    data    = df.iloc[fila_header + 1:].copy()
    data.columns = headers
    data = data.reset_index(drop=True)
    def buscar_col(keywords):
        for h in headers:
            if any(kw.lower() in h.lower() for kw in keywords):
                return h
        return None
    col_jugador = buscar_col(["jugador", "nombre"])
    col_pr      = buscar_col(["puntuación global", "puntuacion global", "global", "power"])
    col_180     = buscar_col(["media 180", "180 por partida", "180 por partido"])
    col_legs    = buscar_col(["legs totales", "total legs", "legs por partido", "leg por partido"])
    col_promedio_dardos = buscar_col(["promedio puntos", "average", "promedio dardos", "ppd", "media puntos"])
    col_checkouts = buscar_col(["checkout"])
    col_pct_vic = buscar_col(["porcentaje victoria", "% victoria", "% victoria", "%victoria"])
    col_volatilidad = buscar_col(["índice volatilidad", "indice volatilidad", "volatilidad"])
    jugadores = {}
    for _, fila in data.iterrows():
        nombre = str(fila.get(col_jugador, "")).strip() if col_jugador else ""
        if not nombre or nombre.lower() in ["nan", "jugador", ""]:
            continue
        pr       = safe_float(fila.get(col_pr,    0)) if col_pr    else 0.0
        lam_180  = safe_float(fila.get(col_180,   0)) if col_180   else 0.0
        lam_legs = safe_float(fila.get(col_legs,  0)) if col_legs  else 0.0
        promedio_dardos = safe_float(fila.get(col_promedio_dardos, 0)) if col_promedio_dardos else 0.0

        # Checkout y % victoria con conversión defensiva 0-1 → 0-100
        raw_ck = str(fila.get(col_checkouts, 0)).replace("%", "").replace(",", ".").strip() if col_checkouts else "0"
        checkouts = safe_float(raw_ck)
        if 0 < checkouts <= 1:
            checkouts *= 100

        raw_pv = str(fila.get(col_pct_vic, 0)).replace("%", "").replace(",", ".").strip() if col_pct_vic else "0"
        pct_vic = safe_float(raw_pv)
        if 0 < pct_vic <= 1:
            pct_vic *= 100

        # Índice de volatilidad (irregularidad del rendimiento)
        volatilidad = safe_float(fila.get(col_volatilidad, 0)) if col_volatilidad else 0.0

        # Numero de partidos jugados = victorias + derrotas.
        col_vic = buscar_col(["número victorias", "numero victorias", "victorias"])
        col_der = buscar_col(["número derrotas", "numero derrotas", "derrotas"])
        n_vic = safe_float(fila.get(col_vic, 0)) if col_vic else 0.0
        n_der = safe_float(fila.get(col_der, 0)) if col_der else 0.0
        n_partidos = int(n_vic) + int(n_der)

        jugadores[nombre.lower()] = {
            "nombre_original": nombre,
            "PR": pr, "lam_180": lam_180, "lam_legs": lam_legs,
            "promedio_dardos": promedio_dardos,
            "checkouts": checkouts, "pct_victorias": pct_vic,
            "volatilidad": volatilidad,
            "n_partidos": n_partidos,
        }
    return jugadores


def jornada_por_hora(ahora):
    """Jornada que toca por horario (sin mirar si tiene datos), o None.
    `ahora` en hora de Madrid. Reglas:
      Lun/Mar/Mie 10:30 - 16:00  -> Grupo A de ese dia
      Jue/Vie     14:00 - 19:00  -> Grupo C
      Jue/Vie     21:00 - 23:59  -> Grupo B
      Vie/Sab     00:00 - 03:00  -> Grupo B del dia anterior (prolongacion)
      Sab         20:40 - 23:59  -> Final Sabado
      Dom         00:00 - 03:00  -> Final Sabado (prolongacion, cierra)
    """
    wd = ahora.weekday()  # 0=lunes ... 6=domingo
    mnow = ahora.hour * 60 + ahora.minute

    DIAS_A = {0: "Grupo A Lunes", 1: "Grupo A Martes", 2: "Grupo A Miércoles"}
    DIAS_C = {3: "Grupo C Jueves", 4: "Grupo C Viernes"}
    DIAS_B = {3: "Grupo B Jueves", 4: "Grupo B Viernes"}

    jornada = None
    if mnow <= 3 * 60:   # 00:00 - 03:00: prolongacion del dia anterior
        if wd == 4:
            jornada = DIAS_B[3]
        elif wd == 5:
            jornada = DIAS_B[4]
        elif wd == 6:
            jornada = "Final Sábado"
    else:
        if wd in DIAS_A:
            if 10 * 60 + 30 <= mnow <= 16 * 60:
                jornada = DIAS_A[wd]
        elif wd in DIAS_C:
            if 14 * 60 <= mnow <= 19 * 60:
                jornada = DIAS_C[wd]
            elif 21 * 60 <= mnow:
                jornada = DIAS_B[wd]
        elif wd == 5:
            if mnow >= 20 * 60 + 40:
                jornada = "Final Sábado"
    return jornada


def jornadas_del_dia(ahora):
    """Jornadas que se juegan en la fecha de `ahora` (Madrid), en orden.
    Jue/Vie tienen dos (Grupo C por la tarde y Grupo B por la noche)."""
    return [n for (wd, _h, _m, n) in INICIOS_JORNADAS if wd == ahora.weekday()]


def jornadas_hasta(ahora):
    """Jornadas de la semana desde el lunes hasta la fecha de `ahora`
    (incluida), en orden. Las de dias posteriores aun son de la semana
    pasada."""
    return [n for (wd, _h, _m, n) in INICIOS_JORNADAS if wd <= ahora.weekday()]


def combinar_forma_reciente(resumen, datos_hoy):
    """Combina, jugador a jugador, el Resumen Semanal con la jornada de hoy
    (fuente 'Forma reciente'). Ver data_loading.cargar_forma_reciente."""
    # Estadisticas numericas que se combinan
    CAMPOS = ["PR", "lam_180", "lam_legs", "promedio_dardos",
              "checkouts", "pct_victorias", "volatilidad"]

    # Peso de "hoy" segun cuantos partidos lleve hoy el jugador.
    # Tabla a medida: con pocos partidos pesa poco (un solo partido no debe
    # distorsionar la valoracion); con la jornada avanzada, lo reciente
    # domina. A partir de 5 partidos sigue subiendo suave, con tope del 85%.
    _PESOS_HOY = {0: 0.0, 1: 0.30, 2: 0.45, 3: 0.60, 4: 0.65, 5: 0.70}

    def _peso_hoy(n):
        if n in _PESOS_HOY:
            return _PESOS_HOY[n]
        if n > 5:
            return min(0.70 + 0.03 * (n - 5), 0.85)
        return 0.0

    combinado = {}
    for nombre_lower, jug_resumen in resumen.items():
        jug_hoy = datos_hoy.get(nombre_lower)

        if not jug_hoy:
            # El jugador no ha jugado hoy: usamos su acumulado tal cual.
            combinado[nombre_lower] = dict(jug_resumen)
            continue

        # Peso dinamico segun partidos jugados hoy
        n_hoy = jug_hoy.get("n_partidos", 0)
        peso_hoy = _peso_hoy(n_hoy)

        nuevo = dict(jug_resumen)  # parte de la base del Resumen
        for campo in CAMPOS:
            v_hoy = jug_hoy.get(campo, 0.0)
            v_res = jug_resumen.get(campo, 0.0)
            # Si el valor de hoy es 0 (dato ausente), no lo mezclamos
            if v_hoy == 0.0:
                nuevo[campo] = v_res
            else:
                nuevo[campo] = peso_hoy * v_hoy + (1.0 - peso_hoy) * v_res
        nuevo["nombre_original"] = jug_resumen.get(
            "nombre_original", nombre_lower.title())
        combinado[nombre_lower] = nuevo

    return combinado


# ─────────────────────────────────────────────────────────────────────────────
# DESCARGA SIN CACHE (para el vigia)
# ─────────────────────────────────────────────────────────────────────────────

def leer_df(pestana):
    """Descarga una pestana como DataFrame (header=None)."""
    url = URLS.get(pestana, "")
    if not url:
        return None
    return pd.read_csv(url, header=None)


def cargar_jugadores(pestana):
    """Como data_loading.cargar_jugadores_desde, sin cache ni Streamlit."""
    try:
        df = leer_df(pestana)
        if df is None:
            return {}
        return jugadores_desde_df(pestana, df)
    except Exception as e:
        log.error("Error cargando %s: %s", pestana, e)
        return {}


def descargar_lineas(pestana, timeout=8):
    """CSV de una pestana como lista de filas (listas de str)."""
    url = URLS.get(pestana)
    if not url:
        return []
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            texto = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.error("No se pudo descargar %s: %s", pestana, e)
        return []
    return list(csv.reader(io.StringIO(texto)))


def cargar_forma_reciente(jornada_hoy):
    """'Forma reciente' igual que en Value Bets: Resumen Semanal combinado
    con `jornada_hoy` (la jornada en juego con datos, o None)."""
    resumen = cargar_jugadores("Resumen Semanal")
    if not resumen:
        return cargar_jugadores(jornada_hoy) if jornada_hoy else {}
    if not jornada_hoy:
        return resumen
    return combinar_forma_reciente(resumen, cargar_jugadores(jornada_hoy))


def partidos_de_jornada(lineas):
    """Partidos de una pestana de jornada en orden de juego, a partir de
    las filas del CSV (descargar_lineas). Cada partido son dos filas
    consecutivas: nombre, legs, 180s, promedio, checkout.

    Devuelve [{orden, j1, j2, legs1, legs2, t180_1, t180_2, estado}], con
    estado 'pendiente' (sin datos), 'en_juego' o 'terminado' (alguien
    llega a 4 legs). j1 es el que aparece primero en el cartel.
    """
    filas = lineas[FILA_INICIO_PARTIDOS - 1:]

    def _celda_dato(v):
        t = str(v).strip().lower()
        return t not in ("", "none", "null", "-", "0", "0.0", "0,0",
                          "0-0", "0,00%", "0%", "00:00")

    def _num(v):
        try:
            return int(float(str(v).strip().replace(",", ".")))
        except Exception:
            return 0

    partidos = []
    i = 0
    while i + 1 < len(filas):
        fila1, fila2 = filas[i], filas[i + 1]
        i += 2
        j1 = fila1[0].strip() if len(fila1) > 0 else ""
        j2 = fila2[0].strip() if len(fila2) > 0 else ""
        if not j1 or not j2:
            continue  # hueco
        celdas1 = fila1[1:5] if len(fila1) >= 5 else fila1[1:]
        celdas2 = fila2[1:5] if len(fila2) >= 5 else fila2[1:]
        legs1 = _num(fila1[1] if len(fila1) > 1 else "")
        legs2 = _num(fila2[1] if len(fila2) > 1 else "")
        if legs1 >= 4 or legs2 >= 4:
            estado = "terminado"
        elif any(_celda_dato(c) for c in celdas1) or any(_celda_dato(c) for c in celdas2):
            estado = "en_juego"
        else:
            estado = "pendiente"
        partidos.append({
            "orden": len(partidos), "j1": j1, "j2": j2,
            "legs1": legs1, "legs2": legs2,
            "t180_1": _num(fila1[2] if len(fila1) > 2 else ""),
            "t180_2": _num(fila2[2] if len(fila2) > 2 else ""),
            "estado": estado,
        })
    return partidos
