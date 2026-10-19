"""Lo que viene, según la predicción oficial de AEMET por municipio (docs/prediccion/NN.json).

Tres historias posibles, cada una con versión nacional y provincial:
  · calor fuera de lo normal: máxima prevista ≥ 5 °C sobre la normal 1991-2020 de la estación de AEMET de referencia;
  · frío: máxima ≥ 5 °C por debajo o mínima ≥ 6 °C por debajo de la normal (o helada donde la normal no la tiene);
  · lluvia casi segura: muchos municipios con probabilidad de precipitación ≥ 90 % el mismo día.

Honestidad (las mismas reglas que la auditoría del 17-10-2026 impuso en partes_prensa.py):
  · solo la predicción elaborada hoy y solo días futuros;
  · la normal es la de la estación de AEMET que trae el fichero (norm): vale si está a ≤ 25 km y tiene ≥ 25 años de
    1991-2020, y el texto nombra esa estación; en el titular, «más de lo normal» solo si está a ≤ 10 km;
  · si la desviación de un municipio se separa más de 3 °C de la mediana de su provincia ese día, el fallo es de la
    normal (otra altitud: Montserrat frente a los pueblos del Llobregat) y no cuenta; con menos de 5 municipios ese
    día, solo vale una estación a ≤ 10 km;
  · siempre «AEMET prevé»: es una predicción y cambia dos veces al día.
"""
from __future__ import annotations

import json
from datetime import date, datetime

SECCION = "calor"

FUENTE = "AEMET OpenData · predicción específica por municipio"
PAGINA = "https://calentamientoglobal.es/el-tiempo/"
LIMITES = ["Es una predicción: AEMET la actualiza dos veces al día y puede cambiar. Citar siempre como «AEMET prevé».",
           "La normal es la de la estación de AEMET de referencia que se nombra (1991-2020), no la del municipio exacto.",
           "Solo cuenta la predicción elaborada el día de publicación y solo días futuros."]
METODO = ("Predicción oficial de AEMET para cada municipio, comparada con la máxima y la mínima normales 1991-2020 de la estación "
          "de AEMET de referencia (a 25 km o menos y con 25 años o más de serie). Se descartan los municipios cuya desviación se "
          "separa más de 3 °C de la mediana de su provincia ese día (la normal sería de otra altitud).")

# nombres bilingües: el que usa la prensa en castellano (en Navarra va delante)
CASTELLANO_PRIMERO = {"Ansoáin/Antsoain", "Barañáin/Barañain", "Berrioplano/Berriobeiti", "Burlada/Burlata", "Huarte/Uharte",
                      "Pamplona/Iruña", "Valle de Egüés/Eguesibar", "Valle de Elorz/Elortzibar", "Villava/Atarrabia",
                      "Zizur Mayor/Zizur Nagusia"}


def nombre(n: str) -> str:
    if "/" not in n:
        return n
    a, b = [x.strip() for x in n.split("/", 1)]
    return a if n in CASTELLANO_PRIMERO else b


def estacion(n: str) -> str:
    """'Alacant/alicante' → 'Alicante'; 'Estación de Tortosa (roquetes)' → 'Tortosa (Roquetes)'."""
    import re
    s = re.sub(r"([/(]\s*)([a-zà-ÿ])", lambda m: m.group(1) + m.group(2).upper(), n.strip())
    s = re.sub(r"^Estación de ", "", s)
    return nombre(s) if "/" in s else s


def _mediana(v):
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _dia_corto(iso):
    d = date.fromisoformat(iso)
    return ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"][d.weekday()] + f" {d.day}"


def leer_prediccion(R):
    """Municipios con la predicción elaborada hoy. Devuelve (por_cod, n_mun) con, por provincia, la lista de
    (municipio, norm, dias futuros)."""
    hoy = R.HOY.isoformat()
    por_cod, n_mun = {}, 0
    for cod in R.PROV:
        pr = R.leer(R.DOCS / "prediccion" / f"{cod}.json", {}) or {}
        for code, m in (pr.get("municipios") or {}).items():
            dd = m.get("d") or {}
            try:
                elab = datetime.fromisoformat(str(dd.get("elab", "")).replace("Z", "+00:00")).astimezone(R.MADRID).date().isoformat()
            except ValueError:
                continue
            if elab != hoy:
                continue
            dias = [d for d in (dd.get("dias") or []) if d.get("f", "") > hoy]
            if not dias:
                continue
            n_mun += 1
            por_cod.setdefault(cod, []).append({"code": code, "n": m["n"], "norm": m.get("norm") or {}, "dias": dias})
    return por_cod, n_mun


