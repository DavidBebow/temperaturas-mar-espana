import requests
import json
import os
import csv
import io
import time
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
    for c in COMUNIDADES:
        if c["bbox_w"] <= lon <= c["bbox_e"] and c["bbox_s"] <= lat <= c["bbox_n"]:
            return c["id"]
    return None

def obtener_focos_rango(api_key, dias=7, fecha_inicio=None):
    area = "-18.5,27.5,4.5,44.0"
    if fecha_inicio is None:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/VIIRS_SNPP_NRT/{area}/{dias}"
    else:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/VIIRS_SNPP_SP/{area}/{dias}/{fecha_inicio}"

    focos_por_comunidad = {c["id"]: [] for c in COMUNIDADES}
    dias_con_fuego      = {c["id"]: set() for c in COMUNIDADES}

    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()

        if not r.text.strip() or "exceeded" in r.text.lower():
            print(f"  Sin datos o límite API para {fecha_inicio or 'NRT'}")
            return focos_por_comunidad, dias_con_fuego

        reader = csv.DictReader(io.StringIO(r.text))
        for row in reader:
            try:
                lat   = float(row["latitude"])
                lon   = float(row["longitude"])
                conf  = row.get("confidence", "n").strip().lower()
                frp   = float(row.get("frp", 0) or 0)
                fecha = row.get("acq_date", "")

                if conf not in ["n", "h", "nominal", "high"]:
                    continue

                comunidad = asignar_comunidad(lat, lon)
                if comunidad:
                    focos_por_comunidad[comunidad].append({
                        "lat":   lat,
                        "lon":   lon,
                        "frp":   round(frp, 1),
                        "fecha": fecha
                    })
                    if fecha:
                        dias_con_fuego[comunidad].add(fecha)
            except (ValueError, KeyError):
                continue

    except Exception as e:
        print(f"  Error obteniendo focos: {e}")

    return focos_por_comunidad, dias_con_fuego

def reverse_geocode(lat, lon):
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "lat": lat, "lon": lon,
            "format": "json", "zoom": 10,
            "accept-language": "es"
        }
        headers = {"User-Agent": "calentamientoglobal.es/incendios"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        addr = data.get("address", {})
        lugar = (
            addr.get("municipality") or
            addr.get("town") or
            addr.get("village") or
            addr.get("county") or
            addr.get("state") or
            "Zona rural"
        )
        return lugar
    except Exception:
        return "Zona rural"

def clasificar_intensidad(frp):
    if frp >= 100: return "Muy alta"
    elif frp >= 30: return "Alta"
    elif frp >= 10: return "Moderada"
    else: return "Baja"

def clasificar_actividad(n_focos):
    if n_focos == 0:    return "#1a3a1a", "Sin incendios activos"
    elif n_focos <= 5:  return "#7a6a10", "Actividad baja"
    elif n_focos <= 20: return "#aa5010", "Actividad moderada"
    elif n_focos <= 50: return "#cc2a00", "Actividad alta"
    else:               return "#ff0000", "Actividad muy alta"

def calcular_max_racha(entradas):
    max_racha = 0
    racha_actual = 0
    for entrada in sorted(entradas, key=lambda x: x["fecha"]):
        if entrada["tiene_fuego"]:
            racha_actual += 1
            max_racha = max(max_racha, racha_actual)
        else:
            racha_actual = 0
    return max_racha

def actualizar_historial(dias_con_fuego_actual):
    ruta = "docs/historial_incendios.json"

    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            historial = json.load(f)
    else:
        historial = {}

    hoy = datetime.now()

    for c in COMUNIDADES:
        cid = c["id"]
        if cid not in historial:
            historial[cid] = []

        fechas_existentes = {e["fecha"] for e in historial[cid]}

        for fecha in dias_con_fuego_actual.get(cid, set()):
            if fecha not in fechas_existentes:
                historial[cid].append({"fecha": fecha, "tiene_fuego": True})
                fechas_existentes.add(fecha)

        for i in range(7):
            fecha = (hoy - timedelta(days=i)).strftime("%Y-%m-%d")
            if fecha not in fechas_existentes:
                historial[cid].append({"fecha": fecha, "tiene_fuego": False})
                fechas_existentes.add(fecha)

        historial[cid] = sorted(
            historial[cid], key=lambda x: x["fecha"], reverse=True
        )[:730]

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)

    return historial

