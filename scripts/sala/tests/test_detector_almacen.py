#!/usr/bin/env python3
"""Pruebas del detector del almacén (scripts/detector_almacen.py).

Día real: almacen_dia_real/ es un recorte de lo publicado el 19-11-2026 (3 capitales, 2 estaciones, el Monitor, el hielo y
las referencias del 15-11 con su maestro). Día roto a propósito: las mismas carpetas con referencias caducadas, sin
referencias, una máxima de 99,9 °C, un fichero gzip truncado y un tope de historias que obliga a repartirlas en dos días.
Uso: python scripts/sala/tests/test_detector_almacen.py"""
import gzip
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent.parent))
import detector_almacen as DA  # noqa: E402

import tarfile  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="almacen_real_")
with tarfile.open(AQUI / "almacen_dia_real.tar.gz") as _t:
    _t.extractall(_TMP)
REAL = Path(_TMP) / "almacen_dia_real"
HOY = date(2026, 11, 19)


def copia():
    d = Path(tempfile.mkdtemp(prefix="almacen_test_"))
    shutil.copytree(REAL, d / "r")
    return d / "r"


class DiaReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = DA.ejecutar(REAL, hoy=HOY, escribir=False)
        cls.h = cls.res["hallazgos"]

    def test_estado_ok_y_datos(self):
        e = self.res["estado"]
        self.assertEqual(e["estado"], "ok")
        self.assertEqual(e["referencias"]["valido_hasta"], "2026-12-30")
        self.assertEqual(e["datos"]["capitales_hasta"], "2026-11-18")
        self.assertEqual(e["datos"]["estaciones_hasta"], "2026-11-19")

    def test_tope_y_orden(self):
        self.assertTrue(1 <= len(self.h) <= DA.MAX_DIARIAS)
        f = [x["fuerza"] for x in self.h]
        self.assertEqual(f, sorted(f, reverse=True))

    def test_contrato(self):
        for x in self.h:
            for k in ("serie", "tipo", "indicador", "territorio", "ambito", "fecha_dato", "titular", "dato", "metodo", "limites",
                      "citabilidad", "exclusivo", "fuerza", "regla", "variante", "destino", "clave", "cifra", "comparacion", "muestra",
                      "calidad", "invalidar", "id"):
                self.assertIn(k, x, f"falta {k} en {x['id']}")
            self.assertEqual(set(x["clave"]), {"indicador", "territorio", "periodo", "corte"})
            self.assertIn(x["tipo"], DA.BASE)
            self.assertEqual(x["destino"], "publicable")
            self.assertFalse(x["exclusivo"])          # David: ninguna en exclusiva
            self.assertTrue(0 < x["fuerza"] <= 100)
            self.assertGreaterEqual(x["fecha_dato"], "2026-11-16")   # nada de antes de la validez de las referencias
        self.assertEqual(len({x["id"] for x in self.h}), len(self.h))

    def test_estacion_primero(self):
        """25-11-2026 · mesa de redacción: Murcia tiene estación de AEMET de serie larga (7178I), así que su récord del 18-11 en la celda
        ERA5 no se publica; se anota el motivo. Ninguna historia de reanálisis lleva umbral absoluto ni le falta la palabra."""
        C = DA.Contexto(REAL / "docs" / "prensa" / "referencias")
        self.assertIn("prov:30", C.est_larga)
        murcia = [x for x in self.res["candidatos"] if x["territorio"] == "Murcia" and x["variante"].startswith("capital_era5")]
        self.assertEqual(murcia, [])
        motivos = [d["motivo"] for d in self.res["estado"]["descartados"] if "murcia" in d["id"].lower() or "cap-30" in d["id"].lower()]
        self.assertTrue(any("manda la estación" in m for m in motivos), motivos)
        for x in self.res["candidatos"]:
            if x["variante"].startswith("capital_era5"):
                self.assertNotEqual(x["regla"], "R08")
                self.assertIn("reanálisis", x["titular"])
                self.assertNotIn("30 °C", x["titular"])
                self.assertIsNone((x.get("cifra") or {}).get("valor"))
                self.assertNotIn(C.provincia(x["ent_id"])[0], C.est_larga)

    def test_lo_que_va_de_exige_dos_tercios(self):
        for x in self.res["candidatos"]:
            if x["regla"] == "R01":
                self.assertGreaterEqual(x["fuerza_detalle"]["r_avance"], 0.7 + 0.3 * DA.FRAC_MIN - 1e-9)

    def test_sin_interno_ni_web_en_prensa(self):
        self.assertTrue(all(x["destino"] == "publicable" for x in self.res["hallazgos"] + self.res["candidatos"]))

    def test_cabe_en_la_sala(self):
        """Un hallazgo del detector entra en anadir() de hallazgos_prensa.py con el contrato actual."""
        import hallazgos_prensa as H
        H.hallazgos.clear()
        H.descartes.clear()
        H.errores.clear()
        sala_hoy = H.HOY
        try:
            H.HOY = HOY
            for x in self.h:
                y = {k: v for k, v in x.items() if not k.startswith("_")}
                y["id_fijo"] = y.pop("id")
                y["novedad"] = y["fuerza_detalle"]["novedad"]
                H.anadir(y)
        finally:
            H.HOY = sala_hoy
        self.assertEqual(len(H.hallazgos), len(self.h))
        self.assertTrue(all(0 < x["fuerza"] <= 100 for x in H.hallazgos))


