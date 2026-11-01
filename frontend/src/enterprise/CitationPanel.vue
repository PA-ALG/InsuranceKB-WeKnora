<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ExpertCitation from './ExpertCitation.vue'
import OfficeSourceViewer from './OfficeSourceViewer.vue'
import OfficeTextView from './OfficeTextView.vue'
import SourcePageViewer from './SourcePageViewer.vue'
import {
  EnterpriseError, isExpertCitation, readCitation, type Citation, type ExpertCitation as ExpertRecord,
} from './enterpriseApi'
import { citationFailure, originLabel } from './fieldLabels'
import { officeTarget, type OfficePosition } from './officeCitation'

const props = defineProps<{ spaceId: string; releaseId: string; member: string; evidence: number }>()
const { t } = useI18n()
const state = ref<'loading' | 'failed' | 'ready'>('loading')
const failure = ref('')
const citation = ref<Citation | null>(null)
// An expert-revised field cites its revision record instead of a page (S9b Spec §2.5).
const expert = ref<ExpertRecord | null>(null)
let generation = 0

const viewerLabels = computed(() => ({
  loading: t('enterpriseKnowledge.viewer.loading'),
  failed: t('enterpriseKnowledge.viewer.failed'),
  retry: t('enterpriseKnowledge.retry'),
  incomplete: t('enterpriseKnowledge.viewer.incomplete'),
  region: t('enterpriseKnowledge.viewer.region', {
    document: citation.value?.source.document ?? '',
    page: citation.value?.page.number ?? '',
  }),
}))

// A PDF citation has page geometry; an Office one (S11d) has its block's locator instead and opens
// in upstream's preview. Anything else shows the document, page and quote only (S11e Spec §3.3).
const office = computed(() => {
  const read = citation.value
  return read && !read.highlight ? officeTarget(read.locator, read.quote) : null
})

function place(position: OfficePosition): string {
  switch (position.kind) {
    case 'slide': return t('enterpriseKnowledge.citation.slide', { slide: position.slide })
    case 'block': return t('enterpriseKnowledge.citation.block', { block: position.block })
    case 'row': return t('enterpriseKnowledge.citation.row', { sheet: position.sheet, row: position.row })
  }
}

const position = computed(() => office.value
  ? place(office.value.position)
  : t('enterpriseKnowledge.citation.page', { page: citation.value?.page.number ?? '' }))

const officeLabels = computed(() => ({
  loading: t('enterpriseKnowledge.viewer.loading'),
  failed: t('enterpriseKnowledge.viewer.failed'),
  retry: t('enterpriseKnowledge.retry'),
  coarse: t('enterpriseKnowledge.viewer.coarse'),
  notLocated: t('enterpriseKnowledge.viewer.notLocated'),
  unsafe: t('enterpriseKnowledge.viewer.unsafe'),
  region: t('enterpriseKnowledge.viewer.officeRegion', {
    document: citation.value?.source.document ?? '', position: position.value,
  }),
}))

// When the preview cannot show the citation, the viewer hands over the downloaded file and the
// cited place is shown as text below it (S11h Spec §2.2).
const textLabels = computed(() => ({
  title: t('enterpriseKnowledge.viewer.text.title'),
  failed: t('enterpriseKnowledge.viewer.text.failed'),
  stalled: t('enterpriseKnowledge.viewer.text.stalled'),
  notLocated: t('enterpriseKnowledge.viewer.text.notLocated'),
  loading: t('enterpriseKnowledge.viewer.text.loading'),
  empty: t('enterpriseKnowledge.viewer.text.empty'),
  unavailable: t('enterpriseKnowledge.viewer.text.unavailable'),
  quoteMissing: t('enterpriseKnowledge.viewer.text.quoteMissing'),
  download: t('enterpriseKnowledge.viewer.text.download'),
  notes: t('enterpriseKnowledge.viewer.text.notes'),
}))

async function load() {
  const current = ++generation
  state.value = 'loading'
  citation.value = null
  expert.value = null
  try {
    const read = await readCitation(props.spaceId, props.releaseId, props.member, props.evidence)
    if (current !== generation) return
    if (isExpertCitation(read)) expert.value = read
    else citation.value = read
    state.value = 'ready'
  } catch (error) {
    if (current !== generation) return
    // Typed refusals only: a failed citation never falls back to another page or release.
    failure.value = citationFailure(t, error instanceof EnterpriseError ? error.code : '')
    state.value = 'failed'
  }
}

watch(() => [props.spaceId, props.releaseId, props.member, props.evidence], load, { immediate: true })
</script>

<template>
  <div class="ek-citation">
    <p v-if="state === 'loading'" role="status" class="ek-status">{{ t('enterpriseKnowledge.loading') }}</p>
    <div v-else-if="state === 'failed'" role="alert" class="ek-alert">
      <span>{{ failure }}</span>
      <button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button>
    </div>
    <template v-else-if="expert">
      <p class="ek-citation__source">
        <span data-origin class="ek-origin">{{ originLabel(t, expert.origin) }}</span>
      </p>
      <ExpertCitation :citation="expert" />
    </template>
    <template v-else-if="citation">
      <p class="ek-citation__source">
        <span>{{ citation.source.document }}</span>
        <span>{{ position }}</span>
        <span
          v-if="citation.origin"
          data-origin
          :class="['ek-origin', { 'ek-origin--generated': citation.origin === 'MODEL_GENERATED' }]"
        >{{ originLabel(t, citation.origin) }}</span>
      </p>
      <blockquote class="ek-citation__quote">{{ citation.quote }}</blockquote>
      <SourcePageViewer
        v-if="citation.highlight"
        :file="citation.file"
        :page="citation.page.number"
        :rects="citation.highlight.rects"
        :complete="citation.highlight.complete"
        :labels="viewerLabels"
      />
      <OfficeSourceViewer
        v-else-if="office"
        :file="citation.file"
        :document="citation.source.document"
        :target="office"
        :labels="officeLabels"
      >
        <template #fallback="{ reason, original }">
          <OfficeTextView
            :original="original"
            :document="citation.source.document"
            :target="office"
            :reason="reason"
            :labels="textLabels"
          />
        </template>
      </OfficeSourceViewer>
      <p v-else role="note" class="ek-status">{{ t('enterpriseKnowledge.viewer.noViewer') }}</p>
    </template>
  </div>
</template>

<style src="./enterprisePage.css"></style>
