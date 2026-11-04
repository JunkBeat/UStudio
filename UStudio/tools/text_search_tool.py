from core.i18n import tr, trn
import logging
import os
import sys
import re
from datetime import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox, QPushButton,
    QTableView, QStatusBar, QProgressBar, QMenu, QFileDialog, QLabel, QAbstractItemView, QHeaderView,
    QTextEdit, QApplication, QToolButton
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer
from PyQt6.QtGui import QAction, QCursor, QFont, QTextCursor

from helpers import bytes_to_hex_dump_with_map
from gui_workers import ProgressThrottle
from core.object_preview import get_row_name, get_row_script_name
from type_icons import get_action_icon, get_type_icon
from config import LogLevel
from gui_common import exec_and_dispose
from helpers import wrap_tooltip
from app_settings import app_settings
import theme

logger = logging.getLogger("ustudio.tools.text_search")

# Profiled against a real 502,105-object fixture (Truck-kun): building the
# preview string for every match used to run a per-character Python loop
# (ord() + list.append() per character — ~9 million calls each for a
# 128,000-match search, ~2.8s of the search's own 18.4s total) plus two
# re.sub() calls per match that re-hit re's internal pattern cache on every
# single call (256,000 cache lookups). Both are pure Python-level overhead
# with an exact C-level equivalent, so replacing them is a straight win
# with no behavior change, not a tradeoff.
#
# _PREVIEW_DISALLOWED_RE reproduces find_matches_in_bytes's old per-char
# branch (ASCII + Cyrillic + tab/LF/CR kept as-is, everything else — the old
# code's "code == 0 or char == '�'" elif was already redundant with its own
# else branch, both producing '.' — collapsed into one fallback) as a single
# character-class regex. A first attempt used str.translate() with a dict
# subclass's __missing__ as the fallback — measured faster than the original
# loop, but still paid a real Python-level call for every character NOT in
# the allowed set (2.6 million such calls on the same 128,000-match run,
# since raw binary padding around a match is mostly non-printable/non-
# Cyrillic junk that misses the dict every time). A single compiled regex
# substitution does the whole string in one C-level pass with no per-
# character Python callback at all, matching or not.
_PREVIEW_DISALLOWED_RE = re.compile('[^ -~А-я\t\n\r]')   # i18n: keep (a character class)

_PREVIEW_WHITESPACE_RE = re.compile(r'\s+')
_PREVIEW_REPEATED_DOTS_RE = re.compile(r'\.{2,}')


_SEARCH_WS = " \t\r\n"


def _encoded_variants(ch: str, case_sensitive: bool, enc: str) -> list:
    """Byte encodings of one character (all its case variants unless the
    search is case-sensitive). bytes-level re.IGNORECASE is ASCII-only, so
    Cyrillic/other case folding has to be spelled out per character."""
    variants = {ch}
    if not case_sensitive:
        variants |= {ch.lower(), ch.upper()}
    out = []
    for v in variants:
        if len(v) != 1:  # e.g. 'ß'.upper() == 'SS' — not a same-length variant
            continue
        try:
            out.append(v.encode(enc))
        except UnicodeEncodeError:
            pass
    return sorted(set(out))


def _char_regex(variants: list) -> bytes:
    if len(variants) == 1:
        return re.escape(variants[0])
    if all(len(v) == 1 for v in variants):
        return b"[" + b"".join(re.escape(v) for v in variants) + b"]"
    return b"(?:" + b"|".join(re.escape(v) for v in variants) + b")"


def build_text_patterns(search_text: str, case_sensitive: bool = False,
                        whole_word: bool = False) -> list:
    r"""Compiled byte-regex patterns [(re.Pattern, encoding)] for UTF-8 and
    UTF-16-LE, tolerant of line breaks:

    - any run of whitespace in the query matches any run of space/tab/CR/LF
      ("Some text" finds "Some\ntext" and "Some\r\n  text");
    - a line break may also appear between any two characters, so text that
      was hard-wrapped mid-word ("Some t\next") is found too;
    - case-insensitive search is Unicode-aware (Cyrillic etc.), not ASCII-only.
    """
    text = search_text.strip()
    if not text:
        return []
    ws_bytes = re.escape(_SEARCH_WS.encode())
    patterns = []
    for enc in ("utf-8", "utf-16-le"):
        wide = enc == "utf-16-le"
        brk = rb"(?:[\r\n]\x00)*" if wide else rb"[\r\n]*"
        ws_one = (b"(?:[" + ws_bytes + rb"]\x00)+") if wide else (b"[" + ws_bytes + b"]+")
        parts = []
        prev_ws = False
        try:
            for ch in text:
                if ch in _SEARCH_WS:
                    if not prev_ws:
                        parts.append(ws_one)
                    prev_ws = True
                    continue
                variants = _encoded_variants(ch, case_sensitive, enc)
                if not variants:
                    raise UnicodeEncodeError(enc, ch, 0, 1, "unencodable")
                if parts and not prev_ws:
                    parts.append(brk)  # optional line break between characters
                parts.append(_char_regex(variants))
                prev_ws = False
            body = b"".join(parts)
            if whole_word and not wide:
                body = rb"\b" + body + rb"\b"
            patterns.append((re.compile(body), enc))
        except (UnicodeEncodeError, re.error):
            continue
    return patterns


class PatternTooSlow(Exception):
    """A regular expression took longer than RegexSearch.TIMEOUT_S on one search step: the whole search stops
    with this message (skipping the object would silently miss hits)."""


def regex_problem(text: str) -> str:
    """The user's wording of what is wrong with a regular expression, or "" when it compiles."""
    import regex
    try:
        regex.compile(text)
    except regex.error as e:
        if getattr(e, "pos", None) is not None:
            return tr("В выражении ошибка около символа {value}.", value=e.pos + 1)
        return tr("В выражении ошибка.")
    return ""


class RegexSearch:
    """The user's regular expression (the «.*» button of the text search, 2026-10-19). Matched on TEXT, not on
    bytes: the object's bytes are decoded as UTF-8 with surrogateescape (bytes that are not UTF-8 become one
    character each, so every character maps back to its own bytes) and searched with the `regex` package —
    a byte pattern cannot express «a Cyrillic letter», `\\w` or `.` = one character. UTF-8 only: Unity stores
    its strings in UTF-8.

    Why `regex` and not `re`: `re` holds the GIL for a whole match, so a pattern that backtracks badly
    (`(a+)+b`) froze the whole app with no way to cancel; `regex` releases it (concurrent=True), handles
    such patterns far better, and every search step gets TIMEOUT_S (-> PatternTooSlow).
    Measured on 20 MB of random bytes (2026-10-19): decode 0.24 s, `\\d+ coins` 0.16 s, `.*coins` 0.06 s
    (`re` on bytes: 10.3 s), `(?:\\w+\\s)+coins` 0.81 s.

    Big data is searched in windows of WINDOW bytes (a decoded window can take 4 bytes per byte), overlapping
    by OVERLAP bytes; a match is taken by the window it starts in, so only a match longer than OVERLAP that
    starts near a window's end can be cut short."""
    encoding = "utf-8"
    TIMEOUT_S = 3.0
    WINDOW = 32 * 1024 * 1024
    OVERLAP = 64 * 1024

    def __init__(self, text: str, case_sensitive: bool = False, whole_word: bool = False):
        import regex
        flags = regex.MULTILINE | (0 if case_sensitive else regex.IGNORECASE)
        body = rf"\b(?:{text})\b" if whole_word else text
        self.pattern = regex.compile(body, flags)

    def find(self, data: bytes):
        """Yields (byte offset, byte length, matched text) in order; empty matches are skipped."""
        size = len(data)
        start = 0
        while start < size:
            core_end = min(size, start + self.WINDOW)
            end = min(size, core_end + self.OVERLAP) if core_end < size else size
            text = bytes(data[start:end]).decode("utf-8", "surrogateescape")
            char_pos = byte_pos = 0          # the last mapped character and its byte offset in the window
            pos = 0
            while pos <= len(text):
                try:
                    m = self.pattern.search(text, pos, concurrent=True, timeout=self.TIMEOUT_S)
                except TimeoutError:
                    raise PatternTooSlow(
                        tr("Выражение проверяется слишком долго — упростите его (например, без вложенных повторов).")
                    ) from None
                if m is None:
                    break
                pos = m.end() if m.end() > m.start() else m.start() + 1
                if m.end() == m.start():
                    continue
                byte_pos += len(text[char_pos:m.start()].encode("utf-8", "surrogateescape"))
                char_pos = m.start()
                if start + byte_pos >= core_end and end < size:
                    break                    # starts in the overlap: the next window takes it
                matched = m.group(0)
                yield start + byte_pos, len(matched.encode("utf-8", "surrogateescape")), matched
            start = core_end


