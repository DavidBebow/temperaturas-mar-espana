#!/usr/bin/env python3
"""Detector diario del almacén (scripts/detector_almacen.py).

Evalúa las reglas del catálogo del almacén (observatorio-datos/almacen/reglas/, calibradas sobre todo el pasado) con SOLO:
  · las referencias publicadas en docs/prensa/referencias/ (las calcula almacen/referencias.py en el Air; valen 45 días);
  · los datos del día que ya publica la web: archivo/era5/NN/2026.csv (capitales, reanálisis), archivo/aemet_diario/*.csv.gz
    (estaciones validadas), docs/sequia/index.json (Monitor), docs/deshielo.json (hielo marino NSIDC) y
    docs/dana/mediterraneo_historico.json (OISST).
No necesita el Air encendido ni ninguna API de pago. Lo llama scripts/hallazgos_prensa.py (fuente `almacen`) y también
funciona solo:  python3 scripts/detector_almacen.py --hoy 2026-11-25

Contrato: cada hallazgo sale con los campos de hallazgos_prensa.py (serie, tipo, indicador, territorio, provincia, ambito,
fecha_dato, titular, dato, contexto, metodo, limites, citabilidad, exclusivo) más regla, variante, destino, clave
{indicador, territorio, periodo, corte}, cifra, comparacion, muestra, calidad, invalidar y novedad (fuerza_detalle).

Decisiones de David (25-11-2026): «lo que va de…» solo con el periodo cerrado o ≥ 2/3 transcurrido; una sola historia por
provincia y fenómeno (estación de AEMET; la capital de respaldo); ninguna historia en exclusiva (la gestiona él).
Reglas que NO se evalúan aquí por falta de fuente pública (se dice en docs/estado/almacen.json): R02 y R10 por municipio
(ERA5-Land por celda, solo en el Air), R11 y R12 (previsión guardada y revisiones: las evalúa el Air, parte interno).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
REFS = DOCS / "prensa" / "referencias"
SALIDA = DOCS / "prensa" / "almacen"
ESTADO = DOCS / "estado" / "almacen.json"

ANIOS_ESTACION = 40      # serie de AEMET que «aguanta» (criterio de la mesa de redacción, 25-11-2026)
MAX_DIARIAS = 5          # historias del detector que llegan a /prensa/ cada día
FRAC_MIN = 2 / 3         # «lo que va de…»: fracción mínima del periodo transcurrida (decisión de David, 25-11-2026)
EXCLUSIVO = False        # ninguna historia en exclusiva: David reparte las noticias
MIN_ANIOS_PREVIOS = 30
PERIODOS = ("mes", "estacion", "anio", "hidro")
ESTACIONES = ["invierno", "primavera", "verano", "otoño"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
LARGO = {"mes": 30, "estacion": 91, "anio": 365, "hidro": 365}
COLAS = {"calor": ("tmax", 1), "frio": ("tmax", -1), "noches": ("tmin", 1), "lluvia": ("prec", 1), "seco": ("prec", -1)}
SERIE_TXT = {"capitales": "reanálisis ERA5 en la celda de la capital (Copernicus), serie diaria desde 1940",
             "estaciones": "estación de AEMET, serie diaria validada del archivo"}

# ------------------------------------------------------------------------------------------ fuerza (almacen/reglas/fuerza.py)
BASE = {"record_absoluto": 100, "record_mes": 50, "primera_vez_desde": 90, "record_fecha": 80, "puesto_extremo": 75,
        "racha": 65, "anomalia_fuerte": 55, "percentil_extremo": 50, "contexto": 30, "episodio": 70, "compuesto": 70,
        "temporada": 60, "antes_raro": 55, "lluvia_dia": 50, "lluvia_en_curso": 54}
AMBITO = {"nacional": 1.0, "regional": 0.9, "provincial": 0.8, "local": 0.7, "global": 0.85}


def r_est(T):
    if T is None:
        return 1.0
    if T <= 1:
        return 0.6
    return min(1.25, max(0.6, 0.55 + 0.3 * math.log10(T)))


def r_pob(pob):
    if not pob:
        return 1.0
    return min(1.2, max(0.85, 1 + 0.1 * math.log10(pob / 1e5)))


def r_lugar(q, ambito):
    if q is None or ambito in ("nacional", "global"):
        return 1.0
    return 1 + 0.25 * max(0.0, min(1.0, q))


def puntuar(tipo, ambito, exclusivo=True, frescura=1.0, T=None, pob=None, q=None, citabilidad="media", pr=None, avance=None, empate=False):
    ra = 1.0 if avance is None else 0.7 + 0.3 * max(0.0, min(1.0, avance))
    nov = (1.0 if pr else r_est(T)) * r_pob(pob) * r_lugar(q, ambito) * ra * (0.85 if empate else 1.0)
    nov = min(1.35, max(0.5, nov))
    f = BASE[tipo] * AMBITO[ambito] * (1.0 if exclusivo else 0.7) * frescura * nov
    if pr and pr > 1:
        f *= min(pr, 5.0) / 2.0
    f = min(100.0, f)
    if citabilidad == "contexto":
        f *= 0.5
    return {"fuerza": round(f, 1), "novedad": round(nov, 3), "r_est": round(r_est(T), 3), "r_pob": round(r_pob(pob), 3),
            "r_lugar": round(r_lugar(q, ambito), 3), "r_avance": round(ra, 3), "empate": empate, "T_anios": round(T, 1) if T else None}


class FZ:
    puntuar = staticmethod(puntuar)


class comun:
    MESES = MESES
    ESTACIONES = ESTACIONES
    PERIODOS = PERIODOS
    MIN_ANIOS_PREVIOS = MIN_ANIOS_PREVIOS


# ------------------------------------------------------------------------------------------ utilidades
def f1(x):
    return f"{x:.1f}".replace(".", ",")

def f0(x):
    return f"{round(x):,}".replace(",", ".")

def fd(d: date):
    return f"{d.day} de {MESES[d.month - 1]}"

def periodo_de(d: date, per: str):
    if per == "mes":
        return (d.year, d.month, d.day, date(d.year, d.month, 1))
    if per == "estacion":
        g = (d.month % 12) // 3
        y0 = d.year - (1 if d.month in (1, 2) else 0)
        ini = date(y0 if g == 0 else d.year, {0: 12, 1: 3, 2: 6, 3: 9}[g], 1)
        return (d.year + (d.month == 12), g, (d - ini).days + 1, ini)
    if per == "anio":
        return (d.year, 0, d.timetuple().tm_yday, date(d.year, 1, 1))
    ini = date(d.year - (d.month < 10), 10, 1)
    return (d.year + (d.month >= 10), 0, (d - ini).days + 1, ini)

def nombre_periodo(d: date, per: str):
    if per == "mes":
        return f"{MESES[d.month - 1]} de {d.year}", f"lo que va de {MESES[d.month - 1]}"
    if per == "estacion":
        g = (d.month % 12) // 3
        return f"el {comun.ESTACIONES[g]} de {d.year}", f"lo que va de {comun.ESTACIONES[g]}"
    if per == "anio":
        return f"{d.year}", f"lo que va de {d.year}"
    y = d.year + (d.month >= 10)
    return f"el año hidrológico {y - 1}-{str(y)[2:]}", f"lo que va de año hidrológico (desde el 1 de octubre)"



def leer_json(p: Path, defecto=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def leer_gz(p: Path):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def num(v):
    try:
        s = str(v).strip().replace(",", ".")
        return float(s) if s else None
    except Exception:
        return None


class Contexto:
    """Lo que el prototipo del Air leía de DuckDB, leído de las referencias (incluido maestro.json.gz)."""

    def __init__(self, ref: Path):
        self.ref = ref
        self.indice = leer_json(ref / "indice.json", {})
        self.R = {}
        for k in ("capitales", "estaciones", "municipios", "provincias", "global", "umbrales", "maestro"):
            self.R[k] = leer_gz(ref / f"{k}.json.gz")
        self.U = self.R["umbrales"]["umbrales"]
        self.hasta_ref = date.fromisoformat(self.R["capitales"]["datos_hasta"])
        self.valido_desde = date.fromisoformat(self.R["capitales"]["valido_desde"])
        self.valido = date.fromisoformat(self.R["capitales"]["valido_hasta"])
        M = self.R["maestro"]
        self.nom = M["nombres"]
        self.cap_prov = M["cap_prov"]
        self.prov_cap = {v: k for k, v in self.cap_prov.items()}
        self.est_prov = M["est_prov"]
        self.pob_cap = M["pob_cap"]
        self.pob_prov = M["pob_prov"]
        self.q_lluvia = M["q_lluvia"]
        self.q_temp = M["q_temp"]
        # 25-11-2026 · mesa de redacción: «primero la estación AEMET». Provincias con una estación de AEMET de serie larga
        # (≥ ANIOS_ESTACION años con dato en las referencias): ahí el reanálisis de la capital no publica nada por su cuenta.
        self.est_larga = {}
        for ent, dias in (self.R["estaciones"].get("dia") or {}).items():
            n = max(((v or [0] * 7)[6] or 0) for v in dias.values()) if dias else 0
            prov = self.est_prov.get(ent)
            if prov and n >= ANIOS_ESTACION and n > self.est_larga.get(prov, (None, 0))[1]:
                self.est_larga[prov] = (ent, n)
        self.sospechosos = {}   # calidad.py solo corre en el Air: aquí no hay lista de datos sospechosos (se dice en el estado)

    def u(self, clave, defecto=None):
        v = self.U.get(clave)
        return defecto if v is None else v

    def lugar_q(self, ent, cola):
        cap = ent if ent.startswith("cap:") else self.prov_cap.get(self.est_prov.get(ent, ent) if not ent.startswith("prov:") else ent)
        if cola in ("seco", "sequia"):
            return self.q_lluvia.get(cap)
        if cola == "lluvia":
            return None if self.q_lluvia.get(cap) is None else 1 - self.q_lluvia[cap]
        if cola in ("calor", "noches", "tropical"):
            return None if self.q_temp.get(cap) is None else 1 - self.q_temp[cap]
        if cola in ("frio", "helada"):
            return self.q_temp.get(cap)
        return None

    def provincia(self, ent):
        p = self.cap_prov.get(ent) or self.est_prov.get(ent) or (ent if ent.startswith("prov:") else None)
        return p, self.nom.get(p, p)


# ------------------------------------------------------------------------------------------ datos del día (ficheros publicados)
DATOS_DESCARTADOS: list[dict] = []   # valores imposibles o ficheros rotos que se han saltado en esta pasada (va al estado y al parte interno)
LIMITES = {"tmax": (-35.0, 52.0), "tmin": (-45.0, 40.0), "prec": (0.0, 600.0)}


def plausible(ent, d, tx, tn, p):
    """Un dato fuera de lo físicamente posible no entra: se anota y el día queda como «sin dato» (no rompe ni inventa un récord)."""
    malo = [n for n, v in (("tmax", tx), ("tmin", tn), ("prec", p)) if v is not None and not (LIMITES[n][0] <= v <= LIMITES[n][1])]
    if tx is not None and tn is not None and tn > tx + 0.5:
        malo.append("tmin>tmax")
    if malo:
        DATOS_DESCARTADOS.append({"ent": ent, "fecha": str(d), "campos": malo, "valores": [tx, tn, p]})
        return False
    return True


def diarios(raiz: Path, fam: str, entes, d0: date, d1: date):
    """{ent: {fecha: (tmax, tmin, prec)}} de d0 a d1 desde el archivo público del repo. Un fichero roto no tumba la pasada."""
    out = defaultdict(dict)
    for ent in entes:
        try:
            if fam == "capitales":
                f = raiz / "archivo" / "era5" / ent.split(":")[1] / "2026.csv"
                abrir, col = (lambda: open(f, encoding="utf-8", newline="")), "lluvia"
            else:
                f = raiz / "archivo" / "aemet_diario" / f"{ent.split(':')[1]}.csv.gz"
                abrir, col = (lambda: gzip.open(f, "rt", encoding="utf-8", newline="")), "prec"
            if not f.exists():
                continue
            with abrir() as fh:
                for r in csv.DictReader(fh):
                    try:
                        d = date.fromisoformat(str(r["fecha"])[:10])
                    except Exception:
                        continue
                    if not (d0 <= d <= d1):
                        continue
                    tx, tn, p = num(r.get("tmax")), num(r.get("tmin")), num(r.get(col))
                    if plausible(ent, d, tx, tn, p):
                        out[ent][d] = (tx, tn, p)
        except Exception as e:   # gzip truncado, CSV sin columnas…
            DATOS_DESCARTADOS.append({"ent": ent, "fecha": None, "campos": ["fichero"], "error": str(e)[:100]})
    return out


def hallazgo(C: Contexto, *, regla, variante, tipo, ent, fecha, indicador, titular, dato, cifra, comparacion, muestra,
             calidad, serie, invalidar, ambito="provincial", destino="publicable", T=None, pob=None, cola=None,
             exclusivo=EXCLUSIVO, contexto=None, limites=None, extra=None, territorio=None, avance=None, empate=False):
    prov_id, prov = C.provincia(ent)
    cit = "contexto" if destino != "publicable" else ("alta" if calidad == "validado" else "media")
    lim = list(limites or [])
    motivo = C.sospechosos.get((ent, str(fecha)))
    if motivo:
        lim.append(f"COMPROBAR: calidad.py marca {ent} el {fecha} ({motivo})")
    pz = FZ.puntuar(tipo, ambito, exclusivo, 1.0, T=T, pob=pob, q=C.lugar_q(ent, cola) if cola else None, citabilidad=cit,
                    avance=avance, empate=empate)
    terr = territorio or C.nom.get(ent, ent)
    h = {"regla": regla, "variante": variante, "destino": destino, "serie": f"almacen_{regla.lower()}", "tipo": tipo,
         "indicador": f"{regla}_{variante}".replace(":", "_"), "territorio": terr, "provincia": prov if ambito != "nacional" else None,
         "ambito": ambito, "fecha_dato": str(fecha), "titular": titular, "dato": dato,
         "clave": {"indicador": variante, "territorio": ent, "periodo": comparacion.get("periodo"), "corte": str(fecha)},
         "cifra": cifra, "comparacion": comparacion, "muestra": muestra, "calidad": calidad, "invalidar": invalidar,
         "metodo": f"{serie}. Regla {regla} del catálogo del almacén (almacen/reglas/), umbral calibrado sobre todo el pasado.",
         "limites": lim, "contexto": list(contexto or []), "citabilidad": cit, "exclusivo": exclusivo,
         "requiere_revision": any("COMPROBAR" in x for x in lim), "fuerza": pz["fuerza"], "fuerza_detalle": pz,
         "ent_id": ent, **(extra or {})}
    return h


# ------------------------------------------------------------------------------------------ reglas (copiadas del catálogo del almacén)
def r01(C, fam, D, desde, hasta, salida, vigentes):
    ref = C.R[fam]
    serie_reg = "capital_era5" if fam == "capitales" else "estacion_aemet"
    for ent, est in ref["estado"].items():
        dd = D.get(ent, {})
        for per in comun.PERIODOS:
            if per not in est:
                continue
            for cola, (var, signo) in COLAS.items():
                u = C.u(f"R01:{serie_reg}:{per}:{cola}")
                estado_v = C.u(f"R01:{serie_reg}:{per}:{cola}:estado", "")
                if u is None or estado_v.startswith("descartada"):
                    continue
                frac, margen = u
                frac = max(frac, FRAC_MIN)   # decisión de David (25-11-2026): solo periodo ≥ 2/3 transcurrido
                tabla = ref["puestos"].get(ent, {}).get(per, {}).get(cola, {})
                i = {"tmax": 0, "tmin": 1, "prec": 2}[var]
                emitido = False
                for k in range((hasta - desde).days + 1):
                    d = desde + timedelta(days=k)
                    py, grp, off, ini = periodo_de(d, per)
                    st = est[per]
                    if date.fromisoformat(st["desde"]) == ini or (ini <= C.hasta_ref):
                        s, n = st[var]
                        s, n = (s or 0), (n or 0)
                        dias = [C.hasta_ref + timedelta(days=j) for j in range(1, (d - C.hasta_ref).days + 1)]
                    else:
                        s, n = 0, 0
                        dias = [ini + timedelta(days=j) for j in range((d - ini).days + 1)]
                    falta = False
                    for x in dias:
                        v = dd.get(x, (None, None, None))[i]
                        if v is None:
                            falta = True
                            continue
                        s += v
                        n += 1
                    if dd.get(d) is None or falta and d == max(dd, default=d):
                        continue
                    if n < (0.97 if var == "prec" else 0.9) * off:
                        continue
                    acum = s if var == "prec" else s / n
                    t = tabla.get(str(d))
                    if not t or len(t) < 3:
                        continue
                    n_prev, normal, top = t[0], t[1], t[2:]
                    if n_prev < comun.MIN_ANIOS_PREVIOS:
                        continue
                    mejor = top[0][0]
                    if off < max(3, round(frac * LARGO[per])):
                        continue
                    if not (signo * (acum - mejor) > 0):
                        continue
                    if var == "prec":
                        if cola == "lluvia" and not (acum >= margen * mejor and acum >= 20):
                            continue
                        if cola == "seco" and not (normal is not None and normal >= margen):
                            continue
                    elif signo * (acum - mejor) < margen:
                        continue
                    if emitido:
                        break
                    emitido = True
                    if d == desde and off > max(3, round(frac * LARGO[per])) + 1:
                        vigentes.append((ent, per, cola))
                        break
                    nom = C.nom.get(ent, ent)
                    pname, ptxt = nombre_periodo(d, per)
                    desde_y = d.year - n_prev if fam == "capitales" else None
                    adj = {"calor": "más cálido", "frio": "más frío", "noches": "de noches más cálidas", "lluvia": "más lluvioso", "seco": "más seco"}[cola]
                    if var == "prec":
                        rel = f"{round(100 * acum / normal)} % de lo normal" if normal else ""
                        cifra = {"valor": round(acum, 1) if fam == "estaciones" else None, "pct_normal": round(100 * acum / normal) if normal else None}
                    else:
                        an = acum - normal if normal is not None else None
                        rel = f"{'+' if an >= 0 else '−'}{f1(abs(an))} °C sobre 1991-2020" if an is not None else ""
                        cifra = {"valor": round(acum, 2) if fam == "estaciones" else None, "anomalia": round(an, 2) if an is not None else None}
                    if fam == "capitales":
                        tit = f"{nom}: {ptxt} es el {adj} de los {n_prev + 1} años de su serie ({rel}, reanálisis)"
                        dato = f"puesto 1 de {n_prev + 1}; anterior: {top[0][1]}; {rel}"
                    else:
                        un = "mm" if var == "prec" else "°C de media de las " + ("máximas" if var == "tmax" else "mínimas")
                        fx = f1 if abs(acum - mejor) >= 0.1 else (lambda x: f"{x:.2f}".replace(".", ","))
                        tit = f"La estación de AEMET de {nom.title()}: {ptxt}, el {adj} en {n_prev + 1} años ({fx(acum)} {un}; récord anterior {fx(mejor)} en {top[0][1]})"
                        dato = f"{f1(acum)} {un} · {rel} · puesto 1 de {n_prev + 1}"
                    salida.append(hallazgo(C, regla="R01", variante=f"{serie_reg}:{per}:{cola}", tipo="puesto_extremo", ent=ent, fecha=d,
                                           indicador=cola, titular=tit, dato=dato, cifra=cifra,
                                           comparacion={"puesto": 1, "de": n_prev + 1, "anterior": top[0], "segundo": top[1] if len(top) > 1 else None, "periodo": pname},
                                           muestra=f"{n_prev + 1} años con el periodo completo hasta el día {off}",
                                           calidad="reanálisis" if fam == "capitales" else "validado", serie=SERIE_TXT[fam],
                                           invalidar=("ERA5 consolida con ~6 días de retraso; una celda de ~25 km no es la estación: puede no ver tormentas locales"
                                                      if fam == "capitales" else "dato validado por AEMET con retraso; cambios de emplazamiento; días que faltan en el periodo"),
                                           T=n_prev + 1, pob=C.pob_cap.get(ent) or C.pob_prov.get(C.provincia(ent)[0]), cola=cola,
                                           avance=min(1.0, off / LARGO[per]),
                                           empate=abs(acum - mejor) < (0.1 if var != "prec" else max(0.5, 0.01 * abs(mejor)))))
                    break

def r03(C, fam, D, desde, hasta, salida, vigentes):
    ref = C.R[fam]
    serie_reg = "capital_era5" if fam == "capitales" else "estacion_aemet"
    curso = ref["rachas_en_curso"]
    for ent, dd in D.items():
        if ent not in curso:
            continue
        for tipo in ("seco", "calor", "frio", "tropical", "helada"):
            u = C.u(f"R03:{serie_reg}:{tipo}")
            if not u:
                continue
            a, L = u
            largo = curso[ent].get(tipo, 0)
            emit_racha = False
            for k in range((C.hasta_ref - C.hasta_ref).days, (hasta - C.hasta_ref).days):
                d = C.hasta_ref + timedelta(days=k + 1)
                v = dd.get(d)
                dia = ref["dia"].get(ent, {}).get(str(d))
                if v is None or dia is None:
                    largo, emit_racha = 0, False
                    continue
                tx, tn, p = v
                ok = {"seco": p is not None and p < 1, "calor": tx is not None and dia[0] is not None and tx - dia[0] >= a,
                      "frio": tx is not None and dia[0] is not None and tx - dia[0] <= -a, "tropical": tn is not None and tn >= 20,
                      "helada": tn is not None and tn <= 0}[tipo]
                largo = largo + 1 if ok else 0
                if not ok:
                    emit_racha = False
                    continue
                top = ref["rachas_top5"].get(ent, {}).get(tipo, {}).get(str(d))
                n_prev = (ref["dia"].get(ent, {}).get(str(d)) or [0] * 7)[6] or 0
                if d < desde or emit_racha or not top or largo < L or largo <= top[0][0] or n_prev < comun.MIN_ANIOS_PREVIOS:
                    continue
                emit_racha = True
                if d == desde and largo > L + 1:   # ya era récord antes de la ventana: el detector real la habría dado antes
                    vigentes.append((ent, "racha", tipo))
                    continue
                nom = C.nom.get(ent, ent).title() if fam == "estaciones" else C.nom.get(ent, ent)
                que = {"seco": "días seguidos sin un día de lluvia de 1 mm", "calor": f"días seguidos con la máxima {a} °C o más por encima de lo normal",
                       "frio": f"días seguidos con la máxima {a} °C o más por debajo de lo normal", "tropical": "noches tropicales seguidas",
                       "helada": "días seguidos de helada"}[tipo]
                n_prev = ref["dia"][ent][str(d)][6]
                tit = f"{'La estación de AEMET de ' if fam == 'estaciones' else ''}{nom} lleva {largo} {que}: nunca había habido una racha así un {fd(d)} en {n_prev} años{'' if fam == 'estaciones' else ' (reanálisis)'}"
                salida.append(hallazgo(C, regla="R03", variante=f"{serie_reg}:{tipo}", tipo="racha", ent=ent, fecha=d, indicador=tipo,
                                       titular=tit, dato=f"{largo} días; la más larga en curso un {fd(d)} hasta ahora: {top[0][0]} ({top[0][1]})",
                                       cifra={"dias": largo}, comparacion={"puesto": 1, "de": n_prev + 1, "anterior": top[0], "periodo": f"racha a {d}"},
                                       muestra=f"{n_prev} años con dato ese día", calidad="reanálisis" if fam == "capitales" else "validado",
                                       serie=SERIE_TXT[fam], cola=tipo, T=n_prev + 1, pob=C.pob_cap.get(ent),
                                       invalidar="días sin dato rompen la racha; en reanálisis, la lluvia de celda puede no coincidir con el pluviómetro"))

def r08(C, fam, D, desde, hasta, salida):
    # 25-11-2026 · R08 usa umbrales absolutos (0, 20 y 30 °C): sobre el reanálisis de celda no se publica. Solo estación de AEMET.
    # (Murcia «día de 30 °C más tardío» y Palma «noche tropical más tardía» del 25-11 salían de la celda ERA5.)
    if fam == "capitales":
        return
    ref = C.R[fam]
    serie_reg = "capital_era5" if fam == "capitales" else "estacion_aemet"
    for ent, dd in D.items():
        fe = ref["fechas_extremas"].get(ent, {})
        tmp = ref["estado"].get(ent, {}).get("temporada", {})
        helada = tmp.get("primera_helada")
        for k in range((hasta - C.hasta_ref).days):
            d = C.hasta_ref + timedelta(days=k + 1)
            v = dd.get(d)
            if v is None:
                continue
            tx, tn, p = v
            off = (d - date(d.year - (d.month < 7), 7, 1)).days
            doy = d.timetuple().tm_yday
            n_anios = (fe.get("o") or fe.get("tn") or {}).get("n")
            casos = []
            if "o" in fe and helada is None and tn is not None and tn <= 0:
                helada = str(d)
                if off < fe["o"]["min"] and C.u(f"R08:{serie_reg}:helada_temprana") is not None:
                    casos.append(("helada_temprana", f"primera helada del otoño más temprana de la serie", round(fe["o"]["media"] - off)))
            if "o" in fe and helada is None and off == fe["o"]["max"] + 1 and fe["o"]["pct_con_dato"] >= 0.8:
                casos.append(("otono_sin_helada", "nunca había llegado esta fecha sin una helada en el otoño", round(off - fe["o"]["media"])))
            if "tn" in fe and doy >= 227 and tn is not None and tn >= 20 and doy > fe["tn"]["max"]:
                casos.append(("tropical_tardia", "la noche tropical más tardía de la serie", round(doy - fe["tn"]["media"])))
            if "cx" in fe and doy >= 227 and tx is not None and tx >= 30 and doy > fe["cx"]["max"]:
                casos.append(("calor_tardio", "el día de 30 °C más tardío de la serie", round(doy - fe["cx"]["media"])))
            for t, frase, dias in casos:
                if d < desde or C.u(f"R08:{serie_reg}:{t}") is None:
                    continue
                if t in ("tropical_tardia", "calor_tardio"):
                    fe[{"tropical_tardia": "tn", "calor_tardio": "cx"}[t]]["max"] = doy   # una vez: la siguiente ya no es «más tardía» que esta
                nom = C.nom.get(ent, ent).title() if fam == "estaciones" else C.nom.get(ent, ent)
                tit = f"{'La estación de AEMET de ' if fam == 'estaciones' else ''}{nom}: {frase} ({fd(d)}, {dias} días más {'pronto' if t == 'helada_temprana' else 'tarde'} que la media)"
                salida.append(hallazgo(C, regla="R08", variante=f"{serie_reg}:{t}", tipo="primera_vez_desde", ent=ent, fecha=d, indicador=t,
                                       titular=tit, dato=f"{fd(d)}; media de la serie a {dias} días", cifra={"fecha": str(d), "dias_frente_media": dias},
                                       comparacion={"puesto": 1, "de": n_anios, "periodo": f"temporada {d.year}"}, muestra=f"{n_anios} años",
                                       calidad="reanálisis" if fam == "capitales" else "validado", serie=SERIE_TXT[fam], T=n_anios,
                                       cola={"helada_temprana": "helada", "otono_sin_helada": "calor", "tropical_tardia": "tropical", "calor_tardio": "calor"}[t],
                                       pob=C.pob_cap.get(ent), invalidar="un día sin dato puede esconder la fecha real; el umbral es fijo (0, 20 y 30 °C)"))

def r09(C, fam, D, desde, hasta, salida):
    ref = C.R[fam]
    serie_reg = "capital_era5" if fam == "capitales" else "estacion_aemet"
    mf = C.u(f"R09:{serie_reg}:fecha_tmax", 3.0)
    mn = C.u(f"R09:{serie_reg}:fecha_tmin_alta", 3.0)
    mm = C.u(f"R09:{serie_reg}:mes_tmax", 0.0)
    vistos = set()
    for ent, dd in D.items():
        for d, (tx, tn, p) in sorted(dd.items()):
            if d < desde:
                continue
            dia = ref["dia"].get(ent, {}).get(str(d))
            rm = ref["record_mes"].get(ent, {}).get(str(d.month))
            nom = C.nom.get(ent, ent).title() if fam == "estaciones" else C.nom.get(ent, ent)
            quien = f"{'La estación de AEMET de ' if fam == 'estaciones' else ''}{nom}"
            val = lambda v: f" ({f1(v)} °C)" if fam == "estaciones" else ""
            if dia and (dia[6] or 0) < comun.MIN_ANIOS_PREVIOS:
                dia = None
            if rm and (rm[2] or 0) < comun.MIN_ANIOS_PREVIOS:
                rm = None
            if dia and tx is not None and dia[3] and tx - dia[3][0] >= mf:
                salida.append(hallazgo(C, regla="R09", variante=f"{serie_reg}:fecha_tmax", tipo="record_fecha", ent=ent, fecha=d, indicador="tmax",
                    titular=(f"{quien} bate por {f1(tx - dia[3][0])} °C su máxima más alta para un {fd(d)}{val(tx)}" if fam == "estaciones" else
                             f"{nom}: la máxima más alta para un {fd(d)} en {dia[6] + 1} años de reanálisis ERA5, {f1(tx - dia[3][0])} °C por encima del récord anterior ({dia[3][1]})"),
                    dato=f"récord anterior {dia[3][1]}",
                    cifra={"valor": tx if fam == "estaciones" else None, "margen": round(tx - dia[3][0], 1)}, comparacion={"puesto": 1, "de": dia[6] + 1, "anterior": dia[3], "periodo": str(d)},
                    muestra=f"{dia[6]} años", calidad="reanálisis" if fam == "capitales" else "validado", serie=SERIE_TXT[fam], T=dia[6] + 1, cola="calor",
                    pob=C.pob_cap.get(ent), invalidar="un dato erróneo de un día da récords falsos: contrastar con la estación vecina"))
            if dia and tn is not None and dia[4] and tn - dia[4][0] >= mn:
                salida.append(hallazgo(C, regla="R09", variante=f"{serie_reg}:fecha_tmin_alta", tipo="record_fecha", ent=ent, fecha=d, indicador="tmin_alta",
                    titular=(f"{quien} tiene la noche más cálida para un {fd(d)}, {f1(tn - dia[4][0])} °C por encima del récord{val(tn)}" if fam == "estaciones" else
                             f"{nom}: la noche más cálida para un {fd(d)} en {dia[6] + 1} años de reanálisis ERA5, {f1(tn - dia[4][0])} °C por encima del récord anterior ({dia[4][1]})"),
                    dato=f"récord anterior {dia[4][1]}",
                    cifra={"valor": tn if fam == "estaciones" else None, "margen": round(tn - dia[4][0], 1)}, comparacion={"puesto": 1, "de": dia[6] + 1, "anterior": dia[4], "periodo": str(d)},
                    muestra=f"{dia[6]} años", calidad="reanálisis" if fam == "capitales" else "validado", serie=SERIE_TXT[fam], T=dia[6] + 1, cola="noches",
                    pob=C.pob_cap.get(ent), invalidar="nubosidad o viento nocturno puntuales; contrastar con estación vecina"))
            for i, var, v in ((0, "tmax", tx), (1, "tmin_alta", tn)):
                if rm and v is not None and v - rm[i][0] > mm and (ent, d.month, var) not in vistos:
                    vistos.add((ent, d.month, var))
                    rm[i] = [v, d.year]
                    q = "máxima" if var == "tmax" else "mínima"
                    salida.append(hallazgo(C, regla="R09", variante=f"{serie_reg}:mes_{var}", tipo="record_mes", ent=ent, fecha=d, indicador=f"mes_{var}",
                        titular=(f"{quien}: la {q} más alta de cualquier {MESES[d.month - 1]} en {rm[2]} años{val(v)}" if fam == "estaciones" else
                                 f"{nom}: la {q} más alta de cualquier {MESES[d.month - 1]} en {rm[2]} años de reanálisis ERA5"),
                        dato="récord del mes",
                        cifra={"valor": v if fam == "estaciones" else None}, comparacion={"puesto": 1, "de": rm[2], "periodo": MESES[d.month - 1]},
                        muestra=f"{rm[2]} {MESES[d.month - 1]}s", calidad="reanálisis" if fam == "capitales" else "validado", serie=SERIE_TXT[fam],
                        T=rm[2] * 30, cola="calor" if var == "tmax" else "noches", pob=C.pob_cap.get(ent), invalidar="dato de un solo día: contrastar"))

def r05_capitales(C, D, desde, hasta, salida):
    k, alto, bajo = C.u("R05:capital_era5", [5, 150, 50])
    ref = C.R["capitales"]
    ult = None
    for i in range((hasta - desde).days + 1):
        d = desde + timedelta(days=i)
        hi, lo = [], []
        for cap, est in ref["estado"].items():
            prov = C.cap_prov.get(cap)
            nor = C.R["provincias"]["hidro_normal"].get(prov, {}).get(str(d))
            if not nor or nor < 15 or "hidro" not in est:
                continue
            s = (est["hidro"]["prec"][0] or 0) if date.fromisoformat(est["hidro"]["desde"]) <= d else 0
            fal = False
            for j in range(1, (d - C.hasta_ref).days + 1):
                v = D.get(cap, {}).get(C.hasta_ref + timedelta(days=j))
                if v is None or v[2] is None:
                    fal = True
                    break
                s += v[2]
            if fal:
                continue
            pct = 100 * s / nor
            (hi if pct >= alto else lo if pct <= bajo else []).append((prov, pct))
        if len(hi) >= k and len(lo) >= k and (ult is None or (d - ult).days > 30):
            ult = d
            mx, mn = max(hi, key=lambda x: x[1]), min(lo, key=lambda x: x[1])
            salida.append(hallazgo(C, regla="R05", variante="capital_era5", tipo="episodio", ent="pais:es", fecha=d, indicador="contraste_era5",
                territorio="España", ambito="nacional", titular=f"El año hidrológico parte España en dos: {len(hi)} capitales con más del {alto} % de su lluvia normal y {len(lo)} con menos del {bajo} % (reanálisis)",
                dato=f"máximo {C.nom.get(mx[0])} {round(mx[1])} %, mínimo {C.nom.get(mn[0])} {round(mn[1])} %", cifra={"alto": len(hi), "bajo": len(lo)},
                comparacion={"periodo": str(d)}, muestra="52 capitales, normal 1991-2020", calidad="reanálisis", serie="ERA5 en la celda de cada capital",
                T=None, pob=None, invalidar="la celda no ve tormentas locales (Huelva: el reanálisis da lluvia que la estación no midió)"))

def r07(C, D, desde, hasta, salida):
    ref = C.R["capitales"]
    pc, ps = C.u("R07:calor_sequia", [0.9, 0.1])
    ult = {}
    for cap, est in ref["estado"].items():
        u89 = est.get("ult89")
        if not u89:
            continue
        tx, pr = list(u89["tmax"]), list(u89["prec"])
        for j in range(1, (hasta - C.hasta_ref).days + 1):
            d = C.hasta_ref + timedelta(days=j)
            v = D.get(cap, {}).get(d)
            tx.append(v[0] if v else None)
            pr.append(v[2] if v else None)
            w_t, w_p = [x for x in tx[-90:] if x is not None], [x for x in pr[-90:] if x is not None]
            q = ref.get("calor_sequia_p90_p10", {}).get(cap, {}).get(str(d))
            if d < desde or not q or len(w_t) < 85 or len(w_p) < 85:
                continue
            t90, p90 = sum(w_t) / len(w_t), sum(w_p)
            if t90 >= q[0] and p90 <= q[1] and (cap not in ult or (d - ult[cap]).days > 30):
                ult[cap] = d
                salida.append(hallazgo(C, regla="R07", variante="calor_sequia", tipo="compuesto", ent=cap, fecha=d, indicador="calor_sequia",
                    titular=f"{C.nom.get(cap)}: los últimos 90 días han sido de los más cálidos y a la vez de los más secos de su serie para esta fecha (reanálisis)",
                    dato=f"máxima de 90 días por encima del percentil 90 y lluvia por debajo del 10 para el {fd(d)}", cifra=None,
                    comparacion={"percentiles": [90, 10], "periodo": f"90 días hasta {d}"}, muestra="86 años", calidad="reanálisis",
                    serie=SERIE_TXT["capitales"], T=10, pob=C.pob_cap.get(cap), cola="seco", invalidar="dos percentiles de celda; la lluvia de 90 días puede depender de un solo día"))
    a, p = C.u("R07:mar_y_torrencial", [0.5, 0.995])
    v = (leer_json(DOCS / "dana" / "mediterraneo_historico.json", {}) or {}).get("v", {})
    nor = C.R["global"]["sst_normal_mediterraneo"]
    p995 = C.R["global"]["prec_p995_capitales_mediterraneas"]
    ult = None
    for i in range((hasta - desde).days + 1):
        d = desde + timedelta(days=i)
        sst = [(v.get(str(x)), nor.get(str(x))) for x in (d, d - timedelta(days=1))]
        an = next((s - n for s, n in sst if s is not None and n is not None), None)
        if an is None or an < a:
            continue
        caps = [(c, D.get(c, {}).get(d, (None, None, None))[2]) for c in p995]
        caps = [(c, mm) for c, mm in caps if mm is not None and mm >= p995[c] and mm >= 30]
        if caps and (ult is None or (d - ult).days > 3):
            ult = d
            salida.append(hallazgo(C, regla="R07", variante="mar_y_torrencial", tipo="compuesto", ent="pais:es" if len(caps) > 1 else caps[0][0], fecha=d,
                indicador="mar_y_torrencial", territorio="Mediterráneo", ambito="nacional",
                titular=f"Mediterráneo {f1(an)} °C por encima de lo normal y lluvia de las de un día cada 200 en {', '.join(C.nom.get(c) for c, _ in caps)}",
                dato="OISST caja 36,5-41,5 N / 1,5 W-5 E; lluvia de celda ERA5", cifra={"anomalia_sst": round(an, 2)}, comparacion={"periodo": str(d)},
                muestra="OISST desde 1981; ERA5 desde 1940", calidad="reanálisis + OISST", serie="NOAA OISST y ERA5", T=0.55, pob=None,
                invalidar="coincidencia no es causa; la anomalía del mar es de toda la caja"))

def r_monitor(C, rows, estado, desde, hasta, salida):
    niv, emb = C.u("R04:monitor", [3, 65])
    dentro, cont = set(estado.get("dentro", [])), set(estado.get("cont", []))
    nhum = C.u("R06:spi6_era5", [-1.5, 700])[1]
    porf = defaultdict(list)
    for e, f, n, s6, ep, hp, ds in rows:
        porf[f].append((e, n, s6, ep, hp))
    ult5 = date.fromisoformat(estado["ult5"]) if estado.get("ult5") else None
    for f in sorted(porf):
        nuevos = [x for x in porf[f] if x[1] is not None and niv <= x[1] <= 4 and (x[3] or 0) >= emb and x[0] not in dentro]
        for x in nuevos:
            dentro.add(x[0])
        if nuevos:
            todos = [x for x in porf[f] if x[1] is not None and niv <= x[1] <= 4 and (x[3] or 0) >= emb]
            nac = len(todos) >= 3
            lista = ", ".join(f"{C.nom.get(x[0])} (SPI-6 {f1(x[2]).replace('-', '−')}; embalses {round(x[3])} %)" for x in sorted(todos, key=lambda x: x[2])[:5])
            salida.append(hallazgo(C, regla="R04", variante="monitor", tipo="episodio", ent="pais:es" if nac else todos[0][0], fecha=f,
                indicador="sequia_escondida", territorio="España" if nac else C.nom.get(todos[0][0]), ambito="nacional" if nac else "provincial",
                titular=f"{len(todos)} provincias en sequía severa o extrema con los embalses por encima del {emb} %: el agua es del año pasado",
                dato=lista, cifra={"provincias": len(todos)}, comparacion={"periodo": str(f)}, muestra="52 provincias, Monitor de sequía",
                calidad="provisional", serie="Monitor de sequía del observatorio (SPI con estaciones AEMET) y embalses MITECO",
                T=None, pob=sum(C.pob_prov.get(x[0], 0) for x in todos), cola="sequia",
                invalidar="el SPI de un mes cerrado se revisa (Cádiz −2,23 → −1,84): citar el nivel, no el decimal; el % de embalse es de la provincia, no de quien la abastece",
                extra={"miembros": [x[0] for x in todos]}))
        for x in porf[f]:   # R06 sequía en lugar húmedo
            na = C.R["provincias"]["normal_anual_mm"].get(x[0])
            if x[1] is not None and 3 <= x[1] <= 4 and na and na >= nhum and x[0] not in cont:
                cont.add(x[0])
                salida.append(hallazgo(C, regla="R06", variante="monitor", tipo="episodio", ent=x[0], fecha=f, indicador="sequia_lugar_humedo",
                    titular=f"Sequía {'extrema' if x[1] == 4 else 'severa'} en {C.nom.get(x[0])}, donde lo normal son {f0(na)} mm al año (SPI-6 {f1(x[2]).replace('-', '−')})",
                    dato=f"nivel {x[1]}; año hidrológico al {round(x[4] or 0)} %", cifra={"spi6": x[2], "nivel": x[1]},
                    comparacion={"normal_anual_mm": na, "periodo": str(f)}, muestra="Monitor de sequía", calidad="provisional",
                    serie="Monitor de sequía del observatorio", T=None, pob=C.pob_prov.get(x[0]), cola="sequia",
                    invalidar="SPI sobre pocas estaciones; revisiones del mes cerrado"))
        hi = [x for x in porf[f] if (x[4] or 0) >= 150]
        lo = [x for x in porf[f] if x[4] is not None and x[4] <= 50]
        k, alto, bajo = C.u("R05:monitor", [5, 175, 40])
        hi = [x for x in porf[f] if (x[4] or 0) >= alto]
        lo = [x for x in porf[f] if x[4] is not None and x[4] <= bajo]
        if len(hi) >= k and len(lo) >= k and (ult5 is None or (f - ult5).days > 30):
            ult5 = f
            mx = max(hi, key=lambda x: x[4])
            mn = min(lo, key=lambda x: x[4])
            salida.append(hallazgo(C, regla="R05", variante="monitor", tipo="episodio", ent="pais:es", fecha=f, indicador="contraste",
                territorio="España", ambito="nacional", titular=f"España, partida en dos: {len(hi)} provincias por encima del {alto} % de su lluvia y {len(lo)} por debajo del {bajo} % en el año hidrológico ({C.nom.get(mx[0])} {round(mx[4])} %, {C.nom.get(mn[0])} {round(mn[4])} %)",
                dato=f"{len(hi)} frente a {len(lo)} provincias", cifra={"alto": len(hi), "bajo": len(lo)}, comparacion={"periodo": str(f)},
                muestra="52 provincias", calidad="provisional", serie="Monitor de sequía (% del año hidrológico, estaciones AEMET)", T=None, pob=None,
                invalidar="los porcentajes de principio de año hidrológico son muy sensibles a una sola tormenta"))
    if porf:
        uf = max(porf)
        estado["dentro"] = sorted(x[0] for x in porf[uf] if x[1] is not None and niv <= x[1] <= 4 and (x[3] or 0) >= emb)
        estado["cont"] = sorted(x[0] for x in porf[uf] if x[0] in cont and x[1] is not None and 3 <= x[1] <= 4)
        estado["ult5"] = str(ult5) if ult5 else None



def r13(C, hielo, desde, hasta, salida):
    """R13 hielo marino: la extensión del día es la más baja para la fecha desde 1978 (NSIDC, docs/deshielo.json). Una historia por racha."""
    h = C.R["global"]["hielo_minimo"]
    for polo, ent in (("arctic", "glo:arctic"), ("antarctic", "glo:antarctic")):
        P = (hielo or {}).get(polo) or {}
        ult = None
        for doy, v in sorted(P.get("serie") or []):
            f = date(hasta.year, 1, 1) + timedelta(days=int(doy) - 1)
            if not (desde <= f <= hasta):
                continue
            r = h.get(ent, {}).get(str(f))
            if r and v is not None and v < r[0] - (C.u(f"R13:{ent}") or 0):
                if ult is not None and (f - ult).days <= 7:
                    ult = f
                    continue
                ult = f
                salida.append(hallazgo(C, regla="R13", variante=ent, tipo="record_fecha", ent=ent, fecha=f, indicador="hielo",
                    territorio="Ártico" if ent.endswith("arctic") else "Antártida", ambito="global",
                    titular=f"El hielo marino {'del Ártico' if ent.endswith(':arctic') else 'antártico'} marca el {fd(f)} su extensión más baja para esa fecha desde 1978: {f1(v)} millones de km²",
                    dato=f"anterior mínimo {f1(r[0])} ({r[1]})", cifra={"valor": round(v, 3)}, comparacion={"puesto": 1, "de": r[2] + 1, "anterior": r[:2], "periodo": str(f)},
                    muestra=f"{r[2]} años", calidad="validado", serie="NSIDC Sea Ice Index v4", T=r[2] + 1, pob=None,
                    invalidar="la extensión diaria se revisa en días posteriores; NSIDC publica su propia serie"))
            elif ult is not None and (f - ult).days > 7:
                ult = None


def filas_monitor(docs: Path, desde: date, hasta: date):
    """Una fila del Monitor por provincia (docs/sequia/index.json) con la fecha de su generación."""
    idx = leer_json(docs / "sequia" / "index.json", {}) or {}
    try:
        f = date.fromisoformat(str(idx.get("generado"))[:10])
    except Exception:
        return [], None
    rows = []
    for p in idx.get("provincias", []):
        ficha = leer_json(docs / "sequia" / f"{p['slug']}.json", {}) or {}
        cod = ficha.get("cod")
        if not cod or p.get("nivel") is None:
            continue
        rows.append((f"prov:{cod}", f, p["nivel"], p.get("spi6"), p.get("embalses_pct"), p.get("hidro_pct"), p.get("dias_sin_lluvia")))
    if not (desde <= f <= hasta):
        return [], f
    return rows, f


# ------------------------------------------------------------------------------------------ selección y salida
def hash_cifra(h):
    return json.dumps(h.get("cifra"), sort_keys=True, default=str)


def slug_id(*partes):
    import re
    import unicodedata
    crudo = unicodedata.normalize("NFKD", "-".join(str(p) for p in partes)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", crudo).strip("-")


def una_por_provincia(C, pub):
    """Primero la estación de AEMET (25-11-2026). Una historia de reanálisis de capital (R01, R03, R08, R09) solo se publica si su provincia
    no tiene estación de AEMET con ≥ ANIOS_ESTACION años: si la tiene y la estación no ha disparado, el reanálisis no basta. Si la estación
    ha dado la misma historia, manda la estación (como hasta ahora)."""
    est = [h for h in pub if h["variante"].split(":")[0] == "estacion_aemet"]
    quitadas = []
    for h in list(pub):
        if h["variante"].split(":")[0] != "capital_era5" or h["regla"] not in ("R01", "R03", "R08", "R09"):
            continue
        prov = C.provincia(h["ent_id"])[0]
        larga = C.est_larga.get(prov)
        if larga:
            quitadas.append({"id": h["id"], "motivo": f"reanálisis: la provincia tiene estación de AEMET de {larga[1]} años "
                                                       f"({C.nom.get(larga[0], larga[0])}); manda la estación"})
            pub.remove(h)
            continue
        clave = h["variante"].split(":", 1)[1]
        prov = C.provincia(h["ent_id"])[0]
        for e in est:
            if e["regla"] == h["regla"] and e["variante"].split(":", 1)[1] == clave and C.provincia(e["ent_id"])[0] == prov \
                    and abs((date.fromisoformat(e["fecha_dato"]) - date.fromisoformat(h["fecha_dato"])).days) <= 5:
                quitadas.append({"id": h["id"], "motivo": f"misma historia en la estación de AEMET de la provincia ({e['territorio']}); manda la estación"})
                pub.remove(h)
                break
    return quitadas


def agregar_nacional(C, pub):
    """Misma variante, ≥ 3 territorios a ≤ 3 días → un hallazgo nacional con miembros."""
    grupos = defaultdict(list)
    for h in pub:
        if h["ambito"] == "provincial":
            grupos[h["variante"]].append(h)
    agregados = []
    for v, hs in grupos.items():
        hs.sort(key=lambda h: h["fecha_dato"])
        bloque = []
        for h in hs + [None]:
            if h and (not bloque or (date.fromisoformat(h["fecha_dato"]) - date.fromisoformat(bloque[0]["fecha_dato"])).days <= 3):
                bloque.append(h)
                continue
            if len({x["ent_id"] for x in bloque}) >= 3:
                b = sorted(bloque, key=lambda x: -x["fuerza"])
                nombres = [x["territorio"] for x in b]
                pz = puntuar(b[0]["tipo"], "nacional", EXCLUSIVO, 1.0, T=b[0]["fuerza_detalle"].get("T_anios"),
                             pob=sum(C.pob_cap.get(x["ent_id"], 0) for x in b), citabilidad=b[0]["citabilidad"],
                             avance=(b[0]["fuerza_detalle"]["r_avance"] - 0.7) / 0.3)
                agregados.append({**b[0], "ambito": "nacional", "territorio": "España", "provincia": None, "fuerza": pz["fuerza"], "fuerza_detalle": pz,
                                  "titular": f"{len(b)} lugares a la vez — {b[0]['titular']} (también {', '.join(nombres[1:6])}{'…' if len(b) > 6 else ''})",
                                  "miembros": [x["ent_id"] for x in b], "agregado": True,
                                  "clave": {**b[0]["clave"], "territorio": "pais:es"}})
                for x in b:
                    x["en_agregado"] = True
            bloque = [h] if h else []
    return agregados


VIDA_DIAS = 10


def ejecutar(raiz: Path = RAIZ, hoy: date | None = None, ref: Path | None = None, escribir: bool = True, ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc).replace(microsecond=0)
    hoy = hoy or ahora.date()
    docs = raiz / "docs"
    ref = ref or docs / "prensa" / "referencias"
    salida_dir = docs / "prensa" / "almacen"
    est = {"generado": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"), "estado": "ok", "mensaje": "", "referencias": {}, "datos": {},
           "reglas_no_evaluadas": [
               {"reglas": "R02, R10 (municipios)", "motivo": "usan ERA5-Land por celda, que solo está en el almacén del Air"},
               {"reglas": "R11, R12", "motivo": "previsión guardada y revisiones: las evalúa el Air (parte interno)"}],
           "sin_lista_de_calidad": "calidad.py corre en el Air: aquí no hay lista de datos sospechosos de las estaciones",
           "n_candidatos": 0, "n_hoy": 0, "descartados": []}
    resultado = {"estado": est, "hallazgos": [], "candidatos": [], "internos": []}

    def cerrar():
        if escribir:
            ESTADO_P = docs / "estado" / "almacen.json"
            ESTADO_P.parent.mkdir(parents=True, exist_ok=True)
            ESTADO_P.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
            # 25-11-2026: el parte interno deja de publicarse en docs/ (era público en Pages). Se escribe fuera de docs/, sin commit, y el
            # workflow lo envía a WordPress (scripts/sala/parte_interno_wp.py); lo pinta el shortcode [cg_parte_interno] solo a administradores.
            priv = raiz / "salida_privada"
            priv.mkdir(parents=True, exist_ok=True)
            (priv / "parte_interno.json").write_text(json.dumps(construir_interno(resultado, docs, ahora), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return resultado

    try:
        C = Contexto(ref)
    except Exception as e:
        est.update(estado="sin_referencias", mensaje=f"no se pudieron leer las referencias ({str(e)[:120]}): el detector no emite nada")
        return cerrar()
    est["referencias"] = {"calculado_el": C.indice.get("calculado_el"), "datos_hasta": str(C.hasta_ref), "valido_desde": str(C.valido_desde),
                          "valido_hasta": str(C.valido), "dias_restantes": (C.valido - hoy).days}
    if hoy > C.valido:
        est.update(estado="referencias_caducadas",
                   mensaje=f"las referencias valían hasta el {C.valido}: el detector no emite nada hasta que se refresquen desde el Air")
        return cerrar()
    desde, hasta = C.hasta_ref + timedelta(days=1), min(hoy, C.valido)
    DATOS_DESCARTADOS.clear()
    salida, vigentes = [], []
    ultimo = {}
    for fam in ("capitales", "estaciones"):
        D = diarios(raiz, fam, list(C.R[fam]["estado"].keys()), desde, hasta)
        ultimo[fam] = max((max(v) for v in D.values() if v), default=None)
        est["datos"][f"{fam}_hasta"] = str(ultimo[fam]) if ultimo[fam] else None
        r01(C, fam, D, desde, hasta, salida, vigentes)
        r03(C, fam, D, desde, hasta, salida, vigentes)
        r08(C, fam, D, desde, hasta, salida)
        r09(C, fam, D, desde, hasta, salida)
        if fam == "capitales":
            r05_capitales(C, D, desde, hasta, salida)
            r07(C, D, desde, hasta, salida)
    est_reglas = leer_json(salida_dir / "estado_reglas.json", {}) or {}
    rows, fm = filas_monitor(docs, desde, hasta)
    est["datos"]["monitor"] = str(fm) if fm else None
    if rows:
        r_monitor(C, rows, est_reglas, desde, hasta, salida)
    hielo = leer_json(docs / "deshielo.json", {})
    est["datos"]["hielo"] = ((hielo or {}).get("arctic") or {}).get("fecha")
    r13(C, hielo, desde, hasta, salida)
    for clave, lim in (("capitales_hasta", 12), ("estaciones_hasta", 25)):
        v = est["datos"].get(clave)
        if not v or (hoy - date.fromisoformat(v)).days > lim:
            est["estado"] = "datos_atrasados"
            est["mensaje"] = (est["mensaje"] + f" {clave.split('_')[0]}: último dato {v or 'ninguno'}.").strip()
    est["datos_descartados"] = list(DATOS_DESCARTADOS)
    if DATOS_DESCARTADOS:
        est["mensaje"] = (est["mensaje"] + f" {len(DATOS_DESCARTADOS)} valores imposibles o ficheros rotos saltados.").strip()
    for h in salida:
        h["id"] = slug_id("almacen", h["regla"], h["variante"], h["ent_id"], h["fecha_dato"])
    pub = [h for h in salida if h["destino"] == "publicable"]
    est["descartados"] += una_por_provincia(C, pub)
    agregados = agregar_nacional(C, pub)
    for a in agregados:
        a["id"] = slug_id("almacen", a["regla"], a["variante"], "agregado", a["fecha_dato"])
    # la lista del día: lo que sale hoy por primera vez (tope de MAX_DIARIAS), más lo que ya salió hoy en una pasada anterior
    emitidos = leer_json(salida_dir / "emitidos.json", {}) or {}
    cand = [h for h in pub + agregados if not h.get("en_agregado")]
    resultado["candidatos"] = cand
    hoy_s = str(hoy)
    ya_hoy = [h for h in cand if emitidos.get(h["id"], {}).get("primera_vez") == hoy_s]
    nuevos = []
    for h in cand:
        edad = (hoy - date.fromisoformat(h["fecha_dato"])).days
        if h["id"] in emitidos:
            continue
        if edad > VIDA_DIAS:
            est["descartados"].append({"id": h["id"], "motivo": f"dato de hace {edad} días: caducado"})
            continue
        previo = [x for x in emitidos.values() if x.get("variante") == h["variante"] and x.get("ent") == h["ent_id"]
                  and (hoy - date.fromisoformat(x["primera_vez"])).days <= 7]
        if any(x.get("cifra") == hash_cifra(h) for x in previo):
            est["descartados"].append({"id": h["id"], "motivo": "mismo titular que ayer sin cifra nueva"})
            continue
        h["_rank"] = h["fuerza"] * max(0.35, 1 - 0.07 * max(0, edad - 1))
        nuevos.append(h)
    nuevos.sort(key=lambda h: -h["_rank"])
    cupo = max(0, MAX_DIARIAS - len(ya_hoy))
    elegidos, resto = nuevos[:cupo], nuevos[cupo:]
    for h in resto:
        est["descartados"].append({"id": h["id"], "motivo": f"fuera del tope de {MAX_DIARIAS} historias al día (fuerza {h['fuerza']}); sigue disponible mientras no caduque"})
    for h in elegidos:
        emitidos[h["id"]] = {"primera_vez": hoy_s, "titular": h["titular"], "fecha_dato": h["fecha_dato"], "variante": h["variante"],
                             "ent": h["ent_id"], "cifra": hash_cifra(h)}
    limite = (hoy - timedelta(days=60)).isoformat()
    emitidos = {k: v for k, v in emitidos.items() if v["primera_vez"] >= limite}
    resultado["hallazgos"] = sorted(ya_hoy + elegidos, key=lambda h: -h["fuerza"])
    resultado["internos"] = [h for h in salida if h["destino"] != "publicable"]
    est["n_candidatos"], est["n_hoy"] = len(cand), len(resultado["hallazgos"])
    est["vigentes_al_empezar"] = len(vigentes)
    if escribir:
        salida_dir.mkdir(parents=True, exist_ok=True)
        (salida_dir / "emitidos.json").write_text(json.dumps(emitidos, ensure_ascii=False, indent=1), encoding="utf-8")
        (salida_dir / "estado_reglas.json").write_text(json.dumps(est_reglas, ensure_ascii=False, indent=1), encoding="utf-8")
        (salida_dir / "hoy.json").write_text(json.dumps({"generado": est["generado"], "hoy": hoy_s, "seleccionados": [h["id"] for h in resultado["hallazgos"]],
                                                         "hallazgos": cand}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return cerrar()


def construir_interno(res: dict, docs: Path, ahora: datetime) -> dict:
    """Parte interno (destinos interno y web): lo que evalúa el Air (previsión, avisos, revisiones) más los avisos del propio detector."""
    est = res["estado"]
    aire = {}      # lo del Air lo envía el propio Air a WordPress (meta cg_parte_interno_air); el shortcode junta las dos mitades
    avisos = []
    if est["estado"] != "ok":
        avisos.append({"nivel": "aviso" if est["estado"] == "datos_atrasados" else "error", "texto": f"detector del almacén: {est['estado']} · {est['mensaje']}"})
    ref = est.get("referencias") or {}
    if ref.get("dias_restantes") is not None and 0 <= ref["dias_restantes"] <= 7:
        avisos.append({"nivel": "aviso", "texto": f"las referencias caducan en {ref['dias_restantes']} días: refrescarlas desde el Air"})
    for d in (est.get("datos_descartados") or [])[:20]:
        avisos.append({"nivel": "aviso", "texto": f"dato descartado {d['ent']} {d.get('fecha')}: {', '.join(d['campos'])} {d.get('valores', d.get('error', ''))}"})
    for d in est.get("descartados", [])[:20]:
        avisos.append({"nivel": "info", "texto": f"descartado {d['id']}: {d['motivo']}"})
    return {"generado": est["generado"], "estado_detector": est["estado"], "avisos_detector": avisos, "air": aire,
            "nota": "Parte interno: no sale en /prensa/ ni en docs/. Lo del Air (acierto de modelos, avisos sin respaldo, revisiones, fallos de calidad) lo envía el Air a WordPress."}


# ------------------------------------------------------------------------------------------ enganche con hallazgos_prensa.py
def al_detector(M):
    """Fuente `almacen` de hallazgos_prensa.py: añade los hallazgos del día con el contrato actual (M = módulo hallazgos_prensa)."""
    res = ejecutar(RAIZ, hoy=M.HOY)
    est = res["estado"]
    if est["estado"] in ("referencias_caducadas", "sin_referencias"):
        M.descartar("almacen", "España", est["mensaje"])
    print(f"  almacén: {est['estado']} · {len(res['hallazgos'])} para hoy de {est.get('n_candidatos')} candidatos")
    for h in res["hallazgos"]:
        x = {k: v for k, v in h.items() if not k.startswith("_")}
        x["id_fijo"] = x.pop("id")
        x["exclusivo"] = EXCLUSIVO
        x["novedad"] = (x.get("fuerza_detalle") or {}).get("novedad", 1.0)
        x["limites"] = list(x.get("limites", [])) + [f"Cifra de la serie: {x.get('muestra')}. Qué podría invalidarla: {x.get('invalidar')}."]
        n0, d0 = len(M.hallazgos), len(M.descartes)
        M.anadir(x)
        if len(M.hallazgos) == n0:
            print(f"  almacén: {x['id_fijo']} NO entró en la cola: {[d['motivo'] for d in M.descartes[d0:]]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hoy", default="")
    ap.add_argument("--ref", default="")
    ap.add_argument("--raiz", default=str(RAIZ))
    ap.add_argument("--sin-escribir", action="store_true")
    a = ap.parse_args()
    res = ejecutar(Path(a.raiz), date.fromisoformat(a.hoy) if a.hoy else None, Path(a.ref) if a.ref else None, escribir=not a.sin_escribir)
    e = res["estado"]
    print(f"estado {e['estado']} · {e['n_candidatos']} candidatos · {e['n_hoy']} para hoy · {e.get('vigentes_al_empezar', 0)} ya vigentes · {e['mensaje']}")
    for h in res["hallazgos"]:
        print(f"  {h['fecha_dato']} [{h['fuerza']:5.1f}] {h['regla']} {h['ambito'][:4]} {h['titular'][:140]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
