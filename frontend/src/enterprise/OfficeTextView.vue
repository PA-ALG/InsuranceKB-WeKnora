<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import type { OfficeTarget } from './officeCitation'
import { readOfficeText, type OfficeFallbackReason, type OfficeText, type OfficeTextLine } from './officeText'

// The cited slide, block or row as text, for when upstream's preview cannot show it (S11h Spec
// §2.2). It reads the bytes the viewer already downloaded; file text is only ever interpolated.
const props = defineProps<{
  original: ArrayBuffer
  document: string
  target: OfficeTarget
  reason: OfficeFallbackReason
  labels: {
    title: string; failed: string; stalled: string; notLocated: string; loading: string; empty: string
    unavailable: string; quoteMissing: string; download: string; notes: string
  }
}>()

const state = ref<'loading' | 'ready' | 'failed'>('loading')
const text = shallowRef<OfficeText | null>(null)

watch(() => [props.original, props.target] as const, ([original, target], _, onCleanup) => {
  let active = true
  onCleanup(() => { active = false })
  state.value = 'loading'
  text.value = null
  readOfficeText(original, target).then(
    read => {
      if (!active) return
      text.value = read
      state.value = 'ready'
    },
    () => { if (active) state.value = 'failed' },
  )
}, { immediate: true })

// The original file, as downloaded through the release's cited-file route: no second request, and
// a generic type so the browser saves it instead of opening it.
const href = ref('')
watch(() => props.original, (original, _, onCleanup) => {
  const url = URL.createObjectURL(new Blob([original], { type: 'application/octet-stream' }))
  href.value = url
  onCleanup(() => URL.revokeObjectURL(url))
}, { immediate: true })

const lines = computed(() => text.value?.lines ?? [])
const firstNote = computed(() => lines.value.findIndex(line => line.kind === 'note'))

// A sheet row is shown under the sheet's first row, column by column.
const byColumn = (a: string, b: string) => a.length - b.length || a.localeCompare(b)
const columns = computed(() => [...new Set(lines.value.map(line => line.column ?? ''))].filter(Boolean).sort(byColumn))
const cellAt = (kind: OfficeTextLine['kind'], column: string) =>
  lines.value.find(line => line.kind === kind && line.column === column)
const hasHeader = computed(() => lines.value.some(line => line.kind === 'header'))
</script>

<template>
  <section data-office-text-view class="office-text-view" :aria-label="labels.title">
    <div class="office-text-view__head">
      <p class="office-text-view__reason">{{ labels[reason] }}</p>
      <a class="office-text-view__download" :href="href" :download="document">{{ labels.download }}</a>
    </div>
    <p v-if="state === 'loading'" role="status" class="ek-status">{{ labels.loading }}</p>
    <p v-else-if="state === 'failed'" class="ek-status">{{ labels.unavailable }}</p>
    <p v-else-if="!lines.length" class="ek-status">{{ labels.empty }}</p>
    <template v-else>
      <p v-if="!text?.quoted" class="ek-status">{{ labels.quoteMissing }}</p>
      <table v-if="target.format === 'xlsx'" class="office-text-view__row">
        <thead v-if="hasHeader">
          <tr>
            <th v-for="column in columns" :key="column" scope="col">{{ cellAt('header', column)?.segments.map(segment => segment.text).join('') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr data-cited>
            <td v-for="column in columns" :key="column">
              <template v-for="(segment, at) in cellAt('cell', column)?.segments ?? []" :key="at">
                <mark v-if="segment.mark">{{ segment.text }}</mark><template v-else>{{ segment.text }}</template>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="office-text-view__lines">
        <template v-for="(line, index) in lines" :key="index">
          <p v-if="index === firstNote" class="office-text-view__notes">{{ labels.notes }}</p>
          <p
            :data-cited="line.cited ? '' : undefined"
            :class="['office-text-view__line', { 'office-text-view__line--cited': line.cited && target.format === 'docx' }]"
          >
            <template v-for="(segment, at) in line.segments" :key="at">
              <mark v-if="segment.mark">{{ segment.text }}</mark><template v-else>{{ segment.text }}</template>
            </template>
          </p>
        </template>
      </div>
    </template>
  </section>
</template>

<style scoped>
.office-text-view {
  margin-top: 12px;
  padding: 12px 16px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 6px;
  background: var(--td-bg-color-container);
}
.office-text-view__head { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: baseline; justify-content: space-between; }
.office-text-view__reason { margin: 0; color: var(--td-text-color-secondary); }
.office-text-view__download { color: var(--td-brand-color); }
.office-text-view__lines { margin-top: 8px; }
.office-text-view__line { margin: 4px 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.office-text-view__line--cited { padding-left: 8px; border-left: 3px solid var(--td-brand-color); }
.office-text-view__notes { margin: 12px 0 4px; font-weight: 600; color: var(--td-text-color-secondary); }
.office-text-view__row { margin-top: 8px; border-collapse: collapse; }
.office-text-view__row th,
.office-text-view__row td { padding: 4px 8px; border: 1px solid var(--td-component-stroke); text-align: left; overflow-wrap: anywhere; }
.office-text-view__row th { font-weight: 600; color: var(--td-text-color-secondary); }
.office-text-view mark { background: var(--td-warning-color-2, #ffe9a8); color: inherit; }
</style>
