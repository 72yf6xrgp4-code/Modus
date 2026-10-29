"""
alertas_ui.py - Pestana 'Apuestas' (antes 'Alertas'): las apuestas apuntadas desde Value Bets
(boton "Modus value" -> "Apuntar apuesta"), el tope de la jornada y el
historico con resultado, beneficio y ROI.

Las filas viven en la pestana 'alertas' del Google Sheet de predicciones.
Se leen con cache de 60 s y boton Actualizar (sin autorefresco ni tareas en
segundo plano). Escrituras: apuntar una apuesta y los botones apostada /
no apostada (cambian la celda 'estado'; una 'no apostada' devuelve su
importe al tope). El resultado y el beneficio los apunta el vigia (del
portatil o de GitHub) y, por si ninguno esta en marcha, tambien esta
pestana al abrirla (como mucho cada 10 minutos, o al pulsar Actualizar).

Las apuestas son personales: todo se muestra solo en modo administrador.
"""

import html as html_mod
import time

import pandas as pd
import streamlit as st

from config import SHEET_ID_PREDICCIONES
from helpers import es_admin, fecha_jornada_madrid
from vigia.registro import (HOJA_ALERTAS, COLUMNAS_ALERTAS, HOJA_WINAMAX,
                            COLUMNAS_WINAMAX, estadisticas_winamax, AVISO_APUESTA,
                            AVISO_REVISAR, ESTADO_APOSTADA,
                            ESTADO_NO_APOSTADA, ESTADO_PENDIENTE,
                            filas_a_dicts, gastado_del_dia, num,
                            resumen_apuestas, beneficio_fila, importe_apostado)
from vigia.registro import (beneficio_real, por_mercado, por_mercado_y_volatilidad,
                            mejores_por_partido, tope_del_dia, MIN_PREVIOS)
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
                      f"Se crea al apuntar la primera apuesta (o al arrancar el vigia).")


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


def anadir_alerta(fila):
    """Anade una fila a 'alertas' (la crea si no existe). (ok, error)"""
    from predicciones import _conectar_gsheets
    cliente, err = _conectar_gsheets()
    if cliente is None:
        return False, err
    try:
        libro = cliente.open_by_key(SHEET_ID_PREDICCIONES)
        try:
            ws = libro.worksheet(HOJA_ALERTAS)
            _asegurar_cabecera(ws)
        except Exception:
            ws = libro.add_worksheet(title=HOJA_ALERTAS, rows=1000,
                                     cols=len(COLUMNAS_ALERTAS))
            ws.append_row(COLUMNAS_ALERTAS)
        ws.append_row([fila.get(c, "") for c in COLUMNAS_ALERTAS],
                      value_input_option="RAW")
    except Exception as e:
        return False, str(e)
    cargar_alertas.clear()
    return True, ""


def _asegurar_cabecera(ws, columnas=COLUMNAS_ALERTAS):
    """Si la hoja tiene la cabecera de una version anterior (le faltan
    columnas nuevas del final, como importe_real o n_partido), la completa."""
    cab = ws.row_values(1)
    if cab != columnas and columnas[:len(cab)] == cab:
        if ws.col_count < len(columnas):
            ws.add_cols(len(columnas) - ws.col_count)
        ws.update(range_name="A1", values=[columnas])


def actualizar_campos(fila, campos):
    """Cambia varias celdas de una alerta en una peticion. (ok, error)"""
    from gspread.utils import rowcol_to_a1
    ws, err = _hoja_alertas()
    if ws is None:
        return False, err
    try:
        _asegurar_cabecera(ws)
        ws.batch_update([{"range": rowcol_to_a1(fila["_fila"], COLUMNAS_ALERTAS.index(c) + 1),
                          "values": [[v]]} for c, v in campos.items()],
                        value_input_option="RAW")
    except Exception as e:
        return False, str(e)
    cargar_alertas.clear()
    return True, ""


