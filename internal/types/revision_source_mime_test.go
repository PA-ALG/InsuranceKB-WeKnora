package types

// S11g: which stored resources record a source revision at commit, and under which MIME.
// Spec: docs/design/slices/S11g-Office来源修订记录.md §2.1.

import "testing"

func TestRevisionSourceMIMEKeepsPDFAndAddsOOXMLByAFixedTable(t *testing.T) {
	docx := "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
	pptx := "application/vnd.openxmlformats-officedocument.presentationml.presentation"
	xlsx := "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
	for name, test := range map[string]struct {
		mime, file, want string
		ok               bool
	}{
		"pdf":                        {"application/pdf", "terms.pdf", "application/pdf", true},
		"pdf mime wins over name":    {" Application/PDF ", "whatever.bin", "application/pdf", true},
		"pdf without mime stays out": {"", "terms.pdf", "", false},
		"docx canonical":             {docx, "manual.docx", docx, true},
		"pptx empty mime":            {"", "deck.PPTX", pptx, true},
		"xlsx canonical mixed case":  {" " + xlsx + " ", "book.xlsx", xlsx, true},
		"docx with foreign mime":     {"image/png", "manual.docx", "", false},
		"docx with zip mime":         {"application/zip", "manual.docx", "", false},
		"pptx mime but docx name":    {pptx, "manual.docx", "", false},
		"markdown":                   {"text/markdown", "notes.md", "", false},
		"legacy doc":                 {"application/msword", "old.doc", "", false},
		"no name":                    {"", "", "", false},
	} {
		t.Run(name, func(t *testing.T) {
			got, ok := RevisionSourceMIME(test.mime, test.file)
			if ok != test.ok || got != test.want {
				t.Fatalf("RevisionSourceMIME(%q, %q) = %q, %v; want %q, %v",
					test.mime, test.file, got, ok, test.want, test.ok)
			}
		})
	}
}
