import requests
import json
import os
import time
from datetime import datetime, timedelta

CIUDADES = [
    {"id": "vitoria",      "nombre": "Vitoria-Gasteiz",       "provincia": "Álava",        "lat": 42.85, "lon": -2.67},
    {"id": "albacete",     "nombre": "Albacete",               "provincia": "Albacete",     "lat": 38.99, "lon": -1.86},
    {"id": "alicante",     "nombre": "Alicante",               "provincia": "Alicante",     "lat": 38.35, "lon": -0.48},
    {"id": "almeria",      "nombre": "Almería",                "provincia": "Almería",      "lat": 36.84, "lon": -2.47},
    {"id": "avila",        "nombre": "Ávila",                  "provincia": "Ávila",        "lat": 40.65, "lon": -4.70},
    {"id": "badajoz",      "nombre": "Badajoz",                "provincia": "Badajoz",      "lat": 38.88, "lon": -6.97},
    {"id": "barcelona",    "nombre": "Barcelona",              "provincia": "Barcelona",    "lat": 41.38, "lon":  2.18},
    {"id": "bilbao",       "nombre": "Bilbao",                 "provincia": "Vizcaya",      "lat": 43.26, "lon": -2.93},
    {"id": "burgos",       "nombre": "Burgos",                 "provincia": "Burgos",       "lat": 42.34, "lon": -3.70},
    {"id": "caceres",      "nombre": "Cáceres",                "provincia": "Cáceres",      "lat": 39.47, "lon": -6.37},
    {"id": "cadiz",        "nombre": "Cádiz",                  "provincia": "Cádiz",        "lat": 36.53, "lon": -6.30},
    {"id": "santander",    "nombre": "Santander",              "provincia": "Cantabria",    "lat": 43.46, "lon": -3.81},
    {"id": "castellon",    "nombre": "Castellón",              "provincia": "Castellón",    "lat": 39.99, "lon": -0.03},
    {"id": "ciudad_real",  "nombre": "Ciudad Real",            "provincia": "Ciudad Real",  "lat": 38.99, "lon": -3.93},
    {"id": "cordoba",      "nombre": "Córdoba",                "provincia": "Córdoba",      "lat": 37.89, "lon": -4.78},
    {"id": "cuenca",       "nombre": "Cuenca",                 "provincia": "Cuenca",       "lat": 40.07, "lon": -2.13},
    {"id": "girona",       "nombre": "Girona",                 "provincia": "Girona",       "lat": 41.98, "lon":  2.82},
    {"id": "granada",      "nombre": "Granada",                "provincia": "Granada",      "lat": 37.18, "lon": -3.60},
    {"id": "guadalajara",  "nombre": "Guadalajara",            "provincia": "Guadalajara",  "lat": 40.63, "lon": -3.17},
    {"id": "san_sebastian","nombre": "San Sebastián",          "provincia": "Guipúzcoa",    "lat": 43.32, "lon": -1.98},
    {"id": "huelva",       "nombre": "Huelva",                 "provincia": "Huelva",       "lat": 37.26, "lon": -6.95},
    {"id": "huesca",       "nombre": "Huesca",                 "provincia": "Huesca",       "lat": 42.14, "lon": -0.41},
    {"id": "jaen",         "nombre": "Jaén",                   "provincia": "Jaén",         "lat": 37.77, "lon": -3.79},
    {"id": "coruna",       "nombre": "A Coruña",               "provincia": "A Coruña",     "lat": 43.37, "lon": -8.40},
    {"id": "logrono",      "nombre": "Logroño",                "provincia": "La Rioja",     "lat": 42.47, "lon": -2.44},
    {"id": "las_palmas",   "nombre": "Las Palmas",             "provincia": "Las Palmas",   "lat": 28.10, "lon": -15.41},
    {"id": "leon",         "nombre": "León",                   "provincia": "León",         "lat": 42.60, "lon": -5.57},
    {"id": "lleida",       "nombre": "Lleida",                 "provincia": "Lleida",       "lat": 41.62, "lon":  0.62},
    {"id": "lugo",         "nombre": "Lugo",                   "provincia": "Lugo",         "lat": 43.01, "lon": -7.56},
    {"id": "madrid",       "nombre": "Madrid",                 "provincia": "Madrid",       "lat": 40.42, "lon": -3.70},
    {"id": "malaga",       "nombre": "Málaga",                 "provincia": "Málaga",       "lat": 36.72, "lon": -4.42},
    {"id": "murcia",       "nombre": "Murcia",                 "provincia": "Murcia",       "lat": 37.99, "lon": -1.13},
    {"id": "pamplona",     "nombre": "Pamplona",               "provincia": "Navarra",      "lat": 42.82, "lon": -1.65},
    {"id": "ourense",      "nombre": "Ourense",                "provincia": "Ourense",      "lat": 42.34, "lon": -7.86},
    {"id": "palencia",     "nombre": "Palencia",               "provincia": "Palencia",     "lat": 42.01, "lon": -4.53},
    {"id": "pontevedra",   "nombre": "Pontevedra",             "provincia": "Pontevedra",   "lat": 42.43, "lon": -8.65},
    {"id": "salamanca",    "nombre": "Salamanca",              "provincia": "Salamanca",    "lat": 40.97, "lon": -5.66},
    {"id": "tenerife",     "nombre": "Santa Cruz Tenerife",    "provincia": "Tenerife",     "lat": 28.46, "lon": -16.25},
    {"id": "segovia",      "nombre": "Segovia",                "provincia": "Segovia",      "lat": 40.95, "lon": -4.12},
    {"id": "sevilla",      "nombre": "Sevilla",                "provincia": "Sevilla",      "lat": 37.39, "lon": -5.99},
    {"id": "soria",        "nombre": "Soria",                  "provincia": "Soria",        "lat": 41.76, "lon": -2.47},
    {"id": "tarragona",    "nombre": "Tarragona",              "provincia": "Tarragona",    "lat": 41.12, "lon":  1.25},
    {"id": "teruel",       "nombre": "Teruel",                 "provincia": "Teruel",       "lat": 40.35, "lon": -1.11},
    {"id": "toledo",       "nombre": "Toledo",                 "provincia": "Toledo",       "lat": 39.86, "lon": -4.02},
    {"id": "valencia",     "nombre": "Valencia",               "provincia": "Valencia",     "lat": 39.47, "lon": -0.38},
    {"id": "valladolid",   "nombre": "Valladolid",             "provincia": "Valladolid",   "lat": 41.65, "lon": -4.72},
    {"id": "zamora",       "nombre": "Zamora",                 "provincia": "Zamora",       "lat": 41.50, "lon": -5.75},
    {"id": "zaragoza",     "nombre": "Zaragoza",               "provincia": "Zaragoza",     "lat": 41.65, "lon": -0.88},
    {"id": "ceuta",        "nombre": "Ceuta",                  "provincia": "Ceuta",        "lat": 35.89, "lon": -5.32},
    {"id": "melilla",      "nombre": "Melilla",                "provincia": "Melilla",      "lat": 35.29, "lon": -2.94},
]

