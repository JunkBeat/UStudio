"""argparse wiring. Short flags are allocated per-subparser (argparse doesn't
require them to be globally unique — only unique within one subcommand's own
flag set), so the same letter can mean different things in different verbs
without ambiguity, e.g. -m is --modified on `list` but --mode on `export`.

Two parser builders:
- build_cli_parser(): sys.argv-facing. `list`/`inspect`/`export` additionally
  accept the load-arg group so a one-shot invocation can load-then-act in one
  command (see main.py's dispatch: it calls cmd_load first only when --folder/
  --files was actually given).
- build_repl_parser(): used inside `shell` — `list`/`inspect`/`export` only
  get their own action flags, never the load-arg group, since the REPL always
  operates on the already-loaded session (that's the entire point of it)."""

import argparse
import shlex
import sys
from typing import List, Optional


# Used when the caller names no folder (export target; import's SAVE target): relative to the current directory, the
# same place a *_Data folder is auto-detected from (cli/game_folder.py).
DEFAULT_EXPORT_DIR = "UStudio_Assets"
DEFAULT_PACKED_DIR = "UStudio_Packed"  # where a one-shot import saves when no -A/--in-place is given
_OUT_HELP = f"(default: ./{DEFAULT_EXPORT_DIR})"


def _add_load_args(sp: argparse.ArgumentParser) -> None:
    group = sp.add_mutually_exclusive_group()
    group.add_argument("-p", "--folder", help="load a whole folder")
    # action="append" (one file per -F, repeatable), NOT nargs="+": nargs="+" is
    # greedy and silently swallows a following positional argument too (found
    # via a real test: `inspect -F a.file 1` fed "1" into --files instead of
    # to the `ref` positional, then failed with a confusing "ref is required"
    # error) — append has no such ambiguity regardless of argument order.
    group.add_argument("-F", "--files", action="append",
                        help="load a specific file (repeatable for multiple files)")
    sp.add_argument("-T", "--threshold", type=int, default=2_000_000,
                     help="object-count threshold above which loading asks for confirmation (default: 2,000,000)")
    sp.add_argument("-L", "--large", dest="on_large_file", choices=["continue"],
                     help="agree to continue when the data exceeds the threshold (required in one-shot "
                          "mode if it does). Only the indexed types are loaded unless --all is given")
    sp.add_argument("-c", "--collision", dest="cab_collision", choices=["keep_first", "raise"], default="keep_first",
                     help="same-named files are all loaded; this only decides the lookup by name alone: "
                          "keep_first (default) or raise (stop at the first collision)")
    sp.add_argument("-x", "--exclude", dest="exclude_folder", action="append",
                     help="folder to skip during a folder load (repeatable)")
    sp.add_argument("--assembly", metavar="FOLDER",
                     help="the game's Managed folder (script DLLs), for MonoBehaviour field names/types. "
                          "Auto-detected next to a *_Data folder; set this when the data was moved/copied "
                          "elsewhere, or -F loaded a single file with no *_Data folder nearby")
    sp.add_argument("-u", "--fallback-version", help="Unity version to assume when a file has none of its own")
    sp.add_argument("-k", "--cn-key", help="known 16-byte AssetBundle decrypt key")
    sp.add_argument("-a", "--all", dest="all_assets", action="store_true",
                     help="index every object type, not just the curated preview-worthy set")
    sp.add_argument("--deps", action="append", metavar="FOLDER",
                     help="also look for files the loaded data depends on (e.g. scripts stored in other bundles) "
                          "in this folder, scanned once before loading (repeatable). Needed when a single "
                          "bundle is loaded with -F and its scripts live in neighboring bundles; a -p folder "
                          "load already searches its own folder")
    sp.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")


