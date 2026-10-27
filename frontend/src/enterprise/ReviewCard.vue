<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Release } from './enterpriseApi'
import { entitySummaries } from './releaseView'
import { MAX_REVIEW_POINTS, canCompare, pendingPoint, type ReviewEntry, type PointDecisionInput } from './useReviews'
import { reviewRows } from './reviewView'
import ReviewPointCard from './ReviewPointCard.vue'
import PointActions from './PointActions.vue'
const props = defineProps<{ entry: ReviewEntry; release: Release | null; readonly: boolean }>()
const emit = defineEmits<{ open: []; decide: [input: PointDecisionInput]; reload: [] }>()
const { t, locale } = useI18n(), id = useId(), confirming = ref(false)
const subjects = computed(() => {
  const names = new Map(props.release ? entitySummaries(props.release).map(e => [e.entityId, e.name]) : [])
  return props.entry.item.subjects.map(subject => names.get(subject) || subject).join('、')
})
const date = computed(() => {
  const date = new Date(props.entry.item.created_at)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString(locale.value)
})
const rows = computed(() => props.entry.detail ? reviewRows(props.entry.detail, props.entry.snapshot) : new Map())
const comparable = computed(() => canCompare(props.entry))
const sessionPoints = computed(() => props.entry.points.filter(value => value.point.status === 'pending'))
const ordinary = computed(() => sessionPoints.value.filter(value => rows.value.get(value.point.slug)?.after?.state !== 'unknown'))
const unknown = computed(() => sessionPoints.value.filter(value => rows.value.get(value.point.slug)?.after?.state === 'unknown'))
const unknownPending = computed(() => unknown.value.filter(pendingPoint))
const unknownEligible = computed(() => unknownPending.value.filter(value => !value.point.blocker))
const unknownBlocked = computed(() => unknownPending.value.length - unknownEligible.value.length)
const decided = computed(() => props.entry.points.filter(value => value.point.status !== 'pending'))
const remaining = computed(() => props.entry.points.filter(pendingPoint))
const eligible = computed(() => remaining.value.filter(value => !value.point.blocker))
const blocked = computed(() => remaining.value.length - eligible.value.length)
watch(() => [props.entry.operation, props.entry.expanded], () => { confirming.value = false })
function approveRest() {
  if (props.entry.busy || !comparable.value || !eligible.value.length || eligible.value.length > MAX_REVIEW_POINTS) return
  if (!confirming.value) { confirming.value = true; return }
  confirming.value = false
  emit('decide', { slugs: eligible.value.map(value => value.point.slug), outcome: 'approve', reason: t('enterpriseKnowledge.review.defaultReason') })
}
</script>
<template>
  <article class="ek-review-card" :data-review-item="entry.item.candidate_id" :aria-busy="entry.busy || entry.phase === 'loading'" :aria-labelledby="`${id}-title`">
    <header class="ek-review-card__heading">
      <h2 :id="`${id}-title`" data-review-subjects>{{ subjects }}</h2>
      <time :datetime="entry.item.created_at">{{ date }}</time>
      <p data-review-progress class="ek-page__meta">{{ readonly ? t('enterpriseKnowledge.review.total', { count: entry.item.point_count })
        : t('enterpriseKnowledge.review.progress', { pending: entry.item.pending_points, count: entry.item.point_count }) }}</p>
      <template v-if="readonly">
        <p data-review-status class="ek-review-result">{{ t(`enterpriseKnowledge.review.${entry.item.status}`) }}</p>
        <p data-review-decision-reason class="ek-review-text">{{ entry.item.decision?.reason }}</p>
      </template>
      <button type="button" class="ek-button" data-review-open :disabled="entry.busy || entry.phase === 'loading'"
        :aria-expanded="entry.expanded" :aria-controls="`${id}-detail`" @click="emit('open')">{{ t(entry.expanded ? 'enterpriseKnowledge.review.close' : 'enterpriseKnowledge.review.open') }}</button>
    </header>
    <section v-if="entry.expanded" :id="`${id}-detail`" data-review-detail tabindex="-1" :aria-label="t('enterpriseKnowledge.review.detail')">
      <p v-if="entry.phase === 'loading'" role="status">{{ t('enterpriseKnowledge.loading') }}</p>
      <p v-if="entry.notice" data-review-notice role="status" class="ek-alert">{{ t('enterpriseKnowledge.review.memberDecided') }}</p>
      <p v-if="entry.error" role="alert" class="ek-alert">{{ t('enterpriseKnowledge.review.failed') }} ({{ entry.error }})</p>
      <button v-if="entry.phase === 'failed'" class="ek-button" type="button" @click="emit('reload')">{{ t('enterpriseKnowledge.retry') }}</button>
      <template v-if="entry.detail && entry.phase === 'ready'">
        <template v-if="readonly">
          <ReviewPointCard v-for="point in entry.points" :key="point.point.slug" :entry="point" :row="rows.get(point.point.slug)!" :busy="false" :comparable="comparable" readonly />
        </template>
        <template v-else>
          <div v-if="!comparable" class="ek-alert" role="status">
            <p>{{ t('enterpriseKnowledge.review.previewUnavailable') }}</p>
            <button type="button" class="ek-button" :disabled="entry.busy" @click="emit('reload')">{{ t('enterpriseKnowledge.retry') }}</button>
          </div>
          <ReviewPointCard v-for="point in ordinary" :key="point.point.slug" :entry="point" :row="rows.get(point.point.slug)!" :busy="entry.busy" :comparable="comparable" @decide="emit('decide', $event)" />
          <section v-if="unknown.length" data-point-unknown-group class="ek-unknown-group" :aria-labelledby="`${id}-unknown`">
            <h3 :id="`${id}-unknown`">{{ t('enterpriseKnowledge.review.unknownGroup') }}</h3>
            <p v-if="unknownBlocked" :id="`${id}-unknown-conflicts`" role="status">{{ t('enterpriseKnowledge.review.conflicts', { count: unknownBlocked }) }}</p>
            <p v-if="unknownEligible.length > MAX_REVIEW_POINTS" :id="`${id}-unknown-approve-limit`" role="status">{{ t('enterpriseKnowledge.review.approveUnknown') }}：{{ t('enterpriseKnowledge.review.batchLimit') }}</p>
            <p v-if="unknownPending.length > MAX_REVIEW_POINTS" :id="`${id}-unknown-reject-limit`" role="status">{{ t('enterpriseKnowledge.review.rejectUnknown') }}：{{ t('enterpriseKnowledge.review.batchLimit') }}</p>
            <PointActions v-if="unknownPending.length" :busy="entry.busy" :blocked="!comparable || !unknownEligible.length" group
              :approve-disabled="unknownEligible.length > MAX_REVIEW_POINTS" :reject-disabled="unknownPending.length > MAX_REVIEW_POINTS"
              :approve-hint="[unknownBlocked ? `${id}-unknown-conflicts` : '', unknownEligible.length > MAX_REVIEW_POINTS ? `${id}-unknown-approve-limit` : ''].filter(Boolean).join(' ') || undefined"
              :reject-hint="unknownPending.length > MAX_REVIEW_POINTS ? `${id}-unknown-reject-limit` : undefined"
              @decide="(outcome, reason) => emit('decide', { slugs: (outcome === 'approve' ? unknownEligible : unknownPending).map(value => value.point.slug), outcome, reason })" />
            <details v-for="point in unknown" :key="point.point.slug" class="ek-unknown-point">
              <summary>{{ rows.get(point.point.slug)!.title }}</summary>
              <ReviewPointCard :entry="point" :row="rows.get(point.point.slug)!" :busy="entry.busy" :comparable="comparable" @decide="emit('decide', $event)" />
            </details>
          </section>
          <details v-if="decided.length" data-point-decided class="ek-decided-points">
            <summary>{{ t('enterpriseKnowledge.review.decided') }} ({{ decided.length }})</summary>
            <ReviewPointCard v-for="point in decided" :key="point.point.slug" :entry="point" :row="rows.get(point.point.slug)!" :busy="false" :comparable="comparable" readonly />
          </details>
          <p v-if="!remaining.length" class="ek-review-result" role="status">{{ t(entry.points.length ? 'enterpriseKnowledge.review.complete' : 'enterpriseKnowledge.review.noFields') }}</p>
          <div v-else class="ek-review-batch">
            <p v-if="blocked" role="status">{{ t('enterpriseKnowledge.review.conflicts', { count: blocked }) }}</p>
            <p v-if="eligible.length > MAX_REVIEW_POINTS" :id="`${id}-rest-limit`" role="status">{{ t('enterpriseKnowledge.review.batchLimit') }}</p>
            <button type="button" class="ek-button ek-review-approve" data-review-approve-rest :disabled="entry.busy || !comparable || !eligible.length || eligible.length > MAX_REVIEW_POINTS"
              :aria-describedby="eligible.length > MAX_REVIEW_POINTS ? `${id}-rest-limit` : undefined" @click="approveRest">
              {{ t(confirming ? 'enterpriseKnowledge.review.confirmRest' : 'enterpriseKnowledge.review.approveRest', { count: eligible.length }) }}
            </button>
          </div>
          <p v-if="entry.busy" role="status">{{ t('enterpriseKnowledge.review.submitting') }}</p>
        </template>
      </template>
    </section>
  </article>
</template>
