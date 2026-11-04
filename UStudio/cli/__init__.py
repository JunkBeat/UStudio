"""Console-mode front end for UStudio, built entirely on core/ (see core/__init__.py's
own docstring — this package is the "future console-mode front end" it refers to).
Never imports PyQt6, config.CONFIG, or anything else GUI-only; it talks to core/
exactly the way loader_thread.py's Qt adapter does, just printing to the terminal
and reading stdin instead of emitting signals / popping dialogs."""
