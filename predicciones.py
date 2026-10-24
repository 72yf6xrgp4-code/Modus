"""
predicciones.py - Registro y seguimiento de predicciones del modelo.

Permite registrar en una hoja de Google Sheets ("Predicciones") todas las
probabilidades que el modelo calcula para los partidos de una jornada, y
despues medir la calidad del modelo comparando cada prediccion con el
resultado real del partido.

Metricas que calcula (FASE 1, sin yield):
  - Tasa de acierto: % de veces que el favorito del modelo gano.
  - Calibracion: cuando el modelo dice 70%, ¿pasa ~70% de las veces?
  - Brier score: medida agregada de la calidad de las predicciones.

Almacenamiento: Google Sheets via gspread + cuenta de servicio. Las
credenciales se leen de st.secrets["gcp_service_account_json"], que debe
contener el JSON de la cuenta de servicio entre triples comillas.

Depende de: config, stats_engine, data_loading.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

from stats_engine import (
    prob_victoria, prob_180s, quien_hace_mas_180s,
    handicaps_legs, legs_totales,
)
from config import SHEET_ID_PREDICCIONES, MODELO_VERSION
from helpers import safe_float

# Las librerias de Google son opcionales: si no estan instaladas, el modulo
# sigue importando y el resto de la app funciona; solo el tracking queda
# desactivado con un aviso. Esto evita que un fallo de dependencias de
# Google tumbe toda la aplicacion.
try:
    import gspread
    from google.oauth2.service_account import Credentials
    _GOOGLE_DISPONIBLE = True
    _GOOGLE_ERROR = ""
except Exception as _e:
    gspread = None
    Credentials = None
    _GOOGLE_DISPONIBLE = False
    _GOOGLE_ERROR = str(_e)


# Nombre EXACTO de la hoja (pestaña) dentro del Google Sheet donde se
# guardan las predicciones. Debe coincidir con la pestaña creada a mano.
NOMBRE_HOJA_PREDICCIONES = "Predicciones"

# Cabecera de la hoja. El orden importa: las filas se escriben en este orden.
# 'ID' es la clave anti-duplicados (semana + partido + mercado + linea).
CABECERA = [
    "ID",
    "Semana",
    "Fecha registro",
    "Jornada",
    "Jugador 1",
    "Jugador 2",
    "Mercado",
    "Linea",
    "Probabilidad modelo",
    "Cuota justa",
    "Prediccion",
    "Resultado real",
    "Acierto",
    "Modelo",
]


# ─────────────────────────────────────────────────────────────────────────────
# CONEXION A GOOGLE SHEETS
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _conectar_gsheets():
    """Abre una conexion autenticada a Google Sheets usando la cuenta de
    servicio guardada en los secrets de Streamlit.

    Devuelve una tupla (cliente, error):
      - Si todo va bien: (cliente_gspread, "").
      - Si algo falla:   (None, "mensaje explicando exactamente que fallo").

    Se cachea con cache_resource para no reautenticar en cada rerun.
    """
    # Si gspread / google-auth no estan instaladas, no se puede conectar.
    if not _GOOGLE_DISPONIBLE:
        return None, ("Las librerias de Google no estan instaladas. "
                      "Anade 'gspread' y 'google-auth' a requirements.txt.")

    # Permisos necesarios: leer/escribir Sheets y abrir el archivo via Drive.
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # Paso 1: localizar el secreto
    try:
        if "gcp_service_account_json" in st.secrets:
            raw = st.secrets["gcp_service_account_json"]
            try:
                info = json.loads(raw)
            except Exception as e:
                return None, (
                    f"El secreto 'gcp_service_account_json' no es un JSON "
                    f"valido ({e}). Revisa que pegaste el JSON completo "
                    f"entre triples comillas, sin cortar nada."
                )
        elif "gcp_service_account" in st.secrets:
            info = dict(st.secrets["gcp_service_account"])
        else:
            return None, (
                "No se encontro el secreto de Google en Streamlit. Debe "
                "llamarse 'gcp_service_account_json' (o la tabla "
                "[gcp_service_account]). Revisa Manage app -> Settings -> "
                "Secrets."
            )
    except Exception as e:
        return None, f"Error leyendo los secrets de Streamlit: {e}"

    # Paso 2: comprobar que el JSON tiene los campos imprescindibles
    campos_necesarios = ("private_key", "client_email", "token_uri")
    faltan = [c for c in campos_necesarios if not info.get(c)]
    if faltan:
        return None, (
            f"Al secreto le faltan campos obligatorios: {', '.join(faltan)}. "
            f"Asegurate de pegar el JSON completo de la cuenta de servicio."
        )

    # Paso 3: crear credenciales y autorizar
    try:
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    except Exception as e:
        return None, (
            f"Las credenciales no son validas ({e}). Suele ser un problema "
            f"con el campo 'private_key': debe ir entre comillas y conservar "
            f"los \\n tal cual aparecen en el JSON."
        )

    try:
        cliente = gspread.authorize(creds)
        return cliente, ""
    except Exception as e:
        return None, f"Error autorizando con Google: {e}"


def tracking_disponible():
    """Indica si el tracking de predicciones esta operativo.

    Devuelve (disponible: bool, motivo: str). Si no esta disponible, 'motivo'
    explica por que (faltan librerias, falta el secreto, etc.) para mostrarlo
    al usuario sin romper la app.
    """
    if not _GOOGLE_DISPONIBLE:
        return False, (
            "Faltan las librerias de Google. Anade 'gspread' y "
            "'google-auth' al archivo requirements.txt del repositorio."
        )
    tiene_secreto = (
        "gcp_service_account_json" in st.secrets
        or "gcp_service_account" in st.secrets
    )
    if not tiene_secreto:
        return False, (
            "No se encontraron las credenciales de Google en los secrets "
            "de Streamlit. Revisa Manage app -> Settings -> Secrets."
        )
    return True, ""


def diagnostico_conexion(url_sheet):
    """Ejecuta una prueba completa de la conexion a Google Sheets y devuelve
    un texto explicando, paso a paso, que funciona y que no.

    Se usa en la interfaz para que el usuario sepa exactamente donde esta el
    problema sin tener que mirar los logs.
    """
    lineas = []

    # 1) Conexion / credenciales
    cliente, err = _conectar_gsheets()
    if cliente is None:
        lineas.append(f"❌ Credenciales: {err}")
        return "\n\n".join(lineas)
    lineas.append("✅ Credenciales de Google validas.")

    # 2) Abrir el libro por su ID (no por la URL publicada, que gspread no
    #    puede usar para escribir). El ID esta fijado en config.py.
    try:
        libro = cliente.open_by_key(SHEET_ID_PREDICCIONES)
        lineas.append(f"✅ Sheet abierto: '{libro.title}'.")
    except Exception as e:
        nombre_err = type(e).__name__
        if "PermissionError" in nombre_err or "403" in str(e):
            lineas.append(
                "❌ Sin permiso para abrir el Sheet. Comparte el Google "
                "Sheet (boton Compartir) con el email de la cuenta de "
                "servicio, con permiso de Editor."
            )
        elif "SpreadsheetNotFound" in nombre_err or "404" in str(e):
            lineas.append(
                "❌ No se encontro el Sheet. Comprueba que el ID en "
                "config.py (SHEET_ID_PREDICCIONES) es correcto y que el "
                "Sheet esta compartido con la cuenta de servicio."
            )
        else:
            lineas.append(f"❌ No se pudo abrir el Sheet: {nombre_err}: {e}")
        return "\n\n".join(lineas)

    # 3) Acceder/crear la pestana Predicciones
    try:
        libro.worksheet(NOMBRE_HOJA_PREDICCIONES)
        lineas.append(f"✅ Pestana '{NOMBRE_HOJA_PREDICCIONES}' encontrada.")
    except Exception:
        try:
            ws = libro.add_worksheet(title=NOMBRE_HOJA_PREDICCIONES,
                                     rows=2000, cols=len(CABECERA))
            ws.append_row(CABECERA)
            lineas.append(
                f"✅ Pestana '{NOMBRE_HOJA_PREDICCIONES}' creada (no existia)."
            )
        except Exception as e:
            lineas.append(
                f"❌ No se pudo crear la pestana '{NOMBRE_HOJA_PREDICCIONES}': "
                f"{e}. Probablemente la cuenta de servicio no tiene permiso "
                f"de Editor sobre el Sheet."
            )
            return "\n\n".join(lineas)

    lineas.append("✅ Todo correcto: el seguimiento puede escribir y leer.")
    return "\n\n".join(lineas)


def _abrir_hoja_predicciones(url_sheet=None):
    """Abre (o crea) la pestaña 'Predicciones' dentro del Google Sheet.

    El parametro url_sheet se mantiene por compatibilidad pero se ignora: el
    Sheet se abre siempre por su ID (SHEET_ID_PREDICCIONES de config.py),
    porque las URLs publicadas no sirven para escribir con gspread.

    Devuelve una tupla (worksheet, error):
      - Si todo va bien: (worksheet, "").
      - Si algo falla:   (None, "mensaje explicando que fallo").
    """
    cliente, err = _conectar_gsheets()
    if cliente is None:
        return None, err

    try:
        libro = cliente.open_by_key(SHEET_ID_PREDICCIONES)
    except Exception as e:
        nombre_err = type(e).__name__
        if "PermissionError" in nombre_err or "403" in str(e):
            return None, (
                "Sin permiso para abrir el Sheet. Comparte el Google Sheet "
                "con el email de la cuenta de servicio (permiso Editor)."
            )
        if "SpreadsheetNotFound" in nombre_err or "404" in str(e):
            return None, (
                "No se encontro el Sheet. Revisa SHEET_ID_PREDICCIONES en "
                "config.py y que el Sheet este compartido con la cuenta de "
                "servicio."
            )
        return None, f"No se pudo abrir el Sheet ({nombre_err}: {e})."

    try:
        hoja = libro.worksheet(NOMBRE_HOJA_PREDICCIONES)
    except Exception:
        # La pestaña no existe todavia: la creamos con la cabecera.
        try:
            hoja = libro.add_worksheet(
                title=NOMBRE_HOJA_PREDICCIONES,
                rows=2000,
                cols=len(CABECERA),
            )
            hoja.append_row(CABECERA)
        except Exception as e:
            return None, (
                f"No se pudo crear la pestana '{NOMBRE_HOJA_PREDICCIONES}' "
                f"({e}). Comprueba que la cuenta de servicio tiene permiso "
                f"de Editor sobre el Sheet."
            )

    # Garantizar que la cabecera existe (hoja recien creada a mano y vacia)
    try:
        primera_fila = hoja.row_values(1)
        if not primera_fila:
            hoja.append_row(CABECERA)
        elif "Modelo" not in primera_fila:
            # Hoja anterior al cambio: anadir la columna "Modelo" al final.
            # Las filas antiguas se quedan en blanco (= modelo v1).
            col = len(primera_fila) + 1
            if hoja.col_count < col:
                hoja.add_cols(col - hoja.col_count)
            hoja.update_cell(1, col, "Modelo")
    except Exception:
        pass

    return hoja, ""


# ─────────────────────────────────────────────────────────────────────────────
# CALCULO DE TODOS LOS MERCADOS DE UN PARTIDO
# ─────────────────────────────────────────────────────────────────────────────

def calcular_mercados_partido(j1_data, j2_data):
    """Calcula TODOS los mercados de un enfrentamiento.

    Parametros:
      j1_data, j2_data: dicts de jugador con claves 'PR', 'lam_180',
                        'lam_legs', 'nombre_original'.

    Devuelve una lista de dicts, uno por linea de mercado, cada uno con:
      {mercado, linea, prob, prediccion}
        - mercado:    categoria ("Ganador", "Handicap legs", ...)
        - linea:      la linea concreta ("J1 -1.5", "Mas de 5.5", ...)
        - prob:       probabilidad del modelo (0-1)
        - prediccion: texto legible de lo que predice el modelo

    Son 14 lineas por partido: ganador, 4 handicaps (los de J1; los de J2
    son las mismas apuestas al reves), total de legs, 7 de 180s y el H2H
    de 180s.
    """
    pr1 = j1_data.get("PR", 0.0)
    pr2 = j2_data.get("PR", 0.0)
    lam1 = j1_data.get("lam_180", 0.0)
    lam2 = j2_data.get("lam_180", 0.0)

    filas = []

    # 1) Ganador del partido -> UNA sola linea.
    #    "Gana J1" y "Gana J2" son la misma apuesta opuesta; registrar las dos
    #    contaria cada resultado dos veces. Guardamos una linea con el
    #    favorito del modelo.
    p1, p2 = prob_victoria(pr1, pr2)
    if p1 >= p2:
        favorito_ganador = "Gana J1"
        prob_ganador = p1
    else:
        favorito_ganador = "Gana J2"
        prob_ganador = p2
    filas.append({
        "mercado": "Ganador",
        "linea": "Ganador del partido",
        "prob": prob_ganador,
        "prediccion": favorito_ganador,
    })

    # 2) Handicaps de legs (4 lineas).
    #    Las lineas de J2 son las mismas apuestas que las de J1 al reves
    #    (J2 +1.5 = NO J1 -1.5, J2 -2.5 = NO J1 +2.5...): registrarlas todas
    #    contaba cada resultado dos veces. Solo se guardan las de J1.
    handicaps = handicaps_legs(pr1, pr2)
    for linea, prob in handicaps.items():
        if linea.startswith("J2"):
            continue
        filas.append({
            "mercado": "Handicap legs",
            "linea": linea,
            "prob": prob,
            "prediccion": "Si" if prob >= 0.5 else "No",
        })

    # 3) Total de legs -> UNA sola linea.
    #    "Más de 5.5" y "Menos de 5.5" son opuestos: una sola apuesta.
    #    Guardamos el lado que el modelo considera mas probable.
    totales = legs_totales(pr1, pr2)
    p_over = totales.get("Más de 5.5", 0.5)
    p_under = totales.get("Menos de 5.5", 0.5)
    if p_over >= p_under:
        linea_total, prob_total, pred_total = "Más de 5.5", p_over, "Más de 5.5"
    else:
        linea_total, prob_total, pred_total = "Menos de 5.5", p_under, "Menos de 5.5"
    filas.append({
        "mercado": "Total legs",
        "linea": "Total de legs",
        "prob": prob_total,
        "prediccion": pred_total,
    })

    # 4) Mercados de 180s (7 lineas).
    #    Son 7 apuestas distintas (J1 +0.5, Total +2.5...), no redundantes.
    mercados_180 = prob_180s(lam1, lam2, pr1, pr2)
    for linea, prob in mercados_180.items():
        filas.append({
            "mercado": "180s",
            "linea": linea,
            "prob": prob,
            "prediccion": "Si" if prob >= 0.5 else "No",
        })

    # 5) Quien hace mas 180s (H2H) -> UNA sola linea.
    #    Es un mercado de 3 vias (J1 / Empate / J2). Guardamos una unica
    #    linea con el favorito del modelo, no las 3.
    p_j1_180, p_emp_180, p_j2_180 = quien_hace_mas_180s(lam1, lam2, pr1, pr2)
    opciones_180 = [("J1 mas 180s", p_j1_180),
                    ("Empate 180s", p_emp_180),
                    ("J2 mas 180s", p_j2_180)]
    favorito_180, prob_fav_180 = max(opciones_180, key=lambda x: x[1])
    filas.append({
        "mercado": "Mas 180s (H2H)",
        "linea": "Quien hace mas 180s",
        "prob": prob_fav_180,
        "prediccion": favorito_180,
    })

    return filas


def _id_prediccion(semana, j1, j2, mercado, linea):
    """Construye el ID unico de una prediccion. Mismo partido + mercado +
    linea + semana -> mismo ID, de modo que registrar dos veces no duplica.
    """
    partes = [str(semana), str(j1), str(j2), str(mercado), str(linea)]
    return "|".join(p.strip().lower() for p in partes)


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRO DE PREDICCIONES (ESCRITURA EN LOTE)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_predicciones(url_sheet, enfrentamientos, semana, jornada=""):
    """Registra en la hoja 'Predicciones' todos los mercados de los
    enfrentamientos indicados.

    Si un mercado de un partido YA estaba registrado, se SOBRESCRIBE con
    los datos nuevos (probabilidad, cuota, prediccion y fecha). Asi, si
    registras un partido pronto y luego lo vuelves a registrar con datos
    mas frescos, se queda la version mas reciente. Las columnas de
    resultado (Resultado real, Acierto) NO se tocan al sobrescribir.

    Parametros:
      url_sheet:        URL del Google Sheet (puede ir vacio).
      enfrentamientos:  lista de tuplas (j1_data, j2_data) con los dicts de
                        jugador de cada partido.
      semana:           identificador de la semana/jornada (string).
      jornada:          texto descriptivo (ej. "Grupo A Lunes").

    Devuelve un dict con el resumen:
      {ok, nuevas, actualizadas, total, error}
        - nuevas:        cuantas filas se escribieron por primera vez.
        - actualizadas:  cuantas filas existentes se sobrescribieron.
        - total:         total de lineas de mercado procesadas.
    """
    hoja, err = _abrir_hoja_predicciones(url_sheet)
    if hoja is None:
        return {"ok": False, "nuevas": 0, "actualizadas": 0, "total": 0,
                "error": err or "No se pudo conectar con la hoja de Google "
                                 "Sheets."}

    # Si la jornada que llega no es una pestana real del Sheet (caso tipico:
    # 'Forma reciente', que es una fuente sintetica para calcular probas,
    # no una pestana), la sustituimos por la jornada activa real del
    # momento. Asi al verificar despues encontraremos el partido en su
    # pestana correcta.
    if jornada and jornada not in JORNADAS_VERIFICABLES:
        try:
            from data_loading import detectar_jornada_de_hoy
            jornada_real = detectar_jornada_de_hoy()
            if jornada_real:
                jornada = jornada_real
        except Exception:
            pass

    # Mapa {ID -> numero de fila en la hoja} para saber que sobrescribir.
    # La fila 1 es la cabecera, asi que los datos empiezan en la fila 2.
    try:
        registros = hoja.get_all_records()
        filas_por_id = {}
        for idx, r in enumerate(registros):
            id_r = str(r.get("ID", "")).strip()
            if id_r:
                filas_por_id[id_r] = idx + 2  # +1 cabecera, +1 base-1
    except Exception:
        filas_por_id = {}

    # Indice de columnas (para las actualizaciones de filas existentes)
    try:
        columnas = hoja.row_values(1)
        col_fecha = columnas.index("Fecha registro") + 1
        col_prob = columnas.index("Probabilidad modelo") + 1
        col_cuota = columnas.index("Cuota justa") + 1
        col_pred = columnas.index("Prediccion") + 1
    except (ValueError, Exception):
        col_fecha = col_prob = col_cuota = col_pred = None
    try:
        col_modelo = columnas.index("Modelo") + 1
    except Exception:
        col_modelo = None

    try:
        from zoneinfo import ZoneInfo
        fecha_reg = datetime.now(ZoneInfo("Europe/Madrid")).strftime(
            "%Y-%m-%d %H:%M")
    except Exception:
        fecha_reg = datetime.now().strftime("%Y-%m-%d %H:%M")
    filas_nuevas = []
    celdas_actualizar = []
    total = 0
    actualizadas = 0

    for j1_data, j2_data in enfrentamientos:
        nombre_j1 = j1_data.get("nombre_original", "?")
        nombre_j2 = j2_data.get("nombre_original", "?")
        mercados = calcular_mercados_partido(j1_data, j2_data)

        for m in mercados:
            total += 1
            id_pred = _id_prediccion(semana, nombre_j1, nombre_j2,
                                     m["mercado"], m["linea"])
            prob = m["prob"]
            cuota = round(1.0 / prob, 2) if prob > 0 else ""

            if id_pred in filas_por_id and col_prob is not None:
                # Ya existe: SOBRESCRIBIR los datos de la prediccion.
                # No se tocan Resultado real ni Acierto.
                fila = filas_por_id[id_pred]
                celdas_actualizar.append(
                    gspread.Cell(fila, col_fecha, fecha_reg))
                celdas_actualizar.append(
                    gspread.Cell(fila, col_prob, round(prob, 4)))
                celdas_actualizar.append(
                    gspread.Cell(fila, col_cuota, cuota))
                celdas_actualizar.append(
                    gspread.Cell(fila, col_pred, m["prediccion"]))
                if col_modelo is not None:
                    celdas_actualizar.append(
                        gspread.Cell(fila, col_modelo, MODELO_VERSION))
                actualizadas += 1
            else:
                # Nuevo: se anade como fila nueva.
                filas_nuevas.append([
                    id_pred,
                    str(semana),
                    fecha_reg,
                    jornada,
                    nombre_j1,
                    nombre_j2,
                    m["mercado"],
                    m["linea"],
                    round(prob, 4),
                    cuota,
                    m["prediccion"],
                    "",   # Resultado real
                    "",   # Acierto
                    MODELO_VERSION,
                ])
                # Lo registramos como existente por si se repite en el lote
                filas_por_id[id_pred] = -1

    # Escritura: primero las filas nuevas, luego las actualizaciones.
    try:
        if filas_nuevas:
            # Quitar los marcadores -1 (filas nuevas aun sin numero real)
            hoja.append_rows(filas_nuevas, value_input_option="RAW")
        if celdas_actualizar:
            hoja.update_cells(celdas_actualizar, value_input_option="RAW")
    except Exception as e:
        return {"ok": False, "nuevas": len(filas_nuevas),
                "actualizadas": actualizadas, "total": total,
                "error": f"Error escribiendo en la hoja: {e}"}

    return {"ok": True, "nuevas": len(filas_nuevas),
            "actualizadas": actualizadas, "total": total, "error": ""}


# ─────────────────────────────────────────────────────────────────────────────
# LECTURA Y METRICAS DE CALIBRACION
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def cargar_predicciones(url_sheet):
    """Lee todas las predicciones registradas en la hoja 'Predicciones'.

    Devuelve un DataFrame de pandas (vacio si no hay datos o falla la
    conexion). Cacheado 2 minutos para no releer en cada interaccion.
    """
    hoja, err = _abrir_hoja_predicciones(url_sheet)
    if hoja is None:
        return pd.DataFrame()
    try:
        registros = hoja.get_all_records()
        return pd.DataFrame(registros)
    except Exception:
        return pd.DataFrame()


def quitar_handicaps_duplicados(df):
    """Quita las lineas de handicap de J2 registradas antes del cambio.

    'J2 +1.5' es exactamente la apuesta contraria a 'J1 -1.5' (y lo mismo
    con las otras tres parejas): acierta cuando la otra acierta y falla
    cuando falla. Contar las dos duplicaba los handicaps en las metricas.
    """
    if df is None or df.empty or "Mercado" not in df.columns or "Linea" not in df.columns:
        return df
    dup = ((df["Mercado"].astype(str).str.strip() == "Handicap legs")
           & df["Linea"].astype(str).str.strip().str.upper().str.startswith("J2"))
    return df[~dup].copy()


def limpiar_predicciones(df):
    """Deja solo las predicciones que cuentan para las metricas.

    - Quita las lineas de handicap de J2 (duplican las de J1).
    - Quita las verificadas con un marcador a medias ("3-1", "3-3"...): se
      verificaron con el partido aun en juego (fallo ya corregido), asi que
      su acierto no vale.
    - Si el mismo partido se registro dos veces el mismo dia de jornada
      (con otro ID por la diferencia UTC/Madrid, ya corregida), se queda
      solo el ultimo registro.
    """
    df = quitar_handicaps_duplicados(df)
    if df is None or df.empty:
        return df
    if "Resultado real" in df.columns:
        res = df["Resultado real"].astype(str).str.strip()
        partes = res.str.extract(r"^(\d+)\s*-\s*(\d+)$")
        con_marcador = partes[0].notna()
        terminado = (partes[0].astype(float).fillna(0).clip(lower=0).combine(
            partes[1].astype(float).fillna(0), max) >= 4)
        df = df[~(con_marcador & ~terminado)].copy()
    cols = ["Jugador 1", "Jugador 2", "Mercado", "Linea", "Fecha registro"]
    if all(c in df.columns for c in cols) and not df.empty:
        fecha = pd.to_datetime(df["Fecha registro"].astype(str), errors="coerce")
        df = df.assign(_dia=(fecha - pd.Timedelta(hours=3)).dt.strftime("%Y-%m-%d"),
                       _orden=fecha)
        clave = [df["Jugador 1"].astype(str).str.lower().str.strip(),
                 df["Jugador 2"].astype(str).str.lower().str.strip(),
                 df["Mercado"].astype(str).str.strip(),
                 df["Linea"].astype(str).str.strip(), df["_dia"]]
        df = df.assign(_k=pd.Series(list(zip(*clave)), index=df.index))
        df = (df.sort_values("_orden", kind="stable")
                .drop_duplicates("_k", keep="last")
                .sort_index()
                .drop(columns=["_dia", "_orden", "_k"]))
    return df


def mascara_caducadas(df, ahora=None):
    """True en las predicciones que ya no se pueden verificar.

    Las pestanas de jornada del Sheet solo guardan la semana en curso: al
    empezar la semana nueva (lunes 03:00) se sobrescriben, asi que una
    prediccion de una semana ya cerrada que sigue sin 'Acierto' no se va a
    verificar nunca. Suele ser un partido registrado que no llego a jugarse
    (un cruce de la Final que no se dio, un partido apuntado en el grupo o
    el dia equivocado de madrugada...). No cuentan como pendientes.
    """
    if df is None or df.empty or "Fecha registro" not in df.columns:
        return pd.Series(False, index=getattr(df, "index", None))
    from helpers import inicio_semana_torneo
    inicio = inicio_semana_torneo(ahora).replace(tzinfo=None)
    fecha = pd.to_datetime(df["Fecha registro"].astype(str), errors="coerce")
    sin_acierto = (df["Acierto"].astype(str).str.strip() == ""
                   if "Acierto" in df.columns else True)
    return sin_acierto & fecha.notna() & (fecha < inicio)


NOMBRE_HOJA_CADUCADAS = "Predicciones caducadas"


def archivar_caducadas(url_sheet=None, ahora=None):
    """Saca de 'Predicciones' las predicciones caducadas (semana cerrada y
    sin verificar) y las mueve a la pestana 'Predicciones caducadas'.

    No se borra nada: las filas se copian primero al archivo y solo si la
    copia sale bien se quitan de 'Predicciones'.

    Devuelve {ok, movidas, partidos, error}.
    """
    hoja, err = _abrir_hoja_predicciones(url_sheet)
    if hoja is None:
        return {"ok": False, "movidas": 0, "partidos": 0, "error": err}
    try:
        valores = hoja.get_all_values()
    except Exception as e:
        return {"ok": False, "movidas": 0, "partidos": 0,
                "error": f"No se pudo leer la hoja: {e}"}
    if len(valores) < 2:
        return {"ok": True, "movidas": 0, "partidos": 0, "error": ""}

    cab = valores[0]
    ancho = len(cab)
    datos = [fila + [""] * (ancho - len(fila)) for fila in valores[1:]]
    df = pd.DataFrame([f[:ancho] for f in datos], columns=cab)
    mascara = mascara_caducadas(df, ahora)
    indices = [i for i, m in enumerate(mascara.tolist()) if m]
    if not indices:
        return {"ok": True, "movidas": 0, "partidos": 0, "error": ""}

    partidos = len({(df.iloc[i].get("Semana", ""), df.iloc[i].get("Jugador 1", ""),
                     df.iloc[i].get("Jugador 2", "")) for i in indices})

    # 1) Copiar al archivo
    try:
        libro = hoja.spreadsheet
        try:
            archivo = libro.worksheet(NOMBRE_HOJA_CADUCADAS)
        except Exception:
            archivo = libro.add_worksheet(title=NOMBRE_HOJA_CADUCADAS,
                                          rows=max(100, len(indices) + 10),
                                          cols=ancho + 1)
            archivo.append_row(cab + ["Archivada"],
                               value_input_option="RAW")
        sello = (ahora or datetime.now(ZoneInfo("Europe/Madrid"))).strftime(
            "%Y-%m-%d %H:%M")
        archivo.append_rows([datos[i][:ancho] + [sello] for i in indices],
                            value_input_option="RAW")
    except Exception as e:
        return {"ok": False, "movidas": 0, "partidos": partidos,
                "error": f"No se pudieron copiar al archivo (no se ha "
                         f"quitado nada): {e}"}

    # 2) Quitar de 'Predicciones' (bloques seguidos, de abajo arriba)
    bloques = []
    for i in indices:
        fila = i + 1  # 0-based en la hoja: +1 por la cabecera
        if bloques and bloques[-1][1] == fila:
            bloques[-1][1] = fila + 1
        else:
            bloques.append([fila, fila + 1])
    peticiones = [{"deleteDimension": {"range": {
        "sheetId": hoja.id, "dimension": "ROWS",
        "startIndex": a, "endIndex": b}}} for a, b in reversed(bloques)]
    try:
        hoja.spreadsheet.batch_update({"requests": peticiones})
    except Exception as e:
        return {"ok": False, "movidas": 0, "partidos": partidos,
                "error": f"Se copiaron al archivo pero no se pudieron quitar "
                         f"de 'Predicciones': {e}. Vuelve a intentarlo; "
                         f"las copias repetidas del archivo no afectan a "
                         f"nada."}
    return {"ok": True, "movidas": len(indices), "partidos": partidos,
            "error": ""}


def calcular_metricas(df):
    """Calcula las metricas de calidad del modelo a partir del DataFrame de
    predicciones. Solo usa las filas que tienen 'Acierto' relleno (es decir,
    partidos ya terminados y verificados).

    Devuelve un dict:
      {
        evaluadas:      nº de predicciones con resultado conocido,
        pendientes:     nº de predicciones aun sin resultado,
        aciertos:       nº de predicciones acertadas,
        tasa_acierto:   % de acierto (0-100),
        brier:          Brier score (0 = perfecto, 0.25 = azar, menor mejor),
        calibracion:    lista de tramos con {rango, n, prob_media, real},
      }
    """
    vacio = {"evaluadas": 0, "pendientes": 0, "caducadas": 0, "aciertos": 0,
             "tasa_acierto": 0.0, "brier": None, "calibracion": [],
             "por_mercado": []}
    if df is None or df.empty or "Acierto" not in df.columns:
        return vacio

    # Normalizar la columna Acierto. Dos estados posibles:
    #   1 / 0   -> prediccion verificada (acierto / fallo)
    #   vacio   -> aun pendiente de verificar
    def _norm_acierto(v):
        s = str(v).strip().lower()
        if s in ("1", "si", "sí", "true", "verdadero", "acierto", "ok"):
            return 1
        if s in ("0", "false", "falso", "fallo"):
            return 0
        if s == "no":
            return 0
        return None  # vacio / desconocido -> pendiente

    df = limpiar_predicciones(df)
    if df is None or df.empty:
        return vacio
    df["_acierto"] = df["Acierto"].apply(_norm_acierto)

    # Separar las categorias: pendientes de esta semana y caducadas (de
    # semanas cerradas, ya no se pueden verificar)
    caducadas_m = mascara_caducadas(df)
    caducadas = int(caducadas_m.sum())
    pendientes = int((df["_acierto"].isna() & ~caducadas_m).sum())
    # Solo 1 y 0 cuentan como evaluadas
    evaluadas_df = df[df["_acierto"].isin([0, 1])].copy()
    n_eval = len(evaluadas_df)
    if n_eval == 0:
        vacio["pendientes"] = pendientes
        vacio["caducadas"] = caducadas
        return vacio

    # En evaluadas_df, _acierto solo tiene 0 y 1: lo forzamos a entero para
    # que los calculos numericos (suma, media, Brier) funcionen sin mezclas.
    evaluadas_df["_acierto"] = evaluadas_df["_acierto"].astype(int)

    aciertos = int(evaluadas_df["_acierto"].sum())
    tasa = 100.0 * aciertos / n_eval

    # Probabilidad del modelo como numero entre 0 y 1.
    # Una probabilidad SOLO puede estar entre 0 y 1. Si un valor llega
    # corrupto (mal formato de celda, separador de miles, etc.) y queda
    # fuera de ese rango, lo descartamos: incluirlo dispararia el Brier
    # score a valores absurdos. Tambien intentamos rescatar valores que
    # vengan como porcentaje (ej. 58.33 -> 0.5833).
    def _num(v):
        try:
            x = float(str(v).strip().replace(",", "."))
        except Exception:
            return None
        # Una probabilidad real esta entre 0 y 1. Si llega algo distinto,
        # intentamos recuperarlo asumiendo que se perdio la coma decimal
        # (residuo de un bug viejo en el que Google Sheets corrompia el
        # formato al escribir con USER_ENTERED). Reglas:
        #   0   < x <= 1     -> valor correcto (0.692)
        #   1   < x <= 100   -> es porcentaje (69.2) -> /100
        #   100 < x <= 1000  -> coma perdida (692)   -> /1000
        #   1000< x <= 10000 -> coma perdida (1713)  -> /10000
        # Cualquier otro valor se descarta.
        if 0.0 <= x <= 1.0:
            return x
        if 1.0 < x <= 100.0:
            return x / 100.0
        if 100.0 < x <= 1000.0:
            return x / 1000.0
        if 1000.0 < x <= 10000.0:
            return x / 10000.0
        return None

    evaluadas_df["_prob_evento"] = evaluadas_df["Probabilidad modelo"].apply(_num)

    # IMPORTANTE: para mercados BINARIOS (Ganador, Handicap, Total, 180s
    # individuales), la columna "Probabilidad modelo" guarda la prob del
    # evento bruto. Si esa prob es <50%, el modelo en realidad apuesta por
    # el complemento (1-p). Hay que invertir para obtener la confianza
    # real de la apuesta.
    #
    # EXCEPCION: el mercado "Mas 180s (H2H)" es de 3 OPCIONES (J1/empate/J2)
    # y ya guarda la prob del favorito del modelo. Su 1-p NO seria la
    # apuesta complementaria coherente, asi que NO se invierte.
    MERCADO_H2H = "Mas 180s (H2H)"

    def _prob_apuesta(row):
        p = row["_prob_evento"]
        if p is None:
            return None
        mercado = str(row.get("Mercado", "")).strip()
        if mercado == MERCADO_H2H:
            # H2H: prob ya es la del favorito del modelo, no invertir.
            return p
        # Binario: si <50%, el modelo apuesta por el complemento.
        return p if p >= 0.5 else 1.0 - p
    evaluadas_df["_prob"] = evaluadas_df.apply(_prob_apuesta, axis=1)

    # Brier score: media de (prob - resultado)^2 sobre las filas con prob
    # valida (0-1). Como _num ya garantiza el rango, el Brier siempre saldra
    # entre 0 y 1. Por seguridad extra, lo recortamos a [0, 1].
    con_prob = evaluadas_df[evaluadas_df["_prob"].notna()]
    brier = None
    if len(con_prob) > 0:
        difs = (con_prob["_prob"] - con_prob["_acierto"]) ** 2
        brier = float(difs.mean())
        # Salvaguarda: el Brier nunca puede salir de [0, 1]
        if brier < 0.0:
            brier = 0.0
        elif brier > 1.0:
            brier = 1.0

    # Calibracion GLOBAL: agrupar por tramos de confianza de la apuesta
    # del modelo. Seis tramos desde 50% para mercados binarios.
    TRAMOS_BIN = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90),
                  (0.90, 0.95), (0.95, 1.01)]
    # Para "Mas 180s (H2H)" — mercado de 3 opciones — la prob del favorito
    # del modelo suele rondar 30-50%. Usamos tramos bajos.
    TRAMOS_H2H = [(0.30, 0.40), (0.40, 0.50), (0.50, 0.60),
                  (0.60, 0.70), (0.70, 1.01)]
    UMBRAL_FIABLE = 15  # menos de 15 predicciones -> tramo no fiable

    def _calibracion_de(sub_df, tramos):
        """Calcula la calibracion sobre un subconjunto (DataFrame) usando
        los tramos indicados.

        Devuelve una lista con un dict por tramo (solo tramos no vacios).
        """
        out = []
        for lo, hi in tramos:
            g = sub_df[(sub_df["_prob"] >= lo) & (sub_df["_prob"] < hi)]
            n_g = len(g)
            if n_g == 0:
                continue
            out.append({
                "rango": f"{int(lo*100)}-{int(hi*100)}%",
                "n": n_g,
                "prob_media": float(g["_prob"].mean()) * 100,
                "real": float(g["_acierto"].mean()) * 100,
                "fiable": n_g >= UMBRAL_FIABLE,
            })
        return out

    # La calibracion GLOBAL mezcla mercados binarios y H2H, asi que no
    # tiene mucho sentido un unico set de tramos. La construimos a partir
    # de los binarios solamente (la del H2H se ve en su tarjeta).
    con_prob_bin = con_prob[con_prob["Mercado"] != MERCADO_H2H] if "Mercado" in con_prob.columns else con_prob
    calibracion = (_calibracion_de(con_prob_bin, TRAMOS_BIN)
                   if len(con_prob_bin) > 0 else [])

    # Desglose por tipo de mercado: para cada mercado, cuantas predicciones
    # se verificaron, cuantas se acertaron, la tasa Y la calibracion propia
    # de ese mercado (con tramos adaptados: H2H usa rangos bajos).
    por_mercado = []
    if "Mercado" in evaluadas_df.columns and n_eval > 0:
        for mercado, grupo in evaluadas_df.groupby("Mercado"):
            n_m = len(grupo)
            ac_m = int(grupo["_acierto"].sum())
            tramos_m = (TRAMOS_H2H if str(mercado) == MERCADO_H2H
                        else TRAMOS_BIN)
            grupo_con_prob = grupo[grupo["_prob"].notna()]
            calib_m = (_calibracion_de(grupo_con_prob, tramos_m)
                       if len(grupo_con_prob) > 0 else [])
            # Tasa del azar para el semaforo de la tarjeta: 33% para H2H
            # (3 opciones), 50% para binarios.
            azar = 33.33 if str(mercado) == MERCADO_H2H else 50.0
            por_mercado.append({
                "mercado": str(mercado),
                "verificadas": n_m,
                "aciertos": ac_m,
                "tasa": 100.0 * ac_m / n_m if n_m > 0 else 0.0,
                "calibracion": calib_m,
                "azar": azar,
            })
        # Ordenar de mejor a peor tasa de acierto
        por_mercado.sort(key=lambda x: x["tasa"], reverse=True)

    return {
        "evaluadas": n_eval,
        "pendientes": pendientes,
        "caducadas": caducadas,
        "aciertos": aciertos,
        "tasa_acierto": tasa,
        "brier": brier,
        "calibracion": calibracion,
        "por_mercado": por_mercado,
    }


# ─────────────────────────────────────────────────────────────────────────────
# VERIFICACION AUTOMATICA DE RESULTADOS (FASE 2)
# ─────────────────────────────────────────────────────────────────────────────

# Pestanas de jornada donde buscar los resultados reales de los partidos.
JORNADAS_VERIFICABLES = [
    "Grupo A Lunes", "Grupo A Martes", "Grupo A Miércoles",
    "Grupo C Jueves", "Grupo B Jueves",
    "Grupo C Viernes", "Grupo B Viernes",
    "Final Sábado",
]


def listar_partidos_registrados(df):
    """Agrupa las predicciones por partido y devuelve una lista resumida.

    Cada partido genera ~18 filas en la hoja (una por mercado). Esta
    funcion las agrupa para mostrar UNA fila por enfrentamiento.

    Recibe el DataFrame de cargar_predicciones. Devuelve una lista de dicts:
      {jornada, partido, semana, mercados, estado}
    donde 'estado' es "Verificado" o "Pendiente".

    La lista se ordena por jornada y luego por partido.
    """
    if df is None or df.empty:
        return []

    # Columnas necesarias
    cols = df.columns
    if "Jugador 1" not in cols or "Jugador 2" not in cols:
        return []

    def _estado_fila(v):
        s = str(v).strip().lower()
        if s in ("1", "0", "si", "sí", "no", "true", "false",
                 "verdadero", "falso", "acierto", "fallo", "ok"):
            return "verificado"
        return "pendiente"  # vacio

    caducada = mascara_caducadas(df)
    partidos = {}
    for idx, fila in df.iterrows():
        j1 = str(fila.get("Jugador 1", "")).strip()
        j2 = str(fila.get("Jugador 2", "")).strip()
        jornada = str(fila.get("Jornada", "")).strip()
        semana = str(fila.get("Semana", "")).strip()
        if not j1 or not j2:
            continue
        # Clave unica del partido: jornada + los dos jugadores
        clave = f"{jornada}|{j1}|{j2}"
        if clave not in partidos:
            partidos[clave] = {
                "jornada": jornada,
                "partido": f"{j1} vs {j2}",
                "semana": semana,
                "mercados": 0,
                "estados": [],
            }
        partidos[clave]["mercados"] += 1
        estado_f = _estado_fila(fila.get("Acierto", ""))
        if estado_f == "pendiente" and bool(caducada.get(idx, False)):
            estado_f = "caducado"
        partidos[clave]["estados"].append(estado_f)

    # Resolver el estado global de cada partido
    resultado = []
    for p in partidos.values():
        estados = set(p["estados"])
        if estados == {"verificado"}:
            estado = "✅ Verificado"
        elif "pendiente" not in estados:
            # Semana cerrada sin resultado: ya no se puede verificar
            estado = "⌛ Caducado"
        else:
            # Si queda alguna fila sin verificar, el partido esta pendiente
            estado = "⏳ Pendiente"
        resultado.append({
            "Jornada": p["jornada"],
            "Partido": p["partido"],
            "Semana": p["semana"],
            "Mercados": p["mercados"],
            "Estado": estado,
        })

    resultado.sort(key=lambda x: (x["Jornada"], x["Partido"]))
    return resultado


def _normalizar_nombre(nombre):
    """Normaliza un nombre para emparejar de forma fiable:
    - quita tildes,
    - todo a minusculas,
    - colapsa espacios multiples,
    - quita signos de puntuacion comunes (puntos, comas).

    Esto permite emparejar 'García López', 'garcia lopez' y 'GARCIA  LOPEZ'
    como el mismo nombre. Es lo que distingue partidos puestos a mano
    (que pueden tener distinto casing/espacios) de los del buscador.
    """
    import unicodedata
    if not nombre:
        return ""
    s = str(nombre).strip().lower()
    # Quitar tildes
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    # Quitar puntuacion comun
    for ch in (".", ",", "'", "`", "´"):
        s = s.replace(ch, "")
    # Colapsar espacios
    s = " ".join(s.split())
    return s


def _emparejar_nombre_simple(nombre, candidatos):
    """Empareja un nombre con uno de una lista. Estrategia (mas a menos
    estricta):
      1) Coincidencia exacta tras normalizar (tildes, casing, espacios).
      2) Coincidencia por subcadena (uno contiene al otro tras normalizar).
      3) Coincidencia por apellido (ultima palabra normalizada).

    Si en la etapa 3 hay AMBIGUEDAD (varios candidatos con el mismo
    apellido), devuelve None — es mejor dejar pendiente que verificar mal.

    Devuelve el nombre ORIGINAL del candidato que coincide, o None.
    """
    if not nombre:
        return None
    n = _normalizar_nombre(nombre)
    # Pre-normalizar todos los candidatos una sola vez
    cands_norm = [(_normalizar_nombre(c), c) for c in candidatos]

    # 1) Coincidencia exacta normalizada
    for cn, c in cands_norm:
        if cn == n:
            return c
    # 2) Subcadena normalizada (uno contiene al otro), con control de
    # ambigüedad: si varios candidatos hacen match, no emparejar.
    candidatos_sub = [c for cn, c in cands_norm
                      if cn and (n in cn or cn in n)]
    if len(candidatos_sub) == 1:
        return candidatos_sub[0]
    if len(candidatos_sub) > 1:
        return None  # ambiguo, mejor pendiente que mal verificado
    # 3) Apellido normalizado, con control de ambigüedad
    ape = n.split()[-1] if n.split() else n
    if not ape:
        return None
    coincidencias = [c for cn, c in cands_norm if ape in cn.split()]
    if len(coincidencias) == 1:
        return coincidencias[0]
    # 0 coincidencias o ambigüedad (>=2) -> no emparejar
    return None


def _extraer_partidos_jugados(jornada):
    """Lee una pestana de jornada y devuelve los partidos realmente jugados.

    Cada partido son DOS filas consecutivas en la zona de partidos (columnas
    A-E): nombre, RESULTADO (legs), Nº 180S. Empareja las filas de dos en dos.

    Devuelve una lista de dicts, uno por partido:
      {j1, j2, legs1, legs2, t180_1, t180_2}

    Tiene en cuenta que 'Final Sábado' tiene todo desplazado una fila mas
    abajo (eso ya lo gestiona cargar_todo via los CORTES de config.py, asi
    que aqui solo emparejamos las filas que cargar_todo devuelve).
    """
    from data_loading import cargar_todo
    from config import URLS, CORTES

    url = URLS.get(jornada, "")
    cortes = CORTES.get(jornada, {})
    if not url or not cortes:
        return []

    try:
        df_izq, _ = cargar_todo(url, jornada, cortes)
    except Exception:
        return []
    if df_izq is None or len(df_izq) < 2:
        return []

    # df_izq tiene columnas: [JUGADORES, RESULTADO, Nº 180S, Promedio, Checkout].
    # Trabajamos por posicion para no depender de los nombres exactos.
    filas = df_izq.values.tolist()

    def _num(v):
        try:
            return int(float(str(v).replace(",", ".").strip()))
        except Exception:
            return None

    partidos = []
    i = 0
    while i + 1 < len(filas):
        f1 = filas[i]
        f2 = filas[i + 1]
        nombre1 = str(f1[0]).strip() if len(f1) > 0 else ""
        nombre2 = str(f2[0]).strip() if len(f2) > 0 else ""
        # Saltar filas sin nombre valido
        if (not nombre1 or not nombre2 or
                nombre1.lower() in ("nan", "") or
                nombre2.lower() in ("nan", "")):
            i += 1
            continue
        legs1 = _num(f1[1]) if len(f1) > 1 else None
        legs2 = _num(f2[1]) if len(f2) > 1 else None
        t180_1 = _num(f1[2]) if len(f1) > 2 else None
        t180_2 = _num(f2[2]) if len(f2) > 2 else None
        # Un partido valido necesita los legs de ambos
        if legs1 is None or legs2 is None:
            i += 1
            continue
        # Y tiene que haber TERMINADO (alguien llega a 4 legs, Bo7). Si no,
        # es un partido en curso: el Sheet ya trae el marcador parcial y,
        # antes, se verificaba con ese 2-1 y el resultado quedaba fijado
        # para siempre. Se salta el par y se verificara cuando acabe.
        if max(legs1, legs2) < 4:
            i += 2
            continue
        partidos.append({
            "j1": nombre1, "j2": nombre2,
            "legs1": legs1, "legs2": legs2,
            "t180_1": t180_1 if t180_1 is not None else 0,
            "t180_2": t180_2 if t180_2 is not None else 0,
        })
        i += 2

    return partidos


def comprobar_partidos_anteriores(jornada, nombre_j1, nombre_j2):
    """Comprueba si los dos jugadores tienen algun partido SIN TERMINAR en
    la jornada indicada.

    Lee la tabla de la jornada (la misma de LIVE). Cada partido son dos
    filas. Un partido se considera:
      - SIN EMPEZAR: alguna fila no tiene legs (vacio / None).
      - TERMINADO:   alguno de los dos jugadores ha alcanzado 4 legs.
      - EN CURSO:    tiene legs pero ninguno llega a 4 todavia.

    Devuelve un dict:
      {ok, pudo_comprobar, avisos, diagnostico}
        - ok:            True si ningun jugador tiene partidos a medias.
        - pudo_comprobar: True si la comprobacion se hizo de verdad. Si es
                          False, la app NO debe dar por buena la
                          comprobacion (no se pudo leer la tabla, etc.).
        - avisos:        lista de partidos sin terminar.
        - diagnostico:   texto con lo que la funcion ha detectado, para
                         depurar por que no encuentra partidos.
    """
    from data_loading import cargar_todo
    from config import URLS, CORTES

    diag = []
    diag.append(f"Jornada recibida: '{jornada}'")

    # Jornadas a probar: si la jornada recibida es de jueves o viernes,
    # probamos AMBAS jornadas de ese dia (Grupo C por la manana, Grupo B
    # por la noche), porque puede que el partido este en la otra.
    jornadas_a_probar = [jornada]
    PARES_MISMO_DIA = {
        "Grupo B Jueves":  "Grupo C Jueves",
        "Grupo C Jueves":  "Grupo B Jueves",
        "Grupo B Viernes": "Grupo C Viernes",
        "Grupo C Viernes": "Grupo B Viernes",
    }
    if jornada in PARES_MISMO_DIA:
        jornadas_a_probar.append(PARES_MISMO_DIA[jornada])
        diag.append(f"Tambien probaremos: '{PARES_MISMO_DIA[jornada]}' "
                    f"(misma fecha)")

    # Probar cada jornada hasta encontrar una donde aparezca el partido
    df_izq = None
    jornada_usada = None
    for jor in jornadas_a_probar:
        url = URLS.get(jor, "")
        cortes = CORTES.get(jor, {})
        if not url or not cortes:
            diag.append(f"❌ '{jor}' no esta en URLS/CORTES.")
            continue
        try:
            df_tmp, _ = cargar_todo(url, jor, cortes)
        except Exception as e:
            diag.append(f"❌ Error cargando '{jor}': {e}")
            continue
        if df_tmp is None or len(df_tmp) < 2:
            diag.append(f"❌ Tabla vacia en '{jor}'.")
            continue
        # Comprobar si el partido a registrar aparece en esta tabla
        nombres_tabla = []
        for fila in df_tmp.values.tolist():
            if len(fila) > 0 and str(fila[0]).strip().lower() not in ("", "nan"):
                nombres_tabla.append(str(fila[0]).strip())
        o1 = str(nombre_j1).lower().strip()
        o2 = str(nombre_j2).lower().strip()
        def _aparece(obj, lista):
            for n in lista:
                nl = n.lower().strip()
                if nl == obj or nl in obj or obj in nl:
                    return True
                ape = obj.split()[-1] if obj.split() else obj
                if ape and ape in nl:
                    return True
            return False
        if _aparece(o1, nombres_tabla) and _aparece(o2, nombres_tabla):
            df_izq = df_tmp
            jornada_usada = jor
            diag.append(f"✅ Partido encontrado en '{jor}'.")
            break
        else:
            diag.append(f"Partido no aparece en '{jor}'.")

    if df_izq is None:
        diag.append("❌ El partido no aparece en ninguna de las jornadas "
                     "probadas. No se puede comprobar.")
        return {"ok": True, "pudo_comprobar": False,
                "avisos": [], "diagnostico": "\n".join(diag)}

    filas = df_izq.values.tolist()
    diag.append(f"Tabla leida: {len(filas)} filas.")

    def _num(v):
        try:
            return int(float(str(v).replace(",", ".").strip()))
        except Exception:
            return None

    objetivo_j1 = str(nombre_j1).lower().strip()
    objetivo_j2 = str(nombre_j2).lower().strip()
    diag.append(f"Buscando a: '{nombre_j1}' y '{nombre_j2}'")

    def _es_el_jugador(nombre, objetivo):
        n = str(nombre).lower().strip()
        if n == objetivo:
            return True
        if n in objetivo or objetivo in n:
            return True
        # Coincidencia por apellido (ultima palabra de cada nombre)
        ape_obj = objetivo.split()[-1] if objetivo.split() else objetivo
        ape_n = n.split()[-1] if n.split() else n
        if ape_obj and ape_n and ape_obj == ape_n:
            return True
        return False

    def _tiene_dato(fila, idx):
        if len(fila) <= idx:
            return False
        v = str(fila[idx]).strip().lower()
        return v not in ("", "nan", "none", "0", "0.0")

    # Primera pasada: recorrer la tabla y construir la lista de partidos,
    # cada uno con su posicion (indice), nombres, jugadores implicados y
    # estado. La tabla esta en orden cronologico (arriba = antes).
    partidos = []
    i = 0
    while i + 1 < len(filas):
        f1 = filas[i]
        f2 = filas[i + 1]
        nombre1 = str(f1[0]).strip() if len(f1) > 0 else ""
        nombre2 = str(f2[0]).strip() if len(f2) > 0 else ""
        if (not nombre1 or not nombre2 or
                nombre1.lower() in ("nan", "") or
                nombre2.lower() in ("nan", "")):
            i += 1
            continue

        legs1 = _num(f1[1]) if len(f1) > 1 else None
        legs2 = _num(f2[1]) if len(f2) > 1 else None
        otros1 = any(_tiene_dato(f1, idx) for idx in (2, 3, 4))
        otros2 = any(_tiene_dato(f2, idx) for idx in (2, 3, 4))

        # Clasificacion del estado:
        #  - TERMINADO: alguno alcanzo 4 legs.
        #  - SIN EMPEZAR: ninguna columna tiene datos.
        #  - EN CURSO: tiene datos pero nadie llego a 4 legs.
        if (legs1 is not None and legs2 is not None and
                (legs1 >= 4 or legs2 >= 4)):
            estado = "terminado"
        elif (legs1 is None and legs2 is None and
              not otros1 and not otros2):
            estado = "sin_empezar"
        else:
            estado = "en_curso"

        partidos.append({
            "orden": len(partidos),
            "nombre1": nombre1, "nombre2": nombre2,
            "legs1": legs1, "legs2": legs2,
            "estado": estado,
        })
        i += 2

    diag.append(f"Partidos en la tabla: {len(partidos)}")

    # Localizar el partido que se va a registrar (el de nombre_j1 vs
    # nombre_j2). Puede aparecer en cualquier orden de jugadores.
    idx_objetivo = None
    for p in partidos:
        n1, n2 = p["nombre1"], p["nombre2"]
        empareja = (
            (_es_el_jugador(n1, objetivo_j1) and _es_el_jugador(n2, objetivo_j2))
            or
            (_es_el_jugador(n1, objetivo_j2) and _es_el_jugador(n2, objetivo_j1))
        )
        if empareja:
            idx_objetivo = p["orden"]
            diag.append(f"Partido a registrar encontrado en posicion "
                        f"{idx_objetivo}: {n1} vs {n2}")
            break

    if idx_objetivo is None:
        # El partido a registrar no aparece en la tabla. Antes esto era
        # siempre "no se puede comprobar", pero hay un caso comun y legitimo:
        # es el PRIMER partido de esos jugadores en la jornada (aun no se
        # ha jugado y por tanto no aparece). Comprobamos si en la tabla
        # hay algun partido anterior que involucre a alguno de los dos
        # jugadores:
        #   - Si NO hay ninguno -> es el primer partido de estos jugadores.
        #     No hay nada que comprobar, dejamos registrar.
        #   - Si SI hay -> situacion rara (tiene anteriores pero el partido
        #     a registrar no aparece): mantenemos el aviso para no
        #     verificar mal.
        tiene_anteriores = False
        for p in partidos:
            if (_es_el_jugador(p["nombre1"], objetivo_j1) or
                    _es_el_jugador(p["nombre1"], objetivo_j2) or
                    _es_el_jugador(p["nombre2"], objetivo_j1) or
                    _es_el_jugador(p["nombre2"], objetivo_j2)):
                tiene_anteriores = True
                break

        if not tiene_anteriores:
            diag.append("✅ El partido a registrar no aparece todavia y los "
                         "jugadores no tienen partidos anteriores en la "
                         "tabla. Es el primer partido — todo OK.")
            return {"ok": True, "pudo_comprobar": True,
                    "avisos": [], "diagnostico": "\n".join(diag)}

        diag.append("⚠️ El partido a registrar NO aparece en la tabla, pero "
                     "los jugadores SI tienen partidos anteriores ahi. "
                     "Mejor revisar antes de registrar.")
        diag.append(f"Nombres en la tabla: "
                     f"{sorted({p['nombre1'] for p in partidos} | {p['nombre2'] for p in partidos})}")
        return {"ok": True, "pudo_comprobar": False,
                "avisos": [], "diagnostico": "\n".join(diag)}

    # Revisar los partidos ANTERIORES (los que estan por encima en la tabla,
    # es decir orden < idx_objetivo) que involucren a alguno de los dos
    # jugadores. Si alguno NO esta terminado -> aviso.
    avisos = []
    for p in partidos:
        if p["orden"] >= idx_objetivo:
            continue  # este partido es el objetivo o uno posterior
        afecta = (
            _es_el_jugador(p["nombre1"], objetivo_j1) or
            _es_el_jugador(p["nombre1"], objetivo_j2) or
            _es_el_jugador(p["nombre2"], objetivo_j1) or
            _es_el_jugador(p["nombre2"], objetivo_j2)
        )
        if not afecta:
            continue
        if p["estado"] != "terminado":
            etiqueta = ("en curso" if p["estado"] == "en_curso"
                        else "sin jugar")
            avisos.append(
                f"{p['nombre1']} {p['legs1']}-{p['legs2']} {p['nombre2']} "
                f"({etiqueta})")
            diag.append(f"  ⚠️ Anterior sin terminar: {p['nombre1']} vs "
                        f"{p['nombre2']} [{p['estado']}]")

    if not avisos:
        diag.append("✅ Todos los partidos anteriores de estos jugadores "
                     "estan terminados.")

    return {
        "ok": len(avisos) == 0,
        "pudo_comprobar": True,
        "avisos": avisos,
        "diagnostico": "\n".join(diag),
    }


def _verificar_mercado(mercado, linea, prediccion, legs_a, legs_b,
                       t180_a, t180_b):
    """Comprueba si una prediccion acerto, dado el resultado real del partido.

    'a' es el Jugador 1 de la prediccion, 'b' el Jugador 2 (en el mismo orden
    en que se registraron). legs y t180 son los del partido real.

    Devuelve:
      1   -> la prediccion acerto
      0   -> la prediccion fallo
      None -> el mercado no se puede verificar (raro)
    """
    dif = legs_a - legs_b           # diferencia de legs J1 - J2
    total_legs = legs_a + legs_b
    gana_a = legs_a > legs_b

    # ── Ganador ──────────────────────────────────────────────────────────────
    if mercado == "Ganador":
        # prediccion es "Gana J1" o "Gana J2"
        acerto_es_j1 = "j1" in prediccion.lower()
        if acerto_es_j1:
            return 1 if gana_a else 0
        else:
            return 1 if not gana_a else 0

    # ── Handicap legs ────────────────────────────────────────────────────────
    if mercado == "Handicap legs":
        # 'linea' es del tipo "J1 -1.5 Legs", "J2 +2.5 Legs", etc.
        # 'prediccion' es "Si" / "No": Si = el modelo cree que SE CUMPLE.
        se_cumple = None
        l = linea.lower()
        if l.startswith("j1 -1.5"):
            se_cumple = dif >= 2
        elif l.startswith("j1 -2.5"):
            se_cumple = dif >= 3
        elif l.startswith("j1 +1.5"):
            se_cumple = dif >= -1     # no pierde por 2 o mas
        elif l.startswith("j1 +2.5"):
            se_cumple = dif >= -2
        elif l.startswith("j2 -1.5"):
            se_cumple = (-dif) >= 2
        elif l.startswith("j2 -2.5"):
            se_cumple = (-dif) >= 3
        elif l.startswith("j2 +1.5"):
            se_cumple = (-dif) >= -1
        elif l.startswith("j2 +2.5"):
            se_cumple = (-dif) >= -2
        if se_cumple is None:
            return None
        predijo_si = prediccion.strip().lower() in ("si", "sí")
        return 1 if (se_cumple == predijo_si) else 0

    # ── Total de legs ────────────────────────────────────────────────────────
    if mercado == "Total legs":
        # 'prediccion' es directamente "Más de 5.5" o "Menos de 5.5":
        # el lado que el modelo considero mas probable.
        p = prediccion.strip().lower()
        if "más" in p or "mas" in p:
            # El modelo predijo "mas de 5.5": acierta si hubo > 5.5 legs
            return 1 if total_legs > 5.5 else 0
        elif "menos" in p:
            return 1 if total_legs < 5.5 else 0
        else:
            return None

    # ── 180s (lineas +0.5 / +1.5 / +2.5) ─────────────────────────────────────
    if mercado == "180s":
        l = linea.lower()
        if l.startswith("j1 +0.5"):
            se_cumple = t180_a >= 1
        elif l.startswith("j1 +1.5"):
            se_cumple = t180_a >= 2
        elif l.startswith("j2 +0.5"):
            se_cumple = t180_b >= 1
        elif l.startswith("j2 +1.5"):
            se_cumple = t180_b >= 2
        elif l.startswith("ambos +0.5"):
            se_cumple = (t180_a >= 1) and (t180_b >= 1)
        elif l.startswith("ambos +1.5") or l.startswith("total +1.5"):
            se_cumple = (t180_a + t180_b) >= 2     # 180s sumados
        elif l.startswith("ambos +2.5") or l.startswith("total +2.5"):
            se_cumple = (t180_a + t180_b) >= 3
        else:
            return None
        predijo_si = prediccion.strip().lower() in ("si", "sí")
        return 1 if (se_cumple == predijo_si) else 0

    # ── Quien hace mas 180s (H2H) ────────────────────────────────────────────
    if mercado == "Mas 180s (H2H)":
        # 'prediccion' es el favorito: "J1 mas 180s" / "Empate 180s" / "J2 mas 180s"
        if t180_a > t180_b:
            real = "J1 mas 180s"
        elif t180_b > t180_a:
            real = "J2 mas 180s"
        else:
            real = "Empate 180s"
        return 1 if (prediccion.strip().lower() == real.lower()) else 0

    return None


def verificar_resultados(url_sheet=None):
    """Verifica automaticamente las predicciones pendientes comparandolas con
    los resultados reales de los partidos en las pestanas de jornada.

    Para cada prediccion sin 'Acierto':
      - Busca si ese enfrentamiento se jugo de verdad en su jornada.
      - Si se jugo: comprueba el mercado y escribe 1 o 0.
      - Si aun NO se ha jugado: lo deja PENDIENTE (no escribe nada), para
        que una verificacion posterior lo recoja cuando ya este jugado.

    Escribe los resultados en LOTE en la columna 'Acierto' (y 'Resultado
    real') de la hoja Predicciones.

    Devuelve un dict resumen:
      {ok, verificadas, aciertos, fallos, sin_cambios, error}
    """
    hoja, err = _abrir_hoja_predicciones(url_sheet)
    if hoja is None:
        return {"ok": False, "verificadas": 0, "aciertos": 0, "fallos": 0,
                "sin_cambios": 0,
                "error": err or "No se pudo abrir la hoja."}

    # Leer todas las predicciones
    try:
        registros = hoja.get_all_records()
    except Exception as e:
        return {"ok": False, "verificadas": 0, "aciertos": 0, "fallos": 0,
                "sin_cambios": 0,
                "error": f"No se pudieron leer las predicciones: {e}"}

    if not registros:
        return {"ok": True, "verificadas": 0, "aciertos": 0, "fallos": 0,
                "sin_cambios": 0, "error": ""}

    # Cargar los partidos jugados de TODAS las jornadas (una sola vez).
    # partidos_por_jornada[jornada] = lista de dicts de partido.
    partidos_por_jornada = {}
    for jornada in JORNADAS_VERIFICABLES:
        partidos_por_jornada[jornada] = _extraer_partidos_jugados(jornada)

    # Indice de columnas de la hoja (fila 1 = cabecera)
    columnas = hoja.row_values(1)
    try:
        col_acierto = columnas.index("Acierto") + 1
        col_resultado = columnas.index("Resultado real") + 1
    except ValueError:
        return {"ok": False, "verificadas": 0, "aciertos": 0, "fallos": 0,
                "sin_cambios": 0,
                "error": "La hoja no tiene las columnas 'Acierto' / "
                         "'Resultado real'. ¿Es la hoja correcta?"}

    # Recorrer predicciones y preparar las actualizaciones
    actualizaciones = []   # lista de (fila_hoja, valor_acierto, valor_resultado)
    aciertos = fallos = sin_cambios = 0
    # Diagnostico: para partidos que quedan pendientes, registramos el motivo
    # (sin duplicar — usamos clave partido+jornada para deduplicar entre
    # los 18 mercados del mismo partido).
    pendientes_diag = {}  # {clave: motivo}

    # Las pestanas de jornada solo tienen los partidos de ESTA semana (se
    # limpian el lunes). Una prediccion pendiente de una semana anterior no
    # se puede verificar ya, y compararla con la semana actual daria un
    # resultado falso si los mismos jugadores vuelven a enfrentarse.
    try:
        from helpers import inicio_semana_torneo
        inicio_semana = inicio_semana_torneo().strftime("%Y-%m-%d %H:%M")
    except Exception:
        inicio_semana = None

    for idx, reg in enumerate(registros):
        fila_hoja = idx + 2   # +1 cabecera, +1 base-1

        # Si ya esta verificada (Acierto no vacio), no la tocamos
        acierto_actual = str(reg.get("Acierto", "")).strip()
        if acierto_actual != "":
            sin_cambios += 1
            continue

        fecha_reg = str(reg.get("Fecha registro", "")).strip()
        if inicio_semana and fecha_reg and fecha_reg < inicio_semana:
            clave_vieja = (f"{reg.get('Jornada', '')}|{reg.get('Jugador 1', '')} "
                           f"vs {reg.get('Jugador 2', '')}")
            pendientes_diag[clave_vieja] = (
                f"Registrada el {fecha_reg}, de una semana anterior: ya no "
                f"se puede verificar con las pestanas actuales")
            continue

        jornada = str(reg.get("Jornada", "")).strip()
        j1_pred = str(reg.get("Jugador 1", "")).strip()
        j2_pred = str(reg.get("Jugador 2", "")).strip()
        mercado = str(reg.get("Mercado", "")).strip()
        linea = str(reg.get("Linea", "")).strip()
        prediccion = str(reg.get("Prediccion", "")).strip()

        clave_partido = f"{jornada}|{j1_pred} vs {j2_pred}"

        # Si la jornada registrada NO es una pestana real del Sheet (caso
        # tipico: "Forma reciente", que es una fuente sintetica), probamos
        # en TODAS las jornadas reales hasta encontrar a los dos jugadores.
        jornada_es_real = jornada in JORNADAS_VERIFICABLES
        if not jornada_es_real:
            partidos = []
            for jor_real in JORNADAS_VERIFICABLES:
                partidos = partidos_por_jornada.get(jor_real, [])
                if not partidos:
                    continue
                nombres_jr = sorted(set(
                    n for p in partidos for n in (p["j1"], p["j2"])))
                j1_pr = _emparejar_nombre_simple(j1_pred, nombres_jr)
                j2_pr = _emparejar_nombre_simple(j2_pred, nombres_jr)
                if j1_pr and j2_pr:
                    # Esta es la jornada real — la usamos
                    jornada = jor_real
                    break
            else:
                pendientes_diag[clave_partido] = (
                    f"Jornada '{jornada}' no es real. Buscando en todas "
                    f"las jornadas, no aparecen ambos jugadores en ninguna.")
                continue

        partidos = partidos_por_jornada.get(jornada, [])
        if not partidos:
            pendientes_diag[clave_partido] = (
                f"Jornada '{jornada}' sin partidos cargados")
            continue

        # Buscar el partido en la jornada registrada. Si no aparecen los
        # nombres, probar la jornada GEMELA del mismo dia (B<->C jueves
        # o viernes) — es habitual que se registre con la jornada
        # equivocada cuando ambos grupos se juegan el mismo dia.
        PARES_MISMO_DIA = {
            "Grupo B Jueves":  "Grupo C Jueves",
            "Grupo C Jueves":  "Grupo B Jueves",
            "Grupo B Viernes": "Grupo C Viernes",
            "Grupo C Viernes": "Grupo B Viernes",
        }

        def _buscar_en(parts):
            """Intenta encontrar el partido en una lista de partidos.
            Devuelve (partido, orden_invertido, motivo).
            motivo es '' si OK, 'nombres' si no estan, 'no_jugado' si
            estan pero el partido no aparece.
            """
            if not parts:
                return None, False, "vacia"
            nombres = sorted(set(
                n for p in parts for n in (p["j1"], p["j2"])))
            j1r = _emparejar_nombre_simple(j1_pred, nombres)
            j2r = _emparejar_nombre_simple(j2_pred, nombres)
            if not j1r or not j2r:
                return None, False, "nombres"
            for p in parts:
                if p["j1"] == j1r and p["j2"] == j2r:
                    return p, False, ""
                if p["j1"] == j2r and p["j2"] == j1r:
                    return p, True, ""
            return None, False, "no_jugado"

        partido, orden_invertido, motivo = _buscar_en(partidos)

        # Si no se encontraron los nombres en la jornada registrada, probar
        # la gemela del mismo dia (puede que se registrara con la jornada
        # equivocada — por ejemplo registrado en B cuando jugo en C).
        jornada_efectiva = jornada
        if partido is None and motivo == "nombres" and jornada in PARES_MISMO_DIA:
            gemela = PARES_MISMO_DIA[jornada]
            partidos_gem = partidos_por_jornada.get(gemela, [])
            p_g, oi_g, motivo_g = _buscar_en(partidos_gem)
            if p_g is not None:
                partido = p_g
                orden_invertido = oi_g
                jornada_efectiva = gemela
                motivo = ""

        if partido is None:
            if motivo == "nombres":
                pendientes_diag[clave_partido] = (
                    f"Nombres no encontrados en '{jornada}'"
                    + (f" ni en '{PARES_MISMO_DIA[jornada]}'"
                       if jornada in PARES_MISMO_DIA else "")
                    + f": {j1_pred}, {j2_pred}")
            else:
                pendientes_diag[clave_partido] = (
                    "Jugadores encontrados pero el partido no aparece "
                    "(¿aun no jugado?)")
            continue

        # Alinear legs/180s con el orden J1/J2 de la PREDICCION
        if not orden_invertido:
            legs_a, legs_b = partido["legs1"], partido["legs2"]
            t180_a, t180_b = partido["t180_1"], partido["t180_2"]
        else:
            legs_a, legs_b = partido["legs2"], partido["legs1"]
            t180_a, t180_b = partido["t180_2"], partido["t180_1"]

        resultado_txt = f"{legs_a}-{legs_b}"
        acierto = _verificar_mercado(mercado, linea, prediccion,
                                     legs_a, legs_b, t180_a, t180_b)
        if acierto is None:
            # Mercado no verificable: lo dejamos pendiente
            continue

        actualizaciones.append((fila_hoja, str(acierto), resultado_txt))
        if acierto == 1:
            aciertos += 1
        else:
            fallos += 1

    # Escribir las actualizaciones en la hoja.
    # Se hace celda por celda agrupando, pero usando update por rangos para
    # no saturar la API. gspread permite actualizar celdas individuales;
    # aqui agrupamos por columna en bloques.
    if actualizaciones:
        try:
            celdas = []
            for fila_hoja, val_acierto, val_resultado in actualizaciones:
                celdas.append(gspread.Cell(fila_hoja, col_acierto, val_acierto))
                celdas.append(gspread.Cell(fila_hoja, col_resultado,
                                           val_resultado))
            hoja.update_cells(celdas, value_input_option="RAW")
        except Exception as e:
            return {"ok": False, "verificadas": 0, "aciertos": 0,
                    "fallos": 0, "sin_cambios": sin_cambios,
                    "error": f"Error escribiendo los resultados: {e}"}

    return {
        "ok": True,
        "verificadas": aciertos + fallos,
        "aciertos": aciertos,
        "fallos": fallos,
        "sin_cambios": sin_cambios,
        "pendientes_diag": pendientes_diag,
        "error": "",
    }

# ─────────────────────────────────────────────────────────────────────────────
# HISTORICO SEMANAL DE JUGADORES
# ─────────────────────────────────────────────────────────────────────────────

NOMBRE_HOJA_HISTORICO = "Historico"

NOMBRE_HOJA_CAMPEONES = "Campeones"
CABECERA_CAMPEONES = ["Fecha sabado", "Campeon"]

# Cabecera de la pestana de historico. Una fila por jugador y semana.
CABECERA_HISTORICO = [
    "Fecha sabado", "Jugador", "PR", "Media 180s", "Legs por partido",
    "Promedio dardos", "Checkout %", "% Victorias", "Volatilidad",
    "Victorias", "Derrotas", "Partidos jugados",
]


def _fecha_sabado_de_la_semana(hoy=None):
    """Devuelve la fecha (YYYY-MM-DD) del sabado de la semana actual del
    torneo (la semana NO cierra hasta que el script de Sheets borra los
    datos, lo cual ocurre el lunes de madrugada).

    Regla:
      - Lunes..sabado -> sabado de esta semana (hacia adelante en el calendario)
      - Domingo       -> sabado de AYER (la semana del torneo sigue abierta)

    Asi, si guardas el domingo tras la jornada final, se asigna a la
    misma semana que el sabado anterior — no a la semana siguiente.
    """
    from datetime import datetime, timedelta
    if hoy is None:
        try:
            from zoneinfo import ZoneInfo
            hoy = datetime.now(ZoneInfo("Europe/Madrid"))
        except Exception:
            hoy = datetime.now()
    # weekday(): lunes=0 ... sabado=5, domingo=6
    wd = hoy.weekday()
    if wd == 6:  # domingo -> sabado de AYER (la semana del torneo sigue abierta)
        sabado = hoy - timedelta(days=1)
    else:        # lunes..sabado -> sabado de esta semana
        delta = 5 - wd
        sabado = hoy + timedelta(days=delta)
    return sabado.strftime("%Y-%m-%d")


def _abrir_hoja_historico():
    """Abre (o crea) la pestana 'Historico' del Sheet de predicciones.

    Devuelve (worksheet, error). Mismo patron que _abrir_hoja_predicciones.
    """
    cliente, err = _conectar_gsheets()
    if cliente is None:
        return None, err
    try:
        libro = cliente.open_by_key(SHEET_ID_PREDICCIONES)
    except Exception as e:
        return None, f"No se pudo abrir el Sheet ({type(e).__name__}: {e})."
    try:
        hoja = libro.worksheet(NOMBRE_HOJA_HISTORICO)
    except Exception:
        # No existe: la creamos con su cabecera.
        try:
            hoja = libro.add_worksheet(
                title=NOMBRE_HOJA_HISTORICO,
                rows=5000,
                cols=len(CABECERA_HISTORICO),
            )
            hoja.append_row(CABECERA_HISTORICO)
        except Exception as e:
            return None, (
                f"No se pudo crear la pestana '{NOMBRE_HOJA_HISTORICO}' "
                f"({e}). Comprueba que la cuenta de servicio tiene permiso "
                f"de Editor sobre el Sheet."
            )
    # Garantizar cabecera
    try:
        if not hoja.row_values(1):
            hoja.append_row(CABECERA_HISTORICO)
    except Exception:
        pass
    return hoja, ""


def guardar_historico_semana(jugadores, fecha_sabado=None):
    """Guarda una 'foto' de las stats de todos los jugadores de la semana
    en la pestana 'Historico'.

    Parametros:
      jugadores:     dict {nombre_lower: datos_jugador} tal como lo
                     devuelve cargar_jugadores (del Resumen Semanal).
      fecha_sabado:  etiqueta de la semana (YYYY-MM-DD). Si es None, se
                     calcula el sabado de la semana actual.

    Comportamiento: si ya existen filas con esa misma fecha de sabado, se
    BORRAN y se reescriben con los datos actuales (sobrescritura), para que
    no se dupliquen semanas.

    Devuelve un dict: {ok, fecha, guardados, sobrescrita, error}.
    """
    if fecha_sabado is None:
        fecha_sabado = _fecha_sabado_de_la_semana()

    hoja, err = _abrir_hoja_historico()
    if hoja is None:
        return {"ok": False, "fecha": fecha_sabado, "guardados": 0,
                "sobrescrita": False, "error": err}

    if not jugadores:
        return {"ok": False, "fecha": fecha_sabado, "guardados": 0,
                "sobrescrita": False,
                "error": "No hay jugadores que guardar."}

    # 1) Comprobar si esa semana ya estaba guardada (sobrescritura)
    sobrescrita = False
    try:
        registros = hoja.get_all_records()
        filas_misma_fecha = [
            i + 2 for i, r in enumerate(registros)
            if str(r.get("Fecha sabado", "")).strip() == fecha_sabado
        ]
    except Exception:
        filas_misma_fecha = []

    # Borramos de abajo hacia arriba para no descuadrar los indices
    if filas_misma_fecha:
        sobrescrita = True
        try:
            for fila in sorted(filas_misma_fecha, reverse=True):
                hoja.delete_rows(fila)
        except Exception as e:
            return {"ok": False, "fecha": fecha_sabado, "guardados": 0,
                    "sobrescrita": False,
                    "error": f"No se pudieron borrar las filas previas "
                             f"de esa semana: {e}"}

    # 2) Construir las filas nuevas (una por jugador). Orden DEBE coincidir
    #    con CABECERA_HISTORICO.
    # Los numericos los enviamos como string con COMA decimal (locale ES)
    # para que el Sheet (que esta en espanol) los interprete sin ambiguedad.
    # Si los enviamos como float con punto, hemos visto que el Sheet los
    # guarda como enteros mal (0.48 -> 48). Asi se evita ese fallo.
    def _num_es(valor, decimales):
        v = round(safe_float(valor), decimales)
        return f"{v:.{decimales}f}".replace(".", ",")

    filas = []
    for datos in jugadores.values():
        filas.append([
            fecha_sabado,
            datos.get("nombre_original", "?"),
            _num_es(datos.get("PR", 0), 2),
            _num_es(datos.get("lam_180", 0), 3),
            _num_es(datos.get("lam_legs", 0), 3),
            _num_es(datos.get("promedio_dardos", 0), 2),
            _num_es(datos.get("checkouts", 0), 2),
            _num_es(datos.get("pct_victorias", 0), 2),
            _num_es(datos.get("volatilidad", 0), 2),
            int(safe_float(datos.get("victorias", 0))),
            int(safe_float(datos.get("derrotas", 0))),
            int(safe_float(datos.get("n_partidos", 0))),
        ])

    # 3) Escribir en lote — USER_ENTERED para que el Sheet interprete las
    # comas decimales correctamente segun su locale.
    try:
        hoja.append_rows(filas, value_input_option="USER_ENTERED")
    except Exception as e:
        return {"ok": False, "fecha": fecha_sabado, "guardados": 0,
                "sobrescrita": sobrescrita,
                "error": f"Error escribiendo el historico: {e}"}

    return {"ok": True, "fecha": fecha_sabado, "guardados": len(filas),
            "sobrescrita": sobrescrita, "error": ""}


@st.cache_data(ttl=120, show_spinner=False)
def cargar_historico():
    """Lee la pestana 'Historico' del Sheet de predicciones.

    Devuelve un DataFrame de pandas con todas las filas guardadas (una por
    jugador y semana). DataFrame vacio si no hay datos o falla la conexion.
    Cacheado 2 minutos.

    IMPORTANTE: usamos get_all_values() en vez de get_all_records() porque
    este ultimo hace conversiones automaticas a numero que pierden la coma
    decimal con locale espanol (0,48 -> 48). Con get_all_values() todo viene
    como string literal y nosotros lo convertimos bien con safe_float
    (que sustituye ',' por '.').
    """
    hoja, err = _abrir_hoja_historico()
    if hoja is None:
        return pd.DataFrame()
    try:
        valores = hoja.get_all_values()
    except Exception:
        return pd.DataFrame()
    if not valores or len(valores) < 2:
        return pd.DataFrame()

    cabecera = valores[0]
    filas = valores[1:]
    # Filtrar filas vacias (todas las celdas en blanco)
    filas = [r for r in filas if any(str(x).strip() for x in r)]
    if not filas:
        return pd.DataFrame()
    df = pd.DataFrame(filas, columns=cabecera)

    def _rescatar(valor, maximo_razonable):
        """Convierte un valor a float aplicando rescate de coma decimal.

        Si el valor numerico supera el maximo razonable de esa metrica,
        se divide por 10, 100, 1000... hasta caer dentro del rango. Si
        no se puede convertir, devuelve 0.0.
        """
        try:
            x = float(str(valor).strip().replace(",", "."))
        except Exception:
            return 0.0
        # Si ya esta en rango razonable, no tocar
        if abs(x) <= maximo_razonable:
            return x
        # Dividir progresivamente hasta caer en rango
        for divisor in (10.0, 100.0, 1000.0, 10000.0):
            candidato = x / divisor
            if abs(candidato) <= maximo_razonable:
                return candidato
        return 0.0

    # Rangos maximos razonables de cada metrica (con margen).
    # Si el numero leido excede el maximo, se asume coma perdida.
    rangos = {
        "PR": 100.0,              # PR real: 50-80
        "Media 180s": 5.0,        # por partido: 0-3
        "Legs por partido": 10.0, # por partido: 4-7 normalmente
        "Promedio dardos": 120.0, # 70-110
        "Checkout %": 100.0,      # 0-100
        "% Victorias": 100.0,     # 0-100
        "Volatilidad": 50.0,      # 5-20
    }
    for col, maximo in rangos.items():
        if col in df.columns:
            df[col] = df[col].apply(lambda v: _rescatar(v, maximo))

    # Enteros (no tienen coma decimal): victorias, derrotas, partidos
    for col in ("Victorias", "Derrotas", "Partidos jugados"):
        if col in df.columns:
            df[col] = df[col].apply(safe_float)

    return df


# ─────────────────────────────────────────────────────────────────────────────
# LOG DE AUTO-REGISTRO
# ─────────────────────────────────────────────────────────────────────────────

NOMBRE_HOJA_LOG_AUTO = "Log Auto Registro"

CABECERA_LOG_AUTO = [
    "Timestamp", "Jornada", "Partidos registrados",
    "Partidos saltados", "Estado", "Detalles",
]


def _abrir_hoja_log_auto():
    """Abre (o crea) la pestana 'Log Auto Registro' del Sheet de
    predicciones. Mismo patron que las otras hojas.
    """
    cliente, err = _conectar_gsheets()
    if cliente is None:
        return None, err
    try:
        libro = cliente.open_by_key(SHEET_ID_PREDICCIONES)
    except Exception as e:
        return None, f"No se pudo abrir el Sheet ({type(e).__name__}: {e})."
    try:
        hoja = libro.worksheet(NOMBRE_HOJA_LOG_AUTO)
    except Exception:
        try:
            hoja = libro.add_worksheet(
                title=NOMBRE_HOJA_LOG_AUTO,
                rows=5000,
                cols=len(CABECERA_LOG_AUTO),
            )
            hoja.append_row(CABECERA_LOG_AUTO)
        except Exception as e:
            return None, (
                f"No se pudo crear '{NOMBRE_HOJA_LOG_AUTO}' ({e})."
            )
    # Garantizar cabecera
    try:
        if not hoja.row_values(1):
            hoja.append_row(CABECERA_LOG_AUTO)
    except Exception:
        pass
    return hoja, ""


def escribir_log_auto(jornada, partidos_registrados, partidos_saltados,
                       estado, detalles):
    """Apunta una fila en la pestana 'Log Auto Registro'.

    Parametros:
      jornada:             nombre de la jornada (ej. 'Grupo A Martes')
      partidos_registrados: lista de strings "J1 vs J2"
      partidos_saltados:   lista de strings "J1 vs J2 (motivo)"
      estado:              "OK", "PARCIAL", "ERROR" o "NADA"
      detalles:            texto libre con info adicional
    """
    hoja, err = _abrir_hoja_log_auto()
    if hoja is None:
        return False, err
    try:
        from zoneinfo import ZoneInfo
        ts = datetime.now(ZoneInfo("Europe/Madrid")).strftime(
            "%Y-%m-%d %H:%M:%S")
    except Exception:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fila = [
        ts,
        jornada or "",
        " | ".join(partidos_registrados) if partidos_registrados else "",
        " | ".join(partidos_saltados) if partidos_saltados else "",
        estado,
        detalles or "",
    ]
    try:
        hoja.append_row(fila, value_input_option="USER_ENTERED")
        return True, ""
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# CAMPEONES DE LA SEMANA
# ─────────────────────────────────────────────────────────────────────────────

def _abrir_hoja_campeones():
    """Abre (o crea) la pestana 'Campeones'. Devuelve (worksheet, error)."""
    cliente, err = _conectar_gsheets()
    if cliente is None:
        return None, err
    try:
        libro = cliente.open_by_key(SHEET_ID_PREDICCIONES)
    except Exception as e:
        return None, f"No se pudo abrir el Sheet ({type(e).__name__}: {e})."
    try:
        hoja = libro.worksheet(NOMBRE_HOJA_CAMPEONES)
    except Exception:
        try:
            hoja = libro.add_worksheet(
                title=NOMBRE_HOJA_CAMPEONES, rows=1000,
                cols=len(CABECERA_CAMPEONES))
            hoja.append_row(CABECERA_CAMPEONES)
        except Exception as e:
            return None, (
                f"No se pudo crear la pestana '{NOMBRE_HOJA_CAMPEONES}' ({e}).")
    try:
        if not hoja.row_values(1):
            hoja.append_row(CABECERA_CAMPEONES)
    except Exception:
        pass
    return hoja, ""


def guardar_campeon_semana(campeon, fecha_sabado=None):
    """Anade el campeon de la semana a la pestana 'Campeones'.

    Si ya existe una fila con esa misma fecha de sabado, la sobrescribe
    (para no duplicar si el cierre se ejecuta dos veces).

    Devuelve dict {ok, fecha, campeon, error}.
    """
    if not campeon:
        return {"ok": False, "error": "campeon vacio", "fecha": "", "campeon": ""}

    if fecha_sabado is None:
        fecha_sabado = _fecha_sabado_de_la_semana()

    hoja, err = _abrir_hoja_campeones()
    if hoja is None:
        return {"ok": False, "error": err, "fecha": fecha_sabado, "campeon": campeon}

    try:
        valores = hoja.get_all_values()
    except Exception as e:
        return {"ok": False, "error": f"No se pudo leer: {e}",
                "fecha": fecha_sabado, "campeon": campeon}

    # ¿Ya existe esa fecha? (saltando cabecera)
    fila_existente = None
    for idx, fila in enumerate(valores[1:], start=2):
        if fila and fila[0].strip() == fecha_sabado:
            fila_existente = idx
            break

    try:
        if fila_existente:
            hoja.update(f"A{fila_existente}:B{fila_existente}",
                        [[fecha_sabado, campeon]])
        else:
            hoja.append_row([fecha_sabado, campeon])
    except Exception as e:
        return {"ok": False, "error": f"No se pudo escribir: {e}",
                "fecha": fecha_sabado, "campeon": campeon}

    return {"ok": True, "error": "", "fecha": fecha_sabado, "campeon": campeon}


def cargar_campeones():
    """Lee la pestana 'Campeones' y devuelve lista de dicts
    [{fecha, campeon}, ...], mas reciente primero. Lista vacia si no hay."""
    hoja, err = _abrir_hoja_campeones()
    if hoja is None:
        return []
    try:
        valores = hoja.get_all_values()
    except Exception:
        return []
    filas = valores[1:] if len(valores) > 1 else []
    out = []
    for fila in filas:
        if len(fila) >= 2 and fila[0].strip() and fila[1].strip():
            out.append({"fecha": fila[0].strip(), "campeon": fila[1].strip()})
    out.reverse()  # mas reciente primero
    return out
