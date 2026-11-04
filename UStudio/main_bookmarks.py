"""Bookmarks («Закладки») in the main window: the store (core.bookmarks, kept in the app settings), the star on
bookmarked rows, «Добавить в закладки» / «Убрать из закладок» (table menu, Ctrl+D) and the
«Закладки» entry of the quick filters bar's type list (proxy.set_bookmark_filter).

Kept out of main.py as a mixin (MainWindow inherits it), like main_environment.py."""
from core.i18n import tr
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtCore import Qt

from app_settings import app_settings
from core.bookmarks import BookmarkStore
from type_icons import get_bookmark_icon

BOOKMARK_SHORTCUT = "Ctrl+D"
_SETTINGS_KEY = "bookmarks"


class BookmarksMixin:
    def _init_bookmarks(self) -> None:
        """Called once the table, proxy and quick filters bar exist."""
        self.bookmarks = BookmarkStore(load=lambda: app_settings().value(_SETTINGS_KEY, "") or "",
                                       save=lambda value: app_settings().setValue(_SETTINGS_KEY, value))
        self.quick_filters_bar.bookmark_matcher_provider = self.bookmarks.matcher
        act = QAction(self.table_view)
        act.setShortcut(QKeySequence(BOOKMARK_SHORTCUT))
        act.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        act.triggered.connect(self._toggle_bookmarks_of_selection)
        self.table_view.addAction(act)
        self._bookmark_shortcut_action = act

    def _bookmarks_attach(self, env) -> None:
        self.bookmarks.set_env(env)
        self.table_model.bookmark_matcher = self.bookmarks.matcher()

    def _bookmarks_detach(self) -> None:
        bookmarks = getattr(self, "bookmarks", None)
        if bookmarks is not None:
            bookmarks.set_env(None)                 # it held the game's Environment
        if hasattr(self, "table_model"):
            self.table_model.bookmark_matcher = None

    # --- changes ---

    def bookmark_action(self, items: list, parent) -> QAction:
        """«Добавить в закладки» / «Убрать из закладок» for `items` (all bookmarked -> remove), for a menu."""
        all_marked = bool(items) and all(self.bookmarks.is_bookmarked(i) for i in items)
        text = tr("Убрать из закладок") if all_marked else tr("Добавить в закладки")
        act = QAction(get_bookmark_icon(), f"{text}\t{BOOKMARK_SHORTCUT}", parent)   # \t: shortcut-style hint
        act.setEnabled(any(self.bookmarks.key_of(i) is not None for i in items))
        act.triggered.connect(lambda: self.toggle_bookmarks(items))
        return act

    def toggle_bookmarks(self, items: list) -> None:
        if not items:
            return
        if all(self.bookmarks.is_bookmarked(i) for i in items):
            changed = self.bookmarks.remove(items)
            message = tr("Убрано из закладок: {count}", count=changed)
        else:
            changed = self.bookmarks.add(items)
            message = tr("Добавлено в закладки: {count}", count=changed)
        if not changed:
            return
        self._after_bookmarks_changed()
        self.status_label.setText(message)

    def _after_bookmarks_changed(self) -> None:
        matcher = self.bookmarks.matcher()
        self.table_model.bookmark_matcher = matcher
        if self.proxy_model.bookmark_matcher is not None:
            self.proxy_model.set_bookmark_filter(matcher)    # the filtered view follows (a removed one leaves it)
        self.table_view.viewport().update()                 # the stars (the icon is asked for on repaint)

    def _toggle_bookmarks_of_selection(self) -> None:
        if not self.table_view.isEnabled():
            return
        if self.table_view.select_all_active:
            items = self.proxy_model.get_visible_items()
        else:
            items = [self.table_model.data_list[self.proxy_model.mapToSource(i).row()]
                     for i in self.table_view.selectionModel().selectedRows()]
        self.toggle_bookmarks(items)