def calcular_estadisticas(historial, cid):
    entradas = historial.get(cid, [])
    if not entradas:
        return {
            "dias_consecutivos":   0,
            "dias_anio_actual":    0,
            "max_racha_con_fuego": 0,
        }

    anio_actual = datetime.now().year

    dias_anio_actual = sum(
        1 for e in entradas
        if e["tiene_fuego"] and e["fecha"].startswith(str(anio_actual))
    )

    dias_consecutivos = 0
    for entrada in sorted(entradas, key=lambda x: x["fecha"], reverse=True):
        if entrada["tiene_fuego"]:
            dias_consecutivos += 1
        else:
            break

    max_racha = calcular_max_racha(entradas)

    return {
        "dias_consecutivos":   dias_consecutivos,
        "dias_anio_actual":    dias_anio_actual,
        "max_racha_con_fuego": max_racha,
    }

def generar_json():
    api_key = os.environ.get("NASA_FIRMS_KEY")
    if not api_key:
        print("ERROR: Falta NASA_FIRMS_KEY")
        return

    print(f"\n{'='*60}")
    print(f"Actualizando incendios — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    print("Obteniendo focos activos (últimos 7 días)...")
    focos_actual, dias_actual = obtener_focos_rango(api_key, dias=7)

    historial = actualizar_historial(dias_actual)

    hoy_str = datetime.now().strftime("%Y-%m-%d")
    todos_focos_hoy = []
    focos_hoy_por_comunidad = {}

    for c in COMUNIDADES:
        cid = c["id"]
        focos_hoy = [f for f in focos_actual.get(cid, []) if f["fecha"] == hoy_str]
        focos_hoy_por_comunidad[cid] = focos_hoy
        for f in focos_hoy:
            todos_focos_hoy.append({
                "lat":       f["lat"],
                "lon":       f["lon"],
                "frp":       f["frp"],
                "comunidad": c["nombre"]
            })

    todos_focos_hoy.sort(key=lambda x: x["frp"], reverse=True)
    MAX_GEOCODE = 40
    focos_geocodificados = []

    print(f"\nTotal focos hoy: {len(todos_focos_hoy)}")
    print(f"Geocodificando los {min(MAX_GEOCODE, len(todos_focos_hoy))} más intensos...")

    for i, foco in enumerate(todos_focos_hoy):
        if i < MAX_GEOCODE:
            nombre = reverse_geocode(foco["lat"], foco["lon"])
            time.sleep(1.1)
            print(f"  {i+1}. {nombre} ({foco['comunidad']}) — FRP: {foco['frp']} MW")
        else:
            nombre = None

        focos_geocodificados.append({
            "lat":        foco["lat"],
            "lon":        foco["lon"],
            "frp":        foco["frp"],
            "intensidad": clasificar_intensidad(foco["frp"]),
            "comunidad":  foco["comunidad"],
            "lugar":      nombre
        })

    resultados = []
    for c in COMUNIDADES:
        cid     = c["id"]
        focos   = focos_hoy_por_comunidad.get(cid, [])
        n_focos = len(focos)
        color, etiqueta = clasificar_actividad(n_focos)
        stats = calcular_estadisticas(historial, cid)

        resultados.append({
            "id":                  cid,
            "nombre":              c["nombre"],
            "lat":                 c["lat"],
            "lon":                 c["lon"],
            "focos_activos":       n_focos,
            "tiene_fuego":         n_focos > 0,
            "color":               color,
            "etiqueta":            etiqueta,
            "dias_consecutivos":   stats["dias_consecutivos"],
            "dias_anio_actual":    stats["dias_anio_actual"],
            "max_racha_con_fuego": stats["max_racha_con_fuego"],
        })

        estado = f"🔥 {n_focos} focos" if n_focos > 0 else "✓ Sin incendios"
        print(f"  {c['nombre']}: {estado} | Consec: {stats['dias_consecutivos']}d | Año actual: {stats['dias_anio_actual']}d")

    os.makedirs("docs", exist_ok=True)
    output = {
        "ultima_actualizacion":  datetime.now().isoformat(),
        "fecha_legible":         datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "total_comunidades":     len(COMUNIDADES),
        "comunidades_con_fuego": sum(1 for r in resultados if r["tiene_fuego"]),
        "total_focos_espana":    sum(r["focos_activos"] for r in resultados),
        "fuente":                "NASA FIRMS — VIIRS SNPP",
        "focos_individuales":    focos_geocodificados,
        "comunidades":           resultados
    }

    with open("docs/incendios.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ JSON guardado en docs/incendios.json")
    print(f"✓ {output['comunidades_con_fuego']} comunidades con fuego activo")
    print(f"✓ {len(focos_geocodificados)} focos individuales guardados\n")

if __name__ == "__main__":
    generar_json()
