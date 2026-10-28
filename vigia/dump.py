"""
vigia/dump.py - `python -m vigia --dump [MATCH_ID]` para revisar a mano
que se lee de Winamax y que probabilidad asigna el modelo a cada salida.
"""

from datetime import datetime

from vigia.ajustes import RAIZ


def dump(match_id, aj, guardar_fixture=False):
    from modelo.motor import calcular_partido, probabilidad
    from vigia import reglas
    from vigia.mercados import asignar, texto_seleccion, tipo_mercado
    from vigia.nombres import emparejar
    from vigia.nucleo import MADRID, DatosSheet, Vigia, ahora_madrid
    from vigia.hoja import HojaMemoria
    from vigia.notificador import Consola
    from vigia.winamax import ClienteWinamax, extraer_estado, mercados, partidos

    cli = ClienteWinamax()
    if not match_id:
        estado = cli.estado_dardos()
        if guardar_fixture:
            _guardar("winamax_dardos.html", cli._get(
                "https://www.winamax.es/apuestas-deportivas/sports/22"))
        print(f"{'id':>10}  {'estado':10} {'inicio':16}  partido  [torneo]")
        for p in sorted(partidos(estado), key=lambda x: x["inicio"]):
            ini = datetime.fromtimestamp(p["inicio"], MADRID).strftime("%d/%m %H:%M") if p["inicio"] else "-"
            print(f"{p['id']:>10}  {p['status']:10} {ini:16}  {p['c1']} vs {p['c2']}  [{p['torneo']}]"
                  f"{'  (outright)' if p['outright'] else ''}")
        print("\nTorneos de Modus segun WINAMAX_TORNEO =", aj.torneo_palabras)
        return 0

    html = cli.html_partido(match_id)
    if guardar_fixture:
        _guardar(f"winamax_partido_{match_id}.html", html)
    estado = extraer_estado(html)
    p = next((x for x in partidos(estado) if x["id"] == str(match_id)), None)
    if not p:
        print("Partido no encontrado en la pagina")
        return 1
    print(f"{p['c1']} vs {p['c2']}  [{p['torneo']}]  {p['status']}")

    datos = DatosSheet()
    datos.refrescar(ahora_madrid(), forzar=True)
    db = {v["nombre_original"]: v for v in datos.jugadores.values()}
    n1, n2 = emparejar(p["c1"], list(db)), emparejar(p["c2"], list(db))
    print(f"En la hoja: {p['c1']} -> {n1}   {p['c2']} -> {n2}")
    calc = invertido = None
    if n1 and n2:
        v = Vigia(None, HojaMemoria(), Consola(), datos, aj)
        invertido, jornada = v.orden_cartel(n1, n2)
        if invertido is None:
            invertido = False
            print("J1 = primero de Winamax (no esta en el calendario)")
        else:
            print(f"J1 segun cartel de {jornada}: {'invertido' if invertido else 'mismo orden'}")
        j1, j2 = (n2, n1) if invertido else (n1, n2)
        d1, d2 = db[j1], db[j2]
        ok, motivo = reglas.partido_elegible(d1.get("volatilidad"), d2.get("volatilidad"))
        print(f"J1 {j1}: PG {d1['PR']:.1f} vol {d1.get('volatilidad')}  |  "
              f"J2 {j2}: PG {d2['PR']:.1f} vol {d2.get('volatilidad')}  ->  "
              f"{'se evalua' if ok else 'DESCARTADO: ' + motivo}")
        calc = calcular_partido(d1, d2, True)
        print(f"P(J1) {calc['p1']*100:.1f} %  P(J2) {calc['p2']*100:.1f} %")

    for m in mercados(estado, match_id):
        print(f"\n## {m['titulo']}  ({m['tipo']}) -> {tipo_mercado(m['titulo'])}"
              f"{'' if m['disponible'] else '  [NO DISPONIBLE]'}")
        for o in m["salidas"]:
            linea = f"   {o['label']:<32} code={o['code']:<4} @{o['cuota']}"
            if calc is not None and o["cuota"]:
                r = asignar(m["titulo"], o["label"], o["code"], (p["c1"], p["c2"]), invertido)
                if r:
                    sel, nombre = r
                    prob = probabilidad(calc, sel)
                    ev = reglas.evaluar(reglas.MERCADO_DE_TIPO[sel["tipo"]], prob, o["cuota"])
                    linea += (f"  => {texto_seleccion(sel, j1, j2)}: p {prob*100:.1f} % "
                              f"edge {ev['edge']*100:+.1f} % margen {ev['margen']*100:+.1f} "
                              f"{'🟢' if ev['verde'] else ''}"
                              f"{' REVISAR' if ev['revisar'] else ''}"
                              f"{' · ' + str(ev['importe']) + ' €' if ev['importe'] else ''}")
                else:
                    linea += "  => (sin asignar)"
            print(linea)
    return 0


def _guardar(nombre, html):
    carpeta = RAIZ / "tests" / "fixtures"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / nombre).write_text(html, encoding="utf-8")
    print(f"Guardado {carpeta / nombre}")
