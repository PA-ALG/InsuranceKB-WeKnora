package types

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"
)

const (
	RevisionManifestAlgorithm = "weknora.chunk_manifest.v1"
	RevisionUnknownIdentity   = "unknown"
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
