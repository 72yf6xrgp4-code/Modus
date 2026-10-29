"""
cuotas_url.py - Entrada a la app por enlace: el aviso del vigia (ntfy) y el
boton "Modus value" abren Value Bets con el partido (y las cuotas) ya
puestos, mediante parametros de la URL:

    ?seccion=value&j1=<J1>&j2=<J2>     aviso del vigia (J1 = primero del cartel)
    ?seccion=value&wm=<base64url>      boton "Modus value" (cuotas de Winamax)
    ?seccion=apuestas                  pestana Apuestas (vale tambien ?seccion=alertas)

La logica de value (probabilidades, 🟢, importe, tope) es la de siempre: la
de la app. Este modulo solo rellena las casillas y anade un panel con todas
las cuotas recibidas y el boton para apuntar la apuesta.
"""

import html as html_mod
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from helpers import es_admin, fecha_jornada_madrid
from modelo.motor import calcular_partido, probabilidad
from modelo.volatilidad import nivel_volatilidad
from vigia import reglas
from vigia.boton import (VERSION_BOTON, DatosNoValidos, casilla, decodificar, preparar,
                         seleccion_de_casilla)
from vigia.cuotas import evaluar_cuotas
from vigia.registro import (MIN_PREVIOS, estado_partido, fiable, gastado_del_dia,
                            tope_del_dia)
from vigia.mercados import texto_seleccion
from vigia.nombres import emparejar

SECCION_DE_PARAM = {"value": "💰 VALUE BETS", "apuestas": "🎟️ APUESTAS",
                    "alertas": "🎟️ APUESTAS"}
_PREFIJOS_CASILLAS = ("vic_", "180_", "mas_", "hcap_", "legs_")
OPCION_MANUAL = "— Selección manual —"
MADRID = ZoneInfo("Europe/Madrid")   # el servidor de Streamlit Cloud va en UTC


def aplicar_parametros_url():
    """Lee los parametros de la URL una sola vez: elige la seccion y guarda
    el partido para Value Bets. Llamar ANTES de crear el menu de secciones."""
    qp = st.query_params
    if not qp:
        return
    seccion = qp.get("seccion")
    if seccion in SECCION_DE_PARAM:
        st.session_state["seccion"] = SECCION_DE_PARAM[seccion]
    if qp.get("j1") or qp.get("wm"):
        st.session_state["url_entrada"] = {
            "j1": qp.get("j1"), "j2": qp.get("j2"), "wm": qp.get("wm")}
    # Se limpian para que recargar o cambiar de seccion no lo repita
    qp.clear()


def _cartel():
    """Partidos del calendario en orden del cartel (los de 'Proximos')."""
    try:
        from data_loading import obtener_proximos_partidos_csv
        res = obtener_proximos_partidos_csv(limite=40)
        lista = res.get("partidos", []) if isinstance(res, dict) else (res or [])
        return [(p["j1"], p["j2"]) for p in lista]
    except Exception:
        return []


def preparar_value_bets(nombres_disponibles):
    """Si se ha llegado por enlace, elige J1/J2 y rellena las casillas de
    cuota. Llamar en Value Bets ANTES de crear el desplegable de proximos
    partidos y los selectores de jugadores."""
    e = st.session_state.pop("url_entrada", None)
    if not e:
        return
    if e.get("wm"):
        try:
            datos = decodificar(e["wm"])
            r = preparar(datos, nombres_disponibles, _cartel())
        except DatosNoValidos as ex:
            st.error(f"Modus value: {ex}. No se ha rellenado ninguna cuota.")
            return
        j1, j2 = r["j1"], r["j2"]
        st.session_state["wm_partido"] = dict(r, datos=datos)
    else:
        j1 = emparejar(e.get("j1") or "", nombres_disponibles)
        j2 = emparejar(e.get("j2") or "", nombres_disponibles)
        if not j1 or not j2 or j1 == j2:
            st.warning(f"No encuentro a {e.get('j1')} / {e.get('j2')} en estos datos. "
                       "Elige el partido a mano.")
            return
        st.session_state.pop("wm_partido", None)
        r = None

    # Partido elegido a mano: el desplegable de proximos no debe mandar
    st.session_state["vb_proximo_partido"] = OPCION_MANUAL
    st.session_state["vb_ultimo_prox"] = None
    st.session_state["vb_j1"] = j1
    st.session_state["vb_j2"] = j2
    st.session_state["_vb_par"] = (j1, j2)   # que no se borren las casillas
    st.session_state["vb_calcular"] = True
    for k in [k for k in st.session_state.keys()
              if isinstance(k, str) and k.startswith(_PREFIJOS_CASILLAS)]:
        del st.session_state[k]
    if r:
        n = 0
        for s in r["selecciones"]:
            k = casilla(s["sel"])
            if k and 1.01 <= s["cuota"] <= 50.0:   # rango de las casillas
                st.session_state[k] = float(s["cuota"])
                n += 1
        aviso = ("" if r["orden"] == "cartel" else
                 " ⚠️ No está en el calendario: J1 = el primero de Winamax "
                 "(compruébalo con el cartel).")
        st.success(f"🌐 Cuotas de Winamax cargadas: **{j1}** vs **{j2}** "
                   f"({n} casillas rellenadas; todas abajo, en «Cuotas de "
                   f"Winamax»).{aviso}")
    else:
        st.success(f"🎯 Partido del aviso: **{j1}** vs **{j2}**")