# Límites OMS 2021 (µg/m³, media 24h)
LIMITES_OMS = {
    "pm25": 15.0,
    "pm10": 45.0,
    "no2":  25.0,
    "o3":   100.0,
    "so2":  40.0,
}

HEADERS_BASE = {
    "Accept": "application/json",
    "User-Agent": "calentamientoglobal.es/calidad-aire"
}

def buscar_estacion(lat, lon, api_key):
    """Busca la estación OpenAQ más cercana a las coordenadas dadas."""
    url = "https://api.openaq.org/v3/locations"
    params = {
        "coordinates": f"{lat},{lon}",
        "radius":       50000,
        "limit":        5,
        "order_by":     "distance",
    }
    headers = {**HEADERS_BASE, "X-API-Key": api_key}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        resultados = r.json().get("results", [])
        if resultados:
            return resultados[0]["id"]
        return None
    except Exception as e:
        print(f"    Error buscando estación: {e}")
        return None

def obtener_mediciones(location_id, api_key):
    """Obtiene las últimas mediciones de una estación."""
    url = f"https://api.openaq.org/v3/locations/{location_id}/latest"
    headers = {**HEADERS_BASE, "X-API-Key": api_key}
    valores = {}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        for entry in r.json().get("results", []):
            param = entry.get("parameter", {}).get("name", "").lower()
            val   = entry.get("value")
            if param and val is not None and val >= 0:
                valores[param] = round(float(val), 1)
        return valores
    except Exception as e:
        print(f"    Error obteniendo mediciones: {e}")
        return {}