def _add_filter_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("-t", "--type", help="comma-separated type name(s) to match")
    sp.add_argument("-s", "--script", dest="script_type",
                     help="MonoBehaviour script class name to match (matches every script with that bare "
                          "name; pass \"Namespace.ClassName\" to narrow to one if the game has more than one "
                          "script with the same bare name)")
    sp.add_argument("-n", "--name-contains", help="case-insensitive substring match on resolved name")
    sp.add_argument("-S", "--source", help="exact source file/entry name to match")


def _add_import_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("patches", metavar="PATCHES", help="folder of exported/edited files to match and apply; an sdf_map.txt in it also generates SDF fonts (see the README)")
    sp.add_argument("-d", "--dry-run", action="store_true", help="show what would be matched/applied, change nothing")
    sp.add_argument("--strict", action="store_true",
                     help="all or nothing (for scripts and installers): if any patch fails to apply, matches no "
                          "object, is skipped for a name/script mismatch, or an sdf_map target resolves to nothing, "
                          "exit non-zero and apply and save nothing. Without it the patches that can be applied "
                          "are applied and saved, every problem is reported, and the exit code is 1 if a patch "
                          "failed to apply")
    sp.add_argument("--force", action="store_true",
                     help="also apply patches whose name/script no longer matches the object at their "
                          "source + PathID (skipped by default, like the GUI's unchecked rows)")
    sp.add_argument("--tex-mode", dest="texture_format_mode", choices=["match_original", "manual"],
                     help="default: whatever `config get texture_import_format_mode` says")
    sp.add_argument("--tex-format", dest="texture_format", help="manual target format (only used with --tex-mode manual)")
    # No effect since 2026-10-20 (every encoder runs at its one measured setting); still accepted
    # so existing scripts and installers that pass it keep working.
    sp.add_argument("--tex-quality", dest="texture_quality", choices=["medium", "high"],
                     help="no effect: textures are always compressed at the best quality (kept for old scripts)")
    sp.add_argument("--audio-quality", type=int, help="FSBank quality 0-100 (0 = normal/average, 100 = best)")
    sp.add_argument("--res-mode", dest="resource_target_mode", choices=["original", "custom_resource"],
                     help="where AudioClip/VideoClip patches write their backing resource data "
                          "(raw or converted — both write through the same mechanism) — "
                          "default: whatever `config get resource_target_mode` says")
    sp.add_argument("--res-name", dest="resource_name",
                     help="custom resource file name (only used with --res-mode "
                          "custom_resource) — default: whatever `config get "
                          "resource_name` says")
    sp.add_argument("--transcode", dest="video_transcode", action="store_true",
                     help="re-encode matched VideoClip patches instead of packaging them as-is "
                          "(off by default, like the GUI's own checkbox — never silently enabled)")
    sp.add_argument("--transcode-to", dest="video_transcode_target", choices=["original", "h264", "vp8"],
                     help="\"original\" (the default) matches each clip's own current container "
                          "when possible, falling back to h264 with a warning otherwise — default: "
                          "whatever `config get video_transcode_target` says")
    sp.add_argument("--transcode-quality", dest="video_transcode_quality", type=int,
                     help="encoder quality 0-100 — default: whatever `config get "
                          "video_transcode_quality` says")
    # A one-shot process's edits only exist in its own memory — chaining a
    # save onto THIS invocation is the only way a one-shot `import` actually
    # persists anything (see cmd_import's own warning when neither is given).
    # Pointless-but-harmless in `shell` mode, where a separate `save` command
    # afterward works just as well since the session survives.
    sp.add_argument("-A", "--save-as", help=f"also save to this NEW folder immediately after applying (one-shot import default: ./{DEFAULT_PACKED_DIR})")
    sp.add_argument("--in-place", action="store_true", help="also overwrite the original files immediately after applying")
    _add_backup_args(sp)
    # NOT adding -q/--quiet here: _add_load_args() (also applied to this
    # subparser in one-shot mode) already defines it, and argparse raises
    # ArgumentError on a genuinely duplicate flag within one subparser
    # (confirmed by hitting exactly that on the real test below) — the REPL's
    # own `import` subparser has no _add_load_args, so it has no --quiet at
    # all; cmd_import's getattr(args, "quiet", False) handles that gracefully.


