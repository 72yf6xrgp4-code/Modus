"""
alertas_ui.py - Pestana 'Alertas' y seguimiento de las apuestas del vigia.

El vigia (vigia/, en el portatil) escribe los avisos en la pestana
'alertas' del Google Sheet de predicciones. Aqui solo se LEEN (cache de
60 s y boton Actualizar, sin autorefresco ni tareas en segundo plano). La
unica escritura es la del boton apostada / no apostada: cambia la celda
'estado' de esa alerta. Si se marca 'no apostada', su importe vuelve al
tope del dia (el vigia lo recalcula leyendo la hoja).

Las apuestas son personales: todo se muestra solo en modo administrador.
"""

import html as html_mod

import pandas as pd
import streamlit as st

from config import SHEET_ID_PREDICCIONES
from helpers import es_admin, fecha_jornada_madrid
from vigia.registro import (HOJA_ALERTAS, COLUMNAS_ALERTAS, AVISO_APUESTA,
                            AVISO_REVISAR, ESTADO_APOSTADA,
                            ESTADO_NO_APOSTADA, ESTADO_PENDIENTE,
                            filas_a_dicts, gastado_del_dia, num,
                            resumen_apuestas, beneficio_fila)
from vigia.reglas import TOPE_DIARIO


def _hoja_alertas():
    """(worksheet, error) de la pestana 'alertas'."""
    try:
        from predicciones import _conectar_gsheets
    except Exception as e:
        return None, f"No se pudo cargar la conexion con Google: {e}"
    cliente, err = _conectar_gsheets()
    if cliente is None:
        return None, err
    try:
        return cliente.open_by_key(SHEET_ID_PREDICCIONES).worksheet(HOJA_ALERTAS), ""
    except Exception as e:
        return None, (f"No se encontro la pestana '{HOJA_ALERTAS}' ({type(e).__name__}). "
                      f"La crea el vigia la primera vez que se ejecuta.")


@st.cache_data(ttl=60, show_spinner=False)
def cargar_alertas():
    """Filas de la pestana 'alertas' como dicts (o (None, error))."""
    ws, err = _hoja_alertas()
    if ws is None:
        return None, err
    try:
        return filas_a_dicts(ws.get_all_values()), ""
    except Exception as e:
        return None, f"Error leyendo las alertas: {e}"


def _marcar(fila, estado):
    ws, err = _hoja_alertas()
    if ws is None:
        st.error(err)
        return
    try:
        ws.update_cell(fila["_fila"], COLUMNAS_ALERTAS.index("estado") + 1, estado)
    except Exception as e:
        st.error(f"No se pudo guardar: {e}")
        return
    cargar_alertas.clear()
    st.rerun()


def _eur(v):
    """7.5 -> '7,5 €'; 50 -> '50 €'; -1.875 -> '-1,88 €'"""
    t = f"{v:.2f}".rstrip("0").rstrip(".")
    return t.replace(".", ",") + " €"


def _pct(v):
    return "—" if v is None else f"{v*100:.1f} %".replace(".", ",")


def _boton_actualizar(key):
    if st.button("🔄 Actualizar", key=key):
        cargar_alertas.clear()
        st.rerun()


def _tarjeta(f):
    revisar = f.get("tipo_aviso") == AVISO_REVISAR
    estado = f.get("estado", "")
    color = {"apostada": "#16a34a", "no apostada": "#94a3b8",
             "revisar": "#f59e0b"}.get(estado, "#2563eb")
    res = f.get("resultado") or ""
    res_txt = {"ganada": "✅ ganada", "perdida": "❌ perdida"}.get(res, "")
    importe = "" if revisar else f" · <b>{_eur(num(f.get('importe')))}</b>"
    cuota = f"{num(f.get('cuota')):.2f}".replace(".", ",")
    e = lambda x: html_mod.escape(str(x or ""))  # noqa: E731
    st.markdown(
        f"<div style='border-left:5px solid {color};background:rgba(148,163,184,0.08);"
        f"border-radius:8px;padding:10px 14px;margin:6px 0;'>"
        f"<div style='font-size:12px;color:#64748b;'>{e(f.get('inicio') or f.get('hora'))}"
        f" · {e(f.get('mercado'))} · {e(estado)} {res_txt}</div>"
        f"<div style='font-size:16px;font-weight:700;'>{'⚠️ REVISAR · ' if revisar else ''}"
        f"{e(f.get('partido'))}</div>"
        f"<div style='font-size:14px;'>{e(f.get('seleccion'))} @{cuota}"
        f" · modelo {num(f.get('p_modelo'))*100:.0f} % · edge {num(f.get('edge'))*100:.0f} %"
        f" {e(f.get('verde'))}{importe}</div></div>",
        unsafe_allow_html=True)


