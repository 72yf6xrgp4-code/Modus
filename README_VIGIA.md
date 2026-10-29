# Vigía de cuotas mínimas y botón «Modus value»

Dos piezas, ninguna pide nada a Winamax:

1. **Vigía (portátil Windows y/o GitHub).** Durante las jornadas lee los datos de la hoja
   (la misma «Forma reciente» que Value Bets) y, cada minuto, el estado de los
   partidos por la API de Google. Cuando un partido pasa a ser **el siguiente**
   (termina el anterior de su jornada; el primero, 10 minutos antes de que
   empiece la jornada) calcula, para cada mercado del modelo, la
   **cuota mínima** a partir de la cual habría value. La apunta en la pestaña
   `cuotas_minimas` del Sheet y te manda un aviso al móvil (ntfy). Al tocar el
   aviso se abre la app con el partido elegido. También apunta el resultado
   y el beneficio de las apuestas de la pestaña `alertas`.
2. **Botón «Modus value» (marcador del navegador).** Con un partido de Modus
   abierto en la web de Winamax, lo pulsas a mano. Lee **solo** las cuotas que
   ya están en esa página y abre la app (Value Bets) con el partido y las
   cuotas rellenadas, el value marcado como siempre y el importe según tus
   reglas. Desde ahí, «📌 Apuntar apuesta» la guarda en 🎟️ Apuestas.

Ninguno inicia sesión, toca el boleto ni apuesta. La app no tiene bucles, ni
hilos, ni autorefresco; el vigía no hace commits.

## 1. Pasar tu instalación del portátil a este repo

Hoy tienes `C:\Users\alexm\Modus` (el repo antiguo) con `.venv` y `.env`, y la
clave en `C:\Users\alexm\claves\modus-cuenta-servicio.json`. En PowerShell:

```powershell
# 1) Quitar la tarea antigua, si se llegó a crear
Get-ScheduledTask -TaskName "Modus Vigia*" -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false

# 2) Clonar el repo publicado, en la rama del vigía
cd C:\Users\alexm
git clone https://github.com/alexmartinezsuarez-commits/modus modus-app
cd modus-app
git checkout vigia-cuotas-minimas

# 3) Entorno virtual nuevo
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-vigia.txt

# 4) Reutilizar tu .env (NTFY_TEMA y GOOGLE_CREDENCIALES siguen valiendo)
copy C:\Users\alexm\Modus\.env .env
notepad .env      # compáralo con .env.example; WINAMAX_TORNEO y VENTANA_MIN ya no se usan
```

La clave JSON **no se mueve**: sigue fuera del repo y `.env` apunta a ella.

Comprueba:

```powershell
python -m pytest                 # todas bien (alguna saltada si no hay Node)
python -m vigia --probar-aviso   # llega un aviso; al tocarlo se abre la app
python -m vigia --liquidar       # conecta con Google y crea la pestaña cuotas_minimas
python -m vigia --ver            # partidos de hoy, cuándo se avisará de cada uno y cuotas mínimas
```

Cuando todo vaya bien, crea la tarea (de una vez; si ya la tenías, vuelve a
ejecutarlo para pasar a la versión nueva):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\crear_tarea_vigia.ps1
```

Crea una sola tarea, **Modus Vigia**, que arranca el vigía:

| Cuándo | Qué hace el vigía |
|---|---|
| L-X 09:59 | ventana 10:00 – 16:00 (Grupo A 10:30) |
| J-V 13:29 | ventana 13:30 – 03:00 (C 14:00 y B 21:00, sin parar entre medias) |
| S 20:09 | ventana 20:10 – 03:00 (Final 20:40) |
| Al iniciar sesión (al encender el PC) y al desbloquearlo | dentro de una ventana, trabaja hasta que acabe; fuera, apunta los resultados pendientes y sale |

Si el PC estaba apagado a la hora de empezar, la tarea arranca en cuanto lo
enciendas. Nunca hay dos vigías del portátil a la vez. De 00:00 a 03:00
cuenta como la jornada del día anterior. Log: `logs\vigia.log` (con
rotación). Si dice «Acceso denegado», abre PowerShell como administrador.

Los resultados se pueden recuperar mientras la pestaña de esa jornada no se
reescriba (la semana siguiente): unos 6 días.

## 1 bis. Vigía en GitHub (sin el portátil)

El mismo vigía puede correr en GitHub Actions con una pasada cada pocos
minutos (`python -m vigia --una-vez`): dentro de
la ventana avisa por ntfy y rellena `cuotas_minimas`; siempre apunta los
resultados pendientes. Puede convivir con el del portátil: antes de avisar,
cada uno mira `vigia_log`, así que no llegan avisos repetidos.

0. **El workflow** `.github/workflows/vigia.yml` lo añades tú en GitHub
   (Add file → Create new file), copiado de la guía que te pasé. Lee la
   clave de Google de la variable de entorno, igual que el auto-registro,
   sin guardarla en disco.
1. **Secretos** (GitHub → repo → Settings → Secrets and variables →
   Actions → New repository secret):
   - `NTFY_TEMA`: el mismo tema que en tu `.env`.
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: ya existe (lo usa el auto-registro).
   - `SHEET_ID_DATOS` (opcional): el de tu `.env`. Solo sirve si esa cuenta
     de servicio puede leer el Sheet de las jornadas; si no, usa el CSV
     publicado (va con unos minutos de retraso).
2. **cron-job.org**: duplica el trabajo del auto-registro y cambia:
   - URL: `https://api.github.com/repos/alexmartinezsuarez-commits/modus/actions/workflows/vigia.yml/dispatches`
     (POST, cuerpo `{"ref":"main"}`, mismas cabeceras y token).
   - Frecuencia: cada 3 minutos, en las franjas de jornada (L-X 9:55-16:05,
     J-V 13:25-03:05, S 20:05-03:05). Fuera de horario basta con una vez
     cada hora (solo apunta resultados).

