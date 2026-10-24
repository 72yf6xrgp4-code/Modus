"""cierre_semanal.py — Script de cierre semanal automatico.

Disenado para ejecutarse cada domingo a las 05:00 Madrid via cron-job.org
(que llama a la API de GitHub Actions). Hace dos cosas:

  1. Guarda la 'foto' del Resumen Semanal en la pestana 'Historico' del
     Sheet (con la fecha del sabado de la semana que acaba de terminar).
  2. Verifica todos los partidos pendientes en la pestana 'Predicciones'
     (escribe la columna 'Acierto' segun los resultados reales).
  3. Guarda el campeon de la semana.
  4. Mueve a 'Predicciones caducadas' las de semanas ya cerradas que se
     quedaron sin verificar.

Apunta el resultado en la pestana 'Log Auto Registro' del Sheet con
jornada='Cierre Semanal' para distinguirlo del auto-registro diario.

USO:
  python cierre_semanal.py

VARIABLES DE ENTORNO REQUERIDAS:
  GOOGLE_SERVICE_ACCOUNT_JSON  - JSON de la cuenta de servicio Google.

EXIT CODES:
  0 - OK (cierre completado o no toca).
  1 - Error grave (configuracion, conexion, etc).
"""

from __future__ import annotations

import os
import sys
import json
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo


# ─────────────────────────────────────────────────────────────────────────────
# INICIALIZACION (mismo stub de Streamlit que auto_registrar.py)
# ─────────────────────────────────────────────────────────────────────────────

