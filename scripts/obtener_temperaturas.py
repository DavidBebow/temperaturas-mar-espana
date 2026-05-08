import requests
import json
import os
from datetime import datetime, timedelta
import statistics

# ============================================================
# PUNTOS DE MEDICIÓN EN LAS COSTAS ESPAÑOLAS
# Coordenadas: [latitud, longitud, nombre, zona]
# ============================================================
PUNTOS = [
    {"id": "san_sebastian",    "lat": 43.32, "lon": -1.98,  "nombre": "San Sebastián",     "zona": "Cantábrico"},
    {"id": "santander",        "lat": 43.46, "lon": -3.80,  "nombre": "Santander",          "zona": "Cantábrico"},
    {"id": "gijon",            "lat": 43.55, "lon": -5.66,  "nombre": "Gijón",              "zona": "Cantábrico"},
    {"id": "coruna",           "lat": 43.37, "lon": -8.40,  "nombre": "A Coruña",           "zona": "Atlántico Norte"},
    {"id": "vigo",             "lat": 42.24, "lon": -8.72,  "nombre": "Vigo",               "zona": "Atlántico Norte"},
    {"id": "huelva",           "lat": 37.14, "lon": -6.83,  "nombre": "Huelva",             "zona": "Atlántico Sur"},
    {"id": "cadiz",            "lat": 36.52, "lon": -6.28,  "nombre": "Cádiz",              "zona": "Atlántico Sur"},
    {"id": "malaga",           "lat": 36.72, "lon": -4.41,  "nombre": "Málaga",             "zona": "Mediterráneo Sur"},
    {"id": "almeria",          "lat": 36.83, "lon": -2.46,  "nombre": "Almería",            "zona": "Mediterráneo Sur"},
    {"id": "cartagena",        "lat": 37.60, "lon": -0.98,  "nombre": "Cartagena",          "zona": "Mediterráneo"},
    {"id": "valencia",         "lat": 39.47, "lon":  0.33,  "nombre": "Valencia",           "zona": "Mediterráneo"},
    {"id": "barcelona",        "lat": 41.38, "lon":  2.18,  "nombre": "Barcelona",          "zona": "Mediterráneo Norte"},
    {"id": "palma",            "lat": 39.57, "lon":  2.64,  "nombre": "Palma de Mallorca",  "zona": "Baleares"},
    {"id": "ibiza",            "lat": 38.90, "lon":  1.43,  "nombre": "Ibiza",              "zona": "Baleares"},
    {"id": "las_palmas",       "lat": 28.10, "lon": -15.41, "nombre": "Las Palmas",         "zona": "Canarias"},
    {"id": "tenerife",         "lat": 28.46, "lon": -16.25, "nombre": "Tenerife",           "zona": "Canarias"},
    {"id": "fuerteventura",    "lat": 28.66, "lon": -13.86, "nombre": "Fuerteventura",      "zona": "Canarias"},
    {"id": "lanzarote",        "lat": 29.04, "lon": -13.60, "nombre": "Lanzarote",          "zona": "Canarias"},
    {"id": "ceuta",            "lat": 35.89, "lon": -5.31,  "nombre": "Ceuta",              "zona": "Estrecho"},
    {"id": "melilla",          "lat": 35.29, "lon": -2.94,  "nombre": "Melilla",            "zona": "Mediterráneo Sur"},
    {"id": "tarragona",        "lat": 41.12, "lon":  1.25,  "nombre": "Tarragona",          "zona": "Mediterráneo Norte"},
    {"id": "costa_brava",      "lat": 41.98, "lon":  3.21,  "nombre": "Costa Brava",         "zona": "Mediterráneo Norte"},
    {"id": "sitges",           "lat": 41.23, "lon":  1.81,  "nombre": "Sitges",              "zona": "Mediterráneo Norte"},
]

