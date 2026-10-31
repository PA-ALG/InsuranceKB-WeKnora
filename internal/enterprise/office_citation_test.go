package enterprise_test

// S11d acceptance (protected, written by Claude): a citation of Office evidence re-verifies the
// captured block and answers with its locator; the cited original keeps its Office media type
// (Spec docs/design/slices/S11d-Office证据回验与引用.md §2.3).
// Reuses newCitationWorld, citedArtifact, releaseMember, citingRef, pdfSHA, pdfBytes, digestOf, get,
// citation, filePath, data, code, machineKey, citationEndpointContext and the auth fakes of this
// package. RED until S11d implements it.

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise"
	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
	"github.com/Tencent/WeKnora/internal/enterprise/mcptools"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/middleware"
)

type citedUnit struct {
	text    string
	locator ooxml.Locator
}

func citedInt(n int) *int { return &n }

// officeArtifact captures a synthetic Office file named name with fingerprint sha as k-1 attempt 2:
// each page is its units joined by a blank line, as S11b builds it.
func officeArtifact(t *testing.T, name, sha string, pages ...[]citedUnit) *source.Artifact {
	t.Helper()
	structure := &ooxml.Structure{
		Contract: ooxml.Contract, Extractor: ooxml.ExtractorIdentity, Format: name[strings.LastIndex(name, ".")+1:],
		ParserIdentitySHA256: digestOf([]byte(ooxml.ExtractorIdentity)), SourceSHA256: sha,
	}
	for i, units := range pages {
		page := ooxml.Page{Number: i + 1, Blocks: []ooxml.Block{}}
		texts := make([]string, 0, len(units))
		offset := 0
		for j, u := range units {
			if j > 0 {
				offset += 2
			}
			end := offset + utf8.RuneCountInString(u.text)
			page.Blocks = append(page.Blocks, ooxml.Block{
				ID: fmt.Sprintf("p%d/b%d", i+1, j+1), Start: offset, End: end, Locator: u.locator,
			})
			texts = append(texts, u.text)
			offset = end
		}
		page.Text = strings.Join(texts, "\n\n")
		page.TextSHA256 = digestOf([]byte(page.Text))
		structure.Pages = append(structure.Pages, page)
	}
	native, err := ooxml.Encode(structure)
	require.NoError(t, err)
	return &source.Artifact{
		KnowledgeID: "k-1", ParseAttempt: 2, FileName: name, FileSHA256: sha,
		ParserIdentitySHA256: structure.ParserIdentitySHA256, NativeJSON: native,
	}
}

var (
	slideOne = ooxml.Locator{Kind: "PPTX_SHAPE", Slide: citedInt(1)}
	slideTwo = ooxml.Locator{Kind: "PPTX_SHAPE", Slide: citedInt(2)}
	blockTwo = ooxml.Locator{Kind: "DOCX_BLOCK", BlockIndex: citedInt(2)}
	rowThree = ooxml.Locator{Kind: "XLSX_CELL_RANGE", Sheet: "费率表", CellRange: "A3:XFD3"}
)

// deckArtifact: slide 1 has two paragraphs (one with a non-BMP character), slide 2 one.
func deckArtifact(t *testing.T) *source.Artifact {
	return officeArtifact(t, "产品介绍.pptx", pdfSHA,
		[]citedUnit{{"产品亮点", slideOne}, {"保障𠮷全面", slideOne}}, []citedUnit{{"适合人群", slideTwo}})
}

// officeEvidence is Office evidence as the Harness serializes it, citing citingRef.
func officeEvidence(locator ooxml.Locator, page, start, end int, quote string) map[string]any {
	fields := map[string]any{"kind": locator.Kind, "page": page, "start": start, "end": end, "shape_id": nil}
	if locator.Slide != nil {
		fields["slide"] = *locator.Slide
	}
	if locator.BlockIndex != nil {
		fields["block_index"] = *locator.BlockIndex
	}
	if locator.Sheet != "" {
		fields["sheet"], fields["cell_range"] = locator.Sheet, locator.CellRange
	}
	return map[string]any{
		"source_ref": citingRef, "file_sha256": pdfSHA, "quote": quote, "access_scope": "space", "locator": fields,
	}
}

// officeWorld publishes release-1 with one Office-sourced member over the given capture.
func officeWorld(t *testing.T, artifact *source.Artifact, evidence ...map[string]any) *citationWorld {
	t.Helper()
	world := newCitationWorld(t)
	world.pages.artifact = artifact
	world.store.releases["release-1"] = release.Release{ID: "release-1", Epoch: 1, Members: []release.Member{
		releaseMember(t, "1828/highlights", "SOURCE_SUPPORTED", evidence...),
	}}
	return world
}

