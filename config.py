"""
config.py - Constantes y configuracion global de Modus Super Series App.

Contiene URLs de las hojas de calculo, rangos de corte para parsear cada
pestana, paleta de colores de jugadores y constantes del modelo matematico.
No importa nada del resto de la app: es la capa mas baja.
"""

URLS = {
    "Grupo A Lunes": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRpzkL3TKUdIptc202-w-A0ifJtiFIIP9rI0q0zQzn_I4VKX8qUi_-r1XXfPkwefN03rIQzYUNyg9xP/pub?gid=770660826&single=true&output=csv",
    "Grupo A Martes": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRpzkL3TKUdIptc202-w-A0ifJtiFIIP9rI0q0zQzn_I4VKX8qUi_-r1XXfPkwefN03rIQzYUNyg9xP/pub?gid=1188400317&single=true&output=csv",
    "Grupo A Miércoles": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRpzkL3TKUdIptc202-w-A0ifJtiFIIP9rI0q0zQzn_I4VKX8qUi_-r1XXfPkwefN03rIQzYUNyg9xP/pub?gid=611921899&single=true&output=csv",
    "Grupo C Jueves": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRpzkL3TKUdIptc202-w-A0ifJtiFIIP9rI0q0zQzn_I4VKX8qUi_-r1XXfPkwefN03rIQzYUNyg9xP/pub?gid=1451632905&single=true&output=csv",
    "Grupo B Jueves": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRpzkL3TKUdIptc202-w-A0ifJtiFIIP9rI0q0zQzn_I4VKX8qUi_-r1XXfPkwefN03rIQzYUNyg9xP/pub?gid=838707746&single=true&output=csv",
    "Grupo C Viernes": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRpzkL3TKUdIptc202-w-A0ifJtiFIIP9rI0q0zQzn_I4VKX8qUi_-r1XXfPkwefN03rIQzYUNyg9xP/pub?gid=951305991&single=true&output=csv",
    "Grupo B Viernes": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRpzkL3TKUdIptc202-w-A0ifJtiFIIP9rI0q0zQzn_I4VKX8qUi_-r1XXfPkwefN03rIQzYUNyg9xP/pub?gid=895443076&single=true&output=csv",
    "Final Sábado": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRpzkL3TKUdIptc202-w-A0ifJtiFIIP9rI0q0zQzn_I4VKX8qUi_-r1XXfPkwefN03rIQzYUNyg9xP/pub?gid=843639863&single=true&output=csv",
    "Resumen Semanal": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRpzkL3TKUdIptc202-w-A0ifJtiFIIP9rI0q0zQzn_I4VKX8qUi_-r1XXfPkwefN03rIQzYUNyg9xP/pub?gid=701394558&single=true&output=csv",
    "Value Bets": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRpzkL3TKUdIptc202-w-A0ifJtiFIIP9rI0q0zQzn_I4VKX8qUi_-r1XXfPkwefN03rIQzYUNyg9xP/pub?gid=2019911134&single=true&output=csv"
}

CORTES = {
    "Resumen Semanal": {"filas": (5, 20), "cols": (1, 10), "der_nombres": 5, "der_cols": (1, 10)},
    "Grupo A Lunes":      {"izq_filas": (5, 36), "izq_cols": (0, 5), "der_nombres": 5,  "der_cols": (6, 12)},
    "Grupo A Martes":     {"izq_filas": (5, 36), "izq_cols": (0, 5), "der_nombres": 5,  "der_cols": (6, 12)},
    "Grupo A Miércoles":  {"izq_filas": (5, 36), "izq_cols": (0, 5), "der_nombres": 5,  "der_cols": (6, 12)},
    "Grupo C Jueves":     {"izq_filas": (5, 36), "izq_cols": (0, 5), "der_nombres": 5,  "der_cols": (6, 12)},
    "Grupo B Jueves":     {"izq_filas": (5, 26), "izq_cols": (0, 5), "der_nombres": 5,  "der_cols": (6, 12)},
    "Grupo C Viernes":    {"izq_filas": (5, 36), "izq_cols": (0, 5), "der_nombres": 5,  "der_cols": (6, 12)},
    "Grupo B Viernes":    {"izq_filas": (5, 26), "izq_cols": (0, 5), "der_nombres": 5,  "der_cols": (6, 12)},
    "Final Sábado":       {"izq_filas": (5, 24), "izq_cols": (0, 5), "der_nombres": 6,  "der_cols": (6, 12)},
    "Value Bets":         {"unica_filas": (6, 28), "unica_cols": (0, 10)}
}

PESTANAS_CON_STATS = [k for k in URLS if k not in ("Value Bets",)]

BANDERAS = {
    "GB": "🇬🇧", "NL": "🇳🇱", "BE": "🇧🇪", "PT": "🇵🇹", "AU": "🇦🇺",
    "DE": "🇩🇪", "PL": "🇵🇱", "IE": "🇮🇪", "CA": "🇨🇦",
    "SE": "🇸🇪", "DK": "🇩🇰", "FR": "🇫🇷", "ES": "🇪🇸", "HR": "🇭🇷",
}

