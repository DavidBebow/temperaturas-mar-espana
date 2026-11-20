#!/usr/bin/env python3
"""¿Subo este fin de semana? · veredicto por perfil para los macizos activados (hoy, Sierra Nevada). Lo llama nieve.py.

Solo biblioteca estándar (la imagen de Open Graph usa Pillow, que se instala con pip en el paso de nieve.yml y, si falta,
simplemente no se dibuja). Sin red propia: la petición horaria la hace la función `pedir` que le pasa nieve.py (la misma
`om` que ya usa para la previsión: misma fuente, Open-Meteo, mismos cuatro modelos).

Para activar otro macizo basta con añadir una entrada a MACIZOS_ACTIVOS (y a la lista del snippet «CG · Nieve compartir»).

Reglas (todas las cifras de corte son constantes con nombre, justo debajo):
  · mediana de los modelos que den cada variable, hora a hora; en horario de día (9 a 17 h, Europe/Madrid);
  · si falta un dato, ese veredicto no se emite; nunca se rellena.
"""
from __future__ import annotations

import hashlib
import json
import statistics as st
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
WEB = "https://calentamientoglobal.es"
PAGES = "https://davidbebow.github.io/temperaturas-mar-espana"

# ------------------------------------------------------------------------------------------------------- activación
MACIZOS_ACTIVOS = {
    "nevada": {
        "slug": "sierra-nevada", "corto": "Sierra Nevada", "principal": "granada-monte",
        # el punto granada-monte está a 2.500 m: Pradollano (el pueblo) está a 2.100 m, así que el rótulo del macizo es otro
        "rotulos": {"granada-monte": "Sierra Nevada (estación)"},
        "parte_url": "https://sierranevada.es/es/invierno/la-estacion/en-directo/parte-nieve/",
        "parte_texto": "parte de nieve de Sierra Nevada (Cetursa)",
        "aludes_aviso": "AEMET no publica boletín de aludes para Sierra Nevada",
    },
}

# --------------------------------------------------------------------------------------------------------- umbrales
HORA_DIA = (9, 17)                 # horario de día, ambos incluidos
RACHA_NO = 70.0                    # km/h: a partir de aquí, «Mejor otro día»
RACHA_RESERVAS = 40.0              # km/h: de aquí a RACHA_NO, «Con reservas»
RACHA_TRAVESIA = 50.0              # km/h: con nieve nueva, travesía y raquetas pasan a «Con reservas»
SENSACION_RESERVAS = -15.0         # °C: sensación térmica mínima igual o por debajo → «Con reservas»
SENSACION_FAMILIA = -8.0           # °C: familia y trineo exigen sensación mínima por encima de esto
NUBES_BAJAS_PCT = 80.0             # nubosidad baja media (%) a partir de la cual el cielo es «nubes bajas o niebla»
DESPEJADO_PCT = 30.0               # nubosidad total media (%) por debajo de la cual el cielo es «despejado»
PRECIP_HORA_MM = 0.2               # una hora cuenta como «con precipitación» a partir de esto
LLUVIA_MM = 2.0                    # precipitación (mm) con la cota por encima del punto: «llueve en el punto»
COTA_DESCUENTO_M = 300             # cota de nieve = isoterma de 0 °C menos esto (igual que el resto de la herramienta)
NIEVE_CAIDA_7D_CM = 5.0            # ¿hay nieve?: caída en los 7 días anteriores
NIEVE_PREVISTA_CM = 5.0            # ¿hay nieve?: prevista hasta ese día
SAT_MIN_PCT = 0.0                  # ¿hay nieve?: el satélite da superficie nevada si el % del macizo supera esto
NIEVE_NUEVA_MIN_CM = 1.0           # «hay nieve nueva» a efectos de travesía
NIEVE_NUEVA_48H_TRAVESIA_CM = 30.0 # nieve nueva en 48 h que pone «Con reservas» en travesía y raquetas
DURA_NOCHE_C = -2.0                # nieve dura: la noche anterior baja de esto…
DURA_DIA_C = 0.0                   # …tras un día por encima de esto (o tras lluvia)
DURA_NIEVE_ENCIMA_CM = 10.0        # …y sin tantos cm nuevos encima
HORAS_NOCHE = (21, 8)              # noche anterior: de las 21 h del día previo a las 8 h del día
CARRETERA_SUBIDA = (8, 10)         # horas de subida
CARRETERA_BAJADA = (16, 19)        # horas de bajada
COTA_CARRETERA_M = 2100            # el final de la carretera de acceso, en Pradollano
GRADIENTE_C_KM = 6.5               # °C por km para pasar la temperatura del punto a la de la carretera
NORMAL_MIN_CM = 5.0                # solo se compara con lo normal si lo normal a esta fecha es al menos esto
HORIZONTE_DIAS = 7                 # «mejor día de los próximos 7»
HORAS_PASADO = 168                 # una semana hacia atrás para «han caído»
HUECOS_MAX = 2                     # horas sin dato que tolera una ventana de 9 h antes de dejar la variable en None
MAX_HORAS_VIGENTE = 12             # el bloque no se pinta con un cálculo más viejo que esto
WA_MAX_CARACTERES = 350
WA_MAX_LINEAS = 5
MODELOS = ["ecmwf_ifs025", "icon_seamless", "meteofrance_seamless", "gfs_seamless"]
VARIABLES = {"snowfall": "nieve", "precipitation": "precip", "temperature_2m": "temp", "apparent_temperature": "sens",
             "wind_gusts_10m": "racha", "cloud_cover": "nubes", "cloud_cover_low": "bajas",
             "freezing_level_height": "fl", "snow_depth": "esp"}
