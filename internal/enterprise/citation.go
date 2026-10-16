package enterprise

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

// SourceFiles opens the original file of a knowledge in the request Space's RAW KB and returns
// its file name. A knowledge outside that KB, deleted, or unknown returns source.ErrNotFound.
type SourceFiles func(ctx context.Context, scope source.Scope, knowledgeID string) (io.ReadCloser, string, error)

// maxSourceFile bounds how much of an original file is read to verify its fingerprint; a
// larger file cannot be the cited one and is refused rather than streamed unverified.
const maxSourceFile = 256 << 20

const errorSourceIntegrity = "SOURCE_INTEGRITY"

// citation opens one evidence object of an explicit release and re-verifies it against the
// captured page before returning the quote and its highlight (S4c-2b-2 Spec §3.4).
func citation(c *gin.Context, service *release.Service, pages *source.Service, spacesPath string) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	slug := c.Query("member")
	index, err := strconv.Atoi(c.Query("evidence"))
	if strings.TrimSpace(slug) == "" || err != nil || index < 0 {
		writeSourceError(c, invalidRequest("member and a non-negative evidence index are required"))
		return
	}
	space := c.Param("space_id")
	at, err := service.Evidence(c.Request.Context(), p, space, c.Param("release_id"), slug, index)
	if err != nil {
		writeError(c, err)
		return
	}
	ev := at.Evidence
	ref, isSource := release.ParseSourceRef(ev.SourceRef)
	loc := ev.Locator
	if !isSource || loc.Kind != "PDF_TEXT_SPAN" || loc.Page == nil || loc.Start == nil || loc.End == nil {
		writeError(c, &release.Error{
			Code: release.ErrorEvidenceUnsupported, Detail: "only PDF text spans can be opened",
		})
		return
	}
	if pages == nil {
		writeSourceError(c, nil)
		return
	}
	view, err := pages.Span(c.Request.Context(), source.Scope{TenantID: p.TenantID, SpaceID: space},
		ref.KnowledgeID, ref.ParseAttempt, *loc.Page, *loc.Start, *loc.End)
	if err != nil {
		writeSourceError(c, err)
		return
	}
	if view.DocumentSHA256 != ref.FileSHA256 || strings.ToLower(ev.FileSHA256) != ref.FileSHA256 ||
		view.Quote != ev.Quote {
		writeError(c, &release.Error{
			Code: release.ErrorEvidenceMismatch, Detail: "the captured source no longer matches this evidence",
		})
		return
	}
	rects := make([][4]int, 0, len(view.Rects))
	for _, r := range view.Rects {
		rects = append(rects, [4]int{r.X0, r.Y0, r.X1, r.Y1})
	}
	file := fmt.Sprintf("%s/releases/%s/sources/%s/attempts/%d/file",
		strings.Replace(spacesPath, ":space_id", url.PathEscape(space), 1),
		url.PathEscape(at.ReleaseID), url.PathEscape(ref.KnowledgeID), ref.ParseAttempt)
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{
		"release_id": at.ReleaseID, "member": at.Slug, "evidence_index": at.Index, "origin": at.Origin,
		"source": gin.H{
			"knowledge_id": view.KnowledgeID, "parse_attempt": view.ParseAttempt,
			"document": view.Document, "file_sha256": view.DocumentSHA256,
		},
		"page":  gin.H{"number": view.Page, "width_points": view.WidthPoints, "height_points": view.HeightPoints},
		"start": view.Start, "end": view.End, "quote": view.Quote,
		"highlight": gin.H{
			"coordinate_space": "normalized_0_1e6_top_left", "complete": view.Complete, "rects": rects,
		},
		"file": file,
	}})
}

// citedFile serves the original file of a (knowledge, attempt) the release cites, only after
// its bytes hash to the cited fingerprint: never another version, never unverified bytes.
func citedFile(c *gin.Context, service *release.Service, files SourceFiles) {
	p, ok := publishingRequest(c, service)
	if !ok {
		return
	}
	attempt, err := strconv.ParseInt(c.Param("attempt"), 10, 64)
	if err != nil || attempt <= 0 {
		writeSourceError(c, invalidRequest("a positive attempt is required"))
		return
	}
	space, knowledgeID := c.Param("space_id"), c.Param("knowledge_id")
	r, err := service.Release(c.Request.Context(), p, space, c.Param("release_id"))
	if err != nil {
		writeError(c, err)
		return
	}
	cited := citedFingerprint(r, knowledgeID, attempt)
	if cited == "" {
		writeSourceError(c, &source.Error{
			Code: source.ErrorSourceNotFound, Detail: "the release does not cite this source",
		})
		return
	}
	if files == nil {
		writeSourceError(c, nil)
		return
	}
	reader, name, err := files(c.Request.Context(), source.Scope{TenantID: p.TenantID, SpaceID: space}, knowledgeID)
	if err != nil {
		if errors.Is(err, source.ErrNotFound) {
			writeSourceError(c, &source.Error{Code: source.ErrorSourceNotFound, Detail: "source file was not found"})
			return
		}
		writeSourceError(c, nil)
		return
	}
	ctx := c.Request.Context()
	closeReader := sync.OnceFunc(func() { _ = reader.Close() })
	defer closeReader()
	// A cancelled request closes the file at once, which also ends a Read blocked on a slow
	// source; contextReader stops further reads. Nothing is written for a cancelled request.
	stop := context.AfterFunc(ctx, closeReader)
	defer stop()
	raw, err := io.ReadAll(io.LimitReader(contextReader{ctx: ctx, r: reader}, maxSourceFile+1))
	if err != nil || ctx.Err() != nil {
		writeSourceError(c, nil)
		return
	}
	sum := sha256.Sum256(raw)
	if len(raw) > maxSourceFile || hex.EncodeToString(sum[:]) != cited {
		c.AbortWithStatusJSON(http.StatusConflict, gin.H{
			"success": false, "code": errorSourceIntegrity, "error": "the stored file is not the cited one",
		})
		return
	}
	c.Header("ETag", `"`+cited+`"`)
	c.Header("Cache-Control", "private, max-age=3600")
	c.Header("Content-Disposition", "inline; filename*=UTF-8''"+url.PathEscape(name))
	c.Data(http.StatusOK, "application/pdf", raw)
}

// citedFingerprint is the file fingerprint a member of the release cites for (knowledge, attempt).
func citedFingerprint(r release.Release, knowledgeID string, attempt int64) string {
	for _, m := range r.Members {
		for _, raw := range m.EvidenceRefs {
			ref, ok := release.ParseSourceRef(raw)
			if ok && ref.KnowledgeID == knowledgeID && ref.ParseAttempt == attempt {
				return ref.FileSHA256
			}
		}
	}
	return ""
}

// contextReader refuses to read once the request context is done.
type contextReader struct {
	ctx context.Context
	r   io.Reader
}

func (c contextReader) Read(p []byte) (int, error) {
	if err := c.ctx.Err(); err != nil {
		return 0, err
	}
	return c.r.Read(p)
}

func invalidRequest(detail string) *source.Error {
	return &source.Error{Code: source.ErrorInvalidRequest, Detail: detail}
}
