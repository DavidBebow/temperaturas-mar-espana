import requests
import json
import os
import sys
import time
from datetime import datetime, timedelta
CIUDADES = [
    {"id": "vitoria",      "nombre": "Vitoria-Gasteiz",     "provincia": "Álava",        "lat": 42.85, "lon": -2.67},
    {"id": "albacete",     "nombre": "Albacete",             "provincia": "Albacete",     "lat": 38.99, "lon": -1.86},
    {"id": "alicante",     "nombre": "Alicante",             "provincia": "Alicante",     "lat": 38.35, "lon": -0.48},
    {"id": "almeria",      "nombre": "Almería",              "provincia": "Almería",      "lat": 36.84, "lon": -2.47},
    {"id": "avila",        "nombre": "Ávila",                "provincia": "Ávila",        "lat": 40.65, "lon": -4.70},
    {"id": "badajoz",      "nombre": "Badajoz",              "provincia": "Badajoz",      "lat": 38.88, "lon": -6.97},
    {"id": "barcelona",    "nombre": "Barcelona",            "provincia": "Barcelona",    "lat": 41.38, "lon":  2.18},
    {"id": "bilbao",       "nombre": "Bilbao",               "provincia": "Vizcaya",      "lat": 43.26, "lon": -2.93},
    {"id": "burgos",       "nombre": "Burgos",               "provincia": "Burgos",       "lat": 42.34, "lon": -3.70},
    {"id": "caceres",      "nombre": "Cáceres",              "provincia": "Cáceres",      "lat": 39.47, "lon": -6.37},
    {"id": "cadiz",        "nombre": "Cádiz",                "provincia": "Cádiz",        "lat": 36.53, "lon": -6.30},
    {"id": "santander",    "nombre": "Santander",            "provincia": "Cantabria",    "lat": 43.46, "lon": -3.81},
    {"id": "castellon",    "nombre": "Castellón",            "provincia": "Castellón",    "lat": 39.99, "lon": -0.03},
    {"id": "ciudad_real",  "nombre": "Ciudad Real",          "provincia": "Ciudad Real",  "lat": 38.99, "lon": -3.93},
    {"id": "cordoba",      "nombre": "Córdoba",              "provincia": "Córdoba",      "lat": 37.89, "lon": -4.78},
    {"id": "cuenca",       "nombre": "Cuenca",               "provincia": "Cuenca",       "lat": 40.07, "lon": -2.13},
    {"id": "girona",       "nombre": "Girona",               "provincia": "Girona",       "lat": 41.98, "lon":  2.82},
    {"id": "granada",      "nombre": "Granada",              "provincia": "Granada",      "lat": 37.18, "lon": -3.60},
    {"id": "guadalajara",  "nombre": "Guadalajara",          "provincia": "Guadalajara",  "lat": 40.63, "lon": -3.17},
    {"id": "san_sebastian","nombre": "San Sebastián",        "provincia": "Guipúzcoa",    "lat": 43.32, "lon": -1.98},
    {"id": "huelva",       "nombre": "Huelva",               "provincia": "Huelva",       "lat": 37.26, "lon": -6.95},
    {"id": "huesca",       "nombre": "Huesca",               "provincia": "Huesca",       "lat": 42.14, "lon": -0.41},
    {"id": "jaen",         "nombre": "Jaén",                 "provincia": "Jaén",         "lat": 37.77, "lon": -3.79},
    {"id": "coruna",       "nombre": "A Coruña",             "provincia": "A Coruña",     "lat": 43.37, "lon": -8.40},
    {"id": "logrono",      "nombre": "Logroño",              "provincia": "La Rioja",     "lat": 42.47, "lon": -2.44},
    {"id": "las_palmas",   "nombre": "Las Palmas",           "provincia": "Las Palmas",   "lat": 28.10, "lon": -15.41},
    {"id": "leon",         "nombre": "León",                 "provincia": "León",         "lat": 42.60, "lon": -5.57},
    {"id": "lleida",       "nombre": "Lleida",               "provincia": "Lleida",       "lat": 41.62, "lon":  0.62},
    {"id": "lugo",         "nombre": "Lugo",                 "provincia": "Lugo",         "lat": 43.01, "lon": -7.56},
    {"id": "madrid",       "nombre": "Madrid",               "provincia": "Madrid",       "lat": 40.42, "lon": -3.70},
    {"id": "malaga",       "nombre": "Málaga",               "provincia": "Málaga",       "lat": 36.72, "lon": -4.42},
    {"id": "murcia",       "nombre": "Murcia",               "provincia": "Murcia",       "lat": 37.99, "lon": -1.13},
    {"id": "pamplona",     "nombre": "Pamplona",             "provincia": "Navarra",      "lat": 42.82, "lon": -1.65},
    {"id": "ourense",      "nombre": "Ourense",              "provincia": "Ourense",      "lat": 42.34, "lon": -7.86},
    {"id": "palencia",     "nombre": "Palencia",             "provincia": "Palencia",     "lat": 42.01, "lon": -4.53},
    {"id": "pontevedra",   "nombre": "Pontevedra",           "provincia": "Pontevedra",   "lat": 42.43, "lon": -8.65},
    {"id": "salamanca",    "nombre": "Salamanca",            "provincia": "Salamanca",    "lat": 40.97, "lon": -5.66},
    {"id": "tenerife",     "nombre": "Santa Cruz Tenerife",  "provincia": "Tenerife",     "lat": 28.46, "lon": -16.25},
    {"id": "segovia",      "nombre": "Segovia",              "provincia": "Segovia",      "lat": 40.95, "lon": -4.12},
    {"id": "sevilla",      "nombre": "Sevilla",              "provincia": "Sevilla",      "lat": 37.39, "lon": -5.99},
    {"id": "soria",        "nombre": "Soria",                "provincia": "Soria",        "lat": 41.76, "lon": -2.47},
    {"id": "tarragona",    "nombre": "Tarragona",            "provincia": "Tarragona",    "lat": 41.12, "lon":  1.25},
    {"id": "teruel",       "nombre": "Teruel",               "provincia": "Teruel",       "lat": 40.35, "lon": -1.11},
    {"id": "toledo",       "nombre": "Toledo",               "provincia": "Toledo",       "lat": 39.86, "lon": -4.02},
    {"id": "valencia",     "nombre": "Valencia",             "provincia": "Valencia",     "lat": 39.47, "lon": -0.38},
    {"id": "valladolid",   "nombre": "Valladolid",           "provincia": "Valladolid",   "lat": 41.65, "lon": -4.72},
    {"id": "zamora",       "nombre": "Zamora",               "provincia": "Zamora",       "lat": 41.50, "lon": -5.75},
    {"id": "zaragoza",     "nombre": "Zaragoza",             "provincia": "Zaragoza",     "lat": 41.65, "lon": -0.88},
    {"id": "ceuta",        "nombre": "Ceuta",                "provincia": "Ceuta",        "lat": 35.89, "lon": -5.32},
    {"id": "melilla",      "nombre": "Melilla",              "provincia": "Melilla",      "lat": 35.29, "lon": -2.94},
]
LIMITES_OMS = {
    "pm25": 15.0,
    "pm10": 45.0,
    "no2":  25.0,
    "o3":   100.0,
    "so2":  40.0,
}

