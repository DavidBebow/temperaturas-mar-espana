import csv
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

COMUNIDADES = [
    {"id": "andalucia", "nombre": "Andalucía", "lat": 37.45, "lon": -4.50, "bbox_w": -7.52, "bbox_s": 35.95, "bbox_e": -1.62, "bbox_n": 38.73},
    {"id": "aragon", "nombre": "Aragón", "lat": 41.60, "lon": -0.90, "bbox_w": -2.25, "bbox_s": 39.95, "bbox_e": 0.78, "bbox_n": 42.98},
    {"id": "asturias", "nombre": "Asturias", "lat": 43.30, "lon": -6.00, "bbox_w": -7.10, "bbox_s": 42.92, "bbox_e": -4.52, "bbox_n": 43.67},
    {"id": "baleares", "nombre": "Islas Baleares", "lat": 39.50, "lon": 2.80, "bbox_w": 1.15, "bbox_s": 38.64, "bbox_e": 4.34, "bbox_n": 40.09},
    {"id": "canarias", "nombre": "Canarias", "lat": 28.20, "lon": -15.50, "bbox_w": -18.18, "bbox_s": 27.63, "bbox_e": -13.34, "bbox_n": 29.47},
    {"id": "cantabria", "nombre": "Cantabria", "lat": 43.18, "lon": -4.00, "bbox_w": -4.88, "bbox_s": 42.77, "bbox_e": -3.32, "bbox_n": 43.51},
    {"id": "castilla_mancha", "nombre": "Castilla-La Mancha", "lat": 39.50, "lon": -2.50, "bbox_w": -5.23, "bbox_s": 37.92, "bbox_e": -0.93, "bbox_n": 41.33},
    {"id": "castilla_leon", "nombre": "Castilla y León", "lat": 41.60, "lon": -4.50, "bbox_w": -7.00, "bbox_s": 40.14, "bbox_e": -2.00, "bbox_n": 43.22},
    {"id": "cataluna", "nombre": "Cataluña", "lat": 41.70, "lon": 1.60, "bbox_w": 0.15, "bbox_s": 40.51, "bbox_e": 3.33, "bbox_n": 42.86},
    {"id": "c_valenciana", "nombre": "Comunidad Valenciana", "lat": 39.20, "lon": -0.75, "bbox_w": -1.52, "bbox_s": 37.84, "bbox_e": 0.53, "bbox_n": 40.79},
    {"id": "extremadura", "nombre": "Extremadura", "lat": 39.20, "lon": -6.20, "bbox_w": -7.55, "bbox_s": 37.93, "bbox_e": -4.63, "bbox_n": 40.49},
    {"id": "galicia", "nombre": "Galicia", "lat": 42.80, "lon": -8.00, "bbox_w": -9.32, "bbox_s": 41.80, "bbox_e": -6.74, "bbox_n": 43.78},
    {"id": "la_rioja", "nombre": "La Rioja", "lat": 42.30, "lon": -2.40, "bbox_w": -3.12, "bbox_s": 41.91, "bbox_e": -1.67, "bbox_n": 42.63},
    {"id": "madrid", "nombre": "Comunidad de Madrid", "lat": 40.40, "lon": -3.70, "bbox_w": -4.59, "bbox_s": 39.88, "bbox_e": -3.05, "bbox_n": 41.17},
    {"id": "murcia", "nombre": "Región de Murcia", "lat": 37.90, "lon": -1.50, "bbox_w": -2.35, "bbox_s": 37.37, "bbox_e": -0.64, "bbox_n": 38.73},
    {"id": "navarra", "nombre": "Navarra", "lat": 42.70, "lon": -1.70, "bbox_w": -2.48, "bbox_s": 41.91, "bbox_e": -0.48, "bbox_n": 43.32},
    {"id": "pais_vasco", "nombre": "País Vasco", "lat": 43.00, "lon": -2.50, "bbox_w": -3.50, "bbox_s": 42.57, "bbox_e": -1.72, "bbox_n": 43.46},
    {"id": "ceuta", "nombre": "Ceuta", "lat": 35.89, "lon": -5.31, "bbox_w": -5.40, "bbox_s": 35.84, "bbox_e": -5.27, "bbox_n": 35.93},
    {"id": "melilla", "nombre": "Melilla", "lat": 35.29, "lon": -2.94, "bbox_w": -2.98, "bbox_s": 35.26, "bbox_e": -2.90, "bbox_n": 35.35},
]

SENSORES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]
AREA_ESPANA = "-18.5,27.5,4.5,44.0"
HORAS_ACTIVO = 48
TZ_ESPANA = ZoneInfo("Europe/Madrid")


