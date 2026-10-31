<script setup lang="ts">
// Opens one synthetic Office citation in the real CitationPanel. The page's API requests are
// answered by check.py from `CASES` and `FILES`; this page only exposes them and verifies the result.
import CitationPanel from '../../src/enterprise/CitationPanel.vue'
import { CASES, FILES, type OfficeCase } from './fixtures'

const name = new URLSearchParams(location.search).get('case') ?? ''
const current = CASES.find(c => c.name === name)

async function fixtures(): Promise<Record<string, string>> {
  const out: Record<string, string> = {}
  for (const [key, build] of Object.entries(FILES)) {
    const bytes = new Uint8Array(await (await build()).arrayBuffer())
    let binary = ''
    for (const byte of bytes) binary += String.fromCharCode(byte)
    out[key] = btoa(binary)
  }
  return out
}

function highlighted(): Range[] {
  const highlight = (CSS as unknown as { highlights?: Map<string, Iterable<Range>> }).highlights?.get('source-locate')
  return highlight ? [...highlight] : []
}

const note = () => document.querySelector('[role="note"]')?.textContent?.trim() ?? ''

function check(c: OfficeCase): string | null {
  const alert = document.querySelector('[role="alert"]')
  if (alert) return `alert: ${alert.textContent?.trim()}`
  const e = c.expect
  if (e.kind === 'text' || e.kind === 'inert') {
    if (e.kind === 'inert') {
      if ((window as unknown as Record<string, unknown>)[e.flag] !== undefined) return 'the embedded script ran'
      if (document.querySelector('iframe')) return 'an iframe was rendered'
    }
    const ranges = highlighted()
    if (ranges.length !== 1) return `wanted 1 highlighted range, got ${ranges.length}`
    if (ranges[0].toString() !== e.quote) return `highlighted "${ranges[0].toString()}"`
    const places = [...document.querySelectorAll(e.within)]
    const at = places.findIndex(place => place.contains(ranges[0].commonAncestorContainer))
    if (at !== e.index) return `highlight is in place ${at}, wanted ${e.index} of ${places.length}`
    return note() ? `unexpected note: ${note()}` : null
  }
  if (e.kind === 'rows') {
    const marked = [...document.querySelectorAll('.source-locate-block')]
    if (marked.length !== 1) return `wanted 1 marked row, got ${marked.length}`
    if (!marked[0].querySelector(`td[id$="sheet-${e.sheet}-A${e.row}"]`)) return `marked the wrong row: ${marked[0].textContent}`
    return note() === e.note ? null : `note: "${note()}"`
  }
  if (e.kind === 'not-located') {
    if (highlighted().length || document.querySelector('.source-locate-block')) return 'something was highlighted'
    if (!document.querySelector('.docx-container')?.textContent?.trim()) return 'the document is not shown'
    return note() === e.note ? null : `note: "${note()}"`
  }
  if (e.kind === 'blocked-link') {
    if (highlighted().length !== 1) return 'the quote is not highlighted'
    // The package rebuild drops the script target; the click guard is the second line.
    const link = [...document.querySelectorAll<HTMLAnchorElement>('.docx-container a')].find(a => a.textContent === '了解详情')
    if (!link) return 'the link text is not rendered'
    if (/^\s*javascript:/i.test(link.getAttribute('href') ?? '')) return 'the script target reached the page'
    const before = location.href
    link.click()
    if (location.href !== before) return 'the link navigated'
    return (window as unknown as Record<string, unknown>)[e.flag] === undefined ? null : 'the script link ran'
  }
  if (e.kind === 'rejected') {
    if (document.querySelector('.document-preview')) return 'the package was rendered'
    if (!document.querySelector('.ek-citation__quote')?.textContent?.trim()) return 'the quote is not shown'
    return note() === e.note ? null : `note: "${note()}"`
  }
  if (document.querySelector('.document-preview, .source-page-viewer')) return 'a viewer was rendered'
  if (!document.querySelector('.ek-citation__quote')?.textContent?.trim()) return 'the quote is not shown'
  return note() === e.note ? null : `note: "${note()}"`
}

/** Polls until the case holds or `timeout` passes; returns null on success, else the last failure. */
async function verify(timeout = 30_000): Promise<string | null> {
  if (!current) return `unknown case "${name}"`
  const until = Date.now() + timeout
  let failure: string | null = 'not checked'
  while (Date.now() < until) {
    failure = check(current)
    // The panel settles before the preview reports; give the note a moment to appear.
    if (failure === null) {
      await new Promise(resolve => setTimeout(resolve, 500))
      failure = check(current)
      if (failure === null) return null
    }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  return failure
}

Object.assign(window, { officeCitationHarness: { cases: CASES, fixtures, verify } })
</script>

<template>
  <main style="max-width: 960px; margin: 0 auto">
    <CitationPanel v-if="current" space-id="demo" release-id="rel-1" :member="current.name" :evidence="0" />
  </main>
</template>
