"""Subset Lato 2.015 to Latin-1 + Cyrillic and rename it (OFL Reserved Font Name).

Source: npm lato-font@3.0.0 (fonts/lato-{normal,bold,black}/*.woff2), Lato 2.015 by Lukasz Dziedzic.
Usage: uv run --no-project --with fonttools --with brotli python scripts/subset_fonts.py <src_dir> site/fonts
"""
import sys
from fontTools import subset
from fontTools.ttLib import TTFont

src, dst = sys.argv[1], sys.argv[2]
UNICODES = ("U+0000-00FF,U+0131,U+0152-0153,U+0160-0161,U+0178,U+017D-017E,U+02C6,U+02DA,U+02DC,"
            "U+0400-045F,U+0490-0491,U+2000-206F,U+20AC,U+20BD,U+2116,U+2122,U+2190-2193,U+2212")
STYLE = {"normal": ("Regular", 400), "bold": ("Bold", 700), "black": ("Black", 900)}
FAMILY = "Izolenta Sans"
for w, (style, weight) in STYLE.items():
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.name_IDs = ["*"]
    font = TTFont(f"{src}/lato-{w}.woff2")
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=subset.parse_unicodes(UNICODES))
    sub.subset(font)
    table = font["name"]
    for name_id in (1, 2, 3, 4, 6, 16, 17, 18, 21, 22):
        table.removeNames(nameID=name_id)
    names = {1: FAMILY, 2: style, 3: f"{FAMILY} {style}; derived from Lato 2.015", 4: f"{FAMILY} {style}",
             6: f"IzolentaSans-{style}", 16: FAMILY, 17: style}
    for name_id, value in names.items():
        table.setName(value, name_id, 3, 1, 0x409)
        table.setName(value, name_id, 1, 0, 0)
    out = f"{dst}/izolenta-sans-{weight}.woff2"
    font.flavor = "woff2"
    font.save(out)
    cmap = TTFont(out).getBestCmap()
    print(out.rsplit("/", 1)[-1], "ok" if all(ord(c) in cmap for c in "АЯаяЁё«»—→№") else "MISSING GLYPHS")
