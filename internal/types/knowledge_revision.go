package types

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const (
	RevisionManifestAlgorithm = "weknora.chunk_manifest.v1"
	RevisionUnknownIdentity   = "unknown"

	KnowledgeRevisionSourcePinned   = "pinned"
	KnowledgeRevisionSourceReleased = "released"
)

var ErrInvalidRevisionManifest = errors.New("invalid revision manifest")

// RevisionManifestChunk is the exact document-text projection covered by the
// v1 manifest. Callers must provide rows in strict chunk_index order.
type RevisionManifestChunk struct {
	ID      string
	Index   int
	Content string
}

// RevisionParserIdentity freezes the effective parser/chunker inputs used by a
// single parse attempt. Unknown build components are explicit so consumers can
// distinguish degraded identity from an omitted field.
type RevisionParserIdentity struct {
	AppVersion          string `json:"app_version"`
	AppCommit           string `json:"app_commit"`
	DocReader           string `json:"docreader"`
	ParserEngine        string `json:"parser_engine"`
	ChunkSize           int    `json:"chunk_size"`
	ChunkOverlap        int    `json:"chunk_overlap"`
	SeparatorsDigest    string `json:"separators_digest"`
	ChunkerConfigDigest string `json:"chunker_config_digest"`
	EmbeddingModelID    string `json:"embedding_model_id"`
}

// Normalized makes the identity total and stable without treating missing
// build metadata as a reason to abandon an otherwise valid revision.
func (p RevisionParserIdentity) Normalized() RevisionParserIdentity {
	p.AppVersion = explicitIdentity(p.AppVersion)
	p.AppCommit = explicitIdentity(p.AppCommit)
	p.DocReader = explicitIdentity(p.DocReader)
	p.ParserEngine = explicitIdentity(p.ParserEngine)
	p.EmbeddingModelID = explicitIdentity(p.EmbeddingModelID)
	if p.SeparatorsDigest == "" {
		sum := sha256.Sum256(nil)
		p.SeparatorsDigest = hex.EncodeToString(sum[:])
	}
	if p.ChunkerConfigDigest == "" {
		p.ChunkerConfigDigest = computeChunkerConfigDigest(p)
	}
	return p
}

func explicitIdentity(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return RevisionUnknownIdentity
	}
	return value
}

func computeChunkerConfigDigest(identity RevisionParserIdentity) string {
	var input strings.Builder
	input.WriteString("weknora.chunker_config\nv1\n")
	input.WriteString(strconv.Itoa(identity.ChunkSize))
	input.WriteByte('\n')
	input.WriteString(strconv.Itoa(identity.ChunkOverlap))
	input.WriteByte('\n')
	input.WriteString(identity.SeparatorsDigest)
	input.WriteByte('\n')
	input.WriteString(identity.ParserEngine)
	input.WriteByte('\n')
	sum := sha256.Sum256([]byte(input.String()))
	return hex.EncodeToString(sum[:])
}

// NewRevisionParserIdentity freezes the effective chunker configuration in a
// language-neutral length-delimited digest.
func NewRevisionParserIdentity(
	appVersion string,
	appCommit string,
	docReader string,
	parserEngine string,
	embeddingModelID string,
	chunking ChunkingConfig,
) RevisionParserIdentity {
	var separatorInput strings.Builder
	separatorInput.WriteString("weknora.chunk_separators\nv1\n")
	separatorInput.WriteString(strconv.Itoa(len(chunking.Separators)))
	separatorInput.WriteByte('\n')
	for _, separator := range chunking.Separators {
		separatorInput.WriteString(strconv.Itoa(len([]byte(separator))))
		separatorInput.WriteByte(':')
		separatorInput.WriteString(separator)
		separatorInput.WriteByte('\n')
	}
	sum := sha256.Sum256([]byte(separatorInput.String()))
	return (RevisionParserIdentity{
		AppVersion:       appVersion,
		AppCommit:        appCommit,
		DocReader:        docReader,
		ParserEngine:     parserEngine,
		ChunkSize:        chunking.ChunkSize,
		ChunkOverlap:     chunking.ChunkOverlap,
		SeparatorsDigest: hex.EncodeToString(sum[:]),
		EmbeddingModelID: embeddingModelID,
	}).Normalized()
}

// RevisionCommitBinding is copied through the existing async task graph. It is
// not an authority on its own: repository commit paths fence ParseAttempt
// against the locked knowledge row and derive the manifest from durable chunks.
type RevisionCommitBinding struct {
	ParseAttempt   int64                  `json:"parse_attempt"`
	FileSHA256     string                 `json:"file_sha256"`
	ParserIdentity RevisionParserIdentity `json:"parser_identity"`
}

func (b RevisionCommitBinding) Valid() bool {
	if b.ParseAttempt <= 0 || len(b.FileSHA256) != sha256.Size*2 {
		return false
	}
	_, err := hex.DecodeString(b.FileSHA256)
	return err == nil && b.FileSHA256 == strings.ToLower(b.FileSHA256)
}

