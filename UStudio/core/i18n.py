"""Translations of the program's texts. No Qt: the GUI, core/ and the command-line tool share it.

Russian is the BASE language: the Russian text written in the code is the key, and a catalog
(locales/<code>.json) gives the text for another language. Nothing to translate for Russian.

    from core.i18n import tr, trn, N_

    tr("Открыть папку")                                   -> "Open folder"
    tr("Обработано: {} из {} объектов.", done, total)     -> str.format() after translating
    tr("Файл «{name}» не найден.", name=path)
    trn(count, "{n} файл", "{n} файла", "{n} файлов")    -> the right plural form, {n} = count
    tr("Вид", ctx="menu")                                 -> a separate entry when one Russian text needs two
                                                             different translations

Rules (tests/test_i18n.py checks them over the sources):
  * The argument of tr()/trn() is a string LITERAL (no f-strings, no variables) — the extractor
    (dev_scripts/i18n_extract.py) can then find every key. Put the variable parts in {placeholders}.
  * tr() is never called at import time (module level, class body, default arguments): the language
    is chosen after the modules are imported. A table of texts at module level marks them with N_()
    (returns the text unchanged) and translates where they are shown: tr(TITLES[kind]).
  * A text that is not in the catalog (or is null there) falls back along the language's fallback
    chain, ending in the Russian text — a missing translation never breaks anything.
  * A translation whose {placeholders} do not fit the arguments falls back to the Russian text
    formatted the same way, instead of raising.

Catalog format (UTF-8 JSON):
    {
      "_meta": {"code": "en", "name": "English", "fallback": []},
      "messages": {"Открыть папку": "Open folder", "{n} файл": ["{n} file", "{n} files"]},
      "contexts": {"menu": {"Вид": "View"}}
    }
  A plural entry's key is the Russian ONE form, its value the list of the language's forms
  (English: one, other; Ukrainian: one, few, many). null = not translated yet.

The command-line tool calls set_language("en") at start (its text stays English); the GUI
(app_language.py) picks the language the user chose in Настройки -> Язык.
"""

from __future__ import annotations

import json
import locale
import os
import string
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

BASE_LANGUAGE = "ru"
SYSTEM = "system"
DEFAULT_LANGUAGE = "en"          # "Как в системе" on a system whose language we do not have
LANGUAGES = ("en", "ru", "uk")   # what the menu offers (catalogs for all but the base one)

# Names shown in the language menu: each in its own language, so a user who cannot read the current
# one still finds theirs.
LANGUAGE_NAMES = {"en": "English", "ru": "Русский", "uk": "Українська"}   # i18n: keep

LOCALES_SUBPATH = "locales"
_ENV_LOCALES_DIR = "USTUDIO_LOCALES_DIR"     # tests point it at a temporary folder


def N_(text: str) -> str:
    """Marks a text for translation without translating it (module-level tables); translate it with tr() where it
    is shown."""
    return text


# --- plural rules ---------------------------------------------------------------------------------------------


def _plural_slavic(n: int) -> int:
    n = abs(int(n))
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return 0
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return 1
    return 2


def _plural_english(n: int) -> int:
    return 0 if abs(int(n)) == 1 else 1


PLURAL_RULES: Dict[str, Callable[[int], int]] = {"ru": _plural_slavic, "uk": _plural_slavic, "en": _plural_english}
PLURAL_FORM_COUNT = {"ru": 3, "uk": 3, "en": 2}


# --- catalogs -------------------------------------------------------------------------------------------------


class Catalog:
    """One language's texts. `messages`: key -> str | list | None; `contexts`: ctx -> the same."""

    def __init__(self, code: str, messages=None, contexts=None, fallback: Sequence[str] = (), name: str = ""):
        self.code = code
        self.name = name or LANGUAGE_NAMES.get(code, code)
        self.messages: Dict[str, object] = dict(messages or {})
        self.contexts: Dict[str, Dict[str, object]] = {k: dict(v) for k, v in (contexts or {}).items()}
        self.fallback: List[str] = list(fallback)

    def lookup(self, key: str, ctx: Optional[str]):
        table = self.contexts.get(ctx, {}) if ctx else self.messages
        return table.get(key)

    @classmethod
    def from_json(cls, code: str, data: dict) -> "Catalog":
        meta = data.get("_meta") or {}
        return cls(code, data.get("messages"), data.get("contexts"), meta.get("fallback") or (), meta.get("name", ""))


def locales_dirs() -> List[Path]:
    """Where locales/ may be: next to the sources during development, next to the exe in a build."""
    env = os.environ.get(_ENV_LOCALES_DIR)
    if env:
        return [Path(env)]
    here = Path(__file__).resolve().parent          # UStudio/core
    out = [here.parent / LOCALES_SUBPATH, Path(sys.executable).resolve().parent / LOCALES_SUBPATH]
    if sys.argv and sys.argv[0]:
        out.append(Path(sys.argv[0]).resolve().parent / LOCALES_SUBPATH)
    return out


def find_locales_dir() -> Optional[Path]:
    for candidate in locales_dirs():
        if candidate.is_dir():
            return candidate
    return None


