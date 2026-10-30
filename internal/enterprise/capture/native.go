package capture

import (
	"bytes"
	"encoding/json"
	"strings"
	"unicode"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
	"github.com/Tencent/WeKnora/internal/types"
)

const (
	// NativeCaptureMode is the parser capture the platform requests for captured PDFs.
	NativeCaptureMode = "builtin-pdfium-charbox-v1"
	// nativeContract is the full native locator contract; partial captures use
	// types.NativePartialLocatorContract.
	nativeContract  = "builtin-pdfium-native-locators.v1"
	coordinateSpace = "normalized_0_1e6_top_left"
)

// ParserConfig is the parse configuration for a captured PDF: the builtin parser is put first for
// PDFs, ahead of whatever engine the knowledge base or upload chose, because only it produces the
// native character boxes (requested with NativeCaptureMode) that sources and citations point into.
func ParserConfig(eff types.EffectiveProcessConfig) types.EffectiveProcessConfig {
	rules := []types.ParserEngineRule{{FileTypes: []string{"pdf"}, Engine: "builtin"}}
	eff.ChunkingConfig.ParserEngineRules = append(rules, eff.ChunkingConfig.ParserEngineRules...)
	return eff
}

// The native wire structures declare their fields in canonical JSON key order: encoding them
// reproduces the sanitized bytes exactly, which is how a capture proves it was not rewritten.
type nativeParserIdentity struct {
	CaptureMode      string `json:"capture_mode"`
	PDFiumVersion    string `json:"pdfium_version"`
	ProducerContract string `json:"producer_contract"`
	Pypdfium2Version string `json:"pypdfium2_version"`
}

type nativeBBox struct {
	BBox                 [4]int `json:"bbox"`
	GlobalCodepointEnd   int    `json:"global_codepoint_end"`
	GlobalCodepointStart int    `json:"global_codepoint_start"`
}

type nativePage struct {
	BBoxes               []nativeBBox                   `json:"bboxes"`
	GlobalCodepointEnd   int                            `json:"global_codepoint_end"`
	GlobalCodepointStart int                            `json:"global_codepoint_start"`
	HeightPoints         string                         `json:"height_points"`
	PageNumber           int                            `json:"page_number"`
	PageTextSHA256       string                         `json:"page_text_sha256"`
	UnavailableRanges    []types.NativeUnavailableRange `json:"unavailable_ranges,omitempty"`
	WidthPoints          string                         `json:"width_points"`
}

type nativeProjection struct {
	Contract             string               `json:"contract"`
	CoordinateSpace      string               `json:"coordinate_space"`
	MarkdownSHA256       string               `json:"markdown_sha256"`
	Pages                []nativePage         `json:"pages"`
	ParserIdentity       nativeParserIdentity `json:"parser_identity"`
	ParserIdentitySHA256 string               `json:"parser_identity_sha256"`
	SourceSHA256         string               `json:"source_sha256"`
}

// ParserIdentitySHA256 reads the parser identity digest from a native structure. It does not
// authorize anything: ValidateNative must still pass before the result is used or sealed.
func ParserIdentitySHA256(result *types.ReadResult) (string, error) {
	var header struct {
		ParserIdentitySHA256 string `json:"parser_identity_sha256"`
	}
	if result == nil || result.NativeStructure == nil ||
		json.Unmarshal(result.NativeStructure.SanitizedJSON, &header) != nil {
		return "", ErrUnavailable
	}
	return header.ParserIdentitySHA256, nil
}

func encodeNative(value any) ([]byte, error) {
	var output bytes.Buffer
	encoder := json.NewEncoder(&output)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(output.Bytes(), []byte("\n")), nil
}

