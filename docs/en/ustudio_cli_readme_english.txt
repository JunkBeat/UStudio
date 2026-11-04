================================================================================
UStudio — Command Line Interface (CLI): Reference
================================================================================

Usage:
    ustudio_cli <command> [options]

Help for any command:
    ustudio_cli help export
    ustudio_cli export --help

--------------------------------------------------------------------------------
QUICK START
--------------------------------------------------------------------------------

    # Display the first 10 AudioClip objects in the console
    ustudio_cli list -F data.unity3d --type AudioClip --limit 10

    # Export all game textures to the ./textures folder
    ustudio_cli export -p "Game_Data" --type Texture2D -o ./textures

    # Inspect the contents of a single object
    ustudio_cli inspect -F data.unity3d level0:1

    # Export -> edit -> import (saving the result to ./output)
    ustudio_cli export -F data.unity3d --id level0:1 --mode json -o ./patch
    (edit the file from ./patch in any text editor)
    ustudio_cli import -F data.unity3d ./patch --save-as ./output

Original files are untouched: --save-as always writes to a new folder.

--------------------------------------------------------------------------------
1. TWO MODES OF OPERATION
--------------------------------------------------------------------------------

Single command — loads data, performs one action, and terminates.
Convenient for scripts:

    ustudio_cli list -F data.unity3d --type AudioClip

Interactive shell — loads data ONCE, after which you can execute any number 
of commands without reloading. For large files, this is significantly faster, 
as single-command mode reloads data with every command call.

    ustudio_cli shell -F data.unity3d
    ustudio [data.unity3d]> list --type Texture2D --limit 5
    ustudio [data.unity3d]> inspect level0:1 --dump typed
    ustudio [data.unity3d]> exit

The shell uses the same commands but without loading options, as data is already 
loaded. Help in shell: `help <command>` (the --help flag is not used there).

--------------------------------------------------------------------------------
2. GENERAL RULES
--------------------------------------------------------------------------------

OUTPUT
  Command results (tables, JSON, CSV, object dumps) go to stdout — they can be 
  redirected to a file or piped to another program:
      ustudio_cli list -F data.unity3d --format json > result.json
  Progress, warnings, and error messages go to stderr and are not included in 
  the result output. The -q (--quiet) flag hides the progress bar.
  If output is redirected (to a file or another program), it is always UTF-8, 
  regardless of the console code page.
  The -v (--verbose) flag is specified BEFORE the command and enables detailed 
  logging: full error stack traces and SDF font generator notes:
      ustudio_cli -v import -F data.unity3d ./patch

RETURN CODES
  0 — success (including when some objects are skipped for expected reasons, 
      e.g., an empty texture during export);
  1 — execution error (nothing loaded, object not found, ambiguous reference, 
      at least one import patch failed to apply, etc.), error text in stderr 
      (if only part of patches failed and --strict is omitted, the rest are saved);
  2 — invalid command-line arguments.

OBJECT REFERENCES
  PATH_ID is unique only within a single file: the same PATH_ID can appear 
  in multiple files. Therefore, references come in three forms:
      1                       — PATH_ID, if it exists in exactly one file;
      level0:1                — SOURCE:PATH_ID, i.e., "file:PATH_ID";
      GameB/Data/level0:1     — if files with identical names exist in different 
                                folders (multiple games): add part of the path 
                                before the filename (case-insensitive).
  If a reference is ambiguous, the command will fail with an error and list all 
  matching files — it will never arbitrarily select the "first match".

--------------------------------------------------------------------------------
3. LOADING OPTIONS
--------------------------------------------------------------------------------

