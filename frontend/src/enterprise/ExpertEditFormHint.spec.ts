// @vitest-environment happy-dom
// S9c acceptance (protected, written by Claude): when "保存并发布" cannot be used the form says what
// is still missing, one condition at a time, and the value and reason labels say what goes where
// (Spec docs/design/slices/S9c-专家编辑表单说明不能保存的原因.md §2). RED until S9c.
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

import ExpertEditForm from './ExpertEditForm.vue'
import type { Release } from './enterpriseApi'

function claim(slug: string, state: string, value: unknown) {
  return {
    kind: 'claim', logical_slug: slug, member_digest: 'd'.repeat(64), access_scope: 'space',
    payload: { subject_ref: 'P1', predicate: slug.split('/')[1], state, value, origin: 'SOURCE_SUPPORTED', evidence: [] },
  }
}

const release: Release = {
  id: 'rel-1', epoch: 1,
  members: [claim('P1/f_wait', 'present', '90日'), claim('P1/f_slogan', 'unknown', null)],
}

function form(slug: string) {
  return mount(ExpertEditForm, {
    props: { spaceId: 'demo', release, slug, title: '字段' },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })] },
  })
}

type View = ReturnType<typeof form>
const disabled = (view: View) => view.get('[data-submit]').attributes('disabled') !== undefined
const missing = (view: View) => view.find('[data-missing]')

describe('a field the materials do not mention', () => {
  it('says to choose "有值" when only a reason was typed, and stops saying it once a value is given', async () => {
    const view = form('P1/f_slogan')
    await view.get('[data-reason]').setValue('灵活定制：四档免赔额自由选')
    expect(disabled(view)).toBe(true)
    expect(missing(view).text()).toContain('请先选择')
    expect(missing(view).text()).toContain('有值')

    await view.get('[data-state] input[value="present"]').setValue(true)
    expect(missing(view).text()).toContain('请填写新值')
    await view.get('[data-value]').setValue('灵活定制：四档免赔额自由选')
    expect(disabled(view)).toBe(false)
    expect(missing(view).exists()).toBe(false)
  })
})

describe('a field with a value', () => {
  it('names the first missing condition', async () => {
    const view = form('P1/f_wait')
    await view.get('[data-value]').setValue('   ')
    expect(missing(view).text()).toContain('请填写新值')
    await view.get('[data-value]').setValue(' 90日 ')
    expect(missing(view).text()).toContain('新值与当前内容相同')
    await view.get('[data-value]').setValue('180日')
    expect(missing(view).text()).toContain('请填写修改原因')
    await view.get('[data-reason]').setValue('理'.repeat(2001))
    expect(missing(view).text()).toContain('修改原因超过 2000 字')
    await view.get('[data-reason]').setValue('备案条款第五条')
    expect(missing(view).exists()).toBe(false)
    expect(disabled(view)).toBe(false)
  })

  it('labels what goes in each box', () => {
    const text = form('P1/f_wait').text()
    expect(text).toContain('新值（字段内容）')
    expect(text).toContain('修改原因（必填，说明依据）')
  })
})
