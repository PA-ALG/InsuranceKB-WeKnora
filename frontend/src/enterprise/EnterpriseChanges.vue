<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Drawer } from 'tdesign-vue-next'
import CitationPanel from './CitationPanel.vue'
import EnterpriseField from './EnterpriseField.vue'
import { readRelease, type Release } from './enterpriseApi'
import { orderedEntityIds, previousReleaseId, releaseChanges } from './releaseChanges'

const props = defineProps<{ spaceId: string; releaseId?: string }>()
const { t } = useI18n(), anchor = useId()
const state = ref<'loading' | 'failed' | 'ready'>('loading')
const current = ref<Release | null>(null), base = ref<Release | null>(null)
const changes = computed(() => current.value ? releaseChanges(current.value, base.value) : null)
const groups = computed(() => {
  if (!changes.value || !current.value || !base.value) return []
  const rows = [
    ...changes.value.added.map(row => ({ ...row, kind: 'added', label: t('enterpriseKnowledge.changes.added') })),
    ...changes.value.changed.map(row => ({ ...row, kind: 'changed', label: t('enterpriseKnowledge.changes.changed') })),
    ...changes.value.removed.map(row => ({ ...row, kind: 'removed', label: t('enterpriseKnowledge.changes.removed') })),
  ]
  return [...new Set([...orderedEntityIds(current.value), ...orderedEntityIds(base.value)])].flatMap(entityId => {
    const entries = rows.filter(row => row.entityId === entityId)
    return entries.length ? [{ entityId, name: entries[0]!.name, rows: entries }] : []
  })
})
const source = ref<{ spaceId: string; releaseId: string; member: string; evidence: number } | null>(null)
let sourceButton: HTMLElement | null = null, generation = 0
function open(releaseId: string, member: string, evidence: number) {
  sourceButton = document.activeElement instanceof HTMLElement ? document.activeElement : null
  source.value = { spaceId: props.spaceId, releaseId, member, evidence }
}
async function close() {
  source.value = null
  await nextTick()
  if (sourceButton?.isConnected) sourceButton.focus()
}
async function load() {
  const request = ++generation, space = props.spaceId, requestedId = props.releaseId
  state.value = 'loading'; source.value = null; base.value = null
  try {
    // A failed base read retries against the already-resolved current release.
    const release = current.value ?? await (requestedId ? readRelease(space, requestedId) : readRelease(space))
    if (request !== generation) return
    if (requestedId && requestedId !== 'active' && release.id !== requestedId) throw new Error('INVALID_RELEASE')
    current.value = release
    const id = previousReleaseId(release)
    if (id) {
      const previous = await readRelease(space, id)
      if (request !== generation) return
      if (previous.id !== id) throw new Error('INVALID_BASE_RELEASE')
      base.value = previous
    }
    state.value = 'ready'
  } catch { if (request === generation) state.value = 'failed' }
}
watch(() => [props.spaceId, props.releaseId], () => { current.value = null; sourceButton = null; void load() }, { immediate: true })
onUnmounted(() => { generation++ })
</script>

<template>
  <main class="ek-page ek-changes-page">
    <div class="ek-changes-shell">
      <RouterLink class="ek-back" :to="{ name: 'enterpriseSpace', params: { spaceId }, query: { release: current?.id || releaseId } }">← {{ t('enterpriseKnowledge.graph.back') }}</RouterLink>
      <h1 class="ek-page__title">{{ current && base ? t('enterpriseKnowledge.changes.title', { current: current.epoch, base: base.epoch }) : t('enterpriseKnowledge.changes.pageTitle') }}</h1>
      <p v-if="state === 'loading'" class="ek-status" role="status">{{ t('enterpriseKnowledge.loading') }}</p>
      <div v-else-if="state === 'failed'" class="ek-alert" role="alert"><span>{{ t('enterpriseKnowledge.changes.failed') }}</span><button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button></div>
      <p v-else-if="!base" class="ek-empty">{{ t('enterpriseKnowledge.changes.firstRelease') }}</p>
      <template v-else-if="current && changes">
        <p class="ek-page__meta">{{ t('enterpriseKnowledge.changes.summary', { added: changes.added.length, changed: changes.changed.length, removed: changes.removed.length }) }}</p>
        <p v-if="!groups.length" class="ek-empty">{{ t('enterpriseKnowledge.changes.noFields', { count: changes.otherChanged }) }}</p>
        <section v-for="group in groups" :key="group.entityId" :data-change-entity="group.entityId" class="ek-changes-group">
          <h2>{{ group.name }}</h2>
          <article v-for="row in group.rows" :key="row.slug" :data-change="row.slug" class="ek-change">
            <header class="ek-change__heading"><span class="ek-change__kind" :class="`ek-change__kind--${row.kind}`">{{ row.label }}</span>
              <RouterLink v-if="row.kind !== 'removed'" :to="{ name: 'enterpriseEntity', params: { spaceId, entityId: row.entityId }, query: { release: current.id }, hash: `#${row.fieldKey}` }">{{ row.fieldTitle }}</RouterLink>
              <span v-else>{{ row.fieldTitle }}</span>
            </header>
            <div class="ek-change__values" :class="{ 'ek-change__values--pair': row.before && row.after }">
              <div v-if="row.before" data-change-before class="ek-change__side">
                <p class="ek-change__version">{{ t('enterpriseKnowledge.changes.before') }}</p>
                <EnterpriseField :field="row.before" :anchor-id="`${anchor}-${encodeURIComponent(row.slug)}-before`" @open="open(base.id, row.slug, $event)" />
              </div>
              <div v-if="row.after" data-change-after class="ek-change__side">
                <p class="ek-change__version">{{ t('enterpriseKnowledge.changes.after') }}</p>
                <EnterpriseField :field="row.after" :anchor-id="`${anchor}-${encodeURIComponent(row.slug)}-after`" @open="open(current.id, row.slug, $event)" />
              </div>
            </div>
          </article>
        </section>
      </template>
    </div>
    <Drawer v-if="source" :visible="true" size="min(640px, 100vw)" :footer="false" destroy-on-close :header="t('enterpriseKnowledge.entity.source', { n: source.evidence + 1 })" @close="close">
      <CitationPanel :space-id="source.spaceId" :release-id="source.releaseId" :member="source.member" :evidence="source.evidence" />
    </Drawer>
  </main>
</template>

<style src="./enterprisePage.css"></style>
<style src="./releaseChanges.css"></style>
