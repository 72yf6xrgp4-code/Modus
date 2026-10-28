"""
vigia/nombres.py - Normalizacion y emparejamiento de nombres de jugadores.

Winamax puede dar los nombres como 'Apellido, Nombre'; la hoja los da como
'Nombre Apellido'. Se emparejan sin tildes ni mayusculas y, si hace falta,
por apellido (solo si no hay ambiguedad).
"""

from modelo.util import normalizar_nombre


def nombre_winamax(nombre):
    """'Baetens, Andy' -> 'Andy Baetens'. Sin coma, lo deja igual."""
    nombre = " ".join(str(nombre or "").split())
    if nombre.count(",") == 1:
        apellido, nom = [p.strip() for p in nombre.split(",")]
        if apellido and nom:
            return f"{nom} {apellido}"
    return nombre


def emparejar(nombre, candidatos):
    """Devuelve el candidato (tal cual viene) que corresponde a `nombre`, o
    None si no hay ninguno o hay ambiguedad. Estrategia, de mas a menos
    estricta:
      1) igual tras normalizar,
      2) mismas palabras en distinto orden,
      3) uno contiene al otro (palabras completas),
      4) mismo apellido (ultima palabra) y, si hay inicial, que coincida.
    """
    n = normalizar_nombre(nombre_winamax(nombre))
    if not n:
        return None
    cands = [(normalizar_nombre(c), c) for c in candidatos]

    exactos = [c for cn, c in cands if cn == n]
    if len(exactos) == 1:
        return exactos[0]

    pal = set(n.split())
    mismas = [c for cn, c in cands if set(cn.split()) == pal]
    if len(mismas) == 1:
        return mismas[0]

    contenidos = [c for cn, c in cands
                  if cn and (pal <= set(cn.split()) or set(cn.split()) <= pal)]
    if len(contenidos) == 1:
        return contenidos[0]
    if len(contenidos) > 1:
        return None

    palabras = n.split()
    apellido = palabras[-1]
    inicial = palabras[0][0] if len(palabras) > 1 else None
    por_apellido = []
    for cn, c in cands:
        pc = cn.split()
        if not pc or pc[-1] != apellido:
            continue
        if inicial and len(pc) > 1 and pc[0][0] != inicial:
            continue
        por_apellido.append(c)
    if len(por_apellido) == 1:
        return por_apellido[0]
    return None


def mismo_jugador(a, b):
    """True si los dos nombres corresponden al mismo jugador."""
    return emparejar(a, [b]) is not None
