"""Integracion con HTML real de Winamax guardado en tests/fixtures.

Para crearlo, el primer dia de Modus con mercados publicados:
    python -m vigia --dump                         (busca el matchId)
    python -m vigia --dump <matchId> --guardar-fixture
Hasta entonces este test se salta.
"""

from pathlib import Path

import pytest

from vigia.mercados import asignar
from vigia.winamax import extraer_estado, mercados, partidos

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("winamax_partido_*.html"))


@pytest.mark.skipif(not FIXTURES, reason="falta un HTML real de Winamax en tests/fixtures")
@pytest.mark.parametrize("ruta", FIXTURES, ids=[f.name for f in FIXTURES])
def test_fixture_real(ruta):
    estado = extraer_estado(ruta.read_text(encoding="utf-8"))
    match_id = ruta.stem.rsplit("_", 1)[-1]
    p = next(x for x in partidos(estado) if x["id"] == match_id)
    assert p["c1"] and p["c2"] and p["inicio"] > 0
    ms = mercados(estado, match_id)
    assert ms, "el partido no trae mercados"
    asignadas = [asignar(m["titulo"], o["label"], o["code"], (p["c1"], p["c2"]), False)
                 for m in ms for o in m["salidas"]]
    tipos = {a[0]["tipo"] for a in asignadas if a}
    assert "ganador" in tipos, "no se reconoce el mercado de ganador"