def prepare_search_patterns(query_str, case_sensitive=False):
    patterns = []
    # Main set of encodings for binary files
    encodings = ['utf-8', 'utf-16-le', 'cp1251', 'cp866']
    
    for enc in encodings:
        try:
            if case_sensitive:
                p_bytes = query_str.encode(enc)
                patterns.append((p_bytes, enc))
            else:
                if enc == 'utf-16-le':
                    # For UTF-16-LE, generate both byte variants (lowercase and uppercase)
                    p_lower = query_str.lower().encode(enc)
                    p_upper = query_str.upper().encode(enc)
                    patterns.append((p_lower, enc))
                    if p_lower != p_upper:
                        patterns.append((p_upper, enc))
                else:
                    # For single-byte encodings, case is handled by target_bytes.lower()
                    p_bytes = query_str.lower().encode(enc)
                    patterns.append((p_bytes, enc))
        except UnicodeEncodeError:
            # Skip the encoding if the search string's characters don't fit into it
            continue
            
    return patterns


class SearchFilterProxyModel(QSortFilterProxyModel):
    def lessThan(self, left, right):
        # kept as a fallback for any other source model — for SearchResultsModel
        # sorting is now done in sort() below, bypassing the per-row lessThan()
        model = self.sourceModel()
        col = left.column()

        left_data = model.data(left, Qt.ItemDataRole.EditRole)
        right_data = model.data(right, Qt.ItemDataRole.EditRole)

        if left_data is None: return True
        if right_data is None: return False

        if col in (3, 4):
            try:
                return int(left_data) < int(right_data)
            except ValueError:
                return str(left_data) < str(right_data)

        return str(left_data) < str(right_data)

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        # QSortFilterProxyModel by default sorts via per-row comparison through
        # lessThan(), which calls data() across the Python/Qt boundary on every comparison —
        # on large search result sets (a huge game can produce very many matches)
        # this is the same kind of bottleneck the main table had. Delegate sorting to
        # the source model instead: there it's a single native Python list.sort() by key, one pass.
        source = self.sourceModel()
        if isinstance(source, SearchResultsModel):
            source.sort(column, order)
        else:
            super().sort(column, order)


