package ooxml

import (
	"archive/zip"
	"bytes"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"path"
	"strconv"
	"strings"
	"unicode"

	"github.com/xuri/excelize/v2"
)

// Package integrity (Spec §2.3). The upstream readers stop at the first XML error, and skip a slide,
// notes page or sheet they cannot find, returning what they have read so far with no error. Their
// result is only trusted after this file proves the package complete: limits counted on real bytes,
// every XML part well-formed UTF-8 to its end, and every part the reader is declared to consume
// present and unambiguous.

// Package limits for an untrusted upload, counted on decompressed bytes.
const (
	maxEntries      = 10_000
	maxUncompressed = 512 << 20
	maxXMLPart      = 64 << 20
	// upstreamUnitCap is sourceloc's own unit limit: a result this large may have been truncated.
	upstreamUnitCap = 200_000
)

// oleHeader starts an OLE compound file: encrypted OOXML or legacy binary Office.
var oleHeader = []byte{0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1}

// parts are the entries of a checked package by name.
type parts map[string]*zip.File

// checkPackage decompresses every entry once, counting real bytes (reading an entry to its end also
// makes archive/zip verify its declared size and checksum). Entry names must be unique, since the
// upstream reader takes the first entry of a name.
func checkPackage(archive *zip.Reader) (parts, error) {
	if len(archive.File) > maxEntries {
		return nil, &Error{Code: ErrorTooLarge, Detail: fmt.Sprintf("%d entries", len(archive.File))}
	}
	files := make(parts, len(archive.File))
	var total int64
	for i, f := range archive.File {
		if files[f.Name] != nil {
			return nil, malformed(fmt.Sprintf("entry %d repeats an entry name", i))
		}
		files[f.Name] = f
		n, err := checkEntry(i, f, int64(maxUncompressed)-total)
		if err != nil {
			return nil, err
		}
		total += n
	}
	return files, nil
}

// checkEntry reads one entry within the remaining budget. An XML part must also stay within the
// part limit, declare no DTD or entity, and be well-formed to its end.
func checkEntry(i int, f *zip.File, remaining int64) (int64, error) {
	rc, err := f.Open()
	if err != nil {
		return 0, malformed(fmt.Sprintf("entry %d cannot be opened", i))
	}
	defer func() { _ = rc.Close() }()
	if !isXMLPart(f.Name) {
		n, err := io.Copy(io.Discard, io.LimitReader(rc, remaining+1))
		if err != nil {
			return 0, malformed(fmt.Sprintf("entry %d cannot be decompressed", i))
		}
		if n > remaining {
			return 0, &Error{Code: ErrorTooLarge, Detail: "decompressed package exceeds the size limit"}
		}
		return n, nil
	}
	limit := min(remaining, maxXMLPart)
	body, err := io.ReadAll(io.LimitReader(rc, limit+1))
	if err != nil {
		return 0, malformed(fmt.Sprintf("entry %d cannot be decompressed", i))
	}
	if int64(len(body)) > limit {
		return 0, &Error{Code: ErrorTooLarge, Detail: fmt.Sprintf("entry %d exceeds the size limit", i)}
	}
	if bytes.Contains(body, []byte("<!DOCTYPE")) || bytes.Contains(body, []byte("<!ENTITY")) {
		return 0, malformed(fmt.Sprintf("entry %d declares a DTD or entity", i))
	}
	if !wellFormed(body) {
		return 0, malformed(fmt.Sprintf("entry %d is not well-formed UTF-8 XML", i))
	}
	return int64(len(body)), nil
}

func isXMLPart(name string) bool {
	lower := strings.ToLower(name)
	return strings.HasSuffix(lower, ".xml") || strings.HasSuffix(lower, ".rels")
}

// wellFormed walks an XML part to its end with the decoder the upstream readers use, so it fails
// wherever they would stop early: invalid UTF-8, a character outside XML's range (NUL included), an
// undefined entity, an unmatched or unclosed element. It also requires exactly one root element, and
// in a worksheet that every cell decodes (cellDecodes).
func wellFormed(body []byte) bool {
	decoder := xml.NewDecoder(bytes.NewReader(body))
	depth, roots, worksheet := 0, 0, false
	for {
		token, err := decoder.Token()
		if errors.Is(err, io.EOF) {
			return roots == 1 && depth == 0
		}
		if err != nil {
			return false
		}
		switch t := token.(type) {
		case xml.StartElement:
			if depth == 0 {
				roots++
				worksheet = t.Name.Local == "worksheet"
			}
			if worksheet && t.Name.Local == "c" {
				if !cellDecodes(decoder, t) {
					return false
				}
				continue // the cell was read through its end element
			}
			depth++
		case xml.EndElement:
			depth--
		case xml.CharData:
			if depth == 0 && len(bytes.TrimSpace(t)) > 0 {
				return false
			}
		}
		if roots > 1 {
			return false
		}
	}
}