def marcar_estado(fila, estado, importe_real=None):
    """Cambia el estado de una alerta (y, si se indica, el importe que de
    verdad apostaste). (ok, error)"""
    campos = {"estado": estado}
    if importe_real is not None:
        campos["importe_real"] = importe_real
    return actualizar_campos(fila, campos)


def cambiar_importe(fila, importe):
    """Importe que de verdad apostaste. Solo cuenta para tus apuestas (tope,
    beneficio real); las estadisticas del modelo siguen con el recomendado.
    Si coincide con el recomendado, se deja vacio. (ok, error)"""
    real = "" if abs(importe - num(fila.get("importe"))) < 1e-9 else importe
    campos = {"importe_real": real}
    if fila.get("resultado") in ("ganada", "perdida"):
        campos["beneficio"] = round(beneficio_fila(dict(fila, importe_real=real), real=True), 2)
    return actualizar_campos(fila, campos)


def _pestana(nombre, columnas):
    """(worksheet, error) de una pestana del Sheet de predicciones; la crea
    con su cabecera si no existe."""
    try:
        from predicciones import _conectar_gsheets
    except Exception as e:
        return None, f"No se pudo cargar la conexion con Google: {e}"
    cliente, err = _conectar_gsheets()
    if cliente is None:
        return None, err
    try:
        libro = cliente.open_by_key(SHEET_ID_PREDICCIONES)
        try:
            return libro.worksheet(nombre), ""
        except Exception:
            ws = libro.add_worksheet(title=nombre, rows=2000, cols=len(columnas))
            ws.append_row(columnas)
            return ws, ""
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=60, show_spinner=False)
def cargar_winamax():
    """Filas de la pestana 'cuotas_winamax' (o (None, error))."""
    ws, err = _pestana(HOJA_WINAMAX, COLUMNAS_WINAMAX)
    if ws is None:
        return None, err
    try:
        return filas_a_dicts(ws.get_all_values()), ""
    except Exception as e:
        return None, f"Error leyendo las cuotas de Winamax: {e}"


def anadir_winamax(filas):
    """Guarda las cuotas leidas con el boton (una peticion). (ok, error)"""
    ws, err = _pestana(HOJA_WINAMAX, COLUMNAS_WINAMAX)
    if ws is None:
        return False, err
    try:
        _asegurar_cabecera(ws, COLUMNAS_WINAMAX)
        ws.append_rows([[f.get(c, "") for c in COLUMNAS_WINAMAX] for f in filas],
                       value_input_option="RAW")
    except Exception as e:
        return False, str(e)
    cargar_winamax.clear()
    return True, ""


def eliminar_alerta(fila):
    """Borra la fila de la alerta en la hoja. Antes comprueba que en esa
    fila sigue estando la misma alerta (la lista va con cache de 60 s y la
    hoja puede haber cambiado). (ok, error)"""
    ws, err = _hoja_alertas()
    if ws is None:
        return False, err
    try:
        actual = ws.row_values(fila["_fila"])
        cab = COLUMNAS_ALERTAS
        def v(c):
            k = cab.index(c)
            return str(actual[k]).strip() if k < len(actual) else ""
        for c in ("fecha", "hora", "partido", "seleccion"):
            if v(c) != str(fila.get(c, "")).strip():
                return False, ("la hoja ha cambiado desde que se cargó; pulsa "
                               "«Actualizar» y vuelve a intentarlo")
        ws.delete_rows(fila["_fila"])
    except Exception as e:
        return False, str(e)
    cargar_alertas.clear()
    return True, ""


