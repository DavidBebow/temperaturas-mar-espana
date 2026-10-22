#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lluvia_diaria_crudo.py · la lluvia de CADA DIA en CADA pluviometro de AEMET, de 1991 a ayer.

Version 1.0.0 (22-10-2026) · calentamientoglobal.es

PARA QUE
Las fichas de lluvia necesitan comparar lo que lleva el ano hidrologico (desde el 1 de
octubre) con lo normal DEL MISMO PLUVIOMETRO, decir cuando cayo por ultima vez un episodio
como el de esta semana y dar los records de verdad, no los de una serie de diez anos.
Todo eso sale de una sola tabla: la lluvia diaria validada de todas las estaciones.

QUE BAJA
Valores climatologicos diarios de AEMET OpenData, todas las estaciones a la vez, en trozos de
15 dias (lo maximo que AEMET sirve de una vez). Solo se guarda la precipitacion.

DONDE LO DEJA
  archivo/lluvia_diaria/<anio>.json.gz   {"anio": 2025, "est": {"3195": [mm o null, ...]}}
                                         una lista por estacion, un valor por dia del ano
                                         natural (1 de enero = 0). null = sin dato.
  archivo/lluvia_diaria/estado.json      que trozos hay y cuando se pidieron.

COMO
- Siembra: los otonos (1 sep - 30 nov) de 1991 a 2025 ya estan bajados en
  archivo/otonio/crudo_otonios.json.gz. Se copian y esos trozos no se piden otra vez.
- Orden: del ano mas reciente al mas antiguo, para que lo que mas se usa llegue antes.
- Es reanudable: cada pasada sigue donde lo dejo la anterior y se para sola antes de
  LLUVIA_TOPE_MIN minutos, guardando lo hecho.
- Los trozos que acaban en los ultimos RECIENTES dias se vuelven a pedir cada RENOVAR_H horas:
  AEMET valida con retraso y a veces corrige.
- 'Ip' (inapreciable) = 0,0. 'Acum' / 'Varias' (lluvia de varios dias en una sola lectura)
  = null: no se puede repartir y no se inventa.

