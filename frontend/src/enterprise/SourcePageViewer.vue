<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { get } from '@/utils/request'
import { createPdfJsPort, type OpenedPdfDocument } from './pdfJsPort'
import { highlightBoxes, type NormalizedRect } from './sourcePage'

const props = defineProps<{
  file: string
  page: number
  rects: readonly NormalizedRect[]
  complete: boolean
  labels: { loading: string; failed: string; retry: string; incomplete: string; region: string }
}>()

const state = ref<'loading' | 'ready' | 'failed'>('loading')
const retry = ref(0)
const canvasHost = ref<HTMLElement>()
const pageContainer = ref<HTMLElement>()
const boxes = computed(() => highlightBoxes(props.rects))

watch(
  () => [props.file, props.page, retry.value] as const,
  ([file, page], _, onCleanup) => {
    const controller = new AbortController()
    let active = true
    let document: OpenedPdfDocument | undefined

    // Clear ownership before closing: invalidation, render failure and a late
    // completion can all reach this path, but each document is closed once.
    function closeDocument() {
      const opened = document
      document = undefined
      if (opened) {
        try {
          void Promise.resolve(opened.close?.()).catch(() => {})
        } catch { /* Closing must not prevent aborting or replacing the citation. */ }
      }
    }

    onCleanup(() => {
      active = false
      controller.abort()
      closeDocument()
    })
    state.value = 'loading'

    void (async () => {
      try {
        const bytes = await get<ArrayBuffer>(file, {
          responseType: 'arraybuffer', timeout: 180_000, signal: controller.signal,
        })
        if (!active) return
        document = await createPdfJsPort().open(new Uint8Array(bytes))
        if (!active) { closeDocument(); return }
        if (!Number.isInteger(page) || page < 1 || page > document.pageCount) {
          closeDocument()
          state.value = 'failed'
          return
        }
        const rendered = await document.renderPage(page)
        if (!active) return
        state.value = 'ready'
        await nextTick()
        if (!active) return
        canvasHost.value?.replaceChildren(rendered.canvas)
        pageContainer.value?.querySelector<HTMLElement>('[data-highlight]')
          ?.scrollIntoView?.({ block: 'center' })
      } catch {
        closeDocument()
        if (active) state.value = 'failed'
      }
    })()
  },
  { immediate: true },
)
</script>

<template>
  <div class="source-page-viewer">
    <p v-if="state === 'loading'" role="status">{{ labels.loading }}</p>
    <div v-else-if="state === 'failed'" class="source-page-error" role="alert">
      <p>{{ labels.failed }}</p>
      <button type="button" @click="retry++">{{ labels.retry }}</button>
    </div>
    <template v-else>
      <div ref="pageContainer" data-source-page class="source-page" role="img" :aria-label="labels.region">
        <div ref="canvasHost" class="source-page-canvas" />
        <span
          v-for="(box, index) in boxes" :key="index"
          data-highlight aria-hidden="true" class="source-page-highlight" :style="{ ...box }"
        />
      </div>
      <p v-if="!complete" data-highlight-incomplete role="note">{{ labels.incomplete }}</p>
    </template>
  </div>
</template>

<style scoped>
.source-page-viewer { min-width: 0; color: var(--td-text-color-primary); }
.source-page { position: relative; width: 100%; }
.source-page-canvas :deep(canvas) { display: block; width: 100%; height: auto; }
.source-page-highlight {
  position: absolute;
  pointer-events: none;
  background: rgb(255 210 0 / 32%);
  outline: 1px solid rgb(196 145 0 / 70%);
}
.source-page-error button { cursor: pointer; color: var(--td-brand-color); }
</style>
