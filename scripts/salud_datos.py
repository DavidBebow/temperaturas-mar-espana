#!/usr/bin/env python3
"""
Vigilante de salud de los datos del Observatorio climático (calentamientoglobal.es).

Lee docs/salud/herramientas.json (manifiesto), comprueba cada herramienta:
  - que su archivo exista y sea JSON válido,
  - cuándo se generó (campo del JSON, o el último run correcto del workflow,
    o el último commit del archivo),
  - si está dentro de su ventana de frescura,
  - sus guardas de contenido (número de elementos, claves, booleanos),
  - cómo acabó el último run de su workflow (API de GitHub Actions),
  - y, si la entrada lleva «contraste», que lo publicado sea cierto según su
    propia regla (sumas que cuadran, fuente y método declarados, años con
    huecos que no se dan por completos). Ver CONTRASTES más abajo.

Escribe:
  docs/salud/estado.json        estado actual de todas las herramientas
  docs/salud/historial.json     una línea por pasada (30 días) para el gráfico
  docs/salud/incidencias.json   cambios de estado (últimos 300)

Y avisa por Telegram solo cuando algo cambia de estado (empeora o se recupera),
más un parte diario a las 07 UTC si hay algo que no está bien.

No toca ningún otro archivo ni script. Si no puede hablar con la API de GitHub,
sigue con lo que tiene y lo anota en el estado.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
SALUD = RAIZ / "docs" / "salud"
MANIFIESTO = SALUD / "herramientas.json"
ESTADO = SALUD / "estado.json"
HISTORIAL = SALUD / "historial.json"
INCIDENCIAS = SALUD / "incidencias.json"

REPO = os.environ.get("GITHUB_REPOSITORY", "davidbebow/temperaturas-mar-espana")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
PAGINA_ESTADO = "https://calentamientoglobal.es/estado-de-los-datos/"

MADRID = ZoneInfo("Europe/Madrid")
AHORA = datetime.now(timezone.utc).replace(microsecond=0)

# Un error vale más que un aviso, que vale más que un ok.
PESO = {"ok": 0, "estatico": 0, "aviso": 1, "error": 2}


# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------
def log(*a):
    print(*a, flush=True)


def parsear_fecha(v) -> datetime | None:
    """Acepta los formatos que conviven en el repo:
    2026-10-11T11:01+02:00 · 2026-10-10T23:11Z · 2026-10-10T20:26:41.092056 (sin zona)
    2026-10-05 · 10/10/2026 a las 20:26 · 10/10/2026
    Sin zona horaria se asume UTC (los runners de GitHub van en UTC)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v if v < 1e11 else v / 1000, tz=timezone.utc)
        except Exception:
            return None
    s = str(v).strip()
    if not s:
        return None
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})(?:\D+(\d{2}):(\d{2}))?", s)
    if m:
        d, mo, y, hh, mm = m.groups()
        return datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), tzinfo=timezone.utc)
    s2 = s.replace("Z", "+00:00")
    # 2026-10-10T23:11+00:00 (sin segundos) también lo acepta fromisoformat en 3.11+
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
        if not m:
            return None
        dt = datetime.fromisoformat(m.group(1))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def horas(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    return round((AHORA - dt).total_seconds() / 3600, 2)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def legible(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.astimezone(MADRID).strftime("%d/%m/%Y %H:%M")


def leer_json(p: Path, defecto):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def escribir_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


# ----------------------------------------------------------------------------
# GitHub API
# ----------------------------------------------------------------------------
_api_ok = True


def api(path: str, params: dict | None = None):
    global _api_ok
    url = f"https://api.github.com/repos/{REPO}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "salud-datos-calentamientoglobal",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        log(f"  [api] {path}: {e}")
        _api_ok = False
        return None


_runs_cache: dict[str, dict] = {}


def runs_workflow(yml: str) -> dict:
    """Último run (cualquier resultado) y último run correcto de un workflow."""
    if yml in _runs_cache:
        return _runs_cache[yml]
    out = {"ultimo": None, "ultimo_ok": None, "fallos_seguidos": 0}
    data = api(f"/actions/workflows/{yml}/runs", {"per_page": 10, "exclude_pull_requests": "true"})
    runs = (data or {}).get("workflow_runs") or []
    seguidos = 0
    contando = True
    for r in runs:
        if r.get("status") != "completed":
            continue
        item = {
            "conclusion": r.get("conclusion"),
            "fecha": r.get("updated_at"),
            "url": r.get("html_url"),
            "evento": r.get("event"),
            "numero": r.get("run_number"),
        }
        if out["ultimo"] is None:
            out["ultimo"] = item
        if r.get("conclusion") == "success":
            if out["ultimo_ok"] is None:
                out["ultimo_ok"] = item
            contando = False
        elif contando and r.get("conclusion") in ("failure", "timed_out"):
            seguidos += 1
    out["fallos_seguidos"] = seguidos
    _runs_cache[yml] = out
    return out


def fecha_commit(ruta: str) -> datetime | None:
    data = api("/commits", {"path": ruta, "per_page": 1})
    if not data:
        return None
    try:
        return parsear_fecha(data[0]["commit"]["committer"]["date"])
    except Exception:
        return None


# ----------------------------------------------------------------------------
# comprobación de una herramienta
# ----------------------------------------------------------------------------
def guardas(data, reglas: dict | None) -> list[str]:
    """Devuelve la lista de guardas que NO se cumplen (vacía = todo bien)."""
    fallos = []
    if not reglas or not isinstance(data, dict):
        return fallos
    r = reglas.get("clave_existe")
    if r and r not in data:
        fallos.append(f"falta la clave «{r}»")
    r = reglas.get("verdadero")
    if r and not data.get(r):
        fallos.append(f"«{r}» no es verdadero")
    r = reglas.get("min_elementos")
    if r:
        v = data.get(r["clave"])
        n = len(v) if isinstance(v, (list, dict)) else 0
        if n < r["min"]:
            fallos.append(f"«{r['clave']}» tiene {n} elementos (mínimo {r['min']})")
    r = reglas.get("min_numero")
    if r:
        v = data.get(r["clave"])
        try:
            if v is None or float(v) < r["min"]:
                fallos.append(f"«{r['clave']}» = {v} (mínimo {r['min']})")
        except (TypeError, ValueError):
            fallos.append(f"«{r['clave']}» no es un número ({v!r})")
    return fallos


# ----------------------------------------------------------------------------
# contrastes de veracidad (18-10-2026)
# ----------------------------------------------------------------------------
# Las guardas miran que el archivo tenga la forma esperada. Los contrastes miran
# que lo que se publica sea cierto según su propia regla: que el total sea la
# suma de sus días, que el dato salga de la estación o del producto que dice la
# página, que no se dé por completo un año con huecos. Cada contraste devuelve
# una lista de (nivel, texto): «error» si una cifra publicada no cuadra, «aviso»
# si el dato está incompleto o el método no es el acordado, «info» solo se anota.
HOY = AHORA.astimezone(MADRID).date()


def _edad(fecha) -> int | None:
    dt = parsear_fecha(fecha)
    return (HOY - dt.date()).days if dt else None


def _entero(x: float) -> int:
    """Redondeo comercial, el mismo que usa calor_mortalidad_generar.py."""
    import math
    return int(math.floor(float(x) + 0.5))


def _lista(nombres: list[str], n: int = 6) -> str:
    return ", ".join(nombres[:n]) + (f" y {len(nombres) - n} más" if len(nombres) > n else "")


def c_calor_mortalidad(d: dict) -> list:
    out = []
    if d.get("metodo_suma") != "diaria_sin_redondear":
        out.append(("aviso", "los totales aún se suman con los valores diarios ya redondeados"))
    dias = d.get("dias") or []
    va = d.get("verano_actual") or {}
    if dias and all("exacto" in x for x in dias) and va.get("atribuibles_calor") is not None:
        suma = _entero(sum(x["exacto"] for x in dias))
        if va["atribuibles_calor"] != suma:
            out.append(("error", f"el total nacional del verano ({va['atribuibles_calor']}) no es la suma "
                                  f"de sus días ({suma})"))
    malas = []
    for slug, p in (d.get("provincias") or {}).items():
        vals = p.get("valores_exactos")
        if vals and p.get("verano") is not None and p["verano"] != _entero(sum(vals)):
            malas.append(f"{p.get('nombre', slug)} ({p['verano']} frente a {_entero(sum(vals))})")
    if malas:
        out.append(("error", "el total del verano no es la suma de sus días en " + _lista(malas)))
    return out


def c_temperaturas_mar(d: dict) -> list:
    out = []
    if d.get("metodo") != "oisst_v21_normal_1991_2020":
        out.append(("aviso", "el dato no sale del método acordado (NOAA OISST v2.1 con normal 1991-2020 de la misma celda)"))
    e = _edad(d.get("fecha_dato"))
    if e is not None and e > 5:
        out.append(("aviso", f"el dato más reciente es de hace {e} días ({d.get('fecha_dato')})"))
    pts = d.get("puntos") or []
    sin = [p.get("nombre", p.get("id")) for p in pts if p.get("temperatura_actual") is None]
    if sin:
        out.append(("aviso", f"{len(sin)} de {len(pts)} puntos sin dato: " + _lista(sin)))
    malas = []
    for p in pts:
        t, n, a = p.get("temperatura_actual"), p.get("media_1991_2020_dia"), p.get("anomalia")
        if None not in (t, n, a) and abs((t - n) - a) > 0.151:
            malas.append(f"{p.get('nombre')} ({t} − {n} ≠ {a})")
    if malas:
        out.append(("error", "la anomalía no es la temperatura menos su normal en " + _lista(malas)))
    prov = sum(1 for p in pts if p.get("provisional"))
    if prov:
        out.append(("info", f"{prov} punto{'s' if prov > 1 else ''} con el dato preliminar de la NOAA"))
    return out


def c_noches_tropicales(d: dict) -> list:
    out = []
    cs = d.get("ciudades") or []
    if d.get("total_ciudades") is not None and d["total_ciudades"] != len(cs):
        out.append(("error", f"dice {d['total_ciudades']} ciudades y publica {len(cs)}"))
    e = _edad(d.get("fecha_anoche"))
    if e is not None and e > 3:
        out.append(("aviso", f"la última noche publicada es de hace {e} días ({d.get('fecha_anoche')})"))
    sin_est = [c.get("nombre", c.get("id")) for c in cs if not c.get("idema") or "cobertura_anyo" not in c]
    if sin_est:
        out.append(("aviso", f"{len(sin_est)} ciudades sin estación o cobertura declarada: " + _lista(sin_est)))
    baja = [f"{c.get('nombre')} ({round(100 * c['cobertura_anyo'])} %)" for c in cs
            if isinstance(c.get("cobertura_anyo"), (int, float)) and c["cobertura_anyo"] < 0.9]
    if baja:
        out.append(("info", "con menos del 90 % de los días del año (la página lo advierte): " + _lista(baja)))
    paradas = [c.get("nombre") for c in cs if c.get("ultimo_dato") and (_edad(c["ultimo_dato"]) or 0) > 10]
    if paradas:
        out.append(("info", "estaciones sin dato en más de 10 días (salen en gris): " + _lista(paradas)))
    return out


def c_dias32_estaciones(d: dict) -> list:
    out = []
    est = d.get("estaciones") or {}
    malas, fuera = [], []
    for slug, s in est.items():
        a = s.get("actual") or {}
        if a.get("dias") is not None and a.get("dias_con_dato") is not None and a["dias"] > a["dias_con_dato"]:
            malas.append(slug)
        if a.get("estacion_parada") or (a.get("cobertura") or 0) < 0.95:
            fuera.append(f"{s.get('estacion', slug)}")
    if malas:
        out.append(("error", "más días de calor que días con dato en " + _lista(malas)))
    if fuera:
        out.append(("info", "sin cifra de estación este año (cobertura < 95 % o parada): " + _lista(fuera)))
    if d.get("archivo_pendiente_anios"):
        out.append(("info", f"quedan {d['archivo_pendiente_anios']} años de archivo por descargar (las medias se completan solas)"))
    return out


def c_dias32_era5(d: dict) -> list:
    out = []
    if "ERA5" not in str(d.get("fuente", "")):
        out.append(("aviso", "la fuente no dice que es reanálisis ERA5"))
    if not d.get("aviso"):
        # el JSON se rehace cada mes; hasta entonces la página ya lo rotula como ERA5
        out.append(("info", "el JSON aún no lleva el aviso de que es la celda ERA5 y no la estación"))
    return out


def c_grados_dia(d: dict) -> list:
    out = []
    provs = d.get("provincias") or {}
    if len(provs) < 50:
        out.append(("aviso", f"solo {len(provs)} de 52 provincias"))
    fin = parsear_fecha(d.get("fin"))
    esperado = HOY.year - 1 if (HOY.month, HOY.day) >= (1, 19) else HOY.year - 2
    if fin and fin.year < esperado:
        out.append(("aviso", f"el último año calculado es {fin.year}; debería estar {esperado}"))
    descuadre = [n for n, p in provs.items()
                 if len({len(p.get(k) or []) for k in ("years", "hdd", "cdd21", "cdd24")}) != 1]
    if descuadre:
        out.append(("error", "series de distinta longitud en " + _lista(descuadre)))
    if "ERA5" not in str(d.get("fuente", "")):
        out.append(("aviso", "la fuente no dice que es reanálisis ERA5 de modelo fijo"))
    return out


def c_mediterraneo(d: dict) -> list:
    out = []
    h = leer_json(RAIZ / "docs" / "dana" / "mediterraneo_historico.json", None)
    v = (h or {}).get("v") or {}
    if not v:
        return [("aviso", "no se puede leer la serie histórica del Mediterráneo")]
    ini = datetime.fromisoformat("1981-09-01").date()
    fin = datetime.fromisoformat(max(v)).date()
    faltan = (fin - ini).days + 1 - sum(1 for k in v if k >= "1981-09-01")
    if faltan > 10:
        out.append(("aviso", f"a la serie diaria desde 1981 le faltan {faltan} días (se rellenan desde el ERDDAP de upwell)"))
    elif faltan:
        out.append(("info", f"a la serie diaria desde 1981 le falta{'n' if faltan > 1 else ''} {faltan} día{'s' if faltan > 1 else ''}"))
    return out


def c_provincias(d: dict) -> list:
    """Recorre las 52 fichas: la cifra de días > 32 °C, si sale, tiene que ser la de la
    estación de AEMET y coincidir con dias32_estaciones.json cuando ambos van a la misma fecha."""
    out = []
    est = (leer_json(RAIZ / "docs" / "dias32_estaciones.json", {}) or {}).get("estaciones", {})
    no_aemet, distinta, con = [], [], 0
    for f in sorted((RAIZ / "docs" / "provincias").glob("*.json")):
        p = leer_json(f, None)
        if not isinstance(p, dict):
            continue
        d32 = (p.get("indicadores") or {}).get("dias32")
        if not d32:
            continue
        con += 1
        if d32.get("fuente") != "AEMET":
            no_aemet.append(p.get("provincia", f.stem))
        s = (est.get(p.get("slug") or f.stem) or {}).get("actual") or {}
        if s.get("hasta") and s.get("hasta") == d32.get("hasta") and s.get("dias") != d32.get("actual"):
            distinta.append(f"{p.get('provincia', f.stem)} ({d32.get('actual')} frente a {s.get('dias')})")
    if no_aemet:
        out.append(("error", "días de más de 32 °C publicados sin ser de estación en " + _lista(no_aemet)))
    if distinta:
        out.append(("error", "la ficha no da la misma cifra que la estación en " + _lista(distinta)))
    out.append(("info", f"{con} fichas con días de más de 32 °C medidos en estación"))
    return out


CONTRASTES = {
    "calor_mortalidad": c_calor_mortalidad,
    "temperaturas_mar": c_temperaturas_mar,
    "noches_tropicales": c_noches_tropicales,
    "dias32_estaciones": c_dias32_estaciones,
    "dias32_era5": c_dias32_era5,
    "grados_dia": c_grados_dia,
    "mediterraneo": c_mediterraneo,
    "provincias": c_provincias,
}


def contrastar(h: dict, datos, res: dict) -> None:
    nombre = h.get("contraste")
    if not nombre or nombre not in CONTRASTES or not isinstance(datos, dict):
        return
    try:
        hallazgos = CONTRASTES[nombre](datos)
    except Exception as e:  # un contraste roto no tumba la comprobación
        hallazgos = [("aviso", f"el contraste de veracidad no se pudo hacer: {str(e)[:120]}")]
    res["contraste"] = {
        "nombre": nombre,
        "superado": not any(n in ("aviso", "error") for n, _ in hallazgos),
        "hallazgos": [{"nivel": n, "texto": t} for n, t in hallazgos],
    }
    for nivel, texto in hallazgos:
        res["detalles"].append(("veracidad: " if nivel != "info" else "") + texto)
        if nivel == "info":
            continue
        if PESO[nivel] > PESO.get(res["estado"], 0):
            res["estado"] = nivel
            res["motivo"] = "contraste de veracidad: " + texto


def comprobar(h: dict) -> dict:
    res = {
        "id": h["id"],
        "nombre": h["nombre"],
        "familia": h.get("familia", "Otros"),
        "archivo": h.get("archivo"),
        "workflow": h.get("workflow"),
        "cadencia": h.get("cadencia"),
        "ventana_h": h.get("ventana_h"),
        "pagina": h.get("pagina"),
        "fuente": h.get("fuente"),
        "estado": "ok",
        "motivo": None,
        "detalles": [],
        "generado": None,
        "generado_legible": None,
        "generado_origen": None,
        "horas": None,
        "dato_del": None,
        "bytes": None,
        "run": None,
    }
    archivo = h.get("archivo")
    datos = None
    existe = False

    if archivo:
        p = RAIZ / archivo
        if p.is_dir():
            existe = any(p.iterdir())
            if existe:
                res["bytes"] = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        elif p.is_file():
            existe = True
            res["bytes"] = p.stat().st_size
            try:
                with open(p, encoding="utf-8") as f:
                    datos = json.load(f)
            except Exception as e:
                res["estado"] = "error"
                res["motivo"] = "el archivo no es JSON válido"
                res["detalles"].append(str(e)[:160])
        if not existe:
            res["estado"] = "error"
            res["motivo"] = "el archivo no existe en el repositorio"

    # --- hora de generación -------------------------------------------------
    gen = None
    for campo in h.get("campo_fecha") or []:
        if isinstance(datos, dict) and campo in datos:
            gen = parsear_fecha(datos.get(campo))
            if gen:
                res["generado_origen"] = f"campo «{campo}»"
                break
    if isinstance(datos, dict) and h.get("campo_dato") and datos.get(h["campo_dato"]) is not None:
        v = datos.get(h["campo_dato"])
        res["dato_del"] = str(v)[:10] if isinstance(v, str) else str(v)

    # --- workflow ---------------------------------------------------------------
    run = None
    if h.get("workflow"):
        run = runs_workflow(h["workflow"])
        res["run"] = run
        if gen is None and run.get("ultimo_ok"):
            gen = parsear_fecha(run["ultimo_ok"]["fecha"])
            if gen:
                res["generado_origen"] = "último run correcto"
    if gen is None and archivo and existe:
        gen = fecha_commit(archivo)
        if gen:
            res["generado_origen"] = "último commit"

    res["generado"] = iso(gen)
    res["generado_legible"] = legible(gen)
    res["horas"] = horas(gen)

    # --- frescura ----------------------------------------------------------------
    ventana = h.get("ventana_h")
    if ventana is None:
        if res["estado"] == "ok":
            res["estado"] = "estatico"
            res["motivo"] = "dato estático, solo se comprueba que exista"
    elif res["estado"] != "error":
        if gen is None:
            res["estado"] = "aviso"
            res["motivo"] = "no se sabe cuándo se generó"
        elif res["horas"] > ventana:
            # Si el proceso sí corrió bien dentro de la ventana, el dato de
            # origen no ha cambiado (p. ej. sin incendios nuevos): no es fallo.
            ok_reciente = None
            if run and run.get("ultimo_ok"):
                ok_reciente = horas(parsear_fecha(run["ultimo_ok"]["fecha"]))
            if ok_reciente is not None and ok_reciente <= ventana:
                res["detalles"].append(f"el proceso corrió bien hace {_dur(ok_reciente)} pero el dato no cambió")
            elif res["horas"] > ventana * 3:
                res["estado"] = "error"
                res["motivo"] = f"sin actualizar desde hace {_dur(res['horas'])} (ventana {_dur(ventana)})"
            else:
                res["estado"] = "aviso"
                res["motivo"] = f"lleva {_dur(res['horas'])} sin refrescar (ventana {_dur(ventana)})"

    # --- guardas -------------------------------------------------------------------
    if datos is not None:
        f = guardas(datos, h.get("guardas"))
        if f:
            res["detalles"].extend(f)
            if res["estado"] in ("ok", "estatico", "aviso"):
                res["estado"] = "error"
                res["motivo"] = "el contenido no pasa las guardas: " + "; ".join(f)

    # --- contrastes de veracidad ----------------------------------------------------
    contrastar(h, datos, res)

    # --- último run fallido con dato fresco → aviso leve -----------------------
    if run and run.get("ultimo") and run["ultimo"].get("conclusion") in ("failure", "timed_out"):
        n = run.get("fallos_seguidos", 1)
        txt = f"el último run del workflow falló ({n} seguido{'s' if n != 1 else ''})"
        res["detalles"].append(txt)
        if res["estado"] in ("ok", "estatico"):
            res["estado"] = "aviso"
            res["motivo"] = txt + ", aunque el dato está al día"
    if run and run.get("ultimo") is None and h.get("workflow") and _api_ok:
        res["detalles"].append("sin runs completados en los últimos 10")

    return res


def _dur(h: float) -> str:
    h = float(h)
    if h < 1:
        return f"{int(round(h * 60))} min"
    if h < 48:
        return f"{h:.0f} h"
    return f"{h / 24:.0f} días"


# ----------------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------------
def telegram(texto: str) -> bool:
    if not TG_TOKEN or not TG_CHAT:
        log("  [telegram] sin credenciales, no se envía")
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    cuerpo = urllib.parse.urlencode({
        "chat_id": TG_CHAT, "text": texto, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=cuerpo), timeout=30) as r:
            return r.status == 200
    except Exception as e:
        log(f"  [telegram] {e}")
        return False


ICONO = {"ok": "🟢", "estatico": "⚪", "aviso": "🟠", "error": "🔴"}


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def linea_tg(r: dict) -> str:
    s = f"{ICONO[r['estado']]} <b>{_esc(r['nombre'])}</b>"
    if r.get("motivo"):
        s += f" — {_esc(r['motivo'])}"
    enlaces = []
    if r.get("run") and r["run"].get("ultimo") and r["estado"] != "ok":
        enlaces.append(f"<a href=\"{r['run']['ultimo']['url']}\">run</a>")
    if r.get("pagina"):
        enlaces.append(f"<a href=\"{r['pagina']}\">página</a>")
    if enlaces:
        s += " · " + " · ".join(enlaces)
    return s


# ----------------------------------------------------------------------------
# principal
# ----------------------------------------------------------------------------
def main() -> int:
    man = leer_json(MANIFIESTO, None)
    if not man:
        log("No se puede leer el manifiesto; no se escribe nada.")
        return 1
    anterior = leer_json(ESTADO, {}) or {}
    ant_por_id = {h["id"]: h for h in anterior.get("herramientas", [])}

    resultados = []
    for h in man["herramientas"]:
        log(f"· {h['id']}")
        try:
            r = comprobar(h)
        except Exception as e:  # nunca tumbar la pasada por una herramienta
            r = {"id": h["id"], "nombre": h["nombre"], "familia": h.get("familia", "Otros"),
                 "estado": "error", "motivo": f"el vigilante no pudo comprobarla: {e}",
                 "detalles": [], "pagina": h.get("pagina"), "fuente": h.get("fuente"),
                 "cadencia": h.get("cadencia"), "ventana_h": h.get("ventana_h"),
                 "archivo": h.get("archivo"), "workflow": h.get("workflow"),
                 "generado": None, "generado_legible": None, "generado_origen": None,
                 "horas": None, "dato_del": None, "bytes": None, "run": None}
        log(f"   {r['estado']}  {r.get('motivo') or ''}")
        resultados.append(r)

    # --- transiciones ----------------------------------------------------------------
    incidencias = leer_json(INCIDENCIAS, []) or []
    nuevas = []
    for r in resultados:
        antes = ant_por_id.get(r["id"], {}).get("estado")
        ahora = r["estado"]
        if antes is None or antes == ahora:
            continue
        inc = {
            "fecha": iso(AHORA), "id": r["id"], "nombre": r["nombre"],
            "de": antes, "a": ahora, "motivo": r.get("motivo"),
            "run_url": (r.get("run") or {}).get("ultimo", {}).get("url") if r.get("run") else None,
        }
        nuevas.append(inc)
    incidencias = (nuevas + incidencias)[:300]

    # --- resumen ---------------------------------------------------------------------
    cuenta = {k: sum(1 for r in resultados if r["estado"] == k) for k in PESO}
    general = "ok"
    if cuenta["error"]:
        general = "error"
    elif cuenta["aviso"]:
        general = "aviso"

    estado = {
        "generado": iso(AHORA),
        "generado_legible": legible(AHORA),
        "repositorio": REPO,
        "api_github_ok": _api_ok,
        "general": general,
        "resumen": {
            "total": len(resultados),
            "al_dia": cuenta["ok"] + cuenta["estatico"],
            "ok": cuenta["ok"], "estatico": cuenta["estatico"],
            "aviso": cuenta["aviso"], "error": cuenta["error"],
        },
        "herramientas": sorted(resultados, key=lambda r: (-PESO[r["estado"]], r["familia"], r["nombre"])),
        "incidencias_recientes": incidencias[:30],
        "pagina": PAGINA_ESTADO,
        "licencia": "Cálculo propio de CalentamientoGlobal.es · CC BY 4.0",
    }

    # --- historial (30 días) -----------------------------------------------------------
    historial = leer_json(HISTORIAL, []) or []
    historial.append({"t": iso(AHORA), "ok": cuenta["ok"] + cuenta["estatico"],
                      "aviso": cuenta["aviso"], "error": cuenta["error"]})
    limite = AHORA - timedelta(days=30)
    historial = [x for x in historial if (parsear_fecha(x.get("t")) or AHORA) >= limite]

    escribir_json(ESTADO, estado)
    escribir_json(HISTORIAL, historial)
    escribir_json(INCIDENCIAS, incidencias)
    log(f"\nResumen: {cuenta}")

    # --- avisos --------------------------------------------------------------------------
    empeoran = [i for i in nuevas if PESO[i["a"]] > PESO[i["de"]]]
    mejoran = [i for i in nuevas if PESO[i["a"]] < PESO[i["de"]]]
    por_id = {r["id"]: r for r in resultados}
    partes = []
    if empeoran:
        partes.append("<b>⚠️ Se ha roto algo en el observatorio</b>\n" +
                      "\n".join(linea_tg(por_id[i["id"]]) for i in empeoran))
    if mejoran:
        partes.append("<b>✅ Recuperado</b>\n" +
                      "\n".join(f"🟢 <b>{_esc(i['nombre'])}</b> ({i['de']} → {i['a']})" for i in mejoran))
    # Parte completo en la primera pasada y cada día a las 07 UTC si hay algo mal.
    es_parte_diario = (not ant_por_id) or (AHORA.hour == 7 and (cuenta["error"] or cuenta["aviso"]))
    if es_parte_diario:
        malas = [r for r in estado["herramientas"] if r["estado"] in ("error", "aviso")]
        partes.append(f"<b>📋 Parte diario · {cuenta['ok'] + cuenta['estatico']} al día · "
                      f"{cuenta['aviso']} con aviso · {cuenta['error']} con problema</b>\n" +
                      ("\n".join(linea_tg(r) for r in malas) if malas else "Todo al día."))
    if partes:
        texto = "\n\n".join(partes) + f"\n\n<a href=\"{PAGINA_ESTADO}\">Estado de los datos</a>"
        telegram(texto[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
