"""
vigia/nucleo.py - Logica del vigia de cuotas minimas: datos del modelo,
hora estimada de cada partido, avisos y liquidacion de las apuestas.

No hace ninguna peticion a Winamax. Todo se inyecta (hoja, notificador,
fuente de datos, reloj) para poder probarlo sin red.
"""

import logging
import time
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from modelo import datos as md
from modelo.motor import calcular_partido
from modelo.volatilidad import nivel_volatilidad
from vigia import cuotas, reglas, registro
from vigia.horario import dia_jornada, fecha_jornada, inicio_jornada, toca_avisar
from vigia.nombres import emparejar, mismo_jugador

log = logging.getLogger(__name__)
MADRID = ZoneInfo("Europe/Madrid")


def ahora_madrid():
    return datetime.now(MADRID)


def apellido(n):
    return n.split()[-1] if n else n


def enlace_app(app_url, j1, j2):
    """Enlace a Value Bets con el partido elegido (J1 = primero del cartel)."""
    return (f"{app_url}/?seccion=value&j1={quote(j1, safe='')}"
            f"&j2={quote(j2, safe='')}")


# ─────────────────────────────────────────────────────────────────────────────
# DATOS DEL MODELO (misma fuente que Value Bets: "Forma reciente")
# ─────────────────────────────────────────────────────────────────────────────

class DatosSheet:
    """Jugadores ('Forma reciente', recargados cada `recarga_seg` segundos)
    y estado de los partidos del dia de jornada (en cada vuelta).

    lector: funcion jornada -> filas que lee la pestana por la API de Google
    (HojaGoogle.leer_jornada). El CSV publicado va con varios minutos de
    retraso; sin lector, o si la API falla, se usa el CSV."""

    def __init__(self, recarga_seg=300, lector=None, historico=None):
        self.recarga_seg = recarga_seg
        self.lector = lector
        # historico: funcion -> filas de la pestana 'Historico' (semanas
        # anteriores): ajusta la volatilidad y completa a los jugadores con
        # pocos datos esta semana (modelo/historico.py)
        self.historico = historico
        self.fuente = "API" if lector else "CSV"
        self._t = 0.0
        self.jugadores = {}
        self.calendario = {}   # jornada -> partidos_de_jornada
        self.jornada_hoy = None

    def lineas(self, jornada):
        if self.lector:
            try:
                filas = self.lector(jornada)
                self.fuente = "API"
                return filas
            except Exception as e:
                if self.fuente != "CSV (la API fallo)":
                    log.warning("La API de Google no lee %s (%s): uso el CSV publicado",
                                jornada, e)
                self.fuente = "CSV (la API fallo)"
        return md.descargar_lineas(jornada)

    def refrescar(self, ahora, forzar=False):
        """Estado de los partidos en cada llamada; jugadores cada
        recarga_seg. Devuelve True si se han recargado los jugadores."""
        dia = dia_jornada(ahora)
        if not forzar and time.time() - self._t < self.recarga_seg:
            self.calendario = {j: md.partidos_de_jornada(self.lineas(j))
                               for j in md.jornadas_del_dia(dia)}
            return False
        # Igual que data_loading.cargar_forma_reciente: la jornada que toca
        # por hora, solo si ya tiene datos; volatilidad ajustada y semanas
        # anteriores con poco peso.
        from modelo import historico as mh
        ref, hist = None, {}
        if self.historico:
            try:
                filas = self.historico()
                ref = mh.referencia_volatilidad([f.get("Volatilidad") for f in filas])
                hist = mh.resumen_historico(filas, antes_de=mh.sabado_de_la_semana(dia), ref=ref)
            except Exception as e:
                log.warning("No se pudo leer el Historico: %s", e)
        jornada = md.jornada_por_hora(ahora)
        hoy = mh.ajustar_jugadores(md.cargar_jugadores(jornada), ref) if jornada else {}
        self.jornada_hoy = jornada if hoy else None
        resumen = mh.ajustar_jugadores(md.cargar_jugadores("Resumen Semanal"), ref)
        if not resumen:
            jugadores = hoy
        elif not self.jornada_hoy:
            jugadores = resumen
        else:
            jugadores = md.combinar_forma_reciente(resumen, hoy)
        self.calendario = {j: md.partidos_de_jornada(self.lineas(j))
                           for j in md.jornadas_del_dia(dia)}
        if hist:
            nombres = {n for ps in self.calendario.values() for p in ps for n in (p["j1"], p["j2"])}
            jugadores = mh.combinar_con_historico(jugadores, hist, nombres_extra=sorted(nombres))
        if jugadores:
            self.jugadores = jugadores
        self._t = time.time()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# VIGIA