Common options for load, shell, list, inspect, export, import, and save commands.

  -p, --folder PATH
      Load an entire folder.
          ustudio_cli list -p "C:\Games\MyGame\MyGame_Data" --type Font
      For macOS games, specify the application bundle path (X.app):
          ustudio_cli list -p "MyGame.app" --type Font
      Nintendo Switch game files must first be extracted with another tool, 
      then specify the unpacked folder:
          ustudio_cli list -p "C:\Games\KAMIKO" --type Font

  -F, --files PATH
      Load a specific file. Can be repeated: -F level0 -F level1.
      Cannot be combined with -p.

  If neither -p nor -F is specified:
      The command searches for a "*_Data" folder in the CURRENT directory and 
      loads it (the path found is output to stderr). The folder must contain Unity 
      data, not just be named "*_Data"; if no suitable folder exists or multiple 
      are found, the command will report this and make no selection.
      Where commands can overwrite originals (import --in-place, save without 
      --save-as, shell), -p or -F is mandatory.

  -a, --all
      Load objects of ALL types. Without this flag, only major types appear 
      (textures, audio, fonts, MonoBehaviour, GameObject, etc.); 
      e.g., Transform objects will be omitted.

  -x, --exclude FOLDER
      Skip the specified folder when loading an entire directory 
      (can be repeated) — for example, to exclude backup folders inside 
      the game path.

  --deps FOLDER
      Additionally search for dependencies in bundle assets within this folder 
      (can be repeated). Useful when loading a SINGLE bundle via -F whose scripts 
      reside in adjacent bundles (common in Unity Addressables, folder 
      StreamingAssets/aa/<Platform>): without --deps, script names appear as 
      "Unknown". The folder is scanned once before loading (fast header read). 
      When loading an entire folder (-p), adjacent bundles are detected automatically.
          Example command:
          ustudio_cli list -F "aa/StandaloneWindows64/localization_en_assets_all.bundle" --script StringTable --deps "aa/StandaloneWindows64"

  --assembly FOLDER
      Specify the path to the Managed folder (containing script DLLs) — used to 
      resolve MonoBehaviour field names and types. Usually auto-detected near 
      the *_Data folder; specify manually if game files are separated or if 
      loading assemblies dumped via IL2CppDumper.
          ustudio_cli inspect 179 -F "resources.assets" --assembly "Game_Data/Managed"

  -u, --fallback-version VERSION
      Specify the Unity version to use if it is missing in the file header or 
      if game developers intentionally obfuscated the headers.
      Example input: "2019.4.15f1"

  -k, --cn-key KEY
      Specify a 16-byte AssetBundle decryption key for games built with the 
      Chinese Unity engine variant. No brute-force.

  -T, --threshold NUMBER   (default: 2000000 <objects>)
      Warning threshold trigger value.
  -L, --large continue
      If loaded data contains more objects than the threshold, confirmation is 
      required. In single mode, passing -L continue bypasses the prompt (without 
      it, the command aborts with an error instead of hanging); in shell mode, 
      a "continue? y/n" prompt is shown. Without -a, only major types are loaded; 
      other objects are skipped and written unchanged during saves.
          ustudio_cli export -p "Game_Data" --type AudioClip -L continue

  -c, --collision {keep_first,raise}   (default: keep_first)
      Handling strategy for files sharing identical names (e.g., two 
      resources.assets in a multi-game folder). All such files are loaded regardless; 
      resources and references select the closest file relative to the object. 
      Affects lookup EXCLUSIVELY when searching by name alone (e.g., "level0" without 
      specifying the game path):
        keep_first — takes the first matching file found (default);
        raise      — aborts loading on the first name collision.

  -q, --quiet
      Hide progress indicators.

--------------------------------------------------------------------------------
4. COMMANDS
--------------------------------------------------------------------------------

--------------------------------------------------------------------------------
load — load and exit
--------------------------------------------------------------------------------
Applies loading parameters only. Useful for verifying that a directory loads correctly.

    ustudio_cli load -p "Truck-kun_Data" --all

--------------------------------------------------------------------------------
shell — load once and work interactively
--------------------------------------------------------------------------------
Applies loading parameters, then displays prompt "ustudio [name]>". Exit via exit or quit.

    ustudio_cli shell -p "Game_Data" --fallback-version 2021.3.0f1

--------------------------------------------------------------------------------
list — display object listing
--------------------------------------------------------------------------------
Loading parameters plus:

  -t, --type TYPES         Comma-separated types: "Texture2D" or
                            "Texture2D,AudioClip".
  -s, --script NAME        Script m_ClassName (for MonoBehaviour).
                            Matches ALL scripts with this class name; for exact 
                            matches, use "m_Namespace.m_ClassName".
  -n, --name-contains STR  Substring match in object name (case-insensitive).
  -S, --source NAME        Exact filename (or bundle entry name), e.g.,
                            "level0" or "sharedassets0.assets".
  -m, --modified           Display only objects containing unsaved edits.
  -r, --sort COLUMNS       Specify sorting parameters (see below).
  -f, --format {table,json,csv}   Output format (default: table).
  -l, --limit NUMBER       Limit the number of rows output to the console.
  -o, --out FILE           Write results to a file instead of stdout.
  --sdf                    Display SDF fonts (see below).

Sorting -r/--sort. Columns: path_id, name, type, script_name, source, size,
modified. Default is ascending order; prefix "-" for descending order. 
Comma-separated columns define priority (ties in the first column sorted by second). 
String comparisons are case-insensitive.
IMPORTANT: options starting with "-" must use "=": --sort=-size 
(not --sort -size, which interprets "-size" as a command flag).

SDF Fonts (--sdf). Displays TextMeshPro fonts (TMP_FontAsset) alongside their 
associated material, atlas texture, and source font file. Filters -t/-s/-n/-S/-m/
-r do not apply, but -f/-l/-o are active. Table headers display references in 
brackets as SOURCE:PATH_ID — use this string for `export --sdf --id`. If materials 
or textures cannot be resolved, error reasons are shown.

