"""Closed vocabulary from blueprint §5; domain-specific predicates stay in Catalog."""

from enum import StrEnum


class ClaimState(StrEnum):
    PRESENT = "present"
    ABSENT_EXPLICITLY = "absent_explicitly"
    UNKNOWN = "unknown"


class SourceClass(StrEnum):
    SOURCE_SUPPORTED = "SOURCE_SUPPORTED"
    MIXED = "MIXED"
    MODEL_GENERATED = "MODEL_GENERATED"
    EXPERT_REVISION = "EXPERT_REVISION"
    STRUCTURED_IMPORT = "STRUCTURED_IMPORT"


class LocatorKind(StrEnum):
    PDF_TEXT_SPAN = "PDF_TEXT_SPAN"
    OCR_REGION = "OCR_REGION"
    DOCX_BLOCK = "DOCX_BLOCK"
    DOCX_TABLE_CELL = "DOCX_TABLE_CELL"
    PPTX_SHAPE = "PPTX_SHAPE"
    XLSX_CELL_RANGE = "XLSX_CELL_RANGE"
    CHUNK_SPAN = "CHUNK_SPAN"
    STRUCTURED_PATH = "STRUCTURED_PATH"
    EXPERT_REVISION = "EXPERT_REVISION"


class Origin(StrEnum):
    COMPILE = "compile"
    EXPERT_EDIT = "expert_edit"
    REVERT = "revert"
    INCREMENTAL = "incremental"
    FEEDBACK = "feedback"
    IMPORT = "import"


class ChangedBy(StrEnum):
    COMPILE = "compile"
    EXPERT = "expert"
    FEEDBACK = "feedback"
    IMPORT = "import"


class ReviewMode(StrEnum):
    MACHINE = "machine"
    HUMAN = "human"


class EvidenceMatch(StrEnum):
    EXACT = "EXACT"
    NORMALIZED = "NORMALIZED"
    FUZZY_REVIEW = "FUZZY_REVIEW"


class CompileTaskKind(StrEnum):
    SCHEMA_FIELDS = "schema_fields"
    DISCOVERY = "discovery"
    CONCEPTS = "concepts"
    QA = "qa"
    GAP_FILL = "gap_fill"


class TextOrigin(StrEnum):
    NATIVE = "NATIVE"
    OCR = "OCR"


class GapTrigger(StrEnum):
    SCHEMA = "schema"
    FEEDBACK = "feedback"
    LINT = "lint"
    NEW_MATERIAL = "new_material"


class ReviewKind(StrEnum):
    CONFLICT = "conflict"
    LOW_SCORE = "low_score"
    FEEDBACK = "feedback"
    LINT = "lint"
    ACL_SHRINK = "acl_shrink"
    REGRESSION = "regression"
    SAMPLE = "sample"


class UnknownReason(StrEnum):
    NOT_IN_MATERIAL = "NOT_IN_MATERIAL"
    MATERIAL_AMBIGUOUS = "MATERIAL_AMBIGUOUS"
    LOCATOR_UNSUPPORTED = "LOCATOR_UNSUPPORTED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class CompileStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class GapStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    ABANDONED = "ABANDONED"


class ReviewStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"
