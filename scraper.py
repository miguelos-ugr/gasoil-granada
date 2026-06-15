#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lee el precio del gasoleo C (calefaccion) en la provincia de Granada y escribe datos.json.
Sin dependencias externas: solo la biblioteca estandar de Python (urllib, re, json).
Disenado para ejecutarse de forma desatendida en GitHub Actions una vez al dia.

Fuente: calienteybarato.com (datos de venta al publico del Ministerio para la
Transicion Ecologica, via geoportalgasolineras.es). El gasoleo C no tiene precio por
estacion de servicio: es una media provincial.
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://calienteybarato.com/precio-gasoil-calefaccion/provincia/granada/"
OUT = Path(__file__).with_name("datos.json")
UA = "Mozilla/5.0 (compatible; gasoil-granada/1.0; +seguimiento personal)"

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(html: str) -> str:
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&euro;", "\u20ac").replace("&#8364;", "\u20ac")
    return re.sub(r"\s+", " ", text)


def num(a: str, b: str) -> float:
    return float(f"{a}.{b}")


def parse(text: str) -> dict:
    out = {}

    m = re.search(r"(\d)[.,](\d{3})\s*\u20ac\s*/\s*litro", text, re.I)
    if m:
        out["precio"] = num(m.group(1), m.group(2))

    m = re.search(
        r"Granada\s+(\d)[.,](\d{3})\s*\u20ac\s+(\d)[.,](\d{3})\s*\u20ac\s+(\d)[.,](\d{3})\s*\u20ac",
        text, re.I)
    if m:
        out["min"] = num(m.group(1), m.group(2))
        if "precio" not in out:
            out["precio"] = num(m.group(3), m.group(4))
        out["max"] = num(m.group(5), m.group(6))

    m = re.search(
        r"Andaluc[i\u00ed]a\s+(\d)[.,](\d{3})\s*\u20ac\s+(\d)[.,](\d{3})\s*\u20ac",
        text, re.I)
    if m:
        out["andalucia"] = num(m.group(3), m.group(4))

    m = re.search(
        r"Media Nacional\s+(\d)[.,](\d{3})\s*\u20ac\s+(\d)[.,](\d{3})\s*\u20ac",
        text, re.I)
    if m:
        out["nacional"] = num(m.group(3), m.group(4))

    m = re.search(r"([\u2191\u2193])?\s*([+-]?\d+(?:[.,]\d+)?)\s*ct\s*vs\s*mes", text, re.I)
    if m:
        v = float(m.group(2).replace(",", "."))
        if m.group(1) == "\u2193" or "-" in m.group(2):
            v = -abs(v)
        out["delta_mes_ct"] = round(v, 2)

    m = re.search(r"Actualizado el\s+(\d{1,2})\s+de\s+([A-Za-z\u00e1-\u00fa]+)\s+de\s+(\d{4})", text, re.I)
    if m:
        mes = MESES.get(m.group(2).lower())
        if mes:
            out["actualizado"] = f"{m.group(3)}-{mes:02d}-{int(m.group(1)):02d}"

    # Serie mensual (24 meses): "Mes AAAA  NacionalEUR  AndaluciaEUR"
    serie = []
    for mm in re.finditer(
        r"([A-Za-z\u00e1-\u00fa]{3,})\s+(20\d{2})\s+(\d)[.,](\d{3})\s*\u20ac\s+(\d)[.,](\d{3})\s*\u20ac",
        text):
        mes = MESES.get(mm.group(1).lower())
        if not mes:
            continue
        etiqueta = f"{mm.group(1)[:3].capitalize()} {mm.group(2)[2:]}"
        serie.append([etiqueta, num(mm.group(5), mm.group(6))])  # columna Andalucia
    if len(serie) >= 6:
        out["serie"] = serie

    return out


def load_previous() -> dict:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text("utf-8"))
        except Exception:
            pass
    return {}


def main() -> int:
    try:
        html = fetch(URL)
    except Exception as e:
        print(f"ERROR al descargar la fuente: {e}", file=sys.stderr)
        return 1

    parsed = parse(strip_tags(html))
    if "precio" not in parsed:
        print("ERROR: no se pudo extraer el precio. Estructura cambiada?", file=sys.stderr)
        return 2

    data = load_previous()                # conserva valores previos por robustez
    data.update(parsed)                   # y sobrescribe los que se hayan leido hoy
    data["granada"] = {
        "precio": parsed.get("precio", data.get("granada", {}).get("precio")),
        "min": parsed.get("min", data.get("granada", {}).get("min")),
        "max": parsed.get("max", data.get("granada", {}).get("max")),
    }
    for k in ("precio", "min", "max"):     # limpia claves sueltas, ya van en "granada"
        data.pop(k, None)
    data["generado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["fuente"] = URL

    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    g = data["granada"]
    print(f"OK  Granada {g['precio']} EUR/L  (rango {g['min']}-{g['max']})  "
          f"actualizado {data.get('actualizado','?')}  | {len(data.get('serie',[]))} puntos de serie")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