def _botones(f, clave, marcar=True):
    """Apostada / No apostada / Eliminar debajo de una tarjeta."""
    b1, b2, b3, b4, _ = st.columns([1, 1, 1, 1, 1])
    if marcar and f.get("tipo_aviso") == AVISO_APUESTA:
        if b1.button("✅ Apostada", key=f"al_si_{clave}",
                     disabled=f.get("estado") == ESTADO_APOSTADA):
            _marcar(f, ESTADO_APOSTADA)
        if b2.button("❌ No apostada", key=f"al_no_{clave}",
                     disabled=f.get("estado") == ESTADO_NO_APOSTADA):
            _marcar(f, ESTADO_NO_APOSTADA)
    if f.get("tipo_aviso") == AVISO_APUESTA and f.get("estado") != ESTADO_NO_APOSTADA:
        with b4.popover("✏️ Importe"):
            popover_importe(f, clave)
    with b3.popover("🗑️ Eliminar"):
        st.markdown(f"¿Eliminar **{html_mod.escape(str(f.get('seleccion', '')))}** "
                    f"({html_mod.escape(str(f.get('partido', '')))}, {f.get('fecha', '')})? "
                    "Se borra de la hoja y no se puede deshacer.")
        if st.button("Sí, eliminar", key=f"al_del_{clave}", type="primary"):
            ok, error = eliminar_alerta(f)
            if ok:
                st.rerun()
            st.error(f"No se pudo eliminar: {error}")


def popover_importe(f, clave):
    """Contenido del desplegable para cambiar lo que de verdad apostaste."""
    rec = num(f.get("importe"))
    st.markdown(f"Recomendado: **{_eur(rec)}**. El importe que pongas solo cuenta para "
                "tus apuestas (tope y beneficio real); las estadísticas del modelo "
                "siguen con el recomendado.")
    nuevo = st.number_input("Importe apostado (€)", min_value=0.5, step=0.5,
                            value=float(importe_apostado(f) or rec or 5.0),
                            key=f"al_imp_{clave}")
    if st.button("Guardar importe", key=f"al_imp_ok_{clave}", type="primary"):
        ok, error = cambiar_importe(f, nuevo)
        if ok:
            st.rerun()
        st.error(f"No se pudo guardar: {error}")


def _marcar(fila, estado):
    ok, error = marcar_estado(fila, estado)
    if not ok:
        st.error(f"No se pudo guardar: {error}")
        return
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
        cargar_winamax.clear()
        st.session_state.pop("_liq_t", None)   # y vuelve a buscar resultados
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# RESULTADOS DESDE LA APP (por si el vigia no esta en marcha)
# ─────────────────────────────────────────────────────────────────────────────

LIQUIDAR_CADA_SEG = 600


class _HojaApp:
    """Lo que necesita Vigia.liquidar, con la conexion de la app. Las
    escrituras se juntan y se hacen en una peticion por pestana."""

    def __init__(self, ws_alertas, ws_winamax):
        self.ws_alertas, self.ws_winamax = ws_alertas, ws_winamax
        self._cambios = []

    def alertas(self):
        return filas_a_dicts(self.ws_alertas.get_all_values())

    def actualizar_alerta(self, n_fila, campos):
        self._cambios.append((n_fila, campos))

    def filas_winamax(self):
        return filas_a_dicts(self.ws_winamax.get_all_values()) if self.ws_winamax else []

    def actualizar_winamax(self, cambios):
        from vigia.hoja import _celdas
        _asegurar_cabecera(self.ws_winamax, COLUMNAS_WINAMAX)
        self.ws_winamax.batch_update(_celdas(COLUMNAS_WINAMAX, cambios),
                                     value_input_option="RAW")

    def log(self, fila):
        pass

    def volcar(self):
        from vigia.hoja import _celdas
        if not self._cambios:
            return
        _asegurar_cabecera(self.ws_alertas)
        self.ws_alertas.batch_update(_celdas(COLUMNAS_ALERTAS, self._cambios),
                                     value_input_option="RAW")


def _pendientes(filas):
    return any(f.get("tipo_aviso") == AVISO_APUESTA
               and f.get("resultado") not in ("ganada", "perdida") for f in filas)


