# Vigía de value bets (Winamax → móvil)

Script que corre **en tu portátil con Windows** durante las jornadas de Modus.
Lee las cuotas prepartido de Winamax (solo lectura, sin iniciar sesión), las
compara con el mismo modelo de la pestaña Value Bets y, si una apuesta cumple
tus reglas, te manda un aviso al móvil (ntfy) y lo apunta en la pestaña
`alertas` del Google Sheet. **Nunca apuesta.** La app de Streamlit solo lee esa
pestaña (pestaña 🔔 Alertas y bloque «Apuestas del vigía» en 📈 Seguimiento).

Nada de esto corre en Streamlit Cloud ni en GitHub Actions: la app no tiene
bucles, ni hilos, ni autorefresco; el vigía no hace commits.

## 1. Instalación (una vez)

En PowerShell, dentro de la carpeta del repo (rama `vigia-alertas`):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-vigia.txt
copy .env.example .env
notepad .env
```

En `.env`:

1. **ntfy**: instala la app ntfy en el móvil. Genera un tema largo y aleatorio
   con `python -c "import secrets;print('modus-'+secrets.token_urlsafe(24))"`,
   ponlo en `NTFY_TEMA` y suscríbete a ese tema en la app. El tema funciona
   como contraseña: no lo compartas.
2. **Google**: guarda el JSON de la cuenta de servicio (el mismo que tienes en
   los *secrets* de Streamlit como `gcp_service_account_json`) en un archivo
   **fuera del repo**, por ejemplo `C:\Users\TU_USUARIO\claves\modus-cuenta-servicio.json`,
   y pon esa ruta en `GOOGLE_CREDENCIALES`. El Sheet de predicciones ya está
   compartido con esa cuenta. Las pestañas `alertas` y `vigia_log` se crean
   solas la primera vez.

Comprueba que todo va:

```powershell
python -m pytest                 # pruebas
python -m vigia --probar-aviso   # te debe llegar un aviso al móvil
```

## 2. Primer día de Modus (revisión a mano)

```powershell
python -m vigia --dump                       # partidos de dardos y su torneo
```

- Mira cómo titula Winamax el torneo de Modus y, si no contiene «modus», pon la
  palabra en `WINAMAX_TORNEO` del `.env`.
- Cuando un partido de Modus tenga mercados publicados:

```powershell
python -m vigia --dump 123456 --guardar-fixture
```

  Muestra cada mercado y cada salida con la selección y la probabilidad que le
  asigna el modelo («(sin asignar)» = se ignora). Revisa que J1/J2, los
  hándicaps y los totales cuadran. El HTML queda en `tests/fixtures/` para el
  test de integración (súbelo al repo o pásamelo para ajustar los patrones).
- **Comprobación ±0,1 puntos**: en ese momento, abre Value Bets en la app con la
  fuente «Forma reciente» y el mismo J1 (el primero del cartel). P(J1) y
  P(J2) deben coincidir con las que imprime `--dump`. Repítelo con 3 partidos.
- Prueba en seco: `python -m vigia --simular` (lee todo, imprime los avisos en
  pantalla, no notifica ni escribe en la hoja).

## 3. Uso diario

```powershell
python -m vigia                                  # 12:00 hasta que no queden partidos
python -m vigia --desde 10:15 --hasta 23:00 --intervalo 60
python -m vigia --liquidar                       # solo apunta resultados pendientes
```

Tarea automática (de lunes a sábado a las 11:55, la creas tú):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\crear_tarea_vigia.ps1
# Para el Grupo A (empieza a las 10:30):
powershell -ExecutionPolicy Bypass -File scripts\crear_tarea_vigia.ps1 -Hora 10:00 -Desde 10:05
```

El portátil tiene que estar encendido y con conexión. El log está en
`logs\vigia.log` (con rotación, 5 × 2 MB).

## Qué hace en cada vuelta

- Cada 60 s lee la página de dardos de Winamax. Solo pide la página de un
  partido si es de Modus, está en `PREMATCH`, empieza en menos de
  `VENTANA_MIN` minutos y aún no tiene aviso. Si Winamax responde 403/429, el
  vigía para y te avisa.
- Cada 5 min recarga los datos del Sheet (la misma «Forma reciente» que Value
  Bets) y apunta resultado y beneficio de las alertas cuyos partidos ya han
  terminado.
- **J1** es el primero del cartel si el partido está en el calendario de la
  hoja. Si no, es el primero de Winamax y el aviso termina en «J1 s/Winamax».

## Reglas

| Regla | Valor |
|---|---|
| Partido válido | los dos jugadores con volatilidad baja o media (sin datos → fuera) |
| Aviso | edge = p × cuota − 1 ≥ 10 % |
| 🟢 | p − 1/cuota ≥ margen del mercado: ganador 6, total de legs 8, hándicaps y 180s 5 puntos (`MARGENES_VALUE` en `config.py`, los mismos de la app). Resultado exacto nunca 🟢 |
| Importe | edge 10–15 % → 2,5 €; 15–20 % → 5 €; ≥ 20 % → 7,5 €. Más de 2,5 € solo si 🟢 y cuota ≤ 4,00 |
| Por partido | un aviso como máximo: la selección con más edge cuando cumple por primera vez |
| Tope | 50 € por jornada, recortando en múltiplos de 2,5. Al agotarlo, aviso «tope alcanzado» y ninguno más ese día. Una alerta marcada «no apostada» devuelve su importe |
| Margen > 20 puntos | «⚠️ REVISAR»: sin importe y sin gastar tope (solo si no hay otra selección válida en ese partido) |

## Archivos

- `modelo/`: motor y lectura del Sheet sin Streamlit (lo usan la app y el vigía).
- `vigia/`: `winamax.py` (lectura), `mercados.py` (títulos → selecciones),
  `reglas.py`, `nucleo.py` (bucle, avisos, tope, liquidación), `hoja.py`,
  `notificador.py`, `registro.py` (esquema de la hoja y ROI), `cli.py`,
  `dump.py`.
- `alertas_ui.py`: pestaña Alertas y bloque de Seguimiento de la app.
- `tests/`: `python -m pytest`.