# Cuántas ciudades por petición. Open-Meteo admite múltiples coordenadas en
# una sola llamada; con 50 basta un request. El chunk deja margen si algún día
# crece la lista, y evita por completo el rate limiting de 50 llamadas sueltas.
CHUNK_CIUDADES = 50


def extraer_valores(current):
    """Normaliza el bloque 'current' de una ubicación a nuestro esquema."""
    pm25 = current.get("pm2_5")
    pm10 = current.get("pm10")
    no2  = current.get("nitrogen_dioxide")
    o3   = current.get("ozone")
    so2  = current.get("sulphur_dioxide")
    aqi  = current.get("european_aqi")
    dust = current.get("dust")
    return {
        "pm25": round(pm25, 1) if pm25 is not None else None,
        "pm10": round(pm10, 1) if pm10 is not None else None,
        "no2":  round(no2,  1) if no2  is not None else None,
        "o3":   round(o3,   1) if o3   is not None else None,
        "so2":  round(so2,  1) if so2  is not None else None,
        "aqi_europeo": int(aqi) if aqi is not None else None,
        "dust": round(dust, 1) if dust is not None else None,
    }


def _pedir_chunk(ciudades, intentos=4):
    """Una petición para varias ciudades. Devuelve lista de dicts 'current'
    alineada con 'ciudades', o None si falla tras todos los reintentos."""
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude":  ",".join(str(c["lat"]) for c in ciudades),
        "longitude": ",".join(str(c["lon"]) for c in ciudades),
        "current":   "pm10,pm2_5,nitrogen_dioxide,ozone,sulphur_dioxide,european_aqi,dust",
        "timezone":  "Europe/Madrid",
    }
    for intento in range(1, intentos + 1):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            # Con varias coordenadas Open-Meteo devuelve una lista; con una
            # sola, un dict. Normalizamos siempre a lista.
            if isinstance(data, dict):
                data = [data]
            if len(data) != len(ciudades):
                raise ValueError(
                    f"respuesta con {len(data)} ubicaciones, esperadas {len(ciudades)}"
                )
            return [loc.get("current", {}) for loc in data]
        except Exception as e:
            espera = 2 ** intento  # 2, 4, 8, 16 s
            print(f"  Intento {intento}/{intentos} falló: {e}")
            if intento < intentos:
                print(f"  Reintentando en {espera}s...")
                time.sleep(espera)
    return None


