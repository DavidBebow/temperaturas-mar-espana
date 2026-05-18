"""
obtener_embalses.py — Embalses España por Provincia
====================================================
Fuente oficial: Boletín Hidrológico Semanal MITECO
  ZIP: BD-Embalses_1988-20XX.zip  (se actualiza cada martes)
  Contiene: BD-embalses.mdb (Microsoft Access)
  Leído con: mdbtools (apt install mdbtools, disponible en ubuntu-latest)

Estrategia:
  1. Descarga el ZIP histórico del MITECO (intenta varios años)
  2. Extrae el .mdb con zipfile
  3. Exporta la tabla a CSV con mdb-export (mdbtools)
  4. Filtra el dato más reciente de cada embalse
  5. Cruza con el diccionario provincia → embalses
  6. Genera docs/embalses_nacional.json  y  docs/embalses/{provincia}.json

Dependencias (GitHub Actions):
  pip install requests
  sudo apt-get install -y mdbtools

Ejecución local:
  python scripts/obtener_embalses.py
"""

import csv
import io
import json
import os
import subprocess
import tempfile
import zipfile
from datetime import datetime, date
import requests

# ─────────────────────────────────────────────────────────────────────────────
# FUENTE MITECO — ZIP histórico acumulativo, actualizado cada martes
# El nombre varía según el año de publicación. Probamos todos los recientes.
# ─────────────────────────────────────────────────────────────────────────────
ZIP_URLS = [
    "https://www.miteco.gob.es/content/dam/miteco/es/agua/temas/evaluacion-de-los-recursos-hidricos/BD-Embalses_1988-2024.zip",
    "https://www.miteco.gob.es/content/dam/miteco/es/agua/temas/evaluacion-de-los-recursos-hidricos/BD-Embalses_1988-2023.zip",
    "https://www.miteco.gob.es/content/dam/miteco/es/agua/temas/evaluacion-de-los-recursos-hidricos/BD-Embalses_1988-2025.zip",
    "https://www.miteco.gob.es/content/dam/miteco/es/agua/temas/evaluacion-de-los-recursos-hidricos/BD-Embalses_1988-2022.zip",
]
CABECERA = {"User-Agent": "Mozilla/5.0 (compatible; calentamientoglobal.es)"}


