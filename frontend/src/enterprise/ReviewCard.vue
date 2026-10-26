<script setup lang="ts">
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import EnterpriseField from './EnterpriseField.vue'
import type { Release } from './enterpriseApi'
import { entitySummaries } from './releaseView'
import { canDecide, type ReviewEntry } from './useReviews'
import { reviewChanges } from './reviewView'
import { reviewReasonLength } from './reviewReason'
const props = defineProps<{ entry: ReviewEntry; release: Release | null }>()
const emit = defineEmits<{ open: []; decide: [outcome: 'approve' | 'reject']; reason: [value: string]; reload: [] }>()
const { t, locale } = useI18n(), id = useId()
const subjects = computed(() => {
  const names = new Map(props.release ? entitySummaries(props.release).map(e => [e.entityId, e.name]) : [])
  return props.entry.item.subjects.map(subject => names.get(subject) || subject).join('、')
})
const date = computed(() => {
  const date = new Date(props.entry.item.created_at)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString(locale.value)
})
const rows = computed(() => props.entry.detail ? reviewChanges(props.entry.detail, props.release) : null)
const count = computed(() => reviewReasonLength(props.entry.reason))
const pending = computed(() => (props.entry.detail?.status ?? props.entry.item.status) === 'pending')
const blocker = computed(() => {
  const code = props.entry.detail?.blocker
  return !code ? '' : code === 'NEEDS_REBASE' ? t('enterpriseKnowledge.review.needsRebase')
    : code === 'CANDIDATE_INVALID' ? t('enterpriseKnowledge.review.invalidCandidate') : `${t('enterpriseKnowledge.review.blocked')} (${code})`
})
const status = computed(() => t(`enterpriseKnowledge.review.${props.entry.detail?.status ?? props.entry.item.status}`))
const result = computed(() => {
  const result = props.entry.result
  return !result ? '' : result.status === 'released' ? t('enterpriseKnowledge.review.releasedAt', { n: result.epoch })
    : t(`enterpriseKnowledge.review.${result.status === 'approved' ? 'awaitingRelease' : 'rejected'}`)
})
</script>
<template>
  <article class="ek-review-card" :data-review-item="entry.item.candidate_id" :aria-busy="entry.busy || entry.phase === 'loading'">
    <header class="ek-review-card__heading">
      <h2 data-review-subjects>{{ subjects }}</h2>
      <time :datetime="entry.item.created_at">{{ date }}</time>
      <p class="ek-page__meta">{{ t('enterpriseKnowledge.review.fields', { count: entry.item.members + entry.item.removals }) }}</p>
    </header>
    <p v-if="entry.result" data-review-state class="ek-review-result" role="status" tabindex="-1">{{ result }}</p>
    <template v-else-if="!pending">
      <p data-review-status class="ek-review-result">{{ status }}</p>
      <p data-review-decision-reason class="ek-review-text">{{ (entry.detail ?? entry.item).decision?.reason }}</p>
    </template>
    <template v-else>
      <button type="button" class="ek-button" data-review-open :disabled="entry.busy || entry.phase === 'loading'"
        :aria-expanded="entry.phase !== 'idle'" :aria-controls="`${id}-detail`" @click="emit('open')">{{ t('enterpriseKnowledge.review.open') }}</button>
      <section v-if="entry.phase !== 'idle'" :id="`${id}-detail`" data-review-detail tabindex="-1" :aria-label="t('enterpriseKnowledge.review.detail')">
        <p v-if="entry.phase === 'loading'" role="status">{{ t('enterpriseKnowledge.loading') }}</p>
        <p v-if="entry.error" role="alert" class="ek-alert">{{ t('enterpriseKnowledge.review.failed') }} ({{ entry.error }})</p>
        <button v-if="entry.phase === 'failed'" class="ek-button" type="button" @click="emit('open')">{{ t('enterpriseKnowledge.retry') }}</button>
        <template v-if="entry.detail && entry.phase === 'ready'">
          <p v-if="blocker" data-review-blocker role="status" class="ek-alert">{{ blocker }}</p>
          <div v-if="rows === null" class="ek-alert" role="status">
            <span>{{ t('enterpriseKnowledge.review.previewUnavailable') }}</span>
            <button type="button" class="ek-button" :disabled="entry.busy" @click="emit('reload')">{{ t('enterpriseKnowledge.retry') }}</button>
          </div>
          <p v-else-if="!rows.length" class="ek-page__meta">{{ t('enterpriseKnowledge.review.noFields') }}</p>
          <div v-for="row in rows ?? []" :key="row.slug" :data-review-change="row.slug" class="ek-review-change">
            <h3>{{ row.name }} · {{ row.fieldTitle }}</h3>
            <div class="ek-review-values">
              <div v-if="row.before" data-review-before><p class="ek-page__meta">{{ t('enterpriseKnowledge.changes.before') }}</p>
                <EnterpriseField :field="row.before" :anchor-id="`${id}-${encodeURIComponent(row.slug)}-before`" /></div>
              <div v-if="row.after" data-review-after><p class="ek-page__meta">{{ t('enterpriseKnowledge.changes.after') }}</p>
                <EnterpriseField :field="row.after" :anchor-id="`${id}-${encodeURIComponent(row.slug)}-after`" /></div>
            </div>
            <blockquote v-for="(quote, index) in row.quotes" :key="index" data-review-quote class="ek-review-text">{{ quote }}</blockquote>
          </div>
          <label :for="`${id}-reason`" class="ek-review-label">{{ t('enterpriseKnowledge.review.reason') }}</label>
          <textarea :id="`${id}-reason`" data-review-reason :value="entry.reason" :disabled="entry.busy" rows="3"
            :aria-invalid="count > 2000" :aria-describedby="`${id}-count`" @input="emit('reason', ($event.target as HTMLTextAreaElement).value)" />
          <p :id="`${id}-count`" class="ek-page__meta">{{ t('enterpriseKnowledge.review.reasonCount', { count }) }}</p>
          <div class="ek-review-actions">
            <button type="button" class="ek-button ek-review-approve" data-review-approve :disabled="!canDecide(entry, release, 'approve')" @click="emit('decide', 'approve')">{{ t('enterpriseKnowledge.review.approve') }}</button>
            <button type="button" class="ek-button" data-review-reject :disabled="!canDecide(entry, release, 'reject')" @click="emit('decide', 'reject')">{{ t('enterpriseKnowledge.review.reject') }}</button>
          </div>
          <p v-if="entry.busy" role="status">{{ t('enterpriseKnowledge.review.submitting') }}</p>
        </template>
      </section>
    </template>
  </article>
</template>
