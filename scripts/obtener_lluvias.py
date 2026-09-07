import requests
import json
import os
from datetime import datetime, timedelta

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# ─────────────────────────────────────────────────────────────────────────────
# Open-Meteo: gratuito, sin API key, sin retraso.
# Documentación: https://open-meteo.com/en/docs
# ─────────────────────────────────────────────────────────────────────────────
# Solo identidad y coordenadas. La media anual ya NO va aqui: vive en NORMALES,
# con su desglose mensual y su procedencia. Tener dos medias en dos sitios es
# como empezo este fallo.
PROVINCIAS = [
    {"id": "almeria",        "nombre": "Almería",        "ccaa": "Andalucía",           "lat": 37.23, "lon": -1.86},
    {"id": "cadiz",          "nombre": "Cádiz",          "ccaa": "Andalucía",           "lat": 36.52, "lon": -6.30},
    {"id": "cordoba",        "nombre": "Córdoba",        "ccaa": "Andalucía",           "lat": 37.88, "lon": -4.78},
    {"id": "granada",        "nombre": "Granada",        "ccaa": "Andalucía",           "lat": 37.18, "lon": -3.60},
    {"id": "huelva",         "nombre": "Huelva",         "ccaa": "Andalucía",           "lat": 37.25, "lon": -6.95},
    {"id": "jaen",           "nombre": "Jaén",           "ccaa": "Andalucía",           "lat": 37.77, "lon": -3.79},
    {"id": "malaga",         "nombre": "Málaga",         "ccaa": "Andalucía",           "lat": 36.72, "lon": -4.42},
    {"id": "sevilla",        "nombre": "Sevilla",        "ccaa": "Andalucía",           "lat": 37.39, "lon": -5.99},
    {"id": "huesca",         "nombre": "Huesca",         "ccaa": "Aragón",              "lat": 42.14, "lon": -0.41},
    {"id": "teruel",         "nombre": "Teruel",         "ccaa": "Aragón",              "lat": 40.34, "lon": -1.11},
    {"id": "zaragoza",       "nombre": "Zaragoza",       "ccaa": "Aragón",              "lat": 41.65, "lon": -0.89},
    {"id": "asturias",       "nombre": "Asturias",       "ccaa": "Asturias",            "lat": 43.36, "lon": -5.85},
    {"id": "baleares",       "nombre": "Illes Balears",  "ccaa": "Illes Balears",       "lat": 39.57, "lon":  2.65},
    {"id": "canarias_las_p", "nombre": "Las Palmas",     "ccaa": "Canarias",            "lat": 28.10, "lon": -15.41},
    {"id": "canarias_sc_tf", "nombre": "S.C. Tenerife",  "ccaa": "Canarias",            "lat": 28.46, "lon": -16.25},
    {"id": "cantabria",      "nombre": "Cantabria",      "ccaa": "Cantabria",           "lat": 43.18, "lon": -3.99},
    {"id": "albacete",       "nombre": "Albacete",       "ccaa": "Castilla-La Mancha",  "lat": 39.00, "lon": -1.86},
    {"id": "ciudad_real",    "nombre": "Ciudad Real",    "ccaa": "Castilla-La Mancha",  "lat": 38.99, "lon": -3.93},
    {"id": "cuenca",         "nombre": "Cuenca",         "ccaa": "Castilla-La Mancha",  "lat": 40.07, "lon": -2.14},
    {"id": "guadalajara",    "nombre": "Guadalajara",    "ccaa": "Castilla-La Mancha",  "lat": 40.63, "lon": -3.17},
    {"id": "toledo",         "nombre": "Toledo",         "ccaa": "Castilla-La Mancha",  "lat": 39.86, "lon": -4.02},
    {"id": "avila",          "nombre": "Ávila",          "ccaa": "Castilla y León",     "lat": 40.66, "lon": -4.69},
    {"id": "burgos",         "nombre": "Burgos",         "ccaa": "Castilla y León",     "lat": 42.34, "lon": -3.70},
    {"id": "leon",           "nombre": "León",           "ccaa": "Castilla y León",     "lat": 42.60, "lon": -5.57},
    {"id": "palencia",       "nombre": "Palencia",       "ccaa": "Castilla y León",     "lat": 42.01, "lon": -4.53},
    {"id": "salamanca",      "nombre": "Salamanca",      "ccaa": "Castilla y León",     "lat": 40.96, "lon": -5.66},
    {"id": "segovia",        "nombre": "Segovia",        "ccaa": "Castilla y León",     "lat": 40.95, "lon": -4.12},
    {"id": "soria",          "nombre": "Soria",          "ccaa": "Castilla y León",     "lat": 41.77, "lon": -2.46},
    {"id": "valladolid",     "nombre": "Valladolid",     "ccaa": "Castilla y León",     "lat": 41.65, "lon": -4.72},
    {"id": "zamora",         "nombre": "Zamora",         "ccaa": "Castilla y León",     "lat": 41.50, "lon": -5.74},
    {"id": "barcelona",      "nombre": "Barcelona",      "ccaa": "Cataluña",            "lat": 41.38, "lon":  2.17},
    {"id": "girona",         "nombre": "Girona",         "ccaa": "Cataluña",            "lat": 41.98, "lon":  2.82},
    {"id": "lleida",         "nombre": "Lleida",         "ccaa": "Cataluña",            "lat": 41.62, "lon":  0.63},
    {"id": "tarragona",      "nombre": "Tarragona",      "ccaa": "Cataluña",            "lat": 41.11, "lon":  1.25},
    {"id": "badajoz",        "nombre": "Badajoz",        "ccaa": "Extremadura",         "lat": 38.88, "lon": -6.97},
    {"id": "caceres",        "nombre": "Cáceres",        "ccaa": "Extremadura",         "lat": 39.47, "lon": -6.37},
    {"id": "acoruna",        "nombre": "A Coruña",       "ccaa": "Galicia",             "lat": 43.36, "lon": -8.40},
    {"id": "lugo",           "nombre": "Lugo",           "ccaa": "Galicia",             "lat": 43.01, "lon": -7.55},
    {"id": "ourense",        "nombre": "Ourense",        "ccaa": "Galicia",             "lat": 42.34, "lon": -7.87},
    {"id": "pontevedra",     "nombre": "Pontevedra",     "ccaa": "Galicia",             "lat": 42.43, "lon": -8.65},
    {"id": "rioja",          "nombre": "La Rioja",       "ccaa": "La Rioja",            "lat": 42.27, "lon": -2.37},
    {"id": "madrid",         "nombre": "Madrid",         "ccaa": "Comunidad de Madrid", "lat": 40.42, "lon": -3.70},
    {"id": "murcia",         "nombre": "Murcia",         "ccaa": "Región de Murcia",    "lat": 37.99, "lon": -1.13},
    {"id": "navarra",        "nombre": "Navarra",        "ccaa": "Navarra",             "lat": 42.82, "lon": -1.65},
    {"id": "alava",          "nombre": "Álava",          "ccaa": "País Vasco",          "lat": 42.85, "lon": -2.67},
    {"id": "guipuzcoa",      "nombre": "Gipuzkoa",       "ccaa": "País Vasco",          "lat": 43.19, "lon": -2.04},
    {"id": "vizcaya",        "nombre": "Bizkaia",        "ccaa": "País Vasco",          "lat": 43.26, "lon": -2.93},
    {"id": "alicante",       "nombre": "Alicante",       "ccaa": "C. Valenciana",       "lat": 38.35, "lon": -0.48},
    {"id": "castellon",      "nombre": "Castellón",      "ccaa": "C. Valenciana",       "lat": 40.00, "lon": -0.05},
    {"id": "valencia",       "nombre": "Valencia",       "ccaa": "C. Valenciana",       "lat": 39.47, "lon": -0.37},
    {"id": "ceuta",          "nombre": "Ceuta",          "ccaa": "Ceuta",               "lat": 35.89, "lon": -5.32},
    {"id": "melilla",        "nombre": "Melilla",        "ccaa": "Melilla",             "lat": 35.29, "lon": -2.94},
]

