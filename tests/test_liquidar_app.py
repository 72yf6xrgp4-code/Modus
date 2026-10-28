import json

from modelo import datos as md
from vigia.registro import COLUMNAS_ALERTAS, COLUMNAS_WINAMAX


class WS:
    """Hoja de gspread de mentira: get_all_values y batch_update."""
    def __init__(self, cab, filas):
        self.valores = [cab] + [[f.get(c, "") for c in cab] for f in filas]
        self.cab = cab

    def get_all_values(self):
        return self.valores

    def batch_update(self, datos, value_input_option=None):
        from gspread.utils import a1_to_rowcol
        for d in datos:
            r, c = a1_to_rowcol(d["range"])
            self.valores[r - 1][c - 1] = d["values"][0][0]


def test_la_app_apunta_resultados(monkeypatch):
    import alertas_ui
    from vigia.nucleo import DatosSheet, Vigia
    lineas = [[""]] * 6 + [["Andy Baetens", "4", "3"], ["Cameron Menzies", "2", "1"]]
    monkeypatch.setattr(md, "descargar_lineas", lambda j, timeout=8: lineas)
    gana = json.dumps({"tipo": "ganador", "jugador": 1})
    alerta = {"fecha": "2026-11-05", "j1": "Andy Baetens", "j2": "Cameron Menzies",
              "tipo_aviso": "apuesta", "estado": "apostada", "cuota": "2", "importe": "5",
              "importe_real": "10", "seleccion_json": gana}
    cuota = {"fecha": "2026-11-05", "j1": "Cameron Menzies", "j2": "Andy Baetens",
             "seleccion_json": json.dumps({"tipo": "ganador", "jugador": 1})}
    ws_a, ws_w = WS(COLUMNAS_ALERTAS, [alerta]), WS(COLUMNAS_WINAMAX, [cuota])
    hoja = alertas_ui._HojaApp(ws_a, ws_w)
    assert Vigia(hoja, None, DatosSheet(), None).liquidar() == 2
    hoja.volcar()
    fila = dict(zip(COLUMNAS_ALERTAS, ws_a.valores[1]))
    assert (fila["resultado"], fila["beneficio"]) == ("ganada", 10.0)   # con lo apostado
    assert dict(zip(COLUMNAS_WINAMAX, ws_w.valores[1]))["resultado"] == "perdida"