OM_PREVISION = "https://api.open-meteo.com/v1/forecast"

ESTADOS = ("Buen día", "Con reservas", "Mejor otro día")
PERFILES = (("pista", "Esquí de pista"), ("travesia", "Travesía y raquetas"), ("senderismo", "Senderismo"),
            ("familia", "Familia y trineo"))
SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre",
         "diciembre"]
FRASE_DURA = "Nieve dura probable a primera hora: crampones y piolet, y saber usarlos"
AVISO_ORIENTACION = ("Orientación a partir de modelos meteorológicos. No sustituye al parte de la estación ni a tu criterio "
                     "sobre el terreno.")


# ------------------------------------------------------------------------------------------------------------ formato
def esc(s) -> str:
    return escape(str(s), quote=True)


def ent(x) -> str:
    """1900 → «1.900»."""
    return f"{int(round(x)):,}".replace(",", ".")


def cm(x: float) -> str:
    if x >= 9.5 or abs(x - round(x)) < 0.05:
        return f"{ent(x)} cm"
    return f"{x:.1f}".replace(".", ",") + " cm"


def dsem(d: date) -> str:
    return SEMANA[d.weekday()]


def dia_corto(d: date) -> str:
    return f"{dsem(d)} {d.day}"


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def lista(xs: list) -> str:
    xs = [x for x in xs if x]
    return xs[0] if len(xs) == 1 else (", ".join(xs[:-1]) + " y " + xs[-1] if xs else "")


# ------------------------------------------------------------------------------------------------------- petición
def pedir_horario(pedir, puntos: list) -> list:
    """Una sola petición con los puntos del macizo; devuelve una respuesta por punto. `pedir(url, params)` es `om` de nieve.py."""
    p = {"latitude": ",".join(f"{x['lat']:.3f}" for x in puntos), "longitude": ",".join(f"{x['lon']:.3f}" for x in puntos),
         "elevation": ",".join(str(x["alt"]) for x in puntos), "hourly": ",".join(VARIABLES),
         "models": ",".join(MODELOS), "past_days": 7, "forecast_days": 9, "timezone": "Europe/Madrid"}
    r = pedir(OM_PREVISION, p)
    return [r] if isinstance(r, dict) else list(r)


def serie_mediana(res: dict) -> tuple:
    """De la respuesta multimodelo, la mediana hora a hora de cada variable entre los modelos que la den.
    Devuelve ({'AAAA-MM-DDTHH:00': {clave: valor|None}}, {clave: n.º de modelos que la dan})."""
    hh = res.get("hourly") or {}
    horas = hh.get("time") or []
    cols = {}
    for var, clave in VARIABLES.items():
        cs = [hh[f"{var}_{m}"] for m in MODELOS if f"{var}_{m}" in hh and any(v is not None for v in hh[f"{var}_{m}"])]
        if not cs and var in hh and any(v is not None for v in hh[var]):
            cs = [hh[var]]
        cols[clave] = cs
    out = {}
    for i, t in enumerate(horas):
        rec = {}
        for clave, cs in cols.items():
            vs = [c[i] for c in cs if i < len(c) and c[i] is not None]
            rec[clave] = st.median(vs) if vs else None
        out[t] = rec
    return out, {c: len(cs) for c, cs in cols.items()}


# --------------------------------------------------------------------------------------------------------- cálculo
class Serie:
    def __init__(self, horas: dict, alt: float, ahora: datetime):
        self.h, self.alt, self.ahora = horas, alt, ahora

    @staticmethod
    def clave(d: date, hora: int) -> str:
        return f"{d.isoformat()}T{hora:02d}:00"

    def v(self, d: date, hora: int, var: str):
        return (self.h.get(self.clave(d, hora)) or {}).get(var)

    def ventana(self, d: date, h0: int, h1: int, var: str) -> list:
        return [self.v(d, hh, var) for hh in range(h0, h1 + 1)]

    def rango(self, desde: datetime, hasta: datetime, var: str) -> list:
        out, t = [], desde
        while t <= hasta:
            out.append((t, (self.h.get(t.strftime("%Y-%m-%dT%H:00")) or {}).get(var)))
            t += timedelta(hours=1)
        return out

    def cota(self, d: date, hora: int):
        """Cota de nieve en esa hora si precipita; None si no."""
        p, fl = self.v(d, hora, "precip"), self.v(d, hora, "fl")
        if p is None or fl is None or p < PRECIP_HORA_MM:
            return None
        return max(0, int(round((fl - COTA_DESCUENTO_M) / 100.0)) * 100)


def _completa(vs: list) -> list | None:
    ok = [v for v in vs if v is not None]
    return ok if len(vs) - len(ok) <= HUECOS_MAX and ok else None


def suma_nieve(s: Serie, desde: datetime, hasta: datetime):
    """Suma de nieve (cm) entre dos instantes; None si faltan demasiadas horas."""
    vs = [v for _t, v in s.rango(desde, hasta, "nieve")]
    ok = [v for v in vs if v is not None]
    if not ok or len(vs) - len(ok) > 6:
        return None
    return sum(ok)


