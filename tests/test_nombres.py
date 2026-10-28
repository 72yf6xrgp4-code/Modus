from vigia.nombres import emparejar, nombre_winamax

DB = ["Andy Baetens", "Cameron Menzies", "Ross Smith", "Michael Smith",
      "Michael van Gerwen", "José Pérez"]


def test_normalizacion():
    assert nombre_winamax("Baetens, Andy") == "Andy Baetens"
    assert nombre_winamax("Andy Baetens") == "Andy Baetens"


def test_emparejar():
    assert emparejar("Baetens, Andy", DB) == "Andy Baetens"
    assert emparejar("ANDY BAETENS", DB) == "Andy Baetens"
    assert emparejar("Jose Perez", DB) == "José Pérez"
    assert emparejar("Perez, Jose", DB) == "José Pérez"
    assert emparejar("Menzies", DB) == "Cameron Menzies"
    assert emparejar("Van Gerwen, Michael", DB) == "Michael van Gerwen"
    assert emparejar("M. van Gerwen", DB) == "Michael van Gerwen"
    assert emparejar("R. Smith", DB) == "Ross Smith"
    # Ambiguo: dos Smith
    assert emparejar("Smith", DB) is None
    assert emparejar("Desconocido Total", DB) is None
