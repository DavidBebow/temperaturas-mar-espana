import requests
import json
import os
import csv
import io
from datetime import datetime, timedelta

COMUNIDADES = [
    {"id": "andalucia",       "nombre": "Andalucía",              "lat": 37.45, "lon": -4.50, "bbox_w": -7.52, "bbox_s": 35.95, "bbox_e": -1.62, "bbox_n": 38.73},
    {"id": "aragon",          "nombre": "Aragón",                 "lat": 41.60, "lon": -0.90, "bbox_w": -2.25, "bbox_s": 39.95, "bbox_e":  0.78, "bbox_n": 42.98},
    {"id": "asturias",        "nombre": "Asturias",               "lat": 43.30, "lon": -6.00, "bbox_w": -7.10, "bbox_s": 42.92, "bbox_e": -4.52, "bbox_n": 43.67},
    {"id": "baleares",        "nombre": "Islas Baleares",         "lat": 39.50, "lon":  2.80, "bbox_w":  1.15, "bbox_s": 38.64, "bbox_e":  4.34, "bbox_n": 40.09},
    {"id": "canarias",        "nombre": "Canarias",               "lat": 28.20, "lon":-15.50, "bbox_w":-18.18, "bbox_s": 27.63, "bbox_e":-13.34, "bbox_n": 29.47},
    {"id": "cantabria",       "nombre": "Cantabria",              "lat": 43.18, "lon": -4.00, "bbox_w": -4.88, "bbox_s": 42.77, "bbox_e": -3.32, "bbox_n": 43.51},
    {"id": "castilla_mancha", "nombre": "Castilla-La Mancha",     "lat": 39.50, "lon": -2.50, "bbox_w": -5.23, "bbox_s": 37.92, "bbox_e": -0.93, "bbox_n": 41.33},
    {"id": "castilla_leon",   "nombre": "Castilla y León",        "lat": 41.60, "lon": -4.50, "bbox_w": -7.00, "bbox_s": 40.14, "bbox_e": -2.00, "bbox_n": 43.22},
    {"id": "cataluna",        "nombre": "Cataluña",               "lat": 41.70, "lon":  1.60, "bbox_w":  0.15, "bbox_s": 40.51, "bbox_e":  3.33, "bbox_n": 42.86},
    {"id": "c_valenciana",    "nombre": "Comunidad Valenciana",   "lat": 39.20, "lon": -0.75, "bbox_w": -1.52, "bbox_s": 37.84, "bbox_e":  0.53, "bbox_n": 40.79},
    {"id": "extremadura",     "nombre": "Extremadura",            "lat": 39.20, "lon": -6.20, "bbox_w": -7.55, "bbox_s": 37.93, "bbox_e": -4.63, "bbox_n": 40.49},
    {"id": "galicia",         "nombre": "Galicia",                "lat": 42.80, "lon": -8.00, "bbox_w": -9.32, "bbox_s": 41.80, "bbox_e": -6.74, "bbox_n": 43.78},
    {"id": "la_rioja",        "nombre": "La Rioja",               "lat": 42.30, "lon": -2.40, "bbox_w": -3.12, "bbox_s": 41.91, "bbox_e": -1.67, "bbox_n": 42.63},
    {"id": "madrid",          "nombre": "Comunidad de Madrid",    "lat": 40.40, "lon": -3.70, "bbox_w": -4.59, "bbox_s": 39.88, "bbox_e": -3.05, "bbox_n": 41.17},
    {"id": "murcia",          "nombre": "Región de Murcia",       "lat": 37.90, "lon": -1.50, "bbox_w": -2.35, "bbox_s": 37.37, "bbox_e": -0.64, "bbox_n": 38.73},
    {"id": "navarra",         "nombre": "Navarra",                "lat": 42.70, "lon": -1.70, "bbox_w": -2.48, "bbox_s": 41.91, "bbox_e": -0.48, "bbox_n": 43.32},
    {"id": "pais_vasco",      "nombre": "País Vasco",             "lat": 43.00, "lon": -2.50, "bbox_w": -3.50, "bbox_s": 42.57, "bbox_e": -1.72, "bbox_n": 43.46},
    {"id": "ceuta",           "nombre": "Ceuta",                  "lat": 35.89, "lon": -5.31, "bbox_w": -5.40, "bbox_s": 35.84, "bbox_e": -5.27, "bbox_n": 35.93},
    {"id": "melilla",         "nombre": "Melilla",                "lat": 35.29, "lon": -2.94, "bbox_w": -2.98, "bbox_s": 35.26, "bbox_e": -2.90, "bbox_n": 35.35},
]

