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
	"path"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
	"github.com/Tencent/WeKnora/internal/enterprise/expert"
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

// CitationView is the same verified evidence used by HTTP and MCP readers: a PDF text span or,
// for Office evidence, its captured block (S11d); exactly one of Span and Block is set.
type CitationView struct {
	Evidence release.EvidenceAt
	Source   release.SourceRef
	Span     *source.SpanView
	Block    *source.BlockView
}

type citationSourceFailure struct{ failure *source.Error }

func (e *citationSourceFailure) Error() string { return e.failure.Error() }
func (e *citationSourceFailure) Unwrap() error { return e.failure }

func citationSourceError(err error) error {
	var failure *source.Error
	if !errors.As(err, &failure) {
		failure = &source.Error{Code: source.ErrorUnavailable, Detail: "source artifact is unavailable"}
	}
	return &citationSourceFailure{failure: failure}
}

// ReadCitation follows an explicit release to its captured source and verifies
// both fingerprints and the exact quote. Source failures retain their own type
// so HTTP keeps its existing 503 mapping, distinct from release storage errors.
func ReadCitation(
	ctx context.Context, service *release.Service, pages *source.Service,
	p release.Principal, space, releaseID, slug string, index int,
) (*CitationView, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if service == nil {
		return nil, &release.Error{Code: release.ErrorServiceUnavailable, Detail: "release service is unavailable"}
	}
	at, err := service.Evidence(ctx, p, space, releaseID, slug, index)
	if err != nil {
		return nil, err
	}
	return verifySourceCitation(ctx, pages, p, space, at)
}

// verifySourceCitation opens the captured page of a PDF text span or an Office block and checks the quote.
func verifySourceCitation(
	ctx context.Context, pages *source.Service, p release.Principal, space string, at release.EvidenceAt,
) (*CitationView, error) {
	ev := at.Evidence
	ref, isSource := release.ParseSourceRef(ev.SourceRef)
	loc := ev.Locator
	office := source.OfficeKind(loc.Kind)
	if !isSource || (loc.Kind != "PDF_TEXT_SPAN" && !office) || loc.Page == nil || loc.Start == nil || loc.End == nil {
		return nil, &release.Error{
			Code: release.ErrorEvidenceUnsupported, Detail: "only PDF text spans and Office blocks can be opened",
		}
	}
	if office {
		return verifyBlockCitation(ctx, pages, source.Scope{TenantID: p.TenantID, SpaceID: space}, at, ref)
	}
	if pages == nil {
		return nil, citationSourceError(nil)
	}
	view, err := pages.Span(ctx, source.Scope{TenantID: p.TenantID, SpaceID: space},
		ref.KnowledgeID, ref.ParseAttempt, *loc.Page, *loc.Start, *loc.End)
	if err != nil {
		return nil, citationSourceError(err)
	}
	if err := ctx.Err(); err != nil {
		return nil, citationSourceError(err)
	}
	if view.DocumentSHA256 != ref.FileSHA256 || strings.ToLower(ev.FileSHA256) != ref.FileSHA256 ||
		view.Quote != ev.Quote {
		return nil, &release.Error{
			Code: release.ErrorEvidenceMismatch, Detail: "the captured source no longer matches this evidence",
		}
	}
	return &CitationView{Evidence: at, Source: ref, Span: view}, nil
}

// verifyBlockCitation re-reads the captured pages of Office evidence and locates its block with the
// same check as submission (S11d Spec §2.3); like a PDF citation it does not repeat the quote digest.
func verifyBlockCitation(
	ctx context.Context, pages *source.Service, scope source.Scope, at release.EvidenceAt, ref release.SourceRef,
) (*CitationView, error) {
	if pages == nil {
		return nil, citationSourceError(nil)
	}
	set, err := pages.Pages(ctx, scope, ref.KnowledgeID, ref.ParseAttempt)
	if err != nil {
		return nil, citationSourceError(err)
	}
	if err := ctx.Err(); err != nil {
		return nil, citationSourceError(err)
	}
	ev := at.Evidence
	loc := ev.Locator
	view, err := set.Locate(ooxml.Locator{
		Kind: loc.Kind, Slide: loc.Slide, BlockIndex: loc.BlockIndex, Sheet: loc.Sheet, CellRange: loc.CellRange,
	}, *loc.Page, *loc.Start, *loc.End)
	if err != nil || set.DocumentSHA256 != ref.FileSHA256 || strings.ToLower(ev.FileSHA256) != ref.FileSHA256 ||
		view.Quote != ev.Quote {
		return nil, &release.Error{
			Code: release.ErrorEvidenceMismatch, Detail: "the captured source no longer matches this evidence",
		}
	}
	return &CitationView{Evidence: at, Source: ref, Block: view}, nil
}

