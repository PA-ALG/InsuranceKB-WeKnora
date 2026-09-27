package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type batchConceptHTTPServiceSpy830G3 struct {
	*schemaWikiHTTPServiceSpy
	createCalls       int
	legacyG1Calls     int
	legacyG2Calls     int
	readCalls         int
	preparationID     string
	candidate         json.RawMessage
	preparationResult *types.WikiReleasePreparation
	readResult        *service.BatchConceptPreparationRead830G3
	err               error
}

func (spy *batchConceptHTTPServiceSpy830G3) CreateEntityPageGraphDraft830G1(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	preparationID string,
	_ json.RawMessage,
) (*types.WikiReleasePreparation, error) {
	spy.legacyG1Calls++
	spy.preparationID = preparationID
	return spy.preparationResult, spy.err
}

func (spy *batchConceptHTTPServiceSpy830G3) CreateConceptFreeWikiDraft830G2(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	preparationID string,
	_ json.RawMessage,
) (*types.WikiReleasePreparation, error) {
	spy.legacyG2Calls++
	spy.preparationID = preparationID
	return spy.preparationResult, spy.err
}

type batchConceptQueryHTTPSpy830G3 struct {
	g3                  bool
	queryCalls          int
	legacyPageCalls     int
	legacyCitationCalls int
	releaseOccurrences  []string
	preparationPresent  bool
}

func (spy *batchConceptQueryHTTPSpy830G3) ReadConceptPage830G2(
	context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope, string, string,
) (*service.ConceptPageRead830G2, error) {
	spy.legacyPageCalls++
	return &service.ConceptPageRead830G2{Contract: "concept-page-read.830.g2.v1"}, nil
}

func (spy *batchConceptQueryHTTPSpy830G3) ReadConceptPageQuery830G3(
	_ context.Context, _ types.WikiReleasePrincipal, _ types.WikiReleaseScope, _ string,
	releases []string, preparationPresent bool,
) (*service.ConceptPageRead830G2, error) {
	spy.queryCalls++
	spy.releaseOccurrences = append([]string(nil), releases...)
	spy.preparationPresent = preparationPresent
	if spy.g3 && (len(releases) > 1 || len(releases) == 1 && strings.TrimSpace(releases[0]) == "" || preparationPresent) {
		return nil, service.ErrSchemaWikiPreparationInvalid
	}
	return &service.ConceptPageRead830G2{Contract: "concept-page-read.830.g2.v1"}, nil
}

func (spy *batchConceptQueryHTTPSpy830G3) IssueConceptCitationAuthority830G2(
	context.Context, types.WikiReleasePrincipal, types.WikiReleaseScope, string, string, string,
) (*service.ConceptCitationContentAuthority830G2, error) {
	spy.legacyCitationCalls++
	return &service.ConceptCitationContentAuthority830G2{Contract: "concept-citation-content-authority.830.g2.v1"}, nil
}

func (spy *batchConceptQueryHTTPSpy830G3) IssueConceptCitationQuery830G3(
	_ context.Context, _ types.WikiReleasePrincipal, _ types.WikiReleaseScope, _, _ string,
	releases []string, preparationPresent bool,
) (*service.ConceptCitationContentAuthority830G2, error) {
	spy.queryCalls++
	spy.releaseOccurrences = append([]string(nil), releases...)
	spy.preparationPresent = preparationPresent
	if len(releases) == 0 || strings.TrimSpace(releases[0]) == "" ||
		spy.g3 && (len(releases) != 1 || preparationPresent) {
		return nil, service.ErrSchemaWikiCitationUnavailable
	}
	return &service.ConceptCitationContentAuthority830G2{Contract: "concept-citation-content-authority.830.g2.v1"}, nil
}

func (spy *batchConceptHTTPServiceSpy830G3) CreateBatchConceptDraft830G3(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	preparationID string,
	candidate json.RawMessage,
) (*types.WikiReleasePreparation, error) {
	spy.createCalls++
	spy.preparationID = preparationID
	spy.candidate = append(json.RawMessage(nil), candidate...)
	return spy.preparationResult, spy.err
}

func (spy *batchConceptHTTPServiceSpy830G3) LoadBatchConceptPreparation830G3(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	preparationID string,
) (*service.BatchConceptPreparationRead830G3, error) {
	spy.readCalls++
	spy.preparationID = preparationID
	return spy.readResult, spy.err
}