# ─────────────────────────────────────────────────────────────────────────────

class Vigia:
    def __init__(self, hoja, notificador, datos, ajustes, reloj=ahora_madrid):
        self.hoja = hoja
        self.notif = notificador
        self.datos = datos
        self.aj = ajustes
        self.reloj = reloj
        self._dia = None
        self._avisados = set()
        self._descartados = {}
        self._anotados = {}   # partido -> ultimo motivo de descarte en vigia_log

    @staticmethod
    def _partido(jornada, p):
        """Nombre del partido en vigia_log: 'J1 vs J2 (Grupo C Jueves, 3)'.
        Jornada y posicion lo identifican aunque la pareja se repita."""
        return f"{p['j1']} vs {p['j2']} ({jornada}, {p['orden'] + 1})"

    def _log(self, tipo, partido="", detalle=""):
        ahora = self.reloj()
        self.hoja.log({"fecha": fecha_jornada(ahora),
                       "hora": ahora.strftime("%H:%M:%S"), "tipo": tipo,
                       "partido": partido, "detalle": detalle})

    def _cargar_dia(self, fecha):
        """Al cambiar de dia (o arrancar), recupera de vigia_log los partidos
        ya avisados hoy para no repetir avisos si el vigia se reinicia."""
        self._dia = fecha
        self._descartados = {}
        del_dia = self.hoja.log_del_dia(fecha)
        self._avisados = {d.get("partido", "") for d in del_dia if d.get("tipo") == "aviso"}
        self._anotados = {d.get("partido", ""): d.get("detalle", "") for d in del_dia
                          if d.get("tipo") == "descartado"}

    def _ya_avisado(self, clave, fecha):
        """Otro vigia (el del portatil o el de GitHub) puede haber avisado de
        este partido despues de que este arrancara: se mira vigia_log justo
        antes de mandar el aviso."""
        if clave in self._avisados:
            return True
        if any(d.get("tipo") == "aviso" and d.get("partido") == clave
               for d in self.hoja.log_del_dia(fecha)):
            self._avisados.add(clave)
            return True
        return False

    def _descartar(self, clave, partido, motivo):
        self._descartados[clave] = motivo
        # Se anota una vez por motivo (aunque se reevalue o se relance el vigia)
        if self._anotados.get(clave) != motivo:
            self._anotados[clave] = motivo
            log.info("Descartado %s: %s", partido, motivo)
            self._log("descartado", partido, motivo)

    # ── un ciclo ───────────────────────────────────────────────────────
    def ciclo(self):
        """Una vuelta. Devuelve cuantos partidos de hoy quedan sin empezar."""
        ahora = self.reloj()
        fecha = fecha_jornada(ahora)
        if fecha != self._dia:
            self._cargar_dia(fecha)
        if self.datos.refrescar(ahora):
            self._descartados.clear()   # con datos nuevos se reevalua
            try:
                self.liquidar()
            except Exception:
                log.exception("Error liquidando")

        dia = dia_jornada(ahora)
        pendientes = 0
        for jornada, lista in self.datos.calendario.items():
            inicio = inicio_jornada(jornada, dia) or ahora
            for idx, p in enumerate(lista):
                if p["estado"] != "pendiente":
                    continue
                pendientes += 1
                avisar, hora = toca_avisar(lista, idx, inicio, ahora,
                                           self.aj.aviso_min_antes)
                if not avisar:
                    continue
                try:
                    self.evaluar(jornada, p, hora, fecha)
                except Exception as e:  # un partido no tumba el ciclo
                    log.exception("Error con %s vs %s", p["j1"], p["j2"])
                    self._log("error", f"{p['j1']} vs {p['j2']}", repr(e)[:300])
        self.hoja.volcar_log()
        return pendientes

    def evaluar(self, jornada, p, hora_inicio, fecha):
        """Avisa del partido (una sola vez) con sus cuotas minimas.
        hora_inicio: hora conocida del partido, o None si es "el siguiente"."""
        partido = clave = self._partido(jornada, p)
        if clave in self._avisados or clave in self._descartados:
            return
        db = {v["nombre_original"]: v for v in self.datos.jugadores.values()}
        n1, n2 = emparejar(p["j1"], list(db)), emparejar(p["j2"], list(db))
        if not n1 or not n2 or n1 == n2:
            falta = [c for c, n in ((p["j1"], n1), (p["j2"], n2)) if not n]
            return self._descartar(clave, partido,
                                   f"no esta en los datos: {', '.join(falta) or n1}")
        d1, d2 = db[n1], db[n2]   # J1 = primero del cartel
        req = reglas.requisito_volatilidad(d1.get("volatilidad"), d2.get("volatilidad"))
        if not req["ok"]:
            return self._descartar(clave, partido, req["motivo"])
        if d1.get("PR", 0) <= 0 or d2.get("PR", 0) <= 0:
            return self._descartar(clave, partido, "sin Puntuacion Global")

        if self._ya_avisado(clave, fecha):
            return
        calc = calcular_partido(d1, d2, j1_saca_primero=True)
        filas = cuotas.tabla(calc, n1, n2, req["edge_min"], req["rebaja"],
                             banca=registro.banca_actual(self.hoja.alertas()))
        ahora = self.reloj()
        hora = hora_inicio.strftime("%H:%M") if hora_inicio else "siguiente"
        v1 = nivel_volatilidad(d1.get("volatilidad")) or ""
        v2 = nivel_volatilidad(d2.get("volatilidad")) or ""
        self.hoja.anadir_cuotas([{
            "fecha": fecha, "hora": ahora.strftime("%H:%M"),
            "inicio_estimado": hora, "jornada": jornada, "orden": p["orden"] + 1,
            "j1": n1, "j2": n2, "vol_j1": v1, "vol_j2": v2,
            "mercado": f["nombre_mercado"], "seleccion": f["texto"],
            "p": round(f["p"], 4), "cuota_justa": f["justa"],
            "cuota_min_aviso": f["aviso"], "cuota_min_10": f["eur_10"],
            "cuota_min_15": f["eur_15"] or "", "cuota_min_verde": f["verde"] or "",
            "edge_exigido": round(req["edge_min"], 4),
        } for f in filas])

        partes = cuotas.resumen_aviso(filas, n1, n2)
        cuando = hora if hora_inicio else "Siguiente:"
        texto = f"🎯 {cuando} {apellido(n1)} vs {apellido(n2)} · " + " · ".join(partes)
        if req["rebaja"]:
            texto += (f" · ⚠️ vol {req['vol']:.1f}: edge ≥{req['edge_min']*100:.0f} %"
                      .replace(".", ","))
        texto = texto[:199]
        self.notif.enviar(texto, enlace=enlace_app(self.aj.app_url, n1, n2))
        self._avisados.add(clave)
        self._log("aviso", partido, texto)
        self.hoja.volcar_log()   # cuanto antes, para que el otro vigia lo vea
        log.info("AVISO %s", texto)

    # ── resultados de las apuestas apuntadas en la app ───────────────────
    def _partido_real(self, f, cache):
        """(partido terminado de la hoja, jornada, invertido) de la fila f,
        o None. invertido: J1 de la fila es J2 en la hoja."""
        try:
            dia = datetime.fromisoformat(f["fecha"])
        except (KeyError, ValueError, TypeError):
            return None
        jornadas = [f.get("jornada")] if f.get("jornada") else md.jornadas_del_dia(dia)
        for j in jornadas:
            if j not in cache:
                cache[j] = md.partidos_de_jornada(self.datos.lineas(j))
            for cp in cache[j]:
                if cp["estado"] != "terminado":
                    continue
                if mismo_jugador(cp["j1"], f["j1"]) and mismo_jugador(cp["j2"], f["j2"]):
                    return cp, j, False
                if mismo_jugador(cp["j1"], f["j2"]) and mismo_jugador(cp["j2"], f["j1"]):
                    return cp, j, True
        return None

    def _resultado_real(self, f, cache):
        """(legs1, legs2, 180s_1, 180s_2) del partido de la fila f, con J1/J2
        en el orden de la fila, si ya ha terminado; si no, None."""
        r = self._partido_real(f, cache)
        if not r:
            return None
        cp, _, inv = r
        if inv:
            return (cp["legs2"], cp["legs1"], cp["t180_2"], cp["t180_1"])
        return (cp["legs1"], cp["legs2"], cp["t180_1"], cp["t180_2"])

    def _pendientes(self, filas, hoy, campos=("n_partido",)):
        """Filas sin resultado, o a las que les falta alguno de `campos` y son
        de esta semana (la hoja de cada jornada se reescribe la siguiente)."""
        hace_6 = (hoy - timedelta(days=6)).isoformat()
        return [f for f in filas
                if f.get("resultado") not in ("ganada", "perdida")
                or (any(str(f.get(c, "")).strip() == "" for c in campos)
                    and str(f.get("fecha", "")) >= hace_6)]

    def _previos(self, f, jornada, orden, cache):
        """Partidos de cada jugador en la semana antes de este (para saber si
        el partido es fiable): {previos_j1, previos_j2}."""
        from vigia.frescura import partidos_previos
        dia = datetime.fromisoformat(f["fecha"])
        semana = {}
        for j in md.jornadas_hasta(dia):
            if j not in cache:
                cache[j] = md.partidos_de_jornada(self.datos.lineas(j))
            semana[j] = cache[j]
        return {"previos_j1": partidos_previos(semana, f["j1"], jornada, orden),
                "previos_j2": partidos_previos(semana, f["j2"], jornada, orden)}

    def liquidar(self):
        """Apunta el resultado de las apuestas (pestana alertas: resultado y
        beneficio) y de las cuotas guardadas con el boton (cuotas_winamax)
        cuyos partidos ya han terminado. De paso rellena la jornada y el
        numero de partido de las filas que no lo tienen."""
        cache = {}
        hoy = (self.reloj() or ahora_madrid()).date()
        n = 0
        filas = [f for f in self.hoja.alertas()
                 if f.get("tipo_aviso") in (registro.AVISO_APUESTA, registro.AVISO_REVISAR)]
        for f in self._pendientes(filas, hoy):
            r = self._partido_real(f, cache)
            if not r:
                continue
            cp, jornada, _ = r
            campos = {} if f.get("n_partido") else {"jornada": f.get("jornada") or jornada,
                                                     "n_partido": cp["orden"] + 1}
            ok = None
            if f.get("resultado") not in ("ganada", "perdida"):
                real = self._resultado_real(f, cache)
                ok = reglas.acierta(registro.seleccion(f), *real)
            if ok is not None:
                resultado = "ganada" if ok else "perdida"
                # Las apostadas, con lo que de verdad apostaste (importe_real)
                ben = registro.beneficio_fila(dict(f, resultado=resultado),
                                              real=f.get("estado") == registro.ESTADO_APOSTADA)
                campos.update(resultado=resultado, beneficio=round(ben, 2))
                self._log("resultado", f.get("partido", ""),
                          f"{resultado} ({cp['legs1']}-{cp['legs2']}, "
                          f"180s {cp['t180_1']}-{cp['t180_2']})")
                n += 1
            if campos:
                self.hoja.actualizar_alerta(f["_fila"], campos)

        # Cuotas de Winamax guardadas con el boton: todas en una peticion
        cambios, n_wm = [], 0
        for f in self._pendientes(self.hoja.filas_winamax(), hoy,
                                  ("n_partido", "previos_j1", "previos_j2")):
            r = self._partido_real(f, cache)
            if not r:
                continue
            cp, jornada, _ = r
            campos = {} if f.get("n_partido") else {"jornada": f.get("jornada") or jornada,
                                                     "n_partido": cp["orden"] + 1}
            if str(f.get("previos_j1", "")).strip() == "":
                campos.update(self._previos(f, f.get("jornada") or jornada, cp["orden"], cache))
            if f.get("resultado") not in ("ganada", "perdida") and f.get("seleccion_json"):
                ok = reglas.acierta(registro.seleccion(f), *self._resultado_real(f, cache))
                if ok is not None:
                    campos["resultado"] = "ganada" if ok else "perdida"
                    n_wm += 1
            if campos:
                cambios.append((f["_fila"], campos))
        if cambios:
            self.hoja.actualizar_winamax(cambios)
            if n_wm:
                self._log("resultado", "", f"{n_wm} cuotas de Winamax con resultado")
        return n + n_wm
