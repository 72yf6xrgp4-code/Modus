"""
vigia/notificador.py - Avisos al movil. Intercambiable:
  - ntfy (por defecto): POST a https://ntfy.sh/<tema>. El tema es la
    "contrasena": largo y aleatorio, en .env.
  - telegram: bot con token y chat_id en .env.
  - consola: solo escribe en el log (modo --simular).
"""

import logging

import requests

log = logging.getLogger(__name__)


class Consola:
    def enviar(self, texto, urgente=False, enlace=None, titulo=None, acciones=None):
        if titulo:
            texto = f"{titulo}\n{texto}"
        log.info("[aviso] %s%s", texto, f"  -> {enlace}" if enlace else "")
        print(texto + (f"\n   {enlace}" if enlace else ""), flush=True)
        return True


class Ntfy:
    def __init__(self, tema, servidor="https://ntfy.sh", timeout=10):
        if not tema:
            raise ValueError("Falta NTFY_TEMA en .env")
        self.servidor = servidor.rstrip("/")
        self.tema = tema
        self.timeout = timeout

    def enviar(self, texto, urgente=False, enlace=None, titulo=None, acciones=None):
        """Se publica en JSON (admite tildes y emojis en el titulo).
        enlace: lo que abre al tocar la notificacion (la app con el partido).
        acciones: [(etiqueta, url)] botones bajo la notificacion."""
        cuerpo = {"topic": self.tema, "title": titulo or "Modus vigía", "message": texto,
                  "tags": ["dart"], "priority": 4 if urgente else 3}
        if enlace:
            cuerpo["click"] = enlace
        if acciones:
            cuerpo["actions"] = [{"action": "view", "label": e, "url": u, "clear": True}
                                 for e, u in acciones[:3]]
        try:
            r = requests.post(self.servidor, json=cuerpo, timeout=self.timeout)
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            log.error("ntfy fallo: %s", e)
            return False


class Telegram:
    def __init__(self, token, chat_id, timeout=10):
        if not token or not chat_id:
            raise ValueError("Faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID en .env")
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.timeout = timeout

    def enviar(self, texto, urgente=False, enlace=None, titulo=None, acciones=None):
        if titulo:
            texto = f"{titulo}\n{texto}"
        if enlace:
            texto = f"{texto}\n{enlace}"
        try:
            r = requests.post(self.url, timeout=self.timeout,
                              data={"chat_id": self.chat_id, "text": texto})
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            # No registrar la URL: lleva el token
            log.error("Telegram fallo: %s", type(e).__name__)
            return False


def crear(tipo, ajustes):
    tipo = (tipo or "ntfy").lower()
    if tipo == "ntfy":
        return Ntfy(ajustes.ntfy_tema, ajustes.ntfy_servidor)
    if tipo == "telegram":
        return Telegram(ajustes.telegram_token, ajustes.telegram_chat_id)
    if tipo == "consola":
        return Consola()
    raise ValueError(f"Notificador desconocido: {tipo}")