def ahora_utc():
    return datetime.now(timezone.utc)


def ahora_espana():
    return datetime.now(TZ_ESPANA)


def asignar_comunidad(lat, lon):
    for c in COMUNIDADES:
        if c["bbox_w"] <= lon <= c["bbox_e"] and c["bbox_s"] <= lat <= c["bbox_n"]:
            return c["id"]
    return None


def parsear_deteccion_utc(fecha, hora):
    if not fecha:
        return None
    hora = str(hora or "").strip().zfill(4)
    try:
        return datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def obtener_focos_sensor(api_key, sensor, dias=2):
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/{sensor}/{AREA_ESPANA}/{dias}"
    focos = []

    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()

        texto = r.text.strip()
        if not texto or "exceeded" in texto.lower() or "invalid map key" in texto.lower():
            print(f"  {sensor}: sin datos, límite API o clave inválida")
            return focos

        reader = csv.DictReader(io.StringIO(texto))
        for row in reader:
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                conf = str(row.get("confidence", "n")).strip().lower()
                frp = float(row.get("frp", 0) or 0)
                fecha = row.get("acq_date", "")
                hora = row.get("acq_time", "")
                deteccion_utc = parsear_deteccion_utc(fecha, hora)

                if conf not in ["n", "h", "nominal", "high"]:
                    continue

                comunidad = asignar_comunidad(lat, lon)
                if not comunidad:
                    continue

                focos.append({
                    "lat": lat,
                    "lon": lon,
                    "frp": round(frp, 1),
                    "fecha": fecha,
                    "acq_time": str(hora).zfill(4),
                    "deteccion_utc": deteccion_utc.isoformat() if deteccion_utc else None,
                    "sensor": sensor,
                    "comunidad_id": comunidad,
                })
            except (ValueError, KeyError):
                continue
    except Exception as e:
        print(f"  {sensor}: error obteniendo focos: {e}")

    print(f"  {sensor}: {len(focos)} detecciones en España")
    return focos


def obtener_focos(api_key, dias=2):
    todos = []
    for sensor in SENSORES:
        todos.extend(obtener_focos_sensor(api_key, sensor, dias=dias))

    unicos = {}
    for f in todos:
        clave = (round(f["lat"], 4), round(f["lon"], 4), f["fecha"], f["acq_time"])
        if clave not in unicos or f["frp"] > unicos[clave]["frp"]:
            unicos[clave] = f

    focos_por_comunidad = {c["id"]: [] for c in COMUNIDADES}
    dias_con_fuego = {c["id"]: set() for c in COMUNIDADES}

    for f in unicos.values():
        cid = f["comunidad_id"]
        focos_por_comunidad[cid].append(f)
        if f["fecha"]:
            dias_con_fuego[cid].add(f["fecha"])

    return focos_por_comunidad, dias_con_fuego


def reverse_geocode(lat, lon):
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json", "zoom": 10, "accept-language": "es"}
        headers = {"User-Agent": "calentamientoglobal.es/incendios"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        addr = r.json().get("address", {})
        return (
            addr.get("municipality")
            or addr.get("town")
            or addr.get("village")
            or addr.get("county")
            or addr.get("state")
            or "Zona rural"
        )
    except Exception:
        return "Zona rural"


def clasificar_intensidad(frp):
    if frp >= 100:
        return "Muy alta"
    if frp >= 30:
        return "Alta"
    if frp >= 10:
        return "Moderada"
    return "Baja"


def clasificar_actividad(n_focos):
    if n_focos == 0:
        return "#1a3a1a", "Sin detecciones recientes"
    if n_focos <= 5:
        return "#7a6a10", "Actividad baja"
    if n_focos <= 20:
        return "#aa5010", "Actividad moderada"
    if n_focos <= 50:
        return "#cc2a00", "Actividad alta"
    return "#ff0000", "Actividad muy alta"


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

    hoy = ahora_espana().date()

    for c in COMUNIDADES:
        cid = c["id"]
        historial.setdefault(cid, [])
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

        historial[cid] = sorted(historial[cid], key=lambda x: x["fecha"], reverse=True)[:730]

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)

    return historial


def calcular_estadisticas(historial, cid):
    entradas = historial.get(cid, [])
    if not entradas:
        return {"dias_consecutivos": 0, "dias_anio_actual": 0, "max_racha_con_fuego": 0}

    anio_actual = ahora_espana().year
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

    return {
        "dias_consecutivos": dias_consecutivos,
        "dias_anio_actual": dias_anio_actual,
        "max_racha_con_fuego": calcular_max_racha(entradas),
    }


