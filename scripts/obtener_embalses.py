"""
obtener_embalses.py — Embalses España por Provincia
====================================================
Fuente: BD-Embalses_1988-2022.zip (MITECO, actualizado cada martes)
  URL estable: https://www.miteco.gob.es/content/dam/miteco/es/agua/
               temas/evaluacion-de-los-recursos-hidricos/
               BD-Embalses_1988-2022.zip
  Contiene: BD-embalses.mdb (Microsoft Access)
  Leído con: mdbtools  →  sudo apt-get install -y mdbtools

El mapa nacional muestra PROVINCIAS (no comunidades autónomas).
Genera:
  docs/embalses_nacional.json   ← lista de provincias para el mapa
  docs/embalses/{provincia}.json ← detalle de cada provincia

Dependencias GitHub Actions:
  sudo apt-get install -y mdbtools
  pip install requests
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
# URL CORRECTA DEL ZIP MITECO  (nombre estable, se actualiza internamente)
# ─────────────────────────────────────────────────────────────────────────────
ZIP_URL = (
    "https://www.miteco.gob.es/content/dam/miteco/es/agua/temas/"
    "evaluacion-de-los-recursos-hidricos/BD-Embalses_1988-2022.zip"
)
CABECERA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# ─────────────────────────────────────────────────────────────────────────────
# PROVINCIAS Y SUS EMBALSES
# Nombres en MAYÚSCULAS igual que en BD-embalses.mdb columna EMBALSE.
# Capacidades y coords verificadas con MITECO/CHSegura.
# ─────────────────────────────────────────────────────────────────────────────
PROVINCIAS = {

    "murcia": {
        "nombre": "Murcia", "comunidad": "Región de Murcia",
        "lat_centro": 37.9, "lon_centro": -1.7,
        "embalses": [
            {"id":"alfonso_xiii",  "nombre":"Alfonso XIII",  "buscar":["ALFONSO XIII"],  "rio":"Quípar",       "municipio":"Calasparra",         "cap":22.0,  "lat":38.214,"lon":-1.728},
            {"id":"algeciras",     "nombre":"Algeciras",     "buscar":["ALGECIRAS"],     "rio":"Guadalentín",  "municipio":"Lorca",              "cap":45.0,  "lat":37.710,"lon":-1.870},
            {"id":"argos",         "nombre":"Argos",         "buscar":["ARGOS"],         "rio":"Argos",        "municipio":"Caravaca de la Cruz", "cap":10.7,  "lat":38.338,"lon":-1.907},
            {"id":"la_cierva",     "nombre":"La Cierva",     "buscar":["LA CIERVA","CIERVA"], "rio":"Segura",  "municipio":"Ojós",               "cap":7.3,   "lat":38.075,"lon":-1.592},
            {"id":"puentes",       "nombre":"Puentes",       "buscar":["PUENTES"],       "rio":"Guadalentín",  "municipio":"Lorca",              "cap":26.0,  "lat":37.776,"lon":-1.787},
            {"id":"santomera",     "nombre":"Santomera",     "buscar":["SANTOMERA"],     "rio":"Rambla Salada","municipio":"Santomera",          "cap":17.9,  "lat":38.072,"lon":-1.057},
            {"id":"valdeinfierno", "nombre":"Valdeinfierno", "buscar":["VALDEINFIERNO"], "rio":"Luchena",      "municipio":"Lorca",              "cap":11.3,  "lat":37.953,"lon":-1.872},
            {"id":"mula",          "nombre":"Mula",          "buscar":["MULA"],          "rio":"Mula",         "municipio":"Mula",               "cap":21.0,  "lat":38.052,"lon":-1.496},
            {"id":"pliego",        "nombre":"Pliego",        "buscar":["PLIEGO"],        "rio":"Pliego",       "municipio":"Pliego",             "cap":3.6,   "lat":38.009,"lon":-1.558},
        ],
    },

    "madrid": {
        "nombre": "Madrid", "comunidad": "Comunidad de Madrid",
        "lat_centro": 40.45, "lon_centro": -3.70,
        "embalses": [
            {"id":"el_atazar",   "nombre":"El Atazar",   "buscar":["EL ATAZAR","ATAZAR"],       "rio":"Lozoya",    "municipio":"Patones",      "cap":425.3,"lat":40.903,"lon":-3.578},
            {"id":"valmayor",    "nombre":"Valmayor",    "buscar":["VALMAYOR"],                 "rio":"Aulencia",  "municipio":"Valdemorillo", "cap":124.4,"lat":40.535,"lon":-4.052},
            {"id":"santillana",  "nombre":"Santillana",  "buscar":["SANTILLANA"],               "rio":"Manzanares","municipio":"Manzanares RV","cap":91.0, "lat":40.727,"lon":-3.891},
            {"id":"el_pardo",    "nombre":"El Pardo",    "buscar":["EL PARDO","PARDO"],          "rio":"Manzanares","municipio":"El Pardo",     "cap":41.7, "lat":40.541,"lon":-3.780},
            {"id":"pinilla",     "nombre":"Pinilla",     "buscar":["PINILLA"],                  "rio":"Lozoya",    "municipio":"Pinilla Valls","cap":38.0, "lat":40.990,"lon":-3.685},
            {"id":"riosequillo", "nombre":"Riosequillo", "buscar":["RIOSEQUILLO"],              "rio":"Jarama",    "municipio":"Buitrago",     "cap":41.3, "lat":40.974,"lon":-3.519},
            {"id":"el_vado",     "nombre":"El Vado",     "buscar":["EL VADO","VADO"],            "rio":"Jarama",    "municipio":"Campillo Ranas","cap":55.1,"lat":40.918,"lon":-3.322},
            {"id":"el_villar",   "nombre":"El Villar",   "buscar":["EL VILLAR","VILLAR"],        "rio":"Lozoya",    "municipio":"Buitrago",     "cap":22.5, "lat":40.913,"lon":-3.631},
        ],
    },

    "sevilla": {
        "nombre": "Sevilla", "comunidad": "Andalucía",
        "lat_centro": 37.4, "lon_centro": -5.9,
        "embalses": [
            {"id":"aracena",    "nombre":"Aracena",    "buscar":["ARACENA"],                 "rio":"R. Huelva", "municipio":"Aracena",    "cap":127.0,"lat":37.879,"lon":-6.604},
            {"id":"la_minilla", "nombre":"La Minilla", "buscar":["LA MINILLA","MINILLA"],     "rio":"R. Huelva", "municipio":"Real Jara",  "cap":197.0,"lat":37.803,"lon":-5.913},
            {"id":"el_gergal",  "nombre":"El Gergal",  "buscar":["EL GERGAL","GERGAL"],       "rio":"Cala",      "municipio":"Guillena",   "cap":82.2, "lat":37.665,"lon":-6.025},
            {"id":"melonares",  "nombre":"Melonares",  "buscar":["MELONARES"],               "rio":"R. Huelva", "municipio":"Guillena",   "cap":168.0,"lat":37.721,"lon":-6.041},
        ],
    },

    "cordoba": {
        "nombre": "Córdoba", "comunidad": "Andalucía",
        "lat_centro": 37.9, "lon_centro": -4.8,
        "embalses": [
            {"id":"iznajar",    "nombre":"Iznájar",    "buscar":["IZNAJAR","IZNÁJAR"],        "rio":"Genil",    "municipio":"Iznájar",    "cap":981.1,"lat":37.267,"lon":-4.310},
            {"id":"bembezar",   "nombre":"Bembézar",   "buscar":["BEMBEZAR","BEMBÉZAR"],      "rio":"Bembézar", "municipio":"Hornachuelos","cap":259.0,"lat":37.834,"lon":-5.247},
            {"id":"la_breña_ii","nombre":"La Breña II","buscar":["BREÑA II","LA BREÑA II"],   "rio":"Bembézar", "municipio":"Hornachuelos","cap":823.0,"lat":37.885,"lon":-5.164},
            {"id":"san_rafael", "nombre":"San Rafael", "buscar":["SAN RAFAEL DEL GUADALMELLATO","SAN RAFAEL"], "rio":"Guadalmellato","municipio":"Córdoba","cap":58.0,"lat":37.901,"lon":-4.830},
        ],
    },

    "granada": {
        "nombre": "Granada", "comunidad": "Andalucía",
        "lat_centro": 37.2, "lon_centro": -3.6,
        "embalses": [
            {"id":"rules",          "nombre":"Rules",          "buscar":["RULES"],              "rio":"Guadalfeo",    "municipio":"Vélez Benaudalla","cap":120.0,"lat":36.814,"lon":-3.573},
            {"id":"los_bermejales", "nombre":"Los Bermejales", "buscar":["BERMEJALES"],          "rio":"Cacín",        "municipio":"Arenas del Rey",  "cap":90.7, "lat":36.987,"lon":-4.044},
            {"id":"canales",        "nombre":"Canales",        "buscar":["CANALES"],            "rio":"Genil",        "municipio":"Güéjar Sierra",   "cap":70.3, "lat":37.138,"lon":-3.558},
            {"id":"negratin",       "nombre":"Negratín",       "buscar":["NEGRATIN","NEGRATÍN"],"rio":"Guadiana Menor","municipio":"Freila",          "cap":567.0,"lat":37.656,"lon":-2.981},
        ],
    },

    "malaga": {
        "nombre": "Málaga", "comunidad": "Andalucía",
        "lat_centro": 36.9, "lon_centro": -4.6,
        "embalses": [
            {"id":"la_vinuela",  "nombre":"La Viñuela",  "buscar":["LA VINUELA","LA VIÑUELA","VIÑUELA"], "rio":"Vélez",     "municipio":"La Viñuela","cap":168.9,"lat":36.871,"lon":-4.149},
            {"id":"guadalteba",  "nombre":"Guadalteba",  "buscar":["GUADALTEBA"],                        "rio":"Guadalteba","municipio":"Ardales",   "cap":122.2,"lat":36.887,"lon":-4.885},
            {"id":"guadalhorce", "nombre":"Guadalhorce", "buscar":["CONDE GUADALHORCE","CONDE DEL GUADALHORCE","GUADALHORCE"], "rio":"Guadalhorce","municipio":"Ardales","cap":135.8,"lat":36.864,"lon":-4.793},
        ],
    },

    "jaen": {
        "nombre": "Jaén", "comunidad": "Andalucía",
        "lat_centro": 37.8, "lon_centro": -3.8,
        "embalses": [
            {"id":"el_tranco","nombre":"El Tranco","buscar":["EL TRANCO","TRANCO"],"rio":"Guadalquivir","municipio":"Hornos","cap":500.0,"lat":38.039,"lon":-2.803},
            {"id":"jandula",  "nombre":"Jándula",  "buscar":["JANDULA","JÁNDULA"],  "rio":"Jándula",     "municipio":"Andújar","cap":322.6,"lat":38.177,"lon":-4.100},
            {"id":"el_rumblar","nombre":"El Rumblar","buscar":["EL RUMBLAR","RUMBLAR"],"rio":"Rumblar","municipio":"Baños Encina","cap":89.5,"lat":38.228,"lon":-3.796},
        ],
    },

    "huelva": {
        "nombre": "Huelva", "comunidad": "Andalucía",
        "lat_centro": 37.6, "lon_centro": -6.9,
        "embalses": [
            {"id":"el_andevalo","nombre":"El Andévalo","buscar":["EL ANDEVALO","EL ANDÉVALO","ANDÉVALO"],"rio":"Odiel","municipio":"El Granado","cap":159.0,"lat":37.674,"lon":-7.090},
            {"id":"rio_tinto",  "nombre":"Río Tinto",  "buscar":["RIO TINTO","RÍO TINTO"],              "rio":"Tinto", "municipio":"Nerva",       "cap":54.0, "lat":37.695,"lon":-6.555},
        ],
    },

    "cadiz": {
        "nombre": "Cádiz", "comunidad": "Andalucía",
        "lat_centro": 36.5, "lon_centro": -5.8,
        "embalses": [
            {"id":"zahara",  "nombre":"Zahara",  "buscar":["ZAHARA","ZAHARA-EL GASTOR"], "rio":"Guadalete","municipio":"Zahara","cap":215.0,"lat":36.837,"lon":-5.428},
            {"id":"bornos",  "nombre":"Bornos",  "buscar":["BORNOS"],                   "rio":"Guadalete","municipio":"Bornos", "cap":255.0,"lat":36.803,"lon":-5.715},
            {"id":"barbate", "nombre":"Barbate", "buscar":["BARBATE"],                  "rio":"Barbate",  "municipio":"Vejer",  "cap":228.0,"lat":36.253,"lon":-5.830},
        ],
    },

    "almeria": {
        "nombre": "Almería", "comunidad": "Andalucía",
        "lat_centro": 37.2, "lon_centro": -2.4,
        "embalses": [
            {"id":"cuevas",  "nombre":"Cuevas Almanzora","buscar":["CUEVAS DE ALMANZORA","CUEVAS ALMANZORA","CUEVAS"],"rio":"Almanzora","municipio":"Cuevas","cap":177.3,"lat":37.328,"lon":-1.884},
            {"id":"benínar", "nombre":"Benínar",          "buscar":["BENINAR","BENÍNAR"],                              "rio":"Adra",      "municipio":"Berja",  "cap":55.9, "lat":36.882,"lon":-2.982},
        ],
    },

    "badajoz": {
        "nombre": "Badajoz", "comunidad": "Extremadura",
        "lat_centro": 38.9, "lon_centro": -6.0,
        "embalses": [
            {"id":"la_serena",  "nombre":"La Serena",  "buscar":["LA SERENA","SERENA"],         "rio":"Zújar",    "municipio":"Zalamea","cap":3219.0,"lat":38.857,"lon":-5.470},
            {"id":"cijara",     "nombre":"Cíjara",     "buscar":["CIJARA","CÍJARA"],             "rio":"Guadiana", "municipio":"Herrera","cap":1617.0,"lat":39.303,"lon":-5.010},
            {"id":"garcia_sola","nombre":"García Sola","buscar":["GARCIA SOLA","GARCÍA SOLA"],   "rio":"Guadiana", "municipio":"Orellana","cap":858.0,"lat":39.016,"lon":-5.540},
            {"id":"zujar",      "nombre":"Zújar",      "buscar":["ZUJAR","ZÚJAR"],               "rio":"Zújar",    "municipio":"Capilla", "cap":309.0,"lat":38.717,"lon":-5.157},
            {"id":"valdecanas", "nombre":"Valdecañas", "buscar":["VALDECANAS","VALDECAÑAS"],     "rio":"Tajo",     "municipio":"Berrocalejo","cap":1446.0,"lat":39.817,"lon":-5.440},
        ],
    },

    "caceres": {
        "nombre": "Cáceres", "comunidad": "Extremadura",
        "lat_centro": 39.8, "lon_centro": -6.4,
        "embalses": [
            {"id":"alcantara",    "nombre":"Alcántara",     "buscar":["ALCANTARA","ALCÁNTARA","JOSE M ORIOL"],"rio":"Tajo",   "municipio":"Alcántara",    "cap":3162.0,"lat":39.728,"lon":-6.892},
            {"id":"gabriel_galan","nombre":"Gabriel y Galán","buscar":["GABRIEL Y GALAN","GABRIEL GALAN"],   "rio":"Alagón", "municipio":"Guijo Granadilla","cap":925.0,"lat":40.218,"lon":-6.086},
        ],
    },

    "toledo": {
        "nombre": "Toledo", "comunidad": "Castilla-La Mancha",
        "lat_centro": 39.8, "lon_centro": -4.0,
        "embalses": [
            {"id":"azutan",  "nombre":"Azután", "buscar":["AZUTAN","AZUTÁN"],   "rio":"Tajo","municipio":"Azután","cap":316.0,"lat":39.791,"lon":-5.143},
        ],
    },

    "cuenca": {
        "nombre": "Cuenca", "comunidad": "Castilla-La Mancha",
        "lat_centro": 40.1, "lon_centro": -2.1,
        "embalses": [
            {"id":"alarcon",    "nombre":"Alarcón",  "buscar":["ALARCON","ALARCÓN"],     "rio":"Júcar",   "municipio":"Alarcón","cap":1118.0,"lat":39.554,"lon":-2.100},
            {"id":"contreras",  "nombre":"Contreras","buscar":["CONTRERAS"],             "rio":"Cabriel", "municipio":"Contreras","cap":852.0,"lat":39.540,"lon":-1.481},
            {"id":"buendia",    "nombre":"Buendía",  "buscar":["BUENDIA","BUENDÍA"],     "rio":"Guadiela","municipio":"Buendía","cap":1640.0,"lat":40.391,"lon":-2.718},
        ],
    },

    "guadalajara": {
        "nombre": "Guadalajara", "comunidad": "Castilla-La Mancha",
        "lat_centro": 40.6, "lon_centro": -3.2,
        "embalses": [
            {"id":"entrepeñas","nombre":"Entrepeñas","buscar":["ENTREPEÑAS","ENTREPENAS"],"rio":"Tajo","municipio":"Sacedón","cap":835.0,"lat":40.545,"lon":-2.691},
        ],
    },

    "albacete": {
        "nombre": "Albacete", "comunidad": "Castilla-La Mancha",
        "lat_centro": 38.9, "lon_centro": -1.9,
        "embalses": [
            {"id":"fuensanta", "nombre":"Fuensanta","buscar":["FUENSANTA"],           "rio":"Segura","municipio":"Yeste",     "cap":210.7,"lat":38.334,"lon":-2.115},
            {"id":"talave",    "nombre":"Talave",   "buscar":["TALAVE"],              "rio":"Mundo", "municipio":"Letur",     "cap":34.0, "lat":38.373,"lon":-2.130},
            {"id":"camarillas","nombre":"Camarillas","buscar":["CAMARILLAS"],         "rio":"Mundo", "municipio":"Isso",      "cap":35.4, "lat":38.440,"lon":-1.886},
        ],
    },

    "valencia": {
        "nombre": "Valencia", "comunidad": "Comunidad Valenciana",
        "lat_centro": 39.5, "lon_centro": -0.6,
        "embalses": [
            {"id":"tous",    "nombre":"Tous",   "buscar":["TOUS"],   "rio":"Júcar","municipio":"Tous",    "cap":377.0,"lat":39.194,"lon":-0.832},
            {"id":"forata",  "nombre":"Forata", "buscar":["FORATA"], "rio":"Magro","municipio":"Yátova",  "cap":37.2, "lat":39.392,"lon":-0.946},
        ],
    },

    "alicante": {
        "nombre": "Alicante", "comunidad": "Comunidad Valenciana",
        "lat_centro": 38.4, "lon_centro": -0.5,
        "embalses": [
            {"id":"amadorio",  "nombre":"Amadorio",  "buscar":["AMADORIO"],  "rio":"Amadorio","municipio":"Villajoyosa","cap":17.0,"lat":38.511,"lon":-0.245},
            {"id":"guadalest", "nombre":"Guadalest", "buscar":["GUADALEST"], "rio":"Guadalest","municipio":"Guadalest", "cap":13.3,"lat":38.671,"lon":-0.137},
        ],
    },

    "castellon": {
        "nombre": "Castellón", "comunidad": "Comunidad Valenciana",
        "lat_centro": 40.1, "lon_centro": -0.1,
        "embalses": [
            {"id":"sichar","nombre":"Sichar","buscar":["SICHAR"],"rio":"Mijares","municipio":"Espadilla","cap":49.3,"lat":39.971,"lon":-0.446},
        ],
    },

    "zaragoza": {
        "nombre": "Zaragoza", "comunidad": "Aragón",
        "lat_centro": 41.6, "lon_centro": -0.9,
        "embalses": [
            {"id":"mequinenza","nombre":"Mequinenza","buscar":["MEQUINENZA"],"rio":"Ebro","municipio":"Mequinenza","cap":1534.0,"lat":41.381,"lon":0.276},
            {"id":"ribarroja", "nombre":"Ribarroja", "buscar":["RIBARROJA"], "rio":"Ebro","municipio":"Riba-roja", "cap":209.5, "lat":41.292,"lon":0.490},
        ],
    },

    "huesca": {
        "nombre": "Huesca", "comunidad": "Aragón",
        "lat_centro": 42.1, "lon_centro": -0.4,
        "embalses": [
            {"id":"mediano", "nombre":"Mediano",     "buscar":["MEDIANO"],        "rio":"Cinca",   "municipio":"Mediano",  "cap":436.0,"lat":42.269,"lon":0.146},
            {"id":"el_grado","nombre":"El Grado",    "buscar":["EL GRADO","GRADO"],"rio":"Cinca",  "municipio":"El Grado", "cap":400.0,"lat":42.136,"lon":0.171},
            {"id":"yesa",    "nombre":"Yesa",         "buscar":["YESA"],           "rio":"Aragón",  "municipio":"Yesa",     "cap":446.8,"lat":42.618,"lon":-1.180},
            {"id":"sotonera","nombre":"La Sotonera",  "buscar":["LA SOTONERA","SOTONERA"],"rio":"Sotón","municipio":"Gurrea","cap":189.4,"lat":42.136,"lon":-0.678},
        ],
    },

    "lleida": {
        "nombre": "Lleida", "comunidad": "Cataluña",
        "lat_centro": 41.9, "lon_centro": 1.1,
        "embalses": [
            {"id":"rialb",    "nombre":"Rialb",    "buscar":["RIALB"],    "rio":"Segre",              "municipio":"Rialb",    "cap":402.9,"lat":42.013,"lon":1.281},
            {"id":"canelles", "nombre":"Canelles", "buscar":["CANELLES"], "rio":"N. Ribagorzana",     "municipio":"Arén",     "cap":678.0,"lat":42.052,"lon":0.627},
            {"id":"oliana",   "nombre":"Oliana",   "buscar":["OLIANA"],   "rio":"Segre",              "municipio":"Oliana",   "cap":101.3,"lat":42.073,"lon":1.371},
        ],
    },

    "barcelona": {
        "nombre": "Barcelona", "comunidad": "Cataluña",
        "lat_centro": 41.6, "lon_centro": 1.9,
        "embalses": [
            {"id":"la_baells","nombre":"La Baells","buscar":["LA BAELLS","BAELLS"],"rio":"Llobregat","municipio":"Berga",    "cap":109.0,"lat":41.955,"lon":1.921},
            {"id":"susqueda", "nombre":"Susqueda", "buscar":["SUSQUEDA"],           "rio":"Ter",       "municipio":"Susqueda","cap":233.0,"lat":41.968,"lon":2.538},
        ],
    },

    "girona": {
        "nombre": "Girona", "comunidad": "Cataluña",
        "lat_centro": 42.0, "lon_centro": 2.8,
        "embalses": [
            {"id":"sau",              "nombre":"Sau",              "buscar":["SAU"],              "rio":"Ter", "municipio":"Vilanova de Sau","cap":168.0,"lat":41.984,"lon":2.427},
            {"id":"darnius_boadella", "nombre":"Darnius-Boadella", "buscar":["DARNIUS","BOADELLA"],"rio":"Muga","municipio":"Darnius",       "cap":61.5, "lat":42.321,"lon":2.817},
        ],
    },

    "la_rioja": {
        "nombre": "La Rioja", "comunidad": "La Rioja",
        "lat_centro": 42.3, "lon_centro": -2.4,
        "embalses": [
            {"id":"gonzalez_lacasa","nombre":"González Lacasa","buscar":["GONZALEZ LACASA","GONZÁLEZ LACASA"],"rio":"Iregua","municipio":"Villanueva Cameros","cap":32.0,"lat":42.245,"lon":-2.631},
            {"id":"mansilla",      "nombre":"Mansilla",       "buscar":["MANSILLA"],                         "rio":"Najerilla","municipio":"Mansilla Sierra","cap":68.0,"lat":42.175,"lon":-2.905},
        ],
    },

    "navarra": {
        "nombre": "Navarra", "comunidad": "Navarra",
        "lat_centro": 42.7, "lon_centro": -1.6,
        "embalses": [
            {"id":"itoiz",  "nombre":"Itoiz",  "buscar":["ITOIZ"],  "rio":"Irati",  "municipio":"Itoiz",    "cap":417.7,"lat":42.750,"lon":-1.435},
            {"id":"alloz",  "nombre":"Alloz",  "buscar":["ALLOZ"],  "rio":"Salado", "municipio":"Guesálaz", "cap":66.2, "lat":42.693,"lon":-1.950},
            {"id":"eugui",  "nombre":"Eugi",   "buscar":["EUGI","EUGUI"], "rio":"Arga","municipio":"Eugi",  "cap":21.6, "lat":42.946,"lon":-1.581},
        ],
    },

    "pais_vasco": {
        "nombre": "País Vasco", "comunidad": "País Vasco",
        "lat_centro": 42.9, "lon_centro": -2.7,
        "embalses": [
            {"id":"ullibarri","nombre":"Ullíbarri-Gamboa","buscar":["ULLIBARRI","ULLÍBARRI-GAMBOA"],"rio":"Zadorra","municipio":"Ullibarri","cap":147.0,"lat":42.840,"lon":-2.638},
            {"id":"urrunaga", "nombre":"Urrunaga",        "buscar":["URRUNAGA"],                     "rio":"Santa Engracia","municipio":"Legutiano","cap":71.5,"lat":42.977,"lon":-2.671},
        ],
    },

    "cantabria": {
        "nombre": "Cantabria", "comunidad": "Cantabria",
        "lat_centro": 43.1, "lon_centro": -4.0,
        "embalses": [
            {"id":"del_ebro","nombre":"Del Ebro","buscar":["DEL EBRO","EBRO"],"rio":"Ebro","municipio":"Arija","cap":540.0,"lat":42.973,"lon":-4.007},
        ],
    },

    "asturias": {
        "nombre": "Asturias", "comunidad": "Asturias",
        "lat_centro": 43.3, "lon_centro": -5.9,
        "embalses": [
            {"id":"tanes",    "nombre":"Tanes",    "buscar":["TANES"],    "rio":"Nalón", "municipio":"Caso",    "cap":44.0,"lat":43.204,"lon":-5.489},
            {"id":"rioseco",  "nombre":"Rioseco",  "buscar":["RIOSECO"],  "rio":"Narcea","municipio":"Belmonte","cap":32.5,"lat":43.292,"lon":-6.571},
            {"id":"calabazos","nombre":"Calabazos","buscar":["CALABAZOS"],"rio":"Esva",  "municipio":"Tineo",   "cap":25.4,"lat":43.391,"lon":-6.479},
        ],
    },

    "leon": {
        "nombre": "León", "comunidad": "Castilla y León",
        "lat_centro": 42.6, "lon_centro": -5.6,
        "embalses": [
            {"id":"barrios_luna","nombre":"Barrios de Luna","buscar":["BARRIOS DE LUNA"],"rio":"Luna","municipio":"Los Barrios","cap":307.5,"lat":42.850,"lon":-5.880},
            {"id":"riano",       "nombre":"Riaño",          "buscar":["RIANO","RIAÑO"],   "rio":"Esla","municipio":"Riaño",      "cap":651.0,"lat":42.979,"lon":-5.005},
            {"id":"porma",       "nombre":"Porma",          "buscar":["PORMA"],           "rio":"Porma","municipio":"Valdehuesa","cap":317.9,"lat":43.009,"lon":-5.287},
        ],
    },

    "zamora": {
        "nombre": "Zamora", "comunidad": "Castilla y León",
        "lat_centro": 41.5, "lon_centro": -5.8,
        "embalses": [
            {"id":"ricobayo","nombre":"Ricobayo","buscar":["RICOBAYO"],"rio":"Esla","municipio":"Ricobayo","cap":1160.0,"lat":41.725,"lon":-5.850},
        ],
    },

    "salamanca": {
        "nombre": "Salamanca", "comunidad": "Castilla y León",
        "lat_centro": 40.9, "lon_centro": -5.7,
        "embalses": [
            {"id":"almendra","nombre":"Almendra","buscar":["ALMENDRA"],"rio":"Tormes","municipio":"Almendra","cap":2648.0,"lat":41.268,"lon":-6.343},
        ],
    },

    "palencia": {
        "nombre": "Palencia", "comunidad": "Castilla y León",
        "lat_centro": 42.0, "lon_centro": -4.5,
        "embalses": [
            {"id":"requejada","nombre":"Requejada","buscar":["REQUEJADA"],"rio":"Pisuerga","municipio":"Cervera","cap":91.5,"lat":42.879,"lon":-4.503},
        ],
    },

    "lugo": {
        "nombre": "Lugo", "comunidad": "Galicia",
        "lat_centro": 43.0, "lon_centro": -7.6,
        "embalses": [
            {"id":"belesar",  "nombre":"Belesar",  "buscar":["BELESAR"],          "rio":"Miño","municipio":"Chantada","cap":654.0,"lat":42.600,"lon":-7.717},
        ],
    },

    "ourense": {
        "nombre": "Ourense", "comunidad": "Galicia",
        "lat_centro": 42.3, "lon_centro": -7.9,
        "embalses": [
            {"id":"castrelo","nombre":"Castrelo de Miño","buscar":["CASTRELO","CASTRELO DE MIÑO"],"rio":"Miño","municipio":"Castrelo","cap":197.0,"lat":42.246,"lon":-8.058},
        ],
    },

    "a_coruña": {
        "nombre": "A Coruña", "comunidad": "Galicia",
        "lat_centro": 43.3, "lon_centro": -8.4,
        "embalses": [
            {"id":"cecebre","nombre":"Cecebre","buscar":["CECEBRE"],"rio":"Mero","municipio":"Cambre","cap":67.4,"lat":43.272,"lon":-8.243},
        ],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK — datos reales del Boletín MITECO semana 19/2026 (11-05-2026)
# Solo para embalses de Murcia; el resto quedará como null hasta que el ZIP funcione.
# ─────────────────────────────────────────────────────────────────────────────
FALLBACK = {
    "ALFONSO XIII":  {"vol": 3.0,  "pct": 13.6},
    "ALGECIRAS":     {"vol": 19.0, "pct": 42.2},
    "ARGOS":         {"vol": 7.0,  "pct": 65.4},
    "LA CIERVA":     {"vol": 5.0,  "pct": 68.5},
    "PUENTES":       {"vol": 14.0, "pct": 53.8},
    "SANTOMERA":     {"vol": 2.0,  "pct": 11.1},
    "VALDEINFIERNO": {"vol": 0.1,  "pct":  0.9},
    "MULA":          {"vol": 1.2,  "pct":  5.7},
    "PLIEGO":        {"vol": 0.2,  "pct":  5.5},
}
FALLBACK_FECHA = "11/05/2026"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def estado(pct):
    if pct is None:  return "#888888", "Sin datos"
    if pct < 20:     return "#CC2200", "Crítico"
    if pct < 40:     return "#FF8822", "Bajo"
    if pct < 60:     return "#FFCC44", "Moderado"
    if pct < 80:     return "#44AA66", "Bueno"
    return "#0066CC", "Muy bueno"


def to_f(s):
    if s is None: return None
    s = str(s).strip().replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        v = float(s)
        return v if v >= 0 else None
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# DESCARGA Y LECTURA DEL ZIP MITECO
# ─────────────────────────────────────────────────────────────────────────────

def descargar_zip():
    print(f"  GET {ZIP_URL}")
    try:
        r = requests.get(ZIP_URL, headers=CABECERA, timeout=120)
        ct = r.headers.get("Content-Type", "")
        print(f"  HTTP {r.status_code}  Content-Type: {ct}  Size: {len(r.content)} bytes")
        if r.status_code == 200 and len(r.content) > 50_000:
            return r.content
        print("  ZIP no válido o demasiado pequeño")
    except Exception as e:
        print(f"  Error descargando ZIP: {e}")
    return None


def leer_mdb(zip_bytes):
    """Lee BD-embalses.mdb del ZIP, devuelve {NOMBRE: {vol, pct, fecha}}."""
    with tempfile.TemporaryDirectory() as tmp:
        # Extraer ZIP
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
        z.extractall(tmp)

        # Encontrar el .mdb
        mdb_path = None
        for root, _, files in os.walk(tmp):
            for f in files:
                if f.lower().endswith(".mdb"):
                    mdb_path = os.path.join(root, f)
                    break
        if not mdb_path:
            print("  No se encontró .mdb en el ZIP")
            return {}
        print(f"  .mdb: {os.path.basename(mdb_path)}")

        # Listar tablas
        try:
            res = subprocess.run(["mdb-tables", "-1", mdb_path],
                                 capture_output=True, text=True, timeout=30)
            tablas = [t.strip() for t in res.stdout.splitlines() if t.strip()]
            print(f"  Tablas: {tablas}")
        except Exception as e:
            print(f"  mdb-tables error: {e}")
            return {}

        # Elegir tabla de datos
        tabla = next(
            (t for t in tablas if any(x in t.upper() for x in ["DATO", "EMBALSE", "T_DAT"])),
            tablas[0] if tablas else None
        )
        if not tabla:
            print("  No se encontró tabla")
            return {}
        print(f"  Tabla: {tabla}")

        # Exportar a CSV
        try:
            res = subprocess.run(["mdb-export", mdb_path, tabla],
                                 capture_output=True, text=True, timeout=180)
            csv_text = res.stdout
        except Exception as e:
            print(f"  mdb-export error: {e}")
            return {}

    if not csv_text.strip():
        print("  mdb-export: vacío")
        return {}

    # Parsear CSV
    reader = csv.DictReader(io.StringIO(csv_text))
    hdrs = reader.fieldnames or []
    print(f"  Columnas: {hdrs[:6]}")

    col_n = col_f = col_t = col_a = None
    for h in hdrs:
        hu = h.upper().strip()
        if "EMBALSE" in hu and col_n is None:    col_n = h
        elif "NOMBRE" in hu and col_n is None:   col_n = h
        elif "FECHA" in hu and col_f is None:    col_f = h
        elif "TOTAL" in hu and col_t is None:    col_t = h
        elif "ACTUAL" in hu and col_a is None:   col_a = h

    if not col_n:
        print(f"  Columna nombre no detectada. Columnas disponibles: {hdrs}")
        return {}

    datos = {}
    for row in reader:
        nombre = (row.get(col_n) or "").strip().upper()
        if not nombre: continue
        total_v  = to_f(row.get(col_t)) if col_t else None
        actual_v = to_f(row.get(col_a)) if col_a else None
        fecha_s  = (row.get(col_f) or "").strip() if col_f else ""

        fdt = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                fdt = datetime.strptime(fecha_s, fmt)
                break
            except ValueError:
                pass

        pct = round((actual_v / total_v) * 100, 1) if total_v and total_v > 0 and actual_v is not None else None

        if nombre not in datos or (fdt and datos[nombre]["fdt"] and fdt > datos[nombre]["fdt"]):
            datos[nombre] = {
                "fdt":   fdt,
                "fecha": fdt.strftime("%d/%m/%Y") if fdt else fecha_s,
                "vol":   round(actual_v, 2) if actual_v is not None else None,
                "pct":   pct,
            }

    if datos:
        fechas = [d["fecha"] for d in datos.values() if d["fecha"]]
        if fechas:
            print(f"  ✓ {len(datos)} embalses — último dato: {max(fechas)}")
    return datos


def buscar(terminos, datos):
    for t in terminos:
        k = t.upper()
        if k in datos: return datos[k]["vol"], datos[k]["pct"], datos[k].get("fecha")
    for t in terminos:
        k = t.upper()
        for clave, d in datos.items():
            if k in clave: return d["vol"], d["pct"], d.get("fecha")
    return None, None, None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def procesar():
    ahora = datetime.now()
    print("=" * 65)
    print(f"Embalses España — MITECO  ({ahora.strftime('%d/%m/%Y %H:%M')})")
    print("=" * 65)

    # 1. Intentar descargar datos reales
    print("Descargando ZIP MITECO...")
    zip_bytes = descargar_zip()
    datos_mdb = {}
    usando_fallback = False
    fecha_dato = FALLBACK_FECHA

    if zip_bytes:
        print("Leyendo .mdb...")
        datos_mdb = leer_mdb(zip_bytes)
        if len(datos_mdb) < 10:
            print(f"⚠  Solo {len(datos_mdb)} embalses leídos — activando fallback")
            usando_fallback = True
        else:
            fechas = [d["fecha"] for d in datos_mdb.values() if d.get("fecha")]
            if fechas:
                fecha_dato = max(fechas)
    else:
        usando_fallback = True

    if usando_fallback:
        print(f"⚠  Usando fallback ({FALLBACK_FECHA})")

    fuente = "Boletín Hidrológico Semanal — MITECO"

    # 2. Crear carpetas
    os.makedirs("docs/embalses", exist_ok=True)

    # 3. Procesar cada provincia
    print("-" * 65)
    provincias_json = []  # para el mapa nacional por provincias

    for id_prov, prov in PROVINCIAS.items():
        lista_emb = []
        sum_vol = sum_cap = 0.0
        tiene_datos = False

        for emb in prov["embalses"]:
            if usando_fallback:
                v = pct = None
                for t in emb["buscar"]:
                    if t in FALLBACK:
                        v   = FALLBACK[t]["vol"]
                        pct = FALLBACK[t]["pct"]
                        break
            else:
                v, pct, _ = buscar(emb["buscar"], datos_mdb)

            if pct is not None:
                tiene_datos = True
                v   = round(float(v), 2)
                pct = round(float(pct), 1)
                sum_vol += v
                sum_cap += emb["cap"]
            else:
                v = None
                sum_cap += emb["cap"]

            col, etq = estado(pct)
            lista_emb.append({
                "id": emb["id"], "nombre": emb["nombre"],
                "rio": emb["rio"], "municipio": emb["municipio"],
                "provincia": prov["nombre"],
                "lat": emb["lat"], "lon": emb["lon"],
                "capacidad_hm3": emb["cap"],
                "volumen_hm3": v, "pct": pct,
                "color": col, "etiqueta": etq,
            })

        # % medio de la provincia
        pct_prov = round((sum_vol / sum_cap) * 100, 1) if (tiene_datos and sum_cap > 0) else None
        col_p, etq_p = estado(pct_prov)

        # JSON de provincia
        with open(f"docs/embalses/{id_prov}.json", "w", encoding="utf-8") as f:
            json.dump({
                "ultima_actualizacion": ahora.isoformat(),
                "fecha_legible":   fecha_dato,
                "provincia":       prov["nombre"],
                "comunidad":       prov["comunidad"],
                "total_embalses":  len(lista_emb),
                "capacidad_total_hm3": round(sum_cap, 1),
                "volumen_total_hm3":   round(sum_vol, 2),
                "pct_media":       pct_prov,
                "color":           col_p,
                "etiqueta":        etq_p,
                "fuente":          fuente,
                "embalses":        lista_emb,
            }, f, ensure_ascii=False, indent=2)

        # Entrada para el mapa nacional (por provincia)
        provincias_json.append({
            "id":                 id_prov,
            "nombre":             prov["nombre"],
            "comunidad":          prov["comunidad"],
            "lat":                prov["lat_centro"],
            "lon":                prov["lon_centro"],
            "pct":                pct_prov,
            "color":              col_p,
            "etiqueta":           etq_p,
            "capacidad_total_hm3": round(sum_cap, 1),
            "volumen_total_hm3":   round(sum_vol, 2),
            "total_embalses":      len(lista_emb),
            "url_detalle":        f"embalses/{id_prov}.html",
            "datos_disponibles":  tiene_datos,
        })

        estado_str = f"{pct_prov}%" if pct_prov is not None else "sin datos"
        print(f"  {prov['nombre']:20s}: {estado_str}")

    # 4. JSON nacional
    with open("docs/embalses_nacional.json", "w", encoding="utf-8") as f:
        json.dump({
            "ultima_actualizacion": ahora.isoformat(),
            "fecha_legible":   fecha_dato,
            "fuente":          fuente,
            "provincias":      provincias_json,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✓ embalses_nacional.json — {len(provincias_json)} provincias")
    print("=" * 65)


if __name__ == "__main__":
    procesar()