class TextSearchThread(QThread):
    # BATCH_SIZE: matches accumulate in results and go to the GUI in batches rather than
    # one at a time — a common text query can produce thousands of matches in one large
    # game, and previously every such match was a separate signal across the thread
    # boundary plus a separate beginInsertRows/endInsertRows on the GUI thread, which
    # turned into a flood and froze the interface with no way to interrupt it.
    BATCH_SIZE = 200

    # Real reported bug: a short/common query (e.g. "a", "car") with "search all
    # object types" and "search binary" both enabled is almost guaranteed to make
    # a SINGLE object or binary file match many tens of thousands of times (a
    # short byte pattern is common in arbitrary binary data almost by definition).
    # Two compounding problems, both traced to the fact that neither the match
    # loop below nor _maybe_flush() had any per-item bound before this fix:
    #  1. find_matches_in_bytes()'s own match-finding loop had no interruption
    #     check at all — Cancel/Esc (checked only BETWEEN objects/files in
    #     _run_search) couldn't take effect until one pathologically-matching
    #     item finished entirely, which for a common short pattern in a large
    #     binary blob could be a very long time.
    #  2. _maybe_flush() only ever ran between objects/files too, so all of one
    #     item's matches — potentially hundreds of thousands — went out as ONE
    #     oversized batch_found_signal, which SearchResultsModel.append_rows()
    #     then had to insert into the table in a single beginInsertRows/
    #     endInsertRows call: exactly the "flood the GUI thread" scenario
    #     BATCH_SIZE's own docstring above already warns against, just
    #     triggered by one huge item instead of many small ones.
    # Capping how many matches a single object/file can contribute keeps both
    # bounded regardless of how common the query is, and further matches within
    # that same item are simply not collected (logged, not surfaced as an error —
    # this is expected behavior for this kind of query, not a failure).
    MAX_MATCHES_PER_ITEM = 5000

    # Real reported follow-up: MAX_MATCHES_PER_ITEM alone still isn't enough —
    # a genuinely common short query (e.g. a single letter) with "all object
    # types" + "search binary" both enabled matches in MOST of a large game's
    # ~500K+ objects, each capped at up to 5000 — the aggregate across the
    # WHOLE search is still tens of millions of result dicts, each one
    # decoded/regex-processed, each one a table row. That's what made the
    # combination "quickly render the program unresponsive" even with the
    # per-item cap in place. A hard cap on the TOTAL across the entire search
    # (checked between objects/files, not per-pattern) bounds this
    # unconditionally, regardless of how common the query or how large the
    # game is — a search tool table with this many rows is already far more
    # than anyone scrolls through by hand; past that the right move is
    # narrowing the query, not showing more rows. Value chosen from real
    # profiling against a 502,105-object fixture: even WITH this cap and
    # every other fix in this file, "a" + all types + binary still took
    # ~23s to hit a 50,000 cap (never even reaching the binary-file phase) —
    # 20,000 keeps the worst realistic case under ~10s instead.
    MAX_TOTAL_MATCHES = 20_000

    progress_signal = pyqtSignal(int, int, str)
    batch_found_signal = pyqtSignal(list)
    finished_signal = pyqtSignal(list, bool)  # (results, truncated) — see MAX_TOTAL_MATCHES
    cancelled_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, env, search_text, case_sensitive, whole_word, search_binary, search_all_unity,
                 main_names_cache=None, parent=None, use_regex=False):
        # parent=None default kept for backward compatibility, but every real
        # caller should pass parent=<the owning dialog> — this thread used to have
        # no parent at all despite being reassigned to a fresh instance on every
        # search, the same dangling-QThread-reference risk documented for
        # loader_thread.DataLoaderThread (see main.py's start_loading_data).
        super().__init__(parent)
        self.env = env
        self.search_text = search_text
        self.case_sensitive = case_sensitive
        self.whole_word = whole_word
        self.search_binary = search_binary
        self.search_all_unity = search_all_unity
        self.use_regex = use_regex
        # Despite the name (kept for compatibility with TextSearchDialog's own
        # call site), this is now a {(source, path_id): row_dict} INDEX, not a
        # {(source, path_id): resolved_name} cache — see the real reported bug
        # this fixes: TextSearchDialog.start_search() used to eagerly call
        # get_row_script_name()/get_row_name() for EVERY row in the main
        # table before starting the search at all — profiled at 11.3s on a
        # real 502,105-row fixture, entirely on the GUI thread (hence "the
        # Search button takes seconds to become active"), for work that's
        # almost always wasted: those are exactly the lazy/memoizing
        # accessors core/object_preview.py's own docstring already documents
        # as "the single largest cost in indexing a large game" specifically
        # so nothing has to pay for them per-row unless something actually
        # asks. Building a plain row INDEX costs nothing beyond storing
        # existing dict references; the actual name resolution now happens
        # in find_matches_in_bytes(), lazily, only for a MonoBehaviour that
        # actually matched — see that method's own comment.
        self.main_names_cache = main_names_cache or {}
        # Tracks how many of `results` have already been sent via
        # batch_found_signal — see _maybe_flush()/MAX_MATCHES_PER_ITEM's own
        # comments. An instance attribute (not a local passed around) so
        # find_matches_in_bytes() can flush mid-item, not just _run_search()
        # between items.
        self._last_emitted = 0
        # Set once MAX_TOTAL_MATCHES is hit — see that constant's own comment.
        self._truncated = False
        # Shared by the object loop, the binary-file loop, AND
        # find_matches_in_bytes()'s own match-finding loops — see _pump()'s
        # docstring. A real reported crash/profiling finding (not a guess):
        # a real 502,105-object fixture showed find_matches_in_bytes() itself
        # able to run CPU-bound for many seconds on a single common query
        # with only the OUTER per-object loop's own ProgressThrottle (0.15s
        # interval, i.e. an explicit GIL-yielding sleep roughly 6-7x/sec)
        # standing between the whole search and the GUI thread — nowhere
        # NEAR enough once a single item's own match-building work (not just
        # the per-object iteration itself) can run for a while. A tighter
        # interval than ProgressThrottle's own shared default (which is
        # tuned for a very different, much longer-running, much-larger-scale
        # operation — see its own docstring) trades a small amount of extra
        # sleep overhead for a search tool that's actually supposed to feel
        # interactive.
        self._throttle = ProgressThrottle(interval=0.05)

    def _build_search_patterns(self):
        """Builds the search patterns — see build_text_patterns() / RegexSearch."""
        if self.use_regex:
            return [(RegexSearch(self.search_text, self.case_sensitive, self.whole_word), RegexSearch.encoding)]
        return build_text_patterns(self.search_text, self.case_sensitive, self.whole_word)

    def _pump(self, results=None, item_label: str = "") -> bool:
        """Call this on every iteration of any CPU-bound loop in this class —
        it's cheap (one time.monotonic() compare) when its internal throttle's
        gate is closed, so there's no need for callers to gate it with their
        own iteration-count modulo check. When the gate opens (see
        self._throttle's own interval, set in __init__): flushes any pending
        matches (if `results` given — see _maybe_flush), emits a progress
        update, then does a real, explicit sleep (ProgressThrottle.pause() —
        see its own docstring for why this, not just relying on CPython's
        automatic GIL switching, actually keeps the GUI thread responsive).
        Returns True the moment the gate opens AND Cancel/Esc has been
        requested, so callers can bail out immediately instead of only
        checking between whole objects/files — see MAX_MATCHES_PER_ITEM's own
        comment for why that granularity wasn't enough. Also throttles
        batch_found_signal's own emission FREQUENCY (not just its per-emit
        size) — profiled at ~4ms per emit() call even with zero receivers
        connected, so calling it every time BATCH_SIZE matches accumulate
        (which a dense query can do many times within a single millisecond)
        was itself a measurable cost, separate from the per-match work below.

        Real reported bug this progress emission fixes, confirmed via a real
        GIL-starvation instrumentation test (a QTimer measuring actual main-
        thread tick latency while the real search thread ran): general GUI
        responsiveness was mostly fine (median ~20ms ticks) — the "status
        frozen at 1/500000, 0% the whole run" symptom was a DIFFERENT bug —
        _run_search()'s own progress_signal only fires BETWEEN whole objects/
        files, and a single densely-matching item (capped at
        MAX_MATCHES_PER_ITEM matches, each one decoded/regex-processed) can
        legitimately take several real seconds on its own — confirmed
        directly: only 2 progress deliveries reached the GUI in an entire
        19-second run, because only 7 objects (each a slow, heavily-matching
        Shader) were ever fully completed. Emitting from HERE too — using
        matches-found-so-far against MAX_TOTAL_MATCHES as the (current,
        total) pair, since that is the one number that's always meaningfully
        moving regardless of which single item is currently slow — keeps the
        displayed progress advancing continuously even while stuck deep
        inside one pathological object/file."""
        if not self._throttle.should_report(0, 2):
            return False
        if results is not None:
            self._maybe_flush(results)
            count = len(results)
            suffix = f" ({item_label})" if item_label else ""
            self.progress_signal.emit(
                count, self.MAX_TOTAL_MATCHES,
                tr("Поиск: найдено совпадений {count}{suffix}", count=count, suffix=suffix),
            )
        self._throttle.pause()
        return self.isInterruptionRequested()

    @staticmethod
    def _u16_whole_word(data_bytes, start, end) -> bool:
        try:
            before = data_bytes[start - 2:start].decode('utf-16-le') if start >= 2 else ''
            after = data_bytes[end:end + 2].decode('utf-16-le') if len(data_bytes) >= end + 2 else ''
        except Exception:
            return True
        return not (before.isalnum() or after.isalnum())

    def find_matches_in_bytes(self, data_bytes, is_binary=False, obj_ref=None, source_name="Unknown", search_patterns=None, results=None):
        if not data_bytes or not search_patterns:
            return

        if results is None:
            results = []

        # Resolved ONCE per call, not once per match — obj_ref/is_binary are
        # the same for every match found in this one blob. Real reported bug,
        # confirmed by direct measurement against a real 4.2MB ComputeShader:
        # obj_ref.peek_name() alone costs ~1.5ms per call on that object (not
        # memoized — unlike get_row_name()/get_row_script_name() for the
        # MonoBehaviour branch, which the app's own row cache already
        # memoizes). Calling it from INSIDE the per-match loop below (the
        # original code) meant up to MAX_MATCHES_PER_ITEM matches × up to 5
        # search-pattern variants all separately re-resolving the exact same
        # object's own name — measured at 17.4 of an 18.9s search's total
        # wall time spent inside ONE find_matches_in_bytes() call for that
        # single object. This is also why _pump()'s own periodic yields
        # didn't help: they run BETWEEN Python-level loop iterations just
        # fine, but each individual peek_name() call is itself one native
        # call the interpreter can't interrupt mid-call — no amount of
        # yielding between iterations reduces how much real work each one
        # does. Resolving once here cuts that cost by up to
        # MAX_MATCHES_PER_ITEM-times-the-pattern-count for a single object.
        is_mono = (not is_binary and obj_ref and getattr(obj_ref.type, 'name', '') == "MonoBehaviour")
        type_name = getattr(obj_ref.type, 'name', 'Unknown') if (not is_binary and obj_ref) else None
        display_name = ""
        if not is_binary and obj_ref:
            if is_mono:
                # Resolved lazily, only for an object that actually
                # matched — see main_names_cache's own comment in
                # __init__ for why this used to be a severe,
                # unconditional, GUI-thread-blocking cost instead.
                row = self.main_names_cache.get((id(getattr(obj_ref, "assets_file", None)), obj_ref.path_id))
                if row is None:
                    row = self.main_names_cache.get((source_name, obj_ref.path_id))
                try:
                    display_name = (get_row_script_name(row) or get_row_name(row)) if row is not None else "Unknown"
                except Exception:
                    display_name = "Unknown"
            else:
                try:
                    display_name = obj_ref.peek_name() or "Unknown"
                except Exception:
                    display_name = "Unknown"

        for pattern, enc in search_patterns:
            if self._truncated or len(results) >= self.MAX_TOTAL_MATCHES:
                self._truncated = True
                break

            matched_positions = []
            matched_texts = []          # RegexSearch only: what each hit matched (a field search needs it)
            stopped = False

            # --- 1. FIND MATCHES ---
            # Both loops below bail out early once MAX_MATCHES_PER_ITEM is hit
            # (stop looking for MORE matches in this one item, not just stop
            # reporting them — for a short/common pattern in a large blob, the
            # scan itself is the expensive part) and pump (flush + yield +
            # check interruption) periodically rather than only between whole
            # objects/files — see MAX_MATCHES_PER_ITEM's own comment for the
            # real reported freeze this fixes, and _pump()'s own docstring for
            # the real reported sluggishness/stutter this fixes.
            if isinstance(pattern, RegexSearch):
                for match_pos, match_len, match_text in pattern.find(data_bytes):
                    matched_positions.append((match_pos, match_len))
                    matched_texts.append(match_text)
                    if len(matched_positions) >= self.MAX_MATCHES_PER_ITEM:
                        break
                    if self._pump(results, source_name):
                        stopped = True
                        break
            elif isinstance(pattern, re.Pattern):
                for match in pattern.finditer(data_bytes):
                    if self.whole_word and enc == "utf-16-le" and not self._u16_whole_word(
                            data_bytes, match.start(), match.end()):
                        continue
                    matched_positions.append((match.start(), len(match.group(0))))
                    if len(matched_positions) >= self.MAX_MATCHES_PER_ITEM:
                        logger.debug(
                            "Search: capped at %d matches for %s (pattern too common)",
                            self.MAX_MATCHES_PER_ITEM, source_name,
                        )
                        break
                    if self._pump(results, source_name):
                        stopped = True
                        break
            else:
                pos = data_bytes.find(pattern, 0)
                pattern_len = len(pattern)
                while pos != -1:
                    if self._pump(results, source_name):
                        stopped = True
                        break
                    is_word = True

                    # --- 2. WHOLE_WORD CHECK FOR UTF-16-LE BYTES ---
                    if self.whole_word and enc == "utf-16-le":
                        before_bytes = data_bytes[pos - 2:pos] if pos >= 2 else b''
                        after_bytes = data_bytes[pos + pattern_len:pos + pattern_len + 2]

                        try:
                            before_char = before_bytes.decode('utf-16-le') if len(before_bytes) == 2 else ''
                            after_char = after_bytes.decode('utf-16-le') if len(after_bytes) == 2 else ''
                            if before_char.isalnum() or after_char.isalnum():
                                is_word = False
                        except Exception:
                            pass

                    if is_word:
                        matched_positions.append((pos, pattern_len))
                        if len(matched_positions) >= self.MAX_MATCHES_PER_ITEM:
                            logger.debug(
                                "Search: capped at %d matches for %s (pattern too common)",
                                self.MAX_MATCHES_PER_ITEM, source_name,
                            )
                            break

                    pos = data_bytes.find(pattern, pos + 1)

            # --- 3. BUILD PREVIEW AND RESULTS ---
            for hit, (pos, match_len) in enumerate(matched_positions):
                # Real reported feedback: 40 bytes of leading context routinely
                # pushed the actual match well past what a table cell/narrow
                # column can show before Qt elides the rest — the match itself
                # was often not even visible in the truncated preview. 20 keeps
                # enough context to read (a preceding word/path fragment)
                # without burying the match itself.
                padding_before = 20
                padding_after = 60

                if enc == "utf-16-le":
                    # Adjust the offset to be even
                    start_pos = pos - padding_before
                    if start_pos < 0:
                        start_pos = 0
                    if start_pos % 2 != 0:
                        start_pos -= 1

                    # The slice's end ALSO has to be a multiple of 2 bytes from start_pos!
                    end_pos = pos + match_len + padding_after
                    if end_pos > len(data_bytes):
                        end_pos = len(data_bytes)
                    if (end_pos - start_pos) % 2 != 0:
                        end_pos += 1
                else:
                    start_pos = max(0, pos - padding_before)
                    end_pos = min(len(data_bytes), pos + match_len + padding_after)

                preview_chunk = data_bytes[start_pos:end_pos]

                # Decode with alignment \u2014 _PREVIEW_DISALLOWED_RE's own comment
                # explains why a single regex substitution, not a per-character
                # Python loop (the original code) or str.translate() with a
                # dict fallback (a first, still-measurably-slower attempt).
                try:
                    decoded_str = preview_chunk.decode(enc, errors='replace')
                    preview_str = _PREVIEW_DISALLOWED_RE.sub('.', decoded_str)
                except Exception:
                    clean_chunk = preview_chunk.replace(b'\x00', b'')
                    preview_str = "".join(chr(b) if 32 <= b < 127 else "." for b in clean_chunk)

                # Normalize repeated dots and whitespace \u2014 precompiled module-level
                # patterns instead of re.sub(r'...', ...), which re-hits re's
                # internal compiled-pattern cache on every single call (profiled:
                # 256,000 cache lookups for the same run above).
                preview_str = _PREVIEW_WHITESPACE_RE.sub(' ', preview_str)
                preview_str = _PREVIEW_REPEATED_DOTS_RE.sub('...', preview_str).strip()

                if not preview_str.replace('.', '').strip():
                    clean_chunk = preview_chunk.replace(b'\x00', b'')
                    preview_str = "".join(chr(b) if 32 <= b < 127 else "." for b in clean_chunk)

                # Build the result object — is_mono/type_name/display_name
                # were already resolved once above, outside this loop.
                if not is_binary and obj_ref:
                    match_data = {
                        "type": type_name,
                        "name": str(display_name),
                        "source": source_name,
                        "path_id": getattr(obj_ref, 'path_id', '—'),
                        "pos": pos,
                        "preview": f"[{enc.upper()}] {preview_str}",
                        "obj_ref": obj_ref,
                        "is_binary_file": False,
                        "is_monobehaviour": is_mono,
                        "raw_bytes": data_bytes,
                        "match_len": match_len
                    }
                else:
                    match_data = {
                        "type": tr("Двоичный файл"), 
                        "name": "—", 
                        "source": source_name,
                        "path_id": "—", 
                        "pos": pos, 
                        "preview": f"[{enc.upper()}] {preview_str}",
                        "obj_ref": None, 
                        "is_binary_file": True, 
                        "is_monobehaviour": False,
                        "raw_bytes": data_bytes,
                        "match_len": match_len
                    }
                if matched_texts:
                    match_data["match_text"] = matched_texts[hit]
                results.append(match_data)
                if self._pump(results, source_name):
                    stopped = True
                    break

            if stopped or (self._truncated or len(results) >= self.MAX_TOTAL_MATCHES):
                self._truncated = self._truncated or len(results) >= self.MAX_TOTAL_MATCHES
                break

    def _maybe_flush(self, results: list, force: bool = False) -> None:
        """Sends the matches accumulated since the last send to the GUI in
        BATCH_SIZE-sized chunks (see BATCH_SIZE) rather than one signal per
        match — and, just as importantly, rather than one single oversized
        signal when a burst of matches arrives between checks (see
        MAX_MATCHES_PER_ITEM's own comment for the real freeze this second
        part fixes). Tracks progress via self._last_emitted instead of a
        passed-in/returned local, since find_matches_in_bytes() now also
        calls this mid-item."""
        while len(results) - self._last_emitted >= self.BATCH_SIZE:
            end = self._last_emitted + self.BATCH_SIZE
            self.batch_found_signal.emit(results[self._last_emitted:end])
            self._last_emitted = end
        if force and len(results) > self._last_emitted:
            self.batch_found_signal.emit(results[self._last_emitted:])
            self._last_emitted = len(results)

    def run(self):
        """Thin exception boundary around _run_search() — every other QThread
        subclass in this app (loader_thread.DataLoaderThread, gui_workers.
        BackgroundWorker, task_queue._QueueWorkerThread, save_thread.py's three
        classes) wraps its whole run() this way specifically so an unexpected
        exception always still emits SOME terminal signal. Without it, an early
        return with nothing caught (previously possible here — nothing above the
        per-item try/excepts inside _run_search() guarded against, say, a
        MemoryError from list(self.env.objects) on a very large environment)
        would leave the search dialog stuck in "searching..." forever with no
        error shown and no way to tell it's dead short of closing the tool —
        the exact bug this project already found and fixed once for
        DataLoaderThread (see CLAUDE.md's fix #13)."""
        try:
            self._run_search()
        except Exception as e:
            # Some exception types (MemoryError, notably) have an empty str() —
            # fall back to the type name, matching every other worker in this
            # app's own handling of this.
            self.error_signal.emit(str(e) or type(e).__name__)

    def _run_search(self):
        results = []
        self._last_emitted = 0
        self._truncated = False
        search_patterns = self._build_search_patterns()

        # 1. Scan Unity objects
        if self.env and hasattr(self.env, 'objects') and self.env.objects:
            all_objects = list(self.env.objects)
            total_objs = len(all_objects)

            for idx, obj in enumerate(all_objects):
                if self.isInterruptionRequested():
                    self._maybe_flush(results, force=True)
                    self.cancelled_signal.emit()
                    return

                # See MAX_TOTAL_MATCHES's own comment — a single common query
                # across a large game can otherwise keep scanning (and
                # building results) indefinitely.
                if len(results) >= self.MAX_TOTAL_MATCHES:
                    self._truncated = True
                    break

                # self._throttle (shared with find_matches_in_bytes() — see
                # its own __init__ comment) throttles progress/pause by TIME,
                # not by object count — otherwise overhead grows linearly with
                # dataset size (a game can have tens of millions of objects —
                # see ProgressThrottle's own docstring). The
                # isInterruptionRequested() check above still runs on every
                # iteration regardless — that's just a flag read, not a
                # system call, and costs negligibly even over tens of
                # millions of iterations.
                if self._throttle.should_report(idx, total_objs):
                    self.progress_signal.emit(idx + 1, total_objs, tr("Сканирование объектов Unity: {value}/{total_objs}", value=idx + 1, total_objs=total_objs))
                    self._throttle.pause()

                if not self.search_all_unity and getattr(obj.type, 'name', '') != "MonoBehaviour":
                    continue

                try:
                    raw_bytes = obj.get_raw_data()
                    source_name = obj.assets_file.name if hasattr(obj, 'assets_file') and obj.assets_file else "Unknown"
                    self.find_matches_in_bytes(
                        raw_bytes,
                        is_binary=False,
                        obj_ref=obj,
                        source_name=source_name,
                        search_patterns=search_patterns,
                        results=results
                    )
                except PatternTooSlow:
                    raise
                except Exception as e:
                    # Deliberately non-fatal — one unreadable object shouldn't
                    # abort the whole search — but silent before this (bare
                    # `except: pass`) made "why didn't my search find X" or
                    # "why does this object never show up" undiagnosable.
                    logger.debug("Search skipped object %s: %s", getattr(obj, "path_id", "?"), e)

                self._maybe_flush(results)
        elif not self.search_binary:
            self.progress_signal.emit(0, 1, tr("Объекты для сканирования отсутствуют."))

        # 2. Scan binary files (.resS / streaming, etc.) — skipped entirely
        # once phase 1 already hit MAX_TOTAL_MATCHES, since further scanning
        # can't produce anything the GUI would ever get to show anyway.
        if (not self._truncated and self.search_binary and self.env and hasattr(self.env, 'files')
                and (self.env.files or getattr(self.env, 'unloaded_binary_files', None))):
            valid_files = []
            for filepath, stream_obj in self.env.files.items():
                filename = os.path.basename(filepath)
                if filename.endswith(".resS") or filename.endswith(".resource"):
                    continue
                if "EndianBinaryReader" in type(stream_obj).__name__ or hasattr(stream_obj, "bytes"):
                    valid_files.append((filename, stream_obj))
            # Executables/DLLs that a folder load deliberately did not open (see
            # core/loader.py NON_UNITY_BINARY_SUFFIXES) are still searchable: their
            # path is read from disk here, one file at a time, only for this search.
            for path in getattr(self.env, "unloaded_binary_files", None) or []:
                valid_files.append((os.path.basename(path), path))

            total_files = len(valid_files)
            for idx, (filename, stream_obj) in enumerate(valid_files):
                if self.isInterruptionRequested():
                    self._maybe_flush(results, force=True)
                    self.cancelled_signal.emit()
                    return

                if len(results) >= self.MAX_TOTAL_MATCHES:
                    self._truncated = True
                    break

                self.progress_signal.emit(idx + 1, total_files, tr("Сканирование бинарных файлов: {value}/{total_files}", value=idx + 1, total_files=total_files))
                try:
                    if isinstance(stream_obj, str):
                        with open(stream_obj, "rb") as fh:
                            file_bytes = fh.read()
                    elif hasattr(stream_obj, "bytes"):
                        file_bytes = stream_obj.bytes
                    elif hasattr(stream_obj, "read"):
                        old_pos = stream_obj.Position if hasattr(stream_obj, "Position") else 0
                        stream_obj.Position = 0
                        file_bytes = stream_obj.read(getattr(stream_obj, "Length", 50*1024*1024))
                        stream_obj.Position = old_pos
                    else:
                        continue

                    self.find_matches_in_bytes(
                        file_bytes,
                        is_binary=True,
                        source_name=filename,
                        search_patterns=search_patterns,
                        results=results
                    )
                except PatternTooSlow:
                    raise
                except Exception as e:
                    # Same reasoning as the object-scan loop above — one
                    # unreadable file shouldn't abort the whole search, but
                    # it shouldn't vanish without a trace either.
                    logger.debug("Search skipped binary file %s: %s", filename, e)

                self._maybe_flush(results)

        self._maybe_flush(results, force=True)
        self.finished_signal.emit(results, self._truncated)


