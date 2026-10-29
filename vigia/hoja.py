"""
vigia/hoja.py - Escritura y lectura del Google Sheet con gspread y la
cuenta de servicio (fichero JSON fuera del repo, ruta en .env).

Pestanas: 'alertas' (las apuestas que apuntas desde la app; el vigia solo
les pone resultado y beneficio), 'cuotas_minimas' (lo que calcula el
vigia) y 'vigia_log' (partidos avisados, descartados y errores). Se crean
con su cabecera si no existen.
"""

import logging
import re

from vigia.registro import (HOJA_ALERTAS, HOJA_LOG, HOJA_CUOTAS, HOJA_WINAMAX,
                            COLUMNAS_ALERTAS, COLUMNAS_LOG, COLUMNAS_CUOTAS,
                            COLUMNAS_WINAMAX, filas_a_dicts)

log = logging.getLogger(__name__)


def _celdas(columnas, cambios):
    """[(n_fila, {columna: valor})] -> datos de batch_update de gspread."""
    from gspread.utils import rowcol_to_a1
    return [{"range": rowcol_to_a1(n, columnas.index(c) + 1), "values": [[v]]}
            for n, campos in cambios for c, v in campos.items()]


class HojaGoogle:
    def __init__(self, ruta_credenciales, sheet_id, sheet_id_datos=""):
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        # Ruta al JSON (portatil) o el JSON ya leido (GitHub Actions)
        if isinstance(ruta_credenciales, dict):
            creds = Credentials.from_service_account_info(ruta_credenciales, scopes=scopes)
        else:
            creds = Credentials.from_service_account_file(ruta_credenciales, scopes=scopes)
        self.cliente = gspread.authorize(creds)
        self.libro = self.cliente.open_by_key(sheet_id)
        self._sheet_id_datos = sheet_id_datos or sheet_id
        self._libro_datos = None
        self._ws_jornadas = {}
        self.ws_alertas = self._pestana(HOJA_ALERTAS, COLUMNAS_ALERTAS)
        self.ws_log = self._pestana(HOJA_LOG, COLUMNAS_LOG)
        self.ws_cuotas = self._pestana(HOJA_CUOTAS, COLUMNAS_CUOTAS)
        self.ws_winamax = self._pestana(HOJA_WINAMAX, COLUMNAS_WINAMAX)
        self._log_pendiente = []

    def _pestana(self, nombre, columnas):
        try:
            ws = self.libro.worksheet(nombre)
        except Exception:
            ws = self.libro.add_worksheet(title=nombre, rows=1000,
                                          cols=len(columnas))
            ws.append_row(columnas)
            return ws
        cabecera = ws.row_values(1)
        if not cabecera:
            ws.append_row(columnas)
        elif cabecera != columnas:
            # Version nueva (columnas anadidas o renombradas): cabecera nueva
            log.warning("Actualizo la cabecera de %s: %s", nombre, columnas)
            if ws.col_count < len(columnas):
                ws.add_cols(len(columnas) - ws.col_count)
            ws.update(range_name="A1", values=[columnas])
        return ws

    def leer_jornada(self, jornada):
        """Filas de una pestana de jornada por la API (al momento; el CSV
        publicado va con minutos de retraso). Misma forma que
        modelo.datos.descargar_lineas. La pestana se busca por su gid."""
        ws = self._ws_jornadas.get(jornada)
        if ws is None:
            from config import URLS
            m = re.search(r"gid=(\d+)", URLS.get(jornada, ""))
            if not m:
                raise ValueError(f"no se el gid de la pestana {jornada}")
            if self._libro_datos is None:
                self._libro_datos = (self.libro if self._sheet_id_datos == self.libro.id
                                     else self.cliente.open_by_key(self._sheet_id_datos))
            ws = self._libro_datos.get_worksheet_by_id(int(m.group(1)))
            self._ws_jornadas[jornada] = ws
        return ws.get_all_values()

    def alertas(self):
        return filas_a_dicts(self.ws_alertas.get_all_values())

    def anadir_alerta(self, fila):
        self.ws_alertas.append_row([fila.get(c, "") for c in COLUMNAS_ALERTAS],
                                   value_input_option="RAW")

    def actualizar_alerta(self, n_fila, campos):
        """Cambia varias celdas de una fila de alertas en una peticion."""
        self.ws_alertas.batch_update(_celdas(COLUMNAS_ALERTAS, [(n_fila, campos)]),
                                     value_input_option="RAW")

    def anadir_cuotas(self, filas):
        self.ws_cuotas.append_rows([[f.get(c, "") for c in COLUMNAS_CUOTAS]
                                    for f in filas], value_input_option="RAW")

    def filas_winamax(self):
        return filas_a_dicts(self.ws_winamax.get_all_values())

    def historico(self):
        """Filas de la pestana 'Historico' (las semanas anteriores que guarda
        el cierre semanal), o [] si no existe."""
        try:
            return filas_a_dicts(self.libro.worksheet("Historico").get_all_values())
        except Exception:
            return []

    def actualizar_winamax(self, cambios):
        """[(n_fila, {columna: valor})] en una sola peticion."""
        self.ws_winamax.batch_update(_celdas(COLUMNAS_WINAMAX, cambios),
                                     value_input_option="RAW")

    def log(self, fila):
        self._log_pendiente.append([fila.get(c, "") for c in COLUMNAS_LOG])

    def log_del_dia(self, fecha):
        return [d for d in filas_a_dicts(self.ws_log.get_all_values())
                if d.get("fecha") == fecha]

    def volcar_log(self):
        """Escribe el log acumulado en una sola peticion."""
        if not self._log_pendiente:
            return
        filas, self._log_pendiente = self._log_pendiente, []
        try:
            self.ws_log.append_rows(filas, value_input_option="RAW")
        except Exception as e:
            log.error("No se pudo escribir vigia_log: %s", e)