def obtener_calidad_todas(ciudades):
    """Obtiene la calidad del aire de todas las ciudades en pocas peticiones.
    Devuelve lista de dicts de valores alineada con 'ciudades'. Si algún chunk
    falla del todo, esas posiciones quedan como {} (Sin datos), pero el resto
    se conserva."""
    valores = []
    for i in range(0, len(ciudades), CHUNK_CIUDADES):
        chunk = ciudades[i:i + CHUNK_CIUDADES]
        currents = _pedir_chunk(chunk)
        if currents is None:
            print(f"  ERROR: chunk {i//CHUNK_CIUDADES + 1} sin datos tras varios intentos.")
            valores.extend({} for _ in chunk)
        else:
            valores.extend(extraer_valores(c) for c in currents)
        if i + CHUNK_CIUDADES < len(ciudades):
            time.sleep(1)  # cortesía entre chunks (solo si hay más de uno)
    return valores


def clasificar_calidad_pm25(pm25):
    if pm25 is None:
        return None, None, 0
    if pm25 < 5:  return "#0066CC", "Excelente", 1
    if pm25 < 15: return "#44AA66", "Buena",     2
    if pm25 < 25: return "#FFCC44", "Moderada",  3
    if pm25 < 50: return "#FF8822", "Mala",      4
    return "#CC2200", "Muy mala", 5
def clasificar_aqi_europeo(aqi):
    if aqi is None: return "#888888", "Sin datos", 0
    if aqi < 20:    return "#0066CC", "Muy buena", 1
    if aqi < 40:    return "#44AA66", "Buena",     2
    if aqi < 60:    return "#FFCC44", "Moderada",  3
    if aqi < 80:    return "#FF8822", "Mala",      4
    if aqi < 100:   return "#CC2200", "Muy mala",  5
    return "#880000", "Extrema", 5
def clasificar_ciudad(pm25, aqi_europeo):
    color, etiqueta, nivel = clasificar_calidad_pm25(pm25)
    if color is not None:
        return color, etiqueta, nivel, pm25, "µg/m³ PM2.5"
    color, etiqueta, nivel = clasificar_aqi_europeo(aqi_europeo)
    return color, etiqueta, nivel, aqi_europeo, "AQI europeo"
def detectar_sahariano(pm10, dust):
    if dust is not None and dust > 50:
        return True
    if pm10 is not None and dust is not None and pm10 > 0:
        if (dust / pm10) > 0.5 and pm10 > 40:
            return True
    return False
def supera_limite_oms(valores):
    for param, limite in LIMITES_OMS.items():
        val = valores.get(param)
        if val is not None and val > limite:
            return True
    return False
def contaminante_dominante(valores):
    nombres = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "o3": "O₃", "so2": "SO₂"}
    peor_ratio, peor_param = 0, None
    for param, limite in LIMITES_OMS.items():
        val = valores.get(param)
        if val is not None and limite > 0:
            ratio = val / limite
            if ratio > peor_ratio:
                peor_ratio, peor_param = ratio, param
    return nombres.get(peor_param) if peor_param else None
def calcular_max_racha(entradas):
    max_racha = racha = 0
    for e in sorted(entradas, key=lambda x: x["fecha"]):
        if e.get("supera_oms"):
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
                "fecha":      hoy,
                "supera_oms": r["supera_oms"],
                "pm25":       r.get("pm25"),
            })
        historial[cid] = sorted(
            historial[cid], key=lambda x: x["fecha"], reverse=True
        )[:365]
        supera_hoy  = r["supera_oms"]
        dias_consec = 0
        for e in historial[cid]:
            if e.get("supera_oms") == supera_hoy:
                dias_consec += 1
            else:
                break
        r["dias_consecutivos_estado"] = dias_consec
        r["max_dias_sobre_oms"]       = calcular_max_racha(historial[cid])
        r["dias_sobre_oms_anio"]      = sum(
            1 for e in historial[cid]
            if e.get("supera_oms") and e["fecha"].startswith(str(datetime.now().year))
        )
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)
    return resultados