def asignar_comunidad(lat, lon):
    """Asigna un foco de incendio a su comunidad autónoma por bounding box."""
    for c in COMUNIDADES:
        if c["bbox_w"] <= lon <= c["bbox_e"] and c["bbox_s"] <= lat <= c["bbox_n"]:
            return c["id"]
    return None

def obtener_focos(api_key, fecha=None):
    """
    Obtiene focos de calor de NASA FIRMS para España.
    Si fecha es None usa datos NRT (últimas 24h).
    Si fecha es una cadena YYYY-MM-DD usa el archivo histórico.
    Solo cuenta focos de confianza nominal o alta.
    """
    area = "-18.5,27.5,4.5,44.0"

    if fecha is None:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/VIIRS_SNPP_NRT/{area}/1"
    else:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/VIIRS_SNPP_SP/{area}/1/{fecha}"

    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()

        if not r.text.strip() or r.text.strip().startswith("You have exceeded"):
            print(f"  API limit o sin datos para {fecha or 'hoy'}")
            return {}

        focos_por_comunidad = {c["id"]: 0 for c in COMUNIDADES}
        reader = csv.DictReader(io.StringIO(r.text))

        for row in reader:
            try:
                lat  = float(row["latitude"])
                lon  = float(row["longitude"])
                conf = row.get("confidence", "n").strip().lower()

                # Solo confianza nominal (n) o alta (h)
                if conf not in ["n", "h", "nominal", "high"]:
                    continue

                comunidad = asignar_comunidad(lat, lon)
                if comunidad:
                    focos_por_comunidad[comunidad] += 1
            except (ValueError, KeyError):
                continue

        return focos_por_comunidad

    except Exception as e:
        print(f"  Error obteniendo focos ({fecha or 'hoy'}): {e}")
        return {}

def clasificar_actividad(focos):
    """Clasifica la actividad y devuelve color y etiqueta."""
    if focos == 0:
        return "#44AA66", "Sin incendios activos"
    elif focos <= 5:
        return "#FFCC44", "Actividad baja"
    elif focos <= 20:
        return "#FF8822", "Actividad moderada"
    elif focos <= 50:
        return "#FF4400", "Actividad alta"
    else:
        return "#CC2200", "Actividad muy alta"

def calcular_max_racha(entradas, con_fuego=True):
    """Calcula la racha máxima de días consecutivos con/sin fuego."""
    max_racha = 0
    racha_actual = 0
    for entrada in sorted(entradas, key=lambda x: x["fecha"]):
        tiene = entrada["tiene_fuego"]
        if tiene == con_fuego:
            racha_actual += 1
            max_racha = max(max_racha, racha_actual)
        else:
            racha_actual = 0
    return max_racha

def actualizar_historial(datos_hoy, datos_anio_anterior):
    """Actualiza el historial con los datos de hoy y del año anterior."""
    ruta = "docs/historial_incendios.json"
    hoy = datetime.now().strftime("%Y-%m-%d")
    fecha_anterior = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    anio_actual = datetime.now().year
    anio_anterior = anio_actual - 1

    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            historial = json.load(f)
    else:
        historial = {}

    for c in COMUNIDADES:
        cid = c["id"]
        if cid not in historial:
            historial[cid] = []

        # Añadir datos de hoy
        focos_hoy = datos_hoy.get(cid, 0)
        if not any(e["fecha"] == hoy for e in historial[cid]):
            historial[cid].append({
                "fecha": hoy,
                "focos": focos_hoy,
                "tiene_fuego": focos_hoy > 0
            })

        # Añadir datos del año anterior (misma fecha)
        focos_ant = datos_anio_anterior.get(cid, 0)
        if not any(e["fecha"] == fecha_anterior for e in historial[cid]):
            historial[cid].append({
                "fecha": fecha_anterior,
                "focos": focos_ant,
                "tiene_fuego": focos_ant > 0
            })

        # Mantener solo últimos 2 años ordenados
        historial[cid] = sorted(
            historial[cid],
            key=lambda x: x["fecha"],
            reverse=True
        )[:730]

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)

    return historial