func batchConceptHTTPContext830G3(
	t *testing.T, method string, body string,
) (*gin.Context, *httptest.ResponseRecorder) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	request := httptest.NewRequest(method, "/", strings.NewReader(body))
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "batch-reviewer"}
	c.Request = request.WithContext(types.WithPrincipal(request.Context(), principal))
	c.Set(types.TenantIDContextKey.String(), uint64(10003))
	c.Set(types.PrincipalContextKey.String(), principal)
	c.Params = gin.Params{
		{Key: "kb_id", Value: "wiki-g3"},
		{Key: "space_id", Value: "space-g3"},
		{Key: "raw_kb_id", Value: "raw-g3"},
		{Key: "preparation_id", Value: "batch-preparation"},
	}
	return c, recorder
}

func TestDecodeBatchConceptCreateDraft830G3AcceptsOnlyExactTwoKeyBody(t *testing.T) {
	valid := `{"preparation_id":"batch-preparation","batch_concept_candidate_bundle":{"contract":"batch-concept-candidate-bundle.830.g3.v1"}}`
	tests := []struct {
		name        string
		body        string
		wantVariant string
		wantError   bool
	}{
		{name: "exact", body: valid, wantVariant: "batch-concept-830-g3"},
		{name: "missing candidate", body: `{"preparation_id":"batch-preparation"}`, wantError: true},
		{name: "missing preparation", body: `{"batch_concept_candidate_bundle":{}}`, wantError: true},
		{name: "null candidate", body: `{"preparation_id":"batch-preparation","batch_concept_candidate_bundle":null}`, wantError: true},
		{name: "mixed g2", body: strings.TrimSuffix(valid, "}") + `,"concept_candidate_bundle":{}}`, wantError: true},
		{name: "extra", body: strings.TrimSuffix(valid, "}") + `,"extra":true}`, wantError: true},
		{name: "duplicate", body: `{"preparation_id":"one","preparation_id":"two","batch_concept_candidate_bundle":{}}`, wantError: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			gin.SetMode(gin.TestMode)
			recorder := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(recorder)
			c.Request = httptest.NewRequest(http.MethodPost, "/", strings.NewReader(test.body))
			var request schemaWikiCreateDraftRequest
			variant, err := decodeSchemaWikiCreateDraftRequest(c, &request)
			if test.wantError {
				require.ErrorIs(t, err, service.ErrSchemaWikiPreparationInvalid)
				require.Empty(t, variant)
				return
			}
			require.NoError(t, err)
			require.Equal(t, test.wantVariant, variant)
		})
	}
}

func TestCreateBatchConceptDraft830G3DispatchesExactCandidate(t *testing.T) {
	candidate := `{"contract":"batch-concept-candidate-bundle.830.g3.v1"}`
	body := `{"preparation_id":"batch-preparation","batch_concept_candidate_bundle":` + candidate + `}`
	spy := &batchConceptHTTPServiceSpy830G3{
		schemaWikiHTTPServiceSpy: &schemaWikiHTTPServiceSpy{},
		preparationResult:        &types.WikiReleasePreparation{ID: "batch-preparation"},
	}
	h := NewSchemaWikiHandler(nil, spy)
	c, recorder := batchConceptHTTPContext830G3(t, http.MethodPost, body)

	h.CreateDraft(c)

	require.Equal(t, http.StatusCreated, recorder.Code)
	require.Equal(t, 1, spy.createCalls)
	require.Equal(t, "batch-preparation", spy.preparationID)
	require.JSONEq(t, candidate, string(spy.candidate))
}

func TestCreateBatchConceptDraft830G3RejectsInvalidUnicodeWireBeforeDispatch(t *testing.T) {
	invalidUTF8 := append([]byte(`{"preparation_id":"batch-`), 0xff)
	invalidUTF8 = append(invalidUTF8, []byte(`","batch_concept_candidate_bundle":{}}`)...)
	for _, test := range []struct {
		name string
		body []byte
	}{
		{name: "invalid UTF-8", body: invalidUTF8},
		{name: "lone high surrogate", body: []byte(`{"preparation_id":"batch-\uD800","batch_concept_candidate_bundle":{}}`)},
		{name: "lone low surrogate", body: []byte(`{"preparation_id":"batch-\uDC00","batch_concept_candidate_bundle":{}}`)},
	} {
		t.Run(test.name, func(t *testing.T) {
			spy := &batchConceptHTTPServiceSpy830G3{
				schemaWikiHTTPServiceSpy: &schemaWikiHTTPServiceSpy{},
				preparationResult:        &types.WikiReleasePreparation{ID: "must-not-be-created"},
			}
			h := NewSchemaWikiHandler(nil, spy)
			c, recorder := batchConceptHTTPContext830G3(t, http.MethodPost, string(test.body))

			h.CreateDraft(c)

			require.Equal(t, http.StatusBadRequest, recorder.Code, recorder.Body.String())
			require.Zero(t, spy.createCalls, "malformed G3 identity must fail before service dispatch")
		})
	}
}

