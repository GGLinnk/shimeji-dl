from __future__ import annotations


class SpriteRejection(ValueError):
    """Base for a single sprite manifest entry rejected during validation."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key


class InvalidSpritePath(SpriteRejection):
    """The sprite key is not a valid, confined asset path."""

    def __init__(self, key: str) -> None:
        super().__init__(key, f"sprite key is not a valid asset path: {key!r}")


class SpriteAbsoluteUrlPresent(SpriteRejection):
    """The sprite key normalized to an absolute URL instead of a relative path."""

    def __init__(self, key: str) -> None:
        super().__init__(key, f"sprite key normalized to an absolute URL: {key!r}")


class SpriteWrongSuffix(SpriteRejection):
    """The sprite key is not a PNG asset; only PNG atlas entries are supported."""

    def __init__(self, key: str) -> None:
        super().__init__(key, f"sprite key is not a PNG asset: {key!r}")


class InvalidSpriteRegion(SpriteRejection):
    """The sprite region failed msgspec's structural or coordinate validation."""

    def __init__(self, key: str) -> None:
        super().__init__(key, f"sprite region failed validation: {key!r}")
