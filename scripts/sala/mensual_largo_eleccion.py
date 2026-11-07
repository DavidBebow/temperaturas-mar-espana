#!/usr/bin/env python3
"""Elección de la estación de AEMET con serie mensual larga de cada capital (bloque B, 07-11-2026).

Entrada: mensual_largo_candidatas.json y mensual_largo_series.json (los dejan mensual_largo_inventario.py y
mensual_largo_descargar.py en la carpeta de David). Salida: mensual_largo_eleccion.json, la fusión en
archivo/aemet_mensual/mensuales.json.gz (solo estaciones nuevas) y la tabla ESTACION_MENSUAL_LARGA para atribucion.py.

Reglas (las del método, sin cambios):
  · año válido de un mes: tm_mes, tm_max y tm_min presentes (lo que exige Historia.mensual);
  · una estación sirve si TODOS los meses tienen >= 25 años válidos en 1961-1990 y en 1996-2025;
  · elegida: la de más años válidos (suma de los dos climas, contando el mes más corto); desempate: observatorio histórico
    frente a aeropuerto, y luego la más cercana;
  · homogeneidad: la misma función y el mismo umbral que «Tu capital» (tu_capital.homogeneidad: diferencia estación − ERA5
    por décadas desde 1979, salto > 0,5 °C = dudosa), más: sin salto > 0,7 °C respecto a la estación actual cuando hay
    >= 10 años de solapamiento (diferencia media de la segunda mitad del solape frente a la primera).
"""
import gzip
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "scripts" / "sala"))
import tu_capital as tc  # noqa: E402

ANTES, AHORA = (1961, 1990), (1996, 2025)
MIN_ANIOS = 25
SALTO_ACTUAL = 0.7
MIN_SOLAPE = 10
GZ = RAIZ / "archivo" / "aemet_mensual" / "mensuales.json.gz"


def validos(meses: dict) -> dict:
    """{mes: {año: (tm, tx, tn)}} con los años que tienen los tres valores."""
    out = {m: {} for m in range(1, 13)}
    for k, v in meses.items():
        a, m = int(k[:4]), int(k[5:7])
        if v[0] is not None and v[1] is not None and v[2] is not None:
            out[m][a] = (v[0], v[1], v[2])
    return out


def anios_por_clima(v: dict) -> tuple[int, int]:
    na = min(sum(1 for a in v[m] if ANTES[0] <= a <= ANTES[1]) for m in range(1, 13))
    nh = min(sum(1 for a in v[m] if AHORA[0] <= a <= AHORA[1]) for m in range(1, 13))
    return na, nh


def serie_anual(meses: dict) -> dict:
    """{año: {'tx','tn'}} con la media de los 12 meses (solo años con los 12)."""
    v = validos(meses)
    out = {}
    for a in sorted({a for m in v for a in v[m]}):
        if all(a in v[m] for m in range(1, 13)):
            out[a] = {"tx": sum(v[m][a][1] for m in range(1, 13)) / 12, "tn": sum(v[m][a][2] for m in range(1, 13)) / 12}
    return out


def salto_actual(anual_c: dict, anual_a: dict | None):
    if not anual_a:
        return None, 0
    com = sorted(set(anual_c) & set(anual_a))
    if len(com) < MIN_SOLAPE:
        return None, len(com)
    d = [((anual_c[a]["tx"] + anual_c[a]["tn"]) - (anual_a[a]["tx"] + anual_a[a]["tn"])) / 2 for a in com]
    h = len(d) // 2
    return abs(sum(d[h:]) / len(d[h:]) - sum(d[:h]) / h), len(com)


