// Package ooxml turns an Office original (PPTX, DOCX, XLSX) into the structure an enterprise capture
// stores: pages of verbatim text and located blocks. The text units and their positions come from the
// upstream internal/sourceloc package; this package adds the input limits enterprise uploads need and
// assembles pages and blocks (Spec docs/design/slices/S11b-Office结构采集与页文本.md).
package ooxml

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"
)

const (
	// Contract names the stored structure layout; it is the capture's native schema version.
	Contract = "enterprise-ooxml-structure.v1"
	// ExtractorIdentity names the extraction; its digest is the capture's parser identity. Bump it
	// when an upstream sourceloc change alters the units it produces.
	ExtractorIdentity = "enterprise.ooxml.sourceloc.v1"
)

const (
	// ErrorUnsupported means not pptx/docx/xlsx, or an OLE package (encrypted or legacy binary Office).
	ErrorUnsupported = "OFFICE_UNSUPPORTED"
	// ErrorTooLarge means a package limit was exceeded.
	ErrorTooLarge = "OFFICE_TOO_LARGE"
	// ErrorMalformed means a broken zip, missing or invalid parts, DTD/entity declarations, or invalid text.
	ErrorMalformed = "OFFICE_MALFORMED"
	// ErrorEmpty means the file has no text block at all.
	ErrorEmpty = "OFFICE_EMPTY"
)

// Error is a typed extraction or verification failure. Detail names parts or counts, never text.
type Error struct{ Code, Detail string }

func (e *Error) Error() string { return e.Code + ": " + e.Detail }

const (
	kindSlide = "PPTX_SHAPE"
	kindBlock = "DOCX_BLOCK"
	kindRows  = "XLSX_CELL_RANGE"
)

// Locator is one block's place in the original, using the contract's locator kinds. The fields are
// declared in JSON key order so the encoding is canonical.
type Locator struct {
	BlockIndex *int   `json:"block_index,omitempty"` // DOCX: 0-based body paragraph or table
	CellRange  string `json:"cell_range,omitempty"`  // XLSX: the whole row, A<r>:XFD<r>
	Kind       string `json:"kind"`
	Sheet      string `json:"sheet,omitempty"` // XLSX: sheet name
	Slide      *int   `json:"slide,omitempty"` // PPTX: 1-based slide in presentation order
}

// Block is one located text unit; Start/End are page-local Unicode code points, half-open.
type Block struct {
	ID      string  `json:"block_id"`
	End     int     `json:"end"`
	Locator Locator `json:"locator"`
	Start   int     `json:"start"`
}

// Page is one slide (PPTX), one sheet (XLSX) or the whole document (DOCX).
type Page struct {
	Blocks     []Block `json:"blocks"`
	Number     int     `json:"page_number"`
	TextSHA256 string  `json:"page_text_sha256"`
	Text       string  `json:"text"`
}

// Structure is the stored native artifact of an Office capture.
type Structure struct {
	Contract             string `json:"contract"`
	Extractor            string `json:"extractor"`
	Format               string `json:"format"`
	Pages                []Page `json:"pages"`
	ParserIdentitySHA256 string `json:"parser_identity_sha256"`
	SourceSHA256         string `json:"source_sha256"`
}

// Encode is the canonical encoding: declared key order, HTML not escaped, no trailing newline.
func Encode(s *Structure) ([]byte, error) {
	if s == nil {
		return nil, errors.New("ooxml: nil structure")
	}
	var out bytes.Buffer
	encoder := json.NewEncoder(&out)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(s); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(out.Bytes(), []byte("\n")), nil
}

// Decode reads a stored structure strictly (unknown fields and trailing data are refused) and
// verifies it completely before returning it.
func Decode(data []byte) (*Structure, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var s Structure
	if err := decoder.Decode(&s); err != nil {
		return nil, malformed("structure is not valid JSON")
	}
	if _, err := decoder.Token(); !errors.Is(err, io.EOF) {
		return nil, malformed("structure has trailing data")
	}
	if err := verify(&s); err != nil {
		return nil, err
	}
	return &s, nil
}

