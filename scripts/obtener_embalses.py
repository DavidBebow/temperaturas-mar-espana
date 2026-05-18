"""
obtener_embalses.py — Embalses España por Provincia
====================================================
FUENTE: Boletín Hidrológico Semanal — MITECO
MÉTODO: Datos ingresados manualmente cada martes desde el Boletín oficial.

Por qué no descarga automáticamente:
  El fichero BD-Embalses_1988-2022.zip del MITECO NO es descargable
  mediante script (el servidor devuelve HTML, no el ZIP). No existe
  API pública con datos dinámicos semanales por embalse individual.

Flujo de trabajo cada martes:
  1. Abrir https://www.miteco.gob.es/es/agua/temas/evaluacion-de-los-
     recursos-hidricos/boletin-hidrologico.html
  2. Consultar el dashboard ArcGIS o descargar el PDF del Boletín
  3. Actualizar DATOS_EMBALSES y FECHA_DATOS al inicio de este archivo
  4. Hacer commit → GitHub Actions ejecuta el script y actualiza los JSON

Genera:
  docs/embalses_nacional.json      ← mapa España por provincia
  docs/embalses/{provincia}.json   ← detalle de cada provincia

No requiere dependencias externas (solo Python estándar).
"""

import json
import os
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════════
# ▶▶▶  ACTUALIZAR AQUÍ CADA MARTES  ◀◀◀
#
# Datos del Boletín Hidrológico Semanal del MITECO.
# Fuente: https://www.miteco.gob.es → Agua → Boletín Hidrológico
# ═══════════════════════════════════════════════════════════════════════════════

FECHA_DATOS = "11/05/2026"   # ← Fecha del boletín (DD/MM/YYYY)

