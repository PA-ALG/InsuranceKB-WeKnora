package handler

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/service"
	apperrors "github.com/Tencent/WeKnora/internal/errors"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/utils"
	"github.com/gin-gonic/gin"
)

type ProductIngestionHandler struct {
	knowledge *KnowledgeHandler
	bridge    service.ProductIngestionBridge
}

func NewProductIngestionHandler(knowledge *KnowledgeHandler, bridge service.ProductIngestionBridge) *ProductIngestionHandler {
	return &ProductIngestionHandler{knowledge: knowledge, bridge: bridge}
}
func productGatewayError(c *gin.Context, status int, code string) {
	c.AbortWithStatusJSON(status, gin.H{"success": false, "error": gin.H{"code": code, "message": code}})
}
func productGatewayAccessError(c *gin.Context, err error) {
	status := http.StatusForbidden
	if app, ok := apperrors.IsAppError(err); ok {
		status = app.HTTPCode
	}
	productGatewayError(c, status, "PRODUCT_INGESTION_ACCESS_DENIED")
}
func productGatewayBridgeError(c *gin.Context, err error) {
	status := http.StatusServiceUnavailable
	var upstream *service.ProductIngestionBridgeError
	if errors.As(err, &upstream) {
		status = upstream.StatusCode
	}
	productGatewayError(c, status, "PRODUCT_INGESTION_UNAVAILABLE")
}

// Route registration must retain the existing browser auth/API-key gate and upload write guards.
// These current RAW and WIKI ACL checks also protect the body-carried retry entry.
func (h *ProductIngestionHandler) access(c *gin.Context, write, capability bool) (context.Context, bool, bool) {
	if h.knowledge == nil {
		productGatewayError(c, 503, "PRODUCT_INGESTION_UNAVAILABLE")
		return nil, false, false
	}
	_, rawID, tenant, rawPermission, err := h.knowledge.validateKnowledgeBaseAccess(c)
	if err != nil {
		productGatewayAccessError(c, err)
		return nil, false, false
	}
	ctx := c.Request.Context()
	if h.bridge == nil || h.bridge.Scope().RawKnowledgeBaseID != rawID || h.bridge.Scope().TenantID != tenant {
		if capability {
			return ctx, false, true
		}
		productGatewayError(c, 404, "PRODUCT_INGESTION_NOT_CONFIGURED")
		return nil, false, false
	}
	scope := h.bridge.Scope()
	_, _, wikiTenant, wikiPermission, err := h.knowledge.validateKnowledgeBaseAccessWithKBID(c, scope.WikiKnowledgeBaseID)
	if err != nil {
		productGatewayAccessError(c, err)
		return nil, false, false
	}
	if wikiTenant != scope.TenantID {
		productGatewayError(c, 403, "PRODUCT_INGESTION_ACCESS_DENIED")
		return nil, false, false
	}
	if write {
		for _, permission := range []types.OrgMemberRole{rawPermission, wikiPermission} {
			if permission != types.OrgRoleAdmin && permission != types.OrgRoleEditor {
				productGatewayError(c, 403, "PRODUCT_INGESTION_ACCESS_DENIED")
				return nil, false, false
			}
		}
		for _, id := range []string{rawID, scope.WikiKnowledgeBaseID} {
			if err := h.knowledge.requireKBOwnershipOrAdmin(c, id); err != nil {
				productGatewayAccessError(c, err)
				return nil, false, false
			}
		}
	}
	return context.WithValue(ctx, types.TenantIDContextKey, tenant), true, true
}

func (h *ProductIngestionHandler) Capabilities(c *gin.Context) {
	_, enabled, ok := h.access(c, false, true)
	if !ok {
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"enabled": enabled}})
}