def _add_backup_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("-b", "--backup", action="store_true",
                     help="before overwriting an original file, copy it to a new dated backup folder — "
                          "for `import` this also covers a resource file (.resource/.resS) the moment a "
                          "patch first writes to it, even in a one-shot run with no --in-place/--save-as")
    sp.add_argument("--backup-keep", type=int, default=1, metavar="N",
                     help="how many of the newest backups of each file to keep besides its first one "
                          "(the untouched original is always kept); older ones are deleted (default: 1)")
    sp.add_argument("--backup-dir", metavar="DIR",
                     help="where backups go (default: a UStudio folder in your local application data, "
                          "outside the game folder). Implies --backup")


def _add_save_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("-A", "--save-as", help="write to this NEW folder instead of overwriting the original files")
    sp.add_argument("-d", "--dry-run", action="store_true", help="show what would be written, change nothing")
    _add_backup_args(sp)
    # NOT -q/--quiet here — see the identical note in _add_import_args: one-shot
    # `save` also carries _add_load_args(), which already defines it.


def _add_cab_bundle_arg(sp: argparse.ArgumentParser) -> None:
    # One-shot convenience only — REPL's own `cab` subcommands never get this,
    # since `cab open` already set session.cab earlier in that session.
    sp.add_argument("-b", "--bundle", help="open this bundle first (one-shot convenience)")


def _add_cab_subparsers(sp_cab: argparse.ArgumentParser, one_shot: bool) -> None:
    cab_sub = sp_cab.add_subparsers(dest="cab_command", required=True)
    add_help = one_shot

    sp_open = cab_sub.add_parser("open", add_help=add_help)
    sp_open.add_argument("bundle", help="path to the bundle file")

    sp_list = cab_sub.add_parser("list", add_help=add_help)
    if one_shot:
        _add_cab_bundle_arg(sp_list)
    sp_list.add_argument("-f", "--format", choices=["table", "json"], default="table")
    sp_list.add_argument("-l", "--limit", type=int)

    sp_view = cab_sub.add_parser("view", add_help=add_help)
    if one_shot:
        _add_cab_bundle_arg(sp_view)
    sp_view.add_argument("-e", "--entry", required=True, help="internal entry name")

    sp_export = cab_sub.add_parser("export", add_help=add_help)
    if one_shot:
        _add_cab_bundle_arg(sp_export)
    sp_export.add_argument("-e", "--entry", help="a single entry name; omit to export ALL entries")
    sp_export.add_argument("-o", "--out", default=DEFAULT_EXPORT_DIR, help=_OUT_HELP)
    sp_export.add_argument("-q", "--quiet", action="store_true")

    sp_rebuild = cab_sub.add_parser("rebuild", add_help=add_help)
    if one_shot:
        _add_cab_bundle_arg(sp_rebuild)
    sp_rebuild.add_argument("-o", "--out", required=True, help="destination path for the rebuilt bundle")
    sp_rebuild.add_argument("--from-folder", help="match files in this folder against entry names by filename")
    sp_rebuild.add_argument("--set", action="append",
                             help="ENTRY=PATH, repeatable - explicit single-entry override, applied after --from-folder")
    sp_rebuild.add_argument("--mode", choices=["memory", "disk"], default="disk",
                             help="disk (default): minimal RAM, genuinely cancellable. "
                                  "memory: faster but can't be cancelled mid-way (see BundleFile.save()'s own docstring)")
    sp_rebuild.add_argument("--packer", choices=["none", "lz4", "lz4hc", "lzma", "original"], default="original")
    sp_rebuild.add_argument("-q", "--quiet", action="store_true")


def needs_load(args: argparse.Namespace) -> bool:
    """True when a one-shot list/inspect/export invocation supplied --folder/
    --files of its own (so it should load-then-act in one command) rather
    than expecting an already-loaded `shell` session."""
    return bool(getattr(args, "folder", None) or getattr(args, "files", None))


