"""Embalses: el boletín hidrológico semanal del MITECO, en España, por cuencas, por provincia y embalse a embalse.

Fuente: docs/embalses_nacional.json (España y provincias), docs/embalses/<provincia>.json (embalses de cada provincia)
y docs/embalses/fichas/*.json (serie semanal de cada embalse desde 1988).

Reglas heredadas de la auditoría del 17-10-2026 (partes_prensa.py):
- El puesto de un embalse en su serie se calcula por VOLUMEN (hm³) en la misma semana de cada año, con empates: un
  empate no es récord.
- Fuera: los «Sistema …» (agrupan varias presas), los de menos de 20 hm³ (el boletín da hm³ enteros) y los que están
  por debajo del 1 % o de 1 hm³ (Alfonso XIII al 0 %: suele ser un vaciado por obras o un dato sin reportar; se publica
  solo si la confederación lo confirma).
- La historia lleva la fecha del boletín y el mismo id toda la semana; pierde peso con los días.
"""
from __future__ import annotations

import glob
import json
from datetime import date
from pathlib import Path

SECCION = "agua"
FUENTE = "Boletín Hidrológico Semanal del MITECO (BD-Embalses)"
PAGINA = "https://calentamientoglobal.es/embalses-espana/"
ALIAS = {"guipuzcoa": "20", "gipuzkoa": "20", "vizcaya": "48", "bizkaia": "48", "araba": "01", "alava": "01",
         "araba/alava": "01", "baleares": "07", "illes balears": "07", "islas baleares": "07"}
CUENCA_TXT = {
    "Miño - Sil": "la cuenca del Miño-Sil",
    "Cuenca Mediterránea Andaluza": "la Cuenca Mediterránea Andaluza",
    "Galicia Costa": "las cuencas de Galicia Costa",
    "Cantábrico Occidental": "la cuenca del Cantábrico Occidental",
    "Cantábrico Oriental": "la cuenca del Cantábrico Oriental",
    "Cuencas Internas de Cataluña": "las cuencas internas de Cataluña",
    "Cuencas Internas del País Vasco": "las cuencas internas del País Vasco",
    "Tinto, Odiel y Piedras": "la cuenca del Tinto, Odiel y Piedras",
}


def _cuenca(c):
    return CUENCA_TXT.get(c, f"la cuenca del {c}")


def _cuenca2(c):
    """Segunda mención en la misma frase: «la del Ebro»."""
    t = _cuenca(c)
    return t.replace("la cuenca del ", "la del ", 1) if t.startswith("la cuenca del ") else t


def _may(t):
    return t[0].upper() + t[1:]


def _cod(R, nombre):
    k = R.sin_tildes(str(nombre)).lower().strip()
    if k in ALIAS:
        return ALIAS[k]
    for cod, (n, slug) in R.PROV.items():
        if R.sin_tildes(n).lower() == k or slug == k.replace(" ", "-"):
            return cod
    return None


def _orden_nombre(n):
    """«Cierva, La» → «La Cierva»: el boletín pone el artículo detrás."""
    for art in ("La", "El", "Los", "Las", "A", "O", "As", "Os"):
        if n.endswith(f", {art}"):
            return f"{art} {n[: -len(art) - 2]}"
    return n


def _nombre_embalse(f):
    """«de Alarcón», «de la Fuensanta», «del Vado»: la preposición que trae la ficha."""
    n = f["nombre"]
    if n.startswith("El "):
        return "del " + n[3:]
    if n.lower().startswith(("la ", "los ", "las ")):
        return "de " + n
    return f"{f.get('de') or 'de'} {n}"


