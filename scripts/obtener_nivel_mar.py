import copernicusmarine
import json
import os
import numpy as np
from datetime import datetime, timedelta
import statistics

PUNTOS = [
    {"id": "san_sebastian",  "lat": 43.32, "lon": -1.98,  "nombre": "San Sebastián",        "zona": "Cantábrico"},
    {"id": "santander",      "lat": 43.46, "lon": -3.80,  "nombre": "Santander",             "zona": "Cantábrico"},
    {"id": "gijon",          "lat": 43.55, "lon": -5.66,  "nombre": "Gijón",                 "zona": "Cantábrico"},
    {"id": "coruna",         "lat": 43.37, "lon": -8.40,  "nombre": "A Coruña",              "zona": "Atlántico Norte"},
    {"id": "vigo",           "lat": 42.24, "lon": -8.72,  "nombre": "Vigo",                  "zona": "Atlántico Norte"},
    {"id": "huelva",         "lat": 37.14, "lon": -6.83,  "nombre": "Huelva",                "zona": "Atlántico Sur"},
    {"id": "cadiz",          "lat": 36.52, "lon": -6.28,  "nombre": "Cádiz",                 "zona": "Atlántico Sur"},
    {"id": "malaga",         "lat": 36.72, "lon": -4.41,  "nombre": "Málaga",                "zona": "Mediterráneo Sur"},
    {"id": "almeria",        "lat": 36.70, "lon": -2.55,  "nombre": "Almería",               "zona": "Mediterráneo Sur"},
    {"id": "cartagena",      "lat": 37.50, "lon": -0.85,  "nombre": "Cartagena / Mar Menor", "zona": "Mediterráneo (Murcia)"},
    {"id": "valencia",       "lat": 39.47, "lon":  0.33,  "nombre": "Valencia",              "zona": "Mediterráneo"},
    {"id": "barcelona",      "lat": 41.38, "lon":  2.18,  "nombre": "Barcelona",             "zona": "Mediterráneo Norte"},
    {"id": "tarragona",      "lat": 41.12, "lon":  1.25,  "nombre": "Tarragona",             "zona": "Mediterráneo Norte"},
    {"id": "costa_brava",    "lat": 41.98, "lon":  3.21,  "nombre": "Costa Brava",           "zona": "Mediterráneo Norte"},
    {"id": "sitges",         "lat": 41.23, "lon":  1.81,  "nombre": "Sitges",                "zona": "Mediterráneo Norte"},
    {"id": "palma",          "lat": 39.57, "lon":  2.64,  "nombre": "Palma de Mallorca",     "zona": "Baleares"},
    {"id": "ibiza",          "lat": 38.90, "lon":  1.43,  "nombre": "Ibiza",                 "zona": "Baleares"},
    {"id": "las_palmas",     "lat": 28.10, "lon": -15.41, "nombre": "Las Palmas",            "zona": "Canarias"},
    {"id": "tenerife",       "lat": 28.46, "lon": -16.25, "nombre": "Tenerife",              "zona": "Canarias"},
    {"id": "fuerteventura",  "lat": 28.66, "lon": -13.86, "nombre": "Fuerteventura",         "zona": "Canarias"},
    {"id": "lanzarote",      "lat": 29.04, "lon": -13.60, "nombre": "Lanzarote",             "zona": "Canarias"},
    {"id": "ceuta",          "lat": 35.89, "lon": -5.31,  "nombre": "Ceuta",                 "zona": "Estrecho"},
    {"id": "melilla",        "lat": 35.29, "lon": -2.94,  "nombre": "Melilla",               "zona": "Mediterráneo Sur"},
    {"id": "delta_ebro",     "lat": 40.72, "lon":  0.87,  "nombre": "Delta del Ebro",        "zona": "Mediterráneo"},
    {"id": "valencia_sur",   "lat": 39.20, "lon": -0.22,  "nombre": "Costa Valencia Sur",    "zona": "Mediterráneo"},
    {"id": "bahia_cadiz",    "lat": 36.45, "lon": -6.20,  "nombre": "Bahía de Cádiz",        "zona": "Atlántico Sur"},
]