def es_foco_reciente(foco):
    if not foco.get("deteccion_utc"):
        return False
    deteccion = datetime.fromisoformat(foco["deteccion_utc"])
    return deteccion >= ahora_utc() - timedelta(hours=HORAS_ACTIVO)


def generar_json():
    api_key = os.environ.get("NASA_FIRMS_KEY")
    if not api_key:
        print("ERROR: Falta NASA_FIRMS_KEY")
        return

    print(f"\n{'=' * 60}")
    print(f"Actualizando incendios — {ahora_espana().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'=' * 60}\n")

    print(f"Obteniendo focos recientes de FIRMS, ventana activa: últimas {HORAS_ACTIVO} horas...")
    focos_actual, dias_actual = obtener_focos(api_key, dias=2)
    historial = actualizar_historial(dias_actual)

    todos_focos_recientes = []
    focos_recientes_por_comunidad = {}

    for c in COMUNIDADES:
        cid = c["id"]
        focos = [f for f in focos_actual.get(cid, []) if es_foco_reciente(f)]
        focos_recientes_por_comunidad[cid] = focos
        for f in focos:
            todos_focos_recientes.append({
                "lat": f["lat"],
                "lon": f["lon"],
                "frp": f["frp"],
                "comunidad": c["nombre"],
                "deteccion_utc": f["deteccion_utc"],
                "sensor": f["sensor"],
            })

    todos_focos_recientes.sort(key=lambda x: x["frp"], reverse=True)
    max_geocode = 40
    focos_geocodificados = []

    print(f"\nTotal focos recientes: {len(todos_focos_recientes)}")
    print(f"Geocodificando los {min(max_geocode, len(todos_focos_recientes))} más intensos...")

    for i, foco in enumerate(todos_focos_recientes):
        if i < max_geocode:
            nombre = reverse_geocode(foco["lat"], foco["lon"])
            time.sleep(1.1)
            print(f"  {i + 1}. {nombre} ({foco['comunidad']}) — FRP: {foco['frp']} MW")
        else:
            nombre = None

        focos_geocodificados.append({
            "lat": foco["lat"],
            "lon": foco["lon"],
            "frp": foco["frp"],
            "intensidad": clasificar_intensidad(foco["frp"]),
            "comunidad": foco["comunidad"],
            "lugar": nombre,
            "deteccion_utc": foco["deteccion_utc"],
            "sensor": foco["sensor"],
        })

    resultados = []
    for c in COMUNIDADES:
        cid = c["id"]
        focos = focos_recientes_por_comunidad.get(cid, [])
        n_focos = len(focos)
        color, etiqueta = clasificar_actividad(n_focos)
        stats = calcular_estadisticas(historial, cid)

        resultados.append({
            "id": cid,
            "nombre": c["nombre"],
            "lat": c["lat"],
            "lon": c["lon"],
            "focos_activos": n_focos,
            "tiene_fuego": n_focos > 0,
            "color": color,
            "etiqueta": etiqueta,
            "dias_consecutivos": stats["dias_consecutivos"],
            "dias_anio_actual": stats["dias_anio_actual"],
            "max_racha_con_fuego": stats["max_racha_con_fuego"],
        })

        estado = f"{n_focos} focos recientes" if n_focos > 0 else "sin detecciones recientes"
        print(f"  {c['nombre']}: {estado} | Consec: {stats['dias_consecutivos']}d | Año actual: {stats['dias_anio_actual']}d")

    os.makedirs("docs", exist_ok=True)
    ahora_es = ahora_espana()
    output = {
        "ultima_actualizacion": ahora_es.isoformat(),
        "fecha_legible": ahora_es.strftime("%d/%m/%Y a las %H:%M"),
        "ventana_activa_horas": HORAS_ACTIVO,
        "total_comunidades": len(COMUNIDADES),
        "comunidades_con_fuego": sum(1 for r in resultados if r["tiene_fuego"]),
        "total_focos_espana": sum(r["focos_activos"] for r in resultados),
        "fuente": "NASA FIRMS — VIIRS SNPP/NOAA-20/NOAA-21 NRT",
        "focos_individuales": focos_geocodificados,
        "comunidades": resultados,
    }

    with open("docs/incendios.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\nJSON guardado en docs/incendios.json")
    print(f"{output['comunidades_con_fuego']} comunidades con detecciones recientes")
    print(f"{len(focos_geocodificados)} focos individuales guardados\n")


if __name__ == "__main__":
    generar_json()
