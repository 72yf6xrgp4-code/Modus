"""
vigia/cli.py - Linea de comandos:

    python -m vigia                      vigilar hoy (12:00 hasta que no
                                         queden partidos de Modus)
    python -m vigia --desde 13:30 --hasta 23:00 --intervalo 60
    python -m vigia --simular            sin notificaciones ni escrituras
    python -m vigia --dump               lista los partidos de dardos de
                                         Winamax con su torneo
    python -m vigia --dump 123456        todos los mercados de un partido
                                         con la probabilidad asignada
    python -m vigia --liquidar           solo apunta resultados pendientes
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
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


def _hora(txt):
    h, m = txt.split(":")
    return int(h), int(m)


def _argumentos(argv):
    ap = argparse.ArgumentParser(prog="python -m vigia",
                                 description="Vigia de value bets de Modus (Winamax).")
    ap.add_argument("--desde", default="12:00", help="hora de inicio (Madrid)")
    ap.add_argument("--hasta", default=None,
                    help="hora de fin (Madrid). Por defecto, hasta que no "
                         "queden partidos de Modus")
    ap.add_argument("--intervalo", type=int, default=60,
                    help="segundos entre consultas a Winamax (minimo 30)")
    ap.add_argument("--simular", action="store_true",
                    help="sin notificaciones ni escrituras en la hoja")
    ap.add_argument("--dump", nargs="?", const="", default=None, metavar="MATCH_ID",
                    help="sin id: lista los partidos de dardos; con id: sus mercados")
    ap.add_argument("--guardar-fixture", action="store_true",
                    help="con --dump ID: guarda el HTML en tests/fixtures")
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


def main(argv=None):
    args = _argumentos(argv)
    configurar_logging(args.verbose)
    aj = cargar_ajustes()

    from vigia import notificador as notif_mod
    from vigia.nucleo import DatosSheet, Vigia, ahora_madrid
    from vigia.winamax import Bloqueado, ClienteWinamax

    if args.probar_aviso:
        n = notif_mod.crear(args.notificador or aj.notificador, aj)
        ok = n.enviar("🎯 Prueba del vigía de Modus: los avisos llegan bien")
        print("Aviso enviado" if ok else "No se pudo enviar el aviso")
        return 0 if ok else 1

    if args.dump is not None:
        from vigia.dump import dump
        return dump(args.dump, aj, args.guardar_fixture)

    if args.liquidar:
        v = Vigia(None, _hoja(aj, args.simular), notif_mod.Consola(),
                  DatosSheet(), aj)
        n = v.liquidar()
        v.hoja.volcar_log()
        print(f"Resultados apuntados: {n}")
        return 0

    notif = (notif_mod.Consola() if args.simular
             else notif_mod.crear(args.notificador or aj.notificador, aj))
    datos = DatosSheet(aj.recarga_datos_seg)
    vigia = Vigia(ClienteWinamax(), _hoja(aj, args.simular), notif, datos, aj)
    intervalo = max(30, args.intervalo)

    ahora = ahora_madrid()
    hd, md_ = _hora(args.desde)
    inicio = ahora.replace(hour=hd, minute=md_, second=0, microsecond=0)
    fin = None
    if args.hasta:
        hh, mh = _hora(args.hasta)
        fin = ahora.replace(hour=hh, minute=mh, second=0, microsecond=0)
        if fin <= inicio:
            fin += timedelta(days=1)    # p. ej. --hasta 02:00
    # Nunca mas alla de las 03:00 (fin de las jornadas nocturnas)
    limite = ahora.replace(hour=3, minute=0, second=0, microsecond=0)
    if ahora.hour >= 3:
        limite += timedelta(days=1)

    if ahora < inicio:
        log.info("Esperando hasta las %s", args.desde)
        while ahora_madrid() < inicio:
            time.sleep(30)

    vigia._log("inicio", "", f"desde {args.desde} hasta {args.hasta or 'fin de partidos'}"
               f"{' (simulacion)' if args.simular else ''}")
    vacios = 0
    try:
        while True:
            ahora = ahora_madrid()
            if (fin and ahora >= fin) or ahora >= limite:
                log.info("Fin de horario")
                break
            try:
                n_modus = vigia.ciclo()
            except Bloqueado as e:
                log.error("Winamax ha bloqueado las peticiones (%s). Paro.", e)
                vigia._log("error", "", f"Bloqueado por Winamax: {e}")
                notif.enviar(f"⛔ Vigía parado: Winamax responde {e}", urgente=True)
                break
            except Exception as e:
                log.exception("Error en el ciclo")
                vigia._log("error", "", repr(e)[:300])
                n_modus = -1
            vigia.hoja.volcar_log()

            # Sin --hasta: parar cuando no queden partidos de Modus (ni en
            # Winamax ni en el calendario) durante 30 minutos seguidos.
            if fin is None and n_modus == 0 and not vigia.quedan_partidos_hoy():
                vacios += 1
                if vacios * intervalo >= 30 * 60:
                    log.info("No quedan partidos de Modus hoy")
                    break
            else:
                vacios = 0
            time.sleep(intervalo)
    except KeyboardInterrupt:
        log.info("Parado a mano")
    finally:
        try:
            vigia.datos.refrescar(ahora_madrid(), forzar=True)
            vigia.liquidar()
        except Exception:
            log.exception("Error liquidando al salir")
        vigia._log("fin", "", datetime.now().strftime("%H:%M"))
        vigia.hoja.volcar_log()
    return 0