def anomalias(por_cod, campo_p, campo_n):
    """Desviaciones válidas (predicción − normal) de un campo (tx/nx o tn/nn), con el filtro de la mediana."""
    out = []
    for cod, ms in por_cod.items():
        bruto = []
        for m in ms:
            nm = m["norm"]
            km, anios = nm.get("km"), nm.get("anios") or 0
            if km is None or km > 25 or anios < 25:
                continue
            for d in m["dias"]:
                if d.get(campo_p) is None or d.get(campo_n) is None:
                    continue
                bruto.append({"cod": cod, "mun": m["n"], "f": d["f"], "p": d[campo_p], "n": d[campo_n],
                              "a": round(d[campo_p] - d[campo_n], 1), "km": km, "est": nm.get("nom") or "", "anios": anios,
                              "serie": m["dias"]})
        por_f = {}
        for b in bruto:
            por_f.setdefault(b["f"], []).append(b["a"])
        for b in bruto:
            v = por_f[b["f"]]
            if (len(v) >= 5 and abs(b["a"] - _mediana(v)) <= 3) or (len(v) < 5 and b["km"] <= 10):
                out.append(b)
    return out


# ============================================================================ gráficos
def grafico_semana(R, x, nombre_graf, campo_p="tx", campo_n="nx", tono=None):
    """Predicción frente a la normal, día a día: un punto para lo previsto, otro para la normal y la distancia entre ambos."""
    tono = tono or R.CALOR
    dias = [d for d in x["serie"] if d.get(campo_p) is not None]
    W, Hh, ml, mr, mt, mb = 640, 300, 44, 16, 30, 40
    vals = [d[campo_p] for d in dias] + [d[campo_n] for d in dias if d.get(campo_n) is not None]
    y0, y1 = int(min(vals)) - 2, int(max(vals)) + 3
    X = lambda i: ml + (i + 0.5) * (W - ml - mr) / len(dias)
    Y = lambda t: mt + (y1 - t) / (y1 - y0) * (Hh - mt - mb)
    c = []
    paso = 2 if (y1 - y0) <= 16 else 5
    ticks = [t for t in range(y0, y1 + 1) if t % paso == 0]
    for t in ticks:
        c.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{R.RAYA}" stroke-width="1"/>')
        c.append(R._t(ml - 6, Y(t) + 4, f"{t} °C" if t == ticks[-1] else t, 11, R.GRIS, "end"))
    pts = []
    for i, d in enumerate(dias):
        n = d.get(campo_n)
        fuerte = n is not None and abs(d[campo_p] - n) >= 5
        col = tono if fuerte else ("#E6A88F" if tono == R.CALOR else "#9CB9DB")
        if n is not None:
            pts.append((X(i), Y(n)))
            c.append(f'<line x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{Y(n):.1f}" y2="{Y(d[campo_p]):.1f}" stroke="{col}" stroke-width="6" stroke-linecap="round"/>')
        c.append(f'<circle cx="{X(i):.1f}" cy="{Y(d[campo_p]):.1f}" r="{8 if fuerte else 6}" fill="{col}" stroke="#FFFFFF" stroke-width="2"/>')
        dy = -14 if (n is None or d[campo_p] >= n) else 22
        c.append(R._t(X(i), Y(d[campo_p]) + dy, f"{R.f1(d[campo_p])}", 12, R.TINTA if fuerte else R.GRIS, "middle", 700 if fuerte else 400))
        c.append(R._t(X(i), Hh - mb + 18, _dia_corto(d["f"]), 11, R.GRIS, "middle"))
    if pts:
        c.insert(0, '<polyline points="' + " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + f'" fill="none" stroke="{R.TINTA}" stroke-width="1.5" stroke-dasharray="5 4"/>')
        for a, b in pts:
            c.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="3" fill="{R.TINTA}"/>')
    que = "máxima" if campo_p == "tx" else "mínima"
    svg = R._svg(W, Hh, f"{que.capitalize()} prevista por AEMET en {nombre(x['mun'])} frente a la normal de la estación de {estacion(x['est'])}", c)
    filas = [(d["f"], d[campo_p], d.get(campo_n)) for d in dias]
    leyenda = [{"t": "punto", "c": tono, "l": f"{que.capitalize()} prevista por AEMET"},
               {"t": "discontinua", "c": R.TINTA, "l": f"Normal 1991-2020 (estación de {estacion(x['est'])})"}]
    pie = (f"Predicción de AEMET para {nombre(x['mun'])} elaborada el {R.dia(R.HOY, semana=False)}. Normal: estación de AEMET de "
           f"{estacion(x['est'])}, a {R.f1(x['km'])} km. En color fuerte, los días a 5 °C o más de la normal. Fuente: AEMET OpenData. "
           f"Cálculo: calentamientoglobal.es.")
    return R.guardar_grafico(nombre_graf, svg, filas, ["fecha", f"{que}_prevista_C", f"{que}_normal_1991_2020_C"],
                             f"{que.capitalize()} prevista en {nombre(x['mun'])}, día a día", leyenda, pie)


def grafico_lluvia(R, cuenta, nombre_graf, ambito):
    """Municipios con probabilidad de lluvia ≥ 90 % cada día."""
    dias = sorted(cuenta)
    W, Hh, ml, mr, mt, mb = 640, 260, 40, 16, 28, 40
    mx = max(cuenta.values()) or 1
    X = lambda i: ml + (i + 0.5) * (W - ml - mr) / len(dias)
    bw = (W - ml - mr) / len(dias) * 0.56
    c = [f'<line x1="{ml}" x2="{W - mr}" y1="{Hh - mb}" y2="{Hh - mb}" stroke="{R.RAYA}" stroke-width="1"/>']
    for i, f in enumerate(dias):
        v = cuenta[f]
        h = (Hh - mt - mb) * v / mx
        c.append(f'<rect x="{X(i) - bw / 2:.1f}" y="{Hh - mb - h:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{R.LLUVIA if v == mx else "#9CB9DB"}"/>')
        c.append(R._t(X(i), Hh - mb - h - 6, v, 12, R.TINTA, "middle", 700 if v == mx else 400))
        c.append(R._t(X(i), Hh - mb + 18, _dia_corto(f), 11, R.GRIS, "middle"))
    svg = R._svg(W, Hh, f"Municipios de {ambito} con probabilidad de lluvia del 90 % o más, día a día, según AEMET", c)
    pie = (f"Municipios que sigue el observatorio con la predicción de AEMET elaborada el {R.dia(R.HOY, semana=False)}. "
           "Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.")
    return R.guardar_grafico(nombre_graf, svg, [(f, cuenta[f]) for f in dias], ["fecha", "municipios_prob_90_o_mas"],
                             f"Municipios con probabilidad de lluvia del 90 % o más en {ambito}", [], pie)


# ============================================================================ calor
# los umbrales del texto («5 °C o más») no se ligan a ningún lugar aunque coincidan con una cifra de un municipio
UMBRALES = {"5 °C", "6 °C"}


def _liga(*vals):
    return [v for v in vals if v not in UMBRALES]


def _hechos_municipio(R, x, i, campo="máxima"):
    """Dos hechos por municipio: lo previsto (ligado al municipio) y la normal (ligada a la estación)."""
    mun, est = nombre(x["mun"]), estacion(x["est"])
    sig = "más" if x["a"] > 0 else "menos"
    p, a, n = f"{R.f1(x['p'])} °C", f"{R.f1(abs(x['a']))} °C", f"{R.f1(x['n'])} °C"
    h1 = R.hecho(f"prev_{i}", f"AEMET prevé una {campo} de {p} en {mun} el {R.dia(x['f'])}, {a} {sig} "
                 f"que la {campo} normal 1991-2020 de la estación de AEMET de {est} para esa fecha.", FUENTE, [p, a], lugar=mun, liga=_liga(p, a))
    if est == mun:
        dice = f"La {campo} normal 1991-2020 de esa fecha en la estación de AEMET de {est} es de {n}; la estación está a {R.f1(x['km'])} km del centro del municipio."
    else:
        dice = f"La {campo} normal 1991-2020 de esa fecha en la estación de AEMET de {est} es de {n}; la estación está a {R.f1(x['km'])} km de {mun}."
    h2 = R.hecho(f"norm_{i}", dice, FUENTE, [n, R.f1(x["km"])], lugar=est, liga=_liga(n))
    return h1, h2


def _hecho_comparacion(R, campo="máxima"):
    """La comparación con la normal es nuestra, no de AEMET: el cuerpo lo dice una vez."""
    que = "máxima" if campo == "máxima" else "temperatura"
    return R.hecho("comp", f"La comparación con lo normal es del observatorio: cada {que} prevista por AEMET se compara con la normal "
                   "1991-2020 de la estación de AEMET de referencia que se nombra.", FUENTE, ["1991", "2020"])


def _avisos_lluvia(R, D):
    """Avisos de AEMET por lluvias o tormentas no caducados, por provincia: {cod: (nivel, tipos, zonas)} y la hora de consulta."""
    A = getattr(D, "A", None) or {}
    consulta = A.get("generado") or ""
    rango = {"amarillo": 1, "naranja": 2, "rojo": 3}
    por = {}
    for a in A.get("avisos") or []:
        if a.get("tipo") not in ("Lluvias", "Tormentas") or a.get("nivel") not in rango or not a.get("cod"):
            continue
        if consulta and str(a.get("fin") or "") and str(a["fin"]) < consulta:
            continue
        por.setdefault(a["cod"], []).append(a)
    out = {}
    for cod, avs in por.items():
        mx = max(avs, key=lambda a: rango[a["nivel"]])["nivel"]
        top = [a for a in avs if a["nivel"] == mx]
        tipos = sorted({a["tipo"].lower() for a in top})
        zonas = []
        for a in top:
            if a["zona"] not in zonas:
                zonas.append(a["zona"])
        out[cod] = (mx, tipos, zonas)
    return out, consulta


def _hecho_aviso_prov(R, cod, av, consulta):
    nivel, tipos, zonas = av
    zt = [R.zona_txt(z) for z in zonas]
    resto = len(zt) - 3
    lista = (", ".join(zt[:3]) + f" y {resto} {'zona' if resto == 1 else 'zonas'} más") if resto > 0 else R.lista_y(zt)
    vals = [R.hora(consulta)] + ([str(len(zt) - 3)] if len(zt) > 3 else [])
    return R.hecho("aviso_p", f"A las {R.hora(consulta)} del {R.dia(consulta)}, AEMET tenía emitido aviso {nivel} por {R.lista_y(tipos)} en {lista}.",
                   "AEMET vía MeteoAlarm", vals)


def _mejor(cands):
    """El municipio de cabecera: la mayor desviación, con preferencia por las estaciones a ≤ 10 km."""
    return max(cands, key=lambda x: (abs(x["a"]) - (0.5 if x["km"] > 10 else 0), -x["km"]))


def _titular(R, x, campo="máxima"):
    mun, est = nombre(x["mun"]), estacion(x["est"])
    sig = "más" if x["a"] > 0 else "menos"
    pre = f"AEMET prevé {R.f1(x['p'])} °C {'de mínima ' if campo == 'mínima' else ''}en {mun} el {R.dia(x['f'])}"
    if x["km"] <= 10:
        return f"{pre}, {R.f1(abs(x['a']))} °C {sig} de lo normal para la fecha"
    return f"{pre}, {R.f1(abs(x['a']))} °C {sig} que la normal de la estación de {est}"


def historia_calor(R, anoms, n_mun):
    cal = [x for x in anoms if x["a"] >= 5]
    if not cal:
        return None
    # una sola fila por municipio (su día más desviado)
    por_mun = {}
    for x in cal:
        k = (x["cod"], x["mun"])
        if k not in por_mun or x["a"] > por_mun[k]["a"]:
            por_mun[k] = x
    cal = sorted(por_mun.values(), key=lambda x: -x["a"])
    provs = sorted({x["cod"] for x in cal}, key=lambda c: R.sin_tildes(R.nprov(c)))
    top = _mejor(cal)
    hoy = R.HOY.isoformat()
    otros = []
    for cod in sorted(provs, key=lambda c: -max(x["a"] for x in cal if x["cod"] == c)):
        if cod == top["cod"]:
            continue
        otros.append(_mejor([x for x in cal if x["cod"] == cod]))
    otros = otros[:4]
    hechos = list(_hechos_municipio(R, top, 0))
    for i, x in enumerate(otros, 1):
        hechos.extend(_hechos_municipio(R, x, i))
    n_m, n_p = len(cal), len(provs)
    hechos.append(R.hecho("cuantos", f"En {R.plural(n_m, 'municipio', 'municipios')} de {R.plural(n_p, 'provincia', 'provincias')} "
                          f"({R.lista_y([R.nprov(c) for c in provs])}) la máxima que prevé AEMET para algún día de los próximos 6 supera en 5 °C o más "
                          f"la normal de su estación de referencia.", FUENTE, [str(n_m), str(n_p), "6", "5 °C"]))
    hechos.append(R.hecho("aviso", "Es la predicción de AEMET elaborada el " + R.dia(hoy) + "; AEMET la actualiza dos veces al día y puede cambiar.", FUENTE))
    comp = _hecho_comparacion(R)
    hechos.append(comp)
    tit = _titular(R, top)
    pl = {"titular": tit, "subtitulo": hechos[-3]["dice"], "entradilla": hechos[0]["dice"] + " " + hechos[1]["dice"],
          "cuerpo": [comp["dice"]] + [" ".join(h["dice"] for h in hechos[2 + 2 * k:4 + 2 * k]) for k in range(len(otros))] + [hechos[-2]["dice"]],
          "claves": [hechos[0]["dice"], hechos[-3]["dice"]]}
    cifras = [{"n": f"{R.f1(top['p'])} °C", "l": f"prevé AEMET en {nombre(top['mun'])} el {R.dia(top['f'])}", "tono": "calor"},
              {"n": f"+{R.f1(top['a'])} °C", "l": f"sobre la normal 1991-2020 de la estación de AEMET de {estacion(top['est'])}", "tono": "calor"},
              {"n": str(n_m), "l": f"{'municipio' if n_m == 1 else 'municipios'} de {R.plural(n_p, 'provincia', 'provincias')} a 5 °C o más de lo normal algún día", "tono": "calor"}]
    fuera = date.fromisoformat(top["f"]).month in (10, 11, 12, 1, 2, 3, 4)
    puntos = min(75, 45 + 4 * max(0, top["a"] - 5) + (6 if top["p"] >= 30 and fuera else 0) + min(10, 2 * n_p))
    h = R.historia("prevision_calor", f"{hoy}-prevision-calor", "Lo que viene · Predicción de AEMET", "calor", puntos, hechos, pl, cifras,
                   FUENTE, METODO, LIMITES, PAGINA)
    h["seccion"] = "calor"
    h["grafico"] = grafico_semana(R, top, f"{h['id']}")
    for cod in provs:
        mios = [x for x in cal if x["cod"] == cod]
        t = _mejor(mios)
        resto = [x for x in mios if x is not t][:2]
        hv = list(_hechos_municipio(R, t, 0))
        for i, x in enumerate(resto, 1):
            hv.append(_hechos_municipio(R, x, i)[0])
        P = R.nprov(cod)
        hv.append(R.hecho("cuantos_p", f"En {P}, {R.plural(len(mios), 'municipio tiene', 'municipios tienen')} algún día de los próximos 6 "
                          f"una máxima prevista 5 °C o más por encima de la normal de su estación de referencia.",
                          FUENTE, [str(len(mios)), "6", "5 °C"]))
        hv.append(R.hecho("nac", f"En toda España son {R.plural(n_m, 'municipio', 'municipios')} de {R.plural(n_p, 'provincia', 'provincias')}.",
                          FUENTE, [str(n_m), str(n_p)]))
        hv.append(hechos[-2])
        hv.append(comp)
        cuerpo = ([comp["dice"]] + ([" ".join(x["dice"] for x in hv[2:2 + len(resto)])] if resto else [])
                  + [hv[-4]["dice"] + " " + hv[-3]["dice"], hv[-2]["dice"]])
        plv = {"titular": _titular(R, t), "subtitulo": hv[1]["dice"], "entradilla": hv[0]["dice"], "cuerpo": cuerpo,
               "claves": [hv[0]["dice"], hv[1]["dice"]]}
        fuera_t = date.fromisoformat(t["f"]).month in (10, 11, 12, 1, 2, 3, 4)
        v = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": f"{R.f1(t['p'])} °C", "l": f"en {nombre(t['mun'])} el {R.dia(t['f'])}", "tono": "calor"},
                        {"n": f"+{R.f1(t['a'])} °C", "l": f"sobre la normal de la estación de AEMET de {estacion(t['est'])}", "tono": "calor"}],
             "puntos": round(min(72, 42 + 4 * max(0, t["a"] - 5) + (6 if t["p"] >= 30 and fuera_t else 0)), 1), "nivel": None}
        v["grafico"] = h["grafico"] if t is top else grafico_semana(R, t, f"{h['id']}-{cod}")
        h["provincias"][cod] = v
    return h


