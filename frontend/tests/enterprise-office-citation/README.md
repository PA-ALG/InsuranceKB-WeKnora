# Office citation browser check (S11e, S11h)

Opens synthetic Office citations in the real `CitationPanel` with headless Chromium and checks
that upstream's original-file preview reveals and highlights them
(Spec `docs/design/slices/S11e-Office引用查看器.md` §5), and that a citation the preview cannot show
still shows as text (Spec `docs/design/slices/S11h-Office渲染失败时的文本视图.md` §4).

From `frontend/` (dependencies installed, Playwright for Python with Chromium available):

```sh
python3 tests/enterprise-office-citation/check.py            # prints PASS/FAIL per case
python3 tests/enterprise-office-citation/check.py --screenshots <dir>
```

The script starts the Vite dev server, reads the cases and fixtures from the check page, and
answers the panel's two requests itself: the citation (an S11d Office response, see
`internal/enterprise/citation.go` `blockCitation`) and the cited file. Nothing reaches a backend;
any request leaving the page is refused and fails the case.

| Case | Expected |
|---|---|
| `pptx-slide-2` | the quote is highlighted word for word on slide 2, not on slide 1 where it also occurs |
| `docx-block-4` | the quote is highlighted in body block 4 (after an empty paragraph), not in the table |
| `xlsx-rates-row-3` | row 3 of sheet "Rates" is marked, not row 3 of "Notes"; the coarse note is shown |
| `docx-quote-missing` | the document is shown, nothing is highlighted, the not-located note is shown |
| `docx-script-link` | the quote is highlighted; the file's `javascript:` link reaches the page without its target, and clicking it does nothing |
| `docx-altchunk` | an altChunk (HTML with a script) and an external image before block 4: no click, the script does not run, no iframe, the quote is still highlighted in block 4 |
| `docx-not-a-package` | the file is not a package: nothing is rendered, the refusal note is shown |
| `pptx-grouped-table` | slide 2 holds a table inside a group, which stops the renderer on the whole deck unless the rebuild drops it: the deck is shown and the quote is highlighted on slide 2 |
| `pptx-quote-in-grouped-table` | the quote is in that grouped table: the preview can only mark slide 2 as a whole (coarse note), and the text view below marks the quote |
| `no-locator` | no viewer; document, page, quote and the no-viewer note only |

`fixtures.ts` builds every file in the browser with JSZip and SheetJS. Never add business
documents, their text or screenshots of them here; private end-to-end checks run outside the
repository.
