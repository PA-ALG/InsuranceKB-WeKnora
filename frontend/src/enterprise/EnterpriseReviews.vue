<script setup lang="ts">
import { computed, nextTick, ref, toRef, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import ReviewCard from './ReviewCard.vue'
import { useReviews, type ReviewFocus, type ReviewEntry } from './useReviews'
const props = defineProps<{ spaceId: string }>()
const { t } = useI18n(), id = useId(), root = ref<HTMLElement>()
const { tab, state, release, entries, notice, load, open, decide, selectTab } = useReviews(toRef(props, 'spaceId'))
const tabs = computed(() => [
  { key: 'pending' as const, label: t('enterpriseKnowledge.review.pending') },
  { key: 'decided' as const, label: t('enterpriseKnowledge.review.decided') },
])
function focusTab() { root.value?.querySelector<HTMLElement>(`[data-review-tab="${tab.value}"]`)?.focus() }
async function finish(action: Promise<ReviewFocus | null>) {
  const ticket = await action
  await nextTick()
  // Recheck after all awaits, including conflict refreshes and the DOM update.
  if (!ticket?.valid()) return
  if (ticket.target === 'tab') { focusTab(); return }
  const card = [...root.value?.querySelectorAll<HTMLElement>('[data-review-item]') ?? []].find(el => el.dataset.reviewItem === ticket.id)
  card?.querySelector<HTMLElement>(`[data-review-${ticket.target}]`)?.focus()
}
async function keydown(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  selectTab(event.key === 'Home' ? 'pending' : event.key === 'End' ? 'decided' : tab.value === 'pending' ? 'decided' : 'pending')
  await nextTick(); focusTab()
}
function reason(entry: ReviewEntry, value: string) { if (!entry.busy) { entry.reason = value; entry.error = '' } }
</script>
<template>
  <main ref="root" class="ek-page ek-review-page">
    <div class="ek-review-shell">
      <RouterLink class="ek-back" :to="{ name: 'enterpriseSpace', params: { spaceId } }">← {{ t('enterpriseKnowledge.graph.back') }}</RouterLink>
      <h1 class="ek-page__title">{{ t('enterpriseKnowledge.review.title') }}</h1>
      <p class="ek-page__meta">{{ t('enterpriseKnowledge.review.description') }}</p>
      <p v-if="notice" data-review-notice role="status" class="ek-alert">{{ t('enterpriseKnowledge.review.decidedElsewhere') }}</p>
      <div role="tablist" :aria-label="t('enterpriseKnowledge.review.title')" class="ek-review-tabs">
        <button v-for="entry in tabs" :id="`${id}-${entry.key}`" :key="entry.key" type="button" role="tab" :data-review-tab="entry.key"
          :aria-selected="tab === entry.key" :aria-controls="`${id}-panel`" :tabindex="tab === entry.key ? 0 : -1"
          @click="selectTab(entry.key)" @keydown="keydown">{{ entry.label }}</button>
      </div>
      <div :id="`${id}-panel`" role="tabpanel" :aria-labelledby="`${id}-${tab}`">
        <p v-if="state === 'loading'" role="status" class="ek-status">{{ t('enterpriseKnowledge.loading') }}</p>
        <div v-else-if="state === 'failed'" role="alert" class="ek-alert">{{ t('enterpriseKnowledge.review.loadFailed') }}
          <button type="button" class="ek-button" data-review-retry @click="finish(load())">{{ t('enterpriseKnowledge.retry') }}</button></div>
        <p v-else-if="!entries.length" class="ek-empty">{{ t(`enterpriseKnowledge.review.${tab === 'pending' ? 'emptyPending' : 'emptyDecided'}`) }}</p>
        <ReviewCard v-for="entry in entries" v-else :key="entry.item.candidate_id" :entry="entry" :release="release"
          @open="finish(open(entry))" @decide="finish(decide(entry, $event))" @reason="reason(entry, $event)" @reload="finish(load())" />
      </div>
    </div>
  </main>
</template>
<style src="./enterprisePage.css"></style>
<style src="./reviews.css"></style>