class HojaMemoria:
    """Hoja en memoria (modo --simular sin credenciales y tests)."""

    def __init__(self, alertas=None, winamax=None):
        self._alertas = list(alertas or [])
        self._winamax = list(winamax or [])
        self.logs = []
        self.cuotas = []

    def alertas(self):
        return [dict(a, _fila=i + 2) for i, a in enumerate(self._alertas)]

    def anadir_alerta(self, fila):
        self._alertas.append(dict(fila))

    def actualizar_alerta(self, n_fila, campos):
        self._alertas[n_fila - 2].update(campos)

    def anadir_cuotas(self, filas):
        self.cuotas.extend(dict(f) for f in filas)

    def filas_winamax(self):
        return [dict(f, _fila=i + 2) for i, f in enumerate(self._winamax)]

    def historico(self):
        return []

    def actualizar_winamax(self, cambios):
        for n, campos in cambios:
            self._winamax[n - 2].update(campos)

    def log(self, fila):
        self.logs.append(dict(fila))

    def log_del_dia(self, fecha):
        return [d for d in self.logs if d.get("fecha") == fecha]

    def volcar_log(self):
        pass


class HojaSoloLectura:
    """Lee de la hoja real pero no escribe nada (modo --simular)."""

    def __init__(self, hoja):
        self._hoja = hoja
        self._memoria = HojaMemoria()

    def alertas(self):
        return self._hoja.alertas() + self._memoria.alertas()

    def leer_jornada(self, jornada):
        return self._hoja.leer_jornada(jornada)

    def anadir_alerta(self, fila):
        self._memoria.anadir_alerta(fila)

    def actualizar_alerta(self, n_fila, campos):
        log.info("[simular] fila %s -> %s", n_fila, campos)

    def anadir_cuotas(self, filas):
        self._memoria.anadir_cuotas(filas)

    def filas_winamax(self):
        return self._hoja.filas_winamax()

    def historico(self):
        return self._hoja.historico()

    def actualizar_winamax(self, cambios):
        log.info("[simular] %d cuotas de Winamax actualizadas", len(cambios))

    def log(self, fila):
        self._memoria.log(fila)

    def log_del_dia(self, fecha):
        return self._hoja.log_del_dia(fecha) + self._memoria.log_del_dia(fecha)

    def volcar_log(self):
        pass
