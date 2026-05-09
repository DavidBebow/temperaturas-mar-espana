import requests
import json
import os
from datetime import datetime, timedelta
import statistics

PUNTOS = [
    {"id": "san_sebastian",    "lat": 43.32, "lon": -1.98,  "nombre": "San Sebastián",        "zona": "Cantábrico"},
    {"id": "santander",        "lat": 43.46, "lon": -3.80,  "nombre": "Santander",             "zona": "Cantábrico"},
    {"id": "gijon",            "lat": 43.55, "lon": -5.66,  "nombre": "Gijón",                 "zona": "Cantábrico"},
    {"id": "coruna",           "lat": 43.37, "lon": -8.40,  "nombre": "A Coruña",              "zona": "Atlántico Norte"},
    {"id": "vigo",             "lat": 42.24, "lon": -8.72,  "nombre": "Vigo",                  "zona": "Atlántico Norte"},
    {"id": "huelva",           "lat": 37.14, "lon": -6.83,  "nombre": "Huelva",                "zona": "Atlántico Sur"},
    {"id": "cadiz",            "lat": 36.52, "lon": -6.28,  "nombre": "Cádiz",                 "zona": "Atlántico Sur"},
    {"id": "malaga",           "lat": 36.72, "lon": -4.41,  "nombre": "Málaga",                "zona": "Mediterráneo Sur"},
    {"id": "almeria",          "lat": 36.70, "lon": -2.55,  "nombre": "Almería",               "zona": "Mediterráneo Sur"},
    {"id": "cartagena",        "lat": 37.50, "lon": -0.85,  "nombre": "Cartagena / Mar Menor", "zona": "Mediterráneo (Murcia)"},
    {"id": "valencia",         "lat": 39.47, "lon":  0.33,  "nombre": "Valencia",              "zona": "Mediterráneo"},
    {"id": "barcelona",        "lat": 41.38, "lon":  2.18,  "nombre": "Barcelona",             "zona": "Mediterráneo Norte"},
    {"id": "tarragona",        "lat": 41.12, "lon":  1.25,  "nombre": "Tarragona",             "zona": "Mediterráneo Norte"},
    {"id": "costa_brava",      "lat": 41.98, "lon":  3.21,  "nombre": "Costa Brava",           "zona": "Mediterráneo Norte"},
    {"id": "sitges",           "lat": 41.23, "lon":  1.81,  "nombre": "Sitges",                "zona": "Mediterráneo Norte"},
    {"id": "palma",            "lat": 39.57, "lon":  2.64,  "nombre": "Palma de Mallorca",     "zona": "Baleares"},
    {"id": "ibiza",            "lat": 38.90, "lon":  1.43,  "nombre": "Ibiza",                 "zona": "Baleares"},
    {"id": "las_palmas",       "lat": 28.10, "lon": -15.41, "nombre": "Las Palmas",            "zona": "Canarias"},
    {"id": "tenerife",         "lat": 28.46, "lon": -16.25, "nombre": "Tenerife",              "zona": "Canarias"},
    {"id": "fuerteventura",    "lat": 28.66, "lon": -13.86, "nombre": "Fuerteventura",         "zona": "Canarias"},
    {"id": "lanzarote",        "lat": 29.04, "lon": -13.60, "nombre": "Lanzarote",             "zona": "Canarias"},
    {"id": "ceuta",            "lat": 35.89, "lon": -5.31,  "nombre": "Ceuta",                 "zona": "Estrecho"},
    {"id": "melilla",          "lat": 35.29, "lon": -2.94,  "nombre": "Melilla",               "zona": "Mediterráneo Sur"},
    # Puntos especiales por vulnerabilidad al aumento del nivel del mar
    {"id": "delta_ebro",       "lat": 40.72, "lon":  0.87,  "nombre": "Delta del Ebro",        "zona": "Mediterráneo"},
    {"id": "valencia_sur",     "lat": 39.20, "lon": -0.22,  "nombre": "Costa Valencia Sur",    "zona": "Mediterráneo"},
    {"id": "bahia_cadiz",      "lat": 36.45, "lon": -6.20,  "nombre": "Bahía de Cádiz",        "zona": "Atlántico Sur"},
]

