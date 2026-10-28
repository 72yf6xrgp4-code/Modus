"""
cuotas_url.py - Entrada a la app por enlace: el aviso del vigia (ntfy) y el
boton "Modus value" abren Value Bets con el partido (y las cuotas) ya
puestos, mediante parametros de la URL:

    ?seccion=value&j1=<J1>&j2=<J2>     aviso del vigia (J1 = primero del cartel)
    ?seccion=value&wm=<base64url>      boton "Modus value" (cuotas de Winamax)
    ?seccion=alertas                   pestana Alertas

La logica de value (probabilidades, 🟢, importe, tope) es la de siempre: la
de la app. Este modulo solo rellena las casillas y anade un panel con todas
las cuotas recibidas y el boton para apuntar la apuesta.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from helpers import es_admin, fecha_jornada_madrid
from modelo.motor import calcular_partido, probabilidad
from modelo.volatilidad import nivel_volatilidad
from vigia import reglas
from vigia.boton import DatosNoValidos, casilla, decodificar, preparar
from vigia.mercados import texto_seleccion
from vigia.nombres import emparejar

SECCION_DE_PARAM = {"value": "💰 VALUE BETS", "alertas": "🔔 ALERTAS"}
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


def _num(v):
    return f"{v:.2f}".replace(".", ",")


def render_panel_winamax(j1, j2, j1_sel, j2_sel):
    """Panel con TODAS las cuotas recibidas del boton (tambien las lineas
    que no tienen casilla), su value segun las reglas y el boton para
    apuntar la apuesta en la pestana Alertas."""
    w = st.session_state.get("wm_partido")
    if not w or (w["j1"], w["j2"]) != (j1_sel, j2_sel):
        return
    datos = w["datos"]
    st.markdown("---")
    st.markdown("### 🌐 Cuotas de Winamax")
    leidas = datetime.fromtimestamp(datos["h"], MADRID).strftime("%H:%M") if datos["h"] else "?"
    st.caption(f"Leídas de la página que tenías abierta a las {leidas} "
               f"(estado en Winamax: {datos['s'] or '?'}). Si han pasado minutos, "
               "recarga la página de Winamax y vuelve a pulsar el botón.")
    if datos["s"] and datos["s"].upper() != "PREMATCH":
        st.warning("⚠️ Winamax no lo marca como prepartido: tus reglas son solo prepartido.")
    if w["orden"] != "cartel":
        st.warning("⚠️ El partido no está en el calendario de la hoja: J1 es el "
                   "primero de Winamax.")

    # Para APUNTAR, la volatilidad no cuenta: siempre el edge minimo normal
    # (10 %) y el importe normal. Solo se muestra como informacion. (El
    # vigia si la aplica en sus avisos: vigia/reglas.requisito_volatilidad.)
    edge_min = reglas.EDGE_MIN
    v1 = nivel_volatilidad(j1.get("volatilidad")) or "sin dato"
    v2 = nivel_volatilidad(j2.get("volatilidad")) or "sin dato"
    if "alto" in (v1, v2) or "sin dato" in (v1, v2):
        st.info(f"ℹ️ Volatilidad: {j1_sel} {v1}, {j2_sel} {v2}. Para apuntar no "
                "cuenta (10 % de edge e importe normal), pero tenlo en cuenta: "
                "con volatilidad alta el modelo acierta menos.")

    calc = calcular_partido(j1, j2, j1_saca_primero=True)
    filas = []
    for s in w["selecciones"]:
        p = probabilidad(calc, s["sel"])
        mercado = reglas.MERCADO_DE_TIPO[s["sel"]["tipo"]]
        ev = reglas.evaluar(mercado, p, s["cuota"])
        filas.append({"s": s, "p": p, "ev": ev, "mercado": mercado,
                      "texto": texto_seleccion(s["sel"], j1_sel, j2_sel)})
    filas.sort(key=lambda f: f["ev"]["edge"], reverse=True)

    tabla = pd.DataFrame([{
        "Selección": f["texto"], "Mercado": f["s"]["nombre"],
        "Cuota": _num(f["s"]["cuota"]), "Modelo": f"{f['p']*100:.1f} %",
        "Cuota mínima": _num(reglas.cuota_minima(f["p"], edge_min)),
        "Edge": f"{f['ev']['edge']*100:+.1f} %",
        "": ("⚠️ REVISAR" if f["ev"]["revisar"] else "🟢" if f["ev"]["verde"] else ""),
        "Importe": (f"{f['ev']['importe']:g} €".replace(".", ",")
                    if f["ev"]["importe"] else ""),
    } for f in filas])
    st.dataframe(tabla, use_container_width=True, hide_index=True)
    st.caption("Cuota mínima = la que da un 10 % de edge. Importe según tus reglas, "
               "antes del tope de la jornada.")
    if w["sin_asignar"]:
        with st.expander(f"Mercados sin asignar ({len(w['sin_asignar'])}): el modelo no los cubre"):
            st.dataframe(pd.DataFrame(w["sin_asignar"], columns=["Mercado", "Salida", "Cuota"]),
                         use_container_width=True, hide_index=True)

    value = [f for f in filas if f["ev"]["importe"] > 0]
    if not value:
        st.info("Ninguna cuota llega al 10 % de edge (o es «REVISAR»): no hay apuesta.")
        return
    if not es_admin():
        return
    _apuntar(value, datos, w, j1, j2, j1_sel, j2_sel)


def _apuntar(value, datos, w, j1, j2, j1_sel, j2_sel):
    import json
    from alertas_ui import anadir_alerta, cargar_alertas
    etiquetas = [f"{f['texto']} @{_num(f['s']['cuota'])} · edge "
                 f"{f['ev']['edge']*100:.0f} %" for f in value]
    i = st.selectbox("Apuesta a apuntar (una por partido)", range(len(value)),
                     format_func=lambda k: etiquetas[k], key="wm_sel_apuesta")
    f = value[i]
    filas_alertas, err = cargar_alertas()
    if filas_alertas is None:
        st.warning(f"⚠️ No puedo leer la pestaña alertas: {err}")
        return
    fecha = fecha_jornada_madrid()
    importe, motivo = reglas.apuntar(filas_alertas, fecha, j1_sel, j2_sel, f["ev"])
    if importe <= 0:
        st.info(f"No se puede apuntar: {motivo}.")
        return
    gastado = sum(float(str(a.get("importe") or 0).replace(",", "."))
                  for a in filas_alertas if a.get("fecha") == fecha
                  and a.get("tipo_aviso") == "apuesta" and a.get("estado") != "no apostada")
    queda = reglas.TOPE_DIARIO - gastado - importe
    st.markdown(f"**Importe: {importe:g} €** · quedarían "
                f"{queda:g} € del tope de la jornada".replace(".", ","))
    if st.button("📌 Apuntar apuesta", type="primary", key="wm_apuntar"):
        ahora = datetime.now(MADRID)
        inicio = (datetime.fromtimestamp(datos["t"], MADRID).strftime("%Y-%m-%d %H:%M")
                  if datos["t"] else "")
        ok, error = anadir_alerta({
            "id": f"{fecha}-{datos['id'] or j1_sel}", "fecha": fecha,
            "hora": ahora.strftime("%H:%M"), "partido": f"{j1_sel} vs {j2_sel}",
            "j1": j1_sel, "j2": j2_sel,
            "vol_j1": nivel_volatilidad(j1.get("volatilidad")) or "",
            "vol_j2": nivel_volatilidad(j2.get("volatilidad")) or "",
            "mercado": f["s"]["nombre"], "seleccion": f["texto"],
            "cuota": f["s"]["cuota"], "p_modelo": round(f["p"], 4),
            "edge": round(f["ev"]["edge"], 4), "margen": round(f["ev"]["margen"], 4),
            "verde": "🟢" if f["ev"]["verde"] else "", "importe": importe,
            "tope_restante": max(0.0, queda), "estado": "pendiente",
            "resultado": "", "beneficio": "", "tipo_aviso": "apuesta",
            "inicio": inicio, "match_id": datos["id"], "jornada": "",
            "orden_j1": w["orden"],
            "seleccion_json": json.dumps(f["s"]["sel"], ensure_ascii=False),
        })
        if ok:
            st.success("✅ Apuntada en 🔔 Alertas. Márcala allí como «apostada» "
                       "cuando la hagas (o «no apostada» para devolver el importe al tope).")
        else:
            st.error(f"❌ No se pudo apuntar: {error}")
