#!/usr/bin/env python3
"""Pruebas de scripts/nieve_finde.py con cinco casos sintéticos (tests/finde_muestra.json): sin nieve, nevada con sol y poco
viento, nevada con racha de 80 km/h, lluvia en el punto y deshielo de día con rehielo de noche. Sin red: la «petición» a
Open-Meteo es un generador que devuelve la misma forma de respuesta (cuatro modelos, horas, past_days=7)."""
import json
import math
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import nieve_finde as nf  # noqa: E402

MUESTRA = json.loads((Path(__file__).parent / "finde_muestra.json").read_text(encoding="utf-8"))
HOY = date.fromisoformat(MUESTRA["hoy"])
AHORA = datetime.fromisoformat(MUESTRA["ahora"])
CFG = nf.MACIZOS_ACTIVOS["nevada"]
PUNTOS = [{"id": "granada-monte", "nombre": "Sierra Nevada (Pradollano)", "lat": 37.095, "lon": -3.395, "alt": 2500}]


def respuesta(caso: dict, quitar=(), sin_modelo=("gfs_seamless", "cloud_cover_low")) -> dict:
    """Respuesta tipo Open-Meteo (hourly con sufijo de modelo) a partir de la descripción por días del caso."""
    dd = {**MUESTRA["defecto_dia"]}
    por_dia = {}
    for k in range(-7, 10):
        f = (HOY + timedelta(days=k)).isoformat()
        resto = MUESTRA["resto"] if f > "2026-11-22" else {}
        por_dia[f] = {**dd, **resto, **(caso.get("previas") or {}).get(f, {}), **caso["dias"].get(f, {})}
    t, cols = [], {v: [] for v in nf.VARIABLES}
    for f, e in por_dia.items():
        for h in range(24):
            t.append(f"{f}T{h:02d}:00")
            sube = max(0.0, math.sin(math.pi * (h - 6) / 18)) if 6 <= h <= 24 else 0.0
            temp = e["tmin"] + (e["tmax"] - e["tmin"]) * (sube if h <= 20 else 0.0)
            racha = e["racha"] * (1.0 if 9 <= h <= 17 else 0.8)
            nh = len(e["nieve_horas"]) or 1
            lh = len(e["lluvia_horas"]) or 1
            nieve = e["nieve_cm"] / nh if h in e["nieve_horas"] else 0.0
            precip = nieve + (e["lluvia_mm"] / lh if h in e["lluvia_horas"] else 0.0)
            cols["snowfall"].append(round(nieve, 3)); cols["precipitation"].append(round(precip, 3))
            cols["temperature_2m"].append(round(temp, 2)); cols["apparent_temperature"].append(round(temp - 0.15 * racha, 2))
            cols["wind_gusts_10m"].append(round(racha, 1)); cols["cloud_cover"].append(e["nubes"])
            cols["cloud_cover_low"].append(e["bajas"]); cols["freezing_level_height"].append(e["fl"])
            cols["snow_depth"].append(0.0)
    hourly = {"time": t}
    for v, serie in cols.items():
        if v in quitar:
            continue
        for m in nf.MODELOS:
            if (m, v) == sin_modelo:
                continue
            hourly[f"{v}_{m}"] = list(serie)
    return {"hourly": hourly}


def calcular(caso: dict, dgt="sin", **kw) -> dict:
    series = {"granada-monte": nf.serie_mediana(respuesta(caso, **kw))}
    d = None if dgt is None else {"hora": "14:31", "estados": {} if dgt == "sin" else {dgt: 1}}
    ctx = {"ahora": AHORA, "hoy": HOY, "sat_pct": caso.get("sat"), "dgt": d, "acum": 40.0, "normal": 66.0,
           "proxima": caso.get("proxima"), "generado": "2026-11-20T13:31:00Z"}
    return nf.calcular_macizo("nevada", PUNTOS, series, ctx)


def dia(mac: dict, f: str) -> dict:
    return next(e for e in mac["dias"] if e["fecha"] == f)