def liquidar_desde_app(filas):
    """Apunta el resultado de las apuestas (y de las cuotas de Winamax
    guardadas) cuyos partidos ya han terminado, leyendo las hojas de las
    jornadas. Lo mismo que hace el vigia. (n, error)"""
    wm, _ = cargar_winamax()
    if not _pendientes(filas) and not any(
            f.get("seleccion_json") and f.get("resultado") not in ("ganada", "perdida")
            for f in (wm or [])):
        return 0, ""
    from vigia.nucleo import DatosSheet, Vigia
    ws, err = _hoja_alertas()
    if ws is None:
        return 0, err
    ws_wm, _ = _pestana(HOJA_WINAMAX, COLUMNAS_WINAMAX)
    try:
        hoja = _HojaApp(ws, ws_wm)
        n = Vigia(hoja, None, DatosSheet(), None).liquidar()
        hoja.volcar()
    except Exception as e:
        return 0, str(e)
    if n:
        cargar_alertas.clear()
        cargar_winamax.clear()
    return n, ""


def _liquidar_al_abrir(filas):
    """Como mucho cada LIQUIDAR_CADA_SEG por sesion (o al pulsar Actualizar)."""
    if time.time() - st.session_state.get("_liq_t", 0) < LIQUIDAR_CADA_SEG:
        return False
    st.session_state["_liq_t"] = time.time()
    n, err = liquidar_desde_app(filas)
    if err:
        st.caption(f"⚠️ No se pudieron apuntar los resultados: {err}")
    elif n:
        st.toast(f"✅ {n} resultados nuevos apuntados")
    return n > 0


def _tarjeta(f):
    revisar = f.get("tipo_aviso") == AVISO_REVISAR
    estado = f.get("estado", "")
    color = {"apostada": "#16a34a", "no apostada": "#94a3b8",
             "revisar": "#f59e0b"}.get(estado, "#2563eb")
    res = f.get("resultado") or ""
    res_txt = {"ganada": "✅ ganada", "perdida": "❌ perdida"}.get(res, "")
    importe = "" if revisar else f" · <b>{_eur(importe_apostado(f))}</b>"
    if not revisar and str(f.get("importe_real") or "").strip():
        importe += f" <span style='color:#64748b'>(recomendado {_eur(num(f.get('importe')))})</span>"
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
    st.caption("Apuestas marcadas en Value Bets («Apostar» / «No la apuesto»). "
               "Se actualiza al pulsar **Actualizar** (o solo, cada minuto como mucho).")
    if not es_admin():
        st.info("🔒 Las apuestas solo se ven en modo administrador.")
        return
    _instalar_boton()
    _boton_actualizar("al_actualizar")
    filas, err = cargar_alertas()
    if filas is None:
        st.warning(f"⚠️ {err}")
        return
    if _liquidar_al_abrir(filas):
        filas, _ = cargar_alertas()

    hoy = fecha_jornada_madrid()
    de_hoy = [f for f in filas if f.get("fecha") == hoy]
    gastado = gastado_del_dia(filas, hoy)
    c1, c2, c3 = st.columns(3)
    c1.metric("Apuestas hoy", len(de_hoy))
    tope = tope_del_dia(filas)
    c2.metric("Tope gastado", _eur(gastado),
              help=f"Tope de hoy: {_eur(tope)} = {_eur(TOPE_DIARIO)} + tu beneficio "
                   f"real acumulado ({_eur(beneficio_real(filas))}, si es positivo)")
    c3.metric("Queda", _eur(max(0.0, tope - gastado)))
    st.progress(min(1.0, gastado / tope) if tope else 0.0)

    st.subheader("Hoy")
    if not de_hoy:
        st.info("Sin apuestas apuntadas hoy.")
    for f in sorted(de_hoy, key=lambda x: x.get("hora", ""), reverse=True):
        _tarjeta(f)
        _botones(f, f["_fila"])

    st.subheader("Histórico")
    anteriores = [f for f in filas if f.get("fecha") != hoy]
    wm, _ = cargar_winamax()
    todas = mejores_por_partido(wm or [])
    _bloque_resumen(filas, todas)
    pendientes = [f for f in anteriores if f.get("tipo_aviso") == AVISO_APUESTA
                  and f.get("estado") == ESTADO_PENDIENTE]
    if pendientes:
        st.caption(f"⚠️ {len(pendientes)} avisos de días anteriores siguen sin marcar "
                   "como apostada / no apostada:")
        for f in pendientes[-10:]:
            _tarjeta(f)
            _botones(f, f["_fila"])
    _evolucion(filas, todas)
    _por_mercado(filas, todas)
    if anteriores:
        with st.expander(f"📋 Todas las apuestas anteriores ({len(anteriores)})"):
            st.dataframe(_tabla(anteriores), use_container_width=True, hide_index=True)
            st.markdown("**Eliminar una apuesta anterior**")
            lista = list(reversed(anteriores))
            i = st.selectbox("Apuesta", range(len(lista)), key="al_del_sel",
                             format_func=lambda k: (f"{lista[k].get('fecha')} {lista[k].get('hora')} · "
                                                    f"{lista[k].get('partido')} · "
                                                    f"{lista[k].get('seleccion')}"),
                             label_visibility="collapsed")
            _botones(lista[i], f"ant_{lista[i]['_fila']}", marcar=False)
    _estadisticas_winamax()


