<script setup lang="ts">
import { computed, inject, nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { isNavigationFailure, NavigationFailureType, routeLocationKey, routerKey } from 'vue-router'
import CitationPanel from './CitationPanel.vue'
import EnterpriseField from './EnterpriseField.vue'
import EnterpriseNavigation from './EnterpriseNavigation.vue'
import ExpertEditForm from './ExpertEditForm.vue'
import { conceptKeys } from './conceptView'
import { readRelease, type Release } from './enterpriseApi'
import { canOfferExpertEdit } from './expertEditAccess'
import { entityView } from './releaseView'
import { previousReleaseId, releaseChanges } from './releaseChanges'

const props = defineProps<{ spaceId: string; entityId: string; releaseId?: string }>()
const { t } = useI18n()
const state = ref<'loading' | 'failed' | 'ready'>('loading')
// Every citation of this page is read from this release, never from whatever is active later.
const release = ref<Release | null>(null)
const base = ref<Release | null>(null)
const updated = computed(() => {
  const changes = release.value ? releaseChanges(release.value, base.value) : null
  return new Map([...(changes?.added ?? []), ...(changes?.changed ?? [])].map(row => [row.slug, row.before]))
})
const view = computed(() => (release.value ? entityView(release.value, props.entityId) : null))
const selected = ref<{ member: string; evidence: number; releaseId: string } | null>(null)
// S9b: administrators edit a field of the shown release; a published edit switches the page to
// the release it produced and says so until another entry or release is shown.
const canEdit = computed(() => canOfferExpertEdit())
const editing = ref<{ slug: string; title: string } | null>(null)
const published = ref<{ releaseId: string; epoch: number } | null>(null)
const publishedEpoch = computed(() =>
  published.value && release.value?.id === published.value.releaseId ? published.value.epoch : null)
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

async function loadBase(current: Release, request: number) {
  try {
    const id = previousReleaseId(current)
    if (!id) return
    const previous = await readRelease(props.spaceId, id)
    if (request === generation && previous.id === id) base.value = previous
  } catch { /* Current fields remain readable when the comparison is unavailable. */ }
}

let loadedSpace: string | undefined
async function load() {
  // Pinning the release already on screen must preserve its DOM and navigation.
  if (state.value === 'ready' && loadedSpace === props.spaceId && props.releaseId === release.value?.id) return
  const current = ++generation, space = props.spaceId
  state.value = 'loading'
  selected.value = null
  editing.value = null
  if (published.value && published.value.releaseId !== props.releaseId) published.value = null
  release.value = null
  base.value = null
  try {
    const read = props.releaseId ? await readRelease(space, props.releaseId) : await readRelease(space)
    if (current !== generation) return
    release.value = read
    loadedSpace = space
    state.value = 'ready'
    void loadBase(read, current)
  } catch {
    if (current === generation) state.value = 'failed'
  }
}

function open(member: string, evidence: number) {
  editing.value = null
  if (release.value) selected.value = { member, evidence, releaseId: release.value.id }
}
function startEdit(slug: string, title: string) {
  selected.value = null
  editing.value = { slug, title }
}
function showPublished(result: { releaseId: string; epoch: number }) {
  editing.value = null
  published.value = result
  void router?.replace({ query: { ...route?.query, release: result.releaseId }, hash: route?.hash })
}
function showActive() {
  editing.value = null
  published.value = null
  // Without a router (embedded) the drawer only closes (S9b Spec §2.4).
  if (!router) return
  // Already on the Active route: dropping the pin would be a duplicate navigation that reads
  // nothing, so read the Active release again here.
  if (props.releaseId === undefined) {
    void load()
    return
  }
  const { release: _pinned, ...query } = route?.query ?? {}
  void router.replace({ query, hash: route?.hash })
}
function openPrevious(member: string, evidence: number) {
  if (base.value) selected.value = { member, evidence, releaseId: base.value.id }
}

watch(() => [props.spaceId, props.releaseId], load, { immediate: true })
// The page is reused across entries of one release: a citation opened for the previous entry
// must not stay open for the next one.
watch(() => props.entityId, () => { selected.value = null; editing.value = null; published.value = null })
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
          <p class="ek-page__meta ek-entity-meta" data-entity-meta>
            <span v-if="view.profileName" class="ek-meta-tag">{{ view.profileName }}</span>
            <span class="ek-meta-tag">{{ t('enterpriseKnowledge.space.version', { epoch: release.epoch }) }}</span>
          </p>
          <p v-if="publishedEpoch !== null" role="status" data-expert-notice class="ek-status">
            {{ t('enterpriseKnowledge.expert.published', { epoch: publishedEpoch }) }}
          </p>
          <p class="ek-page__note" data-source-note>{{ t('enterpriseKnowledge.entity.sourceNote') }}</p>
          <section v-for="section in view.sections" :key="section.key" class="ek-section" :data-section="section.key">
            <h2 class="ek-section__title">{{ section.title }}</h2>
            <EnterpriseField
              v-for="field in section.fields"
              :key="field.slug"
              :field="field"
              :anchor-id="anchors.get(field.slug)"
              :concept-route="conceptRoute(field.slug)"
              :previous="updated.get(field.slug)"
              @open-previous="evidence => openPrevious(field.slug, evidence)"
              :editable="canEdit"
              @edit="startEdit(field.slug, field.title)"
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
              :previous="updated.get(field.slug)"
              @open-previous="evidence => openPrevious(field.slug, evidence)"
              :editable="canEdit"
              @edit="startEdit(field.slug, field.title)"
              @open="evidence => open(field.slug, evidence)"
            />
          </section>
          <section v-if="view.generated.length" class="ek-section" data-generated>
            <h2 class="ek-section__title">{{ t('enterpriseKnowledge.entity.generated') }}</h2>
            <EnterpriseField
              v-for="field in view.generated"
              :key="field.slug"
              :field="field"
              :anchor-id="anchors.get(field.slug)"
              :concept-route="conceptRoute(field.slug)"
              :previous="updated.get(field.slug)"
              @open-previous="evidence => openPrevious(field.slug, evidence)"
              :editable="canEdit"
              @edit="startEdit(field.slug, field.title)"
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
              :release-id="selected.releaseId"
              :member="selected.member"
              :evidence="selected.evidence"
            />
          </t-drawer>
          <t-drawer
            :visible="editing !== null"
            size="640px"
            :footer="false"
            :header="t('enterpriseKnowledge.expert.editTitle', { title: editing?.title ?? '' })"
            destroy-on-close
            @close="editing = null"
          >
            <ExpertEditForm
              v-if="editing"
              :space-id="spaceId"
              :release="release"
              :slug="editing.slug"
              :title="editing.title"
              @published="showPublished"
              @reload="showActive"
              @cancel="editing = null"
            />
          </t-drawer>
        </article>
      </div>
    </template>
  </main>
</template>

<style src="./enterprisePage.css"></style>
<style src="./releaseChanges.css"></style>