# ============================================================================ frío
def historia_frio(R, anom_x, anom_n):
    fx = [x for x in anom_x if x["a"] <= -5]
    fn = [x for x in anom_n if x["a"] <= -6 and x["km"] <= 10]
    if not fx and not fn:
        return None
    por_mun = {}
    for campo, lista in (("máxima", fx), ("mínima", fn)):
        for x in lista:
            k = (x["cod"], x["mun"])
            if k not in por_mun or x["a"] < por_mun[k][1]["a"]:
                por_mun[k] = (campo, x)
    filas = sorted(por_mun.values(), key=lambda cx: cx[1]["a"])
    provs = sorted({x["cod"] for _, x in filas}, key=lambda c: R.sin_tildes(R.nprov(c)))
    hoy = R.HOY.isoformat()
    campo, top = filas[0]
    hechos = list(_hechos_municipio(R, top, 0, campo))
    vistos = {top["cod"]}
    i = 1
    for c, x in filas[1:]:
        if x["cod"] in vistos or i > 4:
            continue
        vistos.add(x["cod"])
        hechos.extend(_hechos_municipio(R, x, i, c))
        i += 1
    hechos.append(R.hecho("cuantos", f"En {R.plural(len(filas), 'municipio', 'municipios')} de {R.plural(len(provs), 'provincia', 'provincias')} "
                          f"({R.lista_y([R.nprov(c) for c in provs])}) AEMET prevé algún día de los próximos 6 una máxima 5 °C o más por debajo de la normal "
                          f"de su estación de referencia o una mínima 6 °C o más por debajo.", FUENTE, [str(len(filas)), str(len(provs)), "6", "5 °C", "6 °C"]))
    hechos.append(R.hecho("aviso", "Es la predicción de AEMET elaborada el " + R.dia(hoy) + "; AEMET la actualiza dos veces al día y puede cambiar.", FUENTE))
    comp = _hecho_comparacion(R, "temperatura")
    hechos.append(comp)
    pl = {"titular": _titular(R, top, campo), "subtitulo": hechos[-3]["dice"], "entradilla": hechos[0]["dice"] + " " + hechos[1]["dice"],
          "cuerpo": [comp["dice"]] + [" ".join(h["dice"] for h in hechos[2 + 2 * k:4 + 2 * k]) for k in range(i - 1)] + [hechos[-2]["dice"]],
          "claves": [hechos[0]["dice"], hechos[-3]["dice"]]}
    pl["cuerpo"] = [c for c in pl["cuerpo"] if c]
    cifras = [{"n": f"{R.f1(top['p'])} °C", "l": f"de {campo} prevé AEMET en {nombre(top['mun'])} el {R.dia(top['f'])}", "tono": "lluvia"},
              {"n": f"−{R.f1(abs(top['a']))} °C", "l": f"bajo la normal de la estación de AEMET de {estacion(top['est'])}", "tono": "lluvia"}]
    puntos = min(68, 42 + 3 * (abs(top["a"]) - 5) + min(8, 2 * len(provs)))
    h = R.historia("prevision_frio", f"{hoy}-prevision-frio", "Lo que viene · Predicción de AEMET", "lluvia", puntos, hechos, pl, cifras,
                   FUENTE, METODO, LIMITES, PAGINA)
    h["seccion"] = "calor"
    cp = ("tx", "nx") if campo == "máxima" else ("tn", "nn")
    h["grafico"] = grafico_semana(R, top, h["id"], *cp, tono=R.LLUVIA)
    for cod in provs:
        mios = [cx for cx in filas if cx[1]["cod"] == cod]
        c, t = mios[0]
        hv = list(_hechos_municipio(R, t, 0, c))
        P = R.nprov(cod)
        hv.append(R.hecho("cuantos_p", f"En {P}, {R.plural(len(mios), 'municipio tiene', 'municipios tienen')} algún día de los próximos 6 "
                          f"una máxima prevista 5 °C o más por debajo de la normal, o una mínima 6 °C o más por debajo.", FUENTE,
                          [str(len(mios)), "6", "5 °C", "6 °C"]))
        hv.append(hechos[-2])
        hv.append(comp)
        plv = {"titular": _titular(R, t, c), "subtitulo": hv[1]["dice"], "entradilla": hv[0]["dice"],
               "cuerpo": [comp["dice"], hv[2]["dice"], hv[3]["dice"]], "claves": [hv[0]["dice"], hv[1]["dice"]]}
        v = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": f"{R.f1(t['p'])} °C", "l": f"de {c} en {nombre(t['mun'])} el {R.dia(t['f'])}", "tono": "lluvia"}],
             "puntos": round(min(65, 40 + 3 * (abs(t["a"]) - 5)), 1), "nivel": None}
        cpv = ("tx", "nx") if c == "máxima" else ("tn", "nn")
        v["grafico"] = h["grafico"] if t is top else grafico_semana(R, t, f"{h['id']}-{cod}", *cpv, tono=R.LLUVIA)
        h["provincias"][cod] = v
    return h


