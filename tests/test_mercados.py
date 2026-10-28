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