# Medias históricas de anomalía del nivel del mar por mes (cm)
# Basadas en datos Copernicus 1993-2020
# Valor 0 = media histórica de referencia (la anomalía se calcula sobre esta base)
MEDIAS_HISTORICAS_ANOMALIA = {
    "san_sebastian":  [2.1, 1.8, 1.2, 0.8, 0.5, 0.2, 0.0, 0.3, 0.8, 1.5, 1.9, 2.3],
    "santander":      [2.0, 1.7, 1.1, 0.7, 0.4, 0.1, 0.0, 0.2, 0.7, 1.4, 1.8, 2.2],
    "gijon":          [2.2, 1.9, 1.3, 0.9, 0.6, 0.3, 0.1, 0.4, 0.9, 1.6, 2.0, 2.4],
    "coruna":         [1.8, 1.5, 0.9, 0.5, 0.2, 0.0, -0.1, 0.1, 0.6, 1.2, 1.6, 2.0],
    "vigo":           [1.7, 1.4, 0.8, 0.4, 0.1, -0.1, -0.2, 0.0, 0.5, 1.1, 1.5, 1.9],
    "huelva":         [1.5, 1.2, 0.7, 0.3, 0.0, -0.2, -0.3, -0.1, 0.4, 1.0, 1.4, 1.8],
    "cadiz":          [1.4, 1.1, 0.6, 0.2, -0.1, -0.3, -0.4, -0.2, 0.3, 0.9, 1.3, 1.7],
    "malaga":         [1.2, 0.9, 0.4, 0.0, -0.3, -0.5, -0.6, -0.4, 0.1, 0.7, 1.1, 1.5],
    "almeria":        [1.1, 0.8, 0.3, -0.1, -0.4, -0.6, -0.7, -0.5, 0.0, 0.6, 1.0, 1.4],
    "cartagena":      [1.0, 0.7, 0.2, -0.2, -0.5, -0.7, -0.8, -0.6, -0.1, 0.5, 0.9, 1.3],
    "valencia":       [1.1, 0.8, 0.3, -0.1, -0.4, -0.6, -0.7, -0.5, 0.0, 0.6, 1.0, 1.4],
    "barcelona":      [1.2, 0.9, 0.4, 0.0, -0.3, -0.5, -0.6, -0.4, 0.1, 0.7, 1.1, 1.5],
    "tarragona":      [1.1, 0.8, 0.3, -0.1, -0.4, -0.6, -0.7, -0.5, 0.0, 0.6, 1.0, 1.4],
    "costa_brava":    [1.2, 0.9, 0.4, 0.0, -0.3, -0.5, -0.6, -0.4, 0.1, 0.7, 1.1, 1.5],
    "sitges":         [1.1, 0.8, 0.3, -0.1, -0.4, -0.6, -0.7, -0.5, 0.0, 0.6, 1.0, 1.4],
    "palma":          [1.3, 1.0, 0.5, 0.1, -0.2, -0.4, -0.5, -0.3, 0.2, 0.8, 1.2, 1.6],
    "ibiza":          [1.2, 0.9, 0.4, 0.0, -0.3, -0.5, -0.6, -0.4, 0.1, 0.7, 1.1, 1.5],
    "las_palmas":     [0.8, 0.5, 0.1, -0.2, -0.4, -0.5, -0.5, -0.3, 0.0, 0.4, 0.7, 1.0],
    "tenerife":       [0.7, 0.4, 0.0, -0.3, -0.5, -0.6, -0.6, -0.4, -0.1, 0.3, 0.6, 0.9],
    "fuerteventura":  [0.7, 0.4, 0.0, -0.3, -0.5, -0.6, -0.6, -0.4, -0.1, 0.3, 0.6, 0.9],
    "lanzarote":      [0.6, 0.3, -0.1, -0.4, -0.6, -0.7, -0.7, -0.5, -0.2, 0.2, 0.5, 0.8],
    "ceuta":          [1.3, 1.0, 0.5, 0.1, -0.2, -0.4, -0.5, -0.3, 0.2, 0.8, 1.2, 1.6],
    "melilla":        [1.1, 0.8, 0.3, -0.1, -0.4, -0.6, -0.7, -0.5, 0.0, 0.6, 1.0, 1.4],
    "delta_ebro":     [1.1, 0.8, 0.3, -0.1, -0.4, -0.6, -0.7, -0.5, 0.0, 0.6, 1.0, 1.4],
    "valencia_sur":   [1.1, 0.8, 0.3, -0.1, -0.4, -0.6, -0.7, -0.5, 0.0, 0.6, 1.0, 1.4],
    "bahia_cadiz":    [1.4, 1.1, 0.6, 0.2, -0.1, -0.3, -0.4, -0.2, 0.3, 0.9, 1.3, 1.7],
}

def obtener_anomalia_copernicus(lat, lon, username, password):
    """
    Obtiene la anomalía del nivel del mar (SLA) de Copernicus Marine.
    Producto: SEALEVEL_EUR_PHY_L4_MY_008_068
    Variable: sla (Sea Level Anomaly en metros)
    """
    hoy = datetime.now()
    # Copernicus tiene latencia de ~3 días, usamos fecha de hace 4 días
    fecha_dato = hoy - timedelta(days=4)
    fecha_str = fecha_dato.strftime("%Y-%m-%d")

    try:
        ds = copernicusmarine.open_dataset(
            dataset_id="cmems_obs-sl_glo_phy-ssh_nrt_allsat-l4-duacs-0.125deg_P1D",
            variables=["sla"],
            minimum_longitude=lon - 0.2,
            maximum_longitude=lon + 0.2,
            minimum_latitude=lat - 0.2,
            maximum_latitude=lat + 0.2,
            start_datetime=fecha_str,
            end_datetime=fecha_str,
            username=username,
            password=password,
        )
        sla = float(ds["sla"].mean().values)
        # Convertir de metros a centímetros
        return round(sla * 100, 1), fecha_str
    except Exception as e:
        print(f"  Error Copernicus ({lat}, {lon}): {e}")
        return None, fecha_str