def estadisticas_dia(s: Serie, d: date) -> dict:
    h0, h1 = HORA_DIA
    fin = datetime(d.year, d.month, d.day, h1)
    r = {"fecha": d.isoformat()}
    rachas = _completa(s.ventana(d, h0, h1, "racha"))
    r["racha"] = None if rachas is None else int(round(max(rachas)))
    sens = _completa(s.ventana(d, h0, h1, "sens"))
    r["sensacion"] = None if sens is None else int(round(min(sens)))
    temps = _completa(s.ventana(d, h0, h1, "temp"))
    r["_tmax"] = None if temps is None else max(temps)
    # nieve nueva: las 24 h hasta las 17 h (lo que se encuentra al subir)
    n24 = suma_nieve(s, fin - timedelta(hours=23), fin)
    n48 = suma_nieve(s, fin - timedelta(hours=47), fin)
    r["nieve_nueva"] = None if n24 is None else round(n24, 1)
    r["nieve_48h"] = None if n48 is None else round(n48, 1)
    # cota con precipitación y lluvia en el punto
    cotas, mm_lluvia, hay_precip = [], 0.0, True
    pr = s.ventana(d, h0, h1, "precip")
    if _completa(pr) is None:
        hay_precip = False
    for hh in range(h0, h1 + 1):
        c = s.cota(d, hh)
        if c is not None:
            cotas.append(c)
            if c > s.alt:
                mm_lluvia += s.v(d, hh, "precip") or 0.0
    r["cota_min"] = min(cotas) if cotas else None
    r["cota_max"] = max(cotas) if cotas else None
    r["lluvia"] = (mm_lluvia >= LLUVIA_MM) if hay_precip else None
    bajas, total = _completa(s.ventana(d, h0, h1, "bajas")), _completa(s.ventana(d, h0, h1, "nubes"))
    if bajas is None:
        r["cielo"] = None
    elif sum(bajas) / len(bajas) >= NUBES_BAJAS_PCT:
        r["cielo"] = "nubes bajas o niebla"
    elif total is not None and sum(total) / len(total) < DESPEJADO_PCT:
        r["cielo"] = "despejado"
    elif total is not None:
        r["cielo"] = "nubes"
    else:
        r["cielo"] = None
    return r


def nieve_dura(s: Serie, d: date, prev: dict, nieve_nueva) -> bool | None:
    """Noche anterior por debajo de DURA_NOCHE_C tras un día por encima de DURA_DIA_C (o tras lluvia) y sin ≥10 cm encima."""
    ayer = d - timedelta(days=1)
    noche = []
    for hh in range(HORAS_NOCHE[0], 24):
        noche.append(s.v(ayer, hh, "temp"))
    for hh in range(0, HORAS_NOCHE[1] + 1):
        noche.append(s.v(d, hh, "temp"))
    noche = _completa(noche)
    if noche is None or nieve_nueva is None or prev.get("_tmax") is None:
        return None
    dia_calido = prev["_tmax"] > DURA_DIA_C or bool(prev.get("lluvia"))
    return min(noche) < DURA_NOCHE_C and dia_calido and nieve_nueva < DURA_NIEVE_ENCIMA_CM


def carretera_dia(s: Serie, d: date) -> dict:
    """Previsión en la cota de la carretera de acceso: subida (8-10 h) y bajada (16-19 h)."""
    sub = None
    for hh in range(CARRETERA_SUBIDA[0], CARRETERA_SUBIDA[1] + 1):
        c = s.cota(d, hh)
        if c is not None and c <= COTA_CARRETERA_M:
            sub = "Posible nieve en la subida"
            break
    baj = None
    for hh in range(CARRETERA_BAJADA[0], CARRETERA_BAJADA[1] + 1):
        t = s.v(d, hh, "temp")
        if t is not None and t + GRADIENTE_C_KM * (s.alt - COTA_CARRETERA_M) / 1000.0 <= 0:
            baj = f"Posible hielo en la bajada a partir de las {hh} h"
            break
    return {"subida": sub, "bajada": baj}


def veredictos(e: dict, hay_nieve: bool, dura: bool | None, carretera_ok: bool | None, cfg: dict) -> dict:
    """Los cuatro perfiles de un día. Si falta un dato del que depende el veredicto, ese perfil no se emite."""
    if not hay_nieve:
        return {}
    r, sens, lluvia, cielo = e.get("racha"), e.get("sensacion"), e.get("lluvia"), e.get("cielo")
    if r is None or sens is None or lluvia is None or cielo is None:
        return {}
    causas, grave = [], False
    if r >= RACHA_NO:
        causas.append(f"rachas de {r} km/h"); grave = True
    if lluvia:
        causas.append("lluvia a esa altura"); grave = True
    leve = []
    if RACHA_RESERVAS <= r < RACHA_NO:
        leve.append(f"rachas de {r} km/h")
    if sens <= SENSACION_RESERVAS:
        leve.append(f"sensación de {sens} °C")
    if cielo == "nubes bajas o niebla":
        leve.append("nubes bajas o niebla")
    base = ESTADOS[2] if grave else (ESTADOS[1] if leve else ESTADOS[0])
    motivo_base = cap(lista(causas if grave else leve)) if (grave or leve) else \
        f"Rachas de {r} km/h, sin lluvia y sensación mínima de {sens} °C"
    out = {}
    # esquí de pista
    out["pista"] = {"estado": base, "motivo": motivo_base + ". Comprueba qué pistas abren en el parte oficial."}
    # travesía y raquetas
    nn, n48 = e.get("nieve_nueva"), e.get("nieve_48h")
    if base == ESTADOS[2]:
        out["travesia"] = {"estado": base, "motivo": motivo_base + "."}
    elif nn is None or n48 is None:
        out["travesia"] = None
    elif n48 >= NIEVE_NUEVA_48H_TRAVESIA_CM or (nn >= NIEVE_NUEVA_MIN_CM and r >= RACHA_TRAVESIA):
        out["travesia"] = {"estado": ESTADOS[1],
                           "motivo": f"Nieve reciente y viento: precaución fuera de pista. {cfg['aludes_aviso']}."}
    else:
        out["travesia"] = {"estado": base, "motivo": motivo_base + "."}
    # senderismo
    est, mot = base, motivo_base + "."
    if dura is None:
        out["senderismo"] = None
    else:
        if dura and est == ESTADOS[0]:
            est, mot = ESTADOS[1], FRASE_DURA + "."
        elif dura:
            mot += " " + FRASE_DURA + "."
        out["senderismo"] = {"estado": est, "motivo": mot}
    # familia y trineo
    if carretera_ok is None:
        out["familia"] = None
    else:
        est, razones = base, []
        if est == ESTADOS[0] and (r >= RACHA_RESERVAS or sens <= SENSACION_FAMILIA or not carretera_ok):
            est = ESTADOS[1]
        if r >= RACHA_RESERVAS:
            razones.append(f"rachas de {r} km/h")
        if sens <= SENSACION_FAMILIA:
            razones.append(f"sensación de {sens} °C")
        if lluvia:
            razones.append("lluvia a esa altura")
        if not carretera_ok:
            razones.append("carretera con restricciones o con posible nieve")
        if est == ESTADOS[0]:
            mot = f"Rachas de {r} km/h, sensación mínima de {sens} °C, sin lluvia y carretera sin restricciones."
        else:
            mot = cap(lista(razones) or lista(leve)) + "."
        out["familia"] = {"estado": est, "motivo": mot}
    return {k: v for k, v in out.items() if v}


