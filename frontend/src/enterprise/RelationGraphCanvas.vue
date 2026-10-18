<script setup lang="ts">
// SVG gestures and force layout adapted from WeKnora WikiBrowser.vue (MIT).
// Rendering and lifecycle are owned here; all graph data comes from one enterprise Release.
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { GraphNode, RelationGraph } from './graphView'
import { nodeRadius, seedLayout, stepLayout, type PositionedNode } from './graphLayout'

const props = defineProps<{ graph: RelationGraph; colors: Map<string, string>; selected?: string }>()
const emit = defineEmits<{ select: [node: GraphNode] }>()
const { t } = useI18n()
const svg = ref<SVGSVGElement>()
const nodes = ref<PositionedNode[]>([])
const width = ref(1000), height = ref(620)
const scale = ref(1), pan = ref({ x: 500, y: 310 })
const hovered = ref(''), focused = ref('')
const active = computed(() => hovered.value || focused.value || props.selected || '')
const neighbors = computed(() => new Set([active.value, ...props.graph.edges.flatMap(edge =>
  edge.source === active.value ? [edge.target] : edge.target === active.value ? [edge.source] : [])]))
const byId = computed(() => new Map(nodes.value.map(node => [node.id, node])))
const edges = computed(() => props.graph.edges.flatMap(edge => {
  const source = byId.value.get(edge.source), target = byId.value.get(edge.target)
  return source && target ? [{ source, target }] : []
}))
const maxDegree = computed(() => Math.max(1, ...nodes.value.map(node => node.degree)))
const color = (node: GraphNode) => node.kind === 'concept' ? 'var(--td-text-color-secondary)' : props.colors.get(node.group)
const labelScale = computed(() => Math.min(1, scale.value))
const labelVisible = (node: GraphNode) => node.id === active.value || node.id === props.selected || scale.value >= 0.75
  || (node.degree > 0 && node.degree >= maxDegree.value * (scale.value < 0.45 ? 0.8 : 0.5))
const shortTitle = (title: string) => Array.from(title).length > 18 ? Array.from(title).slice(0, 18).join('') + '…' : title
const interacted = ref(false)
let animation = 0, observer: ResizeObserver | undefined

function fit() {
  if (!nodes.value.length) return
  const xs = nodes.value.map(node => node.x), ys = nodes.value.map(node => node.y)
  const left = Math.min(...xs) - 120, right = Math.max(...xs) + 120
  const top = Math.min(...ys) - 55, bottom = Math.max(...ys) + 70
  scale.value = Math.max(0.08, Math.min(1.5, width.value / (right - left), height.value / (bottom - top)))
  pan.value = { x: width.value / 2 - (left + right) / 2 * scale.value, y: height.value / 2 - (top + bottom) / 2 * scale.value }
}
function zoom(factor: number, x = width.value / 2, y = height.value / 2) {
  interacted.value = true
  const next = Math.max(0.08, Math.min(5, scale.value * factor))
  pan.value = { x: x - (x - pan.value.x) * next / scale.value, y: y - (y - pan.value.y) * next / scale.value }
  scale.value = next
}
function focusNode(id: string) {
  const element = [...(svg.value?.querySelectorAll<SVGGElement>('[data-graph-node]') ?? [])]
    .find(element => element.dataset.graphNode === id)
  element?.focus()
}
function locateNode(id: string) {
  const node = byId.value.get(id)
  if (!node) return
  interacted.value = true
  scale.value = Math.max(0.9, scale.value)
  pan.value = { x: width.value / 2 - node.x * scale.value, y: height.value / 2 - node.y * scale.value }
}
defineExpose({ focusNode, locateNode })

