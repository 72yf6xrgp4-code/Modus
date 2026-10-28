"""
vigia/cli.py - Linea de comandos:

    python -m vigia                  trabaja durante la ventana de hoy (L-X
                                     10:00-16:00, J-V 13:30-03:00, S
                                     20:10-03:00) y sale al terminar
    python -m vigia --hasta 23:00    otra hora de fin
    python -m vigia --simular        sin notificaciones ni escrituras
    python -m vigia --ver            tabla de hoy (horas estimadas y cuotas
                                     minimas principales) y sale
    python -m vigia --liquidar       solo apunta resultados pendientes
    python -m vigia --probar-aviso   manda un aviso de prueba al movil
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
                    help="segundos entre vueltas (minimo 30)")
    ap.add_argument("--simular", action="store_true",
                    help="sin notificaciones ni escrituras en la hoja")
    ap.add_argument("--ver", action="store_true",
                    help="muestra los partidos de hoy con su hora estimada y "
                         "cuotas minimas, y sale")
    ap.add_argument("--liquidar", action="store_true",
                    help="solo apunta los resultados pendientes y sale")
    ap.add_argument("--notificador", default=None,
                    help="ntfy | telegram | consola (por defecto, el de .env)")
    ap.add_argument("--probar-aviso", action="store_true",
                    help="envia un aviso de prueba al movil y sale")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def _hoja(aj, simular):
    from vigia.hoja import HojaGoogle, HojaMemoria, HojaSoloLectura
    if not aj.credenciales_google:
        if simular:
            log.warning("Sin GOOGLE_CREDENCIALES: hoja en memoria")
            return HojaMemoria()
        raise SystemExit("Falta GOOGLE_CREDENCIALES en .env")
    hoja = HojaGoogle(aj.credenciales_google, aj.sheet_id)
    return HojaSoloLectura(hoja) if simular else hoja


def _ver(aj):
    """Tabla de hoy sin avisar ni escribir."""
    from vigia import cuotas, reglas
    from vigia.horario import dia_jornada, estimar_inicios, inicio_jornada
    from vigia.nombres import emparejar
    from vigia.nucleo import DatosSheet, ahora_madrid
    from modelo.motor import calcular_partido

    ahora = ahora_madrid()
    datos = DatosSheet()
    datos.refrescar(ahora, forzar=True)
    db = {v["nombre_original"]: v for v in datos.jugadores.values()}
    print(f"Datos: Forma reciente (jornada con datos: {datos.jornada_hoy or 'ninguna'}, "
          f"{len(db)} jugadores)")
    if not datos.calendario:
        print("Hoy no hay jornada de Modus.")
    for jornada, lista in datos.calendario.items():
        inicio = inicio_jornada(jornada, dia_jornada(ahora))
        est = estimar_inicios(lista, inicio, ahora, {}, aj.duracion_partido_min)
        print(f"\n## {jornada}")
        for p in lista:
            hora = est[p["orden"]].strftime("%H:%M") if p["orden"] in est else p["estado"]
            n1, n2 = emparejar(p["j1"], list(db)), emparejar(p["j2"], list(db))
            linea = f"{p['orden'] + 1:>2}. ~{hora:<9} {p['j1']} vs {p['j2']}"
            if n1 and n2 and n1 != n2:
                d1, d2 = db[n1], db[n2]
                req = reglas.requisito_volatilidad(d1.get("volatilidad"), d2.get("volatilidad"))
                if req["ok"]:
                    calc = calcular_partido(d1, d2, True)
                    filas = cuotas.tabla(calc, n1, n2, req["edge_min"], req["rebaja"])
                    linea += (f"  P(J1) {calc['p1']*100:.1f} % · "
                              + " · ".join(cuotas.resumen_aviso(filas, n1, n2)))
                    if req["rebaja"]:
                        linea += f"  [vol {req['vol']:.1f}: edge >= {req['edge_min']*100:.0f} %]"
                else:
                    linea += f"  [descartado: {req['motivo']}]"
            else:
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
        v = Vigia(_hoja(aj, args.simular), notif_mod.Consola(), DatosSheet(), aj)
        n = v.liquidar()
        v.hoja.volcar_log()
        print(f"Resultados apuntados: {n}")
        return 0

    ahora = ahora_madrid()
    v_actual = ventana(ahora)
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
            return 0
    fin = v_actual[1] if v_actual else None
    if args.hasta:
        h, m = (int(x) for x in args.hasta.split(":"))
        fin = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
        if fin <= ahora:
            fin += timedelta(days=1)

    notif = (notif_mod.Consola() if args.simular
             else notif_mod.crear(args.notificador or aj.notificador, aj))
    vigia = Vigia(_hoja(aj, args.simular), notif,
                  DatosSheet(aj.recarga_datos_seg), aj)
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
        vigia._log("fin", "", ahora_madrid().strftime("%H:%M"))
        vigia.hoja.volcar_log()
    return 0