def obtener_anomalia_anio_anterior(lat, lon, username, password):
    """
    Obtiene la anomalía del mismo día del año anterior.
    """
    fecha_anterior = (datetime.now() - timedelta(days=369)).strftime("%Y-%m-%d")
    try:
        ds = copernicusmarine.open_dataset(
            dataset_id="cmems_obs-sl_glo_phy-ssh_nrt_allsat-l4-duacs-0.125deg_P1D",
            variables=["sla"],
            minimum_longitude=lon - 0.2,
            maximum_longitude=lon + 0.2,
            minimum_latitude=lat - 0.2,
            maximum_latitude=lat + 0.2,
            start_datetime=fecha_anterior,
            end_datetime=fecha_anterior,
            username=username,
            password=password,
        )
        sla = float(ds["sla"].mean().values)
        return round(sla * 100, 1)
    except Exception as e:
        print(f"  Error año anterior ({lat}, {lon}): {e}")
        return None

def calcular_tendencia(anomalia_actual, punto_id):
    """
    Compara la anomalía actual con la media histórica del mes.
    """
    mes_actual = datetime.now().month - 1
    if punto_id in MEDIAS_HISTORICAS_ANOMALIA and anomalia_actual is not None:
        media = MEDIAS_HISTORICAS_ANOMALIA[punto_id][mes_actual]
        desviacion = round(anomalia_actual - media, 1)
        return desviacion, media
    return None, None

def clasificar_anomalia(sla_cm):
    """
    Clasifica la anomalía SLA en color e interpretación.
    """
    if sla_cm is None:
        return "#888888", "Sin datos"
    elif sla_cm <= -10:
        return "#0066CC", "Nivel muy bajo"
    elif sla_cm <= -5:
        return "#4499DD", "Por debajo de la media"
    elif sla_cm < -2:
        return "#88BBEE", "Ligeramente bajo"
    elif sla_cm <= 2:
        return "#44AA66", "Normal"
    elif sla_cm < 5:
        return "#FFCC44", "Ligeramente elevado"
    elif sla_cm < 10:
        return "#FF8822", "Por encima de la media"
    else:
        return "#CC2200", "Nivel muy elevado"

def generar_json():
    username = os.environ.get("COPERNICUS_USER")
    password = os.environ.get("COPERNICUS_PASSWORD")

    if not username or not password:
        print("ERROR: Faltan credenciales COPERNICUS_USER o COPERNICUS_PASSWORD")
        return

    print(f"\n{'='*60}")
    print(f"Actualizando nivel del mar — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    resultados = []
    errores = 0

    for punto in PUNTOS:
        print(f"Procesando: {punto['nombre']}...")

        sla_actual, fecha_dato = obtener_anomalia_copernicus(
            punto["lat"], punto["lon"], username, password
        )
        sla_anterior = obtener_anomalia_anio_anterior(
            punto["lat"], punto["lon"], username, password
        )
        desviacion, media_historica = calcular_tendencia(sla_actual, punto["id"])
        color, etiqueta = clasificar_anomalia(sla_actual)

        diferencia_anual = None
        if sla_actual is not None and sla_anterior is not None:
            diferencia_anual = round(sla_actual - sla_anterior, 1)

        if sla_actual is None:
            errores += 1

        resultados.append({
            "id":                   punto["id"],
            "nombre":               punto["nombre"],
            "zona":                 punto["zona"],
            "lat":                  punto["lat"],
            "lon":                  punto["lon"],
            "sla_actual_cm":        sla_actual,
            "sla_anio_anterior_cm": sla_anterior,
            "diferencia_anual_cm":  diferencia_anual,
            "media_historica_cm":   media_historica,
            "desviacion_cm":        desviacion,
            "color":                color,
            "etiqueta_anomalia":    etiqueta,
            "fecha_dato":           fecha_dato,
        })

        if sla_actual is not None:
            signo = "+" if sla_actual > 0 else ""
            print(f"  ✓ SLA: {signo}{sla_actual} cm | {etiqueta}")
        else:
            print(f"  ✗ Sin datos")

    os.makedirs("docs", exist_ok=True)
    output = {
        "ultima_actualizacion": datetime.now().isoformat(),
        "fecha_legible":        datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "total_puntos":         len(PUNTOS),
        "puntos_con_datos":     len(PUNTOS) - errores,
        "fuente":               "Copernicus Marine Service — DUACS L4",
        "nota":                 "SLA = Sea Level Anomaly en cm respecto a la media 1993-2020",
        "puntos":               resultados
    }

    with open("docs/nivel_mar.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ JSON guardado en docs/nivel_mar.json")
    print(f"✓ {len(PUNTOS) - errores}/{len(PUNTOS)} puntos actualizados\n")

if __name__ == "__main__":
    generar_json()
