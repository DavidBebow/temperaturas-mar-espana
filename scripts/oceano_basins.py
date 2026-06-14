"""Definición de cuencas oceánicas (compartida por los scripts del océano).
bbox = [lon_oeste, lon_este, lat_sur, lat_norte] en grados (-180..180, -90..90).
lon_este puede ser > 180 para cuencas que cruzan el antimeridiano."""

BASINS = {
    "mediterraneo":      ("Mediterráneo",            -6,  36,  31, 46),
    "atlantico_ne":      ("Atlántico NE / Europa",  -25,  10,  36, 60),
    "atlantico_n":       ("Atlántico Norte",        -80, -10,  10, 60),
    "atlantico_s":       ("Atlántico Sur",          -55,  20, -60,  0),
    "pacifico_tropical": ("Pacífico tropical",     -180, -80, -10, 10),
    "pacifico_n":        ("Pacífico Norte",         120, 240,  10, 60),
    "indico":            ("Índico",                  40, 110, -50, 25),
    "artico":            ("Ártico",                -180, 180,  66, 90),
    "antartico":         ("Océano Antártico",      -180, 180, -90, -55),
}
