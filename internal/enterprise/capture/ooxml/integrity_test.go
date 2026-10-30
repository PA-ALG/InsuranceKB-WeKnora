package ooxml_test

// Package integrity (Spec §2.3): the upstream readers stop silently at a bad XML part and skip a
// declared part they cannot find, so a valid prefix with a broken tail or a missing part must fail
// instead of being sealed as a shorter structure. Every input is synthetic.

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io"
	"testing"

	"github.com/stretchr/testify/require"
	"github.com/xuri/excelize/v2"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
)

// partsOf unpacks a package so a test can drop or rewrite one part.
func partsOf(t *testing.T, data []byte) []part {
	t.Helper()
	reader, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	require.NoError(t, err)
	out := make([]part, 0, len(reader.File))
	for _, f := range reader.File {
		rc, err := f.Open()
		require.NoError(t, err)
		body, err := io.ReadAll(rc)
		require.NoError(t, err)
		require.NoError(t, rc.Close())
		out = append(out, part{f.Name, body})
	}
	return out
}

// edit returns the package with the named part rewritten, or dropped when change returns nil.
func edit(t *testing.T, data []byte, name string, change func([]byte) []byte) []byte {
	t.Helper()
	var out []part
	found := false
	for _, p := range partsOf(t, data) {
		if p.name == name {
			found = true
			if p.body = change(p.body); p.body == nil {
				continue
			}
		}
		out = append(out, p)
	}
	require.True(t, found, "fixture has %s", name)
	return pkg(t, out...)
}

func drop([]byte) []byte { return nil }

func replace(old, replacement string) func([]byte) []byte {
	return func(body []byte) []byte {
		if !bytes.Contains(body, []byte(old)) {
			panic("fixture does not contain " + old)
		}
		return bytes.Replace(body, []byte(old), []byte(replacement), 1)
	}
}

func document(paragraphs string) []byte {
	return []byte(`<?xml version="1.0" encoding="UTF-8"?>` +
		`<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>` +
		paragraphs + `</w:body></w:document>`)
}

func paragraph(text string) string { return `<w:p><w:r><w:t>` + text + `</w:t></w:r></w:p>` }

func TestABrokenTailIsMalformedNotAShorterStructure(t *testing.T) {
	full := document(paragraph("第一段") + paragraph("第二段"))
	cut := bytes.Index(full, []byte(paragraph("第二段")))
	slide := slideXML("第一段", "第二段")
	slideCut := bytes.LastIndex(slide, []byte("<a:t>")) + len("<a:t>第二")
	cases := map[string]struct {
		fileType string
		data     []byte
	}{
		"pptx second paragraph has invalid UTF-8":      {"pptx", withSlide(t, slideXML("第一段", "第二段\xff"))},
		"pptx second paragraph has NUL":                {"pptx", withSlide(t, slideXML("第一段", "第二\x00段"))},
		"pptx slide truncated in the second paragraph": {"pptx", withSlide(t, slide[:slideCut])},
		"docx truncated after the first paragraph": {"docx", pkg(t,
			part{"word/document.xml", full[:cut+len(`<w:p><w:r><w:t>第二`)]})},
		"docx second paragraph has invalid UTF-8": {"docx", pkg(t,
			part{"word/document.xml", document(paragraph("第一段") + paragraph("第二段\xfe"))})},
		"docx second paragraph has a NUL reference": {"docx", pkg(t,
			part{"word/document.xml", document(paragraph("第一段") + paragraph("第二&#0;段"))})},
		"docx part after the root element": {"docx", pkg(t,
			part{"word/document.xml", append(document(paragraph("第一段")), []byte("<w:p/>")...)})},
		"xlsx sheet truncated": {"xlsx", edit(t, workbook(t), "xl/worksheets/sheet1.xml",
			func(b []byte) []byte { return b[:len(b)-20] })},
		"an empty slide's part is truncated": {"pptx", edit(t, deck(t), "ppt/slides/slide1.xml",
			func([]byte) []byte { return []byte(`<p:sld>`) })},
		"a part no reader consumes is not well-formed": {"pptx", pkg(t, append(partsOf(t, deck(t)),
			part{"docProps/app.xml", []byte(`<Properties><Pages>3`)})...)},
		"a cell style index is not an integer": {"xlsx", edit(t, workbook(t), "xl/worksheets/sheet1.xml",
			replace(`<c r="A3"`, `<c s="x" r="A3"`))},
		"a cell formula attribute is mistyped": {"xlsx", edit(t, workbook(t), "xl/worksheets/sheet1.xml",
			replace(`<c r="B3" t="s"><v>`, `<c r="B3" t="s"><f si="x">1</f><v>`))},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			_, err := ooxml.Extract(c.fileType, c.data)
			failure := failureOf(t, err)
			require.Equal(t, "OFFICE_MALFORMED", failure.Code)
			require.NotContains(t, failure.Detail, "第一段", "details never carry document text")
		})
	}
}

