"""
modelo - Motor de probabilidades y lectura de datos SIN Streamlit.

Lo usan la app (a traves de stats_engine, data_loading y helpers, que
reexportan estas funciones con su cache de Streamlit) y el vigia
(vigia/), que corre fuera de Streamlit. Asi los dos dan exactamente los
mismos numeros.

  - util.py         conversiones numericas y normalizacion de nombres
  - motor.py        modelo Elo leg a leg (Bo7), 180s, handicaps, legs
  - volatilidad.py  nivel de riesgo segun el Indice Volatilidad
  - value.py        yield, margen de seguridad por mercado (🟢)
  - datos.py        parseo de las pestanas del Sheet y Forma reciente
"""
