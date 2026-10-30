"""
vigia/cli.py - Linea de comandos:

    python -m vigia                  trabaja durante la ventana de hoy (L-X
                                     10:00-16:00, J-V 13:30-03:00, S
                                     20:10-03:00) y sale al terminar
    python -m vigia --hasta 23:00    otra hora de fin
    python -m vigia --simular        sin notificaciones ni escrituras
    python -m vigia --ver            partidos de hoy, cuando se avisara de
                                     cada uno y sus cuotas minimas, y sale
    python -m vigia --liquidar       solo apunta resultados pendientes
    python -m vigia --una-vez        una sola pasada (para GitHub Actions):
                                     dentro de la ventana avisa y apunta
                                     resultados; fuera, solo resultados
    python -m vigia --probar-aviso   manda un aviso de prueba al movil
    python -m vigia --max-minutos 345
                                     como el primero, pero sale como mucho a
                                     los 345 min (GitHub Actions corta a las 6 h)

Con ODDSPAPI_KEY (en .env o en el entorno) avisa con las cuotas reales de
Winamax por la API de OddsPapi (ver vigia/nucleo.py); sin ella, con las
cuotas minimas.
"""

import argparse
import logging
import sys
import time
from datetime import timedelta
from logging.handlers import RotatingFileHandler

from vigia.ajustes import RAIZ, cargar_ajustes

log = logging.getLogger("vigia")


