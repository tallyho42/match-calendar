#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_logos.py - test: pro kazdou zkratku ocekavanou v HTML musi existovat
platny img/<zkratka>.png (nenulovy, s PNG magickou hlavickou)."""
import os, re, sys

HTML = "fotbalovy-rozpis.html"
IMG_DIR = "img"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def expected_keys(html_path=HTML):
    h = open(html_path, encoding="utf-8").read()
    keys = set(m.lower() for m in re.findall(r'data-(?:home|away)-key="([^"]+)"', h))
    keys |= {"fcb", "rm", "ars"}                      # hlavni sledovane kluby
    keys |= set(re.findall(r'src="img/([a-z0-9_-]+)\.png"', h))
    return sorted(keys)


def check(keys=None, img_dir=IMG_DIR):
    keys = keys or expected_keys()
    missing, ok = [], []
    for k in keys:
        p = os.path.join(img_dir, k + ".png")
        if not os.path.exists(p):
            missing.append((k, "chybi soubor")); continue
        if os.path.getsize(p) == 0:
            missing.append((k, "0 bytu")); continue
        with open(p, "rb") as f:
            head = f.read(8)
        if head != PNG_MAGIC:
            missing.append((k, "neni PNG (%r)" % head[:4])); continue
        ok.append(k)
    return keys, ok, missing


if __name__ == "__main__":
    keys, ok, missing = check()
    print("Ocekavano zkratek: %d" % len(keys))
    print("OK:                %d" % len(ok))
    print("CHYBI: %s" % [k for k, _ in missing])
    if missing:
        for k, why in missing:
            print("   - %-5s %s" % (k, why))
    sys.exit(0 if not missing else 1)