// KnowledgeRevision is immutable after INSERT. There is intentionally no
// update API for this model.
type KnowledgeRevision struct {
	KnowledgeID       string                 `json:"knowledge_id"       gorm:"type:varchar(36);primaryKey"`
	ParseAttempt      int64                  `json:"parse_attempt"      gorm:"primaryKey"`
	FileSHA256        string                 `json:"file_sha256"        gorm:"type:varchar(64);not null"`
	ParserIdentity    RevisionParserIdentity `json:"parser_identity"    gorm:"type:json;serializer:json;not null"`
	ManifestAlgorithm string                 `json:"manifest_algorithm" gorm:"type:varchar(64);not null"`
	ManifestDigest    string                 `json:"manifest_digest"    gorm:"type:varchar(64);not null"`
	ChunkCount        int                    `json:"chunk_count"        gorm:"not null"`
	CompletedAt       time.Time              `json:"completed_at"       gorm:"not null"`
}

func (KnowledgeRevision) TableName() string {
	return "knowledge_revisions"
}

// KnowledgeRevisionSource is the write-once link from one immutable parse
// attempt to the exact stored source object whose bytes produced it. FileSHA256
// is intentionally distinct from ParsedDocument and chunk-manifest identities.
type KnowledgeRevisionSource struct {
	TenantID          uint64     `json:"tenant_id" gorm:"primaryKey;not null"`
	KnowledgeID       string     `json:"knowledge_id" gorm:"type:varchar(36);primaryKey"`
	ParseAttempt      int64      `json:"parse_attempt" gorm:"primaryKey"`
	RevisionSourceID  string     `json:"revision_source_id" gorm:"type:varchar(64);not null;uniqueIndex"`
	ResourceID        string     `json:"resource_id" gorm:"type:varchar(36);not null;index"`
	ResourceHandle    string     `json:"resource_handle" gorm:"type:varchar(22);not null"`
	FileSHA256        string     `json:"file_sha256" gorm:"type:varchar(64);not null"`
	ObjectSHA256      string     `json:"object_sha256" gorm:"type:varchar(64);not null"`
	Size              int64      `json:"size" gorm:"not null"`
	MimeType          string     `json:"mime_type" gorm:"type:varchar(255);not null"`
	PageCount         *int       `json:"page_count,omitempty"`
	ManifestAlgorithm string     `json:"manifest_algorithm" gorm:"type:varchar(64);not null"`
	ManifestDigest    string     `json:"manifest_digest" gorm:"type:varchar(64);not null"`
	ChunkCount        int        `json:"chunk_count" gorm:"not null"`
	ImmutableLocator  string     `json:"immutable_locator" gorm:"type:text;not null"`
	BindingDigest     string     `json:"binding_digest" gorm:"type:varchar(64);not null"`
	RetentionState    string     `json:"retention_state" gorm:"type:varchar(16);not null"`
	CreatedAt         time.Time  `json:"created_at"`
	UpdatedAt         time.Time  `json:"updated_at"`
	ReleasedAt        *time.Time `json:"released_at,omitempty"`
}

func (KnowledgeRevisionSource) TableName() string { return "knowledge_revision_sources" }

// RevisionSourceRecordOutcome is the result of recording a missing commit-time source row (S11g).
type RevisionSourceRecordOutcome string

// Outcomes of RecordMissingRevisionSource: an existing row is never modified.
const (
	RevisionSourceRecordPresent     RevisionSourceRecordOutcome = "present"
	RevisionSourceRecordWouldRecord RevisionSourceRecordOutcome = "would_record"
	RevisionSourceRecordRecorded    RevisionSourceRecordOutcome = "recorded"
)

const pdfMIME = "application/pdf"

