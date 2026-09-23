# -*- coding: utf-8 -*-
"""
Post-fix layout informe ElectroDunas:
1) Leyendas rId12/14/16 -> inline (si aun ancla)
2) Mapas LF ancla wrapSquare (rId13/15) -> inline
3) Compacta series de parrafos vacios entre leyenda y mapa
"""
from __future__ import print_function
import os
import re
import shutil
import zipfile
from pathlib import Path

LEGEND_RIDS = ("rId12", "rId14", "rId16")
# Primeras apariciones ancla de mapas situacionales
MAP_RIDS = ("rId13", "rId15")


def _anchor_to_inline(anchor_xml):
    extent = re.search(r"<wp:extent\b[^/]*/>", anchor_xml)
    if not extent:
        extent = re.search(r"<wp:extent\b[^>]*>.*?</wp:extent>", anchor_xml, re.DOTALL)
    effect = re.search(r"<wp:effectExtent\b[^/]*/>", anchor_xml)
    docpr = re.search(r"<wp:docPr\b[^/]*/>", anchor_xml)
    if not docpr:
        docpr = re.search(r"<wp:docPr\b[^>]*>.*?</wp:docPr>", anchor_xml, re.DOTALL)
    cnv = re.search(
        r"<wp:cNvGraphicFramePr\b[^>]*>.*?</wp:cNvGraphicFramePr>",
        anchor_xml,
        re.DOTALL,
    )
    graphic = re.search(r"<a:graphic\b[^>]*>.*?</a:graphic>", anchor_xml, re.DOTALL)
    if not (extent and docpr and graphic):
        return None
    return "".join(
        [
            '<wp:inline distT="0" distB="0" distL="0" distR="0">',
            extent.group(0),
            effect.group(0) if effect else '<wp:effectExtent l="0" t="0" r="0" b="0"/>',
            docpr.group(0),
            cnv.group(0) if cnv else "<wp:cNvGraphicFramePr/>",
            graphic.group(0),
            "</wp:inline>",
        ]
    )


def _convert_anchors(xml, rids, label):
    changed = []

    def repl(m):
        block = m.group(0)
        rid_m = re.search(r'r:embed="(rId\d+)"', block)
        if not rid_m or rid_m.group(1) not in rids:
            return block
        if "wp:anchor" not in block:
            return block
        am = re.search(r"<wp:anchor[\s>].*</wp:anchor>", block, re.DOTALL)
        if not am:
            return block
        inline = _anchor_to_inline(am.group(0))
        if not inline:
            changed.append((rid_m.group(1), label + ":FAIL"))
            return block
        changed.append((rid_m.group(1), label + ":ok"))
        return block[: am.start()] + inline + block[am.end() :]

    new_xml = re.sub(r"<w:drawing>.*?</w:drawing>", repl, xml, flags=re.DOTALL)
    return new_xml, changed


def _is_empty_para(p):
    """Parrafo sin texto, sin drawing, sin tabla, sin pict."""
    if "<w:drawing>" in p or "<w:tbl>" in p or "<w:pict>" in p:
        return False
    texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)
    joined = "".join(texts).strip()
    return joined == ""


def _para_has_embed(p, rid):
    return ('r:embed="%s"' % rid) in p


def _compact_spacers(xml, max_keep=1):
    """
    Tras cada leyenda (rId12/14/16), reduce rachas de parrafos vacios
    antes del siguiente contenido/mapa. Conserva max_keep vacios.
    """
    parts = re.split(r"(<w:p[\s>].*?</w:p>)", xml, flags=re.DOTALL)
    # parts: text, para, text, para, ...
    out = []
    i = 0
    removed = 0
    while i < len(parts):
        chunk = parts[i]
        out.append(chunk)
        if chunk.startswith("<w:p") and any(_para_has_embed(chunk, r) for r in LEGEND_RIDS):
            # Look ahead: collect empty paras, keep only max_keep
            j = i + 1
            empties = []
            while j < len(parts):
                nxt = parts[j]
                if not nxt.startswith("<w:p"):
                    # interstitial xml between paras — usually empty string
                    empties.append((j, nxt))
                    j += 1
                    continue
                if _is_empty_para(nxt):
                    empties.append((j, nxt))
                    j += 1
                    continue
                break
            # empties may include non-para interstitial; filter para empties
            para_empties_idx = [idx for idx, c in empties if c.startswith("<w:p")]
            keep_n = min(max_keep, len(para_empties_idx))
            drop = set(para_empties_idx[keep_n:])
            for idx, c in empties:
                if idx in drop:
                    removed += 1
                    continue
                out.append(c)
            i = j
            continue
        i += 1
    return "".join(out), removed


def fix_docx(docx_path, backup=True):
    docx_path = Path(docx_path)
    if backup:
        bak = docx_path.with_suffix(docx_path.suffix + ".bak_layout2")
        shutil.copy2(docx_path, bak)
        print("backup:", bak)

    tmp = Path(str(docx_path) + ".__layout_fix3")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    with zipfile.ZipFile(docx_path, "r") as zin:
        zin.extractall(tmp)

    xml_path = tmp / "word" / "document.xml"
    xml = xml_path.read_text(encoding="utf-8")

    xml, c1 = _convert_anchors(xml, LEGEND_RIDS, "legend")
    xml, c2 = _convert_anchors(xml, MAP_RIDS, "map")
    # Only convert FIRST occurrence of each map rid (anchor); later duplicates
    # may be intentional overlays — _convert_anchors already converts all anchors.

    xml, removed = _compact_spacers(xml, max_keep=1)
    xml_path.write_text(xml, encoding="utf-8")
    print("legend:", c1)
    print("map:", c2)
    print("empty paras removed:", removed)

    out_tmp = Path(str(docx_path) + ".__new.docx")
    if out_tmp.exists():
        out_tmp.unlink()
    with zipfile.ZipFile(out_tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for folder, _, files in os.walk(tmp):
            for name in files:
                full = Path(folder) / name
                rel = full.relative_to(tmp).as_posix()
                zout.write(str(full), rel)
    shutil.move(str(out_tmp), str(docx_path))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    import sys

    targets = sys.argv[1:] or [
        r"d:\Proyectos\ELDICA\RECYM\data\output\informe\informe.docx",
        r"d:\Proyectos\ELDICA\RECYM\doc\informe.docx",
    ]
    for t in targets:
        if not os.path.isfile(t):
            print("skip", t)
            continue
        print("\n===", t)
        fix_docx(t)
