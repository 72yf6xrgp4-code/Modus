"""
helpers.py - Funciones de utilidad de bajo nivel y sin estado pesado.

Conversiones numericas seguras, asignacion de colores a jugadores, estilo de
tablas, busqueda difusa de nombres, calculo de tendencias y yield, etc.

Depende solo de: config. Es una capa base que importan casi todos los modulos.
"""

import streamlit as st
import pandas as pd
import numpy as np
from difflib import SequenceMatcher

from config import PALETA_JUGADORES, BANDERAS, JUGADORES_PAISES

def obtener_color_jugador(nombre):
    """Devuelve un color de fondo único para un jugador.
    
    Estrategia: asignación secuencial sin colisiones. La primera vez que se
    ve un jugador se le asigna el siguiente color libre de la paleta y se
    guarda en st.session_state['colores_jugadores']. En llamadas posteriores
    devuelve el color ya asignado.
    
    Los nombres se normalizan (lowercase + strip) para que pequeñas variaciones
    como espacios extra o capitalización no rompan la asignación.
    
    Si se agota la paleta (más de 18 jugadores únicos), cae a un esquema cíclico.
    Devuelve None para nombres vacíos / inválidos.
    """
    if not nombre:
        return None
    nombre_str = str(nombre).strip()
    if not nombre_str or nombre_str.lower() in ('nan', ''):
        return None
    nombre_norm = nombre_str.lower()
    
    # Inicializar el mapa en session_state si no existe
    if 'colores_jugadores' not in st.session_state:
        st.session_state['colores_jugadores'] = {}
    
    mapa = st.session_state['colores_jugadores']
    
    if nombre_norm in mapa:
        return mapa[nombre_norm]
    
    # Asignar siguiente color libre
    idx = len(mapa) % len(PALETA_JUGADORES)
    color = PALETA_JUGADORES[idx]
    mapa[nombre_norm] = color
    return color

