"""The user documentation that lives in docs/ru/ as plain files (shared by the command-line tool, which ships
them next to the exe, and the GUI help window, which renders the Markdown ones).

* find_docs_dir(): the docs/ru folder — in the repository during development, next to the exe in a build.
* render_markdown(): Markdown -> the small HTML subset Qt's QTextBrowser displays well. Qt's own
  QTextDocument.setMarkdown() is NOT used: it dropped a `<br>` line and emptied a table cell in a test with the
  real help text, so the files are converted with markdown-it-py (already installed, rich depends on it)."""

import sys
from pathlib import Path
from typing import List, Optional

from markdown_it import MarkdownIt

DOCS_ROOT = Path("docs")
DOCS_SUBPATH = DOCS_ROOT / "ru"        # the Russian base documents (the command-line tool ships these)
DOC_LANGUAGES = ("ru", "en", "uk")     # docs/<code>/ — the same files, translated

# Tables get the same look the help window's hand-written tables always had.
_TABLE_ATTRS = 'border="1" cellspacing="0" cellpadding="5" width="100%"'


def _candidate_dirs(lang: str = "ru") -> List[Path]:
    sub = DOCS_ROOT / lang
    here = Path(__file__).resolve().parent
    out = [here / sub, here.parent / sub, Path(sys.executable).resolve().parent / sub]
    if sys.argv and sys.argv[0]:
        out.append(Path(sys.argv[0]).resolve().parent / sub)
    return out


def find_docs_dir(lang: str = "ru") -> Optional[Path]:
    """docs/<lang> — in the repository during development, next to the exe in a build."""
    for candidate in _candidate_dirs(lang):
        if candidate.is_dir():
            return candidate
    return None


def read_doc(name: str, lang: Optional[str] = None) -> Optional[str]:
    """The text of docs/<lang>/<name> (UTF-8, with or without BOM) — lang = the interface language by default —,
    else the English, else the Russian one; None if none is there."""
    if lang is None:
        from core.i18n import current_language
        lang = current_language()
    for code in dict.fromkeys((lang, "en", "ru")):
        folder = find_docs_dir(code)
        if folder is None:
            continue
        try:
            return (folder / name).read_text(encoding="utf-8-sig")
        except OSError:
            continue
    return None


def _drop_leading_title(markdown: str) -> str:
    """A document starts with its own "# Title" line for people reading the file; the help window has its own
    headings, so that first title is not shown there."""
    lines = markdown.lstrip("﻿").splitlines()
    for i, line in enumerate(lines):
        if line.strip():
            if line.startswith("# "):
                return "\n".join(lines[i + 1:])
            break
    return markdown


def render_markdown(markdown: str, drop_title: bool = True) -> str:
    if drop_title:
        markdown = _drop_leading_title(markdown)
    # html=True: the documents use a few inline tags (<br>, <small>) that Markdown itself cannot express inside
    # a table cell.
    md = MarkdownIt("commonmark", {"html": True}).enable("table")
    html = md.render(markdown)
    return html.replace("<table>", f"<table {_TABLE_ATTRS}>").replace("<th>", '<th align="left">')