# Formato: "NOMBRE EN MAYÚSCULAS": {"vol": hm³_actual, "pct": porcentaje}
# Fuente: embalses.net / Boletín Hidrológico MITECO — semana 19/2026 (11-05-2026)
# Los nombres deben coincidir con los de PROVINCIAS → embalses → buscar
DATOS_EMBALSES = {
    # ── MURCIA ───────────────────────────────────────────────────────────────
    "ALFONSO XIII":        {"vol":  3.0, "pct": 13.6},
    "ALGECIRAS":           {"vol": 19.0, "pct": 42.2},
    "ARGOS":               {"vol":  7.0, "pct": 65.4},
    "LA CIERVA":           {"vol":  5.0, "pct": 68.5},
    "PUENTES":             {"vol": 14.0, "pct": 53.8},
    "SANTOMERA":           {"vol":  2.0, "pct": 11.1},
    "VALDEINFIERNO":       {"vol":  0.1, "pct":  0.9},
    "MULA":                {"vol":  1.2, "pct":  5.7},
    "PLIEGO":              {"vol":  0.2, "pct":  5.5},
    # ── ANDALUCÍA ────────────────────────────────────────────────────────────
    "LA MINILLA":          {"vol": 180.3, "pct": 91.5},
    "EL GERGAL":           {"vol":  72.6, "pct": 88.3},
    "MELONARES":           {"vol": 151.7, "pct": 90.3},
    "ARACENA":             {"vol": 109.3, "pct": 86.1},
    "IZNAJAR":             {"vol": 862.4, "pct": 87.9},
    "LA BREÑA II":         {"vol": 733.3, "pct": 89.1},
    "BEMBEZAR":            {"vol": 237.0, "pct": 91.5},
    "SAN RAFAEL":          {"vol":  49.8, "pct": 85.8},
    "EL TRANCO":           {"vol": 441.0, "pct": 88.2},
    "JANDULA":             {"vol": 282.4, "pct": 87.5},
    "EL RUMBLAR":          {"vol":  78.5, "pct": 87.7},
    "NEGRATIN":            {"vol": 498.5, "pct": 87.9},
    "RULES":               {"vol":  98.3, "pct": 81.9},
    "LOS BERMEJALES":      {"vol":  74.2, "pct": 81.8},
    "CANALES":             {"vol":  61.6, "pct": 87.6},
    "ZAHARA":              {"vol": 199.5, "pct": 92.8},
    "BORNOS":              {"vol": 229.0, "pct": 89.8},
    "BARBATE":             {"vol": 193.0, "pct": 84.6},
    "LA VINUELA":          {"vol": 131.3, "pct": 77.7},
    "GUADALTEBA":          {"vol":  96.4, "pct": 78.9},
    "CONDE GUADALHORCE":   {"vol": 103.8, "pct": 76.4},
    "EL ANDEVALO":         {"vol": 138.4, "pct": 87.0},
    "RIO TINTO":           {"vol":  46.9, "pct": 86.8},
    "CUEVAS DE ALMANZORA": {"vol": 131.4, "pct": 74.1},
    "BENINAR":             {"vol":  43.7, "pct": 78.2},
    # ── MADRID ───────────────────────────────────────────────────────────────
    "EL ATAZAR":           {"vol": 362.0, "pct": 85.2},
    "VALMAYOR":            {"vol": 106.0, "pct": 85.2},
    "SANTILLANA":          {"vol":  77.6, "pct": 85.2},
    "EL PARDO":            {"vol":  35.5, "pct": 85.2},
    "PINILLA":             {"vol":  32.4, "pct": 85.2},
    "RIOSEQUILLO":         {"vol":  35.2, "pct": 85.2},
    "EL VADO":             {"vol":  47.0, "pct": 85.2},
    # ── EXTREMADURA ──────────────────────────────────────────────────────────
    "LA SERENA":           {"vol": 2760.0, "pct": 85.7},
    "CIJARA":              {"vol": 1386.0, "pct": 85.7},
    "GARCIA SOLA":         {"vol":  735.0, "pct": 85.7},
    "ZUJAR":               {"vol":  265.0, "pct": 85.7},
    "ALCANTARA":           {"vol": 2710.0, "pct": 83.7},
    "GABRIEL GALAN":       {"vol":  774.0, "pct": 83.7},
    # ── CASTILLA-LA MANCHA ───────────────────────────────────────────────────
    "ALARCON":             {"vol":  899.0, "pct": 79.3},
    "CONTRERAS":           {"vol":  675.0, "pct": 79.3},
    "BUENDIA":             {"vol": 1299.0, "pct": 79.3},
    "FUENSANTA":           {"vol":  177.0, "pct": 66.9},
    "TALAVE":              {"vol":   22.8, "pct": 66.9},
    "AZUTAN":              {"vol":  209.0, "pct": 66.1},
    "ENTREPEÑAS":          {"vol": 1320.0, "pct": 66.6},
    # ── COMUNIDAD VALENCIANA ─────────────────────────────────────────────────
    "TOUS":                {"vol":  233.0, "pct": 61.8},
    "FORATA":              {"vol":   23.0, "pct": 61.8},
    "AMADORIO":            {"vol":    8.5, "pct": 49.8},
    "GUADALEST":           {"vol":    6.6, "pct": 49.8},
    "SICHAR":              {"vol":   29.5, "pct": 59.7},
    # ── ARAGÓN ───────────────────────────────────────────────────────────────
    "MEQUINENZA":          {"vol": 1315.0, "pct": 94.0},
    "RIBARROJA":           {"vol":  197.0, "pct": 94.0},
    "MEDIANO":             {"vol":  373.0, "pct": 85.6},
    "EL GRADO":            {"vol":  342.0, "pct": 85.6},
    "YESA":                {"vol":  382.0, "pct": 85.6},
    "SOTONERA":            {"vol":  162.0, "pct": 85.6},
    # ── CATALUÑA ─────────────────────────────────────────────────────────────
    "RIALB":               {"vol":  366.0, "pct": 90.8},
    "CANELLES":            {"vol":  616.0, "pct": 90.8},
    "LA BAELLS":           {"vol":  103.0, "pct": 94.2},
    "SUSQUEDA":            {"vol":  219.0, "pct": 94.2},
    "SAU":                 {"vol":  153.0, "pct": 90.8},
    "BOADELLA":            {"vol":   56.0, "pct": 90.8},
    # ── LA RIOJA ─────────────────────────────────────────────────────────────
    "MANSILLA":            {"vol":   61.5, "pct": 90.5},
    # ── NAVARRA ──────────────────────────────────────────────────────────────
    "ITOIZ":               {"vol":  373.0, "pct": 89.2},
    "ALLOZ":               {"vol":   59.0, "pct": 89.2},
    # ── PAÍS VASCO ───────────────────────────────────────────────────────────
    "ULLIBARRI":           {"vol":  125.8, "pct": 85.6},
    "URRUNAGA":            {"vol":   61.2, "pct": 85.6},
    # ── CANTABRIA ────────────────────────────────────────────────────────────
    "DEL EBRO":            {"vol":  488.0, "pct": 84.9},
    # ── ASTURIAS ─────────────────────────────────────────────────────────────
    "TANES":               {"vol":   36.7, "pct": 83.3},
    "RIOSECO":             {"vol":   27.1, "pct": 83.3},
    # ── CASTILLA Y LEÓN ──────────────────────────────────────────────────────
    "BARRIOS DE LUNA":     {"vol":  272.7, "pct": 88.7},
    "RIANO":               {"vol":  577.0, "pct": 88.7},
    "RICOBAYO":            {"vol":  960.8, "pct": 82.8},
    "ALMENDRA":            {"vol": 2854.0, "pct": 89.2},
    "REQUEJADA":           {"vol":  411.8, "pct": 85.8},
    # ── GALICIA ──────────────────────────────────────────────────────────────
    "BELESAR":             {"vol":  588.0, "pct": 90.1},
    "CASTRELO":            {"vol": 1152.0, "pct": 84.8},
    "CECEBRE":             {"vol":   49.9, "pct": 74.1},
    # ── GALICIA — Pontevedra ──────────────────────────────────────────────────
    "EIRAS":               {"vol":  101.1, "pct": 87.9},
    "CALDAS":              {"vol":   63.3, "pct": 87.9},
    # ── CASTILLA Y LEÓN adicional ─────────────────────────────────────────────
    "EL BURGUILLO":        {"vol":  181.1, "pct": 91.0},
    "ALBERCHE":            {"vol":   80.1, "pct": 91.0},
    "PONTON ALTO":         {"vol":   23.2, "pct": 91.0},
    "LINARES DEL ARROYO":  {"vol":   50.1, "pct": 91.0},
    "CUERDA DEL POZO":     {"vol":  190.5, "pct": 83.5},
    "AGUILAR":             {"vol":  208.8, "pct": 85.2},
    # ── CASTILLA-LA MANCHA adicional ─────────────────────────────────────────
    "GASSET":              {"vol":   37.0, "pct": 89.6},
    "PUENTE NUEVO":        {"vol":   44.8, "pct": 89.6},
    "VEGA DE JABALON":     {"vol":   32.3, "pct": 89.6},
    # ── ARAGÓN — Teruel ───────────────────────────────────────────────────────
    "CUEVA FORADADA":      {"vol":   12.8, "pct": 75.6},
    "GALLIPUEN":           {"vol":   32.0, "pct": 75.6},
    "PENA":                {"vol":   13.6, "pct": 75.6},
    # ── CATALUÑA — Tarragona ──────────────────────────────────────────────────
    "RIUDECANYES":         {"vol":    9.7, "pct": 89.4},
    "SIURANA":             {"vol":   11.1, "pct": 89.4},
    # ── PAÍS VASCO — Guipúzcoa / Álava ───────────────────────────────────────
    "ANARBE":              {"vol":   27.0, "pct": 93.1},
    # ── CASTILLA Y LEÓN — Burgos/Palencia extra ───────────────────────────────
    "SOBRÓN":              {"vol":   17.6, "pct": 84.9},
    "SOBRON":              {"vol":   17.6, "pct": 84.9},
    "URREZ":               {"vol":   22.1, "pct": 84.9},
    "BOLARQUE":            {"vol":   21.0, "pct": 66.6},
    "CAMPORREDONDO":       {"vol":   59.9, "pct": 85.6},
    # ── PROVINCIAS CON PCT DIRECTO DE EMBALSES.NET ───────────────────────────
    # Guadalajara (66.62%) — Entrepeñas pertenece en su mayor parte a Guadalajara
    "ENTREPEÑAS":          {"vol":  556.7, "pct": 66.6},
    # Palencia (85.63%) — datos directos
    "REQUEJADA":           {"vol":   78.4, "pct": 85.6},
}