# ─────────────────────────────────────────────────────────────────────────────
# DICCIONARIO MAESTRO: PROVINCIA → EMBALSES
#
# Fuente: MITECO Inventario de Presas y Embalses + Boletín Hidrológico.
# Solo embalses > 5 hm³ (los que aparecen en el Boletín).
# Nombre en MAYÚSCULAS exactamente como figura en BD-embalses.mdb.
# ─────────────────────────────────────────────────────────────────────────────
PROVINCIAS = {

    # ── MURCIA ──────────────────────────────────────────────────────────────
    "murcia": {
        "nombre": "Murcia",
        "comunidad": "Región de Murcia",
        "id_comunidad": "murcia",
        "embalses": [
            {"id":"alfonso_xiii",  "nombre":"Alfonso XIII",  "buscar":["ALFONSO XIII"],   "rio":"Quípar",       "municipio":"Calasparra",          "capacidad_hm3":22.0,  "lat":38.214,"lon":-1.728},
            {"id":"algeciras",     "nombre":"Algeciras",     "buscar":["ALGECIRAS"],      "rio":"Guadalentín",  "municipio":"Lorca",               "capacidad_hm3":45.0,  "lat":37.710,"lon":-1.870},
            {"id":"argos",         "nombre":"Argos",         "buscar":["ARGOS"],          "rio":"Argos",        "municipio":"Caravaca de la Cruz",  "capacidad_hm3":10.7,  "lat":38.338,"lon":-1.907},
            {"id":"la_cierva",     "nombre":"La Cierva",     "buscar":["LA CIERVA","CIERVA"], "rio":"Segura",   "municipio":"Ojós",                "capacidad_hm3":7.3,   "lat":38.075,"lon":-1.592},
            {"id":"puentes",       "nombre":"Puentes",       "buscar":["PUENTES"],        "rio":"Guadalentín",  "municipio":"Lorca",               "capacidad_hm3":26.0,  "lat":37.776,"lon":-1.787},
            {"id":"santomera",     "nombre":"Santomera",     "buscar":["SANTOMERA"],      "rio":"Rambla Salada","municipio":"Santomera",           "capacidad_hm3":17.9,  "lat":38.072,"lon":-1.057},
            {"id":"valdeinfierno", "nombre":"Valdeinfierno", "buscar":["VALDEINFIERNO"],  "rio":"Luchena",      "municipio":"Lorca",               "capacidad_hm3":11.3,  "lat":37.953,"lon":-1.872},
            {"id":"mula",          "nombre":"Mula",          "buscar":["MULA"],           "rio":"Mula",         "municipio":"Mula",                "capacidad_hm3":21.0,  "lat":38.052,"lon":-1.496},
            {"id":"pliego",        "nombre":"Pliego",        "buscar":["PLIEGO"],         "rio":"Pliego",       "municipio":"Pliego",              "capacidad_hm3":3.6,   "lat":38.009,"lon":-1.558},
        ],
    },

    # ── MADRID ───────────────────────────────────────────────────────────────
    "madrid": {
        "nombre": "Madrid",
        "comunidad": "Comunidad de Madrid",
        "id_comunidad": "madrid",
        "embalses": [
            {"id":"el_atazar",     "nombre":"El Atazar",     "buscar":["ATAZAR","EL ATAZAR"],      "rio":"Lozoya",    "municipio":"Atazar",       "capacidad_hm3":425.3, "lat":40.903,"lon":-3.578},
            {"id":"el_vado",       "nombre":"El Vado",       "buscar":["VADO","EL VADO"],          "rio":"Jarama",    "municipio":"Campillo Ranas","capacidad_hm3":55.1,  "lat":40.918,"lon":-3.322},
            {"id":"el_villar",     "nombre":"El Villar",     "buscar":["VILLAR","EL VILLAR"],      "rio":"Lozoya",    "municipio":"Buitrago",     "capacidad_hm3":22.5,  "lat":40.913,"lon":-3.631},
            {"id":"valmayor",      "nombre":"Valmayor",      "buscar":["VALMAYOR"],               "rio":"Aulencia",  "municipio":"Valdemorillo", "capacidad_hm3":124.4, "lat":40.535,"lon":-4.052},
            {"id":"el_pardo",      "nombre":"El Pardo",      "buscar":["PARDO","EL PARDO"],        "rio":"Manzanares","municipio":"El Pardo",     "capacidad_hm3":41.7,  "lat":40.541,"lon":-3.780},
            {"id":"santillana",    "nombre":"Santillana",    "buscar":["SANTILLANA"],             "rio":"Manzanares","municipio":"Manzanares RV", "capacidad_hm3":91.0,  "lat":40.727,"lon":-3.891},
            {"id":"navacerrada",   "nombre":"Navacerrada",   "buscar":["NAVACERRADA"],            "rio":"Acedera",   "municipio":"Navacerrada",  "capacidad_hm3":16.0,  "lat":40.789,"lon":-4.004},
            {"id":"pinilla",       "nombre":"Pinilla",       "buscar":["PINILLA"],                "rio":"Lozoya",    "municipio":"Pinilla",      "capacidad_hm3":38.0,  "lat":40.990,"lon":-3.685},
            {"id":"riosequillo",   "nombre":"Riosequillo",   "buscar":["RIOSEQUILLO"],            "rio":"Jarama",    "municipio":"Buitrago",     "capacidad_hm3":41.3,  "lat":40.974,"lon":-3.519},
        ],
    },

    # ── SEVILLA ──────────────────────────────────────────────────────────────
    "sevilla": {
        "nombre": "Sevilla",
        "comunidad": "Andalucía",
        "id_comunidad": "andalucia",
        "embalses": [
            {"id":"aracena",       "nombre":"Aracena",       "buscar":["ARACENA"],        "rio":"Rivera de Huelva","municipio":"Aracena",     "capacidad_hm3":127.0, "lat":37.879,"lon":-6.604},
            {"id":"la_minilla",    "nombre":"La Minilla",    "buscar":["LA MINILLA","MINILLA"], "rio":"Rivera Huelva","municipio":"Real de la Jara","capacidad_hm3":197.0, "lat":37.803,"lon":-5.913},
            {"id":"el_gergal",     "nombre":"El Gergal",     "buscar":["GERGAL","EL GERGAL"],  "rio":"Cala",       "municipio":"Guillena",    "capacidad_hm3":82.2,  "lat":37.665,"lon":-6.025},
            {"id":"melonares",     "nombre":"Melonares",     "buscar":["MELONARES"],      "rio":"Rivera Huelva","municipio":"Guillena",    "capacidad_hm3":168.0, "lat":37.721,"lon":-6.041},
            {"id":"charco_redondo","nombre":"Charco Redondo","buscar":["CHARCO REDONDO"], "rio":"Torre",        "municipio":"Los Barrios", "capacidad_hm3":32.0,  "lat":36.220,"lon":-5.617},
        ],
    },

    # ── CÓRDOBA ──────────────────────────────────────────────────────────────
    "cordoba": {
        "nombre": "Córdoba",
        "comunidad": "Andalucía",
        "id_comunidad": "andalucia",
        "embalses": [
            {"id":"iznajar",       "nombre":"Iznájar",       "buscar":["IZNAJAR","IZNÁJAR"],       "rio":"Genil",     "municipio":"Iznájar",     "capacidad_hm3":981.1, "lat":37.267,"lon":-4.310},
            {"id":"malpasillo",    "nombre":"Malpasillo",    "buscar":["MALPASILLO"],              "rio":"Genil",     "municipio":"Rute",        "capacidad_hm3":8.1,   "lat":37.327,"lon":-4.506},
            {"id":"cordobilla",    "nombre":"Cordobilla",    "buscar":["CORDOBILLA"],              "rio":"Genil",     "municipio":"Puente Genil", "capacidad_hm3":57.5,  "lat":37.417,"lon":-4.751},
            {"id":"bembezar",      "nombre":"Bembézar",      "buscar":["BEMBEZAR","BEMBÉZAR"],     "rio":"Bembézar",  "municipio":"Hornachuelos","capacidad_hm3":259.0, "lat":37.834,"lon":-5.247},
            {"id":"san_rafael",    "nombre":"San Rafael",    "buscar":["SAN RAFAEL"],              "rio":"Guadalmellato","municipio":"Córdoba",  "capacidad_hm3":58.0,  "lat":37.901,"lon":-4.830},
            {"id":"la_breña_ii",   "nombre":"La Breña II",   "buscar":["BREÑA II","LA BREÑA II"],  "rio":"Bembézar",  "municipio":"Hornachuelos","capacidad_hm3":823.0, "lat":37.885,"lon":-5.164},
        ],
    },

    # ── GRANADA ──────────────────────────────────────────────────────────────
    "granada": {
        "nombre": "Granada",
        "comunidad": "Andalucía",
        "id_comunidad": "andalucia",
        "embalses": [
            {"id":"rules",         "nombre":"Rules",         "buscar":["RULES"],          "rio":"Guadalfeo",  "municipio":"Vélez de Benaudalla","capacidad_hm3":120.0, "lat":36.814,"lon":-3.573},
            {"id":"los_bermejales","nombre":"Los Bermejales","buscar":["BERMEJALES","LOS BERMEJALES"],"rio":"Cacín","municipio":"Arenas del Rey","capacidad_hm3":90.7,  "lat":36.987,"lon":-4.044},
            {"id":"canales",       "nombre":"Canales",       "buscar":["CANALES"],        "rio":"Genil",      "municipio":"Güéjar Sierra",   "capacidad_hm3":70.3,  "lat":37.138,"lon":-3.558},
            {"id":"quéntar",       "nombre":"Quéntar",       "buscar":["QUENTAR","QUÉNTAR"], "rio":"Aguas Blancas","municipio":"Quéntar",    "capacidad_hm3":14.8,  "lat":37.196,"lon":-3.569},
            {"id":"cubillas",      "nombre":"Cubillas",      "buscar":["CUBILLAS"],       "rio":"Cubillas",   "municipio":"Iznalloz",        "capacidad_hm3":23.3,  "lat":37.481,"lon":-3.634},
        ],
    },

    # ── MÁLAGA ───────────────────────────────────────────────────────────────
    "malaga": {
        "nombre": "Málaga",
        "comunidad": "Andalucía",
        "id_comunidad": "andalucia",
        "embalses": [
            {"id":"la_vinuela",    "nombre":"La Viñuela",    "buscar":["VINUELA","VIÑUELA","LA VIÑUELA"], "rio":"Vélez","municipio":"La Viñuela","capacidad_hm3":168.9, "lat":36.871,"lon":-4.149},
            {"id":"guadalteba",    "nombre":"Guadalteba",    "buscar":["GUADALTEBA"],     "rio":"Guadalteba","municipio":"Ardales",      "capacidad_hm3":122.2, "lat":36.887,"lon":-4.885},
            {"id":"guadalhorce",   "nombre":"Guadalhorce",   "buscar":["GUADALHORCE"],    "rio":"Turón",    "municipio":"Ardales",      "capacidad_hm3":50.7,  "lat":36.862,"lon":-4.857},
            {"id":"conde_guadalhorce","nombre":"Conde Guadalhorce","buscar":["CONDE GUADALHORCE","CONDE DEL GUADALHORCE"],"rio":"Guadalhorce","municipio":"Álora","capacidad_hm3":135.8,"lat":36.864,"lon":-4.793},
        ],
    },

    # ── JAÉN ─────────────────────────────────────────────────────────────────
    "jaen": {
        "nombre": "Jaén",
        "comunidad": "Andalucía",
        "id_comunidad": "andalucia",
        "embalses": [
            {"id":"el_tranco",     "nombre":"El Tranco",     "buscar":["TRANCO","EL TRANCO"],     "rio":"Guadalquivir","municipio":"Hornos",   "capacidad_hm3":500.0, "lat":38.039,"lon":-2.803},
            {"id":"quiebrajano",   "nombre":"Quiebrajano",   "buscar":["QUIEBRAJANO"],            "rio":"Quiebrajano","municipio":"Jaén",     "capacidad_hm3":29.1,  "lat":37.795,"lon":-3.745},
            {"id":"jandula",       "nombre":"Jándula",       "buscar":["JANDULA","JÁNDULA"],      "rio":"Jándula",   "municipio":"Andújar",  "capacidad_hm3":322.6, "lat":38.177,"lon":-4.100},
            {"id":"el_rumblar",    "nombre":"El Rumblar",    "buscar":["RUMBLAR","EL RUMBLAR"],   "rio":"Rumblar",   "municipio":"Baños Encina","capacidad_hm3":89.5, "lat":38.228,"lon":-3.796},
        ],
    },

    # ── BADAJOZ ──────────────────────────────────────────────────────────────
    "badajoz": {
        "nombre": "Badajoz",
        "comunidad": "Extremadura",
        "id_comunidad": "extremadura",
        "embalses": [
            {"id":"garcia_sola",   "nombre":"García Sola",   "buscar":["GARCIA SOLA","GARCÍA SOLA","ORELLANA"], "rio":"Guadiana","municipio":"Orellana la Vieja","capacidad_hm3":858.0,"lat":39.016,"lon":-5.540},
            {"id":"zújar",         "nombre":"Zújar",         "buscar":["ZUJAR","ZÚJAR"],          "rio":"Zújar",    "municipio":"Capilla",     "capacidad_hm3":309.0, "lat":38.717,"lon":-5.157},
            {"id":"la_serena",     "nombre":"La Serena",     "buscar":["LA SERENA","SERENA"],      "rio":"Zújar",    "municipio":"Zalamea Serena","capacidad_hm3":3219.0,"lat":38.857,"lon":-5.470},
            {"id":"cíjara",        "nombre":"Cíjara",        "buscar":["CIJARA","CÍJARA"],         "rio":"Guadiana", "municipio":"Herrera del Duque","capacidad_hm3":1617.0,"lat":39.303,"lon":-5.010},
            {"id":"valdecañas",    "nombre":"Valdecañas",    "buscar":["VALDECANAS","VALDECAÑAS"],  "rio":"Tajo",     "municipio":"Berrocalejo","capacidad_hm3":1446.0, "lat":39.817,"lon":-5.440},
        ],
    },

    # ── CÁCERES ───────────────────────────────────────────────────────────────
    "caceres": {
        "nombre": "Cáceres",
        "comunidad": "Extremadura",
        "id_comunidad": "extremadura",
        "embalses": [
            {"id":"alcantara",     "nombre":"Alcántara",     "buscar":["ALCANTARA","ALCÁNTARA","JOSE M ORIOL"], "rio":"Tajo","municipio":"Alcántara","capacidad_hm3":3162.0,"lat":39.728,"lon":-6.892},
            {"id":"borbollon",     "nombre":"Borbollón",     "buscar":["BORBOLLON","BORBOLLÓN"],  "rio":"Árrago",   "municipio":"Moraleja",    "capacidad_hm3":109.2, "lat":40.141,"lon":-6.557},
            {"id":"gabriel_galan", "nombre":"Gabriel y Galán","buscar":["GABRIEL Y GALAN","GABRIEL GALAN"],"rio":"Alagón","municipio":"Guijo Granadilla","capacidad_hm3":925.0,"lat":40.218,"lon":-6.086},
        ],
    },

    # ── TOLEDO ────────────────────────────────────────────────────────────────
    "toledo": {
        "nombre": "Toledo",
        "comunidad": "Castilla-La Mancha",
        "id_comunidad": "castilla_mancha",
        "embalses": [
            {"id":"azutan",        "nombre":"Azután",        "buscar":["AZUTAN","AZUTÁN"],         "rio":"Tajo",     "municipio":"Azután",      "capacidad_hm3":316.0, "lat":39.791,"lon":-5.143},
            {"id":"castillo_buen_agua","nombre":"Castillo Buen Agua","buscar":["CASTILLO BUEN","BUEN AGUA"],"rio":"Torcón","municipio":"Gálvez","capacidad_hm3":46.9,"lat":39.568,"lon":-4.448},
        ],
    },

    # ── CIUDAD REAL ───────────────────────────────────────────────────────────
    "ciudad_real": {
        "nombre": "Ciudad Real",
        "comunidad": "Castilla-La Mancha",
        "id_comunidad": "castilla_mancha",
        "embalses": [
            {"id":"puente_nuevo",  "nombre":"Puente Nuevo",  "buscar":["PUENTE NUEVO"],            "rio":"Guadiana Menor","municipio":"Puertollano","capacidad_hm3":50.0,"lat":38.646,"lon":-4.148},
            {"id":"gasset",        "nombre":"Gasset",        "buscar":["GASSET"],                  "rio":"Jabalón",  "municipio":"Ciudad Real",  "capacidad_hm3":41.3,  "lat":38.932,"lon":-3.784},
        ],
    },

    # ── ALBACETE ──────────────────────────────────────────────────────────────
    "albacete": {
        "nombre": "Albacete",
        "comunidad": "Castilla-La Mancha",
        "id_comunidad": "castilla_mancha",
        "embalses": [
            {"id":"talave",        "nombre":"Talave",        "buscar":["TALAVE"],                  "rio":"Mundo",    "municipio":"Letur",       "capacidad_hm3":34.0,  "lat":38.373,"lon":-2.130},
            {"id":"camarillas",    "nombre":"Camarillas",    "buscar":["CAMARILLAS"],              "rio":"Mundo",    "municipio":"Isso",        "capacidad_hm3":35.4,  "lat":38.440,"lon":-1.886},
            {"id":"fuensanta",     "nombre":"Fuensanta",     "buscar":["FUENSANTA"],               "rio":"Segura",   "municipio":"Yeste",       "capacidad_hm3":210.7, "lat":38.334,"lon":-2.115},
        ],
    },

    # ── CUENCA ────────────────────────────────────────────────────────────────
    "cuenca": {
        "nombre": "Cuenca",
        "comunidad": "Castilla-La Mancha",
        "id_comunidad": "castilla_mancha",
        "embalses": [
            {"id":"alarcon",       "nombre":"Alarcón",       "buscar":["ALARCON","ALARCÓN"],        "rio":"Júcar",    "municipio":"Alarcón",     "capacidad_hm3":1118.0,"lat":39.554,"lon":-2.100},
            {"id":"contreras",     "nombre":"Contreras",     "buscar":["CONTRERAS"],               "rio":"Cabriel",  "municipio":"Contreras",   "capacidad_hm3":852.0, "lat":39.540,"lon":-1.481},
            {"id":"buendia",       "nombre":"Buendía",       "buscar":["BUENDIA","BUENDÍA"],        "rio":"Guadiela", "municipio":"Buendía",     "capacidad_hm3":1640.0,"lat":40.391,"lon":-2.718},
        ],
    },

    # ── GUADALAJARA ───────────────────────────────────────────────────────────
    "guadalajara": {
        "nombre": "Guadalajara",
        "comunidad": "Castilla-La Mancha",
        "id_comunidad": "castilla_mancha",
        "embalses": [
            {"id":"entrepeñas",    "nombre":"Entrepeñas",    "buscar":["ENTREPEÑAS","ENTREPENAS"],  "rio":"Tajo",     "municipio":"Sacedón",     "capacidad_hm3":835.0, "lat":40.545,"lon":-2.691},
            {"id":"bolarque",      "nombre":"Bolarque",      "buscar":["BOLARQUE"],                "rio":"Tajo",     "municipio":"Bolarque",    "capacidad_hm3":31.5,  "lat":40.371,"lon":-2.825},
        ],
    },

    # ── VALENCIA ──────────────────────────────────────────────────────────────
    "valencia": {
        "nombre": "Valencia",
        "comunidad": "Comunidad Valenciana",
        "id_comunidad": "c_valenciana",
        "embalses": [
            {"id":"tous",          "nombre":"Tous",          "buscar":["TOUS"],                    "rio":"Júcar",    "municipio":"Tous",        "capacidad_hm3":377.0, "lat":39.194,"lon":-0.832},
            {"id":"forata",        "nombre":"Forata",        "buscar":["FORATA"],                  "rio":"Magro",    "municipio":"Yátova",      "capacidad_hm3":37.2,  "lat":39.392,"lon":-0.946},
            {"id":"generalísimo",  "nombre":"Generalísimo",  "buscar":["GENERALISIMO","GENERALÍSIMO","BENIARRÉS"],"rio":"Serpis","municipio":"Beniarrés","capacidad_hm3":32.0,"lat":38.836,"lon":-0.379},
            {"id":"cofrentes",     "nombre":"Cofrentes",     "buscar":["COFRENTES"],               "rio":"Júcar",    "municipio":"Cofrentes",   "capacidad_hm3":47.0,  "lat":39.183,"lon":-1.130},
        ],
    },

    # ── ALICANTE ──────────────────────────────────────────────────────────────
    "alicante": {
        "nombre": "Alicante",
        "comunidad": "Comunidad Valenciana",
        "id_comunidad": "c_valenciana",
        "embalses": [
            {"id":"amadorio",      "nombre":"Amadorio",      "buscar":["AMADORIO"],                "rio":"Amadorio", "municipio":"Villajoyosa", "capacidad_hm3":17.0,  "lat":38.511,"lon":-0.245},
            {"id":"guadalest",     "nombre":"Guadalest",     "buscar":["GUADALEST"],               "rio":"Guadalest","municipio":"Guadalest",   "capacidad_hm3":13.3,  "lat":38.671,"lon":-0.137},
            {"id":"crevillente",   "nombre":"Crevillente",   "buscar":["CREVILLENTE"],             "rio":"Vinalopó", "municipio":"Crevillente", "capacidad_hm3":16.0,  "lat":38.191,"lon":-0.828},
        ],
    },

    # ── CASTELLÓN ─────────────────────────────────────────────────────────────
    "castellon": {
        "nombre": "Castellón",
        "comunidad": "Comunidad Valenciana",
        "id_comunidad": "c_valenciana",
        "embalses": [
            {"id":"sichar",        "nombre":"Sichar",        "buscar":["SICHAR"],                  "rio":"Mijares",  "municipio":"Espadilla",   "capacidad_hm3":49.3,  "lat":39.971,"lon":-0.446},
            {"id":"maria_cristina","nombre":"María Cristina","buscar":["MARIA CRISTINA","MARÍA CRISTINA"],"rio":"Mijares","municipio":"Alcora","capacidad_hm3":21.0,  "lat":40.032,"lon":-0.271},
        ],
    },

    # ── ZARAGOZA ──────────────────────────────────────────────────────────────
    "zaragoza": {
        "nombre": "Zaragoza",
        "comunidad": "Aragón",
        "id_comunidad": "aragon",
        "embalses": [
            {"id":"mequinenza",    "nombre":"Mequinenza",    "buscar":["MEQUINENZA"],              "rio":"Ebro",     "municipio":"Mequinenza",  "capacidad_hm3":1534.0,"lat":41.381,"lon":0.276},
            {"id":"ribarroja",     "nombre":"Ribarroja",     "buscar":["RIBARROJA","RIBA-ROJA"],   "rio":"Ebro",     "municipio":"Ribaroja",    "capacidad_hm3":209.5, "lat":41.292,"lon":0.490},
            {"id":"caspe",         "nombre":"Caspe",         "buscar":["CASPE"],                  "rio":"Guadalope","municipio":"Caspe",       "capacidad_hm3":81.8,  "lat":41.270,"lon":-0.085},
            {"id":"la_loteta",     "nombre":"La Loteta",     "buscar":["LA LOTETA","LOTETA"],       "rio":"—",        "municipio":"Pradilla",    "capacidad_hm3":103.0, "lat":41.760,"lon":-1.331},
        ],
    },

    # ── HUESCA ────────────────────────────────────────────────────────────────
    "huesca": {
        "nombre": "Huesca",
        "comunidad": "Aragón",
        "id_comunidad": "aragon",
        "embalses": [
            {"id":"mediano",       "nombre":"Mediano",       "buscar":["MEDIANO"],                 "rio":"Cinca",    "municipio":"Mediano",     "capacidad_hm3":436.0, "lat":42.269,"lon":0.146},
            {"id":"el_grado",      "nombre":"El Grado",      "buscar":["GRADO","EL GRADO"],         "rio":"Cinca",    "municipio":"El Grado",    "capacidad_hm3":400.0, "lat":42.136,"lon":0.171},
            {"id":"bubal",         "nombre":"Búbal",         "buscar":["BUBAL","BÚBAL"],            "rio":"Gállego",  "municipio":"Biescas",     "capacidad_hm3":64.2,  "lat":42.617,"lon":-0.350},
            {"id":"lanuza",        "nombre":"Lanuza",        "buscar":["LANUZA"],                  "rio":"Gállego",  "municipio":"Sallent",     "capacidad_hm3":16.9,  "lat":42.728,"lon":-0.400},
            {"id":"yesa",          "nombre":"Yesa",          "buscar":["YESA"],                    "rio":"Aragón",   "municipio":"Yesa",        "capacidad_hm3":446.8, "lat":42.618,"lon":-1.180},
            {"id":"sotonera",      "nombre":"La Sotonera",   "buscar":["LA SOTONERA","SOTONERA"],   "rio":"Sotón",    "municipio":"Alcalá Gurrea","capacidad_hm3":189.4,"lat":42.136,"lon":-0.678},
        ],
    },

    # ── TERUEL ────────────────────────────────────────────────────────────────
    "teruel": {
        "nombre": "Teruel",
        "comunidad": "Aragón",
        "id_comunidad": "aragon",
        "embalses": [
            {"id":"camarena",      "nombre":"Camarena",      "buscar":["CAMARENA"],                "rio":"Alfambra",  "municipio":"Camarena la Sierra","capacidad_hm3":34.5,"lat":40.244,"lon":-1.089},
            {"id":"cueva_foradada","nombre":"Cueva Foradada","buscar":["CUEVA FORADADA"],          "rio":"Martín",   "municipio":"Oliete",      "capacidad_hm3":16.9,  "lat":40.996,"lon":-0.628},
            {"id":"pena",          "nombre":"Pena",          "buscar":["PENA","EMBALSE DE PENA"],  "rio":"Pena",     "municipio":"Beceite",     "capacidad_hm3":18.0,  "lat":40.884,"lon":0.013},
        ],
    },

    # ── LLEIDA ────────────────────────────────────────────────────────────────
    "lleida": {
        "nombre": "Lleida",
        "comunidad": "Cataluña",
        "id_comunidad": "cataluna",
        "embalses": [
            {"id":"oliana",        "nombre":"Oliana",        "buscar":["OLIANA"],                  "rio":"Segre",    "municipio":"Oliana",      "capacidad_hm3":101.3, "lat":42.073,"lon":1.371},
            {"id":"rialb",         "nombre":"Rialb",         "buscar":["RIALB"],                   "rio":"Segre",    "municipio":"Rialb",       "capacidad_hm3":402.9, "lat":42.013,"lon":1.281},
            {"id":"sant_llorenç",  "nombre":"Sant Llorenç",  "buscar":["SANT LLORENÇ","SAN LORENZO DE MONTGAI"],"rio":"Segre","municipio":"Montgai","capacidad_hm3":9.1,"lat":41.962,"lon":1.070},
            {"id":"canelles",      "nombre":"Canelles",      "buscar":["CANELLES"],                "rio":"Noguera Ribagorzana","municipio":"Arén","capacidad_hm3":678.0,"lat":42.052,"lon":0.627},
            {"id":"santa_ana",     "nombre":"Santa Ana",     "buscar":["SANTA ANA"],               "rio":"Noguera Ribagorzana","municipio":"Pont Suert","capacidad_hm3":236.0,"lat":42.357,"lon":0.742},
        ],
    },

    # ── BARCELONA ─────────────────────────────────────────────────────────────
    "barcelona": {
        "nombre": "Barcelona",
        "comunidad": "Cataluña",
        "id_comunidad": "cataluna",
        "embalses": [
            {"id":"la_baells",     "nombre":"La Baells",     "buscar":["LA BAELLS","BAELLS"],       "rio":"Llobregat","municipio":"Berga",       "capacidad_hm3":109.0, "lat":41.955,"lon":1.921},
            {"id":"sant_ponc",     "nombre":"Sant Ponç",     "buscar":["SANT PONÇ","SAN PONÇ"],     "rio":"Cardener", "municipio":"Sant Ponç",   "capacidad_hm3":24.8,  "lat":41.970,"lon":1.667},
            {"id":"susqueda",      "nombre":"Susqueda",      "buscar":["SUSQUEDA"],                "rio":"Ter",      "municipio":"Susqueda",    "capacidad_hm3":233.0, "lat":41.968,"lon":2.538},
        ],
    },

    # ── GIRONA ────────────────────────────────────────────────────────────────
    "girona": {
        "nombre": "Girona",
        "comunidad": "Cataluña",
        "id_comunidad": "cataluna",
        "embalses": [
            {"id":"sau",           "nombre":"Sau",           "buscar":["SAU"],                     "rio":"Ter",      "municipio":"Vilanova de Sau","capacidad_hm3":168.0, "lat":41.984,"lon":2.427},
            {"id":"darnius_boadella","nombre":"Darnius-Boadella","buscar":["DARNIUS","BOADELLA"],   "rio":"Muga",     "municipio":"Darnius",     "capacidad_hm3":61.5,  "lat":42.321,"lon":2.817},
        ],
    },

    # ── TARRAGONA ─────────────────────────────────────────────────────────────
    "tarragona": {
        "nombre": "Tarragona",
        "comunidad": "Cataluña",
        "id_comunidad": "cataluna",
        "embalses": [
            {"id":"riudecanyes",   "nombre":"Riudecanyes",   "buscar":["RIUDECANYES"],             "rio":"Riudecanyes","municipio":"Riudecanyes","capacidad_hm3":8.6,   "lat":41.155,"lon":0.927},
        ],
    },

    # ── LA RIOJA ──────────────────────────────────────────────────────────────
    "la_rioja": {
        "nombre": "La Rioja",
        "comunidad": "La Rioja",
        "id_comunidad": "la_rioja",
        "embalses": [
            {"id":"gonzalez_lacasa","nombre":"González Lacasa","buscar":["GONZALEZ LACASA","GONZÁLEZ LACASA"],"rio":"Iregua","municipio":"Villanueva de Cameros","capacidad_hm3":32.0,"lat":42.245,"lon":-2.631},
            {"id":"mansilla",      "nombre":"Mansilla",      "buscar":["MANSILLA"],                "rio":"Najerilla","municipio":"Mansilla de la Sierra","capacidad_hm3":68.0,"lat":42.175,"lon":-2.905},
        ],
    },

    # ── NAVARRA ───────────────────────────────────────────────────────────────
    "navarra": {
        "nombre": "Navarra",
        "comunidad": "Navarra",
        "id_comunidad": "navarra",
        "embalses": [
            {"id":"irabia",        "nombre":"Irabia",        "buscar":["IRABIA"],                  "rio":"Irati",    "municipio":"Orbaiceta",   "capacidad_hm3":32.8,  "lat":42.960,"lon":-1.159},
            {"id":"itoiz",         "nombre":"Itoiz",         "buscar":["ITOIZ"],                   "rio":"Irati",    "municipio":"Itoiz",       "capacidad_hm3":417.7, "lat":42.750,"lon":-1.435},
            {"id":"alloz",         "nombre":"Alloz",         "buscar":["ALLOZ"],                   "rio":"Salado",   "municipio":"Guesálaz",    "capacidad_hm3":66.2,  "lat":42.693,"lon":-1.950},
            {"id":"eugui",         "nombre":"Eugi",          "buscar":["EUGI","EUGUI"],             "rio":"Arga",     "municipio":"Eugi",        "capacidad_hm3":21.6,  "lat":42.946,"lon":-1.581},
        ],
    },

    # ── PAÍS VASCO ────────────────────────────────────────────────────────────
    "pais_vasco": {
        "nombre": "País Vasco",
        "comunidad": "País Vasco",
        "id_comunidad": "pais_vasco",
        "embalses": [
            {"id":"ullibarri",     "nombre":"Ullíbarri-Gamboa","buscar":["ULLIBARRI","ULLÍBARRI"],  "rio":"Zadorra",  "municipio":"Ullibarri",   "capacidad_hm3":147.0, "lat":42.840,"lon":-2.638},
            {"id":"urrunaga",      "nombre":"Urrunaga",      "buscar":["URRUNAGA"],                "rio":"Santa Engracia","municipio":"Legutiano","capacidad_hm3":71.5,  "lat":42.977,"lon":-2.671},
        ],
    },

    # ── ASTURIAS ──────────────────────────────────────────────────────────────
    "asturias": {
        "nombre": "Asturias",
        "comunidad": "Asturias",
        "id_comunidad": "asturias",
        "embalses": [
            {"id":"tanes",         "nombre":"Tanes",         "buscar":["TANES"],                   "rio":"Nalón",    "municipio":"Caso",        "capacidad_hm3":44.0,  "lat":43.204,"lon":-5.489},
            {"id":"rioseco",       "nombre":"Rioseco",       "buscar":["RIOSECO"],                 "rio":"Narcea",   "municipio":"Belmonte",    "capacidad_hm3":32.5,  "lat":43.292,"lon":-6.571},
            {"id":"calabazos",     "nombre":"Calabazos",     "buscar":["CALABAZOS"],               "rio":"Esva",     "municipio":"Tineo",       "capacidad_hm3":25.4,  "lat":43.391,"lon":-6.479},
        ],
    },

    # ── CANTABRIA ─────────────────────────────────────────────────────────────
    "cantabria": {
        "nombre": "Cantabria",
        "comunidad": "Cantabria",
        "id_comunidad": "cantabria",
        "embalses": [
            {"id":"ebro_cantabria","nombre":"Ebro (Cantabria)","buscar":["EBRO","EMBALSE DEL EBRO"],"rio":"Ebro",    "municipio":"Arija",       "capacidad_hm3":540.0, "lat":42.973,"lon":-4.007},
            {"id":"la_cohilla",    "nombre":"La Cohilla",    "buscar":["LA COHILLA","COHILLA"],     "rio":"Saja",     "municipio":"Ruente",      "capacidad_hm3":16.0,  "lat":43.210,"lon":-4.373},
        ],
    },

    # ── GALICIA ───────────────────────────────────────────────────────────────
    "a_coruña": {
        "nombre": "A Coruña",
        "comunidad": "Galicia",
        "id_comunidad": "galicia",
        "embalses": [
            {"id":"cecebre",       "nombre":"Cecebre",       "buscar":["CECEBRE"],                 "rio":"Mero",     "municipio":"Cambre",      "capacidad_hm3":67.4,  "lat":43.272,"lon":-8.243},
            {"id":"abegondo_cecebre","nombre":"Abegondo-Cecebre","buscar":["ABEGONDO"],            "rio":"Mero",     "municipio":"Abegondo",    "capacidad_hm3":16.4,  "lat":43.241,"lon":-8.306},
        ],
    },
    "lugo": {
        "nombre": "Lugo",
        "comunidad": "Galicia",
        "id_comunidad": "galicia",
        "embalses": [
            {"id":"belesar",       "nombre":"Belesar",       "buscar":["BELESAR"],                 "rio":"Miño",     "municipio":"Chantada",    "capacidad_hm3":654.0, "lat":42.600,"lon":-7.717},
            {"id":"os_peares",     "nombre":"Os Peares",     "buscar":["OS PEARES","PEARES"],       "rio":"Miño",     "municipio":"Os Peares",   "capacidad_hm3":80.0,  "lat":42.420,"lon":-7.855},
        ],
    },
    "ourense": {
        "nombre": "Ourense",
        "comunidad": "Galicia",
        "id_comunidad": "galicia",
        "embalses": [
            {"id":"castrelo_mino", "nombre":"Castrelo de Miño","buscar":["CASTRELO","CASTRELO DE MIÑO"],"rio":"Miño","municipio":"Castrelo de Miño","capacidad_hm3":197.0,"lat":42.246,"lon":-8.058},
            {"id":"lindoso",       "nombre":"Lindoso",       "buscar":["LINDOSO"],                 "rio":"Limia",    "municipio":"Lobios",      "capacidad_hm3":241.0, "lat":41.868,"lon":-8.189},
        ],
    },

    # ── CASTILLA Y LEÓN ───────────────────────────────────────────────────────
    "salamanca": {
        "nombre": "Salamanca",
        "comunidad": "Castilla y León",
        "id_comunidad": "castilla_leon",
        "embalses": [
            {"id":"almendra",      "nombre":"Almendra",      "buscar":["ALMENDRA"],                "rio":"Tormes",   "municipio":"Almendra",    "capacidad_hm3":2648.0,"lat":41.268,"lon":-6.343},
            {"id":"agueda",        "nombre":"Agueda",        "buscar":["AGUEDA","ÁGUEDA"],          "rio":"Águeda",   "municipio":"La Fregeneda","capacidad_hm3":149.0, "lat":41.148,"lon":-6.921},
        ],
    },
    "zamora": {
        "nombre": "Zamora",
        "comunidad": "Castilla y León",
        "id_comunidad": "castilla_leon",
        "embalses": [
            {"id":"villachica",    "nombre":"Villachica",    "buscar":["VILLACHICA"],              "rio":"Esla",     "municipio":"Villachica",  "capacidad_hm3":63.0,  "lat":41.647,"lon":-5.897},
            {"id":"ricobayo",      "nombre":"Ricobayo",      "buscar":["RICOBAYO"],                "rio":"Esla",     "municipio":"Ricobayo",    "capacidad_hm3":1160.0,"lat":41.725,"lon":-5.850},
            {"id":"manzanal_del_barco","nombre":"Manzanal del Barco","buscar":["MANZANAL","MANZANAL DEL BARCO"],"rio":"Tera","municipio":"Manzanal","capacidad_hm3":76.0,"lat":41.924,"lon":-5.892},
        ],
    },
    "valladolid": {
        "nombre": "Valladolid",
        "comunidad": "Castilla y León",
        "id_comunidad": "castilla_leon",
        "embalses": [
            {"id":"riolobos",      "nombre":"Riolobos",      "buscar":["RIOLOBOS"],                "rio":"Zapardiel","municipio":"Nava del Rey", "capacidad_hm3":9.5,  "lat":41.373,"lon":-5.232},
        ],
    },
    "burgos": {
        "nombre": "Burgos",
        "comunidad": "Castilla y León",
        "id_comunidad": "castilla_leon",
        "embalses": [
            {"id":"del_ebro",      "nombre":"Del Ebro",      "buscar":["DEL EBRO"],                "rio":"Ebro",     "municipio":"Arija",       "capacidad_hm3":540.0, "lat":42.973,"lon":-4.007},
            {"id":"sobrón",        "nombre":"Sobrón",        "buscar":["SOBRON","SOBRÓN"],          "rio":"Ebro",     "municipio":"Sobrón",      "capacidad_hm3":20.7,  "lat":42.791,"lon":-3.050},
        ],
    },
    "palencia": {
        "nombre": "Palencia",
        "comunidad": "Castilla y León",
        "id_comunidad": "castilla_leon",
        "embalses": [
            {"id":"requejada",     "nombre":"Requejada",     "buscar":["REQUEJADA"],               "rio":"Pisuerga", "municipio":"Cervera Pisuerga","capacidad_hm3":91.5,"lat":42.879,"lon":-4.503},
        ],
    },
    "leon": {
        "nombre": "León",
        "comunidad": "Castilla y León",
        "id_comunidad": "castilla_leon",
        "embalses": [
            {"id":"barrios_luna",  "nombre":"Barrios de Luna","buscar":["BARRIOS DE LUNA"],        "rio":"Luna",     "municipio":"Los Barrios de Luna","capacidad_hm3":307.5,"lat":42.850,"lon":-5.880},
            {"id":"riaño",         "nombre":"Riaño",         "buscar":["RIANO","RIAÑO"],            "rio":"Esla",     "municipio":"Riaño",       "capacidad_hm3":651.0, "lat":42.979,"lon":-5.005},
            {"id":"porma",         "nombre":"Porma",         "buscar":["PORMA"],                   "rio":"Porma",    "municipio":"Valdehuesa",  "capacidad_hm3":317.9, "lat":43.009,"lon":-5.287},
        ],
    },
    "segovia": {
        "nombre": "Segovia",
        "comunidad": "Castilla y León",
        "id_comunidad": "castilla_leon",
        "embalses": [
            {"id":"el_pontón_alto", "nombre":"El Pontón Alto","buscar":["PONTON ALTO","PONTÓN ALTO"],"rio":"Eresma","municipio":"La Losa",     "capacidad_hm3":25.5,  "lat":40.929,"lon":-4.204},
        ],
    },

    # ── HUELVA ────────────────────────────────────────────────────────────────
    "huelva": {
        "nombre": "Huelva",
        "comunidad": "Andalucía",
        "id_comunidad": "andalucia",
        "embalses": [
            {"id":"el_andévalo",   "nombre":"El Andévalo",   "buscar":["EL ANDEVALO","EL ANDÉVALO","ANDEVALO"],"rio":"Odiel","municipio":"El Granado","capacidad_hm3":159.0,"lat":37.674,"lon":-7.090},
            {"id":"rio_tinto",     "nombre":"Río Tinto",     "buscar":["RIO TINTO","RÍO TINTO"],   "rio":"Tinto",    "municipio":"Nerva",       "capacidad_hm3":54.0,  "lat":37.695,"lon":-6.555},
        ],
    },

    # ── CÁDIZ ─────────────────────────────────────────────────────────────────
    "cadiz": {
        "nombre": "Cádiz",
        "comunidad": "Andalucía",
        "id_comunidad": "andalucia",
        "embalses": [
            {"id":"zahara",        "nombre":"Zahara",        "buscar":["ZAHARA","ZAHARA-EL GASTOR"],"rio":"Guadalete","municipio":"Zahara",     "capacidad_hm3":215.0, "lat":36.837,"lon":-5.428},
            {"id":"bornos",        "nombre":"Bornos",        "buscar":["BORNOS"],                  "rio":"Guadalete","municipio":"Bornos",      "capacidad_hm3":255.0, "lat":36.803,"lon":-5.715},
            {"id":"barbate",       "nombre":"Barbate",       "buscar":["BARBATE"],                 "rio":"Barbate",  "municipio":"Vejer",       "capacidad_hm3":228.0, "lat":36.253,"lon":-5.830},
        ],
    },

    # ── ALMERÍA ───────────────────────────────────────────────────────────────
    "almeria": {
        "nombre": "Almería",
        "comunidad": "Andalucía",
        "id_comunidad": "andalucia",
        "embalses": [
            {"id":"cuevas_almanzora","nombre":"Cuevas Almanzora","buscar":["CUEVAS","CUEVAS DE ALMANZORA"],"rio":"Almanzora","municipio":"Cuevas","capacidad_hm3":177.3,"lat":37.328,"lon":-1.884},
            {"id":"negratín",      "nombre":"Negratín",      "buscar":["NEGRATIN","NEGRATÍN"],     "rio":"Guadiana Menor","municipio":"Freila","capacidad_hm3":567.0, "lat":37.656,"lon":-2.981},
        ],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# MAPEO COMUNIDAD → PROVINCIAS (para el JSON nacional)
# ─────────────────────────────────────────────────────────────────────────────
COMUNIDADES_INFO = {
    "andalucia":      {"nombre": "Andalucía",            "url": "embalses/andalucia.html"},
    "aragon":         {"nombre": "Aragón",               "url": "embalses/aragon.html"},
    "asturias":       {"nombre": "Asturias",             "url": "embalses/asturias.html"},
    "cantabria":      {"nombre": "Cantabria",            "url": "embalses/cantabria.html"},
    "castilla_leon":  {"nombre": "Castilla y León",      "url": "embalses/castilla_leon.html"},
    "castilla_mancha":{"nombre": "Castilla-La Mancha",   "url": "embalses/castilla_mancha.html"},
    "cataluna":       {"nombre": "Cataluña",             "url": "embalses/cataluna.html"},
    "c_valenciana":   {"nombre": "Comunidad Valenciana", "url": "embalses/c_valenciana.html"},
    "extremadura":    {"nombre": "Extremadura",          "url": "embalses/extremadura.html"},
    "galicia":        {"nombre": "Galicia",              "url": "embalses/galicia.html"},
    "la_rioja":       {"nombre": "La Rioja",             "url": "embalses/la_rioja.html"},
    "madrid":         {"nombre": "Comunidad de Madrid",  "url": "embalses/madrid.html"},
    "murcia":         {"nombre": "Región de Murcia",     "url": "embalses/murcia.html"},
    "navarra":        {"nombre": "Navarra",              "url": "embalses/navarra.html"},
    "pais_vasco":     {"nombre": "País Vasco",           "url": "embalses/pais_vasco.html"},
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def calcular_estado(pct):
    if pct is None:  return "#888888", "Sin datos"
    if pct < 20:     return "#CC2200", "Crítico"
    if pct < 40:     return "#FF8822", "Bajo"
    if pct < 60:     return "#FFCC44", "Moderado"
    if pct < 80:     return "#44AA66", "Bueno"
    return "#0066CC", "Muy bueno"


def to_float(s):
    if s is None: return None
    s = str(s).strip().replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# DESCARGA DEL ZIP MITECO
# ─────────────────────────────────────────────────────────────────────────────

def descargar_zip():
    for url in ZIP_URLS:
        try:
            print(f"  Probando: {url.split('/')[-1]}")
            r = requests.get(url, headers=CABECERA, timeout=120)
            if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/zip"):
                if len(r.content) > 100_000:
                    print(f"  ✓ ZIP descargado ({len(r.content)//1024} KB): {url.split('/')[-1]}")
                    return r.content, url.split('/')[-1]
        except Exception as e:
            print(f"  Error: {e}")
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# LECTURA DEL .MDB CON MDBTOOLS
# ─────────────────────────────────────────────────────────────────────────────

def leer_mdb(zip_bytes):
    """
    Extrae el .mdb del ZIP, lo exporta a CSV con mdb-export,
    devuelve dict: { 'NOMBRE_MAYUS': {'volumen_hm3': float, 'pct': float} }
    solo con el dato más reciente de cada embalse.
    """
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Extraer el .mdb del ZIP
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
        mdb_names = [n for n in z.namelist() if n.lower().endswith('.mdb')]
        if not mdb_names:
            print("  ZIP: no contiene .mdb")
            return {}
        mdb_path = os.path.join(tmpdir, "embalses.mdb")
        z.extractall(tmpdir)
        # Buscar el .mdb extraído
        for root, dirs, files in os.walk(tmpdir):
            for f in files:
                if f.lower().endswith('.mdb'):
                    mdb_path = os.path.join(root, f)
                    break

        print(f"  MDB: {mdb_path}")

        # 2. Listar tablas con mdb-tables
        try:
            result = subprocess.run(
                ["mdb-tables", "-1", mdb_path],
                capture_output=True, text=True, timeout=30
            )
            tables = [t.strip() for t in result.stdout.splitlines() if t.strip()]
            print(f"  Tablas MDB: {tables}")
        except Exception as e:
            print(f"  mdb-tables error: {e}")
            return {}

        # Buscar la tabla de datos (contiene "datos" o "embalses")
        tabla = None
        for t in tables:
            if any(x in t.upper() for x in ["DATO", "EMBALSE", "T_DATOS"]):
                tabla = t
                break
        if not tabla and tables:
            tabla = tables[0]

        if not tabla:
            print("  No se encontró tabla de datos en el MDB")
            return {}

        print(f"  Usando tabla: {tabla}")

        # 3. Exportar a CSV
        try:
            result = subprocess.run(
                ["mdb-export", mdb_path, tabla],
                capture_output=True, text=True, timeout=120
            )
            csv_text = result.stdout
            if not csv_text.strip():
                print("  mdb-export: sin datos")
                return {}
        except Exception as e:
            print(f"  mdb-export error: {e}")
            return {}

    # 4. Parsear CSV
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []
    print(f"  Columnas CSV: {headers[:8]}")

    # Detectar columnas
    col_nombre = col_fecha = col_total = col_actual = None
    for h in headers:
        hu = h.upper().strip()
        if "EMBALSE" in hu and col_nombre is None:
            col_nombre = h
        elif "NOMBRE" in hu and col_nombre is None:
            col_nombre = h
        elif "FECHA" in hu and col_fecha is None:
            col_fecha = h
        elif "TOTAL" in hu and col_total is None:
            col_total = h
        elif "ACTUAL" in hu and col_actual is None:
            col_actual = h

    if not col_nombre:
        print(f"  No se detectó columna nombre. Columnas: {headers}")
        return {}

    print(f"  Mapeando: nombre={col_nombre}, fecha={col_fecha}, total={col_total}, actual={col_actual}")

    datos = {}  # nombre → {fdt, volumen_hm3, pct}

    for row in reader:
        nombre = (row.get(col_nombre) or "").strip().upper()
        if not nombre:
            continue

        fecha_str = (row.get(col_fecha) or "").strip() if col_fecha else ""
        total_f   = to_float(row.get(col_total))  if col_total  else None
        actual_f  = to_float(row.get(col_actual)) if col_actual else None

        # Parsear fecha
        fdt = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                fdt = datetime.strptime(fecha_str, fmt)
                break
            except (ValueError, TypeError):
                continue

        # Calcular pct
        pct = None
        if total_f and total_f > 0 and actual_f is not None:
            pct = round((actual_f / total_f) * 100, 1)

        # Guardar solo el dato más reciente
        if nombre not in datos or (fdt and (datos[nombre]["fdt"] is None or fdt > datos[nombre]["fdt"])):
            datos[nombre] = {
                "fdt":         fdt,
                "fecha":       fdt.strftime("%d/%m/%Y") if fdt else fecha_str,
                "volumen_hm3": round(actual_f, 2) if actual_f is not None else None,
                "pct":         pct,
            }

    if datos:
        fechas_validas = [d["fecha"] for d in datos.values() if d["fecha"]]
        if fechas_validas:
            print(f"  Último dato: {max(fechas_validas)} — {len(datos)} embalses")
    return datos


def buscar(terminos, datos_mdb):
    for t in terminos:
        key = t.upper()
        if key in datos_mdb:
            d = datos_mdb[key]
            return d["volumen_hm3"], d["pct"], d["fecha"]
    for t in terminos:
        key = t.upper()
        for clave, d in datos_mdb.items():
            if key in clave:
                return d["volumen_hm3"], d["pct"], d["fecha"]
    return None, None, None


# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK — datos manuales (solo Murcia por ahora)
# ─────────────────────────────────────────────────────────────────────────────
FALLBACK = {
    "ALFONSO XIII":  {"volumen_hm3": 3.0,  "pct": 13.6},
    "ALGECIRAS":     {"volumen_hm3": 19.0, "pct": 42.2},
    "ARGOS":         {"volumen_hm3": 7.0,  "pct": 65.4},
    "LA CIERVA":     {"volumen_hm3": 5.0,  "pct": 68.5},
    "PUENTES":       {"volumen_hm3": 14.0, "pct": 53.8},
    "SANTOMERA":     {"volumen_hm3": 2.0,  "pct": 11.1},
    "VALDEINFIERNO": {"volumen_hm3": 0.1,  "pct":  0.9},
    "MULA":          {"volumen_hm3": 1.2,  "pct":  5.7},
    "PLIEGO":        {"volumen_hm3": 0.2,  "pct":  5.5},
}
FALLBACK_FECHA = "11/05/2026"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def procesar():
    ahora = datetime.now()
    print("=" * 65)
    print("Embalses España — Boletín Hidrológico MITECO")
    print(f"Ejecución: {ahora.strftime('%d/%m/%Y %H:%M UTC')}")
    print("=" * 65)

    # 1. Descargar ZIP
    print("Descargando BD-Embalses ZIP...")
    zip_bytes, zip_name = descargar_zip()

    usando_fallback = False
    datos_mdb = {}
    fecha_dato = FALLBACK_FECHA

    if zip_bytes:
        print("Leyendo .mdb con mdbtools...")
        datos_mdb = leer_mdb(zip_bytes)
        if len(datos_mdb) < 10:
            print(f"⚠  Solo {len(datos_mdb)} embalses — activando fallback")
            usando_fallback = True
        else:
            # Determinar la fecha del dato más reciente
            fechas = [d["fecha"] for d in datos_mdb.values() if d.get("fecha")]
            fecha_dato = max(fechas) if fechas else FALLBACK_FECHA
    else:
        print("⚠  ZIP no disponible — activando fallback")
        usando_fallback = True

    fuente = "Boletín Hidrológico Semanal — MITECO"
    if usando_fallback:
        fuente += f" (referencia {FALLBACK_FECHA})"

    # 2. Crear carpetas
    os.makedirs("docs/embalses", exist_ok=True)

    # 3. Procesar cada provincia y acumular por comunidad
    resumen_comunidades = {}  # id_comunidad → {vol, cap, provincias}

    for id_prov, prov in PROVINCIAS.items():
        lista_embalses = []
        total_vol = total_cap = 0.0
        provincia_con_datos = False  # solo True si al menos un embalse tiene dato real

        for embalse in prov["embalses"]:
            if usando_fallback:
                vol = pct = None
                for t in embalse["buscar"]:
                    if t in FALLBACK:
                        vol = FALLBACK[t]["volumen_hm3"]
                        pct = FALLBACK[t]["pct"]
                        break
            else:
                vol, pct, _ = buscar(embalse["buscar"], datos_mdb)

            # Si no hay dato real: guardar null, NO inventar un 5%
            if pct is None:
                color, etiqueta = calcular_estado(None)
                lista_embalses.append({
                    "id":            embalse["id"],
                    "nombre":        embalse["nombre"],
                    "rio":           embalse["rio"],
                    "municipio":     embalse["municipio"],
                    "provincia":     prov["nombre"],
                    "lat":           embalse["lat"],
                    "lon":           embalse["lon"],
                    "capacidad_hm3": embalse["capacidad_hm3"],
                    "volumen_hm3":   None,
                    "pct":           None,
                    "color":         color,
                    "etiqueta":      etiqueta,
                })
                total_cap += embalse["capacidad_hm3"]
                continue

            # Dato real disponible
            provincia_con_datos = True
            vol = round(float(vol), 2)
            pct = round(float(pct), 1)
            color, etiqueta = calcular_estado(pct)
            total_vol += vol
            total_cap += embalse["capacidad_hm3"]

            lista_embalses.append({
                "id":            embalse["id"],
                "nombre":        embalse["nombre"],
                "rio":           embalse["rio"],
                "municipio":     embalse["municipio"],
                "provincia":     prov["nombre"],
                "lat":           embalse["lat"],
                "lon":           embalse["lon"],
                "capacidad_hm3": embalse["capacidad_hm3"],
                "volumen_hm3":   vol,
                "pct":           pct,
                "color":         color,
                "etiqueta":      etiqueta,
            })

        # pct_media solo si hay datos reales; si no, None → gris en el mapa
        embalses_con_datos = [e for e in lista_embalses if e["pct"] is not None]
        if embalses_con_datos and total_cap > 0:
            pct_media = round((total_vol / total_cap) * 100, 1)
        else:
            pct_media = None
        color_p, etiq_p = calcular_estado(pct_media)

        # Guardar JSON de provincia
        with open(f"docs/embalses/{id_prov}.json", "w", encoding="utf-8") as f:
            json.dump({
                "ultima_actualizacion": ahora.isoformat(),
                "fecha_legible":        fecha_dato,
                "provincia":            prov["nombre"],
                "comunidad":            prov["comunidad"],
                "total_embalses":       len(lista_embalses),
                "capacidad_total_hm3":  round(total_cap, 1),
                "volumen_total_hm3":    round(total_vol, 2),
                "pct_media":            pct_media,
                "color":                color_p,
                "etiqueta":             etiq_p,
                "fuente":               fuente,
                "embalses":             lista_embalses,
            }, f, ensure_ascii=False, indent=2)

        estado_str = f"{pct_media}%" if pct_media is not None else "sin datos"
        print(f"  ✓ {prov['nombre']:25s}: {estado_str}")

        # Acumular en comunidad SOLO si tiene datos reales
        if provincia_con_datos:
            idc = prov["id_comunidad"]
            if idc not in resumen_comunidades:
                resumen_comunidades[idc] = {"vol": 0.0, "cap": 0.0}
            resumen_comunidades[idc]["vol"] += total_vol
            resumen_comunidades[idc]["cap"] += total_cap

    # 4. Generar embalses_nacional.json
    comunidades_lista = []
    for idc, info in COMUNIDADES_INFO.items():
        if idc in resumen_comunidades:
            r = resumen_comunidades[idc]
            pct = round((r["vol"] / r["cap"]) * 100, 1) if r["cap"] > 0 else None
            color, etiq = calcular_estado(pct)
            tiene_datos = pct is not None
        else:
            pct, color, etiq, tiene_datos = None, "#2a3a4a", "Sin datos", False

        comunidades_lista.append({
            "id":                idc,
            "nombre":            info["nombre"],
            "pct":               pct,
            "color":             color,
            "etiqueta":          etiq,
            "url_detalle":       info["url"],
            "datos_disponibles": tiene_datos,
        })

    with open("docs/embalses_nacional.json", "w", encoding="utf-8") as f:
        json.dump({
            "ultima_actualizacion": ahora.isoformat(),
            "fecha_legible":        fecha_dato,
            "fuente":               fuente,
            "comunidades":          comunidades_lista,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✓ embalses_nacional.json — {len(comunidades_lista)} comunidades")
    print("=" * 65)


if __name__ == "__main__":
    procesar()
