// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReleaseCustodyGate from './ReleaseCustodyGate.vue'

describe('knowledge base release custody tabs', () => {
  const slots = { default: '<button>材料 Wiki</button><button>图谱</button>' }
  it('shows the exact managed notice and hides both native tabs', () => {
    const view = mount(ReleaseCustodyGate, { props: { managed: true, nativeAllowed: false }, slots })
    expect(view.text()).toBe('该知识库由发布链管理，内容以发布版本为准')
    expect(view.findAll('button')).toHaveLength(0)
  })
  it('shows both native tabs for unmanaged knowledge bases', () => {
    const view = mount(ReleaseCustodyGate, { props: { managed: false, nativeAllowed: true }, slots })
    expect(view.findAll('button').map(button => button.text())).toEqual(['材料 Wiki', '图谱'])
  })
  it('keeps native tabs hidden while loading and emits retry from an accessible error', async () => {
    const view = mount(ReleaseCustodyGate, { props: { managed: false, nativeAllowed: false, loading: true }, slots })
    expect(view.find('[role="status"]').exists()).toBe(true)
    expect(view.text()).not.toContain('材料 Wiki'); expect(view.text()).not.toContain('图谱')
    await view.setProps({ loading: false, error: '无法确认知识库发布状态，请重试' })
    expect(view.find('[role="alert"]').text()).toContain('无法确认知识库发布状态，请重试')
    await view.get('button').trigger('click'); expect(view.emitted('retry')).toHaveLength(1)
  })
})
