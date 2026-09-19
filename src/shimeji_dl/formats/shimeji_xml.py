from __future__ import annotations

from lxml import etree

from ..core.models import AssetRef
from ..core.storage import normalize_resource_ref


class ShimejiXmlFormat:
    """Shimeji XML parser backed by lxml rather than custom XML traversal."""

    def _parse(self, data: bytes) -> etree._Element:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        return etree.fromstring(data, parser=parser)

    def is_valid(self, data: bytes) -> bool:
        try:
            self._parse(data)
        except (etree.XMLSyntaxError, ValueError):
            return False
        return True

    def extract_asset_refs(self, data: bytes) -> list[AssetRef]:
        try:
            root = self._parse(data)
        except (etree.XMLSyntaxError, ValueError):
            return []

        refs: list[AssetRef] = []
        seen: set[tuple[str, str | None]] = set()
        values = [str(value) for value in root.xpath("//@*")]
        values.extend(str(value) for value in root.xpath("//text()[normalize-space()]") if str(value).strip())

        for value in values:
            normalized = normalize_resource_ref(value)
            if normalized is None:
                continue
            path, absolute_url = normalized
            key = (path, absolute_url)
            if key in seen:
                continue
            seen.add(key)
            refs.append(AssetRef(value=value, path=path, absolute_url=absolute_url))
        return refs
