from vigia.mercados import asignar, tipo_mercado

N = ("Baetens, Andy", "Menzies, Cameron")


def test_tipos():
    assert tipo_mercado("Ganador del partido") == "ganador"
    assert tipo_mercado("Hándicap de legs") == "handicap"
    assert tipo_mercado("Total de legs") == "total_legs"
    assert tipo_mercado("Resultado exacto") == "resultado"
    assert tipo_mercado("Total de 180") == "180"
    assert tipo_mercado("Ganador del leg 1") is None
    assert tipo_mercado("Checkout más alto") is None
    # En Modus el partido es un solo set
    assert tipo_mercado("1er set - Hándicap de legs") == "handicap"
    assert tipo_mercado("1er set - Marcador exacto (en legs)") == "resultado"
    assert tipo_mercado("1er set - 1er leg - D. Coulson anota un 180") is None
    assert tipo_mercado("1er set - Total de legs - Par/Impar") is None


def test_ganador_respeta_el_orden_del_cartel():
    sel, _ = asignar("Ganador del partido", "Baetens, Andy", "1", N, invertido=False)
    assert sel == {"tipo": "ganador", "jugador": 1}
    sel, _ = asignar("Ganador del partido", "Baetens, Andy", "1", N, invertido=True)
    assert sel == {"tipo": "ganador", "jugador": 2}


def test_handicap_total_resultado_180():
    assert asignar("Hándicap de legs", "Menzies (-1,5)", "2", N, False)[0] == \
        {"tipo": "handicap", "jugador": 2, "linea": -1.5}
    assert asignar("Hándicap de legs", "Baetens +2.5", "1", N, True)[0] == \
        {"tipo": "handicap", "jugador": 2, "linea": 2.5}
    assert asignar("Hándicap de legs", "Baetens -1", "1", N, False) is None  # sin .5
    assert asignar("Total de legs", "Más de 5,5", "", N, False)[0] == \
        {"tipo": "total_legs", "lado": "mas", "linea": 5.5}
    assert asignar("Resultado exacto", "4-1", "", N, False)[0] == \
        {"tipo": "resultado", "legs1": 4, "legs2": 1}
    assert asignar("Resultado exacto", "4-1", "", N, True)[0] == \
        {"tipo": "resultado", "legs1": 1, "legs2": 4}
    assert asignar("Total de 180", "Más de 1,5", "", N, False)[0] == \
        {"tipo": "180_total", "lado": "mas", "linea": 1.5}
    assert asignar("180s de Baetens", "Menos de 0,5", "", N, False)[0] == \
        {"tipo": "180_jugador", "jugador": 1, "lado": "menos", "linea": 0.5}
    assert asignar("¿Quién hará más 180?", "Empate", "X", N, False)[0] == \
        {"tipo": "mas_180", "quien": 0}
    assert asignar("¿Quién hará más 180?", "Menzies, Cameron", "2", N, False)[0] == \
        {"tipo": "mas_180", "quien": 2}


def test_pagina_real_de_winamax():
    """Partido real (Coulson - Baetens, 28/10/2026): 25 de las 30 salidas
    se asignan; las 5 restantes (1a leg, primer jugador en hacer 180) no
    las cubre el modelo."""
    import json
    from pathlib import Path
    from vigia.mercados import asignar
    html = (Path(__file__).parent / "fixtures" / "winamax_partido_modus.html").read_text(encoding="utf-8")
    i = html.find("PRELOADED_STATE")
    st, _ = json.JSONDecoder().raw_decode(html[html.find("{", i):])
    m = st["matches"]["75997616"]
    nombres = (m["competitor1Name"], m["competitor2Name"])
    asignadas, sin = {}, []
    for bid in m["bets"]:
        b = st["bets"][str(bid)]
        for oid in b["outcomes"]:
            o = st["outcomes"][str(oid)]
            r = asignar(b["betTitle"], o["label"], o["code"], nombres, False)
            if r:
                asignadas[json.dumps(r[0], sort_keys=True)] = st["odds"][str(oid)]
            else:
                sin.append(b["betTitle"])
    assert len(asignadas) == 25
    assert set(sin) == {"1er Set - 1ª leg - Ganador", "1er Jugador anota un 180"}
    k = lambda **d: json.dumps(d, sort_keys=True)  # noqa: E731
    assert asignadas[k(tipo="ganador", jugador=1)] == 1.48
    assert asignadas[k(tipo="total_legs", lado="menos", linea=5.5)] == 2.05
    assert asignadas[k(tipo="handicap", jugador=1, linea=-1.5)] == 1.94
    assert asignadas[k(tipo="resultado", legs1=4, legs2=1)] == 3.9
    assert asignadas[k(tipo="mas_180", quien=0)] == 3.3
    assert asignadas[k(tipo="hcap_180", jugador=1, linea=0.5)] == 1.48
    assert asignadas[k(tipo="180_jugador", jugador=2, lado="mas", linea=1.5)] == 2.1
    assert asignadas[k(tipo="180_total", lado="menos", linea=2.5)] == 1.88