# ═══════════════════════════════════════════════════════════════════════════════
# DICCIONARIO DE PROVINCIAS Y EMBALSES
# ═══════════════════════════════════════════════════════════════════════════════
PROVINCIAS = {

    "murcia": {
        "nombre": "Murcia", "comunidad": "Región de Murcia",
        "lat": 37.9, "lon": -1.7,
        "embalses": [
            {"id":"alfonso_xiii",  "nombre":"Alfonso XIII",  "buscar":["ALFONSO XIII"],   "rio":"Quípar",       "municipio":"Calasparra",         "cap":22.0,  "lat":38.214,"lon":-1.728},
            {"id":"algeciras",     "nombre":"Algeciras",     "buscar":["ALGECIRAS"],      "rio":"Guadalentín",  "municipio":"Lorca",              "cap":45.0,  "lat":37.710,"lon":-1.870},
            {"id":"argos",         "nombre":"Argos",         "buscar":["ARGOS"],          "rio":"Argos",        "municipio":"Caravaca de la Cruz", "cap":10.7,  "lat":38.338,"lon":-1.907},
            {"id":"la_cierva",     "nombre":"La Cierva",     "buscar":["LA CIERVA"],      "rio":"Segura",       "municipio":"Ojós",               "cap":7.3,   "lat":38.075,"lon":-1.592},
            {"id":"puentes",       "nombre":"Puentes",       "buscar":["PUENTES"],        "rio":"Guadalentín",  "municipio":"Lorca",              "cap":26.0,  "lat":37.776,"lon":-1.787},
            {"id":"santomera",     "nombre":"Santomera",     "buscar":["SANTOMERA"],      "rio":"Rambla Salada","municipio":"Santomera",          "cap":17.9,  "lat":38.072,"lon":-1.057},
            {"id":"valdeinfierno", "nombre":"Valdeinfierno", "buscar":["VALDEINFIERNO"],  "rio":"Luchena",      "municipio":"Lorca",              "cap":11.3,  "lat":37.953,"lon":-1.872},
            {"id":"mula",          "nombre":"Mula",          "buscar":["MULA"],           "rio":"Mula",         "municipio":"Mula",               "cap":21.0,  "lat":38.052,"lon":-1.496},
            {"id":"pliego",        "nombre":"Pliego",        "buscar":["PLIEGO"],         "rio":"Pliego",       "municipio":"Pliego",             "cap":3.6,   "lat":38.009,"lon":-1.558},
        ],
    },

    "sevilla": {
        "nombre": "Sevilla", "comunidad": "Andalucía",
        "lat": 37.4, "lon": -5.9,
        "embalses": [
            {"id":"la_minilla", "nombre":"La Minilla", "buscar":["LA MINILLA"], "rio":"Rivera de Huelva","municipio":"Real de la Jara","cap":197.0,"lat":37.803,"lon":-5.913},
            {"id":"el_gergal",  "nombre":"El Gergal",  "buscar":["EL GERGAL"],  "rio":"Cala",           "municipio":"Guillena",       "cap":82.2, "lat":37.665,"lon":-6.025},
            {"id":"melonares",  "nombre":"Melonares",  "buscar":["MELONARES"],  "rio":"Rivera de Huelva","municipio":"Guillena",       "cap":168.0,"lat":37.721,"lon":-6.041},
            {"id":"aracena",    "nombre":"Aracena",    "buscar":["ARACENA"],    "rio":"Rivera de Huelva","municipio":"Aracena",        "cap":127.0,"lat":37.879,"lon":-6.604},
        ],
    },

    "cordoba": {
        "nombre": "Córdoba", "comunidad": "Andalucía",
        "lat": 37.9, "lon": -4.8,
        "embalses": [
            {"id":"iznajar",    "nombre":"Iznájar",    "buscar":["IZNAJAR"],     "rio":"Genil",    "municipio":"Iznájar",    "cap":981.1,"lat":37.267,"lon":-4.310},
            {"id":"la_breña",   "nombre":"La Breña II","buscar":["LA BREÑA II"], "rio":"Bembézar", "municipio":"Hornachuelos","cap":823.0,"lat":37.885,"lon":-5.164},
            {"id":"bembezar",   "nombre":"Bembézar",   "buscar":["BEMBEZAR"],    "rio":"Bembézar", "municipio":"Hornachuelos","cap":259.0,"lat":37.834,"lon":-5.247},
            {"id":"san_rafael", "nombre":"San Rafael", "buscar":["SAN RAFAEL"],  "rio":"Guadalmellato","municipio":"Córdoba","cap":58.0,"lat":37.901,"lon":-4.830},
        ],
    },

    "jaen": {
        "nombre": "Jaén", "comunidad": "Andalucía",
        "lat": 37.8, "lon": -3.8,
        "embalses": [
            {"id":"el_tranco","nombre":"El Tranco","buscar":["EL TRANCO"],"rio":"Guadalquivir","municipio":"Hornos",          "cap":500.0,"lat":38.039,"lon":-2.803},
            {"id":"jandula",  "nombre":"Jándula",  "buscar":["JANDULA"],  "rio":"Jándula",     "municipio":"Andújar",         "cap":322.6,"lat":38.177,"lon":-4.100},
            {"id":"el_rumblar","nombre":"El Rumblar","buscar":["EL RUMBLAR"],"rio":"Rumblar",  "municipio":"Baños de la Encina","cap":89.5,"lat":38.228,"lon":-3.796},
        ],
    },

    "granada": {
        "nombre": "Granada", "comunidad": "Andalucía",
        "lat": 37.2, "lon": -3.6,
        "embalses": [
            {"id":"negratin",       "nombre":"Negratín",       "buscar":["NEGRATIN"],        "rio":"Guadiana Menor","municipio":"Freila",         "cap":567.0,"lat":37.656,"lon":-2.981},
            {"id":"rules",          "nombre":"Rules",          "buscar":["RULES"],           "rio":"Guadalfeo",     "municipio":"Vélez Benaudalla","cap":120.0,"lat":36.814,"lon":-3.573},
            {"id":"los_bermejales", "nombre":"Los Bermejales", "buscar":["LOS BERMEJALES"],  "rio":"Cacín",         "municipio":"Arenas del Rey",  "cap":90.7, "lat":36.987,"lon":-4.044},
            {"id":"canales",        "nombre":"Canales",        "buscar":["CANALES"],         "rio":"Genil",         "municipio":"Güéjar Sierra",   "cap":70.3, "lat":37.138,"lon":-3.558},
        ],
    },

    "malaga": {
        "nombre": "Málaga", "comunidad": "Andalucía",
        "lat": 36.9, "lon": -4.6,
        "embalses": [
            {"id":"la_vinuela",  "nombre":"La Viñuela",       "buscar":["LA VINUELA"],         "rio":"Vélez",     "municipio":"La Viñuela","cap":168.9,"lat":36.871,"lon":-4.149},
            {"id":"guadalteba",  "nombre":"Guadalteba",       "buscar":["GUADALTEBA"],         "rio":"Guadalteba","municipio":"Ardales",   "cap":122.2,"lat":36.887,"lon":-4.885},
            {"id":"guadalhorce", "nombre":"Conde Guadalhorce","buscar":["CONDE GUADALHORCE"],  "rio":"Guadalhorce","municipio":"Ardales",  "cap":135.8,"lat":36.864,"lon":-4.793},
        ],
    },

    "huelva": {
        "nombre": "Huelva", "comunidad": "Andalucía",
        "lat": 37.6, "lon": -6.9,
        "embalses": [
            {"id":"el_andevalo","nombre":"El Andévalo","buscar":["EL ANDEVALO"],"rio":"Odiel","municipio":"El Granado","cap":159.0,"lat":37.674,"lon":-7.090},
            {"id":"rio_tinto",  "nombre":"Río Tinto",  "buscar":["RIO TINTO"],  "rio":"Tinto","municipio":"Nerva",    "cap":54.0, "lat":37.695,"lon":-6.555},
        ],
    },

    "cadiz": {
        "nombre": "Cádiz", "comunidad": "Andalucía",
        "lat": 36.5, "lon": -5.8,
        "embalses": [
            {"id":"zahara",  "nombre":"Zahara",  "buscar":["ZAHARA"],  "rio":"Guadalete","municipio":"Zahara","cap":215.0,"lat":36.837,"lon":-5.428},
            {"id":"bornos",  "nombre":"Bornos",  "buscar":["BORNOS"],  "rio":"Guadalete","municipio":"Bornos", "cap":255.0,"lat":36.803,"lon":-5.715},
            {"id":"barbate", "nombre":"Barbate", "buscar":["BARBATE"], "rio":"Barbate",  "municipio":"Vejer",  "cap":228.0,"lat":36.253,"lon":-5.830},
        ],
    },

    "almeria": {
        "nombre": "Almería", "comunidad": "Andalucía",
        "lat": 37.2, "lon": -2.4,
        "embalses": [
            {"id":"cuevas", "nombre":"Cuevas Almanzora","buscar":["CUEVAS DE ALMANZORA"],"rio":"Almanzora","municipio":"Cuevas del Almanzora","cap":177.3,"lat":37.328,"lon":-1.884},
            {"id":"beninar","nombre":"Benínar",          "buscar":["BENINAR"],            "rio":"Adra",      "municipio":"Berja",              "cap":55.9, "lat":36.882,"lon":-2.982},
        ],
    },

    "madrid": {
        "nombre": "Madrid", "comunidad": "Comunidad de Madrid",
        "lat": 40.45, "lon": -3.70,
        "embalses": [
            {"id":"el_atazar",   "nombre":"El Atazar",   "buscar":["EL ATAZAR"],   "rio":"Lozoya",   "municipio":"Patones",      "cap":425.3,"lat":40.903,"lon":-3.578},
            {"id":"valmayor",    "nombre":"Valmayor",    "buscar":["VALMAYOR"],    "rio":"Aulencia",  "municipio":"Valdemorillo", "cap":124.4,"lat":40.535,"lon":-4.052},
            {"id":"santillana",  "nombre":"Santillana",  "buscar":["SANTILLANA"],  "rio":"Manzanares","municipio":"Manzanares RV","cap":91.0, "lat":40.727,"lon":-3.891},
            {"id":"el_pardo",    "nombre":"El Pardo",    "buscar":["EL PARDO"],    "rio":"Manzanares","municipio":"El Pardo",     "cap":41.7, "lat":40.541,"lon":-3.780},
            {"id":"pinilla",     "nombre":"Pinilla",     "buscar":["PINILLA"],     "rio":"Lozoya",    "municipio":"Pinilla",      "cap":38.0, "lat":40.990,"lon":-3.685},
            {"id":"riosequillo", "nombre":"Riosequillo", "buscar":["RIOSEQUILLO"], "rio":"Jarama",    "municipio":"Buitrago",     "cap":41.3, "lat":40.974,"lon":-3.519},
            {"id":"el_vado",     "nombre":"El Vado",     "buscar":["EL VADO"],     "rio":"Jarama",    "municipio":"Campillo",     "cap":55.1, "lat":40.918,"lon":-3.322},
        ],
    },

    "badajoz": {
        "nombre": "Badajoz", "comunidad": "Extremadura",
        "lat": 38.9, "lon": -6.0,
        "embalses": [
            {"id":"la_serena",  "nombre":"La Serena",  "buscar":["LA SERENA"],  "rio":"Zújar",    "municipio":"Zalamea",   "cap":3219.0,"lat":38.857,"lon":-5.470},
            {"id":"cijara",     "nombre":"Cíjara",     "buscar":["CIJARA"],     "rio":"Guadiana", "municipio":"Herrera",   "cap":1617.0,"lat":39.303,"lon":-5.010},
            {"id":"garcia_sola","nombre":"García Sola","buscar":["GARCIA SOLA"],"rio":"Guadiana", "municipio":"Orellana",  "cap":858.0, "lat":39.016,"lon":-5.540},
            {"id":"zujar",      "nombre":"Zújar",      "buscar":["ZUJAR"],      "rio":"Zújar",    "municipio":"Capilla",   "cap":309.0, "lat":38.717,"lon":-5.157},
        ],
    },

    "caceres": {
        "nombre": "Cáceres", "comunidad": "Extremadura",
        "lat": 39.8, "lon": -6.4,
        "embalses": [
            {"id":"alcantara",    "nombre":"Alcántara",     "buscar":["ALCANTARA"],     "rio":"Tajo",  "municipio":"Alcántara",      "cap":3162.0,"lat":39.728,"lon":-6.892},
            {"id":"gabriel_galan","nombre":"Gabriel y Galán","buscar":["GABRIEL GALAN"],"rio":"Alagón","municipio":"Granadilla",     "cap":925.0, "lat":40.218,"lon":-6.086},
        ],
    },

    "cuenca": {
        "nombre": "Cuenca", "comunidad": "Castilla-La Mancha",
        "lat": 40.1, "lon": -2.1,
        "embalses": [
            {"id":"alarcon",   "nombre":"Alarcón",  "buscar":["ALARCON"],  "rio":"Júcar",   "municipio":"Alarcón","cap":1118.0,"lat":39.554,"lon":-2.100},
            {"id":"contreras", "nombre":"Contreras","buscar":["CONTRERAS"],"rio":"Cabriel", "municipio":"Contreras","cap":852.0,"lat":39.540,"lon":-1.481},
            {"id":"buendia",   "nombre":"Buendía",  "buscar":["BUENDIA"],  "rio":"Guadiela","municipio":"Buendía","cap":1640.0,"lat":40.391,"lon":-2.718},
        ],
    },

    "albacete": {
        "nombre": "Albacete", "comunidad": "Castilla-La Mancha",
        "lat": 38.9, "lon": -1.9,
        "embalses": [
            {"id":"fuensanta", "nombre":"Fuensanta","buscar":["FUENSANTA"],"rio":"Segura","municipio":"Yeste","cap":210.7,"lat":38.334,"lon":-2.115},
            {"id":"talave",    "nombre":"Talave",   "buscar":["TALAVE"],   "rio":"Mundo", "municipio":"Letur","cap":34.0, "lat":38.373,"lon":-2.130},
        ],
    },

    "toledo": {
        "nombre": "Toledo", "comunidad": "Castilla-La Mancha",
        "lat": 39.8, "lon": -4.0,
        "embalses": [
            {"id":"azutan","nombre":"Azután","buscar":["AZUTAN"],"rio":"Tajo","municipio":"Azután","cap":316.0,"lat":39.791,"lon":-5.143},
        ],
    },

    "guadalajara": {
        "nombre": "Guadalajara", "comunidad": "Castilla-La Mancha",
        "lat": 40.6, "lon": -3.2,
        "embalses": [
            {"id":"entrepeñas","nombre":"Entrepeñas","buscar":["ENTREPEÑAS","ENTREPENAS"],"rio":"Tajo","municipio":"Sacedón","cap":835.0,"lat":40.545,"lon":-2.691},
            {"id":"bolarque",  "nombre":"Bolarque",  "buscar":["BOLARQUE"],               "rio":"Tajo","municipio":"Bolarque","cap":31.5,"lat":40.371,"lon":-2.825},
        ],
    },

    "valencia": {
        "nombre": "Valencia", "comunidad": "Comunidad Valenciana",
        "lat": 39.5, "lon": -0.6,
        "embalses": [
            {"id":"tous",   "nombre":"Tous",  "buscar":["TOUS"],  "rio":"Júcar","municipio":"Tous",  "cap":377.0,"lat":39.194,"lon":-0.832},
            {"id":"forata", "nombre":"Forata","buscar":["FORATA"],"rio":"Magro","municipio":"Yátova","cap":37.2, "lat":39.392,"lon":-0.946},
        ],
    },

    "alicante": {
        "nombre": "Alicante", "comunidad": "Comunidad Valenciana",
        "lat": 38.4, "lon": -0.5,
        "embalses": [
            {"id":"amadorio",  "nombre":"Amadorio",  "buscar":["AMADORIO"],  "rio":"Amadorio", "municipio":"Villajoyosa","cap":17.0,"lat":38.511,"lon":-0.245},
            {"id":"guadalest", "nombre":"Guadalest", "buscar":["GUADALEST"], "rio":"Guadalest","municipio":"Guadalest", "cap":13.3,"lat":38.671,"lon":-0.137},
        ],
    },

    "castellon": {
        "nombre": "Castellón", "comunidad": "Comunidad Valenciana",
        "lat": 40.1, "lon": -0.1,
        "embalses": [
            {"id":"sichar","nombre":"Sichar","buscar":["SICHAR"],"rio":"Mijares","municipio":"Espadilla","cap":49.3,"lat":39.971,"lon":-0.446},
        ],
    },

    "zaragoza": {
        "nombre": "Zaragoza", "comunidad": "Aragón",
        "lat": 41.6, "lon": -0.9,
        "embalses": [
            {"id":"mequinenza","nombre":"Mequinenza","buscar":["MEQUINENZA"],"rio":"Ebro","municipio":"Mequinenza","cap":1534.0,"lat":41.381,"lon":0.276},
            {"id":"ribarroja", "nombre":"Ribarroja", "buscar":["RIBARROJA"], "rio":"Ebro","municipio":"Riba-roja", "cap":209.5, "lat":41.292,"lon":0.490},
        ],
    },

    "huesca": {
        "nombre": "Huesca", "comunidad": "Aragón",
        "lat": 42.1, "lon": -0.4,
        "embalses": [
            {"id":"mediano", "nombre":"Mediano",    "buscar":["MEDIANO"],  "rio":"Cinca",  "municipio":"Mediano", "cap":436.0,"lat":42.269,"lon":0.146},
            {"id":"el_grado","nombre":"El Grado",   "buscar":["EL GRADO"], "rio":"Cinca",  "municipio":"El Grado","cap":400.0,"lat":42.136,"lon":0.171},
            {"id":"yesa",    "nombre":"Yesa",        "buscar":["YESA"],     "rio":"Aragón", "municipio":"Yesa",    "cap":446.8,"lat":42.618,"lon":-1.180},
            {"id":"sotonera","nombre":"La Sotonera", "buscar":["SOTONERA"], "rio":"Sotón",  "municipio":"Gurrea",  "cap":189.4,"lat":42.136,"lon":-0.678},
        ],
    },

    "lleida": {
        "nombre": "Lleida", "comunidad": "Cataluña",
        "lat": 41.9, "lon": 1.1,
        "embalses": [
            {"id":"rialb",   "nombre":"Rialb",   "buscar":["RIALB"],   "rio":"Segre",         "municipio":"Rialb","cap":402.9,"lat":42.013,"lon":1.281},
            {"id":"canelles","nombre":"Canelles","buscar":["CANELLES"],"rio":"N. Ribagorzana","municipio":"Arén", "cap":678.0,"lat":42.052,"lon":0.627},
        ],
    },

    "barcelona": {
        "nombre": "Barcelona", "comunidad": "Cataluña",
        "lat": 41.6, "lon": 1.9,
        "embalses": [
            {"id":"la_baells","nombre":"La Baells","buscar":["LA BAELLS","BAELLS"],"rio":"Llobregat","municipio":"Berga",    "cap":109.0,"lat":41.955,"lon":1.921},
            {"id":"susqueda", "nombre":"Susqueda", "buscar":["SUSQUEDA"],           "rio":"Ter",      "municipio":"Susqueda","cap":233.0,"lat":41.968,"lon":2.538},
        ],
    },

    "girona": {
        "nombre": "Girona", "comunidad": "Cataluña",
        "lat": 42.0, "lon": 2.8,
        "embalses": [
            {"id":"sau",     "nombre":"Sau",     "buscar":["SAU"],     "rio":"Ter","municipio":"Vilanova de Sau","cap":168.0,"lat":41.984,"lon":2.427},
            {"id":"boadella","nombre":"Boadella","buscar":["BOADELLA"],"rio":"Muga","municipio":"Darnius",      "cap":61.5, "lat":42.321,"lon":2.817},
        ],
    },

    "la_rioja": {
        "nombre": "La Rioja", "comunidad": "La Rioja",
        "lat": 42.3, "lon": -2.4,
        "embalses": [
            {"id":"mansilla","nombre":"Mansilla","buscar":["MANSILLA"],"rio":"Najerilla","municipio":"Mansilla Sierra","cap":68.0,"lat":42.175,"lon":-2.905},
        ],
    },

    "navarra": {
        "nombre": "Navarra", "comunidad": "Navarra",
        "lat": 42.7, "lon": -1.6,
        "embalses": [
            {"id":"itoiz","nombre":"Itoiz","buscar":["ITOIZ"],"rio":"Irati", "municipio":"Itoiz",   "cap":417.7,"lat":42.750,"lon":-1.435},
            {"id":"alloz","nombre":"Alloz","buscar":["ALLOZ"],"rio":"Salado","municipio":"Guesálaz","cap":66.2, "lat":42.693,"lon":-1.950},
        ],
    },


    "cantabria": {
        "nombre": "Cantabria", "comunidad": "Cantabria",
        "lat": 43.1, "lon": -4.0,
        "embalses": [
            {"id":"del_ebro","nombre":"Del Ebro","buscar":["DEL EBRO"],"rio":"Ebro","municipio":"Arija","cap":540.0,"lat":42.973,"lon":-4.007},
        ],
    },

    "asturias": {
        "nombre": "Asturias", "comunidad": "Asturias",
        "lat": 43.3, "lon": -5.9,
        "embalses": [
            {"id":"tanes",   "nombre":"Tanes",   "buscar":["TANES"],   "rio":"Nalón", "municipio":"Caso",    "cap":44.0,"lat":43.204,"lon":-5.489},
            {"id":"rioseco", "nombre":"Rioseco", "buscar":["RIOSECO"], "rio":"Narcea","municipio":"Belmonte","cap":32.5,"lat":43.292,"lon":-6.571},
        ],
    },

    "leon": {
        "nombre": "León", "comunidad": "Castilla y León",
        "lat": 42.6, "lon": -5.6,
        "embalses": [
            {"id":"barrios_luna","nombre":"Barrios de Luna","buscar":["BARRIOS DE LUNA"],"rio":"Luna","municipio":"Los Barrios","cap":307.5,"lat":42.850,"lon":-5.880},
            {"id":"riano",       "nombre":"Riaño",          "buscar":["RIANO","RIAÑO"],   "rio":"Esla","municipio":"Riaño",      "cap":651.0,"lat":42.979,"lon":-5.005},
        ],
    },

    "zamora": {
        "nombre": "Zamora", "comunidad": "Castilla y León",
        "lat": 41.5, "lon": -5.8,
        "embalses": [
            {"id":"ricobayo","nombre":"Ricobayo","buscar":["RICOBAYO"],"rio":"Esla","municipio":"Ricobayo","cap":1160.0,"lat":41.725,"lon":-5.850},
        ],
    },

    "salamanca": {
        "nombre": "Salamanca", "comunidad": "Castilla y León",
        "lat": 40.9, "lon": -5.7,
        "embalses": [
            {"id":"almendra","nombre":"Almendra","buscar":["ALMENDRA"],"rio":"Tormes","municipio":"Almendra","cap":3585.0,"lat":41.268,"lon":-6.343},
        ],
    },

    "palencia": {
        "nombre": "Palencia", "comunidad": "Castilla y León",
        "lat": 42.0, "lon": -4.5,
        "embalses": [
            {"id":"requejada","nombre":"Requejada","buscar":["REQUEJADA"],"rio":"Pisuerga","municipio":"Cervera","cap":91.5,"lat":42.879,"lon":-4.503},
            {"id":"camporredondo","nombre":"Camporredondo","buscar":["CAMPORREDONDO"],"rio":"Carrión","municipio":"Alba de los Cardaños","cap":70.0,"lat":42.905,"lon":-4.753},
        ],
    },

    "lugo": {
        "nombre": "Lugo", "comunidad": "Galicia",
        "lat": 43.0, "lon": -7.6,
        "embalses": [
            {"id":"belesar","nombre":"Belesar","buscar":["BELESAR"],"rio":"Miño","municipio":"Chantada","cap":654.0,"lat":42.600,"lon":-7.717},
        ],
    },

    "ourense": {
        "nombre": "Ourense", "comunidad": "Galicia",
        "lat": 42.3, "lon": -7.9,
        "embalses": [
            {"id":"castrelo","nombre":"Castrelo de Miño","buscar":["CASTRELO"],"rio":"Miño","municipio":"Castrelo","cap":1359.0,"lat":42.246,"lon":-8.058},
        ],
    },

    "a_coruña": {
        "nombre": "A Coruña", "comunidad": "Galicia",
        "lat": 43.3, "lon": -8.4,
        "embalses": [
            {"id":"cecebre","nombre":"Cecebre","buscar":["CECEBRE"],"rio":"Mero","municipio":"Cambre","cap":67.4,"lat":43.272,"lon":-8.243},
        ],
    },

    "pontevedra": {
        "nombre": "Pontevedra", "comunidad": "Galicia",
        "lat": 42.4, "lon": -8.6,
        "embalses": [
            {"id":"eiras",  "nombre":"Eiras",  "buscar":["EIRAS"],  "rio":"Verdugo","municipio":"Fornelos","cap":115.0,"lat":42.380,"lon":-8.433},
            {"id":"caldas", "nombre":"Caldas",  "buscar":["CALDAS"], "rio":"Umia",   "municipio":"Caldas",  "cap":72.0, "lat":42.566,"lon":-8.629},
        ],
    },

    "avila": {
        "nombre": "Ávila", "comunidad": "Castilla y León",
        "lat": 40.7, "lon": -5.0,
        "embalses": [
            {"id":"el_burguillo","nombre":"El Burguillo","buscar":["EL BURGUILLO","BURGUILLO"],"rio":"Alberche","municipio":"El Tiemblo","cap":199.0,"lat":40.413,"lon":-4.650},
            {"id":"el_alberche", "nombre":"El Alberche",  "buscar":["ALBERCHE"],               "rio":"Alberche","municipio":"Navaluenga","cap":88.0, "lat":40.362,"lon":-4.727},
        ],
    },

    "burgos": {
        "nombre": "Burgos", "comunidad": "Castilla y León",
        "lat": 42.3, "lon": -3.7,
        "embalses": [
            {"id":"sobrón","nombre":"Sobrón","buscar":["SOBRON","SOBRÓN"],"rio":"Ebro","municipio":"Sobrón","cap":20.7,"lat":42.791,"lon":-3.050},
            {"id":"urrez", "nombre":"Úrrez",  "buscar":["URREZ"],          "rio":"Ausines","municipio":"Hontoria","cap":26.0,"lat":42.307,"lon":-3.649},
        ],
    },

    "segovia": {
        "nombre": "Segovia", "comunidad": "Castilla y León",
        "lat": 40.9, "lon": -4.1,
        "embalses": [
            {"id":"el_ponton_alto","nombre":"El Pontón Alto","buscar":["PONTON ALTO","EL PONTON","PONTÓN"],"rio":"Eresma","municipio":"La Losa","cap":25.5,"lat":40.929,"lon":-4.204},
            {"id":"linares",       "nombre":"Linares",        "buscar":["LINARES DEL ARROYO","LINARES"],   "rio":"Riaza", "municipio":"Cerezo",  "cap":55.0,"lat":41.302,"lon":-3.556},
        ],
    },

    "soria": {
        "nombre": "Soria", "comunidad": "Castilla y León",
        "lat": 41.8, "lon": -2.5,
        "embalses": [
            {"id":"la_cuerda_del_pozo","nombre":"La Cuerda del Pozo","buscar":["CUERDA DEL POZO","LA CUERDA"],"rio":"Duero","municipio":"Vinuesa","cap":228.0,"lat":41.966,"lon":-2.766},
        ],
    },

    "valladolid": {
        "nombre": "Valladolid", "comunidad": "Castilla y León",
        "lat": 41.7, "lon": -4.7,
        "embalses": [
            {"id":"aguilar","nombre":"Aguilar de Campoo","buscar":["AGUILAR"],"rio":"Pisuerga","municipio":"Aguilar","cap":245.0,"lat":42.795,"lon":-4.266},
        ],
    },

    "ciudad_real": {
        "nombre": "Ciudad Real", "comunidad": "Castilla-La Mancha",
        "lat": 38.9, "lon": -3.9,
        "embalses": [
            {"id":"gasset",      "nombre":"Gasset",       "buscar":["GASSET"],      "rio":"Jabalón", "municipio":"Ciudad Real","cap":41.3,"lat":38.932,"lon":-3.784},
            {"id":"puente_nuevo","nombre":"Puente Nuevo",  "buscar":["PUENTE NUEVO"],"rio":"Guadiana","municipio":"Puertollano","cap":50.0,"lat":38.646,"lon":-4.148},
            {"id":"vega_jabalón","nombre":"Vega de Jabalón","buscar":["VEGA DE JABALON","VEGA JABALON"],"rio":"Jabalón","municipio":"Carrión","cap":36.0,"lat":38.834,"lon":-3.793},
        ],
    },

    "teruel": {
        "nombre": "Teruel", "comunidad": "Aragón",
        "lat": 40.3, "lon": -1.1,
        "embalses": [
            {"id":"cueva_foradada","nombre":"Cueva Foradada","buscar":["CUEVA FORADADA"],"rio":"Martín",  "municipio":"Oliete",  "cap":16.9,"lat":40.996,"lon":-0.628},
            {"id":"gallipuen",     "nombre":"Gallipuén",     "buscar":["GALLIPUEN"],      "rio":"Alfambra","municipio":"Gallipuén","cap":42.3,"lat":40.422,"lon":-0.888},
            {"id":"pena",          "nombre":"Pena",          "buscar":["PENA","EMBALSE DE PENA"],"rio":"Pena","municipio":"Beceite","cap":18.0,"lat":40.884,"lon":0.013},
        ],
    },

    "tarragona": {
        "nombre": "Tarragona", "comunidad": "Cataluña",
        "lat": 41.2, "lon": 1.2,
        "embalses": [
            {"id":"riudecanyes","nombre":"Riudecanyes","buscar":["RIUDECANYES"],"rio":"Riudecanyes","municipio":"Riudecanyes","cap":10.8,"lat":41.155,"lon":0.927},
            {"id":"siurana",    "nombre":"Siurana",    "buscar":["SIURANA"],    "rio":"Siurana",    "municipio":"Cornudella",  "cap":12.4,"lat":41.253,"lon":0.912},
        ],
    },

    "guipuzcoa": {
        "nombre": "Guipúzcoa", "comunidad": "País Vasco",
        "lat": 43.1, "lon": -2.2,
        "embalses": [
            {"id":"añarbe","nombre":"Añarbe","buscar":["ANARBE","AÑARBE"],"rio":"Añarbe","municipio":"Hernani","cap":29.0,"lat":43.213,"lon":-1.968},
        ],
    },

    "alava": {
        "nombre": "Álava", "comunidad": "País Vasco",
        "lat": 42.8, "lon": -2.7,
        "embalses": [
            {"id":"ullibarri_alava","nombre":"Ullíbarri-Gamboa","buscar":["ULLIBARRI"],"rio":"Zadorra","municipio":"Ullibarri","cap":147.0,"lat":42.840,"lon":-2.638},
            {"id":"urrunaga_alava", "nombre":"Urrunaga",        "buscar":["URRUNAGA"], "rio":"Santa Engracia","municipio":"Legutiano","cap":71.5,"lat":42.977,"lon":-2.671},
        ],
    },
}
# ═══════════════════════════════════════════════════════════════════════════════