var rowRange = regexp.MustCompile(`^A([1-9][0-9]*):XFD([1-9][0-9]*)$`)

// pageCheck carries the per-format ordering state across the blocks of a structure.
type pageCheck struct {
	format      string
	lastIndex   int             // DOCX: block_index must increase
	usedSheets  map[string]bool // XLSX: a sheet appears on one page only
	pageSheet   string
	lastRowSeen int
}

func verify(s *Structure) error {
	if s.Contract != Contract || s.Extractor != ExtractorIdentity ||
		s.ParserIdentitySHA256 != digest([]byte(s.Extractor)) || !validSHA256(s.SourceSHA256) {
		return malformed("structure identity is invalid")
	}
	if _, ok := formatOf(s.Format); !ok || len(s.Pages) == 0 || (s.Format == "docx" && len(s.Pages) != 1) {
		return malformed("structure format or page count is invalid")
	}
	check := &pageCheck{format: s.Format, lastIndex: -1, usedSheets: map[string]bool{}}
	for i := range s.Pages {
		if err := check.page(&s.Pages[i], i+1); err != nil {
			return err
		}
	}
	return nil
}

func (c *pageCheck) page(p *Page, number int) error {
	if p.Number != number || p.Blocks == nil || !utf8.ValidString(p.Text) || strings.ContainsRune(p.Text, 0) ||
		digest([]byte(p.Text)) != p.TextSHA256 {
		return malformed(fmt.Sprintf("page %d text or digest is invalid", number))
	}
	runes := []rune(p.Text)
	ids := make(map[string]bool, len(p.Blocks))
	previousEnd := 0
	c.pageSheet, c.lastRowSeen = "", 0
	for i, b := range p.Blocks {
		if strings.TrimSpace(b.ID) == "" || ids[b.ID] || b.Start < previousEnd || b.Start >= b.End ||
			b.End > len(runes) || strings.TrimSpace(string(runes[b.Start:b.End])) == "" {
			return malformed(fmt.Sprintf("page %d block %d range or id is invalid", number, i))
		}
		ids[b.ID] = true
		previousEnd = b.End
		if !c.locator(b.Locator, number) {
			return malformed(fmt.Sprintf("page %d block %d locator is invalid", number, i))
		}
	}
	if c.pageSheet != "" {
		c.usedSheets[c.pageSheet] = true
	}
	return nil
}

func (c *pageCheck) locator(l Locator, page int) bool {
	switch c.format {
	case "pptx":
		return l.Kind == kindSlide && l.Slide != nil && *l.Slide == page &&
			l.BlockIndex == nil && l.CellRange == "" && l.Sheet == ""
	case "docx":
		if l.Kind != kindBlock || l.BlockIndex == nil || *l.BlockIndex <= c.lastIndex ||
			l.Slide != nil || l.CellRange != "" || l.Sheet != "" {
			return false
		}
		c.lastIndex = *l.BlockIndex
		return true
	default:
		match := rowRange.FindStringSubmatch(l.CellRange)
		if l.Kind != kindRows || l.Slide != nil || l.BlockIndex != nil || strings.TrimSpace(l.Sheet) == "" ||
			match == nil || match[1] != match[2] {
			return false
		}
		if c.pageSheet == "" {
			if c.usedSheets[l.Sheet] {
				return false
			}
			c.pageSheet = l.Sheet
		}
		row, err := strconv.Atoi(match[1])
		if err != nil || l.Sheet != c.pageSheet || row <= c.lastRowSeen {
			return false
		}
		c.lastRowSeen = row
		return true
	}
}

func digest(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func validSHA256(value string) bool {
	if len(value) != 2*sha256.Size || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func malformed(detail string) *Error { return &Error{Code: ErrorMalformed, Detail: detail} }
