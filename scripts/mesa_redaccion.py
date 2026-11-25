#!/usr/bin/env python3
"""
Mesa de redacción · calentamientoglobal.es (25-11-2026, chat 1: criterio, agrupación, escala y marcos grandes).

Capa entre los detectores (hallazgos_prensa.py, detector_almacen.py, scripts/sala/*) y la página /prensa/:
  1. agrupar()        funde en una historia nacional lo que es el mismo fenómeno, periodo y fecha en varios territorios;
                      las versiones provinciales siguen existiendo, pero no compiten con la nacional.
  2. puntuar()        una sola escala 0-100 para todas las fuentes (alcance, rareza, novedad, frescura, calidad) y los cinco
                      criterios de noticia como puertas.
  3. marcos_grandes() lo que va de año, de estación, de año hidrológico y de mes en las series largas de AEMET, por capital y
                      agregado a España (saca H1). Se emite al cerrar un mes o cuando cambia el número de capitales en primer puesto.
  4. plantillas       titular y entradilla por tipo de historia, sin adjetivos; incluye el día sin noticia.
  5. portada()        historia del día (o «sin noticia»), hasta cuatro más, «Datos del día» y «Contexto».

No escribe nada en docs/ por sí mismo: el chat 2 lo engancha al workflow y escribe docs/prensa/portada.json.
Solo lee ficheros del repositorio público (archivo/aemet_diario, docs/prensa/referencias/maestro.json.gz). Sin APIs.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# ============================================================================ escala única (documentada en el informe, §3)
PESOS = {"alcance": 0.30, "rareza": 0.35, "novedad": 0.15, "frescura": 0.10, "calidad": 0.10}
POB_ESPANA = 49_128_297          # suma del padrón por provincia del maestro del almacén
ANIOS_SERIE_LARGA = 40           # serie oficial que «aguanta»
PESO_FUENTE = {                  # cuánto vale un puesto según de dónde sale
    "estacion": 1.0,             # estación de AEMET con ≥ 40 años
    "nacional": 1.0,             # serie nacional oficial (MITECO, Copernicus para el planeta, AEMET España)
    "atribucion": 0.8,           # periodo de retorno de hoy (método de dos climas): rareza real, pero es análisis
    "reanalisis": 0.7,           # ERA5 / ERA5-Land: solo puestos y tendencias, dicho en el titular
    "corta": 0.45,               # estación con < 40 años (Pego, 15 otoños; San Javier desde 1987)
    "sin_serie": 0.3,            # avisos, previsiones, recuentos sin serie
}
CALIDAD_Q = {"validado": 1.0, "oficial": 0.9, "tiempo_real": 0.75, "reanalisis": 0.6, "modelo": 0.3, "revision": 0.0}
UMBRAL_DIA = 55                  # historia del día: cumple las cinco y puntúa ≥ 55
UMBRAL_MAS = 45                  # las otras cuatro: rareza + se sostiene + algo nuevo, y ≥ 45
VIDA_DIAS = 7                    # «se sostiene»: dato de hace como mucho siete días
VIDA_VALIDADO = 10               # … salvo marcos de periodo con dato validado de AEMET, que llega con 8-9 días (decisión pendiente de David)


def _acot(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def alcance(pob: float | None, n_lugares: int = 1, ambito: str = "provincial") -> float:
    """0-1. Tres cuartos por población afectada (100.000 → 0; España → 1, escala logarítmica), un cuarto por número de lugares
    (1 → 0; 32 o más → 1). Lo global, que no se mide en habitantes de España, vale 0,5."""
    if ambito == "global":
        return 0.5
    pob = pob or 0
    a_pob = _acot(math.log10(max(pob, 1e5) / 1e5) / math.log10(POB_ESPANA / 1e5))
    a_n = _acot(math.log2(max(n_lugares, 1)) / 5)
    return round(0.75 * a_pob + 0.25 * a_n, 3)


def periodo_retorno(puesto: int | None, n_anios: int | None, T: float | None = None) -> float | None:
    """Periodo de retorno empírico en años: puesto k de n → (n+1)/k. Si el hallazgo trae su propio T, manda ese."""
    if T:
        return float(T)
    if puesto and n_anios:
        return (n_anios + 1) / puesto
    return None


def rareza(fuente: str, puesto=None, n_anios=None, T=None) -> float:
    """0-1. log10(T)/2 (T = 100 años → 1), por el peso de la fuente."""
    t = periodo_retorno(puesto, n_anios, T)
    if not t:
        return round(0.25 * PESO_FUENTE.get(fuente, 0.3), 3)
    return round(PESO_FUENTE.get(fuente, 0.3) * _acot(math.log10(max(t, 1)) / 2), 3)


def frescura(edad_disponible: int) -> float:
    """1 hasta 2 días desde que el dato está disponible; 0 a los 9."""
    return round(_acot(1 - max(0, edad_disponible - 2) / 7), 3)


def puntuar(r: dict) -> dict:
    """r: rasgos de una historia (ver rasgos()). Devuelve puntos 0-100, componentes y las cinco puertas."""
    A = alcance(r.get("pob"), r.get("n_lugares", 1), r.get("ambito", "provincial"))
    R = rareza(r.get("fuente", "sin_serie"), r.get("puesto"), r.get("n_anios"), r.get("T"))
    N = r.get("novedad", 1.0)
    F = frescura(r.get("edad_disponible", r.get("edad", 0)))
    Q = CALIDAD_Q.get(r.get("calidad", "tiempo_real"), 0.6)
    puntos = 100 * (PESOS["alcance"] * A + PESOS["rareza"] * R + PESOS["novedad"] * N + PESOS["frescura"] * F + PESOS["calidad"] * Q)
    larga = (r.get("n_anios") or 0) >= ANIOS_SERIE_LARGA or r.get("fuente") == "nacional"
    puertas = {
        # un territorio que justifica un medio regional (una capital o una provincia, ≥ 100.000 habitantes) o nacional
        "alcance": A >= 0.15 or r.get("ambito") in ("nacional", "global") or (r.get("pob") or 0) >= 100_000,
        "rareza": bool(r.get("emergencia")) or (larga and r.get("fuente") in ("estacion", "nacional", "reanalisis")
                                                 and (r.get("puesto") or 99) <= 3),
        "por_que_hoy": N > 0,
        "una_frase": bool(r.get("plantilla")),
        # dato de ≤ 7 días; un periodo validado por AEMET (que llega con 8-9 días de retraso) se admite hasta 10 días
        "se_sostiene": (r.get("edad", 99) <= (VIDA_VALIDADO if r.get("periodo_validado") else VIDA_DIAS)) and Q >= 0.6 and bool(r.get("invalidar")),
    }
    if r.get("fuente") == "reanalisis" and "reanálisis" not in (r.get("titular") or "").lower():
        puertas["se_sostiene"] = False     # reanálisis sin decirlo en el titular: no sale
    return {"puntos": round(puntos, 1), "A": A, "R": R, "N": N, "F": F, "Q": Q, "puertas": puertas,
            "medio": "nacional" if (A >= 0.5 or r.get("ambito") in ("nacional", "global")) else "regional",
            "portada": all(puertas.values()) and puntos >= UMBRAL_DIA and (r.get("ambito") != "provincial" or (r.get("puesto") or 99) == 1),
            "mas": puertas["rareza"] and puertas["se_sostiene"] and puertas["por_que_hoy"] and puntos >= UMBRAL_MAS}


# ============================================================================ maestro (población, nombres)
_M = None


def maestro(raiz: Path = RAIZ) -> dict:
    global _M
    if _M is None:
        try:
            with gzip.open(raiz / "docs" / "prensa" / "referencias" / "maestro.json.gz", "rt", encoding="utf-8") as f:
                _M = json.load(f)
        except Exception:
            _M = {"nombres": {}, "pob_cap": {}, "pob_prov": {}, "cap_prov": {}, "est_prov": {}}
        _M["_prov_por_nombre"] = {_norm(v): k for k, v in _M["nombres"].items() if k.startswith("prov:")}
        _M["_cap_por_nombre"] = {_norm(v): k for k, v in _M["nombres"].items() if k.startswith("cap:")}
    return _M


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s.split("/")[0])


_ALIAS = {"laspalmas": "laspalmasdegrancanaria", "alicante": "alacant", "castellon": "castellodelaplana", "vitoria": "vitoriagasteiz",
          "sansebastian": "donostia", "pamplona": "pamplona", "palma": "palma"}


def poblacion(territorio: str, ambito: str = "provincial") -> int | None:
    """Habitantes de la capital (si el territorio es una capital o su estación) o de la provincia. «Estación (Provincia)» → la provincia."""
    M = maestro()
    m = re.search(r"\(([^)]+)\)\s*$", territorio or "")
    if m:
        p = M["_prov_por_nombre"].get(_norm(m.group(1)))
        if p:
            return M["pob_prov"].get(p)
    n = _norm(territorio)
    for k, v in M["nombres"].items():
        if k.startswith("cap:") and (_norm(v) == n or _norm(v).startswith(n) or _norm(v).startswith(_ALIAS.get(n, "#"))):
            return M["pob_cap"].get(k)
    p = M["_prov_por_nombre"].get(n)
    return M["pob_prov"].get(p) if p else None


# ============================================================================ rasgos de un hallazgo de hallazgos.json
RUTINA = {"lluvia_dia", "lluvia_en_curso", "lluvia_semana", "aviso", "embalses", "prevision", "caudal", "percentil_extremo", "anomalia_fuerte"}
CONTEXTO = {"antes_raro", "temporada", "compuesto", "contexto", "tendencia"}


def rasgos(h: dict, hoy: date) -> dict:
    """Traduce un hallazgo (contrato de hallazgos_prensa.py, incluido el del almacén) a los rasgos de la escala única."""
    fd = date.fromisoformat(h["fecha_dato"][:10])
    edad = (hoy - fd).days
    comp = h.get("comparacion") or {}
    cal_txt = (h.get("calidad") or "").lower()
    fuente_txt = (h.get("fuente") or "") + " " + (h.get("metodo") or "")
    if h.get("requiere_revision"):
        calidad = "revision"
    elif "reanálisis" in cal_txt or str(h.get("variante", "")).startswith("capital_era5") or h.get("tipo_fuente") == "era5":
        calidad = "reanalisis"
    elif h.get("provisional"):
        calidad = "tiempo_real"
    elif cal_txt == "validado" or h.get("aemet") or h.get("tipo_fuente") == "aemet" or "AEMET" in fuente_txt:
        calidad = "validado"
    else:
        calidad = "oficial"
    puesto, n = comp.get("puesto"), comp.get("de")
    T = None
    fuente = "sin_serie"
    if h.get("tipo") == "antes_raro" and h.get("rareza"):
        fuente, T = "atribucion", h["rareza"].get("T_ahora")
    elif puesto and n:
        fuente = "reanalisis" if calidad == "reanalisis" else ("estacion" if n >= ANIOS_SERIE_LARGA else "corta")
    elif h.get("serie") == "capitales" and h.get("tipo") in ("record_fecha", "record_absoluto"):
        puesto, n = 1, hoy.year - int(h.get("serie_desde") or 1940)
        fuente = "estacion" if h.get("aemet") else "reanalisis"
        if h.get("tipo") == "record_fecha":
            # récord para el día del año sin margen: en una serie de n años sale ~365/n veces al año por estación
            # (la calibración del almacén lo cifra en ~220 al año en la red): su periodo de retorno real es n/365 años
            T = max(1.0, n / 365)
            puesto = 4       # no es «primer puesto» en el sentido del criterio 2: no abre la página por sí solo
    elif h.get("serie") in ("embalses", "temperatura_global", "mediterraneo"):
        fuente = "nacional"
    ambito = h.get("ambito", "provincial")
    miembros = h.get("miembros") or []
    if ambito == "nacional":
        pob = sum(poblacion(m) or 0 for m in (h.get("_miembros_territorios") or [])) or (POB_ESPANA if not miembros else None)
        if not pob:
            pob = 300_000 * max(1, len(miembros))      # sin nombres: media de una capital por miembro
    else:
        pob = poblacion(h.get("territorio", ""), ambito)
    tipo = h.get("tipo")
    seccion = "contexto" if tipo in CONTEXTO or h.get("citabilidad") == "contexto" else ("datos" if tipo in RUTINA else "noticia")
    return {"pob": pob, "n_lugares": max(1, len(miembros)), "ambito": ambito, "fuente": fuente, "puesto": puesto, "n_anios": n, "T": T,
            "edad": edad, "edad_disponible": edad, "calidad": calidad, "novedad": 1.0, "invalidar": h.get("invalidar") or h.get("limites"),
            "plantilla": True, "titular": h.get("titular", ""), "seccion": seccion}


# ============================================================================ agrupación
def fenomeno(h: dict) -> tuple:
    """Mismo fenómeno y periodo: lo que cambia entre dos hallazgos que son la misma historia es solo el territorio."""
    ind = h.get("indicador", "")
    if h.get("clave"):
        return ("clave", h.get("variante") or (h["clave"] or {}).get("indicador"), (h["clave"] or {}).get("periodo"))
    if h.get("serie") == "huella" and h.get("tipo") == "antes_raro":
        mensual = ind.startswith("mes_")
        return ("huella", ind, h["fecha_dato"][:7] if mensual else h["fecha_dato"][:10], h.get("cierre_mes"))
    if h.get("serie") in ("capitales", "estaciones"):
        return (h["serie"], h.get("tipo"), ind, h["fecha_dato"][:10])
    return (h.get("serie"), h.get("tipo"), ind)


def agrupar(hallazgos: list[dict], min_lugares: int = 3, ventana_dias: int = 3) -> list[dict]:
    """Funde los provinciales del mismo fenómeno y periodo (fechas a ≤ ventana_dias) en una historia nacional con:
    titular nacional («En N capitales…»), alcance (lugares y población), la lista como detalle y las versiones provinciales.
    Los agregados que ya traía la sala (ámbito nacional con `miembros`) se respetan y se les cuelgan sus miembros.
    Devuelve la lista de historias: nacionales y provinciales que no se han fundido; las fundidas van dentro de su nacional."""
    por_id = {h.get("id"): h for h in hallazgos if h.get("id")}
    ya_en = set()
    salida = []
    for h in hallazgos:   # agregados previos (sala y almacén)
        if h.get("ambito") == "nacional" and h.get("miembros"):
            vers = [por_id[m] for m in h["miembros"] if m in por_id]
            ya_en.update(m for m in h["miembros"])
            x = dict(h)
            x["versiones_provinciales"] = vers
            x["_miembros_territorios"] = [v.get("territorio") for v in vers] or _territorios_de_titular(h)
            salida.append(x)
    grupos = defaultdict(list)
    for h in hallazgos:
        if h.get("id") in ya_en or (h.get("ambito") == "nacional" and h.get("miembros")):
            continue
        if h.get("ambito") in ("provincial", "local", "regional"):
            grupos[fenomeno(h)].append(h)
        else:
            salida.append(dict(h))
    for clave, lista in grupos.items():
        lista.sort(key=lambda h: h["fecha_dato"])
        bloque = []
        for h in lista + [None]:
            if h is not None and (not bloque or (date.fromisoformat(h["fecha_dato"][:10]) - date.fromisoformat(bloque[0]["fecha_dato"][:10])).days <= ventana_dias):
                bloque.append(h)
                continue
            terr = {b.get("territorio") for b in bloque}
            if len(terr) >= min_lugares:
                salida.append(historia_agregada(bloque))
            else:
                salida.extend(dict(b) for b in bloque)
            bloque = [h] if h is not None else []
    return salida


def _territorios_de_titular(h):
    m = re.search(r"\(también ([^)]+)\)", h.get("titular", ""))
    primero = re.sub(r"^\d+ lugares a la vez — ", "", h.get("titular", "")).split(":")[0]
    return [primero] + ([t.strip(" …") for t in m.group(1).split(",")] if m else [])


def historia_agregada(bloque: list[dict]) -> dict:
    """Historia nacional a partir de ≥ 3 provinciales del mismo fenómeno: el titular lo pone plantilla_agregada()."""
    orden = sorted(bloque, key=lambda h: -(h.get("fuerza") or 0))
    p = orden[0]
    terr = [b.get("territorio") for b in orden]
    pob = sum(poblacion(t) or 0 for t in terr)
    x = {k: v for k, v in p.items() if k not in ("id", "provincia", "provincia_slug")}
    x.update({"id": f"mesa-{_slug(p.get('serie'))}-{_slug(p.get('indicador'))}-{p['fecha_dato'][:10]}-espana", "ambito": "nacional",
              "territorio": "España", "miembros": [b.get("id") for b in orden], "_miembros_territorios": terr, "pob_alcance": pob,
              "versiones_provinciales": orden, "fecha_dato": max(b["fecha_dato"] for b in orden), "agregada_por_mesa": True})
    x["titular"], x["entradilla"] = plantilla_agregada(orden)
    return x


def _slug(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _lista(n):
    n = [x for x in n if x]
    return ", ".join(n[:-1]) + " y " + n[-1] if len(n) > 1 else (n[0] if n else "")


def plantilla_agregada(orden: list[dict]) -> tuple[str, str]:
    """Titular nacional + entradilla para un grupo de provinciales. Plantillas por tipo; si no hay una, la genérica."""
    p = orden[0]
    n = len(orden)
    terr = [b.get("territorio") for b in orden]
    if p.get("serie") == "huella" and p.get("tipo") == "antes_raro":
        f = date.fromisoformat(p["fecha_dato"][:10])
        T = sorted((b.get("rareza") or {}).get("T_ahora") or 0 for b in orden)
        en_curso = p.get("cierre_mes") != "cerrado"
        tit = (f"En {n} capitales, {'lo que va de ' if en_curso else ''}{MESES[f.month - 1]} de {f.year} es un mes que en 1961-1990 "
               f"ocurría una vez cada diez años o menos; con el clima de hoy, una vez cada {_num(T[len(T) // 2])} años (mediana)")
        ent = (f"La media de temperatura de {'lo que va de ' if en_curso else ''}{MESES[f.month - 1]} supera en {n} capitales lo que en 1961-1990 "
               f"era un mes de una vez cada diez años o menos. Con el clima de 1996-2025, el periodo de retorno mediano es de "
               f"{_num(T[len(T) // 2])} años. Compara dos climas de la misma serie; no atribuye el mes a una causa. "
               f"Capitales: {_lista(terr)}.")
        return tit, ent
    if p.get("serie") == "capitales" and p.get("tipo") == "record_fecha":
        f = date.fromisoformat(p["fecha_dato"][:10])
        q = {"tmax": "máxima más alta", "tmin_alta": "mínima más alta", "tmin_baja": "mínima más baja"}.get(p.get("indicador"), "temperatura extrema")
        return (f"{n} capitales registraron el {f.day} de {MESES[f.month - 1]} la {q} para esa fecha desde 1940: {_lista(terr)}",
                f"Valor medido por AEMET en la estación de cada capital; récord para la fecha en la serie del reanálisis ERA5 de su celda desde 1940. "
                f"Es un récord del día del año, no del mes ni de la serie.")
    resto = re.sub(r"^\d+ lugares a la vez — ", "", p.get("titular", ""))
    resto = re.sub(r"\s*\(también [^)]*\)", "", resto)
    que = "estaciones de AEMET" if p.get("serie") == "estaciones" or "estacion_aemet" in str(p.get("variante")) else "capitales"
    if ": " in resto and resto.split(": ", 1)[0].strip() in terr:
        cuerpo = resto.split(": ", 1)[1]
        tit = f"En {n} {que}, {cuerpo[0].lower() + cuerpo[1:]}"
    else:   # sin «Lugar: …» no se puede quitar el lugar con seguridad: se dice que pasa en N sitios y se cita el primero
        tit = f"{n} {que} a la vez ({_lista(terr[:3])}{'…' if n > 3 else ''}): {resto}"
    ent = f"{p.get('titular', '')}. Mismo fenómeno, misma fecha, en {n} lugares: {_lista(terr)}."
    return tit, ent


def _num(x) -> str:
    if x is None:
        return "—"
    x = float(x)
    if x >= 100:
        return f"{round(x):,}".replace(",", ".")
    return f"{x:.1f}".replace(".", ",").replace(",0", "") if x < 10 else f"{round(x)}"


# ============================================================================ marcos grandes (lo que va de año, estación, mes, año hidrológico)
def estaciones_capital(raiz: Path = RAIZ, solo_capital: bool = True) -> dict:
    """{cod_provincia: (indicativo, ciudad, estación)} de scripts/balance_mensual.ESTACIONES. solo_capital deja fuera las de
    «referencia» (Tortosa por Tarragona, Vigo por Pontevedra, Gran Canaria por Las Palmas): no están en la capital."""
    sys.path.insert(0, str(raiz / "scripts"))
    import balance_mensual as B   # noqa: E402
    return {c: v[:3] for c, v in B.ESTACIONES.items() if not solo_capital or v[3] == "capital"}


_SERIES = {}


def serie_diaria(indicativo: str, raiz: Path = RAIZ) -> dict:
    """{date: (tmax, tmin, prec)} de archivo/aemet_diario/<ind>.csv.gz (serie validada que ya publica la web)."""
    if indicativo in _SERIES:
        return _SERIES[indicativo]
    out = {}
    f = raiz / "archivo" / "aemet_diario" / f"{indicativo}.csv.gz"
    if f.exists():
        with gzip.open(f, "rt", encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    d = date.fromisoformat(r["fecha"][:10])
                except Exception:
                    continue
                v = []
                for k in ("tmax", "tmin", "prec"):
                    try:
                        v.append(float(r[k]) if r.get(k) not in ("", None) else None)
                    except ValueError:
                        v.append(None)
                out[d] = tuple(v)
    _SERIES[indicativo] = out
    return out


PERIODOS = ("mes", "estacion", "anio", "hidro")
COLAS = {"calor": (0, +1, "más cálido"), "noches": (1, +1, "de noches más cálidas"), "lluvioso": (2, +1, "más lluvioso"),
         "seco": (2, -1, "más seco"), "frio": (0, -1, "más frío")}
ESTACION_TXT = {12: "invierno", 1: "invierno", 2: "invierno", 3: "primavera", 4: "primavera", 5: "primavera", 6: "verano", 7: "verano",
                8: "verano", 9: "otoño", 10: "otoño", 11: "otoño"}


def inicio_periodo(d: date, per: str) -> date:
    if per == "mes":
        return d.replace(day=1)
    if per == "anio":
        return date(d.year, 1, 1)
    if per == "hidro":
        return date(d.year if d.month >= 10 else d.year - 1, 10, 1)
    m0 = {12: 12, 1: 12, 2: 12, 3: 3, 4: 3, 5: 3, 6: 6, 7: 6, 8: 6, 9: 9, 10: 9, 11: 9}[d.month]
    return date(d.year - (1 if d.month < 3 and m0 == 12 else 0), m0, 1)


def fin_periodo(ini: date, per: str) -> date:
    meses = {"mes": 1, "estacion": 3, "anio": 12, "hidro": 12}[per]
    m = ini.month - 1 + meses
    return date(ini.year + m // 12, m % 12 + 1, 1) - timedelta(days=1)


def nombre_periodo(ini: date, per: str, hasta: date) -> tuple[str, str]:
    """(nombre corto, nombre con «lo que va de» si no está cerrado)."""
    cerrado = hasta >= fin_periodo(ini, per)
    if per == "mes":
        base = f"{MESES[ini.month - 1]} de {ini.year}"
    elif per == "anio":
        fin_mes = (hasta + timedelta(days=1)).day == 1
        base = f"{ini.year}" if cerrado else (f"enero-{MESES[hasta.month - 1]} de {ini.year}" if fin_mes else f"lo que va de {ini.year}")
    elif per == "hidro":
        base = f"el año hidrológico {ini.year}-{str(ini.year + 1)[2:]}"
    else:
        base = f"el {ESTACION_TXT[ini.month]} de {ini.year}"
    if cerrado or per == "anio":
        return base, base
    return base, "lo que va de " + re.sub(r"^el ", "", base)


def puesto_periodo(serie: dict, ini: date, hasta: date, idx: int, signo: int, min_frac=0.95):
    """Puesto del acumulado (media de temperatura o suma de lluvia) de ini..hasta frente al mismo tramo de años anteriores.
    Solo años con ≥ min_frac de días con dato en el tramo. Devuelve (puesto, n_años incluido el actual, valor, [(valor, año) del top 3 previo])
    o None."""
    largo = (hasta - ini).days + 1

    def acum(y):
        try:
            a = ini.replace(year=y)
            b = hasta.replace(year=y + (hasta.year - ini.year))
        except ValueError:   # 29 de febrero
            return None
        vals = []
        d = a
        while d <= b:
            v = serie.get(d)
            if v and v[idx] is not None:
                vals.append(v[idx])
            d += timedelta(days=1)
        if len(vals) < min_frac * largo:
            return None
        return sum(vals) if idx == 2 else sum(vals) / len(vals)
    act = acum(ini.year)
    if act is None:
        return None
    anios = sorted({d.year for d in serie})
    prev = [(acum(y), y) for y in anios if y < ini.year]
    prev = [(v, y) for v, y in prev if v is not None]
    if idx == 2 and largo >= 30:
        # un tramo de 30 días o más con 0,0 mm exactos en todos los días es casi siempre un hueco codificado como cero
        # (Cádiz 1971 y 1985 en septiembre-octubre): fuera de la comparación, en las dos colas
        prev = [(v, y) for v, y in prev if v > 0]
    if not prev:
        return None
    puesto = 1 + sum(1 for v, _ in prev if signo * (v - act) >= 0)
    top = sorted(prev, key=lambda x: -signo * x[0])[:3]
    return puesto, len(prev) + 1, act, top, min(y for _, y in prev)


def avance(ini: date, per: str, hasta: date) -> float:
    return ((hasta - ini).days + 1) / ((fin_periodo(ini, per) - ini).days + 1)


def marcos_grandes(hoy: date, lag: int = 5, raiz: Path = RAIZ, colas=("calor", "noches", "lluvioso", "seco"), estaciones=None,
                   min_avance: float = 2 / 3) -> list[dict]:
    """Regla 1.4. Con el dato validado de AEMET hasta hoy − lag, para cada capital con estación de ≥ 40 años y cada periodo
    (mes, estación, año, año hidrológico) y cola: puesto en la serie. Devuelve historias por capital (puesto 1-3) y una nacional
    por periodo y cola con el número de capitales en primer puesto y la de serie más larga. Solo periodos cerrados o con ≥ 2/3
    transcurridos (decisión de David, 25-11-2026); el año hidrológico, solo cerrado. La nacional lleva `marco` con la cuenta,
    que portada() compara con la de ayer para decidir si es noticia hoy."""
    hasta = hoy - timedelta(days=lag)
    estaciones = estaciones or estaciones_capital(raiz)
    out = []
    for per in PERIODOS:
        ini = inicio_periodo(hasta, per)
        cerrado_hoy = hasta == fin_periodo(ini, per)
        # el periodo recién cerrado (el mes anterior, el año hidrológico anterior) cuenta mientras está fresco
        ini_prev = inicio_periodo(ini - timedelta(days=1), per)
        candidatos = []
        if (avance(ini, per, hasta) >= min_avance and per != "hidro") or cerrado_hoy:
            candidatos.append((ini, hasta, cerrado_hoy))
        if (hasta - (ini - timedelta(days=1))).days <= VIDA_DIAS:
            candidatos.append((ini_prev, ini - timedelta(days=1), (hasta - (ini - timedelta(days=1))).days == 0))
        for (i0, h0, recien) in candidatos:
            for cola in colas:
                idx, signo, adj = COLAS[cola]
                filas = []
                for cod, (ind, ciudad, est) in estaciones.items():
                    s = serie_diaria(ind, raiz)
                    r = puesto_periodo(s, i0, h0, idx, signo)
                    if not r:
                        continue
                    puesto, n, val, top, desde = r
                    empate = bool(top) and puesto == 1 and abs(val - top[0][0]) < (0.05 if idx < 2 else max(0.5, 0.01 * abs(top[0][0])))
                    if empate:
                        puesto = 2          # empate práctico con el récord: no es «el más…»; se dice «iguala»
                    if n < ANIOS_SERIE_LARGA or puesto > 3:
                        continue
                    if idx == 2 and cola == "lluvioso" and val < 20:
                        continue
                    filas.append({"cod": cod, "ciudad": ciudad, "estacion": est, "ind": ind, "puesto": puesto, "n": n, "valor": round(val, 2), "empate": empate,
                                  "anterior": top[0] if top else None, "desde": desde})
                if not filas:
                    continue
                corto, largo = nombre_periodo(i0, per, h0)
                cerrado = h0 >= fin_periodo(i0, per)
                for f in filas:
                    out.append(_historia_marco_capital(f, per, cola, adj, corto, largo, cerrado, i0, h0, hoy, lag))
                primeros = [f for f in filas if f["puesto"] == 1]
                if len(primeros) >= 3:
                    out.append(_historia_marco_nacional(primeros, filas, per, cola, adj, corto, largo, cerrado, i0, h0, hoy, lag, len(estaciones)))
    return out


def _unidad(cola):
    return "mm" if cola in ("lluvioso", "seco") else "°C"


def _fmt(v, cola):
    return (f"{v:.1f}".replace(".", ",") if cola in ("lluvioso", "seco") else f"{v:.2f}".replace(".", ","))


def _historia_marco_capital(f, per, cola, adj, corto, largo, cerrado, i0, h0, hoy, lag):
    ordinal = "iguala el récord del" if f.get("empate") else {1: "el", 2: "el segundo", 3: "el tercero"}[f["puesto"]]
    var = {"calor": "media de las máximas", "noches": "media de las mínimas", "frio": "media de las máximas"}.get(cola, "lluvia acumulada")
    ant = f["anterior"]
    if f.get("empate"):
        tit = (f"{f['ciudad']}: {largo} iguala el {adj} en {f['n']} años de serie de AEMET ({_fmt(f['valor'], cola)} {_unidad(cola)}, "
               f"como en {f['anterior'][1]})")
    else:
        tit = None
    tit = tit or (f"{f['ciudad']}: {largo}, {ordinal} {adj} en {f['n']} años de serie de AEMET"
           + (f" ({_fmt(f['valor'], cola)} {_unidad(cola)}; el anterior, {_fmt(ant[0], cola)} en {ant[1]})" if f["puesto"] == 1 and ant else ""))
    ent = (f"La estación de AEMET de {f['estacion']} registra en {largo} una {var} de {_fmt(f['valor'], cola)} {_unidad(cola)}, "
           f"{'la más ' + ('alta' if COLAS[cola][1] > 0 else 'baja') if f['puesto'] == 1 else 'puesto ' + str(f['puesto'])} de su serie, que empieza en {f['desde']}. "
           f"Dato validado de AEMET hasta el {h0.day} de {MESES[h0.month - 1]}.")
    return {"tipo_mesa": "marco_capital", "serie": "mesa_marcos", "tipo": "puesto_extremo", "ambito": "provincial", "territorio": f["ciudad"],
            "fecha_dato": str(h0), "fecha_disponible": str(h0 + timedelta(days=lag)), "titular": tit, "entradilla": ent,
            "clave": {"indicador": f"marco:{per}:{cola}", "territorio": f"est:{f['ind']}", "periodo": f"{i0}", "corte": str(h0)},
            "cifra": {"puesto": f["puesto"]}, "valor": f["valor"], "comparacion": {"puesto": f["puesto"], "de": f["n"], "anterior": ant, "periodo": corto},
            "calidad": "validado", "fuente": "AEMET, serie diaria validada de la estación", "cerrado": cerrado, "periodo": per, "cola": cola,
            "invalidar": "AEMET valida con retraso y puede corregir días; cambios de emplazamiento de la estación; días sin dato en el periodo",
            "citabilidad": "alta"}


def _historia_marco_nacional(primeros, filas, per, cola, adj, corto, largo, cerrado, i0, h0, hoy, lag, total):
    n = len(primeros)
    lider = max(primeros, key=lambda f: f["n"])
    tit = (f"{largo[0].upper() + largo[1:]}, {'el ' + adj if not largo.startswith('lo que va') else 'el ' + adj} registrado en {n} capitales "
           f"con serie de AEMET de 40 años o más; en {lider['ciudad']}, desde {lider['desde']}")
    if largo.startswith("lo que va"):
        tit = f"{largo[0].upper() + largo[1:]} es el {adj} registrado en {n} capitales con serie de AEMET de 40 años o más; en {lider['ciudad']}, desde {lider['desde']}"
    otras = sorted(primeros, key=lambda f: -f["n"])
    ent = (f"En {n} de las {total} capitales con estación de AEMET en la propia ciudad, {largo} es el {adj} de su serie, entre las de 40 años o más. "
           f"La más larga es la de {lider['estacion']} ({lider['n']} años, desde {lider['desde']}): "
           f"{_fmt(lider['valor'], cola)} {_unidad(cola)} frente a {_fmt(lider['anterior'][0], cola)} en {lider['anterior'][1]}. "
           f"Dato validado de AEMET hasta el {h0.day} de {MESES[h0.month - 1]}"
           f"{'' if cerrado else '; el periodo no ha terminado'}. Capitales: {_lista([f['ciudad'] for f in otras])}.")
    return {"tipo_mesa": "marco_nacional", "serie": "mesa_marcos", "tipo": "puesto_extremo", "ambito": "nacional", "territorio": "España",
            "fecha_dato": str(h0), "fecha_disponible": str(h0 + timedelta(days=lag)), "titular": tit, "entradilla": ent,
            "clave": {"indicador": f"marco:{per}:{cola}", "territorio": "pais:es", "periodo": f"{i0}", "corte": str(h0)},
            "marco": {"n_primeros": n, "n_top3": len(filas), "total": total, "cerrado": cerrado, "lider": lider["ciudad"], "periodo": per, "cola": cola,
                      "hito": str(h0) if (h0 + timedelta(days=1)).day == 1 else None},
            "cifra": {"n_primeros": n}, "comparacion": {"puesto": 1, "de": lider["n"], "periodo": corto},
            "_miembros_territorios": [f["ciudad"] for f in primeros], "miembros": [f"est:{f['ind']}" for f in primeros],
            "versiones_provinciales": [f["ciudad"] for f in filas],
            "calidad": "validado", "fuente": "AEMET, series diarias validadas de las estaciones de las capitales", "cerrado": cerrado,
            "periodo": per, "cola": cola, "citabilidad": "alta",
            "invalidar": "AEMET valida con retraso; cada capital frente a su propia serie (no es un promedio de España); cambios de emplazamiento"}


# ============================================================================ récords diarios de estación (serie ≥ 40 años)
def estaciones_archivo(raiz: Path = RAIZ) -> dict:
    """Todas las estaciones de archivo/aemet_diario con su nombre de capital (si lo es) o su nombre de AEMET y provincia."""
    m = maestro(raiz)
    caps = {v[0]: v[1] for v in estaciones_capital(raiz, solo_capital=False).values()}
    out = {}
    for f in sorted((raiz / "archivo" / "aemet_diario").glob("*.csv.gz")):
        ind = f.name[:-7]
        prov = m["nombres"].get(m["est_prov"].get(f"est:{ind}", ""), "")
        nom = caps.get(ind) or f"{m['nombres'].get('est:' + ind, ind).title()} ({prov})"
        out[ind] = (ind, nom, m["nombres"].get(f"est:{ind}", ind).title())
    return out


def records_estacion(dia: date, raiz: Path = RAIZ, estaciones=None, margen_fecha: float = 4.0) -> list[dict]:
    """Récords del día `dia` en las estaciones del archivo con ≥ 40 años: máxima o mínima más alta de cualquier mes de ese
    nombre y día más lluvioso de cualquier mes de ese nombre (≥ 30 l/m²)."""
    estaciones = estaciones or estaciones_archivo(raiz)
    out = []
    for cod, (ind, ciudad, est) in estaciones.items():
        s = serie_diaria(ind, raiz)
        v = s.get(dia)
        if not v:
            continue
        mismo_mes = [(d, x) for d, x in s.items() if d.month == dia.month and (d.year < dia.year or (d.year == dia.year and d < dia))]
        anios = len({d.year for d, _ in mismo_mes if d.year < dia.year})
        if anios < ANIOS_SERIE_LARGA:
            continue
        for idx, q, cola in ((0, "máxima", "calor"), (1, "mínima", "noches"), (2, "lluvia", "lluvioso")):
            if v[idx] is None:
                continue
            prev = [(x[idx], d) for d, x in mismo_mes if x[idx] is not None]
            if not prev:
                continue
            mx = max(prev)
            if v[idx] > mx[0] and (idx < 2 or v[idx] >= 30):
                if idx == 2:
                    tit = f"{ciudad}: {_fmt(v[2], 'lluvioso')} l/m² el {dia.day} de {MESES[dia.month - 1]}, el día más lluvioso de cualquier {MESES[dia.month - 1]} en {anios} años de serie de AEMET"
                else:
                    tit = f"{ciudad}: la {q} más alta de cualquier {MESES[dia.month - 1]} en {anios} años de serie de AEMET ({_fmt(v[idx], cola)[:-1]} °C, el {dia.day})"
                out.append({"tipo_mesa": "record_mes", "serie": "mesa_records", "tipo": "record_mes", "ambito": "provincial", "territorio": ciudad,
                            "fecha_dato": str(dia), "titular": tit, "indicador": f"record_mes_{cola}",
                            "entradilla": f"La estación de AEMET de {est} registró {_fmt(v[idx], cola)} {'l/m²' if idx == 2 else '°C'} el {dia.day} de {MESES[dia.month - 1]}; "
                                          f"el récord anterior para un {MESES[dia.month - 1]} era {_fmt(mx[0], cola)}, del {mx[1].day} de {MESES[mx[1].month - 1]} de {mx[1].year}.",
                            "clave": {"indicador": f"record_mes:{cola}", "territorio": f"est:{ind}", "periodo": f"{dia.year}-{dia.month:02d}", "corte": str(dia)},
                            "cifra": {"valor": v[idx], "anterior": [mx[0], mx[1].year]}, "comparacion": {"puesto": 1, "de": anios + 1, "periodo": MESES[dia.month - 1]},
                            "calidad": "validado", "citabilidad": "alta", "cola": cola, "id": f"mesa-record-mes-{cola}-{ind}-{dia}",
                            "invalidar": "dato de un solo día: AEMET puede corregirlo al validar; contrastar con la estación vecina"})
    return out


_RACHAS = {}


def racha_seca(indicativo: str, raiz: Path = RAIZ) -> dict:
    """{date: días seguidos sin un día de 1 mm o más, contando ese día} de la serie validada; un día sin dato corta la racha."""
    if indicativo in _RACHAS:
        return _RACHAS[indicativo]
    s = serie_diaria(indicativo, raiz)
    out, n, prev = {}, 0, None
    for d in sorted(s):
        p = s[d][2]
        if p is None or (prev and (d - prev).days > 1):
            n = 0
        n = n + 1 if (p is not None and p < 1) else 0
        out[d] = n
        prev = d
    _RACHAS[indicativo] = out
    return out


def rachas_estacion(dia: date, raiz: Path = RAIZ, minimo: int = 30, estaciones=None) -> list[dict]:
    """Racha seca en curso el día `dia` más larga que cualquier racha en curso ese mismo día del año en ≥ 40 años de serie,
    y de al menos `minimo` días (umbral calibrado de R03 en estación: 30). Se emite una vez por racha (clave = día de inicio)."""
    estaciones = estaciones or estaciones_archivo(raiz)
    out = []
    for ind, (_, nombre, est) in estaciones.items():
        r = racha_seca(ind, raiz)
        n = r.get(dia, 0)
        if n < minimo:
            continue
        previas = [r.get(dia.replace(year=y)) for y in range(min(x.year for x in r), dia.year) if (dia.month, dia.day) != (2, 29)]
        previas = [x for x in previas if x is not None]
        if len(previas) < ANIOS_SERIE_LARGA or n <= max(previas):
            continue
        inicio = dia - timedelta(days=n - 1)
        tit = (f"{nombre} lleva {n} días seguidos sin un día de lluvia de 1 l/m²: ninguna racha así a {dia.day} de {MESES[dia.month - 1]} "
               f"en {len(previas)} años de serie de AEMET (la más larga hasta ahora para esta fecha, {max(previas)} días)")
        out.append({"tipo_mesa": "racha", "serie": "mesa_rachas", "tipo": "racha", "ambito": "provincial", "territorio": nombre, "fecha_dato": str(dia),
                    "titular": tit, "indicador": "racha_seca", "id": f"mesa-racha-seca-{ind}-{inicio}",
                    "clave": {"indicador": "racha:seca", "territorio": f"est:{ind}", "periodo": str(inicio), "corte": str(dia)},
                    "cifra": {"inicio": str(inicio)}, "comparacion": {"puesto": 1, "de": len(previas) + 1, "periodo": f"racha a {dia}"},
                    "calidad": "validado", "citabilidad": "alta", "cola": "seco",
                    "invalidar": "un día sin dato rompe la racha; el pluviómetro puede no registrar lloviznas de menos de 1 l/m²"})
    return out


# ============================================================================ plantillas (1.6)
PLANTILLAS = {
    "marco_nacional": [
        "{Periodo} es el {adj} registrado en {n} capitales con serie de AEMET de 40 años o más; en {lider}, desde {desde}",
        "{n} capitales viven su {periodo_corto} {adj} desde que hay registros; la serie más larga, {lider}, empieza en {desde}",
        "En {n} de {total} capitales, {periodo} es el {adj} de su serie de AEMET",
    ],
    "marco_capital": [
        "{Ciudad}: {periodo}, el {adj} en {n} años de serie de AEMET ({valor}; el anterior, {anterior} en {anio_ant})",
        "{Ciudad} no había tenido nunca un {periodo_corto} tan {adj_corto}: {valor}, en una serie de {n} años",
        "{Ciudad}: {periodo}, el {ordinal} {adj} en {n} años de serie de AEMET",
    ],
    "record_mes": [
        "{Ciudad}: la {variable} más alta de cualquier {mes} en {n} años de serie de AEMET ({valor}, el {dia})",
        "{n_est} estaciones de AEMET con 40 años o más de serie baten el {fecha} su {variable} más alta para un {mes}",
    ],
    "record_lluvia": [
        "{Ciudad}: {valor} l/m² el {fecha}, el día más lluvioso de cualquier {mes} en {n} años de serie de AEMET",
        "{Ciudad} recoge en un día {veces} veces lo que llueve de media en todo {mes}: {valor} l/m², récord de {n} años",
    ],
    "racha": [
        "{Lugar} lleva {dias} días {condicion}: la racha más larga para un {fecha} en {n} años de serie de AEMET",
        "{n_lug} capitales encadenan {condicion} sin precedente para esta fecha; la más larga, {lugar}, {dias} días",
    ],
    "reanalisis": [
        "{Ciudad}: {periodo}, el {adj} de {n} años según el reanálisis ERA5 ({anomalia} sobre 1991-2020)",
        "En {n_lug} capitales, {periodo} es el {adj} de la serie del reanálisis ERA5, que empieza en 1940",
    ],
    "episodio": [
        "AEMET activa el aviso rojo por {fenomeno} en {zonas}; {estacion} lleva {valor} l/m²",
        "{estacion} recoge {valor} l/m² en 24 horas, {comparacion}; aviso {nivel} en {n_zonas} zonas",
    ],
    "sequia": [
        "{n} provincias en sequía severa o extrema con los embalses por encima del {pct} %: la reserva es del año pasado",
        "{Provincia}, en sequía {nivel} donde lo normal son {normal} l/m² al año",
    ],
    "atribucion": [
        "Un {mes} como el de {anio} es hoy al menos {veces} veces más probable que en 1961-1990 en {n} capitales",
        "{Ciudad}: lo que en 1961-1990 era un {mes} de una vez cada {T_antes} años hoy ocurre una vez cada {T_ahora}",
    ],
    "sin_noticia": [
        "Hoy no hay nada excepcional en los datos. Sigue vigente: {marco_vigente}",
        "Sin noticia hoy. El dato que marca la temporada: {marco_vigente}",
    ],
}
ENTRADILLAS = {
    "marco_nacional": "En {n} de las {total} capitales con estación de AEMET en la propia ciudad, {periodo} es el {adj} de su serie entre las de 40 años o más. "
                      "La más larga es la de {estacion_lider} ({n_lider} años): {valor} frente a {anterior} en {anio_ant}. Dato validado de AEMET hasta el {hasta}.",
    "marco_capital": "La estación de AEMET de {estacion} registra en {periodo} una {variable} de {valor}, {puesto_txt} de su serie, que empieza en {desde}. "
                     "Dato validado de AEMET hasta el {hasta}.",
    "sin_noticia": "Ningún dato de hoy cumple los cinco criterios: alcance, rareza en una serie larga, algo nuevo desde ayer, una frase y un dato que se sostiene. "
                   "Lo vigente: {marco_vigente}. Debajo, los datos del día.",
}


# ============================================================================ portada (1.7)
def portada(candidatos: list[dict], hoy: date, emitidos: dict) -> dict:
    """candidatos: historias ya agrupadas, con `rasgos` y `puntuacion`. emitidos: {clave_str: cifra} de días anteriores
    (novedad). Devuelve la portada del día y actualiza `emitidos`."""
    noticias, datos, contexto = [], [], []
    for c in candidatos:
        k = json.dumps([c.get("clave", {}).get("indicador") if c.get("clave") else c.get("indicador"),
                        (c.get("clave") or {}).get("territorio") or c.get("territorio"),
                        (c.get("clave") or {}).get("periodo") or c.get("fecha_dato", "")[:7]], ensure_ascii=False)
        cifra = json.dumps(c.get("cifra") or c.get("dato") or c.get("titular"), ensure_ascii=False, sort_keys=True, default=str)
        r = c["rasgos"]
        cerrado = bool((c.get("marco") or {}).get("cerrado") or c.get("cerrado"))
        mk = c.get("marco")
        if mk:
            # Regla 1.4: el marco nacional es noticia al cerrarse un mes (hito) o cuando el número de capitales en primer puesto
            # cruza una decena por encima de lo ya publicado (de 28 a 30, de 19 a 21). Que pase de 27 a 28 y vuelva a 27 no es noticia
            # (el recuento sube solo a medida que llegan días validados de más estaciones).
            antes = emitidos.get(k) or {"max_n": 0, "hitos": []}
            n = mk["n_primeros"]
            nuevo_hito = bool(mk.get("hito")) and mk["hito"] not in antes.get("hitos", [])
            sube = antes.get("max_n", 0) > 0 and n // 10 > antes.get("max_n", 0) // 10
            r["novedad"] = 1.0 if (k not in emitidos or nuevo_hito or sube) else 0.0
        elif k in emitidos:
            antes = emitidos[k]
            r["novedad"] = 0.0 if antes["cifra"] == cifra else 0.5
            if c.get("tipo_mesa") == "marco_capital" and antes["cifra"] != cifra:
                # una capital sube de puesto (3.º → 2.º → 1.º): es nuevo; si baja, no
                r["novedad"] = 1.0 if c["cifra"]["puesto"] < json.loads(antes["cifra"])["puesto"] else 0.0
            if cerrado and not antes["cerrado"]:
                r["novedad"] = 1.0          # se cierra el periodo: es noticia aunque la cifra se parezca
        c["_k"], c["_cifra"], c["_cerrado"] = k, cifra, cerrado
        c["puntuacion"] = puntuar(r)
        sec = r.get("seccion", "noticia")
        (datos if sec == "datos" else contexto if sec == "contexto" else noticias).append(c)
    noticias.sort(key=lambda c: -(c["puntuacion"]["puntos"] + (3 if (c.get("marco") or {}).get("cerrado") else 0)))
    # Emergencia (aviso rojo de AEMET o ≥ 200 l/m² en un día en una estación de AEMET): abre la página aunque otra puntúe más.
    # No es una noticia de datos: va con su plantilla de aviso y su fuente oficial.
    emerg = [c for c in noticias if c["rasgos"].get("emergencia") and all(c["puntuacion"]["puertas"].values())]
    dia = emerg[0] if emerg else next((c for c in noticias if c["puntuacion"]["portada"]), None)
    mas = [c for c in noticias if c is not dia and c["puntuacion"]["mas"]][:4]
    for c in ([dia] if dia else []) + mas:
        if c.get("marco"):
            e = emitidos.get(c["_k"]) or {"max_n": 0, "hitos": []}
            e["max_n"] = max(e["max_n"], c["marco"]["n_primeros"])
            if c["marco"].get("hito"):
                e["hitos"] = e["hitos"] + [c["marco"]["hito"]]
            emitidos[c["_k"]] = e
        else:
            emitidos[c["_k"]] = {"cifra": c["_cifra"], "cerrado": c["_cerrado"]}
    resto = [c for c in noticias if c is not dia and c not in mas]
    return {"fecha": str(hoy), "historia_del_dia": dia, "sin_noticia": dia is None, "mas": mas,
            "datos_del_dia": sorted(datos, key=lambda c: -c["puntuacion"]["puntos"]),
            "contexto": sorted(contexto + resto, key=lambda c: -c["puntuacion"]["puntos"])}
