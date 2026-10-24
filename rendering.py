"""
rendering.py - Funciones de renderizado visual de la interfaz Streamlit.

Pentagonos de habilidades, tarjetas de estadisticas de jugador, barras
comparativas, heatmaps, radares y la vista completa de Value Bets.

Depende de: config, helpers, data_loading, stats_engine.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

from config import URLS, CORTES, PESTANAS_CON_STATS, MUESTRA_MIN_PARTIDOS, MARGEN_VALUE
from helpers import (
    safe_float, color_volatilidad, calcular_tendencia, sanitize_prob,
    buscar_jugador, calcular_yield, pct, badge_yield, obtener_bandera,
    es_admin, fecha_jornada_madrid, es_value, icono_yield,
)
from data_loading import (
    cargar_todo, cargar_jugadores_desde,
    obtener_proximos_partidos_csv,
    cargar_forma_reciente, detectar_jornada_de_hoy, jornada_mas_reciente,
)
from stats_engine import (
    prob_victoria, prob_180s, quien_hace_mas_180s, handicaps_legs,
    legs_totales, prob_a_cuota, extraer_h2h_semanal, obtener_ultimos_partidos,
    _extraer_metricas_jugadores, simular_match,
    pocos_partidos,
)

# El modulo de seguimiento de predicciones es OPCIONAL: si falta el archivo
# o alguna de sus dependencias (gspread, google-auth), la app debe seguir
# funcionando con normalidad y solo se desactiva la seccion de tracking.
try:
    from predicciones import (
        registrar_predicciones, cargar_predicciones, calcular_metricas,
        tracking_disponible, diagnostico_conexion, verificar_resultados,
        listar_partidos_registrados, comprobar_partidos_anteriores,
        guardar_historico_semana, cargar_historico,
        quitar_handicaps_duplicados, limpiar_predicciones,
        archivar_caducadas,
    )
    _PREDICCIONES_OK = True
    _PREDICCIONES_ERROR = ""
except Exception as _e:
    _PREDICCIONES_OK = False
    _PREDICCIONES_ERROR = f"{type(_e).__name__}: {_e}"
    registrar_predicciones = None
    cargar_predicciones = None
    calcular_metricas = None
    tracking_disponible = None
    diagnostico_conexion = None
    verificar_resultados = None
    listar_partidos_registrados = None
    comprobar_partidos_anteriores = None
    guardar_historico_semana = None
    cargar_historico = None
    quitar_handicaps_duplicados = lambda df: df
    limpiar_predicciones = lambda df: df
    archivar_caducadas = None

def render_barras_enfrentadas(j1_nombre, j1_prob, j2_nombre, j2_prob, j1_color="#1f77b4", j2_color="#ff7f0e"):
    total = j1_prob + j2_prob
    if total == 0:
        j1_prob = j2_prob = 0.5
    j1_pct = (j1_prob / total * 100) if total > 0 else 50
    j2_pct = (j2_prob / total * 100) if total > 0 else 50
    st.markdown(f"""
    <div style="margin: 20px 0;">
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 10px;">
            <div style="flex: 0 0 25%; text-align: right;">
                <p style="margin: 0; font-weight: bold; font-size: 1.1em; color: {j1_color};">{j1_nombre}</p>
                <p style="margin: 5px 0 0 0; font-size: 1.3em; font-weight: bold; color: {j1_color};">{j1_pct:.1f}%</p>
            </div>
            <div style="flex: 1;">
                <div style="display: flex; height: 45px; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                    <div style="width: {j1_pct}%; background: linear-gradient(90deg, {j1_color}, {j1_color}dd); display: flex; align-items: center; justify-content: flex-end; padding-right: 10px;">
                        <span style="color: white; font-weight: bold; font-size: 0.9em;">{j1_prob*100:.1f}%</span>
                    </div>
                    <div style="width: {j2_pct}%; background: linear-gradient(90deg, {j2_color}dd, {j2_color}); display: flex; align-items: center; justify-content: flex-start; padding-left: 10px;">
                        <span style="color: white; font-weight: bold; font-size: 0.9em;">{j2_prob*100:.1f}%</span>
                    </div>
                </div>
            </div>
            <div style="flex: 0 0 25%; text-align: left;">
                <p style="margin: 0; font-weight: bold; font-size: 1.1em; color: {j2_color};">{j2_nombre}</p>
                <p style="margin: 5px 0 0 0; font-size: 1.3em; font-weight: bold; color: {j2_color};">{j2_pct:.1f}%</p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def mostrar_cuota_justa(cuota):
    st.caption(f"💡 Cuota justa: **{cuota:.2f}**")

def render_mas_180s_barras(j1_nombre, p_j1, j2_nombre, p_j2, p_emp, j1_color="#1f77b4", j2_color="#ff7f0e"):
    p_j1 = sanitize_prob(p_j1)
    p_j2 = sanitize_prob(p_j2)
    p_emp = sanitize_prob(p_emp)
    total = p_j1 + p_emp + p_j2
    if total <= 0:
        total = 1.0
    pct_j1 = (p_j1 / total * 100)
    pct_emp = (p_emp / total * 100)
    pct_j2 = (p_j2 / total * 100)
    html_str = f"""
    <div style="margin: 20px 0;">
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 10px;">
            <div style="flex: 0 0 20%; text-align: right;">
                <p style="margin: 0; font-weight: bold; font-size: 0.95em; color: {j1_color};">{j1_nombre}</p>
                <p style="margin: 5px 0 0 0; font-size: 1.1em; font-weight: bold; color: {j1_color};">{pct_j1:.1f}%</p>
            </div>
            <div style="flex: 1;">
                <div style="display: flex; height: 45px; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                    <div style="width: {pct_j1}%; background: linear-gradient(90deg, {j1_color}, {j1_color}dd); display: flex; align-items: center; justify-content: flex-end; padding-right: 8px;">
                        <span style="color: white; font-weight: bold; font-size: 0.8em;">{p_j1*100:.1f}%</span>
                    </div>
                    <div style="width: {pct_emp}%; background: linear-gradient(90deg, #999, #777); display: flex; align-items: center; justify-content: center;">
                        <span style="color: white; font-weight: bold; font-size: 0.8em;">{p_emp*100:.1f}%</span>
                    </div>
                    <div style="width: {pct_j2}%; background: linear-gradient(90deg, {j2_color}dd, {j2_color}); display: flex; align-items: center; justify-content: flex-start; padding-left: 8px;">
                        <span style="color: white; font-weight: bold; font-size: 0.8em;">{p_j2*100:.1f}%</span>
                    </div>
                </div>
            </div>
            <div style="flex: 0 0 20%; text-align: left;">
                <p style="margin: 0; font-weight: bold; font-size: 0.95em; color: {j2_color};">{j2_nombre}</p>
                <p style="margin: 5px 0 0 0; font-size: 1.1em; font-weight: bold; color: {j2_color};">{pct_j2:.1f}%</p>
            </div>
        </div>
    </div>
    """
    st.markdown(html_str, unsafe_allow_html=True)

def render_pentagono_svg(pr, lam_180, promedio_dardos, checkouts, pct_vic, color="#1f77b4"):
    """Renderiza solo el SVG del pentágono sin los datos."""
    
    # Normalizar valores entre 0-100
    pr_norm = min(100, max(0, pr))
    lam_180_norm = min(100, max(0, (lam_180 / 3.0) * 100))
    promedio_dardos_norm = min(100, max(0, (promedio_dardos / 100) * 100))
    checkouts_norm = min(100, max(0, checkouts))
    pct_vic_norm = min(100, max(0, pct_vic))
    
    values = [pr_norm, lam_180_norm, promedio_dardos_norm, checkouts_norm, pct_vic_norm]
    labels = ["Power", "λ 180s", "Ø Dardos", "Checkout", "% Vic"]
    
    # SVG centrado perfecto
    svg_size = 340
    center_x, center_y = svg_size / 2, svg_size / 2
    radius = 90
    angle_offset = -90
    
    # Calcular puntos del pentágono base
    points = []
    label_pos = []
    for i in range(5):
        angle = angle_offset + (i * 72)
        rad = np.radians(angle)
        
        x = center_x + radius * np.cos(rad)
        y = center_y + radius * np.sin(rad)
        points.append((x, y))
        
        label_radius = radius + 30
        lx = center_x + label_radius * np.cos(rad)
        ly = center_y + label_radius * np.sin(rad)
        label_pos.append((lx, ly))
    
    # Calcular puntos de datos
    data_points = []
    for i in range(5):
        angle = angle_offset + (i * 72)
        rad = np.radians(angle)
        data_radius = (values[i] / 100) * radius
        x = center_x + data_radius * np.cos(rad)
        y = center_y + data_radius * np.sin(rad)
        data_points.append((x, y))
    
    svg_parts = []
    svg_parts.append(f'<svg width="{svg_size}" height="{svg_size}" xmlns="http://www.w3.org/2000/svg">')
    svg_parts.append(f'<rect width="{svg_size}" height="{svg_size}" fill="white"/>')
    
    # Círculos de referencia
    for r_pct in [25, 50, 75, 100]:
        r = (r_pct / 100) * radius
        svg_parts.append(f'<circle cx="{center_x}" cy="{center_y}" r="{r}" fill="none" stroke="rgba(200,200,200,0.25)" stroke-width="0.8"/>')
    
    # Líneas radiales
    for point in points:
        svg_parts.append(f'<line x1="{center_x}" y1="{center_y}" x2="{point[0]}" y2="{point[1]}" stroke="rgba(200,200,200,0.15)" stroke-width="0.8"/>')
    
    # Pentágono base
    pentagon_path = "M " + " L ".join([f"{p[0]},{p[1]}" for p in points]) + " Z"
    svg_parts.append(f'<path d="{pentagon_path}" fill="none" stroke="rgba(150,150,150,0.2)" stroke-width="1"/>')
    
    # Área de datos
    data_path = "M " + " L ".join([f"{p[0]},{p[1]}" for p in data_points]) + " Z"
    rgb_color = color.lstrip('#')
    rgb_tuple = tuple(int(rgb_color[i:i+2], 16) for i in (0, 2, 4))
    svg_parts.append(f'<path d="{data_path}" fill="rgba({rgb_tuple[0]},{rgb_tuple[1]},{rgb_tuple[2]},0.15)" stroke="{color}" stroke-width="2.5"/>')
    
    # Puntos de datos
    for point in data_points:
        svg_parts.append(f'<circle cx="{point[0]}" cy="{point[1]}" r="3.5" fill="{color}" stroke="white" stroke-width="1.5"/>')
    
    # Etiquetas
    for i, (x, y) in enumerate(label_pos):
        svg_parts.append(f'<text x="{x}" y="{y}" text-anchor="middle" dominant-baseline="middle" font-size="9" font-family="Arial" fill="#666" font-weight="500">{labels[i]}</text>')
    
    svg_parts.append('</svg>')
    
    return "\n".join(svg_parts)

def render_pentagono_habilidades(pr, lam_180, promedio_dardos, checkouts, pct_vic, color="#1f77b4"):
    """Renderiza pentágono con datos debajo."""
    
    valores_display = [f"{pr:.1f}", f"{lam_180:.2f}", f"{promedio_dardos:.1f}", f"{checkouts:.0f}%", f"{pct_vic:.0f}%"]
    svg_html = render_pentagono_svg(pr, lam_180, promedio_dardos, checkouts, pct_vic, color)
    
    rgb_color = color.lstrip('#')
    rgb_tuple = tuple(int(rgb_color[i:i+2], 16) for i in (0, 2, 4))
    
    # HTML para los datos debajo del pentágono
    html_datos = f"""
    <div style="margin-top: 10px;">
        {svg_html}
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1fr; gap: 8px; margin-top: 20px; text-align: center;">
            <div style="background: rgba({rgb_tuple[0]},{rgb_tuple[1]},{rgb_tuple[2]},0.1); padding: 8px; border-radius: 6px; border-left: 3px solid {color};">
                <p style="margin: 0; font-size: 11px; color: #666;">Power</p>
                <p style="margin: 3px 0 0 0; font-size: 13px; font-weight: bold; color: {color};">{valores_display[0]}</p>
            </div>
            <div style="background: rgba({rgb_tuple[0]},{rgb_tuple[1]},{rgb_tuple[2]},0.1); padding: 8px; border-radius: 6px; border-left: 3px solid {color};">
                <p style="margin: 0; font-size: 11px; color: #666;">λ 180s</p>
                <p style="margin: 3px 0 0 0; font-size: 13px; font-weight: bold; color: {color};">{valores_display[1]}</p>
            </div>
            <div style="background: rgba({rgb_tuple[0]},{rgb_tuple[1]},{rgb_tuple[2]},0.1); padding: 8px; border-radius: 6px; border-left: 3px solid {color};">
                <p style="margin: 0; font-size: 11px; color: #666;">Ø Dardos</p>
                <p style="margin: 3px 0 0 0; font-size: 13px; font-weight: bold; color: {color};">{valores_display[2]}</p>
            </div>
            <div style="background: rgba({rgb_tuple[0]},{rgb_tuple[1]},{rgb_tuple[2]},0.1); padding: 8px; border-radius: 6px; border-left: 3px solid {color};">
                <p style="margin: 0; font-size: 11px; color: #666;">Checkout</p>
                <p style="margin: 3px 0 0 0; font-size: 13px; font-weight: bold; color: {color};">{valores_display[3]}</p>
            </div>
            <div style="background: rgba({rgb_tuple[0]},{rgb_tuple[1]},{rgb_tuple[2]},0.1); padding: 8px; border-radius: 6px; border-left: 3px solid {color};">
                <p style="margin: 0; font-size: 11px; color: #666;">% Vic</p>
                <p style="margin: 3px 0 0 0; font-size: 13px; font-weight: bold; color: {color};">{valores_display[4]}</p>
            </div>
        </div>
    </div>
    """
    
    return html_datos

