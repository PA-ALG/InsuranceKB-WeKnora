<script setup lang="ts">
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import EnterpriseField from './EnterpriseField.vue'
import PointActions from './PointActions.vue'
import type { PointEntry, PointDecisionInput } from './useReviews'
import type { ReviewRow } from './reviewView'
const props = defineProps<{ entry: PointEntry; row: ReviewRow; busy: boolean; comparable: boolean; readonly?: boolean }>()
const emit = defineEmits<{ decide: [input: PointDecisionInput] }>()
const { t } = useI18n(), id = useId()
const status = computed(() => props.entry.result?.status ?? props.entry.point.status)
const reason = computed(() => props.entry.result?.reason ?? props.entry.point.decision?.reason)
const blocker = computed(() => props.entry.point.blocker === 'NEEDS_REBASE' ? t('enterpriseKnowledge.review.needsRebase')
  : `${t('enterpriseKnowledge.review.blocked')} (${props.entry.point.blocker})`)
</script>
<template>
  <article class="ek-review-change" :data-point="entry.point.slug" :aria-labelledby="`${id}-title`" :aria-busy="busy">
    <h3 :id="`${id}-title`">{{ row.title }}</h3>
    <p v-if="entry.result || readonly || status !== 'pending'" data-point-state class="ek-review-result" role="status" tabindex="-1">
      {{ entry.result?.epoch ? t('enterpriseKnowledge.review.releasedAt', { n: entry.result.epoch }) : t(`enterpriseKnowledge.review.${status}`) }}
      <span v-if="reason" class="ek-review-text"> · {{ reason }}</span>
    </p>
    <template v-else>
      <p v-if="entry.point.kind === 'member'">{{ t('enterpriseKnowledge.review.memberUpdate') }}</p>
      <template v-else>
        <p v-if="entry.point.kind === 'removal'" class="ek-alert">{{ t('enterpriseKnowledge.review.removal') }}</p>
        <div class="ek-review-values">
          <div v-if="comparable" data-point-before>
            <p class="ek-page__meta">{{ t('enterpriseKnowledge.review.before') }}</p>
            <EnterpriseField v-if="row.before" :field="row.before" :anchor-id="`${id}-before`" />
            <p v-else-if="row.beforeExists">{{ t('enterpriseKnowledge.review.existingContent') }} · {{ row.slug }}</p>
            <p v-else>{{ t('enterpriseKnowledge.changes.notPreviouslyPresent') }}</p>
          </div>
          <div v-if="row.after && entry.point.kind === 'claim'" data-point-after>
            <p class="ek-page__meta">{{ t('enterpriseKnowledge.review.after') }}</p>
            <EnterpriseField :field="row.after" :anchor-id="`${id}-after`" />
          </div>
        </div>
        <blockquote v-for="(quote, index) in row.quotes" :key="index" data-point-quote class="ek-review-text">{{ quote }}</blockquote>
      </template>
      <p v-if="entry.point.blocker" data-point-blocker role="status" class="ek-alert">{{ blocker }}</p>
      <p v-if="entry.error" data-point-error class="ek-alert" role="alert" tabindex="-1">{{ t('enterpriseKnowledge.review.failed') }} ({{ entry.error }})</p>
      <PointActions :busy="busy" :blocked="!!entry.point.blocker || !comparable" @decide="(outcome, reason) => emit('decide', { slugs: [entry.point.slug], outcome, reason })" />
    </template>
  </article>
</template>
