"""Shared SK-2b test data (written by Claude): materials with real file bytes and a fake platform.

The discovery steps check the bytes of a file against the digest its record names, so these
materials carry invented file bytes and the digest of those bytes. The texts are the invented
SK-2a decks; no private sample text is used anywhere.
"""

import hashlib
from collections.abc import Sequence

from insurance_harness.compilers.methods.platform import PlatformCallError
from insurance_harness.compilers.wiki_pages.members import NativeChunk, NativePage
from insurance_harness.ingest.raw_sources import RawListing, RawSource, UnfinishedSource
from tests.compilers.methods.helpers import DECK_A, DECK_C, METHOD_A, World
from tests.ingest.method_helpers import DeckPages, v2

DISCOVERY_KB = "kb-methods"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DiscoveryWorld(World):
    """Deck A and deck C as files in the RAW knowledge base, each with an active record."""

    def __init__(self) -> None:  # the SK-2a world's materials, but with real file digests
        self.decks = {}
        self.raws = {}
        self.reader = DeckPages({})
        self.registry = v2()
        self.files: dict[str, bytes] = {}
        self.add_file("k-deck-a", "需求销售方法.pptx", DECK_A)
        self.add_file("k-deck-c", "转保沟通.pptx", DECK_C)

    def add_file(
        self, knowledge_id: str, file_name: str, slides: Sequence[Sequence[str]], data: bytes = b""
    ) -> RawSource:
        content = data or f"{knowledge_id} file bytes".encode()
        self.files[knowledge_id] = content
        return self.add(knowledge_id, file_name, digest(content), slides)


class FakePlatform:
    """The RAW files and one discovery knowledge base, with every call recorded."""

    def __init__(self, world: DiscoveryWorld) -> None:
        self.files = dict(world.files)  # what a download serves, by RAW knowledge id
        self.names = {kid: raw.file_name for kid, raw in world.raws.items()}
        self.items: dict[str, tuple[str, str, bool]] = {}  # copy id -> (name, digest, parsed)
        self.calls: list[tuple[str, str]] = []
        self.fail_upload: set[str] = set()  # file names whose upload fails
        self.download_error: dict[str, str] = {}  # RAW knowledge id -> error code
        self.duplicate_of: dict[str, str] = {}  # digest -> the copy id a 409 names
        self.serial = 0

    def listing(self, kb_id: str) -> RawListing:
        self.calls.append(("listing", kb_id))
        completed = [
            RawSource(knowledge_id=cid, parse_attempt=1, file_name=name, sha256=sha)
            for cid, (name, sha, parsed) in self.items.items()
            if parsed
        ]
        unfinished = [
            UnfinishedSource(knowledge_id=cid, file_name=name, state="NOT_CAPTURED_YET")
            for cid, (name, _, parsed) in self.items.items()
            if not parsed
        ]
        return RawListing(completed=completed, unfinished=unfinished)

    def download(self, knowledge_id: str) -> bytes:
        self.calls.append(("download", knowledge_id))
        if knowledge_id in self.download_error:
            raise PlatformCallError(self.download_error[knowledge_id])
        return self.files[knowledge_id]

    def upload(self, kb_id: str, file_name: str, data: bytes) -> tuple[str, bool]:
        self.calls.append(("upload", file_name))
        if file_name in self.fail_upload:
            raise PlatformCallError("UPLOAD_FAILED")
        sha = digest(data)
        if sha in self.duplicate_of:
            return self.duplicate_of[sha], False
        self.serial += 1
        copy_id = f"copy-{self.serial}"
        self.items[copy_id] = (file_name, sha, True)
        return copy_id, True

    def delete(self, knowledge_id: str) -> None:
        self.calls.append(("delete", knowledge_id))
        self.items.pop(knowledge_id)

    def writes(self) -> list[tuple[str, str]]:
        return [call for call in self.calls if call[0] in {"upload", "delete"}]


def chunk(copy_id: str, *texts: str) -> NativeChunk:
    """A chunk of a copy, holding the texts as the copy's parse joined them."""
    return NativeChunk(content="\n".join(texts), knowledge_id=copy_id)


def page(
    title: str = METHOD_A,
    *chunks: NativeChunk,
    page_type: str = "entity",
    aliases: Sequence[str] = (),
) -> NativePage:
    return NativePage(
        slug=f"{page_type}/{len(title)}",
        title=title,
        page_type=page_type,
        summary="模型写的摘要",
        content="模型写的正文",
        aliases=list(aliases),
        chunks=list(chunks),
    )
