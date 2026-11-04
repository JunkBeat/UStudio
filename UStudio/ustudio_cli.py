"""Entry point for UStudio's console mode. Deliberately a SEPARATE script from
main.py (which imports PyQt6 at module scope) — this must stay importable and
runnable without Qt installed at all, matching core/'s own "no PyQt6" rule.

Usage:
    python ustudio_cli.py load   -p "Game_Data" ...
    python ustudio_cli.py shell  -p "Game_Data"
    python ustudio_cli.py list   -p "Game_Data" --type Texture2D
    python ustudio_cli.py export -p "Game_Data" --type AudioClip -o ./out
"""

import logging
import sys
import traceback

from core.logging_setup import configure_console_logging

from cli import commands, output, repl, settings
from cli.banner import print_banner
from cli.game_folder import DefaultFolderError, apply_default_load_source
from cli.parser import build_cli_parser, needs_load, print_command_help
from cli.session import CliSession


def _configure_logging(verbose: bool) -> None:
    # Same rich-formatted handler the GUI's own configure_console_logging()
    # already provides (see that function's docstring — built for exactly this
    # future console entry point), just pointed at stderr instead of its
    # stdout default so core/'s log lines (Russian, shared with the GUI) never
    # land in a piped --format json result.
    configure_console_logging(level=logging.DEBUG if verbose else logging.INFO, stream=sys.stderr)


def _apply_settings_defaults(args) -> None:
    """Settings persisted via `config set` fill in whatever the caller didn't
    pass explicitly on the command line — CLI flags always win over a saved
    default, never the other way around."""
    if not hasattr(args, "fallback_version"):
        return
    saved = settings.load_settings()
    if not args.fallback_version:
        args.fallback_version = saved["fallback_version"]
    if not args.cn_key:
        args.cn_key = saved["unity_cn_key"]


def _run_config_command(args) -> int:
    if args.config_command == "get":
        values = settings.load_settings()
        if args.key:
            if args.key not in values:
                output.error(f"unknown setting: {args.key}")
                return 1
            print(values[args.key])
        else:
            output.print_json(values)
        return 0
    if args.config_command == "set":
        try:
            settings.set_one(args.key, args.value)
        except KeyError as e:
            output.error(str(e))
            return 1
        print(f"saved {args.key} = {args.value}", file=sys.stderr)
        return 0
    return 1


def _run_cache_command(args) -> int:
    """`cache` — where unpacked APK/OBB data lives, how much room it takes, and `--clear`."""
    from core import platform_sources as ps
    entries = ps.list_cache()
    total = sum(e.size for e in entries)
    print(f"{len(entries)} unpacked copy(ies), {total / 1024 ** 2:,.0f} MB in {ps.cache_base('android').parent}",
          file=sys.stderr)
    for e in entries:
        print(f"  {e.size / 1024 ** 2:8,.0f} MB  {e.origin or '(incomplete)'}", file=sys.stderr)
    if args.clear:
        freed = ps.clear_cache()
        print(f"cleared {freed / 1024 ** 2:,.0f} MB", file=sys.stderr)
    return 0


def _mb(n: int) -> str:
    return f"{n / 1024 ** 3:,.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:,.1f} MB"


def _run_backup_command(args) -> int:
    """`backup list` / `backup restore` — see core/backup.py. Deliberately whole-file only:
    per-object diff/restore was removed (see cli/parser.py's own comment on _add_backup_args'
    restore subparser for why) — a restore always makes its own safety copy and keeps 1 prior
    copy besides the first, no longer configurable."""
    from pathlib import Path
    from core import backup as bk
    root = Path(args.backup_dir) if getattr(args, "backup_dir", None) else None
    if args.backup_command == "list":
        # Real reported problem: one unbroken run of long lines (a full folder
        # path leading each entry, immediately followed by full file paths with
        # no separator) reads as a wall of text the instant any path wraps in a
        # real terminal — which is the common case, not an edge case, since
        # these paths are often long by nature. Fixed by leading each entry
        # with its own SHORT, scannable line (game tag/date/size — never long
        # enough to wrap) and pushing the two genuinely long things (the
        # backup folder, the original file paths) onto their own indented
        # lines below it, with a blank line between entries so one entry's
        # wrapped path is never visually confused for the start of the next.
        game_filter = (getattr(args, "game", None) or "").lower()
        infos = bk.list_backups(root)
        print(f"{len(infos)} backup(s), {_mb(bk.backups_total_size(root))} in {root or bk.default_backup_root()}",
              file=sys.stderr)
        print()
        for info in infos:
            if game_filter and game_filter not in (info.game.get("name", "") + " " + info.game.get("root", "")).lower():
                continue
            game_name = info.game.get("name", "")
            game_version = info.game.get("game_version", "")
            tag = f"{game_name} {game_version}".strip() if (game_name or game_version) else ""
            header = f"[{tag}]  " if tag else ""
            print(f"{header}{info.created}  ·  {len(info.files)} file(s), {_mb(info.size)}")
            print(f"  папка копии: {info.folder}")
            for e in info.files:
                print(f"    {e['original']}")
            print()
        return 0
    relocate = []
    for rule in getattr(args, "relocate", None) or []:
        old, sep, new = rule.partition("=")
        if not (sep and old.strip() and new.strip()):
            print(f"error: --relocate expects OLD=NEW (two folders joined by '='), got: {rule}", file=sys.stderr)
            return 1
        relocate.append((old.strip(), new.strip()))
    try:
        done = bk.restore_backup(Path(args.folder) if args.folder else None, root, args.file,
                                 safety_copy=True, dry_run=args.dry_run,
                                 keep_latest=1, copy=args.copy, game=getattr(args, "game", None),
                                 relocate=relocate)
    except bk.BackupFolderMissing as e:
        print(f"error: {e}", file=sys.stderr)
        print("If the game folder was moved, say where it is now: --relocate OLD=NEW "
              "(OLD is the folder as `backup list` shows it, NEW is where it lives now).", file=sys.stderr)
        return 1
    except bk.BackupError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    verb = "would restore" if args.dry_run else "restored"
    for src, orig in done:
        print(f"  {verb}: {orig}  <-  {src}", file=sys.stderr)
    print(f"{len(done)} file(s) {verb}.", file=sys.stderr)
    return 0