def render_jugador_visual(player, stats, stats_resumen, selected, mostrar_tendencias=True, mostrar_racha=False, jornada_racha=None):
    """Renderiza un jugador con 9 estadísticas en un layout simétrico:
    
        ┌─────────────────────────────────────────────┐
        │       ⭐ PUNTUACIÓN GLOBAL (destacada)        │   ← fila completa
        └─────────────────────────────────────────────┘
        ┌──────────┬──────────┬──────────┬──────────┐
        │ Media 180│ Promedio │   Legs   │ Checkout │   ← fila 1 del grid
        ├──────────┼──────────┼──────────┼──────────┤
        │ Victorias│ Derrotas │ % Victor.│Volatilid.│   ← fila 2 del grid
        └──────────┴──────────┴──────────┴──────────┘
    
    Puntuación Global se destaca en la parte superior con borde grueso dorado,
    fondo degradado y tamaño tipográfico mayor — refleja su importancia como
    métrica clave compuesta.
    
    El Índice de Volatilidad se colorea según el riesgo:
        - Verde (< 8)      → riesgo bajo (rendimiento estable)
        - Amarillo (8-12)  → riesgo medio
        - Rojo (> 12)      → riesgo alto (rendimiento irregular)
    
    Colores estándar: azul por defecto, verde victorias, rojo derrotas, dorado
    puntuación global, traffic-light para volatilidad.
    
    Sistema de sinónimos: cada etiqueta tiene varias formas posibles para que
    funcione tanto con las jornadas diarias (etiquetas largas) como con el
    Resumen Semanal (etiquetas más cortas).
    """
    
    # Configuración: (etiqueta_display, icono, sinónimos_de_más_específico_a_más_genérico)
    # Orden:
    #   - Puntuación Global primero (se renderiza destacada arriba)
    #   - Luego las 8 restantes en grid 2×4
    config_stats = [
        ("Puntuación Global", "⭐",
         ["puntiación global", "puntuación global", "puntacion global", "puntiación", "puntuación", "puntacion"]),
        ("Media 180 por partida", "🎯",
         ["media 180 por partida", "180 por partida", "180 por partido", "media 180", "media de 180"]),
        ("Promedio puntos total", "📊",
         ["promedio puntos total", "promedio puntos", "media puntos", "puntos total", "promedio dardos", "average"]),
        ("Legs por partido", "🎮",
         ["legs totales", "total legs", "legs por partido", "leg por partido"]),
        ("Promedio Checkouts", "✅",
         ["promedio checkouts", "promedio checkout", "checkouts", "checkout"]),
        ("Número victorias", "🏆",
         ["número victorias", "numero victorias", "n. victorias", "n victorias", "victorias"]),
        ("Número derrotas", "❌",
         ["número derrotas", "numero derrotas", "n. derrotas", "n derrotas", "derrotas"]),
        ("Porcentaje victoria", "📈",
         ["porcentaje victoria", "porcentaje de victoria", "% victoria", "%victoria", "porc. victoria"]),
        ("Índice Volatilidad", "🎲",
         ["índice volatilidad", "indice volatilidad", "índice de volatilidad", "volatilidad"]),
    ]
    
    def buscar_valor(stats_dict, sinonimos, claves_excluidas):
        """Busca el primer match (forward only) en stats_dict para alguno de los sinónimos.
        Los sinónimos se prueban en orden, de más específicos a más genéricos.
        """
        for syn in sinonimos:
            syn_lower = syn.lower()
            for k, v in stats_dict.items():
                if k in claves_excluidas:
                    continue
                k_lower = str(k).lower().strip()
                if not k_lower:
                    continue
                if syn_lower in k_lower:
                    return k, v
        return None, "-"
    
    # Match case-insensitive del jugador en stats_resumen
    # (las jornadas diarias guardan nombres con mayúsculas, el resumen en minúsculas)
    stats_jugador_resumen = None
    if mostrar_tendencias and stats_resumen:
        if player in stats_resumen:
            stats_jugador_resumen = stats_resumen[player]
        else:
            player_lower = str(player).lower().strip()
            for k_resumen, v_resumen in stats_resumen.items():
                if str(k_resumen).lower().strip() == player_lower:
                    stats_jugador_resumen = v_resumen
                    break
    
    # Detectar si la jornada del jugador ha comenzado.
    # Si TODOS los valores numéricos son 0 (o no hay ninguno parseable), el jugador
    # aún no ha jugado en esta jornada, así que no tiene sentido mostrar indicadores
    # de tendencia (saldrían 🔴↓ comparando 0 contra el promedio semanal).
    jornada_iniciada = False
    for _, v in stats.items():
        try:
            num = float(str(v).replace('%', '').replace(',', '.').strip())
            if num > 0:
                jornada_iniciada = True
                break
        except:
            continue
    
    # Si la jornada no ha empezado, suprimir los indicadores de tendencia
    # (pero guardamos la referencia original para el parentesis de la
    # tarjeta de volatilidad, que debe verse aunque no haya tendencias)
    stats_resumen_original = stats_jugador_resumen
    if not jornada_iniciada:
        stats_jugador_resumen = None
    
    claves_usadas = set()
    cards_html = '<div class="stats-grid">'
    
    for etiqueta, icono, sinonimos in config_stats:
        clave_encontrada, valor = buscar_valor(stats, sinonimos, claves_usadas)

        # ── Caso especial: Índice Volatilidad sin datos suficientes ──────
        # El Sheet no calcula la volatilidad hasta que el jugador lleva
        # varios partidos. En vez de ocultar la tarjeta (queda feo), se
        # muestra "Faltan datos" y, entre parentesis, el indice del
        # Resumen Semanal (dias anteriores) si existe.
        if etiqueta == "Índice Volatilidad":
            vol_sin_datos = False
            if not clave_encontrada:
                vol_sin_datos = True
            else:
                try:
                    v_num = float(str(valor).replace('%', '')
                                  .replace(',', '.').strip())
                    if v_num == 0:
                        vol_sin_datos = True
                except Exception:
                    vol_sin_datos = True

            if vol_sin_datos:
                paren = ""
                if stats_resumen_original:
                    _, v_sem = buscar_valor(stats_resumen_original,
                                             sinonimos, set())
                    try:
                        n_sem = float(str(v_sem).replace('%', '')
                                      .replace(',', '.').strip())
                        if n_sem != 0:
                            paren = f"({n_sem:.1f})".replace('.', ',')
                    except Exception:
                        pass
                paren_html = (
                    f'<span style="font-size:13px;color:#999;'
                    f'font-weight:500;">{paren}</span>'
                ) if paren else ''
                cards_html += (
                    f'<div style="background:linear-gradient(135deg,'
                    f'rgba(156,163,175,0.08) 0%,rgba(255,255,255,0.01) 100%);'
                    f'border-left:3px solid #9ca3af;border-radius:8px;'
                    f'padding:12px 15px;">'
                    f'<div style="display:flex;align-items:center;gap:8px;'
                    f'margin-bottom:8px;">'
                    f'<span style="font-size:18px;">{icono}</span>'
                    f'<span style="font-size:12px;color:#888;'
                    f'font-weight:600;">{etiqueta}</span>'
                    f'</div>'
                    f'<div style="display:flex;align-items:baseline;'
                    f'justify-content:space-between;gap:6px;flex-wrap:wrap;">'
                    f'<span style="font-size:15px;font-weight:600;'
                    f'color:#6b7280;">Faltan datos</span>'
                    f'{paren_html}'
                    f'</div>'
                    f'</div>'
                )
                if clave_encontrada:
                    claves_usadas.add(clave_encontrada)
                continue

        if not clave_encontrada:
            continue
        
        claves_usadas.add(clave_encontrada)
        
        # Formatear valor: si es decimal con muchos decimales, redondear a 1 decimal
        # (ej. "5,666666667" → "5,7"). Conserva % y enteros tal cual.
        valor_str = str(valor).strip()
        if '%' not in valor_str and not valor_str.startswith('#'):
            try:
                num = float(valor_str.replace(',', '.').strip())
                # Si tiene parte decimal significativa y la cadena original tiene >3 chars decimales
                partes = valor_str.replace(',', '.').split('.')
                if len(partes) == 2 and len(partes[1]) > 2:
                    # Redondear a 1 decimal con coma española
                    valor = f"{num:.1f}".replace('.', ',')
            except:
                pass
        
        # Tendencia (comparación con resumen semanal)
        indicador = ""
        comparativa = ""
        if stats_jugador_resumen:
            _, valor_semanal = buscar_valor(stats_jugador_resumen, sinonimos, set())
            # Para Puntuación Global pasamos la clave original (contiene "puntiación") para activar el umbral del 3%
            etiqueta_para_tendencia = clave_encontrada if etiqueta == "Puntuación Global" else etiqueta
            indicador, _, comparativa = calcular_tendencia(valor, valor_semanal, etiqueta_para_tendencia)
            
            # Para volatilidad la lógica es INVERSA: menos volatilidad = mejor.
            # Invertimos el indicador (🟢↑ era "mejoró subiendo", ahora significa "empeoró subiendo").
            if etiqueta == "Índice Volatilidad":
                if "🟢" in indicador:
                    indicador = indicador.replace("🟢", "🔴")
                elif "🔴" in indicador:
                    indicador = indicador.replace("🔴", "🟢")
        
        # Detectar si es la tarjeta destacada (Puntuación Global)
        es_featured = etiqueta == "Puntuación Global"
        es_volatilidad = etiqueta == "Índice Volatilidad"
        
        # Colores según tipo de estadística
        if etiqueta == "Número victorias":
            color_borde = "#28a745"
            color_valor = "#28a745"
            bg_grad = "rgba(40, 167, 69, 0.08)"
        elif etiqueta == "Número derrotas":
            color_borde = "#dc3545"
            color_valor = "#dc3545"
            bg_grad = "rgba(220, 53, 69, 0.08)"
        elif es_featured:
            color_borde = "#f59e0b"
            color_valor = "#b45309"
            bg_grad = "rgba(245, 158, 11, 0.15)"
        elif es_volatilidad:
            paleta_vol = color_volatilidad(valor)
            color_borde = paleta_vol["borde"]
            color_valor = paleta_vol["valor"]
            bg_grad = paleta_vol["bg"]
        else:
            # Azul por defecto para todas las demás
            color_borde = "#1f77b4"
            color_valor = "#1f77b4"
            bg_grad = "rgba(31, 119, 180, 0.08)"
        
        # Indicador de tendencia: color verde si sube, rojo si baja, gris si neutro
        if "🟢" in indicador:
            tend_color = "#28a745"
            tend_weight = "700"
        elif "🔴" in indicador:
            tend_color = "#dc3545"
            tend_weight = "700"
        else:
            tend_color = "#999"
            tend_weight = "500"
        
        if indicador or comparativa:
            tend_html = (
                f'<span style="font-size:12px;color:{tend_color};font-weight:{tend_weight};white-space:nowrap;">'
                f'{indicador} {comparativa}</span>'
            )
        else:
            tend_html = ''
        
        # Badge de riesgo solo para la tarjeta de volatilidad (cuando hay valor parseable)
        riesgo_badge = ''
        if es_volatilidad:
            paleta_vol = color_volatilidad(valor)
            if paleta_vol["riesgo_label"]:
                riesgo_badge = (
                    f'<span style="font-size:10px;color:{paleta_vol["riesgo_texto"]};'
                    f'background:{paleta_vol["riesgo_bg"]};padding:2px 8px;border-radius:10px;'
                    f'font-weight:700;letter-spacing:0.3px;margin-left:6px;white-space:nowrap;">'
                    f'{paleta_vol["riesgo_label"]}</span>'
                )
        
        # Renderizado de la tarjeta destacada (Puntuación Global) — ocupa toda la fila
        if es_featured:
            cards_html += (
                f'<div style="grid-column:1 / -1;'
                f'background:linear-gradient(135deg,{bg_grad} 0%,rgba(255,255,255,0.01) 100%);'
                f'border:2px solid {color_borde};border-radius:10px;padding:18px 22px;'
                f'box-shadow:0 2px 8px rgba(245,158,11,0.12);">'
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap;">'
                f'<span style="font-size:22px;">{icono}</span>'
                f'<span style="font-size:13px;color:#666;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;">{etiqueta}</span>'
                f'<span style="font-size:10px;color:#92400e;font-weight:600;'
                f'background:rgba(245,158,11,0.18);padding:2px 8px;border-radius:10px;">⭐ MÉTRICA CLAVE</span>'
                f'</div>'
                f'<div style="display:flex;align-items:baseline;justify-content:space-between;gap:8px;flex-wrap:wrap;">'
                f'<span style="font-size:34px;font-weight:bold;color:{color_valor};line-height:1;">{valor}</span>'
                f'{tend_html}'
                f'</div>'
                f'</div>'
            )
        else:
            # Tarjeta estándar
            cards_html += (
                f'<div style="background:linear-gradient(135deg,{bg_grad} 0%,rgba(255,255,255,0.01) 100%);'
                f'border-left:3px solid {color_borde};border-radius:8px;padding:12px 15px;">'
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">'
                f'<span style="font-size:18px;">{icono}</span>'
                f'<span style="font-size:12px;color:#888;font-weight:600;">{etiqueta}</span>'
                f'</div>'
                f'<div style="display:flex;align-items:baseline;justify-content:space-between;gap:6px;flex-wrap:wrap;">'
                f'<span style="font-size:22px;font-weight:bold;color:{color_valor};">{valor}</span>'
                f'{tend_html}{riesgo_badge}'
                f'</div>'
                f'</div>'
            )
    
    cards_html += '</div>'
    st.markdown(cards_html, unsafe_allow_html=True)

    # ── Tarjeta Racha (ancho completo) ────────────────────────────────────
    if mostrar_racha:
        try:
            from data_loading import (cargar_historial_semana,
                                       cargar_historial_jornada, calcular_racha)
            # Si jornada_racha tiene valor, leer solo esa jornada; si es None,
            # toda la semana.
            if jornada_racha:
                resultados = cargar_historial_jornada(player, jornada_racha)
                titulo_racha = "RACHA EN LA JORNADA"
            else:
                resultados = cargar_historial_semana(player)
                titulo_racha = "RACHA SEMANAL"
            racha_n, racha_tipo = calcular_racha(resultados)
            # Mostrar solo los ULTIMOS 5 partidos
            resultados = resultados[-5:]
            if resultados:  # solo si ha jugado algun partido
                puntos = ""
                for r in resultados:
                    color = "#22c55e" if r else "#ef4444"
                    sombra = ("rgba(34,197,94,0.5)" if r
                              else "rgba(239,68,68,0.4)")
                    puntos += (
                        f"<span style='display:inline-block;width:13px;"
                        f"height:13px;border-radius:50%;background:{color};"
                        f"box-shadow:0 0 4px {sombra};'></span>"
                    )
                if racha_tipo == "W" and racha_n >= 2:
                    badge_color, badge_bg, badge = "#22c55e", "rgba(34,197,94,0.12)", f"{racha_n}V"
                elif racha_tipo == "L" and racha_n >= 2:
                    badge_color, badge_bg, badge = "#ef4444", "rgba(239,68,68,0.10)", f"{racha_n}D"
                elif racha_tipo == "W":
                    badge_color, badge_bg, badge = "#22c55e", "rgba(34,197,94,0.10)", "1V"
                elif racha_tipo == "L":
                    badge_color, badge_bg, badge = "#ef4444", "rgba(239,68,68,0.08)", "1D"
                else:
                    badge_color, badge_bg, badge = "#94a3b8", "rgba(148,163,184,0.10)", "—"
                badge_html = (
                    f"<span style='font-size:11px;font-weight:700;"
                    f"color:{badge_color};background:{badge_bg};"
                    f"padding:2px 10px;border-radius:10px;"
                    f"white-space:nowrap;'>{badge}</span>"
                )
                racha_html = (
                    f"<div style='grid-column:1 / -1;background:linear-gradient("
                    f"135deg,rgba(248,250,252,0.8) 0%,rgba(255,255,255,0.01) "
                    f"100%);border:1px solid #e2e8f0;border-radius:10px;"
                    f"padding:14px 20px;margin-top:6px;margin-bottom:18px;'>"
                    f"<div style='display:flex;align-items:center;"
                    f"justify-content:space-between;gap:12px;flex-wrap:wrap;'>"
                    f"<div style='display:flex;align-items:center;gap:8px;'>"
                    f"<span style='font-size:18px;'>📈</span>"
                    f"<span style='font-size:12px;color:#888;font-weight:600;"
                    f"text-transform:uppercase;letter-spacing:0.04em;'>"
                    f"{titulo_racha}</span>"
                    f"{badge_html}"
                    f"</div>"
                    f"<div style='display:flex;align-items:center;gap:8px;"
                    f"flex-wrap:wrap;flex:1;justify-content:flex-end;'>"
                    f"{puntos}"
                    f"</div>"
                    f"</div>"
                    f"</div>"
                )
                racha_compacto = " ".join(
                    line.strip() for line in racha_html.splitlines()
                    if line.strip()
                )
                st.markdown(racha_compacto, unsafe_allow_html=True)
        except Exception:
            pass


def selector_jornada(key_prefix, incluir_resumen=True,
                     modo_forma_reciente=True):
    """Selector de fuente de datos.

    modo_forma_reciente=True (Value Bets):
        Por defecto la fuente es "⚡ Forma reciente" (combinacion ponderada
        de la jornada de hoy con el Resumen Semanal). El selector manual de
        grupo/dia va PLEGADO dentro de un expander discreto.

    modo_forma_reciente=False (Resultados y Estadisticas):
        No existe "Forma reciente". El selector de grupo/dia se muestra
        SIEMPRE visible, sin expander, como un menu normal.

    Devuelve el nombre de la fuente seleccionada (clave de URLS, o el valor
    especial "Forma reciente" solo en modo_forma_reciente).
    """
    grupos = {
        "Grupo A": ["Grupo A Lunes", "Grupo A Martes", "Grupo A Miércoles"],
        "Grupo B": ["Grupo B Jueves", "Grupo B Viernes"],
        "Grupo C": ["Grupo C Jueves", "Grupo C Viernes"],
    }

    grupo_key = f"{key_prefix}_grupo_sel"
    jornada_key = f"{key_prefix}_jornada_sel"

    # Valores por defecto segun el modo
    if modo_forma_reciente:
        defecto_jornada = "Forma reciente"
        defecto_grupo = "Forma reciente"
    else:
        # La jornada en juego o la ultima que ha empezado (no siempre el lunes)
        try:
            defecto_jornada = jornada_mas_reciente()
        except Exception:
            defecto_jornada = "Grupo A Lunes"
        if defecto_jornada == "Final Sábado":
            defecto_grupo = "Final"
        else:
            defecto_grupo = next((g for g, dias in grupos.items()
                                  if defecto_jornada in dias), "Grupo A")
    if jornada_key not in st.session_state:
        st.session_state[jornada_key] = defecto_jornada
    if grupo_key not in st.session_state:
        st.session_state[grupo_key] = defecto_grupo

    # Funcion interna que dibuja el selector de grupo/dia. Se reutiliza en
    # los dos modos; solo cambia si va dentro de un expander o no.
    # Son dos barras de botones (segmented control) en vez de 3 filas de
    # botones sueltos: en el movil los botones se apilaban uno debajo de
    # otro y ocupaban una pantalla entera antes de ver ningun dato.
    def _dibujar_botones():
        opciones_g = ["Grupo A", "Grupo B", "Grupo C", "Final"]
        if incluir_resumen:
            opciones_g.append("Resumen Semanal")
        etiquetas_g = {"Final": "🏆 Final", "Resumen Semanal": "📊 Resumen"}
        actual_g = st.session_state[grupo_key]
        actual_g = actual_g if actual_g in opciones_g else None
        # La key incluye el valor actual: si el estado cambia desde otro sitio
        # (p. ej. el boton "Forma reciente"), el control se redibuja con el.
        sel_g = st.segmented_control(
            "Grupo", opciones_g, default=actual_g,
            format_func=lambda g: etiquetas_g.get(g, g),
            key=f"{key_prefix}_seg_grupo_{actual_g}",
            label_visibility="collapsed")
        if sel_g and sel_g != actual_g:
            st.session_state[grupo_key] = sel_g
            st.session_state[jornada_key] = (
                grupos[sel_g][0] if sel_g in grupos
                else "Final Sábado" if sel_g == "Final" else "Resumen Semanal")
            st.rerun()

        # Dias del grupo activo (solo si es Grupo A/B/C)
        grupo_actual = st.session_state[grupo_key]
        if grupo_actual in grupos:
            dias = grupos[grupo_actual]
            actual_d = st.session_state[jornada_key]
            actual_d = actual_d if actual_d in dias else None
            sel_d = st.segmented_control(
                "Día", dias, default=actual_d,
                format_func=lambda d: d.replace(grupo_actual + " ", ""),
                key=f"{key_prefix}_seg_dia_{actual_d}",
                label_visibility="collapsed")
            if sel_d and sel_d != actual_d:
                st.session_state[jornada_key] = sel_d
                st.rerun()

    # ── Modo Resultados: menu normal, siempre visible ────────────────────────
    if not modo_forma_reciente:
        _dibujar_botones()
        return st.session_state[jornada_key]

    # ── Modo Value Bets: Forma reciente + selector plegado ───────────────────
    seleccion_actual = st.session_state[jornada_key]
    expandido = (seleccion_actual != "Forma reciente")
    etiqueta_exp = "⚙️ Cambiar fuente de datos"
    if seleccion_actual != "Forma reciente":
        etiqueta_exp += f" — usando: {seleccion_actual}"

    with st.expander(etiqueta_exp, expanded=expandido):
        st.caption(
            "Por defecto se usa **⚡ Forma reciente** (combina la jornada de "
            "hoy con el acumulado semanal, dando mas peso a lo reciente). "
            "Puedes elegir una jornada concreta abajo si lo prefieres."
        )
        tipo_fr = "primary" if seleccion_actual == "Forma reciente" else "secondary"
        if st.button("⚡ Forma reciente (recomendado)",
                     key=f"{key_prefix}_btn_forma", use_container_width=True,
                     type=tipo_fr):
            st.session_state[jornada_key] = "Forma reciente"
            st.session_state[grupo_key] = "Forma reciente"
            st.rerun()
        st.markdown("---")
        _dibujar_botones()

    return st.session_state[jornada_key]