def causa_corta(v: dict) -> str:
    m = v["motivo"].lower()
    c = []
    if "rachas" in m:
        c.append("viento")
    if "lluvia" in m:
        c.append("lluvia")
    if "sensación" in m:
        c.append("frío")
    if "nubes bajas" in m:
        c.append("nubes bajas")
    return lista(c)


def calcular_punto(horas: dict, alt: float, ahora: datetime, hoy: date, sat_pct, cfg: dict, dgt: dict | None) -> dict:
    """Los próximos HORIZONTE_DIAS días de un punto."""
    s = Serie(horas, alt, ahora)
    dias, prev = [], None
    for k in range(-1, HORIZONTE_DIAS):
        d = hoy + timedelta(days=k)
        e = estadisticas_dia(s, d)
        fin = datetime(d.year, d.month, d.day, HORA_DIA[1])
        tope = min(fin, ahora - timedelta(hours=1))
        caida = suma_nieve(s, fin - timedelta(hours=HORAS_PASADO), tope) if tope > fin - timedelta(hours=HORAS_PASADO) else 0.0
        prevista = suma_nieve(s, ahora, fin) if fin > ahora else 0.0
        hay = None
        if sat_pct is not None and sat_pct > SAT_MIN_PCT:
            hay = True
        elif caida is not None and caida >= NIEVE_CAIDA_7D_CM:
            hay = True
        elif prevista is not None and prevista >= NIEVE_PREVISTA_CM:
            hay = True
        elif caida is not None and prevista is not None:
            hay = False
        e["hay_nieve"] = hay
        e["caida_7d"] = None if caida is None else round(caida, 1)
        e["prevista_hasta"] = None if prevista is None else round(prevista, 1)
        e["_prev"] = prev
        if k >= 0:
            dura = nieve_dura(s, d, prev or {}, e["nieve_nueva"]) if prev else None
            e["nieve_dura"] = dura if hay else None
            cr = carretera_dia(s, d)
            e["carretera_prev"] = cr
            restringida = None if dgt is None else bool(dgt["estados"])
            carretera_ok = None if restringida is None else (not restringida and not cr["subida"])
            e["perfiles"] = veredictos(e, bool(hay), dura, carretera_ok, cfg) if hay is not None else {}
            e["incompleto"] = hay is None or (bool(hay) and not e["perfiles"])
            e["finde"] = d.weekday() >= 5
            dias.append(e)
        prev = e
    for e in dias:
        e.pop("_prev", None)
    for e in dias + ([prev] if prev else []):
        e.pop("_tmax", None)
    return {"dias": dias}


def mejor_dia(dias: list) -> dict | None:
    """El de mejor estado para más perfiles; a igualdad, menos viento."""
    cand = []
    for e in dias:
        pf = e.get("perfiles") or {}
        if not pf:
            continue
        nb = sum(1 for v in pf.values() if v["estado"] == ESTADOS[0])
        nr = sum(1 for v in pf.values() if v["estado"] == ESTADOS[1])
        cand.append((nb, nr, -(e.get("racha") or 0), e))
    if not cand:
        return None
    nb, nr, _r, e = max(cand, key=lambda z: z[:3])
    if nb + nr == 0:
        return None
    buenos = [n for k, n in PERFILES if (e["perfiles"].get(k) or {}).get("estado") == ESTADOS[0]]
    motivo = ("buen día para los cuatro perfiles" if len(buenos) == len(PERFILES) else
              "buen día para " + lista([b.lower() for b in buenos])) if buenos else "el que menos reservas tiene"
    return {"fecha": e["fecha"], "motivo": motivo, "perfiles_buen_dia": nb}


# ----------------------------------------------------------------------------------------------------- DGT y normal
def resumen_dgt(puertos: dict | None, macizo: str, ahora_utc: datetime, vigente) -> dict | None:
    """{'hora': 'HH:MM', 'estados': {estado: n}} con los tramos del macizo; None si el dato no es reciente."""
    if not puertos or not vigente(puertos, ahora_utc):
        return None
    try:
        corte = datetime.fromisoformat(puertos["corte"]).astimezone(TZ)
    except (KeyError, ValueError):
        return None
    est = {}
    for t in puertos.get("tramos") or []:
        if t.get("macizo") == macizo:
            est[t["estado"]] = est.get(t["estado"], 0) + 1
    return {"hora": f"{corte:%H:%M}", "estados": est}


