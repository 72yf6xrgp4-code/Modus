"""Estado de Winamax sintetico (misma forma que PRELOADED_STATE) para los
tests. Las etiquetas imitan las de winamax.es; se cambiaran por las reales
cuando haya un fixture de un partido de Modus."""

import json


def estado(match_id="900", c1="Baetens, Andy", c2="Menzies, Cameron",
           inicio=2_000_000_000, torneo="Modus Super Series",
           mercados_partido=None, status="PREMATCH"):
    """mercados_partido: [(titulo, [(label, code, cuota), ...]), ...]"""
    mercados_partido = mercados_partido or []
    bets, outcomes, odds, bet_ids = {}, {}, {}, []
    oid = 1
    for b, (titulo, salidas) in enumerate(mercados_partido, start=1):
        bid = f"{match_id}{b:03d}"
        ids = []
        for label, code, cuota in salidas:
            k = str(int(bid) * 100 + oid)
            outcomes[k] = {"label": label, "code": code}
            odds[k] = cuota
            ids.append(k)
            oid += 1
        bets[bid] = {"betTitle": titulo, "betTypeName": titulo,
                     "outcomes": ids, "available": True}
        bet_ids.append(bid)
    return {
        "sports": {"22": {"sportName": "Dardos"}},
        "tournaments": {"77": {"tournamentName": torneo}},
        "matches": {match_id: {
            "matchId": int(match_id), "competitor1Name": c1,
            "competitor2Name": c2, "status": status, "matchStart": inicio,
            "isOutright": False, "tournamentId": 77, "sportId": 22,
            "bets": bet_ids,
        }},
        "bets": bets, "outcomes": outcomes, "odds": odds,
    }


def html(est):
    return ("<html><head><script>var PRELOADED_STATE = "
            + json.dumps(est) + ";</script></head><body></body></html>")