def generar_json():
    print(f"\n{'='*60}")
    print(f"Calidad del aire — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"Fuente: Open-Meteo Air Quality API (sin API key)")
    print(f"{'='*60}\n")

    # UNA petición (o pocas) para todas las ciudades: adiós al rate limiting.
    print(f"Consultando {len(CIUDADES)} ciudades en lote...")
    valores_todos = obtener_calidad_todas(CIUDADES)

    # Salvaguarda: si NINGUNA ciudad trajo dato, abortamos SIN escribir para
    # conservar el docs/calidad_aire.json bueno anterior.
    con_dato = sum(1 for v in valores_todos if v.get("pm25") is not None or v.get("aqi_europeo") is not None)
    if con_dato == 0:
        print("ERROR: la API no devolvió datos para ninguna ciudad. Se conserva el JSON anterior.")
        sys.exit(1)

    resultados = []
    errores    = 0
    for ciudad, valores in zip(CIUDADES, valores_todos):
        pm25 = valores.get("pm25")
        pm10 = valores.get("pm10")
        no2  = valores.get("no2")
        o3   = valores.get("o3")
        so2  = valores.get("so2")
        aqi  = valores.get("aqi_europeo")
        dust = valores.get("dust")
        if pm25 is None and aqi is None:
            errores += 1
        color, etiqueta, nivel, valor_mostrado, unidad_mostrada = clasificar_ciudad(pm25, aqi)
        sahariano    = detectar_sahariano(pm10, dust)
        supera_oms   = supera_limite_oms(valores)
        contaminante = contaminante_dominante(valores)
        etiq_aqi     = clasificar_aqi_europeo(aqi)[1] if aqi is not None else "Sin datos"
        estado = f"PM2.5:{pm25} AQI:{aqi} → {etiqueta}"
        if sahariano:
            estado += " 🏜️"
        print(f"  {ciudad['nombre']}: {estado}")
        resultados.append({
            "id":              ciudad["id"],
            "nombre":          ciudad["nombre"],
            "provincia":       ciudad["provincia"],
            "lat":             ciudad["lat"],
            "lon":             ciudad["lon"],
            "pm25":            pm25,
            "pm10":            pm10,
            "no2":             no2,
            "o3":              o3,
            "so2":             so2,
            "aqi_europeo":     aqi,
            "etiqueta_aqi":    etiq_aqi,
            "dust":            dust,
            "color":           color,
            "etiqueta":        etiqueta,
            "nivel":           nivel,
            "valor_mostrado":  valor_mostrado,
            "unidad_mostrada": unidad_mostrada,
            "supera_oms":      supera_oms,
            "sahariano":       sahariano,
            "contaminante_dominante":  contaminante,
            "dias_consecutivos_estado": 0,
            "max_dias_sobre_oms":       0,
            "dias_sobre_oms_anio":      0,
        })
    resultados = actualizar_historial(resultados)
    ciudades_ok    = sum(1 for r in resultados if r["nivel"] in [1, 2])
    ciudades_malas = sum(1 for r in resultados if r["nivel"] >= 4)
    saharianos     = sum(1 for r in resultados if r["sahariano"])
    os.makedirs("docs", exist_ok=True)
    output = {
        "ultima_actualizacion":   datetime.now().isoformat(),
        "fecha_legible":          datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "total_ciudades":         len(CIUDADES),
        "ciudades_con_datos":     len(CIUDADES) - errores,
        "ciudades_buena_calidad": ciudades_ok,
        "ciudades_mala_calidad":  ciudades_malas,
        "episodio_sahariano":     saharianos > 3,
        "ciudades_saharianas":    saharianos,
        "fuente":                 "Open-Meteo Air Quality API — CAMS Copernicus",
        "nota_oms":               "Límites OMS 2021: PM2.5<15, PM10<45, NO2<25, O3<100 µg/m³",
        "ciudades":               resultados,
    }
    with open("docs/calidad_aire.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ {len(CIUDADES) - errores}/{len(CIUDADES)} ciudades con datos")
    print(f"✓ {ciudades_ok} ciudades buena calidad")
    print(f"✓ {ciudades_malas} ciudades mala calidad")
    if saharianos:
        print(f"⚠️  {saharianos} ciudades con episodio sahariano\n")
if __name__ == "__main__":
    generar_json()
