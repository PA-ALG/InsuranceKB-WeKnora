package handler

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

type knowledgeRevisionSourceBackfiller interface {
	BackfillCurrentCompleted(context.Context, string, int64) (*types.KnowledgeRevisionSource, error)
}

// KnowledgeRevisionSourceHandler exposes only the human-admin backfill
// operation. Fixed bytes remain behind the server-derived Schema citation
// token route and are never addressable by caller-supplied revision metadata.
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
		writeKnowledgeRevisionSourceError(c, service.ErrRevisionSourceMismatch)
		return
	}
	source, err := h.service.BackfillCurrentCompleted(c.Request.Context(), knowledgeID, attempt)
	if err != nil || source == nil || source.PageCount == nil {
		if err == nil {
			err = service.ErrRevisionSourceMismatch
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

func writeKnowledgeRevisionSourceError(c *gin.Context, err error) {
	status := http.StatusConflict
	code := "REVISION_SOURCE_MISMATCH"
	switch {
	case errors.Is(err, service.ErrRevisionSourceBackfillDisabled):
		status = http.StatusServiceUnavailable
		code = "REVISION_SOURCE_BACKFILL_DISABLED"
	case errors.Is(err, service.ErrRevisionSourcePageUnavailable):
		status = http.StatusUnprocessableEntity
		code = "PAGE_UNAVAILABLE"
	}
	c.JSON(status, gin.H{
		"success": false,
		"error":   gin.H{"code": code, "message": "revision source request failed"},
	})
}
