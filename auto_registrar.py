"""auto_registrar.py — Script de auto-registro de predicciones.

Disenado para ejecutarse desde GitHub Actions cada 15 minutos durante
horario de jornada. Detecta los proximos partidos NO empezados y los
registra en la pestana 'Predicciones', con datos lo mas frescos posibles.

REGLAS DE FUNCIONAMIENTO:
  1. Solo registra mar/mie/vie/sab (y dom de madrugada, cierre de la Final).
     Lunes y jueves NO: son inicio de grupo, datos poco fiables.
  2. Solo si hay una jornada activa por hora (el cron de GitHub ya solo
     corre en esas franjas).
  3. Partido terminado: alguien llega a 4 legs.
  4. Partido en curso: hay algun dato pero nadie llega a 4 -> NO se registra.
  5. Registra los partidos "no empezados" cuyos dos jugadores ya han
     terminado todos sus partidos anteriores de la jornada.
  6. Sobrescribe los registros si ya existian, sin tocar resultado/acierto.
  7. En cada pasada verifica tambien las predicciones pendientes.
  8. Apunta en la pestana 'Log Auto Registro' lo que hizo cada vez.

USO:
  python auto_registrar.py

VARIABLES DE ENTORNO REQUERIDAS:
  GOOGLE_SERVICE_ACCOUNT_JSON  - JSON completo de la cuenta de servicio
                                 (el mismo que usa la app Streamlit).

EXIT CODES:
  0 - OK (registro o nada que hacer).
  1 - Error (configuracion, conexion, etc).
"""

from __future__ import annotations

import os
import sys
import json
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACION
# ─────────────────────────────────────────────────────────────────────────────

# Dias que SI registramos (weekday: lun=0, mar=1, mie=2, jue=3, vie=4, sab=5)
DIAS_REGISTRABLES = {1, 2, 4, 5, 6}  # mar, mie, vie, sab, dom (dom solo 00-03 Final)

# Fila de inicio de partidos en las pestanas de jornada (1-indexed)
FILA_INICIO_PARTIDOS = 7

# Maximo numero de partidos al dia (15 partidos = 30 filas)
NUM_PARTIDOS_POR_JORNADA = 15


# ─────────────────────────────────────────────────────────────────────────────
# INICIALIZACION
# ─────────────────────────────────────────────────────────────────────────────

