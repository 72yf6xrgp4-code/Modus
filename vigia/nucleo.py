"""
vigia/nucleo.py - Logica del vigia de cuotas minimas: datos del modelo,
hora estimada de cada partido, avisos y liquidacion de las apuestas.

No hace ninguna peticion a Winamax. Todo se inyecta (hoja, notificador,
fuente de datos, reloj y, si hay clave, el cliente de OddsPapi) para poder
probarlo sin red.

Con OddsPapi (ODDSPAPI_KEY) el vigia trabaja con las cuotas reales de
Winamax: un partido esta listo cuando los partidos anteriores de sus dos
jugadores estan terminados en la hoja Y sus estadisticas ya los cuentan
(vigia/frescura.py). Desde ese momento y hasta que empieza, cada vuelta
pide sus cuotas; guarda la primera lectura (cuotas_winamax, para las
estadisticas) y avisa en cuanto alguna llega a tu edge.
"""

import logging
import time
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from modelo import datos as md
from modelo.motor import calcular_partido
from modelo.volatilidad import nivel_volatilidad
from vigia import aviso, cuotas, reglas, registro
from vigia.horario import dia_jornada, fecha_jornada, inicio_jornada, toca_avisar
from vigia.nombres import emparejar, mismo_jugador

log = logging.getLogger(__name__)
MADRID = ZoneInfo("Europe/Madrid")


def ahora_madrid():
    return datetime.now(MADRID)


def apellido(n):
    return n.split()[-1] if n else n