# ─────────────────────────────────────────────────────────────────────────────
# NORMALES 1991-2020, POR PROVINCIA Y POR MES
# ─────────────────────────────────────────────────────────────────────────────
# (mm al año, [mm de enero .. mm de diciembre])
#
# Son de ERA5-Land (Copernicus), tomadas EN LA MISMA CELDA DE 0,1° que el punto
# que este script consulta a Open-Meteo para cada provincia. Eso importa: la
# observacion es de UN punto (la capital), asi que la normal tiene que ser la de
# ese punto. La media provincial ponderada por poblacion que publica el sitio en
# /lluvias-en-espana/{provincia}/ es otra cosa —un area de 100 km— y compararlas
# seria el mismo error de escala, con otra cara. Se vio en Las Palmas: 500 mm
# observados en el punto contra 200 de media provincial daban '+268 %, Muy
# lluvioso'; contra la normal del punto (248) el numero ya significa algo.
# Se generan con normales_punto.py, en la carpeta de trabajo del proyecto.
#
# Antes había aquí un número por provincia escrito de memoria. No cuadraban:
# Almería 220 (real 298), Gipuzkoa 1500 (1464), Alicante 330 (370),
# A Coruña 1050 (1289), Pontevedra 1600 (1652). El mapa llevaba meses midiendo
# desviaciones contra una climatología que no existía.
#
# El desglose mensual no es un lujo: en España cae el 61 por ciento de la lluvia
# entre octubre y marzo y solo el 13 por ciento en verano. Repartir el año a
# partes iguales —que es lo que hacía media_anual * dia_del_anio / 365— exige en
# septiembre el 68 por ciento del total anual cuando de verdad ha caído el 57, y
# pinta de sequía cualquier verano normal.
NORMALES = {
    "almeria": (313.0, [32.4, 30.6, 33.9, 28.4, 19.3, 8.8, 3.1, 11.5, 37.5, 39.3, 36.9, 31.3]),
    "cadiz": (569.4, [65.5, 60.4, 62.8, 55.2, 32.7, 7.7, 1.6, 3.8, 29.3, 81.8, 78.6, 90.1]),
    "cordoba": (498.2, [54.3, 47.4, 57.1, 51.9, 36.2, 11.8, 2.9, 5.6, 29.6, 61.4, 65.3, 74.7]),
    "granada": (506.0, [52.2, 48.6, 57.6, 55.3, 47.5, 22.7, 6.1, 11.7, 31.9, 50.7, 60.9, 61.0]),
    "huelva": (435.4, [47.7, 41.4, 45.8, 47.4, 31.0, 6.6, 1.0, 2.6, 22.0, 66.8, 54.9, 68.2]),
    "jaen": (622.1, [59.3, 57.1, 65.5, 71.8, 58.4, 23.6, 5.8, 14.5, 45.4, 70.9, 74.4, 75.3]),
    "malaga": (449.9, [60.1, 48.9, 51.0, 35.8, 21.3, 7.7, 1.6, 4.1, 21.6, 54.0, 69.9, 73.8]),
    "sevilla": (512.2, [52.9, 49.9, 58.2, 53.6, 37.0, 8.6, 2.2, 2.9, 29.7, 71.8, 66.2, 79.1]),
    "huesca": (669.3, [47.8, 34.7, 53.6, 72.4, 67.0, 45.7, 32.0, 51.2, 64.9, 83.9, 68.3, 47.8]),
    "teruel": (438.8, [28.6, 27.6, 38.4, 52.7, 58.1, 41.5, 20.0, 31.2, 33.9, 41.0, 36.1, 29.7]),
    "zaragoza": (392.9, [31.0, 24.4, 34.9, 47.1, 39.6, 30.3, 17.0, 21.9, 30.2, 44.6, 44.4, 27.6]),
    "asturias": (1326.9, [113.6, 98.5, 109.4, 130.5, 132.8, 98.5, 85.5, 91.4, 91.6, 126.4, 137.2, 111.7]),
    "baleares": (438.0, [41.0, 36.6, 29.8, 38.6, 33.7, 18.2, 6.0, 20.1, 48.1, 58.6, 61.0, 46.2]),
    "canarias_las_p": (248.4, [26.3, 27.8, 25.9, 18.7, 14.1, 10.9, 13.2, 10.5, 13.7, 27.2, 27.8, 32.1]),
    "canarias_sc_tf": (287.7, [30.3, 31.8, 30.2, 20.7, 13.1, 12.6, 16.0, 12.9, 13.6, 30.4, 37.3, 38.7]),
    "cantabria": (1199.2, [106.9, 98.7, 100.9, 114.0, 110.3, 98.6, 81.2, 77.1, 84.8, 102.1, 126.2, 98.4]),
    "albacete": (403.4, [31.7, 29.3, 43.2, 46.4, 43.8, 24.2, 8.2, 20.6, 38.3, 39.4, 40.1, 38.3]),
    "ciudad_real": (434.4, [40.8, 38.4, 44.4, 51.8, 45.0, 16.8, 5.3, 8.6, 26.6, 53.9, 51.3, 51.7]),
    "cuenca": (633.0, [57.9, 50.4, 63.5, 73.9, 65.2, 36.1, 11.9, 21.2, 40.1, 74.4, 70.6, 67.9]),
    "guadalajara": (491.4, [45.2, 37.5, 45.8, 58.1, 52.4, 24.6, 8.9, 13.7, 29.0, 66.8, 60.9, 48.4]),
    "toledo": (453.9, [39.8, 36.5, 43.5, 51.2, 47.6, 20.6, 10.2, 11.8, 27.2, 60.1, 54.1, 51.3]),
    "avila": (549.6, [49.6, 42.0, 50.3, 61.9, 64.1, 34.2, 18.7, 19.8, 33.9, 62.9, 61.0, 51.2]),
    "burgos": (656.8, [62.0, 51.2, 57.2, 73.6, 71.5, 47.5, 26.8, 23.0, 43.5, 66.8, 70.5, 63.1]),
    "leon": (603.5, [65.7, 43.2, 53.6, 59.1, 55.5, 34.1, 20.1, 22.9, 33.5, 77.9, 67.5, 70.3]),
    "palencia": (501.9, [46.5, 35.9, 42.1, 54.6, 55.5, 32.8, 19.1, 15.9, 32.0, 60.3, 56.2, 51.0]),
    "salamanca": (488.7, [47.9, 37.6, 44.5, 55.1, 50.7, 25.0, 13.4, 13.9, 29.2, 64.4, 56.0, 51.0]),
    "segovia": (683.2, [67.4, 55.5, 63.4, 78.8, 77.1, 40.6, 20.9, 23.2, 39.6, 73.1, 77.8, 65.9]),
    "soria": (576.6, [50.0, 42.8, 49.0, 68.4, 66.2, 47.3, 28.8, 27.0, 37.1, 56.4, 57.6, 45.8]),
    "valladolid": (506.2, [48.9, 37.6, 45.2, 56.7, 51.4, 30.4, 17.7, 15.2, 31.4, 62.9, 57.1, 51.8]),
    "zamora": (474.3, [44.9, 33.6, 41.7, 51.3, 48.9, 26.6, 13.9, 13.5, 28.9, 65.3, 54.3, 51.3]),
    "barcelona": (606.2, [40.7, 36.5, 42.1, 53.6, 46.9, 35.1, 27.6, 45.3, 84.6, 91.9, 60.0, 41.9]),
    "girona": (895.2, [62.5, 55.9, 73.6, 89.1, 84.6, 65.8, 56.7, 58.2, 95.9, 113.7, 77.1, 62.2]),
    "lleida": (444.9, [32.0, 21.7, 34.6, 50.1, 46.6, 30.7, 19.8, 34.5, 51.1, 52.0, 42.5, 29.3]),
    "tarragona": (536.6, [40.1, 31.0, 40.1, 49.9, 47.9, 26.9, 19.9, 43.8, 73.9, 73.7, 50.7, 38.9]),
    "badajoz": (451.7, [47.6, 42.5, 46.7, 45.7, 38.0, 11.5, 2.8, 4.7, 24.1, 66.9, 60.7, 60.4]),
    "caceres": (555.5, [56.9, 49.2, 56.5, 58.2, 47.4, 16.1, 4.9, 7.8, 35.7, 82.1, 72.1, 68.7]),
    "acoruna": (1221.3, [145.7, 107.0, 107.9, 113.4, 87.8, 58.7, 39.7, 50.7, 73.8, 133.5, 158.5, 144.6]),
    "lugo": (1084.7, [120.9, 91.5, 97.5, 103.8, 86.5, 57.6, 32.3, 42.3, 65.5, 123.6, 133.6, 129.5]),
    "ourense": (1063.4, [126.1, 90.6, 98.1, 100.4, 85.8, 50.0, 29.1, 33.5, 58.4, 126.6, 132.7, 132.1]),
    "pontevedra": (1656.9, [207.2, 141.0, 151.3, 150.3, 125.0, 65.3, 39.9, 53.4, 93.0, 204.8, 215.9, 209.7]),
    "rioja": (654.3, [60.7, 53.2, 58.3, 70.9, 68.0, 53.4, 31.9, 31.5, 39.0, 59.8, 71.4, 56.1]),
    "madrid": (447.1, [42.0, 35.6, 43.0, 50.2, 46.2, 20.0, 7.6, 11.0, 24.8, 62.6, 56.5, 47.6]),
    "murcia": (299.7, [26.3, 23.5, 33.5, 32.5, 25.1, 11.5, 3.1, 9.4, 40.0, 35.0, 33.9, 25.8]),
    "navarra": (854.9, [79.4, 70.0, 76.8, 93.1, 80.7, 57.6, 33.4, 50.8, 57.5, 86.2, 92.6, 76.8]),
    "alava": (819.9, [82.3, 73.8, 77.2, 86.1, 74.9, 57.9, 35.2, 36.2, 47.3, 77.3, 94.3, 77.6]),
    "guipuzcoa": (1495.9, [136.7, 125.4, 120.8, 139.5, 134.2, 106.4, 93.1, 98.1, 103.2, 133.7, 167.6, 137.1]),
    "vizcaya": (1220.9, [129.4, 117.0, 110.2, 105.0, 88.9, 73.3, 67.2, 64.7, 75.3, 109.6, 156.7, 123.4]),
    "alicante": (331.2, [32.1, 25.8, 31.2, 35.7, 26.2, 12.9, 4.1, 11.7, 39.7, 41.0, 40.4, 30.3]),
    "castellon": (454.1, [38.2, 30.9, 39.2, 45.5, 42.7, 26.9, 13.2, 28.0, 52.9, 55.9, 44.1, 36.7]),
    "valencia": (423.8, [34.3, 28.8, 38.6, 40.4, 32.5, 18.6, 9.6, 25.5, 58.9, 55.5, 45.0, 36.0]),
    "ceuta": (603.0, [84.2, 75.8, 69.1, 49.3, 26.9, 6.0, 2.1, 5.2, 29.6, 71.5, 86.6, 96.5]),
    "melilla": (356.3, [42.5, 39.6, 45.2, 34.7, 22.0, 7.7, 1.8, 7.5, 27.0, 43.2, 48.4, 36.5]),
}

