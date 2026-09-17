package handler

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

type G3PlatformUploadLookup interface {
	LookupUpload(
		context.Context, types.WikiReleaseScope, string, int,
	) (*service.G3PlatformUploadSnapshotV1, error)
}

type G3PlatformSourceSnapshotCapturer interface {
	Capture(
		context.Context, types.WikiReleaseScope, string, int64,
	) (*service.G3PlatformSignedSourceSnapshotV1, error)
}

type G3PlatformBaseSnapshotReader interface {
	Read(
		context.Context, types.WikiReleaseScope, string, uint64,
	) (*service.G3PlatformSignedBaseSnapshotV1, error)
}

// G3PlatformSnapshotsHandler exposes machine-readable source custody under the
// same exact-scope and dual-KB ACL seal as Active Wiki reads.
type G3PlatformSnapshotsHandler struct {
	access   *WikiReleaseHandler
	uploads  G3PlatformUploadLookup
	sources  G3PlatformSourceSnapshotCapturer
	bases    G3PlatformBaseSnapshotReader
	reparser G3PlatformBoundReparser
}

type G3PlatformBoundReparser interface {
	BoundReparseKnowledge(context.Context, string, service.G3BoundReparseRequest) (types.G3BoundReparseReceipt, error)
	ReadBoundReparseKnowledge(context.Context, string, string) (types.G3BoundReparseReceipt, error)
}

func NewG3PlatformSnapshotsHandler(
	access *WikiReleaseHandler,
	uploads G3PlatformUploadLookup,
	sources G3PlatformSourceSnapshotCapturer,
	bases G3PlatformBaseSnapshotReader,
	reparser ...G3PlatformBoundReparser,
) *G3PlatformSnapshotsHandler {
	h := &G3PlatformSnapshotsHandler{
		access: access, uploads: uploads, sources: sources, bases: bases,
	}
	if len(reparser) > 0 {
		h.reparser = reparser[0]
	}
	return h
}

