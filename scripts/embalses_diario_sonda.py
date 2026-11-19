#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embalses_diario_sonda.py — Prueba de viabilidad del dato DIARIO de embalses
============================================================================
Repo PUBLICO (temperaturas-mar-espana): scripts/embalses_diario_sonda.py
Lo lanza .github/workflows/embalses_diario_sonda.yml (a mano o al subirlo).

NO publica ningun dato de embalses ni toca los JSON existentes. Solo llama
UNA vez a cada fuente candidata y deja un informe con lo que responde:

  docs/embalses/sonda_diario.json   informe completo (para analizarlo)
  docs/embalses/sonda_diario.md     resumen legible (tambien en el run)

Fuentes que prueba:
  1. MITECO, capa nacional SAIH "Embalses: nivel/volumen" (GeoServer)
  2. Datos abiertos con API: Duero (CKAN), Guadalquivir (WFS),
     Cataluna (Socrata), Andalucia (REDIAM "Embalses al dia")
  3. Webs SAIH de cada organismo de cuenca (descubre sus paginas de embalses)

Cortesia: una peticion por URL, pausa entre peticiones, cabecera que nos
identifica, y en las webs SAIH (no en las API publicadas en catalogos
oficiales) se respeta robots.txt. Nunca falla el job: todo error se anota.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

SALIDA_DIR = os.environ.get("SALIDA_DIR", "docs")
OUT_DIR = os.path.join(SALIDA_DIR, "embalses")
UA = ("Mozilla/5.0 (compatible; CalentamientoGlobal-sonda/1.0; "
      "+https://calentamientoglobal.es/embalses-espana/)")
CABECERA = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "es-ES,es;q=0.9"}
TIMEOUT = int(os.environ.get("SONDA_TIMEOUT", "40"))
PAUSA = float(os.environ.get("SONDA_PAUSA", "1.5"))
MAX_BYTES = 6_000_000
MAX_SEGUNDO_NIVEL = 6

RE_INTERES = re.compile(r"embals|presa|pantano|volum|reserva|parte[-_ ]?diario|"
                        r"descarga|open ?data|datos|api|json|csv|xls|wfs|informe", re.I)
RE_EMBALSE = re.compile(r"embals|pantano|reserva|parte", re.I)
RE_FECHA = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})(?:[ T]\d{1,2}:\d{2})?")

# ─────────────────────────────────────────────────────────────────────────────
# Fuentes
# ─────────────────────────────────────────────────────────────────────────────
GEOSERVER_MITECO = "https://gis.miteco.gob.es/geoserver/agua/embalses_et"

# API / servicios publicados en catalogos oficiales de datos abiertos.
API = [
    # Ebro: ¿algún nombre de servidor del SAIH acepta conexiones desde GitHub?
    ("Ebro", "API volúmenes (www)", "https://www.saihebro.com/api/principal/getVolumenesEmbalsados"),
    ("Ebro", "API volúmenes (ssl)", "https://ssl.saihebro.com/api/principal/getVolumenesEmbalsados"),
    ("Ebro", "API volúmenes (website)", "https://website.saihebro.com/api/principal/getVolumenesEmbalsados"),
    ("Ebro", "API volúmenes (ebs)", "https://ebs.saihebro.com/api/principal/getVolumenesEmbalsados"),
    ("Ebro", "API volúmenes (apidocs)", "https://apidocs.saihebro.com/api/principal/getVolumenesEmbalsados"),
    ("Ebro", "Informes: parte diario de embalses (ssl)", "https://ssl.saihebro.com/datos/informes"),
    ("Ebro", "Informes: parte diario de embalses (apidocs)", "https://apidocs.saihebro.com/datos/informes"),
    # Madrid: datos abiertos del Canal de Isabel II (embalses del Tajo en Madrid)
    ("Madrid (Canal de Isabel II)", "JSON de datos abiertos",
     "https://datos.comunidad.madrid/dataset/7fdba62f-03e0-4f36-a35f-7771652ecf6e/resource/"
     "e3d2e0d0-5241-467e-9f9d-d9b3bb61d6a5/download/"
     "volumen-de-agua-embalsada-en-los-embalses-del-canal-de-isabel-ii.json"),
    ("Madrid (Canal de Isabel II)", "CKAN package_show",
     "https://datos.comunidad.madrid/api/3/action/package_show?id=7fdba62f-03e0-4f36-a35f-7771652ecf6e"),
    # API pública de MapasDeEmbalses.es (un embalse del Tajo y uno del Ebro, de muestra)
    ("MapasDeEmbalses.es", "API pública: Buendía", "https://mapasdeembalses.es/api/v1/embalses/buendia"),
    ("MapasDeEmbalses.es", "API pública: Mequinenza", "https://mapasdeembalses.es/api/v1/embalses/mequinenza"),
    ("MapasDeEmbalses.es", "API pública: Alarcón", "https://mapasdeembalses.es/api/v1/embalses/alarcon"),
]

