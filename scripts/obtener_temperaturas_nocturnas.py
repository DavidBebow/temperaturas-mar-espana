import requests
import json
import os
import time
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed

API_KEY  = os.environ.get("AEMET_API_KEY", "")
BASE_URL = "https://opendata.aemet.es/opendata/api"
HEADERS  = {"api_key": API_KEY, "Accept": "application/json"}

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

hoy  = date.today()
ayer = hoy - timedelta(days=1)

def fmt(d):
    return d.strftime("%Y-%m-%dT00:00:00UTC")

def aemet_tramo(idema, fecha_ini, fecha_fin):
    """Una petición AEMET de hasta 31 días. Devuelve lista de registros."""
    url = (
        f"{BASE_URL}/valores/climatologicos/diarios/datos"
        f"/fechaini/{fmt(fecha_ini)}/fechafin/{fmt(fecha_fin)}"
        f"/estacion/{idema}"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            body = r.json()
            if body.get("estado") == 200:
                datos_url = body.get("datos")
                if datos_url:
                    r2 = requests.get(datos_url, timeout=15)
                    if r2.status_code == 200:
                        return r2.json()
    except Exception as e:
        print(f"    Error {idema} {fecha_ini}: {e}")
    return []

def aemet_ciudad(ciudad):
    """Descarga todos los tramos necesarios para una ciudad en paralelo interno."""
    mes_act   = hoy.month
    anyo_act  = hoy.year
    anyo_ant  = hoy.year - 1

    inicio_mes_act  = date(anyo_act, mes_act, 1)
    inicio_anyo_act = date(anyo_act, 1, 1)
    inicio_mes_ant  = date(anyo_ant, mes_act, 1)
    fin_mes_ant     = (date(anyo_ant, mes_act % 12 + 1, 1) - timedelta(days=1)) \
                      if mes_act < 12 else date(anyo_ant, 12, 31)

    def tramos(fecha_ini, fecha_fin):
        """Fragmenta un rango en tramos de 15 días (límite máximo de AEMET)."""
        resultado = []
        cursor = fecha_ini
        while cursor <= fecha_fin:
            fin = min(cursor + timedelta(days=14), fecha_fin)
            resultado.append((cursor, fin))
            cursor = fin + timedelta(days=1)
        return resultado

    # Lanzamos todos los tramos de esta ciudad en paralelo (máx 8 hilos internos)
    todos_tramos = (
        [("mes", ini, fin) for ini, fin in tramos(inicio_mes_act, ayer)] +
        [("anyo", ini, fin) for ini, fin in tramos(inicio_anyo_act, ayer)] +
        [("ant",  ini, fin) for ini, fin in tramos(inicio_mes_ant, fin_mes_ant)]
    )

    regs_mes  = []
    regs_anyo = []
    regs_ant  = []

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(aemet_tramo, ciudad["idema"], ini, fin): etiq
                   for etiq, ini, fin in todos_tramos}
        for future in as_completed(futures):
            etiq = futures[future]
            datos = future.result()
            if etiq == "mes":
                regs_mes  += datos
            elif etiq == "anyo":
                regs_anyo += datos
            else:
                regs_ant  += datos

    return regs_mes, regs_anyo, regs_ant

def parse_float(val):
    if val is None or val == "" or val == "Ip":
        return None
    try:
        return float(str(val).replace(",", "."))
    except:
        return None

