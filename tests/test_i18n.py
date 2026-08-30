#!/usr/bin/env python3
"""
Unit tests for the interface language: the account preference API that stores
it, and the front-end catalogs that supply the translated strings.

The catalog tests are the ones that catch real regressions during development:
a string added to a page without a matching entry in nl/fr renders as English
(or, worse, as a bare key), and nothing else would notice.

Runs offline (no live server, no Elia calls):
    ENERGY_PEBBLE_DATA_DIR=$(mktemp -d) pytest tests/test_i18n.py
"""

import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Point main.py at a throwaway data dir before importing it (it initializes
# the database at import time).
os.environ.setdefault("ENERGY_PEBBLE_DATA_DIR", tempfile.mkdtemp(prefix="pebble-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)

STATIC = Path(__file__).resolve().parent.parent / "static"

# Every file that carries translatable strings. Admin pages are deliberately
# absent: they are internal and stay English.
TRANSLATED_FILES = [
    STATIC / "index.html",
    STATIC / "dashboard.html",
    STATIC / "login.html",
    STATIC / "impact-circle.html",
    STATIC / "simulator.html",
    STATIC / "setup" / "index.html",
    STATIC / "settings-modal.js",
    STATIC / "pebble-sim.js",
]


@pytest.fixture(autouse=True)
def clean_preferences():
    yield
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute("DELETE FROM user_preferences")
        conn.commit()


def _headers(user):
    return {"Remote-User": user}


# --- the preference API -------------------------------------------------------

def test_language_defaults_to_english():
    body = client.get("/api/user/preferences", headers=_headers("nele")).json()
    assert body["preferences"]["language"] == "en"
    assert body["options"]["language"] == ["en", "nl", "fr"]


def test_language_round_trips():
    h = _headers("nele")
    saved = client.put("/api/user/preferences", headers=h, json={"language": "nl"})
    assert saved.status_code == 200
    assert saved.json()["preferences"]["language"] == "nl"
    assert client.get("/api/user/preferences", headers=h).json()["preferences"]["language"] == "nl"

    # Changing it again overwrites rather than adding a second row
    client.put("/api/user/preferences", headers=h, json={"language": "fr"})
    assert client.get("/api/user/preferences", headers=h).json()["preferences"]["language"] == "fr"
    with sqlite3.connect(main.DB_PATH) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM user_preferences WHERE user_id = ?", ("nele",)).fetchone()
    assert rows[0] == 1


def test_language_is_per_account():
    client.put("/api/user/preferences", headers=_headers("nele"), json={"language": "fr"})
    other = client.get("/api/user/preferences", headers=_headers("bram")).json()
    assert other["preferences"]["language"] == "en"


def test_unknown_language_is_rejected():
    resp = client.put("/api/user/preferences", headers=_headers("nele"), json={"language": "de"})
    assert resp.status_code == 400
    assert "language" in resp.json()["detail"]
    # ...and nothing was written
    assert client.get("/api/user/preferences", headers=_headers("nele")).json()["preferences"]["language"] == "en"


def test_empty_update_keeps_current_language():
    h = _headers("nele")
    client.put("/api/user/preferences", headers=h, json={"language": "nl"})
    assert client.put("/api/user/preferences", headers=h, json={}).json()["preferences"]["language"] == "nl"


def test_preferences_require_authentication():
    assert client.get("/api/user/preferences").status_code == 401
    assert client.put("/api/user/preferences", json={"language": "nl"}).status_code == 401


# --- the front-end catalogs ---------------------------------------------------

def _catalogs():
    """Parse the three catalogs out of static/i18n-strings.js.

    The file is JavaScript, not JSON, so the keys are read with a regex rather
    than a parser: it only has to see which keys each language defines.
    """
    source = (STATIC / "i18n-strings.js").read_text(encoding="utf-8")
    catalogs = {}
    for lang in ("en", "nl", "fr"):
        # Slice from `<lang>: {` to the closing brace of that object
        start = re.search(r"^  %s: \{$" % lang, source, re.M)
        assert start, f"catalog {lang} not found"
        end = re.compile(r"^  \}", re.M).search(source, start.end())
        block = source[start.end():end.start()]
        catalogs[lang] = set(re.findall(r"^    '([^']+)':", block, re.M))
    return catalogs


def test_translations_cover_every_english_key():
    catalogs = _catalogs()
    assert catalogs["en"], "English catalog is empty — the parser is wrong"
    for lang in ("nl", "fr"):
        missing = sorted(catalogs["en"] - catalogs[lang])
        extra = sorted(catalogs[lang] - catalogs["en"])
        assert not missing, f"{lang} is missing: {missing}"
        assert not extra, f"{lang} has keys English does not: {extra}"


def _keys_used():
    """Every translation key referenced from a page or component."""
    patterns = [
        re.compile(r'data-i18n(?:-[a-z-]+)?="([a-zA-Z0-9._]+)"'),
        re.compile(r"\bt\(\s*'([a-zA-Z0-9._]+)'"),
        re.compile(r"""I18n\.t\(\s*["']([a-zA-Z0-9._]+)"""),
        re.compile(r"Key: '([a-zA-Z0-9._]+)'"),
        re.compile(r"""dataset\.i18n = ["']([a-zA-Z0-9._]+)["']"""),
    ]
    plural_re = re.compile(r"plural\(\s*'([a-zA-Z0-9._]+)'")

    keys, plurals = {}, set()
    for path in TRANSLATED_FILES:
        source = path.read_text(encoding="utf-8")
        for pattern in patterns:
            for key in pattern.findall(source):
                keys.setdefault(key, path.name)
        plurals.update(plural_re.findall(source))
    return keys, plurals


def test_every_key_used_in_the_ui_exists_in_the_catalog():
    english = _catalogs()["en"]
    keys, plurals = _keys_used()
    assert keys, "no keys found — the extraction patterns are wrong"

    missing = sorted(f"{key} (in {where})" for key, where in keys.items() if key not in english)
    assert not missing, f"keys used but not translated: {missing}"

    # Plural keys are stored as <key>.one / <key>.other
    missing_plurals = sorted(
        f"{key}{suffix}" for key in plurals for suffix in (".one", ".other")
        if f"{key}{suffix}" not in english
    )
    assert not missing_plurals, f"plural forms missing: {missing_plurals}"


def test_catalog_has_no_unused_keys():
    """A key nobody references is dead weight three times over."""
    english = _catalogs()["en"]
    keys, plurals = _keys_used()
    referenced = set(keys)
    for key in plurals:
        referenced.update({f"{key}.one", f"{key}.other"})
    assert not sorted(english - referenced)


def test_placeholders_match_across_languages():
    """{name} placeholders must survive translation, or the text breaks."""
    source = (STATIC / "i18n-strings.js").read_text(encoding="utf-8")
    per_lang = {}
    for lang in ("en", "nl", "fr"):
        start = re.search(r"^  %s: \{$" % lang, source, re.M)
        end = re.compile(r"^  \}", re.M).search(source, start.end())
        block = source[start.end():end.start()]
        per_lang[lang] = {
            key: set(re.findall(r"\{(\w+)\}", value))
            for key, value in re.findall(r"^    '([^']+)': (.*?),?$", block, re.M)
        }

    for lang in ("nl", "fr"):
        for key, placeholders in per_lang["en"].items():
            assert per_lang[lang].get(key) == placeholders, \
                f"{lang}:{key} placeholders {per_lang[lang].get(key)} != en {placeholders}"


def test_every_page_loads_the_runtime():
    """A page with keys but no i18n.js would render raw key names."""
    for path in TRANSLATED_FILES:
        if path.suffix != ".html":
            continue
        source = path.read_text(encoding="utf-8")
        assert "i18n-strings.js" in source, f"{path.name} does not load the catalogs"
        assert "i18n.js" in source, f"{path.name} does not load the runtime"
        assert "I18n.start(" in source, f"{path.name} never starts the runtime"


def test_runtime_loads_before_the_components_that_register_with_it():
    """pebble-sim and settings-modal register their shadow roots with I18n at
    upgrade time; if their script runs first, window.I18n does not exist yet
    and their contents stay untranslated."""
    for name in ("index.html", "dashboard.html", "simulator.html"):
        source = (STATIC / name).read_text(encoding="utf-8")
        runtime = source.index('src="i18n.js"')
        for component in ("pebble-sim.js", "settings-modal.js"):
            marker = f'src="{component}"'
            if marker in source:
                assert runtime < source.index(marker), \
                    f"{name} loads {component} before i18n.js"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