func TestCreateBatchConceptDraft830G3AcceptsValidUnicodeWireForms(t *testing.T) {
	for _, test := range []struct {
		name   string
		wireID string
		wantID string
	}{
		{name: "literal U+FFFD", wireID: "batch-�", wantID: "batch-�"},
		{name: "escaped U+FFFD", wireID: `batch-\uFFFD`, wantID: "batch-�"},
		{name: "emoji surrogate pair", wireID: `batch-\uD83D\uDE00`, wantID: "batch-😀"},
		{name: "literal backslash surrogate text", wireID: `batch-\\uD800`, wantID: `batch-\uD800`},
		{name: "literal backslash line separator text", wireID: `batch-\\u2028`, wantID: `batch-\u2028`},
		{name: "NFC", wireID: "批次-准备", wantID: "批次-准备"},
	} {
		t.Run(test.name, func(t *testing.T) {
			body := `{"preparation_id":"` + test.wireID + `","batch_concept_candidate_bundle":{}}`
			spy := &batchConceptHTTPServiceSpy830G3{
				schemaWikiHTTPServiceSpy: &schemaWikiHTTPServiceSpy{},
				preparationResult:        &types.WikiReleasePreparation{ID: test.wantID},
			}
			h := NewSchemaWikiHandler(nil, spy)
			c, recorder := batchConceptHTTPContext830G3(t, http.MethodPost, body)

			h.CreateDraft(c)

			require.Equal(t, http.StatusCreated, recorder.Code, recorder.Body.String())
			require.Equal(t, 1, spy.createCalls)
			require.Equal(t, test.wantID, spy.preparationID)
		})
	}
}

func TestCreateDraftLegacyVariantsKeepMalformedUnicodeCompatibility(t *testing.T) {
	malformedIDs := map[string][]byte{
		"invalid UTF-8":       {0xff},
		"lone high surrogate": []byte(`\uD800`),
		"lone low surrogate":  []byte(`\uDC00`),
	}
	for _, variant := range []struct {
		name      string
		field     string
		wantCalls func(*batchConceptHTTPServiceSpy830G3) int
	}{
		{name: "G1", field: "entity_page_manifest", wantCalls: func(spy *batchConceptHTTPServiceSpy830G3) int { return spy.legacyG1Calls }},
		{name: "G2", field: "concept_candidate_bundle", wantCalls: func(spy *batchConceptHTTPServiceSpy830G3) int { return spy.legacyG2Calls }},
	} {
		for name, malformed := range malformedIDs {
			t.Run(variant.name+"/"+name, func(t *testing.T) {
				body := append([]byte(`{"preparation_id":"batch-`), malformed...)
				body = append(body, []byte(`","`+variant.field+`":{}}`)...)
				spy := &batchConceptHTTPServiceSpy830G3{
					schemaWikiHTTPServiceSpy: &schemaWikiHTTPServiceSpy{},
					preparationResult:        &types.WikiReleasePreparation{ID: "legacy-preparation"},
				}
				h := NewSchemaWikiHandler(nil, spy)
				c, recorder := batchConceptHTTPContext830G3(t, http.MethodPost, string(body))

				h.CreateDraft(c)

				require.Equal(t, http.StatusCreated, recorder.Code, recorder.Body.String())
				require.Equal(t, 1, variant.wantCalls(spy))
				require.Equal(t, "batch-�", spy.preparationID)
			})
		}
	}
}

func TestBatchConceptPreparationID830G3IsNotNormalizedByHandler(t *testing.T) {
	const exactID = "  batch\npreparation  "
	t.Run("create", func(t *testing.T) {
		candidate := `{"contract":"batch-concept-candidate-bundle.830.g3.v1"}`
		body, err := json.Marshal(map[string]any{
			"preparation_id": exactID, "batch_concept_candidate_bundle": json.RawMessage(candidate),
		})
		require.NoError(t, err)
		spy := &batchConceptHTTPServiceSpy830G3{
			schemaWikiHTTPServiceSpy: &schemaWikiHTTPServiceSpy{},
			preparationResult:        &types.WikiReleasePreparation{ID: exactID},
		}
		h := NewSchemaWikiHandler(nil, spy)
		c, recorder := batchConceptHTTPContext830G3(t, http.MethodPost, string(body))

		h.CreateDraft(c)

		require.Equal(t, http.StatusCreated, recorder.Code, recorder.Body.String())
		require.Equal(t, exactID, spy.preparationID, "G3 service must receive exact decoded identity")
	})

	t.Run("read", func(t *testing.T) {
		spy := &batchConceptHTTPServiceSpy830G3{
			schemaWikiHTTPServiceSpy: &schemaWikiHTTPServiceSpy{},
			readResult: &service.BatchConceptPreparationRead830G3{
				Contract: "batch-concept-preparation-read.830.g3.v1", PreparationID: exactID,
			},
		}
		h := NewSchemaWikiHandler(nil, spy)
		c, recorder := batchConceptHTTPContext830G3(t, http.MethodGet, "")
		for index := range c.Params {
			if c.Params[index].Key == "preparation_id" {
				c.Params[index].Value = exactID
			}
		}

		h.ReadBatchConceptPreparation830G3(c)

		require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
		require.Equal(t, exactID, spy.preparationID, "G3 service must receive exact decoded route identity")
	})
}