Examples:
    ustudio_cli list -F data.unity3d --type AudioClip --limit 10
    ustudio_cli list -F data.unity3d --script "PlayerController" --format json
    ustudio_cli list -F data.unity3d --name-contains "button" --type Sprite
    ustudio_cli list -F data.unity3d --modified

    # Save object listing to a CSV file:
    ustudio_cli list -p "Game_Data" --type Texture2D --format csv -o textures.csv

    # List objects sorted by name A-Z:
    ustudio_cli list -F data.unity3d --sort name

    # List objects sorted by name Z-A (note the "=" character):
    ustudio_cli list -F data.unity3d --sort=-name

    # Sort first by type (A-Z), then by size (descending):
    ustudio_cli list -F data.unity3d --sort=type,-size

    # Display list of all SDF fonts:
    ustudio_cli list -F data.unity3d --sdf

--------------------------------------------------------------------------------
inspect — examine contents of a single object
--------------------------------------------------------------------------------
Loading parameters plus:

  ref                      Object reference: PATH_ID or SOURCE:PATH_ID.
  -S, --source NAME        File target if PATH_ID exists across multiple archives 
                           (alternative to specifying source via colon in ref).
  -d, --dump {typed,json,hex}   Dump formatting mode (default: typed)
        typed — "Type Name = value", one line per field;
        json  — formatted JSON dump;
        hex   — first 4096 bytes of raw object data in hex view.

Examples:
    ustudio_cli inspect -F data.unity3d level0:1
    ustudio_cli inspect -F data.unity3d level0:1 --dump json
    ustudio_cli inspect -F data.unity3d 1 --source level0

    # If PATH_ID exists in multiple files, options will be shown:
    ustudio_cli inspect -F data.unity3d 1
      -> error: PATH_ID 1 exists in multiple files, specify source:path_id

--------------------------------------------------------------------------------
export — export objects to folder
--------------------------------------------------------------------------------
Loading parameters, list filters (-t/-s/-n/-S) plus:

  -i, --id REF         Export exactly one object by ID (overrides filters).
  -m, --mode {typed,raw,content-raw,json}   Export mode (default: typed)
        typed        — standard asset format: PNG for textures, WAV for audio,
                       fonts, text assets, etc.; falls back to JSON dump if 
                       type conversion is unsupported;
        json         — complete field tree dump (.dump.json extension);
        raw          — raw object binary data (.dump.bin extension);
        content-raw  — raw data from external resource stream 
                       (e.g., texture pixel buffer from .resS)
                       (.resdata.bin extension).
  -o, --out FOLDER     Output directory (default: ./UStudio_Assets).
  -w, --overwrite      Overwrite existing files.
  --strict             Return non-zero exit code if any single asset fails to 
                       export (expected skips — empty textures, silent audio — 
                       are not treated as errors).
  --group-by {none,type,source}
        Organize exported files into subdirectories under -o: none — flat directory 
        (default), type — subfolders by asset type (-o/Texture2D/), source — by 
        origin archives. Default value can be configured via: `config set 
        export_grouping type`.
  --sdf                Export SDF fonts completely (MonoBehaviour, material, 
                       texture, and referenced Font if available) under path  
                       SDF/<font_name>/ inside folder -o. When combined with 
                       -i — exports a single SDF font (requires TMP_FontAsset reference 
                       retrieved from `list --sdf` output); without -i — exports 
                       all detected SDF fonts. Filters and -m flag are ignored. 
                       Unresolved components are skipped with a notice.

Filenames follow the pattern "{name} #{path_id} ({source}).ext" — used by 
the import command to map modified files back to object targets. Do not rename files.

Examples:
    ustudio_cli export -F data.unity3d --type Texture2D -o ./textures
    ustudio_cli export -p "Game_Data" --type AudioClip --group-by source -o ./audio
    ustudio_cli export -F data.unity3d --id level0:1 --mode json -o ./dump
    ustudio_cli export -F data.unity3d --name-contains "logo" --type Texture2D,Sprite

    # Export a single SDF font (using TMP_FontAsset reference from `list --sdf`):
    ustudio_cli export -F data.unity3d --sdf --id "sharedassets0.assets:2646" -o ./out

    # Export all SDF fonts into path SDF/<font name>/:
    ustudio_cli export -F data.unity3d --sdf -o ./out