def _tabla(filas):
    cols = ["fecha", "hora", "partido", "mercado", "seleccion", "cuota",
            "p_modelo", "edge", "verde", "importe", "importe_real", "estado",
            "resultado", "beneficio"]
    df = pd.DataFrame([{c: f.get(c, "") for c in cols} for f in filas])
    df = df.rename(columns={"importe": "recomendado", "importe_real": "apostado"})
    return df.iloc[::-1]


def _bloque_resumen(filas, mejores):
    """Dos columnas: lo que de verdad apostaste y 'si las hubieses hecho
    todas' (la mejor apuesta de cada partido fiable leido con el boton, con
    el importe del modelo: registro.mejores_por_partido)."""
    real = resumen_apuestas(filas, solo_apostadas=True)
    todas = resumen_apuestas(mejores, solo_apostadas=False)
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
    st.caption(f"🧪 «Si las hubieras hecho todas»: de cada partido que leíste con el "
               f"botón «Modus value» y en el que los dos jugadores llevaban {MIN_PREVIOS} "
               f"partidos o más esa semana, la mejor apuesta (la de más edge entre las "
               f"que tu regla manda apostar), con el importe que indicaba el modelo.")


def _evolucion(filas, mejores):
    """Beneficio acumulado: lo que apostaste y 'si las hubieras hecho todas'."""
    reales = [f for f in filas if f.get("tipo_aviso") == AVISO_APUESTA
              and f.get("estado") == ESTADO_APOSTADA
              and f.get("resultado") in ("ganada", "perdida")]
    todas = [f for f in mejores if f.get("resultado") in ("ganada", "perdida")]
    if not reales and not todas:
        return
    df = pd.DataFrame(
        [{"fecha": f.get("fecha"), "real": beneficio_fila(f, real=True), "todas": 0.0}
         for f in reales]
        + [{"fecha": f.get("fecha"), "real": 0.0, "todas": beneficio_fila(f)} for f in todas])
    evol = df.groupby("fecha")[["todas", "real"]].sum().sort_index().cumsum()
    evol.columns = ["Si las hubieras hecho todas", "Las que apostaste"]
    st.markdown("**Beneficio acumulado (€)**")
    st.line_chart(evol, height=240)


