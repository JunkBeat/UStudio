"""PyQt-free business logic shared by the GUI app and (in the future) a console-mode
front end. Nothing under this package may import PyQt6 or config.CONFIG — see
core/progress.py for the callback seam that replaces Qt signals here."""
