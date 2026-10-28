from vigia.frescura import partido_anterior


def _p(orden, j1, j2, legs1=0, legs2=0, estado=None):
    if estado is None:
        estado = "terminado" if max(legs1, legs2) >= 4 else "pendiente"
    return {"orden": orden, "j1": j1, "j2": j2, "legs1": legs1, "legs2": legs2,
            "estado": estado}


JORNADA = [
    _p(0, "Derek Coulson", "David Davies", 4, 2),
    _p(1, "Archie Self", "Andy Baetens", 1, 4),
    _p(2, "Danny Ayres", "Darren Beveridge", 4, 3),
    _p(3, "Derek Coulson", "Andy Baetens"),            # el del boton
    _p(4, "Archie Self", "Danny Ayres"),
]


def _stats(**n):
    return {k.lower(): {"nombre_original": k, "n_partidos": v} for k, v in n.items()}


def test_datos_al_dia():
    res = partido_anterior(JORNADA, "Derek Coulson", "Andy Baetens",
                           _stats(**{"Derek Coulson": 1, "Andy Baetens": 1}))
    assert all(r["ok"] for r in res)
    assert "contra David Davies (4-2)" in res[0]["texto"]
    assert "contra Archie Self (4-1)" in res[1]["texto"]   # marcador desde su lado


def test_faltan_en_las_estadisticas():
    res = partido_anterior(JORNADA, "Derek Coulson", "Andy Baetens",
                           _stats(**{"Derek Coulson": 1}))   # Baetens aun sin stats
    assert res[0]["ok"] and not res[1]["ok"]
    assert "cuentan 0 de sus 1" in res[1]["texto"] and "Archie Self" in res[1]["texto"]


def test_partido_anterior_sin_terminar_en_la_hoja():
    jornada = [dict(p) for p in JORNADA]
    jornada[1] = _p(1, "Archie Self", "Andy Baetens", 1, 3, estado="en_juego")
    res = partido_anterior(jornada, "Derek Coulson", "Andy Baetens",
                           _stats(**{"Derek Coulson": 1, "Andy Baetens": 0}))
    assert not res[1]["ok"] and "en juego" in res[1]["texto"]


def test_primer_partido_y_nombres_de_winamax():
    # 'A. Baetens' / 'D. Coulson' como los escribe Winamax
    res = partido_anterior(JORNADA[1:], "Archie Self", "Danny Ayres",
                           _stats(**{"Archie Self": 1, "Danny Ayres": 1}))
    assert all(r["ok"] for r in res)
    res = partido_anterior([JORNADA[3]], "D. Coulson", "A. Baetens", {})
    assert [r["texto"] for r in res] == ["es su primer partido de hoy"] * 2