class SearchResultsModel(QAbstractTableModel):
    def __init__(self, data_list=None):
        super().__init__()
        self.data_list = data_list if data_list is not None else []
        self.headers = [tr("Имя"), tr("Тип"), tr("Источник"), "PathID", tr("Позиция"), tr("Предпросмотр контента")]

    def rowCount(self, parent=QModelIndex()): return len(self.data_list)
    def columnCount(self, parent=QModelIndex()): return len(self.headers)
    
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.data_list)): return None
        item = self.data_list[index.row()]
        col = index.column()
        
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 0: return item["name"] if item["name"] else "—"
            if col == 1: return item["type"]
            if col == 2: return item["source"]
            if col == 3: return item["path_id"] if item["path_id"] else "—"
            if col == 4: return item["pos"]
            if col == 5: return item["preview"]
        # Preview strings routinely exceed the column's on-screen width — Qt
        # elides the cell text down to "..." rather than showing nothing, but
        # the full match context (already confirmed correct — see the log
        # export) is otherwise only reachable by opening the raw viewer. Same
        # elide-with-full-text-on-hover pattern this app already uses for long
        # path labels elsewhere (e.g. CabBrowserDialog).
        if role == Qt.ItemDataRole.ToolTipRole and col == 5:
            return item["preview"]
        return None
        
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def append_rows(self, items: list):
        """Batch insertion — one beginInsertRows/endInsertRows per batch of matches
        (see TextSearchThread.BATCH_SIZE), rather than per individual match."""
        if not items:
            return
        start = len(self.data_list)
        end = start + len(items) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self.data_list.extend(items)
        self.endInsertRows()

    def clear_all(self):
        self.beginResetModel()
        self.data_list.clear()
        self.endResetModel()

    _SORT_KEYS = ("name", "type", "source", "path_id", "pos", "preview")

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if not (0 <= column < len(self._SORT_KEYS)):
            return
        key_name = self._SORT_KEYS[column]
        reverse = order == Qt.SortOrder.DescendingOrder

        def sort_key(item):
            value = item.get(key_name)
            # PathID/Position are usually numbers, but for matches in binary files PathID
            # is "—" — group non-numeric values separately to get a
            # stable order instead of inconsistent pairwise lessThan() comparisons
            try:
                return (0, int(value))
            except (TypeError, ValueError):
                return (1, str(value))

        # beginResetModel/endResetModel instead of layoutChanged — see the detailed comment
        # on ObjectTableModel.sort() in main.py: layoutChanged without a built
        # changePersistentIndex mapping forces QSortFilterProxyModel down a
        # heavier path on top of the already-sorted list, which is what remained the
        # bottleneck with an active filter.
        self.beginResetModel()
        self.data_list.sort(key=sort_key, reverse=reverse)
        self.endResetModel()