func TestCreateBatchConceptDraft830G3AcceptsComplete342FixtureBelowEightMiB(t *testing.T) {
	body, err := os.ReadFile("../../harness/tests/fixtures/batch_concept_compile_830_g3/preparation-request.json")
	require.NoError(t, err)
	require.LessOrEqual(t, len(body), maxSchemaWikiRequestBytes)
	spy := &batchConceptHTTPServiceSpy830G3{
		schemaWikiHTTPServiceSpy: &schemaWikiHTTPServiceSpy{},
		preparationResult:        &types.WikiReleasePreparation{ID: "batch-g3-preparation-fixture"},
	}
	h := NewSchemaWikiHandler(nil, spy)
	c, recorder := batchConceptHTTPContext830G3(t, http.MethodPost, string(body))

	h.CreateDraft(c)

	require.Equal(t, http.StatusCreated, recorder.Code)
	require.Equal(t, 1, spy.createCalls)
	require.Equal(t, "fixture-g3-actual342", spy.preparationID)
	require.Greater(t, len(spy.candidate), 2_000_000)
}

func TestReadBatchConceptPreparation830G3ReturnsExactThirteenKeyEnvelope(t *testing.T) {
	for _, status := range []string{"DRAFT", "READY"} {
		t.Run(status, func(t *testing.T) {
			spy := &batchConceptHTTPServiceSpy830G3{
				schemaWikiHTTPServiceSpy: &schemaWikiHTTPServiceSpy{},
				readResult: &service.BatchConceptPreparationRead830G3{
					Contract: "batch-concept-preparation-read.830.g3.v1", ReadMode: "preparation",
					TenantID: 10003, SpaceID: "space-g3", RawKBID: "raw-g3", WikiKBID: "wiki-g3",
					PreparationID: "batch-preparation", Status: status,
					CandidateSHA256: strings.Repeat("a", 64), ExpectedBaseReleaseID: "base-release",
					ExpectedBaseActivationEpoch: 5,
					PageManifest: types.BatchConceptPageManifest830G3{
						Contract: "batch-concept-page-manifest.830.g3.v1", Members: []types.ConceptPageMember830G2{},
						MembersSHA256: strings.Repeat("b", 64), Audit: []types.ConceptAuditDisposition830G2{},
					},
					ReadSHA256: strings.Repeat("c", 64),
				},
			}
			h := NewSchemaWikiHandler(nil, spy)
			c, recorder := batchConceptHTTPContext830G3(t, http.MethodGet, "")

			h.ReadBatchConceptPreparation830G3(c)

			require.Equal(t, http.StatusOK, recorder.Code)
			require.Equal(t, 1, spy.readCalls)
			var envelope struct {
				Success bool                   `json:"success"`
				Data    map[string]interface{} `json:"data"`
			}
			require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &envelope))
			require.True(t, envelope.Success)
			require.Len(t, envelope.Data, 13)
			require.Equal(t, status, envelope.Data["status"])
			require.Equal(t, "batch-preparation", envelope.Data["preparation_id"])
		})
	}
}

