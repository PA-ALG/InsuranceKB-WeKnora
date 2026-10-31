# Office citation browser check (S11e)

Opens synthetic Office citations in the real `CitationPanel` with headless Chromium and checks
that upstream's original-file preview reveals and highlights them
(Spec `docs/design/slices/S11e-Office引用查看器.md` §5).

From `frontend/` (dependencies installed, Playwright for Python with Chromium available):

```sh
python3 tests/enterprise-office-citation/check.py            # prints PASS/FAIL per case
python3 tests/enterprise-office-citation/check.py --screenshots <dir>
```

The script starts the Vite dev server, reads the cases and fixtures from the check page, and
answers the panel's two requests itself: the citation (an S11d Office response, see
`internal/enterprise/citation.go` `blockCitation`) and the cited file. Nothing reaches a backend.

| Case | Expected |
|---|---|
| `pptx-slide-2` | the quote is highlighted word for word on slide 2, not on slide 1 where it also occurs |
| `docx-block-4` | the quote is highlighted in body block 4 (after an empty paragraph), not in the table |
| `xlsx-rates-row-3` | row 3 of sheet "Rates" is marked, not row 3 of "Notes"; the coarse note is shown |
| `docx-quote-missing` | the document is shown, nothing is highlighted, the not-located note is shown |
| `docx-script-link` | the quote is highlighted; clicking the file's `javascript:` link runs nothing |
| `no-locator` | no viewer; document, page, quote and the no-viewer note only |

`fixtures.ts` builds every file in the browser with JSZip and SheetJS. Never add business
documents, their text or screenshots of them here; private end-to-end checks run outside the
repository.