# ============================================================
# MEDIAS HISTÓRICAS POR PUNTO Y MES (°C)
# Basadas en datos climatológicos 1981-2010
# Fuente: AEMET / Copernicus Marine
# ============================================================
MEDIAS_HISTORICAS = {
    "san_sebastian":  [12.5, 12.0, 12.5, 13.5, 15.5, 17.5, 19.5, 21.0, 20.0, 17.5, 14.5, 13.0],
    "santander":      [13.0, 12.5, 13.0, 14.0, 16.0, 18.0, 20.0, 21.5, 20.5, 18.0, 15.0, 13.5],
    "gijon":          [13.5, 13.0, 13.5, 14.5, 16.5, 18.5, 20.5, 22.0, 21.0, 18.5, 15.5, 14.0],
    "coruna":         [14.0, 13.5, 14.0, 14.5, 16.0, 17.5, 19.0, 20.5, 20.0, 18.0, 16.0, 14.5],
    "vigo":           [14.5, 14.0, 14.5, 15.0, 16.5, 18.0, 19.5, 21.0, 20.5, 18.5, 16.5, 15.0],
    "huelva":         [17.0, 17.0, 18.0, 19.0, 20.5, 22.0, 23.5, 24.5, 24.0, 22.0, 19.5, 17.5],
    "cadiz":          [17.5, 17.5, 18.5, 19.5, 21.0, 22.5, 24.0, 25.0, 24.5, 22.5, 20.0, 18.0],
    "malaga":         [16.5, 16.5, 17.5, 18.5, 20.5, 23.0, 25.5, 26.5, 25.5, 23.0, 20.0, 17.5],
    "almeria":        [16.0, 16.0, 17.0, 18.0, 20.0, 23.0, 26.0, 27.0, 26.0, 23.0, 19.5, 17.0],
    "cartagena":      [15.5, 15.5, 16.5, 17.5, 20.0, 23.5, 26.5, 27.5, 26.5, 23.5, 19.5, 16.5],
    "valencia":       [14.5, 14.5, 15.5, 17.0, 19.5, 23.0, 26.0, 27.0, 26.0, 22.5, 18.5, 15.5],
    "barcelona":      [13.5, 13.5, 14.5, 16.0, 18.5, 22.5, 25.5, 26.5, 25.0, 21.5, 17.5, 14.5],
    "palma":          [14.5, 14.0, 15.0, 16.5, 19.5, 23.0, 26.0, 27.0, 25.5, 22.0, 18.0, 15.5],
    "ibiza":          [15.0, 14.5, 15.5, 17.0, 20.0, 23.5, 26.5, 27.5, 26.0, 22.5, 18.5, 16.0],
    "las_palmas":     [20.5, 20.0, 20.5, 21.0, 22.0, 23.5, 24.5, 25.5, 25.0, 24.0, 22.5, 21.0],
    "tenerife":       [20.0, 19.5, 20.0, 20.5, 21.5, 23.0, 24.0, 25.0, 24.5, 23.5, 22.0, 20.5],
    "fuerteventura":  [20.0, 19.5, 20.0, 20.5, 21.5, 23.0, 24.0, 25.0, 24.5, 23.5, 22.0, 20.5],
    "lanzarote":      [19.5, 19.0, 19.5, 20.0, 21.0, 22.5, 23.5, 24.5, 24.0, 23.0, 21.5, 20.0],
    "ceuta":          [17.0, 17.0, 17.5, 18.5, 20.5, 22.5, 24.5, 25.5, 25.0, 22.5, 19.5, 17.5],
    "melilla":        [16.5, 16.5, 17.0, 18.0, 20.0, 23.0, 25.5, 26.5, 25.5, 22.5, 19.5, 17.0],
}

def obtener_temperatura_actual(lat, lon):
    """
    Obtiene la temperatura actual del mar usando Open-Meteo Marine API.
    API completamente gratuita, sin necesidad de registro.
    """
    url = "https://marine-api.open-meteo.com/v1/marine"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "sea_surface_temperature",
        "forecast_days": 1,
        "timezone": "Europe/Madrid"
    }
    
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        temps = data.get("hourly", {}).get("sea_surface_temperature", [])
        # Filtrar valores None y tomar la media de las últimas 6 horas disponibles
        temps_validas = [t for t in temps if t is not None]
        
        if temps_validas:
            return round(temps_validas[-1], 1)  # última lectura disponible
        return None
    except Exception as e:
        print(f"  Error obteniendo datos para ({lat}, {lon}): {e}")
        return None