class RawViewerDialog(QDialog):
    def __init__(self, parent, raw_bytes, target_offset, match_len=None):
        super().__init__(parent)
        self.raw_bytes = raw_bytes
        self.target_offset = target_offset
        self.match_len = match_len

        self.setWindowTitle(tr("Просмотр Raw данных"))
        self.resize(750, 500)
        self.setModal(True)
        
        self.last_search_text = ""
        self.found_matches_offsets = []
        self.current_match_index = -1
        self.matches_outside = 0

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        self.txt_edit = QTextEdit()
        self.txt_edit.setReadOnly(True)
        self.txt_edit.setCurrentFont(
            QFont("Consolas") if sys.platform.startswith("win") else QApplication.font()
        )
        self.txt_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        dump_text, self.offset_map = bytes_to_hex_dump_with_map(
            self.raw_bytes,
            target_offset=self.target_offset
        )
        self.txt_edit.setPlainText(dump_text)
        layout.addWidget(self.txt_edit)
        # A big object is shown only partly (bytes_to_hex_dump_with_map's window around the hit): the
        # search looks only inside the bytes that are on screen — a match elsewhere has no line to go to
        # (user report: the view jumped to the top for such matches).
        self.shown_start = min(self.offset_map) if self.offset_map else 0
        self.shown_end = max(self.offset_map) + 1 if self.offset_map else 0

        search_layout = QHBoxLayout()

        self.inner_search_input = QLineEdit()
        self.inner_search_input.setPlaceholderText(
            tr("напечатайте текст (Enter / Далее)...")
        )
        self.inner_search_input.returnPressed.connect(self.search_next_in_raw)

        btn_next = QPushButton(tr("Далее"))
        btn_next.clicked.connect(self.search_next_in_raw)

        self.lbl_search_status = QLabel("")
        self.lbl_search_status.setStyleSheet("color: palette(mid);")

        search_layout.addWidget(QLabel(tr("Поиск в raw:")))
        search_layout.addWidget(self.inner_search_input, 1)
        search_layout.addWidget(self.lbl_search_status)
        search_layout.addWidget(btn_next)

        layout.addLayout(search_layout)

        if self.raw_bytes:
            # IF an exact match_len was passed — use it!
            # If not — use 16 bytes (1 line), but NOT 40.
            if self.match_len and self.match_len > 0:
                highlight_len = self.match_len
            else:
                highlight_len = min(16, len(self.raw_bytes) - self.target_offset)

            QTimer.singleShot(
                0,
                lambda: (
                    self.scroll_to_offset(self.target_offset),
                    self.highlight_offset(self.target_offset, highlight_len)
                )
            ) 
    
    def highlight_offset(self, offset, byte_length):
        if not self.offset_map:
            return
        selections = []
        remaining = byte_length
        current = offset

        while remaining > 0:
            line = self.offset_map.get(current)
            if line is None:
                break

            block = self.txt_edit.document().findBlockByLineNumber(line)
            if not block.isValid():
                break

            text = block.text()

            # Find the '|' separator of the ASCII section
            pipe_idx = text.rfind("|")
            if pipe_idx == -1:
                break

            line_offset = current % 16
            chars = min(16 - line_offset, remaining)

            # --- 1. Highlight in the HEX section ---
            # Each byte pair in hex takes 3 characters (e.g. "FF ")
            # Offset from the start of the line: 8 characters (address) + 2 spaces = 10
            hex_start = 10 + (line_offset * 3)
            hex_len = chars * 3 - 1  # -1 to avoid including the trailing space

            cursor_hex = QTextCursor(block)
            cursor_hex.setPosition(block.position() + hex_start)
            cursor_hex.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                hex_len
            )

            sel_hex = QTextEdit.ExtraSelection()
            sel_hex.cursor = cursor_hex
            sel_hex.format.setBackground(Qt.GlobalColor.yellow)
            sel_hex.format.setForeground(Qt.GlobalColor.black)
            selections.append(sel_hex)

            # --- 2. Highlight in the ASCII section ---
            # Characters start right after '|', i.e. pipe_idx - 16
            ascii_start_col = pipe_idx - 16
            
            cursor_ascii = QTextCursor(block)
            cursor_ascii.setPosition(block.position() + ascii_start_col + line_offset)
            cursor_ascii.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                chars
            )

            sel_ascii = QTextEdit.ExtraSelection()
            sel_ascii.cursor = cursor_ascii
            sel_ascii.format.setBackground(Qt.GlobalColor.yellow)
            sel_ascii.format.setForeground(Qt.GlobalColor.black)
            selections.append(sel_ascii)

            current += chars
            remaining -= chars

        self.txt_edit.setExtraSelections(selections)

    def scroll_to_offset(self, offset):
        if not self.offset_map:
            return
        line = self.offset_map.get(offset, 0)

        block = self.txt_edit.document().findBlockByLineNumber(line)
        if not block.isValid():
            return

        cursor = QTextCursor(block)
        self.txt_edit.setTextCursor(cursor)

        QApplication.processEvents()

        self.txt_edit.verticalScrollBar().setValue(
            int(self.txt_edit.document().documentLayout().blockBoundingRect(block).top())
        )

    def search_next_in_raw(self):
        search_text = self.inner_search_input.text()
        if not search_text or not self.raw_bytes: 
            return

        if search_text != self.last_search_text:
            self.last_search_text = search_text
            self.found_matches_offsets = []
            self.current_match_index = -1

            is_pure_ascii = all(ord(c) < 128 for c in search_text)
            
            patterns = []
            patterns.append(search_text.encode('utf-8', errors='ignore'))
            if not is_pure_ascii:
                patterns.append(search_text.encode('utf-16-le', errors='ignore'))

            found = set()
            for pattern in patterns:
                if not pattern: continue
                # only matches lying wholly inside the shown part of the dump
                pos = self.raw_bytes.find(pattern, self.shown_start, self.shown_end)
                while pos != -1:
                    found.add((pos, len(pattern)))
                    pos = self.raw_bytes.find(pattern, pos + 1, self.shown_end)
            self.found_matches_offsets = sorted(found)
            self.matches_outside = 0
            if not found and (self.shown_start > 0 or self.shown_end < len(self.raw_bytes)):
                self.matches_outside = sum(self.raw_bytes.count(p) for p in patterns if p)

        if not self.found_matches_offsets:
            self.inner_search_input.setStyleSheet("background-color: #ffcccc; color: black;")
            self.lbl_search_status.setText(
                tr("Есть только за пределами показанной части") if self.matches_outside else tr("Не найдено"))
            return
        else:
            self.inner_search_input.setStyleSheet("")

        self.current_match_index += 1
        if self.current_match_index >= len(self.found_matches_offsets):
            self.current_match_index = 0
            
        target_offset, pattern_len = self.found_matches_offsets[self.current_match_index]
        self.lbl_search_status.setText(tr("{value} из {count}", value=self.current_match_index + 1, count=len(self.found_matches_offsets)))

        self.scroll_to_offset(target_offset)
        self.highlight_offset(target_offset, pattern_len)


