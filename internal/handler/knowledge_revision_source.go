package handler

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/revisionsource"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

type knowledgeRevisionSourceBackfiller interface {
	BackfillCurrentCompleted(context.Context, string, int64) (*types.KnowledgeRevisionSource, error)
}

type knowledgeRevisionSourceExact3Backfiller interface {
	BackfillExact3(
		context.Context,
		string,
		revisionsource.KnowledgeRevisionSourceExact3RequestV1,
	) (*revisionsource.KnowledgeRevisionSourceExact3ResultV1, error)
}

// KnowledgeRevisionSourceHandler exposes only the human-admin backfill
// operations; it never serves file bytes.
type KnowledgeRevisionSourceHandler struct {
	service knowledgeRevisionSourceBackfiller
}

func NewKnowledgeRevisionSourceHandler(
	service knowledgeRevisionSourceBackfiller,
) *KnowledgeRevisionSourceHandler {
	return &KnowledgeRevisionSourceHandler{service: service}
}

type knowledgeRevisionSourceReceiptV1 struct {
	Contract          string `json:"contract"`
	KnowledgeID       string `json:"knowledge_id"`
	ParseAttempt      int64  `json:"parse_attempt"`
	RevisionSourceID  string `json:"revision_source_id"`
	FileSHA256        string `json:"file_sha256"`
	ObjectSHA256      string `json:"object_sha256"`
	Size              int64  `json:"size"`
	MimeType          string `json:"mime_type"`
	PageCount         int    `json:"page_count"`
	ManifestAlgorithm string `json:"manifest_algorithm"`
	ManifestDigest    string `json:"manifest_digest"`
	ChunkCount        int    `json:"chunk_count"`
	BindingDigest     string `json:"binding_digest"`
	RetentionState    string `json:"retention_state"`
}

func (h *KnowledgeRevisionSourceHandler) Backfill(c *gin.Context) {
	knowledgeID := strings.TrimSpace(c.Param("id"))
	attempt, err := strconv.ParseInt(c.Param("attempt"), 10, 64)
	if err != nil || knowledgeID == "" || attempt <= 0 || h == nil || h.service == nil {
		writeKnowledgeRevisionSourceError(c, revisionsource.ErrRevisionSourceMismatch)
		return
	}
	source, err := h.service.BackfillCurrentCompleted(c.Request.Context(), knowledgeID, attempt)
	if err != nil || source == nil || source.PageCount == nil {
		if err == nil {
			err = revisionsource.ErrRevisionSourceMismatch
		}
		writeKnowledgeRevisionSourceError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": knowledgeRevisionSourceReceiptV1{
		Contract: "knowledge-revision-source.v1", KnowledgeID: source.KnowledgeID,
		ParseAttempt: source.ParseAttempt, RevisionSourceID: source.RevisionSourceID,
		FileSHA256: source.FileSHA256, ObjectSHA256: source.ObjectSHA256,
		Size: source.Size, MimeType: source.MimeType, PageCount: *source.PageCount,
		ManifestAlgorithm: source.ManifestAlgorithm, ManifestDigest: source.ManifestDigest,
		ChunkCount: source.ChunkCount, BindingDigest: source.BindingDigest,
		RetentionState: source.RetentionState,
	}})
}

type knowledgeRevisionSourceRecorder interface {
	RecordMissingSource(
		context.Context, string, int64, bool,
	) (*types.KnowledgeRevisionSource, types.RevisionSourceRecordOutcome, error)
}

type knowledgeRevisionSourceRecordReceiptV1 struct {
	Contract          string `json:"contract"`
	Outcome           string `json:"outcome"`
	KnowledgeID       string `json:"knowledge_id"`
	ParseAttempt      int64  `json:"parse_attempt"`
	RevisionSourceID  string `json:"revision_source_id"`
	FileSHA256        string `json:"file_sha256"`
	Size              int64  `json:"size"`
	MimeType          string `json:"mime_type"`
	ManifestAlgorithm string `json:"manifest_algorithm"`
	ManifestDigest    string `json:"manifest_digest"`
	ChunkCount        int    `json:"chunk_count"`
	RetentionState    string `json:"retention_state"`
}