Cada pasada tarda en arrancar entre 30 s y 1 min, así que los avisos llegan
un poco más tarde que con el portátil (que mira cada minuto).

**Y además, la app:** al abrir 🎟️ Apuestas apunta los resultados que falten
(como mucho cada 10 minutos, o al pulsar «Actualizar»). Así el tope y el
beneficio están al día aunque no haya ningún vigía en marcha.

## 2. Instalar el botón «Modus value»

El código del marcador está en `boton/marcador.txt`. También aparece en la
app: 🎟️ Apuestas → «Instalar el botón Modus value», con botón de copiar.

**Chrome o Edge (portátil)**
1. Muestra la barra de marcadores: `Ctrl+Mayús+B`.
2. Clic derecho en la barra → *Añadir página…* (Edge: *Agregar página*).
3. Nombre: `Modus value`. URL: pega el código entero (empieza por `javascript:`).
4. Uso: abre el partido en winamax.es y pulsa el marcador.

**Safari (iPhone)**
1. Copia el código desde la app (🎟️ Apuestas → Instalar el botón).
2. En Safari, abre cualquier página y añádela a marcadores (compartir →
   *Añadir marcador*) con el nombre `Modus value`.
3. *Marcadores* → *Editar* → toca `Modus value` → borra la dirección y pega el
   código → *OK*.
4. Uso: con el partido abierto en Winamax, toca la barra de direcciones,
   escribe `Modus value` y elige el marcador (o ábrelo desde *Marcadores*).

Si Winamax cambia su página o no encuentra las cuotas, el botón lo dice
(«no encuentro las cuotas…») y no envía nada. No hace falta recargar: lee las
cuotas que se ven en pantalla (siempre al día) y, si la página se cargó en ese
mismo partido, completa con ella los mercados que no se ven. Winamax solo
pinta los mercados cercanos a la pantalla: si llegaste navegando y falta
alguno, desplázate hasta verlo y vuelve a pulsar.

**Prueba con una página guardada:** guarda la página de un partido con
`Ctrl+S` (*Página web, completa*) como `tests\fixtures\winamax_partido.html` y
lanza `python -m pytest tests\test_boton.py`. Necesita Node con Playwright
(`npm i -g playwright` y `npx playwright install chromium`); si no los tienes,
pásame el archivo.

## Reglas

| Regla | Valor |
|---|---|
| Volatilidad | la del jugador más irregular de los dos. Hasta 12 (baja o media): edge mínimo 20 %. Por encima de 12 (alta): +2 puntos de edge por cada punto (13 → 22 %, 15 → 26 %, 17 → 30 %) y el importe baja un escalón (15 → 10 €, 10 → 5 €). Más de 18 o sin dato → se descarta y se anota en `vigia_log` (en los **avisos del vigía**; para **apuntar en la app** la volatilidad no cuenta: siempre 20 % e importe normal, solo se muestra como información) |
| Value | edge = p × cuota − 1 ≥ el mínimo exigido (20 %, o más con volatilidad alta) |
| 🟢 | p − 1/cuota ≥ margen del mercado (`MARGEN_POR_MERCADO` de `config.py`: ganador 6, total de legs 8, hándicaps y 180s 5). Resultado exacto nunca 🟢 |
| Importe | edge 20–35 % → 5 €; 35–50 % → 10 €; más del 50 % → 15 €. Más de 5 € solo si 🟢 y cuota ≤ 4,00 |
| Por partido | sin límite: puedes apostar a varias selecciones del mismo partido si lo consideras |
| Tope | 50 € por jornada más tu beneficio real acumulado (las apuestas marcadas «apostada» ya liquidadas; si vas en pérdidas, 50 €). El importe recomendado se recorta en múltiplos de 5 € a lo que quede; una «no apostada» devuelve su importe |
| Importe a mano | en Value Bets eliges el importe antes de pulsar «Apostar» (por defecto, el recomendado), y en 🎟️ Apuestas lo puedes cambiar después con ✏️ Importe. Se guarda en la columna `importe_real` de `alertas` y solo cuenta para **tus apuestas** (tope, «Las que apostaste», beneficio real); las estadísticas del modelo («Si las hubieras hecho todas», seguimiento por mercado, Winamax frente al modelo) siguen con el recomendado (`importe`) |