func (h *G3PlatformSnapshotsHandler) ReparseUpload(c *gin.Context) {
	_, scope, ok := h.request(c, h != nil && h.uploads != nil && h.reparser != nil)
	if !ok {
		return
	}
	runID := c.Param("run_id")
	ordinal, err := strconv.Atoi(c.Param("ordinal"))
	if err != nil || ordinal < 0 || !validG3PlatformPathID(runID) {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	uploader, err := h.uploads.LookupUpload(c.Request.Context(), scope, runID, ordinal)
	if err != nil || uploader == nil {
		if err == nil {
			err = service.ErrG3PlatformUploadNotFound
		}
		writeG3PlatformSnapshotError(c, err)
		return
	}
	if c.Request.Method == http.MethodGet {
		query := c.Request.URL.Query()
		if len(query) != 1 || len(query["recovery_key"]) != 1 {
			writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
			return
		}
		receipt, err := h.reparser.ReadBoundReparseKnowledge(c.Request.Context(), uploader.KnowledgeID, query.Get("recovery_key"))
		if err != nil || receipt.RunID != runID || receipt.Ordinal != ordinal {
			writeG3PlatformSnapshotError(c, service.ErrG3PlatformUploadNotFound)
			return
		}
		c.JSON(http.StatusOK, gin.H{"success": true, "data": receipt})
		return
	}
	if c.Request.Method != http.MethodPost {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	var body struct {
		ExpectedParseAttempt int64  `json:"expected_parse_attempt"`
		RecoveryKey          string `json:"recovery_key"`
		DeadlineAt           string `json:"deadline_at"`
	}
	decoder := json.NewDecoder(http.MaxBytesReader(c.Writer, c.Request.Body, 2048))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&body) != nil {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	deadline, err := time.Parse(time.RFC3339Nano, body.DeadlineAt)
	if err != nil || body.ExpectedParseAttempt <= 0 {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	receipt, err := h.reparser.BoundReparseKnowledge(c.Request.Context(), uploader.KnowledgeID, service.G3BoundReparseRequest{
		RawKBID: scope.RawKBID, RunID: runID, Ordinal: ordinal, ExpectedParseAttempt: body.ExpectedParseAttempt,
		RecoveryKey: body.RecoveryKey, DeadlineAt: deadline,
	})
	if err != nil {
		writeG3PlatformSnapshotError(c, service.ErrG3PlatformSnapshotUnavailable)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": receipt})
}

func (h *G3PlatformSnapshotsHandler) Upload(c *gin.Context) {
	_, scope, ok := h.request(c, h != nil && h.uploads != nil)
	if !ok {
		return
	}
	runID := strings.TrimSpace(c.Param("run_id"))
	ordinal, err := strconv.ParseInt(c.Param("ordinal"), 10, 32)
	if err != nil || ordinal < 0 || !validG3PlatformPathID(runID) {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	record, err := h.uploads.LookupUpload(c.Request.Context(), scope, runID, int(ordinal))
	if err != nil || record == nil {
		if err == nil {
			err = service.ErrG3PlatformSnapshotUnavailable
		}
		writeG3PlatformSnapshotError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": record})
}

func (h *G3PlatformSnapshotsHandler) FileBySHA256(c *gin.Context) {
	if h == nil {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotServiceUnavailable)
		return
	}
	lookup, available := h.uploads.(interface {
		LookupFileBySHA256(context.Context, types.WikiReleaseScope, string, string) (*service.G3PlatformFileFingerprintV1, error)
	})
	_, scope, ok := h.request(c, available)
	if !ok {
		return
	}
	sha := c.Param("sha256")
	if len(c.Request.URL.Query()) > 1 || (len(c.Request.URL.Query()) == 1 && !c.Request.URL.Query().Has("knowledge_id")) || len(c.Request.URL.Query()["knowledge_id"]) > 1 {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	record, err := lookup.LookupFileBySHA256(c.Request.Context(), scope, sha, c.Query("knowledge_id"))
	if err != nil || record == nil {
		if err == nil {
			err = service.ErrG3PlatformSnapshotUnavailable
		}
		writeG3PlatformSnapshotError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": record})
}

func (h *G3PlatformSnapshotsHandler) Source(c *gin.Context) {
	_, scope, ok := h.request(c, h != nil && h.sources != nil)
	if !ok {
		return
	}
	knowledgeID := strings.TrimSpace(c.Param("knowledge_id"))
	attempt, err := strconv.ParseInt(c.Param("attempt"), 10, 64)
	if err != nil || attempt <= 0 || !validG3PlatformPathID(knowledgeID) {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	record, err := h.sources.Capture(c.Request.Context(), scope, knowledgeID, attempt)
	if err != nil || record == nil {
		if err == nil {
			err = service.ErrG3PlatformSnapshotUnavailable
		}
		writeG3PlatformSnapshotError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": record})
}

func (h *G3PlatformSnapshotsHandler) Base(c *gin.Context) {
	_, scope, ok := h.request(c, h != nil && h.bases != nil)
	if !ok {
		return
	}
	releaseID := strings.TrimSpace(c.Param("release_id"))
	epoch, err := strconv.ParseUint(c.Param("epoch"), 10, 64)
	if err != nil || epoch == 0 || !validG3PlatformPathID(releaseID) {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	record, err := h.bases.Read(c.Request.Context(), scope, releaseID, epoch)
	if err != nil || record == nil {
		if err == nil {
			err = service.ErrG3PlatformSnapshotUnavailable
		}
		writeG3PlatformSnapshotError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": record})
}

func (h *G3PlatformSnapshotsHandler) request(
	c *gin.Context,
	dependencyReady bool,
) (types.WikiReleasePrincipal, types.WikiReleaseScope, bool) {
	if h == nil || h.access == nil || !dependencyReady {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotServiceUnavailable)
		return types.WikiReleasePrincipal{}, types.WikiReleaseScope{}, false
	}
	principal, scope, err := h.access.requestIdentity(c)
	if err != nil {
		writeG3PlatformSnapshotError(c, service.ErrG3PlatformSnapshotUnauthorized)
		return types.WikiReleasePrincipal{}, types.WikiReleaseScope{}, false
	}
	return principal, scope, true
}

var (
	errG3PlatformSnapshotInvalidRequest     = errors.New("G3_PLATFORM_REQUEST_INVALID")
	errG3PlatformSnapshotServiceUnavailable = errors.New("G3_PLATFORM_SNAPSHOT_SERVICE_UNAVAILABLE")
)

func writeG3PlatformSnapshotError(c *gin.Context, err error) {
	status := http.StatusServiceUnavailable
	code := "G3_PLATFORM_SNAPSHOT_SERVICE_UNAVAILABLE"
	switch {
	case errors.Is(err, errG3PlatformSnapshotInvalidRequest):
		status = http.StatusBadRequest
		code = "G3_PLATFORM_REQUEST_INVALID"
	case errors.Is(err, service.ErrG3PlatformSnapshotUnauthorized),
		errors.Is(err, service.ErrWikiReleaseAccessDenied):
		status = http.StatusForbidden
		code = "G3_PLATFORM_SNAPSHOT_UNAUTHORIZED"
	case errors.Is(err, service.ErrG3PlatformUploadNotFound):
		status = http.StatusNotFound
		code = "G3_PLATFORM_UPLOAD_NOT_FOUND"
	case errors.Is(err, service.ErrG3PlatformSnapshotUnavailable):
		status = http.StatusConflict
		code = "G3_PLATFORM_SNAPSHOT_UNAVAILABLE"
	}
	c.AbortWithStatusJSON(status, gin.H{
		"success": false,
		"error":   gin.H{"code": code, "message": code},
	})
}

func validG3PlatformPathID(value string) bool {
	if value == "" || len(value) > 160 || strings.TrimSpace(value) != value {
		return false
	}
	for _, char := range value {
		if (char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') ||
			(char >= '0' && char <= '9') || char == '-' || char == '_' {
			continue
		}
		return false
	}
	return true
}