// cellDecodes reads one worksheet cell the way the workbook reader does while streaming (excelize
// v2.11.0 rows.go cellXMLHandler), which discards a decode error and with it the cell's text: the style
// index parsed without trimming, then every v, f and is element decoded with the reader's typed fields.
// How a decoded value is then rendered is the reader's semantics and is not checked here.
func cellDecodes(decoder *xml.Decoder, cell xml.StartElement) bool {
	for _, attr := range cell.Attr {
		if attr.Name.Local == "s" {
			if _, err := strconv.ParseInt(attr.Value, 10, 64); err != nil {
				return false
			}
		}
	}
	for {
		token, err := decoder.Token()
		if err != nil {
			return false
		}
		switch t := token.(type) {
		case xml.StartElement:
			var into any
			switch t.Name.Local {
			case "v":
				into = new(string)
			case "f":
				into = new(cellFormula)
			case "is":
				into = new(cellInline)
			default:
				continue
			}
			if decoder.DecodeElement(into, &t) != nil {
				return false
			}
		case xml.EndElement:
			if t == cell.End() {
				return true
			}
		}
	}
}

// cellFormula and cellInline keep the typed fields of excelize v2.11.0 xlsxF and xlsxSI, the ones that
// can fail to decode; their string fields cannot and are left out. Re-check on an excelize upgrade.
type cellFormula struct {
	Aca  bool `xml:"aca,attr"`
	Bx   bool `xml:"bx,attr"`
	Ca   bool `xml:"ca,attr"`
	Del1 bool `xml:"del1,attr"`
	Del2 bool `xml:"del2,attr"`
	Dt2D bool `xml:"dt2D,attr"`
	Dtr  bool `xml:"dtr,attr"`
	Si   *int `xml:"si,attr"`
}

type cellInline struct {
	PhoneticPr *struct {
		FontID *int `xml:"fontId,attr"`
	} `xml:"phoneticPr"`
	R []struct {
		RPr *struct {
			B        *boolValue  `xml:"b"`
			Charset  *intValue   `xml:"charset"`
			Condense *boolValue  `xml:"condense"`
			Extend   *boolValue  `xml:"extend"`
			Family   *intValue   `xml:"family"`
			I        *boolValue  `xml:"i"`
			Outline  *boolValue  `xml:"outline"`
			Shadow   *boolValue  `xml:"shadow"`
			Strike   *boolValue  `xml:"strike"`
			Sz       *floatValue `xml:"sz"`
			Color    *struct {
				Auto    bool    `xml:"auto,attr"`
				Indexed int     `xml:"indexed,attr"`
				Theme   *int    `xml:"theme,attr"`
				Tint    float64 `xml:"tint,attr"`
			} `xml:"color"`
		} `xml:"rPr"`
	} `xml:"r"`
	RPh []struct {
		Eb uint32 `xml:"eb,attr"`
		Sb uint32 `xml:"sb,attr"`
	} `xml:"rPh"`
}

type (
	boolValue struct {
		Val *bool `xml:"val,attr"`
	}
	intValue struct {
		Val *int `xml:"val,attr"`
	}
	floatValue struct {
		Val *float64 `xml:"val,attr"`
	}
)

// relationship is one entry of an OPC relationships part.
type relationship struct{ Type, Target string }

// relationships reads a relationships part as the upstream reader does: by ID, the last entry winning.
func (files parts) relationships(name string) (map[string]relationship, error) {
	var rels struct {
		Items []struct {
			ID     string `xml:"Id,attr"`
			Type   string `xml:"Type,attr"`
			Target string `xml:"Target,attr"`
		} `xml:"Relationship"`
	}
	if err := files.unmarshal(name, &rels); err != nil {
		return nil, err
	}
	out := make(map[string]relationship, len(rels.Items))
	for _, r := range rels.Items {
		out[r.ID] = relationship{Type: r.Type, Target: r.Target}
	}
	return out, nil
}

