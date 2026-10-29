// @vitest-environment happy-dom
// S3d-4 follow-up acceptance (protected, written by Claude; user 2026-10-18 "这个出处 放到右下角"):
// the field name stands alone on top; the full-version switch sits at the bottom left and the
// origin label and sources at the bottom right of the same row.
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import EnterpriseField from './EnterpriseField.vue'
import type { FieldView } from './releaseView'

function field(value: FieldView['value'], evidenceCount = 3) {
  const view: FieldView = { slug: 'P1/f', title: '犹豫期', state: 'present', value, origin: 'MIXED', evidenceCount }
  return mount(EnterpriseField, {
    props: { field: view },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })] },
  })
}

const LONG = [1, 2, 3].map(n => `${n}. 第${n}项：${'自签收本合同之日起有十五日的犹豫期。'.repeat(5)}`).join('')

describe('the field footer', () => {
  it.each([['a short value', '15日'], ['a long value', LONG]])('holds the sources of %s, not the head', (_, value) => {
    const view = field(value)
    expect(view.get('.ek-field__head').findAll('button')).toHaveLength(0)
    expect(view.get('.ek-field__head').find('[data-origin]').exists()).toBe(false)
    const meta = view.get('.ek-field__foot .ek-field__meta')
    expect(meta.findAll('button').map(button => button.text())).toEqual(['出处 1', '出处 2', '出处 3'])
    expect(meta.get('[data-origin]').text()).toBe('原文与整理')
  })

  it('puts the switch before the sources in the same row', () => {
    const foot = field(LONG).get('.ek-field__foot')
    const children = Array.from(foot.element.children)
    const toggle = children.findIndex(child => child.querySelector('[data-toggle]') !== null)
    const meta = children.findIndex(child => child.classList.contains('ek-field__meta'))
    expect(toggle).toBeGreaterThanOrEqual(0)
    expect(meta).toBeGreaterThan(toggle)
  })
})