def configurar_credenciales():
    """Lee GOOGLE_SERVICE_ACCOUNT_JSON del entorno y monta un stub de
    streamlit para que data_loading y predicciones funcionen sin Streamlit.
    """
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        print("ERROR: no esta definida GOOGLE_SERVICE_ACCOUNT_JSON",
              file=sys.stderr)
        sys.exit(1)
    try:
        creds_dict = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: GOOGLE_SERVICE_ACCOUNT_JSON no es JSON valido: {e}",
              file=sys.stderr)
        sys.exit(1)

    import types
    st_stub = types.ModuleType("streamlit")
    st_stub.secrets = {"gcp_service_account": creds_dict}

    class _Cache:
        def __call__(self, *args, **kwargs):
            if len(args) == 1 and callable(args[0]) and not kwargs:
                return args[0]
            def decorador(fn):
                return fn
            return decorador
        def clear(self):
            pass

    st_stub.cache_data = _Cache()
    st_stub.cache_resource = _Cache()

    class _SS(dict):
        def __getattr__(self, k):
            if k not in self:
                if k == "last_update":
                    self[k] = {}
                else:
                    raise AttributeError(k)
            return self[k]
        def __setattr__(self, k, v): self[k] = v
        def get(self, k, d=None): return dict.get(self, k, d)

    st_stub.session_state = _SS()
    st_stub.session_state["last_update"] = {}

    def _noop(*a, **k):
        return None
    for fn in ("warning", "error", "info", "success", "write", "markdown",
                "caption", "title", "subheader", "spinner"):
        setattr(st_stub, fn, _noop)

    sys.modules["streamlit"] = st_stub


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    configurar_credenciales()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    wd = ahora.weekday()
    print(f"[cierre-semanal] {ahora.isoformat()} (wd={wd})")

    # ── Importar modulos de la app ────────────────────────────────────────
    try:
        from data_loading import cargar_jugadores_desde
        from predicciones import (
            guardar_historico_semana, verificar_resultados,
            escribir_log_auto, guardar_campeon_semana, archivar_caducadas,
        )
        from clasificacion import obtener_campeon_semana
    except Exception as e:
        print(f"ERROR importando modulos: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ── Filtro: solo domingos ─────────────────────────────────────────────
    # En el cron-job.org ya hemos configurado que solo se ejecute los
    # domingos. Pero por si acaso, doble verificacion aqui.
    if wd != 6:
        msg = f"hoy no es domingo (wd={wd}); cierre semanal NO se ejecuta"
        print(f"  -> {msg}")
        try:
            escribir_log_auto(
                jornada="Cierre Semanal", partidos_registrados=[],
                partidos_saltados=[], estado="NADA", detalles=msg,
            )
        except Exception:
            pass
        sys.exit(0)

    detalles_total = []
    estados = []

    # ── 1) Guardar historico ──────────────────────────────────────────────
    print("  -> Paso 1/2: guardar historico semanal")
    try:
        resumen = cargar_jugadores_desde("Resumen Semanal")
        if not resumen:
            msg_hist = "ERROR guardando historico: Resumen Semanal vacio"
            print(f"     {msg_hist}")
            detalles_total.append(msg_hist)
            estados.append("ERROR")
        else:
            res_hist = guardar_historico_semana(resumen)
            if res_hist.get("ok"):
                # guardar_historico_semana devuelve 'guardados' y 'sobrescrita'
                # (el log antes leia claves que no existen y siempre ponia 0)
                msg_hist = (
                    f"Historico guardado: semana {res_hist.get('fecha', '?')}, "
                    f"{res_hist.get('guardados', 0)} jugadores"
                    f"{' (sobrescrita)' if res_hist.get('sobrescrita') else ''}"
                )
                print(f"     {msg_hist}")
                detalles_total.append(msg_hist)
                estados.append("OK")
            else:
                msg_hist = (
                    f"ERROR guardando historico: "
                    f"{res_hist.get('error', 'desconocido')}"
                )
                print(f"     {msg_hist}")
                detalles_total.append(msg_hist)
                estados.append("ERROR")
    except Exception as e:
        msg_hist = f"EXCEPCION guardando historico: {e}"
        print(f"     {msg_hist}")
        traceback.print_exc()
        detalles_total.append(msg_hist)
        estados.append("ERROR")

    # ── 2) Verificar resultados ───────────────────────────────────────────
    print("  -> Paso 2/2: verificar resultados de la semana")
    try:
        res_ver = verificar_resultados()
        if res_ver.get("ok"):
            msg_ver = (
                f"Verificacion: {res_ver.get('verificadas', 0)} verificadas "
                f"({res_ver.get('aciertos', 0)} aciertos, "
                f"{res_ver.get('fallos', 0)} fallos), "
                f"{res_ver.get('sin_cambios', 0)} sin_cambios"
            )
            pendientes = res_ver.get("pendientes_diag", {})
            if pendientes:
                msg_ver += f", {len(pendientes)} pendientes"
            print(f"     {msg_ver}")
            detalles_total.append(msg_ver)
            estados.append("OK")
        else:
            msg_ver = (
                f"ERROR verificando: {res_ver.get('error', 'desconocido')}"
            )
            print(f"     {msg_ver}")
            detalles_total.append(msg_ver)
            estados.append("ERROR")
    except Exception as e:
        msg_ver = f"EXCEPCION verificando: {e}"
        print(f"     {msg_ver}")
        traceback.print_exc()
        detalles_total.append(msg_ver)
        estados.append("ERROR")

    # ── 3) Guardar campeon de la semana ───────────────────────────────────
    print("  -> Paso 3/3: guardar campeon de la semana")
    try:
        campeon = obtener_campeon_semana()
        if campeon:
            res_camp = guardar_campeon_semana(campeon)
            if res_camp.get("ok"):
                msg_camp = (f"Campeon guardado: {res_camp.get('campeon')} "
                            f"(fecha {res_camp.get('fecha')})")
                print(f"     {msg_camp}")
                detalles_total.append(msg_camp)
                estados.append("OK")
            else:
                msg_camp = f"ERROR guardando campeon: {res_camp.get('error')}"
                print(f"     {msg_camp}")
                detalles_total.append(msg_camp)
                estados.append("ERROR")
        else:
            msg_camp = "Sin campeon (la final no ha terminado)"
            print(f"     {msg_camp}")
            detalles_total.append(msg_camp)
    except Exception as e:
        msg_camp = f"EXCEPCION guardando campeon: {e}"
        print(f"     {msg_camp}")
        traceback.print_exc()
        detalles_total.append(msg_camp)
        estados.append("ERROR")

    # ── 4) Archivar predicciones caducadas (semanas cerradas sin verificar)
    print("  -> Paso 4/4: archivar predicciones caducadas")
    try:
        res_arch = archivar_caducadas()
        if res_arch.get("ok"):
            msg_arch = (f"Caducadas archivadas: {res_arch.get('movidas', 0)} "
                        f"({res_arch.get('partidos', 0)} partidos)")
        else:
            msg_arch = f"ERROR archivando caducadas: {res_arch.get('error')}"
            estados.append("ERROR")
        print(f"     {msg_arch}")
        detalles_total.append(msg_arch)
    except Exception as e:
        msg_arch = f"EXCEPCION archivando caducadas: {e}"
        print(f"     {msg_arch}")
        traceback.print_exc()
        detalles_total.append(msg_arch)
        estados.append("ERROR")

    # ── Log final ─────────────────────────────────────────────────────────
    if "ERROR" not in estados:
        estado_final = "OK"
    elif "OK" in estados:
        estado_final = "PARCIAL"
    else:
        estado_final = "ERROR"

    detalles_log = " | ".join(detalles_total)
    try:
        escribir_log_auto(
            jornada="Cierre Semanal", partidos_registrados=[],
            partidos_saltados=[], estado=estado_final,
            detalles=detalles_log,
        )
    except Exception as e:
        print(f"  -> No se pudo escribir en el log: {e}")

    print(f"  -> {estado_final}: {detalles_log}")

    # Exit code 0 si todo OK o parcial, 1 solo si todo fallo
    sys.exit(0 if estado_final != "ERROR" else 1)


if __name__ == "__main__":
    main()