func (h *ProductIngestionHandler) Upload(c *gin.Context) {
	ctx, _, ok := h.access(c, true, false)
	if !ok {
		return
	}
	if h.bridge.MaxUploadBytes() <= 0 || h.bridge.MaxUploadFiles() <= 0 {
		productGatewayError(c, 503, "PRODUCT_INGESTION_UNAVAILABLE")
		return
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, h.bridge.MaxUploadBytes())
	err := c.Request.ParseMultipartForm(8 << 20)
	form := c.Request.MultipartForm
	if form != nil {
		defer form.RemoveAll()
	}
	if err != nil || form == nil || len(form.Value) > 0 || len(form.File) != 1 {
		productGatewayError(c, 400, "PRODUCT_INGESTION_ORIGINAL_FILES_REQUIRED")
		return
	}
	files := form.File["files"]
	if len(files) == 0 || len(files) > h.bridge.MaxUploadFiles() {
		productGatewayError(c, 400, "PRODUCT_INGESTION_UPLOAD_CAPACITY_EXCEEDED")
		return
	}
	for _, file := range files {
		if file.Size <= 0 || file.Size > utils.GetMaxFileSizeMB()*1024*1024 {
			productGatewayError(c, 400, "PRODUCT_INGESTION_FILE_SIZE_INVALID")
			return
		}
	}
	// Read the original multipart files once before admission so the durable
	// run records exactly which unique content it can recover after a crash.
	unique := make([]*multipart.FileHeader, 0, len(files))
	manifest := make([]service.ProductUploadManifestMaterial, 0, len(files))
	seen := make(map[string]bool, len(files))
	for _, file := range files {
		reader, openErr := file.Open()
		if openErr != nil {
			productGatewayError(c, 400, "PRODUCT_INGESTION_ORIGINAL_FILES_REQUIRED")
			return
		}
		digest := sha256.New()
		written, copyErr := io.Copy(digest, reader)
		closeErr := reader.Close()
		if copyErr != nil || closeErr != nil || written != file.Size {
			productGatewayError(c, 400, "PRODUCT_INGESTION_ORIGINAL_FILES_REQUIRED")
			return
		}
		fingerprint := hex.EncodeToString(digest.Sum(nil))
		contentKey := fmt.Sprintf("%s:%d", fingerprint, file.Size)
		if seen[contentKey] {
			continue
		}
		seen[contentKey] = true
		manifest = append(manifest, service.ProductUploadManifestMaterial{
			Ordinal: len(unique), OriginalFilename: file.Filename,
			FileSize: file.Size, FileSHA256: fingerprint,
		})
		unique = append(unique, file)
	}
	// Admission is durable before the first original reaches KnowledgeService.
	run, err := h.bridge.CreateRun(ctx, len(unique), manifest, len(files)-len(unique))
	if err != nil {
		productGatewayBridgeError(c, err)
		return
	}
	if run == nil || run.RunID == "" {
		productGatewayError(c, 503, "PRODUCT_INGESTION_UNAVAILABLE")
		return
	}
	accepted := 0
	for ordinal, file := range unique {
		metadata := map[string]string{"product_ingestion_upload": fmt.Sprintf("%s:%d", run.RunID, ordinal)}
		knowledge, err := h.knowledge.kgService.CreateKnowledgeFromFile(ctx, h.bridge.Scope().RawKnowledgeBaseID, file, metadata, nil, "", nil, "web", nil)
		if err == nil && knowledge != nil {
			accepted++
		} else {
			var duplicate *types.DuplicateKnowledgeError
			if errors.As(err, &duplicate) && duplicate != nil && knowledge != nil && duplicate.Knowledge != nil && knowledge.ID == duplicate.Knowledge.ID &&
				knowledge.TenantID == h.bridge.Scope().TenantID && knowledge.KnowledgeBaseID == h.bridge.Scope().RawKnowledgeBaseID &&
				knowledge.Type == "file" && knowledge.ParseStatus != "failed" && knowledge.FileSize == manifest[ordinal].FileSize &&
				knowledge.FileSHA256 == manifest[ordinal].FileSHA256 {
				accepted++
			}
		}
		// Never repeat an uncertain save. Incomplete groups remain durable until their deadline.
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"run_id": run.RunID, "accepted_file_count": accepted, "rejected_file_count": len(files) - accepted}})
}

func (h *ProductIngestionHandler) List(c *gin.Context) {
	ctx, _, ok := h.access(c, false, false)
	if !ok {
		return
	}
	runs, err := h.bridge.ListRuns(ctx)
	if err != nil {
		productGatewayBridgeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"runs": runs}})
}
func (h *ProductIngestionHandler) Get(c *gin.Context) {
	ctx, _, ok := h.access(c, false, false)
	if !ok {
		return
	}
	run, err := h.bridge.GetRun(ctx, c.Param("run_id"))
	if err != nil {
		productGatewayBridgeError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": run})
}
func (h *ProductIngestionHandler) RetryFields(c *gin.Context) {
	ctx, _, ok := h.access(c, true, false)
	if !ok {
		return
	}
	var body struct {
		FieldKeys []string `json:"field_keys"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 64<<10)
	decoder := json.NewDecoder(c.Request.Body)
	decoder.DisallowUnknownFields()
	if decoder.Decode(&body) != nil || len(body.FieldKeys) == 0 {
		productGatewayError(c, 400, "PRODUCT_INGESTION_RETRY_FIELDS_INVALID")
		return
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		productGatewayError(c, 400, "PRODUCT_INGESTION_RETRY_FIELDS_INVALID")
		return
	}
	seen := map[string]bool{}
	for _, key := range body.FieldKeys {
		if key == "" || len(key) > 256 || strings.TrimSpace(key) != key || seen[key] {
			productGatewayError(c, 400, "PRODUCT_INGESTION_RETRY_FIELDS_INVALID")
			return
		}
		seen[key] = true
	}
	run, err := h.bridge.RetryFields(ctx, c.Param("run_id"), body.FieldKeys)
	if err != nil {
		productGatewayBridgeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": run})
}

func (h *ProductIngestionHandler) RetryProcessing(c *gin.Context) {
	ctx, _, ok := h.access(c, true, false)
	if !ok {
		return
	}
	raw, err := io.ReadAll(http.MaxBytesReader(c.Writer, c.Request.Body, 1024))
	if err != nil {
		productGatewayError(c, 400, "PRODUCT_INGESTION_RETRY_PROCESSING_INVALID")
		return
	}
	fields, err := closedG3PlatformReleaseObject(raw, "expected_version")
	var version int64
	if err != nil || json.Unmarshal(fields["expected_version"], &version) != nil || version < 1 || version > 9007199254740991 {
		productGatewayError(c, 400, "PRODUCT_INGESTION_RETRY_PROCESSING_INVALID")
		return
	}
	run, err := h.bridge.RetryProcessing(ctx, c.Param("run_id"), version)
	if err != nil {
		productGatewayBridgeError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"success": true, "data": run})
}
