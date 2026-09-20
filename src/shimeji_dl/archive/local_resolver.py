from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, NoReturn

from ..sources.shimejis_xyz.target_vocabulary import pack_slug
from ..sources.target.target_kind import TargetKind
from ..sources.target.target_vocabularies import reduce_target
from .local_character_index import CharacterEntry, build_local_character_index
from .metadata_state import MetadataState
from .refusals.character_not_found import CharacterNotFound
from .refusals.collection_not_found import CollectionNotFound
from .refusals.empty_output_root import EmptyOutputRoot
from .refusals.metadata_writing_was_disabled import MetadataWritingWasDisabled
from .refusals.no_collection_recorded import NoCollectionRecorded
from .refusals.no_source_recorded import NoSourceRecorded
from .refusals.source_not_found import SourceNotFound
from .refusals.unreadable_metadata_document import UnreadableMetadataDocument
from .refusals.unsupported_target import UnsupportedTarget
from .reporter import ArchiveReporter
from .request import ArchiveRequest


def resolve_global(image_root: Path, output_root: Path, *, reporter: ArchiveReporter) -> ArchiveRequest:
    entries = build_local_character_index(image_root, reporter=reporter)
    if not entries:
        raise EmptyOutputRoot(output_root)
    return ArchiveRequest(name=output_root.resolve().name, characters=tuple(entry.directory for entry in entries))


def resolve_target(image_root: Path, output_root: Path, target: str, *, reporter: ArchiveReporter) -> ArchiveRequest:
    """Resolve one archive-command target against what is on disk, never over the network."""
    entries = build_local_character_index(image_root, reporter=reporter)
    if not entries:
        raise EmptyOutputRoot(output_root)

    local = reduce_target(target)
    if local is None:
        # A URL no registered vocabulary accepts names no source, never a display-name guess.
        if "://" in target:
            raise UnsupportedTarget(target)
        # Neither a character slug nor a pack form: the only shape left is a collection's own display name.
        return _resolve_collection_by_display_name(entries, target.strip())
    if local.kind is TargetKind.CHARACTER:
        if "://" not in target:
            return _resolve_bare_character(entries, target, local.identifier)
        return _resolve_character(entries, local.identifier)
    if local.kind is TargetKind.COLLECTION:
        return _resolve_collection(entries, local.identifier)
    return _resolve_site(entries, local.identifier)


def _resolve_character(entries: list[CharacterEntry], identifier: str) -> ArchiveRequest:
    matched = _match_directory(entries, identifier.casefold())
    if matched is not None:
        return ArchiveRequest(name=matched.directory.name, characters=(matched.directory,))
    raise CharacterNotFound(identifier)


def _resolve_bare_character(entries: list[CharacterEntry], raw_target: str, lowered_identifier: str) -> ArchiveRequest:
    """A bare character-shaped target: an already-lowercase slug is a character only.

    A mixed-case one first tries its raw text as a collection's exact display name, then falls back to the character its lowered form names, exactly as the download command would fetch it.
    """
    stripped = raw_target.strip().rstrip("/")
    if stripped != lowered_identifier:
        matched = _match_collection_by_display_name(entries, stripped)
        if matched is not None:
            return matched
    return _resolve_character(entries, lowered_identifier)


def _resolve_collection(entries: list[CharacterEntry], identifier: str) -> ArchiveRequest:
    folded = identifier.casefold()
    matched = _match_collection(entries, folded)
    if matched is not None:
        return matched
    _raise_collection_refusal(entries, identifier)


def _resolve_collection_by_display_name(entries: list[CharacterEntry], display_name: str) -> ArchiveRequest:
    """Match a collection by its display name, exactly as the site records it: never case-folded, never a directory guess."""
    matched = _match_collection_by_display_name(entries, display_name)
    if matched is not None:
        return matched
    _raise_collection_refusal(entries, display_name)


def _match_collection_by_display_name(entries: list[CharacterEntry], display_name: str) -> ArchiveRequest | None:
    by_group_name = _matching(entries, display_name, key=lambda entry: entry.group_name, fold=False)
    if by_group_name:
        matched_entry, matched_name = by_group_name[0]
        canonical = matched_entry.group or matched_name
        return ArchiveRequest(name=pack_slug(canonical), characters=tuple(entry.directory for entry, _ in by_group_name))
    return None