DIAS_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def normal_dia(meses, fecha):
    """Lo normal para UN dia concreto: el mes al que pertenece, repartido."""
    return meses[fecha.month - 1] / DIAS_MES[fecha.month - 1]


def normal_ventana(meses, fin, dias):
    """Lo normal para los `dias` que terminan en `fin`, dia a dia. Cruza el
    cambio de mes sin despeinarse, que es justo cuando mas se notaria."""
    return sum(normal_dia(meses, fin - timedelta(days=k)) for k in range(dias))


def normal_hasta(meses, fecha):
    """Lo normal acumulado del 1 de enero a `fecha`: los meses completos
    enteros, y el mes en curso a prorrata de los dias transcurridos."""
    return sum(meses[:fecha.month - 1]) + meses[fecha.month - 1] * (fecha.day / DIAS_MES[fecha.month - 1])


# ─────────────────────────────────────────────────────────────────────────────
# OPEN-METEO: una sola llamada por provincia devuelve todo el histórico del año
# ─────────────────────────────────────────────────────────────────────────────

def get_daily_prec(url, lat, lon, start, end, timeout=60):
    """Llamada a Open-Meteo. Devuelve (fechas, mm) alineados, con reintentos."""
    params = {
        "latitude":   lat, "longitude":  lon,
        "daily":      "precipitation_sum",
        "timezone":   "Europe/Madrid",
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date":   end.strftime("%Y-%m-%d"),
    }
    for intento in range(3):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            data = r.json()
            if "daily" not in data:
                return [], []
            return data["daily"]["time"], data["daily"]["precipitation_sum"]
        except Exception:
            if intento < 2:
                import time; time.sleep(5)
    return [], []