def texto_carretera(dgt: dict | None) -> str | None:
    if dgt is None:
        return None
    if not dgt["estados"]:
        return f"Sin restricciones ahora (DGT, {dgt['hora']})"
    nombres = {"cerrado": "carretera cortada", "cadenas": "cadenas obligatorias", "pesados": "restricción a pesados",
               "nieve": "nieve o hielo en la calzada"}
    partes = [f"{nombres[k]} en {n} tramo{'s' if n != 1 else ''}" for k, n in dgt["estados"].items() if k in nombres]
    return f"Ahora (DGT, {dgt['hora']}): {lista(partes)}"


def frente_normal(acum, normal) -> tuple:
    """(porcentaje con signo, frase) o (None, None) si lo normal a esta fecha es menos de NORMAL_MIN_CM."""
    if acum is None or normal is None or normal < NORMAL_MIN_CM:
        return None, None
    pct = int(round(100.0 * (acum / normal - 1)))
    if abs(pct) < 5:
        t = f"lo normal a esta fecha ({cm(normal)})"
    elif pct < 0:
        t = f"un {abs(pct)} % menos de lo normal a esta fecha ({cm(normal)})"
    else:
        t = f"un {pct} % más de lo normal a esta fecha ({cm(normal)})"
    return pct, f"Esta temporada han caído {cm(acum)} de nieve: {t}"


# --------------------------------------------------------------------------------------------------------- textos
def dias_finde(dias: list, hoy: date) -> list:
    """El próximo sábado y domingo (si hoy es sábado o domingo, cuenta hoy). Si hoy es domingo, solo hoy."""
    wd = hoy.weekday()
    sab = hoy if wd == 5 else hoy + timedelta(days=(5 - wd) % 7) if wd != 6 else None
    fs = [sab, sab + timedelta(days=1)] if sab else [hoy]
    por = {e["fecha"]: e for e in dias}
    return [por[f.isoformat()] for f in fs if f.isoformat() in por]


def etiqueta_finde(fs: list) -> str:
    ds = [date.fromisoformat(e["fecha"]) for e in fs]
    if len(ds) == 1:
        return f"el domingo {ds[0].day}" if ds[0].weekday() == 6 else f"el {dia_corto(ds[0])}"
    a, b = ds
    if a.month == b.month:
        return f"finde del {a.day} y {b.day}"
    return f"finde del {a.day} de {MESES[a.month - 1]} y {b.day} de {MESES[b.month - 1]}"


def frase_veredicto(fs: list, hay: bool) -> str:
    if not fs:
        return "No hay datos suficientes de los modelos para valorar el fin de semana."
    if not hay:
        return "Sin nieve para subir este fin de semana, según los modelos y el satélite."
    partes = []
    for e in fs:
        d = date.fromisoformat(e["fecha"])
        p = (e.get("perfiles") or {}).get("pista")
        if not p:
            partes.append(f"{cap(dsem(d))}: sin datos suficientes para valorarlo.")
            continue
        c = causa_corta(p)
        partes.append(f"{cap(dsem(d))}: {p['estado'].lower()} en pista" + (f" por {c}" if c and p["estado"] != ESTADOS[0] else "") + ".")
    return " ".join(partes)


def proxima_txt(proxima: dict | None, hoy: date) -> str:
    if not proxima:
        return "ninguna en 15 días"
    d = date.fromisoformat(proxima["fecha"])
    t = f"{dia_corto(d)}"
    if proxima.get("cota") is not None:
        t += f", cota {ent(proxima['cota'])} m"
    return t


def texto_whatsapp(mac: dict, cfg: dict, hoy: date) -> str:
    url = mac["url_compartir"]
    nombre = cfg["corto"]
    fs = mac["_fs"]
    if not fs:
        return ""
    if not mac["hay_nieve"]:
        l1 = f"{nombre}, {etiqueta_finde(fs)}: sin nieve para subir."
        l2 = f"Próxima nevada prevista: {proxima_txt(mac.get('_proxima'), hoy)}."
        return "\n".join([l1, l2, url])
    por = {e["fecha"]: e for e in mac["dias"]}
    md = mac.get("mejor_dia")
    e = por.get(md["fecha"]) if md else next((x for x in fs if x.get("perfiles")), None)
    if e is None:
        return ""
    d = date.fromisoformat(e["fecha"])
    nn = e.get("nieve_nueva")
    partes = []
    if nn is not None:
        partes.append(f"{cm(nn)} nuevos" if nn >= NIEVE_NUEVA_MIN_CM else "sin nieve nueva")
    cielo = {"despejado": "sol", "nubes": "nubes", "nubes bajas o niebla": "nubes bajas"}.get(e.get("cielo"))
    if cielo:
        partes.append(cielo)
    if e.get("racha") is not None:
        partes.append(f"rachas de {e['racha']} km/h")
    l1 = f"❄️ {nombre}, {dia_corto(d)}: " + (lista(partes) if partes else "mejor día de la semana") + "."
    extra = []
    if md:
        extra.append(f"Mejor día: {dsem(date.fromisoformat(md['fecha']))}.")
    else:
        extra.append("Ningún día de la semana sale bien.")
    ct = mac["carretera"].get("ahora")
    if ct and ct.startswith("Sin restricciones"):
        extra.append("Carretera sin restricciones ahora.")
    elif ct:
        extra.append("Carretera con restricciones ahora.")
    ojo = "Ojo: nieve dura a primera hora." if e.get("nieve_dura") else ""
    for variante in ([l1, " ".join(extra), ojo, url], [l1, " ".join(extra), url], [l1, extra[0], url], [l1, url]):
        lineas = [x for x in variante if x]
        t = "\n".join(lineas)
        if len(t) <= WA_MAX_CARACTERES and len(lineas) <= WA_MAX_LINEAS:
            return t
    return ""