def elegir(cand: dict, series: dict) -> dict:
    out = {}
    for slug, c in cand.items():
        actual_anual = serie_anual(series[c["actual"]]["meses"]) if c.get("actual") in series else None
        filas = []
        for x in c["candidatas"]:
            s = series.get(x["indicativo"])
            fila = {"indicativo": x["indicativo"], "nombre": x["nombre"], "distancia_km": x["distancia_km"],
                    "historico": x["observatorio_historico"], "completa": bool(s and s.get("completa"))}
            if not s or not s.get("meses"):
                fila["descartada"] = "sin datos"
            elif not s.get("completa"):
                fila["descartada"] = "descarga incompleta"
            else:
                na, nh = anios_por_clima(validos(s["meses"]))
                fila.update(anios_antes=na, anios_ahora=nh)
                if na < MIN_ANIOS or nh < MIN_ANIOS:
                    fila["descartada"] = f"serie corta ({na} y {nh} años válidos en el mes más corto; mínimo {MIN_ANIOS})"
                else:
                    anual = serie_anual(s["meses"])
                    h = tc.homogeneidad(c["cod"], anual)
                    fila["homogeneidad"] = h["estado"]
                    fila["homog_motivo"] = h.get("motivo")
                    sj, nsol = salto_actual(anual, actual_anual if x["indicativo"] != c.get("actual") else None)
                    fila["salto_vs_actual"], fila["solape_anios"] = (None if sj is None else round(sj, 2)), nsol
                    if h["estado"] == "dudosa":
                        fila["descartada"] = "homogeneidad dudosa: " + str(h.get("motivo"))
                    elif sj is not None and sj > SALTO_ACTUAL:
                        fila["descartada"] = f"salto de {sj:.2f} °C frente a la estación actual ({nsol} años de solape)"
            filas.append(fila)
        buenas = [f for f in filas if "descartada" not in f]
        buenas.sort(key=lambda f: (-(f["anios_antes"] + f["anios_ahora"]), not f["historico"], f["distancia_km"]))
        out[slug] = {"capital": c["capital"], "cod": c["cod"], "actual": c.get("actual"),
                     "elegida": buenas[0] if buenas else None, "candidatas": filas}
    return out


def fusionar(eleccion: dict, series: dict) -> list[str]:
    d = json.load(gzip.open(GZ, "rt", encoding="utf-8"))
    nuevas, actualizadas = [], []
    for e in eleccion.values():
        if not e["elegida"]:
            continue
        ide = e["elegida"]["indicativo"]
        s = series[ide]
        if ide in d["estaciones"]:     # ya estaba: solo se añaden los meses que faltaban (p. ej. los más recientes)
            meses = d["estaciones"][ide]["meses"]
            falta = {k: v for k, v in s["meses"].items() if k not in meses and any(x is not None for x in v)}
            if falta:
                meses.update(falta)
                d["estaciones"][ide]["meses"] = dict(sorted(meses.items()))
                actualizadas.append(ide)
            continue
        d["estaciones"][ide] = {"nombre": s["nombre"], "provincia": s["provincia"], "meses": dict(sorted(s["meses"].items()))}
        nuevas.append(ide)
    if nuevas or actualizadas:
        d["descargado"] = d["descargado"].rstrip(")") + f"; +{len(nuevas)} estaciones de capital con serie larga bajadas el 07-11-2026)" \
            if d["descargado"].endswith(")") else d["descargado"] + f" (+{len(nuevas)} estaciones, 07-11-2026)"
        with gzip.GzipFile(str(GZ), "wb", mtime=0, compresslevel=9) as fh:
            fh.write(json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    return nuevas, actualizadas


def main(cand_p, series_p, aplicar=False):
    cand = json.load(open(cand_p, encoding="utf-8"))
    series = json.load(open(series_p, encoding="utf-8"))
    el = elegir(cand, series)
    json.dump(el, open("mensual_largo_eleccion.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for slug, e in el.items():
        g = e["elegida"]
        if g:
            print(f"{e['capital']:22s} -> {g['indicativo']:6s} {g['nombre'][:28]:28s} {g['anios_antes']:2d}/{g['anios_ahora']:2d} años "
                  f"homog {g['homogeneidad']:11s} salto vs actual {g['salto_vs_actual']} ({g['solape_anios']} años)")
        else:
            print(f"{e['capital']:22s} -> ninguna: " + "; ".join(f"{f['indicativo']} {f.get('descartada')}" for f in e["candidatas"][:4]))
    if aplicar:
        print("estaciones nuevas y actualizadas en el gz:", fusionar(el, series))
        print("ESTACION_MENSUAL_LARGA =", {s: e["elegida"]["indicativo"] for s, e in el.items() if e["elegida"]})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--aplicar" in sys.argv)