# Webs SAIH: se abre la portada, se listan los enlaces de interes y se visitan
# hasta MAX_SEGUNDO_NIVEL paginas que hablen de embalses. Respetan robots.txt.
WEBS = [
    ("MITECO, visor nacional de redes de seguimiento", ["https://sig.miteco.gob.es/redes-seguimiento/"]),
]

# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────
_robots = {}


def robots_permite(url):
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers=CABECERA, timeout=15)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        _robots[base] = rp
        time.sleep(0.5)
    try:
        return _robots[base].can_fetch(UA, url)
    except Exception:
        return True


def limpiar(html):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", t).strip()


def resumen_json(obj):
    out = {}
    if isinstance(obj, dict):
        out["claves"] = list(obj.keys())[:40]
        feats = obj.get("features")
        if isinstance(feats, list):
            out["n_features"] = len(feats)
            out["total_declarado"] = obj.get("totalFeatures", obj.get("numberMatched"))
            if feats:
                props = feats[0].get("properties") or feats[0].get("attributes") or {}
                out["campos"] = list(props.keys())
                out["muestra"] = [(f.get("properties") or f.get("attributes") or {})
                                  for f in feats[:3]]
        res = obj.get("result")
        if isinstance(res, dict) and isinstance(res.get("resources"), list):
            out["ckan_titulo"] = res.get("title")
            out["ckan_licencia"] = res.get("license_title")
            out["ckan_frecuencia"] = res.get("frequency") or [
                e.get("value") for e in res.get("extras", []) if "frec" in str(e.get("key", "")).lower()]
            out["ckan_notas"] = str(res.get("notes"))[:600]
            out["ckan_recursos"] = [{"nombre": r.get("name"), "formato": r.get("format"),
                                     "url": r.get("url"), "modificado": r.get("last_modified")}
                                    for r in res["resources"]]
        if "claves" in out and len(out) == 1:
            out["muestra"] = str(obj)[:2600]
    elif isinstance(obj, list):
        out["n_elementos"] = len(obj)
        if obj and isinstance(obj[0], dict):
            out["campos"] = list(obj[0].keys())
            out["muestra"] = obj[:3]
        else:
            out["muestra"] = obj[:5]
    return out


def resumen_xml(txt):
    out = {}
    nombres = re.findall(r"<(?:\w+:)?Name>([^<]{1,120})</(?:\w+:)?Name>", txt)
    titulos = re.findall(r"<(?:\w+:)?Title>([^<]{1,160})</(?:\w+:)?Title>", txt)
    out["nombres_capa"] = list(dict.fromkeys(nombres))[:40]
    out["titulos"] = list(dict.fromkeys(titulos))[:20]
    campos = re.findall(r'<xsd?:element[^>]*name="([^"]+)"[^>]*type="([^"]+)"', txt)
    if campos:
        out["campos"] = [f"{n} ({t})" for n, t in campos][:60]
    out["formatos_json"] = bool(re.search(r"application/json", txt))
    exc = re.search(r"<(?:\w+:)?(?:ServiceException|ExceptionText)[^>]*>([^<]{1,400})", txt)
    if exc:
        out["excepcion"] = exc.group(1).strip()
    return out


def resumen_html(txt, url):
    out = {}
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", txt)
    out["titulo"] = limpiar(m.group(1))[:160] if m else None
    tablas = re.findall(r"(?is)<table[^>]*>(.*?)</table>", txt)
    out["n_tablas"] = len(tablas)
    mejor = max(tablas, key=len) if tablas else None
    if mejor:
        filas = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", mejor)
        out["tabla_mayor_filas"] = len(filas)
        out["tabla_mayor_muestra"] = [
            [limpiar(c)[:40] for c in re.findall(r"(?is)<t[hd][^>]*>(.*?)</t[hd]>", f)][:12]
            for f in filas[:12]]
    texto = limpiar(txt)
    out["menciones_hm3"] = len(re.findall(r"hm\s?[3³]", texto, re.I))
    out["menciones_embalse"] = len(re.findall(r"embalse", texto, re.I))
    out["fechas_vistas"] = list(dict.fromkeys(m.group(0) for m in RE_FECHA.finditer(texto)))[:8]
    enlaces = {}
    for href, etq in re.findall(r'(?is)<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', txt):
        etq = limpiar(etq)[:70]
        if RE_INTERES.search(href) or RE_INTERES.search(etq):
            enlaces.setdefault(urljoin(url, href.strip()), etq)
    out["enlaces_interes"] = [{"url": u, "texto": t} for u, t in list(enlaces.items())[:45]]
    # Pistas de API que usa la propia pagina (JS)
    pistas = set(re.findall(r'["\'](https?://[^"\']{8,200}|/[^"\' ]{3,160})["\']', txt))
    out["pistas_api"] = sorted(p for p in pistas if re.search(
        r"api|json|ashx|asmx|wfs|ows|geoserver|rest/|FeatureServer|MapServer|WebServices|"
        r"embals|datos", p, re.I) and not re.search(r"\.(css|png|jpg|svg|woff2?|ico)(\?|$)", p, re.I))[:40]
    out["texto_inicio"] = texto[:400]
    return out