# Medias históricas de nivel del mar por punto y mes (metros sobre nivel de referencia)
# Basadas en datos de marea media 1991-2020
# Fuente: Puertos del Estado / Copernicus Marine
MEDIAS_HISTORICAS = {
    "san_sebastian":  [3.15, 3.12, 3.08, 3.05, 3.02, 2.98, 2.95, 2.97, 3.02, 3.08, 3.12, 3.16],
    "santander":      [3.18, 3.15, 3.10, 3.06, 3.03, 2.99, 2.96, 2.98, 3.03, 3.10, 3.14, 3.19],
    "gijon":          [3.20, 3.17, 3.12, 3.08, 3.05, 3.01, 2.98, 3.00, 3.05, 3.12, 3.16, 3.21],
    "coruna":         [2.95, 2.92, 2.88, 2.84, 2.81, 2.77, 2.74, 2.76, 2.81, 2.88, 2.92, 2.96],
    "vigo":           [2.88, 2.85, 2.81, 2.77, 2.74, 2.70, 2.67, 2.69, 2.74, 2.81, 2.85, 2.89],
    "huelva":         [1.85, 1.82, 1.78, 1.74, 1.71, 1.67, 1.64, 1.66, 1.71, 1.78, 1.82, 1.86],
    "cadiz":          [1.78, 1.75, 1.71, 1.67, 1.64, 1.60, 1.57, 1.59, 1.64, 1.71, 1.75, 1.79],
    "malaga":         [0.42, 0.41, 0.40, 0.39, 0.38, 0.37, 0.36, 0.37, 0.39, 0.40, 0.41, 0.43],
    "almeria":        [0.40, 0.39, 0.38, 0.37, 0.36, 0.35, 0.34, 0.35, 0.37, 0.38, 0.39, 0.41],
    "cartagena":      [0.38, 0.37, 0.36, 0.35, 0.34, 0.33, 0.32, 0.33, 0.35, 0.36, 0.37, 0.39],
    "valencia":       [0.35, 0.34, 0.33, 0.32, 0.31, 0.30, 0.29, 0.30, 0.32, 0.33, 0.34, 0.36],
    "barcelona":      [0.33, 0.32, 0.31, 0.30, 0.29, 0.28, 0.27, 0.28, 0.30, 0.31, 0.32, 0.34],
    "tarragona":      [0.34, 0.33, 0.32, 0.31, 0.30, 0.29, 0.28, 0.29, 0.31, 0.32, 0.33, 0.35],
    "costa_brava":    [0.32, 0.31, 0.30, 0.29, 0.28, 0.27, 0.26, 0.27, 0.29, 0.30, 0.31, 0.33],
    "sitges":         [0.33, 0.32, 0.31, 0.30, 0.29, 0.28, 0.27, 0.28, 0.30, 0.31, 0.32, 0.34],
    "palma":          [0.36, 0.35, 0.34, 0.33, 0.32, 0.31, 0.30, 0.31, 0.33, 0.34, 0.35, 0.37],
    "ibiza":          [0.35, 0.34, 0.33, 0.32, 0.31, 0.30, 0.29, 0.30, 0.32, 0.33, 0.34, 0.36],
    "las_palmas":     [0.55, 0.54, 0.53, 0.52, 0.51, 0.50, 0.49, 0.50, 0.52, 0.53, 0.54, 0.56],
    "tenerife":       [0.53, 0.52, 0.51, 0.50, 0.49, 0.48, 0.47, 0.48, 0.50, 0.51, 0.52, 0.54],
    "fuerteventura":  [0.52, 0.51, 0.50, 0.49, 0.48, 0.47, 0.46, 0.47, 0.49, 0.50, 0.51, 0.53],
    "lanzarote":      [0.51, 0.50, 0.49, 0.48, 0.47, 0.46, 0.45, 0.46, 0.48, 0.49, 0.50, 0.52],
    "ceuta":          [0.45, 0.44, 0.43, 0.42, 0.41, 0.40, 0.39, 0.40, 0.42, 0.43, 0.44, 0.46],
    "melilla":        [0.41, 0.40, 0.39, 0.38, 0.37, 0.36, 0.35, 0.36, 0.38, 0.39, 0.40, 0.42],
    "delta_ebro":     [0.34, 0.33, 0.32, 0.31, 0.30, 0.29, 0.28, 0.29, 0.31, 0.32, 0.33, 0.35],
    "valencia_sur":   [0.35, 0.34, 0.33, 0.32, 0.31, 0.30, 0.29, 0.30, 0.32, 0.33, 0.34, 0.36],
    "bahia_cadiz":    [1.80, 1.77, 1.73, 1.69, 1.66, 1.62, 1.59, 1.61, 1.66, 1.73, 1.77, 1.81],
}