--------------------------------------------------------------------------------
import — apply patch folder
--------------------------------------------------------------------------------
Reads files from a directory, matches targeted objects by filename, and updates 
their content. Filenames must retain export naming conventions: 
"{name} #{path_id} ({source}).ext". Modification type is determined by extension:

    .dump.json     — complete object fields (JSON dump);
    .dump.bin      — raw object bytes (Raw dump);
    .resdata.bin   — external resource raw stream (Raw Content);
    .png           — image source for Texture2D / Sprite;
    .wav           — audio source for AudioClip;
    .mp4 / .webm   — video source for VideoClip;
    .ttf / .otf    — font data for Font;
    .txt / .json / .bin — text contents for TextAsset.

If multiple modification files target a single object within the folder, they apply 
in order: .dump.bin -> .dump.json -> .resdata.bin -> .png/.wav/... — meaning 
edited PNG/WAV files take precedence over earlier dumps.

Patches targeting objects missing from loaded archives are reported. This 
frequently occurs after game updates when asset IDs shift. The command logs a line 
for every unmatched file:

    unmatched: Name #12345 (sharedassets1.assets).dump.bin: no object #12345 in 'sharedassets1.assets'
    1 patch file(s) matched no loaded object and will NOT be applied (...)

Summary counts are reported at exit: "Applied 2/3 patch(es)" and "1 unmatched". 
Valid patches apply normally. If no files match loaded objects, execution aborts. 
With --strict, any unmatched file causes execution to abort immediately without saving 
changes (non-zero exit code). In `--dry-run` mode, "DRY RUN - N match(es) would be applied" 
counts matched targets only.

Targeted objects are validated against patch names. For MonoBehaviour objects, both 
script class and asset name are verified ("Script.Name"): game updates frequently assign 
shifted IDs to adjacent components sharing class types. If asset names differ, edits are 
still accepted if self-consistency is established in dump data (.dump.json): 
the object matches the name declared within the patch itself (re-applying a mod) or points 
to an identical GameObject reference. For unnamed assets ("Script.Unnamed"), 
validation cannot compare names: such edits are skipped if adjacent patches in the 
same file fail validation due to index shifts. Skipped patches log "skipped: ..." 
reasons; --force overrides validation.

If a patch targets a valid object but fails processing (corrupt file, layout mismatch, 
encoding error), remaining patches proceed normally and save. The summary reports failed 
edits and exits with status 1 (successful edits remain saved). The same rules apply 
to SDF font generation tasks listed in sdf_map.txt. 
Require atomic execution for mod installers or automated scripts? Add --strict: on 
any error, no changes are committed or saved.
Exception (including --strict mode): external resource streams for AudioClip / 
VideoClip (--res-mode original) write directly to target .resource / .resS files 
prior to final save. If import is cancelled, these files have already been modified; 
error logs list affected files, and with --backup enabled, original contents are 
safely stored in backup storage.

For .dump.bin, structural compatibility is checked: files must not be empty or 
truncated, layout must match object structure, and MonoBehaviour script references 
must match current object declarations (preventing cross-script or version mismatches). 
Full structure verification occurs when all assemblies are loaded (-p); with --partial, 
only script reference IDs are validated.

