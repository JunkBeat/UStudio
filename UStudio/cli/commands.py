"""The actual verb implementations — thin glue between argparse's Namespace,
core/'s PyQt-free functions, and output.py's formatting. Every function here
is called identically from one-shot mode (parser.py) and from `shell` mode
(repl.py) — same functions, same argument shapes, just a different Namespace
source (sys.argv vs a parsed REPL line)."""

import sys
import traceback
from pathlib import Path
from typing import List, Optional

from core.cab_archive import CabArchive
from core.addressables_resolver import build_cab_index_for_folder
from core.collision_report import meaningful_collisions
from core.file_utils import detect_game_paths
from core.loader import EnvironmentLoader
from core.models import RowItem
from core.object_preview import (
    IMPORT_WARNING_PREFIX,
    apply_matched_patch,
    build_export_json,
    build_export_stem,
    dump_typed_text,
    export_object,
    export_object_content_raw,
    export_object_raw,
    get_row_name,
    get_row_script_name,
    match_patch_files,
    row_matches_script_selector,
    safe_parse_dict,
    sanitize_export_filename,
    scan_patch_folder,
)
from core.options import LoadMode, LoadOptions
from core.patch_sources import resolve_patch_sources
from core.progress import OperationCancelled, CoreOperationError
from core.save_manager import (
    SaveError,
    commit_overwrite,
    compute_base_dir,
    find_modified_roots,
    original_path,
    prepare_overwrite,
    release_environment,
    resolve_custom_dest,
    save_to_custom_path,
)
from core.sdf_resolver import (
    SDF_FONT_SCRIPT_NAME,
    SDFGroup,
    build_sdf_groups,
    export_sdf_package,
    resolve_sdf_components,
)

from cli import output, settings
from cli.parser import DEFAULT_PACKED_DIR
from core.identity import ObjectRefError, format_ref, parse_ref, resolve_ref
from cli.session import CliSession, InteractiveCallbacks, NonInteractiveCallbacks, OperationAbortedError


class CommandError(Exception):
    """A command-level failure — caught at the top (parser.py/repl.py), printed
    via output.error(), and turned into a non-zero process exit code (one-shot)
    or just reported without killing the shell (REPL)."""


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------

def plan_partial_load(args) -> None:
    """`import --partial`: works out which files the patches name and, when
    every one of them can be pinned to exactly one file under -p, leaves that list
    on args.partial_files for cmd_load() to load INSTEAD of the whole folder.
    Otherwise prints why not and leaves args untouched — the caller then does the
    ordinary full load, so the flag can only ever make an import faster, never
    change what it finds (see core.patch_sources for what "can't pin down" means).
    Needs args.patch_scan (main() sets it right after validating the patch folder)."""
    if not getattr(args, "partial_load", False):
        return
    if args.files:
        raise CommandError("--partial can't be combined with -F: -F already loads exactly the files you name")
    if not args.folder:
        raise CommandError("--partial needs -p FOLDER (the folder to look for the patches' files in)")

    root = Path(args.folder).resolve()
    if not root.is_dir():
        raise CommandError(f"--folder expects a directory: {root}")

    if args.patch_scan.sdf_maps:
        # An sdf_map.txt names fonts by display name, which says nothing about which file holds them.
        print("partial load not possible (the folder has an sdf_map.txt, which names fonts, not files)"
              " - loading the whole folder instead", file=sys.stderr)
        return

    wanted = {m.group(2) for _path, m, _mode in args.patch_scan.importable}
    resolution = resolve_patch_sources(str(root), wanted, args.exclude_folder or [])
    if not resolution.ok:
        print(f"partial load not possible ({resolution.why_not()}) - loading the whole folder instead",
              file=sys.stderr)
        return

    args.partial_files = resolution.files
    names = [Path(f).name for f in resolution.files]
    shown = ", ".join(names[:5]) + (f", ... (+{len(names) - 5})" if len(names) > 5 else "")
    print(f"partial load: {len(names)} of {resolution.files_scanned} file(s): {shown}", file=sys.stderr)


def _scan_dependency_folders(loader, folders, quiet: bool) -> None:
    """`--deps FOLDER`: the CLI counterpart of the GUI's "resolve references in
    neighbouring bundles" action. Indexes the internal file names of every bundle
    under each folder once (near-free header reads, no decompression) into the
    loader's own CabIndex, which the Environment consults when a reference
    (typically a MonoScript in a shared *_monoscripts.bundle) isn't in the loaded files."""
    for folder in folders or []:
        root = Path(folder).resolve()
        if not root.is_dir():
            raise CommandError(f"--deps expects an existing folder: {root}")
        if not quiet:
            print(f"Scanning {root} for dependencies...", file=sys.stderr)
        build_cab_index_for_folder(str(root), index=loader.cab_index)
        if not quiet:
            idx = loader.cab_index
            print(f"  {len(idx.entries):,} linked file(s) found in {idx.bundles_with_cabs:,} bundle(s)",
                  file=sys.stderr)