def calcular_estadisticas(historial, cid):
    """Calcula todas las estadísticas para una comunidad."""
    entradas = historial.get(cid, [])
    if not entradas:
        return {
            "dias_consecutivos": 0,
            "dias_anio_actual": 0,
            "dias_anio_anterior": 0,
            "max_racha_con_fuego": 0,
        }

    hoy = datetime.now()
    anio_actual = hoy.year
    anio_anterior = anio_actual - 1

    # Días con fuego este año
    dias_anio_actual = sum(
        1 for e in entradas
        if e["tiene_fuego"] and e["fecha"].startswith(str(anio_actual))
    )

    # Días con fuego el año anterior
    dias_anio_anterior = sum(
        1 for e in entradas
        if e["tiene_fuego"] and e["fecha"].startswith(str(anio_anterior))
    )

    # Días consecutivos con fuego hasta hoy
    dias_consecutivos = 0
    for entrada in sorted(entradas, key=lambda x: x["fecha"], reverse=True):
        if entrada["tiene_fuego"]:
            dias_consecutivos += 1
        else:
            break

    # Récord de racha con fuego
    max_racha = calcular_max_racha(entradas, con_fuego=True)

    return {
        "dias_consecutivos":   dias_consecutivos,
        "dias_anio_actual":    dias_anio_actual,
        "dias_anio_anterior":  dias_anio_anterior,
        "max_racha_con_fuego": max_racha,
    }

def generar_json():
    api_key = os.environ.get("NASA_FIRMS_KEY")
    if not api_key:
        print("ERROR: Falta la variable NASA_FIRMS_KEY")
        return

    print(f"\n{'='*60}")
    print(f"Actualizando incendios — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    fecha_anterior = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    print("Obteniendo focos activos hoy...")
    datos_hoy = obtener_focos(api_key)

    print(f"Obteniendo focos del año anterior ({fecha_anterior})...")
    datos_anio_anterior = obtener_focos(api_key, fecha=fecha_anterior)

    historial = actualizar_historial(datos_hoy, datos_anio_anterior)

    resultados = []
    for c in COMUNIDADES:
        cid   = c["id"]
        focos = datos_hoy.get(cid, 0)
        color, etiqueta = clasificar_actividad(focos)
        stats = calcular_estadisticas(historial, cid)

        resultados.append({
            "id":                   cid,
            "nombre":               c["nombre"],
            "lat":                  c["lat"],
            "lon":                  c["lon"],
            "focos_activos":        focos,
            "tiene_fuego":          focos > 0,
            "color":                color,
            "etiqueta":             etiqueta,
            "dias_consecutivos":    stats["dias_consecutivos"],
            "dias_anio_actual":     stats["dias_anio_actual"],
            "dias_anio_anterior":   stats["dias_anio_anterior"],
            "max_racha_con_fuego":  stats["max_racha_con_fuego"],
        })

        estado = f"🔥 {focos} focos" if focos > 0 else "✓ Sin incendios"
        print(f"  {c['nombre']}: {estado} | Consecutivos: {stats['dias_consecutivos']}d | Este año: {stats['dias_anio_actual']}d | Año ant: {stats['dias_anio_anterior']}d")

    os.makedirs("docs", exist_ok=True)
    output = {
        "ultima_actualizacion": datetime.now().isoformat(),
        "fecha_legible":        datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "total_comunidades":    len(COMUNIDADES),
        "comunidades_con_fuego": sum(1 for r in resultados if r["tiene_fuego"]),
        "total_focos_espana":   sum(r["focos_activos"] for r in resultados),
        "fuente":               "NASA FIRMS — VIIRS SNPP",
        "comunidades":          resultados
    }

    with open("docs/incendios.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ JSON guardado en docs/incendios.json")
    print(f"✓ {output['comunidades_con_fuego']} comunidades con fuego activo")
    print(f"✓ {output['total_focos_espana']} focos totales en España\n")

if __name__ == "__main__":
    generar_json()