// Record records the commit-time source row of an attempt committed without one (S11g). It is a
// dry run unless dry_run=false is given explicitly.
func (h *KnowledgeRevisionSourceHandler) Record(c *gin.Context) {
	recorder, ok := any(h.service).(knowledgeRevisionSourceRecorder)
	knowledgeID := strings.TrimSpace(c.Param("id"))
	attempt, err := strconv.ParseInt(c.Param("attempt"), 10, 64)
	dryRun, validMode := recordDryRun(c.Request.URL.RawQuery)
	if !ok || err != nil || knowledgeID == "" || attempt <= 0 || !validMode {
		writeKnowledgeRevisionSourceError(c, revisionsource.ErrRevisionSourceMismatch)
		return
	}
	source, outcome, err := recorder.RecordMissingSource(c.Request.Context(), knowledgeID, attempt, dryRun)
	if err != nil || source == nil {
		if err == nil {
			err = revisionsource.ErrRevisionSourceMismatch
		}
		writeKnowledgeRevisionSourceError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": knowledgeRevisionSourceRecordReceiptV1{
		Contract: "knowledge-revision-source-record.v1", Outcome: string(outcome),
		KnowledgeID: source.KnowledgeID, ParseAttempt: source.ParseAttempt,
		RevisionSourceID: source.RevisionSourceID, FileSHA256: source.FileSHA256,
		Size: source.Size, MimeType: source.MimeType,
		ManifestAlgorithm: source.ManifestAlgorithm, ManifestDigest: source.ManifestDigest,
		ChunkCount: source.ChunkCount, RetentionState: source.RetentionState,
	}})
}

// recordDryRun reads dry_run from the raw query: absent means a dry run; exactly one "true" or
// "false" is honoured; a malformed query, a repeated or empty value is rejected (#513 review R2).
func recordDryRun(rawQuery string) (bool, bool) {
	values, err := url.ParseQuery(rawQuery)
	if err != nil {
		return false, false
	}
	modes, present := values["dry_run"]
	switch {
	case !present:
		return true, true
	case len(modes) != 1:
		return false, false
	case modes[0] == "true":
		return true, true
	case modes[0] == "false":
		return false, true
	default:
		return false, false
	}
}

func (h *KnowledgeRevisionSourceHandler) BackfillExact3(c *gin.Context) {
	backfiller, ok := any(h.service).(knowledgeRevisionSourceExact3Backfiller)
	if !ok || strings.TrimSpace(c.Param("kb_id")) == "" || c.Request == nil || c.Request.Body == nil {
		writeKnowledgeRevisionSourceError(c, revisionsource.ErrRevisionSourceMismatch)
		return
	}
	var request revisionsource.KnowledgeRevisionSourceExact3RequestV1
	decoder := json.NewDecoder(io.LimitReader(c.Request.Body, 32<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil || !decodedToEOF(decoder) {
		writeKnowledgeRevisionSourceError(c, revisionsource.ErrRevisionSourceMismatch)
		return
	}
	result, err := backfiller.BackfillExact3(c.Request.Context(), c.Param("kb_id"), request)
	if err != nil || result == nil {
		if err == nil {
			err = revisionsource.ErrRevisionSourceMismatch
		}
		writeKnowledgeRevisionSourceError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": result})
}

func writeKnowledgeRevisionSourceError(c *gin.Context, err error) {
	status := http.StatusConflict
	code := "REVISION_SOURCE_MISMATCH"
	switch {
	case errors.Is(err, revisionsource.ErrRevisionSourceBackfillDisabled):
		status = http.StatusServiceUnavailable
		code = "REVISION_SOURCE_BACKFILL_DISABLED"
	case errors.Is(err, revisionsource.ErrRevisionSourcePageUnavailable):
		status = http.StatusUnprocessableEntity
		code = "PAGE_UNAVAILABLE"
	case errors.Is(err, revisionsource.ErrRevisionSourceExact3Conflict):
		code = "REVISION_SOURCE_EXACT3_CONFLICT_STOP"
	}
	errorBody := gin.H{"code": code, "message": "revision source request failed"}
	var exact3Err *revisionsource.KnowledgeRevisionSourceExact3Error
	if errors.As(err, &exact3Err) && exact3Err.FailedRole != "" {
		errorBody["failed_role"] = exact3Err.FailedRole
		if exact3Err.Receipt != nil {
			errorBody["receipt"] = exact3Err.Receipt
		}
	}
	c.JSON(status, gin.H{"success": false, "error": errorBody})
}

// decodedToEOF reports whether nothing follows the decoded request value.
func decodedToEOF(decoder *json.Decoder) bool {
	var trailing any
	return decoder.Decode(&trailing) == io.EOF
}
