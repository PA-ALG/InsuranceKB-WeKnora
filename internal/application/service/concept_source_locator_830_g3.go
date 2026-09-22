package service

import (
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/types"
)

const conceptCitationAuthorityContract830G3 = "concept-citation-content-authority.830.g3.v1"
const conceptSourceBlockLocatorContract830G3 = "concept-source-block-locator.830.g3.v1"

// Offsets are Unicode code points in the unchanged source block and native text.
type ConceptSourceBlockLocator830G3 struct {
	Contract          string `json:"contract"`
	SourceBlockSHA256 string `json:"source_block_sha256"`
	SourcePageNumber  int    `json:"source_page_number"`
	Start             int    `json:"start"`
	End               int    `json:"end"`
	BlockGlobalStart  int    `json:"block_global_start"`
	GlobalStart       int    `json:"global_start"`
	GlobalEnd         int    `json:"global_end"`
	ActualPageNumber  int    `json:"actual_page_number"`
}

func resolveConceptSourceBlockQuote830G3(index *conceptNativeQuoteIndex830G2, evidence types.ConceptEvidence830G2, block types.ConceptSourceBlock830G2, exactRanges ...map[string]g3FirstParseRange) (ConceptCitationBBox830G2, *ConceptSourceBlockLocator830G3, error) {
	empty := ConceptCitationBBox830G2{}
	if index == nil || index.sourceSHA != evidence.SourceHash || index.parserIdentitySHA != evidence.ParserIdentity || block.ConceptSourceIdentity830G2 != evidence.ConceptSourceIdentity830G2 || block.BlockID != evidence.BlockID || block.PageNumber != evidence.PageNumber || block.SourceType != evidence.SourceType || evidence.PageNumber <= 0 || evidence.OffsetUnit != "UNICODE_CODE_POINT" || !conceptEvidenceMatchesSourceText830G2(evidence, block.Text) {
		return empty, nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	old, oldErr := resolveConceptNativeQuoteInIndex830G2(index, evidence.SourceHash, evidence.ParserIdentity, evidence.PageNumber, evidence.Quote)
	var blockStart int
	if len(exactRanges) > 0 && exactRanges[0] != nil {
		r, ok := exactRanges[0][block.BlockID]
		if !ok || !g3FirstParseRangeMatches(index.text, block.Text, r) {
			return empty, nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		mapping := g3PlatformChunkPageMapping(types.RevisionManifestChunk{ID: block.BlockID, Content: block.Text}, index, exactRanges[0])
		if mapping.SourcePageNumber == nil || *mapping.SourcePageNumber != evidence.PageNumber {
			return empty, nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		blockStart = r.Start
	} else {
		at := strings.Index(index.text, block.Text)
		if at < 0 || strings.Index(index.text[at+1:], block.Text) >= 0 {
			return old, nil, oldErr
		}
		blockStart = utf8.RuneCountInString(index.text[:at])
	}
	start, end := blockStart+evidence.Start, blockStart+evidence.End
	for number, page := range index.pages {
		if start < page.globalStart || end > page.globalStart+len(page.runes) {
			continue
		}
		if string(page.runes[start-page.globalStart:end-page.globalStart]) != evidence.Quote {
			return empty, nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		bbox := ConceptCitationBBox830G2{CoordinateSpace: index.coordinateSpace, X0: 1_000_001, Y0: 1_000_001, X1: -1, Y1: -1}
		for offset, char := range []rune(evidence.Quote) {
			if unicode.IsSpace(char) {
				continue
			}
			box, ok := page.boxes[start+offset]
			if !ok || !validConceptBBox830G2(box) {
				return empty, nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			bbox.X0 = min(bbox.X0, box[0])
			bbox.Y0 = min(bbox.Y0, box[1])
			bbox.X1 = max(bbox.X1, box[2])
			bbox.Y1 = max(bbox.Y1, box[3])
		}
		if !validConceptBBox830G2([4]int{bbox.X0, bbox.Y0, bbox.X1, bbox.Y1}) || (oldErr == nil && evidence.PageNumber == number && old != bbox) {
			return empty, nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		locator := &ConceptSourceBlockLocator830G3{Contract: conceptSourceBlockLocatorContract830G3, SourceBlockSHA256: testSHA256830G2(block.Text), SourcePageNumber: evidence.PageNumber, Start: evidence.Start, End: evidence.End, BlockGlobalStart: blockStart, GlobalStart: start, GlobalEnd: end, ActualPageNumber: number}
		return bbox, locator, nil
	}
	// A unique block anchor cannot be replaced by an unrelated occurrence on another page.
	return empty, nil, ErrConceptSourceAuthorityUnavailable830G2
}

func conceptCitationAuthorityFromLocated830G3(request ConceptCitationAuthorityRequest830G2, source *types.KnowledgeRevisionSource, bbox ConceptCitationBBox830G2, locator *ConceptSourceBlockLocator830G3, keyID string, expires int64) ConceptCitationContentAuthority830G2 {
	authority := conceptCitationAuthorityFromResolved830G2(request, source, bbox, keyID, expires)
	if locator != nil && request.TrustedG3 {
		copyLocator := *locator
		authority.Contract = conceptCitationAuthorityContract830G3
		authority.SourceLocator = &copyLocator
	}
	return authority
}

func validConceptSourceLocatorShape830G3(authority ConceptCitationContentAuthority830G2) bool {
	if authority.Contract == conceptCitationAuthorityContract830G2 {
		return authority.SourceLocator == nil
	}
	l := authority.SourceLocator
	return authority.Contract == conceptCitationAuthorityContract830G3 && l != nil && l.Contract == conceptSourceBlockLocatorContract830G3 && validServiceSHA256(l.SourceBlockSHA256) && l.SourcePageNumber == authority.PageNumber && l.SourcePageNumber > 0 && l.Start >= 0 && l.End > l.Start && l.BlockGlobalStart >= 0 && l.GlobalStart >= l.BlockGlobalStart && l.GlobalEnd > l.GlobalStart && l.GlobalStart-l.BlockGlobalStart == l.Start && l.GlobalEnd-l.BlockGlobalStart == l.End && l.ActualPageNumber > 0 && l.ActualPageNumber <= authority.RevisionSource.PageCount
}