// unmarshal decodes a part known by a fixed name (the name is safe to report).
func (files parts) unmarshal(name string, into any) error {
	f := files[name]
	if f == nil {
		return malformed(name + " is missing")
	}
	rc, err := f.Open()
	if err != nil {
		return malformed(name + " cannot be opened")
	}
	defer func() { _ = rc.Close() }()
	if err := xml.NewDecoder(io.LimitReader(rc, maxXMLPart)).Decode(into); err != nil {
		return malformed(name + " is invalid")
	}
	return nil
}

// declaredSlides returns the number of slides ppt/presentation.xml declares after proving that each
// resolves to a slide part, and that a slide's notes relationship, if any, resolves to a notes part.
func declaredSlides(files parts) (int, error) {
	var presentation struct {
		SlideIDs []struct {
			RID string `xml:"http://schemas.openxmlformats.org/officeDocument/2006/relationships id,attr"`
		} `xml:"sldIdLst>sldId"`
	}
	if err := files.unmarshal("ppt/presentation.xml", &presentation); err != nil {
		return 0, err
	}
	targets, err := files.relationships("ppt/_rels/presentation.xml.rels")
	if err != nil {
		return 0, err
	}
	for i, slide := range presentation.SlideIDs {
		rel, ok := targets[slide.RID]
		if !ok {
			return 0, malformed(fmt.Sprintf("slide %d has no relationship", i+1))
		}
		slidePath := resolvePart("ppt", rel.Target)
		if files[slidePath] == nil {
			return 0, malformed(fmt.Sprintf("slide %d part is missing", i+1))
		}
		if err := files.checkNotes(slidePath, i+1); err != nil {
			return 0, err
		}
	}
	return len(presentation.SlideIDs), nil
}

// checkNotes: a slide without a relationships part has no notes; otherwise at most one notes
// relationship (the upstream reader visits them in map order) whose part is present.
func (files parts) checkNotes(slidePath string, slide int) error {
	relsPath := path.Join(path.Dir(slidePath), "_rels", path.Base(slidePath)+".rels")
	if files[relsPath] == nil {
		return nil
	}
	rels, err := files.relationships(relsPath)
	if err != nil {
		return malformed(fmt.Sprintf("slide %d relationships are invalid", slide))
	}
	notes := 0
	for _, rel := range rels {
		if !strings.HasSuffix(rel.Type, "/notesSlide") {
			continue
		}
		notes++
		if notes > 1 || files[resolvePart(path.Dir(slidePath), rel.Target)] == nil {
			return malformed(fmt.Sprintf("slide %d notes part is missing or repeated", slide))
		}
	}
	return nil
}

// resolvePart resolves a relationship target exactly as the upstream reader does: against the source
// part's directory, or from the package root when absolute.
func resolvePart(dir, target string) string {
	if strings.HasPrefix(target, "/") {
		return strings.TrimPrefix(path.Clean(target), "/")
	}
	return path.Clean(path.Join(dir, target))
}

// checkSheets proves every declared sheet is read to its end: names are unique under the case folding
// the workbook reader uses to find a sheet, and each sheet streams with the reader's own calls without
// the error the upstream reader ignores.
func checkSheets(book *excelize.File, sheets []string) error {
	if len(sheets) == 0 {
		return malformed("workbook declares no sheet")
	}
	seen := make(map[string]bool, len(sheets))
	for i, name := range sheets {
		key := foldKey(name)
		if seen[key] {
			return malformed(fmt.Sprintf("sheet %d repeats a sheet name", i+1))
		}
		seen[key] = true
		if err := readsCompletely(book, name); err != nil {
			return malformed(fmt.Sprintf("sheet %d is missing or unreadable", i+1))
		}
	}
	return nil
}

func readsCompletely(book *excelize.File, sheet string) error {
	rows, err := book.Rows(sheet)
	if err != nil {
		return err
	}
	defer func() { _ = rows.Close() }()
	for rows.Next() {
		if _, err := rows.Columns(); err != nil {
			return err
		}
	}
	return rows.Error()
}

// foldKey maps every rune to the smallest rune of its simple case-folding orbit, so two names have
// the same key exactly when strings.EqualFold holds.
func foldKey(name string) string {
	return strings.Map(func(r rune) rune {
		smallest := r
		for f := unicode.SimpleFold(r); f != r; f = unicode.SimpleFold(f) {
			smallest = min(smallest, f)
		}
		return smallest
	}, name)
}
