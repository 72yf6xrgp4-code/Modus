"""
vigia/ajustes.py - Configuracion del vigia, leida de .env (en la raiz del
repo, ignorado por git) o de variables de entorno. Ver .env.example.
"""

import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_env(ruta):
    """Lector minimo de .env (CLAVE=valor), sin dependencias."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


@dataclass
class Ajustes:
    notificador: str = "ntfy"
    ntfy_tema: str = ""
    ntfy_servidor: str = "https://ntfy.sh"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    credenciales_google: str = ""
    sheet_id: str = ""
    app_url: str = "https://modusapp.streamlit.app"
    tope_diario: float = 50.0
    recarga_datos_seg: int = 300
    # Duracion media de un partido (no tienen hora fija: empiezan seguidos)
    duracion_partido_min: int = 10
    # Se avisa cuando faltan como mucho estos minutos (entre 30 y 45)
    aviso_min_antes: int = 45


def cargar_ajustes():
    _cargar_env(RAIZ / ".env")
    from config import SHEET_ID_PREDICCIONES
    e = os.environ.get
    return Ajustes(
        notificador=e("NOTIFICADOR", "ntfy"),
        ntfy_tema=e("NTFY_TEMA", ""),
        ntfy_servidor=e("NTFY_SERVIDOR", "https://ntfy.sh"),
        telegram_token=e("TELEGRAM_TOKEN", ""),
        telegram_chat_id=e("TELEGRAM_CHAT_ID", ""),
        credenciales_google=e("GOOGLE_CREDENCIALES", ""),
        sheet_id=e("SHEET_ID", "") or SHEET_ID_PREDICCIONES,
        app_url=e("APP_URL", "https://modusapp.streamlit.app").rstrip("/"),
        tope_diario=float(e("TOPE_DIARIO", "50").replace(",", ".")),
        recarga_datos_seg=int(e("RECARGA_DATOS_SEG", "300")),
        duracion_partido_min=int(e("DURACION_PARTIDO_MIN", "10")),
        aviso_min_antes=int(e("AVISO_MIN_ANTES", "45")),
    )
