package handler

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type conceptPageHTTPStub830G2 struct {
	response  *service.ConceptPageRead830G2
	release   string
	authority *service.ConceptCitationContentAuthority830G2
	issueErr  error
}

func (s *conceptPageHTTPStub830G2) IssueConceptCitationAuthority830G2(_ context.Context, _ types.WikiReleasePrincipal, _ types.WikiReleaseScope, releaseID, _, _ string) (*service.ConceptCitationContentAuthority830G2, error) {
	s.release = releaseID
	return s.authority, s.issueErr
}

func (s *conceptPageHTTPStub830G2) ReadConceptPage830G2(
	_ context.Context,
	_ types.WikiReleasePrincipal,
	_ types.WikiReleaseScope,
	_ string,
	releaseID string,
) (*service.ConceptPageRead830G2, error) {
	s.release = releaseID
	return s.response, nil
}

func TestConceptFreeWikiHandler830G2ReadsExactReleaseQuery(t *testing.T) {
	gin.SetMode(gin.TestMode)
	stub := &conceptPageHTTPStub830G2{response: &service.ConceptPageRead830G2{
		Contract: "concept-page-read.830.g2.v1", ReadMode: "pinned", ReleaseID: "release-g2",
		ActivationEpoch: 1, CandidateHash: "candidate", SpaceID: "space-a",
		RawKBID: "raw-a", WikiKBID: "wiki-a",
		Member: types.ConceptPageMember830G2{Kind: "concept", MemberID: "concept-a"},
	}}
	handler := NewConceptFreeWikiHandler830G2(stub)
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Request = httptest.NewRequest(http.MethodGet, "/?release_id=release-g2", nil)
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}
	c.Request = c.Request.WithContext(types.WithPrincipal(c.Request.Context(), principal))
	c.Set(types.PrincipalContextKey.String(), principal)
	c.Set(types.TenantIDContextKey.String(), uint64(1))
	c.Params = gin.Params{
		{Key: "kb_id", Value: "wiki-a"}, {Key: "space_id", Value: "space-a"},
		{Key: "raw_kb_id", Value: "raw-a"}, {Key: "member_id", Value: "concept-a"},
	}

	handler.ReadPage(c)
	require.Equal(t, http.StatusOK, recorder.Code)
	require.Equal(t, "release-g2", stub.release)
	require.Contains(t, recorder.Body.String(), `"contract":"concept-page-read.830.g2.v1"`)
}

func TestConceptFreeWikiHandler830G2CitationPreviewIsTypedUnavailable(t *testing.T) {
	gin.SetMode(gin.TestMode)
	stub := &conceptPageHTTPStub830G2{issueErr: service.ErrConceptSourceAuthorityUnavailable830G2, response: &service.ConceptPageRead830G2{
		Contract: "concept-page-read.830.g2.v1", ReadMode: "pinned", ReleaseID: "release-g2",
		Citations: []service.ConceptPageCitation830G2{{CitationID: "citation-a", PageNumber: 1, Quote: "q"}},
	}}
	handler := NewConceptFreeWikiHandler830G2(stub)
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Request = httptest.NewRequest(http.MethodGet, "/?release_id=release-g2", nil)
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}
	c.Request = c.Request.WithContext(types.WithPrincipal(c.Request.Context(), principal))
	c.Set(types.PrincipalContextKey.String(), principal)
	c.Set(types.TenantIDContextKey.String(), uint64(1))
	c.Params = gin.Params{
		{Key: "kb_id", Value: "wiki-a"}, {Key: "space_id", Value: "space-a"},
		{Key: "raw_kb_id", Value: "raw-a"}, {Key: "member_id", Value: "concept-a"},
		{Key: "citation_id", Value: "citation-a"},
	}

	handler.PreviewCitation(c)
	require.Equal(t, http.StatusServiceUnavailable, recorder.Code)
	require.Equal(t, "release-g2", stub.release)
	require.Contains(t, recorder.Body.String(), "CONCEPT_SOURCE_AUTHORITY_UNAVAILABLE")
}

func TestConceptFreeWikiHandler830G2CitationPreviewReturnsClosedAuthority(t *testing.T) {
	gin.SetMode(gin.TestMode)
	stub := &conceptPageHTTPStub830G2{authority: &service.ConceptCitationContentAuthority830G2{Contract: "concept-citation-content-authority.830.g2.v1", ReleaseID: "release-g2", CitationID: "citation-a", OpaqueToken: "opaque"}}
	handler := NewConceptFreeWikiHandler830G2(stub)
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Request = httptest.NewRequest(http.MethodGet, "/?release_id=release-g2", nil)
	principal := types.Principal{Type: types.PrincipalWebUser, ID: "viewer"}
	c.Request = c.Request.WithContext(types.WithPrincipal(c.Request.Context(), principal))
	c.Set(types.PrincipalContextKey.String(), principal)
	c.Set(types.TenantIDContextKey.String(), uint64(1))
	c.Params = gin.Params{{Key: "kb_id", Value: "wiki-a"}, {Key: "space_id", Value: "space-a"}, {Key: "raw_kb_id", Value: "raw-a"}, {Key: "member_id", Value: "concept-a"}, {Key: "citation_id", Value: "citation-a"}}
	handler.PreviewCitation(c)
	require.Equal(t, http.StatusOK, recorder.Code)
	require.Contains(t, recorder.Body.String(), `"contract":"concept-citation-content-authority.830.g2.v1"`)
	require.Contains(t, recorder.Body.String(), `"opaque_token":"opaque"`)
}

func TestConceptSourceAuthorityHTTP830G2FailsClosed(t *testing.T) {
	gin.SetMode(gin.TestMode)
	for name, writeError := range map[string]func(*gin.Context, error){
		"review":   writeSchemaWikiError,
		"activate": writeWikiReleaseError,
	} {
		t.Run(name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(recorder)
			writeError(c, service.ErrConceptSourceAuthorityUnavailable830G2)
			require.Equal(t, http.StatusServiceUnavailable, recorder.Code)
			require.Contains(t, recorder.Body.String(), `"code":"CONCEPT_SOURCE_AUTHORITY_UNAVAILABLE"`)
			require.Contains(t, recorder.Body.String(), `"success":false`)
		})
	}
}