// officeSourceMIME is a fixed table, not the host MIME database: the stored resource MIME comes
// from mime.TypeByExtension and is empty when the image ships no /etc/mime.types (S11g).
var officeSourceMIME = map[string]string{
	".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
	".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

// RevisionSourceMIME decides whether a stored source resource records a commit-time source
// revision and under which MIME: PDFs exactly as before (by MIME only), and the three OOXML
// formats S11 captures when the resource MIME is empty or equals the format's canonical MIME.
// Anything else records nothing, so the commit still succeeds without a source row.
func RevisionSourceMIME(resourceMIME, originalName string) (string, bool) {
	normalized := strings.ToLower(strings.TrimSpace(resourceMIME))
	if normalized == pdfMIME {
		return pdfMIME, true
	}
	canonical, ok := officeSourceMIME[strings.ToLower(filepath.Ext(strings.TrimSpace(originalName)))]
	if !ok || (normalized != "" && normalized != canonical) {
		return "", false
	}
	return canonical, true
}

// ComputeKnowledgeRevisionSourceID freezes the server-owned source-row key.
func ComputeKnowledgeRevisionSourceID(source KnowledgeRevisionSource) (string, error) {
	if source.TenantID == 0 || source.KnowledgeID == "" || source.ParseAttempt <= 0 ||
		source.ResourceID == "" || source.Size <= 0 || strings.TrimSpace(source.MimeType) == "" ||
		!validRevisionSHA256(source.FileSHA256) {
		return "", ErrInvalidRevisionManifest
	}
	return revisionAuthorityDigest("knowledge-revision-source-id.v1", []string{
		strconv.FormatUint(source.TenantID, 10), source.KnowledgeID,
		strconv.FormatInt(source.ParseAttempt, 10), source.ResourceID,
		source.FileSHA256, strconv.FormatInt(source.Size, 10), source.MimeType,
	}), nil
}

// ComputeKnowledgeRevisionSourceBindingDigest closes the server-owned source
// row over its immutable object, exact parse attempt, manifest and page count.
// An empty digest represents an intentionally unsealed legacy row; it is never
// accepted by fixed-revision readers.
func ComputeKnowledgeRevisionSourceBindingDigest(source KnowledgeRevisionSource) (string, error) {
	if source.TenantID == 0 || source.KnowledgeID == "" || source.ParseAttempt <= 0 ||
		source.ResourceID == "" || source.ResourceHandle == "" ||
		source.ImmutableLocator != BuildResourcePath(source.ResourceHandle) ||
		source.Size <= 0 || !strings.EqualFold(strings.TrimSpace(source.MimeType), "application/pdf") ||
		source.PageCount == nil || *source.PageCount <= 0 ||
		source.ManifestAlgorithm != RevisionManifestAlgorithm || source.ChunkCount <= 0 ||
		source.RetentionState != KnowledgeRevisionSourcePinned {
		return "", ErrInvalidRevisionManifest
	}
	for _, digest := range []string{
		source.RevisionSourceID, source.FileSHA256, source.ObjectSHA256, source.ManifestDigest,
	} {
		if !validRevisionSHA256(digest) {
			return "", ErrInvalidRevisionManifest
		}
	}
	if source.ObjectSHA256 != source.FileSHA256 {
		return "", ErrInvalidRevisionManifest
	}
	return revisionAuthorityDigest("knowledge-revision-source-binding.v1", []string{
		strconv.FormatUint(source.TenantID, 10), source.KnowledgeID,
		strconv.FormatInt(source.ParseAttempt, 10), source.RevisionSourceID,
		source.ResourceID, source.ResourceHandle, source.ImmutableLocator,
		source.FileSHA256, source.ObjectSHA256, strconv.FormatInt(source.Size, 10),
		strings.ToLower(strings.TrimSpace(source.MimeType)), strconv.Itoa(*source.PageCount),
		source.ManifestAlgorithm, source.ManifestDigest, strconv.Itoa(source.ChunkCount),
		source.RetentionState,
	}), nil
}

// ValidateKnowledgeRevisionSourceBinding rejects unsealed, drifted and
// self-rehashed source rows before any object bytes are opened.
func ValidateKnowledgeRevisionSourceBinding(source KnowledgeRevisionSource) error {
	digest, err := ComputeKnowledgeRevisionSourceBindingDigest(source)
	if err != nil || source.BindingDigest != digest {
		return ErrInvalidRevisionManifest
	}
	return nil
}

func revisionAuthorityDigest(contract string, fields []string) string {
	var input strings.Builder
	input.WriteString(contract)
	input.WriteByte('\n')
	input.WriteString(strconv.Itoa(len(fields)))
	input.WriteByte('\n')
	for _, field := range fields {
		input.WriteString(strconv.Itoa(len([]byte(field))))
		input.WriteByte(':')
		input.WriteString(field)
		input.WriteByte('\n')
	}
	sum := sha256.Sum256([]byte(input.String()))
	return hex.EncodeToString(sum[:])
}

func validRevisionSHA256(value string) bool {
	if len(value) != sha256.Size*2 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

// ComputeRevisionManifestDigest implements weknora.chunk_manifest.v1 exactly.
func ComputeRevisionManifestDigest(
	knowledgeID string,
	parseAttempt int64,
	chunks []RevisionManifestChunk,
) (string, error) {
	if knowledgeID == "" || parseAttempt <= 0 {
		return "", ErrInvalidRevisionManifest
	}

	var input strings.Builder
	input.WriteString("weknora.chunk_manifest\nv1\n")
	input.WriteString(knowledgeID)
	input.WriteByte('\n')
	input.WriteString(strconv.FormatInt(parseAttempt, 10))
	input.WriteByte('\n')
	input.WriteString(strconv.Itoa(len(chunks)))
	input.WriteByte('\n')

	previousIndex := -1
	for _, chunk := range chunks {
		if chunk.ID == "" || chunk.Index < 0 || chunk.Index <= previousIndex {
			return "", fmt.Errorf("%w: chunks must have ids and strict ascending indexes", ErrInvalidRevisionManifest)
		}
		previousIndex = chunk.Index
		contentDigest := sha256.Sum256([]byte(chunk.Content))
		input.WriteString(strconv.Itoa(chunk.Index))
		input.WriteByte(':')
		input.WriteString(chunk.ID)
		input.WriteByte(':')
		input.WriteString(hex.EncodeToString(contentDigest[:]))
		input.WriteByte('\n')
	}

	sum := sha256.Sum256([]byte(input.String()))
	return hex.EncodeToString(sum[:]), nil
}
