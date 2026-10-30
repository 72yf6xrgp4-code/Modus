"""
vigia/aviso.py - Texto del aviso al movil con las cuotas reales de Winamax
(vigia con OddsPapi). Sin red.

    Título:  💰 Davies – van de Pas · 17:30
    Mensaje: ✅ Gana Davies → 10 €
             cuota 2,10 · aguanta hasta 1,95 · edge +22 % 🟢
             ✅ Más de 5,5 legs → 5 €
             cuota 1,90 · aguanta hasta 1,84 · edge +21 %

'aguanta hasta' = la cuota mas baja con la que sigue habiendo value
(el edge exigido): si en Winamax ya esta por debajo, no la hagas.
"""

from vigia import reglas
from vigia.registro import motivo_poco_fiable

MAX_APUESTAS = 4


def nombre_corto(nombre):
    """'Benito van de Pas' -> 'van de Pas'; 'Self' -> 'Self'."""
    partes = str(nombre or "").split()
    return " ".join(partes[1:]) if len(partes) > 1 else (partes[0] if partes else "")


def _num(v):
    return f"{v:.2f}".replace(".", ",")


def _eur(v):
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " €"


def repartir_tope(importes, queda):
    """Recorta los importes (en orden) a lo que queda del tope del dia, en
    multiplos de 5 EUR. Devuelve la lista recortada."""
    salida = []
    for imp in importes:
        cabe = max(0.0, (queda // reglas.UNIDAD) * reglas.UNIDAD)
        salida.append(min(imp, cabe))
        queda -= salida[-1]
    return salida


def componer(j1, j2, apuestas, edge_min, hora, queda=None, vol=None, rebaja=False,
             info=None):
    """(titulo, mensaje) del aviso.

    apuestas: [{texto, cuota, p, ev}] ordenadas por edge (las de importe > 0).
    hora: 'HH:MM' prevista (o '', va en el titulo). queda: lo que queda del
    tope de hoy (None = sin tope): los importes se recortan a eso. info:
    {previos_j1, ...} para avisar si es poco fiable.
    """
    titulo = f"💰 {nombre_corto(j1)} – {nombre_corto(j2)}" + (f" · {hora}" if hora else "")
    importes = [a["ev"]["importe"] for a in apuestas[:MAX_APUESTAS]]
    if queda is not None:
        importes = repartir_tope(importes, queda)
    lineas = []
    for a, imp in zip(apuestas[:MAX_APUESTAS], importes):
        minima = reglas.cuota_minima(a["p"], edge_min)
        lineas.append(f"✅ {a['texto']} → {_eur(imp) if imp > 0 else '0 € (tope)'}")
        lineas.append(f"cuota {_num(a['cuota'])} · aguanta hasta {_num(minima)} · "
                      f"edge {a['ev']['edge'] * 100:+.0f} %" + (" 🟢" if a["ev"]["verde"] else ""))
    if len(apuestas) > MAX_APUESTAS:
        lineas.append(f"(+{len(apuestas) - MAX_APUESTAS} más en la app)")
    if rebaja and vol is not None:
        lineas.append(f"⚠️ Volatilidad alta ({vol:.1f}): edge exigido "
                      f"{edge_min * 100:.0f} %".replace(".", ","))
    if info:
        from vigia.registro import fiable
        if not fiable(info):
            motivo = motivo_poco_fiable(dict(info, j1=j1, j2=j2))
            lineas.append("⚠️ " + motivo[:1].upper() + motivo[1:])
    return titulo, "\n".join(lineas)
