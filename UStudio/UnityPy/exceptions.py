class TypeTreeError(Exception):
    def __init__(self, message, nodes):
        super().__init__(message)
        self.nodes = nodes


class UnityVersionFallbackError(Exception):
    def __init__(self, message):
        super().__init__(message)


class UnityVersionFallbackWarning(UserWarning):
    def __init__(self, message):
        super().__init__(message)


class CabNameCollisionError(Exception):
    """Raised by Environment.register_cab() when cab_collision_policy == "raise" and two
    different source files reduce to the same internal name (see register_cab()'s
    docstring for why that happens)."""
    def __init__(self, key: str, existing_name: str, new_name: str):
        super().__init__(
            f"Cab name collision on {key!r}: {existing_name!r} and {new_name!r} both "
            f"reduce to the same internal name."
        )
        self.key = key
        self.existing_name = existing_name
        self.new_name = new_name