def render_value_bets():
    st.title("💰 Value Bets")
    value_bets_list = []
    fuente = selector_jornada("vb", incluir_resumen=True,
                              modo_forma_reciente=True)
    st.session_state.vb_fuente = fuente
    with st.spinner(f"Cargando datos de '{fuente}'..."):
        # "Forma reciente" no es una pestana real: es la combinacion
        # ponderada de la jornada de hoy con el Resumen Semanal.
        if fuente == "Forma reciente":
            db_jugadores = cargar_forma_reciente()
        else:
            db_jugadores = cargar_jugadores_desde(fuente)
    if not db_jugadores:
        st.warning(f"⚠️ No se encontraron jugadores en '{fuente}'.")
        return

    # Además de la fuente seleccionada, cargamos la base GLOBAL de jugadores
    # desde el Resumen Semanal, que contiene a TODOS los jugadores de la
    # semana (Grupo A, B y C). Esto permite que el desplegable de próximos
    # partidos y los selectores de J1/J2 funcionen con cualquier jugador,
    # independientemente del día/grupo seleccionado arriba.
    #
    # Para los cálculos seguimos prefiriendo los datos de la fuente elegida;
    # solo si un jugador no está en esa fuente usamos su ficha del Resumen
    # Semanal como respaldo (db_jugadores_completa).
    db_global = {}
    if fuente != "Resumen Semanal":
        try:
            db_global = cargar_jugadores_desde("Resumen Semanal") or {}
        except Exception:
            db_global = {}
    # db_jugadores_completa = fuente seleccionada con prioridad, completada
    # con los jugadores del Resumen Semanal que falten.
    db_jugadores_completa = dict(db_global)
    db_jugadores_completa.update(db_jugadores)  # la fuente elegida tiene prioridad

    # La lista de nombres del selector usa la base COMPLETA, así puedes
    # elegir (o autocompletar) cualquier jugador de cualquier grupo.
    nombres_disponibles = sorted(
        v["nombre_original"] for v in db_jugadores_completa.values()
    )
    if fuente in st.session_state.last_update:
        tiempo_transcurrido = (datetime.now() - st.session_state.last_update[fuente]).seconds
        st.info(f"📊 {len(nombres_disponibles)} jugadores | ⏱️ Actualizado hace {tiempo_transcurrido}s")
    st.markdown("### 🥊 Seleccionar Enfrentamiento")
    st.caption("Pon como **Jugador 1** al que aparece primero en el cartel del "
               "partido: el modelo le da la ventaja de empezar lanzando.")

    # ── Desplegable de próximos partidos ──────────────────────────────────────
    # Lista los 5 próximos partidos que aún no han empezado, leídos del CSV
    # de la jornada que toca (activa o, si no hay, la próxima). NO usa la API
    # de MODUS porque devuelve fixtures de jornadas viejas ya finalizadas.
    resultado_api = obtener_proximos_partidos_csv(limite=5)
    # Compatibilidad: la función ahora devuelve un dict; si por lo que sea
    # llegara una lista (versión antigua en caché), la adaptamos.
    if isinstance(resultado_api, dict):
        proximos = resultado_api.get("partidos", [])
        diagnostico = resultado_api.get("diagnostico", "")
    else:
        proximos = resultado_api or []
        diagnostico = ""

    def _emparejar_nombre(nombre_api, candidatos):
        """Empareja un nombre de la API con uno de la lista del desplegable.
        Hace match exacto primero y, si falla, match difuso por subcadena
        (útil cuando la API y el spreadsheet escriben el nombre distinto).
        Devuelve el nombre del candidato o None si no hay coincidencia.
        """
        if not nombre_api:
            return None
        na = nombre_api.lower().strip()
        # Match exacto (ignorando mayúsculas)
        for c in candidatos:
            if c.lower().strip() == na:
                return c
        # Match por subcadena en ambos sentidos
        for c in candidatos:
            cl = c.lower().strip()
            if na in cl or cl in na:
                return c
        # Match por apellido (última palabra)
        ape = na.split()[-1] if na.split() else na
        for c in candidatos:
            if ape and ape in c.lower():
                return c
        return None

    if proximos:
        OPCION_MANUAL = "— Selección manual —"

        # Reconstruimos la etiqueta de cada partido SOLO con los nombres de
        # los dos jugadores ("J1 vs J2"), ignorando cualquier campo 'etiqueta'
        # que venga de la API (que podría incluir fecha/hora u otra info
        # extra). Así el desplegable siempre muestra únicamente nombres.
        for p in proximos:
            p["etiqueta_limpia"] = f"{p['j1']} vs {p['j2']}"

        opciones_prox = [OPCION_MANUAL] + [p["etiqueta_limpia"] for p in proximos]

        seleccion_prox = st.selectbox(
            "📅 Próximos partidos",
            opciones_prox,
            index=0,
            key="vb_proximo_partido",
            help="Elige un partido para autocompletar automáticamente "
                 "Jugador 1 y Jugador 2. Se muestran todos los partidos "
                 "que aún no han empezado."
        )

        # Si el usuario eligió un partido concreto, autocompletar J1 y J2.
        #
        # Importante: NO se hace st.rerun() aquí. Un rerun reinicia toda la
        # app y haría que la barra lateral volviese a la sección por defecto
        # (LIVE), sacando al usuario de Value Bets. En su lugar, escribimos
        # directamente en st.session_state.vb_j1 / vb_j2 ANTES de que los
        # selectbox de abajo se creen: como esos selectbox usan esas mismas
        # claves, se renderizan ya con los jugadores correctos en este mismo
        # run, sin recargar la página.
        #
        # 'vb_ultimo_prox' recuerda qué partido se aplicó por última vez, para
        # no machacar las selecciones manuales del usuario en cada rerun
        # natural de Streamlit (al pulsar otros widgets de la página).
        if seleccion_prox != OPCION_MANUAL:
            partido = next((p for p in proximos
                            if p["etiqueta_limpia"] == seleccion_prox), None)
            if partido and st.session_state.get("vb_ultimo_prox") != seleccion_prox:
                j1_match = _emparejar_nombre(partido["j1"], nombres_disponibles)
                j2_match = _emparejar_nombre(partido["j2"], nombres_disponibles)
                if j1_match and j2_match and j1_match != j2_match:
                    # Escritura directa en las claves de los widgets J1/J2.
                    # Es seguro porque los widgets aún no se han instanciado.
                    st.session_state.vb_j1 = j1_match
                    st.session_state.vb_j2 = j2_match
                    st.session_state.vb_ultimo_prox = seleccion_prox
                    st.success(
                        f"✅ Enfrentamiento cargado: **{j1_match}** vs **{j2_match}**"
                    )
                else:
                    # No se pudo emparejar alguno de los dos jugadores
                    faltan = []
                    if not j1_match:
                        faltan.append(partido["j1"])
                    if not j2_match:
                        faltan.append(partido["j2"])
                    if faltan:
                        st.warning(
                            "⚠️ No encontré en esta fuente de datos a: "
                            + ", ".join(faltan)
                            + ". Selecciónalos manualmente abajo."
                        )
        else:
            # Volvió a "Selección manual": limpiar el marcador para permitir
            # que un partido se pueda volver a aplicar más adelante.
            st.session_state.vb_ultimo_prox = None
    else:
        # No hay próximos partidos: mostrar el motivo en vez de ocultar todo.
        st.caption(
            "📅 Próximos partidos: " +
            (diagnostico or "no hay partidos pendientes ahora mismo.") +
            " Selecciona los jugadores manualmente abajo."
        )


    if st.session_state.vb_j1 is None or st.session_state.vb_j1 not in nombres_disponibles:
        st.session_state.vb_j1 = nombres_disponibles[0]
    if st.session_state.vb_j2 is None or st.session_state.vb_j2 not in nombres_disponibles:
        opciones_j2 = [n for n in nombres_disponibles if n != st.session_state.vb_j1]
        st.session_state.vb_j2 = opciones_j2[0] if opciones_j2 else nombres_disponibles[0]
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        # El selectbox usa 'vb_j1' como key directamente: el widget y el
        # estado de sesión son la MISMA variable. Esto permite que el
        # desplegable de próximos partidos autocomplete el valor sin recargar.
        #
        # Solo pasamos 'index' la primera vez (cuando la key aún no existe en
        # session_state). Si ya existe, Streamlit usa el valor de la key, así
        # que pasar 'index' además sería redundante y podría dar un warning.
        kwargs_j1 = {"key": "vb_j1"}
        if "vb_j1" not in st.session_state or st.session_state.vb_j1 not in nombres_disponibles:
            valor_inicial = st.session_state.get("vb_j1")
            if valor_inicial not in nombres_disponibles:
                valor_inicial = nombres_disponibles[0]
            kwargs_j1["index"] = nombres_disponibles.index(valor_inicial)
        j1_sel = st.selectbox("Jugador 1", nombres_disponibles, **kwargs_j1)
    with col2:
        opciones_j2 = [n for n in nombres_disponibles if n != j1_sel]
        if not opciones_j2:
            opciones_j2 = nombres_disponibles
        # Si el J2 actual ya no es válido (coincide con J1 o no está en la
        # lista), ajustarlo ANTES de crear el widget — no se puede tocar la
        # key una vez instanciado el selectbox.
        if st.session_state.get("vb_j2") not in opciones_j2:
            st.session_state.vb_j2 = opciones_j2[0]
        kwargs_j2 = {"key": "vb_j2"}
        # Pasamos index solo si la key todavía no existe (primer render).
        if "vb_j2" not in st.session_state:
            kwargs_j2["index"] = 0
        j2_sel = st.selectbox("Jugador 2", opciones_j2, **kwargs_j2)
    # Al cambiar de partido se vacian las cuotas escritas: si no, las del
    # partido anterior seguian puestas y salian "value bets" que no lo eran.
    par_actual = (j1_sel, j2_sel)
    if st.session_state.get("_vb_par") not in (None, par_actual):
        for k in [k for k in st.session_state.keys()
                  if isinstance(k, str) and k.startswith(
                      ("vic_", "180_", "mas_", "hcap_", "legs_"))]:
            del st.session_state[k]
    st.session_state["_vb_par"] = par_actual
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔢 Calcular", type="primary", use_container_width=True, help="Calcular probabilidades"):
            st.session_state.vb_calcular = True
        # Boton pequeño para registrar este partido en el seguimiento del
        # modelo. Va justo debajo de Calcular. Antes de registrar, comprueba
        # que los jugadores no tengan partidos anteriores sin terminar.
        # Solo el administrador puede escribir en el Sheet de seguimiento.
        if _PREDICCIONES_OK and registrar_predicciones is not None and es_admin():

            def _hacer_registro(jr1, jr2, j1_sel, j2_sel, fuente):
                """Registra el partido y muestra el mensaje de resultado."""
                # Mismo ID que auto_registrar: dia de jornada en hora de Madrid
                # (antes se usaba la hora UTC del servidor y, cerca de la
                # medianoche, el mismo partido acababa registrado dos veces).
                semana_vb = f"Semana {fecha_jornada_madrid()}"
                jornada_reg = fuente
                if fuente == "Forma reciente":
                    jornada_reg = detectar_jornada_de_hoy() or fuente
                with st.spinner(f"Registrando {j1_sel} vs {j2_sel}..."):
                    resultado = registrar_predicciones(
                        "", [(jr1, jr2)], semana_vb, jornada_reg
                    )
                if resultado["ok"]:
                    nuevas = resultado.get("nuevas", 0)
                    actualizadas = resultado.get("actualizadas", 0)
                    if actualizadas > 0 and nuevas == 0:
                        st.success(
                            f"♻️ {j1_sel} vs {j2_sel} ya estaba "
                            f"registrado — actualizado con los datos "
                            f"actuales ({actualizadas} mercados)."
                        )
                    elif actualizadas > 0:
                        st.success(
                            f"✅ Registrado: {j1_sel} vs {j2_sel} "
                            f"({nuevas} nuevos, {actualizadas} "
                            f"actualizados)."
                        )
                    else:
                        st.success(
                            f"✅ Registrado: {j1_sel} vs {j2_sel} "
                            f"({nuevas} mercados)."
                        )
                    if cargar_predicciones is not None:
                        cargar_predicciones.clear()
                else:
                    st.error(f"❌ {resultado['error']}")

            if st.button("📝 Registrar", use_container_width=True,
                         key="vb_btn_registrar",
                         help="Registra este partido en el seguimiento del "
                              "modelo (pestaña SEGUIMIENTO)."):
                jr1 = (buscar_jugador(j1_sel, db_jugadores)
                       or buscar_jugador(j1_sel, db_jugadores_completa))
                jr2 = (buscar_jugador(j2_sel, db_jugadores)
                       or buscar_jugador(j2_sel, db_jugadores_completa))
                if not jr1 or not jr2:
                    st.error("No se encontraron datos de los jugadores.")
                elif j1_sel == j2_sel:
                    st.error("Elige dos jugadores distintos.")
                else:
                    # Comprobar partidos anteriores sin terminar
                    jornada_chk = fuente
                    if fuente == "Forma reciente":
                        jornada_chk = detectar_jornada_de_hoy() or fuente
                    chequeo = {"ok": True, "pudo_comprobar": False,
                               "avisos": [], "diagnostico": ""}
                    if comprobar_partidos_anteriores is not None:
                        with st.spinner("Comprobando partidos anteriores..."):
                            chequeo = comprobar_partidos_anteriores(
                                jornada_chk, j1_sel, j2_sel)

                    if not chequeo.get("pudo_comprobar", False):
                        # No se pudo comprobar: NO registramos en silencio.
                        # Avisamos y mostramos el diagnostico.
                        st.session_state["vb_aviso_registro"] = {
                            "j1": j1_sel, "j2": j2_sel,
                            "tipo": "no_comprobado",
                            "avisos": [],
                            "diagnostico": chequeo.get("diagnostico", ""),
                        }
                    elif chequeo["ok"]:
                        # Comprobado y todo terminado: registrar directo.
                        _hacer_registro(jr1, jr2, j1_sel, j2_sel, fuente)
                    else:
                        # Hay partidos a medias: avisar.
                        st.session_state["vb_aviso_registro"] = {
                            "j1": j1_sel, "j2": j2_sel,
                            "tipo": "a_medias",
                            "avisos": chequeo["avisos"],
                            "diagnostico": chequeo.get("diagnostico", ""),
                        }

            # Si hay un aviso pendiente para ESTE partido, mostrarlo y
            # ofrecer registrar de todas formas.
            aviso = st.session_state.get("vb_aviso_registro")
            if (aviso and aviso.get("j1") == j1_sel
                    and aviso.get("j2") == j2_sel):
                if aviso.get("tipo") == "no_comprobado":
                    st.warning(
                        "⚠️ No se ha podido comprobar si los jugadores "
                        "tienen partidos sin terminar. Revisa el "
                        "diagnostico antes de registrar."
                    )
                else:
                    st.warning(
                        "⚠️ Hay partidos sin terminar de estos jugadores:\n\n"
                        + "\n".join(f"• {a}" for a in aviso["avisos"])
                        + "\n\nLos datos pueden no estar completos."
                    )
                # Mostrar el diagnostico para depurar
                if aviso.get("diagnostico"):
                    with st.expander("🔍 Ver diagnostico de la comprobacion"):
                        st.code(aviso["diagnostico"], language="text")
                if st.button("📝 Registrar de todas formas",
                             use_container_width=True,
                             key="vb_btn_registrar_forzar"):
                    jr1 = (buscar_jugador(j1_sel, db_jugadores)
                           or buscar_jugador(j1_sel, db_jugadores_completa))
                    jr2 = (buscar_jugador(j2_sel, db_jugadores)
                           or buscar_jugador(j2_sel, db_jugadores_completa))
                    if jr1 and jr2:
                        _hacer_registro(jr1, jr2, j1_sel, j2_sel, fuente)
                    st.session_state["vb_aviso_registro"] = None
    if not st.session_state.vb_calcular:
        st.info("👆 Selecciona los jugadores y pulsa **Calcular**")
        return

    # PRIORIDAD DEL DESPLEGABLE: si hay un enfrentamiento seleccionado en
    # "Próximos partidos" (distinto de "Selección manual"), sus jugadores
    # mandan sobre lo que haya en las casillas manuales. Esto evita el bug
    # de calcular con jugadores antiguos cuando el desplegable muestra otro
    # partido.
    sel_prox = st.session_state.get("vb_proximo_partido")
    if sel_prox and sel_prox != "— Selección manual —" and proximos:
        partido_sel = next((p for p in proximos
                             if p.get("etiqueta_limpia") == sel_prox
                             or f"{p['j1']} vs {p['j2']}" == sel_prox), None)
        if partido_sel:
            m1 = _emparejar_nombre(partido_sel["j1"], nombres_disponibles)
            m2 = _emparejar_nombre(partido_sel["j2"], nombres_disponibles)
            if m1 and m2 and m1 != m2:
                j1_sel, j2_sel = m1, m2

    # Buscar los datos de cada jugador: primero en la fuente seleccionada
    # (datos del día/grupo concreto) y, si no está ahí, en la base completa
    # (Resumen Semanal). Así se puede analizar un enfrentamiento aunque uno
    # de los jugadores sea de otro grupo distinto al seleccionado arriba.
    j1 = buscar_jugador(j1_sel, db_jugadores) or buscar_jugador(j1_sel, db_jugadores_completa)
    j2 = buscar_jugador(j2_sel, db_jugadores) or buscar_jugador(j2_sel, db_jugadores_completa)
    if not j1 or not j2:
        st.error("No se encontraron datos para uno de los jugadores.")
        return
    pr1, pr2     = j1["PR"],       j2["PR"]
    lam1, lam2   = j1["lam_180"],  j2["lam_180"]
    legs1, legs2 = j1["lam_legs"], j2["lam_legs"]
    for _j in (j1, j2):
        _n = pocos_partidos(_j)
        if _n:
            st.warning(
                f"⚠️ {_j.get('nombre_original', '')} lleva solo {_n} "
                f"{'partido' if _n == 1 else 'partidos'}: sus datos son poco "
                f"fiables y las probabilidades de este partido también.")
    st.markdown("---")
    st.markdown("### 📊 Comparativa de Jugadores")
    
    # Mostrar pentágonos lado a lado con Streamlit columns
    col_p1, col_vs, col_p2 = st.columns([1, 0.15, 1])
    
    with col_p1:
        st.markdown(f"<h3 style='text-align: center; color: #1f77b4;'>{j1['nombre_original']}</h3>", unsafe_allow_html=True)
        svg_j1 = render_pentagono_svg(pr1, lam1, j1["promedio_dardos"], j1["checkouts"], j1["pct_victorias"], color="#1f77b4")
        st.markdown(f"<div style='text-align: center;'>{svg_j1}</div>", unsafe_allow_html=True)
        
        # Datos en 5 columnas coloreados en azul
        dcols = st.columns(5)
        datos_j1 = [
            ("Power", f"{pr1:.1f}"),
            ("λ 180s", f"{lam1:.2f}"),
            ("Ø Dardos", f"{j1['promedio_dardos']:.1f}"),
            ("Checkout", f"{j1['checkouts']:.0f}%"),
            ("% Vic", f"{j1['pct_victorias']:.0f}%")
        ]
        for idx, (label, valor) in enumerate(datos_j1):
            with dcols[idx]:
                st.markdown(f"""
                <div style='text-align: center; padding: 10px; background: rgba(31, 119, 180, 0.1); border-radius: 6px; border-left: 3px solid #1f77b4;'>
                    <p style='margin: 0; font-size: 11px; color: #666;'>{label}</p>
                    <p style='margin: 5px 0 0 0; font-size: 18px; font-weight: bold; color: #1f77b4;'>{valor}</p>
                </div>
                """, unsafe_allow_html=True)
        
        # Card de Índice Volatilidad — separada, full-width, con semáforo
        vol_j1 = j1.get("volatilidad", 0.0)
        paleta_vol_j1 = color_volatilidad(vol_j1)
        vol_label_j1 = paleta_vol_j1["riesgo_label"].capitalize() if paleta_vol_j1["riesgo_label"] else "Sin datos"
        vol_str_j1 = f"{vol_j1:.2f}".replace(".", ",")
        st.markdown(
            f"<div style='margin-top: 12px; text-align: center; padding: 14px 18px; "
            f"background: {paleta_vol_j1['bg']}; border-radius: 8px; "
            f"border: 1px solid {paleta_vol_j1['borde']};'>"
            f"<p style='margin: 0; font-size: 12px; color: #666; font-weight: 600;'>📉 Índice Volatilidad</p>"
            f"<div style='margin-top: 8px; display: flex; align-items: baseline; justify-content: center; gap: 12px; flex-wrap: wrap;'>"
            f"<span style='font-size: 26px; font-weight: bold; color: {paleta_vol_j1['valor']};'>{vol_str_j1}</span>"
            f"<span style='font-size: 13px; font-weight: 600; color: {paleta_vol_j1['riesgo_texto']};'>● {vol_label_j1}</span>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True
        )
    
    with col_vs:
        st.markdown("""
        <div style='display: flex; align-items: center; justify-content: center; height: 100%; padding: 150px 0;'>
            <p style='font-size: 32px; font-weight: bold; color: #999; margin: 0;'>vs</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col_p2:
        st.markdown(f"<h3 style='text-align: center; color: #ff7f0e;'>{j2['nombre_original']}</h3>", unsafe_allow_html=True)
        svg_j2 = render_pentagono_svg(pr2, lam2, j2["promedio_dardos"], j2["checkouts"], j2["pct_victorias"], color="#ff7f0e")
        st.markdown(f"<div style='text-align: center;'>{svg_j2}</div>", unsafe_allow_html=True)
        
        # Datos en 5 columnas coloreados en naranja
        dcols = st.columns(5)
        datos_j2 = [
            ("Power", f"{pr2:.1f}"),
            ("λ 180s", f"{lam2:.2f}"),
            ("Ø Dardos", f"{j2['promedio_dardos']:.1f}"),
            ("Checkout", f"{j2['checkouts']:.0f}%"),
            ("% Vic", f"{j2['pct_victorias']:.0f}%")
        ]
        for idx, (label, valor) in enumerate(datos_j2):
            with dcols[idx]:
                st.markdown(f"""
                <div style='text-align: center; padding: 10px; background: rgba(255, 127, 14, 0.1); border-radius: 6px; border-left: 3px solid #ff7f0e;'>
                    <p style='margin: 0; font-size: 11px; color: #666;'>{label}</p>
                    <p style='margin: 5px 0 0 0; font-size: 18px; font-weight: bold; color: #ff7f0e;'>{valor}</p>
                </div>
                """, unsafe_allow_html=True)
        
        # Card de Índice Volatilidad — separada, full-width, con semáforo
        vol_j2 = j2.get("volatilidad", 0.0)
        paleta_vol_j2 = color_volatilidad(vol_j2)
        vol_label_j2 = paleta_vol_j2["riesgo_label"].capitalize() if paleta_vol_j2["riesgo_label"] else "Sin datos"
        vol_str_j2 = f"{vol_j2:.2f}".replace(".", ",")
        st.markdown(
            f"<div style='margin-top: 12px; text-align: center; padding: 14px 18px; "
            f"background: {paleta_vol_j2['bg']}; border-radius: 8px; "
            f"border: 1px solid {paleta_vol_j2['borde']};'>"
            f"<p style='margin: 0; font-size: 12px; color: #666; font-weight: 600;'>📉 Índice Volatilidad</p>"
            f"<div style='margin-top: 8px; display: flex; align-items: baseline; justify-content: center; gap: 12px; flex-wrap: wrap;'>"
            f"<span style='font-size: 26px; font-weight: bold; color: {paleta_vol_j2['valor']};'>{vol_str_j2}</span>"
            f"<span style='font-size: 13px; font-weight: 600; color: {paleta_vol_j2['riesgo_texto']};'>● {vol_label_j2}</span>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True
        )
    
    st.markdown("---")
    st.markdown("### 🔥 Head to Head Semanal")
    with st.spinner("Analizando enfrentamientos directos..."):
        h2h = extraer_h2h_semanal(j1['nombre_original'], j2['nombre_original'])
    
    if h2h["partidos"]:
        # Head to Head con nombres prominentes
        html_h2h = f"""
        <div style="display: flex; justify-content: space-around; align-items: center; gap: 30px; margin: 30px 0;">
            <div style="text-align: center; flex: 1;">
                <h2 style="color: #1f77b4; margin: 0; font-size: 32px;">{j1['nombre_original']}</h2>
                <p style="color: #1f77b4; font-size: 48px; font-weight: bold; margin: 10px 0;">{h2h["victorias_j1"]}</p>
                <p style="color: #666; font-size: 14px; margin: 0;">Victorias H2H</p>
            </div>
            <div style="text-align: center; font-size: 28px; color: #999;">vs</div>
            <div style="text-align: center; flex: 1;">
                <h2 style="color: #ff7f0e; margin: 0; font-size: 32px;">{j2['nombre_original']}</h2>
                <p style="color: #ff7f0e; font-size: 48px; font-weight: bold; margin: 10px 0;">{h2h["victorias_j2"]}</p>
                <p style="color: #666; font-size: 14px; margin: 0;">Victorias H2H</p>
            </div>
        </div>
        """
        st.markdown(html_h2h, unsafe_allow_html=True)
        
        with st.expander("📋 Ver historial de enfrentamientos"):
            for partido in h2h["partidos"]:
                st.markdown(f"**{partido['dia']}**: {partido['jugador1']} vs {partido['jugador2']} - **{partido['marcador']}** (Ganador: {partido['ganador']})")
    else:
        st.info("ℹ️ No se encontraron enfrentamientos directos esta semana")

    # ─── Últimos 3 partidos por jugador ───────────────────────────────────────
    # Dos desplegables (uno por jugador) con sus 3 últimos partidos jugados en
    # la semana, en orden cronológico inverso. Muestra rival, marcador y todas
    # las stats de la fila del jugador en cada partido.
    st.markdown("---")
    st.markdown("### 📅 Últimos partidos jugados")
    col_u1, col_u2 = st.columns(2)
    
    def _render_ultimos_partidos(col, jugador_dict, color_jug, color_rival):
        nombre = jugador_dict['nombre_original']
        with col:
            with st.expander(f"📂 Últimos 3 partidos de **{nombre}**", expanded=False):
                with st.spinner(f"Buscando partidos de {nombre}..."):
                    ultimos = obtener_ultimos_partidos(nombre, n=3)
                
                if not ultimos:
                    st.info(f"ℹ️ No se encontraron partidos terminados de {nombre} esta semana")
                    return
                
                for idx, p in enumerate(ultimos, start=1):
                    # Cabecera del partido: resultado con marcador
                    icono = "🏆" if p["ganador"] else "❌"
                    color_resultado = "#22c55e" if p["ganador"] else "#dc3545"
                    texto_resultado = "Victoria" if p["ganador"] else "Derrota"
                    
                    # Preservar el orden original del partido: si nuestro jugador
                    # era el de arriba en el spreadsheet, va a la izquierda; si
                    # era el de abajo, va a la derecha. Así no parece que siempre
                    # haya jugado de "local".
                    if p.get("jugador_primero", True):
                        izq_nombre, izq_color = nombre, color_jug
                        der_nombre, der_color = p['rival'], color_rival
                    else:
                        izq_nombre, izq_color = p['rival'], color_rival
                        der_nombre, der_color = nombre, color_jug
                    
                    st.markdown(
                        f"<div style='margin-top: {16 if idx > 1 else 6}px; padding: 10px 14px; "
                        f"background: rgba(150,150,150,0.10); border-left: 4px solid {color_jug}; "
                        f"border-radius: 6px;'>"
                        f"<div style='display: flex; justify-content: space-between; align-items: center; "
                        f"gap: 10px; flex-wrap: wrap;'>"
                        f"<span style='font-weight: 600; color: #444; font-size: 13px;'>"
                        f"#{idx} · <span style='color: #888;'>{p['dia']}</span></span>"
                        f"<span style='font-size: 14px;'>"
                        f"<span style='color: {izq_color}; font-weight: 700;'>{izq_nombre}</span> "
                        f"<span style='color: #888;'>vs</span> "
                        f"<span style='color: {der_color}; font-weight: 700;'>{der_nombre}</span>"
                        f"</span>"
                        f"<span style='font-weight: 700; font-size: 16px; color: {color_resultado};'>"
                        f"{icono} {p['marcador']} · {texto_resultado}</span>"
                        f"</div>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    
                    # Stats del jugador en ese partido: tabla compacta
                    stats = p["stats"]
                    if stats:
                        # Saltar columna del nombre (primera) y otras vacías;
                        # mostrar resto como pares etiqueta-valor en mini-grid.
                        # También se omite la columna "Resultado" (legs del partido)
                        # porque ya se muestra como marcador en la cabecera.
                        items = []
                        for k, v in stats.items():
                            k_str = str(k).strip()
                            k_lower = k_str.lower()
                            v_str = str(v).strip()
                            if not k_str or k_lower.startswith("unnamed"):
                                continue
                            if v_str.lower() in ('', 'nan'):
                                continue
                            # Saltar la celda que contiene el propio nombre del jugador
                            if v_str.lower() == nombre.lower():
                                continue
                            # Saltar la columna "Resultado" — info redundante con
                            # el marcador que ya aparece en la cabecera del partido
                            if "resultado" in k_lower:
                                continue
                            items.append((k_str, v_str))
                        
                        if items:
                            # Grid responsivo: ~4 columnas en desktop, se adapta
                            cells_html = ""
                            for k, v in items:
                                cells_html += (
                                    f"<div style='background: rgba(255,255,255,0.03); "
                                    f"padding: 8px 10px; border-radius: 5px; "
                                    f"border: 1px solid rgba(150,150,150,0.2);'>"
                                    f"<div style='font-size: 10px; color: #888; "
                                    f"text-transform: uppercase; letter-spacing: 0.3px; "
                                    f"margin-bottom: 3px;'>{k}</div>"
                                    f"<div style='font-size: 15px; font-weight: 600; "
                                    f"color: {color_jug};'>{v}</div>"
                                    f"</div>"
                                )
                            st.markdown(
                                f"<div style='display: grid; "
                                f"grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); "
                                f"gap: 8px; margin-top: 8px; margin-bottom: 4px;'>"
                                f"{cells_html}</div>",
                                unsafe_allow_html=True
                            )
    
    _render_ultimos_partidos(col_u1, j1, "#1f77b4", "#ff7f0e")
    _render_ultimos_partidos(col_u2, j2, "#ff7f0e", "#1f77b4")

    # J1 siempre saca primero (la ventaja de saque va al jugador 1 seleccionado).
    # Las funciones tienen `j1_saca_primero=True` como default, así que basta con
    # llamarlas sin pasar el parámetro.
    v1, v2 = prob_victoria(pr1, pr2)
    m180 = prob_180s(lam1, lam2, pr1=pr1, pr2=pr2)
    p_j1_mas, p_emp, p_j2_mas = quien_hace_mas_180s(lam1, lam2, pr1=pr1, pr2=pr2)
    hcaps = handicaps_legs(pr1, pr2)
    legs_total_dict = legs_totales(pr1, pr2)
    st.markdown("---")
    st.markdown("### 🎲 Mercados Disponibles")
    st.caption(
        f"🟢 value: la probabilidad del modelo supera la de la cuota en "
        f"{MARGEN_VALUE*100:.0f} puntos o más · 🟡 yield positivo pero dentro "
        f"del margen de error del modelo (no fiable) · ⚪ sin value · 🔴 negativo")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🏆 Victoria", "🎯 180s", "🥇 ¿Quién hace más 180?", "📐 Hándicaps", "📊 Total Legs", "🔢 Resultado exacto"])
    with tab1:
        st.markdown("#### 🏆 Mercado de Victoria")
        render_barras_enfrentadas(j1['nombre_original'], v1, j2['nombre_original'], v2, j1_color="#1f77b4", j2_color="#ff7f0e")
        st.markdown("---")
        col_v1, col_v2 = st.columns(2)
        with col_v1:
            st.markdown(f"<p style='color: #1f77b4; font-weight: bold;'>🎯 Gana {j1['nombre_original']}</p>", unsafe_allow_html=True)
            cuota_justa = prob_a_cuota(v1)
            mostrar_cuota_justa(cuota_justa)
            c1 = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="vic_j1", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{v1*100:.1f}% probabilidad")
            if c1 and c1 > 0:
                y = calcular_yield(v1, c1)
                yield_color = icono_yield(y, c1)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c1):
                    value_bets_list.append({"Mercado": f"Gana {j1['nombre_original']}", "Probabilidad": v1, "Cuota Justa": cuota_justa, "Cuota Bookie": c1, "Yield": y})
        with col_v2:
            st.markdown(f"<p style='color: #ff7f0e; font-weight: bold;'>🎯 Gana {j2['nombre_original']}</p>", unsafe_allow_html=True)
            cuota_justa = prob_a_cuota(v2)
            mostrar_cuota_justa(cuota_justa)
            c2 = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="vic_j2", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{v2*100:.1f}% probabilidad")
            if c2 and c2 > 0:
                y = calcular_yield(v2, c2)
                yield_color = icono_yield(y, c2)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c2):
                    value_bets_list.append({"Mercado": f"Gana {j2['nombre_original']}", "Probabilidad": v2, "Cuota Justa": prob_a_cuota(v2), "Cuota Bookie": c2, "Yield": y})
    with tab2:
        st.markdown("#### 🎯 Mercado de 180s (Distribución Poisson)")
        st.markdown(f"<h5 style='color: #1f77b4;'>{j1['nombre_original']}</h5>", unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**+0.5 180s** (Al menos 1 180)")
            cuota_justa = prob_a_cuota(m180["J1 +0.5"])
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_j1_05", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{m180['J1 +0.5']*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(m180["J1 +0.5"], c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j1['nombre_original']} +0.5 180s", "Probabilidad": m180["J1 +0.5"], "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        with col_b:
            st.markdown("**+1.5 180s** (Al menos 2 180s)")
            cuota_justa = prob_a_cuota(m180["J1 +1.5"])
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_j1_15", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{m180['J1 +1.5']*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(m180["J1 +1.5"], c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j1['nombre_original']} +1.5 180s", "Probabilidad": m180["J1 +1.5"], "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        # Mercados negativos para J1
        col_c, col_d = st.columns(2)
        with col_c:
            st.markdown("**-0.5 180s** (Menos de 1 180)")
            prob_neg = 1 - m180["J1 +0.5"]
            cuota_justa = prob_a_cuota(prob_neg)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_j1_neg05", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob_neg*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob_neg, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j1['nombre_original']} -0.5 180s", "Probabilidad": prob_neg, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        with col_d:
            st.markdown("**-1.5 180s** (Menos de 2 180s)")
            prob_neg = 1 - m180["J1 +1.5"]
            cuota_justa = prob_a_cuota(prob_neg)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_j1_neg15", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob_neg*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob_neg, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j1['nombre_original']} -1.5 180s", "Probabilidad": prob_neg, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        st.markdown("---")
        st.markdown(f"<h5 style='color: #ff7f0e;'>{j2['nombre_original']}</h5>", unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**+0.5 180s** (Al menos 1 180)")
            cuota_justa = prob_a_cuota(m180["J2 +0.5"])
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_j2_05", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{m180['J2 +0.5']*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(m180["J2 +0.5"], c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j2['nombre_original']} +0.5 180s", "Probabilidad": m180["J2 +0.5"], "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        with col_b:
            st.markdown("**+1.5 180s** (Al menos 2 180s)")
            cuota_justa = prob_a_cuota(m180["J2 +1.5"])
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_j2_15", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{m180['J2 +1.5']*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(m180["J2 +1.5"], c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j2['nombre_original']} +1.5 180s", "Probabilidad": m180["J2 +1.5"], "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        # Mercados negativos para J2
        col_c, col_d = st.columns(2)
        with col_c:
            st.markdown("**-0.5 180s** (Menos de 1 180)")
            prob_neg = 1 - m180["J2 +0.5"]
            cuota_justa = prob_a_cuota(prob_neg)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_j2_neg05", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob_neg*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob_neg, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j2['nombre_original']} -0.5 180s", "Probabilidad": prob_neg, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        with col_d:
            st.markdown("**-1.5 180s** (Menos de 2 180s)")
            prob_neg = 1 - m180["J2 +1.5"]
            cuota_justa = prob_a_cuota(prob_neg)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_j2_neg15", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob_neg*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob_neg, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j2['nombre_original']} -1.5 180s", "Probabilidad": prob_neg, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        st.markdown("---")
        st.markdown("##### 🤝 Total del partido (180s entre los dos)")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Total +1.5 180s** (2 o más entre los dos)")
            cuota_justa = prob_a_cuota(m180["Total +1.5"])
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_ambos_15", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{m180['Total +1.5']*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(m180["Total +1.5"], c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": "Total +1.5 180s", "Probabilidad": m180["Total +1.5"], "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        with col_b:
            st.markdown("**Total +2.5 180s** (3 o más entre los dos)")
            cuota_justa = prob_a_cuota(m180["Total +2.5"])
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_ambos_25", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{m180['Total +2.5']*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(m180["Total +2.5"], c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": "Total +2.5 180s", "Probabilidad": m180["Total +2.5"], "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        # Mercados negativos del total
        col_c, col_d = st.columns(2)
        with col_c:
            st.markdown("**Total -1.5 180s** (menos de 2 entre los dos)")
            prob_neg = 1 - m180["Total +1.5"]
            cuota_justa = prob_a_cuota(prob_neg)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_ambos_neg15", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob_neg*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob_neg, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": "Total -1.5 180s", "Probabilidad": prob_neg, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        with col_d:
            st.markdown("**Total -2.5 180s** (menos de 3 entre los dos)")
            prob_neg = 1 - m180["Total +2.5"]
            cuota_justa = prob_a_cuota(prob_neg)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key=f"180_ambos_neg25", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob_neg*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob_neg, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": "Total -2.5 180s", "Probabilidad": prob_neg, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
    with tab3:
        st.markdown("#### 🥇 ¿Quién hace más 180s?")
        render_mas_180s_barras(j1['nombre_original'], p_j1_mas, j2['nombre_original'], p_j2_mas, p_emp, j1_color="#1f77b4", j2_color="#ff7f0e")
        st.markdown("---")
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.markdown(f"<p style='color: #1f77b4; font-weight: bold;'>{j1['nombre_original']}</p>", unsafe_allow_html=True)
            cuota_justa = prob_a_cuota(p_j1_mas)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota {j1['nombre_original']}", min_value=1.01, max_value=50.0, value=None, step=0.05, key="mas_j1", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{p_j1_mas*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(p_j1_mas, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"Más 180s: {j1['nombre_original']}", "Probabilidad": p_j1_mas, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        with col_m2:
            st.markdown("**Empate**")
            cuota_justa = prob_a_cuota(p_emp)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota empate", min_value=1.01, max_value=50.0, value=None, step=0.05, key="mas_emp", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{p_emp*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(p_emp, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": "Empate 180s", "Probabilidad": p_emp, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        with col_m3:
            st.markdown(f"<p style='color: #ff7f0e; font-weight: bold;'>{j2['nombre_original']}</p>", unsafe_allow_html=True)
            cuota_justa = prob_a_cuota(p_j2_mas)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota {j2['nombre_original']}", min_value=1.01, max_value=50.0, value=None, step=0.05, key="mas_j2", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{p_j2_mas*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(p_j2_mas, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"Más 180s: {j2['nombre_original']}", "Probabilidad": p_j2_mas, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
    with tab4:
        st.markdown("#### 🎯 Hándicaps de Legs")
        
        # JUGADOR 1
        st.markdown(f"<h4 style='color: #1f77b4;'>{j1['nombre_original']}</h4>", unsafe_allow_html=True)
        
        # Hándicaps Positivos J1
        st.markdown("**Hándicaps Positivos**")
        col_pos_j1_1, col_pos_j1_2 = st.columns(2)
        with col_pos_j1_1:
            st.markdown("**+1.5 Legs**")
            prob = hcaps["J1 +1.5 Legs"]
            cuota_justa = prob_a_cuota(prob)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="hcap_j1_pos_15", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j1['nombre_original']} +1.5 Legs", "Probabilidad": prob, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        with col_pos_j1_2:
            st.markdown("**+2.5 Legs**")
            prob = hcaps["J1 +2.5 Legs"]
            cuota_justa = prob_a_cuota(prob)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="hcap_j1_pos_25", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j1['nombre_original']} +2.5 Legs", "Probabilidad": prob, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        # Hándicaps Negativos J1
        st.markdown("**Hándicaps Negativos**")
        col_neg_j1_1, col_neg_j1_2 = st.columns(2)
        with col_neg_j1_1:
            st.markdown("**-1.5 Legs**")
            prob = hcaps["J1 -1.5 Legs"]
            cuota_justa = prob_a_cuota(prob)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="hcap_j1_neg_15", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j1['nombre_original']} -1.5 Legs", "Probabilidad": prob, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        with col_neg_j1_2:
            st.markdown("**-2.5 Legs**")
            prob = hcaps["J1 -2.5 Legs"]
            cuota_justa = prob_a_cuota(prob)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="hcap_j1_neg_25", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j1['nombre_original']} -2.5 Legs", "Probabilidad": prob, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        st.divider()
        
        # JUGADOR 2
        st.markdown(f"<h4 style='color: #ff7f0e;'>{j2['nombre_original']}</h4>", unsafe_allow_html=True)
        
        # Hándicaps Positivos J2
        st.markdown("**Hándicaps Positivos**")
        col_pos_j2_1, col_pos_j2_2 = st.columns(2)
        with col_pos_j2_1:
            st.markdown("**+1.5 Legs**")
            prob = hcaps["J2 +1.5 Legs"]
            cuota_justa = prob_a_cuota(prob)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="hcap_j2_pos_15", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j2['nombre_original']} +1.5 Legs", "Probabilidad": prob, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        with col_pos_j2_2:
            st.markdown("**+2.5 Legs**")
            prob = hcaps["J2 +2.5 Legs"]
            cuota_justa = prob_a_cuota(prob)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="hcap_j2_pos_25", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j2['nombre_original']} +2.5 Legs", "Probabilidad": prob, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        # Hándicaps Negativos J2
        st.markdown("**Hándicaps Negativos**")
        col_neg_j2_1, col_neg_j2_2 = st.columns(2)
        with col_neg_j2_1:
            st.markdown("**-1.5 Legs**")
            prob = hcaps["J2 -1.5 Legs"]
            cuota_justa = prob_a_cuota(prob)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="hcap_j2_neg_15", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j2['nombre_original']} -1.5 Legs", "Probabilidad": prob, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        
        with col_neg_j2_2:
            st.markdown("**-2.5 Legs**")
            prob = hcaps["J2 -2.5 Legs"]
            cuota_justa = prob_a_cuota(prob)
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="hcap_j2_neg_25", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{prob*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(prob, c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": f"{j2['nombre_original']} -2.5 Legs", "Probabilidad": prob, "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
    with tab5:
        st.markdown("#### 📊 Total Legs (First to 4)")
        render_barras_enfrentadas("Más de 5.5", legs_total_dict["Más de 5.5"], "Menos de 5.5", legs_total_dict["Menos de 5.5"], j1_color="#28a745", j2_color="#dc3545")
        st.markdown("---")
        col_l1, col_l2 = st.columns(2)
        with col_l1:
            st.markdown("**Más de 5.5 Legs**")
            cuota_justa = prob_a_cuota(legs_total_dict["Más de 5.5"])
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="legs_mas", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{legs_total_dict['Más de 5.5']*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(legs_total_dict["Más de 5.5"], c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": "Más de 5.5 Legs", "Probabilidad": legs_total_dict["Más de 5.5"], "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
        with col_l2:
            st.markdown("**Menos de 5.5 Legs**")
            cuota_justa = prob_a_cuota(legs_total_dict["Menos de 5.5"])
            mostrar_cuota_justa(cuota_justa)
            c = st.number_input(f"Tu cuota", min_value=1.01, max_value=50.0, value=None, step=0.05, key="legs_menos", label_visibility="collapsed", placeholder="Introduce cuota")
            st.caption(f"{legs_total_dict['Menos de 5.5']*100:.1f}% probabilidad")
            if c and c > 0:
                y = calcular_yield(legs_total_dict["Menos de 5.5"], c)
                yield_color = icono_yield(y, c)
                st.metric("Yield", f"{yield_color} {'+' if y > 0 else ''}{y*100:.1f}%")
                if es_value(y, c):
                    value_bets_list.append({"Mercado": "Menos de 5.5 Legs", "Probabilidad": legs_total_dict["Menos de 5.5"], "Cuota Justa": cuota_justa, "Cuota Bookie": c, "Yield": y})
    with tab6:
        st.markdown("#### 🔢 Resultado exacto (First to 4)")
        st.caption(
            "Probabilidad de cada marcador final. Cada burbuja muestra el "
            "marcador y su cuota justa; la barra indica la probabilidad."
        )
        finales = simular_match(pr1, pr2)
        nom1 = j1["nombre_original"]
        nom2 = j2["nombre_original"]

        # Cabecera con los dos jugadores y su color
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;"
            f"font-weight:700;font-size:1.05rem;margin-bottom:8px;'>"
            f"<span style='color:#1f77b4'>{nom1}</span>"
            f"<span style='color:#ff7f0e'>{nom2}</span></div>",
            unsafe_allow_html=True,
        )

        # Marcadores: a la izquierda los que gana J1, a la derecha los de J2.
        # Cada fila enfrenta un marcador de J1 con su espejo de J2.
        filas_marc = [
            ((4, 0), (0, 4)),
            ((4, 1), (1, 4)),
            ((4, 2), (2, 4)),
            ((4, 3), (3, 4)),
        ]

        def _burbuja(l1, l2, p, color):
            """Devuelve el HTML de una burbuja de marcador."""
            cuota = prob_a_cuota(p)
            pct = p * 100
            ancho = max(2, min(100, pct * 3))  # escala visual de la barra
            return (
                f"<div style='border:2px solid {color};border-radius:14px;"
                f"padding:10px 14px;margin:6px 0;background:#ffffff;'>"
                f"<div style='font-size:1.35rem;font-weight:800;"
                f"color:#222;text-align:center;'>{l1} - {l2}</div>"
                f"<div style='background:#eee;border-radius:6px;height:8px;"
                f"margin-top:8px;overflow:hidden;'>"
                f"<div style='width:{ancho}%;height:8px;"
                f"background:{color};'></div></div>"
                f"<div style='font-size:0.8rem;color:#666;margin-top:4px;"
                f"text-align:center;'>{pct:.1f}%</div>"
                f"<div style='font-size:0.85rem;color:#444;margin-top:4px;"
                f"text-align:center;'>💡 Cuota justa: "
                f"<b>{cuota:.2f}</b></div>"
                f"</div>"
            )

        for (m_izq, m_der) in filas_marc:
            cizq, cder = st.columns(2)
            with cizq:
                p = finales.get(m_izq, 0.0)
                st.markdown(_burbuja(m_izq[0], m_izq[1], p, "#1f77b4"),
                            unsafe_allow_html=True)
            with cder:
                p = finales.get(m_der, 0.0)
                st.markdown(_burbuja(m_der[0], m_der[1], p, "#ff7f0e"),
                            unsafe_allow_html=True)

    if value_bets_list:
        st.markdown("---")
        st.markdown("### 💎 Resumen de Value Bets Encontradas")
        value_bets_list.sort(key=lambda x: x["Yield"], reverse=True)
        for vb in value_bets_list:
            yield_pct = vb["Yield"] * 100
            st.markdown(f"""
            <div style="
                border-left: 4px solid #28a745;
                padding: 15px;
                margin: 10px 0;
                background: linear-gradient(90deg, rgba(40,167,69,0.1) 0%, rgba(40,167,69,0.02) 100%);
                border-radius: 5px;
            ">
                <div style="display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center;">
                    <div style="flex: 1 1 100%; min-width: 0;">
                        <p style="margin: 0; font-size: 1.1em; font-weight: bold; color: #333;">{vb["Mercado"]}</p>
                    </div>
                    <div style="text-align: center; flex: 1 1 70px; white-space: nowrap;">
                        <p style="margin: 0; font-size: 0.8em; color: #666;">Probabilidad</p>
                        <p style="margin: 0; font-size: 1.1em; font-weight: bold; color: #1f77b4;">{vb["Probabilidad"]*100:.1f}%</p>
                    </div>
                    <div style="text-align: center; flex: 1 1 70px; white-space: nowrap;">
                        <p style="margin: 0; font-size: 0.8em; color: #666;">Cuota Justa</p>
                        <p style="margin: 0; font-size: 1.1em; font-weight: bold;">{vb["Cuota Justa"]:.2f}</p>
                    </div>
                    <div style="text-align: center; flex: 1 1 70px; white-space: nowrap;">
                        <p style="margin: 0; font-size: 0.8em; color: #666;">Cuota Bookie</p>
                        <p style="margin: 0; font-size: 1.1em; font-weight: bold; color: #ff7f0e;">{vb["Cuota Bookie"]:.2f}</p>
                    </div>
                    <div style="text-align: center; flex: 1 1 70px; white-space: nowrap;">
                        <p style="margin: 0; font-size: 0.8em; color: #666;">Yield</p>
                        <p style="margin: 0; font-size: 1.3em; font-weight: bold; color: #28a745;">+{yield_pct:.1f}%</p>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        st.success(f"✅ Se encontraron **{len(value_bets_list)}** mercados con value positivo")
    else:
        claves_cuota = ("vic_", "180_", "mas_", "hcap_", "legs_")
        hay_cuotas = any(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for k, v in st.session_state.items()
            if isinstance(k, str) and k.startswith(claves_cuota))
        if hay_cuotas:
            st.info("ℹ️ Ninguna de las cuotas introducidas tiene value "
                    "(🟢). Prueba con otros mercados de las pestañas.")
        else:
            st.info("✍️ Escribe la cuota de tu casa de apuestas en cualquier "
                    "mercado de las pestañas de arriba y aquí verás si tiene "
                    "value.")

def render_heatmap_estadisticas(stats_dict, titulo="📊 Comparativa de Estadísticas"):
    """Renderiza un heatmap (tabla coloreada) con las 5 métricas clave por jugador.

    Cada columna se colorea independientemente con gradiente rojo→amarillo→verde
    según el valor relativo del jugador en esa métrica. Esto evita que escalas distintas
    (ej. λ180s en 0-3 vs. % victoria en 0-100) se aplasten entre sí.
    """
    if not stats_dict:
        return

    df, cols_metricas = _extraer_metricas_jugadores(stats_dict)
    if df.empty:
        return

    st.subheader(titulo)
    st.caption("🟢 Mejor en cada métrica · 🔴 Peor · El gradiente es relativo al rango de cada columna")

    def color_celda(val, vmin, vmax):
        """Mapea un valor a un color de fondo rojo→amarillo→verde.
        Reemplaza Styler.background_gradient (que requiere matplotlib)."""
        if pd.isna(val) or vmin == vmax:
            return ''
        norm = (val - vmin) / (vmax - vmin)
        norm = max(0.0, min(1.0, norm))
        if norm < 0.5:
            r = 235
            g = int(80 + norm * 2 * 175)
            b = 80
        else:
            r = int(235 - (norm - 0.5) * 2 * 175)
            g = 200
            b = 80
        return f'background-color: rgba({r}, {g}, {b}, 0.55); color: #111; font-weight: 600;'

    def gradiente_columna(col):
        valores_validos = col.dropna()
        if len(valores_validos) == 0:
            return ['' for _ in col]
        vmin = valores_validos.min()
        vmax = valores_validos.max()
        return [color_celda(v, vmin, vmax) for v in col]

    styled = df.style.apply(
        gradiente_columna,
        subset=cols_metricas,
        axis=0
    ).format({
        "Media 180": lambda x: f"{x:.2f}" if pd.notna(x) else "—",
        "Promedio Puntos": lambda x: f"{x:.1f}" if pd.notna(x) else "—",
        "Checkout %": lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
        "% Victoria": lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
        "Puntuación Global": lambda x: f"{x:.1f}" if pd.notna(x) else "—",
    }).set_properties(**{
        'text-align': 'center',
    }).set_table_styles([
        {'selector': 'th', 'props': [('text-align', 'center'), ('font-weight', 'bold')]},
        {'selector': 'th.col_heading', 'props': [('background-color', '#1f2937'), ('color', 'white')]},
    ])

    st.dataframe(styled, use_container_width=True, hide_index=True)

def render_radar_multiple(stats_dict, titulo="🕸️ Perfil Comparativo (Pentágono)", key_prefix="radar"):
    """Pentágono múltiple superpuesto: 1 polígono por jugador, 5 vértices = 5 métricas.

    Permite filtrar jugadores con un multiselect (por defecto los 5 primeros, para
    no saturar visualmente cuando hay 8+ jugadores).

    Normalización fija por métrica:
        - Media 180: 0-3
        - Promedio Puntos: 0-100
        - Checkout %, % Victoria, Puntuación Global: 0-100
    """
    if not stats_dict:
        return

    df, cols_metricas = _extraer_metricas_jugadores(stats_dict)
    if df.empty:
        return

    # Rangos máximos para normalizar cada eje a 0-100% del radio
    rangos_max = {
        "Media 180": 3.0,
        "Promedio Puntos": 100.0,
        "Checkout %": 100.0,
        "% Victoria": 100.0,
        "Puntuación Global": 100.0,
    }

    st.subheader(titulo)

    # Multiselect: por defecto los 5 primeros para evitar saturar
    jugadores_disponibles = df["Jugador"].tolist()
    default_n = min(5, len(jugadores_disponibles))
    seleccionados = st.multiselect(
        "Jugadores a comparar (puedes añadir o quitar):",
        jugadores_disponibles,
        default=jugadores_disponibles[:default_n],
        key=f"{key_prefix}_multi_select"
    )

    if not seleccionados:
        st.info("Selecciona al menos un jugador para visualizar el pentágono.")
        return

    # Paleta D3/Tableau (10 colores que se distinguen bien entre sí)
    paleta = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"
    ]

    # Geometría del SVG
    svg_size = 480
    center_x = center_y = svg_size / 2
    radius = 150
    angle_offset = -90

    # Vértices del pentágono base + posiciones de etiquetas
    base_points = []
    label_pos = []
    for i in range(5):
        angle = angle_offset + i * 72
        rad = np.radians(angle)
        x = center_x + radius * np.cos(rad)
        y = center_y + radius * np.sin(rad)
        base_points.append((x, y))
        # Las etiquetas a un radio mayor para que no se solapen con el pentágono
        label_radius = radius + 38
        lx = center_x + label_radius * np.cos(rad)
        ly = center_y + label_radius * np.sin(rad)
        label_pos.append((lx, ly))

    svg = []
    svg.append(f'<svg width="{svg_size}" height="{svg_size}" xmlns="http://www.w3.org/2000/svg" style="background:white;">')

    # Círculos concéntricos de referencia (25%, 50%, 75%, 100%)
    for r_pct in [25, 50, 75, 100]:
        r = (r_pct / 100) * radius
        svg.append(f'<circle cx="{center_x}" cy="{center_y}" r="{r}" fill="none" stroke="#e5e7eb" stroke-width="0.8"/>')

    # Líneas radiales hacia los vértices
    for p in base_points:
        svg.append(f'<line x1="{center_x}" y1="{center_y}" x2="{p[0]}" y2="{p[1]}" stroke="#e5e7eb" stroke-width="0.8"/>')

    # Pentágono base
    pent_path = "M " + " L ".join([f"{p[0]},{p[1]}" for p in base_points]) + " Z"
    svg.append(f'<path d="{pent_path}" fill="none" stroke="#9ca3af" stroke-width="1"/>')

    # Polígono por cada jugador seleccionado
    for idx, jugador in enumerate(seleccionados):
        fila = df[df["Jugador"] == jugador].iloc[0]
        color = paleta[idx % len(paleta)]
        rgb = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))

        puntos_jugador = []
        for i, nombre_metrica in enumerate(cols_metricas):
            val = fila[nombre_metrica]
            if pd.isna(val):
                val = 0
            max_val = rangos_max[nombre_metrica]
            norm = min(1.0, max(0.0, val / max_val))
            angle = angle_offset + i * 72
            rad = np.radians(angle)
            r = norm * radius
            x = center_x + r * np.cos(rad)
            y = center_y + r * np.sin(rad)
            puntos_jugador.append((x, y))

        path = "M " + " L ".join([f"{p[0]},{p[1]}" for p in puntos_jugador]) + " Z"
        svg.append(f'<path d="{path}" fill="rgba({rgb[0]},{rgb[1]},{rgb[2]},0.18)" stroke="{color}" stroke-width="2.2"/>')

        # Puntos en cada vértice del polígono del jugador
        for p in puntos_jugador:
            svg.append(f'<circle cx="{p[0]}" cy="{p[1]}" r="3.2" fill="{color}" stroke="white" stroke-width="1.2"/>')

    # Etiquetas de las métricas en cada vértice
    for i, (lx, ly) in enumerate(label_pos):
        svg.append(
            f'<text x="{lx}" y="{ly}" text-anchor="middle" dominant-baseline="middle" '
            f'font-size="11" font-family="Arial, sans-serif" fill="#374151" font-weight="600">'
            f'{cols_metricas[i]}</text>'
        )

    svg.append('</svg>')
    svg_html = "".join(svg)

    # Layout: pentágono a la izquierda, leyenda a la derecha
    col_svg, col_leyenda = st.columns([2, 1])

    with col_svg:
        st.markdown(
            f'<div style="text-align:center;">{svg_html}</div>',
            unsafe_allow_html=True
        )

    with col_leyenda:
        st.markdown("**Leyenda**")
        for idx, jugador in enumerate(seleccionados):
            color = paleta[idx % len(paleta)]
            fila = df[df["Jugador"] == jugador].iloc[0]
            # Mostrar puntuación global como referencia rápida
            pg = fila["Puntuación Global"]
            pg_str = f"{pg:.1f}" if pd.notna(pg) else "—"
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;margin:6px 0;padding:6px;'
                f'background:rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08);'
                f'border-left:3px solid {color};border-radius:4px;">'
                f'<div style="width:14px;height:14px;background:{color};border-radius:3px;flex-shrink:0;"></div>'
                f'<div style="flex:1;">'
                f'<div style="font-size:13px;font-weight:600;color:#111;">{jugador}</div>'
                f'<div style="font-size:11px;color:#666;">PG: {pg_str}</div>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    st.caption(
        "💡 Cuanto más grande es el polígono, mejor perfil global. "
        "La forma indica el estilo del jugador (puntudo en 180s, equilibrado, etc.)."
    )