def pedir(url, respetar_robots=False):
    r = {"url": url}
    if respetar_robots and not robots_permite(url):
        r.update(ok=False, error="robots.txt no lo permite: no se pide")
        return r, None
    t0 = time.time()
    try:
        resp = requests.get(url, headers=CABECERA, timeout=TIMEOUT, allow_redirects=True, stream=True)
        cuerpo = b""
        for trozo in resp.iter_content(65536):
            cuerpo += trozo
            if len(cuerpo) > MAX_BYTES:
                r["truncado"] = True
                break
        resp.close()
    except requests.RequestException as e:
        r.update(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}",
                 segundos=round(time.time() - t0, 1))
        time.sleep(PAUSA)
        return r, None
    ct = resp.headers.get("Content-Type", "")
    r.update(ok=resp.status_code == 200, status=resp.status_code, tipo=ct, bytes=len(cuerpo),
             segundos=round(time.time() - t0, 1), cors=resp.headers.get("Access-Control-Allow-Origin"),
             ultima_modificacion=resp.headers.get("Last-Modified"))
    if resp.url != url:
        r["url_final"] = resp.url
    txt = None
    if "pdf" in ct.lower() or cuerpo[:4] == b"%PDF":
        r["clase"] = "pdf"
    elif re.search(r"zip|octet|excel|spreadsheet", ct, re.I):
        r["clase"] = "binario"
    else:
        txt = cuerpo.decode(resp.encoding or "utf-8", errors="replace")
        cab = txt.lstrip()[:200].lower()
        try:
            if cab[:1] in "[{":
                r["clase"] = "json"
                r["json"] = resumen_json(json.loads(txt))
            elif cab.startswith("<?xml") or "<wfs:" in cab or "<wms_capabilities" in cab \
                    or "<xsd:schema" in cab or "serviceexception" in cab:
                r["clase"] = "xml"
                r["xml"] = resumen_xml(txt)
            else:
                r["clase"] = "html"
                r["html"] = resumen_html(txt, resp.url)
        except Exception as e:  # el informe nunca debe romperse por un parseo
            r["clase"] = "desconocido"
            r["error_parseo"] = f"{type(e).__name__}: {e}"
            r["inicio"] = txt[:600]
    time.sleep(PAUSA)
    return r, txt


# ─────────────────────────────────────────────────────────────────────────────
# Pasadas
# ─────────────────────────────────────────────────────────────────────────────
def pasada_api(informe):
    capas = []
    for ambito, que, url in API:
        print(f"[API] {ambito} — {que}")
        r, txt = pedir(url)
        r.update(ambito=ambito, que=que)
        informe["api"].append(r)
        if ambito == "MITECO nacional" and r.get("clase") == "xml":
            capas += [n for n in r["xml"].get("nombres_capa", [])
                      if not re.search(r"^(WMS|WFS|OGC|GetCap|GetMap|GetFeature)", n, re.I)]
        # Duero: seguir los recursos que declare CKAN
        if ambito == "Duero" and r.get("json", {}).get("ckan_recursos"):
            for rec in r["json"]["ckan_recursos"][:4]:
                if rec.get("url"):
                    print(f"[API] Duero — recurso {rec.get('formato')}")
                    r2, _ = pedir(rec["url"])
                    r2.update(ambito="Duero", que=f"Recurso CKAN: {rec.get('nombre')} ({rec.get('formato')})")
                    informe["api"].append(r2)