JUGADORES_PAISES = {
    # Reino Unido
    "luke littler": "GB", "gary anderson": "GB", "peter wright": "GB", "gerwyn price": "GB",
    "jonny clayton": "GB", "james wade": "GB", "dave chisnall": "GB", "rob cross": "GB",
    "nathan aspinall": "GB", "chris dobey": "GB", "josh rock": "GB", "luke humphries": "GB",
    "michael smith": "GB", "ross smith": "GB", "stephen bunting": "GB", "andrew gilding": "GB",
    "brendan dolan": "GB", "ritchie edhouse": "GB", "ryan searle": "GB", "callan rydz": "GB",
    "joe cullen": "GB", "cameron menzies": "GB", "connor scutt": "GB", "glenn de bois": "GB",
    "nick kenny": "GB", "nathan rafferty": "GB", "steve west": "GB", "neil duff": "GB",
    "lewis williams": "GB", "scott waites": "GB", "kristjan karer": "GB",
    "kyle anderson": "GB", "martin adams": "GB", "john lowe": "GB", "barry hearn": "GB",
    "mervyn king": "GB",
    
    # Países Bajos
    "michael van gerwen": "NL", "danny noppert": "NL", "wessel nijman": "NL", "dirk van duijvenbode": "NL",
    "kevin doets": "NL", "jelle klaasen": "NL", "maik kuivenhoven": "NL", "benito van de pas": "NL",
    "michiel kiemeneij": "NL",
    
    # Bélgica
    "dimitri van den bergh": "BE", "kim huybrechts": "BE", "alexis toylo": "BE",
    
    # Portugal
    "jose de sousa": "PT", "noa lynn": "PT", "paulo costa": "PT",
    
    # Australia
    "damon heta": "AU",
    
    # Alemania
    "martin schindler": "DE", "gabriel clemens": "DE", "ricardo pietreczko": "DE", 
    "florian hempel": "DE", "max hopp": "DE",
    
    # Polonia
    "krzysztof ratajski": "PL", "przemyslaw cecot": "PL",
    
    # Irlanda
    "keane barry": "IE", "william o'connor": "IE", "ciaran teeters": "IE", "dylan slevin": "IE",
    "paddy power": "IE",
    
    # Canadá
    "matt campbell": "CA",
    
    # Suecia
    "rikard karlsson": "SE",
    
    # Dinamarca
    "anders hertz": "DK",
    
    # Croacia
    "boris krcmar": "HR",
    
    # España
    "carlos garcia": "ES",
}

# Colores vibrantes pero suaves, todos con suficiente contraste con texto oscuro.
# La asignación es secuencial por orden de aparición y se guarda en
# st.session_state para que un jugador conserve su color durante la sesión.
PALETA_JUGADORES = [
    "#fbbf24",  # ámbar
    "#fb923c",  # naranja
    "#f87171",  # rojo coral
    "#e879f9",  # fucsia
    "#a78bfa",  # violeta
    "#818cf8",  # índigo
    "#60a5fa",  # azul
    "#22d3ee",  # cian
    "#2dd4bf",  # turquesa
    "#34d399",  # esmeralda
    "#a3e635",  # lima
    "#facc15",  # amarillo
    "#fb7185",  # rosa
    "#c084fc",  # púrpura
    "#38bdf8",  # cielo
    "#4ade80",  # verde
    "#f472b6",  # rosa fuerte
    "#fcd34d",  # mostaza
]

# Cambiar estos valores recalibra TODO el modelo de victoria, hándicaps y legs.

ELO_S = 90.0     # Sensibilidad: a menor S, el favorito tiene más peso
ELO_B = 10.0      # Bonus de saque (Throw First Advantage), en puntos de PG

# Referencia para escalar lambda de 180s. Si E[legs] del partido > 5.7,
# se esperan más 180s; si E[legs] < 5.7, menos. Calibrado a partidos equilibrados.
LEGS_PROMEDIO_REFERENCIA = 5.7

# Muestra pequeña: con menos de estos partidos, el PR y la media de 180s de
# un jugador se acercan a la media del torneo en proporcion a lo que ha
# jugado (1 partido = 1/6 de su dato y 5/6 de la media). A partir de este
# numero se usan sus datos tal cual. 0 desactiva el ajuste.
MUESTRA_MIN_PARTIDOS = 6

GRUPOS_DIAS = {
    "Grupo A": ["Grupo A Lunes", "Grupo A Martes", "Grupo A Miércoles"],
    "Grupo B": ["Grupo B Jueves", "Grupo B Viernes"],
    "Grupo C": ["Grupo C Jueves", "Grupo C Viernes"],
}

# 'verdes' = nº de filas desde arriba que se pintan en verde (clasifican / mejor posición)
# 'rojos'  = nº de filas desde abajo que se pintan en rojo (eliminados / peor posición)
# En Grupo A solo se pinta el líder, sin rojos. Grupo B: 3 arriba, 2 abajo. Grupo C: 2 y 4.
COLORES_CLASIFICACION = {
    "Grupo A": {"verdes": 1, "rojos": 0},
    "Grupo B": {"verdes": 3, "rojos": 2},
    "Grupo C": {"verdes": 2, "rojos": 4},
}


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE SHEET DE ESCRITURA (tracking de predicciones)
# ─────────────────────────────────────────────────────────────────────────────
# Las URLs de URLS son de tipo "publicado" (/d/e/2PACX-...): sirven para LEER
# datos en CSV, pero gspread NO puede escribir con ellas.
# Para el tracking de predicciones, gspread necesita la URL NORMAL del Sheet,
# la que contiene el ID real del documento. Es el mismo Google Sheet, solo
# que referenciado por su ID en lugar de por la URL de publicacion.
SHEET_ID_PREDICCIONES = "1OwbnxDnFrRKrZqZszPz8QvJsZLFegDI_yPde4j-yN2Q"
SHEET_URL_PREDICCIONES = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID_PREDICCIONES}/edit"
)