def _resolve_site(entries: list[CharacterEntry], identifier: str) -> ArchiveRequest:
    folded = identifier.casefold()
    matched = _match_source(entries, folded)
    if matched is not None:
        return matched
    _raise_source_refusal(entries, identifier)


def _match_directory(entries: list[CharacterEntry], folded_identifier: str) -> CharacterEntry | None:
    for entry in entries:
        if entry.directory.name.casefold() == folded_identifier:
            return entry
    return None


def _match_collection(entries: list[CharacterEntry], folded_identifier: str) -> ArchiveRequest | None:
    by_group = _matching(entries, folded_identifier, key=lambda entry: entry.group)
    if by_group:
        name = pack_slug(by_group[0][1])
        return ArchiveRequest(name=name, characters=tuple(entry.directory for entry, _ in by_group))

    by_group_name = _matching(entries, folded_identifier, key=lambda entry: entry.group_name)
    if by_group_name:
        matched_entry, matched_name = by_group_name[0]
        canonical = matched_entry.group or matched_name
        return ArchiveRequest(
            name=pack_slug(canonical),
            characters=tuple(entry.directory for entry, _ in by_group_name),
        )
    return None


def _match_source(entries: list[CharacterEntry], folded_identifier: str) -> ArchiveRequest | None:
    by_source = _matching(entries, folded_identifier, key=lambda entry: entry.source_adapter)
    if by_source:
        name = by_source[0][1]
        return ArchiveRequest(name=name, characters=tuple(entry.directory for entry, _ in by_source))
    return None


def _matching(
    entries: list[CharacterEntry],
    identifier: str,
    *,
    key: Callable[[CharacterEntry], str | None],
    fold: bool = True,
) -> list[tuple[CharacterEntry, str]]:
    """Every entry whose `key` value matches `identifier`, case-folded unless `fold` is disabled."""
    target = identifier.casefold() if fold else identifier
    return [
        (entry, value)
        for entry in entries
        if (value := key(entry)) is not None and (value.casefold() if fold else value) == target
    ]


_CausalMetadataState = Literal[
    MetadataState.UNREADABLE,
    MetadataState.NO_MANIFEST,
    MetadataState.MANIFEST_WITHOUT_GROUP,
    MetadataState.NO_DOCUMENT,
]


def _classify_metadata_state(entries: list[CharacterEntry]) -> _CausalMetadataState:
    """Classify why no character entry matched, given metadata-carrying axes only."""
    if any(entry.is_unreadable for entry in entries):
        return MetadataState.UNREADABLE
    if any(entry.has_metadata_document for entry in entries):
        if any(entry.manifest_available for entry in entries):
            return MetadataState.MANIFEST_WITHOUT_GROUP
        return MetadataState.NO_MANIFEST
    return MetadataState.NO_DOCUMENT


def _raise_collection_refusal(entries: list[CharacterEntry], identifier: str) -> NoReturn:
    if any(entry.group is not None or entry.group_name is not None for entry in entries):
        raise CollectionNotFound(identifier)
    state = _classify_metadata_state(entries)
    if state is MetadataState.UNREADABLE:
        raise UnreadableMetadataDocument(identifier, subject="collection")
    if state is MetadataState.NO_DOCUMENT:
        raise MetadataWritingWasDisabled(identifier, subject="collection")
    raise NoCollectionRecorded(identifier, state)


def _raise_source_refusal(entries: list[CharacterEntry], identifier: str) -> NoReturn:
    if any(entry.source_adapter is not None for entry in entries):
        raise SourceNotFound(identifier)
    state = _classify_metadata_state(entries)
    if state is MetadataState.UNREADABLE:
        raise UnreadableMetadataDocument(identifier, subject="source")
    if state is MetadataState.NO_DOCUMENT:
        raise MetadataWritingWasDisabled(identifier, subject="source")
    # The source axis has no manifest-shaped sub-state: source_adapter is written unconditionally, so either sub-state here means the same one fact for it.
    raise NoSourceRecorded(identifier)