def build_cli_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ustudio_cli", description="UStudio console mode")
    p.add_argument("-v", "--verbose", action="store_true", help="show details: full tracebacks on error, and the SDF generator's notes")
    sub = p.add_subparsers(dest="command", required=True)

    sp_load = sub.add_parser("load", help="load a folder or files (for scripting: chain other verbs instead)")
    _add_load_args(sp_load)

    sp_shell = sub.add_parser("shell", help="load once, then run commands interactively")
    _add_load_args(sp_shell)

    sp_list = sub.add_parser("list", help="list objects matching filters")
    _add_load_args(sp_list)
    _add_filter_args(sp_list)
    sp_list.add_argument("-m", "--modified", action="store_true", help="only objects with unsaved edits")
    sp_list.add_argument("--sdf", action="store_true",
                          help="list detected SDF font packages (TMP_FontAsset + its material/atlas "
                               "texture/source font) grouped together, instead of the normal flat list. "
                               "Ignores -t/-s/-n/-S/-m/-r; -f/-l/-o still apply")
    sp_list.add_argument("-r", "--sort",
                          help="comma-separated column(s) to sort by, e.g. 'name' (A-Z) or '-size,name' "
                               "(size high-to-low, then name A-Z); prefix a column with '-' for Z-A/high-to-low. "
                               "IMPORTANT: if the value itself starts with '-', use '=' (--sort=-size or -r=-size), "
                               "not a space, or argparse reads it as another flag. "
                               "Columns: path_id, name, type, script_name, source, size, modified")
    sp_list.add_argument("-f", "--format", choices=["table", "json", "csv"], default="table")
    sp_list.add_argument("-l", "--limit", type=int, help="max rows to show")
    sp_list.add_argument("-o", "--out", help="write to this file instead of stdout")

    sp_inspect = sub.add_parser("inspect", help="dump one object (PATH_ID or SOURCE:PATH_ID)")
    _add_load_args(sp_inspect)
    sp_inspect.add_argument("ref", help="PATH_ID or SOURCE:PATH_ID")
    sp_inspect.add_argument("-S", "--source", help="disambiguates a PATH_ID that exists in more than one file")
    sp_inspect.add_argument("-d", "--dump", choices=["typed", "json", "hex"], default="typed")

    sp_export = sub.add_parser("export", help="export object(s) to a folder")
    _add_load_args(sp_export)
    _add_filter_args(sp_export)
    sp_export.add_argument("-i", "--id", help="export exactly one object (PATH_ID or SOURCE:PATH_ID)")
    sp_export.add_argument("-m", "--mode", choices=["typed", "raw", "content-raw", "json"], default="typed")
    sp_export.add_argument("-o", "--out", default=DEFAULT_EXPORT_DIR, help="destination folder " + _OUT_HELP)
    sp_export.add_argument("-w", "--overwrite", action="store_true", help="overwrite existing files")
    sp_export.add_argument("--strict", action="store_true", help="exit non-zero if any object fails to export")
    sp_export.add_argument("--group-by", choices=["none", "type", "source"],
                            help="put each exported object under a --out/<type>/ or --out/<source>/ subfolder "
                                 "instead of one flat folder — same three choices as the GUI's own Settings "
                                 "→ Export grouping option. Ignored with --sdf (that mode has its own "
                                 "fixed SDF/<font name>/ layout). Default: whatever `config get export_grouping` says")
    sp_export.add_argument("--sdf", action="store_true",
                            help="export TMP_FontAsset SDF font package(s) (MonoBehaviour/Material/Texture2D/"
                                 "converted Font) into SDF/<font name>/ under --out instead of exporting "
                                 "individual objects. Combine with -i/--id to export just that one font; "
                                 "omit -i to export every detected SDF font pack. -m/-t/-s/-n/-S are ignored")

    sp_import = sub.add_parser("import", help="apply a folder of patch files (and an optional sdf_map.txt) against loaded objects")
    _add_load_args(sp_import)
    _add_import_args(sp_import)
    # One-shot only, NOT in build_repl_parser()'s `import`: a shell session has
    # already loaded whole files, which is the point of the shell.
    sp_import.add_argument(
        "--partial", dest="partial_load", action="store_true",
        help="load only the files the patches name (found in the -p folder) instead of the whole folder; "
             "falls back to the full load, saying why, if any of them can't be pinned to exactly one file. "
             "Off by default")

    sp_save = sub.add_parser("save", help="persist modified objects to disk")
    _add_load_args(sp_save)
    _add_save_args(sp_save)

    sp_cab = sub.add_parser("cab", help="operate on a single bundle archive")
    _add_cab_subparsers(sp_cab, one_shot=True)

    sp_cache = sub.add_parser("cache", help="show or clear the cache of unpacked APK/OBB data")
    sp_cache.add_argument("--clear", action="store_true", help="delete every unpacked copy (they are re-created on demand)")

    sp_backup = sub.add_parser("backup", help="list backups made before overwriting, or restore from them")
    backup_sub = sp_backup.add_subparsers(dest="backup_command", required=True)
    sp_bl = backup_sub.add_parser("list", help="show every backup and how much room they take")
    sp_bl.add_argument("--backup-dir", metavar="DIR", help="backup folder (default: the standard location)")
    sp_bl.add_argument("--game", metavar="NAME",
                       help="only backups of this game (part of its name or folder, case-insensitive) — "
                            "run without --game first to see every backup's game name in the output")
    sp_br = backup_sub.add_parser(
        "restore", help="copy files back to where they came from (default: the untouched original of every file)")
    sp_br.add_argument("folder", nargs="?", metavar="BACKUP_FOLDER",
                       help="restore the files of this one backup instead of every file's oldest copy")
    sp_br.add_argument("-f", "--file", action="append", metavar="NAME",
                       help="only this file (name or full original path; repeatable)")
    sp_br.add_argument("--backup-dir", metavar="DIR", help="backup folder (default: the standard location)")
    sp_br.add_argument("-d", "--dry-run", action="store_true", help="show what would be restored, change nothing")
    sp_br.add_argument("--copy", metavar="DATE",
                       help="restore each file's newest copy made at this date/time (e.g. 2026-09-24 or "
                            "\"2026-09-24 19:32\") instead of the oldest one")
    sp_br.add_argument("--game", metavar="NAME",
                       help="only restore backups of this game (part of its name or folder, case-insensitive "
                            "— see `backup list`'s own output for the exact name) — narrows -f NAME before "
                            "it's matched, so a file name shared by two games' backups (refused otherwise, "
                            "ambiguous) can be told apart without a full path")
    sp_br.add_argument("--relocate", action="append", metavar="OLD=NEW",
                       help="the game folder was moved: restore into NEW instead of OLD (OLD as `backup list` "
                            "shows it; repeatable). Without it a file whose folder no longer exists is refused, "
                            "never restored into a re-created copy of the old path")
    # Per-object diff/restore (`backup diff`, `--object`) was removed: it added
    # real bug surface (three separate real bugs were found in the resource-
    # write/backup paths in the same review that led to this cut) for a case
    # (undo ONE change inside an already-edited file) that whole-file restore
    # already covers for the overwhelming majority of real "I made a mistake"
    # moments. Restoring an entire file always makes a safety copy first and
    # always keeps 1 prior copy besides the first — no longer a choice, since
    # a restore is itself the kind of destructive action that should default
    # to safe rather than expose a flag most scripts would never think to set.

    sp_config = sub.add_parser("config", help="get/set persisted CLI defaults")
    config_sub = sp_config.add_subparsers(dest="config_command", required=True)
    sp_cfg_get = config_sub.add_parser("get")
    sp_cfg_get.add_argument("key", nargs="?")
    sp_cfg_set = config_sub.add_parser("set")
    sp_cfg_set.add_argument("key")
    sp_cfg_set.add_argument("value")

    # `ustudio help` / `ustudio help export` — git/npm-style bare-word help,
    # alongside (not instead of) the -h/--help argparse already gives every
    # parser/subparser for free. Handled specially in ustudio_cli.py's main()
    # right after parsing, before any load/settings machinery runs.
    sp_help = sub.add_parser("help", help="show help, optionally for one command")
    sp_help.add_argument("topic", nargs="?", help="a command name, e.g. `help export`")

    return p


