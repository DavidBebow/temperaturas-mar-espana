"""Prueba de scripts/niebla.py con tests/niebla_muestra/ (python tests/test_niebla.py)."""
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import niebla as N                # noqa: E402

M = Path(__file__).parent / "niebla_muestra"
AHORA = datetime.fromisoformat("2026-11-16T08:45:00+01:00")
MALO = re.compile(r"None|NaN|—|\bnan\b")


class Niebla(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.terr = N.Territorio()
        cls.dgt = N.leer_dgt((M / "dgt.xml").read_bytes(), cls.terr, AHORA)
        cls.metar = N.leer_metar(json.loads((M / "metar.json").read_text()), cls.terr, AHORA)
        cls.aemet = N.leer_aemet(json.loads((M / "aemet.json").read_text()), cls.terr, AHORA)

    def test_dgt_solo_niebla_activa_y_sin_duplicados(self):
        ids = sorted(t["id"] for t in self.dgt["tramos"])
        self.assertEqual(ids, ["2001", "2005"])          # 2002 solo visibilidad, 2003 obras, 2004 terminada
        t = {x["id"]: x for x in self.dgt["tramos"]}["2001"]
        self.assertEqual((t["carretera"], t["provincia_slug"], t["pk_ini"], t["pk_fin"]), ("A-31", "albacete", 60.0, 68.0))
        self.assertEqual(t["desde"], "2026-11-16T06:32+01:00")

    def test_metar_clases(self):
        c = {p["id"]: p["clase"] for p in self.metar["puntos"]}
        self.assertEqual(c, {"LEAB": "niebla", "LELN": "bruma", "LEMD": "despejado"})   # LEZL tiene 3 h: se descarta
        self.assertEqual(self.metar["viejos"], 1)
        v = {p["id"]: p["vis_m"] for p in self.metar["puntos"]}
        self.assertEqual(v, {"LEAB": 300, "LELN": 2000, "LEMD": 10000})

    def test_aemet_solo_con_sensor(self):
        c = {p["id"]: p["clase"] for p in self.aemet["puntos"]}
        self.assertEqual(c, {"A001": "niebla", "A002": "despejado"})
        self.assertEqual({p["id"]: p["vis_m"] for p in self.aemet["puntos"]}["A001"], 400)

    def test_clase(self):
        self.assertEqual(N.clase(None, "BCFG"), "niebla")
        self.assertEqual(N.clase(999, ""), "niebla")
        self.assertEqual(N.clase(1000, ""), "bruma")
        self.assertEqual(N.clase(5000, ""), "bruma")
        self.assertEqual(N.clase(5001, ""), "despejado")
        self.assertEqual(N.clase(9999, "-RA"), "despejado")

    def test_provincias_y_frase(self):
        d = N.construir(AHORA, self.dgt, self.metar, self.aemet, {})
        p = d["provincias"]
        self.assertEqual(p["albacete"]["estado"], "niebla")
        self.assertEqual(p["murcia"]["estado"], "niebla")
        self.assertEqual(p["leon"]["estado"], "bruma")
        self.assertEqual(p["madrid"]["estado"], "sin_niebla")
        self.assertEqual(p["barcelona"]["estado"], "sin_dato")           # la DGT no la cubre y no hay puntos
        self.assertEqual(p["ciudad-real"]["estado"], "sin_niebla")       # visibilidad reducida no es niebla
        self.assertTrue(p["albacete"]["apoyo"].startswith("1 tramo de la DGT"))
        self.assertEqual(d["totales"], {"tramos": 2, "puntos_niebla": 2, "puntos_bruma": 1, "provincias_niebla": 2})
        self.assertEqual(d["frase"], "A las 08:45 del 16 de noviembre hay niebla en 2 tramos de carretera de 2 provincias "
                                     "y en 2 puntos de observación.")
        self.assertNotRegex(json.dumps(d, ensure_ascii=False), MALO)

    def test_sin_dgt_marca_sin_dato(self):
        d = N.construir(AHORA, None, self.metar, None, {"dgt": "caída"})
        self.assertFalse(d["fuentes"]["dgt"]["ok"])
        self.assertEqual(d["provincias"]["huesca"]["estado"], "sin_dato")

    def test_pasada_aemet_insuficiente_y_conserva(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "niebla.json"
            d, msg = N.pasada(AHORA, lambda: (M / "dgt.xml").read_bytes(), lambda: json.loads((M / "metar.json").read_text()),
                              lambda: json.loads((M / "aemet.json").read_text()), self.terr, out)
            self.assertIn("publicado", msg)
            self.assertFalse(d["fuentes"]["aemet"]["ok"])                 # solo 2 estaciones (<30): se anota y se sigue
            self.assertTrue(out.exists())

            def falla():
                raise RuntimeError("caído")
            d2, msg2 = N.pasada(AHORA, falla, falla, falla, self.terr, out)
            self.assertIn("FALLAN TODAS", msg2)
            self.assertEqual(d2["frase"], d["frase"])


if __name__ == "__main__":
    unittest.main()
