"""Content-addressable artifact store.

Artifacts are raw bytes produced by tools (fetched pages, file contents, etc.)
that exceed the in-memory threshold. Memory holds only the handle; Decision
receives the bytes only when Perception explicitly attaches them.

Storage layout under state/artifacts/:
    <sha256_prefix>.bin  — raw bytes
    <sha256_prefix>.json — Artifact metadata
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .schemas import Artifact

STORE_DIR = Path(__file__).parent.parent / "state" / "artifacts"
STORE_DIR.mkdir(parents=True, exist_ok=True)

ARTIFACT_THRESHOLD_BYTES = 4 * 1024  # 4 KB


class ArtifactStore:
    def __init__(self, store_dir: Path = STORE_DIR):
        self.dir = store_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        blob: bytes,
        *,
        content_type: str,
        source: str,
        descriptor: str,
    ) -> str:
        sha = hashlib.sha256(blob).hexdigest()[:16]
        artifact_id = f"art:{sha}"

        bin_path = self.dir / f"{sha}.bin"
        meta_path = self.dir / f"{sha}.json"

        if not bin_path.exists():
            bin_path.write_bytes(blob)

        if not meta_path.exists():
            art = Artifact(
                id=artifact_id,
                content_type=content_type,
                size_bytes=len(blob),
                source=source,
                descriptor=descriptor,
            )
            meta_path.write_text(art.model_dump_json(), encoding="utf-8")

        return artifact_id

    def get_bytes(self, artifact_id: str) -> bytes:
        sha = artifact_id.removeprefix("art:")
        return (self.dir / f"{sha}.bin").read_bytes()

    def get_meta(self, artifact_id: str) -> Artifact:
        sha = artifact_id.removeprefix("art:")
        raw = (self.dir / f"{sha}.json").read_text(encoding="utf-8")
        return Artifact.model_validate_json(raw)

    def exists(self, artifact_id: str) -> bool:
        sha = artifact_id.removeprefix("art:")
        return (self.dir / f"{sha}.bin").exists()


artifacts = ArtifactStore()
