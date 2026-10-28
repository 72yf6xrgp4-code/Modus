"""Genera boton/marcador.txt (el marcador "javascript:..." que se instala en
el navegador) a partir de boton/modus_value.js.

    python boton/construir.py
"""

import re
from pathlib import Path
from urllib.parse import quote

AQUI = Path(__file__).resolve().parent


def marcador(fuente=None):
    js = fuente if fuente is not None else (AQUI / "modus_value.js").read_text(encoding="utf-8")
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)          # comentarios /* */
    lineas = [l.strip() for l in js.splitlines()]
    js = " ".join(l for l in lineas if l)
    # Codificado para que ni Chrome ni Safari toquen comillas, % o espacios
    return "javascript:" + quote(js, safe="(){}[];,.=!&|<>+-*/:?'\"_$")


if __name__ == "__main__":
    (AQUI / "marcador.txt").write_text(marcador() + "\n", encoding="utf-8")
    print(f"Escrito {AQUI / 'marcador.txt'}")