def _fichas(R, bol):
    out = []
    for p in sorted(glob.glob(str(R.DOCS / "embalses" / "fichas" / "*.json"))):
        try:
            f = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(f, dict) and f.get("nombre") and f.get("boletin_fecha") == bol:
            out.append(f)
    return out


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _puesto(f):
    """Puesto del volumen de esta semana en la misma semana de cada año de la serie (por hm³, con empates).
    Devuelve {'clase': 'max'|'min'|'max_n'|'min_n', 'n', 'de', 'desde', 'otro': {anio, vol_hm3}} o None."""
    pct, cap, vol = _num(f.get("pct")), _num(f.get("capacidad_hm3")) or 0, _num(f.get("volumen_hm3"))
    rk = f.get("ranking_semana") or {}
    de, desde = rk.get("de"), rk.get("desde", 1988)
    if (pct is None or vol is None or not de or de < 15 or cap < 20 or pct < 1 or vol < 1
            or str(f.get("nombre", "")).lower().startswith("sistema")):
        return None
    anio = int(str(f["boletin_fecha"])[:4])
    otros = [x for x in (f.get("anual_semana") or []) if x.get("anio") != anio and _num(x.get("vol_hm3")) is not None]
    if len(otros) + 1 != de:
        return None
    vols = [_num(x["vol_hm3"]) for x in otros]
    if any(v == vol for v in vols):
        return None
    n_mas, n_menos = sum(1 for v in vols if v > vol), sum(1 for v in vols if v < vol)
    top = max(otros, key=lambda x: _num(x["vol_hm3"]))
    bot = min(otros, key=lambda x: _num(x["vol_hm3"]))
    tops = [x for x in otros if _num(x["vol_hm3"]) == _num(top["vol_hm3"])]
    bots = [x for x in otros if _num(x["vol_hm3"]) == _num(bot["vol_hm3"])]
    if n_mas == 0:
        return {"clase": "max", "n": 1, "de": de, "desde": desde, "otro": top, "iguales": tops}
    if n_menos == 0:
        return {"clase": "min", "n": 1, "de": de, "desde": desde, "otro": bot, "iguales": bots}
    if cap >= 100 and n_mas <= 2:
        return {"clase": "max_n", "n": n_mas + 1, "de": de, "desde": desde, "otro": top, "iguales": tops}
    if cap >= 100 and n_menos <= 2:
        return {"clase": "min_n", "n": n_menos + 1, "de": de, "desde": desde, "otro": bot, "iguales": bots}
    return None


ORD = {2: "segundo", 3: "tercer"}


def _hecho_puesto(R, f, pz, i, con_prov=True):
    pct, vol, cap = _num(f["pct"]), _num(f["volumen_hm3"]), _num(f["capacidad_hm3"])
    nombre = _nombre_embalse(f)
    prov = f" ({f['provincia']})" if con_prov and f.get("provincia") else ""
    mas = pz["clase"].startswith("max")
    cual = "mayor" if mas else "menor"
    if pz["n"] == 1:
        que = f"el {cual} volumen de agua para esa semana del año en los {pz['de']} años de su serie, que empieza en {pz['desde']}"
    else:
        que = f"el {ORD[pz['n']]} {cual} volumen de agua para esa semana del año en los {pz['de']} años de su serie, que empieza en {pz['desde']}"
    otro = pz["otro"]
    anios = sorted({x["anio"] for x in pz.get("iguales") or [otro]})
    cuando_a = R.lista_y([str(x) for x in anios])
    dice = (f"El embalse {nombre}{prov} estaba al {R.f1(pct)} % ({R.miles(vol)} de {R.miles(cap)} hm³): {que}. "
            + (f"El anterior {'máximo' if mas else 'mínimo'} para esa semana era de {R.miles(otro['vol_hm3'])} hm³, en {cuando_a}." if pz["n"] == 1 else
               f"El {'máximo' if mas else 'mínimo'} para esa semana es de {R.miles(otro['vol_hm3'])} hm³, de {cuando_a}."))
    return R.hecho(f"emb_puesto_{i}", dice, FUENTE, [f"{R.f1(pct)} %", R.miles(vol), R.miles(cap), str(pz["de"]), str(pz["desde"]),
                                                   R.miles(otro["vol_hm3"])] + [str(x) for x in anios],
                   lugar=f["nombre"], superlativo=True, record=pz["n"] == 1, liga=[f"{R.f1(pct)} %"])