def cmd_load(args, session: CliSession, interactive: bool) -> None:
    partial_files = getattr(args, "partial_files", None)
    if partial_files:
        # Loaded as an explicit file list (so only those files are parsed) but
        # rooted at the -p folder: env.path — where a dependency file or a
        # .resS is looked up — is the same as in a full folder load, and the
        # SESSION below still records a folder load, so --save-as keeps laying
        # files out relative to that folder exactly as it would after one.
        mode = LoadMode.FILES
        folder_path = Path(args.folder).resolve()
        selected_dir = str(folder_path)
        selected_files: List[str] = [str(Path(f).resolve()) for f in partial_files]
        detect_from = folder_path
    elif args.folder:
        mode = LoadMode.FOLDER
        folder_path = Path(args.folder).resolve()
        if not folder_path.exists():
            raise CommandError(f"--folder path does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise CommandError(f"--folder expects a directory, got a file: {folder_path} (use --files instead)")
        selected_dir = str(folder_path)
        selected_files: List[str] = []
        detect_from = folder_path
    else:
        mode = LoadMode.FILES
        selected_dir = ""
        resolved_files = [Path(f).resolve() for f in args.files]
        for p in resolved_files:
            if not p.exists():
                raise CommandError(f"--files path does not exist: {p}")
            if p.is_dir():
                raise CommandError(f"--files expects a file, got a directory: {p} (use --folder instead)")
        selected_files = [str(p) for p in resolved_files]
        detect_from = resolved_files[0]

    game_paths = detect_game_paths(detect_from)
    managed_dir = game_paths["managed_dir"]
    assembly_arg = getattr(args, "assembly", None)
    if assembly_arg:
        assembly_path = Path(assembly_arg).resolve()
        if not assembly_path.is_dir():
            raise CommandError(f"--assembly path does not exist or is not a folder: {assembly_path}")
        managed_dir = str(assembly_path)

    options = LoadOptions(
        load_mode=mode,
        selected_dir=selected_dir,
        selected_files=selected_files,
        game_data_dir=game_paths["data_dir"],
        managed_dir=managed_dir,
        game_root_dir=game_paths["game_root_dir"],
        is_il2cpp=game_paths["is_il2cpp"],
        fallback_version=args.fallback_version or "",
        unity_cn_key=args.cn_key or "",
        object_count_threshold=args.threshold,
        excluded_folders=list(args.exclude_folder or []),
        cab_collision_policy=args.cab_collision,
        load_all_assets=args.all_assets,
    )

    if interactive:
        callbacks = InteractiveCallbacks(quiet=args.quiet)
    else:
        callbacks = NonInteractiveCallbacks(
            on_large_file=args.on_large_file,
            quiet=args.quiet,
        )

    try:
        # See output.redirect_native_stdout_to_stderr's own docstring: this
        # is where TypeTreeGeneratorAPI's native IL2CPP error text (found via
        # a real test, not theoretical) would otherwise leak straight past
        # sys.stdout and corrupt a --format json result.
        with output.redirect_native_stdout_to_stderr():
            loader = EnvironmentLoader(options, callbacks)
            _scan_dependency_folders(loader, getattr(args, "deps", None), args.quiet)
            result = loader.load()
    except OperationCancelled:
        raise CommandError("cancelled")
    except (OperationAbortedError, CoreOperationError) as e:
        raise CommandError(str(e))

    session.env = result.env
    session.rows = result.objects
    session.unity_version = result.unity_version
    session.platform_name = result.platform_name
    session.folder_label = Path(selected_dir or selected_files[0]).name
    session.load_mode = LoadMode.FOLDER if partial_files else mode
    session.selected_dir = selected_dir
    session.selected_files = [] if partial_files else selected_files

    print(
        f"Loaded. {len(session.rows):,} objects, "
        f"{len({r['type'] for r in session.rows})} types, "
        f"Unity {session.unity_version or 'unknown'}.",
        file=sys.stderr,
    )

    # GUI parity (cab_collision_handler.py's log report) — the CLI had no
    # equivalent at all before this: env.name_collisions was never even
    # inspected here. Only fires for a collision where both sides actually
    # hold objects (see meaningful_collisions' own docstring) — not the far
    # more common, harmless case of two folders sharing an identical Mono
    # runtime DLL/config file.
    collisions = meaningful_collisions(getattr(session.env, "name_collisions", None))
    if collisions:
        print(
            f"note: {len(collisions)} file(s) with the same name but different content were found "
            "across different sources (e.g. more than one 'resources.assets') and both sides contain "
            "objects - this folder probably holds more than one Unity game. Resources and cross-file "
            "references are resolved from the folder nearest each object, so reading and saving work "
            "per game; only SOURCE:PATH_ID references stay ambiguous for the affected files (use "
            "-S SOURCE or -x/--exclude to pick one).",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# filtering shared by list/export
# ---------------------------------------------------------------------------

def _filter_rows(rows: List[RowItem], args, env=None) -> List[RowItem]:
    result = rows
    if args.type:
        wanted = {t.strip() for t in args.type.split(",")}
        result = [r for r in result if r["type"] in wanted]
    if args.script_type:
        # A bare name (e.g. "Bloom") matches every script sharing that bare
        # class name, even if the game has more than one under different
        # namespaces/assemblies -- pass a dot-qualified name
        # ("Namespace.ClassName", optionally "(AssemblyName.dll)" too — see
        # core.object_common.script_checklist_entries()'s own docstring) to
        # narrow to exactly one, same convention as the GUI's Filters dialog
        # and Quick Filter free-text field.
        result = [r for r in result if row_matches_script_selector(r, {args.script_type})]
    if args.name_contains:
        needle = args.name_contains.lower()
        result = [r for r in result if needle in get_row_name(r).lower()]
    if args.source:
        from core.identity import row_matches_source
        result = [r for r in result if row_matches_source(r, args.source, env)]
    if getattr(args, "modified", False):
        result = [r for r in result if r["obj_ref"].data is not None]
    return result


# Column key functions for `list --sort`, sharing output.row_to_dict's own
# column set so a sort key always means the same thing as what --format table/
# json/csv actually prints. String columns are lowercased so "A to Z" reads as
# a human would expect (not ASCII order, where every uppercase letter sorts
# before every lowercase one).
_SORT_COLUMNS = {
    "path_id": lambda r: r["path_id"],
    "name": lambda r: get_row_name(r).lower(),
    "type": lambda r: r["type"].lower(),
    "script_name": lambda r: (get_row_script_name(r) if r["type"] == "MonoBehaviour" else "").lower(),
    "source": lambda r: r["source"].lower(),
    "size": lambda r: r["size"],
    "modified": lambda r: r["obj_ref"].data is not None,
}


def _parse_sort_spec(spec: str) -> List["tuple[str, bool]"]:
    """'-size,name' -> [("size", True), ("name", False)] - a leading '-' on a
    column name means descending (Z-A/high-to-low) for that column only, mirroring
    the same convention Django's QuerySet.order_by() uses, so a mixed-direction
    multi-column sort never needs a second flag."""
    parts: List["tuple[str, bool]"] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        desc = token.startswith("-")
        col = token[1:] if desc else token
        if col not in _SORT_COLUMNS:
            raise CommandError(f"unknown sort column: {col!r} (known: {', '.join(sorted(_SORT_COLUMNS))})")
        parts.append((col, desc))
    if not parts:
        raise CommandError("--sort given but empty")
    return parts


def _sort_rows(rows: List[RowItem], spec: str) -> List[RowItem]:
    """Multi-column sort via repeated stable sorts, least-significant column
    first - the standard way to get independent per-column direction (e.g.
    "type,-size": type A-Z, then size high-to-low within each type) out of
    Python's sort, which only take one `reverse` per call."""
    parts = _parse_sort_spec(spec)
    result = list(rows)
    for col, desc in reversed(parts):
        result.sort(key=_SORT_COLUMNS[col], reverse=desc)
    return result


# ---------------------------------------------------------------------------
# SDF font packages — shared by `list --sdf` and `export --sdf`. A TMP_FontAsset
# (MonoBehaviour) plus its Material/atlas Texture2D/source Font, resolved via
# core.sdf_resolver — same PyQt-free module the GUI's SDF Viewer Mode
# (sdf_group_model.py) is built on, so "which components a font pack has" can
# never drift between the two front ends.
# ---------------------------------------------------------------------------

# (role, attribute-on-SDFGroup, error-attribute-on-SDFGroup-or-None) — order
# matches SDFGroup.children()/export_sdf_package()'s own font/material/
# texture/source_font order.
_SDF_ROLES = (
    ("font", "font", None),
    ("material", "material", "material_error"),
    ("texture", "texture", "texture_error"),
    ("source_font", "source_font", None),
)


def _require_sdf_groups(session: CliSession) -> List[SDFGroup]:
    groups = build_sdf_groups(session.rows)
    if not groups:
        raise CommandError("no SDF font packages (TMP_FontAsset) found among loaded objects")
    return groups


def _print_sdf_table(groups: List[SDFGroup], file) -> None:
    """SOURCE:PATH_ID is printed on the font's own header line (via
    format_ref) specifically so it can be copied straight into `export --sdf
    --id ...` for a single-font export — the table's PATH_ID column doesn't
    exist here (this isn't the normal flat `list`), so without this a user
    would have no way to name one specific font pack at all."""
    branch, last_branch, pipe, blank = output.tree_connectors(file)
    for group in groups:
        print(f"{get_row_name(group.font)}  [{format_ref(group.font)}]", file=file)
        visible = [
            (role, getattr(group, attr), getattr(group, err_attr, "") if err_attr else "")
            for role, attr, err_attr in _SDF_ROLES
        ]
        # A missing, error-less source_font is routine (most fonts have none
        # linked at all - see resolve_sdf_components()'s own docstring), not
        # worth a line; a missing material/texture ALWAYS has an error string
        # attached (resolve_sdf_components() guarantees this), so it still
        # shows up here as the error case below.
        visible = [(role, item, error) for role, item, error in visible if item is not None or error]
        for i, (role, item, error) in enumerate(visible):
            connector = last_branch if i == len(visible) - 1 else branch
            if item is not None:
                d = output.row_to_dict(item)
                print(f"{connector}{d['type']:<14} {d['name']}  ({d['source']}, {output.format_size(d['size'])})",
                      file=file)
            else:
                print(f"{connector}{role}: (not found)", file=file)
    print(f"\n{len(groups)} SDF font pack(s)", file=file)


def _sdf_groups_to_json(groups: List[SDFGroup]) -> List[dict]:
    result = []
    for group in groups:
        entry = {}
        for role, attr, err_attr in _SDF_ROLES:
            item = getattr(group, attr)
            entry[role] = output.row_to_dict(item) if item is not None else None
            if err_attr:
                entry[f"{role}_error"] = getattr(group, err_attr, "") or None
        result.append(entry)
    return result


def _sdf_groups_to_rows(groups: List[SDFGroup]) -> List[dict]:
    """Flat one-row-per-component shape for --format csv (which has no way to
    express nesting) - each row is a normal row_to_dict() plus 'sdf_group'/
    'role' columns identifying which font pack/slot it belongs to, or just
    those two columns plus 'error' when a slot didn't resolve."""
    rows = []
    for group in groups:
        font_name = get_row_name(group.font)
        for role, attr, err_attr in _SDF_ROLES:
            item = getattr(group, attr)
            error = getattr(group, err_attr, "") if err_attr else ""
            if item is None and not error:
                continue
            if item is not None:
                d = dict(output.row_to_dict(item))
            else:
                d = {"path_id": "", "name": "", "type": "", "script_name": "", "source": "", "size": "", "modified": ""}
            d["sdf_group"] = font_name
            d["role"] = role
            d["error"] = error
            rows.append(d)
    return rows


_SDF_CSV_COLUMNS = ["sdf_group", "role", "path_id", "name", "type", "source", "size", "modified", "error"]


def cmd_list_sdf(args, session: CliSession) -> None:
    """`list --sdf` - lists detected SDF font packages instead of the normal
    flat object list, mirroring the GUI's SDF Viewer Mode tree (see
    sdf_group_model.py's own module docstring) rather than object_table.py's
    flat rows: a font's material/atlas texture/source font are shown grouped
    under it, not interleaved with unrelated rows the way a plain --script-
    type TMP_FontAsset filter would leave them."""
    groups = _require_sdf_groups(session)
    if getattr(args, "limit", None):
        groups = groups[: args.limit]
    file = open(args.out, "w", encoding="utf-8", newline="") if args.out else sys.stdout
    try:
        if args.format == "json":
            output.print_json(_sdf_groups_to_json(groups), file=file)
        elif args.format == "csv":
            output.print_csv(_sdf_groups_to_rows(groups), _SDF_CSV_COLUMNS, file=file)
        else:
            _print_sdf_table(groups, file=file)
    finally:
        if args.out:
            file.close()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def cmd_list(args, session: CliSession) -> None:
    _require_loaded(session)
    if getattr(args, "sdf", False):
        cmd_list_sdf(args, session)
        return
    rows = _filter_rows(session.rows, args, session.env)
    if getattr(args, "sort", None):
        rows = _sort_rows(rows, args.sort)
    if args.limit:
        rows = rows[: args.limit]
    output.emit_rows(rows, args.format, out=args.out)


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------

def cmd_inspect(args, session: CliSession) -> None:
    _require_loaded(session)
    row = _resolve_single(session, args.ref, getattr(args, "source", None))
    obj = row["obj_ref"]

    if args.dump == "typed":
        text, error, is_partial = dump_typed_text(obj)
        if error:
            raise CommandError(error.splitlines()[0])
        if is_partial:
            print("(partial parse - some fields may be missing)", file=sys.stderr)
        print(text)
    elif args.dump == "hex":
        data = obj.get_raw_data()
        print(data[:4096].hex(" ", 2))
        if len(data) > 4096:
            print(f"... ({len(data):,} bytes total, showing first 4096)", file=sys.stderr)
    else:  # json
        data, error = safe_parse_dict(obj)
        if error:
            raise CommandError(error.splitlines()[0])
        output.print_json(data)


# ---------------------------------------------------------------------------
# export --sdf - a TMP_FontAsset's whole package (font/material/atlas texture/
# source font), into SDF/<font name>/<files> under the chosen --out folder -
# same shape and same core.sdf_resolver.export_sdf_package() call the GUI's
# own "Экспортировать SDF шрифт.../...все SDF шрифты..." actions use (see
# object_actions.py's export_sdf_font()/export_all_sdf_fonts()), just driven
# from argparse instead of a QFileDialog + background QThread.
# ---------------------------------------------------------------------------

def _export_one_sdf_package(components, sdf_root: Path, overwrite: bool) -> "tuple[int, int]":
    """Returns (ok_count, failed_count) across the package's own up-to-4
    components - a partial result (e.g. texture failed but font/material
    exported fine) still counts as 1 ok'd package overall at the call site,
    matching export_sdf_font()'s own GUI behavior (only ALL components
    failing is treated as the package itself having failed)."""
    out_dir, results = export_sdf_package(components, sdf_root, overwrite=overwrite)
    ok = failed = 0
    for r in results:
        if r.skipped:
            print(f"  skip: {r.label}: {(r.message or '').splitlines()[0]}", file=sys.stderr)
        elif r.message:
            failed += 1
            print(f"  error: {r.label}: {r.message.splitlines()[0]}", file=sys.stderr)
        else:
            ok += 1
            print(f"  {r.label}: {r.out_path}", file=sys.stderr)
    return ok, failed


def cmd_export_sdf(args, session: CliSession) -> None:
    """`export --sdf` - with --id, exports exactly one font's package;
    without it, every detected SDF font package (mirrors export_all_sdf_
    fonts()'s bulk behavior). --type/--script/--name-contains/--source
    are ignored here (a font pack is identified by --id or "all of them",
    the same way --sdf works for `list`), since narrowing which MonoBehaviour
    rows count as fonts is exactly what core.sdf_resolver.build_sdf_groups()
    already does."""
    sdf_root = Path(args.out) / "SDF"

    if args.id:
        row = _resolve_single(session, args.id, args.source)
        if get_row_script_name(row) != SDF_FONT_SCRIPT_NAME:
            raise CommandError(
                f"{format_ref(row)} is not a TMP_FontAsset "
                f"(script_name={get_row_script_name(row) or '(none)'!r}) - use `list --sdf` to see detected fonts"
            )
        components = resolve_sdf_components(row["obj_ref"])
        ok, failed = _export_one_sdf_package(components, sdf_root, args.overwrite)
        print(f"Exported {ok} component(s) ({failed} failed) to {sdf_root}", file=sys.stderr)
        if failed and args.strict:
            raise CommandError(f"{failed} component(s) failed to export")
        return

    groups = _require_sdf_groups(session)
    exported = 0
    failed_packages = 0
    for group in groups:
        font_name = get_row_name(group.font)
        print(f"{font_name}:", file=sys.stderr)
        try:
            components = resolve_sdf_components(group.font["obj_ref"])
            ok, failed = _export_one_sdf_package(components, sdf_root, args.overwrite)
            if ok:
                exported += 1
            else:
                failed_packages += 1
        except Exception as e:
            failed_packages += 1
            print(f"  error: {e}", file=sys.stderr)
            if getattr(args, "verbose", False):
                traceback.print_exc(file=sys.stderr)

    print(f"Exported {exported}/{len(groups)} SDF font pack(s) to {sdf_root}", file=sys.stderr)
    if failed_packages:
        print(f"  {failed_packages} pack(s) failed entirely (no component exported)", file=sys.stderr)
        if args.strict:
            raise CommandError(f"{failed_packages} SDF font pack(s) failed to export")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def _grouped_export_dir(base_dir: Path, row: RowItem, group_by: str) -> Path:
    """CLI-local mirror of object_actions.py's `_grouped_out_dir` — same
    "none"/"type"/"source" subfolder choice, reimplemented here rather than
    imported to keep the CLI layer PyQt-free (object_actions.py imports PyQt6)."""
    if group_by == "type":
        subdir = sanitize_export_filename(str(row.get("type", "")), fallback="unknown_type")
    elif group_by == "source":
        subdir = sanitize_export_filename(str(row.get("source", "")), fallback="unknown_source")
    else:
        return base_dir
    target = base_dir / subdir
    target.mkdir(parents=True, exist_ok=True)
    return target


def cmd_export(args, session: CliSession) -> None:
    _require_loaded(session)

    if getattr(args, "sdf", False):
        cmd_export_sdf(args, session)
        return

    if args.id:
        rows = [_resolve_single(session, args.id, args.source)]
    else:
        rows = _filter_rows(session.rows, args, session.env)

    if not rows:
        raise CommandError("no objects matched")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Real reported gap: the GUI's own export flow has had a "none"/"type"/
    # "source" subfolder-grouping setting for a while (CONFIG.export_grouping,
    # object_actions.py's _grouped_out_dir()) with no CLI equivalent at all —
    # every CLI export landed in one flat folder regardless. Mirrors that
    # exact same three-way choice and the same "config get/set" default
    # convention _add_import_args's own texture/video options already use,
    # rather than introducing a fourth, CLI-only value set for the same idea.
    group_by = args.group_by or settings.load_settings()["export_grouping"]

    exported = 0
    skipped = 0
    failed = 0
    for row in rows:
        obj = row["obj_ref"]
        item_out_dir = _grouped_export_dir(out_dir, row, group_by)
        try:
            was_skipped = False
            if args.mode == "raw":
                path, error = export_object_raw(obj, item_out_dir)
                ok, msg = path is not None, error
            elif args.mode == "content-raw":
                path, error, was_skipped = export_object_content_raw(obj, item_out_dir)
                ok, msg = path is not None, error
            elif args.mode == "json":
                text, error, was_skipped = build_export_json(obj)
                if text is None:
                    ok, msg = False, error
                else:
                    stem = build_export_stem(obj)
                    (item_out_dir / f"{stem}.dump.json").write_text(text, encoding="utf-8")
                    ok, msg = True, None
            else:  # typed
                path, error, was_skipped = export_object(obj, item_out_dir, overwrite=args.overwrite)
                ok, msg = path is not None, error

            # was_skipped=True is export_object()'s/export_object_content_raw()'s
            # own signal for an EXPECTED, non-error state (an empty texture, a
            # font with no embedded data, ...) — its own docstring is explicit
            # that a caller must NOT count this as a failure. A real error
            # (msg set, was_skipped False) still counts as one.
            if ok:
                exported += 1
            elif was_skipped:
                skipped += 1
                print(f"  skip: {format_ref(row)}: {(msg or '').splitlines()[0]}", file=sys.stderr)
            elif msg:
                failed += 1
                print(f"  error: {format_ref(row)}: {msg.splitlines()[0]}", file=sys.stderr)
        except Exception as e:
            failed += 1
            print(f"  error: {format_ref(row)}: {e}", file=sys.stderr)
            if getattr(args, "verbose", False):
                traceback.print_exc(file=sys.stderr)

    print(f"Exported {exported}/{len(rows)} object(s) to {out_dir}", file=sys.stderr)
    if skipped:
        print(f"  {skipped} skipped (expected, e.g. empty texture/no samples)", file=sys.stderr)
    if failed:
        print(f"  {failed} failed", file=sys.stderr)
        if getattr(args, "strict", False):
            raise CommandError(f"{failed} object(s) failed to export")


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def check_patches_folder(patches: str):
    """Fails fast — with the reason — when the patch folder can't possibly
    yield anything to import, and returns its PatchFolderScan otherwise. Meant
    to run BEFORE the (potentially minutes-long) load: without this, a wrong or
    empty folder only gets reported after everything has already been loaded,
    as a generic "no files matched a loaded object". Only looks at filenames
    (see core.object_preview.scan_patch_folder); whether a patch matches an
    object that's actually loaded is still cmd_import's business."""
    folder = Path(patches)
    if not folder.exists():
        raise CommandError(f"patches folder does not exist: {folder}")
    if not folder.is_dir():
        raise CommandError(f"patches must be a folder, got a file: {folder}")

    scan = scan_patch_folder(folder)
    if scan.has_anything_to_import:
        return scan
    if scan.files_scanned == 0:
        raise CommandError(f"patches folder is empty: {folder}")
    if scan.name_matches == 0:
        raise CommandError(
            f"none of the {scan.files_scanned} file(s) in {folder} follow the export naming "
            f"'<name> #<path_id> (<source>).<ext>' and there is no sdf_map.txt - nothing to import "
            f"(files written by `export` follow that naming)"
        )
    raise CommandError(
        f"{scan.name_matches} file(s) in {folder} follow the export naming, but none has an "
        f"importable extension"
    )


def _failed_patches_message(failed: int, applied: int, session: CliSession, interactive: bool) -> str:
    """The error that cancels an import because patches failed: says what was NOT done, and what already was
    (resource files are written to disk the moment a patch uses them, before any save)."""
    from core.object_content_raw import resource_files_written
    msg = f"{failed} patch(es) failed to apply - nothing was saved (--strict)"
    if interactive and applied:
        msg += f" ({applied} patch(es) that applied are still pending in this session: `save` keeps them)"
    written = resource_files_written(session.env) if session.env is not None else []
    if written:
        msg += ("\n  already written to disk before the failure (resource files are written as soon as a patch "
                "uses them; --backup would have saved their original content):\n    " + "\n    ".join(written))
    return msg


def cmd_import(args, session: CliSession, interactive: bool = False) -> None:
    _require_loaded(session)
    # One-shot mode already ran this before loading (see ustudio_cli.main) and
    # left the result on args; the REPL never does, so it runs here.
    scan = getattr(args, "patch_scan", None)
    if scan is None:
        scan = check_patches_folder(args.patches)

    saved = settings.load_settings()
    texture_quality = args.texture_quality or saved["texture_import_quality"]
    texture_format_mode = args.texture_format_mode or saved["texture_import_format_mode"]
    texture_manual_format = args.texture_format or saved["texture_import_manual_format"]
    audio_quality = args.audio_quality if args.audio_quality is not None else saved["audio_import_quality"]
    resource_target_mode = args.resource_target_mode or saved["resource_target_mode"]
    resource_name = args.resource_name or saved["resource_name"]
    # Reuses the SAME -b/--backup/--backup-keep flags already used for the
    # save side of this command (see _backup_kwargs) — a resource-backed
    # content-raw/converted import (AudioClip/VideoClip/Texture2D-into-a-
    # .resource-file) writes straight to disk immediately, before any `save`
    # step, so it needs its own backup-before-first-write, not just the one
    # `save`/`import --in-place` already does for the .assets/.bundle file
    # itself. No new flag: passing --backup once covers both.
    backup_before_overwrite = bool(getattr(args, "backup", False) or getattr(args, "backup_dir", None))
    backup_keep_latest = getattr(args, "backup_keep", 1)
    # ...into the SAME folder as the .assets backups, so that `backup restore --backup-dir DIR` finds both
    if getattr(args, "backup_dir", None) and session.env is not None:
        from core.object_content_raw import set_resource_backup_root
        set_resource_backup_root(session.env, args.backup_dir)
    video_transcode = getattr(args, "video_transcode", False)
    video_transcode_target = args.video_transcode_target or saved["video_transcode_target"]
    video_transcode_quality = (
        args.video_transcode_quality if args.video_transcode_quality is not None
        else saved["video_transcode_quality"]
    )

    candidates = [(r["path_id"], r["source"], r["obj_ref"]) for r in session.rows]
    unmatched: list = []     # importable patch files that found no object (see below)
    matches = match_patch_files(
        Path(args.patches), candidates,
        texture_quality=texture_quality,
        texture_format_mode=texture_format_mode,
        texture_manual_format=texture_manual_format,
        audio_quality=audio_quality,
        resource_target_mode=resource_target_mode,
        resource_name=resource_name,
        backup_before_overwrite=backup_before_overwrite,
        backup_keep_latest=backup_keep_latest,
        video_transcode=video_transcode,
        video_transcode_target=video_transcode_target,
        video_transcode_quality=video_transcode_quality,
        unmatched=unmatched,
    )

    sdf_jobs = _load_sdf_jobs(args, session, scan)
    if not matches and not sdf_jobs:
        raise CommandError(f"no files in {args.patches} matched a loaded object")

    def _flag(m) -> str:
        if m.name_mismatch:
            if m.mismatch_kind == "script":
                what = f"script mismatch: patch is for '{m.declared_name}', object now has '{m.current_name}'"
            elif m.mismatch_kind == "shifted":
                what = "no name to check, and the neighbouring patches of this file no longer match their objects"
            else:
                what = f"name mismatch: patch is for '{m.declared_name}', object now is '{m.current_name}'"
            return f"  ({what} - path_id may have moved to a different object)"
        if m.name_unverified:
            return ("  (script unresolved - patch not verified against the object)" if m.mismatch_kind == "script"
                    else "  (no name to check it by - patch not verified against the object)")
        return ""

    def _what(m) -> str:
        return f"{m.file_path.name} -> {m.display_name} ({m.mode})"

    def _type(m) -> str:
        return getattr(getattr(m.obj, "type", None), "name", None) or "object"

    # A patch file that is named like an export but whose (path_id, source) matches no loaded object used to vanish
    # without a word (match_patch_files() just skipped it), while "Applied N/N" and the exit code claimed success: after
    # a game update shifted the ids a mod was silently half-applied. They are listed, counted, and --strict refuses
    # to apply anything while one of them exists.
    if unmatched:
        for path, path_id, source in unmatched:
            print(f"  unmatched: {path.name}: no object #{path_id} in '{source}'", file=sys.stderr)
        print(f"  {len(unmatched)} patch file(s) matched no loaded object and will NOT be applied "
              "(the game files may have changed since the patches were made)", file=sys.stderr)
        if getattr(args, "strict", False) and not args.dry_run:
            raise CommandError(f"{len(unmatched)} patch file(s) matched no loaded object - nothing was applied")

    # GUI parity (ImportMatchDialog unchecks these by default): a patch whose
    # name/script no longer matches its (source, path_id) slot may belong to a
    # different object after a game update, so it is skipped unless --force.
    skipped = [m for m in matches if m.name_mismatch]
    if skipped and not getattr(args, "force", False):
        matches = [m for m in matches if not m.name_mismatch]
        for m in skipped:
            print(f"  skipped: {_what(m)}{_flag(m)}", file=sys.stderr)
        print(
            f"  skipped {len(skipped)} patch(es) with a name/script mismatch - pass --force to apply them anyway",
            file=sys.stderr,
        )
    else:
        skipped = []

    # One numbered line per patch ("[i/N] Type: file -> name (mode)"), printed when it is DONE, not before: a
    # listing ahead of the work would claim success for a patch that then fails. A failure prints "error:" instead.
    total = len(matches)

    if args.dry_run:
        for i, m in enumerate(matches, 1):
            print(f"[{i}/{total}] {_type(m)}: {_what(m)}{_flag(m)}", file=sys.stderr)
        print(f"DRY RUN - {len(matches)} match(es) would be applied, nothing applied.", file=sys.stderr)
        _print_sdf_plan(sdf_jobs)
        if skipped and getattr(args, "strict", False):
            raise CommandError(f"{len(skipped)} patch(es) skipped because of a name/script mismatch")
        if unmatched and getattr(args, "strict", False):
            raise CommandError(f"{len(unmatched)} patch file(s) matched no loaded object")
        return

    applied = 0
    warned = 0
    failed = 0
    for i, m in enumerate(matches, 1):
        prefix = f"[{i}/{total}]"
        try:
            result = apply_matched_patch(m)
        except Exception as e:
            failed += 1
            print(f"{prefix} error: {m.file_path.name}: {e}", file=sys.stderr)
            if getattr(args, "verbose", False):
                traceback.print_exc(file=sys.stderr)
            continue

        if result is None:
            applied += 1
            print(f"{prefix} {_type(m)}: {_what(m)}{_flag(m)}", file=sys.stderr)
        elif result.startswith(IMPORT_WARNING_PREFIX):
            applied += 1
            warned += 1
            print(f"{prefix} {_type(m)} (warning): {_what(m)}{_flag(m)}", file=sys.stderr)
            print(f"    {result[len(IMPORT_WARNING_PREFIX):]}", file=sys.stderr)
        else:
            failed += 1
            print(f"{prefix} error: {m.file_path.name}: {result.splitlines()[0]}", file=sys.stderr)

    # A patch to an object whose type a large load left out adopted it into its file; the save below is driven by
    # the rows, so it needs one (core.patch_matching.adopted_without_row)
    from core.loader import build_row_item
    from core.patch_matching import adopted_without_row
    for obj in adopted_without_row([m.obj for m in matches], session.rows):
        session.rows.append(build_row_item(obj, include_all=True))

    print(f"Applied {applied}/{len(matches) + len(skipped) + len(unmatched)} patch(es)", file=sys.stderr)
    if unmatched:
        print(f"  {len(unmatched)} unmatched (no such object, see above)", file=sys.stderr)
    if skipped:
        print(f"  {len(skipped)} skipped (name/script mismatch, see above)", file=sys.stderr)
        if getattr(args, "strict", False):
            raise CommandError(f"{len(skipped)} patch(es) skipped because of a name/script mismatch")
    if warned:
        print(f"  {warned} with a warning (see above)", file=sys.stderr)
    if failed:
        print(f"  {failed} failed", file=sys.stderr)
        # --strict is all-or-nothing: one patch that fails to apply and nothing is saved (an installer must never leave
        # half a mod behind). Without it every patch is still tried, the ones that applied are kept, and the command
        # ends with an error below so that a script cannot mistake a partial result for a success.
        if getattr(args, "strict", False):
            raise CommandError(_failed_patches_message(failed, applied, session, interactive))

    fonts_done, fonts_failed = _run_sdf_jobs(sdf_jobs, args)
    applied += fonts_done

    save_as = getattr(args, "save_as", None)
    in_place = getattr(args, "in_place", False)
    saved = bool(applied) and (bool(save_as) or in_place or not interactive)
    if applied and (save_as or in_place):
        _perform_save(session, save_as=save_as, quiet=getattr(args, "quiet", False), dry_run=False, **_backup_kwargs(args))
    elif applied and not interactive:
        # A one-shot process's edits live only in its own memory, so with no
        # explicit save method they go to a NEW default folder (never over the
        # originals). `shell` mode keeps the session, so a later `save` works.
        _perform_save(session, save_as=DEFAULT_PACKED_DIR, quiet=getattr(args, "quiet", False), dry_run=False)

    if failed or fonts_failed:
        what = " and ".join(p for p in (f"{failed} patch(es)" if failed else "", f"{fonts_failed} font(s)" if fonts_failed else "") if p)
        if saved:
            fate = f"; the {applied} that applied were saved"
        elif interactive and applied:
            fate = f"; the {applied} that applied are still pending in this session (`save` keeps them)"
        else:
            fate = "; nothing was saved"
        raise CommandError(f"{what} failed to apply{fate} (use --strict to apply nothing when anything fails)")


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

def cmd_save(args, session: CliSession) -> None:
    _require_loaded(session)
    _perform_save(session, save_as=args.save_as, quiet=getattr(args, "quiet", False), dry_run=args.dry_run,
                  **_backup_kwargs(args))


# ---------------------------------------------------------------------------
# SDF generation from an sdf_map.txt found in the `import` folder — the map
# (core.sdf_map) names the targets, fonts, characters and settings; there is no
# separate command. Shares core.sdf_map.load_sdf_map_jobs() with the GUI's
# "import into environment", so both resolve a map identically.
# ---------------------------------------------------------------------------

def _load_sdf_jobs(args, session: CliSession, scan) -> list:
    if not scan.sdf_maps:
        return []
    from core.identity import prefer_canonical_registration
    from core.sdf_map import FontMapError, load_sdf_map_jobs

    # prefer_canonical_registration: a game folder with its own backup/ copy can leave two rows
    # with the identical (source, path_id); keep only the file that is actually active.
    rows = prefer_canonical_registration(session.rows, session.env)
    try:
        jobs, warnings = load_sdf_map_jobs(scan.sdf_maps, rows)
    except FontMapError as e:
        raise CommandError(str(e))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if warnings and getattr(args, "strict", False):
        raise CommandError(f"{len(warnings)} sdf_map target(s) did not resolve to any loaded object")
    missing = sorted({str(m.font_path) for job in jobs for m in job.mappings if not m.font_path.is_file()})
    if missing:
        raise CommandError("font file(s) named in sdf_map.txt not found:\n  " + "\n  ".join(missing))
    return jobs


def _sdf_effective(m):
    from core.sdf_map import SdfFallback, effective_settings
    return effective_settings(m, SdfFallback())  # no CLI flags any more: built-in values only


def _print_sdf_plan(jobs) -> None:
    from core.identity import format_ref
    from core.object_preview import get_row_name
    from core.sdf_map import FontMapError
    planned = failing = 0
    for job in jobs:
        for m in job.mappings:
            try:
                eff = _sdf_effective(m)
            except FontMapError as e:
                failing += 1
                print(f"  SDF {format_ref(m.row)} {get_row_name(m.row)!r}: error: {e}", file=sys.stderr)
                continue
            planned += 1
            size = "fit" if eff.point_size_fit else (f"{eff.point_size:g}" if eff.point_size is not None else "original")
            rng = f"{eff.pxrange:g}" if eff.pxrange is not None else "original"
            atlas = f", atlas={eff.atlas_width}x{eff.atlas_height}" if eff.atlas_width else ""
            match = ", match_height=on" if eff.match_height else ""
            if eff.add_missing:
                match += ", add_chars=on"
            print(
                f"  SDF {format_ref(m.row)} {get_row_name(m.row)!r} <- {m.font_path.name} "
                f"(mode={eff.mode}, size={size}, range={rng}{atlas}{match}, {len(m.characters)} chars)",
                file=sys.stderr,
            )
    if jobs:
        # Only fonts whose settings are valid would be generated; the others fail and are reported above.
        failing_note = f" {failing} font(s) have errors and would be skipped (see above)." if failing else ""
        print(f"DRY RUN - {planned} SDF font(s) would be generated.{failing_note}", file=sys.stderr)


def _run_sdf_jobs(jobs, args) -> tuple:
    """Generates every mapped font; returns (how many succeeded, how many failed). With --strict one failure raises."""
    if not jobs:
        return 0, 0
    from core.identity import format_ref
    from core.object_preview import get_row_name
    from core.sdf_generator import SDFGenerationError, add_characters_to_font_asset
    from core.sdf_map import FontMapError

    total = sum(len(j.mappings) for j in jobs)
    succeeded = failed = done = 0
    verbose = getattr(args, "verbose", False)
    # Generation can take a while per font (msdf-atlas-gen + packing), so the header says it started and
    # each font's line is begun ("[1/2] ", no newline) BEFORE its work and finished with "ok: ..." /
    # "error: ..." afterwards — one line per font, and a long one still shows how far it has got.
    # The generator's notes (height matching, bold spacing, characters brought over, ...) are details:
    # shown only with -v/--verbose.
    print(f"Generating SDF for {total} font(s)...", file=sys.stderr)
    for job in jobs:
        for m in job.mappings:
            row, name = m.row, get_row_name(m.row)
            done += 1
            print(f"[{done}/{total}] ", end="", file=sys.stderr, flush=True)
            try:
                eff = _sdf_effective(m)
                result = add_characters_to_font_asset(
                    row["obj_ref"], str(m.font_path), m.characters, mode=eff.mode,
                    point_size_override=eff.point_size, point_size_fit=eff.point_size_fit,
                    pxrange_override=eff.pxrange,
                    atlas_width_override=eff.atlas_width, atlas_height_override=eff.atlas_height,
                    match_original_height=eff.match_height,
                    include_existing_characters=eff.add_missing,
                )
            except (SDFGenerationError, FontMapError) as e:
                failed += 1
                print(f"error: {format_ref(row)} {name!r}: {e}", file=sys.stderr)
                continue
            except Exception as e:
                failed += 1
                print(f"error: {format_ref(row)} {name!r}: {e}", file=sys.stderr)
                if getattr(args, "verbose", False):
                    traceback.print_exc(file=sys.stderr)
                continue

            if result.added_count == 0:
                failed += 1
                if result.run_error:
                    # The whole run failed (typically: the characters don't fit the fixed atlas) —
                    # already a complete sentence naming the atlas/size and the ways out.
                    print(f"error: {format_ref(row)} {name!r}: generation failed: {result.run_error}", file=sys.stderr)
                else:
                    skipped = sum(1 for r in result.results if not r.added)
                    print(
                        f"error: {format_ref(row)} {name!r}: 0/{len(m.characters)} characters added "
                        f"({skipped} already present/unavailable)",
                        file=sys.stderr,
                    )
                if getattr(args, "verbose", False):
                    print(result.summary_text(), file=sys.stderr)
            else:
                succeeded += 1
                print(f"ok: {format_ref(row)} {name!r}: added {result.added_count}/{len(m.characters)}", file=sys.stderr)
                if verbose:
                    for note in result.notes:
                        print(f"    {note}", file=sys.stderr)

    print(f"Generated SDF for {succeeded}/{total} font(s)", file=sys.stderr)
    if failed:
        print(f"  {failed} failed", file=sys.stderr)
        # Same rule as for patches (see cmd_import): --strict stops everything, otherwise cmd_import ends with an error
        # after the fonts that did generate were saved.
        if getattr(args, "strict", False):
            raise CommandError(f"{failed} font(s) failed to generate - nothing was saved (--strict)")
    return succeeded, failed


def _report_backup(folder) -> None:
    from core.backup import backups_total_size, folder_size
    mb = lambda n: f"{n / 1024 ** 3:,.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:,.1f} MB"
    print(f"\nBackup of the originals: {folder} ({mb(folder_size(folder))}; "
          f"all backups take {mb(backups_total_size(folder.parent))})", file=sys.stderr)


def _backup_kwargs(args) -> dict:
    """--backup / --backup-dir (the latter implies the former) as _perform_save() keywords."""
    backup_dir = getattr(args, "backup_dir", None)
    return {"backup": bool(getattr(args, "backup", False) or backup_dir), "backup_dir": backup_dir,
            "backup_keep": getattr(args, "backup_keep", 1)}


def _perform_save(session: CliSession, save_as: Optional[str], quiet: bool, dry_run: bool,
                  backup: bool = False, backup_dir: Optional[str] = None, backup_keep: int = 1) -> None:
    """The actual save — shared by the standalone `save` command and `import`'s
    optional --save-as/--in-place chaining (see cmd_import: a one-shot
    import's edits only exist in this process's memory, so a one-shot workflow
    that wants them to survive has to save in the SAME invocation, not a
    separate later one)."""
    groups = find_modified_roots(session.rows)
    if not groups:
        raise CommandError("nothing modified - no objects have pending edits")
    read_only = getattr(session.env, "source_read_only_reason", "")
    if read_only and not save_as:
        raise CommandError(f"cannot overwrite the original: {read_only} Pass -A/--save-as PATH instead.")

    if dry_run:
        print("DRY RUN - nothing will be written.", file=sys.stderr)
        base_dir = compute_base_dir(session.load_mode, session.selected_dir, session.selected_files, session.env)
        for root_file, rows in groups:
            orig = original_path(root_file)
            name = Path(orig).name if orig else (getattr(root_file, "name", "") or "?")
            if save_as:
                dest = resolve_custom_dest(Path(orig) if orig else Path(name), base_dir, Path(save_as))
                print(f"  would write: {name} ({len(rows)} object(s)) -> {dest}", file=sys.stderr)
            else:
                extra = " after backing it up" if backup else ""
                print(f"  would overwrite: {orig or name} ({len(rows)} object(s)){extra}", file=sys.stderr)
        return

    def report_progress(status: str, current: int, total: int) -> None:
        if not quiet:
            bar = output.render_bar(current, total)
            pct = int(current / total * 100) if total else 100
            line = f"\r[{bar}] {pct:3d}%  {status}"
            print(line.ljust(130), end="", file=sys.stderr, flush=True)
            if current >= total:
                print(file=sys.stderr)

    if save_as and backup:
        # Nothing is overwritten with --save-as, so there is nothing to back up; saying so beats a silent no-op
        # (a script that passes --backup expecting a safety net would otherwise think it has one).
        print("warning: --backup/--backup-dir does nothing for the files saved with --save-as "
              "(no original is overwritten)", file=sys.stderr)

    try:
        if save_as:
            base_dir = compute_base_dir(session.load_mode, session.selected_dir, session.selected_files, session.env)
            count, _rows = save_to_custom_path(groups, Path(save_as), base_dir, report_progress)
            print(f"Saved {count} file(s) to {save_as}", file=sys.stderr)
        else:
            # Resolved BEFORE prepare_overwrite(): that call closes every modified root's
            # own handle, and reading PlayerSettings through a closed reader fails
            # ("operation forbidden on released memoryview") — the version would silently
            # be missing from the backup record. commit_overwrite() runs with the
            # Environment already gone (see its own docstring on game_version).
            from core.loader import resolve_game_version
            game_version = resolve_game_version(session.env) if session.env is not None else ""
            prepared = prepare_overwrite(groups, report_progress)
            # Every file of this Environment, not just the modified roots — see
            # core.save_manager.release_environment() (a shell session that loads
            # again afterwards would otherwise keep stale mappings of files it never
            # modified).
            release_environment(session.env)
            count = commit_overwrite(
                prepared, report_progress, make_backup=backup,
                backup_root=Path(backup_dir) if backup_dir else None, backup_keep=backup_keep,
                on_backup=_report_backup, game_version=game_version)
            print(f"Overwrote {count} file(s) in place.", file=sys.stderr)
            # Every root's own OS handle was deliberately closed by
            # prepare_overwrite() — this session's Environment is now
            # permanently unusable, exactly like the GUI's post-overwrite
            # reload (see CliSession.clear()'s own docstring).
            session.clear()
            print("Session data cleared - `load` again to keep working.", file=sys.stderr)
    except SaveError as e:
        raise CommandError(str(e))
    except OperationCancelled:
        raise CommandError("cancelled")


# ---------------------------------------------------------------------------
# cab — a single bundle, independent of the main load/rows above (matches the
# GUI's CabBrowserDialog being its own separate Environment, not part of the
# main table). Flat: `cab open` sets session.cab; every other `cab` verb acts
# on it directly rather than through a nested sub-prompt.
# ---------------------------------------------------------------------------

def cmd_cab_open(args, session: CliSession) -> None:
    try:
        session.cab = CabArchive.open(args.bundle)
    except CoreOperationError as e:
        raise CommandError(str(e))
    session.cab_path = args.bundle
    print(f"Opened {Path(args.bundle).name}: {len(session.cab.bundle.files)} entries.", file=sys.stderr)


def _require_cab(session: CliSession) -> CabArchive:
    if session.cab is None:
        raise CommandError("no bundle open - run `cab open BUNDLE_PATH` first")
    return session.cab


def cmd_cab_list(args, session: CliSession) -> None:
    cab = _require_cab(session)
    rows = [
        {"entry": name, "size": size, "objects": count if count is not None else "-"}
        for name, size, count in cab.entries()
    ]
    if args.limit:
        rows = rows[: args.limit]
    if args.format == "json":
        output.print_json(rows)
    else:
        output.print_table(rows, ["entry", "size", "objects"])


def cmd_cab_view(args, session: CliSession) -> None:
    cab = _require_cab(session)
    cab.ensure_environment()
    try:
        parsed_entry, rows = cab.view_entry(args.entry)
    except Exception as e:
        raise CommandError(f"{args.entry}: {e}")
    if rows is None:
        print(f"{args.entry}: contains no objects - nothing to view.", file=sys.stderr)
        return
    output.print_table([output.row_to_dict(r) for r in rows], output.DEFAULT_COLUMNS)


def cmd_cab_export(args, session: CliSession) -> None:
    cab = _require_cab(session)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    def progress(current, total):
        if not args.quiet and total:
            bar = output.render_bar(current, total)
            pct = int(current / total * 100)
            print(f"\r[{bar}] {pct:3d}%  {current:,}/{total:,} bytes".ljust(90), end="", file=sys.stderr, flush=True)

    try:
        if args.entry:
            written = cab.export_entry(args.entry, out_dir / args.entry, progress_callback=progress)
            print(f"\nExported {args.entry} ({written:,} bytes) to {out_dir}", file=sys.stderr)
        else:
            count = cab.export_all(out_dir, progress_callback=progress)
            print(f"\nExported {count} entries to {out_dir}", file=sys.stderr)
    except (CoreOperationError, OperationCancelled) as e:
        raise CommandError(str(e))


def cmd_cab_rebuild(args, session: CliSession) -> None:
    cab = _require_cab(session)

    replacements = {}
    if args.from_folder:
        replacements.update(cab.match_files_for_import(args.from_folder))
    for pair in args.set or []:
        if "=" not in pair:
            raise CommandError(f"--set expects ENTRY=PATH, got: {pair!r}")
        entry, _, path = pair.partition("=")
        replacements[entry] = path

    if not replacements:
        raise CommandError("nothing to rebuild with - pass --from-folder and/or --set ENTRY=PATH")

    collisions = CabArchive.find_import_all_collisions(replacements)
    if collisions:
        for a, b, path in collisions:
            print(f"  warning: {a!r} and {b!r} both resolve to the same file: {path}", file=sys.stderr)

    def progress(*info):
        # rebuild_and_save's callback shape depends on mode: (phase, current,
        # total) for "disk" (see BundleFile.save_to_file), nothing at all for
        # "memory" (bundle.save() has no internal checkpoints — see that
        # method's own docstring on why "memory" can't report progress or be
        # cancelled mid-way).
        if args.quiet:
            return
        if len(info) == 3:
            phase, current, total = info
            bar = output.render_bar(current, total)
            pct = int(current / total * 100) if total else 100
            line = f"\r[{bar}] {pct:3d}%  {phase}: {current:,}/{total:,}"
        else:
            line = f"\r{' '.join(str(x) for x in info)}"
        print(line.ljust(90), end="", file=sys.stderr, flush=True)

    def should_cancel():
        return False  # SIGINT handling for `cab rebuild` isn't wired up separately from cmd_load's

    try:
        count = cab.rebuild_and_save(
            args.out, replacements, mode=args.mode, packer=args.packer,
            progress_callback=progress if args.mode == "disk" else None,
            should_cancel=should_cancel if args.mode == "disk" else None,
        )
    except (CoreOperationError, OperationCancelled) as e:
        raise CommandError(str(e))
    print(f"\nRebuilt with {count} replaced entry(ies) -> {args.out}", file=sys.stderr)


def dispatch_cab(args, session: CliSession) -> None:
    """Shared by one-shot mode and the REPL — one-shot subcommands other than
    `open` optionally carry --bundle (see _add_cab_bundle_arg) to open-then-act
    in a single invocation; the REPL never has --bundle at all (getattr default
    covers that), since `cab open` already set session.cab earlier."""
    if getattr(args, "bundle", None) and args.cab_command != "open":
        cmd_cab_open(args, session)

    if args.cab_command == "open":
        cmd_cab_open(args, session)
    elif args.cab_command == "list":
        cmd_cab_list(args, session)
    elif args.cab_command == "view":
        cmd_cab_view(args, session)
    elif args.cab_command == "export":
        cmd_cab_export(args, session)
    elif args.cab_command == "rebuild":
        cmd_cab_rebuild(args, session)


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _require_loaded(session: CliSession) -> None:
    if not session.loaded:
        raise CommandError("nothing loaded - run `load` first (or start `shell --folder ...`)")


def _resolve_single(session: CliSession, ref: str, source_override: Optional[str]) -> RowItem:
    try:
        source, path_id = parse_ref(ref)
    except ObjectRefError as e:
        raise CommandError(str(e))
    source = source_override or source
    try:
        return resolve_ref(session.rows, path_id, source, session.env)
    except ObjectRefError as e:
        raise CommandError(str(e))
