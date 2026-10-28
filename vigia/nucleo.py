"""
vigia/nucleo.py - Logica del vigia: datos del modelo, evaluacion de cada
partido de Winamax, avisos, tope diario y liquidacion de resultados.

Todo se inyecta (cliente de Winamax, hoja, notificador, fuente de datos)
para poder probarlo sin red.
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from modelo import datos as md
from modelo.motor import calcular_partido, probabilidad
from modelo.util import normalizar_nombre
from modelo.volatilidad import nivel_volatilidad
from vigia import reglas, registro
from vigia.mercados import asignar, texto_seleccion
from vigia.nombres import emparejar, mismo_jugador
from vigia.winamax import Bloqueado, mercados, partidos

log = logging.getLogger(__name__)
MADRID = ZoneInfo("Europe/Madrid")


def ahora_madrid():
    return datetime.now(MADRID)


def fecha_jornada(ahora):
    """Dia 'de jornada' (YYYY-MM-DD), igual que helpers.fecha_jornada_madrid:
    de 00:00 a 03:00 cuenta como el dia anterior (la sesion nocturna se
    alarga). Lo usan el tope diario y el aviso unico por partido."""
    if ahora.hour * 60 + ahora.minute <= 3 * 60:
        ahora = ahora - timedelta(days=1)
    return ahora.strftime("%Y-%m-%d")


def eur(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + " €"


def apellido(n):
    return n.split()[-1] if n else n


# ─────────────────────────────────────────────────────────────────────────────
# DATOS DEL MODELO (misma fuente que Value Bets: "Forma reciente")
# ─────────────────────────────────────────────────────────────────────────────

class DatosSheet:
    """Jugadores ('Forma reciente') y calendario del dia, recargados cada
    `recarga_seg` segundos."""

    def __init__(self, recarga_seg=300):
        self.recarga_seg = recarga_seg
        self._t = 0.0
        self.jugadores = {}
        self.calendario = {}   # jornada -> partidos_de_jornada
        self.jornada_hoy = None

    def refrescar(self, ahora, forzar=False):
        if not forzar and time.time() - self._t < self.recarga_seg:
            return False
        # Igual que data_loading.cargar_forma_reciente: la jornada que toca
        # por hora, solo si ya tiene datos.
        jornada = md.jornada_por_hora(ahora)
        hoy = md.cargar_jugadores(jornada) if jornada else {}
        self.jornada_hoy = jornada if hoy else None
        resumen = md.cargar_jugadores("Resumen Semanal")
        if not resumen:
            jugadores = hoy
        elif not self.jornada_hoy:
            jugadores = resumen
        else:
            jugadores = md.combinar_forma_reciente(resumen, hoy)
        if jugadores:
            self.jugadores = jugadores
        dia = datetime.fromisoformat(fecha_jornada(ahora))
        self.calendario = {j: md.partidos_de_jornada(md.descargar_lineas(j))
                           for j in md.jornadas_del_dia(dia)}
        self._t = time.time()
        return True

    def partidos_calendario(self):
        for jornada, lista in self.calendario.items():
            for p in lista:
                yield jornada, p


# ─────────────────────────────────────────────────────────────────────────────
# VIGIA
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Candidata:
    sel: dict
    mercado: str        # ganador / handicap / total_legs / resultado / 180s
    nombre_mercado: str
    titulo: str
    label: str
    cuota: float
    p: float
    ev: dict


class Vigia:
    def __init__(self, cliente, hoja, notificador, datos, ajustes,
                 reloj=ahora_madrid):
        self.cliente = cliente
        self.hoja = hoja
        self.notif = notificador
        self.datos = datos
        self.aj = ajustes
        self.reloj = reloj
        self._descartados = {}   # match_id -> motivo (se limpia al recargar)
        self._vistos = set()
        self._dia = None
        self._avisados = set()
        self._tope_avisado = False
        self._sin_modus = 0

    # ── estado del dia ─────────────────────────────────────────────────
    def _clave(self, fecha, a, b):
        x, y = sorted([normalizar_nombre(a), normalizar_nombre(b)])
        return f"{fecha}|{x}|{y}"

    def _cargar_dia(self, fecha):
        """Recupera de la hoja los avisos de hoy (por si el vigia se
        reinicia) y si ya se aviso del tope."""
        self._dia = fecha
        self._avisados = set()
        for f in self.hoja.alertas():
            if f.get("fecha") == fecha:
                self._avisados.add(self._clave(fecha, f.get("j1", ""), f.get("j2", "")))
        self._tope_avisado = any(d.get("tipo") == "tope"
                                 for d in self.hoja.log_del_dia(fecha))

    def gastado(self, fecha):
        return registro.gastado_del_dia(self.hoja.alertas(), fecha)

    def _log(self, tipo, partido="", detalle=""):
        ahora = self.reloj()
        self.hoja.log({"fecha": fecha_jornada(ahora),
                       "hora": ahora.strftime("%H:%M:%S"), "tipo": tipo,
                       "partido": partido, "detalle": detalle})

    def _descartar(self, p, motivo):
        if self._descartados.get(p["id"]) != motivo:
            self._descartados[p["id"]] = motivo
            log.info("Descartado %s vs %s: %s", p["c1"], p["c2"], motivo)
            self._log("descartado", f"{p['c1']} vs {p['c2']}", motivo)

    # ── un ciclo ───────────────────────────────────────────────────────
    def es_modus(self, p):
        t = normalizar_nombre(p.get("torneo", ""))
        return any(normalizar_nombre(w) in t for w in self.aj.torneo_palabras)

    def ciclo(self):
        """Una vuelta: devuelve el n de partidos de Modus prepartido."""
        ahora = self.reloj()
        fecha = fecha_jornada(ahora)
        if fecha != self._dia:
            self._cargar_dia(fecha)
        if self.datos.refrescar(ahora):
            self._descartados.clear()
            self.liquidar()

        estado = self.cliente.estado_dardos()
        ts = ahora.timestamp()
        pre = [p for p in partidos(estado)
               if p["status"].upper() == "PREMATCH" and not p["outright"]
               and p["inicio"] > ts and p["c1"] and p["c2"]]
        modus = []
        for p in pre:
            if p["id"] not in self._vistos:
                self._vistos.add(p["id"])
                es = self.es_modus(p)
                self._log("visto", f"{p['c1']} vs {p['c2']}",
                          f"torneo='{p['torneo']}' id={p['id']} "
                          f"{'MODUS' if es else 'ignorado'}")
            if self.es_modus(p):
                modus.append(p)
        for p in sorted(modus, key=lambda x: x["inicio"]):
            try:
                self.evaluar_partido(p, ahora, fecha)
            except Bloqueado:
                raise
            except Exception as e:  # un partido no tumba el ciclo
                log.exception("Error evaluando %s", p["id"])
                self._log("error", f"{p['c1']} vs {p['c2']}", repr(e)[:300])
        self.hoja.volcar_log()
        return len(modus)

    def orden_cartel(self, n1, n2):
        """(invertido, jornada): invertido=True si en el cartel el primero
        es n2. (None, None) si el partido no esta en el calendario."""
        for jornada, cp in self.datos.partidos_calendario():
            if mismo_jugador(cp["j1"], n1) and mismo_jugador(cp["j2"], n2):
                return False, jornada
            if mismo_jugador(cp["j1"], n2) and mismo_jugador(cp["j2"], n1):
                return True, jornada
        return None, None

    def evaluar_partido(self, p, ahora, fecha):
        if self._tope_avisado:
            return
        db = {v["nombre_original"]: v for v in self.datos.jugadores.values()}
        nombres = list(db)
        n1, n2 = emparejar(p["c1"], nombres), emparejar(p["c2"], nombres)
        if not n1 or not n2:
            falta = [c for c, n in ((p["c1"], n1), (p["c2"], n2)) if not n]
            return self._descartar(p, f"no esta en la hoja: {', '.join(falta)}")
        if n1 == n2:
            return self._descartar(p, f"los dos nombres apuntan a {n1}")
        if self._clave(fecha, n1, n2) in self._avisados:
            return

        invertido, jornada = self.orden_cartel(n1, n2)
        orden = "cartel"
        if invertido is None:
            invertido, orden, jornada = False, "winamax", ""
        j1, j2 = (n2, n1) if invertido else (n1, n2)
        d1, d2 = db[j1], db[j2]

        ok, motivo = reglas.partido_elegible(d1.get("volatilidad"),
                                             d2.get("volatilidad"))
        if not ok:
            return self._descartar(p, motivo)
        if d1.get("PR", 0) <= 0 or d2.get("PR", 0) <= 0:
            return self._descartar(p, "sin Puntuacion Global")

        # Winamax publica los mercados poco antes: solo se mira la pagina
        # del partido si empieza pronto.
        if p["inicio"] - ahora.timestamp() > self.aj.ventana_min * 60:
            return

        cands = self.candidatas(p, invertido, d1, d2)
        avisables = [c for c in cands if c.ev["edge"] >= reglas.EDGE_MIN - 1e-9]
        if not avisables:
            return
        normales = [c for c in avisables if not c.ev["revisar"]]
        mejor = max(normales or avisables, key=lambda c: c.ev["edge"])
        self.avisar(p, mejor, j1, j2, d1, d2, orden, jornada, fecha)

    def candidatas(self, p, invertido, d1, d2):
        estado = self.cliente.estado_partido(p["id"])
        calc = calcular_partido(d1, d2, j1_saca_primero=True)
        salida = []
        for m in mercados(estado, p["id"]):
            if not m["disponible"]:
                continue
            for o in m["salidas"]:
                if not o["cuota"]:
                    continue
                r = asignar(m["titulo"], o["label"], o["code"],
                            (p["c1"], p["c2"]), invertido)
                if r is None:
                    continue
                sel, nombre = r
                prob = probabilidad(calc, sel)
                if prob is None:
                    continue
                mercado = reglas.MERCADO_DE_TIPO[sel["tipo"]]
                salida.append(Candidata(sel, mercado, nombre, m["titulo"],
                                        o["label"], o["cuota"], prob,
                                        reglas.evaluar(mercado, prob, o["cuota"])))
        return salida

    # ── avisos ─────────────────────────────────────────────────────────
    def avisar(self, p, c, j1, j2, d1, d2, orden, jornada, fecha):
        ahora = self.reloj()
        hora = datetime.fromtimestamp(p["inicio"], MADRID).strftime("%H:%M")
        partido = f"{apellido(j1)} vs {apellido(j2)}"
        sel_txt = texto_seleccion(c.sel, j1, j2)
        extra = " · J1 s/Winamax" if orden == "winamax" else ""
        clave = self._clave(fecha, j1, j2)
        cuota_txt = f"{c.cuota:.2f}".replace(".", ",")

        if c.ev["revisar"]:
            tipo, estado, importe = registro.AVISO_REVISAR, registro.ESTADO_REVISAR, 0.0
            gastado = self.gastado(fecha)
            texto = (f"⚠️ REVISAR {hora} {partido} · {sel_txt} @{cuota_txt} · "
                     f"modelo {c.p*100:.0f} % · margen {c.ev['margen']*100:.0f} pts{extra}")
        else:
            gastado = self.gastado(fecha)
            importe = reglas.aplicar_tope(c.ev["importe"], gastado,
                                          self.aj.tope_diario)
            if importe <= 0:
                self._avisar_tope(fecha)
                return
            tipo, estado = registro.AVISO_APUESTA, registro.ESTADO_PENDIENTE
            gastado += importe
            verde = " 🟢" if c.ev["verde"] else ""
            texto = (f"🎯 {hora} {partido} · {sel_txt} @{cuota_txt} · "
                     f"modelo {c.p*100:.0f} % · edge {c.ev['edge']*100:.0f} %{verde} · "
                     f"{eur(importe)} · quedan {eur(self.aj.tope_diario - gastado)}{extra}")
        texto = texto[:199]

        fila = {
            "id": f"{fecha}-{p['id']}", "fecha": fecha,
            "hora": ahora.strftime("%H:%M"), "partido": f"{j1} vs {j2}",
            "j1": j1, "j2": j2,
            "vol_j1": nivel_volatilidad(d1.get("volatilidad")) or "",
            "vol_j2": nivel_volatilidad(d2.get("volatilidad")) or "",
            "mercado": c.nombre_mercado, "seleccion": sel_txt,
            "cuota": c.cuota, "p_modelo": round(c.p, 4),
            "edge": round(c.ev["edge"], 4), "margen": round(c.ev["margen"], 4),
            "verde": "🟢" if c.ev["verde"] else "", "importe": importe,
            "tope_restante": max(0.0, self.aj.tope_diario - gastado),
            "estado": estado, "resultado": "", "beneficio": "",
            "tipo_aviso": tipo,
            "inicio": datetime.fromtimestamp(p["inicio"], MADRID).strftime("%Y-%m-%d %H:%M"),
            "match_id": p["id"], "jornada": jornada, "orden_j1": orden,
            "seleccion_json": json.dumps(c.sel, ensure_ascii=False),
        }
        self.hoja.anadir_alerta(fila)
        self._avisados.add(clave)
        self.notif.enviar(texto, urgente=(tipo == registro.AVISO_APUESTA))
        self._log("alerta", fila["partido"], texto)
        log.info("ALERTA %s", texto)
        if tipo == registro.AVISO_APUESTA and self.aj.tope_diario - gastado < reglas.UNIDAD:
            self._avisar_tope(fecha)

    def _avisar_tope(self, fecha):
        if self._tope_avisado:
            return
        self._tope_avisado = True
        texto = f"🛑 Tope de {eur(self.aj.tope_diario)} alcanzado: no habrá más avisos hoy"
        self.notif.enviar(texto, urgente=True)
        self._log("tope", "", texto)

    # ── resultados ─────────────────────────────────────────────────────
    def liquidar(self):
        """Apunta resultado y beneficio de las alertas cuyos partidos ya han
        terminado (leyendo las pestanas de jornada del Sheet)."""
        filas = [f for f in self.hoja.alertas()
                 if f.get("tipo_aviso") in (registro.AVISO_APUESTA, registro.AVISO_REVISAR)
                 and f.get("resultado") not in ("ganada", "perdida")]
        if not filas:
            return 0
        cache = {}
        n = 0
        for f in filas:
            try:
                dia = datetime.fromisoformat(f["fecha"])
            except (KeyError, ValueError):
                continue
            jornadas = [f.get("jornada")] if f.get("jornada") else md.jornadas_del_dia(dia)
            real = None
            for j in jornadas:
                if j not in cache:
                    cache[j] = md.partidos_de_jornada(md.descargar_lineas(j))
                for cp in cache[j]:
                    if cp["estado"] != "terminado":
                        continue
                    if mismo_jugador(cp["j1"], f["j1"]) and mismo_jugador(cp["j2"], f["j2"]):
                        real = (cp["legs1"], cp["legs2"], cp["t180_1"], cp["t180_2"])
                    elif mismo_jugador(cp["j1"], f["j2"]) and mismo_jugador(cp["j2"], f["j1"]):
                        real = (cp["legs2"], cp["legs1"], cp["t180_2"], cp["t180_1"])
                    if real:
                        break
                if real:
                    break
            if not real:
                continue
            ok = reglas.acierta(registro.seleccion(f), *real)
            if ok is None:
                continue
            resultado = "ganada" if ok else "perdida"
            ben = registro.beneficio_fila(dict(f, resultado=resultado))
            self.hoja.actualizar_resultado(f["_fila"], resultado, ben)
            self._log("resultado", f.get("partido", ""),
                      f"{resultado} ({real[0]}-{real[1]}, 180s {real[2]}-{real[3]})")
            n += 1
        return n

    def quedan_partidos_hoy(self):
        """True si el calendario de hoy aun tiene partidos sin terminar."""
        return any(cp["estado"] != "terminado"
                   for _j, cp in self.datos.partidos_calendario())
