<script setup lang="ts">
import { nextTick, onMounted, ref, shallowRef } from 'vue'

import {
  assertPinnedCitation,
  citationHighlightStyle,
  parseCitationTarget,
  type CitationPinV1,
} from './schemaCitationTarget.ts'
import type { PdfPort, RenderedPdfPage } from './pdfJsPort.ts'

const props = defineProps<{
  target: unknown
  pin: CitationPinV1
  previewBytes: Uint8Array
  pdfPort: PdfPort
}>()

const errorCode = ref<string | null>(null)
const renderedPage = shallowRef<RenderedPdfPage | null>(null)
const highlightStyle = ref<Record<string, string> | null>(null)
const canvasHost = ref<HTMLElement | null>(null)

const SAFE_ERRORS = new Set([
  'BBOX_UNAVAILABLE',
  'CITATION_MEMBER_BINDING_MISMATCH',
  'CITATION_REPLAY_IDENTITY_MISMATCH',
  'CITATION_REVISION_NOT_PINNED',
  'CITATION_TARGET_INCOMPLETE',
  'PAGE_UNAVAILABLE',
  'PDF_PREVIEW_UNAVAILABLE',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function safeError(error: unknown): string {
  return error instanceof Error && SAFE_ERRORS.has(error.message)
    ? error.message
    : 'PDF_PREVIEW_UNAVAILABLE'
}

onMounted(async () => {
  try {
    if (isRecord(props.target) && !Object.hasOwn(props.target, 'page_number')) {
      throw new Error('PAGE_UNAVAILABLE')
    }
    if (isRecord(props.target) && !Object.hasOwn(props.target, 'bbox')) {
      throw new Error('BBOX_UNAVAILABLE')
    }
    const target = parseCitationTarget(props.target)
    assertPinnedCitation(target, props.pin)
    const opened = await props.pdfPort.open(props.previewBytes.slice())
    if (target.page_number > opened.pageCount) {
      throw new Error('PAGE_UNAVAILABLE')
    }
    const page = await opened.renderPage(target.page_number)
    if (page.pageNumber !== target.page_number) {
      throw new Error('PAGE_UNAVAILABLE')
    }
    const bbox = citationHighlightStyle(target, { width: page.width, height: page.height })
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
</script>

<template>
  <div class="schema-citation-viewer">
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