# --------------------------------------------------------------------------------------------------- macizo entero
def calcular_macizo(clave: str, puntos: list, series: dict, ctx: dict) -> dict:
    """Calcula finde.json para un macizo. `series` = {id_del_punto: (horas, n_modelos)}; ctx trae ahora, hoy, sat_pct, dgt,
    temporada del punto principal ({'acum','normal'}) y la próxima nevada ({'fecha','cota'})."""
    cfg = MACIZOS_ACTIVOS[clave]
    ahora, hoy = ctx["ahora"], ctx["hoy"]
    out_puntos, notas = {}, []
    for p in puntos:
        if p["id"] not in series:
            continue
        horas, nmod = series[p["id"]]
        r = calcular_punto(horas, p["alt"], ahora, hoy, ctx.get("sat_pct"), cfg, ctx.get("dgt"))
        r.update({"nombre": cfg["rotulos"].get(p["id"], p["nombre"]), "alt": p["alt"]})
        out_puntos[p["id"]] = r
        for c, n in nmod.items():
            if n < len(MODELOS):
                notas.append(f"{p['id']}: «{c}» con la mediana de {n} de {len(MODELOS)} modelos")
    if cfg["principal"] not in out_puntos:
        return {}
    pr = out_puntos[cfg["principal"]]
    dias = pr["dias"]
    fs = dias_finde(dias, hoy)
    hay = any(e.get("hay_nieve") for e in dias)
    hay_finde = any(e.get("hay_nieve") for e in fs)
    mac = {"nombre": cfg["corto"], "slug": cfg["slug"], "url": f"{WEB}/nieve/{cfg['slug']}/",
           "punto": {"id": cfg["principal"], "nombre": pr["nombre"], "alt": pr["alt"]},
           "hay_nieve": hay_finde, "hay_nieve_semana": hay, "finde": [e["fecha"] for e in fs],
           "mejor_dia": mejor_dia([e for e in dias if e.get("hay_nieve")]), "dias": dias}
    dgt = ctx.get("dgt")
    mac["carretera"] = {"ahora": texto_carretera(dgt), "hora": None if dgt is None else dgt["hora"],
                        "fuente": "DGT" if dgt else None}
    pct, frase = frente_normal(ctx.get("acum"), ctx.get("normal"))
    mac["normal_pct"], mac["normal_txt"] = pct, frase
    mac["frase"] = frase_veredicto(fs, hay_finde)
    mac["etiqueta_finde"] = etiqueta_finde(fs) if fs else ""
    mac["url_compartir"] = f"{WEB}/nieve/{cfg['slug']}/?d={hoy:%Y%m%d}"
    mac["parte_oficial"] = cfg["parte_url"]
    mac["_fs"], mac["_proxima"] = fs, ctx.get("proxima")
    mac["texto_wa"] = texto_whatsapp(mac, cfg, hoy)
    mac["proxima_nevada"] = ctx.get("proxima")
    mac["puntos"] = {k: {"nombre": v["nombre"], "alt": v["alt"], "dias": v["dias"]} for k, v in out_puntos.items()}
    mac["notas"] = notas
    mac["generado"] = ctx["generado"]
    mac["og"] = {"url": f"{PAGES}/nieve/og/{cfg['slug']}.png", "v": "".join(c for c in ctx["generado"] if c.isdigit())[:12],
                 "ancho": 1200, "alto": 630}
    mac.pop("_fs"), mac.pop("_proxima")
    return mac


# -------------------------------------------------------------------------------------------------------- el bloque
def _chip(estado: str) -> str:
    cls = {"Buen día": "bueno", "Con reservas": "reservas", "Mejor otro día": "malo"}[estado]
    return f'<span class="cgnv-fd-chip cgnv-fd-{cls}">{esc(estado)}</span>'


def _datos_dia(e: dict) -> str:
    p = []
    if e.get("nieve_nueva") is not None:
        p.append(f"<b>{esc(cm(e['nieve_nueva']))}</b> de nieve nueva" if e["nieve_nueva"] >= NIEVE_NUEVA_MIN_CM
                 else "sin nieve nueva")
    if e.get("cota_min") is not None:
        c = f"cota de nieve {ent(e['cota_min'])} m" if e["cota_min"] == e["cota_max"] else \
            f"cota de nieve de {ent(e['cota_min'])} a {ent(e['cota_max'])} m"
        p.append(c)
    if e.get("racha") is not None:
        p.append(f"rachas de {e['racha']} km/h")
    if e.get("sensacion") is not None:
        p.append(f"sensación mínima de {e['sensacion']} °C")
    if e.get("cielo"):
        p.append(e["cielo"])
    return esc_keep_b("; ".join(p) + ("." if p else ""))


def esc_keep_b(s: str) -> str:
    return esc(s).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


