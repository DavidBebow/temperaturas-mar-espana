"""
Script incremental: solo descarga los datos del día anterior y actualiza
el JSON existente. Mucho más rápido que recalcular todo cada día.
Lógica:
- Lee el JSON anterior (si existe) y conserva el histórico
- Para cada ciudad, pide a AEMET solo el dato de AYER
- Actualiza tmin_anoche, recalcula medias del mes y acumula noches tropicales
- Las medias del año anterior se recalculan UNA VEZ AL MES (día 1)
"""
import os
import json
import time
import requests
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo
API_KEY  = os.environ.get("AEMET_API_KEY", "")
BASE_URL = "https://opendata.aemet.es/opendata/api"
HEADERS  = {"api_key": API_KEY, "Accept": "application/json"}
JSON_PATH = "docs/temperaturas_nocturnas.json"
TZ = ZoneInfo("Europe/Madrid")
CIUDADES = [
    {"id": "sevilla",       "nombre": "Sevilla",       "ccaa": "Andalucía",          "idema": "5783",  "lat": 37.418, "lon": -5.881},
    {"id": "malaga",        "nombre": "Málaga",        "ccaa": "Andalucía",          "idema": "6155A", "lat": 36.660, "lon": -4.499},
    {"id": "granada",       "nombre": "Granada",       "ccaa": "Andalucía",          "idema": "5514",  "lat": 37.142, "lon": -3.631},
    {"id": "cordoba",       "nombre": "Córdoba",       "ccaa": "Andalucía",          "idema": "5402",  "lat": 37.848, "lon": -4.848},
    {"id": "almeria",       "nombre": "Almería",       "ccaa": "Andalucía",          "idema": "6325O", "lat": 36.847, "lon": -2.380},
    {"id": "huelva",        "nombre": "Huelva",        "ccaa": "Andalucía",          "idema": "4642E", "lat": 37.282, "lon": -6.909},
    {"id": "cadiz",         "nombre": "Cádiz",         "ccaa": "Andalucía",          "idema": "5973",  "lat": 36.500, "lon": -6.269},
    {"id": "jaen",          "nombre": "Jaén",          "ccaa": "Andalucía",          "idema": "5270B", "lat": 37.784, "lon": -3.807},
    {"id": "motril",        "nombre": "Motril",        "ccaa": "Andalucía",          "idema": "6172O", "lat": 36.731, "lon": -3.509},
    {"id": "valencia",      "nombre": "Valencia",      "ccaa": "C. Valenciana",      "idema": "8416Y", "lat": 39.480, "lon": -0.366},
    {"id": "alicante",      "nombre": "Alicante",      "ccaa": "C. Valenciana",      "idema": "8025",  "lat": 38.372, "lon": -0.493},
    {"id": "castellon",     "nombre": "Castellón",     "ccaa": "C. Valenciana",      "idema": "8500A", "lat": 39.945, "lon": -0.026},
    {"id": "murcia",        "nombre": "Murcia",        "ccaa": "Región de Murcia",   "idema": "7228",  "lat": 38.000, "lon": -1.170},
    {"id": "cartagena",     "nombre": "Cartagena",     "ccaa": "Región de Murcia",   "idema": "7012C", "lat": 37.596, "lon": -0.983},
    {"id": "lorca",         "nombre": "Lorca",         "ccaa": "Región de Murcia",   "idema": "7209",  "lat": 37.672, "lon": -1.701},
    {"id": "barcelona",     "nombre": "Barcelona",     "ccaa": "Cataluña",           "idema": "0076",  "lat": 41.380, "lon":  2.148},
    {"id": "tarragona",     "nombre": "Tarragona",     "ccaa": "Cataluña",           "idema": "0016A", "lat": 41.097, "lon":  1.237},
    {"id": "lleida",        "nombre": "Lleida",        "ccaa": "Cataluña",           "idema": "9771C", "lat": 41.628, "lon":  0.595},
    {"id": "girona",        "nombre": "Girona",        "ccaa": "Cataluña",           "idema": "0367",  "lat": 41.903, "lon":  2.760},
    {"id": "madrid",        "nombre": "Madrid",        "ccaa": "Madrid",             "idema": "3195",  "lat": 40.411, "lon": -3.684},
    {"id": "toledo",        "nombre": "Toledo",        "ccaa": "Castilla-La Mancha", "idema": "3260B", "lat": 39.882, "lon": -4.049},
    {"id": "ciudad_real",   "nombre": "Ciudad Real",   "ccaa": "Castilla-La Mancha", "idema": "4121",  "lat": 38.990, "lon": -3.920},
    {"id": "albacete",      "nombre": "Albacete",      "ccaa": "Castilla-La Mancha", "idema": "8175",  "lat": 38.945, "lon": -1.863},
    {"id": "valladolid",    "nombre": "Valladolid",    "ccaa": "Castilla y León",    "idema": "2422",  "lat": 41.664, "lon": -4.767},
    {"id": "salamanca",     "nombre": "Salamanca",     "ccaa": "Castilla y León",    "idema": "2867",  "lat": 40.960, "lon": -5.500},
    {"id": "burgos",        "nombre": "Burgos",        "ccaa": "Castilla y León",    "idema": "2331",  "lat": 42.357, "lon": -3.621},
    {"id": "leon",          "nombre": "León",          "ccaa": "Castilla y León",    "idema": "2661",  "lat": 42.589, "lon": -5.651},
    {"id": "zaragoza",      "nombre": "Zaragoza",      "ccaa": "Aragón",             "idema": "9434",  "lat": 41.661, "lon": -1.004},
    {"id": "huesca",        "nombre": "Huesca",        "ccaa": "Aragón",             "idema": "9898",  "lat": 42.082, "lon": -0.333},
    {"id": "teruel",        "nombre": "Teruel",        "ccaa": "Aragón",             "idema": "8368U", "lat": 40.355, "lon": -1.130},
    {"id": "bilbao",        "nombre": "Bilbao",        "ccaa": "País Vasco",         "idema": "1082",  "lat": 43.300, "lon": -2.906},
    {"id": "san_sebastian", "nombre": "San Sebastián", "ccaa": "País Vasco",         "idema": "1024E", "lat": 43.308, "lon": -1.994},
    {"id": "vitoria",       "nombre": "Vitoria",       "ccaa": "País Vasco",         "idema": "9091O", "lat": 42.882, "lon": -2.729},
    {"id": "vigo",          "nombre": "Vigo",          "ccaa": "Galicia",            "idema": "1484C", "lat": 42.232, "lon": -8.718},
    {"id": "coruna",        "nombre": "A Coruña",      "ccaa": "Galicia",            "idema": "1387",  "lat": 43.366, "lon": -8.422},
    {"id": "santiago",      "nombre": "Santiago",      "ccaa": "Galicia",            "idema": "1428",  "lat": 42.896, "lon": -8.411},
    {"id": "oviedo",        "nombre": "Oviedo",        "ccaa": "Asturias",           "idema": "1249X", "lat": 43.354, "lon": -5.873},
    {"id": "santander",     "nombre": "Santander",     "ccaa": "Cantabria",          "idema": "1111",  "lat": 43.491, "lon": -3.800},
    {"id": "pamplona",      "nombre": "Pamplona",      "ccaa": "Navarra",            "idema": "9263D", "lat": 42.769, "lon": -1.645},
    {"id": "logrono",       "nombre": "Logroño",       "ccaa": "La Rioja",           "idema": "9170",  "lat": 42.451, "lon": -2.502},
    {"id": "badajoz",       "nombre": "Badajoz",       "ccaa": "Extremadura",        "idema": "4452",  "lat": 38.881, "lon": -6.821},
    {"id": "caceres",       "nombre": "Cáceres",       "ccaa": "Extremadura",        "idema": "3469A", "lat": 39.472, "lon": -6.337},
    {"id": "palma",         "nombre": "Palma",         "ccaa": "Baleares",           "idema": "B228",  "lat": 39.551, "lon":  2.628},
    {"id": "ibiza",         "nombre": "Ibiza",         "ccaa": "Baleares",           "idema": "B954",  "lat": 38.873, "lon":  1.398},
    {"id": "mahon",         "nombre": "Mahón",         "ccaa": "Baleares",           "idema": "B893",  "lat": 39.862, "lon":  4.216},
    {"id": "las_palmas",    "nombre": "Las Palmas",    "ccaa": "Canarias",           "idema": "C029O", "lat": 28.146, "lon": -15.415},
    {"id": "santa_cruz_tf", "nombre": "Sta. Cruz TF",  "ccaa": "Canarias",           "idema": "C447A", "lat": 28.463, "lon": -16.259},
    {"id": "ceuta",         "nombre": "Ceuta",         "ccaa": "Ceuta",              "idema": "5000C", "lat": 35.890, "lon": -5.316},
    {"id": "melilla",       "nombre": "Melilla",       "ccaa": "Melilla",            "idema": "6000A", "lat": 35.279, "lon": -2.956},
]
ahora = datetime.now(TZ)
hoy  = ahora.date()
ayer = hoy - timedelta(days=1)
# ─────────────────────────────────────────────────────────────────────────────
# Cargar el histórico previo (si existe)
# ─────────────────────────────────────────────────────────────────────────────
def cargar_historico():
    """
    El JSON guarda, dentro de cada ciudad, un campo 'historico' con todas las
    mínimas y máximas diarias del año en curso. Así no hace falta volver a
    pedirlas a AEMET cada día.
    """
    if not os.path.exists(JSON_PATH):
        return {}, None, None  # primera ejecución
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        hist = {c["id"]: c.get("historico", {}) for c in data.get("ciudades", [])}
        anyo_guardado = data.get("anyo_actual")
        mes_guardado  = data.get("_mes_calculado_ant")  # control para recalcular año anterior
        return hist, anyo_guardado, mes_guardado
    except Exception as e:
