<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import type { ConceptSession830G2 } from '@/api/schema-wiki/conceptFreeWiki830G2'
import type { SchemaWikiCitationPreviewTransport } from '@/api/schema-wiki'
import type { PdfPort, RenderedPdfPage } from './pdfJsPort'
import { parseConceptCitationAuthority830G2 } from './conceptCitationAuthority830G2'

import { createVerifiedPdfReuse, type VerifiedPdfReuse, type VerifiedPdfLease } from './verifiedPdfReuse'

const props = defineProps<{ session: ConceptSession830G2; citationId: string;
  previewTransport: SchemaWikiCitationPreviewTransport; pdfPort: PdfPort; pdfReuse?: VerifiedPdfReuse }>()
const error = ref('')
const rendered = shallowRef<RenderedPdfPage | null>(null)
const host = ref<HTMLElement | null>(null)
const highlight = ref<Record<string, string>>({})
const reuse = props.pdfReuse ?? createVerifiedPdfReuse(props.pdfPort, 0)
let lease: VerifiedPdfLease | null = null
let alive = true
onBeforeUnmount(() => {
  alive = false
  lease?.release(); lease = null
  if (!props.pdfReuse) reuse.clear()
})
onMounted(async () => {
  try {
    const { session, citationId } = props
    const authority = await parseConceptCitationAuthority830G2(await props.previewTransport.getAuthority({
      release_id: session.read.release_id, activation_epoch: session.read.activation_epoch,
      field_id: session.read.member.member_id, citation_id: citationId,
    }), session, citationId)
    if (!alive) return
    const sourceKey = JSON.stringify([session.scope, session.read.release_id,
      session.read.activation_epoch, session.read.candidate_hash, authority.source, authority.revision_source])
    lease = await reuse.acquire(sourceKey, authority.revision_source.file_sha256,
      authority.revision_source.page_count, () => props.previewTransport.getBytesByToken(authority.opaque_token))
    if (!alive) { lease.release(); lease = null; return }
    const opened = lease.document
    const physicalPage = authority.source_locator?.actual_page_number ?? authority.page_number
    const page = await opened.renderPage(physicalPage)
    if (page.pageNumber !== physicalPage || ![page.width, page.height].every(n => Number.isFinite(n) && n > 0)) {
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
    lease?.release(); lease = null
    if (!alive) return
    reuse.clear()
    rendered.value = null
    error.value = e instanceof Error && ['G2_CITATION_AUTHORITY_INVALID', 'PREVIEW_BYTES_HASH_MISMATCH', 'PAGE_UNAVAILABLE'].includes(e.message)
      ? e.message : 'PDF_PREVIEW_UNAVAILABLE'
  }
})
</script>

<template>
  <p v-if="rendered" data-testid="citation-page-label">第 {{ rendered.pageNumber }} 页</p>
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
