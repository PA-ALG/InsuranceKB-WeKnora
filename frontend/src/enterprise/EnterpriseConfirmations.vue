<script setup lang="ts">
import { computed, nextTick, ref, toRef, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfirmationCard from './ConfirmationCard.vue'
import type { ConfirmationItem } from './enterpriseApi'
import { useConfirmations } from './useConfirmations'

const props = defineProps<{ spaceId: string }>()
const { t } = useI18n()
const { tab, state, items, drafts, notice, moved, load, selectTab, answer } = useConfirmations(toRef(props, 'spaceId'))
const root = ref<HTMLElement>(), regionId = useId()
const tabs = computed(() => [
  { key: 'open' as const, title: t('enterpriseKnowledge.confirm.open') },
  { key: 'closed' as const, title: t('enterpriseKnowledge.confirm.closed') },
])

function focusTab() {
  root.value?.querySelector<HTMLButtonElement>(`[data-confirm-tab="${tab.value}"]`)?.focus()
}
async function moveTab(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  selectTab(event.key === 'Home' ? 'open' : event.key === 'End' ? 'closed' : tab.value === 'open' ? 'closed' : 'open')
  await nextTick()
  focusTab()
}
function update(item: ConfirmationItem, change: { option?: string; note?: string }) {
  const draft = drafts.get(item.id)
  if (!draft || draft.busy) return
  if (change.option !== undefined) draft.option = change.option
  if (change.note !== undefined) draft.note = change.note
  draft.error = ''
}
async function submit(item: ConfirmationItem) {
  const result = await answer(item)
  if (result !== 'answered' && result !== 'moved' && result !== 'closed') return
  await nextTick()
  if (result === 'moved') {
    // The card left 待处理; the notice says where it went and takes the focus.
    root.value?.querySelector<HTMLElement>('[data-confirm-moved]')?.focus()
    return
  }
  // The submit button is disabled once the recorded choice matches the draft, so the result line takes focus.
  const card = [...root.value?.querySelectorAll<HTMLElement>('[data-confirm-item]') ?? []]
    .find(element => element.dataset.confirmItem === item.id)
  const target = result === 'answered' ? card?.querySelector<HTMLElement>('[data-confirm-state]') : undefined
  if (target) target.focus()
  else focusTab()
}
</script>

<template>
  <main ref="root" class="ek-page ek-confirm-page">
    <div class="ek-confirm-shell">
      <RouterLink class="ek-back" :to="{ name: 'enterpriseSpace', params: { spaceId } }">← {{ t('enterpriseKnowledge.graph.back') }}</RouterLink>
      <header class="ek-confirm-heading">
        <div><h1 class="ek-page__title">{{ t('enterpriseKnowledge.confirm.title') }}</h1>
          <p class="ek-page__meta">{{ t('enterpriseKnowledge.confirm.description') }}</p></div>
        <span v-if="state === 'ready'" class="ek-meta-tag">{{ t('enterpriseKnowledge.confirm.count', { count: items.length }) }}</span>
      </header>
      <p v-if="notice" class="ek-confirm-notice" role="status" data-confirm-notice>{{ t('enterpriseKnowledge.confirm.closedMeanwhile', { title: notice }) }}</p>
      <p v-if="moved" class="ek-confirm-notice" role="status" tabindex="-1" data-confirm-moved>{{ t('enterpriseKnowledge.confirm.moved', { option: moved }) }}</p>
      <div class="ek-confirm-tabs" role="tablist" :aria-label="t('enterpriseKnowledge.confirm.title')">
        <button v-for="entry in tabs" :id="`${regionId}-${entry.key}`" :key="entry.key" type="button" role="tab" :data-confirm-tab="entry.key"
          :aria-selected="tab === entry.key" :aria-controls="regionId" :tabindex="tab === entry.key ? 0 : -1"
          @click="selectTab(entry.key)" @keydown="moveTab">{{ entry.title }}</button>
      </div>
      <div :id="regionId" role="tabpanel" :aria-labelledby="`${regionId}-${tab}`">
        <p v-if="state === 'loading'" class="ek-status" role="status">{{ t('enterpriseKnowledge.loading') }}</p>
        <div v-else-if="state === 'failed'" class="ek-alert" role="alert">
          <span>{{ t('enterpriseKnowledge.confirm.loadFailed') }}</span><button type="button" class="ek-button" @click="load()">{{ t('enterpriseKnowledge.retry') }}</button>
        </div>
        <p v-else-if="!items.length" class="ek-empty">{{ tab === 'open' ? t('enterpriseKnowledge.confirm.emptyOpen') : t('enterpriseKnowledge.confirm.emptyClosed') }}</p>
        <ConfirmationCard v-for="item in items" v-else :key="item.id" :item="item" :draft="drafts.get(item.id)"
          @option="update(item, { option: $event })" @note="update(item, { note: $event })" @submit="submit(item)" />
      </div>
    </div>
  </main>
</template>

<style src="./enterprisePage.css"></style>
<style src="./confirmations.css"></style>