func TestBatchConceptPageQuery830G3PreservesRawOccurrencesForAtomicServiceGate(t *testing.T) {
	for _, test := range []struct {
		name       string
		query      string
		wantStatus int
		wantValues []string
		wantPrep   bool
	}{
		{name: "current", wantStatus: http.StatusOK},
		{name: "pinned", query: "?release_id=release-g3", wantStatus: http.StatusOK, wantValues: []string{"release-g3"}},
		{name: "explicit empty", query: "?release_id=", wantStatus: http.StatusBadRequest, wantValues: []string{""}},
		{name: "repeated", query: "?release_id=release-g3&release_id=other", wantStatus: http.StatusBadRequest, wantValues: []string{"release-g3", "other"}},
		{name: "mixed preparation", query: "?release_id=release-g3&preparation_id=batch", wantStatus: http.StatusBadRequest, wantValues: []string{"release-g3"}, wantPrep: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			spy := &batchConceptQueryHTTPSpy830G3{g3: true}
			h := NewConceptFreeWikiHandler830G2(spy)
			c, recorder := batchConceptHTTPContext830G3(t, http.MethodGet, "")
			request := httptest.NewRequest(http.MethodGet, "/"+test.query, nil)
			c.Request = request.WithContext(c.Request.Context())
			c.Params = append(c.Params, gin.Param{Key: "member_id", Value: "overview-g3"})

			h.ReadPage(c)

			require.Equal(t, test.wantStatus, recorder.Code, recorder.Body.String())
			require.Equal(t, 1, spy.queryCalls)
			require.Zero(t, spy.legacyPageCalls)
			require.Equal(t, test.wantValues, spy.releaseOccurrences)
			require.Equal(t, test.wantPrep, spy.preparationPresent)
		})
	}
}

func TestBatchConceptCitationQuery830G3RejectsBeforeLegacyIssuer(t *testing.T) {
	for _, query := range []string{
		"?release_id=release-g3&release_id=other",
		"?release_id=release-g3&preparation_id=batch",
	} {
		spy := &batchConceptQueryHTTPSpy830G3{g3: true}
		h := NewConceptFreeWikiHandler830G2(spy)
		c, recorder := batchConceptHTTPContext830G3(t, http.MethodGet, "")
		request := httptest.NewRequest(http.MethodGet, "/"+query, nil)
		c.Request = request.WithContext(c.Request.Context())
		c.Params = append(c.Params,
			gin.Param{Key: "member_id", Value: "field-g3"},
			gin.Param{Key: "citation_id", Value: "citation-g3"},
		)

		h.PreviewCitation(c)

		require.Equal(t, http.StatusServiceUnavailable, recorder.Code, recorder.Body.String())
		require.Equal(t, 1, spy.queryCalls)
		require.Zero(t, spy.legacyCitationCalls, "malformed G3 query must not mint a token")
	}
}

func TestConceptQuery830G3AtomicEntryPreservesG2FirstValueCompatibility(t *testing.T) {
	for _, test := range []struct {
		name     string
		citation bool
		query    string
	}{
		{name: "page first G2 second G3", query: "?release_id=release-g2&release_id=release-g3&preparation_id=batch"},
		{name: "page first empty uses current", query: "?release_id=&release_id=release-g3&preparation_id="},
		{name: "page whitespace uses current", query: "?release_id=%20%20%20&preparation_id=batch"},
		{name: "citation first G2 second G3", citation: true, query: "?release_id=release-g2&release_id=release-g3&preparation_id=batch"},
	} {
		t.Run(test.name, func(t *testing.T) {
			spy := &batchConceptQueryHTTPSpy830G3{g3: false}
			h := NewConceptFreeWikiHandler830G2(spy)
			c, recorder := batchConceptHTTPContext830G3(t, http.MethodGet, "")
			request := httptest.NewRequest(http.MethodGet, "/"+test.query, nil)
			c.Request = request.WithContext(c.Request.Context())
			c.Params = append(c.Params, gin.Param{Key: "member_id", Value: "member-g2"})
			if test.citation {
				c.Params = append(c.Params, gin.Param{Key: "citation_id", Value: "citation-g2"})
				h.PreviewCitation(c)
			} else {
				h.ReadPage(c)
			}

			require.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
			require.Equal(t, 1, spy.queryCalls)
			require.Zero(t, spy.legacyPageCalls)
			require.Zero(t, spy.legacyCitationCalls)
			require.True(t, spy.preparationPresent)
		})
	}

	spy := &batchConceptQueryHTTPSpy830G3{g3: false}
	h := NewConceptFreeWikiHandler830G2(spy)
	c, recorder := batchConceptHTTPContext830G3(t, http.MethodGet, "")
	request := httptest.NewRequest(http.MethodGet, "/?release_id=%20%20", nil)
	c.Request = request.WithContext(c.Request.Context())
	c.Params = append(c.Params,
		gin.Param{Key: "member_id", Value: "member-g2"},
		gin.Param{Key: "citation_id", Value: "citation-g2"},
	)
	h.PreviewCitation(c)
	require.Equal(t, http.StatusServiceUnavailable, recorder.Code, recorder.Body.String())
	require.Zero(t, spy.queryCalls, "empty selected citation release is rejected before service dispatch")
}