def _vol_num(v):
    """Indice de volatilidad como numero (2 decimales) o '' sin dato."""
    return round(float(str(v).replace(",", ".")), 2) if nivel_volatilidad(v) else ""


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
        self._lineas = {}      # jornada -> filas leidas en la ultima vuelta
        self._stats = {}
        self._hist, self._hist_t = None, 0.0

    def edad(self):
        """Segundos desde la ultima recarga de los jugadores."""
        return time.time() - self._t

    def stats_jornada(self, jornada):
        """Estadisticas de los jugadores en esa jornada (n_partidos...), de
        las filas ya leidas en esta vuelta si las hay (por la API: al
        momento) o del CSV publicado."""
        if jornada not in self._stats:
            st = md.jugadores_desde_lineas(jornada, self._lineas.get(jornada))
            self._stats[jornada] = st or md.cargar_jugadores(jornada)
        return self._stats[jornada]

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
            self._lineas = {j: self.lineas(j) for j in md.jornadas_del_dia(dia)}
            self._stats = {}
            self.calendario = {j: md.partidos_de_jornada(l) for j, l in self._lineas.items()}
            return False
        # Igual que data_loading.cargar_forma_reciente: la jornada que toca
        # por hora, solo si ya tiene datos; volatilidad ajustada y semanas
        # anteriores con poco peso.
        from modelo import historico as mh
        ref, hist = None, {}
        if self.historico:
            try:
                if self._hist is None or time.time() - self._hist_t >= self.recarga_seg:
                    self._hist, self._hist_t = self.historico(), time.time()
                filas = self._hist
                ref = mh.referencia_volatilidad([f.get("Volatilidad") for f in filas])
                hist = mh.resumen_historico(filas, antes_de=mh.sabado_de_la_semana(dia), ref=ref)
            except Exception as e:
                log.warning("No se pudo leer el Historico: %s", e)
        # Filas de las jornadas de hoy (por la API: al momento). Sirven para el
        # estado de los partidos y para las estadisticas de hoy.
        self._lineas = {j: self.lineas(j) for j in md.jornadas_del_dia(dia)}
        self._stats = {}
        jornada = md.jornada_por_hora(ahora)
        hoy = mh.ajustar_jugadores(self.stats_jornada(jornada), ref) if jornada else {}
        self.jornada_hoy = jornada if hoy else None
        resumen = mh.ajustar_jugadores(md.cargar_jugadores("Resumen Semanal"), ref)
        if not resumen:
            jugadores = hoy
        elif not self.jornada_hoy:
            jugadores = resumen
        else:
            jugadores = md.combinar_forma_reciente(resumen, hoy)
        self.calendario = {j: md.partidos_de_jornada(l) for j, l in self._lineas.items()}
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
    def __init__(self, hoja, notificador, datos, ajustes, reloj=ahora_madrid, api=None):
        self.hoja = hoja
        self.api = api              # vigia.oddspapi.Cliente, o None
        self._guardados = set()     # partidos con su lectura ya guardada
        self._esperas = {}          # partido -> por que aun no esta listo
        self._cerrados = set()      # partidos que ya empezaron (OddsPapi)
        self._semana = {}           # jornadas de dias anteriores (no cambian)
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
        if self.api:
            pendientes = self._ciclo_api(ahora, fecha)
            self.hoja.volcar_log()
            return pendientes
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

    # ── con OddsPapi: cuotas reales de Winamax ───────────────────────────
    def _espera(self, clave, motivo):
        if self._esperas.get(clave) != motivo:
            log.info("Esperando %s: %s", clave, motivo)
        self._esperas[clave] = motivo

    def _ciclo_api(self, ahora, fecha):
        """Una vuelta con OddsPapi. Devuelve cuantos partidos quedan sin empezar."""
        from vigia.frescura import partido_anterior
        listos, pendientes = [], set()
        for jornada, lista in self.datos.calendario.items():
            for p in lista:
                if p["estado"] != "pendiente":
                    continue
                clave = self._partido(jornada, p)
                pendientes.add(clave)
                if (clave in self._descartados or clave in self._cerrados
                        or clave in self._avisados):
                    continue
                fr = partido_anterior(lista, p["j1"], p["j2"], self.datos.stats_jornada(jornada))
                faltan = [f"{r['jugador']}: {r['texto']}" for r in fr if not r["ok"]]
                if faltan:
                    self._espera(clave, "; ".join(faltan))
                else:
                    listos.append((jornada, p, clave))
        # Los que empezaron sin llegar a avisar: por que (para ver retrasos)
        for clave in [c for c in self._esperas if c not in pendientes]:
            motivo = self._esperas.pop(clave)
            if clave not in self._avisados:
                self._log("sin aviso", clave, f"empezó esperando: {motivo}"[:300])
        if not listos:
            return len(pendientes)
        # El modelo, con las estadisticas recien leidas (incluyen sus ultimos partidos)
        if self.datos.edad() > 50:
            self.datos.refrescar(ahora, forzar=True)
        from vigia.oddspapi import ErrorOddsPapi
        try:
            partidos = self.api.partidos(ahora)
        except ErrorOddsPapi as e:
            log.warning("OddsPapi: %s", e)
            self._descartar("oddspapi", "", f"OddsPapi: {e}")
            self._descartados.pop("oddspapi", None)   # se reintenta en la siguiente
            return len(pendientes)
        for jornada, p, clave in listos:
            try:
                self.evaluar_api(jornada, p, clave, fecha, partidos)
            except ErrorOddsPapi as e:
                self._espera(clave, f"OddsPapi: {e}")
            except Exception as e:  # un partido no tumba el ciclo
                log.exception("Error con %s", clave)
                self._log("error", clave, repr(e)[:300])
        return len(pendientes)

    def _info_partido(self, j1, j2, d1, d2):
        """{jornada, n_partido, previos_j1, previos_j2, semanas_j1, semanas_j2}."""
        from vigia.frescura import info_partido
        dia = dia_jornada(self.reloj())
        hoy = md.jornadas_del_dia(dia)
        semana = {}
        for j in md.jornadas_hasta(dia):
            if j in self.datos.calendario:
                semana[j] = self.datos.calendario[j]
            else:
                if j not in self._semana:
                    self._semana[j] = md.partidos_de_jornada(self.datos.lineas(j))
                semana[j] = self._semana[j]
        info = info_partido(semana, hoy, j1, j2)
        return dict(info, semanas_j1=int(d1.get("semanas_historico") or 0),
                    semanas_j2=int(d2.get("semanas_historico") or 0))

    def evaluar_api(self, jornada, p, clave, fecha, partidos):
        """Partido listo: pide sus cuotas de Winamax a OddsPapi, guarda la
        primera lectura y avisa (una vez) si alguna llega a tu edge."""
        from modelo.motor import probabilidad
        from vigia import oddspapi
        from vigia.boton import DatosNoValidos, decodificar, preparar
        from vigia.mercados import texto_seleccion
        partido = clave
        db = {v["nombre_original"]: v for v in self.datos.jugadores.values()}
        n1, n2 = emparejar(p["j1"], list(db)), emparejar(p["j2"], list(db))
        if not n1 or not n2 or n1 == n2:
            falta = [c for c, n in ((p["j1"], n1), (p["j2"], n2)) if not n]
            return self._descartar(clave, partido,
                                   f"no esta en los datos: {', '.join(falta) or n1}")
        d1, d2 = db[n1], db[n2]   # J1 = primero del cartel
        if d1.get("PR", 0) <= 0 or d2.get("PR", 0) <= 0:
            return self._descartar(clave, partido, "sin Puntuacion Global")
        f = oddspapi.buscar_partido(partidos, n1, n2)
        if f is None:
            return self._espera(clave, "OddsPapi no tiene el partido")
        if f.get("statusId") != 0:
            self._cerrados.add(clave)
            return
        if not f.get("hasOdds"):
            return self._espera(clave, "Winamax aún no tiene cuotas")
        odds = self.api.cuotas(f["fixtureId"])
        if odds.get("statusId", 0) != 0:
            self._cerrados.add(clave)
            return
        try:
            datos = decodificar(oddspapi.codificar(
                oddspapi.traducir(odds, f, self.reloj().timestamp(), self.api.casa)))
            r = preparar(datos, [n1, n2], [(n1, n2)])
        except (oddspapi.ErrorOddsPapi, DatosNoValidos) as e:
            return self._espera(clave, str(e))
        self._esperas.pop(clave, None)

        req = reglas.requisito_volatilidad(d1.get("volatilidad"), d2.get("volatilidad"))
        edge_min = req["edge_min"] if req["ok"] else reglas.EDGE_MIN
        calc = calcular_partido(d1, d2, j1_saca_primero=True)
        alertas = self.hoja.alertas()
        banca = registro.banca_actual(alertas)
        apuestas = []
        for s in r["selecciones"]:
            prob = probabilidad(calc, s["sel"])
            if prob is None:
                continue
            ev = reglas.evaluar(reglas.MERCADO_DE_TIPO[s["sel"]["tipo"]], prob, s["cuota"],
                                edge_min, req["rebaja"], banca)
            if ev["importe"] > 0:
                apuestas.append({"texto": texto_seleccion(s["sel"], n1, n2),
                                 "cuota": s["cuota"], "p": prob, "ev": ev})
        apuestas.sort(key=lambda a: a["ev"]["edge"], reverse=True)

        avisar = req["ok"] and apuestas and not self._ya_avisado(clave, fecha)
        info = None
        if clave not in self._guardados or avisar:
            info = self._info_partido(n1, n2, d1, d2)
            self._guardar_lectura(datos, r, calc, banca, info, d1, d2, fecha)
            self._guardados.add(clave)
        if not avisar:
            if not req["ok"]:
                self._descartar(clave, partido, req["motivo"])
            return
        queda = registro.tope_del_dia(alertas) - registro.gastado_del_dia(alertas, fecha)
        hora = (datetime.fromtimestamp(datos["t"], MADRID).strftime("%H:%M")
                if datos["t"] else "")
        titulo, texto = aviso.componer(
            n1, n2, apuestas, edge_min, hora, jornada=info.get("jornada") or jornada,
            n_partido=info.get("n_partido") or p["orden"] + 1, queda=queda,
            vol=req["vol"], rebaja=req["rebaja"], info=info)
        from vigia.boton import enlace_web_winamax
        enlace = enlace_app(self.aj.app_url, n1, n2)
        self.notif.enviar(texto, urgente=True, enlace=enlace, titulo=titulo,
                          acciones=[("Abrir en la app", enlace),
                                    ("Winamax", enlace_web_winamax(datos["id"]))])
        self._avisados.add(clave)
        self._log("aviso", partido, f"{titulo} | {texto}".replace("\n", " | ")[:500])
        self.hoja.volcar_log()   # cuanto antes, para que el otro vigia lo vea
        log.info("AVISO %s\n%s", titulo, texto)

    def _guardar_lectura(self, datos, r, calc, banca, info, d1, d2, fecha):
        """Guarda la lectura en cuotas_winamax (solo partidos fiables, como
        la app), con fuente 'vigia'."""
        if not registro.fiable(info):
            return
        ahora = self.reloj()
        base = dict(info, fecha=fecha, hora=ahora.strftime("%H:%M"), lectura=datos["h"],
                    match_id=datos["id"], j1=r["j1"], j2=r["j2"],
                    inicio=(datetime.fromtimestamp(datos["t"], MADRID)
                            .strftime("%Y-%m-%d %H:%M") if datos["t"] else ""),
                    vol_j1=_vol_num(d1.get("volatilidad")),
                    vol_j2=_vol_num(d2.get("volatilidad")), fuente="vigia", resultado="")
        filas = registro.filas_de_lectura(base, r["selecciones"], r["sin_asignar"], calc, banca)
        if filas:
            self.hoja.anadir_winamax(filas)

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
