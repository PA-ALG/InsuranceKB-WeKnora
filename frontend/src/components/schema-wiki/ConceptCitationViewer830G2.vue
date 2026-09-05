<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import type { ConceptSession830G2 } from '@/api/schema-wiki/conceptFreeWiki830G2'
import type { SchemaWikiCitationPreviewTransport } from '@/api/schema-wiki'
import type { PdfPort, RenderedPdfPage } from './pdfJsPort'
import { conceptSHA256830G2, parseConceptCitationAuthority830G2 } from './conceptCitationAuthority830G2'

const props = defineProps<{ session: ConceptSession830G2; citationId: string;
  previewTransport: SchemaWikiCitationPreviewTransport; pdfPort: PdfPort }>()
const error = ref('')
const rendered = shallowRef<RenderedPdfPage | null>(null)
const host = ref<HTMLElement | null>(null)
const highlight = ref<Record<string, string>>({})
let alive = true
onBeforeUnmount(() => { alive = false })
onMounted(async () => {
  try {
    const { session, citationId } = props
    const authority = await parseConceptCitationAuthority830G2(await props.previewTransport.getAuthority({
      release_id: session.read.release_id, activation_epoch: session.read.activation_epoch,
      field_id: session.read.member.member_id, citation_id: citationId,
    }), session, citationId)
    if (!alive) return
    const bytes = await props.previewTransport.getBytesByToken(authority.opaque_token)
    if (!(bytes instanceof Uint8Array) || bytes.length === 0
      || await conceptSHA256830G2(bytes) !== authority.revision_source.file_sha256) {
      throw new Error('PREVIEW_BYTES_HASH_MISMATCH')
    }
    if (!alive) return
    const opened = await props.pdfPort.open(bytes.slice())
    if (opened.pageCount !== authority.revision_source.page_count) throw new Error('PAGE_UNAVAILABLE')
    const page = await opened.renderPage(authority.page_number)
    if (page.pageNumber !== authority.page_number || ![page.width, page.height].every(n => Number.isFinite(n) && n > 0)) {
      throw new Error('PAGE_UNAVAILABLE')
    }
    if (!alive) return
    const b = authority.bbox
    highlight.value = { left: `${b.x0 * page.width / 1_000_000}px`, top: `${b.y0 * page.height / 1_000_000}px`,
      width: `${(b.x1 - b.x0) * page.width / 1_000_000}px`, height: `${(b.y1 - b.y0) * page.height / 1_000_000}px` }
    rendered.value = page
    await nextTick()
    if (alive) host.value?.replaceChildren(page.canvas)
  } catch (e) {
    if (!alive) return
    rendered.value = null
    error.value = e instanceof Error && ['G2_CITATION_AUTHORITY_INVALID', 'PREVIEW_BYTES_HASH_MISMATCH', 'PAGE_UNAVAILABLE'].includes(e.message)
      ? e.message : 'PDF_PREVIEW_UNAVAILABLE'
  }
})
</script>

<template>
  <p v-if="error" role="status" data-testid="citation-error">原文暂不可用（{{ error }}）</p>
  <div v-else-if="rendered" class="concept-source-page" data-testid="citation-page"
    :data-page-number="rendered.pageNumber" :style="{ width: `${rendered.width}px`, height: `${rendered.height}px` }">
    <div ref="host" />
    <span class="concept-source-highlight" data-testid="citation-highlight" :style="highlight" />
  </div>
  <p v-else role="status">正在核验并打开原文…</p>
</template>

<style scoped>
.concept-source-page { position: relative; }
.concept-source-highlight { position: absolute; border: 2px solid #e89b19;
  background: rgb(255 207 64 / 24%); pointer-events: none; }
</style>
