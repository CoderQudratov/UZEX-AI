"""Artifact-bound source evidence, held in RAM. No user or plan persistence."""

import hashlib
import json
from datetime import date

from app.agent.query_models import Evidence

APPROVED_VERSION = "sha256:88182bf4dad3569eea5fac611e8a16db7a455110fdaa6495650e7d87e09ac258"


class EvidenceMismatch(RuntimeError):
    """The immutable prepared artifact no longer matches the verified source."""


class EvidenceContext:
    def __init__(self, database_path):
        catalog = json.loads(database_path.with_name("schema_catalog.json").read_text())
        report = json.loads(database_path.with_name("build_report.json").read_text())
        with database_path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if (
            catalog["dataset_version"] != APPROVED_VERSION
            or report["database_sha256"] != digest
            or report["logical_sha256"] != catalog["logical_sha256"]
        ):
            raise ValueError("Prepared artifact evidence is invalid")
        self.path = database_path
        self.signature = self._signature()
        self.version = catalog["dataset_version"]
        self.snapshot = date.fromisoformat(catalog["semantics"]["snapshot"][:10])

    def _signature(self):
        stat = self.path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def assert_current(self):
        if self._signature() != self.signature:
            raise EvidenceMismatch("Verified artifact changed")

    def make(self, **kwargs):
        return Evidence(dataset_version=self.version, snapshot=self.snapshot, **kwargs)