Loading parameters plus:

  FOLDER               Patch files directory (required argument). Validated BEFORE 
                       loading data: if no matching patch files exist, execution 
                       aborts immediately.
  -d, --dry-run        Preview scheduled changes without modifying data.
  --strict             Strict execution mode for scripts and mod installers. If any 
                       patch fails, cannot match target ID (see "unmatched" above), 
                       is skipped due to name/script mismatch, or an sdf_map.txt target 
                       fails to resolve, execution aborts with exit code 1 without 
                       saving modifications. Without --strict, valid patches apply 
                       and issues are summarized.
  --force              Apply patches even if asset name or script reference in filename 
                       mismatches loaded targets (e.g., target PATH_ID reassigned following 
                       game updates). Default behavior skips mismatched patches.
  --partial            Partial load mode: loads only archive files referenced in patch 
                       filenames instead of loading the full directory specified in -p. 
                       Significantly improves import performance in large installations. 
                       Supported only in single command mode with -p. If a file path 
                       cannot be resolved deterministically (missing or ambiguous due 
                       to duplicate filenames — resolve via -x), the command reports 
                       the cause and falls back to full directory load. Game assembly 
                       scripts are not parsed during partial loads; MonoBehaviour script 
                       names are not cross-checked ("script unresolved"); .dump.bin files 
                       are verified by script reference ID only.

  Textures:
  --tex-mode {match_original,manual}
        match_original — preserve existing texture format (default);
        manual         — explicitly set format via --tex-format.
  --tex-format FORMAT  Target format for --tex-mode manual:
        uncompressed:              RGBA32 (with alpha), RGB24, Alpha8
        desktop/consoles (BC/DXT): DXT1 (no alpha), DXT3, DXT5, BC4, BC5, BC7
                                   (highest quality; Unity 5+ required)
        mobile platforms:          ETC_RGB4, ETC2_RGB, ETC2_RGBA8, ASTC_RGBA_4x4 (higher
                                   quality), ASTC_RGBA_8x8 (smaller size), ATC_RGB4, ATC_RGBA8
        The specified format is applied even if incompatible with the target system (e.g., 
        DXT format applied to mobile assets). Write format names exactly as shown (case-sensitive). 
        Typographical errors will NOT raise errors; texture formats will remain unchanged.
  --tex-quality {medium,high}   Deprecated: textures are always compressed using maximum quality settings. 
                                Retained for backward compatibility.

  Audio:
  --audio-quality NUMBER   Encoding quality level, 0–100 (0 — default, 100 — maximum quality).

  Storage target for AudioClip / VideoClip (and external resource assets):
  --res-mode {original,custom_resource}
        original        — write to original asset resource stream (default);
        custom_resource — write to isolated resource file specified via --res-name 
                          to prevent original resource file growth across multiple imports.
  --res-name NAME      Filename for isolated resource storage (used only with --res-mode custom_resource). 
                       File is created on disk upon save execution.

  Video:
  --transcode                          Transcode video streams before packaging (default: disabled; 
                                       embeds source container directly).
  --transcode-to {original,h264,vp8}   Target container codec; original matches target clip 
                                       encoding (falls back to h264 with warning on conflict).
  --transcode-quality NUMBER   Transcoding quality scaling, 0 to 100. 
                              Transcoded output assets are written alongside 
                              patch files using suffix "_transcoded".

  Default option values for these parameters are saved in `config` settings (see 
  below), allowing persistence across CLI invocations.

  Output persistence:
  Modifications occur in process memory; in single-command mode without output flags, 
  results are written automatically to a NEW output folder ./UStudio_Packed 
  (leaving originals untouched):
  -A, --save-as FOLDER Save modifications to specified SEPARATE folder.
  --in-place           Overwrite original target files (game directory path must be 
                       explicitly set via -p or -F).
  -b, --backup         Create backups of original files prior to in-place overwrite 
                       (a new backup instance is created per save). On failure 
                       (e.g., insufficient storage), original files remain untouched. 
                       Backups store only files targeted for modification by the 
                       import session: modified container archives (.assets, bundles) 
                       and resource streams (.resource / .resS) written to directly 
                       during execution. Unmodified resources are not copied. 
                       Stored backups represent pre-modification states. 
                       Using --save-as suppresses backup creation (no files overwritten); 
                       a notice is displayed.
  --backup-dir FOLDER  Storage path for created backups (implicitly enables --backup): 
                       stores archive containers and external resource streams. 
                       Default path: %LOCALAPPDATA%\UStudio\backups, external to game 
                       directories to prevent loading within future CLI sessions.
  --backup-keep N      Number of recent secondary backup iterations retained alongside 
                       the initial base backup (default: 1). Base backup (pristine original) 
                       is permanently preserved; intermediate builds are pruned to conserve space.
  In shell mode, auto-save is disabled — sessions remain active, allowing delayed execution via save.

  Addressables support (StreamingAssets\aa directory): manifest catalogs 
  (catalog.json, catalog.bin, or catalog.bundle) store checksum signatures for 
  managed asset bundles. Modified bundles with legacy checksums fail runtime load checks. 
  Saving updated bundles automatically recalculates manifest signatures: --in-place overwrites 
  manifests (including them in backup targets), while --save-as outputs modified catalogs 
  alongside bundle copies. Copy manifest files along with asset bundles during manual deployment.

Examples:
    # Preview pending patch changes without committing updates:
    ustudio_cli import -F data.unity3d ./edited --dry-run

    # Apply updates and write output to target path:
    ustudio_cli import -F data.unity3d ./edited --save-as ./output

    # Apply updates in-place with original data backup:
    ustudio_cli import -F data.unity3d ./edited --in-place --backup

    # Partial loading mode for large project structures:
    ustudio_cli import -p "Game_Data" ./edited --partial --save-as ./output

    # Texture processing: re-encode streams using BC7 format:
    ustudio_cli import -F data.unity3d ./textures --tex-mode manual --tex-format BC7 --save-as ./output

    # High-quality audio import using external custom resource files:
    ustudio_cli import -F data.unity3d ./audio --audio-quality 90 --res-mode custom_resource --res-name my_audio.resource --save-as ./output

    # Ignore non-matching patches (default) or force patch application:
    ustudio_cli import -F data.unity3d ./edited --dry-run
    ustudio_cli import -F data.unity3d ./edited --force --save-as ./output


--------------------------------------------------------------------------------
save — commit modified data to storage
--------------------------------------------------------------------------------
Loading parameters plus:

  -A, --save-as FOLDER Save to NEW target path (originals remain untouched). 
                       Without this flag, source files are overwritten.
  -d, --dry-run        Simulate save actions without performing I/O operations.
  -b, --backup, --backup-dir FOLDER, --backup-keep N
                       Configure pre-write backup parameters identical to `import`.

If no object modifications exist in memory, execution fails ("nothing modified"). 
In single-command mode, import handles saving operations directly; save is 
primarily intended for interactive shell sessions:

    ustudio [data.unity3d]> import ./edited
    ustudio [data.unity3d]> list --modified
    ustudio [data.unity3d]> save --save-as ./output

Following in-place overwrite operations (without --save-as), loaded asset handles 
are closed; reload files to resume interactive operations within shell.

--------------------------------------------------------------------------------
SDF Font Generation (sdf_map.txt configuration) — EXPERIMENTAL
--------------------------------------------------------------------------------
No dedicated sub-command required: if a patch folder provided to import 
(including nested paths) contains `sdf_map.txt`, standard patching executes 
first, followed by TextMeshPro font generation (TMP_FontAsset) updating missing 
glyphs using targeted .ttf/.otf sources. Standard patch files are optional — 
a directory containing `sdf_map.txt` and font files is sufficient.

Experimental status: verify target builds via --dry-run or --save-as output 
before performing in-place overwrites.

    ustudio_cli import -F data.unity3d ./sdf_patches --dry-run
    ustudio_cli import -F data.unity3d ./sdf_patches --save-as ./output

--dry-run displays generation plans ("SDF <ref> 'name' <- font (mode=..., size=..., 
range=..., N chars)") without performing asset writes. Execution details display 
status per font asset:
    [1/2] ok: resources.assets:539 'LiberationSans SDF': added 182/183
To view generator output notes, append the -v flag.

Complete documentation covering sdf_map.txt formatting (all parameters, character 
mappings, syntax examples) is available in `sdf_map.md`. The following summary covers 
CLI execution context only.

Brief sdf_map.txt syntax example:
    "Arial SDF", "Other SDF" = font.ttf
    "Pixel SDF" = pixel.ttf, mode=full, size=fit, chars="ABCabc"

Character lookup sequence (evaluated in order): chars= parameter in line -> chars= 
in "default:" definition -> adjacent chars.txt file located beside sdf_map.txt. 
If all lookups fail, execution aborts with line reference errors.

The "default:" directive (maximum one entry allowed) sets fallback options for all 
unspecified font declarations. Parameters size, match_height, range, atlas, and add_chars 
defined in default lines apply exclusively to generation lines operating in `full` mode. 
Explicitly setting full-mode options on add/replace declarations raises validation errors. 
Parameter precedence: font declaration line -> "default:" line -> internal defaults 
(mode=add, original font point size and sharpness, match_height=on, add_chars=on).

Relative file paths (font files, character sets) resolve relative to the folder containing 
`sdf_map.txt`, enabling portable map configurations.

Declaring identical font assets across multiple lines using conflicting parameters 
triggers validation failures listing all parameter collisions. Unresolved font targets 
issue warnings (or execution errors under --strict). Using --partial alongside 
`sdf_map.txt` forces full folder loading, as mapped SDF assets may reside in 
unindexed archives.

--------------------------------------------------------------------------------
cab — direct unity asset archive manipulation
--------------------------------------------------------------------------------
The `cab` command bypasses standard loader initialization: each sub-command requires 
an explicit -b/--bundle flag (single mode) or active container context set via 
`cab open` (shell mode).

  cab open PATH
      Open specified bundle asset. In shell mode, subsequent operations 
      (list/view/export/rebuild) apply to this target automatically.

  cab list [-b BUNDLE] [-f {table,json}] [-l NUMBER]
      List internal archive entries: entry name, binary size, object count.

  cab view [-b BUNDLE] -e ENTRY
      Parse target archive entry and display contained MonoBehaviour components in table format.

  cab export [-b BUNDLE] [-e ENTRY] [-o FOLDER] [-q]
      Export targeted entry (raw stream) or ALL internal entries if -e is omitted. 
      Default destination directory: ./UStudio_Assets.

  cab rebuild [-b BUNDLE] -o FILE [--from-folder FOLDER] [--set ENTRY=PATH ...]
              [--mode {memory,disk}] [--packer {none,lz4,lz4hc,lzma,original}] [-q]
      Reconstruct target bundle replacing entries with updated files 
      (bundles are rewritten completely per format specifications):
        --from-folder FOLDER — replace entry contents using matching filenames from folder;
        --set ENTRY=PATH     — replace specific entry stream (repeatable; overrides 
                              matching entries specified via --from-folder);
        --mode disk          — process rebuild using temporary storage (default); 
                              allows execution cancellation (Ctrl+C);
        --mode memory        — process entirely in system memory. Faster, but 
                              cannot be cancelled during packing;
        --packer             — target compression scheme (original preserves 
                              source bundle format).