def media(lista):
    vals = [v for v in lista if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None

def contar_nt(lista):
    return sum(1 for v in lista if v is not None and v >= 20.0)

def calcular_color(t):
    if t is None:  return "#888888", "Sin datos"
    if t >= 25:    return "#CC2200", "Muy cálida"
    if t >= 20:    return "#FF6600", "Tropical"
    if t >= 15:    return "#FFAA00", "Cálida"
    if t >= 10:    return "#44AA66", "Templada"
    if t >= 5:     return "#3399CC", "Fresca"
    return "#0055AA", "Fría"

def procesar_ciudad(ciudad):
    """Procesa una ciudad completa. Se llama desde el pool externo."""
    regs_mes, regs_anyo, regs_ant = aemet_ciudad(ciudad)

    ayer_str = ayer.strftime("%Y-%m-%d")
    t_min_anoche = None
    for r in regs_mes:
        if r.get("fecha", "") == ayer_str:
            t_min_anoche = parse_float(r.get("tmin"))
            break

    mins_mes = [parse_float(r.get("tmin")) for r in regs_mes]
    maxs_mes = [parse_float(r.get("tmax")) for r in regs_mes]
    mins_anyo = [parse_float(r.get("tmin")) for r in regs_anyo]
    mins_ant  = [parse_float(r.get("tmin")) for r in regs_ant]
    maxs_ant  = [parse_float(r.get("tmax")) for r in regs_ant]

    media_min_mes     = media(mins_mes)
    media_max_mes     = media(maxs_mes)
    media_min_mes_ant = media(mins_ant)
    media_max_mes_ant = media(maxs_ant)

    diff_min = round(media_min_mes - media_min_mes_ant, 1) \
               if media_min_mes is not None and media_min_mes_ant is not None else None
    diff_max = round(media_max_mes - media_max_mes_ant, 1) \
               if media_max_mes is not None and media_max_mes_ant is not None else None

    color, etiqueta = calcular_color(t_min_anoche)

    return {
        "id":                ciudad["id"],
        "nombre":            ciudad["nombre"],
        "ccaa":              ciudad["ccaa"],
        "lat":               ciudad["lat"],
        "lon":               ciudad["lon"],
        "t_min_anoche":      round(t_min_anoche, 1) if t_min_anoche is not None else None,
        "media_min_mes":     media_min_mes,
        "media_max_mes":     media_max_mes,
        "media_min_mes_ant": media_min_mes_ant,
        "media_max_mes_ant": media_max_mes_ant,
        "diff_min_vs_ant":   diff_min,
        "diff_max_vs_ant":   diff_max,
        "nt_mes":            contar_nt(mins_mes),
        "nt_anyo":           contar_nt(mins_anyo),
        "color":             color,
        "etiqueta":          etiqueta,
    }

def procesar():
    if not API_KEY:
        print("ERROR: AEMET_API_KEY no definida.")
        return

    print(f"Procesando {len(CIUDADES)} ciudades en paralelo (10 hilos)...")
    os.makedirs("docs", exist_ok=True)

    MESES = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    mes_act = hoy.month

    resultado = [None] * len(CIUDADES)

    # 10 ciudades en paralelo — equilibrio entre velocidad y rate limit AEMET
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(procesar_ciudad, c): i for i, c in enumerate(CIUDADES)}
        completadas = 0
        for future in as_completed(futures):
            idx = futures[future]
            try:
                resultado[idx] = future.result()
                completadas += 1
                print(f"  [{completadas}/{len(CIUDADES)}] {resultado[idx]['nombre']} ✓  "
                      f"tmin={resultado[idx]['t_min_anoche']} nt_mes={resultado[idx]['nt_mes']}")
            except Exception as e:
                print(f"  Error ciudad idx {idx}: {e}")
                resultado[idx] = {**CIUDADES[idx], "t_min_anoche": None,
                    "media_min_mes": None, "media_max_mes": None,
                    "media_min_mes_ant": None, "media_max_mes_ant": None,
                    "diff_min_vs_ant": None, "diff_max_vs_ant": None,
                    "nt_mes": 0, "nt_anyo": 0, "color": "#888888", "etiqueta": "Sin datos"}

    output = {
        "ultima_actualizacion": datetime.now().isoformat(),
        "fecha_legible":        datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "mes_actual":           MESES[mes_act - 1].capitalize(),
        "anyo_actual":          hoy.year,
        "mes_anterior_ref":     f"{MESES[mes_act - 1]} {hoy.year - 1}",
        "fuente":               "AEMET OpenData",
        "total_ciudades":       len(resultado),
        "ciudades":             resultado,
    }

    with open("docs/temperaturas_nocturnas.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Generado con {len(resultado)} ciudades.")

if __name__ == "__main__":
    procesar()
