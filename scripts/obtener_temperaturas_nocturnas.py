"""
Script incremental: solo descarga los datos del día anterior y actualiza
el JSON existente. Mucho más rápido que recalcular todo cada día.

Lógica:
- Lee el JSON anterior (si existe) y conserva el histórico
- Para cada ciudad, pide a AEMET solo el dato de AYER
- Actualiza tmin_anoche, recalcula medias del mes y acumula noches tropicales
- Las medias del año anterior se recalculan UNA VEZ AL MES (día 1)
"""
import os
import json
import time
import requests
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

API_KEY  = os.environ.get("AEMET_API_KEY", "")
BASE_URL = "https://opendata.aemet.es/opendata/api"
HEADERS  = {"api_key": API_KEY, "Accept": "application/json"}

JSON_PATH = "docs/temperaturas_nocturnas.json"
TZ = ZoneInfo("Europe/Madrid")

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

ahora = datetime.now(TZ)
hoy  = ahora.date()
ayer = hoy - timedelta(days=1)

# ─────────────────────────────────────────────────────────────────────────────
# Cargar el histórico previo (si existe)
# ─────────────────────────────────────────────────────────────────────────────
def cargar_historico():
    """
    El JSON guarda, dentro de cada ciudad, un campo 'historico' con todas las
    mínimas y máximas diarias del año en curso. Así no hace falta volver a
    pedirlas a AEMET cada día.
    """
    if not os.path.exists(JSON_PATH):
        return {}, None, None  # primera ejecución
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        hist = {c["id"]: c.get("historico", {}) for c in data.get("ciudades", [])}
        anyo_guardado = data.get("anyo_actual")
        mes_guardado  = data.get("_mes_calculado_ant")  # control para recalcular año anterior
        return hist, anyo_guardado, mes_guardado
    except Exception as e:
        print(f"⚠️  No se pudo leer histórico: {e}")
        return {}, None, None

# ─────────────────────────────────────────────────────────────────────────────
# Llamadas a AEMET
# ─────────────────────────────────────────────────────────────────────────────
def fmt(d):
    return d.strftime("%Y-%m-%dT00:00:00UTC")

def aemet_tramo(idema, fecha_ini, fecha_fin, intentos=3):
    url = (
        f"{BASE_URL}/valores/climatologicos/diarios/datos"
        f"/fechaini/{fmt(fecha_ini)}/fechafin/{fmt(fecha_fin)}"
        f"/estacion/{idema}"
    )
    for intento in range(intentos):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 429:
                time.sleep(5 * (intento + 1))
                continue
            if r.status_code != 200:
                if intento == intentos - 1:
                    print(f"      ❌ {idema}: status {r.status_code}")
                time.sleep(2)
                continue
            body = r.json()
            if body.get("estado") == 404:
                return []
            if body.get("estado") != 200:
                return []
            datos_url = body.get("datos")
            if not datos_url:
                return []
            r2 = requests.get(datos_url, timeout=20)
            if r2.status_code == 200:
                return r2.json()
        except Exception as e:
            if intento == intentos - 1:
                print(f"      ❌ {idema} excepción: {e}")
            time.sleep(2)
    return []

def tramos_15dias(fecha_ini, fecha_fin):
    resultado = []
    cursor = fecha_ini
    while cursor <= fecha_fin:
        fin = min(cursor + timedelta(days=14), fecha_fin)
        resultado.append((cursor, fin))
        cursor = fin + timedelta(days=1)
    return resultado

# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────
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

def es_fecha_iso(clave):
    try:
        date.fromisoformat(clave)
        return True
    except (TypeError, ValueError):
        return False

def datos_historicos(historico):
    """Devuelve solo entradas diarias, excluyendo metadatos internos."""
    return {
        f: d for f, d in historico.items()
        if es_fecha_iso(f) and isinstance(d, dict)
    }

def calcular_color(t):
    if t is None:  return "#888888", "Sin datos"
    if t >= 25:    return "#CC2200", "Muy cálida"
    if t >= 20:    return "#FF6600", "Tropical"
    if t >= 15:    return "#FFAA00", "Cálida"
    if t >= 10:    return "#44AA66", "Templada"
    if t >= 5:     return "#3399CC", "Fresca"
    return "#0055AA", "Fría"

