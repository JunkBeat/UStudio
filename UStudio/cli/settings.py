"""Plain-JSON persisted defaults for the CLI, filling the same role config.py's
QSettings-backed CONFIG plays for the GUI — without importing PyQt6 (the GUI's store is
app_settings.py; core/quick_filters.py imports it only inside its load/save functions).

Stored at %LOCALAPPDATA%\\UStudio\\cli_settings.json — same base folder main.py
already uses for its own crash log, just a different file."""

import json
import os
from pathlib import Path
from typing import Any, Dict

_DEFAULTS: Dict[str, Any] = {
    "fallback_version": "",
    "unity_cn_key": "",
    "object_count_threshold": 2_000_000,
    "cab_collision_policy": "keep_first",
    "excluded_folders": [],
    "texture_import_quality": "high",
    "texture_import_format_mode": "match_original",
    "texture_import_manual_format": "BC7",
    "audio_import_quality": 80,
    "resource_target_mode": "original",
    "resource_name": "res_new",
    "video_transcode_target": "original",
    "video_transcode_quality": 70,
    "export_grouping": "none",
}


def _settings_path() -> Path:
    # USTUDIO_CLI_SETTINGS_PATH: test-only escape hatch (tests/test_cli.py's
    # config get/set tests point this at a scratch file) so an automated test
    # run never mutates the user's own real settings — nothing in normal CLI
    # use ever sets this env var, so ordinary behavior is unaffected.
    override = os.environ.get("USTUDIO_CLI_SETTINGS_PATH")
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA", "")) or Path.home()
    return base / "UStudio" / "cli_settings.json"


def load_settings() -> Dict[str, Any]:
    """Returns a dict with every key in _DEFAULTS present — missing/corrupt file
    silently falls back to defaults rather than erroring, since the CLI must
    still work on a first run with nothing persisted yet."""
    path = _settings_path()
    data: Dict[str, Any] = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    merged = dict(_DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in _DEFAULTS})
    return merged


def save_settings(values: Dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = load_settings()
    merged.update({k: v for k, v in values.items() if k in _DEFAULTS})
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")


def set_one(key: str, value: Any) -> None:
    if key not in _DEFAULTS:
        raise KeyError(f"unknown setting: {key!r} (known: {', '.join(sorted(_DEFAULTS))})")
    save_settings({key: value})
