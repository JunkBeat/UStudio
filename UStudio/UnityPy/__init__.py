# current commit = c354911 (v1.25.4)
# https://github.com/K0lb3/UnityPy/commit/c354911cdc36f661a8ecdd3009e72e57fa477b6f
# Merged from upstream: d67692f..c354911. Deliberately NOT taken: 998b312/d1edc71
# (upstream SF v23) - this copy has its own v23 implementation (see CLAUDE.md).

__version__ = "1.25.4"

from .environment import Environment as Environment
from .helpers.ArchiveStorageManager import (
    set_assetbundle_decrypt_key as set_assetbundle_decrypt_key,
)

load = Environment

# backward compatibility
AssetsManager = Environment
