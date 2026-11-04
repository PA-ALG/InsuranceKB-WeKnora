<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { EntityCell, EntityFieldChange, EntityReview } from './entityReview'
import vocabulary from './entityReviewVocabulary.json'
defineProps<{ change: EntityReview }>()
const { t } = useI18n()
function label(path: string): string {
  const key = (vocabulary.fields as Record<string, string>)[path]
  return key ? t(`enterpriseKnowledge.review.entityFields.${key}`) : path
}
function action(field: EntityFieldChange, beforeKnown: boolean): string {
  if (!beforeKnown) return t('enterpriseKnowledge.review.entityChange.proposed')
  if (!field.before.present) return t('enterpriseKnowledge.review.entityChange.added')
  return field.after.present ? t('enterpriseKnowledge.review.entityChange.changed') : t('enterpriseKnowledge.review.entityChange.removed')
}
function value(cell: EntityCell, known = true): string {
  if (!known) return t('enterpriseKnowledge.review.entityChange.unavailable')
  return cell.present ? JSON.stringify(cell.value) : t('enterpriseKnowledge.review.entityChange.notSet')
}
</script>
<template>
  <div class="ek-entity-changes">
    <p v-if="!change.fields.length" data-entity-unchanged>{{ t('enterpriseKnowledge.review.entityChange.unchanged') }}</p>
    <section v-for="field in change.fields" :key="field.path" :data-entity-field="field.path" class="ek-entity-change">
      <h4>{{ label(field.path) }} <span class="ek-page__meta">· {{ action(field, change.beforeKnown) }}</span></h4>
      <div class="ek-review-values">
        <div data-entity-before>
          <p class="ek-page__meta">{{ t('enterpriseKnowledge.review.before') }}</p>
          <pre class="ek-review-text">{{ value(field.before, change.beforeKnown) }}</pre>
          <p v-if="change.beforeKnown && field.before.explanation" class="ek-review-text">{{ field.before.explanation }}</p>
        </div>
        <div data-entity-after>
          <p class="ek-page__meta">{{ t('enterpriseKnowledge.review.after') }}</p>
          <pre class="ek-review-text">{{ value(field.after) }}</pre>
          <p v-if="field.after.explanation" class="ek-review-text">{{ field.after.explanation }}</p>
        </div>
      </div>
    </section>
  </div>
</template>
