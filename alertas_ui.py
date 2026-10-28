"""
alertas_ui.py - Pestana 'Alertas': las apuestas apuntadas desde Value Bets
(boton "Modus value" -> "Apuntar apuesta"), el tope de la jornada y el
historico con resultado, beneficio y ROI.

Las filas viven en la pestana 'alertas' del Google Sheet de predicciones.
Se leen con cache de 60 s y boton Actualizar (sin autorefresco ni tareas en
segundo plano). Escrituras: apuntar una apuesta y los botones apostada /
no apostada (cambian la celda 'estado'; una 'no apostada' devuelve su
importe al tope). El resultado y el beneficio los apunta el vigia del
portatil leyendo los resultados de la hoja.

Las apuestas son personales: todo se muestra solo en modo administrador.
"""

import html as html_mod

import pandas as pd
import streamlit as st

from config import SHEET_ID_PREDICCIONES
from helpers import es_admin, fecha_jornada_madrid
from vigia.registro import (HOJA_ALERTAS, COLUMNAS_ALERTAS, HOJA_WINAMAX,
                            COLUMNAS_WINAMAX, estadisticas_winamax, AVISO_APUESTA,
                            AVISO_REVISAR, ESTADO_APOSTADA,
                            ESTADO_NO_APOSTADA, ESTADO_PENDIENTE,
                            filas_a_dicts, gastado_del_dia, num,
                            resumen_apuestas, beneficio_fila)
from vigia.registro import (beneficio_real, por_mercado, por_mercado_y_volatilidad,
                            tope_del_dia)
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


def marcar_estado(fila, estado):
    """Cambia la celda 'estado' de una alerta. (ok, error)"""
    ws, err = _hoja_alertas()
    if ws is None:
        return False, err
    try:
        ws.update_cell(fila["_fila"], COLUMNAS_ALERTAS.index("estado") + 1, estado)
    except Exception as e:
        return False, str(e)
    cargar_alertas.clear()
    return True, ""


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
    b1, b2, b3, _ = st.columns([1, 1, 1, 2])
    if marcar and f.get("tipo_aviso") == AVISO_APUESTA:
        if b1.button("✅ Apostada", key=f"al_si_{clave}",
                     disabled=f.get("estado") == ESTADO_APOSTADA):
            _marcar(f, ESTADO_APOSTADA)
        if b2.button("❌ No apostada", key=f"al_no_{clave}",
                     disabled=f.get("estado") == ESTADO_NO_APOSTADA):
            _marcar(f, ESTADO_NO_APOSTADA)
    with b3.popover("🗑️ Eliminar"):
        st.markdown(f"¿Eliminar **{html_mod.escape(str(f.get('seleccion', '')))}** "
                    f"({html_mod.escape(str(f.get('partido', '')))}, {f.get('fecha', '')})? "
                    "Se borra de la hoja y no se puede deshacer.")
        if st.button("Sí, eliminar", key=f"al_del_{clave}", type="primary"):
            ok, error = eliminar_alerta(f)
            if ok:
                st.rerun()
            st.error(f"No se pudo eliminar: {error}")


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
    st.caption("Apuestas marcadas en Value Bets («La he apostado» / «No la apuesto»). "
               "Se actualiza al pulsar **Actualizar** (o solo, cada minuto como mucho).")
    if not es_admin():
        st.info("🔒 Las alertas solo se ven en modo administrador.")
        return
    _instalar_boton()
    _boton_actualizar("al_actualizar")
    filas, err = cargar_alertas()
    if filas is None:
        st.warning(f"⚠️ {err}")
        return

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
    _bloque_resumen(filas)
    pendientes = [f for f in anteriores if f.get("tipo_aviso") == AVISO_APUESTA
                  and f.get("estado") == ESTADO_PENDIENTE]
    if pendientes:
        st.caption(f"⚠️ {len(pendientes)} avisos de días anteriores siguen sin marcar "
                   "como apostada / no apostada:")
        for f in pendientes[-10:]:
            _tarjeta(f)
            _botones(f, f["_fila"])
    _evolucion(filas)
    _por_mercado(filas)
    if anteriores:
        with st.expander(f"📋 Todas las alertas anteriores ({len(anteriores)})"):
            st.dataframe(_tabla(anteriores), use_container_width=True, hide_index=True)
            st.markdown("**Eliminar una alerta anterior**")
            lista = list(reversed(anteriores))
            i = st.selectbox("Alerta", range(len(lista)), key="al_del_sel",
                             format_func=lambda k: (f"{lista[k].get('fecha')} {lista[k].get('hora')} · "
                                                    f"{lista[k].get('partido')} · "
                                                    f"{lista[k].get('seleccion')}"),
                             label_visibility="collapsed")
            _botones(lista[i], f"ant_{lista[i]['_fila']}", marcar=False)
    _estadisticas_winamax()


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


def _evolucion(filas):
    """Beneficio acumulado y desglose por mercado de las apuestas liquidadas."""
    apuestas = [f for f in filas if f.get("tipo_aviso") == AVISO_APUESTA]
    liquidadas = [f for f in apuestas if f.get("resultado") in ("ganada", "perdida")]
    if not liquidadas:
        return
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


def _por_mercado(filas):
    """Seguimiento de cada mercado por separado, sin y con volatilidad."""
    if not any(f.get("tipo_aviso") == AVISO_APUESTA for f in filas):
        return
    st.markdown("#### 📊 Seguimiento por mercado")
    sin_vol, con_vol = st.tabs(["Sin volatilidad", "Con volatilidad"])
    with sin_vol:
        st.caption("Cada mercado por separado, sin tener en cuenta la volatilidad. "
                   "«Apuestas» son todas las que tuvieron value (las hicieras o no), con "
                   "su importe; «real» solo las que marcaste como apostadas.")
        grupos, _ = por_mercado(filas)
        st.dataframe(_tabla_mercados(grupos), use_container_width=True, hide_index=True)
    with con_vol:
        st.caption("Lo mismo aplicando la regla de volatilidad del vigía: con volatilidad "
                   "alta se exige más edge (+2 puntos por punto por encima de 12) y el "
                   "importe baja un escalón; con más de 18 o sin dato, la apuesta no "
                   "cuenta. Compáralo con la otra pestaña para ver si la regla compensa.")
        grupos, excluidas = por_mercado(filas, con_volatilidad=True)
        if grupos:
            st.dataframe(_tabla_mercados(grupos), use_container_width=True, hide_index=True)
        if excluidas:
            st.caption(f"Apuestas que la regla habría descartado (o sin dato de "
                       f"volatilidad): {excluidas}.")
        st.markdown("**Por nivel de volatilidad del partido** (todas las apuestas con value)")
        niveles = por_mercado_y_volatilidad(filas)
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
    ruta = Path(__file__).resolve().parent / "boton" / "marcador.txt"
    try:
        codigo = ruta.read_text(encoding="utf-8").strip()
    except OSError:
        return
    with st.expander("🔖 Instalar el botón «Modus value»"):
        st.markdown(
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
