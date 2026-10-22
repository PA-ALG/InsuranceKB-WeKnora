<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ExpertCitation from './ExpertCitation.vue'
import SourcePageViewer from './SourcePageViewer.vue'
import {
  EnterpriseError, isExpertCitation, readCitation, type Citation, type ExpertCitation as ExpertRecord,
} from './enterpriseApi'
import { citationFailure, originLabel } from './fieldLabels'

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
        <span>{{ t('enterpriseKnowledge.citation.page', { page: citation.page.number }) }}</span>
        <span
          v-if="citation.origin"
          data-origin
          :class="['ek-origin', { 'ek-origin--generated': citation.origin === 'MODEL_GENERATED' }]"
        >{{ originLabel(t, citation.origin) }}</span>
      </p>
      <blockquote class="ek-citation__quote">{{ citation.quote }}</blockquote>
      <SourcePageViewer
        :file="citation.file"
        :page="citation.page.number"
        :rects="citation.highlight.rects"
        :complete="citation.highlight.complete"
        :labels="viewerLabels"
      />
    </template>
  </div>
</template>

<style src="./enterprisePage.css"></style>