def obtener_temperatura_anio_anterior(lat, lon):
    """
    Obtiene la temperatura del mismo día del año anterior.
    """
    fecha_anterior = datetime.now() - timedelta(days=365)
    fecha_str = fecha_anterior.strftime("%Y-%m-%d")
    
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": fecha_str,
        "end_date": fecha_str,
        "hourly": "sea_surface_temperature",
        "timezone": "Europe/Madrid"
    }
    
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        temps = data.get("hourly", {}).get("sea_surface_temperature", [])
        temps_validas = [t for t in temps if t is not None]
        
        if temps_validas:
            return round(statistics.mean(temps_validas), 1)
        return None
    except Exception as e:
        print(f"  Error datos año anterior para ({lat}, {lon}): {e}")
        return None

def calcular_anomalia(temp_actual, lat, lon, punto_id):
    """
    Calcula la anomalía respecto a la media histórica del mes actual.
    La anomalía indica cuántos grados está por encima o debajo de la media histórica.
    """
    mes_actual = datetime.now().month - 1  # índice 0-11
    
    if punto_id in MEDIAS_HISTORICAS:
        media = MEDIAS_HISTORICAS[punto_id][mes_actual]
        anomalia = round(temp_actual - media, 1)
        return anomalia, media
    
    return None, None

def clasificar_anomalia(anomalia):
    """
    Clasifica la anomalía para determinar el color del marcador en el mapa.
    Retorna un código de color y una etiqueta descriptiva.
    """
    if anomalia is None:
        return "#888888", "Sin datos"
    elif anomalia <= -2.0:
        return "#0066CC", "Muy por debajo de la media"
    elif anomalia <= -1.0:
        return "#4499DD", "Por debajo de la media"
    elif anomalia < -0.3:
        return "#88BBEE", "Ligeramente frío"
    elif anomalia <= 0.3:
        return "#44AA66", "Normal"
    elif anomalia < 1.0:
        return "#FFCC44", "Ligeramente cálido"
    elif anomalia < 2.0:
        return "#FF8822", "Por encima de la media"
    else:
        return "#CC2200", "Muy por encima de la media"

def generar_json():
    """
    Función principal: recorre todos los puntos, obtiene datos y genera el JSON.
    """
    print(f"\n{'='*60}")
    print(f"Actualizando temperaturas del mar - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")
    
    resultados = []
    errores = 0
    
    for punto in PUNTOS:
        print(f"Procesando: {punto['nombre']}...")
        
        # Temperatura actual
        temp_actual = obtener_temperatura_actual(punto["lat"], punto["lon"])
        
        # Temperatura año anterior
        temp_anterior = obtener_temperatura_anio_anterior(punto["lat"], punto["lon"])
        
        # Anomalía
        if temp_actual is not None:
            anomalia, media_historica = calcular_anomalia(
                temp_actual, punto["lat"], punto["lon"], punto["id"]
            )
            color, etiqueta = clasificar_anomalia(anomalia)
        else:
            anomalia = None
            media_historica = None
            color = "#888888"
            etiqueta = "Sin datos"
            errores += 1
        
        # Diferencia con año anterior
        diferencia_anual = None
        if temp_actual is not None and temp_anterior is not None:
            diferencia_anual = round(temp_actual - temp_anterior, 1)
        
        resultado = {
            "id": punto["id"],
            "nombre": punto["nombre"],
            "zona": punto["zona"],
            "lat": punto["lat"],
            "lon": punto["lon"],
            "temperatura_actual": temp_actual,
            "temperatura_anio_anterior": temp_anterior,
            "diferencia_anual": diferencia_anual,
            "media_historica_mes": media_historica,
            "anomalia": anomalia,
            "color": color,
            "etiqueta_anomalia": etiqueta,
        }
        
        resultados.append(resultado)
        
        if temp_actual is not None:
            print(f"  ✓ {temp_actual}°C | Anomalía: {'+' if anomalia and anomalia > 0 else ''}{anomalia}°C | {etiqueta}")
        else:
            print(f"  ✗ Sin datos")
    
    # Metadatos del archivo
    output = {
        "ultima_actualizacion": datetime.now().isoformat(),
        "fecha_legible": datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "total_puntos": len(PUNTOS),
        "puntos_con_datos": len(PUNTOS) - errores,
        "fuente": "Open-Meteo Marine API",
        "puntos": resultados
    }
    
    # Guardar JSON
    os.makedirs("docs", exist_ok=True)
    ruta = "docs/datos.json"
    
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"✓ JSON guardado en {ruta}")
    print(f"✓ {len(PUNTOS) - errores}/{len(PUNTOS)} puntos actualizados correctamente")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    generar_json()
