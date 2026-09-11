package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/json"
	"strings"
	"testing"
	"time"
	"unicode"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func cfg42Native(t *testing.T, texts ...string) *types.ReadResult {
	t.Helper()
	original, _ := testNativeResult830G2(t)
	var p conceptNativeProjection830G2
	require.NoError(t, json.Unmarshal(original.NativeStructure.SanitizedJSON, &p))
	p.Pages = nil
	markdown := strings.Join(texts, "\n\n")
	p.MarkdownSHA256 = testSHA830G2(markdown)
	start := 0
	for i, text := range texts {
		runes := []rune(text)
		page := conceptNativePage830G2{PageNumber: i + 1, GlobalCodepointStart: start, GlobalCodepointEnd: start + len(runes), PageTextSHA256: testSHA830G2(text), WidthPoints: "100", HeightPoints: "200", BBoxes: []conceptNativeBBox830G2{}}
		for j, c := range runes {
			if !unicode.IsSpace(c) {
				page.BBoxes = append(page.BBoxes, conceptNativeBBox830G2{GlobalCodepointStart: start + j, GlobalCodepointEnd: start + j + 1, BBox: [4]int{j * 100, 1000, j*100 + 90, 2000}})
			}
		}
		p.Pages = append(p.Pages, page)
		start += len(runes) + 2
	}
	raw, err := canonicalJSON830G2(p)
	require.NoError(t, err)
	sha := testSHA256Bytes830G2(raw)
	return &types.ReadResult{MarkdownContent: markdown, NativeStructure: &types.NativeStructureArtifact{SchemaVersion: p.Contract, SourceSHA256: p.SourceSHA256, RawSHA256: sha, SanitizedSHA256: sha, SanitizedJSON: raw}}
}

func cfg42AuthorityFixture(t *testing.T) (*ConceptSourceAuthorityService830G2, ConceptCitationAuthorityRequest830G2) {
	t.Helper()
	bridge, doc, scope, evidence, block := nativeIndexFixture830G2(t)
	doc.result = cfg42Native(t, "引言", block.Text)
	now := time.Unix(1_800_000_000, 0).UTC()
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x72}, ed25519.SeedSize))
	codec, err := NewSchemaWikiCitationTokenCodec("citation-key", map[string]ed25519.PrivateKey{"citation-key": key}, func() time.Time { return now })
	require.NoError(t, err)
	bridge.codec = codec
	req := ConceptCitationAuthorityRequest830G2{Scope: scope, ReleaseID: "release-g3", ActivationEpoch: 6, CandidateHash: testSHA830G2("candidate"), MemberID: "member-1", CitationID: "citation-123456789012345678901234", Evidence: evidence, SourceBlock: block}
	req.TrustedG3 = true
	return bridge, req
}

func TestCFG42WrongRecordedPageUsesVerifiedBlockAnchor(t *testing.T) {
	bridge, req := cfg42AuthorityFixture(t)
	authority, err := bridge.IssueConceptCitationAuthority830G2(context.Background(), req)
	require.NoError(t, err)
	require.Equal(t, 1, authority.PageNumber)
	raw, err := json.Marshal(authority)
	require.NoError(t, err)
	var view map[string]any
	require.NoError(t, json.Unmarshal(raw, &view))
	require.Equal(t, "concept-citation-content-authority.830.g3.v1", view["contract"])
	locator, ok := view["source_locator"].(map[string]any)
	require.True(t, ok)
	require.Equal(t, float64(2), locator["actual_page_number"])
	require.Equal(t, float64(7), locator["start"])
	require.Equal(t, float64(11), locator["global_start"])
}