func TestAnOfficeCitationOpensTheVerifiedQuoteWithItsBlockLocator(t *testing.T) {
	world := officeWorld(t, deckArtifact(t), officeEvidence(slideOne, 1, 6, 11, "保障𠮷全面"))
	w := get(world.router(t, machineKey()), citation("1828/highlights", "0"))
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	require.Equal(t, map[string]any{
		"release_id": "release-1", "member": "1828/highlights", "evidence_index": float64(0),
		"origin": "SOURCE_SUPPORTED",
		"source": map[string]any{
			"knowledge_id": "k-1", "parse_attempt": float64(2), "document": "产品介绍.pptx", "file_sha256": pdfSHA,
		},
		"page":  map[string]any{"number": float64(1)},
		"start": float64(6), "end": float64(11), "quote": "保障𠮷全面",
		"locator": map[string]any{"kind": "PPTX_SHAPE", "slide": float64(1)},
		"block":   map[string]any{"block_id": "p1/b2", "start": float64(6), "end": float64(11)},
		"file":    "/api/v1/enterprise/spaces/demo/releases/release-1/sources/k-1/attempts/2/file",
	}, data(t, w.Body.Bytes()), "an Office citation has no PDF geometry and no highlight")
	require.Equal(t, source.Scope{TenantID: 7, SpaceID: "demo"}, world.pages.scope)

	for name, c := range map[string]struct {
		artifact *source.Artifact
		evidence map[string]any
		locator  map[string]any
	}{
		"docx": {
			officeArtifact(t, "条款.docx", pdfSHA, []citedUnit{
				{"第一条 保险责任", ooxml.Locator{Kind: "DOCX_BLOCK", BlockIndex: citedInt(0)}},
				{"等待期为90日。", blockTwo},
			}),
			officeEvidence(blockTwo, 1, 10, 18, "等待期为90日。"),
			map[string]any{"kind": "DOCX_BLOCK", "block_index": float64(2)},
		},
		"xlsx": {
			officeArtifact(t, "费率.xlsx", pdfSHA, []citedUnit{
				{"年龄\t保费", ooxml.Locator{Kind: "XLSX_CELL_RANGE", Sheet: "费率表", CellRange: "A1:XFD1"}},
				{"30\t1200", rowThree},
			}),
			officeEvidence(rowThree, 1, 7, 14, "30\t1200"),
			map[string]any{"kind": "XLSX_CELL_RANGE", "sheet": "费率表", "cell_range": "A3:XFD3"},
		},
	} {
		t.Run(name, func(t *testing.T) {
			w := get(officeWorld(t, c.artifact, c.evidence).router(t, machineKey()), citation("1828/highlights", "0"))
			require.Equal(t, http.StatusOK, w.Code, w.Body.String())
			got := data(t, w.Body.Bytes())
			require.Equal(t, c.locator, got["locator"])
			require.Equal(t, c.evidence["quote"], got["quote"])
			require.Equal(t, map[string]any{"number": float64(1)}, got["page"])
			require.NotContains(t, got, "highlight")
		})
	}
}

