<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import CitationPanel from './CitationPanel.vue'
import EnterpriseField from './EnterpriseField.vue'
import { readRelease, type Release } from './enterpriseApi'
import { entityView } from './releaseView'

const props = defineProps<{ spaceId: string; entityId: string; releaseId?: string }>()
const { t } = useI18n()
const state = ref<'loading' | 'failed' | 'ready'>('loading')
// Every citation of this page is read from this release, never from whatever is active later.
const release = ref<Release | null>(null)
const view = computed(() => (release.value ? entityView(release.value, props.entityId) : null))
const selected = ref<{ member: string; evidence: number } | null>(null)
let generation = 0

async function load() {
  const current = ++generation
  state.value = 'loading'
  selected.value = null
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
</script>

<template>
  <main class="ek-page">
    <RouterLink class="ek-back" :to="{ name: 'enterpriseSpace', params: { spaceId } }">{{ spaceId }}</RouterLink>
    <p v-if="state === 'loading'" role="status" class="ek-status">{{ t('enterpriseKnowledge.loading') }}</p>
    <div v-else-if="state === 'failed'" role="alert" class="ek-alert">
      <span>{{ t('enterpriseKnowledge.entity.failed') }}</span>
      <button type="button" class="ek-button" @click="load">{{ t('enterpriseKnowledge.retry') }}</button>
    </div>
    <p v-else-if="!view" class="ek-empty">{{ t('enterpriseKnowledge.entity.notFound') }}</p>
    <template v-else-if="release">
      <h1 class="ek-page__title">{{ view.name }}</h1>
      <p class="ek-page__meta">{{ t('enterpriseKnowledge.space.version', { epoch: release.epoch }) }}</p>
      <section v-for="section in view.sections" :key="section.key" class="ek-section" :data-section="section.key">
        <h2 class="ek-section__title">{{ section.title }}</h2>
        <EnterpriseField
          v-for="field in section.fields"
          :key="field.slug"
          :field="field"
          @open="evidence => open(field.slug, evidence)"
        />
      </section>
      <section v-if="view.other.length" class="ek-section" data-other>
        <h2 class="ek-section__title">{{ t('enterpriseKnowledge.entity.other') }}</h2>
        <EnterpriseField
          v-for="field in view.other"
          :key="field.slug"
          :field="field"
          @open="evidence => open(field.slug, evidence)"
        />
      </section>
      <section v-if="view.generated.length" class="ek-section ek-section--generated" data-generated>
        <h2 class="ek-section__title">{{ t('enterpriseKnowledge.entity.generated') }}</h2>
        <EnterpriseField
          v-for="field in view.generated"
          :key="field.slug"
          :field="field"
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
    </template>
  </main>
</template>

<style src="./enterprisePage.css"></style>
