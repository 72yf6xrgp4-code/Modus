"""
vigia/ajustes.py - Configuracion del vigia, leida de .env (en la raiz del
repo, ignorado por git) o de variables de entorno. Ver .env.example.
"""

import os
from dataclasses import dataclass, field
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


def _lista(v):
    return [p.strip().lower() for p in (v or "").split(",") if p.strip()]


@dataclass
class Ajustes:
    notificador: str = "ntfy"
    ntfy_tema: str = ""
    ntfy_servidor: str = "https://ntfy.sh"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    credenciales_google: str = ""
    sheet_id: str = ""
    # Palabras que identifican el torneo de Modus en Winamax
    torneo_palabras: list = field(default_factory=lambda: ["modus"])
    tope_diario: float = 50.0
    recarga_datos_seg: int = 300
    # Solo se piden los mercados de partidos que empiezan en menos de esto
    ventana_min: int = 120


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
        torneo_palabras=_lista(e("WINAMAX_TORNEO", "modus")),
        tope_diario=float(e("TOPE_DIARIO", "50").replace(",", ".")),
        recarga_datos_seg=int(e("RECARGA_DATOS_SEG", "300")),
        ventana_min=int(e("VENTANA_MIN", "120")),
    )