def render_alertas():
    st.caption("Avisos del vigía de Winamax. Se actualiza al pulsar "
               "**Actualizar** (o solo, cada minuto como mucho).")
    if not es_admin():
        st.info("🔒 Las alertas solo se ven en modo administrador.")
        return
    _boton_actualizar("al_actualizar")
    filas, err = cargar_alertas()
    if filas is None:
        st.warning(f"⚠️ {err}")
        return

    hoy = fecha_jornada_madrid()
    de_hoy = [f for f in filas if f.get("fecha") == hoy]
    gastado = gastado_del_dia(filas, hoy)
    c1, c2, c3 = st.columns(3)
    c1.metric("Avisos hoy", len(de_hoy))
    c2.metric("Tope gastado", _eur(gastado), help=f"Tope diario: {_eur(TOPE_DIARIO)}")
    c3.metric("Queda", _eur(max(0.0, TOPE_DIARIO - gastado)))
    st.progress(min(1.0, gastado / TOPE_DIARIO) if TOPE_DIARIO else 0.0)

    st.subheader("Hoy")
    if not de_hoy:
        st.info("Sin avisos hoy.")
    for f in sorted(de_hoy, key=lambda x: x.get("hora", ""), reverse=True):
        _tarjeta(f)
        if f.get("tipo_aviso") == AVISO_APUESTA:
            b1, b2, _ = st.columns([1, 1, 3])
            if b1.button("✅ Apostada", key=f"al_si_{f['_fila']}",
                         disabled=f.get("estado") == ESTADO_APOSTADA):
                _marcar(f, ESTADO_APOSTADA)
            if b2.button("❌ No apostada", key=f"al_no_{f['_fila']}",
                         disabled=f.get("estado") == ESTADO_NO_APOSTADA):
                _marcar(f, ESTADO_NO_APOSTADA)

    st.subheader("Histórico")
    anteriores = [f for f in filas if f.get("fecha") != hoy]
    _bloque_resumen(filas)
    pendientes = [f for f in anteriores if f.get("tipo_aviso") == AVISO_APUESTA
                  and f.get("estado") == ESTADO_PENDIENTE]
    if pendientes:
        st.caption(f"⚠️ {len(pendientes)} avisos de días anteriores siguen sin marcar "
                   "como apostada / no apostada:")
        for f in pendientes[-10:]:
            _tarjeta(f)
            b1, b2, _ = st.columns([1, 1, 3])
            if b1.button("✅ Apostada", key=f"al_si_{f['_fila']}"):
                _marcar(f, ESTADO_APOSTADA)
            if b2.button("❌ No apostada", key=f"al_no_{f['_fila']}"):
                _marcar(f, ESTADO_NO_APOSTADA)
    if anteriores:
        with st.expander(f"📋 Todas las alertas anteriores ({len(anteriores)})"):
            st.dataframe(_tabla(anteriores), use_container_width=True, hide_index=True)


def _tabla(filas):
    cols = ["fecha", "hora", "partido", "mercado", "seleccion", "cuota",
            "p_modelo", "edge", "verde", "importe", "estado", "resultado",
            "beneficio"]
    df = pd.DataFrame([{c: f.get(c, "") for c in cols} for f in filas])
    return df.iloc[::-1]


def _bloque_resumen(filas):
    """Dos columnas: lo que de verdad apostaste y 'si las hubieses hecho
    todas' (todas las alertas de apuesta con su importe recomendado)."""
    real = resumen_apuestas(filas, solo_apostadas=True)
    todas = resumen_apuestas(filas, solo_apostadas=False)
    col_r, col_t = st.columns(2)
    for col, titulo, r in ((col_r, "💶 Las que apostaste", real),
                           (col_t, "🧪 Si las hubieras hecho todas", todas)):
        with col:
            st.markdown(f"**{titulo}**")
            a, b = st.columns(2)
            a.metric("Beneficio", _eur(r["beneficio"]))
            b.metric("ROI", _pct(r["roi"]))
            a.metric("Acierto", _pct(r["acierto"]),
                     help=f"{r['ganadas']} de {r['liquidadas']} liquidadas")
            b.metric("Apostado", _eur(r["invertido"]),
                     help=f"{r['pendientes']} sin resultado todavía")


def render_seguimiento_apuestas():
    """Bloque para la pestana Seguimiento: evolucion de las apuestas que
    indico el vigia, reales y 'si las hubieses hecho todas'."""
    st.markdown("---")
    st.subheader("🎯 Apuestas del vigía")
    if not es_admin():
        st.info("🔒 El seguimiento de apuestas solo se ve en modo administrador.")
        return
    _boton_actualizar("seg_ap_actualizar")
    filas, err = cargar_alertas()
    if filas is None:
        st.warning(f"⚠️ {err}")
        return
    apuestas = [f for f in filas if f.get("tipo_aviso") == AVISO_APUESTA]
    if not apuestas:
        st.info("Todavía no hay apuestas del vigía.")
        return
    _bloque_resumen(filas)

    liquidadas = [f for f in apuestas if f.get("resultado") in ("ganada", "perdida")]
    if liquidadas:
        df = pd.DataFrame([{
            "fecha": f.get("fecha"), "hora": f.get("hora", ""),
            "mercado": f.get("mercado", ""),
            "todas": beneficio_fila(f),
            "real": beneficio_fila(f) if f.get("estado") == ESTADO_APOSTADA else 0.0,
            "importe": num(f.get("importe")),
            "ganada": f.get("resultado") == "ganada",
        } for f in liquidadas]).sort_values(["fecha", "hora"])
        evol = df.groupby("fecha")[["todas", "real"]].sum().cumsum()
        evol.columns = ["Si las hubieras hecho todas", "Las que apostaste"]
        st.markdown("**Beneficio acumulado (€)**")
        st.line_chart(evol, height=260)

        por_mercado = df.groupby("mercado").agg(
            apuestas=("ganada", "size"), aciertos=("ganada", "sum"),
            apostado=("importe", "sum"), beneficio=("todas", "sum"))
        por_mercado["beneficio"] = por_mercado["beneficio"].round(2)
        por_mercado["ROI %"] = (100 * por_mercado["beneficio"]
                                / por_mercado["apostado"]).round(1)
        st.markdown("**Por mercado (si las hubieras hecho todas)**")
        st.dataframe(por_mercado, use_container_width=True)
    revisar = sum(1 for f in filas if f.get("tipo_aviso") == AVISO_REVISAR)
    if revisar:
        st.caption(f"⚠️ Avisos «REVISAR» (margen > 20 puntos): {revisar}. No cuentan "
                   "aquí porque no tenían importe.")