**Cuotas mínimas** (pestaña `cuotas_minimas`): cuota justa = 1/p; para avisar
(edge 20 %, o el exigido por volatilidad alta: columna `edge_exigido`) = 1,20/p;
para 10 € = 1,35/p; para 15 € = 1,50/p; para 🟢 = 1/(p − margen). Siempre se
redondean **hacia arriba** (con p = 0,742, la de avisar es 1,62).

**Cuándo avisa el vigía:** los partidos no tienen hora fija (empiezan uno tras
otro) y Winamax publica sus mercados poco antes. Por eso avisa de cada partido
cuando pasa a ser el siguiente: en cuanto la hoja marca como terminado el
anterior de su jornada («🎯 Siguiente: …»). El primero de cada jornada, y
cualquiera que traiga hora en el calendario, se avisa `AVISO_MIN_ANTES`
minutos antes (10 por defecto; «🎯 14:00 …»). Un solo aviso por partido,
aunque se retrase. El estado se lee cada minuto por la API de Google con la
cuenta de servicio (el CSV publicado va con minutos de retraso) y solo dentro
de las ventanas de jornada; si la API fallara, usa el CSV y lo anota en el log.

**Seguimiento por mercado** (🎟️ Apuestas → Histórico): cada mercado por
separado, **sin volatilidad** (todas las apuestas con value y las que hiciste)
y **con volatilidad** (aplicando la regla del vigía y por nivel de volatilidad
del partido), para ver en qué mercados y con qué volatilidad gana el modelo.

**Eliminar una apuesta a mano** (🎟️ Apuestas): cada apuesta de hoy tiene, junto a
«Apostada» y «No apostada», un botón 🗑️ que pide confirmación; las anteriores
se borran desde el desplegable «Todas las apuestas anteriores» → «Eliminar una
apuesta anterior». Se borra la fila de la pestaña `alertas` (antes comprueba que
sigue siendo la misma) y deja de contar en el tope y en el seguimiento.

**Cuotas de Winamax guardadas** (pestaña `cuotas_winamax`): cada vez que pulsas
«Modus value» en la app con tu usuario admin, se guardan **todas** las cuotas
leídas (una vez por lectura), con la probabilidad del modelo, la cuota justa,
el edge, 🟢 y el importe que tocaría. Las salidas que la app no sabe asignar
también se guardan, sin probabilidad. El vigía rellena la columna `resultado`
(ganada/perdida) cuando liquida. En 🎟️ Apuestas → **Winamax frente al modelo**:

- **Por edge:** qué habrías ganado apostando 1 € a todas las cuotas leídas,
  por tramos de edge (para ver desde qué edge gana de verdad el modelo).
- **Modelo vs Winamax:** quién acierta más (Brier: más bajo, mejor) con la
  probabilidad del modelo frente a la de Winamax sin su margen, por mercado.
- **Margen de Winamax:** cuánto se queda la casa en cada mercado
  (suma de 1/cuota − 1).

**¿Están los datos del partido anterior?** Al abrir un partido con el botón
«Modus value», la app comprueba en la hoja de la jornada en juego, para cada
jugador, que sus partidos anteriores de hoy ya aparecen terminados y que sus
estadísticas de hoy (victorias + derrotas) los cuentan todos. Si falta alguno,
sale un aviso en rojo en «Cuotas de Winamax» (y otro en «Apuestas con valor»)
diciendo qué partido falta: pulsa «Ejecutar actualización», espera y
«Refrescar datos» antes de apostar. Si está todo, dice con qué partido anterior
de cada uno calcula («✅ Datos al día»). Fuera de jornada no se comprueba (se
usa el Resumen Semanal).

**Versión del botón.** El marcador guarda una copia del código y no se
actualiza solo. Cada vez que el botón cambia sube su versión (ahora la 2) y,
si pulsas uno antiguo, la app te avisa de que lo reinstales (🎟️ Apuestas →
«Instalar el botón Modus value»: copia el código y pégalo como URL del
marcador). Desde la versión 2, si llegas al partido navegando dentro de
Winamax (sin recargar), el botón solo usa las cuotas que se ven en pantalla:
las del estado de carga serían de la página anterior. Si la página lleva más
de 10 minutos abierta y algún mercado no se veía, la app avisa de que esas
cuotas pueden haber cambiado.

**Por número de partido de la jornada** (🎟️ Apuestas): cada apuesta y cada
cuota guardada con el botón llevan el número de partido de la jornada (1.º a
15.º; columnas `jornada` y `n_partido`). La tabla «🔢 Por número de partido»
compara, por tramos (1.º-3.º, 4.º-6.º…), lo que daba el modelo con el acierto
real, y el beneficio; en «Winamax frente al modelo» → «Por nº de partido», el
Brier del modelo y de Winamax. Sirve para ver si el modelo es más fiable
cuando los jugadores llevan más partidos ese día. Las filas de esta semana que
no lo tenían se rellenan solas al apuntar los resultados.