def configurar_logging(verbose=False):
    carpeta = RAIZ / "logs"
    carpeta.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fichero = RotatingFileHandler(carpeta / "vigia.log", maxBytes=2_000_000,
                                  backupCount=5, encoding="utf-8")
    fichero.setFormatter(fmt)
    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(fmt)
    raiz = logging.getLogger()
    raiz.setLevel(logging.DEBUG if verbose else logging.INFO)
    raiz.handlers[:] = [fichero, consola]
    for ruidoso in ("urllib3", "google", "gspread"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # emojis en la consola de Windows
    except Exception:
        pass


def _argumentos(argv):
    ap = argparse.ArgumentParser(prog="python -m vigia",
                                 description="Vigia de cuotas minimas de Modus.")
    ap.add_argument("--hasta", default=None,
                    help="hora de fin HH:MM (Madrid). Por defecto, el final de "
                         "la ventana de hoy")
    ap.add_argument("--intervalo", type=int, default=60,
                    help="segundos entre lecturas del estado de los partidos "
                         "(minimo 30; recomendado 60-90)")
    ap.add_argument("--simular", action="store_true",
                    help="sin notificaciones ni escrituras en la hoja")
    ap.add_argument("--ver", action="store_true",
                    help="muestra los partidos de hoy, cuando se avisara de cada "
                         "uno y sus cuotas minimas, y sale")
    ap.add_argument("--una-vez", action="store_true",
                    help="una sola pasada y sale (la lanza GitHub Actions cada "
                         "pocos minutos): avisos dentro de la ventana y "
                         "resultados pendientes siempre")
    ap.add_argument("--max-minutos", type=int, default=None,
                    help="sale como mucho a los N minutos de arrancar (GitHub "
                         "Actions corta los trabajos a las 6 h)")
    ap.add_argument("--liquidar", action="store_true",
                    help="solo apunta los resultados pendientes y sale")
    ap.add_argument("--notificador", default=None,
                    help="ntfy | telegram | consola (por defecto, el de .env)")
    ap.add_argument("--probar-aviso", action="store_true",
                    help="envia un aviso de prueba al movil y sale")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def _hoja(aj, simular):
    import json
    import os
    from vigia.hoja import HojaGoogle, HojaMemoria, HojaSoloLectura
    cred = aj.credenciales_google
    if not cred and os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        # En GitHub Actions: el JSON de la cuenta de servicio en la variable
        # de entorno (como auto_registrar.py), sin escribirlo en disco
        cred = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    if not cred:
        if simular:
            log.warning("Sin GOOGLE_CREDENCIALES: hoja en memoria")
            return HojaMemoria()
        raise SystemExit("Falta GOOGLE_CREDENCIALES en .env")
    hoja = HojaGoogle(cred, aj.sheet_id, aj.sheet_id_datos)
    return HojaSoloLectura(hoja) if simular else hoja


def _api(aj):
    """Cliente de OddsPapi si hay ODDSPAPI_KEY, o None."""
    if not aj.oddspapi_key:
        return None
    from vigia.oddspapi import Cliente
    log.info("Cuotas de %s por OddsPapi", aj.oddspapi_casa)
    return Cliente(aj.oddspapi_key, aj.oddspapi_casa)


def _liquidar(aj, args):
    """Apunta los resultados pendientes (alertas y cuotas de Winamax)."""
    from vigia import notificador as notif_mod
    from vigia.nucleo import DatosSheet, Vigia
    hoja = _hoja(aj, args.simular)
    v = Vigia(hoja, notif_mod.Consola(),
              DatosSheet(lector=getattr(hoja, "leer_jornada", None),
                         historico=getattr(hoja, "historico", None)), aj)
    n = v.liquidar()
    v.hoja.volcar_log()
    return n


def _ver(aj):
    """Estado de los partidos de hoy y cuando se avisara de cada uno, sin
    avisar ni escribir."""
    from vigia import cuotas, reglas
    from vigia.horario import dia_jornada, inicio_jornada, toca_avisar
    from vigia.nombres import emparejar
    from vigia.nucleo import DatosSheet, ahora_madrid
    from modelo.motor import calcular_partido

    ahora = ahora_madrid()
    try:
        hoja = _hoja(aj, simular=True)
        lector, historico = hoja.leer_jornada, hoja.historico
    except Exception as e:
        print(f"(sin acceso a la API de Google: {e}; uso el CSV publicado)")
        lector = historico = None
    datos = DatosSheet(lector=lector, historico=historico)
    datos.refrescar(ahora, forzar=True)
    db = {v["nombre_original"]: v for v in datos.jugadores.values()}
    print(f"Datos: Forma reciente (jornada con datos: {datos.jornada_hoy or 'ninguna'}, "
          f"{len(db)} jugadores) · estado de los partidos: {datos.fuente}")
    con_hist = sum(1 for v in db.values() if v.get("peso_historico"))
    if con_hist:
        print(f"Histórico: {con_hist} jugadores con semanas anteriores "
              f"({sum(1 for v in db.values() if v.get('solo_historico'))} solo con ellas)")
    if not datos.calendario:
        print("Hoy no hay jornada de Modus.")
    for jornada, lista in datos.calendario.items():
        inicio = inicio_jornada(jornada, dia_jornada(ahora))
        print(f"\n## {jornada} (empieza a las {inicio:%H:%M})")
        for idx, p in enumerate(lista):
            avisar, hora = toca_avisar(lista, idx, inicio, ahora, aj.aviso_min_antes)
            if p["estado"] != "pendiente":
                cuando = p["estado"].replace("_", " ")
            elif avisar:
                cuando = "AVISO YA"
            elif hora:
                cuando = f"aviso {aj.aviso_min_antes} min antes de las {hora:%H:%M}"
            else:
                cuando = "aviso al terminar el anterior"
            linea = f"{p['orden'] + 1:>2}. [{cuando}] {p['j1']} vs {p['j2']}"
            n1, n2 = emparejar(p["j1"], list(db)), emparejar(p["j2"], list(db))
            if p["estado"] == "pendiente" and n1 and n2 and n1 != n2:
                d1, d2 = db[n1], db[n2]
                req = reglas.requisito_volatilidad(d1.get("volatilidad"), d2.get("volatilidad"))
                if req["ok"]:
                    calc = calcular_partido(d1, d2, True)
                    filas = cuotas.tabla(calc, n1, n2, req["edge_min"], req["rebaja"])
                    linea += ("\n      " + " · ".join(cuotas.resumen_aviso(filas, n1, n2)))
                    if req["rebaja"]:
                        linea += f"  [vol {req['vol']:.1f}: edge >= {req['edge_min']*100:.0f} %]"
                else:
                    linea += f"  [descartado: {req['motivo']}]"
            elif p["estado"] == "pendiente":
                linea += "  [no esta en los datos]"
            print(linea)
    return 0


def main(argv=None):
    args = _argumentos(argv)
    configurar_logging(args.verbose)
    aj = cargar_ajustes()

    from vigia import notificador as notif_mod
    from vigia.horario import proxima_ventana, ventana
    from vigia.nucleo import DatosSheet, Vigia, ahora_madrid

    if args.probar_aviso:
        n = notif_mod.crear(args.notificador or aj.notificador, aj)
        ok = n.enviar("🎯 Prueba del vigía de Modus: los avisos llegan bien",
                      enlace=aj.app_url)
        print("Aviso enviado" if ok else "No se pudo enviar el aviso")
        return 0 if ok else 1

    if args.ver:
        return _ver(aj)

    if args.liquidar:
        print(f"Resultados apuntados: {_liquidar(aj, args)}")
        return 0

    ahora = ahora_madrid()
    v_actual = ventana(ahora)
    if args.una_vez:
        if v_actual is None:
            n = _liquidar(aj, args)
            log.info("Fuera de la ventana: %d resultados apuntados", n)
            return 0
        notif = (notif_mod.Consola() if args.simular
                 else notif_mod.crear(args.notificador or aj.notificador, aj))
        hoja = _hoja(aj, args.simular)
        vigia = Vigia(hoja, notif, DatosSheet(lector=getattr(hoja, "leer_jornada", None),
                         historico=getattr(hoja, "historico", None)), aj, api=_api(aj))
        vigia.ciclo()   # la primera vuelta tambien apunta resultados
        vigia.hoja.volcar_log()
        return 0
    if v_actual is None:
        sig = proxima_ventana(ahora)
        if sig and sig[0] - ahora <= timedelta(minutes=60):
            log.info("Esperando a la ventana de las %s", sig[0].strftime("%H:%M"))
            while ahora_madrid() < sig[0]:
                time.sleep(30)
            v_actual = sig
        elif not args.hasta:
            dias = ["lunes", "martes", "miércoles", "jueves", "viernes",
                    "sábado", "domingo"]
            print("Fuera del horario de Modus. Próxima ventana: "
                  + (f"{dias[sig[0].weekday()]} {sig[0]:%d/%m %H:%M}" if sig else "?"))
            # Al encender el PC fuera de horario: al menos, ponerse al dia
            # con los resultados de las apuestas
            try:
                print(f"Resultados apuntados: {_liquidar(aj, args)}")
            except Exception:
                log.exception("Error apuntando resultados")
            return 0
    fin = v_actual[1] if v_actual else None
    if args.hasta:
        h, m = (int(x) for x in args.hasta.split(":"))
        fin = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
        if fin <= ahora:
            fin += timedelta(days=1)
    if args.max_minutos:
        fin = min(fin, ahora + timedelta(minutes=args.max_minutos))

    notif = (notif_mod.Consola() if args.simular
             else notif_mod.crear(args.notificador or aj.notificador, aj))
    hoja = _hoja(aj, args.simular)
    # Estado de los partidos por la API de Google (al momento), no por el CSV
    vigia = Vigia(hoja, notif,
                  DatosSheet(aj.recarga_datos_seg, lector=getattr(hoja, "leer_jornada", None),
                             historico=getattr(hoja, "historico", None)),
                  aj, api=_api(aj))
    intervalo = max(30, args.intervalo)
    vigia._log("inicio", "", f"hasta {fin.strftime('%H:%M')}"
               f"{' (simulacion)' if args.simular else ''}")
    try:
        while ahora_madrid() < fin:
            try:
                vigia.ciclo()
            except Exception as e:
                log.exception("Error en el ciclo")
                vigia._log("error", "", repr(e)[:300])
            vigia.hoja.volcar_log()
            time.sleep(intervalo)
        log.info("Fin de la ventana")
    except KeyboardInterrupt:
        log.info("Parado a mano")
    finally:
        try:
            vigia.datos.refrescar(ahora_madrid(), forzar=True)
            vigia.liquidar()
        except Exception:
            log.exception("Error liquidando al salir")
        vigia._log("fin", "", ahora_madrid().strftime("%H:%M")
                   + (f" · {vigia.api.peticiones} peticiones a OddsPapi" if vigia.api else ""))
        vigia.hoja.volcar_log()
    return 0