def _use_utf8_when_redirected() -> None:
    """A redirected stdout/stderr (a pipe or a file: scripts, installers, CI) defaulted to the legacy Windows
    code page, so the same line read as mojibake by a caller expecting UTF-8 and a character the code page lacks
    could crash the print. UTF-8 is the one encoding every caller can rely on; a real console keeps working
    through its own wide-character path and is left alone. `errors` never raises: a lone surrogate (an object
    name read with surrogateescape) prints as an escape instead of killing the command."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass  # not a text stream we can reconfigure (a frozen app without a console): nothing to fix


def main(argv=None) -> int:
    _use_utf8_when_redirected()
    # The command-line tool speaks English, whatever language the GUI is set to: the messages it prints
    # from core/ come from locales/en.json (core/i18n.py).
    from core.i18n import set_language
    set_language("en")
    parser = build_cli_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:  # started with nothing: show who we are and how to get help
        print_banner()
        print(parser.format_usage().rstrip(), file=sys.stderr)
        return 2  # a bare call is still a usage error for scripts, like argparse's own
    args = parser.parse_args(argv)

    if args.command == "help":
        print_banner(hint=False)
        print_command_help(parser, args.topic)
        return 0

    _configure_logging(args.verbose)

    if args.command == "config":
        return _run_config_command(args)

    if args.command == "cache":
        return _run_cache_command(args)

    if args.command == "backup":
        return _run_backup_command(args)

    _apply_settings_defaults(args)
    session = CliSession()

    try:
        # `import` checks its patch folder BEFORE anything else: a wrong/empty
        # folder is a filename-only check, and otherwise it would only be
        # reported after everything had been loaded.
        if args.command == "import":
            args.patch_scan = commands.check_patches_folder(args.patches)

        # No -p/-F: fall back to a *_Data folder in the current directory, but
        # only for commands that can't overwrite the originals (see
        # cli/game_folder.py). Echoed to stderr so what was picked is never
        # silent — deliberately not suppressed by -q, and stderr keeps it out
        # of a piped --format json result.
        auto_folder = apply_default_load_source(args)
        if auto_folder is not None:
            print(f"using {auto_folder} (auto-detected *_Data folder in the current directory)",
                  file=sys.stderr)

        if args.command == "import":
            commands.plan_partial_load(args)

        if args.command == "shell":
            print_banner()
            commands.cmd_load(args, session, interactive=True)
            return repl.run(session)

        if args.command == "load":
            commands.cmd_load(args, session, interactive=False)
            return 0

        if args.command == "cab":
            # Independent of the main load/rows entirely — `cab` manages its
            # own session.cab via --bundle (see dispatch_cab), never needs
            # cmd_load at all.
            commands.dispatch_cab(args, session)
            return 0

        # list / inspect / export / import / save: load first only if
        # the caller actually asked to (one-shot mode combines "load" + "act"
        # in one invocation). `save` alone will simply find nothing modified
        # on a fresh load — accurate, not a bug: only `import` can create an
        # edit to save within the same one-shot process (see cmd_import's
        # --save-as/--in-place chaining for why that's the one that matters).
        if needs_load(args):
            commands.cmd_load(args, session, interactive=False)
        elif args.command in ("list", "inspect", "export", "import", "save"):
            output.error("nothing to load - pass --folder/--files, or use `shell` mode")
            return 1

        if args.command == "list":
            commands.cmd_list(args, session)
        elif args.command == "inspect":
            commands.cmd_inspect(args, session)
        elif args.command == "export":
            commands.cmd_export(args, session)
        elif args.command == "import":
            commands.cmd_import(args, session, interactive=False)
        elif args.command == "save":
            commands.cmd_save(args, session)

        return 0

    except (commands.CommandError, DefaultFolderError) as e:
        output.error(str(e))
        return 1
    except KeyboardInterrupt:
        output.error("cancelled")
        return 1
    except Exception as e:  # noqa: BLE001 - top-level: never a raw traceback by default
        output.error(str(e))
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