def bloque_html(mac: dict | None, cfg: dict, ahora_utc: datetime) -> str:
    """El bloque del día para la página del macizo. Vacío si no hay cálculo reciente."""
    if not mac or not mac.get("dias"):
        return ""
    try:
        gen = datetime.fromisoformat(mac["generado"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return ""
    if ahora_utc - gen > timedelta(hours=MAX_HORAS_VIGENTE):
        return ""
    corto, slug = cfg["corto"], cfg["slug"]
    por = {e["fecha"]: e for e in mac["dias"]}
    fs = [por[f] for f in mac["finde"] if f in por]
    o = ['<div class="cgnv-fd">', f'<h2 class="cgnv-panel-h2">¿Subo este fin de semana a {esc(corto)}?</h2>',
         f'<p class="cgnv-fd-v">{esc(mac["frase"])}</p>']
    if fs:
        o.append('<div class="cgnv-fd-cards">')
        for e in fs:
            d = date.fromisoformat(e["fecha"])
            o.append(f'<div class="cgnv-fd-card"><h3>{esc(cap(dsem(d)))} {d.day}</h3>')
            if e.get("hay_nieve"):
                o.append(f'<p>{_datos_dia(e)}</p>')
                pf = e.get("perfiles") or {}
                if pf:
                    o.append('<ul class="cgnv-fd-perf">')
                    for k, nombre in PERFILES:
                        v = pf.get(k)
                        if v:
                            o.append(f'<li>{_chip(v["estado"])} <b>{esc(nombre)}.</b> {esc(v["motivo"])}</li>')
                    o.append("</ul>")
                else:
                    o.append("<p>Faltan datos de los modelos para dar un veredicto de este día.</p>")
            elif e.get("hay_nieve") is False:
                o.append(f'<p>Sin nieve para subir: ni el satélite la ve ni se prevé nieve nueva. {_datos_dia(e)}</p>')
            else:
                o.append("<p>Faltan datos de los modelos para valorar este día.</p>")
            o.append("</div>")
        o.append("</div>")
    lin = []
    cr = mac["carretera"].get("ahora")
    prevs = [(date.fromisoformat(e["fecha"]), e.get("carretera_prev") or {}) for e in fs if e.get("hay_nieve")]
    pv = [f"{dsem(d)}: {lista([x for x in (c.get('subida'), c.get('bajada')) if x]).lower()}" for d, c in prevs
          if c.get("subida") or c.get("bajada")]
    if cr or pv:
        t = cr or ""
        if pv:
            t += (". " if t else "") + "Previsión en la carretera de acceso, " + "; ".join(pv)
        lin.append(f"<li><b>Carretera.</b> {esc(t)}. Lleva siempre cadenas en la subida en invierno.</li>")
    duras = [cap(dsem(date.fromisoformat(e["fecha"]))) for e in fs if e.get("nieve_dura")]
    if duras:
        lin.append(f"<li><b>Nieve dura ({esc(lista(duras).lower())}).</b> {esc(FRASE_DURA)}.</li>")
    if mac.get("normal_txt"):
        lin.append(f"<li><b>Frente a lo normal.</b> {esc(mac['normal_txt'])}.</li>")
    if lin:
        o.append('<ul class="cgnv-fd-l">' + "".join(lin) + "</ul>")
    md = mac.get("mejor_dia")
    if md:
        d = date.fromisoformat(md["fecha"])
        o.append(f'<p class="cgnv-fd-m"><b>Mejor día de los próximos 7:</b> {esc(dsem(d))} {d.day} ({esc(md["motivo"])}).</p>')
    elif mac.get("hay_nieve_semana"):
        o.append('<p class="cgnv-fd-m"><b>Mejor día de los próximos 7:</b> ninguno sale bien según los modelos.</p>')
    else:
        pn = mac.get("proxima_nevada")
        o.append('<p class="cgnv-fd-m"><b>Próxima nevada prevista:</b> ' + esc(proxima_txt(pn, date.today())) + ".</p>")
    if mac.get("texto_wa"):
        o.append(f'<p><a class="cgnv-fd-btn" rel="nofollow" href="/nieve/{esc(slug)}/?cgnv_wa=1">Enviar al grupo por WhatsApp</a></p>')
    o.append(f'<p class="cgnv-pie">{esc(AVISO_ORIENTACION)} <a href="{esc(cfg["parte_url"])}">Consulta el {esc(cfg["parte_texto"])}</a>.</p>')
    o.append("</div>")
    return "".join(o)


CSS_BLOQUE = """
.cgnv-panel-mac{grid-template-areas:"intro hoy" "fd fd" "pt pt" "cifras cifras" "prev prev" "graf graf";grid-template-rows:repeat(6,auto)}
.cg-ssr-slot .cgnv-fd{visibility:visible;font-size:17px;line-height:1.55}
.cgnv-fd{grid-area:fd;margin-top:26px;background:var(--p-hondo);border-radius:22px;padding:24px 26px 18px;color:var(--p-sub)}
.cgnv .cgnv-fd .cgnv-panel-h2{font-size:26px;line-height:1.2;color:#fff;font-weight:720;margin:0 0 8px}
.cgnv .cgnv-fd-v{font-size:19px;line-height:1.45;color:var(--p-cristal);font-weight:600;margin:0 0 16px;max-width:none}
.cgnv-fd-cards{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:0 0 14px}
.cgnv-fd-card{background:var(--p-cel);border-radius:18px;padding:16px 18px}
.cgnv .cgnv-fd-card h3{font-size:20px;color:#fff;margin:0 0 6px}
.cgnv .cgnv-fd-card p,.cgnv .cgnv-fd-l li{font-size:15.5px;line-height:1.5;color:var(--p-sub);max-width:none}
.cgnv-fd-card p b,.cgnv-fd-l b,.cgnv-fd-perf b,.cgnv-fd-m b{color:#fff}
.cgnv-fd-perf,.cgnv-fd-l{list-style:none;margin:8px 0 0;padding:0}
.cgnv-fd-perf li{padding:8px 0;border-top:1px solid rgba(191,230,255,.12);font-size:14.5px;line-height:1.45;color:var(--p-sub)}
.cgnv-fd-l li{padding:7px 0;border-top:1px solid rgba(191,230,255,.12)}
.cgnv-fd-chip{display:inline-block;font-size:13.5px;font-weight:700;padding:2px 10px;border-radius:999px;margin-right:6px;white-space:nowrap}
.cgnv-fd-bueno{background:#4caf50;color:#06210a}.cgnv-fd-reservas{background:#ffe14d;color:#2a2200}.cgnv-fd-malo{background:#d62828;color:#fff}
.cgnv .cgnv-fd-m{font-size:16.5px;margin:12px 0 10px;max-width:none}
.cgnv a.cgnv-fd-btn{display:inline-block;background:#25d366;color:#06210a;font-weight:700;text-decoration:none;padding:10px 20px;border-radius:999px}
.cgnv a.cgnv-fd-btn:hover{background:#4be386;color:#06210a}
.cgnv .cgnv-fd .cgnv-pie{font-size:13.5px;line-height:1.5;color:var(--p-mut);margin:12px 0 0;max-width:none}
@media(max-width:860px){.cgnv-panel-mac{grid-template-areas:"intro" "hoy" "fd" "pt" "cifras" "prev" "graf";grid-template-rows:repeat(7,auto)}
.cgnv-fd{padding:18px 16px 14px}.cgnv-fd-cards{grid-template-columns:1fr}}
"""


# ------------------------------------------------------------------------------------------------------- la imagen
FUENTES = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
           "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
FUENTES_B = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
MIN_TIPO_PX = 28


def _fuente(ImageFont, rutas: list, px: int):
    for r in rutas:
        if Path(r).exists():
            return ImageFont.truetype(r, px)
    return ImageFont.load_default(size=px)


def _envolver(draw, texto: str, fuente, ancho: int) -> list:
    lineas, act = [], ""
    for pal in texto.split():
        prueba = (act + " " + pal).strip()
        if draw.textlength(prueba, font=fuente) <= ancho:
            act = prueba
        else:
            lineas.append(act)
            act = pal
    return lineas + ([act] if act else [])


def imagen_og(mac: dict, cfg: dict, hoy: date) -> bytes | None:
    """PNG de 1200×630 (< 300 KB) con el veredicto del fin de semana. None si Pillow no está."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
    except ImportError:
        return None
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), "#0c2133")
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((24, 24, W - 24, H - 24), radius=26, fill="#132f45")
    f_t, f_n, f_c = (_fuente(ImageFont, FUENTES_B, 66), _fuente(ImageFont, FUENTES, MIN_TIPO_PX),
                     _fuente(ImageFont, FUENTES_B, 34))
    f_b = _fuente(ImageFont, FUENTES_B, MIN_TIPO_PX)
    x0, y = 60, 48
    d.text((x0, y), mac["nombre"], font=f_t, fill="#ffffff")
    d.text((W - 60, y + 30), f"{dsem(hoy)} {hoy.day} de {MESES[hoy.month - 1]}", font=f_n, fill="#8fa9bd", anchor="ra")
    y += 96
    for ln in _envolver(d, mac["frase"], f_c, W - 2 * x0)[:3]:
        d.text((x0, y), ln, font=f_c, fill="#bfe6ff")
        y += 44
    por = {e["fecha"]: e for e in mac["dias"]}
    fs = [por[f] for f in mac["finde"] if f in por][:2]
    y = max(y + 14, 300)
    ancho_c = (W - 2 * x0 - 24) // 2
    for i, e in enumerate(fs):
        x = x0 + i * (ancho_c + 24)
        d.rounded_rectangle((x, y, x + ancho_c, y + 190), radius=18, fill="#0a1b2a")
        dd = date.fromisoformat(e["fecha"])
        d.text((x + 20, y + 14), f"{cap(dsem(dd))} {dd.day}", font=f_c, fill="#ffffff")
        if e.get("hay_nieve") and e.get("nieve_nueva") is not None:
            l1 = f"{cm(e['nieve_nueva'])} nuevos" if e["nieve_nueva"] >= NIEVE_NUEVA_MIN_CM else "Sin nieve nueva"
            l2 = " · ".join(x for x in ((f"racha {e['racha']} km/h" if e.get("racha") is not None else ""),
                                        e.get("cielo") or "") if x)
        else:
            l1, l2 = "Sin nieve", ""
        d.text((x + 20, y + 70), l1, font=f_b, fill="#e8f1f8")
        for k, ln in enumerate(_envolver(d, l2, f_n, ancho_c - 40)[:2]):
            d.text((x + 20, y + 112 + 34 * k), ln, font=f_n, fill="#b9cddc")
    if mac.get("normal_txt"):
        t = "Temporada: " + mac["normal_txt"].split(": ", 1)[-1]
        for ln in _envolver(d, t, f_n, W - 2 * x0)[:1]:
            d.text((x0, y + 206), ln, font=f_n, fill="#ffd2bf")
    d.text((x0, H - 76), "calentamientoglobal.es/nieve", font=f_b, fill="#ff7a45")
    q = im.quantize(colors=48, method=Image.Quantize.MEDIANCUT)
    buf = io.BytesIO()
    q.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def leer_json(p: Path, defecto=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto
