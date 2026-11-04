"""Shared sanity-size guard for allocations sized directly from a binary
file's own declared header fields (a Texture2D's width/height, a Mesh's
vertex count, ...) — see this fork's own KNOWN_BUGS.md-adjacent review
notes: a maliciously crafted, tiny input file can declare an absurd size in
one of these fields, forcing a huge allocation before any of the actual
pixel/vertex data is read or validated — a decompression-bomb-style
amplification, not a bug in any one parsing function.

Deliberately scoped to PER-ASSET fields (one texture's dimensions, one
mesh's vertex count) — never applied to a whole BundleFile's aggregate
decompressed size, which legitimately reaches tens of GB for a real game
(this project's own hard-case fixture is ~35GB decompressed across 1055
internal files) and would make a flat ceiling either useless (set high
enough not to break that) or actively wrong (set low enough to matter). A
single texture or a single mesh's one vertex channel, by contrast, is never
legitimately anywhere close to this ceiling regardless of how large the
overall game is — confirmed against this project's own real fixtures, whose
largest single assets are on the order of tens of MB.

A single, generous, explicit ceiling rather than a "smart" compression-ratio
heuristic — this project's own established methodology declines to write
unverified binary-format-adjacent logic, and a ratio-based heuristic (what
counts as "suspicious" differs between LZ4/LZMA/an uncompressed field) would
be exactly that."""

MAX_SINGLE_ALLOCATION_SIZE = 2 * 1024 * 1024 * 1024  # 2 GiB
"""Ceiling for a single per-asset, size-from-header allocation (see
check_allocation_size()). Raise this directly if a real, legitimate asset is
ever rejected by it — this is a safety net against malicious/corrupt input,
not a hard architectural limit."""


def check_allocation_size(size: int, context: str) -> None:
    """Raises ValueError if `size` (bytes) exceeds MAX_SINGLE_ALLOCATION_SIZE.
    Call this BEFORE allocating a buffer whose size comes directly from an
    untrusted file's own declared header field, so a crafted/corrupt input
    fails fast with a clear message instead of attempting a huge allocation —
    which can hang or kill the process outright on a memory-constrained
    machine, well before Python would even raise a cleanly catchable
    MemoryError."""
    if size > MAX_SINGLE_ALLOCATION_SIZE:
        raise ValueError(
            f"Refusing to allocate {size:,} bytes for {context} — exceeds the "
            f"{MAX_SINGLE_ALLOCATION_SIZE:,}-byte sanity limit "
            "(UnityPy.helpers.size_guard.MAX_SINGLE_ALLOCATION_SIZE). This usually "
            "means the input file is corrupt or maliciously crafted; raise the "
            "limit only if you're certain this is a legitimate, unusually large asset."
        )
