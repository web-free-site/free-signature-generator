#!/usr/bin/env python3
# Sign PDF - TekiDeki
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Kristian Mario Miskovic (TekiDeki)
"""Build a single self contained index.html.

Deterministic by design: the same sources always give byte identical output,
with no timestamps, no dictionary ordering surprises and no machine paths.

The fourth locale, Serbian Cyrillic, is never written by hand. It is produced
here by transliterating the Serbian Latin strings, so the two always agree.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
TEMPLATE = SRC / "template.html"
STYLES = SRC / "styles.css"
ENGINE_JS = SRC / "engine.js"
APP_JS = SRC / "app.js"
LOCALES = SRC / "i18n" / "locales.json"
VENDORS = (
    SRC / "vendor" / "pdf-lib.min.js",
    SRC / "vendor" / "pdf.min.js",
)
WORKER = SRC / "vendor" / "pdf.worker.min.js"
OUT = ROOT / "index.html"
DIST = ROOT / "dist"
PUBLIC = ROOT / "public"
SITE = SRC / "site"
VERSION_FILE = ROOT / "VERSION"

AUTHORED = ("en", "fr", "ro", "sr-latn")
ALL_LOCALES = ("en", "fr", "ro", "sr-latn", "sr-cyrl")

# Terms that stay in Latin script inside the Cyrillic locale.
KEEP_LATIN = (
    "Free Signature Generator",
    "Sign PDF",
    "TekiDeki",
    "web-free.site",
    "Apache-2.0",
    "PDF",
    "PNG",
    "JPG",
    "Adobe Sign",
    "DocuSign",
    "eIDAS",
)

NON_SERBIAN = set("qwxQ WX".replace(" ", ""))

DIGRAPHS = {"lj": "љ", "nj": "њ", "dž": "џ"}
LETTERS = {
    "a": "а", "b": "б", "c": "ц", "č": "ч", "ć": "ћ", "d": "д", "đ": "ђ",
    "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "ј", "k": "к",
    "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "r": "р", "s": "с",
    "š": "ш", "t": "т", "u": "у", "v": "в", "z": "з", "ž": "ж",
}

PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z]+\}")
FORBIDDEN = {"\u2013": "en dash", "\u2014": "em dash", "\u00a0": "no-break space"}

SITE_ORIGIN = "https://free-signature-generator.web-free.site"
SHELL = SITE / "shell.html"
SITE_CSS = SITE / "site.css"


class BuildError(SystemExit):
    pass


def fail(message: str) -> None:
    raise BuildError("build failed: " + message)


def read(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        fail(f"{path.name} starts with a byte order mark")
    return data.decode("utf-8")


def check_text(name: str, text: str) -> None:
    for char, label in FORBIDDEN.items():
        if char in text:
            line = text[: text.index(char)].count("\n") + 1
            fail(f"{name} contains a {label} on line {line}")
    if "\ufffd" in text:
        fail(f"{name} contains a replacement character")


def transliterate(text: str) -> str:
    """Serbian Latin to Cyrillic, leaving {placeholders} and kept terms alone."""
    if not text:
        return text

    protected: list[str] = []

    def keep(value: str) -> str:
        protected.append(value)
        return f"\x00{len(protected) - 1}\x00"

    work = PLACEHOLDER_RE.sub(lambda match: keep(match.group(0)), text)
    for term in sorted(KEEP_LATIN, key=len, reverse=True):
        work = work.replace(term, keep(term))

    out: list[str] = []
    index = 0
    lowered = work.lower()
    while index < len(work):
        pair = lowered[index: index + 2]
        if pair in DIGRAPHS:
            cyr = DIGRAPHS[pair]
            out.append(cyr.upper() if work[index].isupper() else cyr)
            index += 2
            continue
        char = work[index]
        lower = char.lower()
        if lower in LETTERS:
            cyr = LETTERS[lower]
            out.append(cyr.upper() if char.isupper() else cyr)
        else:
            out.append(char)
        index += 1

    result = "".join(out)
    for position, value in enumerate(protected):
        result = result.replace(f"\x00{position}\x00", value)
    return result


def leftovers(text: str) -> set[str]:
    """Latin letters that survived transliteration and should not have."""
    work = PLACEHOLDER_RE.sub(" ", text)
    for term in sorted(KEEP_LATIN, key=len, reverse=True):
        work = work.replace(term, " ")
    return {char for char in work if char.isascii() and char.isalpha() and char not in NON_SERBIAN}


def load_locales() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(read(LOCALES))
    except json.JSONDecodeError as error:
        fail(f"locales.json is not valid JSON: {error}")
    for locale in AUTHORED:
        if locale not in data:
            fail(f"locales.json is missing the {locale} block")
    reference = set(data["en"])
    for locale in AUTHORED:
        keys = set(data[locale])
        if keys != reference:
            missing = sorted(reference - keys)
            extra = sorted(keys - reference)
            fail(f"{locale} key set differs (missing {missing[:6]}, extra {extra[:6]})")
    placeholders = lambda value: frozenset(PLACEHOLDER_RE.findall(value))
    for key in reference:
        expected = placeholders(data["en"][key])
        for locale in AUTHORED:
            if placeholders(data[locale][key]) != expected:
                fail(f"placeholder mismatch for {key} in {locale}")
    data["sr-cyrl"] = {key: transliterate(data["sr-latn"][key]) for key in data["sr-latn"]}
    for locale in ALL_LOCALES:
        for key, value in data[locale].items():
            if not isinstance(value, str) or not value.strip():
                fail(f"empty or non string value for {key} in {locale}")
            check_text(f"locales.json {locale}.{key}", value)
    for key, value in data["sr-cyrl"].items():
        bad = leftovers(value)
        if bad:
            fail(f"sr-cyrl.{key} still has Latin letters {sorted(bad)}: {value}")
    return data


def build() -> str:
    version = read(VERSION_FILE).strip()
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        fail("VERSION must be a dotted number")

    template = read(TEMPLATE)
    styles = read(STYLES)
    engine_js = read(ENGINE_JS)
    app_js = read(APP_JS)
    for name, text in (("template.html", template), ("styles.css", styles),
                       ("engine.js", engine_js), ("app.js", app_js)):
        check_text(name, text)

    vendor_js = [read(path) for path in VENDORS]
    worker_js = read(WORKER)

    # A closing script tag inside an inlined script would end the tag early
    # and silently break the page, so every bundle is checked at build time.
    for path, text in list(zip(VENDORS, vendor_js)) + [("engine.js", engine_js), ("app.js", app_js)]:
        name = path.name if hasattr(path, "name") else path
        if "</script" in text.lower():
            fail(f"{name} contains a literal closing script tag")
    if "</script" in worker_js.lower():
        fail("pdf.worker.min.js contains a literal closing script tag")

    locales = load_locales()

    used = set(re.findall(r'data-i18n(?:-title|-aria-label|-placeholder)?="([^"]+)"', template))
    used |= set(re.findall(r"\bt\(['\"]([A-Za-z0-9]+)['\"]", app_js))
    missing = sorted(key for key in used if key not in locales["en"])
    if missing:
        fail(f"template or app uses unknown keys: {missing}")

    for locale in ALL_LOCALES:
        if f'<option value="{locale}">' not in template:
            fail(f"the language selector is missing {locale}")

    payload = ",\n".join(
        "  " + json.dumps(locale) + ": " + json.dumps(locales[locale], ensure_ascii=False, sort_keys=True)
        for locale in ALL_LOCALES
    )
    locales_js = ("/* Generated by build.py from src/i18n/locales.json. Do not edit. */\n"
                  "window.TD_LOCALES = {\n" + payload + "\n};\n")
    if "</script" in locales_js.lower():
        fail("a locale string contains a literal closing script tag")

    html = template
    style_tag = '<link rel="stylesheet" href="styles.css">'
    if style_tag not in html:
        fail("template is missing the stylesheet link")
    html = html.replace(style_tag, "<style>\n" + styles.rstrip() + "\n</style>", 1)

    for src, body in (
        ('<script src="vendor/pdf-lib.min.js"></script>', vendor_js[0]),
        ('<script src="vendor/pdf.min.js"></script>', vendor_js[1]),
        ('<script id="pdfWorkerSource" type="text/plain"></script>',
         '<script id="pdfWorkerSource" type="text/plain">' + worker_js + "</script>"),
        ('<script src="engine.js"></script>', engine_js),
        ('<script src="i18n/locales.js"></script>', locales_js),
        ('<script src="app.js"></script>', app_js),
    ):
        if src not in html:
            fail(f"template is missing {src}")
        html = html.replace(src, body if body.startswith('<script id="pdfWorkerSource"')
                            else "<script>\n" + body.rstrip() + "\n</script>", 1)

    html = html.replace('<html lang="en">', '<html lang="en" data-version="' + version + '">', 1)
    html = html.replace("</body>", "<!-- Sign PDF " + version + " - single file build -->\n</body>", 1)

    masked = html
    for body in vendor_js + [worker_js]:
        masked = masked.replace(body, "/* vendor */").replace(body.rstrip(), "/* vendor */")
    check_text("index.html", masked)
    if '<link rel="stylesheet"' in html or re.search(r'<script src="(?!https://)', html):
        fail("index.html still references a local asset")
    if not html.startswith("<!DOCTYPE html>"):
        fail("index.html must start with the doctype")

    OUT.write_text(html, encoding="utf-8")
    return html


STATIC_PAGES = [
    {
        "path": "about",
        "lang": "en",
        "title": "About Free Signature Generator",
        "description": "Open-source browser tool to draw signatures, export PNG and sign PDF locally. Built on TekiDeki Sign-PDF (Apache-2.0).",
        "body": (
            "<h1>About</h1>"
            "<p><strong>Free Signature Generator</strong> helps you draw or type a signature, download a transparent PNG, "
            "and place that signature on a PDF, all in your browser without uploading files.</p>"
            "<h2>Upstream project</h2>"
            "<p>This site is built on <a href=\"https://github.com/TekiDeki/Sign-PDF\">Sign PDF</a> by "
            "Kristian Mario Miskovic (TekiDeki), licensed under <strong>Apache-2.0</strong>. We keep the LICENSE and "
            "NOTICE files and credit the original author. Vendored <strong>pdf-lib</strong> (MIT) and "
            "<strong>PDF.js</strong> (Apache-2.0) power PDF work in the browser.</p>"
            "<h2>Not a qualified signature</h2>"
            "<p>This is <em>not</em> a certified, qualified or certificate-based electronic signature. It is not equivalent "
            "to Adobe Sign, DocuSign, or an eIDAS qualified signature. You receive a visual signature on the page or a PNG file.</p>"
            "<p><a href=\"/\">Open the signature tool</a></p>"
        ),
        "alt_fr": "fr/about",
    },
    {
        "path": "privacy",
        "lang": "en",
        "title": "Privacy - Free Signature Generator",
        "description": "No upload, no accounts, no analytics on signature or PDF content. Local browser processing only.",
        "body": (
            "<h1>Privacy</h1>"
            "<p>PDF pages and signatures are processed <strong>locally in your browser</strong>. We do not receive your "
            "documents or signature images.</p>"
            "<ul>"
            "<li>No user accounts</li>"
            "<li>No upload of PDF or signature files to our servers for signing</li>"
            "<li>Optional preferences may be stored in <code>localStorage</code> on your device</li>"
            "</ul>"
            "<p>Third-party ad scripts (Adsterra) may set cookies or load resources according to their own policies. "
            "We do not use Google AdSense.</p>"
        ),
        "alt_fr": "fr/privacy",
    },
    {
        "path": "terms",
        "lang": "en",
        "title": "Terms - Free Signature Generator",
        "description": "Use at your own risk. Not legal advice. Signatures produced here are not qualified electronic signatures.",
        "body": (
            "<h1>Terms of use</h1>"
            "<p>The tool is provided <strong>as is</strong> without warranty. You are responsible for how you use signed "
            "documents in your jurisdiction.</p>"
            "<h2>Electronic signature disclaimer</h2>"
            "<p>Signatures placed with this tool are <strong>not</strong> certified, qualified or certificate-based "
            "electronic signatures. They are not a substitute for platforms such as Adobe Sign or DocuSign, and they "
            "may not meet eIDAS or local legal requirements for qualified signatures.</p>"
            "<p>Software is based on Sign PDF (Apache-2.0). See LICENSE and NOTICE in the repository.</p>"
        ),
        "alt_fr": "fr/terms",
    },
    {
        "path": "contact",
        "lang": "en",
        "title": "Contact - Free Signature Generator",
        "description": "Contact via the web-free.site hub. No support for legal validity of signatures.",
        "body": (
            "<h1>Contact</h1>"
            "<p>This is a static, client-side tool hosted at "
            "<a href=\"https://free-signature-generator.web-free.site/\">free-signature-generator.web-free.site</a>.</p>"
            "<p>For other free tools from the same publisher, visit "
            "<a href=\"https://web-free.site\">web-free.site</a>.</p>"
            "<p>Upstream source code: <a href=\"https://github.com/TekiDeki/Sign-PDF\">TekiDeki/Sign-PDF</a>.</p>"
        ),
    },
    {
        "path": "how-to",
        "lang": "en",
        "title": "How to sign a PDF and export a signature PNG",
        "description": "Step-by-step: draw or type a signature, download transparent PNG, place on PDF locally.",
        "body": (
            "<h1>How to use Free Signature Generator</h1>"
            "<ol>"
            "<li><strong>Draw, type or upload</strong> your signature in the right panel.</li>"
            "<li>Click <strong>Download signature as PNG</strong> to save a transparent PNG anytime.</li>"
            "<li>Open a PDF, click a page where the signature should go, drag to move and resize.</li>"
            "<li>Click <strong>Download the signed PDF</strong>. The file is built locally; nothing is uploaded.</li>"
            "</ol>"
            "<h2>FAQ</h2>"
            "<p><strong>Is it legally binding?</strong> No. This is not a qualified or certificate-based e-signature.</p>"
            "<p><strong>Is my PDF uploaded?</strong> No. Processing stays in your browser tab.</p>"
            "<p><a href=\"/\">Start signing</a></p>"
        ),
    },
    {
        "path": "draw-signature-transparent-png",
        "lang": "en",
        "title": "Draw a signature and download a transparent PNG",
        "description": "Free online signature pad: draw or type your name and download a transparent PNG without uploading.",
        "body": (
            "<h1>Draw a signature and download a transparent PNG</h1>"
            "<p>Use our free browser tool to <strong>draw a handwritten signature</strong> or "
            "<strong>type your name</strong> in script or serif, then export a <strong>transparent PNG</strong>. "
            "No upload and no account.</p>"
            "<p>You can reuse the same signature to sign a PDF on the same page.</p>"
            "<p><a href=\"/\">Open Free Signature Generator</a></p>"
        ),
    },
    {
        "path": "sign-pdf-without-uploading",
        "lang": "en",
        "title": "Sign PDF without uploading the file",
        "description": "Sign PDF documents in the browser. Local processing only, no server upload.",
        "body": (
            "<h1>Sign a PDF without uploading the file</h1>"
            "<p>Drop a PDF into the tool and add your signature on any page. The document never leaves your device; "
            "pages are rendered and exported with <strong>pdf-lib</strong> and <strong>PDF.js</strong> inside your browser.</p>"
            "<p>Remember: this produces a visual signature, not a qualified digital signature.</p>"
            "<p><a href=\"/\">Sign a PDF now</a></p>"
        ),
    },
    {
        "path": "fr/about",
        "lang": "fr",
        "title": "À propos du générateur de signature gratuit",
        "description": "Outil open source pour dessiner une signature, exporter un PNG et signer un PDF localement.",
        "body": (
            "<h1>À propos</h1>"
            "<p><strong>Générateur de signature gratuit</strong> vous permet de dessiner ou taper une signature, "
            "télécharger un PNG transparent et la placer sur un PDF, entièrement dans le navigateur.</p>"
            "<p>Basé sur <a href=\"https://github.com/TekiDeki/Sign-PDF\">Sign PDF</a> (Apache-2.0) par Kristian Mario Miskovic (TekiDeki).</p>"
            "<h2>Pas une signature qualifiée</h2>"
            "<p>Ce n'est pas une signature électronique certifiée, qualifiée ou à certificat, ni l'équivalent d'Adobe Sign, DocuSign ou d'une signature eIDAS qualifiée.</p>"
            "<p><a href=\"/fr/\">Ouvrir l'outil</a></p>"
        ),
        "hreflang_en": "about",
    },
    {
        "path": "fr/privacy",
        "lang": "fr",
        "title": "Confidentialité",
        "description": "Traitement local dans le navigateur. Pas d'envoi de PDF ni de signatures.",
        "body": (
            "<h1>Confidentialité</h1>"
            "<p>Les PDF et signatures sont traités <strong>localement</strong>. Nous ne recevons pas vos fichiers.</p>"
            "<p>Des scripts publicitaires tiers (Adsterra) peuvent utiliser leurs propres cookies.</p>"
        ),
        "hreflang_en": "privacy",
    },
    {
        "path": "fr/terms",
        "lang": "fr",
        "title": "Conditions d'utilisation",
        "description": "Avertissement : pas de signature électronique qualifiée.",
        "body": (
            "<h1>Conditions</h1>"
            "<p>Outil fourni tel quel. Vous êtes responsable de l'usage des documents signés.</p>"
            "<p>Les signatures ne sont <strong>pas</strong> qualifiées au sens eIDAS.</p>"
        ),
        "hreflang_en": "terms",
    },
]


def shell_hreflang(page: dict) -> str:
    canonical = SITE_ORIGIN + "/" + page["path"].strip("/") + "/"
    links = [f'<link rel="alternate" hreflang="{page["lang"]}" href="{canonical}">']
    if page.get("alt_fr"):
        links.append(f'<link rel="alternate" hreflang="fr" href="{SITE_ORIGIN}/{page["alt_fr"]}/">')
    if page.get("hreflang_en"):
        links.append(f'<link rel="alternate" hreflang="en" href="{SITE_ORIGIN}/{page["hreflang_en"]}/">')
    links.append(f'<link rel="alternate" hreflang="x-default" href="{SITE_ORIGIN}/">')
    return "\n".join(links)


def render_static_page(page: dict, shell: str) -> str:
    depth = page["path"].count("/") + 1
    root = "../" * depth
    home = SITE_ORIGIN + ("/fr/" if page["lang"] == "fr" else "/")
    asset_root = SITE_ORIGIN + "/"
    canonical = SITE_ORIGIN + "/" + page["path"].strip("/") + "/"
    nav_root = root
    return (
        shell.replace("{{LANG}}", page["lang"])
        .replace("{{TITLE}}", page["title"])
        .replace("{{DESCRIPTION}}", page["description"])
        .replace("{{CANONICAL}}", canonical)
        .replace("{{HREFLANG}}", shell_hreflang(page))
        .replace("{{BODY}}", page["body"])
        .replace("{{ROOT}}", nav_root)
        .replace("{{HOME}}", home)
        .replace("{{ASSET_ROOT}}", asset_root)
    )


def localize_tool_html(html: str, *, lang: str, canonical_path: str, asset_prefix: str) -> str:
    canonical = SITE_ORIGIN + canonical_path
    html = re.sub(
        r'<html lang="en"([^>]*)>',
        lambda match: f'<html lang="{lang}" data-default-lang="{lang}"{match.group(1)}>',
        html,
        count=1,
    )
    html = re.sub(
        r'<link rel="canonical" href="[^"]+">',
        f'<link rel="canonical" href="{canonical}">',
        html,
        count=1,
    )
    if lang == "fr":
        html = html.replace(
            'href="https://free-signature-generator.web-free.site/"',
            'href="https://free-signature-generator.web-free.site/fr/"',
            1,
        )
    if asset_prefix:
        for name in ("manifest.json", "favicon.ico", "favicon-32.png", "apple-touch-icon.png"):
            html = html.replace(f'href="{name}"', f'href="{asset_prefix}{name}"')
    return html


def write_sitemap(dist: Path) -> None:
    urls = [
        ("/", "weekly", "1.0"),
        ("/fr/", "weekly", "1.0"),
        ("/about/", "monthly", "0.7"),
        ("/privacy/", "monthly", "0.6"),
        ("/terms/", "monthly", "0.6"),
        ("/contact/", "monthly", "0.5"),
        ("/how-to/", "monthly", "0.8"),
        ("/draw-signature-transparent-png/", "monthly", "0.75"),
        ("/sign-pdf-without-uploading/", "monthly", "0.75"),
        ("/how-to-create-a-signature-for-email/", "monthly", "0.75"),
        ("/how-to-make-a-transparent-signature-for-documents/", "monthly", "0.75"),
        ("/fr/about/", "monthly", "0.65"),
        ("/fr/privacy/", "monthly", "0.55"),
        ("/fr/terms/", "monthly", "0.55"),
    ]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, freq, priority in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{SITE_ORIGIN}{path}</loc>")
        lines.append(f"    <changefreq>{freq}</changefreq>")
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    (dist / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def publish_dist(html: str) -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    (DIST / "index.html").write_text(html, encoding="utf-8")
    fr_html = localize_tool_html(html, lang="fr", canonical_path="/fr/", asset_prefix="../")
    (DIST / "fr").mkdir(parents=True, exist_ok=True)
    (DIST / "fr" / "index.html").write_text(fr_html, encoding="utf-8")

    shell = read(SHELL)
    for page in STATIC_PAGES:
        out_dir = DIST / page["path"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(render_static_page(page, shell), encoding="utf-8")

    shutil.copy2(SITE_CSS, DIST / "site.css")

    for name in (
        "manifest.json", "sw.js", "robots.txt", "favicon.ico", "favicon-32.png",
        "apple-touch-icon.png", ".nojekyll",
    ):
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, DIST / name)

    if PUBLIC.exists():
        shutil.copytree(PUBLIC, DIST, dirs_exist_ok=True)

    icons_src = ROOT / "icons"
    if icons_src.is_dir():
        shutil.copytree(icons_src, DIST / "icons", dirs_exist_ok=True)

    write_sitemap(DIST)
    shutil.copy2(DIST / "sitemap.xml", ROOT / "sitemap.xml")


def main() -> None:
    html = build()
    publish_dist(html)
    size = len(html.encode("utf-8"))
    locales = json.loads(read(LOCALES))
    print(f"index.html written, {size} bytes, {size / 1024:.1f} KiB")
    print(f"dist/ published for Cloudflare Workers assets")
    print(f"locales: {', '.join(ALL_LOCALES)} ({len(locales['en'])} keys each)")
    print(f"VERSION: {read(VERSION_FILE).strip()}")


if __name__ == "__main__":
    main()
