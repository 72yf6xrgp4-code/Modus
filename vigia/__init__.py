"""
vigia - Vigia de value bets para la Modus Super Series.

Corre en el portatil (IP espanola), NUNCA en Streamlit ni en GitHub
Actions. Lee las cuotas prepartido de Winamax (solo lectura, sin iniciar
sesion), las compara con el modelo de la app (modelo/) y, cuando una
apuesta cumple las reglas, avisa al movil y la apunta en la pestana
'alertas' del Google Sheet. NUNCA apuesta.

Uso: python -m vigia --help
"""