// citation opens one evidence object of an explicit release and re-verifies it against the
// captured page before returning the quote and its highlight (S4c-2b-2 Spec §3.4).
// An expert revision citation answers with its record when experts is configured (S9a).
func citation(
	c *gin.Context, service *release.Service, pages *source.Service, experts *expert.Service, spacesPath string,
) {
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
	ctx := c.Request.Context()
	at, err := service.Evidence(ctx, p, space, c.Param("release_id"), slug, index)
	if err != nil {
		writeError(c, err)
		return
	}
	if experts != nil && at.Evidence.Locator.Kind == expert.LocatorKind {
		expertCitation(c, experts, p, at)
		return
	}
	verified, err := verifySourceCitation(ctx, pages, p, space, at)
	if err != nil {
		var failure *citationSourceFailure
		if errors.As(err, &failure) {
			writeSourceError(c, err)
		} else {
			writeError(c, err)
		}
		return
	}
	at, ref, view := verified.Evidence, verified.Source, verified.Span
	file := fmt.Sprintf("%s/releases/%s/sources/%s/attempts/%d/file",
		strings.Replace(spacesPath, ":space_id", url.PathEscape(space), 1),
		url.PathEscape(at.ReleaseID), url.PathEscape(ref.KnowledgeID), ref.ParseAttempt)
	if verified.Block != nil {
		blockCitation(c, at, verified.Block, file)
		return
	}
	rects := make([][4]int, 0, len(view.Rects))
	for _, r := range view.Rects {
		rects = append(rects, [4]int{r.X0, r.Y0, r.X1, r.Y1})
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{
		"release_id": at.ReleaseID, "member": at.Slug, "evidence_index": at.Index, "origin": at.Origin,
		"source": citedSource(view.KnowledgeID, view.ParseAttempt, view.Document, view.DocumentSHA256, view.RevisedAt),
		"page":   gin.H{"number": view.Page, "width_points": view.WidthPoints, "height_points": view.HeightPoints},
		"start":  view.Start, "end": view.End, "quote": view.Quote,
		"highlight": gin.H{
			"coordinate_space": "normalized_0_1e6_top_left", "complete": view.Complete, "rects": rects,
		},
		"file": file,
	}})
}

// citedSource names the cited revision; revised_at (RFC 3339, UTC) is its time when known (SK-3 §4.3).
func citedSource(knowledgeID string, attempt int64, document, sha string, revisedAt time.Time) gin.H {
	out := gin.H{"knowledge_id": knowledgeID, "parse_attempt": attempt, "document": document, "file_sha256": sha}
	if !revisedAt.IsZero() {
		out["revised_at"] = revisedAt.UTC().Format(time.RFC3339)
	}
	return out
}

// blockCitation answers Office evidence with its captured block and locator. Office captures carry
// no geometry, so there is no highlight; a viewer opens the page and block (S11d Spec §2.3).
func blockCitation(c *gin.Context, at release.EvidenceAt, view *source.BlockView, file string) {
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{
		"release_id": at.ReleaseID, "member": at.Slug, "evidence_index": at.Index, "origin": at.Origin,
		"source": citedSource(view.KnowledgeID, view.ParseAttempt, view.Document, view.DocumentSHA256, view.RevisedAt),
		"page":   gin.H{"number": view.Page},
		"start":  view.Start, "end": view.End, "quote": view.Quote,
		"locator": view.Block.Locator,
		"block":   gin.H{"block_id": view.Block.ID, "start": view.Block.Start, "end": view.Block.End},
		"file":    file,
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
	tag := `"` + cited + `"`
	condition := c.GetHeader("If-None-Match")
	notModified := condition != "" && matchesReleaseETag(condition, tag)
	raw, name, ok := readSourceFile(c, files,
		source.Scope{TenantID: p.TenantID, SpaceID: space}, knowledgeID, cited, notModified)
	if !ok {
		return
	}
	releaseCacheHeaders(c, tag)
	c.Header("Content-Disposition", "inline; filename*=UTF-8''"+url.PathEscape(name))
	c.Data(http.StatusOK, citedMediaType(name), raw)
}

// citedMediaType names the media type of a cited original by its extension: the Office formats a
// capture supports (S11b), otherwise PDF, the only other format that is captured.
func citedMediaType(name string) string {
	switch strings.ToLower(path.Ext(name)) {
	case ".pptx":
		return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
	case ".docx":
		return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
	case ".xlsx":
		return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
	}
	return "application/pdf"
}

// readSourceFile checks the live source before confirming a cached copy or verifying all bytes.
// Both callers authorize the reference first; the provider enforces the Space's RAW KB boundary.
// Each caller preserves its endpoint's validator matching rule; a match never skips the check.
// False means the response is already handled (304 or failure), with no file body to serve.
func readSourceFile(
	c *gin.Context, files SourceFiles, scope source.Scope, knowledgeID, fingerprint string,
	notModified bool,
) ([]byte, string, bool) {
	if files == nil {
		writeSourceError(c, nil)
		return nil, "", false
	}
	reader, name, err := files(c.Request.Context(), scope, knowledgeID)
	if err != nil {
		if errors.Is(err, source.ErrNotFound) {
			writeSourceError(c, &source.Error{Code: source.ErrorSourceNotFound, Detail: "source file was not found"})
			return nil, "", false
		}
		writeSourceError(c, nil)
		return nil, "", false
	}
	ctx := c.Request.Context()
	closeReader := sync.OnceFunc(func() { _ = reader.Close() })
	defer closeReader()
	// A cancelled request closes the file at once, which also ends a Read blocked on a slow
	// source; contextReader stops further reads. Nothing is written for a cancelled request.
	stop := context.AfterFunc(ctx, closeReader)
	defer stop()
	if ctx.Err() != nil {
		writeSourceError(c, nil)
		return nil, "", false
	}
	etag := `"` + fingerprint + `"`
	if notModified {
		closeReader()
		releaseCacheHeaders(c, etag)
		c.Status(http.StatusNotModified)
		return nil, "", false
	}
	raw, err := io.ReadAll(io.LimitReader(contextReader{ctx: ctx, r: reader}, maxSourceFile+1))
	if err != nil || ctx.Err() != nil {
		writeSourceError(c, nil)
		return nil, "", false
	}
	sum := sha256.Sum256(raw)
	if len(raw) > maxSourceFile || hex.EncodeToString(sum[:]) != fingerprint {
		c.AbortWithStatusJSON(http.StatusConflict, gin.H{
			"success": false, "code": errorSourceIntegrity, "error": "the stored file is not the cited one",
		})
		return nil, "", false
	}
	return raw, name, true
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
