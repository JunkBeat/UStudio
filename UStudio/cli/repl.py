"""The `shell` command's interactive loop — load once (see parser.py's
build_cli_parser: `shell` takes the same load-arg group as `load`/one-shot
`export`/etc.), then dispatch repeated commands against the same CliSession
with zero reload cost, which is the entire reason this mode exists (see the
REPL-vs-one-shot comparison worked out earlier in this project's design
conversation: a dominant multi-GB bundle can cost several seconds to
quick-scan alone — paying that once instead of once per command is the
whole point)."""

import sys

from core.progress import OperationCancelled

from cli import commands, output
from cli.parser import build_repl_parser, split_repl_line
from cli.session import CliSession

_HELP_TEXT = """\
Commands: load, list, inspect, export, import, save, cab, help, exit
Running a command with -h for its own flags is NOT available in shell mode
(add_help is disabled here so --help can't accidentally exit the shell) -
see the top-level `ustudio COMMAND --help` instead, outside the shell."""


def run(session: CliSession) -> int:
    parser = build_repl_parser()
    print(_HELP_TEXT, file=sys.stderr)

    while True:
        try:
            line = input(f"\nustudio [{session.folder_label}]> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        tokens = split_repl_line(line)
        if tokens is None:
            continue

        if tokens[0] in ("exit", "quit"):
            break
        if tokens[0] == "help":
            print(_HELP_TEXT)
            continue

        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            # argparse's own error()/help actions call sys.exit() — that would
            # kill the whole shell over one bad command. Swallow it here; the
            # usage message argparse already printed to stderr is enough.
            continue

        try:
            _dispatch(args, session)
        except commands.CommandError as e:
            output.error(str(e))
        except OperationCancelled:
            output.error("cancelled")
        except Exception as e:  # noqa: BLE001 - a REPL must survive a bad command
            output.error(f"unexpected: {e}")

    print(f"Session summary: {session.folder_label or '(nothing loaded)'}.", file=sys.stderr)
    return 0


def _dispatch(args, session: CliSession) -> None:
    if args.command == "load":
        commands.cmd_load(args, session, interactive=True)
    elif args.command == "list":
        commands.cmd_list(args, session)
    elif args.command == "inspect":
        commands.cmd_inspect(args, session)
    elif args.command == "export":
        commands.cmd_export(args, session)
    elif args.command == "import":
        commands.cmd_import(args, session, interactive=True)
    elif args.command == "save":
        commands.cmd_save(args, session)
    elif args.command == "cab":
        commands.dispatch_cab(args, session)