def clasificar_calidad_pm25(pm25):
    """Clasifica la calidad del aire según PM2.5 y límites OMS."""
    if pm25 is None:
        return "#888888", "Sin datos", 0
    if pm25 < 5:
        return "#0066CC", "Excelente", 1
    if pm25 < 15:
        return "#44AA66", "Buena",     2
    if pm25 < 25:
        return "#FFCC44", "Moderada",  3
    if pm25 < 50:
        return "#FF8822", "Mala",      4
    return "#CC2200", "Muy mala",      5

def detectar_sahariano(pm25, pm10):
    """Detecta probable episodio de polvo sahariano."""
    if pm10 is None or pm25 is None:
        return False
    if pm10 > 50 and pm25 > 0:
        ratio = pm10 / pm25
        return ratio > 3.0
    return False

def supera_limite_oms(valores):
    """Devuelve True si algún contaminante supera el límite OMS."""
    for param, limite in LIMITES_OMS.items():
        val = valores.get(param)
        if val is not None and val > limite:
            return True
    return False

def contaminante_dominante(valores):
    """Devuelve el contaminante más problemático del día."""
    if not valores:
        return None
    peor_ratio = 0
    peor_param = None
    nombres = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "o3": "O₃", "so2": "SO₂"}
    for param, limite in LIMITES_OMS.items():
        val = valores.get(param)
        if val is not None and limite > 0:
            ratio = val / limite
            if ratio > peor_ratio:
                peor_ratio = ratio
                peor_param = param
    if peor_param:
        return nombres.get(peor_param, peor_param)
    return None

def calcular_max_racha(entradas):
    max_racha = racha = 0
    for e in sorted(entradas, key=lambda x: x["fecha"]):
        if e["supera_oms"]:
            racha += 1
            max_racha = max(max_racha, racha)
        else:
            racha = 0
    return max_racha

def actualizar_historial(resultados):
    ruta = "docs/historial_calidad_aire.json"
    hoy  = datetime.now().strftime("%Y-%m-%d")

    historial = {}
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            historial = json.load(f)

    for r in resultados:
        cid = r["id"]
        if cid not in historial:
            historial[cid] = []

        fechas = {e["fecha"] for e in historial[cid]}

        if hoy not in fechas:
            historial[cid].append({
                "fecha":       hoy,
                "supera_oms":  r["supera_oms"],
                "pm25":        r.get("pm25"),
            })

        # Rellenar día sin datos si no existe
        for e in historial[cid]:
            if "supera_oms" not in e:
                e["supera_oms"] = False

        historial[cid] = sorted(
            historial[cid], key=lambda x: x["fecha"], reverse=True
        )[:365]

        # Calcular días consecutivos
        dias_consec = 0
        supera_hoy  = r["supera_oms"]
        for e in historial[cid]:
            if e["supera_oms"] == supera_hoy:
                dias_consec += 1
            else:
                break

        r["dias_consecutivos_estado"] = dias_consec
        r["max_dias_sobre_oms"]       = calcular_max_racha(historial[cid])
        r["dias_sobre_oms_anio"]      = sum(
            1 for e in historial[cid]
            if e["supera_oms"] and e["fecha"].startswith(str(datetime.now().year))
        )

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)

    return resultados