Sin dependencias: solo la biblioteca estandar.
"""
import gzip
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

VERSION = "1.0.0"
RAIZ = Path(__file__).resolve().parent.parent
DIR = RAIZ / "archivo" / "lluvia_diaria"
ESTADO = DIR / "estado.json"
CRUDO_OTONIOS = RAIZ / "archivo" / "otonio" / "crudo_otonios.json.gz"
BASE_AEMET = "https://opendata.aemet.es/opendata/api"

ANIO_INI = 1991
PASO = 15
RECIENTES = 40          # dias: los trozos que acaban dentro se refrescan
RENOVAR_H = float(os.environ.get("LLUVIA_RENOVAR_H", "6"))
TOPE_MIN = float(os.environ.get("LLUVIA_TOPE_MIN", "300"))
PAUSA = float(os.environ.get("LLUVIA_PAUSA", "3.0"))   # el API comparte cupo con otros flujos
T0 = time.time()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def queda_tiempo():
    return (time.time() - T0) / 60 < TOPE_MIN


# ------------------------------------------------------------------ AEMET

def _get(url, clave=None, timeout=120):
    cab = {"Accept": "application/json"}
    if clave:
        cab["api_key"] = clave
    req = urllib.request.Request(url, headers=cab)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def pide(ruta, clave, reintentos=6):
    """Dos pasos (metadatos con la URL de 'datos', luego los datos en ISO-8859-15).
    Devuelve la lista, [] si AEMET dice que no hay datos, o None si falla."""
    for intento in range(reintentos):
        try:
            meta = json.loads(_get(BASE_AEMET + ruta, clave).decode("utf-8", "replace"))
            est = meta.get("estado")
            if est == 404:
                return []
            if est != 200 or not meta.get("datos"):
                raise RuntimeError("estado %s: %s" % (est, meta.get("descripcion")))
            return json.loads(_get(meta["datos"]).decode("ISO-8859-15", "replace"))
        except Exception as e:  # noqa: BLE001
            espera = 10 * (intento + 1)
            log("  reintento %d en %d s (%s: %s)" % (intento + 1, espera, type(e).__name__, str(e)[:90]))
            time.sleep(espera)
    return None


def ruta_diarios(ini, fin):
    return ("/valores/climatologicos/diarios/datos/fechaini/%sT00:00:00UTC/fechafin/%sT23:59:59UTC/todasestaciones/"
            % (ini.isoformat(), fin.isoformat()))


def mm(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    b = s.lower()
    if b == "ip":
        return 0.0
    if b in ("acum", "varias"):
        return None
    try:
        x = float(s.replace(",", "."))
    except ValueError:
        return None
    return x if 0 <= x < 1500 else None


# ------------------------------------------------------------- ficheros

def dias_anio(a):
    return (date(a + 1, 1, 1) - date(a, 1, 1)).days


def ruta_anio(a):
    return DIR / ("%d.json.gz" % a)


def leer_anio(a):
    p = ruta_anio(a)
    if p.exists():
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:  # noqa: BLE001
            log("  %s ilegible (%s): se rehace" % (p.name, e))
    return {"anio": a, "est": {}}


def guardar_anio(a, d):
    DIR.mkdir(parents=True, exist_ok=True)
    d["anio"] = a
    d["version"] = VERSION
    tmp = ruta_anio(a).with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(d, f, separators=(",", ":"))
    os.replace(tmp, ruta_anio(a))


def leer_estado():
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"trozos": {}}


def guardar_estado(e):
    DIR.mkdir(parents=True, exist_ok=True)
    e["version"] = VERSION
    e["generado"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    os.replace(tmp, ESTADO)


def poner(d, idema, f, v):
    a = f.year
    lst = d["est"].get(idema)
    if lst is None:
        lst = d["est"][idema] = [None] * dias_anio(a)
    lst[(f - date(a, 1, 1)).days] = v


# ------------------------------------------------------------- trozos

def tramos(a, hasta):
    """Trozos de un ano natural, cortados en el 1 de septiembre y el 1 de diciembre para que
    el otono (sembrado) sea un trozo propio. Devuelve [(ini, fin, otono?)]."""
    out = []
    cortes = [(date(a, 1, 1), date(a, 8, 31), False),
              (date(a, 9, 1), date(a, 11, 30), True),
              (date(a, 12, 1), date(a, 12, 31), False)]
    for ini, fin, oto in cortes:
        fin = min(fin, hasta)
        while ini <= fin:
            f2 = min(ini + timedelta(days=PASO - 1), fin)
            out.append((ini, f2, oto))
            ini = f2 + timedelta(days=1)
    return out


def sembrar(estado, ayer):
    """Copia los otonos de crudo_otonios a los ficheros anuales (una vez por otono)."""
    if not CRUDO_OTONIOS.exists():
        log("Sin crudo_otonios: no se siembra nada.")
        return
    with gzip.open(CRUDO_OTONIOS, "rt", encoding="utf-8") as f:
        c = json.load(f)
    estado["inventario"] = c.get("inventario", estado.get("inventario", {}))
    por_anio = {}
    for idema, anios in c.get("datos", {}).items():
        for a, dias in anios.items():
            por_anio.setdefault(int(a), {})[idema] = dias
    sembrados = estado.setdefault("sembrado", [])
    for a in sorted(por_anio):
        if a in sembrados or date(a, 11, 30) > ayer:
            continue
        d = leer_anio(a)
        n = 0
        for idema, dias in por_anio[a].items():
            for i, v in dias.items():
                if v is None:
                    continue
                poner(d, idema, date(a, 9, 1) + timedelta(days=int(i)), float(v))
                n += 1
        guardar_anio(a, d)
        for ini, fin, oto in tramos(a, date(a, 12, 31)):
            if oto:
                estado["trozos"][ini.isoformat()] = {"fin": fin.isoformat(), "t": time.time(), "de": "otonio"}
        sembrados.append(a)
        log("  sembrado el otono de %d (%d valores)" % (a, n))
    guardar_estado(estado)


def main():
    clave = os.environ.get("AEMET_API_KEY", "").strip()
    hoy = datetime.now(timezone.utc).date()
    ayer = hoy - timedelta(days=1)
    estado = leer_estado()
    estado.setdefault("trozos", {})
    sembrar(estado, ayer)
    if not clave:
        log("Sin AEMET_API_KEY: solo siembra. Fin.")
        return

    pendientes = []
    for a in range(ayer.year, ANIO_INI - 1, -1):
        for ini, fin, oto in tramos(a, ayer):
            t = estado["trozos"].get(ini.isoformat())
            reciente = fin >= hoy - timedelta(days=RECIENTES)
            hecho = t is not None and t.get("fin") == fin.isoformat()
            viejo = hecho and reciente and time.time() - t.get("t", 0) > RENOVAR_H * 3600
            if not hecho or viejo:
                # los recientes primero: son los que la web ensena hoy
                pendientes.append((0 if reciente else 1, -ini.toordinal(), ini, fin))
    pendientes.sort()
    log("Trozos pendientes: %d" % len(pendientes))

    abiertos, pedidos, fallos = {}, 0, 0
    for _, _, ini, fin in pendientes:
        if not queda_tiempo():
            log("Tope de %.0f min: sigo en la proxima pasada." % TOPE_MIN)
            break
        filas = pide(ruta_diarios(ini, fin), clave)
        pedidos += 1
        time.sleep(PAUSA)
        if filas is None:
            fallos += 1
            log("  %s -> %s FALLO" % (ini, fin))
            if fallos >= 12:
                log("Demasiados fallos seguidos: AEMET no responde bien. Paro y guardo.")
                break
            continue
        fallos = 0
        a = ini.year
        d = abiertos.get(a) or leer_anio(a)
        abiertos[a] = d
        # un trozo que se vuelve a pedir sustituye lo que habia en esas fechas
        n_dias = (fin - ini).days + 1
        i0 = (ini - date(a, 1, 1)).days
        for lst in d["est"].values():
            for k in range(i0, i0 + n_dias):
                lst[k] = None
        n = 0
        for r in filas or []:
            idema = r.get("indicativo")
            v = mm(r.get("prec"))
            if not idema or v is None:
                continue
            try:
                f = date.fromisoformat(str(r.get("fecha", ""))[:10])
            except ValueError:
                continue
            if not (ini <= f <= fin):
                continue
            poner(d, idema, f, v)
            n += 1
        estado["trozos"][ini.isoformat()] = {"fin": fin.isoformat(), "t": time.time(), "n": n}
        if pedidos % 10 == 0:
            for aa, dd in abiertos.items():
                guardar_anio(aa, dd)
            guardar_estado(estado)
            log("  %d trozos · ultimo %s (%d valores) · %.0f min" % (pedidos, ini, n, (time.time() - T0) / 60))
    for aa, dd in abiertos.items():
        guardar_anio(aa, dd)
    total = sum(1 for a in range(ANIO_INI, ayer.year + 1) for ini, fin, o in tramos(a, ayer))
    hechos = sum(1 for a in range(ANIO_INI, ayer.year + 1) for ini, fin, o in tramos(a, ayer)
                 if (estado["trozos"].get(ini.isoformat()) or {}).get("fin") == fin.isoformat())
    estado["completo"] = hechos == total
    estado["avance"] = "%d/%d" % (hechos, total)
    guardar_estado(estado)
    log("Fin: %d trozos pedidos ahora · %d/%d hechos · %.0f min" % (pedidos, hechos, total, (time.time() - T0) / 60))


if __name__ == "__main__":
    main()