def print_command_help(parser: argparse.ArgumentParser, topic: Optional[str]) -> None:
    """`argparse._SubParsersAction.choices` is the standard (if underscored)
    way to reach a specific subparser by name for this — no public argparse
    API exposes "the subparser for command X" any other way, and this is a
    long-stable pattern, not a fragile private-API guess."""
    if not topic:
        parser.print_help()
        return
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            sub_parser = action.choices.get(topic)
            if sub_parser is not None:
                sub_parser.print_help()
                return
    print(f"no such command: {topic}", file=sys.stderr)


def build_repl_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="", add_help=False)
    sub = p.add_subparsers(dest="command", required=True)

    sp_load = sub.add_parser("load", add_help=False, help="load a different folder/files")
    _add_load_args(sp_load)

    sp_list = sub.add_parser("list", add_help=False)
    _add_filter_args(sp_list)
    sp_list.add_argument("-m", "--modified", action="store_true")
    sp_list.add_argument("--sdf", action="store_true")
    sp_list.add_argument("-r", "--sort")
    sp_list.add_argument("-f", "--format", choices=["table", "json", "csv"], default="table")
    sp_list.add_argument("-l", "--limit", type=int)
    sp_list.add_argument("-o", "--out")

    sp_inspect = sub.add_parser("inspect", add_help=False)
    sp_inspect.add_argument("ref")
    sp_inspect.add_argument("-S", "--source")
    sp_inspect.add_argument("-d", "--dump", choices=["typed", "json", "hex"], default="typed")

    sp_export = sub.add_parser("export", add_help=False)
    _add_filter_args(sp_export)
    sp_export.add_argument("-i", "--id")
    sp_export.add_argument("-m", "--mode", choices=["typed", "raw", "content-raw", "json"], default="typed")
    sp_export.add_argument("-o", "--out", default=DEFAULT_EXPORT_DIR, help=_OUT_HELP)
    sp_export.add_argument("-w", "--overwrite", action="store_true")
    sp_export.add_argument("--strict", action="store_true")
    sp_export.add_argument("--group-by", choices=["none", "type", "source"])
    sp_export.add_argument("--sdf", action="store_true")

    sp_import = sub.add_parser("import", add_help=False)
    _add_import_args(sp_import)

    sp_save = sub.add_parser("save", add_help=False)
    _add_save_args(sp_save)

    sp_cab = sub.add_parser("cab", add_help=False)
    _add_cab_subparsers(sp_cab, one_shot=False)

    for name in ("exit", "quit", "help"):
        sub.add_parser(name, add_help=False)

    return p


def split_repl_line(line: str) -> Optional[List[str]]:
    """shlex-based tokenizing so a quoted value (a name with spaces) still
    loses its quotes the way a real shell would. Plain shlex.split() is NOT
    safe here: posix=True (needed for quote-stripping) also treats backslash
    as an escape character, which silently mangles a Windows path
    (confirmed: "C:\\Users\\x\\Game_Data" -> "C:UsersxGame_Data") — and
    posix=False avoids that but then leaves the literal quote characters in
    a quoted token instead of stripping them. Disabling escape-interpretation
    on an otherwise-posix lexer is the one combination that gets both right
    (verified against both a quoted name and a raw Windows path before
    relying on it here, not assumed from the docs alone)."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    return list(lexer)
