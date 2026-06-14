#!/usr/bin/env python3
"""
OCÉANO · Paso 2 de 3  — EL "MOAT" DE DATOS PROPIOS
Actualiza el histórico y calcula rachas/récords que ninguna API publica.

Lee/escribe (todo en docs/):
  oceano.json            -> se le inyectan racha_dias/record (global) y racha/record (cuencas)
  historial_oceano.json  -> serie diaria acumulada
  records_oceano.json    -> récords persistentes
"""
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
TODAY = os.path.join(DOCS, "oceano.json")
HIST  = os.path.join(DOCS, "historial_oceano.json")
RECS  = os.path.join(DOCS, "records_oceano.json")

def load(p, d):
    return json.load(open(p, encoding="utf8")) if os.path.exists(p) else d

def main():
    hoy = load(TODAY, None)
    if hoy is None:
        raise SystemExit("Falta docs/oceano.json (ejecuta oceano_ingest.py primero)")
    fecha = hoy["fecha"]; pct = hoy["global"]["pct_en_mhw"]; anom = hoy["global"].get("anomalia_media")

    hist = load(HIST, {"serie": []})
    serie = [p for p in hist["serie"] if p["fecha"] != fecha]
    serie.append({"fecha": fecha, "pct": pct, "anom": anom})
    serie.sort(key=lambda p: p["fecha"]); hist["serie"] = serie

    if anom is not None and any(p.get("anom") is not None for p in serie):
        signo = lambda p: (p.get("anom") or 0) > 0
    else:
        med = sorted(p["pct"] for p in serie)[len(serie) // 2]
        signo = lambda p: p["pct"] > med
    racha = 0
    for p in reversed(serie):
        if signo(p): racha += 1
        else: break

    recs = load(RECS, {"global": 0, "cuencas": {}, "cuenca_state": {}})
    recs["global"] = max(recs.get("global", 0), racha)
    hoy["global"]["racha_dias"] = racha
    hoy["global"]["record_racha"] = recs["global"]

    cstate = recs.setdefault("cuenca_state", {})
    for c in hoy["cuencas"]:
        st = cstate.get(c["id"], {"racha": 0})
        st["racha"] = st.get("racha", 0) + 1 if c["categoria"] >= 1 else 0
        cstate[c["id"]] = st
        recs["cuencas"][c["id"]] = max(recs["cuencas"].get(c["id"], 0), st["racha"])
        c["racha"] = st["racha"]; c["record"] = recs["cuencas"][c["id"]]

    json.dump(hist, open(HIST, "w", encoding="utf8"), ensure_ascii=False, indent=2)
    json.dump(recs, open(RECS, "w", encoding="utf8"), ensure_ascii=False, indent=2)
    json.dump(hoy,  open(TODAY, "w", encoding="utf8"), ensure_ascii=False, indent=2)
    print(f"OK  racha_global={racha} (récord {recs['global']})  puntos={len(serie)}")

if __name__ == "__main__":
    main()
