"""
vigia/hoja.py - Escritura y lectura del Google Sheet con gspread y la
cuenta de servicio (fichero JSON fuera del repo, ruta en .env).

Pestanas: 'alertas' (una fila por aviso) y 'vigia_log' (partidos vistos,
descartados y errores). Se crean con su cabecera si no existen.
"""

import logging

from vigia.registro import (HOJA_ALERTAS, HOJA_LOG, COLUMNAS_ALERTAS,
                            COLUMNAS_LOG, filas_a_dicts)

log = logging.getLogger(__name__)


class HojaGoogle:
    def __init__(self, ruta_credenciales, sheet_id):
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(ruta_credenciales,
                                                      scopes=scopes)
        self.libro = gspread.authorize(creds).open_by_key(sheet_id)
        self.ws_alertas = self._pestana(HOJA_ALERTAS, COLUMNAS_ALERTAS)
        self.ws_log = self._pestana(HOJA_LOG, COLUMNAS_LOG)
        self._log_pendiente = []

    def _pestana(self, nombre, columnas):
        try:
            ws = self.libro.worksheet(nombre)
        except Exception:
            ws = self.libro.add_worksheet(title=nombre, rows=1000,
                                          cols=len(columnas))
            ws.append_row(columnas)
            return ws
        if not ws.row_values(1):
            ws.append_row(columnas)
        return ws

    def alertas(self):
        return filas_a_dicts(self.ws_alertas.get_all_values())

    def anadir_alerta(self, fila):
        self.ws_alertas.append_row([fila.get(c, "") for c in COLUMNAS_ALERTAS],
                                   value_input_option="RAW")

    def actualizar_resultado(self, n_fila, resultado, beneficio):
        cab = COLUMNAS_ALERTAS
        c_res = cab.index("resultado") + 1
        c_ben = cab.index("beneficio") + 1
        self.ws_alertas.update_cell(n_fila, c_res, resultado)
        self.ws_alertas.update_cell(n_fila, c_ben, round(beneficio, 2))

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

    def __init__(self, alertas=None):
        self._alertas = list(alertas or [])
        self.logs = []

    def alertas(self):
        return [dict(a, _fila=i + 2) for i, a in enumerate(self._alertas)]

    def anadir_alerta(self, fila):
        self._alertas.append(dict(fila))

    def actualizar_resultado(self, n_fila, resultado, beneficio):
        self._alertas[n_fila - 2]["resultado"] = resultado
        self._alertas[n_fila - 2]["beneficio"] = round(beneficio, 2)

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

    def anadir_alerta(self, fila):
        self._memoria.anadir_alerta(fila)

    def actualizar_resultado(self, n_fila, resultado, beneficio):
        log.info("[simular] fila %s -> %s (%.2f)", n_fila, resultado, beneficio)

    def log(self, fila):
        self._memoria.log(fila)

    def log_del_dia(self, fecha):
        return self._hoja.log_del_dia(fecha) + self._memoria.log_del_dia(fecha)

    def volcar_log(self):
        pass