// threeSheets: three declared sheets, each with text, so a dropped sheet would lose a row.
func threeSheets(t *testing.T) []byte {
	t.Helper()
	f := excelize.NewFile()
	defer func() { _ = f.Close() }()
	require.NoError(t, f.SetSheetName("Sheet1", "Rates"))
	for _, name := range []string{"Notes", "Terms"} {
		_, err := f.NewSheet(name)
		require.NoError(t, err)
	}
	for i, name := range []string{"Rates", "Notes", "Terms"} {
		require.NoError(t, f.SetCellValue(name, "A1", fmt.Sprintf("row of sheet %d", i+1)))
	}
	buf, err := f.WriteToBuffer()
	require.NoError(t, err)
	return buf.Bytes()
}

func TestADeclaredPartThatCannotBeReadIsMalformedNotSkipped(t *testing.T) {
	presentation := "ppt/presentation.xml"
	presentationRels := "ppt/_rels/presentation.xml.rels"
	slideRels := "ppt/slides/_rels/slide3.xml.rels"
	twoNotes := func(b []byte) []byte {
		return replace(`</Relationships>`, `<Relationship Id="rId2" Type="`+notesRel+
			`" Target="../notesSlides/notesSlide1.xml"/></Relationships>`)(b)
	}
	cases := map[string]struct {
		fileType string
		data     []byte
	}{
		"a declared slide with text is missing": {"pptx", edit(t, deck(t), "ppt/slides/slide2.xml", drop)},
		"a slide id has no relationship": {"pptx", edit(t, deck(t), presentationRels,
			replace(`Id="rId3"`, `Id="rId9"`))},
		"the notes part of a slide is missing": {"pptx", edit(t, deck(t), "ppt/notesSlides/notesSlide1.xml", drop)},
		"a slide has two notes relationships":  {"pptx", edit(t, deck(t), slideRels, twoNotes)},
		"presentation relationships missing":   {"pptx", edit(t, deck(t), presentationRels, drop)},
		"presentation part missing":            {"pptx", edit(t, deck(t), presentation, drop)},
		"word/document.xml missing":            {"docx", pkg(t, part{"word/styles.xml", []byte(`<w:styles/>`)})},
		"the third declared sheet is missing": {"xlsx", edit(t, threeSheets(t), "xl/worksheets/sheet3.xml",
			drop)},
		"two sheets differ only in case": {"xlsx", edit(t, threeSheets(t), "xl/workbook.xml",
			replace(`name="Terms"`, `name="rates"`))},
		"a cell reference cannot be read": {"xlsx", edit(t, threeSheets(t), "xl/worksheets/sheet2.xml",
			replace(`<c r="A1"`, `<c r="1A"`))},
		"a row number beyond the sheet limit": {"xlsx", edit(t, threeSheets(t), "xl/worksheets/sheet3.xml",
			replace(`<row r="1"`, `<row r="1048577"`))},
		"two entries share a name": {"pptx", pkg(t, append(partsOf(t, deck(t)),
			part{"ppt/slides/slide2.xml", slideXML("另一份")})...)},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			_, err := ooxml.Extract(c.fileType, c.data)
			requireCode(t, err, "OFFICE_MALFORMED")
		})
	}

	// Positive controls: the unedited fixtures read completely.
	for fileType, data := range map[string][]byte{"pptx": deck(t), "xlsx": threeSheets(t)} {
		s := mustExtract(t, fileType, data)
		require.Len(t, s.Pages, 3, fileType)
	}
}

func TestAStoredStructureNamesItsFormatByTheFrozenLiteral(t *testing.T) {
	book := mustExtract(t, "xlsx", workbook(t))
	require.Len(t, book.Pages, 3)
	encoded, err := ooxml.Encode(book)
	require.NoError(t, err)
	_, err = ooxml.Decode(encoded)
	require.NoError(t, err, "positive control: the literal xlsx decodes")

	// The input aliases Supports accepts are not stored formats; ".docx" here is also three pages of
	// XLSX_CELL_RANGE blocks, which neither a docx nor any non-xlsx format may carry.
	for _, format := range []string{".docx", "PPTX", "XLSX", ".xlsx", " xlsx", "xlsx ", "docx", "pptx", "odp", ""} {
		t.Run(fmt.Sprintf("%q", format), func(t *testing.T) {
			changed := *book
			changed.Format = format
			data, err := ooxml.Encode(&changed)
			require.NoError(t, err)
			_, err = ooxml.Decode(data)
			requireCode(t, err, "OFFICE_MALFORMED")
		})
	}
}