def obtener_serie(prov, ini_anual, fin):
    """UNA sola llamada al ARCHIVO por provincia, del 1 de enero a `fin`.

    Antes eran dos llamadas a dos endpoints distintos: /v1/archive para el
    acumulado anual y /v1/forecast para la semana y el dia. Y ahi estaba el
    fallo: consultado sobre dias YA PASADOS, /v1/forecast no devuelve la lluvia
    observada, devuelve el analisis del modelo de prediccion, que se queda muy
    corto. Medido el 07/09/2026, misma ventana y mismo punto:

        provincia    forecast   archive
        A Coruna         0,3       3,3
        Asturias         0,6       4,0
        Gipuzkoa         0,5       3,5
        Cantabria        1,5       4,7

    Con eso, la lluvia de la semana se comparaba contra una media semanal que si
    es real, y practicamente toda Espana salia "Muy seco" siempre. Dos cifras en
    las mismas unidades y a distinta escala, una al lado de la otra.

    Ahora todo —dia, semana y ano— sale de la misma serie y de la misma fuente.
    Devuelve (fecha_ultimo_dato, lista de mm) o (None, []).
    """
    fechas, mm = get_daily_prec(ARCHIVE_URL, prov["lat"], prov["lon"], ini_anual, fin)
    if not fechas:
        return None, []
    # El archivo va con retraso variable: los ultimos dias pueden venir a None.
    # Se recortan en vez de contarlos como cero, que restaria lluvia inventada.
    while mm and mm[-1] is None:
        mm.pop(); fechas.pop()
    if not mm:
        return None, []
    return datetime.strptime(fechas[-1], "%Y-%m-%d"), [x if x is not None else 0.0 for x in mm]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS (igual que antes)