def pintar_partidos(fila):
    """Aplica dos capas de estilo a la tabla de detalles de partidos:
    
    - Cada par de filas (un partido) alterna fondo gris suave/transparente
      para hacer visualmente bloque.
    - La PRIMERA celda (nombre del jugador) se pinta con el color único que
      le corresponde por nombre, en negrita y con texto oscuro para contraste.
    
    Si la primera celda no tiene un nombre válido, se pinta como el resto.
    """
    nombre_jugador = str(fila.iloc[0]).strip() if len(fila) > 0 else ""
    color_jugador = obtener_color_jugador(nombre_jugador)
    
    # Fondo alternado por partido (cada par de filas)
    es_par = (fila.name // 2) % 2 == 0
    fondo_fila = 'rgba(150, 150, 150, 0.15)' if es_par else 'transparent'
    
    estilos = []
    for i in range(len(fila)):
        if i == 0 and color_jugador:
            # Celda del nombre: color del jugador con texto oscuro y negrita
            estilos.append(
                f'background-color: {color_jugador}; '
                f'color: #1a1a1a; font-weight: 700;'
            )
        else:
            estilos.append(f'background-color: {fondo_fila};')
    return estilos

def obtener_bandera(nombre_jugador):
    nombre_lower = nombre_jugador.lower().strip().replace("_", " ")
    codigo_pais = JUGADORES_PAISES.get(nombre_lower, None)
    if codigo_pais and codigo_pais in BANDERAS:
        return BANDERAS[codigo_pais]
    return None

def calcular_tendencia(valor_actual, valor_semanal, etiqueta):
    """Calcula tendencia con reglas específicas: 5% general, 3% para Puntuación Global.
    
    Soporta valores con coma decimal (formato europeo: 5,6 → 5.6) y porcentaje.
    Excluye Número de Victorias/Derrotas (contadores absolutos), pero SÍ aplica
    a Porcentaje Victoria (valor relativo).
    """
    try:
        # Limpiar formato europeo (coma decimal) y símbolo de porcentaje
        val_act = float(str(valor_actual).replace('%', '').replace(',', '.').strip())
        val_sem = float(str(valor_semanal).replace('%', '').replace(',', '.').strip())
    except:
        return "", valor_actual, ""
    
    # Excluir solo los conteos absolutos de Victorias/Derrotas
    # (Porcentaje Victoria sí debe mostrar tendencia)
    etiqueta_lower = etiqueta.lower()
    es_conteo_vic_der = (
        ("victoria" in etiqueta_lower or "derrota" in etiqueta_lower)
        and "porcentaje" not in etiqueta_lower
        and "%" not in etiqueta_lower
    )
    if es_conteo_vic_der:
        return "", valor_actual, ""
    
    # Calcular porcentaje de cambio
    if val_sem == 0:
        porcentaje_cambio = 0
    else:
        porcentaje_cambio = ((val_act - val_sem) / abs(val_sem)) * 100
    
    # Umbral diferente para Puntuación Global
    umbral = 3 if "puntiación" in etiqueta_lower else 5
    
    # Formato del valor de referencia con coma decimal (estilo español)
    comparativa = f"({val_sem:.1f})".replace(".", ",")
    
    # Mostrar indicador solo si supera el umbral
    if abs(porcentaje_cambio) >= umbral:
        if porcentaje_cambio > 0:
            indicador = "🟢 ↑"
        else:
            indicador = "🔴 ↓"
        return indicador, valor_actual, comparativa
    else:
        return "", valor_actual, comparativa


def safe_float(val, default=0.0):
    try:
        v = float(str(val).replace(',', '.').strip())
        if not np.isfinite(v):
            return default
        return v
    except:
        return default

def color_volatilidad(valor):
    """Devuelve la paleta de colores (borde, valor, fondo, texto_riesgo, etiqueta_riesgo)
    según el índice de volatilidad, midiendo la irregularidad/riesgo del rendimiento:

        - Verde   si valor < 8    → RIESGO BAJO (rendimiento estable)
        - Amarillo si 8 ≤ v ≤ 12  → RIESGO MEDIO (rendimiento algo irregular)
        - Rojo    si valor > 12   → RIESGO ALTO (rendimiento muy irregular)

    Umbrales alineados con el formato condicional de la hoja de cálculo.

    Acepta tanto strings con coma decimal española ("18,02") como números.
    Si el valor no es parseable, es NaN o es 0 (jugador sin datos), devuelve
    una paleta neutra en gris sin etiqueta de riesgo.
    """
    paleta_neutra = {
        "borde": "#9ca3af", "valor": "#6b7280",
        "bg": "rgba(156, 163, 175, 0.08)",
        "riesgo_texto": "#6b7280", "riesgo_bg": "rgba(156, 163, 175, 0.15)",
        "riesgo_label": ""
    }
    try:
        v = float(str(valor).replace('%', '').replace(',', '.').strip())
    except:
        return paleta_neutra
    # NaN o jugador sin datos (valor 0 exacto): paleta neutra sin etiqueta
    if not np.isfinite(v) or v == 0:
        return paleta_neutra
    if v < 8:
        return {
            "borde": "#22c55e", "valor": "#16a34a",
            "bg": "rgba(34, 197, 94, 0.10)",
            "riesgo_texto": "#15803d", "riesgo_bg": "rgba(34, 197, 94, 0.18)",
            "riesgo_label": "RIESGO BAJO"
        }
    elif v <= 12:
        return {
            "borde": "#eab308", "valor": "#ca8a04",
            "bg": "rgba(234, 179, 8, 0.12)",
            "riesgo_texto": "#854d0e", "riesgo_bg": "rgba(234, 179, 8, 0.22)",
            "riesgo_label": "RIESGO MEDIO"
        }
    else:
        return {
            "borde": "#dc2626", "valor": "#dc2626",
            "bg": "rgba(220, 38, 38, 0.10)",
            "riesgo_texto": "#991b1b", "riesgo_bg": "rgba(220, 38, 38, 0.18)",
            "riesgo_label": "RIESGO ALTO"
        }

def sanitize_prob(p):
    if not np.isfinite(p) or p <= 0:
        return 0.0001
    if p >= 1:
        return 0.9999
    return max(0.0001, min(0.9999, p))

def pct(p):
    return f"{p * 100:.1f}%"

def calcular_yield(prob, cuota_bookie):
    return (prob * cuota_bookie) - 1

def margen_mercado(mercado=None):
    """Margen de seguridad del value para un mercado (por la key de su
    casilla de cuota: 'vic_j1', 'legs_mas', '180_j1_05'...). Si no se
    reconoce, el general MARGEN_VALUE."""
    from config import MARGEN_VALUE, MARGEN_POR_MERCADO
    if mercado:
        for prefijo, m in MARGEN_POR_MERCADO.items():
            if str(mercado).startswith(prefijo):
                return m
    return MARGEN_VALUE


def es_value(y, cuota, margen=None, mercado=None):
    """True si la apuesta es value con margen de seguridad.

    y = prob * cuota - 1. Exigir prob >= 1/cuota + margen equivale a
    y >= margen * cuota (a cuota alta hace falta mas yield, porque un error
    de unos puntos en la probabilidad pesa mas). El margen depende del
    mercado (MARGEN_POR_MERCADO en config.py).
    """
    m = margen_mercado(mercado) if margen is None else margen
    if y is None or not cuota:
        return False
    # 1e-9: que justo en el limite (p. ej. 58 % a cuota 2,00 con margen 8)
    # cuente como value pese al redondeo de los decimales
    return y > 0 and y >= m * cuota - 1e-9


def icono_yield(y, cuota, mercado=None):
    """🟢 value con margen · 🟡 yield positivo pero dentro del margen
    (no fiable) · ⚪ neutro · 🔴 claramente negativo."""
    if es_value(y, cuota, mercado=mercado):
        return "🟢"
    if y > 0:
        return "🟡"
    return "🔴" if y < -0.05 else "⚪"


def badge_yield(y):
    if y > 0:
        return f"✅ +{y*100:.1f}%"
    elif y < -0.05:
        return f"❌ {y*100:.1f}%"
    else:
        return f"➖ {y*100:.1f}%"

def _buscar_stat(stats_dict, keywords):
    for k, v in stats_dict.items():
        if any(kw in k.lower() for kw in keywords):
            return v
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# FECHAS DEL TORNEO (hora de Madrid)
# ─────────────────────────────────────────────────────────────────────────────

def ahora_madrid():
    """Fecha y hora actual en Europe/Madrid (el servidor de Streamlit Cloud y
    GitHub Actions van en UTC)."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Madrid"))
    except Exception:
        return datetime.now()


def fecha_jornada_madrid(ahora=None):
    """Dia 'de jornada' en formato YYYY-MM-DD.

    Es la fecha de Madrid, salvo de 00:00 a 03:00, que cuenta como el dia
    anterior: la sesion nocturna del Grupo B (y el final del sabado) se
    alarga pasada la medianoche. Asi un partido registrado a las 23:50 y
    vuelto a registrar a las 00:10 mantiene el mismo ID y no se duplica.
    """
    from datetime import timedelta
    ahora = ahora or ahora_madrid()
    if ahora.hour * 60 + ahora.minute <= 3 * 60:
        ahora = ahora - timedelta(days=1)
    return ahora.strftime("%Y-%m-%d")


def inicio_semana_torneo(ahora=None):
    """Lunes a las 03:00 (Madrid) de la semana de torneo en curso. Lo que
    ocurre antes pertenece a la semana anterior (el domingo de madrugada
    aun se cierra la Final del sabado)."""
    from datetime import timedelta
    ahora = ahora or ahora_madrid()
    lunes = (ahora - timedelta(days=ahora.weekday())).replace(
        hour=3, minute=0, second=0, microsecond=0)
    if ahora < lunes:
        lunes -= timedelta(days=7)
    return lunes


# ─────────────────────────────────────────────────────────────────────────────
# MODO ADMINISTRADOR
# ─────────────────────────────────────────────────────────────────────────────
# Las acciones que escriben en el Google Sheet o lanzan el script (Registrar,
# Verificar, Guardar historico, Ejecutar actualizacion) solo se muestran a
# quien escriba la clave ADMIN_CLAVE de los secrets de Streamlit. Si el
# secreto no esta configurado, todo sigue visible como antes.

def clave_admin_configurada():
    try:
        return bool(st.secrets.get("ADMIN_CLAVE", ""))
    except Exception:
        return False


def es_admin():
    if not clave_admin_configurada():
        return True
    return bool(st.session_state.get("admin_ok", False))


def render_acceso_admin():
    """Casilla de clave en la barra lateral (solo si hay ADMIN_CLAVE)."""
    if not clave_admin_configurada():
        return
    import hmac
    if st.session_state.get("admin_ok"):
        st.sidebar.caption("🔓 Modo administrador activo")
        if st.sidebar.button("Salir del modo administrador", key="admin_salir"):
            st.session_state["admin_ok"] = False
            st.rerun()
        return
    clave = st.sidebar.text_input("🔒 Clave de administrador", type="password",
                                  key="admin_clave_in")
    if clave:
        if hmac.compare_digest(clave, str(st.secrets.get("ADMIN_CLAVE", ""))):
            st.session_state["admin_ok"] = True
            st.rerun()
        else:
            st.sidebar.error("Clave incorrecta")


def buscar_jugador(nombre, db):
    nombre_lower = nombre.strip().lower()
    if nombre_lower in db:
        return db[nombre_lower]
    for k, v in db.items():
        if nombre_lower in k or k in nombre_lower:
            return v
    return None
