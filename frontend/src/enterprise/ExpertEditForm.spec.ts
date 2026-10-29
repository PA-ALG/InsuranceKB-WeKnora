// @vitest-environment happy-dom
// S9b acceptance (protected, written by Claude): the expert edit form pre-fills the current value,
// only submits a complete change, sends the six keys against the shown release, and explains
// every refusal without losing what was typed (Spec docs/design/slices/S9b-专家编辑界面.md §2.3).
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  submitExpertEdit: vi.fn(),
}))

import ExpertEditForm from './ExpertEditForm.vue'
import { EnterpriseError, submitExpertEdit, type Release } from './enterpriseApi'

const DIGEST = 'd'.repeat(64)

function claim(slug: string, state: string, value: unknown) {
  return {
    kind: 'claim', logical_slug: slug, member_digest: slug === 'P1/f_wait' ? DIGEST : 'e'.repeat(64),
    access_scope: 'space',
    payload: { subject_ref: 'P1', predicate: slug.split('/')[1], state, value, origin: 'SOURCE_SUPPORTED', evidence: [] },
  }
}

const release: Release = {
  id: 'rel-1', epoch: 1,
  members: [
    claim('P1/f_wait', 'present', '90日'),
    claim('P1/f_list', 'present', ['一年', '三年']),
    claim('P1/f_absent', 'absent_explicitly', null),
  ],
}

function form(slug = 'P1/f_wait') {
  return mount(ExpertEditForm, {
    props: { spaceId: 'demo', release, slug, title: '等待期' },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })] },
  })
}

type View = ReturnType<typeof form>
const submit = (view: View) => view.get('[data-submit]')
const disabled = (view: View) => submit(view).attributes('disabled') !== undefined
const chooseState = (view: View, state: string) => view.get(`[data-state] input[value="${state}"]`).setValue(true)

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

afterEach(() => { vi.resetAllMocks() })

describe('pre-fill', () => {
  it('starts from the current state and value', () => {
    const view = form()
    expect((view.get('[data-state] input[value="present"]').element as HTMLInputElement).checked).toBe(true)
    expect((view.get('[data-value]').element as HTMLTextAreaElement).value).toBe('90日')
    expect(view.text()).toContain('90日')
  })

  it('lists a string array one item per line', () => {
    expect((form('P1/f_list').get('[data-value]').element as HTMLTextAreaElement).value).toBe('一年\n三年')
  })

  it('shows the state of a claim without a value and no value box', () => {
    const view = form('P1/f_absent')
    expect((view.get('[data-state] input[value="absent_explicitly"]').element as HTMLInputElement).checked).toBe(true)
    expect(view.find('[data-value]').exists()).toBe(false)
    expect(view.text()).toContain('材料明确没有')
  })
})

describe('when saving is allowed', () => {
  it('needs a reason and a change', async () => {
    const view = form()
    expect(disabled(view)).toBe(true)
    await view.get('[data-reason]').setValue('备案条款第五条')
    expect(disabled(view)).toBe(true)
    await view.get('[data-value]').setValue('  90日 ')
    expect(disabled(view)).toBe(true)
    await view.get('[data-value]').setValue('180日')
    expect(disabled(view)).toBe(false)
  })

  it('needs a value for a present claim', async () => {
    const view = form()
    await view.get('[data-reason]').setValue('r')
    await view.get('[data-value]').setValue('   ')
    expect(disabled(view)).toBe(true)
  })

  it('accepts a state change without a value and hides the value box', async () => {
    const view = form()
    await chooseState(view, 'unknown')
    expect(view.find('[data-value]').exists()).toBe(false)
    await view.get('[data-reason]').setValue('材料中没有写')
    expect(disabled(view)).toBe(false)
  })

  it('limits the reason to 2000 characters and shows the count', async () => {
    const view = form()
    await view.get('[data-value]').setValue('180日')
    await view.get('[data-reason]').setValue('理'.repeat(2000))
    expect(view.text()).toContain('已填 2000 / 2000 字')
    expect(disabled(view)).toBe(false)
    await view.get('[data-reason]').setValue('理'.repeat(2001))
    expect(disabled(view)).toBe(true)
  })
})

describe('saving', () => {
  it('sends the six keys against the shown release and reports the new version', async () => {
    const pending = deferred<{ release_id: string; epoch: number; revision_record_id: string }>()
    vi.mocked(submitExpertEdit).mockReturnValue(pending.promise)
    const view = form()
    await view.get('[data-value]').setValue('  180日 ')
    await view.get('[data-reason]').setValue(' 备案条款第五条 ')
    await submit(view).trigger('click')
    expect(vi.mocked(submitExpertEdit).mock.calls).toEqual([['demo', {
      base_release_id: 'rel-1', member_slug: 'P1/f_wait', base_member_digest: DIGEST,
      state: 'present', value: '180日', reason: '备案条款第五条',
    }]])
    expect(view.get('[role="status"]').text()).toContain('正在保存…')
    expect(disabled(view)).toBe(true)
    pending.resolve({ release_id: 'rel-2', epoch: 2, revision_record_id: 'rev-1' })
    await flushPromises()
    expect(view.emitted('published')).toEqual([[{ releaseId: 'rel-2', epoch: 2 }]])
  })

  it('sends an empty value when the claim is not present', async () => {
    vi.mocked(submitExpertEdit).mockResolvedValue({ release_id: 'rel-2', epoch: 2, revision_record_id: 'rev-1' })
    const view = form()
    await chooseState(view, 'absent_explicitly')
    await view.get('[data-reason]').setValue('条款无此责任')
    await submit(view).trigger('click')
    await flushPromises()
    expect(vi.mocked(submitExpertEdit).mock.calls[0][1]).toMatchObject({ state: 'absent_explicitly', value: '' })
  })
})

describe('refusals', () => {
  const STALE = '这个字段已有更新的版本，请查看最新版本后再修改'
  it.each([
    ['EXPERT_EDIT_STALE', 409, STALE, true],
    ['MEMBER_NOT_FOUND', 404, STALE, true],
    ['RELEASE_CONFLICT', 409, STALE, true],
    ['NEEDS_REBASE', 409, STALE, true],
    ['EXPERT_EDIT_INVALID', 400, '填写不完整，或与当前内容相同', false],
    ['RELEASE_ACCESS_DENIED', 403, '只有管理员可以修改字段', false],
    ['REQUEST_FAILED', 403, '只有管理员可以修改字段', false],
    ['SERVICE_UNAVAILABLE', 503, '暂时无法保存，请稍后重试', false],
    ['REQUEST_FAILED', 503, '暂时无法保存，请稍后重试', false],
    ['INTERNAL_ERROR', 500, '保存失败，请重试', false],
  ])('%s (%i) explains itself and keeps the input', async (code, status, text, reload) => {
    vi.mocked(submitExpertEdit).mockRejectedValue(new EnterpriseError(code, status))
    const view = form()
    await view.get('[data-value]').setValue('180日')
    await view.get('[data-reason]').setValue('备案条款第五条')
    await submit(view).trigger('click')
    await flushPromises()
    expect(view.get('[role="alert"]').text()).toContain(text)
    expect((view.get('[data-value]').element as HTMLTextAreaElement).value).toBe('180日')
    expect((view.get('[data-reason]').element as HTMLTextAreaElement).value).toBe('备案条款第五条')
    expect(view.emitted('published')).toBeUndefined()
    expect(view.find('[data-reload]').exists()).toBe(reload)
    if (reload) {
      await view.get('[data-reload]').trigger('click')
      expect(view.emitted('reload')).toEqual([[]])
    }
  })
})