def render_small_multiples(stats_dict, titulo="📊 Ranking por Métrica"):
    """Small multiples con layout simétrico:
        - Puntuación Global destacada arriba ocupando toda la fila (más grande,
          con acento dorado para subrayar su importancia).
        - Las 4 métricas restantes en rejilla 2×2 simétrica debajo.
        - En móvil todo se apila a 1 columna.

    Cada mini-gráfico ordena los jugadores de mejor a peor en su métrica y los
    pinta con barras horizontales. El color va de verde (top del ranking) a rojo
    (último), no por valor absoluto, así el ranking se lee de un vistazo aunque
    los valores estén muy juntos.
    """
    if not stats_dict:
        return

    df, cols_metricas = _extraer_metricas_jugadores(stats_dict)
    if df.empty:
        return

    st.subheader(titulo)
    st.caption("Cada gráfico ordena a los jugadores de mejor a peor en esa métrica concreta. 🟢 mejor del ranking · 🔴 peor")

    # Formato del valor que se muestra al final de cada barra
    formatos = {
        "Media 180": lambda x: f"{x:.2f}",
        "Promedio Puntos": lambda x: f"{x:.1f}",
        "Checkout %": lambda x: f"{x:.1f}%",
        "% Victoria": lambda x: f"{x:.1f}%",
        "Puntuación Global": lambda x: f"{x:.1f}",
    }

    def _color_ranking(idx, n):
        """Gradiente verde→rojo según posición en el ranking (no según valor)."""
        norm = 1.0 if n == 1 else 1 - (idx / (n - 1))
        if norm >= 0.5:
            r = int(235 - (norm - 0.5) * 2 * 175)
            g = 200
            b = 80
        else:
            r = 235
            g = int(80 + norm * 2 * 175)
            b = 80
        return f"rgb({r},{g},{b})"

    def _render_card(metrica, destacada=False):
        """Construye el HTML de una tarjeta (mini-gráfico de una métrica)."""
        sub = df[["Jugador", metrica]].dropna(subset=[metrica]).copy()
        if sub.empty:
            return ""
        sub = sub.sort_values(by=metrica, ascending=False).reset_index(drop=True)
        max_val = sub[metrica].max()
        n = len(sub)

        # Dimensiones distintas si la tarjeta está destacada
        bar_height = 30 if destacada else 22
        font_size_value = 13 if destacada else 11
        font_size_name = 13 if destacada else 11
        name_width = 110 if destacada else 95
        title_size = 17 if destacada else 14
        margin_row = 7 if destacada else 5

        rows_html = ""
        for idx, row in sub.iterrows():
            jugador = row["Jugador"]
            valor = row[metrica]
            valor_str = formatos.get(metrica, lambda x: f"{x:.1f}")(valor)
            ancho_pct = max(6.0, (valor / max_val) * 100) if (max_val and max_val > 0) else 6.0
            color = _color_ranking(idx, n)

            rows_html += (
                f'<div style="display:flex;align-items:center;gap:10px;margin:{margin_row}px 0;">'
                f'<span style="font-size:{font_size_name}px;width:{name_width}px;flex-shrink:0;'
                f'color:#374151;font-weight:500;overflow:hidden;text-overflow:ellipsis;'
                f'white-space:nowrap;" title="{jugador}">{jugador}</span>'
                f'<div style="flex:1;background:rgba(0,0,0,0.05);border-radius:4px;height:{bar_height}px;">'
                f'<div style="width:{ancho_pct:.1f}%;background:{color};height:100%;border-radius:4px;'
                f'display:flex;align-items:center;justify-content:flex-end;padding-right:8px;'
                f'box-shadow:inset 0 0 0 1px rgba(0,0,0,0.04);">'
                f'<span style="color:white;font-size:{font_size_value}px;font-weight:700;'
                f'text-shadow:0 1px 1px rgba(0,0,0,0.25);">{valor_str}</span>'
                f'</div>'
                f'</div>'
                f'</div>'
            )

        # Estilo distinto para la tarjeta destacada (Puntuación Global)
        if destacada:
            card_style = (
                'grid-column: 1 / -1;'
                'background: linear-gradient(135deg, rgba(245,158,11,0.06) 0%, rgba(255,255,255,0.01) 100%);'
                'border: 2px solid #f59e0b;'
                'border-radius: 10px;'
                'padding: 18px 22px;'
                'box-shadow: 0 2px 8px rgba(245,158,11,0.08);'
            )
            title_color = "#b45309"
            title_extra = '<span style="font-size:11px;color:#92400e;font-weight:600;margin-left:8px;background:rgba(245,158,11,0.15);padding:2px 8px;border-radius:10px;">⭐ MÉTRICA CLAVE</span>'
        else:
            card_style = (
                'background: white;'
                'border: 1px solid #e5e7eb;'
                'border-radius: 8px;'
                'padding: 14px 16px;'
            )
            title_color = "#1f2937"
            title_extra = ""

        return (
            f'<div style="{card_style}">'
            f'<h5 style="margin:0 0 12px 0;color:{title_color};font-size:{title_size}px;'
            f'font-weight:700;border-bottom:2px solid #e5e7eb;padding-bottom:8px;'
            f'display:flex;align-items:center;">{metrica}{title_extra}</h5>'
            f'{rows_html}'
            f'</div>'
        )

    # Orden: Puntuación Global primero (destacada), luego las demás en orden fijo
    metrica_destacada = "Puntuación Global"
    orden_resto = ["Media 180", "Promedio Puntos", "Checkout %", "% Victoria"]
    metricas_resto = [m for m in orden_resto if m in cols_metricas]

    cards_html = '<div class="small-multiples-grid">'
    if metrica_destacada in cols_metricas:
        cards_html += _render_card(metrica_destacada, destacada=True)
    for metrica in metricas_resto:
        cards_html += _render_card(metrica, destacada=False)
    cards_html += '</div>'

    # CSS de rejilla: 2 columnas en desktop, 1 en móvil. Puntuación Global usa
    # `grid-column: 1 / -1` para ocupar toda la fila.
    st.markdown("""
    <style>
    .small-multiples-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 14px;
        margin: 10px 0 20px 0;
    }
    @media (max-width: 768px) {
        .small-multiples-grid {
            grid-template-columns: 1fr;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(cards_html, unsafe_allow_html=True)

def render_comparativa_completa(stats_dict, key_prefix="comp", tipo="radar"):
    """Heatmap + visualización extra. El parámetro `tipo` decide qué se añade debajo:
        - "radar":  pentágono múltiple superpuesto (varios jugadores a la vez)
        - "barras": small multiples (5 mini-gráficos de barras horizontales)
    """
    if not stats_dict:
        return

    render_heatmap_estadisticas(stats_dict, titulo="📊 Comparativa Visual de Estadísticas")
    st.markdown("")
    if tipo == "radar":
        render_radar_multiple(stats_dict, titulo="🕸️ Perfil Comparativo (Pentágono)", key_prefix=key_prefix)
    elif tipo == "barras":
        render_small_multiples(stats_dict, titulo="📊 Ranking por Métrica")


def render_tracking_predicciones(jugadores_resumen=None):
    """Renderiza la seccion de seguimiento de predicciones del modelo.

    Tiene varias partes:
      1) Boton para guardar el historico semanal de los jugadores.
      2) Boton/expander para verificar resultados de las predicciones.
      3) Panel de metricas por mercado (tasa de acierto y calibracion).
      4) Lista de partidos registrados.

    Parametros:
      jugadores_resumen: dict de jugadores del Resumen Semanal (para el
                         boton de guardar historico). Si es None, ese boton
                         avisa de que no hay datos.

    Pensada para usarse como seccion propia ('SEGUIMIENTO').
    """
    st.caption(
        "Comprueba, con el tiempo, lo que el modelo predijo frente a lo que "
        "realmente ocurrio."
    )

    # Si el modulo de predicciones no se pudo cargar (falta el archivo o sus
    # dependencias gspread/google-auth), mostramos el motivo y salimos sin
    # tumbar el resto de la app.
    if not _PREDICCIONES_OK:
        st.warning(
            "⚠️ La seccion de seguimiento no esta disponible: el modulo "
            "`predicciones.py` no se pudo cargar.\n\n"
            f"Detalle tecnico: `{_PREDICCIONES_ERROR}`\n\n"
            "Comprueba que el archivo **predicciones.py** esta subido al "
            "repositorio y que **gspread** y **google-auth** figuran en el "
            "archivo `requirements.txt`."
        )
        return

    # Segunda comprobacion: el modulo cargo, pero ¿estan las librerias de
    # Google y el secreto? Si falta algo, lo explicamos y salimos.
    if tracking_disponible is not None:
        disponible, motivo = tracking_disponible()
        if not disponible:
            st.warning(f"⚠️ Seguimiento no disponible: {motivo}")
            return

    # ── Parte 1: como registrar (el registro se hace desde Value Bets) ───────
    st.info(
        "📝 **Para registrar un partido**: ve a **Value Bets**, selecciona "
        "los dos jugadores y pulsa el boton **📝 Registrar** (debajo de "
        "Calcular). El partido se anade aqui para su seguimiento."
    )

    # Boton de diagnostico de la conexion con Google Sheets.
    if es_admin() and st.button("🔧 Probar conexion con Google Sheets", key="trk_btn_diag"):
        with st.spinner("Probando conexion..."):
            if diagnostico_conexion is not None:
                informe = diagnostico_conexion("")
            else:
                informe = "El modulo de predicciones no se cargo."
        st.code(informe, language="text")

    # ── Parte 2: verificacion automatica de resultados ───────────────────────
    with st.expander("✅ Verificar resultados de los partidos", expanded=False):
        st.markdown(
            "Comprueba automaticamente las predicciones pendientes contra "
            "los resultados reales de las pestanas de jornada. Cada "
            "prediccion se marca como **acierto (1)** o **fallo (0)**. Los "
            "partidos que aun no se hayan jugado quedan pendientes."
        )
        if not es_admin():
            st.caption("🔒 La verificación manual solo está disponible en "
                       "modo administrador. Se hace sola cada 15 minutos "
                       "durante las jornadas.")
        elif st.button("✅ Verificar resultados ahora", type="primary",
                       key="trk_btn_verificar"):
            with st.spinner("Comparando predicciones con los resultados "
                            "reales de las jornadas..."):
                res_ver = verificar_resultados()
            if res_ver["ok"]:
                st.success(
                    f"✅ Verificacion completada: "
                    f"**{res_ver['aciertos']}** aciertos, "
                    f"**{res_ver['fallos']}** fallos, "
                    f"{res_ver['sin_cambios']} ya estaban verificadas. "
                    f"Los partidos aun sin resultado quedan pendientes."
                )
                # Si quedaron partidos pendientes con motivo, mostrarlos
                # en un expander — muy util para detectar nombres mal
                # escritos a mano que impiden la verificacion.
                pdiag = res_ver.get("pendientes_diag") or {}
                if pdiag:
                    with st.expander(
                        f"⚠️ {len(pdiag)} partido(s) sin verificar — "
                        f"ver motivos"):
                        st.caption(
                            "Si un partido SI se jugo pero no se verifica, "
                            "suele ser porque el nombre del jugador "
                            "registrado no coincide con el de la pestana "
                            "de la jornada (casing, espacios, tildes). "
                            "Reregistralo desde Value Bets para que use "
                            "el nombre correcto."
                        )
                        for clave, motivo in sorted(pdiag.items()):
                            st.markdown(f"- **{clave}** → {motivo}")
                # Limpiar cache para que el panel de abajo se actualice
                cargar_predicciones.clear()
            else:
                st.error(f"❌ {res_ver['error']}")

    # ── Limpieza: archivar predicciones caducadas ───────────────────────────
    if es_admin() and archivar_caducadas is not None:
        with st.expander("🧹 Limpiar partidos no verificados", expanded=False):
            st.markdown(
                "Mueve a la pestaña **Predicciones caducadas** las "
                "predicciones de semanas ya cerradas que se quedaron sin "
                "verificar (las pestañas de jornada ya no tienen esos "
                "partidos). No se borra nada: se pueden consultar en esa "
                "pestaña. Las de la semana en curso no se tocan. Se hace "
                "solo en el cierre semanal."
            )
            if st.button("🧹 Archivar caducadas", key="trk_btn_archivar"):
                with st.spinner("Moviendo predicciones caducadas..."):
                    r = archivar_caducadas()
                if r["ok"]:
                    if r["movidas"]:
                        st.success(f"✅ {r['movidas']} predicciones "
                                   f"({r['partidos']} partidos) movidas a "
                                   f"'Predicciones caducadas'.")
                    else:
                        st.info("No había predicciones caducadas.")
                    cargar_predicciones.clear()
                else:
                    st.error(f"❌ {r['error']}")

    # ── Parte 3: panel de metricas de calibracion ────────────────────────────
    st.markdown("### 🎯 Calidad del modelo")

    # Leemos las predicciones de la fuente que el usuario tenga seleccionada
    # arriba en Value Bets (vb_fuente); si no, del primer URL disponible.
    fuente_metricas = st.session_state.get("vb_fuente", "")
    url_metricas = URLS.get(fuente_metricas, "")
    if not url_metricas and URLS:
        url_metricas = list(URLS.values())[0]

    with st.spinner("Leyendo predicciones registradas..."):
        df_pred = cargar_predicciones(url_metricas)

    if df_pred is None or df_pred.empty:
        st.info(
            "ℹ️ Aun no hay predicciones registradas (o no se pudo leer la "
            "hoja). Registra una jornada con el boton de arriba para empezar."
        )
        return

    # ── Separacion: modelo nuevo (desde el cambio) / historico ──────────────
    try:
        from comparativa import separar_por_modelo
        from config import MODELO_VERSION
        grupos = separar_por_modelo(df_pred)
    except Exception:
        grupos, MODELO_VERSION = {}, "v2"
    df_nuevo = grupos.get(MODELO_VERSION)
    df_hist = (pd.concat([g for v, g in grupos.items() if v != MODELO_VERSION])
               if any(v != MODELO_VERSION for v in grupos) else None)
    OPC_NUEVO = "🆕 A partir de ahora (modelo nuevo)"
    OPC_HIST = "📦 Histórico (modelo anterior)"
    OPC_TODO = "Todo"
    periodo = st.segmented_control(
        "Estadísticas de", [OPC_NUEVO, OPC_HIST, OPC_TODO],
        default=OPC_NUEVO, key="trk_periodo") or OPC_NUEVO
    if periodo == OPC_NUEVO:
        if df_nuevo is None or df_nuevo.empty:
            st.info(
                "🆕 Aún no hay partidos registrados con el modelo nuevo. Los "
                "que se registren desde ahora aparecerán aquí, separados del "
                "histórico. Mientras tanto puedes ver el **Histórico**."
            )
            render_comparativa_modelos(df_pred)
            return
        try:
            desde = pd.to_datetime(df_nuevo["Fecha registro"].astype(str),
                                   errors="coerce").min()
            st.caption(f"Partidos registrados con el modelo nuevo, desde el "
                       f"{desde:%d/%m/%Y}.")
        except Exception:
            pass
        df_vista = df_nuevo
    elif periodo == OPC_HIST:
        if df_hist is None or df_hist.empty:
            st.info("No hay partidos del modelo anterior.")
            render_comparativa_modelos(df_pred)
            return
        st.caption("Partidos registrados con el modelo anterior (hasta el "
                   "cambio de calibración).")
        df_vista = df_hist
    else:
        df_vista = df_pred

    metricas = calcular_metricas(df_vista)

    # Sin handicaps J2 duplicados, registros repetidos ni verificaciones a medias
    total_reg = len(limpiar_predicciones(df_vista))
    evaluadas = metricas["evaluadas"]
    pendientes = metricas["pendientes"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Registradas", total_reg)
    c2.metric("Verificadas", evaluadas)
    c3.metric("Pendientes", pendientes,
              help="Predicciones de esta semana cuyo resultado aun no se ha "
                   "verificado (se verificaran cuando el partido se juegue).")
    c4.metric("Caducadas", metricas.get("caducadas", 0),
              help="Predicciones de semanas ya cerradas que se quedaron sin "
                   "verificar. Las pestanas de jornada solo guardan la semana "
                   "en curso, asi que ya no se pueden comprobar. Casi siempre "
                   "son partidos que no llegaron a jugarse (un cruce de la "
                   "Final que no se dio, o un partido apuntado de madrugada "
                   "en el grupo o el dia equivocado, fallo ya corregido). "
                   "No cuentan en ninguna metrica.")

    if evaluadas == 0:
        st.info(
            "Hay predicciones registradas pero ninguna verificada todavia. "
            "Cuando los partidos terminen, rellena la columna **Acierto** "
            "de la hoja *Predicciones* (1 = acerto, 0 = fallo) y las "
            "metricas apareceran aqui."
        )
        render_comparativa_modelos(df_pred)
        return

    # Aviso de muestra pequena
    if evaluadas < 30:
        st.warning(
            f"⚠️ Solo hay {evaluadas} predicciones verificadas. Con tan "
            f"pocas, las cifras son muy ruidosas: tomalas como orientativas "
            f"hasta acumular bastantes mas."
        )

    # ── TARJETAS POR MERCADO ─────────────────────────────────────────────
    # Una tarjeta visual por mercado: nombre, tasa de acierto grande con
    # color semaforo, barra de progreso, "X de Y verificadas".
    por_merc = metricas.get("por_mercado", [])
    if por_merc:
        st.markdown("#### 🎯 Acierto por tipo de mercado")
        st.caption(
            "Tasa de acierto del modelo en cada mercado. Cuanto mas alta, "
            "mas fiables son sus predicciones en ese mercado."
        )

        def _color_tasa(tasa, n, azar):
            """Color semaforo segun cuanto supera la tasa de acierto al
            azar (50% binario, 33% H2H). El umbral verde/amarillo/rojo se
            calcula relativo a ese azar para que H2H se evalue justo.
            """
            if n < 15:
                return "#9aa0a6"  # gris: muestra insuficiente
            margen = tasa - azar  # cuanto supera al azar
            if margen >= 20:
                return "#28a745"  # verde: claramente mejor que azar
            if margen >= 5:
                return "#f4b400"  # amarillo: algo mejor que azar
            return "#d93025"      # rojo: cerca o por debajo del azar

        # Mostrar las tarjetas en 2 columnas
        for i in range(0, len(por_merc), 2):
            cols = st.columns(2)
            for j, col in enumerate(cols):
                if i + j >= len(por_merc):
                    continue
                m = por_merc[i + j]
                tasa = m["tasa"]
                n = m["verificadas"]
                ac = m["aciertos"]
                azar = m.get("azar", 50.0)
                color = _color_tasa(tasa, n, azar)
                nota = "Muestra insuficiente" if n < 15 else ""
                ancho = max(2, min(100, tasa))
                # Linea de azar para contexto
                ref = (f" · azar {azar:.0f}%"
                       if abs(azar - 50.0) > 0.1 else "")
                with col:
                    st.markdown(
                        f"<div style='border:1px solid #ddd;"
                        f"border-left:6px solid {color};border-radius:10px;"
                        f"padding:14px 16px;margin:6px 0;background:#fff;'>"
                        f"<div style='font-weight:700;font-size:0.95rem;"
                        f"color:#222;'>{m['mercado']}</div>"
                        f"<div style='font-size:2rem;font-weight:800;"
                        f"color:{color};margin-top:4px;'>{tasa:.1f}%</div>"
                        f"<div style='background:#eee;border-radius:6px;"
                        f"height:8px;margin-top:6px;overflow:hidden;'>"
                        f"<div style='width:{ancho}%;height:8px;"
                        f"background:{color};'></div></div>"
                        f"<div style='font-size:0.8rem;color:#666;"
                        f"margin-top:6px;'>{ac} de {n} verificadas{ref}"
                        + (f" · <span style='color:#9aa0a6;'>{nota}"
                           f"</span>" if nota else "")
                        + "</div></div>",
                        unsafe_allow_html=True,
                    )

    # ── CALIBRACION POR MERCADO ──────────────────────────────────────────
    # Una tabla coloreada + un grafico de barras por mercado.
    if por_merc and any(m.get("calibracion") for m in por_merc):
        st.markdown("---")
        st.markdown("#### 📊 Calibracion del modelo por mercado")
        st.caption(
            "Para cada mercado: la confianza media del modelo frente a la "
            "tasa real de acierto, agrupada por tramos. Si las dos barras "
            "se parecen, el modelo esta bien calibrado en ese tramo. "
            "Colores: 🟢 desviacion <5% · 🟡 5-15% · 🔴 >15% · ⬜ pocos datos."
        )

        def _color_calib(prob, real, n):
            """Color de fila segun desviacion entre prob predicha y real."""
            if n < 15:
                return "#9aa0a6"  # gris
            dif = abs(real - prob)
            if dif < 5:
                return "#28a745"
            if dif < 15:
                return "#f4b400"
            return "#d93025"

        for m in por_merc:
            calib = m.get("calibracion", [])
            if not calib:
                continue
            with st.expander(f"📈 {m['mercado']}  ·  {m['verificadas']} "
                             f"predicciones", expanded=False):
                # Tabla coloreada como HTML
                filas_html = []
                for t in calib:
                    color = _color_calib(t["prob_media"], t["real"], t["n"])
                    dif = abs(t["real"] - t["prob_media"])
                    nota = ""
                    if t["n"] < 15:
                        nota = "muestra insuficiente"
                    elif dif < 5:
                        nota = "bien calibrado"
                    elif dif < 15:
                        nota = "desviacion media"
                    else:
                        nota = "desviacion alta"
                    filas_html.append(
                        f"<tr>"
                        f"<td style='padding:8px 12px;border-left:5px solid "
                        f"{color};'>{t['rango']}</td>"
                        f"<td style='padding:8px 12px;text-align:right;'>"
                        f"{t['n']}</td>"
                        f"<td style='padding:8px 12px;text-align:right;'>"
                        f"{t['prob_media']:.1f}%</td>"
                        f"<td style='padding:8px 12px;text-align:right;'>"
                        f"{t['real']:.1f}%</td>"
                        f"<td style='padding:8px 12px;color:{color};"
                        f"font-weight:600;'>{nota}</td>"
                        f"</tr>"
                    )
                tabla = (
                    "<table style='width:100%;border-collapse:collapse;"
                    "font-size:0.9rem;background:#fff;border-radius:8px;"
                    "overflow:hidden;margin-bottom:14px;'>"
                    "<thead><tr style='background:#f1f3f4;'>"
                    "<th style='padding:8px 12px;text-align:left;'>"
                    "Tramo</th>"
                    "<th style='padding:8px 12px;text-align:right;'>"
                    "Predicciones</th>"
                    "<th style='padding:8px 12px;text-align:right;'>"
                    "Modelo predijo</th>"
                    "<th style='padding:8px 12px;text-align:right;'>"
                    "Ocurrio realmente</th>"
                    "<th style='padding:8px 12px;text-align:left;'>"
                    "Calidad</th>"
                    "</tr></thead><tbody>"
                    + "".join(filas_html) +
                    "</tbody></table>"
                )
                st.markdown(tabla, unsafe_allow_html=True)

    # ── Comparativa modelo anterior / modelo nuevo ──────────────────────────
    render_comparativa_modelos(df_pred)

    # ── Parte 4: lista de partidos registrados ───────────────────────────────
    # Una fila por partido (no por mercado), con su estado.
    if listar_partidos_registrados is not None:
        st.markdown("---")
        st.markdown("### 📋 Partidos registrados")
        lista = listar_partidos_registrados(df_vista)
        if not lista:
            st.info("Aun no hay partidos registrados.")
        else:
            st.caption(
                f"{len(lista)} partidos registrados. Cada partido incluye "
                f"sus mercados. Estado: ✅ verificado, ⏳ pendiente de "
                f"resultado, ⌛ caducado (semana cerrada sin resultado)."
            )
            # Filtro opcional por estado
            estados_disp = ["Todos", "✅ Verificado", "⏳ Pendiente",
                            "⌛ Caducado"]
            filtro = st.selectbox("Filtrar por estado", estados_disp,
                                  key="trk_filtro_partidos")
            if filtro != "Todos":
                lista = [p for p in lista if p["Estado"] == filtro]
            if not lista:
                st.info(f"No hay partidos con estado '{filtro}'.")
            else:
                df_lista = pd.DataFrame(lista)
                # Orden de columnas
                df_lista = df_lista[["Jornada", "Partido", "Semana",
                                     "Mercados", "Estado"]]
                st.dataframe(df_lista, use_container_width=True,
                             hide_index=True)


@st.cache_data(ttl=600, show_spinner=False)
def _comparativa_cacheada(df_limpio):
    from comparativa import comparar_retroactivo
    return comparar_retroactivo(df_limpio)


def render_comparativa_modelos(df_pred):
    """Seguimiento: modelo anterior (v1) frente al calibrado (v2)."""
    try:
        from comparativa import (resumen_retroactivo, calibracion_retroactiva,
                                 separar_por_modelo)
        from config import MODELOS, MODELO_VERSION
    except Exception as e:
        st.caption(f"Comparativa de modelos no disponible ({e}).")
        return

    st.markdown("---")
    st.markdown("### 🔬 Modelo anterior vs modelo nuevo")
    st.caption(
        f"**Antes** = {MODELOS['v1']['nombre']}. "
        f"**Ahora** = {MODELOS[MODELO_VERSION]['nombre']}. "
        "Brier y log-loss: cuanto más bajos, mejor (0,25 de Brier = tirar una "
        "moneda). Acierto: % de veces que sale el lado que elige el modelo."
    )
    df_l = limpiar_predicciones(df_pred)
    tab_retro, tab_vivo = st.tabs(["🔁 Mismos partidos (recalculados)",
                                   "📡 Desde el cambio (en vivo)"])

    with tab_retro:
        with st.spinner("Recalculando los partidos con el modelo nuevo..."):
            bt = _comparativa_cacheada(df_l)
        tabla, glob = resumen_retroactivo(bt)
        if tabla.empty:
            st.info("Aún no hay partidos verificados del modelo anterior.")
        else:
            st.caption(
                f"Los {glob['partidos']} partidos verificados del modelo "
                "anterior, recalculados con el modelo nuevo a partir de los "
                "datos que usó entonces. ⚠️ El modelo nuevo se ajustó con estos "
                "mismos partidos, así que esta comparación le favorece: la "
                "prueba de verdad es la pestaña *en vivo*."
            )
            m1, m2, m3 = st.columns(3)
            m1.metric("Líneas comparadas", f"{glob['lineas']:,}".replace(",", "."))
            m2.metric("Brier global", f"{glob['brier_ahora']:.4f}",
                      delta=f"{glob['brier_ahora'] - glob['brier_antes']:+.4f}",
                      delta_color="inverse",
                      help=f"Antes: {glob['brier_antes']:.4f}")
            m3.metric("Acierto global", f"{glob['acierto_ahora']:.1f}%",
                      delta=f"{glob['acierto_ahora'] - glob['acierto_antes']:+.1f} pts",
                      help=f"Antes: {glob['acierto_antes']:.1f}%")

            vista = tabla.copy()
            vista["Mejora Brier"] = np.where(
                vista["Brier antes"] > 0,
                100 * (vista["Brier antes"] - vista["Brier ahora"])
                / vista["Brier antes"], np.nan)
            vista["Veredicto"] = [
                ("🟢 mejor" if (b_n < b_o if b_n == b_n else l_n < l_o)
                 else "🔴 peor")
                for b_o, b_n, l_o, l_n in zip(vista["Brier antes"],
                                              vista["Brier ahora"],
                                              vista["Log-loss antes"],
                                              vista["Log-loss ahora"])]
            st.dataframe(
                vista[["Mercado", "N", "Acierto antes", "Acierto ahora",
                       "Brier antes", "Brier ahora", "Mejora Brier",
                       "Log-loss antes", "Log-loss ahora", "Veredicto"]],
                hide_index=True, use_container_width=True,
                column_config={
                    "Acierto antes": st.column_config.NumberColumn(format="%.1f%%"),
                    "Acierto ahora": st.column_config.NumberColumn(format="%.1f%%"),
                    "Brier antes": st.column_config.NumberColumn(format="%.4f"),
                    "Brier ahora": st.column_config.NumberColumn(format="%.4f"),
                    "Mejora Brier": st.column_config.NumberColumn(format="%.1f%%"),
                    "Log-loss antes": st.column_config.NumberColumn(format="%.3f"),
                    "Log-loss ahora": st.column_config.NumberColumn(format="%.3f"),
                })

            mercados_cal = [m for m in ("Ganador", "Handicap legs",
                                        "Total legs", "180s")
                            if m in set(bt["mercado"])]
            if mercados_cal:
                st.markdown("**Calibración: lo que predice frente a lo que pasa**")
                merc = st.segmented_control("Mercado", mercados_cal,
                                            default=mercados_cal[0],
                                            key="cmp_cal_mercado")
                cal = calibracion_retroactiva(bt, merc or mercados_cal[0])
                if not cal.empty:
                    try:
                        import altair as alt
                        base = alt.Chart(cal)
                        diag = alt.Chart(pd.DataFrame({"x": [50, 100], "y": [50, 100]})
                                         ).mark_line(strokeDash=[4, 4], color="#9aa0a6"
                                         ).encode(x="x", y="y")
                        puntos = base.mark_line(point=True).encode(
                            x=alt.X("Predicho:Q", title="Predicho (%)",
                                    scale=alt.Scale(domain=[50, 100])),
                            y=alt.Y("Real:Q", title="Ocurrió (%)",
                                    scale=alt.Scale(domain=[0, 100])),
                            color=alt.Color("Modelo:N", scale=alt.Scale(
                                domain=["Antes", "Ahora"],
                                range=["#9aa0a6", "#1f77b4"])),
                            tooltip=["Modelo", "Tramo", "N",
                                     alt.Tooltip("Predicho:Q", format=".1f"),
                                     alt.Tooltip("Real:Q", format=".1f")])
                        st.altair_chart((diag + puntos).properties(height=300),
                                        use_container_width=True)
                        st.caption("Cuanto más cerca de la diagonal, mejor "
                                   "calibrado.")
                    except Exception:
                        pass
                    st.dataframe(cal, hide_index=True, use_container_width=True,
                                 column_config={
                                     "Predicho": st.column_config.NumberColumn(format="%.1f%%"),
                                     "Real": st.column_config.NumberColumn(format="%.1f%%")})

    with tab_vivo:
        grupos = separar_por_modelo(df_l)
        nuevo = grupos.get(MODELO_VERSION)
        m_nuevo = calcular_metricas(nuevo) if nuevo is not None else None
        if m_nuevo is None or m_nuevo["evaluadas"] == 0:
            st.info(
                "📡 Todavía no hay predicciones verificadas del modelo nuevo. "
                "Desde que subas esta versión, cada partido registrado se "
                f"marca como **{MODELO_VERSION}** en la columna *Modelo* de la "
                "hoja y aquí irán apareciendo sus resultados reales al lado "
                "de los del modelo anterior."
            )
            return
        filas = []
        for v, sub in grupos.items():
            m = calcular_metricas(sub)
            if m["evaluadas"] == 0:
                continue
            fila = {"Modelo": f"{v} · {MODELOS.get(v, {}).get('nombre', '')}",
                    "Verificadas": m["evaluadas"],
                    "Acierto": m["tasa_acierto"],
                    "Brier": m["brier"]}
            for pm in m["por_mercado"]:
                fila[pm["mercado"]] = pm["tasa"]
            filas.append(fila)
        tabla_v = pd.DataFrame(filas)
        if m_nuevo["evaluadas"] < 300:
            st.warning(
                f"⚠️ El modelo nuevo solo lleva {m_nuevo['evaluadas']} "
                "predicciones verificadas (unos "
                f"{max(1, m_nuevo['evaluadas'] // 14)} partidos). Hasta tener "
                "varias semanas, las diferencias pueden ser ruido."
            )
        st.dataframe(
            tabla_v, hide_index=True, use_container_width=True,
            column_config={c: st.column_config.NumberColumn(format="%.1f%%")
                           for c in tabla_v.columns
                           if c not in ("Modelo", "Verificadas", "Brier")}
            | {"Brier": st.column_config.NumberColumn(format="%.4f")})
        st.caption("Acierto por mercado en %. El Brier del modelo nuevo debería "
                   "quedar por debajo del anterior.")


def render_historico(df_hist, jugadores_resumen=None):
    """Renderiza la seccion de historico: lista de jugadores acumulados por
    semanas, con buscador y graficos de evolucion. Incluye el boton para
    guardar la semana actual en el historico.

    Parametros:
      df_hist:           DataFrame devuelto por cargar_historico().
      jugadores_resumen: dict de jugadores del Resumen Semanal, para el
                         boton de guardar la semana.
    """
    st.caption(
        "Datos guardados al final de cada jornada. Aqui se acumulan semana "
        "a semana para ver la evolucion de cada jugador."
    )

    # ── Boton: guardar la semana actual en el historico ───────────────────
    with st.expander("💾 Guardar historico de la semana", expanded=False):
        st.markdown(
            "Guarda una *foto* de las estadisticas actuales de todos los "
            "jugadores (del Resumen Semanal). Hazlo al final de cada jornada "
            "para tener un registro que consultar en el futuro. Si ya "
            "guardaste esta semana, se sobrescribe con los datos actuales."
        )
        if not es_admin():
            st.caption("🔒 Solo disponible en modo administrador. El cierre "
                       "semanal del domingo lo guarda automáticamente.")
        elif guardar_historico_semana is None:
            st.info("La funcion de historico no esta disponible.")
        elif not jugadores_resumen:
            st.warning(
                "No hay datos de jugadores del Resumen Semanal para guardar."
            )
        else:
            st.caption(f"Se guardarian {len(jugadores_resumen)} jugadores.")
            if st.button("💾 Guardar historico ahora", type="primary",
                         key="hist_btn_guardar"):
                with st.spinner("Guardando historico..."):
                    res = guardar_historico_semana(jugadores_resumen)
                if res["ok"]:
                    if res["sobrescrita"]:
                        st.success(
                            f"♻️ Semana del {res['fecha']} actualizada: "
                            f"{res['guardados']} jugadores guardados "
                            f"(se sobrescribio la version anterior)."
                        )
                    else:
                        st.success(
                            f"✅ Guardado el historico de la semana del "
                            f"{res['fecha']}: {res['guardados']} jugadores."
                        )
                    # Refrescar la cache para que la tabla muestre lo nuevo
                    try:
                        cargar_historico.clear()
                    except Exception:
                        pass
                else:
                    st.error(f"❌ {res['error']}")

    if df_hist is None or df_hist.empty:
        st.info(
            "Todavia no hay datos en el historico. Usa el boton **💾 Guardar "
            "historico de la semana** de arriba al final de una jornada "
            "para empezar a acumular datos aqui."
        )
        return

    # Semanas y jugadores disponibles
    semanas = sorted(df_hist["Fecha sabado"].astype(str).unique())
    jugadores = sorted(df_hist["Jugador"].astype(str).unique())
    st.markdown(
        f"**{len(jugadores)} jugadores** · **{len(semanas)} semanas** "
        f"guardadas ({semanas[0]} → {semanas[-1]})"
    )

    # ── Buscador de jugador ───────────────────────────────────────────────
    st.markdown("### 🔎 Buscar jugador")
    texto = st.text_input(
        "Escribe el nombre del jugador",
        key="hist_buscar",
        placeholder="Ej: Morris",
        label_visibility="collapsed",
    )

    if texto and texto.strip():
        t = texto.strip().lower()
        coincidencias = [j for j in jugadores if t in j.lower()]
        if not coincidencias:
            st.warning(f"Ningun jugador coincide con '{texto}'.")
        else:
            # Si hay varias coincidencias, dejar elegir
            if len(coincidencias) > 1:
                jugador_sel = st.selectbox(
                    "Varios jugadores coinciden, elige uno:",
                    coincidencias, key="hist_sel_jug")
            else:
                jugador_sel = coincidencias[0]

            _render_evolucion_jugador(df_hist, jugador_sel)
    else:
        st.caption("Escribe un nombre arriba para ver la evolucion de un "
                   "jugador, o consulta la tabla completa mas abajo.")

    # ── Tabla completa ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📋 Todos los datos")
    # Filtro opcional por semana
    semana_filtro = st.selectbox(
        "Filtrar por semana (o todas)",
        ["Todas"] + semanas,
        key="hist_filtro_semana",
    )
    df_mostrar = df_hist.copy()
    if semana_filtro != "Todas":
        df_mostrar = df_mostrar[
            df_mostrar["Fecha sabado"].astype(str) == semana_filtro]
    # Ordenar por semana y luego por PR descendente
    if "PR" in df_mostrar.columns:
        df_mostrar = df_mostrar.sort_values(
            ["Fecha sabado", "PR"], ascending=[True, False])
    st.dataframe(df_mostrar, use_container_width=True, hide_index=True)


def _render_evolucion_jugador(df_hist, jugador):
    """Muestra la evolucion semana a semana de un jugador.

    Estructura:
      1) Selector de semana → vista detallada de esa semana usando el
         mismo layout que 'Resultados y Estadisticas' (sin flechas).
      2) Graficos de evolucion semana a semana.
      3) Tabla con todos los datos del jugador.
    """
    df_j = df_hist[df_hist["Jugador"].astype(str) == jugador].copy()
    if df_j.empty:
        st.warning(f"No hay datos de {jugador}.")
        return

    df_j = df_j.sort_values("Fecha sabado")
    st.markdown(f"### 📈 Evolucion de {jugador}")
    st.caption(f"{len(df_j)} semanas registradas.")

    # ── 1) Vista detallada de UNA semana, estilo 'Resultados' ─────────────
    semanas = df_j["Fecha sabado"].astype(str).tolist()
    semana_sel = st.selectbox(
        "📅 Ver semana",
        semanas,
        index=len(semanas) - 1,  # por defecto, la mas reciente
        key=f"hist_sem_jug_{jugador}",
    )
    fila = df_j[df_j["Fecha sabado"].astype(str) == semana_sel].iloc[0]

    # Construimos un dict con las claves que render_jugador_visual espera
    # (sinonimos del Sheet de jornadas). Formateamos cada valor como string
    # con el aspecto deseado:
    #   - Victorias y derrotas: enteros (sin decimales)
    #   - Checkout y % victoria: porcentaje sin decimales (ej. "68%")
    #   - El resto: numero con coma decimal espanola
    def _ent(v):  # entero sin decimales
        return str(int(round(safe_float(v))))
    def _pct(v): # porcentaje entero con %
        return f"{int(round(safe_float(v)))}%"
    def _dec(v, n=2):  # decimal con coma
        return f"{safe_float(v):.{n}f}".replace(".", ",")

    stats_para_render = {
        "puntuación global":     _dec(fila.get("PR", 0), 2),
        "media 180 por partida": _dec(fila.get("Media 180s", 0), 2),
        "promedio puntos total": _dec(fila.get("Promedio dardos", 0), 2),
        "legs por partido":      _dec(fila.get("Legs por partido", 0), 2),
        "promedio checkouts":    _pct(fila.get("Checkout %", 0)),
        "número victorias":      _ent(fila.get("Victorias", 0)),
        "número derrotas":       _ent(fila.get("Derrotas", 0)),
        "porcentaje victoria":   _pct(fila.get("% Victorias", 0)),
        "índice volatilidad":    _dec(fila.get("Volatilidad", 0), 2),
    }

    st.markdown(f"#### Datos de la semana del **{semana_sel}**")
    # mostrar_tendencias=False para que NO salgan flechas (no aplican aqui)
    render_jugador_visual(
        jugador.lower(),
        stats_para_render,
        stats_resumen=None,
        selected="Historico",
        mostrar_tendencias=False,
    )

    # ── 2) Graficos de evolucion semana a semana ──────────────────────────
    st.markdown("---")
    st.markdown("#### 📊 Evolucion entre semanas")
    if len(df_j) < 2:
        st.info("Solo hay una semana registrada. Los graficos de evolucion "
                "apareceran cuando haya al menos dos semanas.")
    else:
        metricas = [
            ("PR", "PR (Puntuacion Global)"),
            ("Media 180s", "Media de 180s por partido"),
            ("Promedio dardos", "Promedio de puntos"),
            ("Checkout %", "Checkout %"),
            ("% Victorias", "% de victorias"),
            ("Volatilidad", "Indice de volatilidad"),
        ]
        df_idx = df_j.set_index("Fecha sabado")
        for col, etiqueta in metricas:
            if col not in df_j.columns:
                continue
            st.markdown(f"**{etiqueta}**")
            st.line_chart(df_idx[[col]], height=200)

    # ── 3) Tabla con todos los datos del jugador ──────────────────────────
    st.markdown("---")
    st.markdown("#### 📋 Datos por semana")
    st.dataframe(df_j, use_container_width=True, hide_index=True)


def render_banner_proxima_jornada(proxima_nombre, proxima_hora,
                                    proxima_dia, tiempo_restante=None):
    """Burbuja compacta para mostrar 'Proxima jornada' en la cabecera de
    LIVE cuando ya hay datos cargados pero la hora oficial todavia no ha
    llegado. Misma estetica que la tarjeta interior del empty state pero
    sin el wrapper grande.
    """
    valor_tiempo = tiempo_restante or "—"
    html = f"""
    <div style='background:#fff; border:1px solid #e2e8f0;
                border-radius:14px; padding:20px 24px;
                margin:8px 0 20px;'>
        <div style='font-size:0.75rem; color:#64748b;
                    text-transform:uppercase; letter-spacing:0.08em;
                    font-weight:600; margin-bottom:6px;'>
            ⏭️ Próxima jornada
        </div>
        <div style='font-size:1.2rem; font-weight:700;
                    color:#0f172a; margin-bottom:18px;'>
            {proxima_nombre}
        </div>
        <div style='display:grid;
                    grid-template-columns:repeat(3, 1fr);
                    gap:14px; text-align:center;'>
            <div style='padding:12px 8px; background:#f8fafc;
                        border-radius:10px;'>
                <div style='font-size:1.3rem; margin-bottom:4px;'>📅</div>
                <div style='font-size:0.7rem; color:#64748b;
                            text-transform:uppercase;
                            letter-spacing:0.05em; font-weight:600;
                            margin-bottom:2px;'>Día</div>
                <div style='font-size:0.95rem; font-weight:700;
                            color:#0f172a;'>{proxima_dia or "—"}</div>
            </div>
            <div style='padding:12px 8px; background:#f8fafc;
                        border-radius:10px;'>
                <div style='font-size:1.3rem; margin-bottom:4px;'>🕒</div>
                <div style='font-size:0.7rem; color:#64748b;
                            text-transform:uppercase;
                            letter-spacing:0.05em; font-weight:600;
                            margin-bottom:2px;'>Hora</div>
                <div style='font-size:0.95rem; font-weight:700;
                            color:#0f172a;'>{proxima_hora or "—"}</div>
            </div>
            <div style='padding:12px 8px; background:#eff6ff;
                        border-radius:10px; border:1px solid #dbeafe;'>
                <div style='font-size:1.3rem; margin-bottom:4px;'>⏳</div>
                <div style='font-size:0.7rem; color:#1e40af;
                            text-transform:uppercase;
                            letter-spacing:0.05em; font-weight:600;
                            margin-bottom:2px;'>Faltan</div>
                <div style='font-size:0.95rem; font-weight:700;
                            color:#1e40af;'>{valor_tiempo}</div>
            </div>
        </div>
    </div>
    """
    html_compacto = " ".join(line.strip() for line in html.splitlines()
                              if line.strip())
    st.markdown(html_compacto, unsafe_allow_html=True)


def render_empty_state_live(titulo_principal=None,
                              proxima_nombre=None,
                              proxima_hora=None,
                              proxima_dia=None,
                              tiempo_restante=None,
                              motivo=None):
    """Empty state moderno para LIVE.

    Muestra una tarjeta a todo el ancho con icono, mensaje principal y la
    informacion de la proxima jornada (si la hay). Se usa cuando no hay
    datos en directo todavia.

    El HTML se construye como un UNICO string para evitar que Streamlit
    lo "sanee" en trozos y muestre HTML literal en pantalla (bug
    detectado con .append a lista).
    """
    titulo = titulo_principal or "Sin partidos en directo ahora mismo"
    motivo_html = (f"<div style='color:#64748b; font-size:1rem; "
                   f"margin-bottom:32px;'>{motivo}</div>") if motivo else ""

    if proxima_nombre:
        valor_tiempo = tiempo_restante or "—"
        tarjeta_proxima = f"""
        <div style='background:#fff; border:1px solid #e2e8f0;
                    border-radius:14px; padding:28px 24px;
                    margin:24px 0 16px;'>
            <div style='font-size:0.75rem; color:#64748b;
                        text-transform:uppercase; letter-spacing:0.08em;
                        font-weight:600; margin-bottom:6px;'>
                ⏭️ Próxima jornada
            </div>
            <div style='font-size:1.3rem; font-weight:700;
                        color:#0f172a; margin-bottom:24px;'>
                {proxima_nombre}
            </div>
            <div style='display:grid;
                        grid-template-columns:repeat(3, 1fr);
                        gap:16px; text-align:center;'>
                <div style='padding:14px 8px; background:#f8fafc;
                            border-radius:10px;'>
                    <div style='font-size:1.5rem; margin-bottom:6px;'>📅</div>
                    <div style='font-size:0.7rem; color:#64748b;
                                text-transform:uppercase;
                                letter-spacing:0.05em; font-weight:600;
                                margin-bottom:2px;'>Día</div>
                    <div style='font-size:0.95rem; font-weight:700;
                                color:#0f172a;'>{proxima_dia or "—"}</div>
                </div>
                <div style='padding:14px 8px; background:#f8fafc;
                            border-radius:10px;'>
                    <div style='font-size:1.5rem; margin-bottom:6px;'>🕒</div>
                    <div style='font-size:0.7rem; color:#64748b;
                                text-transform:uppercase;
                                letter-spacing:0.05em; font-weight:600;
                                margin-bottom:2px;'>Hora</div>
                    <div style='font-size:0.95rem; font-weight:700;
                                color:#0f172a;'>{proxima_hora or "—"}</div>
                </div>
                <div style='padding:14px 8px; background:#eff6ff;
                            border-radius:10px; border:1px solid #dbeafe;'>
                    <div style='font-size:1.5rem; margin-bottom:6px;'>⏳</div>
                    <div style='font-size:0.7rem; color:#1e40af;
                                text-transform:uppercase;
                                letter-spacing:0.05em; font-weight:600;
                                margin-bottom:2px;'>Faltan</div>
                    <div style='font-size:0.95rem; font-weight:700;
                                color:#1e40af;'>{valor_tiempo}</div>
                </div>
            </div>
        </div>
        """
    else:
        tarjeta_proxima = ""

    html = f"""
    <div style='text-align:center; padding:56px 32px; margin:24px 0;
                width:100%; box-sizing:border-box;
                background:linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
                border-radius:20px; border:1px solid #e2e8f0;
                box-shadow:0 4px 16px rgba(0,0,0,0.04);'>
        <div style='font-size:72px; margin-bottom:16px;
                    filter:grayscale(0.2);'>🎯</div>
        <div style='font-size:1.5rem; font-weight:700; color:#0f172a;
                    margin-bottom:8px;'>{titulo}</div>
        {motivo_html}
        {tarjeta_proxima}
        <div style='color:#94a3b8; font-size:0.9rem; margin-top:16px;'>
            Mientras tanto, consulta
            <strong style='color:#475569;'>📊 Resultados y estadísticas</strong>
            o <strong style='color:#475569;'>📚 Histórico</strong>.
        </div>
    </div>
    """
    # IMPORTANTE: st.markdown con unsafe_allow_html interpreta lineas con
    # 4+ espacios iniciales como bloque de codigo Markdown, mostrando el
    # HTML literal en pantalla. Compactamos el HTML a una sola linea para
    # evitarlo completamente.
    html_compacto = " ".join(line.strip() for line in html.splitlines()
                              if line.strip())
    st.markdown(html_compacto, unsafe_allow_html=True)


def calcular_tiempo_restante(proxima_dia, proxima_hora):
    """Calcula un string tipo '2h 15min' hasta la proxima jornada.

    proxima_dia puede ser 'Hoy', 'Mañana' o un texto con fecha como
    'Lunes 02/06'. proxima_hora es 'HH:MM'.

    Devuelve un string o None si no se puede calcular.
    """
    if not proxima_dia or not proxima_hora:
        return None
    try:
        from datetime import datetime, timedelta
        try:
            from zoneinfo import ZoneInfo
            ahora = datetime.now(ZoneInfo("Europe/Madrid"))
        except Exception:
            ahora = datetime.now()
        h, m = [int(x) for x in proxima_hora.split(":")]

        if proxima_dia.lower() == "hoy":
            objetivo = ahora.replace(hour=h, minute=m,
                                     second=0, microsecond=0)
        elif proxima_dia.lower() == "mañana":
            objetivo = (ahora + timedelta(days=1)).replace(
                hour=h, minute=m, second=0, microsecond=0)
        else:
            # Formato 'Lunes 02/06' o similar — parsear la fecha
            import re
            mtc = re.search(r"(\d{1,2})/(\d{1,2})", proxima_dia)
            if not mtc:
                return None
            dia = int(mtc.group(1))
            mes = int(mtc.group(2))
            anio = ahora.year
            objetivo = ahora.replace(month=mes, day=dia, hour=h,
                                     minute=m, second=0, microsecond=0)
            if objetivo < ahora:
                objetivo = objetivo.replace(year=anio + 1)

        diff = objetivo - ahora.replace(tzinfo=objetivo.tzinfo)
        total_seg = int(diff.total_seconds())
        if total_seg < 0:
            return None
        horas = total_seg // 3600
        minutos = (total_seg % 3600) // 60
        if horas == 0:
            return f"{minutos} min"
        if horas < 24:
            return f"{horas}h {minutos:02d}min"
        dias = horas // 24
        h_rest = horas % 24
        return f"{dias}d {h_rest}h"
    except Exception:
        return None



def render_top10_pr_historico(df_hist):
    """Top 10 jugadores por PR medio historico.

    Agrupa todas las filas del historico por jugador, calcula el PR medio
    de cada uno (a lo largo de todas las semanas guardadas) y muestra los
    10 mejores. Tambien indica cuantas semanas tiene cada jugador.
    """
    import pandas as pd

    if df_hist is None or df_hist.empty:
        return
    if "Jugador" not in df_hist.columns or "PR" not in df_hist.columns:
        return

    df = df_hist.copy()
    # PR a numero (por si viene como string)
    df["PR"] = pd.to_numeric(
        df["PR"].astype(str).str.replace(",", ".", regex=False),
        errors="coerce")
    df = df.dropna(subset=["PR"])
    df = df[df["PR"] > 0]  # descartar PR=0 (semanas sin datos)
    if df.empty:
        return

    agrupado = df.groupby("Jugador").agg(
        pr_medio=("PR", "mean"),
        semanas=("PR", "count"),
    ).reset_index()
    agrupado = agrupado.sort_values("pr_medio", ascending=False).head(10)

    st.markdown("---")
    st.subheader("🏅 Top 10 Histórico (PR medio)")
    st.caption("Media del Power Rating de cada jugador a lo largo de todas "
               "las semanas guardadas.")

    pr_max = agrupado["pr_medio"].max() if not agrupado.empty else 1
    filas_html = ""
    for i, (_, row) in enumerate(agrupado.iterrows()):
        pos = i + 1
        if pos == 1:
            medalla = "🥇"
        elif pos == 2:
            medalla = "🥈"
        elif pos == 3:
            medalla = "🥉"
        else:
            medalla = f"<span style='color:#94a3b8;font-weight:700;'>{pos}</span>"
        pr = row["pr_medio"]
        sem = int(row["semanas"])
        pct = max(6, round(100 * pr / pr_max)) if pr_max > 0 else 0
        filas_html += (
            f"<div style='display:flex;align-items:center;gap:12px;"
            f"padding:10px 16px;border-bottom:1px solid #f1f5f9;'>"
            f"<span style='font-size:18px;min-width:30px;text-align:center;'>"
            f"{medalla}</span>"
            f"<span style='font-size:15px;font-weight:700;min-width:160px;'>"
            f"{row['Jugador']}</span>"
            f"<div style='flex:1;background:#f1f5f9;border-radius:6px;"
            f"height:14px;overflow:hidden;'>"
            f"<div style='width:{pct}%;height:100%;background:linear-gradient("
            f"90deg,#3b82f6,#60a5fa);'></div></div>"
            f"<span style='font-size:15px;font-weight:800;color:#1e3a8a;"
            f"min-width:55px;text-align:right;'>{pr:.1f}</span>".replace('.', ',')
            + f"<span style='font-size:11px;color:#94a3b8;min-width:70px;"
            f"text-align:right;'>{sem} sem.</span>"
            f"</div>"
        )
    html = ("<div style='background:white;border:1px solid #e2e8f0;"
            "border-radius:12px;overflow:hidden;'>" + filas_html + "</div>")
    html_compacto = " ".join(
        line.strip() for line in html.splitlines() if line.strip())
    st.markdown(html_compacto, unsafe_allow_html=True)
