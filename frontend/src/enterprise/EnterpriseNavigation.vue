<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Release } from './enterpriseApi'
import { navigationTree } from './navigationView'
import { conceptKeys, conceptView } from './conceptView'
import NavigationEntry from './NavigationEntry.vue'

const props = defineProps<{ release: Release; spaceId: string; entityId?: string; conceptKey?: string }>()
const { t } = useI18n()
const tree = computed(() => navigationTree(props.release))
const concepts = computed(() => conceptKeys(props.release).map(key => conceptView(props.release, key)!))
const categories = computed(() => {
  const groups = new Map<string, typeof concepts.value>()
  for (const concept of concepts.value) {
    if (!groups.has(concept.category)) groups.set(concept.category, [])
    groups.get(concept.category)!.push(concept)
  }
  return [...groups].map(([title, entries]) => ({ title, entries }))
})
const selected = ref(0)
const mobileOpen = ref(false)
const id = useId()
const tabs = computed(() => [...tree.value.map(domain => domain.title || t(domain.key ? 'enterpriseKnowledge.nav.other' : 'enterpriseKnowledge.title')), t('enterpriseKnowledge.nav.concepts')])
watch(() => [props.release, props.entityId, props.conceptKey], () => {
  const index = tree.value.findIndex(domain => domain.groups.some(group => group.entries.some(entry => entry.entityId === props.entityId)))
  selected.value = props.conceptKey ? tree.value.length : Math.max(index, 0)
  mobileOpen.value = false
}, { immediate: true })
function keydown(event: KeyboardEvent, index: number) {
  let next = index
  if (event.key === 'ArrowRight') next = (index + 1) % tabs.value.length
  else if (event.key === 'ArrowLeft') next = (index + tabs.value.length - 1) % tabs.value.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = tabs.value.length - 1
  else return
  event.preventDefault()
  selected.value = next
  const buttons = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
  buttons?.[next]?.focus()
}
</script>

<template>
  <nav :class="['ek-navigation', { 'ek-navigation--open': mobileOpen }]" :aria-label="t('enterpriseKnowledge.nav.navigation')">
    <button type="button" class="ek-button ek-navigation__toggle" :aria-expanded="mobileOpen" :aria-controls="id" @click="mobileOpen = !mobileOpen">
      {{ t('enterpriseKnowledge.nav.navigation') }} <span aria-hidden="true">{{ mobileOpen ? '▴' : '▾' }}</span>
    </button>
    <div :id="id" class="ek-navigation__body">
      <div role="tablist" :aria-label="t('enterpriseKnowledge.nav.navigation')" class="ek-nav-tabs">
        <button v-for="(title, index) in tabs" :id="`${id}-tab-${index}`" :key="index" type="button" role="tab"
          :data-nav-domain="index < tree.length && tree[index]?.key ? '' : undefined"
          :aria-selected="selected === index" :aria-controls="`${id}-panel-${index}`" :tabindex="selected === index ? 0 : -1"
          @click="selected = index" @keydown="keydown($event, index)">{{ title }}</button>
      </div>
      <div v-for="(domain, index) in tree" v-show="selected === index" :id="`${id}-panel-${index}`" :key="domain.key"
        role="tabpanel" :aria-labelledby="`${id}-tab-${index}`">
        <section v-for="group in domain.groups" :key="group.key" class="ek-nav-group">
          <h2 v-if="group.key" data-nav-group>{{ group.title || t('enterpriseKnowledge.nav.other') }} <small>{{ group.entries.length }}</small></h2>
          <ul>
            <NavigationEntry v-for="entry in group.entries" :key="entry.entityId" :entry="entry" :release="release" :space-id="spaceId" :selected="entry.entityId === entityId" />
          </ul>
        </section>
      </div>
      <div v-show="selected === tree.length" :id="`${id}-panel-${tree.length}`" role="tabpanel" :aria-labelledby="`${id}-tab-${tree.length}`">
        <section v-for="category in categories" :key="category.title" class="ek-nav-group">
          <h2>{{ category.title || t('enterpriseKnowledge.nav.other') }}</h2>
          <ul>
            <li v-for="concept in category.entries" :key="concept.key" data-nav-concept>
              <RouterLink :to="{ name: 'enterpriseConcept', params: { spaceId, conceptKey: concept.key }, query: { release: release.id } }"
                :aria-current="concept.key === conceptKey ? 'page' : undefined">{{ concept.title }}</RouterLink>
            </li>
          </ul>
        </section>
        <p v-if="!concepts.length" class="ek-empty">{{ t('enterpriseKnowledge.nav.noConcepts') }}</p>
      </div>
    </div>
  </nav>
</template>
