<script setup lang="ts">
import { computed, defineAsyncComponent, ref, shallowRef, watch } from 'vue'
import { get } from '@/utils/request'
import type { SourceLocateRequest } from '@/utils/sourceLocator'
import { officeLocateRequest, type OfficeFormat, type OfficeTarget } from './officeCitation'

// Upstream's original-file preview renders the Office file and highlights the citation; it is
// loaded on demand so the Office renderers stay out of the enterprise pages' first bundle.
const DocumentPreview = defineAsyncComponent(
  () => import('@/components/document-preview.vue').then(module => module.default),
)

const props = defineProps<{
  file: string
  document: string
  target: OfficeTarget
  labels: { loading: string; failed: string; retry: string; coarse: string; notLocated: string; region: string }
}>()

type Located = { found: boolean; precise: boolean }

const MEDIA_TYPES: Record<OfficeFormat, string> = {
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

const state = ref<'loading' | 'ready' | 'failed'>('loading')
const retry = ref(0)
const blob = shallowRef<Blob | null>(null)
const located = ref<Located | null>(null)
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
    located.value = null
    void (async () => {
      try {
        const bytes = await get<ArrayBuffer>(file, {
          responseType: 'arraybuffer', timeout: 180_000, signal: controller.signal,
        })
        if (!active) return
        blob.value = new Blob([bytes], { type: MEDIA_TYPES[format] })
        state.value = 'ready'
      } catch {
        if (active) state.value = 'failed'
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

// A rendered Office file is untrusted: docx-preview writes a file's external link targets into
// anchors as they are, `javascript:` included. Only web and mail links may be followed.
const FOLLOWABLE = /^(?:https?|mailto):$/

function blockUnsafeLinks(event: MouseEvent) {
  const link = event.target instanceof Element ? event.target.closest('a[href]') : null
  if (link instanceof HTMLAnchorElement && !FOLLOWABLE.test(link.protocol)) event.preventDefault()
}

function onLocated(result: Located) {
  located.value = { found: !!result?.found, precise: !!result?.precise }
}
</script>

<template>
  <div class="office-source-viewer">
    <p v-if="state === 'loading'" role="status">{{ labels.loading }}</p>
    <div v-else-if="state === 'failed'" class="office-source-error" role="alert">
      <p>{{ labels.failed }}</p>
      <button type="button" @click="retry++">{{ labels.retry }}</button>
    </div>
    <template v-else-if="blob">
      <div
        role="region" :aria-label="labels.region" class="office-source-preview"
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
    </template>
  </div>
</template>

<style scoped>
.office-source-viewer { min-width: 0; color: var(--td-text-color-primary); }
.office-source-preview { width: 100%; }
.office-source-error button { cursor: pointer; color: var(--td-brand-color); }
</style>