def estado(pct):
    if pct is None:  return "#888888", "Sin datos"
    if pct < 20:     return "#CC2200", "Crítico"
    if pct < 40:     return "#FF8822", "Bajo"
    if pct < 60:     return "#FFCC44", "Moderado"
    if pct < 80:     return "#44AA66", "Bueno"
    return "#0066CC", "Muy bueno"


def buscar_dato(terminos):
    """Busca el dato en DATOS_EMBALSES por coincidencia exacta o parcial."""
    for t in terminos:
        if t in DATOS_EMBALSES:
            return DATOS_EMBALSES[t]["vol"], DATOS_EMBALSES[t]["pct"]
    for t in terminos:
        for clave, d in DATOS_EMBALSES.items():
            if t in clave or clave in t:
                return d["vol"], d["pct"]
    return None, None


def procesar():
    ahora = datetime.now()
    print("=" * 65)
    print(f"Embalses España — Boletín MITECO {FECHA_DATOS}")
    print(f"Generado: {ahora.strftime('%d/%m/%Y %H:%M')}")
    print("=" * 65)

    os.makedirs("docs/embalses", exist_ok=True)

    provincias_nacional = []

    for id_prov, prov in PROVINCIAS.items():
        lista_emb = []
        sum_vol = sum_cap = 0.0
        tiene_datos = False

        for emb in prov["embalses"]:
            vol, pct = buscar_dato(emb["buscar"])

            if pct is not None:
                tiene_datos = True
                vol = round(float(vol), 2)
                pct = round(float(pct), 1)
                sum_vol += vol
                sum_cap += emb["cap"]
            else:
                vol = None
                sum_cap += emb["cap"]

            col, etq = estado(pct)
            lista_emb.append({
                "id": emb["id"], "nombre": emb["nombre"],
                "rio": emb["rio"], "municipio": emb["municipio"],
                "provincia": prov["nombre"],
                "lat": emb["lat"], "lon": emb["lon"],
                "capacidad_hm3": emb["cap"],
                "volumen_hm3": vol, "pct": pct,
                "color": col, "etiqueta": etq,
            })

        pct_prov = round((sum_vol / sum_cap) * 100, 1) if (tiene_datos and sum_cap > 0) else None
        col_p, etq_p = estado(pct_prov)

        # JSON de provincia
        with open(f"docs/embalses/{id_prov}.json", "w", encoding="utf-8") as f:
            json.dump({
                "ultima_actualizacion": ahora.isoformat(),
                "fecha_legible":   FECHA_DATOS,
                "provincia":       prov["nombre"],
                "comunidad":       prov["comunidad"],
                "total_embalses":  len(lista_emb),
                "capacidad_total_hm3": round(sum_cap, 1),
                "volumen_total_hm3":   round(sum_vol, 2),
                "pct_media":       pct_prov,
                "color":           col_p,
                "etiqueta":        etq_p,
                "fuente":          f"Boletín Hidrológico Semanal — MITECO ({FECHA_DATOS})",
                "embalses":        lista_emb,
            }, f, ensure_ascii=False, indent=2)

        # Entrada para el mapa nacional
        provincias_nacional.append({
            "id":                id_prov,
            "nombre":            prov["nombre"],
            "comunidad":         prov["comunidad"],
            "lat":               prov["lat"],
            "lon":               prov["lon"],
            "pct":               pct_prov,
            "color":             col_p,
            "etiqueta":          etq_p,
            "capacidad_total_hm3": round(sum_cap, 1),
            "volumen_total_hm3":   round(sum_vol, 2),
            "total_embalses":    len(lista_emb),
            "url_detalle":       f"embalses/{id_prov}.html",
            "datos_disponibles": tiene_datos,
        })

        marca = "✓" if tiene_datos else "·"
        val   = f"{pct_prov}%" if pct_prov is not None else "sin datos"
        print(f"  {marca} {prov['nombre']:20s}: {val}")

    # JSON nacional
    with open("docs/embalses_nacional.json", "w", encoding="utf-8") as f:
        json.dump({
            "ultima_actualizacion": ahora.isoformat(),
            "fecha_legible":   FECHA_DATOS,
            "fuente":          "Boletín Hidrológico Semanal — MITECO",
            "provincias":      provincias_nacional,
        }, f, ensure_ascii=False, indent=2)

    con_datos = sum(1 for p in provincias_nacional if p["datos_disponibles"])
    print(f"\n✓ {len(provincias_nacional)} provincias generadas ({con_datos} con datos, {len(provincias_nacional)-con_datos} pendientes)")
    print("=" * 65)


if __name__ == "__main__":
    procesar()