// ValidateNative checks that a parse result's native structure belongs to the source bytes and
// parser identity, is the exact canonical encoding, and that every page and character box lines
// up with the Markdown: page order, page text digests, the two-newline page separator, box
// bounds and the locator coverage rules of the contract.
func ValidateNative(result *types.ReadResult, sourceSHA, parserIdentitySHA string) error {
	if result == nil || result.Error != "" || result.NativeStructure == nil || !ValidSHA256(sourceSHA) ||
		!ValidSHA256(parserIdentitySHA) {
		return ErrUnavailable
	}
	artifact := result.NativeStructure
	if artifact.SchemaVersion == ooxml.Contract {
		return validateOffice(result, sourceSHA, parserIdentitySHA)
	}
	if (artifact.SchemaVersion != nativeContract && artifact.SchemaVersion != types.NativePartialLocatorContract) ||
		artifact.SourceSHA256 != sourceSHA || artifact.RawSHA256 != artifact.SanitizedSHA256 ||
		sha256Hex(artifact.SanitizedJSON) != artifact.SanitizedSHA256 {
		return ErrUnavailable
	}
	var projection nativeProjection
	decoder := json.NewDecoder(bytes.NewReader(artifact.SanitizedJSON))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&projection) != nil || !atEOF(decoder) {
		return ErrUnavailable
	}
	canonical, err := encodeNative(projection)
	identityCanonical, identityErr := encodeNative(projection.ParserIdentity)
	if err != nil || identityErr != nil || !bytes.Equal(canonical, artifact.SanitizedJSON) ||
		projection.Contract != artifact.SchemaVersion || projection.SourceSHA256 != sourceSHA ||
		projection.MarkdownSHA256 != sha256Hex([]byte(result.MarkdownContent)) ||
		projection.CoordinateSpace != coordinateSpace ||
		!types.ValidNativeLocatorIdentity(projection.Contract, projection.ParserIdentity.ProducerContract) ||
		projection.ParserIdentity.CaptureMode != NativeCaptureMode ||
		projection.ParserIdentity.Pypdfium2Version == "" || projection.ParserIdentity.PDFiumVersion == "" ||
		projection.ParserIdentitySHA256 != sha256Hex(identityCanonical) ||
		projection.ParserIdentitySHA256 != parserIdentitySHA || len(projection.Pages) == 0 {
		return ErrUnavailable
	}
	markdown := []rune(result.MarkdownContent)
	lastEnd := 0
	for index := range projection.Pages {
		page := &projection.Pages[index]
		if !validPage(page, index, lastEnd, markdown) {
			return ErrUnavailable
		}
		pageRunes := markdown[page.GlobalCodepointStart:page.GlobalCodepointEnd]
		boxes := make(map[int][4]int, len(page.BBoxes))
		for _, box := range page.BBoxes {
			if box.GlobalCodepointEnd != box.GlobalCodepointStart+1 ||
				box.GlobalCodepointStart < page.GlobalCodepointStart ||
				box.GlobalCodepointEnd > page.GlobalCodepointEnd || !validBBox(box.BBox) {
				return ErrUnavailable
			}
			if unicode.IsSpace(pageRunes[box.GlobalCodepointStart-page.GlobalCodepointStart]) {
				return ErrUnavailable
			}
			if _, duplicate := boxes[box.GlobalCodepointStart]; duplicate {
				return ErrUnavailable
			}
			boxes[box.GlobalCodepointStart] = box.BBox
		}
		if !types.ValidateNativeLocatorCoverage(projection.Contract, pageRunes, page.GlobalCodepointStart, boxes,
			page.UnavailableRanges) {
			return ErrUnavailable
		}
		lastEnd = page.GlobalCodepointEnd
	}
	if lastEnd != len(markdown) {
		return ErrUnavailable
	}
	return nil
}

func validPage(page *nativePage, index, lastEnd int, markdown []rune) bool {
	if page.PageNumber != index+1 || (index == 0 && page.GlobalCodepointStart != 0) ||
		page.GlobalCodepointStart < lastEnd || page.GlobalCodepointEnd < page.GlobalCodepointStart ||
		page.GlobalCodepointEnd > len(markdown) ||
		!validDimension(page.WidthPoints) || !validDimension(page.HeightPoints) ||
		sha256Hex([]byte(string(markdown[page.GlobalCodepointStart:page.GlobalCodepointEnd]))) != page.PageTextSHA256 {
		return false
	}
	return index == 0 || (page.GlobalCodepointStart-lastEnd == 2 &&
		string(markdown[lastEnd:page.GlobalCodepointStart]) == "\n\n")
}

func validBBox(box [4]int) bool {
	return box[0] >= 0 && box[1] >= 0 && box[0] < box[2] && box[1] < box[3] &&
		box[2] <= 1_000_000 && box[3] <= 1_000_000
}

func validDimension(value string) bool {
	if value == "" || value[0] == '0' || strings.ContainsAny(value, "+-eE ") {
		return false
	}
	dot := false
	for index, character := range value {
		if character == '.' && !dot && index > 0 && index < len(value)-1 {
			dot = true
			continue
		}
		if character < '0' || character > '9' {
			return false
		}
	}
	return !dot || value[len(value)-1] != '0'
}