def comprobar_partido_anterior(j1_sel, j2_sel):
    """(jornada, lista de vigia.frescura.partido_anterior) del partido, o
    (None, None) si no hay jornada en juego o no se puede leer la hoja."""
    from data_loading import (_descargar_csv_jornada, cargar_jugadores_desde,
                              detectar_jornada_de_hoy)
    from modelo.datos import partidos_de_jornada
    from vigia.frescura import partido_anterior
    jornada = detectar_jornada_de_hoy(exigir_datos=False)
    if not jornada:
        return None, None
    lineas = _descargar_csv_jornada(jornada)
    if not lineas:
        return jornada, None
    stats_hoy = cargar_jugadores_desde(jornada) or {}
    return jornada, partido_anterior(partidos_de_jornada(lineas), j1_sel, j2_sel, stats_hoy)


def datos_partido(j1_sel, j2_sel):
    """{jornada, n_partido, previos_j1, previos_j2} del partido: su sitio en
    el cartel de hoy y cuantos partidos llevaba cada jugador esta semana
    antes de el. None si no se pueden leer las hojas de las jornadas."""
    try:
        from data_loading import _descargar_csv_jornada
        from modelo.datos import jornadas_del_dia, jornadas_hasta, partidos_de_jornada
        from vigia.frescura import info_partido
        from vigia.horario import dia_jornada
        dia = dia_jornada(datetime.now(MADRID))
        semana = {}
        for j in jornadas_hasta(dia):
            lineas = _descargar_csv_jornada(j)
            if not lineas:
                return None
            semana[j] = partidos_de_jornada(lineas)
        return info_partido(semana, jornadas_del_dia(dia), j1_sel, j2_sel)
    except Exception:
        return None


def _aviso_partido_anterior(j1_sel, j2_sel, completo):
    """Avisa si los datos aun no tienen el partido anterior de alguno de
    los dos jugadores (completo=False: solo una linea si falta algo)."""
    jornada, res = comprobar_partido_anterior(j1_sel, j2_sel)
    if jornada is None:
        if completo:
            st.caption("ℹ️ No hay jornada en juego: los datos son los del Resumen Semanal.")
        return
    if res is None:
        st.warning(f"⚠️ No he podido leer la hoja de {jornada} para comprobar que los "
                   "datos incluyen el partido anterior de cada jugador.")
        return
    malos = [r for r in res if not r["ok"]]
    fuente = st.session_state.get("vb_fuente", "Forma reciente")
    if malos:
        if not completo:
            st.warning("⚠️ Ojo: los datos aún no incluyen el partido anterior de "
                       + " ni de ".join(r["jugador"] for r in malos)
                       + " (detalle arriba, en «Cuotas de Winamax»).")
            return
        st.error("⚠️ **Faltan datos del partido anterior.** "
                 + " ".join(f"**{r['jugador']}**: {r['texto']}." for r in malos)
                 + " El modelo aún no lo tiene en cuenta: pulsa «Ejecutar actualización» "
                   "en la barra lateral, espera un poco y pulsa «Refrescar datos» antes "
                   "de apostar.")
        for r in res:
            if r["ok"]:
                st.caption(f"✅ {r['jugador']}: {r['texto']}.")
    elif completo:
        st.caption("✅ Datos al día — " + " · ".join(
            f"{r['jugador']}: {r['texto']}" for r in res) + ".")
    if completo and fuente not in ("Forma reciente", jornada) and any(r["jugados"] for r in res):
        st.caption(f"ℹ️ Estás usando la fuente «{fuente}», que no incluye los partidos "
                   f"de hoy; la recomendada es ⚡ Forma reciente.")