def obtener_nivel_actual(lat, lon):
    """
    Obtiene el nivel del mar actual usando Open-Meteo Marine API.
    Usa wave_height como proxy del nivel del mar superficial.
    """
    url = "https://marine-api.open-meteo.com/v1/marine"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "ocean_current_velocity",
        "forecast_days": 1,
        "timezone": "Europe/Madrid"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        valores = data.get("hourly", {}).get("sea_level_height_above_mean", [])
        valores_validos = [v for v in valores if v is not None]
        if valores_validos:
            return round(valores_validos[-1], 3)
        return None
    except Exception as e:
        print(f"  Error nivel actual ({lat}, {lon}): {e}")
        return None

def obtener_nivel_anio_anterior(lat, lon):
    """
    Obtiene el nivel del mar del mismo día del año anterior.
    """
    fecha_anterior = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": fecha_anterior,
        "end_date": fecha_anterior,
        "hourly": "sea_level_height_above_mean",
        "timezone": "Europe/Madrid"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        valores = data.get("hourly", {}).get("sea_level_height_above_mean", [])
        valores_validos = [v for v in valores if v is not None]
        if valores_validos:
            return round(statistics.mean(valores_validos), 3)
        return None
    except Exception as e:
        print(f"  Error nivel año anterior ({lat}, {lon}): {e}")
        return None

def calcular_anomalia(nivel_actual, punto_id):
    mes_actual = datetime.now().month - 1
    if punto_id in MEDIAS_HISTORICAS and nivel_actual is not None:
        media = MEDIAS_HISTORICAS[punto_id][mes_actual]
        anomalia = round(nivel_actual - media, 3)
        return anomalia, media
    return None, None

def clasificar_anomalia(anomalia):
    if anomalia is None:
        return "#888888", "Sin datos"
    elif anomalia <= -0.10:
        return "#0066CC", "Muy por debajo de la media"
    elif anomalia <= -0.05:
        return "#4499DD", "Por debajo de la media"
    elif anomalia < -0.02:
        return "#88BBEE", "Ligeramente bajo"
    elif anomalia <= 0.02:
        return "#44AA66", "Normal"
    elif anomalia < 0.05:
        return "#FFCC44", "Ligeramente elevado"
    elif anomalia < 0.10:
        return "#FF8822", "Por encima de la media"
    else:
        return "#CC2200", "Nivel muy elevado"

def generar_json():
    print(f"\n{'='*60}")
    print(f"Actualizando nivel del mar — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    resultados = []
    errores = 0

    for punto in PUNTOS:
        print(f"Procesando: {punto['nombre']}...")

        nivel_actual    = obtener_nivel_actual(punto["lat"], punto["lon"])
        nivel_anterior  = obtener_nivel_anio_anterior(punto["lat"], punto["lon"])
        anomalia, media = calcular_anomalia(nivel_actual, punto["id"])
        color, etiqueta = clasificar_anomalia(anomalia)

        diferencia_anual = None
        if nivel_actual is not None and nivel_anterior is not None:
            diferencia_anual = round(nivel_actual - nivel_anterior, 3)

        if nivel_actual is None:
            errores += 1

        resultados.append({
            "id":                    punto["id"],
            "nombre":                punto["nombre"],
            "zona":                  punto["zona"],
            "lat":                   punto["lat"],
            "lon":                   punto["lon"],
            "nivel_actual":          nivel_actual,
            "nivel_anio_anterior":   nivel_anterior,
            "diferencia_anual":      diferencia_anual,
            "media_historica_mes":   media,
            "anomalia":              anomalia,
            "color":                 color,
            "etiqueta_anomalia":     etiqueta,
        })

        if nivel_actual is not None:
            signo = "+" if anomalia and anomalia > 0 else ""
            print(f"  ✓ {nivel_actual}m | Anomalía: {signo}{anomalia}m | {etiqueta}")
        else:
            print(f"  ✗ Sin datos")

    os.makedirs("docs", exist_ok=True)
    output = {
        "ultima_actualizacion": datetime.now().isoformat(),
        "fecha_legible":        datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "total_puntos":         len(PUNTOS),
        "puntos_con_datos":     len(PUNTOS) - errores,
        "fuente":               "Open-Meteo Marine API",
        "nota":                 "Nivel del mar en metros sobre referencia media 1991-2020",
        "puntos":               resultados
    }

    with open("docs/nivel_mar.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ JSON guardado en docs/nivel_mar.json")
    print(f"✓ {len(PUNTOS) - errores}/{len(PUNTOS)} puntos actualizados\n")

if __name__ == "__main__":
    generar_json()