func TestOfficeCitationFailuresAreTyped(t *testing.T) {
	replaced := digestOf([]byte("another deck"))
	cases := []struct {
		name     string
		artifact *source.Artifact
		evidence map[string]any
		status   int
		code     string
	}{
		{
			"quote no longer matches", deckArtifact(t), officeEvidence(slideOne, 1, 6, 11, "保障𠮷全心"),
			http.StatusConflict, release.ErrorEvidenceMismatch,
		},
		{
			"slide of another page", deckArtifact(t), officeEvidence(slideTwo, 1, 6, 11, "保障𠮷全面"),
			http.StatusConflict, release.ErrorEvidenceMismatch,
		},
		{
			"across two blocks", deckArtifact(t), officeEvidence(slideOne, 1, 0, 11, "产品亮点\n\n保障𠮷全面"),
			http.StatusConflict, release.ErrorEvidenceMismatch,
		},
		{
			"page beyond the deck", deckArtifact(t), officeEvidence(slideOne, 3, 0, 1, "产"),
			http.StatusConflict, release.ErrorEvidenceMismatch,
		},
		{
			"a locator of another Office format", deckArtifact(t), officeEvidence(blockTwo, 1, 0, 4, "产品亮点"),
			http.StatusConflict, release.ErrorEvidenceMismatch,
		},
		{
			"an Office locator on a PDF capture", citedArtifact(t), officeEvidence(slideOne, 1, 5, 13, "等待期为90日。"),
			http.StatusConflict, release.ErrorEvidenceMismatch,
		},
		{
			"the capture is another file", officeArtifact(t, "产品介绍.pptx", replaced,
				[]citedUnit{{"产品亮点", slideOne}, {"保障𠮷全面", slideOne}}),
			officeEvidence(slideOne, 1, 6, 11, "保障𠮷全面"), http.StatusConflict, release.ErrorEvidenceMismatch,
		},
		{"offsets missing", deckArtifact(t), func() map[string]any {
			e := officeEvidence(slideOne, 1, 6, 11, "保障𠮷全面")
			delete(e["locator"].(map[string]any), "start")
			return e
		}(), http.StatusUnprocessableEntity, release.ErrorEvidenceUnsupported},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			w := get(officeWorld(t, c.artifact, c.evidence).router(t, machineKey()), citation("1828/highlights", "0"))
			require.Equal(t, c.status, w.Code, w.Body.String())
			require.Equal(t, c.code, code(t, w.Body.Bytes()))
			require.NotContains(t, w.Body.String(), "保障", "a refusal never echoes source text")
		})
	}

	world := officeWorld(t, nil, officeEvidence(slideOne, 1, 6, 11, "保障𠮷全面"))
	world.pages.err = source.ErrNotCaptured
	w := get(world.router(t, machineKey()), citation("1828/highlights", "0"))
	require.Equal(t, http.StatusConflict, w.Code, w.Body.String())
	require.Equal(t, source.ErrorNotCaptured, code(t, w.Body.Bytes()))
}

// officeFileRouter mounts the routes over an original file named name whose bytes are pdfBytes.
func officeFileRouter(t *testing.T, world *citationWorld, name string) *gin.Engine {
	t.Helper()
	schema, err := os.ReadFile("../../contracts/candidate_bundle.schema.json")
	require.NoError(t, err)
	service := release.NewService(world.store, nil, map[string][]byte{"candidate_bundle": schema},
		release.WithPublisher(world.store))
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(middleware.Auth(tenantService{}, userService{}, nil, keyService{key: machineKey()}, nil))
	gate := middleware.NewAPIKeyRouteAuthorizer()
	api := r.Group("/api/v1", gate.Middleware())
	enterprise.Mount(api.Group("/enterprise/spaces/:space_id"), enterprise.Deps{
		Candidates: service, Sources: source.NewService(world.pages), Authorizer: gate,
		Files: func(context.Context, source.Scope, string) (io.ReadCloser, string, error) {
			return io.NopCloser(bytes.NewReader(pdfBytes)), name, nil
		},
	})
	return r
}

func TestTheCitedOfficeFileKeepsItsMediaType(t *testing.T) {
	for name, media := range map[string]string{
		"产品介绍.pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
		"条款.DOCX":   "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		"费率.xlsx":   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		"保险条款.pdf":  "application/pdf",
	} {
		t.Run(name, func(t *testing.T) {
			world := officeWorld(t, deckArtifact(t), officeEvidence(slideOne, 1, 6, 11, "保障𠮷全面"))
			w := get(officeFileRouter(t, world, name), filePath)
			require.Equal(t, http.StatusOK, w.Code, w.Body.String())
			require.Equal(t, pdfBytes, w.Body.Bytes())
			require.Equal(t, media, w.Header().Get("Content-Type"))
		})
	}
}

func TestMCPCitationOfOfficeEvidence(t *testing.T) {
	world := officeWorld(t, deckArtifact(t),
		officeEvidence(slideTwo, 2, 0, 4, "适合人群"), officeEvidence(slideTwo, 2, 0, 4, "适合人"))
	service := release.NewService(world.store, nil, nil, release.WithPublisher(world.store))
	citations := mcptools.NewCitations(service, source.NewService(world.pages))
	view, err := citations.Citation(citationEndpointContext(), 7, "demo", "release-1", "1828/highlights", 0)
	require.NoError(t, err)
	require.Equal(t, mcptools.Citation{Document: "产品介绍.pptx", Page: 2, Quote: "适合人群"}, view)

	_, err = citations.Citation(citationEndpointContext(), 7, "demo", "release-1", "1828/highlights", 1)
	var mismatch *release.Error
	require.ErrorAs(t, err, &mismatch)
	require.Equal(t, release.ErrorEvidenceMismatch, mismatch.Code)
}