def _num(v):
    return f"{v:.2f}".replace(".", ",")


def render_panel_winamax(j1, j2, j1_sel, j2_sel):
    """Datos de las cuotas recibidas del boton: hora de lectura, avisos y,
    en un desplegable, TODAS las cuotas (tambien las lineas sin casilla)
    con su value. Las que hay que apostar salen en "Apuestas con valor"."""
    w = st.session_state.get("wm_partido")
    if not w or (w["j1"], w["j2"]) != (j1_sel, j2_sel):
        return
    datos = w["datos"]
    st.markdown("---")
    st.markdown("### 🌐 Cuotas de Winamax")
    leidas = datetime.fromtimestamp(datos["h"], MADRID).strftime("%H:%M") if datos["h"] else "?"
    if datos.get("f") == "pantalla":
        st.caption(f"Leídas a las {leidas} de lo que se veía en pantalla "
                   f"({len(datos['mercados'])} mercados). Winamax solo pinta los mercados "
                   "cercanos: si falta alguno, desplázate hasta verlo y vuelve a pulsar.")
    else:
        st.caption(f"Leídas de la página de Winamax a las {leidas} "
                   f"(estado: {datos['s'] or '?'}), con las cuotas al día de la pantalla.")
    if datos.get("b", 1) < VERSION_BOTON:
        st.warning("🔖 Tu botón «Modus value» es una versión antigua (por eso a veces "
                   "hay que recargar la página de Winamax). Reinstálalo: 🎟️ Apuestas → "
                   "«Instalar el botón Modus value», copia el código y pégalo como "
                   "dirección (URL) de tu marcador.")
    elif datos.get("f") == "pagina" and datos.get("ne") and datos.get("e", 0) > 600:
        st.warning(f"⏱️ {datos['ne']} mercados no se veían en pantalla: sus cuotas son "
                   f"de cuando cargaste la página de Winamax (hace {datos['e'] // 60} min) "
                   "y pueden haber cambiado. Desplázate hasta verlos (o recarga) y vuelve "
                   "a pulsar el botón.")
    if datos["s"] and datos["s"].upper() != "PREMATCH":
        st.warning("⚠️ Winamax no lo marca como prepartido: tus reglas son solo prepartido.")
    if w["orden"] != "cartel":
        st.warning("⚠️ El partido no está en el calendario de la hoja: J1 es el "
                   "primero de Winamax.")
    _aviso_partido_anterior(j1_sel, j2_sel, completo=True)

    calc = calcular_partido(j1, j2, j1_saca_primero=True)
    filas = evaluar_cuotas(calc, [(s["sel"], s["cuota"], "winamax") for s in w["selecciones"]],
                           j1_sel, j2_sel)
    _guardar_lectura(w, datos, calc, j1, j2, j1_sel, j2_sel)
    tabla = pd.DataFrame([{
        "Selección": f["texto"], "Mercado": f["nombre_mercado"],
        "Cuota": _num(f["cuota"]), "Modelo": f"{f['p']*100:.1f} %",
        "Cuota mínima": _num(reglas.cuota_minima(f["p"], reglas.EDGE_MIN)),
        "Edge": f"{f['ev']['edge']*100:+.1f} %",
        "": "🟢" if f["ev"]["verde"] else "",
        "Importe": _eur(f["ev"]["importe"]) if f["ev"]["importe"] else "",
    } for f in filas])
    with st.expander(f"📋 Todas las cuotas leídas ({len(filas)}) y su value"):
        st.dataframe(tabla, use_container_width=True, hide_index=True)
        st.caption(f"Cuota mínima = la que da un {reglas.EDGE_MIN*100:.0f} % de edge.")
        if w["sin_asignar"]:
            st.markdown(f"**Sin asignar ({len(w['sin_asignar'])})**: mercados que el modelo no cubre.")
            st.dataframe(pd.DataFrame(w["sin_asignar"], columns=["Mercado", "Salida", "Cuota"]),
                         use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# APUESTAS CON VALOR (sustituye al antiguo "Resumen de Value Bets")
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
.ap-card{border:1px solid #e2e8f0;border-left:6px solid #16a34a;border-radius:14px;
  padding:.85rem 1rem;background:#fff;box-shadow:0 1px 3px rgba(15,23,42,.06);
  margin-bottom:.6rem}
.ap-card.amarillo{border-left-color:#f59e0b}.ap-card.gris{border-left-color:#94a3b8;opacity:.75}
.ap-top{display:flex;justify-content:space-between;align-items:flex-start;gap:.75rem}
.ap-sel{font-weight:800;font-size:1.08rem;color:#0f172a;line-height:1.3}
.ap-mer{font-size:.75rem;color:#64748b;margin-top:2px}
.ap-eur{flex:0 0 auto;background:#16a34a;color:#fff;font-weight:800;font-size:1.25rem;
  border-radius:12px;padding:.3rem .75rem;white-space:nowrap}
.ap-eur small{display:block;font-size:.6rem;font-weight:600;opacity:.85;text-align:center}
.ap-card.amarillo .ap-eur{background:#f59e0b}.ap-card.gris .ap-eur{background:#94a3b8}
.ap-datos{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.4rem;margin-top:.7rem}
.ap-datos div{background:#f8fafc;border-radius:10px;padding:.4rem .2rem;text-align:center}
.ap-datos b{display:block;font-size:1rem;color:#0f172a}
.ap-datos span{font-size:.65rem;color:#64748b}
.ap-datos .pos{color:#15803d}
.ap-estado{margin-top:.55rem;font-size:.85rem;font-weight:700}
.ap-tope{display:flex;gap:.5rem;flex-wrap:wrap;margin:.2rem 0 .6rem}
.ap-tope span{background:#f1f5f9;border-radius:999px;padding:.25rem .7rem;font-size:.82rem;
  color:#334155;font-weight:600}
</style>
"""


def _eur(v):
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " €"


def _cuotas_de_casillas():
    """[(sel, cuota, 'casilla')] de las casillas de Value Bets con cuota."""
    salida = []
    for k, v in st.session_state.items():
        if not (isinstance(k, str) and k.startswith(_PREFIJOS_CASILLAS)):
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 1:
            continue
        sel = seleccion_de_casilla(k)
        if sel:
            salida.append((sel, float(v), "casilla"))
    return salida


def render_apuestas_valor(j1, j2, j1_sel, j2_sel):
    """Las apuestas con valor del partido (cuotas escritas a mano o leidas
    con el boton), con cuanto apostar segun tus reglas y los botones para
    marcar si la has hecho o no."""
    cuotas_sel = _cuotas_de_casillas()
    w = st.session_state.get("wm_partido")
    if w and (w["j1"], w["j2"]) == (j1_sel, j2_sel):
        cuotas_sel += [(s["sel"], s["cuota"], "winamax") for s in w["selecciones"]]

    st.markdown("---")
    st.markdown("### 💰 Apuestas con valor")
    if not cuotas_sel:
        st.info("✍️ Escribe la cuota de tu casa en cualquier mercado de las pestañas "
                "de arriba (o usa el botón «Modus value») y aquí verás si hay que "
                "apostar y cuánto.")
        return
    st.markdown(_CSS, unsafe_allow_html=True)

    calc = calcular_partido(j1, j2, j1_saca_primero=True)
    filas = evaluar_cuotas(calc, cuotas_sel, j1_sel, j2_sel)
    apostables = [f for f in filas if f["ev"]["importe"] > 0]

    # Tope de hoy y lo ya apuntado en este partido
    fecha = fecha_jornada_madrid()
    from alertas_ui import cargar_alertas
    alertas, err = cargar_alertas()
    if alertas is None:
        alertas = []
        if es_admin():
            st.caption(f"⚠️ No puedo leer la pestaña alertas del Sheets ({err}): no se podrá marcar.")
    gastado = gastado_del_dia(alertas, fecha)
    marcadas, _ = estado_partido(alertas, fecha, j1_sel, j2_sel)
    tope = tope_del_dia(alertas)
    queda = max(0.0, tope - gastado)
    n_partido = sum(1 for e in marcadas.values() if e != "no apostada")
    w = st.session_state.get("wm_partido")
    if w and (w["j1"], w["j2"]) == (j1_sel, j2_sel):
        _aviso_partido_anterior(j1_sel, j2_sel, completo=False)
    st.markdown(f"<div class='ap-tope'><span>Hoy: {_eur(gastado)} de "
                f"{_eur(tope)}</span><span>Quedan {_eur(queda)}</span>"
                f"<span>En este partido: {n_partido}</span></div>", unsafe_allow_html=True)

    if not apostables:
        st.info(f"Ninguna cuota llega al {reglas.EDGE_MIN*100:.0f} % de edge: no hay "
                "apuesta en este partido.")
    for i, f in enumerate(apostables):
        _tarjeta(f, i, alertas, fecha, j1, j2, j1_sel, j2_sel, queda)
    casi = [f for f in filas if f["ev"]["verde"] and not f["ev"]["importe"]]
    if casi:
        st.caption(f"🟢 También con value, pero sin llegar al {reglas.EDGE_MIN*100:.0f} % "
                   "de edge (no se apuestan): "
                   + " · ".join(f"{f['texto']} @{_num(f['cuota'])} "
                                f"({f['ev']['edge']*100:+.1f} %)" for f in casi))
    v1 = nivel_volatilidad(j1.get("volatilidad")) or "sin dato"
    v2 = nivel_volatilidad(j2.get("volatilidad")) or "sin dato"
    if apostables and ("alto" in (v1, v2) or "sin dato" in (v1, v2)):
        st.caption(f"ℹ️ Volatilidad: {j1_sel} {v1}, {j2_sel} {v2}. No cambia el importe, "
                   "pero con volatilidad alta el modelo acierta menos.")


def _fila_apuntada(alertas, fecha, j1_sel, j2_sel, clave):
    """La alerta de hoy de esta seleccion en este partido, o None."""
    import json
    previa = None
    for a in alertas or []:
        try:
            sel = json.loads(a.get("seleccion_json") or "{}")
        except ValueError:
            continue
        if (a.get("fecha") == fecha and a.get("tipo_aviso") == "apuesta"
                and json.dumps(sel, sort_keys=True) == clave
                and {a.get("j1"), a.get("j2")} == {j1_sel, j2_sel}):
            previa = a
    return previa


def _tarjeta(f, i, alertas, fecha, j1, j2, j1_sel, j2_sel, queda):
    from alertas_ui import popover_importe
    from vigia.registro import importe_apostado
    ev = f["ev"]
    fila = _fila_apuntada(alertas, fecha, j1_sel, j2_sel, f["clave"])
    estado = fila.get("estado") if fila else None
    # Recomendado: el del edge recortado al tope (con el tope agotado no hay
    # recomendado, pero puedes apostar igual poniendo tu el importe)
    recomendado, motivo = reglas.apuntar(alertas, fecha, j1_sel, j2_sel, ev)
    importe = importe_apostado(fila) if estado in ("apostada", "pendiente") else recomendado
    clase = ("" if ev["verde"] else "amarillo") if estado != "no apostada" else "gris"
    etiqueta = "🟢 " if ev["verde"] else ""
    eur_txt = _eur(importe) if importe else "—"
    rotulo = "APOSTADO" if estado in ("apostada", "pendiente") else "RECOMENDADO"
    if estado == "apostada":
        est = "<div class='ap-estado' style='color:#15803d'>✅ Apostada</div>"
    elif estado == "no apostada":
        est = "<div class='ap-estado' style='color:#64748b'>❌ No apostada</div>"
    elif estado == "pendiente":
        est = "<div class='ap-estado' style='color:#b45309'>⏳ Apuntada, sin marcar</div>"
    elif not recomendado:
        est = (f"<div class='ap-estado' style='color:#64748b'>Sin importe recomendado: "
               f"{motivo}. Si aun así quieres, pon tú el importe.</div>")
    else:
        est = ""
    esc = html_mod.escape
    st.markdown(
        f"<div class='ap-card {clase}'><div class='ap-top'><div>"
        f"<div class='ap-sel'>{etiqueta}{esc(f['texto'])}</div>"
        f"<div class='ap-mer'>{esc(f['nombre_mercado'])}"
        f"{' · cuota de Winamax' if f['origen'] == 'winamax' else ''}</div></div>"
        f"<div class='ap-eur'>{eur_txt}<small>{rotulo}</small></div></div>"
        f"<div class='ap-datos'>"
        f"<div><b>{_num(f['cuota'])}</b><span>Cuota</span></div>"
        f"<div><b>{f['p']*100:.1f} %</b><span>Modelo</span></div>"
        f"<div><b>{_num(f['justa'])}</b><span>Cuota justa</span></div>"
        f"<div><b class='pos'>{ev['edge']*100:+.1f} %</b><span>Edge</span></div>"
        f"</div>{est}</div>", unsafe_allow_html=True)

    if not es_admin():
        return
    if estado == "apostada":
        # Ya apostada: se puede cambiar el importe o corregir a "no apostada"
        c1, c2 = st.columns(2)
        with c1.popover("✏️ Cambiar importe", use_container_width=True):
            popover_importe(fila, f"vb_{i}")
        if c2.button("❌ No la aposté", key=f"ap_no_{i}", use_container_width=True):
            _guardar(f, "no apostada", ev["importe"], None, fecha, j1, j2, j1_sel, j2_sel)
        st.write("")
        return
    # Sin apostar: el importe lo eliges tu (por defecto, el recomendado)
    base = recomendado or ev["importe"]
    c0, c1, c2 = st.columns(3)
    elegido = c0.number_input("Importe (€)", min_value=0.5, step=0.5, value=float(base),
                              key=f"ap_imp_{i}",
                              help=f"Recomendado: {_eur(base)}. Si lo cambias, solo cuenta "
                                   "para tus apuestas (tope y beneficio real); las "
                                   "estadísticas del modelo siguen con el recomendado.")
    c1.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    c2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if c1.button(f"✅ Apostar {_eur(elegido)}", key=f"ap_si_{i}", use_container_width=True,
                 type="primary"):
        _guardar(f, "apostada", base, elegido, fecha, j1, j2, j1_sel, j2_sel)
    if c2.button("❌ No la apuesto", key=f"ap_no_{i}", use_container_width=True,
                 disabled=estado == "no apostada"):
        _guardar(f, "no apostada", base, None, fecha, j1, j2, j1_sel, j2_sel)
    if elegido > queda + 1e-9:
        st.caption(f"⚠️ {_eur(elegido)} supera lo que queda del tope de hoy ({_eur(queda)}).")
    st.write("")


def _guardar_lectura(w, datos, calc, j1, j2, j1_sel, j2_sel):
    """Guarda en la pestana cuotas_winamax TODAS las cuotas leidas con el
    boton (una vez por pulsacion), con la probabilidad del modelo y el edge
    de ese momento, para comparar y sacar estadisticas."""
    import json
    lectura = f"{datos['id'] or j1_sel}-{datos['h']}"
    if not es_admin():
        return
    hecho = st.session_state.get("_wm_guardada")
    if hecho and hecho[0] == lectura:      # ya se guardo (o no) en esta lectura
        st.caption(hecho[1])
        return

    def fin(msg):
        st.session_state["_wm_guardada"] = (lectura, msg)
        st.caption(msg)

    from alertas_ui import anadir_winamax
    ahora = datetime.now(MADRID)
    base = {
        "fecha": fecha_jornada_madrid(), "hora": ahora.strftime("%H:%M"),
        "lectura": datos["h"], "match_id": datos["id"],
        "inicio": (datetime.fromtimestamp(datos["t"], MADRID).strftime("%Y-%m-%d %H:%M")
                   if datos["t"] else ""),
        "j1": j1_sel, "j2": j2_sel,
        "vol_j1": _vol_num(j1.get("volatilidad")), "vol_j2": _vol_num(j2.get("volatilidad")),
        "fuente": datos.get("f", ""), "resultado": "",
    }
    info = datos_partido(j1_sel, j2_sel)
    if info is None:   # sin marcarla: se reintenta en la siguiente recarga
        st.caption("📊 No se guardan las cuotas para las estadísticas: no he podido "
                   "leer las hojas de las jornadas para saber si el partido es fiable.")
        return
    base.update(info)
    if not fiable(info):
        poco = [f"{n} ({info[k]})" for n, k in ((j1_sel, "previos_j1"), (j2_sel, "previos_j2"))
                if info[k] < MIN_PREVIOS]
        return fin(f"📊 No se guardan las cuotas para las estadísticas: hacen falta "
                   f"{MIN_PREVIOS} partidos previos esta semana y " + ", ".join(poco)
                   + " no los tiene; con tan pocos datos el modelo no es fiable.")
    filas = []
    for s in w["selecciones"]:
        p = probabilidad(calc, s["sel"])
        mercado = reglas.MERCADO_DE_TIPO[s["sel"]["tipo"]]
        ev = reglas.evaluar(mercado, p, s["cuota"])
        filas.append(dict(base, titulo=s["titulo"], salida=s["label"], mercado=s["nombre"],
                          seleccion=texto_seleccion(s["sel"], j1_sel, j2_sel),
                          cuota=s["cuota"], p_modelo=round(p, 4),
                          cuota_justa=round(1.0 / p, 2), edge=round(ev["edge"], 4),
                          verde="🟢" if ev["verde"] else "", importe=ev["importe"],
                          seleccion_json=json.dumps(s["sel"], ensure_ascii=False)))
    for titulo, salida, cuota in w["sin_asignar"]:
        filas.append(dict(base, titulo=titulo, salida=salida, cuota=cuota))
    ok, error = anadir_winamax(filas)
    if ok:
        fin(f"💾 {len(filas)} cuotas guardadas en la pestaña cuotas_winamax (partido "
            f"fiable: {info['previos_j1']} y {info['previos_j2']} partidos previos).")
    else:
        st.caption(f"⚠️ No se pudieron guardar las cuotas: {error}")


def _vol_num(v):
    """Indice de volatilidad como numero (2 decimales) o '' si no hay dato."""
    return round(float(str(v).replace(",", ".")), 2) if nivel_volatilidad(v) else ""


def _guardar(f, estado, importe, importe_real, fecha, j1, j2, j1_sel, j2_sel):
    """Apunta la seleccion en la pestana alertas con el estado elegido.
    importe = el recomendado (para las estadisticas); importe_real = lo que
    de verdad apostaste (None = no cambiarlo; si coincide con el
    recomendado se deja vacio)."""
    import json
    from alertas_ui import anadir_alerta, cargar_alertas, marcar_estado
    w = st.session_state.get("wm_partido") or {}
    datos = w.get("datos") or {}
    alertas, _ = cargar_alertas()
    previa = _fila_apuntada(alertas, fecha, j1_sel, j2_sel, f["clave"])
    real = None
    if importe_real is not None:
        rec = float(str((previa or {}).get("importe") or importe).replace(",", "."))
        real = "" if abs(importe_real - rec) < 1e-9 else importe_real
    if previa is not None:
        ok, error = marcar_estado(previa, estado, real)
    else:
        ahora = datetime.now(MADRID)
        info = datos_partido(j1_sel, j2_sel) or {}
        jornada, n_partido = info.get("jornada", ""), info.get("n_partido", "")
        gastado = gastado_del_dia(alertas or [], fecha)
        ok, error = anadir_alerta({
            "id": f"{fecha}-{j1_sel}-{j2_sel}-{f['texto']}", "fecha": fecha,
            "hora": ahora.strftime("%H:%M"), "partido": f"{j1_sel} vs {j2_sel}",
            "j1": j1_sel, "j2": j2_sel,
            # El numero (no solo el nivel): lo usa el seguimiento por mercado
            "vol_j1": _vol_num(j1.get("volatilidad")),
            "vol_j2": _vol_num(j2.get("volatilidad")),
            "mercado": f["nombre_mercado"], "seleccion": f["texto"],
            "cuota": f["cuota"], "p_modelo": round(f["p"], 4),
            "edge": round(f["ev"]["edge"], 4), "margen": round(f["ev"]["margen"], 4),
            "verde": "🟢" if f["ev"]["verde"] else "", "importe": importe,
            "importe_real": real or "",
            "tope_restante": max(0.0, tope_del_dia(alertas or []) - gastado
                                 - ((real or importe) if estado == "apostada" else 0)),
            "estado": estado, "resultado": "", "beneficio": "",
            "tipo_aviso": "apuesta",
            "inicio": (datetime.fromtimestamp(datos["t"], MADRID).strftime("%Y-%m-%d %H:%M")
                       if datos.get("t") else ""),
            "match_id": datos.get("id", ""), "jornada": jornada, "n_partido": n_partido,
            "orden_j1": w.get("orden", "cartel"),
            "seleccion_json": json.dumps(f["sel"], ensure_ascii=False),
        })
    if ok:
        st.rerun()
    st.error(f"❌ No se pudo guardar: {error}")