class Coherencia(unittest.TestCase):
    def test_misma_clave_misma_cifra(self):
        """coherencia.py cruza la clave de cada hallazgo del almacén entre hallazgos.json y almacen/hoy.json."""
        import coherencia as CO
        r = copia()
        res = DA.ejecutar(r, hoy=HOY, escribir=True)
        (r / "docs" / "prensa" / "hallazgos.json").write_text(json.dumps(
            {"enviables": [{k: v for k, v in x.items() if k != "fuerza_detalle"} for x in res["hallazgos"]]}, default=str))
        self.assertEqual(CO.c_clave(r / "docs")[1], [])
        hoy = json.loads((r / "docs" / "prensa" / "almacen" / "hoy.json").read_text())
        for x in hoy["hallazgos"]:
            for k, v in (x.get("cifra") or {}).items():
                if isinstance(v, (int, float)):
                    x["cifra"][k] = v + 5
        (r / "docs" / "prensa" / "almacen" / "hoy.json").write_text(json.dumps(hoy, default=str))
        n, fallos = CO.c_clave(r / "docs")
        self.assertTrue(fallos and fallos[0]["comprobacion"] == "clave")


class DiaRoto(unittest.TestCase):
    def test_referencias_caducadas_no_emiten(self):
        r = copia()
        res = DA.ejecutar(r, hoy=date(2026, 12, 31), escribir=True)
        self.assertEqual(res["estado"]["estado"], "referencias_caducadas")
        self.assertEqual(res["hallazgos"], [])
        est = json.loads((r / "docs" / "estado" / "almacen.json").read_text())
        self.assertEqual(est["estado"], "referencias_caducadas")
        self.assertIn("refresquen", est["mensaje"])
        interno = json.loads((r / "docs" / "prensa" / "almacen" / "interno.json").read_text())
        self.assertTrue(any("referencias_caducadas" in a["texto"] for a in interno["avisos_detector"]))

    def test_sin_referencias_no_emiten(self):
        r = copia()
        shutil.rmtree(r / "docs" / "prensa" / "referencias")
        res = DA.ejecutar(r, hoy=HOY, escribir=False)
        self.assertEqual(res["estado"]["estado"], "sin_referencias")
        self.assertEqual(res["hallazgos"], [])

    def test_maxima_imposible_no_hace_record(self):
        r = copia()
        f = r / "archivo" / "era5" / "30" / "2026.csv"
        filas = f.read_text().splitlines()
        filas = [x if not x.startswith("2026-11-18") else "2026-11-18,99.9,14.0,0.0" for x in filas]
        f.write_text("\n".join(filas) + "\n")
        res = DA.ejecutar(r, hoy=HOY, escribir=False)
        self.assertTrue(any(d["ent"] == "cap:30" and d["fecha"] == "2026-11-18" for d in res["estado"]["datos_descartados"]))
        self.assertFalse([x for x in res["candidatos"] if x["regla"] == "R09" and x["territorio"] == "Murcia" and x["fecha_dato"] == "2026-11-18"])

    def test_fichero_roto_no_tumba(self):
        r = copia()
        f = r / "archivo" / "aemet_diario" / "5402.csv.gz"
        b = f.read_bytes()
        f.write_bytes(b[: len(b) // 2])
        res = DA.ejecutar(r, hoy=HOY, escribir=False)
        self.assertEqual(res["estado"]["estado"], "ok")
        self.assertTrue(any("fichero" in d["campos"] and d["ent"] == "est:5402" for d in res["estado"]["datos_descartados"]))

    def test_reparto_en_dos_dias_sin_repetir(self):
        r = copia()
        maximo = DA.MAX_DIARIAS
        DA.MAX_DIARIAS = 2
        try:
            d1 = DA.ejecutar(r, hoy=HOY, escribir=True)
            again = DA.ejecutar(r, hoy=HOY, escribir=True)           # otra pasada el mismo día: sale lo mismo
            d2 = DA.ejecutar(r, hoy=date(2026, 11, 20), escribir=True)   # al día siguiente: lo nuevo, nunca lo de ayer
        finally:
            DA.MAX_DIARIAS = maximo
        ids1 = [x["id"] for x in d1["hallazgos"]]
        self.assertEqual(len(ids1), 2)
        self.assertEqual(ids1, [x["id"] for x in again["hallazgos"]])
        self.assertFalse(set(ids1) & {x["id"] for x in d2["hallazgos"]})
        self.assertLessEqual(len(d2["hallazgos"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
