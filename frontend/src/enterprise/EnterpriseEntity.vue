<script setup lang="ts">
import { computed, inject, nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { isNavigationFailure, NavigationFailureType, routeLocationKey, routerKey } from 'vue-router'
import CitationPanel from './CitationPanel.vue'
import EnterpriseField from './EnterpriseField.vue'
import EnterpriseNavigation from './EnterpriseNavigation.vue'
import { conceptKeys } from './conceptView'
import { readRelease, type Release } from './enterpriseApi'
import { entityView } from './releaseView'

const props = defineProps<{ spaceId: string; entityId: string; releaseId?: string }>()
const { t } = useI18n()
const state = ref<'loading' | 'failed' | 'ready'>('loading')
// Every citation of this page is read from this release, never from whatever is active later.
const release = ref<Release | null>(null)
const view = computed(() => (release.value ? entityView(release.value, props.entityId) : null))
const selected = ref<{ member: string; evidence: number } | null>(null)
const root = ref<HTMLElement | null>(null)
const route = inject(routeLocationKey, undefined)
const router = inject(routerKey, undefined)
const concepts = computed(() => new Set(release.value ? conceptKeys(release.value) : []))
const fieldKeys = computed(() => new Map((release.value?.members ?? [])
  .filter(member => member.kind === 'claim' && typeof member.payload?.predicate === 'string')
  .map(member => [member.logical_slug, member.payload.predicate as string])))
const anchors = computed(() => {
  const ids = new Map<string, string>()
  const seen = new Set<string>()
  if (!view.value) return ids
  const fields = [...view.value.sections.flatMap(section => section.fields), ...view.value.other, ...view.value.generated]
  for (const field of fields) {
    const key = fieldKeys.value.get(field.slug) || field.slug
    // Several applicability claims can share a field: its stable anchor targets the first one.
    ids.set(field.slug, seen.has(key) ? `${key}--${encodeURIComponent(field.slug)}` : key)
    seen.add(key)
  }
  return ids
})
function conceptRoute(slug: string) {
  const key = fieldKeys.value.get(slug)
  return key && concepts.value.has(key) && release.value
    ? { name: 'enterpriseConcept', params: { spaceId: props.spaceId, conceptKey: key }, query: { release: release.value.id } }
    : undefined
}
let generation = 0

async function load() {
  const current = ++generation
  state.value = 'loading'
  selected.value = null
  release.value = null
  try {
    const read = props.releaseId ? await readRelease(props.spaceId, props.releaseId) : await readRelease(props.spaceId)
    if (current !== generation) return
    release.value = read
    state.value = 'ready'
  } catch {
    if (current === generation) state.value = 'failed'
  }
}

function open(member: string, evidence: number) {
  selected.value = { member, evidence }
}

watch(() => [props.spaceId, props.releaseId], load, { immediate: true })
// The page is reused across entries of one release: a citation opened for the previous entry
// must not stay open for the next one.
watch(() => props.entityId, () => { selected.value = null })
async function scrollToField() {
  await nextTick()
  if (state.value !== 'ready' || !route?.hash) return
  let id = route.hash.slice(1)
  try { id = decodeURIComponent(id) } catch { /* A literal percent in a field key stays literal. */ }
  const target = Array.from(root.value?.querySelectorAll<HTMLElement>('.ek-field[id]') ?? []).find(field => field.id === id)
  target?.scrollIntoView({ block: 'start' })
  target?.focus({ preventScroll: true })
}
watch(() => [state.value, view.value, route?.hash], scrollToField, { flush: 'post' })
// Selecting the same field again leaves the route unchanged, so its watcher cannot scroll.
const removeNavigationHook = router?.afterEach((_to, _from, failure) => {
  if (isNavigationFailure(failure, NavigationFailureType.duplicated)) void scrollToField()
})
onUnmounted(() => { generation++; removeNavigationHook?.() })
</script>

<template>
  <main ref="root" class="ek-page">
    <RouterLink class="ek-back" :to="{ name: 'enterpriseSpace', params: { spaceId }, query: { release: release?.id || releaseId } }">{{ spaceId }}</RouterLink>
    <p v-if="state === 'loading'" role="status" class="ek-status">{{ t('enterpriseKnowledge.loading') }}</p>
    <div v-else-if="state === 'failed'" role="alert" class="ek-alert">
      <span>{{ t('enterpriseKnowledge.entity.failed') }}</span>
      <button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button>
    </div>
    <p v-else-if="!view" class="ek-empty">{{ t('enterpriseKnowledge.entity.notFound') }}</p>
    <template v-else-if="release">
      <div class="ek-layout">
        <EnterpriseNavigation :release="release" :space-id="spaceId" :entity-id="entityId" />
        <article class="ek-layout__content">
          <h1 class="ek-page__title">{{ view.name }}</h1>
          <p class="ek-page__meta">{{ t('enterpriseKnowledge.space.version', { epoch: release.epoch }) }}</p>
          <p class="ek-page__note" data-source-note>{{ t('enterpriseKnowledge.entity.sourceNote') }}</p>
          <section v-for="section in view.sections" :key="section.key" class="ek-section" :data-section="section.key">
            <h2 class="ek-section__title">{{ section.title }}</h2>
            <EnterpriseField
              v-for="field in section.fields"
              :key="field.slug"
              :field="field"
              :anchor-id="anchors.get(field.slug)"
              :concept-route="conceptRoute(field.slug)"
              @open="evidence => open(field.slug, evidence)"
            />
          </section>
          <section v-if="view.other.length" class="ek-section" data-other>
            <h2 class="ek-section__title">{{ t('enterpriseKnowledge.entity.other') }}</h2>
            <EnterpriseField
              v-for="field in view.other"
              :key="field.slug"
              :field="field"
              :anchor-id="anchors.get(field.slug)"
              :concept-route="conceptRoute(field.slug)"
              @open="evidence => open(field.slug, evidence)"
            />
          </section>
          <section v-if="view.generated.length" class="ek-section ek-section--generated" data-generated>
            <h2 class="ek-section__title">{{ t('enterpriseKnowledge.entity.generated') }}</h2>
            <EnterpriseField
              v-for="field in view.generated"
              :key="field.slug"
              :field="field"
              :anchor-id="anchors.get(field.slug)"
              :concept-route="conceptRoute(field.slug)"
              @open="evidence => open(field.slug, evidence)"
            />
          </section>
          <t-drawer
            :visible="selected !== null"
            size="640px"
            :footer="false"
            :header="t('enterpriseKnowledge.entity.source', { n: (selected?.evidence ?? 0) + 1 })"
            destroy-on-close
            @close="selected = null"
          >
            <CitationPanel
              v-if="selected"
              :space-id="spaceId"
              :release-id="release.id"
              :member="selected.member"
              :evidence="selected.evidence"
            />
          </t-drawer>
        </article>
      </div>
    </template>
  </main>
</template>

<style src="./enterprisePage.css"></style>