class Finde(unittest.TestCase):
    def test_casos(self):
        for nombre, caso in MUESTRA["casos"].items():
            with self.subTest(nombre):
                mac = calcular(caso)
                ex = caso["esperado"]
                sab = dia(mac, "2026-11-21")
                self.assertEqual(mac["hay_nieve"], ex["hay_nieve"])
                if "sab" in ex:
                    est = {k: v["estado"] for k, v in sab["perfiles"].items()}
                    self.assertEqual(est, ex["sab"], sab["perfiles"])
                else:
                    self.assertEqual(sab["perfiles"], {})
                for k in ("nieve_dura_sab", "lluvia_sab", "racha_sab", "cielo_sab"):
                    if k in ex:
                        campo = {"nieve_dura_sab": "nieve_dura", "lluvia_sab": "lluvia", "racha_sab": "racha", "cielo_sab": "cielo"}[k]
                        self.assertEqual(sab[campo], ex[k], k)
                if "mejor" in ex:
                    self.assertEqual(mac["mejor_dia"]["fecha"], ex["mejor"])
                wa = mac["texto_wa"]
                self.assertTrue(wa.strip(), "texto_wa vacío")
                self.assertLessEqual(len(wa), nf.WA_MAX_CARACTERES)
                self.assertLessEqual(len(wa.split("\n")), nf.WA_MAX_LINEAS)
                self.assertTrue(wa.endswith(f"?d={HOY:%Y%m%d}"), wa)
                if "wa_empieza" in ex:
                    self.assertTrue(wa.startswith(ex["wa_empieza"]), wa)
                for frag in ([ex["wa_contiene"]] if isinstance(ex.get("wa_contiene"), str) else ex.get("wa_contiene", [])):
                    self.assertIn(frag, wa)

    def test_sin_nieve_sin_proxima(self):
        caso = {**MUESTRA["casos"]["sin_nieve"], "proxima": None}
        self.assertIn("Próxima nevada prevista: ninguna en 15 días.", calcular(caso)["texto_wa"])

    def test_nieve_dura_y_frase(self):
        mac = calcular(MUESTRA["casos"]["deshielo_y_rehielo"])
        sen = dia(mac, "2026-11-21")["perfiles"]["senderismo"]
        self.assertIn("Nieve dura probable a primera hora: crampones y piolet, y saber usarlos", sen["motivo"])

    def test_carretera(self):
        caso = MUESTRA["casos"]["nevada_sol_poco_viento"]
        mac = calcular(caso)
        self.assertEqual(mac["carretera"]["ahora"], "Sin restricciones ahora (DGT, 14:31)")
        con = calcular(caso, dgt="cadenas")
        self.assertIn("cadenas obligatorias", con["carretera"]["ahora"])
        self.assertNotEqual(dia(con, "2026-11-21")["perfiles"]["familia"]["estado"], "Buen día")
        # sin dato de la DGT no se emite el veredicto de familia
        sin = calcular(caso, dgt=None)
        self.assertNotIn("familia", dia(sin, "2026-11-21")["perfiles"])
        self.assertIsNone(sin["carretera"]["ahora"])
        # posible nieve en la subida si nieva entre las 8 y las 10 h con la cota por debajo de la carretera
        c2 = json.loads(json.dumps(caso))
        c2["dias"]["2026-11-21"]["nieve_horas"] = [7, 8, 9]
        self.assertEqual(dia(calcular(c2), "2026-11-21")["carretera_prev"]["subida"], "Posible nieve en la subida")
        self.assertNotEqual(dia(calcular(c2), "2026-11-21")["perfiles"]["familia"]["estado"], "Buen día")
        # hielo en la bajada: a 2.500 m con -3 °C a las 16 h, en la carretera (2.100 m) hay +2,6 °C; con -9 °C, hielo
        c3 = json.loads(json.dumps(caso))
        c3["dias"]["2026-11-21"].update({"tmax": -5, "tmin": -12})
        self.assertRegex(dia(calcular(c3), "2026-11-21")["carretera_prev"]["bajada"], r"^Posible hielo en la bajada a partir de las \d+ h$")
        for c in (mac, con):
            self.assertNotIn("no hacen falta cadenas", json.dumps(c, ensure_ascii=False).lower())

    def test_datos_incompletos_sin_veredicto(self):
        for quitar in ("wind_gusts_10m", "apparent_temperature", "cloud_cover_low"):
            mac = calcular(MUESTRA["casos"]["nevada_sol_poco_viento"], quitar=(quitar,), sin_modelo=())
            e = dia(mac, "2026-11-21")
            self.assertEqual(e["perfiles"], {}, quitar)
            self.assertTrue(e["incompleto"])
            self.assertIsNone(mac["mejor_dia"])
        # una variable que un modelo no da se calcula con los demás y se anota
        mac = calcular(MUESTRA["casos"]["nevada_sol_poco_viento"])
        self.assertTrue(any("cloud_cover_low" in n or "bajas" in n for n in mac["notas"]))

    def test_normal(self):
        self.assertEqual(nf.frente_normal(40.0, 66.0)[0], -39)
        self.assertIn("un 39 % menos de lo normal", nf.frente_normal(40.0, 66.0)[1])
        self.assertEqual(nf.frente_normal(10.0, 4.9), (None, None))

    def test_bloque_y_sanidad(self):
        for nombre, caso in MUESTRA["casos"].items():
            with self.subTest(nombre):
                mac = calcular(caso)
                html = nf.bloque_html(mac, CFG, datetime(2026, 11, 20, 13, 40, tzinfo=nf.TZ))
                self.assertIn("¿Subo este fin de semana a Sierra Nevada?", html)
                self.assertIn('rel="nofollow" href="/nieve/sierra-nevada/?cgnv_wa=1"', html)
                self.assertIn("Orientación a partir de modelos meteorológicos. No sustituye al parte de la estación", html)
                self.assertIn("https://sierranevada.es/es/invierno/la-estacion/en-directo/parte-nieve/", html)
                for malo in ("None", "NaN", "—", "Array", "nan", "undefined"):
                    self.assertNotIn(malo, html + mac["texto_wa"])
                for etiqueta in ("<svg", "<img", "<figure", "<dl", "<i>", "<script"):
                    self.assertNotIn(etiqueta, html)
        mac = calcular(MUESTRA["casos"]["nevada_sol_poco_viento"])
        html = nf.bloque_html(mac, CFG, datetime(2026, 11, 20, 13, 40, tzinfo=nf.TZ))
        for palabra in ("Buen día", "Con reservas"):
            self.assertIn(palabra, html)
        self.assertIn("Mejor día de los próximos 7:", html)
        # con un cálculo de hace más de 12 h el bloque no se pinta
        self.assertEqual(nf.bloque_html(mac, CFG, datetime(2026, 11, 21, 6, 0, tzinfo=nf.TZ)), "")

    def test_imagen(self):
        mac = calcular(MUESTRA["casos"]["nevada_sol_poco_viento"])
        png = nf.imagen_og(mac, CFG, HOY)
        if png is None:
            self.skipTest("Pillow no está instalado")
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertLess(len(png), 300 * 1024)
        import io
        from PIL import Image
        self.assertEqual(Image.open(io.BytesIO(png)).size, (1200, 630))

    def test_domingo_cuenta_hoy(self):
        dias = [{"fecha": (date(2026, 11, 22) + timedelta(days=k)).isoformat()} for k in range(7)]
        self.assertEqual([e["fecha"] for e in nf.dias_finde(dias, date(2026, 11, 22))], ["2026-11-22"])
        dias = [{"fecha": (date(2026, 11, 21) + timedelta(days=k)).isoformat()} for k in range(7)]
        self.assertEqual([e["fecha"] for e in nf.dias_finde(dias, date(2026, 11, 21))], ["2026-11-21", "2026-11-22"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