def generar_json():
    api_key = os.environ.get("OPENAQ_KEY")
    if not api_key:
        print("ERROR: Falta OPENAQ_KEY")
        return

    print(f"\n{'='*60}")
    print(f"Actualizando calidad del aire — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    # Cargar caché de IDs de estaciones para no buscarlas cada vez
    cache_ruta = "docs/cache_estaciones.json"
    cache = {}
    if os.path.exists(cache_ruta):
        with open(cache_ruta, "r") as f:
            cache = json.load(f)

    resultados  = []
    sin_datos   = 0

    for ciudad in CIUDADES:
        cid = ciudad["id"]
        print(f"Procesando: {ciudad['nombre']}...")

        # Buscar estación si no está en caché
        if cid not in cache:
            station_id = buscar_estacion(ciudad["lat"], ciudad["lon"], api_key)
            if station_id:
                cache[cid] = station_id
                print(f"  Estación encontrada: {station_id}")
            else:
                print(f"  Sin estación disponible")
            time.sleep(0.5)
        else:
            station_id = cache[cid]

        valores = {}
        if station_id:
            valores = obtener_mediciones(station_id, api_key)
            time.sleep(0.3)

        pm25 = valores.get("pm25")
        pm10 = valores.get("pm10")
        no2  = valores.get("no2")
        o3   = valores.get("o3")
        so2  = valores.get("so2")

        color, etiqueta, nivel = clasificar_calidad_pm25(pm25)
        sahariano   = detectar_sahariano(pm25, pm10)
        supera_oms  = supera_limite_oms(valores)
        contaminante = contaminante_dominante(valores)

        if not valores:
            sin_datos += 1

        resultado = {
            "id":           cid,
            "nombre":       ciudad["nombre"],
            "provincia":    ciudad["provincia"],
            "lat":          ciudad["lat"],
            "lon":          ciudad["lon"],
            "station_id":   station_id,
            "pm25":         pm25,
            "pm10":         pm10,
            "no2":          no2,
            "o3":           o3,
            "so2":          so2,
            "color":        color,
            "etiqueta":     etiqueta,
            "nivel":        nivel,
            "supera_oms":   supera_oms,
            "sahariano":    sahariano,
            "contaminante_dominante": contaminante,
            # Estos se rellenan en actualizar_historial
            "dias_consecutivos_estado": 0,
            "max_dias_sobre_oms":       0,
            "dias_sobre_oms_anio":      0,
        }
        resultados.append(resultado)

        estado = f"{etiqueta} | PM2.5: {pm25}" if pm25 else "Sin datos"
        if sahariano:
            estado += " 🏜️ SAHARIANO"
        print(f"  ✓ {estado}")

    # Guardar caché actualizada
    with open(cache_ruta, "w") as f:
        json.dump(cache, f, indent=2)

    resultados = actualizar_historial(resultados)

    ciudades_buenas = sum(1 for r in resultados if r["nivel"] <= 2 and r["nivel"] > 0)
    ciudades_malas  = sum(1 for r in resultados if r["nivel"] >= 4)
    saharianos      = sum(1 for r in resultados if r["sahariano"])

    os.makedirs("docs", exist_ok=True)
    output = {
        "ultima_actualizacion": datetime.now().isoformat(),
        "fecha_legible":        datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "total_ciudades":       len(CIUDADES),
        "ciudades_con_datos":   len(CIUDADES) - sin_datos,
        "ciudades_buena_calidad": ciudades_buenas,
        "ciudades_mala_calidad":  ciudades_malas,
        "episodio_sahariano":   saharianos > 3,
        "ciudades_saharianas":  saharianos,
        "fuente":               "OpenAQ v3 — Red de estaciones oficiales",
        "nota_oms":             "Límites OMS 2021: PM2.5 <15, PM10 <45, NO2 <25, O3 <100 µg/m³",
        "ciudades":             resultados
    }

    with open("docs/calidad_aire.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ JSON guardado en docs/calidad_aire.json")
    print(f"✓ {len(CIUDADES) - sin_datos}/{len(CIUDADES)} ciudades con datos")
    print(f"✓ {ciudades_malas} ciudades con mala calidad")
    if saharianos:
        print(f"⚠️  {saharianos} ciudades con episodio sahariano probable\n")

if __name__ == "__main__":
    generar_json()
