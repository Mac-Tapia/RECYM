# -*- coding: utf-8 -*-
"""Ajustes finos de layout/texto en informe.docx ya rellenado."""
from __future__ import print_function
import os
import re
import shutil
import zipfile
from pathlib import Path


def _is_empty_para(p):
    if "<w:drawing>" in p or "<w:tbl>" in p or "<w:pict>" in p:
        return False
    texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)
    return "".join(texts).strip() == ""


def _para_text(p):
    return "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))


def fix_xml(xml):
    notes = []
    # Typo en titulo 2.3.3
    if "NÁLISIS DE CARGABILIDAD" in xml or "N\xc1LISIS DE CARGABILIDAD" in xml:
        xml2 = xml.replace("NÁLISIS DE CARGABILIDAD", "ANÁLISIS DE CARGABILIDAD")
        if xml2 != xml:
            notes.append("typo NÁLISIS->ANÁLISIS")
            xml = xml2
    # Also broken encoding variants
    xml2 = re.sub(r"(?<!A)NÁLISIS DE CARGABILIDAD", "ANÁLISIS DE CARGABILIDAD", xml)
    if xml2 != xml:
        notes.append("typo regex NÁLISIS")
        xml = xml2

    parts = re.split(r"(<w:p[\s>].*?</w:p>)", xml, flags=re.DOTALL)
    out = []
    i = 0
    removed = 0
    while i < len(parts):
        chunk = parts[i]
        out.append(chunk)
        if chunk.startswith("<w:p"):
            t = _para_text(chunk)
            # Tras "Para la evaluación se está considerando..." quitar vacíos
            # hasta el parrafo "De acuerdo con el cuadro..."
            if "Para la evaluaci" in t and "solicitudes que se encuentran" in t:
                j = i + 1
                buffer = []
                while j < len(parts):
                    nxt = parts[j]
                    if not nxt.startswith("<w:p"):
                        buffer.append(nxt)
                        j += 1
                        continue
                    if _is_empty_para(nxt):
                        removed += 1
                        j += 1
                        continue
                    break
                # keep non-para buffer only if next real para follows; drop empties
                for b in buffer:
                    if b.strip():
                        out.append(b)
                i = j
                continue
        i += 1
    if removed:
        notes.append("removed empty paras after intro 2.3.2: %d" % removed)
    return "".join(out), notes


def fix_docx(path):
    path = Path(path)
    bak = path.with_suffix(path.suffix + ".bak_fine")
    shutil.copy2(path, bak)
    tmp = Path(str(path) + ".__fine")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    with zipfile.ZipFile(path, "r") as zin:
        zin.extractall(tmp)
    xml_path = tmp / "word" / "document.xml"
    xml = xml_path.read_text(encoding="utf-8")
    # diagnose typo
    for m in re.finditer(r".{0,5}LISIS DE CARGABILIDAD", xml):
        print("found heading:", repr(m.group(0)))
    new_xml, notes = fix_xml(xml)
    xml_path.write_text(new_xml, encoding="utf-8")
    out = Path(str(path) + ".__new.docx")
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for folder, _, files in os.walk(tmp):
            for name in files:
                full = Path(folder) / name
                zout.write(str(full), full.relative_to(tmp).as_posix())
    shutil.move(str(out), str(path))
    shutil.rmtree(tmp, ignore_errors=True)
    print("notes:", notes)


if __name__ == "__main__":
    fix_docx(r"d:\Proyectos\ELDICA\RECYM\doc\informe.docx")
    # also plantilla for future fills
    plant = r"d:\Proyectos\ELDICA\RECYM\data\output\informe\informe.docx"
    if os.path.isfile(plant):
        fix_docx(plant)
