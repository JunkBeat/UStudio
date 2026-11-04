"""The one place the GUI opens its persistent settings.

Every module calls app_settings() instead of building `QSettings("UStudio", "UStudio")` itself. On Windows
that native form is the REGISTRY (`HKCU\\Software\\UStudio\\UStudio`) whatever
`QSettings.setDefaultFormat()` says, so a test that touched a widget which built its own QSettings wrote
into the user's real settings (2026-10-13: the user's saved font-preview text was overwritten). With one
factory there is one switch:

  * USTUDIO_SETTINGS_FILE=<path.ini> in the environment -> every caller reads and writes that ini file
    instead (read on each call, so setting it after import works too). tests/conftest.py sets it for a
    pytest run, standalone test scripts call use_ini_file(); a test launch of a built exe can use it the
    same way USTUDIO_LOG_DIR keeps the launch out of the user's crash.log.

tests/test_app_settings.py scans the sources so a new `QSettings(...)` outside this module fails a test.
"""

import os

from PyQt6.QtCore import QSettings

_ORGANIZATION = "UStudio"
_APPLICATION = "UStudio"
SETTINGS_FILE_ENV = "USTUDIO_SETTINGS_FILE"


def app_settings() -> QSettings:
    """A QSettings on the app's settings store (the registry, or the ini file named by USTUDIO_SETTINGS_FILE)."""
    ini_path = os.environ.get(SETTINGS_FILE_ENV)
    if ini_path:
        return QSettings(ini_path, QSettings.Format.IniFormat)
    return QSettings(_ORGANIZATION, _APPLICATION)


def use_ini_file(path) -> None:
    """Sends every later app_settings() call to the ini file at `path` (tests: call before building widgets)."""
    os.environ[SETTINGS_FILE_ENV] = str(path)
