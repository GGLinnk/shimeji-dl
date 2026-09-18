from .shimejis_xyz import ShimejisXYZSource


def default_sources() -> dict[str, ShimejisXYZSource]:
    source = ShimejisXYZSource()
    return {source.key: source}


__all__ = ["ShimejisXYZSource", "default_sources"]