# ---------------------------------------------------------------------------------------------------- gráficos
def _grafico_barras(R, filas, nombre, titulo, pie, etiqueta_col):
    """filas: [(etiqueta, pct, pct_1a|None, pct_10a|None, vol, cap)] → barras de % con la media de diez años
    (raya) y hace un año (punto)."""
    if not filas:
        return None
    filas = [(_orden_nombre(f[0]),) + tuple(f[1:]) for f in filas]
    ml = int(min(300, 24 + 7.2 * max(len(f[0]) for f in filas)))
    W, fila, mr, mt = 640 + max(0, ml - 200), 28, 78, 30
    Hh = mt + fila * len(filas) + 10
    X = lambda v: ml + max(0.0, min(100.0, v)) / 100 * (W - ml - mr)
    s = []
    for v in (0, 25, 50, 75, 100):
        s.append(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{mt - 6}" y2="{Hh - 6}" stroke="{R.RAYA}" stroke-width="1"></line>')
        s.append(R._t(X(v), mt - 12, f"{v} %", 11, R.GRIS, "middle"))
    for i, (et, pct, p1a, p10, vol, cap) in enumerate(filas):
        y = mt + i * fila
        s.append(R._t(ml - 10, y + 18, et, 13, R.TINTA, "end", 400))
        s.append(f'<rect x="{ml}" y="{y + 6}" width="{max(1.5, X(pct) - ml):.1f}" height="16" fill="{R.LLUVIA}"></rect>')
        if p10 is not None:
            s.append(f'<line x1="{X(p10):.1f}" x2="{X(p10):.1f}" y1="{y + 2}" y2="{y + 26}" stroke="{R.TINTA}" stroke-width="2"></line>')
        if p1a is not None:
            s.append(f'<circle cx="{X(p1a):.1f}" cy="{y + 14}" r="4" fill="#FFFFFF" stroke="{R.CALOR}" stroke-width="2"></circle>')
        s.append(R._t(W - 8, y + 19, f"{R.f1(pct)} %", 12.5, R.TINTA, "end", 600))
    svg = R._svg(W, Hh, titulo, s)
    leyenda = [{"t": "banda", "c": R.LLUVIA, "l": "Reserva en el boletín"}, {"t": "linea", "c": R.TINTA, "l": "Media de diez años, misma semana"},
               {"t": "punto", "c": R.CALOR, "l": "Hace un año"}]
    return R.guardar_grafico(nombre, svg, [(f[0], f[1], f[2], f[3], f[4], f[5]) for f in filas],
                             [etiqueta_col, "pct", "pct_hace_1_anio", "pct_media_10_anios", "vol_hm3", "capacidad_hm3"], titulo, leyenda, pie)


# ---------------------------------------------------------------------------------------------------- generador
def generar(R, D):
    N = R.leer(R.DOCS / "embalses_nacional.json", {}) or {}
    nac, bol = N.get("nacional") or {}, N.get("boletin_fecha")
    if not nac or not bol:
        return []
    dias = (R.HOY - date.fromisoformat(bol)).days
    if dias > 9:  # sin boletín nuevo en más de una semana: nada que contar
        return []
    bol_ant = N.get("boletin_fecha_anterior")
    pct, p1a, p10, p1s = _num(nac["pct"]), _num(nac.get("pct_hace_1a")), _num(nac.get("pct_media_10a")), _num(nac.get("pct_hace_1s"))
    vol, cap, v1s = _num(nac["volumen_total_hm3"]), _num(nac["capacidad_total_hm3"]), _num(nac.get("vol_hace_1s_hm3"))
    fichas = _fichas(R, bol)
    hid = f"{bol}-embalses"
    dbol = R.dia(bol)

    # ---- cuencas
    cu = {}
    for f in fichas:
        c = f.get("cuenca")
        cp, vo = _num(f.get("capacidad_hm3")), _num(f.get("volumen_hm3"))
        if not c or not cp or vo is None:
            continue
        x = cu.setdefault(c, {"cap": 0.0, "vol": 0.0, "dif": 0.0, "n_dif": 0, "n": 0, "cap1a": 0.0, "vol1a": 0.0, "cap10": 0.0, "v10": 0.0})
        x["cap"] += cp
        x["vol"] += vo
        x["n"] += 1
        sa = f.get("semana_anterior") or {}
        if _num(sa.get("dif_hm3")) is not None:
            x["dif"] += _num(sa["dif_hm3"])
            x["n_dif"] += 1
        h1 = f.get("hace_1a") or {}
        if _num(h1.get("vol_hm3")) is not None:
            x["cap1a"] += cp
            x["vol1a"] += _num(h1["vol_hm3"])
        if _num(f.get("pct_media_10a")) is not None:
            x["cap10"] += cp
            x["v10"] += _num(f["pct_media_10a"]) / 100 * cp
    for c, x in cu.items():
        x["pct"] = round(x["vol"] / x["cap"] * 100, 1)
        x["pct1a"] = round(x["vol1a"] / x["cap1a"] * 100, 1) if x["cap1a"] >= 0.95 * x["cap"] else None
        x["pct10"] = round(x["v10"] / x["cap10"] * 100, 1) if x["cap10"] >= 0.95 * x["cap"] else None
    grandes = {c: x for c, x in cu.items() if x["cap"] >= 300}

    # ---- puestos en la serie (España)
    puestos = []
    for f in fichas:
        pz = _puesto(f)
        if pz:
            puestos.append((f, pz))
    maxs = sorted([p for p in puestos if p[1]["clase"] == "max"], key=lambda p: -_num(p[0]["capacidad_hm3"]))
    mins = sorted([p for p in puestos if p[1]["clase"] == "min"], key=lambda p: -_num(p[0]["capacidad_hm3"]))

    # ---- hechos nacionales
    hechos = [R.hecho("emb_nac", f"Los embalses de España guardaban el {dbol} {R.miles(vol)} hm³, el {R.f1(pct)} % de su capacidad "
                      f"({R.miles(cap)} hm³), según el boletín hidrológico semanal del MITECO.", FUENTE,
                      [R.miles(vol), f"{R.f1(pct)} %", R.miles(cap)])]
    dif = None
    if v1s is not None:
        dif = vol - v1s
        if abs(dif) >= 1:
            hechos.append(R.hecho("emb_semana", f"En una semana, la reserva {'ganó' if dif > 0 else 'perdió'} {R.miles(abs(dif))} hm³: "
                                  f"el {R.dia(bol_ant) if bol_ant else 'boletín anterior'} tenía {R.miles(v1s)} hm³"
                                  + (f", el {R.f1(p1s)} %." if p1s is not None else "."), FUENTE,
                                  [R.miles(abs(dif)), R.miles(v1s)] + ([f"{R.f1(p1s)} %"] if p1s is not None else [])))
        else:
            hechos.append(R.hecho("emb_semana", f"La reserva apenas cambió en una semana: el {R.dia(bol_ant) if bol_ant else 'boletín anterior'} "
                                  f"tenía {R.miles(v1s)} hm³.", FUENTE, [R.miles(v1s)]))
    if p10 is not None:
        hechos.append(R.hecho("emb_media", f"La media de los últimos diez años para esa misma semana es del {R.f1(p10)} %: la reserva estaba "
                              f"{R.f1(abs(pct - p10))} puntos {'por encima' if pct > p10 else 'por debajo'}"
                              + (f". Hace un año estaba al {R.f1(p1a)} %." if p1a is not None else "."), FUENTE,
                              [f"{R.f1(p10)} %", R.f1(abs(pct - p10))] + ([f"{R.f1(p1a)} %"] if p1a is not None else [])))
    if len(grandes) >= 4:
        alta = max(grandes.items(), key=lambda kv: kv[1]["pct"])
        baja = min(grandes.items(), key=lambda kv: kv[1]["pct"])
        hechos.append(R.hecho("emb_cuencas", f"{_may(_cuenca(alta[0]))} era la más llena, al {R.f1(alta[1]['pct'])} %, y "
                              f"{_cuenca2(baja[0])}, la menos llena, al {R.f1(baja[1]['pct'])} % (entre las cuencas de más de 300 hm³).",
                              f"{FUENTE}; suma por cuencas de calentamientoglobal.es",
                              [f"{R.f1(alta[1]['pct'])} %", f"{R.f1(baja[1]['pct'])} %"], superlativo=True))
        anio = [(c, x, x["pct"] - x["pct1a"]) for c, x in grandes.items() if x["pct1a"] is not None]
        if anio:
            c_a, x_a, d_a = max(anio, key=lambda t: abs(t[2]))
            if abs(d_a) >= 10:
                txt_a = (f"Hace un año, {_cuenca(c_a)} estaba al {R.f1(x_a['pct1a'])} %: es la que más ha cambiado, {R.f1(abs(d_a))} puntos "
                         f"{'más' if d_a > 0 else 'menos'} de agua." if c_a in (alta[0], baja[0]) else
                         f"Frente a hace un año, el mayor cambio es el de {_cuenca(c_a)}: está al {R.f1(x_a['pct'])} %, "
                         f"{R.f1(abs(d_a))} puntos {'más' if d_a > 0 else 'menos'} que entonces ({R.f1(x_a['pct1a'])} %).")
                hechos.append(R.hecho("emb_cuencas_anio", _may(txt_a),
                                      f"{FUENTE}; suma por cuencas de calentamientoglobal.es",
                                      [f"{R.f1(x_a['pct'])} %", R.f1(abs(d_a)), f"{R.f1(x_a['pct1a'])} %"], superlativo=True))
        cambios = [(c, x) for c, x in grandes.items() if x["n_dif"] >= 0.9 * x["n"] and abs(x["dif"]) >= 5]
        if cambios:
            gana = max(cambios, key=lambda kv: kv[1]["dif"])
            pierde = min(cambios, key=lambda kv: kv[1]["dif"])
            if gana[1]["dif"] > 0 and pierde[1]["dif"] < 0:
                t = (f"{_may(_cuenca(gana[0]))} fue la que más agua ganó en la semana, {R.miles(gana[1]['dif'])} hm³, y "
                     f"{_cuenca2(pierde[0])}, la que más perdió, {R.miles(abs(pierde[1]['dif']))} hm³.")
            elif gana[1]["dif"] > 0:
                t = f"{_may(_cuenca(gana[0]))} fue la que más agua ganó en la semana: {R.miles(gana[1]['dif'])} hm³."
            elif pierde[1]["dif"] < 0:
                t = f"{_may(_cuenca(pierde[0]))} fue la que más agua perdió en la semana: {R.miles(abs(pierde[1]['dif']))} hm³."
            else:
                t = ""
            if t:
                hechos.append(R.hecho("emb_cuencas_semana", t, f"{FUENTE}; suma por cuencas de calentamientoglobal.es",
                                      [R.miles(abs(gana[1]["dif"])), R.miles(abs(pierde[1]["dif"]))], superlativo=True))
    for i, (f, pz) in enumerate((maxs[:3] + mins[:3])):
        hechos.append(_hecho_puesto(R, f, pz, i))
    if maxs or mins:
        partes = []
        if maxs:
            partes.append(R.plural(len(maxs), "embalse tenía", "embalses tenían") + " el mayor volumen de agua para esa semana del año en su serie")
        if mins:
            partes.append(R.plural(len(mins), "embalse tenía", "embalses tenían") + " el menor")
        hechos.append(R.hecho("emb_puestos_n", f"Según el boletín del {dbol}, " + " y ".join(partes) + " (embalses de 20 hm³ o más, con la serie del MITECO desde 1988).",
                              f"{FUENTE}; cálculo de calentamientoglobal.es", [str(len(maxs)), str(len(mins))], superlativo=True, record=True))

    # ---- plantilla nacional
    sobre = f"{R.f1(abs(pct - p10))} puntos {'por encima' if pct > p10 else 'por debajo'} de la media de diez años" if p10 is not None else ""
    if dif is not None and abs(dif) >= 100:
        tit = f"Los embalses {'ganaron' if dif > 0 else 'perdieron'} {R.miles(abs(dif))} hm³ en la semana hasta el {dbol} y quedaron al {R.f1(pct)} %"
        if sobre and len(tit) + len(sobre) < 163:
            tit += f", {sobre}"
    else:
        tit = f"Los embalses estaban al {R.f1(pct)} % el {dbol}" + (f", {sobre}" if sobre else "")
    sub = next((h["dice"] for h in hechos if h["id"] in ("emb_puestos_n", "emb_cuencas")), "")
    cuerpo = [" ".join(h["dice"] for h in hechos if h["id"] in ("emb_semana", "emb_media"))]
    cuerpo.append(" ".join(h["dice"] for h in hechos if h["id"].startswith("emb_cuencas")))
    cuerpo.append(" ".join(h["dice"] for h in hechos if h["id"].startswith("emb_puesto")))
    cuerpo = [c for c in cuerpo if c]
    pl = {"titular": tit, "subtitulo": sub, "entradilla": hechos[0]["dice"], "cuerpo": cuerpo,
          "claves": [h["dice"] for h in hechos[:3]]}
    cifras = [{"n": f"{R.f1(pct)} %", "l": f"reserva de agua de España el {dbol}", "tono": "lluvia"}]
    if dif is not None and abs(dif) >= 1:
        cifras.append({"n": f"{'+' if dif > 0 else '−'}{R.miles(abs(dif))} hm³", "l": "en una semana", "tono": "lluvia" if dif > 0 else "calor"})
    if p10 is not None:
        cifras.append({"n": f"{'+' if pct >= p10 else '−'}{R.f1(abs(pct - p10))}", "l": "puntos frente a la media de diez años", "tono": "lluvia" if pct >= p10 else "calor"})
    if maxs or mins:
        cifras.append({"n": str(len(maxs) + len(mins)), "l": "embalses en el máximo o el mínimo de su serie para esa semana", "tono": "lluvia"})
    puntos = 52 + (8 if dif is not None and abs(dif) >= 300 else 0) + (10 if dif is not None and abs(dif) >= 1000 else 0) \
        + min(12, 3 * (len(maxs) + len(mins))) - 3 * max(0, dias - 1)
    h = R.historia("embalses", hid, "Agua · boletín semanal del MITECO", "lluvia", max(12, puntos), hechos, pl, cifras,
                   fuentes=FUENTE,
                   metodo="Boletín Hidrológico Semanal del MITECO. Cuencas: suma de los embalses de cada cuenca. Puesto de cada embalse: su volumen "
                          "(hm³) frente al de la misma semana de cada año de su serie, desde 1988, con empates.",
                   limites=["El boletín da volúmenes en hm³ enteros: en embalses pequeños un solo hm³ mueve varios puntos.",
                            "Fuera de los puestos: embalses de menos de 20 hm³, los «Sistema» del boletín y los que están por debajo del 1 % "
                            "(un embalse vacío suele ser un vaciado por obras o un dato sin reportar)."],
                   pagina=PAGINA)
    h["fecha"] = bol
    h["seccion"] = SECCION
    filas = []
    for c, x in sorted(grandes.items(), key=lambda kv: -kv[1]["pct"]):
        filas.append((c, x["pct"], x["pct1a"], x["pct10"], round(x["vol"]), round(x["cap"])))
    g = _grafico_barras(R, filas, hid, f"Reserva de agua por cuencas, boletín del {dbol}",
                        "Porcentaje de llenado de cada cuenca (suma de sus embalses). Raya: media de diez años para la misma semana; punto: hace un año. "
                        "Fuente: Boletín Hidrológico Semanal del MITECO. Suma por cuencas: calentamientoglobal.es.", "cuenca")
    if g:
        h["grafico"] = g

    # ---- versiones provinciales
    nac_ctx = R.hecho("emb_nac_ctx", f"En el conjunto de España, la reserva estaba al {R.f1(pct)} % el {dbol}.", FUENTE, [f"{R.f1(pct)} %"])
    por_prov = {}
    for f in fichas:
        cod = _cod(R, f.get("provincia"))
        if cod:
            por_prov.setdefault(cod, []).append(f)
    for p in N.get("provincias") or []:
        cod = _cod(R, p.get("provincia") or p.get("nombre"))
        if not cod or _num(p.get("pct")) is None:
            continue
        v = _version(R, cod, p, por_prov.get(cod, []), bol, bol_ant, dias, nac_ctx, hid)
        if v:
            h["provincias"][cod] = v
    return [h]


def _version(R, cod, p, fichas, bol, bol_ant, dias, nac_ctx, hid):
    P = R.nprov(cod)
    pct, p1a, p10 = _num(p["pct"]), _num(p.get("pct_hace_1a")), _num(p.get("pct_media_10a"))
    vol, cap, v1s = _num(p.get("volumen_total_hm3")), _num(p.get("capacidad_total_hm3")), _num(p.get("vol_hace_1s_hm3"))
    if vol is None or not cap:
        return None
    n = int(p.get("total_embalses") or len(fichas) or 0)
    V = (lambda pl, sg: sg if n == 1 else pl)
    dbol = R.dia(bol)
    hechos = [R.hecho("embp", f"Los {R.plural(n, 'embalse', 'embalses')} de {P} guardaban el {dbol} {R.miles(vol)} hm³ de {R.miles(cap)}, "
                      f"el {R.f1(pct)} % de su capacidad, según el boletín hidrológico semanal del MITECO.", FUENTE,
                      [str(n), R.miles(vol), R.miles(cap), f"{R.f1(pct)} %"], lugar=P, liga=[f"{R.f1(pct)} %"])]
    if n == 1:
        hechos[0]["dice"] = hechos[0]["dice"].replace(f"Los 1 embalse de {P} guardaban", f"El único embalse de {P} en el boletín guardaba")
    dif = None
    if v1s is not None:
        dif = vol - v1s
        if abs(dif) >= 1:
            hechos.append(R.hecho("embp_semana", f"En una semana {V('ganaron', 'ganó') if dif > 0 else V('perdieron', 'perdió')} {R.miles(abs(dif))} hm³: "
                                  f"el {R.dia(bol_ant) if bol_ant else 'boletín anterior'} {V('tenían', 'tenía')} {R.miles(v1s)} hm³.", FUENTE,
                                  [R.miles(abs(dif)), R.miles(v1s)]))
        else:
            hechos.append(R.hecho("embp_semana", f"La reserva no cambió en una semana: el {R.dia(bol_ant) if bol_ant else 'boletín anterior'} "
                                  f"también {V('tenían', 'tenía')} {R.miles(v1s)} hm³.", FUENTE, [R.miles(v1s)]))
    if p10 is not None:
        dev = pct - p10
        txt = (f"La media de los últimos diez años para esa semana es del {R.f1(p10)} %"
               + (f": {V('estaban', 'estaba')} {R.f1(abs(dev))} puntos {'por encima' if dev > 0 else 'por debajo'}" if abs(dev) >= 0.1 else f": {V('estaban', 'estaba')} en la media")
               + (f". Hace un año {V('estaban', 'estaba')} al {R.f1(p1a)} %." if p1a is not None else "."))
        hechos.append(R.hecho("embp_media", txt, FUENTE, [f"{R.f1(p10)} %", R.f1(abs(dev))] + ([f"{R.f1(p1a)} %"] if p1a is not None else []),
                              lugar=P))
    puestos = [(f, _puesto(f)) for f in fichas]
    puestos = sorted([(f, pz) for f, pz in puestos if pz], key=lambda x: (x[1]["n"], -_num(x[0]["capacidad_hm3"])))
    for i, (f, pz) in enumerate(puestos[:3]):
        hechos.append(_hecho_puesto(R, f, pz, i, con_prov=False))
    grandes = sorted([f for f in fichas if _num(f.get("capacidad_hm3")) and _num(f.get("pct")) is not None
                      and not str(f.get("nombre", "")).lower().startswith("sistema")], key=lambda f: -_num(f["capacidad_hm3"]))
    en_puesto = {f["nombre"] for f, _ in puestos[:3]}
    g0 = next((f for f in grandes if f["nombre"] not in en_puesto and _num(f["pct"]) >= 1), None)
    if g0 and len(grandes) >= 2:
        hechos.append(R.hecho("embp_mayor", f"El mayor de la provincia, el embalse {_nombre_embalse(g0)}, estaba al {R.f1(g0['pct'])} % "
                              f"({R.miles(g0['volumen_hm3'])} de {R.miles(g0['capacidad_hm3'])} hm³).", FUENTE,
                              [f"{R.f1(g0['pct'])} %", R.miles(g0["volumen_hm3"]), R.miles(g0["capacidad_hm3"])], lugar=g0["nombre"],
                              superlativo=True, liga=[f"{R.f1(g0['pct'])} %"]))
    hechos.append(nac_ctx)

    # titular
    top = puestos[0] if puestos and puestos[0][1]["n"] == 1 else None
    if top:
        f, pz = top
        tit = (f"El embalse {_nombre_embalse(f)} estaba al {R.f1(f['pct'])} % el {dbol}: el {'mayor' if pz['clase'] == 'max' else 'menor'} volumen "
               f"para esa semana en {pz['de']} años")
    elif dif is not None and abs(dif) >= max(2, 0.03 * cap):
        tit = (f"Los embalses de {P} {V('ganaron', 'ganó') if dif > 0 else V('perdieron', 'perdió')} {R.miles(abs(dif))} hm³ en la semana "
               f"hasta el {dbol} y {V('quedaron', 'quedó')} al {R.f1(pct)} %")
    elif p10 is not None and abs(pct - p10) >= 5:
        tit = (f"Los embalses de {P} estaban al {R.f1(pct)} % el {dbol}, {R.f1(abs(pct - p10))} puntos {'por encima' if pct > p10 else 'por debajo'} "
               f"de su media de diez años")
    else:
        tit = f"Los embalses de {P} guardaban {R.miles(vol)} hm³ el {dbol}, el {R.f1(pct)} % de su capacidad"
    if n == 1 and not top:
        tit = tit.replace(f"Los embalses de {P}", f"El embalse de {P}").replace("estaban", "estaba").replace("guardaban", "guardaba")
    if len(tit) > 165:
        tit = f"Los embalses de {P} estaban al {R.f1(pct)} % el {dbol}"
    ids_c = [h["id"] for h in hechos]
    sub = next((h["dice"] for h in hechos if h["id"] == "embp_media"), "")
    cuerpo = [" ".join(h["dice"] for h in hechos if h["id"] in ("embp_semana",)),
              " ".join(h["dice"] for h in hechos if h["id"].startswith("emb_puesto") or h["id"] == "embp_mayor"),
              nac_ctx["dice"]]
    cuerpo = [c for c in cuerpo if c]
    if top:
        ent_id = next(h for h in hechos if h["id"].startswith("emb_puesto"))
        pl = {"titular": tit, "subtitulo": hechos[0]["dice"], "entradilla": ent_id["dice"],
              "cuerpo": [c.replace(ent_id["dice"], "").strip() for c in cuerpo] + ([sub] if sub else []),
              "claves": [hechos[0]["dice"], ent_id["dice"]]}
        pl["cuerpo"] = [c for c in pl["cuerpo"] if c]
    else:
        pl = {"titular": tit, "subtitulo": sub, "entradilla": hechos[0]["dice"], "cuerpo": cuerpo, "claves": [h["dice"] for h in hechos[:2]]}
    cifras = [{"n": f"{R.f1(pct)} %", "l": f"embalses de {P} el {dbol}", "tono": "lluvia"}]
    if dif is not None and abs(dif) >= 1:
        cifras.append({"n": f"{'+' if dif > 0 else '−'}{R.miles(abs(dif))} hm³", "l": "en una semana", "tono": "lluvia" if dif > 0 else "calor"})
    if p10 is not None:
        cifras.append({"n": f"{R.f1(p10)} %", "l": "media de diez años para esa semana", "tono": "lluvia"})
    puntos = 28 + (16 if top else 0) + (8 if p10 is not None and abs(pct - p10) >= 15 else 0) \
        + (8 if dif is not None and abs(dif) >= max(2, 0.03 * cap) else 0) - 2 * max(0, dias - 1)
    v = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hechos, "plantilla": pl, "cifras": cifras, "puntos": max(8, puntos)}
    # gráfico: los embalses de la provincia
    det = None
    for cand in (R.DOCS / "embalses" / f"{p.get('slug')}.json",):
        det = R.leer(cand, None)
    filas = []
    for e in sorted((det or {}).get("embalses") or [], key=lambda e: -(_num(e.get("capacidad_hm3")) or 0))[:12]:
        if _num(e.get("pct")) is None or str(e.get("nombre", "")).lower().startswith("sistema"):
            continue
        filas.append((e["nombre"], _num(e["pct"]), _num(e.get("pct_hace_1a")), _num(e.get("pct_media_10a")), e.get("volumen_hm3"), e.get("capacidad_hm3")))
    if len(filas) >= 2:
        g = _grafico_barras(R, filas, f"{hid}-{cod}", f"Embalses de {P}, boletín del {dbol}",
                            f"Porcentaje de llenado de los embalses de {P} (los 12 mayores). Raya: media de diez años para la misma semana; punto: hace un año. "
                            "Fuente: Boletín Hidrológico Semanal del MITECO.", "embalse")
        if g:
            v["grafico"] = g
    return v