func TestCFG42TrustedGateTokenReopenAndTamperedLocator(t *testing.T) {
	bridge, req := cfg42AuthorityFixture(t)
	ctx := context.Background()
	untrusted := req
	untrusted.TrustedG3 = false
	_, err := bridge.IssueConceptCitationAuthority830G2(ctx, untrusted)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	authority, err := bridge.IssueConceptCitationAuthority830G2(ctx, req)
	require.NoError(t, err)
	contents, err := bridge.ReadConceptCitationByOpaqueToken830G2(ctx, req.Scope, authority.OpaqueToken, req)
	require.NoError(t, err)
	require.Equal(t, []byte("pdf"), contents)
	_, err = bridge.ReadConceptCitationByOpaqueToken830G2(ctx, req.Scope, authority.OpaqueToken, untrusted)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	claims, err := bridge.codec.verifyConcept830G2(authority.OpaqueToken)
	require.NoError(t, err)
	mutations := []func(*ConceptCitationContentAuthority830G2){
		func(a *ConceptCitationContentAuthority830G2) { a.SourceLocator.ActualPageNumber = 1 },
		func(a *ConceptCitationContentAuthority830G2) {
			a.SourceLocator.SourceBlockSHA256 = testSHA830G2("wrong block")
		},
		func(a *ConceptCitationContentAuthority830G2) { a.SourceLocator.Start++; a.SourceLocator.GlobalStart++ },
	}
	for _, change := range mutations {
		changed := claims.Authority
		l := *changed.SourceLocator
		changed.SourceLocator = &l
		change(&changed)
		changed.AuthorityDigest, err = computeConceptCitationAuthorityDigest830G2(changed)
		require.NoError(t, err)
		token, err := bridge.codec.issueConcept830G2(req.Scope, changed, bridge.codec.now())
		require.NoError(t, err)
		_, err = bridge.ReadConceptCitationByOpaqueToken830G2(ctx, req.Scope, token, req)
		require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2, "even signed locator must match pinned evidence replay")
	}
	changed := claims.Authority
	changed.Contract = conceptCitationAuthorityContract830G2
	_, err = computeConceptCitationAuthorityDigest830G2(changed)
	require.Error(t, err)
	changed = claims.Authority
	changed.SourceLocator = nil
	_, err = computeConceptCitationAuthorityDigest830G2(changed)
	require.Error(t, err)
}

func TestCFG42BlockAnchorRejectsDriftAmbiguityCrossPageAndMissingBoxes(t *testing.T) {
	_, req := cfg42AuthorityFixture(t)
	for _, tc := range []struct {
		name   string
		pages  []string
		mutate func(*types.ConceptEvidence830G2, *types.ConceptSourceBlock830G2)
	}{
		{"repeated title within page", []string{"title A😀 prefix A😀 suffix", "后文"}, nil},
		{"repeated complete block", []string{"prefix A😀 suffix prefix A😀 suffix", "后文"}, nil},
		{"misaligned offsets", []string{"引言", "prefix A😀 suffix"}, func(e *types.ConceptEvidence830G2, b *types.ConceptSourceBlock830G2) { e.Start-- }},
		{"foreign block", []string{"引言", "prefix A😀 suffix"}, func(e *types.ConceptEvidence830G2, b *types.ConceptSourceBlock830G2) { b.BlockID = "other" }},
		{"cross page quote", []string{"prefix A", "😀 suffix"}, func(e *types.ConceptEvidence830G2, b *types.ConceptSourceBlock830G2) {
			b.Text = "prefix A\n\n😀 suffix"
			e.Quote = "A\n\n😀"
			e.End = e.Start + 4
			e.QuoteHash = testSHA830G2(e.Quote)
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			e, b := req.Evidence, req.SourceBlock
			if tc.mutate != nil {
				tc.mutate(&e, &b)
			}
			index, err := prepareConceptNativeQuoteIndex830G2(cfg42Native(t, tc.pages...), e.SourceHash, e.ParserIdentity)
			require.NoError(t, err)
			_, locator, err := resolveConceptSourceBlockQuote830G3(index, e, b)
			if tc.name == "repeated title within page" {
				require.NoError(t, err)
				require.NotNil(t, locator)
				require.Equal(t, 1, locator.ActualPageNumber)
			} else {
				require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
			}
		})
	}
	index, err := prepareConceptNativeQuoteIndex830G2(cfg42Native(t, "引言", req.SourceBlock.Text), req.Evidence.SourceHash, req.Evidence.ParserIdentity)
	require.NoError(t, err)
	delete(index.pages[2].boxes, 11)
	_, _, err = resolveConceptSourceBlockQuote830G3(index, req.Evidence, req.SourceBlock)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
}

func TestCFG42StrictFallbackKeepsFrozenV1Shape(t *testing.T) {
	bridge, doc, scope, e, b := nativeIndexFixture830G2(t)
	_ = doc
	_, _, locator, err := bridge.verifyEvidenceLocated830G3(context.Background(), scope, e, &b, true)
	require.NoError(t, err)
	require.Nil(t, locator)
	source, bbox, err := bridge.verifyEvidence(context.Background(), scope, e, &b)
	require.NoError(t, err)
	req := ConceptCitationAuthorityRequest830G2{TrustedG3: true, Scope: scope, Evidence: e}
	a := conceptCitationAuthorityFromLocated830G3(req, source, bbox, locator, "key", 1)
	old := conceptCitationAuthorityFromResolved830G2(req, source, bbox, "key", 1)
	raw, err := json.Marshal(a)
	require.NoError(t, err)
	want, err := json.Marshal(old)
	require.NoError(t, err)
	require.Equal(t, want, raw)
	require.NotContains(t, string(raw), "source_locator")
}
