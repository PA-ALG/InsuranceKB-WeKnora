<script setup lang="ts">
import { computed, nextTick, ref, toRef, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Drawer } from 'tdesign-vue-next'
import CitationPanel from './CitationPanel.vue'
import SpotCheckCard from './SpotCheckCard.vue'
import type { SpotSample, SpotVerdict } from './enterpriseApi'
import { sampledField } from './spotCheckView'
import { useSpotChecks } from './useSpotChecks'

const props = defineProps<{ spaceId: string }>()
const { t } = useI18n()
const { tab, state, samples, releases, draft, load, loadRelease, selectTab, decide } = useSpotChecks(toRef(props, 'spaceId'))
const root = ref<HTMLElement>(), regionId = useId()
const tabs = computed(() => [
  { key: 'pending' as const, title: t('enterpriseKnowledge.spot.pending') },
  { key: 'decided' as const, title: t('enterpriseKnowledge.spot.decided') },
])
const groups = computed(() => {
  const groups = new Map<string, SpotSample[]>()
  for (const sample of samples.value) groups.set(sample.release_id, [...(groups.get(sample.release_id) ?? []), sample])
  return [...groups].map(([id, items]) => ({ id, items, ...releases.get(id) }))
})
const source = ref<{ spaceId: string; sampleId: string; releaseId: string; member: string; evidence: number } | null>(null)
let sourceButton: HTMLElement | null = null
function openSource(sample: SpotSample, evidence: number) {
  if (!sampledField(sample, releases.get(sample.release_id)?.release)) return
  sourceButton = document.activeElement instanceof HTMLElement ? document.activeElement : null
  source.value = { spaceId: props.spaceId, sampleId: sample.id, releaseId: sample.release_id, member: sample.logical_slug, evidence }
}
async function closeSource() {
  source.value = null
  await nextTick()
  if (sourceButton?.isConnected) sourceButton.focus()
}
function switchTab(next: 'pending' | 'decided') {
  source.value = null
  selectTab(next)
}
async function moveTab(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  switchTab(event.key === 'Home' ? 'pending' : event.key === 'End' ? 'decided' : tab.value === 'pending' ? 'decided' : 'pending')
  await nextTick()
  root.value?.querySelector<HTMLButtonElement>(`[data-spot-tab="${tab.value}"]`)?.focus()
}
async function submit(sample: SpotSample, outcome: SpotVerdict['outcome']) {
  if (!await decide(sample, outcome)) return
  if (source.value?.sampleId === sample.id) source.value = null
  await nextTick()
  const target = root.value?.querySelector<HTMLButtonElement>('[data-verdict]:not(:disabled)')
    ?? root.value?.querySelector<HTMLButtonElement>(`[data-spot-tab="${tab.value}"]`)
  target?.focus()
}
watch(() => props.spaceId, () => { source.value = null; sourceButton = null }, { flush: 'sync' })
</script>

<template>
  <main ref="root" class="ek-page ek-spot-page">
    <div class="ek-spot-shell">
      <RouterLink class="ek-back" :to="{ name: 'enterpriseSpace', params: { spaceId } }">← {{ t('enterpriseKnowledge.graph.back') }}</RouterLink>
      <header class="ek-spot-heading">
        <div><h1 class="ek-page__title">{{ t('enterpriseKnowledge.spot.title') }}</h1>
          <p class="ek-page__meta">{{ t('enterpriseKnowledge.spot.description') }}</p></div>
        <span v-if="state === 'ready'" class="ek-meta-tag">{{ t('enterpriseKnowledge.spot.count', { count: samples.length }) }}</span>
      </header>
      <div class="ek-spot-tabs" role="tablist" :aria-label="t('enterpriseKnowledge.spot.title')">
        <button v-for="item in tabs" :id="`${regionId}-${item.key}`" :key="item.key" type="button" role="tab" :data-spot-tab="item.key"
          :aria-selected="tab === item.key" :aria-controls="regionId" :tabindex="tab === item.key ? 0 : -1"
          @click="switchTab(item.key)" @keydown="moveTab">{{ item.title }}</button>
      </div>
      <div :id="regionId" role="tabpanel" :aria-labelledby="`${regionId}-${tab}`">
        <p v-if="state === 'loading'" class="ek-status" role="status">{{ t('enterpriseKnowledge.loading') }}</p>
        <div v-else-if="state === 'failed'" class="ek-alert" role="alert">
          <span>{{ t('enterpriseKnowledge.spot.loadFailed') }}</span><button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button>
        </div>
        <p v-else-if="!samples.length" class="ek-empty">{{ tab === 'pending' ? t('enterpriseKnowledge.spot.emptyPending') : t('enterpriseKnowledge.spot.emptyDecided') }}</p>
        <section v-for="group in groups" v-else :key="group.id" class="ek-spot-release" :data-spot-release="group.id">
          <div class="ek-spot-release__heading">
            <h2>{{ group.release ? t('enterpriseKnowledge.space.version', { epoch: group.release.epoch }) : t('enterpriseKnowledge.spot.historicalRelease') }}</h2>
            <span class="ek-page__meta">{{ t('enterpriseKnowledge.spot.count', { count: group.items.length }) }}</span>
          </div>
          <p v-if="group.state === 'loading'" role="status" class="ek-page__meta">{{ t('enterpriseKnowledge.spot.releaseLoading') }}</p>
          <div v-if="group.state === 'failed'" role="alert" class="ek-alert">
            <span>{{ t('enterpriseKnowledge.spot.releaseFailed') }}</span>
            <button type="button" class="ek-button" @click="loadRelease(group.id)">{{ t('enterpriseKnowledge.retry') }}</button>
          </div>
          <SpotCheckCard v-for="sample in group.items" :key="sample.id" :sample="sample" :release="group.release"
            :loading="group.state === 'loading'" :draft="draft(sample.id)" @note="draft(sample.id).note = $event"
            @decide="submit(sample, $event)" @source="openSource(sample, $event)" />
        </section>
      </div>
    </div>
    <Drawer v-if="source" :visible="true" size="min(640px, 100vw)" :footer="false" destroy-on-close
      :header="t('enterpriseKnowledge.entity.source', { n: (source?.evidence ?? 0) + 1 })" @close="closeSource">
      <CitationPanel v-if="source" :space-id="source.spaceId" :release-id="source.releaseId" :member="source.member" :evidence="source.evidence" />
    </Drawer>
  </main>
</template>

<style src="./enterprisePage.css"></style>
<style src="./spotChecks.css"></style>