Examples:
    ustudio_cli cab list --bundle data.unity3d --limit 10
    ustudio_cli cab view --bundle data.unity3d --entry level0
    ustudio_cli cab export --bundle data.unity3d --entry level0 -o ./out
    ustudio_cli cab export --bundle data.unity3d -o ./all_entries
    ustudio_cli cab rebuild --bundle data.unity3d --set level0=./new_level0 -o ./rebuilt.unity3d
    ustudio_cli cab rebuild --bundle data.unity3d --from-folder ./edited_entries -o ./rebuilt.unity3d --packer lz4

--------------------------------------------------------------------------------
backup — manage data backups
--------------------------------------------------------------------------------
Backups are created when specifying --backup (or --backup-dir) during in-place 
save operations (save, import --in-place). Sub-commands below do not load game files.

  backup list [--game NAME] [--backup-dir FOLDER]
      List stored backup entries: path, creation date, contained files, total volume. 
      Square brackets display target game name and version recorded at creation time 
      if resolved. Use --game to filter results for specific titles (substring 
      match, case-insensitive); exact game name keys are listed in `backup list` output.

  backup restore [BACKUP_FOLDER] [-f NAME]... [--copy DATE] [--game NAME] [-d]
                 [--relocate OLD=NEW]... [--backup-dir FOLDER]
      Restores target files to original paths. Omitting BACKUP_FOLDER restores 
      the OLDEST recorded state (pristine original asset); passing BACKUP_FOLDER 
      restores files corresponding to that specific session.
        -f, --file NAME  restore target file matching name or path 
                         (can be repeated);
        --copy DATE      select backup matching target timestamp instead of oldest instance 
                         ("2026-09-24" or "2026-09-24 19:32");
        --game NAME      restrict restore target to specific game title;
        -d, --dry-run    preview restore targets without modifying storage;
        --relocate OLD=NEW
                         handle moved installations: restore files to NEW target path 
                         instead of stored OLD location (OLD matches paths reported by 
                         `backup list`; option can be repeated).
      Current files are backed up automatically to a new backup entry prior to 
      restoration, allowing restore actions to be reverted. File replacements are 
      staged alongside target paths and swapped atomically to prevent partial writes; 
      locked files yield execution errors.

      Files whose base directories no longer exist (e.g., relocated installations) 
      are skipped: restoration halts without writing files, recommending --relocate. 
      Missing directories are not created automatically to prevent restoring files 
      to obsolete locations.

      If target filenames (-f resources.assets) exist across backups of multiple titles, 
      the tool avoids ambiguous operations and lists options: specify full file paths 
      or append --game filters.

      IMPORTANT: backups capture file states at reservation time. Automatic game 
      updates applied after backup creation make stored originals outdated. 
      Game updates cannot be distinguished automatically from user edits. Verify game 
      versions associated with backups using `backup list`.

Examples:
    # Display stored backup listings and storage metrics:
    ustudio_cli backup list

    # Display backups filtered by game title:
    ustudio_cli backup list --game Petscop

    # Execute in-place edit with backup, then restore original assets:
    ustudio_cli import -F data.unity3d ./edited --in-place --backup
    ustudio_cli backup restore

    # Preview restore execution targets:
    ustudio_cli backup restore --dry-run

    # Restore a specific file by filename:
    ustudio_cli backup restore -f resources.assets

    # Restore backup data for target file corresponding to creation date:
    ustudio_cli backup restore -f resources.assets --copy 2026-09-24

    # Resolve filename collisions across titles via game filter or explicit path:
    ustudio_cli backup restore -f resources.assets --game Petscop
    ustudio_cli backup restore -f "C:\Games\Petscop\Petscop_Data\resources.assets"

    # Restore all backup files for a target game title:
    ustudio_cli backup restore --game Petscop

    # Relocate restoration targets to new installation directories:
    ustudio_cli backup restore --relocate "C:\Games\Petscop=D:\Games\Petscop"

    # Restore specific backup folder instance (path copied from `backup list` output):
    ustudio_cli backup restore "C:\Users\me\AppData\Local\UStudio\backups\2026-09-24_19-32-01"

--------------------------------------------------------------------------------
config — manage application defaults
--------------------------------------------------------------------------------
Configuration options are stored in %LOCALAPPDATA%\UStudio\cli_settings.json.

  config get [KEY]         Read specified configuration key or return all settings (JSON).
  config set KEY VALUE     Update setting key and commit changes to disk.

