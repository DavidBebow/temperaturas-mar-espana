"""El planeta: indicadores globales con su fuente oficial.

- Temperatura del planeta: ERA5 de Copernicus (C3S/ECMWF) vía Climate Pulse, docs/temperatura_global.json
  (obtener_temperatura_global.py). Es el producto global oficial. El dato diario es de Copernicus; la media del año y
  el puesto los calcula el observatorio, así que se dicen «con datos de Copernicus». El puesto del año en curso compara el mismo tramo del calendario en cada año desde 1940.
- Hielo marino: NSIDC Sea Ice Index (NASA/NOAA), docs/deshielo.json; la normal es la media 1981-2010 para esa fecha.
- Glaciares: Servicio Mundial de Vigilancia de Glaciares (WGMS, Fluctuations of Glaciers), docs/glaciares/; balance de
  masa anual medido (mm de agua equivalente) y variación acumulada del frente (m). La Maladeta (Huesca) lleva versión
  provincial.

No se usan: docs/emisiones_co2.json (inventario anual por país del Global Carbon Project con datos de 2023: no hay un
dato nuevo) ni docs/reloj_climatico.json (Climate Clock es un proyecto divulgativo, no un organismo que mida).

Las historias de esta sección no cambian de id cada día: llevan delante el lunes de la semana (la temperatura y el
hielo se rehacen a diario dentro de la misma historia) o la fecha de la edición del dato.
"""
from __future__ import annotations

from datetime import date

SECCION = "planeta"
ORD = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto", 5: "quinto"}


def _lunes(iso):
    d = date.fromisoformat(str(iso)[:10])
    return date.fromordinal(d.toordinal() - d.weekday()).isoformat()


def _f2(x):
    return f"{float(x):.2f}".replace(".", ",")


def _f3(x):
    return f"{float(x):.3f}".replace(".", ",")


# ---------------------------------------------------------------------------- temperatura del planeta
def _temperatura(R):
    t = R.leer(R.DOCS / "temperatura_global.json", {}) or {}
    if not t.get("fuente_ok") or not t.get("fecha_dato"):
        return None
    a = t.get("anyo_en_curso") or {}
    if not isinstance(a, dict) or not a.get("puesto") or a.get("media_preindustrial") is None:
        return None
    fd = t["fecha_dato"]
    if (R.HOY - date.fromisoformat(fd)).days > 7:
        return None  # dato viejo: Climate Pulse se ha parado
    puesto, anio = int(a["puesto"]), int(a["anyo"])
    fuente = "Copernicus (ERA5, C3S/ECMWF) vía Climate Pulse"
    prov = " (dato provisional)" if (t.get("estado") or "").upper() == "PRELIMINARY" else ""
    hasta = R.dia(fd, semana=False)
    hechos = [
        R.hecho("tg_anio", f"Entre el 1 de enero y el {hasta} de {anio}, la temperatura media del planeta estuvo {R.f1(a['media_preindustrial'])} °C por encima "
                f"de la era preindustrial, con datos de Copernicus.", fuente, [f"{R.f1(a['media_preindustrial'])} °C", str(anio)]),
        R.hecho("tg_puesto", f"Es el {ORD.get(puesto, str(puesto) + '.º')} valor más alto para ese tramo del año en la serie de Copernicus, que empieza en 1940.",
                fuente, ["1940"], superlativo=True, record=puesto == 1),
        R.hecho("tg_dia", f"El {hasta} de {anio}, la temperatura media del planeta fue de {_f2(t['t_absoluta'])} °C, {_f2(t['anomalia_preindustrial'])} °C por encima "
                f"de la era preindustrial{prov}.", fuente, [f"{_f2(t['t_absoluta'])} °C", f"{_f2(t['anomalia_preindustrial'])} °C"]),
    ]
    if t.get("dias_sobre_15_ultimo_anyo") is not None:
        hechos.append(R.hecho("tg_15", f"En los últimos 365 días, {t['dias_sobre_15_ultimo_anyo']} estuvieron al menos 1,5 °C por encima de la era preindustrial; "
                              f"el Acuerdo de París se refiere a la media de varias décadas, no a días sueltos.", fuente, [str(t["dias_sobre_15_ultimo_anyo"]), "1,5 °C"]))
    hechos.append(R.hecho("tg_ref", "La era preindustrial es la media de 1850-1900; Copernicus la calcula sumando 0,88 °C a la anomalía frente a 1991-2020.",
                          fuente, ["1850", "1900", "0,88 °C", "1991", "2020"]))
    if puesto == 1:
        tit = (f"{anio}, el año más cálido a estas alturas de la serie de Copernicus, que empieza en 1940: el planeta va {R.f1(a['media_preindustrial'])} °C "
               f"por encima de la era preindustrial")
    else:
        tit = (f"{anio}, el {ORD.get(puesto, str(puesto) + '.º')} año más cálido a estas alturas de la serie de Copernicus, que empieza en 1940: "
               f"el planeta va {R.f1(a['media_preindustrial'])} °C por encima de la era preindustrial")
    pl = {"titular": tit, "subtitulo": hechos[2]["dice"], "entradilla": hechos[0]["dice"] + " " + hechos[1]["dice"],
          "cuerpo": [hechos[2]["dice"]] + ([hechos[3]["dice"]] if len(hechos) > 4 else []) + [hechos[-1]["dice"]],
          "claves": [h["dice"] for h in hechos[:3]]}
    cifras = [{"n": f"+{R.f1(a['media_preindustrial'])} °C", "l": f"temperatura media del planeta en {anio} hasta el {hasta}, frente a la era preindustrial", "tono": "calor"},
              {"n": f"+{_f2(t['anomalia_preindustrial'])} °C", "l": f"el {hasta}", "tono": "calor"}]
    if t.get("dias_sobre_15_ultimo_anyo") is not None:
        cifras.append({"n": str(t["dias_sobre_15_ultimo_anyo"]), "l": "días por encima de +1,5 °C en los últimos 365", "tono": "calor"})
    h = R.historia("temperatura_global", f"{_lunes(R.HOY.isoformat())}-temperatura-del-planeta", "El planeta · temperatura global", "calor",
                   60 if puesto == 1 else (45 if puesto == 2 else 32), hechos, pl, cifras, fuentes=fuente,
                   metodo="Media diaria global del aire a 2 metros del reanálisis ERA5 (Copernicus, Climate Pulse). El puesto compara la media desde el 1 de enero "
                          "hasta la misma fecha en cada año desde 1940.",
                   limites=["El dato de los últimos días es provisional y Copernicus lo puede retocar."], pagina="https://calentamientoglobal.es/temperatura-del-planeta/")
    h["fecha"] = fd
    return h