def configurar_credenciales():
    """Lee GOOGLE_SERVICE_ACCOUNT_JSON del entorno y lo deja accesible
    para que el resto del codigo (data_loading, predicciones) lo encuentre.

    Lo guarda en una variable global accesible desde st.secrets-like.
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

    # Inyectar las credenciales en un st.secrets-like que data_loading
    # espera. Stub minimo de streamlit suficiente para que importe.
    import types
    st_stub = types.ModuleType("streamlit")
    st_stub.secrets = {"gcp_service_account": creds_dict}

    # Cache decoradores sin efecto
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
            # Auto-crear claves comunes que la app espera que existan
            if k not in self:
                if k == "last_update":
                    self[k] = {}
                else:
                    raise AttributeError(k)
            return self[k]
        def __setattr__(self, k, v): self[k] = v
        def get(self, k, d=None): return dict.get(self, k, d)

    st_stub.session_state = _SS()
    # Pre-inicializar claves que la app usa con frecuencia
    st_stub.session_state["last_update"] = {}

    # Funciones de UI que data_loading podria invocar — todas no-op
    def _noop(*a, **k):
        return None
    for fn in ("warning", "error", "info", "success", "write", "markdown",
                "caption", "title", "subheader", "spinner"):
        setattr(st_stub, fn, _noop)

    sys.modules["streamlit"] = st_stub


# ─────────────────────────────────────────────────────────────────────────────
# DETECCION DE PARTIDOS
# ─────────────────────────────────────────────────────────────────────────────

def _celda_tiene_dato(valor):
    """True si la celda tiene algun valor (no es ni None ni vacio)."""
    if valor is None:
        return False
    s = str(valor).strip()
    return s != "" and s != "0,00%" and s != "0%"


def _legs_de_celda(valor):
    """Convierte el contenido de una celda de legs a int. 0 si vacia."""
    if valor is None:
        return 0
    s = str(valor).strip().replace(",", ".")
    if not s:
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0


def clasificar_partidos(filas_partidos):
    """Recibe lista de filas crudas (cada fila = lista de celdas A..E) y
    devuelve, por cada partido (de 2 filas consecutivas), su estado.

    Devuelve lista de dicts:
      [{idx: 0, j1, j2, estado: 'no_empezado'|'en_curso'|'terminado'},
       {idx: 1, j1, j2, estado: ...},
       ...]
    """
    partidos = []
    for i in range(0, len(filas_partidos), 2):
        if i + 1 >= len(filas_partidos):
            break  # fila impar suelta, ignorar
        fila_j1 = filas_partidos[i]
        fila_j2 = filas_partidos[i + 1]

        j1 = (fila_j1[0] if len(fila_j1) > 0 else "").strip()
        j2 = (fila_j2[0] if len(fila_j2) > 0 else "").strip()

        if not j1 or not j2:
            # Fila sin nombre: hueco (los nombres se cargan progresivamente).
            # NO cortamos: saltamos este par y seguimos, por si mas abajo
            # hay partidos ya cargados.
            continue

        # Celdas de stats: columnas B-E (indices 1-4)
        celdas_j1 = fila_j1[1:5] if len(fila_j1) >= 5 else fila_j1[1:]
        celdas_j2 = fila_j2[1:5] if len(fila_j2) >= 5 else fila_j2[1:]

        legs_j1 = _legs_de_celda(fila_j1[1] if len(fila_j1) > 1 else "")
        legs_j2 = _legs_de_celda(fila_j2[1] if len(fila_j2) > 1 else "")

        terminado = (legs_j1 >= 4 or legs_j2 >= 4)
        algun_dato = (any(_celda_tiene_dato(c) for c in celdas_j1) or
                       any(_celda_tiene_dato(c) for c in celdas_j2))

        if terminado:
            estado = "terminado"
        elif algun_dato:
            estado = "en_curso"
        else:
            estado = "no_empezado"

        partidos.append({
            "idx": i // 2,
            "j1": j1,
            "j2": j2,
            "estado": estado,
            "legs_j1": legs_j1,
            "legs_j2": legs_j2,
        })
    return partidos


def seleccionar_partidos_a_registrar(partidos):
    """Registra los partidos no empezados cuyos jugadores YA HAN TERMINADO
    todos sus partidos previos en la jornada.

    Logica: la prediccion debe hacerse con la 'Forma reciente' mas fresca
    posible. Si el jugador tiene un partido anterior sin terminar (en curso
    o aun no jugado), registrar su siguiente partido ahora usaria datos
    incompletos -> se espera a la siguiente ejecucion del cron.

    Los partidos previos de OTROS jugadores no bloquean. Los huecos (filas
    sin nombre) tampoco. El anti-duplicados por ID permite que cada pasada
    del cron registre los que se hayan desbloqueado sin repetir.

    Devuelve (lista_a_registrar, lista_descartados_con_motivo).
    """
    a_registrar = []
    descartados = []

    for p in partidos:
        if p["estado"] != "no_empezado":
            continue

        j1_l = p["j1"].lower()
        j2_l = p["j2"].lower()

        # Buscar si algun partido ANTERIOR de j1 o j2 no esta terminado
        bloqueante = None
        for prev in partidos:
            if prev["idx"] >= p["idx"]:
                break  # la lista va en orden de juego; solo miramos previos
            if prev["estado"] == "terminado":
                continue
            jugadores_prev = {prev["j1"].lower(), prev["j2"].lower()}
            if j1_l in jugadores_prev or j2_l in jugadores_prev:
                bloqueante = (f"{prev['j1']} vs {prev['j2']} "
                              f"[{prev['estado']}]")
                break

        if bloqueante:
            descartados.append(
                f"{p['j1']} vs {p['j2']} (espera a: {bloqueante})"
            )
        else:
            a_registrar.append(p)

    return a_registrar, descartados


def verificar_pendientes():
    """Verifica las predicciones pendientes con los resultados ya jugados.

    Se llama en TODAS las pasadas del cron (tambien cuando no hay nada que
    registrar o la jornada ya ha terminado). Antes solo se verificaba si se
    registraba algun partido, asi que los ultimos partidos de cada jornada
    quedaban pendientes hasta el cierre del domingo.
    Devuelve un texto corto para el log.
    """
    print("  -> Verificando resultados pendientes...")
    try:
        from predicciones import verificar_resultados
        res_ver = verificar_resultados()
        if res_ver.get("ok"):
            txt = (f"Verificacion: verificadas={res_ver.get('verificadas', 0)} "
                   f"aciertos={res_ver.get('aciertos', 0)} "
                   f"fallos={res_ver.get('fallos', 0)} "
                   f"pendientes={len(res_ver.get('pendientes_diag', {}))}")
        else:
            txt = f"Verificacion ERROR: {res_ver.get('error', 'desconocido')}"
    except Exception as e:
        txt = f"Verificacion EXCEPCION: {e}"
    print(f"     {txt}")
    return txt


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    configurar_credenciales()

    # IMPORTANTE: imports DESPUES de configurar_credenciales para que
    # streamlit-stub y st.secrets esten ya listos antes de cargar data_loading.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # Ajustar Madrid time
    ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    wd = ahora.weekday()
    print(f"[auto-registrar] {ahora.isoformat()} (wd={wd})")

    # ── Filtro de dias ────────────────────────────────────────────────────
    if wd not in DIAS_REGISTRABLES:
        print(f"  -> hoy no toca registrar (dia {wd})")
        sys.exit(0)

    # ── Importar modulos de la app ────────────────────────────────────────
    try:
        from data_loading import cargar_forma_reciente
        from predicciones import (
            registrar_predicciones, escribir_log_auto,
        )
    except Exception as e:
        print(f"ERROR importando modulos: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ── Detectar jornada activa por HORA (no por datos) ──────────────────
    h = ahora.hour
    minuto = ahora.minute
    mnow = h * 60 + minuto
    jornada = None

    if mnow <= 3 * 60:
        # Madrugada: prolongacion nocturna del dia anterior.
        #   Vie 00-03 -> B Jueves  (jueves NO registrable, se filtra abajo)
        #   Sab 00-03 -> B Viernes (viernes SI registrable -> OK)
        #   Dom 00-03 -> Final Sab (sabado SI registrable -> OK)
        if wd == 4:   jornada = "Grupo B Jueves"
        elif wd == 5: jornada = "Grupo B Viernes"
        elif wd == 6: jornada = "Final Sábado"
    else:
        if wd == 1 and 10*60+30 <= mnow <= 16*60:
            jornada = "Grupo A Martes"
        elif wd == 2 and 10*60+30 <= mnow <= 16*60:
            jornada = "Grupo A Miércoles"
        elif wd == 4:
            if 14*60 <= mnow <= 19*60:  jornada = "Grupo C Viernes"
            elif 21*60 <= mnow:          jornada = "Grupo B Viernes"
        elif wd == 5 and mnow >= 20*60+40:
            jornada = "Final Sábado"

    print(f"  -> hora={h:02d}:{minuto:02d} mnow={mnow} jornada_por_hora={jornada}")

    # Excluir jornadas cuyo dia padre no es registrable.
    # "Grupo B Jueves" ocurre en Vie 00-03: jueves no esta en DIAS_REGISTRABLES.
    JORNADAS_EXCLUIDAS = {"Grupo B Jueves"}
    if jornada in JORNADAS_EXCLUIDAS:
        msg = f"jornada {jornada} excluida (dia padre no registrable)"
        print(f"  -> {msg}")
        escribir_log_auto(
            jornada=jornada, partidos_registrados=[], partidos_saltados=[],
            estado="NADA", detalles=msg + " | " + verificar_pendientes(),
        )
        sys.exit(0)

    if not jornada:
        print("  -> no hay jornada activa por hora")
        escribir_log_auto(
            jornada="", partidos_registrados=[], partidos_saltados=[],
            estado="NADA",
            detalles=(f"sin jornada activa (h={h:02d}:{minuto:02d}) | "
                      + verificar_pendientes()),
        )
        sys.exit(0)
    print(f"  -> jornada activa: {jornada}")

    # ── Leer las filas de partidos de la pestana via CSV publico ────────
    try:
        from config import URLS
        import pandas as pd
        import io
        import urllib.request
    except Exception as e:
        print(f"ERROR importando dependencias adicionales: {e}")
        sys.exit(1)

    url_csv = URLS.get(jornada)
    if not url_csv:
        msg = f"No hay URL CSV para jornada '{jornada}'"
        print(f"  -> {msg}")
        escribir_log_auto(jornada=jornada, partidos_registrados=[],
                           partidos_saltados=[], estado="ERROR",
                           detalles=msg)
        sys.exit(1)

    try:
        with urllib.request.urlopen(url_csv, timeout=20) as resp:
            csv_text = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        msg = f"Error descargando CSV: {e}"
        print(f"  -> {msg}")
        escribir_log_auto(jornada=jornada, partidos_registrados=[],
                           partidos_saltados=[], estado="ERROR",
                           detalles=msg)
        sys.exit(1)

    # Parsear el CSV en lista de listas (lineas crudas)
    import csv as csv_mod
    lineas = list(csv_mod.reader(io.StringIO(csv_text)))
    # Las filas de partidos: desde FILA_INICIO_PARTIDOS (1-indexed) hasta
    # FILA_INICIO_PARTIDOS + 30 (15 partidos = 30 filas). Como Python es
    # 0-indexed, restamos 1.
    idx_inicio = FILA_INICIO_PARTIDOS - 1
    idx_fin = idx_inicio + (NUM_PARTIDOS_POR_JORNADA * 2)
    filas_partidos = lineas[idx_inicio:idx_fin]

    if not filas_partidos:
        msg = "La pestana no tiene filas de partidos"
        print(f"  -> {msg}")
        escribir_log_auto(jornada=jornada, partidos_registrados=[],
                           partidos_saltados=[], estado="NADA",
                           detalles=msg + " | " + verificar_pendientes())
        sys.exit(0)

    # ── Clasificar partidos por estado ────────────────────────────────────
    partidos = clasificar_partidos(filas_partidos)
    print(f"  -> {len(partidos)} partidos detectados:")
    for p in partidos:
        print(f"     [{p['idx']:>2}] {p['j1']} vs {p['j2']} "
              f"({p['legs_j1']}-{p['legs_j2']}) [{p['estado']}]")

    # ── Seleccionar cuales registrar ─────────────────────────────────────
    a_registrar, descartados = seleccionar_partidos_a_registrar(partidos)

    if not a_registrar:
        print("  -> no hay partidos pendientes que registrar")
        escribir_log_auto(jornada=jornada, partidos_registrados=[],
                           partidos_saltados=descartados, estado="NADA",
                           detalles="sin partidos no-empezados pendientes | "
                                    + verificar_pendientes())
        sys.exit(0)

    # ── Cargar Forma reciente ─────────────────────────────────────────────
    try:
        forma_dict = cargar_forma_reciente()
    except Exception as e:
        msg = f"Error cargando Forma reciente: {e}"
        print(f"  -> {msg}")
        traceback.print_exc()
        escribir_log_auto(jornada=jornada, partidos_registrados=[],
                           partidos_saltados=[], estado="ERROR",
                           detalles=msg)
        sys.exit(1)

    if not forma_dict:
        # Diagnostico: ¿que falla? Intentamos cargar Resumen Semanal
        # directamente y mostramos el error real.
        print("  -> Forma reciente vacia, diagnosticando...")
        try:
            from data_loading import cargar_jugadores_desde
            resumen_test = cargar_jugadores_desde("Resumen Semanal")
            print(f"     cargar_jugadores_desde('Resumen Semanal') "
                  f"devolvio: {len(resumen_test)} jugadores")
            if not resumen_test:
                # Intentar leer el CSV crudo para ver si llega
                import pandas as pd
                try:
                    df_test = pd.read_csv(URLS["Resumen Semanal"], header=None)
                    print(f"     CSV crudo: {df_test.shape[0]} filas, "
                          f"{df_test.shape[1]} cols")
                except Exception as e:
                    print(f"     Error leyendo CSV crudo: {e}")
                    traceback.print_exc()
        except Exception as e:
            print(f"     Error en diagnostico: {e}")
            traceback.print_exc()

        msg = "Forma reciente vacia"
        print(f"  -> {msg}")
        escribir_log_auto(jornada=jornada, partidos_registrados=[],
                           partidos_saltados=[], estado="ERROR",
                           detalles=msg)
        sys.exit(1)

    # ── Registrar cada partido seleccionado ──────────────────────────────
    registrados_ok = []
    errores = []
    # Dia de jornada (madrugada = dia anterior), igual que el boton Registrar
    from helpers import fecha_jornada_madrid
    semana = f"Semana {fecha_jornada_madrid(ahora)}"

    def _buscar_jugador(nombre):
        nl = nombre.strip().lower()
        if nl in forma_dict:
            return forma_dict[nl]
        # match parcial por apellido/sufijo
        for k, v in forma_dict.items():
            if nl in k or k in nl:
                return v
        return None

    for p in a_registrar:
        j1_data = _buscar_jugador(p["j1"])
        j2_data = _buscar_jugador(p["j2"])
        if not j1_data or not j2_data:
            falta = []
            if not j1_data: falta.append(p["j1"])
            if not j2_data: falta.append(p["j2"])
            errores.append(
                f"{p['j1']} vs {p['j2']} (sin stats: {', '.join(falta)})"
            )
            continue
        try:
            res = registrar_predicciones(
                "", [(j1_data, j2_data)], semana, jornada
            )
            if res.get("ok"):
                registrados_ok.append(f"{p['j1']} vs {p['j2']}")
            else:
                errores.append(
                    f"{p['j1']} vs {p['j2']} "
                    f"(error: {res.get('error', 'desconocido')})"
                )
        except Exception as e:
            errores.append(f"{p['j1']} vs {p['j2']} (excepcion: {e})")
            traceback.print_exc()

    # ── Log de registro ───────────────────────────────────────────────────
    if registrados_ok and not errores:
        estado = "OK"
    elif registrados_ok and errores:
        estado = "PARCIAL"
    elif errores:
        estado = "ERROR"
    else:
        estado = "NADA"
    detalles = f"{len(registrados_ok)} registrados, {len(errores)} errores"
    if errores:
        detalles += " | Errores: " + " ; ".join(errores)

    # ── Verificar resultados pendientes ───────────────────────────────────
    # Cada vez que el cron actua durante una jornada, ademas de registrar
    # los proximos partidos tambien verifica los que ya han terminado.
    # Asi las predicciones se van resolviendo automaticamente sin esperar
    # al cierre semanal del domingo.
    detalles += " | " + verificar_pendientes()

    escribir_log_auto(jornada=jornada, partidos_registrados=registrados_ok,
                       partidos_saltados=descartados + errores,
                       estado=estado, detalles=detalles)
    print(f"  -> {estado}: {detalles}")


if __name__ == "__main__":
    main()