Supported setting keys: fallback_version, unity_cn_key, object_count_threshold,
cab_collision_policy, excluded_folders,
texture_import_format_mode, texture_import_manual_format, audio_import_quality,
resource_target_mode, resource_name, video_transcode_target,
video_transcode_quality, export_grouping.

Examples:
    ustudio_cli config get
    ustudio_cli config get texture_import_format_mode
    ustudio_cli config set texture_import_format_mode manual
    ustudio_cli config set resource_target_mode custom_resource
    ustudio_cli config set export_grouping type

--------------------------------------------------------------------------------
cache — manage extracted APK/OBB archive cache
--------------------------------------------------------------------------------
    ustudio_cli cache            display cached instances and storage usage
    ustudio_cli cache --clear    clear all cached archive contents

Refer to "Android" section below for details.

--------------------------------------------------------------------------------
help — command reference documentation
--------------------------------------------------------------------------------
    ustudio_cli help                 display general command list
    ustudio_cli help export          display command documentation (equivalent to export --help)

--------------------------------------------------------------------------------
5. END-TO-END EXAMPLE: export -> edit -> import -> verify
--------------------------------------------------------------------------------

    # 1. Export target object to JSON dump format:
    ustudio_cli export -F data.unity3d --id level0:1 --mode json -o ./patch

    # 2. Modify ./patch/logo #1 (level0).dump.json using any text editor — 
    #    e.g., update field value for "m_Name".

    # 3. Apply updates and write output to a new target directory:
    ustudio_cli import -F data.unity3d ./patch --save-as ./output

    # 4. Verify output changes by examining patched object structure:
    ustudio_cli inspect -F ./output/data.unity3d level0:1 --dump json

Source data.unity3d remains unmodified. To overwrite source data directly, 
specify --in-place (recommended alongside --backup).

Interactive shell equivalent — avoids reloading data during multi-step edits:

    ustudio_cli shell -F data.unity3d

    ustudio [data.unity3d]> export --id level0:1 --mode json -o ./patch
    (edit patch file outside shell)
    ustudio [data.unity3d]> import ./patch
    ustudio [data.unity3d]> list --modified
    ustudio [data.unity3d]> save --save-as ./output
    ustudio [data.unity3d]> exit

Additional common workflows:

    # Texture editing: export -> modify PNG -> import
    ustudio_cli export -F data.unity3d --name-contains "logo" --type Texture2D -o ./tex
    (modify PNG file without changing filename)
    ustudio_cli import -F data.unity3d ./tex --save-as ./output

    # Audio replacement
    ustudio_cli export -F data.unity3d --type AudioClip --name-contains "click" -o ./snd
    (replace WAV file with custom audio using identical filename)
    ustudio_cli import -F data.unity3d ./snd --save-as ./output

    # Text asset localization: export TextAssets, edit strings, re-import
    ustudio_cli export -p "Game_Data" --type TextAsset -o ./texts
    ustudio_cli import -p "Game_Data" ./texts --partial --save-as ./output

--------------------------------------------------------------------------------
Android (APK/OBB) and Multi-Game Directory Setups
--------------------------------------------------------------------------------

APK/OBB packages load directly using standard target options:

    ustudio_cli list -F "game.apk" --type Texture2D --limit 5

Package assets extract automatically on first load to the local cache folder 
(%LOCALAPPDATA%\UStudio\android_cache); subsequent operations reuse cached data. 
Updated APK packages invalidate stale cache entries automatically; entries 
unused for over 30 days or exceeding 4 GB storage limits are cleaned up automatically. 
Manage cache files using `cache` commands (see above).

Direct modification INSIDE source APK files is unsupported: executing import 
or save without -A/--save-as returns execution errors. Pass -A FOLDER to generate 
unpacked Data/... directory structures ready for repacking into APK containers:

    ustudio_cli import -F "game.apk" ./edited -A ./output

Multi-game directory handling: Identically named files (e.g., level0) located in 
shared environments are disambiguated by prepending folder paths: target specifications 
via reference tags or -S/--source accept folder path prefixes (case-insensitive; 
ambiguous targets return all matching option paths alongside error messages):

    ustudio_cli inspect -p "C:\Games" "GameB/Data/level0:5"
    ustudio_cli list -p "C:\Games" -S "GameB/Data/level0" --type Material

--------------------------------------------------------------------------------
Startup Banner
--------------------------------------------------------------------------------
Launching without arguments (or invoking `help` and `shell`) outputs the UStudio 
CLI logo, version information, and quick tips to the terminal stream. Banner text 
is written exclusively to stderr when stderr connects directly to an active 
terminal instance; automated scripts and `--format json` output streams bypass 
banner rendering. Set environment variable NO_COLOR=1 to disable color output, 
or USTUDIO_NO_BANNER=1 to suppress startup banner rendering completely. 
Invoking CLI without command parameters exits with status code 2.