def pasada_webs(informe):
    for ambito, portadas in WEBS:
        bloque = {"ambito": ambito, "paginas": []}
        vistos, cola = set(), []
        for url in portadas:
            print(f"[WEB] {ambito} — {url}")
            r, _ = pedir(url, respetar_robots=True)
            r["nivel"] = 1
            bloque["paginas"].append(r)
            vistos.add(url)
            host = urlparse(r.get("url_final", url)).netloc.split(":")[0]
            raiz = ".".join(host.split(".")[-2:])
            for e in (r.get("html") or {}).get("enlaces_interes", []):
                u = e["url"]
                if (u.startswith("http") and urlparse(u).netloc.endswith(raiz)
                        and (RE_EMBALSE.search(u) or RE_EMBALSE.search(e["texto"]))
                        and not re.search(r"\.(pdf|zip|xlsx?|docx?|jpg|png)(\?|$)", u, re.I)):
                    cola.append(u)
        for u in list(dict.fromkeys(cola)):
            if u in vistos or len(vistos) >= len(portadas) + MAX_SEGUNDO_NIVEL:
                continue
            vistos.add(u)
            print(f"[WEB] {ambito} —   > {u}")
            r, _ = pedir(u, respetar_robots=True)
            r["nivel"] = 2
            bloque["paginas"].append(r)
        informe["webs"].append(bloque)


# Las webs ajenas llevan a veces claves suyas incrustadas en el JS (mapas, etc.).
# Nunca deben acabar en nuestro informe: se tachan antes de escribir nada.
_TACHAR = [
    (re.compile(r"\b(?:pk|sk|tk)\.eyJ[\w\-.]+"), "[oculto]"),
    (re.compile(r"eyJ[\w\-]{15,}\.[\w\-.]+"), "[oculto]"),
    (re.compile(r"AIza[\w\-]{30,}"), "[oculto]"),
    (re.compile(r"(?i)\b(api[_-]?key|apikey|access[_-]?token|token|key|secret|password|pwd|sig)=[^&\"'\s<>]+"),
     r"\1=[oculto]"),
    (re.compile(r"[A-Za-z0-9_\-]{44,}"), "[largo]"),
]


def tachar(o):
    if isinstance(o, str):
        for rx, sub in _TACHAR:
            o = rx.sub(sub, o)
        return o
    if isinstance(o, dict):
        return {tachar(k) if isinstance(k, str) else k: tachar(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [tachar(v) for v in o]
    return o


def veredicto_api(r):
    if not r.get("ok"):
        return "NO — " + (r.get("error") or f"HTTP {r.get('status')}")[:170]
    c = r.get("clase")
    if c == "json":
        j = r["json"]
        n = j.get("n_features", j.get("n_elementos"))
        if j.get("ckan_recursos") is not None:
            return f"SI — CKAN, {len(j['ckan_recursos'])} recursos"
        return f"SI — JSON, {n} registros, campos: {', '.join(map(str, (j.get('campos') or [])[:60]))}"
    if c == "xml":
        x = r["xml"]
        if x.get("excepcion"):
            return "RESPONDE CON ERROR — " + x["excepcion"][:160]
        return "SI — XML; capas: " + ", ".join(x.get("nombres_capa", [])[:6])
    if c == "html":
        h = r["html"]
        return f"SI — HTML «{h.get('titulo')}», {h.get('n_tablas')} tablas, {h.get('menciones_hm3')} menciones hm3"
    return f"SI — {c}, {r.get('bytes')} bytes"


def escribir(informe):
    informe = tachar(informe)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "sonda_diario.json"), "w", encoding="utf-8") as f:
        json.dump(informe, f, ensure_ascii=False, indent=1, default=str)
    L = [f"# Sonda del dato diario de embalses — {informe['generado']}", "",
         "No publica datos: solo anota qué responde cada fuente.", "",
         "## Servicios y API", "", "| Ámbito | Qué | Resultado |", "|---|---|---|"]
    for r in informe["api"]:
        L.append(f"| {r['ambito']} | {r['que']} | {veredicto_api(r).replace('|', '/')} |")
    L += ["", "## Webs SAIH", "",
          "| Cuenca | Página | HTTP | Tablas | hm³ | Fechas vistas |", "|---|---|---|---|---|---|"]
    for b in informe["webs"]:
        for p in b["paginas"]:
            h = p.get("html") or {}
            est = p.get("status") or (p.get("error") or "")[:50]
            L.append(f"| {b['ambito']} | {p['url'][:90]} | {est} | {h.get('n_tablas', '')} | "
                     f"{h.get('menciones_hm3', '')} | {', '.join(h.get('fechas_vistas', [])[:3])} |")
    md = "\n".join(L) + "\n"
    with open(os.path.join(OUT_DIR, "sonda_diario.md"), "w", encoding="utf-8") as f:
        f.write(md)
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write(md)
    print("\n" + md)


def main():
    informe = {"generado": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               "version": "2.0", "api": [], "webs": []}
    for nombre, pasada in (("api", pasada_api), ("webs", pasada_webs)):
        try:
            pasada(informe)
        except Exception as e:  # pase lo que pase, se escribe lo que haya
            informe[f"error_{nombre}"] = f"{type(e).__name__}: {e}"
            print(f"Pasada {nombre} interrumpida: {e}")
    escribir(informe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