# ─────────────────────────────────────────────────────────────────────────────
# Procesamiento por ciudad
# ─────────────────────────────────────────────────────────────────────────────
def procesar_ciudad(args):
    """
    args = (ciudad, historico_previo, anyo_cambio, mes_cambio)
    historico_previo: dict {fecha: {"tmin": x, "tmax": y}}
    anyo_cambio: True si hay que descargar año entero (cambio de año o sin histórico)
    mes_cambio:  True si hay que recalcular el mes anterior (cambio de mes o sin datos)
    """
    ciudad, hist_previo, anyo_cambio, mes_cambio = args

    mes_act  = hoy.month
    anyo_act = hoy.year
    anyo_ant = anyo_act - 1

    # ── Histórico del año actual ──────────────────────────────────────────────
    historico = dict(hist_previo)  # copiamos lo que ya teníamos

    if anyo_cambio or not historico:
        # Primera ejecución del año (o primer día absoluto) → descarga completa
        print(f"    {ciudad['nombre']}: descargando año entero...")
        inicio_anyo = date(anyo_act, 1, 1)
        for ini, fin in tramos_15dias(inicio_anyo, ayer):
            datos = aemet_tramo(ciudad["idema"], ini, fin)
            for r in datos:
                f = r.get("fecha")
                if f:
                    historico[f] = {
                        "tmin": parse_float(r.get("tmin")),
                        "tmax": parse_float(r.get("tmax")),
                    }
            time.sleep(0.4)
    else:
        # Solo pedimos los días que falten entre el último guardado y ayer
        fechas_existentes = set(datos_historicos(historico).keys())
        ayer_str = ayer.strftime("%Y-%m-%d")
        if ayer_str not in fechas_existentes:
            # Buscamos la última fecha guardada
            fechas_ord = sorted(fechas_existentes)
            ultima = date.fromisoformat(fechas_ord[-1]) if fechas_ord else date(anyo_act, 1, 1)
            siguiente = ultima + timedelta(days=1)
            if siguiente <= ayer:
                for ini, fin in tramos_15dias(siguiente, ayer):
                    datos = aemet_tramo(ciudad["idema"], ini, fin)
                    for r in datos:
                        f = r.get("fecha")
                        if f:
                            historico[f] = {
                                "tmin": parse_float(r.get("tmin")),
                                "tmax": parse_float(r.get("tmax")),
                            }
                    time.sleep(0.4)

    # ── Histórico del mismo mes del año anterior (solo cuando cambia el mes) ──
    # Lo guardamos como datos resumidos directamente
    hist_mes_ant = hist_previo.get("_resumen_mes_ant") if isinstance(hist_previo, dict) else None

    if mes_cambio or hist_mes_ant is None or not isinstance(hist_mes_ant, dict):
        print(f"    {ciudad['nombre']}: recalculando mes año anterior...")
        inicio_mes_ant = date(anyo_ant, mes_act, 1)
        fin_mes_ant    = (date(anyo_ant, mes_act % 12 + 1, 1) - timedelta(days=1)) \
                         if mes_act < 12 else date(anyo_ant, 12, 31)
        mins_ant, maxs_ant = [], []
        for ini, fin in tramos_15dias(inicio_mes_ant, fin_mes_ant):
            datos = aemet_tramo(ciudad["idema"], ini, fin)
            for r in datos:
                mins_ant.append(parse_float(r.get("tmin")))
                maxs_ant.append(parse_float(r.get("tmax")))
            time.sleep(0.4)
        hist_mes_ant = {
            "media_min": media(mins_ant),
            "media_max": media(maxs_ant),
        }

    # ── Cálculos finales a partir del histórico ───────────────────────────────
    mes_str = f"{anyo_act}-{mes_act:02d}"
    hist_diario = datos_historicos(historico)
    mins_mes  = [d.get("tmin") for f, d in hist_diario.items() if f.startswith(mes_str)]
    maxs_mes  = [d.get("tmax") for f, d in hist_diario.items() if f.startswith(mes_str)]
    mins_anyo = [d.get("tmin") for d in hist_diario.values()]

    ayer_str = ayer.strftime("%Y-%m-%d")
    dato_ayer = hist_diario.get(ayer_str, {})
    t_min_anoche = dato_ayer.get("tmin")
    t_max_ayer = dato_ayer.get("tmax")

    media_min_mes     = media(mins_mes)
    media_max_mes     = media(maxs_mes)
    media_min_mes_ant = hist_mes_ant.get("media_min")
    media_max_mes_ant = hist_mes_ant.get("media_max")

    diff_min = round(media_min_mes - media_min_mes_ant, 1) \
               if media_min_mes is not None and media_min_mes_ant is not None else None
    diff_max = round(media_max_mes - media_max_mes_ant, 1) \
               if media_max_mes is not None and media_max_mes_ant is not None else None

    color, etiqueta = calcular_color(t_min_anoche)

    # Guardamos el resumen del mes anterior dentro del propio histórico
    historico["_resumen_mes_ant"] = hist_mes_ant

    return {
        "id":                ciudad["id"],
        "nombre":            ciudad["nombre"],
        "ccaa":              ciudad["ccaa"],
        "lat":               ciudad["lat"],
        "lon":               ciudad["lon"],
        "fecha_anoche":       ayer_str,
        "t_min_anoche":      round(t_min_anoche, 1) if t_min_anoche is not None else None,
        "t_max_ayer":         round(t_max_ayer, 1) if t_max_ayer is not None else None,
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
        "historico":         historico,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def procesar():
    if not API_KEY:
        print("ERROR: AEMET_API_KEY no definida.")
        raise SystemExit(1)

    os.makedirs("docs", exist_ok=True)

    # Cargar histórico anterior
    historico_previo, anyo_guardado, mes_guardado = cargar_historico()
    anyo_cambio = (anyo_guardado != hoy.year)
    mes_cambio  = (mes_guardado != hoy.month)

    if anyo_cambio:
        print(f"📅 Cambio de año detectado: descarga completa del año en curso.")
    if mes_cambio:
        print(f"📅 Cambio de mes detectado: recálculo del mismo mes del año anterior.")
    if not anyo_cambio and not mes_cambio:
        print(f"⚡ Modo incremental: solo se descargarán los días nuevos.")

    print(f"Procesando {len(CIUDADES)} ciudades (3 hilos paralelos)...")

    resultado = [None] * len(CIUDADES)

    args_list = [
        (c, historico_previo.get(c["id"], {}), anyo_cambio, mes_cambio)
        for c in CIUDADES
    ]

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(procesar_ciudad, args_list[i]): i for i in range(len(CIUDADES))}
        completadas = 0
        for future in as_completed(futures):
            idx = futures[future]
            try:
                resultado[idx] = future.result()
                completadas += 1
                r = resultado[idx]
                print(f"  [{completadas}/{len(CIUDADES)}] {r['nombre']:<18} "
                      f"tmin_anoche={r['t_min_anoche']}  "
                      f"nt_mes={r['nt_mes']}  nt_año={r['nt_anyo']}")
            except Exception as e:
                print(f"  Error idx {idx}: {e}")
                c = CIUDADES[idx]
                resultado[idx] = {
                    "id": c["id"], "nombre": c["nombre"], "ccaa": c["ccaa"],
                    "lat": c["lat"], "lon": c["lon"],
                    "fecha_anoche": ayer.strftime("%Y-%m-%d"),
                    "t_min_anoche": None,
                    "t_max_ayer": None,
                    "media_min_mes": None, "media_max_mes": None,
                    "media_min_mes_ant": None, "media_max_mes_ant": None,
                    "diff_min_vs_ant": None, "diff_max_vs_ant": None,
                    "nt_mes": 0, "nt_anyo": 0,
                    "color": "#888888", "etiqueta": "Sin datos",
                    "historico": historico_previo.get(c["id"], {}),
                }

    MESES = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]

    output = {
        "ultima_actualizacion":   ahora.isoformat(),
        "fecha_legible":          ahora.strftime("%d/%m/%Y a las %H:%M"),
        "fecha_anoche":           ayer.strftime("%Y-%m-%d"),
        "mes_actual":             MESES[hoy.month - 1].capitalize(),
        "anyo_actual":            hoy.year,
        "mes_anterior_ref":       f"{MESES[hoy.month - 1]} {hoy.year - 1}",
        "fuente":                 "AEMET OpenData",
        "total_ciudades":         len(resultado),
        "_mes_calculado_ant":     hoy.month,
        "ciudades":               resultado,
    }

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Generado con {len(resultado)} ciudades.")

if __name__ == "__main__":
    procesar()