function point(event: MouseEvent) {
  const rect = svg.value?.getBoundingClientRect()
  return { x: rect?.width ? (event.clientX - rect.left) * width.value / rect.width : event.clientX,
    y: rect?.height ? (event.clientY - rect.top) * height.value / rect.height : event.clientY }
}
let drag: { pointer: number; start: { x: number; y: number }; origin: { x: number; y: number }; node?: PositionedNode; moved: boolean } | null = null
let suppressClick = false
function startDrag(event: PointerEvent, node?: PositionedNode) {
  if (event.button !== 0) return
  event.stopPropagation()
  interacted.value = true
  suppressClick = false
  const start = point(event)
  drag = { pointer: event.pointerId, start, origin: node ? { x: node.x, y: node.y } : { ...pan.value }, node, moved: false }
  if (node) { node.pinned = true; node.vx = 0; node.vy = 0 }
  svg.value?.setPointerCapture?.(event.pointerId)
}
function moveDrag(event: PointerEvent) {
  if (!drag || event.pointerId !== drag.pointer) return
  const current = point(event), dx = current.x - drag.start.x, dy = current.y - drag.start.y
  if (Math.hypot(dx, dy) > 4) drag.moved = true
  if (drag.node) {
    drag.node.x = drag.origin.x + dx / scale.value
    drag.node.y = drag.origin.y + dy / scale.value
  } else pan.value = { x: drag.origin.x + dx, y: drag.origin.y + dy }
}
function endDrag(event: PointerEvent) {
  if (!drag || event.pointerId !== drag.pointer) return
  suppressClick = drag.moved
  // Capture belongs to SVG so a click after a node press is dispatched there in browsers.
  const clicked = !drag.moved && event.type === 'pointerup' ? drag.node : undefined
  drag = null
  if (svg.value?.hasPointerCapture?.(event.pointerId)) svg.value.releasePointerCapture(event.pointerId)
  if (clicked) { suppressClick = true; emit('select', clicked) }
}
function select(node: GraphNode) {
  if (suppressClick) { suppressClick = false; return }
  emit('select', node)
}
function wheel(event: WheelEvent) {
  const cursor = point(event)
  zoom(event.deltaY > 0 ? 0.9 : 1.1, cursor.x, cursor.y)
}
watch(() => props.graph, graph => {
  cancelAnimationFrame(animation)
  drag = null
  hovered.value = ''; focused.value = ''; interacted.value = false
  nodes.value = seedLayout(graph)
  for (let tick = 0; tick < 40; tick++) stepLayout(nodes.value, graph, 1 - tick / 80)
  fit()
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
  let tick = 40
  const animate = () => {
    for (let step = 0; step < 3; step++, tick++) stepLayout(nodes.value, graph, Math.max(0.03, 1 - tick / 100))
    if (!interacted.value) fit()
    if (tick < 100) animation = requestAnimationFrame(animate)
  }
  if (nodes.value.length) animation = requestAnimationFrame(animate)
}, { immediate: true })
onMounted(() => {
  observer = new ResizeObserver(entries => {
    const rect = entries[0]?.contentRect
    if (!rect?.width || !rect.height) return
    width.value = rect.width; height.value = rect.height
    fit()
  })
  if (svg.value) observer.observe(svg.value)
})
onUnmounted(() => { cancelAnimationFrame(animation); observer?.disconnect(); drag = null })
</script>

<template>
  <div class="ek-graph-canvas">
    <svg ref="svg" :viewBox="`0 0 ${width} ${height}`" role="group" :aria-label="t('enterpriseKnowledge.graph.canvas')"
      @wheel.prevent="wheel" @pointerdown="startDrag($event)" @pointermove="moveDrag" @pointerup="endDrag"
      @pointercancel="endDrag" @lostpointercapture="endDrag">
      <g data-graph-transform :transform="`translate(${pan.x},${pan.y}) scale(${scale})`">
        <g class="ek-graph-edges" aria-hidden="true">
          <line v-for="edge in edges" :key="JSON.stringify([edge.source.id, edge.target.id])" data-graph-edge
            :x1="edge.source.x" :y1="edge.source.y" :x2="edge.target.x" :y2="edge.target.y"
            :class="{ 'ek-graph-edge--active': active === edge.source.id || active === edge.target.id,
              'ek-graph-edge--muted': active && active !== edge.source.id && active !== edge.target.id }" />
        </g>
        <g v-for="node in nodes" :key="node.id" :data-graph-node="node.id" class="ek-graph-node"
          :class="{ 'ek-graph-node--muted': active && !neighbors.has(node.id), 'ek-graph-node--selected': selected === node.id }"
          :style="{ '--node-color': color(node) }" :transform="`translate(${node.x},${node.y})`" tabindex="0" role="button"
          :aria-label="`${node.title} · ${node.kind === 'product' ? t('enterpriseKnowledge.concept.columns.product') : t('enterpriseKnowledge.graph.concept')}`"
          :aria-pressed="selected === node.id" @click.stop="select(node)" @keydown.enter.prevent="emit('select', node)"
          @keydown.space.prevent="emit('select', node)" @focus="focused = node.id" @blur="focused = ''"
          @mouseenter="hovered = node.id" @mouseleave="hovered = ''" @pointerdown="startDrag($event, node)">
          <title>{{ node.title }}</title>
          <circle class="ek-graph-node__ring" :r="nodeRadius(node) + 6" />
          <circle v-if="node.kind === 'product'" class="ek-graph-node__shape" :r="nodeRadius(node)" />
          <rect v-else class="ek-graph-node__shape ek-graph-node__concept" :x="-nodeRadius(node)" :y="-nodeRadius(node)"
            :width="nodeRadius(node) * 2" :height="nodeRadius(node) * 2" rx="5" />
          <text :y="nodeRadius(node) + 23 / labelScale" :style="{ fontSize: `${13 / labelScale}px` }" text-anchor="middle"
            :opacity="labelVisible(node) ? 1 : 0" aria-hidden="true">{{ shortTitle(node.title) }}</text>
        </g>
      </g>
    </svg>
    <div class="ek-graph-controls">
      <button type="button" class="ek-button" data-graph-zoom-out :aria-label="t('enterpriseKnowledge.graph.zoomOut')" @click="zoom(0.8)">−</button>
      <span>{{ Math.round(scale * 100) }}%</span>
      <button type="button" class="ek-button" data-graph-zoom-in :aria-label="t('enterpriseKnowledge.graph.zoomIn')" @click="zoom(1.25)">+</button>
      <button type="button" class="ek-button" data-graph-fit @click="interacted = true; fit()">{{ t('enterpriseKnowledge.graph.fit') }}</button>
    </div>
  </div>
</template>
