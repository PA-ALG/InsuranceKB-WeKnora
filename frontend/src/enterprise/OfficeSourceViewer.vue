<script setup lang="ts">
import { computed, defineAsyncComponent, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { get } from '@/utils/request'
import type { SourceLocateRequest } from '@/utils/sourceLocator'
import { officeLocateRequest, type OfficeFormat, type OfficeTarget } from './officeCitation'
import { OfficePackageRejected, sanitizeOfficePackage } from './officePackage'
import type { OfficeFallbackReason } from './officeText'

// Upstream's original-file preview renders the Office file and highlights the citation; it is
// loaded on demand so the Office renderers stay out of the enterprise pages' first bundle.
const DocumentPreview = defineAsyncComponent(
  () => import('@/components/document-preview.vue').then(module => module.default),
)

const props = defineProps<{
  file: string
  document: string
  target: OfficeTarget
  labels: {
    loading: string; failed: string; retry: string; coarse: string; notLocated: string; unsafe: string; region: string
  }
}>()

// The citation panel puts the text view here (S11h Spec §2.2) with the downloaded bytes.
defineSlots<{ fallback?(props: { reason: OfficeFallbackReason; original: ArrayBuffer }): unknown }>()

type Located = { found: boolean; precise: boolean }

const MEDIA_TYPES: Record<OfficeFormat, string> = {
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

const state = ref<'loading' | 'ready' | 'failed' | 'rejected'>('loading')
const retry = ref(0)
const blob = shallowRef<Blob | null>(null)
const original = shallowRef<ArrayBuffer | null>(null)
const located = ref<Located | null>(null)
const fallback = ref<OfficeFallbackReason | null>(null)
const region = useTemplateRef<HTMLElement>('region')
const request = shallowRef<SourceLocateRequest>()
let token = 0
const note = computed(() => {
  if (!located.value) return ''
  if (!located.value.found) return props.labels.notLocated
  return located.value.precise ? '' : props.labels.coarse
})

// The bytes come from the release's cited-file route, never from the upstream knowledge preview,
// which does not check release access. Every opening asks the server: the route answers with an
// ETag and `no-cache`, so a cached copy is only reused after the server revalidates it.
watch(
  () => [props.file, props.target.format, retry.value] as const,
  ([file, format], _, onCleanup) => {
    const controller = new AbortController()
    let active = true
    onCleanup(() => {
      active = false
      controller.abort()
    })
    state.value = 'loading'
    blob.value = null
    original.value = null
    located.value = null
    void (async () => {
      try {
        const bytes = await get<ArrayBuffer>(file, {
          responseType: 'arraybuffer', timeout: 180_000, signal: controller.signal,
        })
        if (!active) return
        // The renderer only ever sees the rebuilt package (Spec §3.2a).
        const clean = await sanitizeOfficePackage(bytes, format)
        if (!active) return
        blob.value = new Blob([clean], { type: MEDIA_TYPES[format] })
        original.value = bytes
        state.value = 'ready'
      } catch (error) {
        if (active) state.value = error instanceof OfficePackageRejected ? 'rejected' : 'failed'
      }
    })()
  },
  { immediate: true },
)

// Another citation of the same file re-locates without downloading it again.
watch(() => props.target, target => {
  request.value = officeLocateRequest(target, ++token)
  located.value = null
}, { immediate: true })

// Upstream's preview catches its renderers' failures and shows an error element instead of
// emitting (document-preview.vue `onErrorCaptured`, `.preview-error`); a renderer may also never
// finish. The text view takes over when the preview fails, says nothing for 30 seconds, or does
// not bring the quote into view (`onLocated`), and steps back once the preview shows it after all
// (S11h Spec §2.2). Every opened file and every new citation starts over.
const STALLED_MS = 30_000

watch([region, request], ([element], _, onCleanup) => {
  fallback.value = null
  if (!element) return
  const failed = () => {
    if (element.querySelector('.preview-error')) fallback.value = 'failed'
  }
  const observer = new MutationObserver(failed)
  observer.observe(element, { childList: true, subtree: true })
  const timer = setTimeout(() => {
    if (!located.value && !fallback.value) fallback.value = 'stalled'
  }, STALLED_MS)
  failed()
  onCleanup(() => {
    observer.disconnect()
    clearTimeout(timer)
  })
})

// A rendered Office file is untrusted: docx-preview writes a file's external link targets into
// anchors as they are, `javascript:` included. The package rebuild already drops such targets;
// here only web and mail links may be followed, and a link whose target was dropped goes nowhere.
const FOLLOWABLE = /^(?:https?|mailto):$/

function blockUnsafeLinks(event: MouseEvent) {
  const link = event.target instanceof Element ? event.target.closest('a[href]') : null
  if (!(link instanceof HTMLAnchorElement)) return
  if (!link.getAttribute('href')?.trim() || !FOLLOWABLE.test(link.protocol)) event.preventDefault()
}

function onLocated(result: Located) {
  located.value = { found: !!result?.found, precise: !!result?.precise }
  // Upstream marks a whole slide when the quote is not in its rendered text (it is in the notes,
  // a skipped grouped frame, a chart or a picture), so the quote is not in view. A sheet row is
  // always marked whole, its cells in view.
  const inView = located.value.found && (located.value.precise || props.target.format !== 'pptx')
  fallback.value = inView ? null : 'notLocated'
}
</script>

<template>
  <div class="office-source-viewer">
    <p v-if="state === 'loading'" role="status">{{ labels.loading }}</p>
    <p v-else-if="state === 'rejected'" data-rejected role="note" class="ek-status">{{ labels.unsafe }}</p>
    <div v-else-if="state === 'failed'" class="office-source-error" role="alert">
      <p>{{ labels.failed }}</p>
      <button type="button" @click="retry++">{{ labels.retry }}</button>
    </div>
    <template v-else-if="blob">
      <div
        ref="region" role="region" :aria-label="labels.region" class="office-source-preview"
        @click.capture="blockUnsafeLinks" @auxclick.capture="blockUnsafeLinks"
      >
        <DocumentPreview
          :source-blob="blob"
          :file-type="target.format"
          :file-name="document"
          :active="true"
          :source-mode="true"
          :locate="request"
          @located="onLocated"
        />
      </div>
      <p v-if="note" data-located role="note" class="ek-status">{{ note }}</p>
      <slot v-if="fallback && original" name="fallback" :reason="fallback" :original="original" />
    </template>
  </div>
</template>

<style scoped>
.office-source-viewer { min-width: 0; color: var(--td-text-color-primary); }
.office-source-preview { width: 100%; }
.office-source-error button { cursor: pointer; color: var(--td-brand-color); }
</style>
