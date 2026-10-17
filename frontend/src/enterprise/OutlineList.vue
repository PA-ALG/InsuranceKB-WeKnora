<script setup lang="ts">
import { computed } from 'vue'
import type { OutlineItem } from './valueOutline'

// `collapsible` items open and close one by one; `open` is the field-wide full version.
const props = defineProps<{ items: OutlineItem[]; collapsible: boolean; open: boolean }>()

// A folded item shows its named term, or else its text cut to one line, so the reader knows what
// it is. An item this short is shown whole and never folded, and a level made mostly of such items
// (a list of disease names, say) flows as one wrapped paragraph instead of one line each.
const SHORT_CHARS = 40
const FLOW_MIN = 6
const FLOW_SHARE = 0.8

function short(item: OutlineItem): boolean {
  return item.children.length === 0 && (item.lead + item.body).length <= SHORT_CHARS
}

const flowing = computed(
  () =>
    props.items.length >= FLOW_MIN &&
    props.items.every(item => item.children.length === 0) &&
    props.items.filter(short).length >= FLOW_SHARE * props.items.length,
)

function folded(item: OutlineItem): boolean {
  return props.collapsible && !flowing.value && !short(item)
}
</script>

<template>
  <ol :class="['ek-outline', { 'ek-outline--flow': flowing }]">
    <li
      v-for="(item, index) in items"
      :key="index"
      :class="['ek-outline__item', { 'ek-outline__item--plain': collapsible && !flowing && !folded(item) }]"
      :data-item="folded(item) ? undefined : ''"
    >
      <details v-if="folded(item)" data-item class="ek-outline__details" :open="open">
        <summary class="ek-outline__summary">
          <span v-if="item.marker" class="ek-outline__marker">{{ item.marker }}</span>
          <strong v-if="item.lead" class="ek-outline__lead">{{ item.lead }}</strong>
          <span v-else class="ek-outline__body ek-outline__line">{{ item.body }}</span>
        </summary>
        <div v-if="(item.lead && item.body) || item.children.length" class="ek-outline__content">
          <span v-if="item.lead && item.body" class="ek-outline__body">{{ item.body }}</span>
          <OutlineList v-if="item.children.length" :items="item.children" :collapsible="collapsible" :open="open" />
        </div>
      </details>
      <template v-else>
        <span v-if="item.marker" class="ek-outline__marker">{{ item.marker }}</span>
        <strong v-if="item.lead" class="ek-outline__lead">{{ item.lead }}</strong>
        <span v-if="item.body" class="ek-outline__body">{{ item.body }}</span>
        <OutlineList v-if="item.children.length" :items="item.children" :collapsible="false" :open="open" />
      </template>
    </li>
  </ol>
</template>