def _tabla_mercados(grupos):
    """DataFrame del seguimiento por mercado (todas / las que apostaste)."""
    def pct(v):
        return "—" if v is None else f"{v*100:.1f} %".replace(".", ",")
    filas = []
    for g in grupos:
        t, r = g["todas"], g["reales"]
        filas.append({
            "Mercado": g["mercado"],
            "Apuestas": t["n"], "Liquidadas": t["liq"], "Acierto": pct(t["acierto"]),
            "Apostado": _eur(t["apostado"]), "Beneficio": _eur(t["beneficio"]),
            "ROI": pct(t["roi"]),
            "Apostadas de verdad": r["liq"], "Beneficio real": _eur(r["beneficio"]),
            "ROI real": pct(r["roi"]),
        })
    return pd.DataFrame(filas)


def _por_mercado(filas, mejores):
    """Seguimiento de cada mercado por separado, sin y con volatilidad."""
    if not mejores and not any(f.get("tipo_aviso") == AVISO_APUESTA for f in filas):
        return
    st.markdown("#### 📊 Seguimiento por mercado")
    sin_vol, con_vol = st.tabs(["Sin volatilidad", "Con volatilidad"])
    with sin_vol:
        st.caption("Cada mercado por separado, sin tener en cuenta la volatilidad. "
                   "«Apuestas»: si las hubieras hecho todas (la mejor de cada partido "
                   "fiable leído con el botón, con el importe del modelo); «real»: las que "
                   "marcaste como apostadas, con lo que de verdad apostaste.")
        grupos, _ = por_mercado(filas, todas=mejores)
        st.dataframe(_tabla_mercados(grupos), use_container_width=True, hide_index=True)
    with con_vol:
        st.caption("Lo mismo aplicando la regla de volatilidad del vigía: con volatilidad "
                   "alta se exige más edge (+2 puntos por punto por encima de 12) y el "
                   "importe baja un escalón; con más de 18 o sin dato, la apuesta no "
                   "cuenta. Compáralo con la otra pestaña para ver si la regla compensa.")
        grupos, excluidas = por_mercado(filas, con_volatilidad=True, todas=mejores)
        if grupos:
            st.dataframe(_tabla_mercados(grupos), use_container_width=True, hide_index=True)
        if excluidas:
            st.caption(f"Apuestas que la regla habría descartado (o sin dato de "
                       f"volatilidad): {excluidas}.")
        st.markdown("**Por nivel de volatilidad del partido** (si las hubieras hecho todas)")
        niveles = por_mercado_y_volatilidad(mejores)
        orden = ["baja/media", "alta", "sin dato"]
        tabla = []
        for mercado in sorted({m for m, _ in niveles}):
            fila = {"Mercado": mercado}
            for nivel in orden:
                g = niveles.get((mercado, nivel))
                if not g or not g["liq"]:
                    fila[nivel] = "—"
                else:
                    roi = "—" if g["roi"] is None else f"{g['roi']*100:+.0f} %"
                    fila[nivel] = (f"{g['ganadas']}/{g['liq']} · ROI {roi}").replace(".", ",")
            tabla.append(fila)
        st.dataframe(pd.DataFrame(tabla), use_container_width=True, hide_index=True)
        st.caption("Cada casilla: ganadas / liquidadas · ROI. El nivel es el del jugador "
                   "más irregular del partido.")