def load_catalog(code: str) -> Optional[Catalog]:
    """The catalog of `code` from locales/<code>.json, or None (missing / unreadable: texts stay Russian)."""
    folder = find_locales_dir()
    if folder is None:
        return None
    try:
        data = json.loads((folder / f"{code}.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return Catalog.from_json(code, data) if isinstance(data, dict) else None


# --- the current language -------------------------------------------------------------------------------------

_lock = threading.Lock()
_language = BASE_LANGUAGE
_chain: List[Catalog] = []          # the language's catalog, then its fallbacks (the base language needs none)
_catalog_cache: Dict[str, Optional[Catalog]] = {}


def _catalog(code: str) -> Optional[Catalog]:
    if code not in _catalog_cache:
        _catalog_cache[code] = load_catalog(code)
    return _catalog_cache[code]


def _build_chain(code: str) -> List[Catalog]:
    """The catalog of `code`, then its fallbacks (each once; the base language has no catalog)."""
    chain: List[Catalog] = []
    seen = {BASE_LANGUAGE}
    todo = [code]
    while todo:
        c = todo.pop(0)
        if c in seen:
            continue
        seen.add(c)
        cat = _catalog(c)
        if cat is not None:
            chain.append(cat)
            todo.extend(cat.fallback)
    return chain


def set_language(code: str, catalogs: Optional[Dict[str, Catalog]] = None) -> str:
    """Switches every later tr()/trn() to `code` ("en", "ru", "uk" or SYSTEM). Returns the language in use.
    `catalogs` (tests) replaces the files on disk."""
    global _language, _chain
    code = resolve_language(code)
    with _lock:
        if catalogs is not None:
            _catalog_cache.clear()
            _catalog_cache.update(catalogs)
        _language, _chain = code, _build_chain(code)
    return code


def current_language() -> str:
    return _language


def reset_catalog_cache() -> None:
    with _lock:
        _catalog_cache.clear()


_WINDOWS_PRIMARY_LANGUAGES = {0x09: "en", 0x19: "ru", 0x22: "uk"}


def language_of_langid(langid: int) -> str:
    """A Windows LANGID (GetUserDefaultUILanguage) -> "en" / "ru" / "uk", or DEFAULT_LANGUAGE."""
    return _WINDOWS_PRIMARY_LANGUAGES.get(langid & 0x3FF, DEFAULT_LANGUAGE)


def language_of_tag(tag: str) -> str:
    """A locale name ("ru_RU", "uk-UA", "English_United States") -> "en" / "ru" / "uk", or DEFAULT_LANGUAGE."""
    tag = (tag or "").lower().replace("-", "_")
    for code, prefixes in (("ru", ("ru_", "russian")), ("uk", ("uk_", "ukrainian")), ("en", ("en_", "english"))):
        if tag == code or tag.startswith(prefixes):
            return code
    return DEFAULT_LANGUAGE


def system_language() -> str:
    """The user's display language if we have it ("en", "ru", "uk"), else DEFAULT_LANGUAGE (English)."""
    if sys.platform == "win32":
        try:
            import ctypes
            return language_of_langid(ctypes.windll.kernel32.GetUserDefaultUILanguage())
        except Exception:
            pass
    for value in (os.environ.get("LC_ALL"), os.environ.get("LC_MESSAGES"), os.environ.get("LANG"),
                  locale.getlocale()[0]):
        if value:
            return language_of_tag(value.split(".")[0])
    return DEFAULT_LANGUAGE


def resolve_language(choice: str) -> str:
    """A menu choice -> the language to use: SYSTEM -> system_language(); an unknown code -> DEFAULT_LANGUAGE."""
    if choice == SYSTEM:
        return system_language()
    if choice == BASE_LANGUAGE or choice in LANGUAGES:
        return choice
    return DEFAULT_LANGUAGE


# --- translating ----------------------------------------------------------------------------------------------


def _format(text: str, fallback: str, args, kwargs) -> str:
    if not args and not kwargs:
        return text
    try:
        return text.format(*args, **kwargs)
    except (IndexError, KeyError, ValueError, AttributeError, TypeError):
        if text is fallback:
            raise
        return fallback.format(*args, **kwargs)


def tr(text: str, *args, ctx: Optional[str] = None, **kwargs) -> str:
    """`text` (Russian) in the current language, then str.format(*args, **kwargs) if any are given."""
    return _tr(_chain, text, args, ctx, kwargs)


def _tr(chain, text, args, ctx, kwargs) -> str:
    translated = text
    for cat in chain:
        value = cat.lookup(text, ctx)
        if isinstance(value, str) and value:
            translated = value
            break
    return _format(translated, text, args, kwargs)


def trn(n: int, one: str, few: str, many: str, *args, ctx: Optional[str] = None, **kwargs) -> str:
    """The plural form of the current language for `n` (Russian forms one/few/many: 1, 2-4, 5 файлов).
    {n} in the text is `n`; other placeholders come from args/kwargs."""
    return _trn(_chain, n, one, few, many, args, ctx, kwargs)


def _trn(chain, n, one, few, many, args, ctx, kwargs) -> str:
    kwargs.setdefault("n", n)
    russian = (one, few, many)[_plural_slavic(n)]
    for cat in chain:
        value = cat.lookup(one, ctx)
        if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            rule = PLURAL_RULES.get(cat.code, _plural_english)
            index = min(rule(n), len(value) - 1)
            if value[index]:
                return _format(value[index], russian, args, kwargs)
    return _format(russian, russian, args, kwargs)


def translate_to(code: str, text: str, *args, ctx: Optional[str] = None, **kwargs) -> str:
    """tr() in another language without switching to it (e.g. the "restart to apply" note in the chosen language)."""
    code = resolve_language(code)
    with _lock:
        chain = _build_chain(code)
    return _tr(chain, text, args, ctx, kwargs)


def placeholders(text: str) -> set:
    """The {fields} of a format string ("{}" counted by position: {0}, {1}, ...), for checking a translation."""
    out, auto = set(), 0
    try:
        for _literal, field, _spec, _conv in string.Formatter().parse(text):
            if field is None:
                continue
            name = field.split(".")[0].split("[")[0]
            if name == "":
                name = str(auto)
                auto += 1
            out.add(name)
    except ValueError:
        out.add("<invalid>")
    return out