# ---------------------------------------------------------------------------- hielo marino
def _grafico_hielo(R, d, nombre):
    W, Hh, gap = 960, 330, 40
    pw = (W - gap) / 2
    ml, mr, mt, mb = 46, 12, 28, 34
    s, filas = [], []
    for k, (clave, titulo_p) in enumerate((("arctic", "Ártico"), ("antarctic", "Antártida"))):
        x = d[clave]
        serie = [(int(a), float(b)) for a, b in x["serie"]]
        media = [(int(a), float(b)) for a, b in x["media"]]
        vals = [v for _, v in serie + media]
        lo, hi = int(min(vals)) - 1, int(max(vals)) + 2
        ox = k * (pw + gap)
        X = lambda dd, ox=ox: ox + ml + (dd - 1) / 365 * (pw - ml - mr)
        Y = lambda v, lo=lo, hi=hi: mt + (hi - v) / (hi - lo) * (Hh - mt - mb)
        s.append(R._t(ox + ml, 16, titulo_p, 14, R.TINTA, "start", 700))
        paso = 2 if hi - lo <= 12 else 4
        for t in range(lo + (lo % paso), hi + 1, paso):
            s.append(f'<line x1="{ox + ml:.1f}" x2="{ox + pw - mr:.1f}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{R.RAYA}" stroke-width="1"></line>')
            s.append(R._t(ox + ml - 6, Y(t) + 4, str(t), 11, R.GRIS, "end"))
        for i, mes in enumerate(R.MESES):
            dd = date(2025, i + 1, 1).timetuple().tm_yday
            s.append(R._t(X(dd + 14), Hh - mb + 18, mes[:3].capitalize(), 11, R.GRIS, "middle"))
        s.append('<polyline fill="none" stroke="#8A8277" stroke-width="2" stroke-dasharray="5 4" points="'
                 + " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in media) + '"></polyline>')
        s.append(f'<polyline fill="none" stroke="{R.LLUVIA}" stroke-width="2.6" points="' + " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in serie) + '"></polyline>')
        ua, ub = serie[-1]
        s.append(f'<circle cx="{X(ua):.1f}" cy="{Y(ub):.1f}" r="4" fill="{R.LLUVIA}"></circle>')
        s.append(R._t(X(ua) + 6, Y(ub) + 16 if clave == "antarctic" else Y(ub) - 8, f"{_f2(ub)}", 12, R.TINTA, "start", 700))
        for a, b in serie:
            filas.append((titulo_p, a, b, ""))
        for a, b in media:
            filas.append((titulo_p, a, "", b))
    titulo = "Extensión del hielo marino en el Ártico y la Antártida (millones de km²)"
    svg = R._svg(W, Hh, titulo, s)
    return R.guardar_grafico(nombre, svg, filas, ["zona", "dia_del_anio", "extension_2026_millones_km2", "media_1981_2010_millones_km2"], titulo,
                             [{"t": "linea", "c": R.LLUVIA, "l": "2026"}, {"t": "discontinua", "c": "#8A8277", "l": "Media 1981-2010"}],
                             "Extensión diaria del hielo marino (media de 5 días). Fuente: NSIDC Sea Ice Index (NASA/NOAA). Gráfico: calentamientoglobal.es.")


def _hielo(R):
    d = R.leer(R.DOCS / "deshielo.json", {}) or {}
    ar, an = d.get("arctic") or {}, d.get("antarctic") or {}
    if not ar.get("fecha") or not an.get("fecha") or ar.get("anom") is None or an.get("anom") is None:
        return None
    fd = ar["fecha"]
    if (R.HOY - date.fromisoformat(fd)).days > 7:
        return None
    fuente = "NSIDC Sea Ice Index (NASA/NOAA)"
    dfe = R.dia(fd, semana=False)
    pa, pb = abs(float(ar["anom_pct"])), abs(float(an["anom_pct"]))
    debajo_a, debajo_b = float(ar["anom"]) < 0, float(an["anom"]) < 0
    hechos = [
        R.hecho("hielo_artico", f"El {dfe}, el hielo marino del Ártico ocupaba {_f2(ar['ext'])} millones de km², según el NSIDC (NASA/NOAA): "
                f"{_f2(abs(ar['anom']))} millones de km² {'menos' if debajo_a else 'más'} que la media de 1981-2010 para esa fecha ({_f2(ar['normal'])}), "
                f"un {R.f1(pa)} % {'por debajo' if debajo_a else 'por encima'}.", fuente,
                [_f2(ar["ext"]), _f2(abs(ar["anom"])), _f2(ar["normal"]), f"{R.f1(pa)} %", "1981", "2010"]),
        R.hecho("hielo_antartida", f"En la Antártida, el hielo marino ocupaba {_f2(an['ext'])} millones de km², {_f2(abs(an['anom']))} millones {'menos' if debajo_b else 'más'} "
                f"que su media de 1981-2010 ({_f2(an['normal'])}), un {R.f1(pb)} % {'por debajo' if debajo_b else 'por encima'}.", fuente,
                [_f2(an["ext"]), _f2(abs(an["anom"])), _f2(an["normal"]), f"{R.f1(pb)} %"]),
    ]
    falta = abs(float(ar["anom"])) + (abs(float(an["anom"])) if debajo_b else 0)
    veces = int(falta * 1e6 / 506000)
    if debajo_a and veces >= 2:
        hechos.append(R.hecho("hielo_espana", f"Lo que falta en {'los dos polos' if debajo_b else 'el Ártico'} frente a su media, {_f2(falta)} millones de km², equivale a más de "
                              f"{veces} veces la superficie de España, que es de unos 506.000 km² según el INE.", "NSIDC; superficie de España: INE",
                              [_f2(falta), str(veces), "506.000"]))
    if debajo_a and debajo_b:
        tit = f"Los dos polos, con menos hielo de lo normal: el Ártico, un {R.f1(pa)} % por debajo de su media para el {dfe}"
    elif debajo_a:
        tit = f"El hielo marino del Ártico, un {R.f1(pa)} % por debajo de su media para el {dfe}"
    else:
        tit = f"El hielo marino de la Antártida, un {R.f1(pb)} % {'por debajo' if debajo_b else 'por encima'} de su media para el {dfe}"
    pl = {"titular": tit, "subtitulo": hechos[1]["dice"], "entradilla": hechos[0]["dice"],
          "cuerpo": [h["dice"] for h in hechos[1:]] + ["La media de referencia es la del periodo 1981-2010 para el mismo día del año, que usa el NSIDC."],
          "claves": [h["dice"] for h in hechos]}
    hechos.append(R.hecho("hielo_ref", "La media de referencia es la del periodo 1981-2010 para el mismo día del año, que usa el NSIDC.", fuente, ["1981", "2010"]))
    cifras = [{"n": f"−{R.f1(pa)} %" if debajo_a else f"+{R.f1(pa)} %", "l": f"hielo marino del Ártico frente a su media 1981-2010, el {dfe}", "tono": "lluvia"},
              {"n": f"−{R.f1(pb)} %" if debajo_b else f"+{R.f1(pb)} %", "l": "hielo marino de la Antártida frente a su media", "tono": "lluvia"}]
    puntos = 30 + min(15, max(pa, pb if debajo_b else 0) / 2)
    base = f"{_lunes(R.HOY.isoformat())}-hielo-marino"
    h = R.historia("hielo_marino", base, "El planeta · hielo marino", "lluvia", puntos, hechos, pl, cifras, fuentes=fuente,
                   metodo="Extensión diaria del hielo marino del NSIDC Sea Ice Index (media móvil de 5 días) frente a la media 1981-2010 del mismo día.",
                   limites=["Los datos del último día son provisionales."], pagina="https://calentamientoglobal.es/deshielo-de-los-polos/")
    h["fecha"] = fd
    try:
        h["grafico"] = _grafico_hielo(R, d, base)
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"planeta: gráfico del hielo: {e}")
    return h


# ---------------------------------------------------------------------------- glaciares (WGMS)
def _grafico_glaciar(R, nombre_g, serie, nombre):
    W, Hh, ml, mr, mt, mb = 640, 280, 48, 12, 18, 30
    vals = [v for _, v in serie]
    lo = min(-1000, (min(vals) // 500) * 500)
    hi = max(500, -(-max(vals) // 500) * 500)
    Y = lambda v: mt + (hi - v) / (hi - lo) * (Hh - mt - mb)
    bw = (W - ml - mr) / len(serie)
    s = []
    for t in range(int(lo), int(hi) + 1, 500):
        s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{R.RAYA if t else R.GRIS}" stroke-width="1"></line>')
        s.append(R._t(ml - 6, Y(t) + 4, R.miles(t).replace("-", "−"), 11, R.GRIS, "end"))
    ult = serie[-1][0]
    for i, (a, v) in enumerate(serie):
        x0 = ml + i * bw + 1.5
        col = R.CALOR if a == ult else ("#E3A487" if v < 0 else R.LLUVIA)
        s.append(f'<rect x="{x0:.1f}" y="{min(Y(v), Y(0)):.1f}" width="{bw - 3:.1f}" height="{abs(Y(0) - Y(v)):.1f}" fill="{col}"></rect>')
        if a % 5 == 0 or a == ult:
            s.append(R._t(x0 + (bw - 3) / 2, Hh - mb + 16, str(a), 10.5, R.TINTA if a == ult else R.GRIS, "middle", 700 if a == ult else 400))
    titulo = f"Balance de masa anual del glaciar de la {nombre_g.title()} (mm de agua equivalente)"
    svg = R._svg(W, Hh, titulo, s)
    return R.guardar_grafico(nombre, svg, serie, ["anio", "balance_masa_mm_agua_equivalente"], titulo, [],
                             "Balance de masa glaciológico anual: por debajo de cero, el glaciar pierde hielo. Fuente: Servicio Mundial de Vigilancia de Glaciares (WGMS). "
                             "Gráfico: calentamientoglobal.es.")


def _glaciares(R):
    carpeta = R.DOCS / "glaciares"
    idx = R.leer(carpeta / "indice.json", {}) or {}
    ser = R.leer(carpeta / "series.json", {}) or {}
    if not idx.get("g") or not ser:
        return None
    f = idx["f"]
    filas = [dict(zip(f, g)) for g in idx["g"]]
    ult = max((r["mb1"] for r in filas if r.get("mb1")), default=None)
    if not ult:
        return None
    vals = []
    for r in filas:
        if r.get("mb1") != ult:
            continue
        s = ser.get(str(r["id"]))
        if not s or not s[0]:
            continue
        y0, arr = s[0]
        i = ult - int(y0)
        if 0 <= i < len(arr) and arr[i] is not None:
            vals.append((r, float(arr[i])))
    if len(vals) < 30:
        return None
    pierden = sum(1 for _, v in vals if v < 0)
    version = str(idx.get("v") or "WGMS")
    fuente = "Servicio Mundial de Vigilancia de Glaciares (WGMS)"
    hechos = [R.hecho("glac_mundo", f"En la base de datos del Servicio Mundial de Vigilancia de Glaciares (WGMS) que usa el observatorio, {len(vals)} glaciares tienen "
                      f"balance de masa medido en {ult}: {pierden} perdieron hielo.", fuente, [str(len(vals)), str(ult), str(pierden)])]
    mal = next((r for r in filas if r.get("n") == "MALADETA" and r.get("c") == "ES"), None)
    cod_huesca = next((k for k, v in R.PROV.items() if v[1] == "huesca"), None)
    serie_m = None
    if mal:
        s = ser.get(str(mal["id"])) or [None, None]
        if s[0]:
            y0, arr = s[0]
            serie_m = [(int(y0) + i, int(v)) for i, v in enumerate(arr) if v is not None]
    hm = []
    if serie_m and serie_m[-1][0] == ult and serie_m[-1][1] < 0:
        v_ult = serie_m[-1][1]
        peor = min(serie_m, key=lambda x: x[1])
        acum = sum(v for _, v in serie_m)
        a0 = serie_m[0][0]
        hm.append(R.hecho("glac_maladeta", f"El glaciar de la Maladeta, en el Pirineo de Huesca, perdió en {ult} una masa de hielo equivalente a {R.miles(abs(v_ult))} mm de agua, "
                          f"según el WGMS: una capa de {R.f1(abs(v_ult) / 1000)} metros de agua repartida por todo el glaciar.", fuente,
                          [str(ult), R.miles(abs(v_ult)), R.f1(abs(v_ult) / 1000)], lugar="Maladeta"))
        if acum < 0 and peor[1] < 0:
            hm.append(R.hecho("glac_maladeta_serie", f"Desde {a0}, el balance acumulado de la Maladeta es una pérdida equivalente a {R.miles(abs(acum))} mm de agua; "
                              f"su peor año fue {peor[0]}, con {R.miles(abs(peor[1]))} mm.", fuente,
                              [str(a0), R.miles(abs(acum)), str(peor[0]), R.miles(abs(peor[1]))], superlativo=True))
        # La variación del frente (docs/glaciares, campo fv) no se usa: en 2022 salta 560 m de golpe y no está claro si
        # es un retroceso o un cambio de referencia del frente al fragmentarse el glaciar.
    hechos += hm
    tit = f"{pierden} de {len(vals)} glaciares con balance medido perdieron hielo en {ult}, con datos del WGMS"
    pl = {"titular": tit, "subtitulo": hm[0]["dice"] if hm else "", "entradilla": hechos[0]["dice"],
          "cuerpo": [" ".join(x["dice"] for x in hm)] if hm else [hechos[0]["dice"]],
          "claves": [x["dice"] for x in hechos[:3]]}
    cifras = [{"n": f"{pierden} de {len(vals)}", "l": f"glaciares con balance medido que perdieron hielo en {ult}", "tono": "lluvia"}]
    if hm:
        cifras.append({"n": f"{R.miles(abs(serie_m[-1][1]))} mm", "l": f"de agua equivalente perdió la Maladeta en {ult}", "tono": "calor"})
    edicion = version.split()[-1] if version.split()[-1][:4].isdigit() else R.HOY.isoformat()
    base = f"{_lunes(R.HOY.isoformat())}-glaciares-{ult}"
    h = R.historia("glaciares", base, "El planeta · glaciares", "lluvia", 32, hechos, pl, cifras, fuentes=fuente,
                   metodo=f"Base de datos Fluctuations of Glaciers del WGMS (edición {edicion}): balance de masa glaciológico anual y variación del frente.",
                   limites=["Los glaciares con balance medido son una muestra de los del mundo, no todos.", "El último año puede revisarse en la siguiente edición."],
                   pagina="https://calentamientoglobal.es/glaciares-estado/")
    h["fecha"] = edicion
    if serie_m:
        try:
            h["grafico"] = _grafico_glaciar(R, "Maladeta", serie_m, base)
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"planeta: gráfico glaciar: {e}")
    if hm and cod_huesca:
        hv = hm + [hechos[0]]
        plv = {"titular": f"El glaciar de la Maladeta perdió en {ult} el equivalente a {R.f1(abs(serie_m[-1][1]) / 1000)} metros de agua, con datos del WGMS",
               "subtitulo": hm[1]["dice"] if len(hm) > 1 else "", "entradilla": hm[0]["dice"], "cuerpo": [" ".join(x["dice"] for x in hv[1:])], "claves": [x["dice"] for x in hv[:3]]}
        h["provincias"][cod_huesca] = {"provincia": R.nprov(cod_huesca), "slug": R.PROV[cod_huesca][1], "hechos": hv, "plantilla": plv,
                                       "cifras": cifras[1:] + cifras[:1], "puntos": 40, "grafico": h.get("grafico")}
    return h


def generar(R, D):
    out = []
    for fn in (_temperatura, _hielo, _glaciares):
        try:
            h = fn(R)
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"planeta.{fn.__name__}: {type(e).__name__}: {e}")
            h = None
        if h:
            h["seccion"] = SECCION
            out.append(h)
    return out