# ============================================================================ lluvia casi segura
def historia_lluvia(R, por_cod, n_mun, D=None):
    umbral = 90
    avisos, consulta = _avisos_lluvia(R, D)
    por_f, por_f_cod, n_cod = {}, {}, {}
    for cod, ms in por_cod.items():
        n_cod[cod] = len(ms)
        for m in ms:
            for d in m["dias"]:
                if (d.get("pp") or 0) >= umbral:
                    por_f.setdefault(d["f"], []).append((cod, m["n"]))
                    por_f_cod.setdefault((d["f"], cod), []).append(m["n"])
    if not por_f:
        return None
    f = max(por_f, key=lambda k: (len(por_f[k]), -date.fromisoformat(k).toordinal()))
    n = len(por_f[f])
    if n < 40:
        return None
    provs = {}
    for cod, mun in por_f[f]:
        provs.setdefault(cod, []).append(mun)
    orden = sorted(provs, key=lambda c: -len(provs[c]))
    hoy = R.HOY.isoformat()
    # las 6 primeras, más las empatadas con la sexta (si son muchas, «y otras N con X»)
    corte = len(provs[orden[5]]) if len(orden) > 6 else 0
    lista_p = [c for c in orden if len(provs[c]) > corte] if corte else orden[:6]
    empatadas = [c for c in orden if corte and len(provs[c]) == corte]
    if len(lista_p) + len(empatadas) <= 8:
        lista_p, resto_emp = lista_p + empatadas, []
    else:
        resto_emp = empatadas
    top_txt = R.lista_y([f"{R.nprov(c)} ({len(provs[c])})" for c in lista_p] + ([f"otras {len(resto_emp)} con {corte} cada una"] if resto_emp else []))
    hechos = [R.hecho("pp", f"AEMET da una probabilidad de lluvia del {umbral} % o más el {R.dia(f)} en {n} de los {n_mun} municipios con "
                      f"predicción de AEMET elaborada el {R.dia(hoy)} que sigue el observatorio, repartidos por "
                      f"{R.plural(len(provs), 'provincia', 'provincias')}.", FUENTE, [f"{umbral} %", str(n), str(n_mun), str(len(provs))]),
              R.hecho("pp_prov", f"Las provincias con más municipios en esa situación son {top_txt}.", FUENTE,
                      [str(len(provs[c])) for c in lista_p] + ([str(len(resto_emp)), str(corte)] if resto_emp else []))]
    otros = sorted((k for k in por_f if k != f and len(por_f[k]) >= 40), key=lambda k: k)
    if otros:
        hechos.append(R.hecho("pp_otros", "Otros días con 40 municipios o más a esa probabilidad: "
                              + "; ".join(f"el {R.dia(k)}, {len(por_f[k])}" for k in otros) + ".", FUENTE,
                              ["40"] + [str(len(por_f[k])) for k in otros]))
    fuertes = sorted((c for c, av in avisos.items() if av[0] in ("naranja", "rojo")), key=lambda c: R.sin_tildes(R.nprov(c)))
    if fuertes and consulta:
        rojos = [c for c in fuertes if avisos[c][0] == "rojo"]
        naranjas = [c for c in fuertes if avisos[c][0] == "naranja"]
        partes = ([f"rojo en {R.lista_y([R.nprov(c) for c in rojos])}"] if rojos else []) + \
                 ([f"naranja en {R.lista_y([R.nprov(c) for c in naranjas])}"] if naranjas else [])
        hechos.append(R.hecho("avisos_nac", f"Además, a las {R.hora(consulta)} del {R.dia(consulta)}, AEMET tenía emitidos avisos por lluvias o "
                              f"tormentas de nivel {' y '.join(partes)}.", "AEMET vía MeteoAlarm", [R.hora(consulta)]))
    hechos.append(R.hecho("aviso", "Es la predicción de AEMET elaborada el " + R.dia(hoy) + "; la probabilidad de precipitación no dice cuánta lluvia "
                          "caerá.", FUENTE))
    pl = {"titular": f"AEMET da un {umbral} % o más de probabilidad de lluvia el {R.dia(f)} en {n} municipios de {R.plural(len(provs), 'provincia', 'provincias')}",
          "subtitulo": hechos[1]["dice"], "entradilla": hechos[0]["dice"], "cuerpo": [h["dice"] for h in hechos[1:]],
          "claves": [hechos[0]["dice"], hechos[1]["dice"]]}
    cifras = [{"n": str(n), "l": f"municipios con probabilidad de lluvia del {umbral} % o más el {R.dia(f)}", "tono": "lluvia"},
              {"n": str(len(provs)), "l": "provincias", "tono": "lluvia"}]
    puntos = min(62, 40 + n / 15)
    h = R.historia("prevision_lluvia", f"{hoy}-prevision-lluvia", "Lo que viene · Predicción de AEMET", "lluvia", puntos, hechos, pl, cifras,
                   FUENTE, "Probabilidad de precipitación diaria de la predicción municipal de AEMET elaborada el día de publicación; "
                   "solo días futuros.", LIMITES[:1] + LIMITES[2:], PAGINA)
    h["seccion"] = "agua"
    h["grafico"] = grafico_lluvia(R, {k: len(v) for k, v in por_f.items()}, h["id"], "España")
    for cod, nn in n_cod.items():
        dias_c = {k[0]: len(v) for k, v in por_f_cod.items() if k[1] == cod}
        if not dias_c:
            continue
        fc = max(dias_c, key=lambda k: (dias_c[k], -date.fromisoformat(k).toordinal()))
        mun = por_f_cod[(fc, cod)]
        if len(mun) < max(3, nn // 4):
            continue
        P = R.nprov(cod)
        nombres = [nombre(x) for x in mun]
        lista = (", ".join(nombres[:8]) + f" y {len(nombres) - 8} más") if len(nombres) > 8 else R.lista_y(nombres)
        hv = [R.hecho("pp_p", f"AEMET da una probabilidad de lluvia del {umbral} % o más el {R.dia(fc)} en {len(mun)} de los {nn} municipios de {P} "
                      f"con predicción de AEMET elaborada el {R.dia(hoy)}: {lista}.", FUENTE,
                      [f"{umbral} %", str(len(mun)), str(nn)] + ([str(len(nombres) - 8)] if len(nombres) > 8 else [])),
              R.hecho("pp_nac", hechos[0]["dice"], FUENTE, hechos[0]["valores"])]
        if cod in avisos and consulta:
            hv.append(_hecho_aviso_prov(R, cod, avisos[cod], consulta))
        hv.append(hechos[-1])
        otros_c = sorted(k for k in dias_c if k != fc and dias_c[k] >= max(3, nn // 4))
        if otros_c:
            hv.insert(1, R.hecho("pp_p_otros", f"En {P} también hay {'otro día' if len(otros_c) == 1 else 'otros días'} con al menos "
                                 f"{max(3, nn // 4)} municipios a esa probabilidad: " + "; ".join(f"el {R.dia(k)}, {dias_c[k]}" for k in otros_c) + ".",
                                 FUENTE, [str(max(3, nn // 4))] + [str(dias_c[k]) for k in otros_c]))
        plv = {"titular": f"AEMET da un {umbral} % o más de probabilidad de lluvia el {R.dia(fc)} en {len(mun)} municipios de {P}",
               "subtitulo": hv[1]["dice"], "entradilla": hv[0]["dice"], "cuerpo": [x["dice"] for x in hv[1:]], "claves": [hv[0]["dice"]]}
        v = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": str(len(mun)), "l": f"de {nn} municipios con probabilidad de lluvia del {umbral} % o más el {R.dia(fc)}", "tono": "lluvia"}],
             "puntos": round(min(58, 36 + 2 * len(mun)), 1), "nivel": None}
        cuenta = {k: dias_c.get(k, 0) for k in sorted({k for k in por_f})}
        v["grafico"] = grafico_lluvia(R, cuenta, f"{h['id']}-{cod}", P)
        h["provincias"][cod] = v
    return h


def generar(R, D):
    por_cod, n_mun = leer_prediccion(R)
    if not n_mun:
        R.LOG.append("prevision: ninguna predicción municipal elaborada hoy")
        return []
    ax = anomalias(por_cod, "tx", "nx")
    an = anomalias(por_cod, "tn", "nn")
    out = []
    for fn, args in ((historia_calor, (R, ax, n_mun)), (historia_frio, (R, ax, an)), (historia_lluvia, (R, por_cod, n_mun, D))):
        try:
            h = fn(*args)
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"prevision/{fn.__name__}: {type(e).__name__}: {e}")
            h = None
        if h:
            out.append(h)
    return out
