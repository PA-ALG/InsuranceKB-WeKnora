<script setup lang="ts">
import { nextTick, onMounted, ref, shallowRef } from 'vue'

import {
  citationPreviewHighlightStyle,
  parseSchemaWikiCitationContentAuthorityV1,
  type SchemaWikiCitationContentAuthorityV1,
  type SchemaWikiCitationPreviewRequestV1,
} from './schemaCitationTarget.ts'
import type { PdfPort, RenderedPdfPage } from './pdfJsPort.ts'

interface ImmutablePreviewTransport {
  getAuthority(request: SchemaWikiCitationPreviewRequestV1): Promise<unknown>
  getBytesByToken(opaqueToken: string): Promise<Uint8Array>
}

const props = defineProps<{
  request: SchemaWikiCitationPreviewRequestV1
  previewTransport: ImmutablePreviewTransport
  pdfPort: PdfPort
}>()

const emit = defineEmits<{
  back: [value: { release_id: string; activation_epoch: number }]
}>()

const errorCode = ref<string | null>(null)
const renderedPage = shallowRef<RenderedPdfPage | null>(null)
const highlightStyle = ref<Record<string, string> | null>(null)
const canvasHost = ref<HTMLElement | null>(null)

const SAFE_ERRORS = new Set([
  'BBOX_UNAVAILABLE',
  'CITATION_MEMBER_BINDING_MISMATCH',
  'CITATION_PREVIEW_AUTHORITY_INVALID',
  'CITATION_PREVIEW_REQUEST_INVALID',
  'CITATION_REPLAY_IDENTITY_MISMATCH',
  'CITATION_REVISION_NOT_PINNED',
  'CITATION_TARGET_INCOMPLETE',
  'PAGE_UNAVAILABLE',
  'PDF_PREVIEW_UNAVAILABLE',
  'PREVIEW_BYTES_HASH_MISMATCH',
])

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const copy = Uint8Array.from(bytes)
  const digest = await globalThis.crypto.subtle.digest('SHA-256', copy.buffer)
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

function safeError(error: unknown): string {
  return error instanceof Error && SAFE_ERRORS.has(error.message)
    ? error.message
    : 'PDF_PREVIEW_UNAVAILABLE'
}

onMounted(async () => {
  try {
    const authority: SchemaWikiCitationContentAuthorityV1 = (
      parseSchemaWikiCitationContentAuthorityV1(
        await props.previewTransport.getAuthority(props.request),
        props.request,
      )
    )
    const bytes = await props.previewTransport.getBytesByToken(authority.opaque_token)
    if (!(bytes instanceof Uint8Array) || bytes.byteLength === 0) {
      throw new Error('PDF_PREVIEW_UNAVAILABLE')
    }
    if (await sha256Hex(bytes) !== authority.revision_source.file_sha256) {
      throw new Error('PREVIEW_BYTES_HASH_MISMATCH')
    }
    const opened = await props.pdfPort.open(bytes.slice())
    if (
      opened.pageCount !== authority.revision_source.page_count
      || authority.page_number > opened.pageCount
    ) {
      throw new Error('PAGE_UNAVAILABLE')
    }
    const page = await opened.renderPage(authority.page_number)
    if (page.pageNumber !== authority.page_number) {
      throw new Error('PAGE_UNAVAILABLE')
    }
    const bbox = citationPreviewHighlightStyle(
      authority,
      { width: page.width, height: page.height },
    )
    renderedPage.value = page
    highlightStyle.value = {
      left: `${bbox.left}px`,
      top: `${bbox.top}px`,
      width: `${bbox.width}px`,
      height: `${bbox.height}px`,
    }
    await nextTick()
    canvasHost.value?.replaceChildren(page.canvas)
  } catch (error: unknown) {
    renderedPage.value = null
    highlightStyle.value = null
    errorCode.value = safeError(error)
  }
})

function back(): void {
  emit('back', {
    release_id: props.request.release_id,
    activation_epoch: props.request.activation_epoch,
  })
}
</script>

<template>
  <div class="schema-citation-viewer">
    <button
      type="button"
      data-testid="citation-back"
      @click="back"
    >
      Back
    </button>
    <p
      v-if="errorCode"
      data-testid="citation-error"
      role="status"
    >
      {{ errorCode }}
    </p>
    <div
      v-else-if="renderedPage"
      class="schema-citation-viewer__page"
      data-testid="citation-page"
      :data-page-number="renderedPage.pageNumber"
      :style="{ width: `${renderedPage.width}px`, height: `${renderedPage.height}px` }"
    >
      <div ref="canvasHost" class="schema-citation-viewer__canvas" />
      <span
        v-if="highlightStyle"
        class="schema-citation-viewer__highlight"
        data-testid="citation-highlight"
        :style="highlightStyle"
      />
    </div>
  </div>
</template>

<style scoped>
.schema-citation-viewer__page {
  position: relative;
}

.schema-citation-viewer__highlight {
  position: absolute;
  border: 2px solid #e89b19;
  background: rgb(255 207 64 / 24%);
  pointer-events: none;
}
</style>
