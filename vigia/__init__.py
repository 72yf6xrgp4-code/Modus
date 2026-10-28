"""
vigia - Vigia de "cuotas minimas" para la Modus Super Series.

Corre en el portatil, NUNCA en Streamlit ni en GitHub Actions, y NO hace
ninguna peticion a Winamax. Durante las jornadas lee el calendario y los
datos de la hoja (la misma "Forma reciente" que Value Bets) y, entre 30 y
45 minutos antes de cada partido, calcula para cada mercado del modelo la
cuota minima a partir de la cual habria value. Las apunta en la pestana
'cuotas_minimas' del Google Sheet y manda un aviso al movil (ntfy) con un
enlace a la app con el partido ya elegido. Tambien liquida (resultado y
beneficio) las apuestas apuntadas en la pestana 'alertas'. NUNCA apuesta.

Uso: python -m vigia --help
"""