# ─────────────────────────────────────────────────────────────────────────────

def calcular_anomalia(real_mm, media_mm):
    if not media_mm:
        return None
    return round(((real_mm - media_mm) / media_mm) * 100, 1)

def etiqueta_anomalia(a):
    if a is None:  return "Sin datos"
    if a < -40:    return "Muy seco"
    if a < -15:    return "Seco"
    if a < 15:     return "Normal"
    if a < 40:     return "Lluvioso"
    return "Muy lluvioso"

def color_lluvia(mm):
    if mm is None: return "#2a3a4a"
    if mm == 0:    return "#1a2530"
    if mm < 2:     return "#1e4060"
    if mm < 5:     return "#1e6090"
    if mm < 10:    return "#1e90c0"
    if mm < 20:    return "#22b8e8"
    if mm < 40:    return "#44d4ff"
    return "#88eeff"

def color_anomalia(a):
    if a is None:  return "#2a3a4a"
    if a < -40:    return "#8B1A1A"
    if a < -15:    return "#CC3300"
    if a < 15:     return "#CCAA44"
    if a < 40:     return "#2288CC"
    return "#0044AA"

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def procesar_lluvias():
    hoy       = datetime.now()
    ini_anual = datetime(hoy.year, 1, 1)
    # Se pide hasta HOY y luego se recorta lo que el archivo aun no tenga, en vez
    # de suponer un retraso fijo de 2 dias. El retraso varia, y con el fijo el
    # JSON decia "fecha_datos 05/09" mientras el mapa rotulaba esa columna como
    # "ayer" un dia 7: dos dias de diferencia sin avisar a nadie.
    tope = hoy

    print("Open-Meteo (archivo) · %d provincias" % len(PROVINCIAS))

    provincias_resultado = []
    ultimo_global = None

    for i, prov in enumerate(PROVINCIAS, 1):
        print("  [%02d/%d] %s..." % (i, len(PROVINCIAS), prov["nombre"]), end=" ", flush=True)
        fecha, serie = obtener_serie(prov, ini_anual, tope)
        if fecha is None:
            print("SIN DATOS")
            continue
        if ultimo_global is None or fecha > ultimo_global:
            ultimo_global = fecha

        anual, meses = NORMALES[prov["id"]]

        mm_dia    = round(serie[-1], 1)
        mm_semana = round(sum(serie[-7:]), 1)
        mm_anual  = round(sum(serie), 1)

        media_diaria    = round(normal_dia(meses, fecha), 2)
        media_semana    = round(normal_ventana(meses, fecha, 7), 1)
        media_hasta_hoy = round(normal_hasta(meses, fecha), 1)

        print("dia=%smm  7d=%smm  anual=%smm  (%s)"
              % (mm_dia, mm_semana, mm_anual, fecha.strftime("%d/%m")))

        anom_dia    = calcular_anomalia(mm_dia,    media_diaria)
        anom_semana = calcular_anomalia(mm_semana, media_semana)
        anom_anual  = calcular_anomalia(mm_anual,  media_hasta_hoy)

        provincias_resultado.append({
            "id": prov["id"], "nombre": prov["nombre"], "ccaa": prov["ccaa"],
            "lat": prov["lat"], "lon": prov["lon"],
            "mm_ayer":   mm_dia,
            "mm_semana": mm_semana,
            "mm_anual":  mm_anual,
            "media_diaria_mm":    media_diaria,
            "media_semana_mm":    media_semana,
            "media_anual_mm":     anual,
            "media_hasta_hoy_mm": media_hasta_hoy,
            "anomalia_ayer_pct":   anom_dia,
            "anomalia_semana_pct": anom_semana,
            "anomalia_anual_pct":  anom_anual,
            "etiqueta_ayer":   etiqueta_anomalia(anom_dia),
            "etiqueta_semana": etiqueta_anomalia(anom_semana),
            "etiqueta_anual":  etiqueta_anomalia(anom_anual),
            "color_ayer":        color_lluvia(mm_dia),
            "color_semana":      color_lluvia(mm_semana),
            "color_anual":       color_lluvia(mm_anual),
            "color_anom_ayer":   color_anomalia(anom_dia),
            "color_anom_semana": color_anomalia(anom_semana),
            "color_anom_anual":  color_anomalia(anom_anual),
        })

    if len(provincias_resultado) < len(PROVINCIAS):
        # Publicar 47 provincias como si fueran 52 deja huecos en blanco en el
        # mapa que parecen "no llovio". Mejor enterarse en el registro de la accion.
        print("\nAVISO: %d de %d provincias sin datos."
              % (len(PROVINCIAS) - len(provincias_resultado), len(PROVINCIAS)))

    os.makedirs("docs", exist_ok=True)
    output = {
        "ultima_actualizacion": hoy.isoformat(),
        "fecha_legible":  hoy.strftime("%d/%m/%Y a las %H:%M"),
        # La fecha REAL del ultimo dato, no una supuesta. El mapa la rotula.
        "fecha_datos":    ultimo_global.strftime("%d/%m/%Y") if ultimo_global else None,
        "fuente":         "Open-Meteo (ERA5)",
        "normales":       "ERA5-Land 1991-2020 · calentamientoglobal.es",
        "provincias":     provincias_resultado,
    }

    with open("docs/lluvias_nacional.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n\u2713 docs/lluvias_nacional.json generado \u00b7 %d provincias \u00b7 datos hasta %s"
          % (len(provincias_resultado), ultimo_global.strftime("%d/%m/%Y") if ultimo_global else "?"))


if __name__ == "__main__":
    procesar_lluvias()