def _estadisticas_winamax():
    """Cuotas de Winamax guardadas con el boton, frente al modelo."""
    st.markdown("#### 🌐 Winamax frente al modelo")
    filas, err = cargar_winamax()
    if filas is None:
        st.caption(f"⚠️ {err}")
        return
    if not filas:
        st.info("Aún no hay cuotas guardadas. Cada vez que uses el botón «Modus value» se "
                "guardan todas las cuotas leídas en la pestaña cuotas_winamax; el vigía "
                "apunta después si se cumplieron.")
        return
    e = estadisticas_winamax(filas)
    r = e["resumen"]
    a, b, c = st.columns(3)
    a.metric("Partidos leídos", r["lecturas"])
    b.metric("Cuotas guardadas", r["cuotas"])
    c.metric("Con resultado", r["liquidadas"])

    def pct(v, signo=False):
        if v is None:
            return "—"
        return (f"{v*100:+.1f} %" if signo else f"{v*100:.1f} %").replace(".", ",")

    t1, t2, t3 = st.tabs(["Por edge", "Modelo vs Winamax", "Margen de Winamax"])
    with t1:
        st.caption("Si hubieras apostado 1 € a TODAS las cuotas leídas, según el edge "
                   "que daba el modelo. Sirve para ver a partir de qué edge gana.")
        st.dataframe(pd.DataFrame([{
            "Edge": t["nombre"], "Apuestas": t["n"], "Ganadas": t["ganadas"],
            "Beneficio": _eur(t["beneficio"]), "ROI": pct(t["roi"], True)} for t in e["tramos"]]),
            use_container_width=True, hide_index=True)
        if e["mercados"]:
            st.markdown("**Con edge de 20 % o más, por mercado**")
            st.dataframe(pd.DataFrame([{
                "Mercado": t["nombre"], "Apuestas": t["n"], "Ganadas": t["ganadas"],
                "Beneficio": _eur(t["beneficio"]), "ROI": pct(t["roi"], True)}
                for t in e["mercados"]]), use_container_width=True, hide_index=True)
    with t2:
        st.caption("Quién estima mejor la probabilidad de cada selección: el modelo o "
                   "las cuotas de Winamax (sin su margen). Puntuación de Brier: cuanto "
                   "más baja, mejor.")
        if e["precision"]:
            st.dataframe(pd.DataFrame([{
                "Mercado": p["mercado"], "Selecciones": p["n"],
                "Brier modelo": f"{p['brier_modelo']:.3f}".replace(".", ","),
                "Brier Winamax": f"{p['brier_winamax']:.3f}".replace(".", ","),
                "Mejor": p["mejor"]} for p in e["precision"]]),
                use_container_width=True, hide_index=True)
        else:
            st.info("Aún no hay selecciones con resultado.")
    with t3:
        st.caption("Lo que se queda Winamax en cada mercado: suma de 1/cuota de todas "
                   "las salidas menos 1. Cuanto más alto, peores cuotas.")
        st.dataframe(pd.DataFrame([{
            "Mercado": m["mercado"], "Veces leído": m["mercados"],
            "Margen medio": pct(m["margen"])} for m in e["margen"]]),
            use_container_width=True, hide_index=True)


def _instalar_boton():
    """Instrucciones y codigo del marcador "Modus value"."""
    from pathlib import Path
    from vigia.boton import VERSION_BOTON
    ruta = Path(__file__).resolve().parent / "boton" / "marcador.txt"
    try:
        codigo = ruta.read_text(encoding="utf-8").strip()
    except OSError:
        return
    with st.expander("🔖 Instalar el botón «Modus value»"):
        st.markdown(
            f"**Versión {VERSION_BOTON}.** Si ya lo tenías instalado y la app te "
            "avisa de que es antiguo, sustituye la dirección (URL) del marcador por "
            "este código.\n\n"
            "Lee **solo** las cuotas de la página de Winamax que tienes abierta "
            "y abre aquí Value Bets con el partido y las cuotas. No pide nada a "
            "Winamax, no inicia sesión, no toca el boleto y no apuesta.\n\n"
            "**Chrome / Edge (portátil):** muestra la barra de marcadores "
            "(Ctrl+Mayús+B) → clic derecho → *Añadir página* → nombre "
            "`Modus value` → en *URL* pega el código de abajo.\n\n"
            "**Safari (iPhone):** guarda cualquier página como marcador "
            "(compartir → *Añadir marcador*), llámalo `Modus value`; luego "
            "*Marcadores* → *Editar* → toca ese marcador y sustituye la "
            "dirección por el código de abajo. Para usarlo, con el partido "
            "abierto en Winamax, toca la barra de direcciones, escribe "
            "`Modus value` y elige el marcador.")
        st.code(codigo, language=None, wrap_lines=True)
