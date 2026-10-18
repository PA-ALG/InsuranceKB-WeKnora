<script setup lang="ts">
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import EnterpriseField from './EnterpriseField.vue'
import type { Release, SpotSample, SpotVerdict } from './enterpriseApi'
import { sampledField } from './spotCheckView'
import { noteLength, type SpotDraft } from './useSpotChecks'

const props = defineProps<{ sample: SpotSample; release?: Release; loading: boolean; draft: SpotDraft }>()
const emit = defineEmits<{ note: [value: string]; decide: [outcome: SpotVerdict['outcome']]; source: [evidence: number] }>()
const { t, locale } = useI18n()
const field = computed(() => sampledField(props.sample, props.release))
const noteId = useId(), fieldId = useId()
const length = computed(() => noteLength(props.draft.note))
const outcomes = computed(() => [
  { key: 'correct' as const, title: t('enterpriseKnowledge.spot.correct') },
  { key: 'incomplete' as const, title: t('enterpriseKnowledge.spot.incomplete') },
  { key: 'wrong' as const, title: t('enterpriseKnowledge.spot.wrong') },
])
const verdictTitle = computed(() => outcomes.value.find(item => item.key === props.sample.verdict?.outcome)?.title)
const decidedAt = computed(() => {
  const raw = props.sample.verdict?.decided_at ?? '', date = new Date(raw)
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString(locale.value)
})
</script>

<template>
  <article class="ek-spot-card" :data-spot-sample="sample.id" :aria-busy="draft.busy">
    <div class="ek-spot-card__content">
      <h3>{{ field?.name || t('enterpriseKnowledge.spot.unavailable') }}</h3>
      <EnterpriseField v-if="field" :field="field.field" :anchor-id="fieldId" @open="emit('source', $event)" />
      <p v-else-if="loading" class="ek-page__meta">{{ t('enterpriseKnowledge.loading') }}</p>
      <p v-else class="ek-spot-changed">{{ t('enterpriseKnowledge.spot.changed') }}</p>
    </div>
    <div class="ek-spot-card__review">
      <template v-if="sample.verdict">
        <span class="ek-spot-verdict" :data-outcome="sample.verdict.outcome">{{ verdictTitle }}</span>
        <p class="ek-spot-note">{{ sample.verdict.note || t('enterpriseKnowledge.spot.noNote') }}</p>
        <p class="ek-page__meta">{{ t('enterpriseKnowledge.spot.reviewer') }} {{ sample.verdict.reviewer }}</p>
        <time class="ek-page__meta" :datetime="sample.verdict.decided_at">{{ decidedAt }}</time>
      </template>
      <template v-else>
        <label :for="noteId">{{ t('enterpriseKnowledge.spot.note') }}</label>
        <textarea :id="noteId" :value="draft.note" :disabled="draft.busy" :aria-invalid="length > 1000"
          :aria-describedby="`${noteId}-hint`" rows="3" :placeholder="t('enterpriseKnowledge.spot.notePlaceholder')"
          @input="emit('note', ($event.target as HTMLTextAreaElement).value)" />
        <span :id="`${noteId}-hint`" class="ek-spot-limit" :class="{ 'ek-spot-limit--invalid': length > 1000 }">{{ t('enterpriseKnowledge.spot.noteLimit', { count: length }) }}</span>
        <div class="ek-spot-actions">
          <button v-for="outcome in outcomes" :key="outcome.key" type="button" class="ek-button" :data-verdict="outcome.key"
            :disabled="!field || draft.busy || length > 1000" @click="emit('decide', outcome.key)">{{ outcome.title }}</button>
        </div>
        <p v-if="draft.busy" role="status" class="ek-page__meta">{{ t('enterpriseKnowledge.spot.submitting') }}</p>
        <p v-if="draft.error" role="alert" class="ek-spot-error">{{ draft.error === 'denied' ? t('enterpriseKnowledge.spot.denied') : t('enterpriseKnowledge.spot.submitFailed') }}</p>
      </template>
    </div>
  </article>
</template>