class RegexToggleButton(QToolButton):
    """The «.*» button inside the search field, at its right edge. A real button placed over the field, not a
    QLineEdit action: an action is drawn as a 16 px icon with no checked state — the first version was barely
    visible (user report). Off: the text in the field's own text colour on a faint frame; on: white on the
    accent colour. The field keeps room for it (text margins)."""
    WIDTH = 30

    def __init__(self, line_edit: QLineEdit):
        super().__init__(line_edit)
        self._edit = line_edit
        self.setText(".*")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_colors()
        line_edit.setTextMargins(0, 0, self.WIDTH + 4, 0)
        line_edit.installEventFilter(self)
        self._place()

    def apply_colors(self) -> None:
        colors = theme.current_colors()
        accent = colors.highlight if colors else "#6c5ce7"
        on_text = colors.highlighted_text if colors else "white"
        off_text = colors.text if colors else "gray"
        frame = colors.border if colors else "#888888"
        self.setStyleSheet(f"""
            QToolButton {{ font-family: Consolas, monospace; font-size: 14px; font-weight: bold;
                           color: {off_text}; background: transparent; border: 1px solid {frame};
                           border-radius: 4px; padding: 0px; }}
            QToolButton:hover {{ border-color: {accent}; }}
            QToolButton:checked {{ color: {on_text}; background: {accent}; border-color: {accent}; }}
            QToolButton:disabled {{ color: {frame}; }}
        """)

    def _place(self) -> None:
        rect = self._edit.rect()
        height = max(16, rect.height() - 8)
        self.setFixedSize(self.WIDTH, height)
        self.move(rect.right() - self.WIDTH - 3, (rect.height() - height) // 2)

    def eventFilter(self, obj, event):
        if obj is self._edit and event.type() in (event.Type.Resize, event.Type.Show):
            self._place()
        return False


class TextSearchDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.search_thread = None
        self.results_list = []
        self._cancelling = False

        self.setWindowTitle(tr("Поиск текста в объектах"))
        self.resize(850, 450)
        self.setModal(False)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("Введите текст для поиска..."))
        # Regular expressions: a toggle INSIDE the field (user request 2026-10-19: no room for a fifth checkbox).
        self.btn_regex = RegexToggleButton(self.search_input)
        self.btn_regex.setToolTip(wrap_tooltip(
            tr("Использовать регулярные выражения. Например, \\d+ монет — найти число, после которого идёт слово "
               "«монет».")))
        try:
            self.btn_regex.setChecked(app_settings().value("text_search/regex", False, type=bool))
        except Exception:
            pass
        self.btn_regex.toggled.connect(self._on_regex_toggled)
        self.search_input.textChanged.connect(self._check_regex)
        
        self.chk_case = QCheckBox(tr("Учитывать регистр"))
        self.chk_whole = QCheckBox(tr("Целые слова"))
        self.chk_binary = QCheckBox(tr("Поиск в бинарниках"))
        self.chk_all_unity = QCheckBox(tr("Все типы Unity"))
        self._search_option_checkboxes = [self.chk_case, self.chk_whole, self.chk_binary, self.chk_all_unity]

        self.btn_find = QPushButton(tr("Найти"))
        self.btn_find.clicked.connect(self.start_search)

        self.btn_cancel_search = QPushButton(tr("Отмена"))
        self.btn_cancel_search.setEnabled(False)
        self.btn_cancel_search.clicked.connect(self.cancel_search)

        top_layout.addWidget(QLabel(tr("Текст:")))
        top_layout.addWidget(self.search_input, 1)
        top_layout.addWidget(self.chk_case)
        top_layout.addWidget(self.chk_whole)
        top_layout.addWidget(self.chk_binary)
        top_layout.addWidget(self.chk_all_unity)
        top_layout.addWidget(self.btn_find)
        top_layout.addWidget(self.btn_cancel_search)
        layout.addLayout(top_layout)
        
        self.results_view = QTableView()

        v_header = self.results_view.verticalHeader()
        v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        v_header.setDefaultSectionSize(22)

        h_header = self.results_view.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h_header.setDefaultSectionSize(120) 

        self.results_view.setStyleSheet("""
            QTableView::item { 
                padding: 2px 4px; 
            }
        """)
        
        self.results_model = SearchResultsModel(self.results_list)
        self.search_proxy = SearchFilterProxyModel()
        self.search_proxy.setSourceModel(self.results_model)
        
        self.results_view.setModel(self.search_proxy)
        self.results_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.results_view.setSortingEnabled(True)
        self.results_view.horizontalHeader().setStretchLastSection(True)
        self.results_view.doubleClicked.connect(self.open_raw_at_offset)
        self.results_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_view.customContextMenuRequested.connect(self.show_context_menu)

        self.results_view.setColumnWidth(0, 130)
        self.results_view.setColumnWidth(1, 110)
        self.results_view.setColumnWidth(2, 130)
        self.results_view.setColumnWidth(3, 70)
        self.results_view.setColumnWidth(4, 60)
        layout.addWidget(self.results_view)
        
        bottom_panel = QHBoxLayout()
        self.btn_save_log = QPushButton(tr("Сохранить лог в файл..."))
        self.btn_save_log.clicked.connect(self.save_results_to_log)
        bottom_panel.addWidget(self.btn_save_log)
        bottom_panel.addStretch(1)
        layout.addLayout(bottom_panel)
        
        self.status_bar = QStatusBar()
        # explicit reminder that the search (which can run over a huge loaded environment)
        # can be cancelled with Esc or the "Cancel" button — shown while the search is running
        self.esc_hint_label = QLabel(tr("Esc — отмена"))
        self.esc_hint_label.setStyleSheet("color: gray;")
        self.esc_hint_label.hide()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(150)
        self.progress_bar.hide()
        self.status_bar.addPermanentWidget(self.esc_hint_label)
        self.status_bar.addPermanentWidget(self.progress_bar)
        layout.addWidget(self.status_bar)

    def _on_regex_toggled(self, checked: bool) -> None:
        try:
            app_settings().setValue("text_search/regex", bool(checked))
        except Exception:
            pass
        self._check_regex()

    def _regex_problem(self) -> str:
        text = self.search_input.text()
        return regex_problem(text) if self.btn_regex.isChecked() and text else ""

    def _check_regex(self) -> None:
        """As the user types: a broken expression turns the field red and says where in the status line."""
        problem = self._regex_problem()
        self.search_input.setStyleSheet("QLineEdit { border: 1px solid #e05555; }" if problem else "")
        if problem:
            self.status_bar.showMessage(problem)
        elif getattr(self, "_showing_regex_problem", False):
            self.status_bar.clearMessage()
        self._showing_regex_problem = bool(problem)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (event.Type.PaletteChange, event.Type.StyleChange) and hasattr(self, "btn_regex"):
            self.btn_regex.apply_colors()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            # In this (non-modal) window, Esc is EXCLUSIVELY responsible for cancelling the search —
            # never fall through to QDialog's default "Esc = close the
            # window" behavior. It used to fall through: a noticeable amount of time passes between
            # requestInterruption() and the background thread actually stopping (the thread checks
            # for interruption no more often than once per object/file), and a repeated/late Esc
            # that caught search_thread already not isRunning() would fall through to closing the dialog —
            # that was the cause of "the search window closes".
            self.cancel_search()
            event.accept()
            return
        super().keyPressEvent(event)

    def cancel_search(self):
        if self.search_thread is not None and self.search_thread.isRunning():
            self._cancelling = True
            self.search_thread.requestInterruption()
            # Clear the table right away, without waiting for the thread to actually stop (which
            # can take a couple of seconds on a large object/file) — this way cancellation looks
            # instant instead of "hung". Any matches the thread still manages to
            # send afterward (the last forced flush) are discarded in
            # on_batch_found, so the table doesn't "come back to life" on its own.
            self.results_model.clear_all()
            self.status_bar.showMessage(tr("Отмена поиска..."))
            self.btn_cancel_search.setEnabled(False)

    def start_search(self):
        text = self.search_input.text()
        if not text: return
        problem = self._regex_problem()
        if problem:
            self.status_bar.showMessage(problem)
            return
        self._last_search_text = text            # «Изучить поля скрипта» looks for it in the fields

        if self.search_thread is not None and self.search_thread.isRunning():
            self.status_bar.showMessage(tr("Поиск уже выполняется, дождитесь завершения."), 3000)
            return

        # Guard against starting without a loaded environment
        main_env = getattr(self.main_window, 'env', None)
        if not main_env:
            self.status_bar.showMessage(tr("Ошибка: файлы игры не загружены в главное окно!"), 4000)
            return

        self._cancelling = False
        self.btn_find.setEnabled(False)
        self.btn_cancel_search.setEnabled(True)
        # Changing a search-option checkbox mid-scan has no effect on the
        # already-running thread (its options were captured once, at
        # construction) — disabling them for the duration makes that
        # obvious instead of implying a live option a user could toggle.
        for chk in self._search_option_checkboxes:
            chk.setEnabled(False)
        self.btn_regex.setEnabled(False)
        self.results_model.clear_all()
        self.progress_bar.show()
        # Indeterminate for the whole search — same convention main.py's own
        # load progress bar already uses ("no reliable total yet"). A search
        # genuinely has no single meaningful "% done": object count and match
        # count are both real numbers but neither is the other, and mixing
        # them (tried first) made the bar jump between two different scales
        # every time the emitting side switched — see update_progress()'s own
        # comment for why the status TEXT, not this bar's numeric value, is
        # what actually carries progress information now.
        self.progress_bar.setRange(0, 0)
        self.esc_hint_label.show()

        self.results_view.setSortingEnabled(False)
        self.search_proxy.sort(-1)

        # Safe dict construction (the generator won't fail if raw_data_list is empty or None)
        main_list = getattr(self.main_window, 'raw_data_list', None) or []
        # A plain row INDEX, not a resolved-name cache — see
        # TextSearchThread.__init__'s own comment for the real reported bug
        # this fixes. This used to call get_row_script_name()/get_row_name()
        # (this project's own lazy/memoizing accessors, deliberately expensive
        # on first use) for EVERY row here, unconditionally, before the search
        # thread even started — profiled at 11.3s on a real 502,105-row
        # fixture, entirely on THIS (the GUI) thread, which is exactly why
        # clicking "Найти" used to take that long just to visibly react.
        # Building this index is just storing existing dict references — no
        # per-row resolution, no measurable cost regardless of table size.
        names_cache = {}
        for item in main_list:
            if isinstance(item, dict) and "source" in item and "path_id" in item:
                names_cache[(item["source"], item["path_id"])] = item  # fallback: name + PathID
                # With several games loaded the same name + PathID exists more than once; the
                # file object itself tells them apart (see the lookup in find_matches_in_bytes).
                af = getattr(item.get("obj_ref"), "assets_file", None)
                if af is not None:
                    names_cache[(id(af), item["path_id"])] = item

        self.search_thread = TextSearchThread(
            main_env,
            text,
            self.chk_case.isChecked(),
            self.chk_whole.isChecked(),
            self.chk_binary.isChecked(),
            self.chk_all_unity.isChecked(),
            main_names_cache=names_cache,
            parent=self,
            use_regex=self.btn_regex.isChecked(),
        )
        self.search_thread.progress_signal.connect(self.update_progress)
        self.search_thread.batch_found_signal.connect(self.on_batch_found)
        self.search_thread.finished_signal.connect(self.on_search_finished)
        self.search_thread.cancelled_signal.connect(self.on_search_cancelled)
        self.search_thread.error_signal.connect(self.on_search_error)
        self.search_thread.start()

    def update_progress(self, current, total, status):
        # current/total are no longer applied to progress_bar's numeric value
        # — see start_search()'s own comment on setRange(0, 0). TextSearchThread
        # emits this signal from two different places with two genuinely
        # different (current, total) SCALES (object index/total objects
        # between whole objects, vs. matches-found/MAX_TOTAL_MATCHES from
        # inside a single slow object — see TextSearchThread._pump()'s own
        # comment for why both exist), and feeding both into one determinate
        # bar made it visibly jump between two unrelated percentages. `status`
        # already carries whichever of the two is relevant at each callback.
        #
        # Real reported bug, root-caused via a stack-sampling watchdog (a
        # plain threading.Thread snapshotting sys._current_frames() every
        # 50ms throughout a real search): this method used to also call
        # QApplication.processEvents() here, reentrancy-guarded against the
        # stack-overflow crash that caused (see git history) — but the guard
        # only stops a NESTED call to processEvents() from firing a SECOND
        # processEvents(); it does nothing to stop the OUTER call from
        # itself dispatching an ever-growing backlog of queued signals
        # (progress_signal AND batch_found_signal both fire frequently
        # during a dense search) in one long, uninterruptible go. Measured
        # directly: 304/333 samples (91%) of an 18.7s "a" + all types +
        # binary search had the main thread's own top frame pinned at that
        # processEvents() call, including one unbroken stretch of 113
        # consecutive samples (~5.6s) — this IS the reported "freezes for a
        # second, unfreezes for a second" rhythm: a backlog builds while the
        # search thread has the GIL, then one processEvents() call drains
        # the whole thing at once (visible as a freeze), then the cycle
        # repeats. Removing the call entirely fixed it: re-measured at
        # 321/331 samples (97%) genuinely idle in the app's own event loop
        # instead, longest unbroken stretch 315/331 samples. Qt's own event
        # loop (app.exec(), already running the whole time) already
        # dispatches Cancel/Esc and every other queued event on its own —
        # nothing here was ever needed to make that happen, and forcing it
        # from inside a slot that loop itself just invoked is what caused
        # the pathology.
        self.status_bar.showMessage(status)

    def on_batch_found(self, batch):
        if self._cancelling:
            # The thread's final forced flush, arriving after
            # cancel_search() has already optimistically cleared the table — discard it so
            # the table doesn't "come back to life" on its own after cancellation
            return
        self.results_model.append_rows(batch)

    def _reset_search_ui(self):
        self.progress_bar.hide()
        self.esc_hint_label.hide()
        self.btn_find.setEnabled(True)
        self.btn_cancel_search.setEnabled(False)
        for chk in self._search_option_checkboxes:
            chk.setEnabled(True)
        self.btn_regex.setEnabled(True)
        self.results_view.setSortingEnabled(True)

    def on_search_finished(self, results, truncated=False):
        self._cancelling = False
        self._reset_search_ui()
        if truncated:
            self.status_bar.showMessage(
                tr("Поиск остановлен: достигнут предел в {max_total_matches} совпадений. Показаны первые {count} — "
                   "уточните запрос, чтобы увидеть остальное.", max_total_matches=TextSearchThread.MAX_TOTAL_MATCHES, count=len(results))
            )
        else:
            self.status_bar.showMessage(tr("Поиск завершен. Найдено: {count}", count=len(results)))

    def on_search_cancelled(self):
        self._cancelling = False
        self._reset_search_ui()
        self.status_bar.showMessage(tr("Поиск отменён пользователем, таблица очищена."))

    def on_search_error(self, message: str):
        self._cancelling = False
        self._reset_search_ui()
        self.status_bar.showMessage(tr("Ошибка поиска: {message}", message=message), 8000)
        if hasattr(self.main_window, "log"):
            self.main_window.log(tr("Ошибка поиска по тексту: {message}", message=message), LogLevel.ERROR)

    def open_raw_at_offset(self, index):
        if not index.isValid(): return
        source_index = self.search_proxy.mapToSource(index)
        if source_index.row() >= len(self.results_model.data_list): return
        item_data = self.results_model.data_list[source_index.row()]
        viewer = RawViewerDialog(self, item_data.get("raw_bytes", b""), item_data.get("pos", 0), item_data.get("match_len"))
        exec_and_dispose(viewer)

    def _selected_monobehaviours(self, clicked) -> list:
        """The MonoBehaviours of the selected rows, each once (one object can have several hits), when the clicked
        row is one of them; else []."""
        model = self.results_view.selectionModel()
        rows = [i.row() for i in model.selectedRows()] if model is not None else []
        if clicked.row() not in rows:
            return []
        objs, seen = [], set()
        for row in sorted(rows):
            source_row = self.search_proxy.mapToSource(self.search_proxy.index(row, 0)).row()
            if not 0 <= source_row < len(self.results_model.data_list):
                continue
            data = self.results_model.data_list[source_row]
            obj = data.get("obj_ref")
            if data.get("is_monobehaviour") and obj is not None and id(obj) not in seen:
                seen.add(id(obj))
                objs.append(obj)
        return objs

    def show_context_menu(self, pos):
        index = self.results_view.indexAt(pos)
        if not index.isValid(): return
        source_index = self.search_proxy.mapToSource(index)
        if source_index.row() >= len(self.results_model.data_list): return
        item_data = self.results_model.data_list[source_index.row()]
        
        menu = QMenu()
        act_show_raw = QAction(get_action_icon("view"), tr("Показать полностью (Raw)"), self)
        act_show_raw.triggered.connect(lambda: self.open_raw_at_offset(index))
        menu.addAction(act_show_raw)

        if not item_data.get("is_binary_file", True):
            # open_json_editor_dialog/dump_single_object/dump_by_script_type live
            # on MainWindow.object_actions (see object_actions.py) rather than
            # directly on MainWindow itself.
            object_actions = getattr(self.main_window, "object_actions", None)
            type_name = item_data.get("type")

            # Edit, then the exports (user request: right after the editing, a divider
            # after them), then go to / filter / offset / explorer.
            menu.addSeparator()
            if object_actions is not None:
                act_json_editor = QAction(get_action_icon("edit"), tr("Отредактировать данные"), self)
                act_json_editor.triggered.connect(lambda: object_actions.open_json_editor_dialog(item_data))
                menu.addAction(act_json_editor)

                act_dump_single = QAction(get_action_icon("export"), tr("Экспортировать Json дамп..."), self)
                act_dump_single.triggered.connect(lambda: object_actions.dump_single_object(item_data))
                menu.addAction(act_dump_single)

                if item_data.get("is_monobehaviour", False):
                    act_dump_script = QAction(get_action_icon("export"), tr("Экспортировать Json дампы по скрипту..."), self)
                    act_dump_script.triggered.connect(lambda: object_actions.dump_by_script_type(item_data))
                    menu.addAction(act_dump_script)
                menu.addSeparator()

            if item_data.get("is_monobehaviour", False) and hasattr(self.main_window, "open_field_table_tool"):
                # straight to this script's fields, the ones holding the found text ticked (user request)
                act_fields = QAction(get_action_icon("study_fields"), tr("Изучить поля скрипта..."), self)
                needle = item_data.get("match_text") or getattr(self, "_last_search_text", "")
                act_fields.triggered.connect(lambda: self.main_window.open_field_table_tool(
                    item_data.get("obj_ref"), needle))
                menu.addAction(act_fields)
                if hasattr(self.main_window, "add_to_field_table"):
                    # the same ticks without opening the window (user request: collect several hits first);
                    # every selected MonoBehaviour row when the clicked one is among them
                    objs = self._selected_monobehaviours(index) or [item_data.get("obj_ref")]
                    text = tr("Добавить в инспектор полей") + (f" ({len(objs)})" if len(objs) > 1 else "")
                    act_add = QAction(get_action_icon("study_fields"), text, self)
                    act_add.triggered.connect(lambda: self.status_bar.showMessage(self.main_window.add_to_field_table(
                        objs, needle), 8000))
                    menu.addAction(act_add)
                menu.addSeparator()

            if hasattr(self.main_window, 'jump_to_object_by_source_path_id'):
                act_goto = QAction(get_type_icon(type_name), tr("Перейти к объекту"), self)
                act_goto.triggered.connect(
                    lambda: self.main_window.jump_to_object_by_source_path_id(
                        item_data["source"], item_data["path_id"], obj=item_data.get("obj_ref")
                    )
                )
                menu.addAction(act_goto)

            if hasattr(self.main_window, 'filter_to_type_or_script'):
                act_isolate = QAction(get_type_icon(type_name), tr("Отобразить объекты этого типа"), self)
                # For MonoBehaviour - the script name, for everything else - the type name: TextAsset, Texture2D...
                is_mb = item_data.get("is_monobehaviour", False)
                target_name = item_data["name"] if is_mb else item_data["type"]
                act_isolate.triggered.connect(
                    lambda: self.main_window.filter_to_type_or_script(target_name, is_mb)
                )
                menu.addAction(act_isolate)

            self._add_offset_and_explorer_actions(menu, item_data)

        else:
            menu.addSeparator()     # user request: a divider after «Показать полностью»
            self._add_offset_and_explorer_actions(menu, item_data)

        menu.exec(QCursor.pos())

    def _add_offset_and_explorer_actions(self, menu, item_data: dict) -> None:
        """«Копировать смещение» / «Показать файл в проводнике» — placed right after
        the go-to/filter group (or directly under «Показать полностью» for a
        whole-file hit, which has no such group)."""
        act_copy_offset = QAction(get_action_icon("copy"), tr("Копировать смещение"), self)
        act_copy_offset.triggered.connect(lambda: QApplication.clipboard().setText(str(item_data.get("pos", ""))))
        menu.addAction(act_copy_offset)
        if getattr(self.main_window, "object_actions", None) is not None:
            act_explorer = QAction(get_action_icon("explorer"), tr("Показать файл в проводнике"), self)
            act_explorer.triggered.connect(lambda: self._show_result_file_in_explorer(item_data))
            menu.addAction(act_explorer)

    def _show_result_file_in_explorer(self, item_data: dict) -> None:
        """An object hit resolves its parent file the same way the main table's
        action does; a whole-file (binary) hit only carries the file's base name,
        looked up among the loaded files."""
        actions = self.main_window.object_actions
        if item_data.get("is_binary_file", True) or item_data.get("obj_ref") is None:
            path = actions.find_loaded_file_path(str(item_data.get("source", "")))
            if path:
                actions.reveal_path_in_explorer(path)
            else:
                self.main_window.log(tr("Не удалось определить путь к файлу результата."), LogLevel.WARNING)
        else:
            actions.show_in_explorer(item_data)

    def save_results_to_log(self):
        if not self.results_model.data_list:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Сохранить лог поиска"),
            "search_results_log.txt",
            tr("Текстовые файлы (*.txt)")
        )
        if not file_path:
            return

        try:
            data = self.results_model.data_list

            type_width = max(len("Type"), max(len(str(i.get("type", ""))) for i in data))
            name_width = max(len("Name"), max(len(str(i.get("name", ""))) for i in data))
            source_width = max(len("Source"), max(len(str(i.get("source", ""))) for i in data))
            pos_width = max(len("Pos"), max(len(str(i.get("pos", 0))) for i in data))

            header = (
                f"{'Type':<{type_width}}  "
                f"{'Name':<{name_width}}  "
                f"{'Source':<{source_width}}  "
                f"{'Pos':>{pos_width}}  "
                f"Preview"
            )
            divider = "─" * len(header)
            labels = (tr("Запрос:"), tr("Параметры:"), tr("Найдено:"), tr("Дата:"))
            label_width = max(len(l) for l in labels) + 1

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(tr("UStudio — лог поиска по тексту") + "\n")
                f.write(divider + "\n")
                f.write(f" {tr('Запрос:'):<{label_width}}{self.search_input.text()}\n")
                f.write(f" {tr('Найдено:'):<{label_width}}" + trn(len(data), "{n} совпадение", "{n} совпадения",
                                                                 "{n} совпадений") + "\n")
                f.write(f" {tr('Дата:'):<{label_width}}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(divider + "\n\n")

                f.write(header + "\n")
                f.write(divider + "\n")

                for item in data:
                    f.write(
                        f"{str(item.get('type', '')):<{type_width}}  "
                        f"{str(item.get('name', '')):<{name_width}}  "
                        f"{str(item.get('source', '')):<{source_width}}  "
                        f"{str(item.get('pos', 0)):>{pos_width}}  "
                        f"{item.get('preview', '')}\n"
                    )

            self.status_bar.showMessage(tr("Лог сохранен"), 3000)

        except Exception as e:
            self.status_bar.showMessage(tr("Ошибка: {error}", error=e), 3000)