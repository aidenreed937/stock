"""业务管线产物与清单基础设施包。"""

from __future__ import annotations

from stock_analytics.pipelines.artifacts.cleanup import (
    ArtifactRunCandidate,
    collect_run_candidates,
    delete_run_candidates,
)
from stock_analytics.pipelines.artifacts.contracts import (
    RUN_CLASSES,
    RunClass,
    normalize_run_class,
)
from stock_analytics.pipelines.artifacts.index import (
    INDEX_FILENAME,
    INDEX_SCHEMA_VERSION,
    read_run_index,
    rebuild_run_index,
)
from stock_analytics.pipelines.artifacts.integrity import (
    build_artifact_integrity,
    check_artifact_integrity,
)
from stock_analytics.pipelines.artifacts.manifest import (
    MANIFEST_SCHEMA_VERSION,
    build_manifest_base,
    build_watermark_index,
)
from stock_analytics.pipelines.artifacts.ops import (
    ArtifactCleanupResult,
    ArtifactIndexResult,
    cleanup_artifacts,
    index_artifacts,
)
from stock_analytics.pipelines.artifacts.reader import (
    ArtifactRun,
    ArtifactUnavailableError,
    resolve_artifact_run,
    select_artifact_run_dir,
)
from stock_analytics.pipelines.artifacts.registry_repo import ArtifactRegistryRepository
from stock_analytics.pipelines.artifacts.store import (
    ArtifactRunPaths,
    ArtifactStore,
    ArtifactWriteSession,
)
from stock_analytics.pipelines.artifacts.validator import (
    ArtifactValidationError,
    ArtifactValidationResult,
    ArtifactValidator,
)
from stock_analytics.pipelines.artifacts.validator_files import (
    ArtifactValidationIssue,
    actual_files,
    check_artifact_files,
    check_optional_files,
    check_required_files,
    load_manifest,
    manifest_names,
)

__all__ = [
    "INDEX_FILENAME",
    "INDEX_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "RUN_CLASSES",
    "ArtifactCleanupResult",
    "ArtifactIndexResult",
    "ArtifactRegistryRepository",
    "ArtifactRun",
    "ArtifactRunCandidate",
    "ArtifactRunPaths",
    "ArtifactStore",
    "ArtifactUnavailableError",
    "ArtifactValidationError",
    "ArtifactValidationIssue",
    "ArtifactValidationResult",
    "ArtifactValidator",
    "ArtifactWriteSession",
    "RunClass",
    "actual_files",
    "build_artifact_integrity",
    "build_manifest_base",
    "build_watermark_index",
    "check_artifact_files",
    "check_artifact_integrity",
    "check_optional_files",
    "check_required_files",
    "cleanup_artifacts",
    "collect_run_candidates",
    "delete_run_candidates",
    "index_artifacts",
    "load_manifest",
    "manifest_names",
    "normalize_run_class",
    "read_run_index",
    "rebuild_run_index",
    "resolve_artifact_run",
    "select_artifact_run_dir",
]
