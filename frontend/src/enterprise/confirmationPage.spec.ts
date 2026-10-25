// @vitest-environment happy-dom
// S5b-3b acceptance (protected, written by Claude): the confirmation desk lists a Space's open
// items as their submitter worded them, records a person's choice of one offered option, and
// shows how closed items were handled (Spec docs/design/slices/S5b-3b-待确认材料页面.md §2.2–§3).
import { readFileSync } from 'node:fs'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'
import jaJP from '@/i18n/locales/ja-JP'
import koKR from '@/i18n/locales/ko-KR'
import ruRU from '@/i18n/locales/ru-RU'
import routerSource from '@/router/index.ts?raw'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
  listConfirmations: vi.fn(),
  answerConfirmation: vi.fn(),
}))

import EnterpriseConfirmations from './EnterpriseConfirmations.vue'
import EnterpriseSpace from './EnterpriseSpace.vue'
import {
  answerConfirmation, EnterpriseError, listConfirmations, readRelease,
  type ConfirmationAnswer, type ConfirmationItem,
} from './enterpriseApi'
import { confirmationAnswer, confirmationItem } from './__tests__/confirmationFixtures'
import { spotRelease } from './__tests__/spotCheckFixtures'

const views: ReturnType<typeof mount>[] = []
function page(spaceId = 'demo') {
  const view = mount(EnterpriseConfirmations, {
    attachTo: document.body,
    props: { spaceId },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub },
    },
  })
  views.push(view)
  return view
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

const ids = (view: ReturnType<typeof mount>) => view.findAll('[data-confirm-item]').map(item => item.attributes('data-confirm-item'))
const disabled = (view: { attributes: (name: string) => string | undefined }) => view.attributes('disabled') !== undefined

afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

describe('confirmation desk', () => {
  it('lists this Space\'s open items as worded by the submitter, and nothing internal', async () => {
    vi.mocked(listConfirmations).mockResolvedValue([
      confirmationItem('c1'), confirmationItem('c2', { title: '另一份材料' }), confirmationItem('x', { space_id: 'other' }),
    ])
    const style = document.createElement('style')
    style.textContent = ['enterprisePage.css', 'confirmations.css']
      .map(name => readFileSync(new URL(name, import.meta.url), 'utf8')).join('\n')
    document.head.append(style)
    try {
      const view = page()
      expect(view.find('[role="status"]').exists()).toBe(true)
      await flushPromises()
      expect(vi.mocked(listConfirmations).mock.calls).toEqual([['demo', 'open']])
      expect(ids(view)).toEqual(['c1', 'c2'])
      const card = view.get('[data-confirm-item="c1"]')
      expect(card.get('fieldset legend').text()).toBe('一份材料需要确认归属')
      const detail = card.get('[data-confirm-detail]')
      expect(detail.element.textContent).toBe('第一行说明\n第二行说明')
      expect(getComputedStyle(detail.element).whiteSpace).toBe('pre-wrap')
      const options = card.findAll('fieldset [data-confirm-option]')
      expect(options.map(option => option.attributes('data-confirm-option'))).toEqual(['replace', 'supplement', 'ignore'])
      expect(options.map(option => (option.element as HTMLInputElement).closest('label')?.textContent?.trim()))
        .toEqual(['替换原有文件', '作为补充材料', '忽略这份文件'])
      expect(options.every(option => option.attributes('type') === 'radio' && !(option.element as HTMLInputElement).checked)).toBe(true)
      // One choice per item: the two cards never share a radio group.
      expect(new Set(view.findAll('[data-confirm-option]').map(option => option.attributes('name'))).size).toBe(2)
      for (const internal of ['submitter:subject-1', 'rev-7', 'c'.repeat(64), 'service:submitter']) {
        expect(view.text()).not.toContain(internal)
      }
      expect(card.find('[data-confirm-state]').exists()).toBe(false)
      expect(disabled(card.get('[data-confirm-submit]'))).toBe(true)
    } finally { style.remove() }
  })

  it('submits the chosen option and note, then waits for the system without reloading', async () => {
    vi.mocked(listConfirmations).mockResolvedValue([confirmationItem('c1')])
    const pending = deferred<ConfirmationAnswer>()
    vi.mocked(answerConfirmation).mockReturnValue(pending.promise)
    const view = page()
    await flushPromises()
    const card = view.get('[data-confirm-item="c1"]')
    const submit = card.get('[data-confirm-submit]')
    expect(submit.text()).toBe('提交选择')
    await card.get('[data-confirm-option="replace"]').setValue(true)
    await card.get('textarea').setValue('以新版条款为准')
    expect(disabled(submit)).toBe(false)
    await submit.trigger('click')
    expect(vi.mocked(answerConfirmation).mock.calls).toEqual([['demo', 'c1', 'replace', '以新版条款为准']])
    expect(disabled(submit)).toBe(true)
    pending.resolve(confirmationAnswer('c1', { id: 'answer-2', option_key: 'replace', note: '以新版条款为准' }))
    await flushPromises()
    const state = card.get('[data-confirm-state]')
    expect(state.text()).toContain('已选择：替换原有文件，等待系统处理')
    expect(submit.text()).toBe('修改选择')
    expect(disabled(submit)).toBe(true)
    expect(document.activeElement).toBe(state.element)
    expect(vi.mocked(listConfirmations)).toHaveBeenCalledTimes(1)
  })

  it('starts from the latest answer and resubmits only a change within the note limit', async () => {
    vi.mocked(listConfirmations).mockResolvedValue([confirmationItem('c1', { answer: confirmationAnswer('c1') })])
    const view = page()
    await flushPromises()
    const card = view.get('[data-confirm-item="c1"]')
    expect((card.get('[data-confirm-option="supplement"]').element as HTMLInputElement).checked).toBe(true)
    expect((card.get('textarea').element as HTMLTextAreaElement).value).toBe('保留两份')
    expect(card.get('[data-confirm-state]').text()).toContain('已选择：作为补充材料，等待系统处理')
    const submit = card.get('[data-confirm-submit]')
    expect(submit.text()).toBe('修改选择')
    expect(disabled(submit)).toBe(true)
    await card.get('textarea').setValue('保留两份，以新版为准')
    expect(disabled(submit)).toBe(false)
    await card.get('textarea').setValue('保留两份 ')
    expect(disabled(submit)).toBe(true)
    await card.get('[data-confirm-option="ignore"]').setValue(true)
    expect(disabled(submit)).toBe(false)
    await card.get('textarea').setValue('长'.repeat(1001))
    expect(disabled(submit)).toBe(true)
    expect(card.text()).toContain('1001 / 1000 字')
    await card.get('textarea').setValue(` ${'长'.repeat(1000)} `)
    expect(disabled(submit)).toBe(false)
  })

  it('names a missing permission, an invalid option or a failure on that card alone', async () => {
    vi.mocked(listConfirmations).mockResolvedValue([confirmationItem('c1'), confirmationItem('c2')])
    vi.mocked(answerConfirmation)
      .mockRejectedValueOnce(new EnterpriseError('RELEASE_ACCESS_DENIED', 403))
      .mockRejectedValueOnce(new EnterpriseError('ANSWER_INVALID', 400))
      .mockRejectedValueOnce(new EnterpriseError('REQUEST_FAILED'))
      .mockResolvedValueOnce(confirmationAnswer('another-item', { option_key: 'replace' }))
    const view = page()
    await flushPromises()
    const card = view.get('[data-confirm-item="c1"]'), other = view.get('[data-confirm-item="c2"]')
    await card.get('[data-confirm-option="replace"]').setValue(true)
    const submit = card.get('[data-confirm-submit]')
    for (const message of ['需要管理员且有 Wiki 编辑权限', '选项无效，请刷新后重试', '提交失败，请重试', '提交失败，请重试']) {
      await submit.trigger('click')
      await flushPromises()
      expect(card.get('[role="alert"]').text()).toContain(message)
      expect(card.find('[data-confirm-state]').exists()).toBe(false)
      expect(disabled(submit)).toBe(false)
    }
    expect(other.find('[role="alert"]').exists()).toBe(false)
    expect(vi.mocked(answerConfirmation)).toHaveBeenCalledTimes(4)
    expect(vi.mocked(listConfirmations)).toHaveBeenCalledTimes(1)
  })

  it('reloads with a notice when the item was closed meanwhile', async () => {
    vi.mocked(listConfirmations)
      .mockResolvedValueOnce([confirmationItem('c1'), confirmationItem('c2', { title: '另一份材料' })])
      .mockResolvedValueOnce([confirmationItem('c2', { title: '另一份材料' })])
    vi.mocked(answerConfirmation).mockRejectedValueOnce(new EnterpriseError('CONFIRMATION_CLOSED', 409))
    const view = page()
    await flushPromises()
    const card = view.get('[data-confirm-item="c1"]')
    await card.get('[data-confirm-option="ignore"]').setValue(true)
    await card.get('[data-confirm-submit]').trigger('click')
    await flushPromises()
    expect(vi.mocked(listConfirmations).mock.calls).toEqual([['demo', 'open'], ['demo', 'open']])
    expect(view.get('[data-confirm-notice]').text()).toContain('「一份材料需要确认归属」已处理，列表已刷新')
    expect(ids(view)).toEqual(['c2'])
    expect(document.activeElement).toBe(view.get('[data-confirm-tab="open"]').element)
  })

  it('shows closed items by how they were closed, without answering controls', async () => {
    const closure = { closed_by: 'service:submitter', closed_at: '2026-10-25T10:00:00Z' }
    vi.mocked(listConfirmations).mockImplementation((_space, status) => Promise.resolve(status === 'closed' ? [
      confirmationItem('c1', { answer: confirmationAnswer('c1', { id: 'a2', option_key: 'replace' }),
        closure: { reason: 'applied', answer_id: 'a2', ...closure } }),
      confirmationItem('c2', { closure: { reason: 'obsolete', ...closure } }),
      confirmationItem('c3', { answer: confirmationAnswer('c3', { id: 'a3' }),
        closure: { reason: 'applied', answer_id: 'a-elsewhere', ...closure } }),
    ] : []))
    const view = page()
    await flushPromises()
    expect(view.text()).toContain('没有待确认的材料')
    await view.get('[data-confirm-tab="closed"]').trigger('click')
    await flushPromises()
    expect(vi.mocked(listConfirmations).mock.calls).toEqual([['demo', 'open'], ['demo', 'closed']])
    expect(ids(view)).toEqual(['c1', 'c2', 'c3'])
    expect(view.get('[data-confirm-item="c1"] [data-confirm-state]').text()).toContain('已按「替换原有文件」处理')
    expect(view.get('[data-confirm-item="c1"]').text()).toContain('user:alice')
    expect(view.get('[data-confirm-item="c2"] [data-confirm-state]').text()).toContain('已无需处理')
    // An applied closure that names another answer is shown as handled, never as a guessed option.
    const unmatched = view.get('[data-confirm-item="c3"] [data-confirm-state]').text()
    expect(unmatched).toContain('已处理')
    expect(unmatched).not.toContain('作为补充材料')
    expect(view.find('[data-confirm-option]').exists()).toBe(false)
    expect(view.find('[data-confirm-submit]').exists()).toBe(false)
  })

  it('retries a failed load, says when nothing waits, and switches tabs by keyboard', async () => {
    vi.mocked(listConfirmations)
      .mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503))
      .mockResolvedValue([])
    const view = page()
    await flushPromises()
    const alert = view.get('[role="alert"]')
    expect(alert.text()).toContain('待确认材料加载失败')
    await alert.get('button').trigger('click')
    await flushPromises()
    expect(view.text()).toContain('没有待确认的材料')
    await view.get('[data-confirm-tab="open"]').trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    const closed = view.get('[data-confirm-tab="closed"]')
    expect(closed.attributes('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(closed.element)
    expect(view.text()).toContain('没有已处理的材料')
    await closed.trigger('keydown', { key: 'Home' })
    await flushPromises()
    expect(view.get('[data-confirm-tab="open"]').attributes('aria-selected')).toBe('true')
    expect(vi.mocked(listConfirmations).mock.calls.map(call => call[1])).toEqual(['open', 'open', 'closed', 'open'])
  })

  it('keeps a tab\'s own result when an earlier tab answers late', async () => {
    const openList = deferred<ConfirmationItem[]>(), closedList = deferred<ConfirmationItem[]>()
    vi.mocked(listConfirmations).mockReturnValueOnce(openList.promise).mockReturnValueOnce(closedList.promise)
    const view = page()
    await view.get('[data-confirm-tab="closed"]').trigger('click')
    closedList.resolve([])
    await flushPromises()
    openList.resolve([confirmationItem('stale')])
    await flushPromises()
    expect(ids(view)).toEqual([])
    expect(view.text()).toContain('没有已处理的材料')
  })

  it('drops the list and the answer of a Space the page has left', async () => {
    const answer = deferred<ConfirmationAnswer>(), late = deferred<ConfirmationItem[]>()
    vi.mocked(listConfirmations)
      .mockResolvedValueOnce([confirmationItem('c1')])
      .mockReturnValueOnce(late.promise)
      .mockResolvedValueOnce([confirmationItem('c1')])
    vi.mocked(answerConfirmation).mockReturnValue(answer.promise)
    const view = page()
    await flushPromises()
    await view.get('[data-confirm-option="replace"]').setValue(true)
    await view.get('[data-confirm-submit]').trigger('click')
    await view.setProps({ spaceId: 'next' })
    await view.setProps({ spaceId: 'demo' })
    await flushPromises()
    answer.resolve(confirmationAnswer('c1', { option_key: 'replace' }))
    late.resolve([confirmationItem('n1', { space_id: 'next' })])
    await flushPromises()
    expect(vi.mocked(listConfirmations).mock.calls).toEqual([['demo', 'open'], ['next', 'open'], ['demo', 'open']])
    expect(ids(view)).toEqual(['c1'])
    const card = view.get('[data-confirm-item="c1"]')
    expect(card.find('[data-confirm-state]').exists()).toBe(false)
    expect((card.get('[data-confirm-option="replace"]').element as HTMLInputElement).checked).toBe(false)
    expect(disabled(card.get('[data-confirm-submit]'))).toBe(true)
  })

  // Review R1: a submission the page left by reloading its list never overwrites what the list shows.
  it('keeps the closure a later list shows over a late submission', async () => {
    const post = deferred<ConfirmationAnswer>()
    const applied = confirmationAnswer('c1', { id: 'answer-a', option_key: 'replace' })
    vi.mocked(listConfirmations).mockImplementation((_space, status) => Promise.resolve(status === 'open'
      ? [confirmationItem('c1')]
      : [confirmationItem('c1', { answer: applied, closure: {
        reason: 'applied', answer_id: 'answer-a', closed_by: 'service:submitter', closed_at: '2026-10-25T10:00:00Z',
      } })]))
    vi.mocked(answerConfirmation).mockReturnValue(post.promise)
    const view = page()
    await flushPromises()
    await view.get('[data-confirm-option="replace"]').setValue(true)
    await view.get('[data-confirm-submit]').trigger('click')
    await view.get('[data-confirm-tab="closed"]').trigger('click')
    await flushPromises()
    post.resolve(applied)
    await flushPromises()
    expect(view.get('[data-confirm-tab="closed"]').attributes('aria-selected')).toBe('true')
    expect(view.get('[data-confirm-item="c1"] [data-confirm-state]').text()).toContain('已按「替换原有文件」处理')
    expect(view.find('[data-confirm-option]').exists()).toBe(false)
  })

  it('keeps a newer answer a later list shows over a late submission', async () => {
    const post = deferred<ConfirmationAnswer>()
    const newer = confirmationAnswer('c1', { id: 'answer-b', option_key: 'supplement', note: '以新版为准' })
    vi.mocked(listConfirmations)
      .mockResolvedValueOnce([confirmationItem('c1')])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([confirmationItem('c1', { answer: newer })])
    vi.mocked(answerConfirmation).mockReturnValue(post.promise)
    const view = page()
    await flushPromises()
    await view.get('[data-confirm-option="replace"]').setValue(true)
    await view.get('[data-confirm-submit]').trigger('click')
    await view.get('[data-confirm-tab="closed"]').trigger('click')
    await flushPromises()
    await view.get('[data-confirm-tab="open"]').trigger('click')
    await flushPromises()
    post.resolve(confirmationAnswer('c1', { id: 'answer-a', option_key: 'replace' }))
    await flushPromises()
    const card = view.get('[data-confirm-item="c1"]')
    expect(card.get('[data-confirm-state]').text()).toContain('已选择：作为补充材料，等待系统处理')
    expect((card.get('[data-confirm-option="supplement"]').element as HTMLInputElement).checked).toBe(true)
    expect((card.get('textarea').element as HTMLTextAreaElement).value).toBe('以新版为准')
  })

  it('lets a list that returns after a late submission decide the card', async () => {
    const post = deferred<ConfirmationAnswer>(), reopened = deferred<ConfirmationItem[]>()
    vi.mocked(listConfirmations)
      .mockResolvedValueOnce([confirmationItem('c1')])
      .mockResolvedValueOnce([])
      .mockReturnValueOnce(reopened.promise)
    vi.mocked(answerConfirmation).mockReturnValue(post.promise)
    const view = page()
    await flushPromises()
    await view.get('[data-confirm-option="replace"]').setValue(true)
    await view.get('[data-confirm-submit]').trigger('click')
    await view.get('[data-confirm-tab="closed"]').trigger('click')
    await flushPromises()
    await view.get('[data-confirm-tab="open"]').trigger('click')
    post.resolve(confirmationAnswer('c1', { option_key: 'replace' }))
    await flushPromises()
    reopened.resolve([confirmationItem('c1')])
    await flushPromises()
    const card = view.get('[data-confirm-item="c1"]')
    expect(card.find('[data-confirm-state]').exists()).toBe(false)
    const submit = card.get('[data-confirm-submit]')
    expect(submit.text()).toBe('提交选择')
    expect(disabled(submit)).toBe(false)
  })

  it.each(['returns', 'fails'])('leaves the focus alone when a 409 refresh the page has left %s', async outcome => {
    let finish!: () => void
    const refresh = new Promise<ConfirmationItem[]>((resolve, reject) => {
      finish = () => outcome === 'returns' ? resolve([]) : reject(new EnterpriseError('SERVICE_UNAVAILABLE', 500))
    })
    vi.mocked(listConfirmations)
      .mockResolvedValueOnce([confirmationItem('c1')])
      .mockReturnValueOnce(refresh)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([confirmationItem('c2')])
    vi.mocked(answerConfirmation).mockRejectedValueOnce(new EnterpriseError('CONFIRMATION_CLOSED', 409))
    const view = page()
    await flushPromises()
    await view.get('[data-confirm-option="replace"]').setValue(true)
    await view.get('[data-confirm-submit]').trigger('click')
    await flushPromises()
    await view.get('[data-confirm-tab="closed"]').trigger('click')
    await flushPromises()
    await view.get('[data-confirm-tab="open"]').trigger('click')
    await flushPromises()
    const note = view.get('[data-confirm-item="c2"] textarea')
    ;(note.element as HTMLTextAreaElement).focus()
    await note.setValue('继续填写')
    finish()
    await flushPromises()
    expect(document.activeElement).toBe(note.element)
    expect(ids(view)).toEqual(['c2'])
    expect((view.get('[data-confirm-item="c2"] textarea').element as HTMLTextAreaElement).value).toBe('继续填写')
  })

  // Review R2: the note is trimmed, counted and checked as the server does (Go strings.TrimSpace).
  it('counts, compares and checks the note the way the server does', async () => {
    vi.mocked(listConfirmations).mockResolvedValue([confirmationItem('c1', { answer: confirmationAnswer('c1') })])
    const view = page()
    await flushPromises()
    const card = view.get('[data-confirm-item="c1"]'), submit = card.get('[data-confirm-submit]')
    await card.get('textarea').setValue('\u0085保留两份\u0085')
    expect(disabled(submit)).toBe(true)
    await card.get('textarea').setValue('保留两份\uFEFF')
    expect(disabled(submit)).toBe(false)
    await card.get('textarea').setValue(`\uFEFF${'a'.repeat(1000)}`)
    expect(card.text()).toContain('1001 / 1000 字')
    expect(disabled(submit)).toBe(true)
    await card.get('textarea').setValue(`\u0085${'a'.repeat(1000)}`)
    expect(card.text()).toContain('1000 / 1000 字')
    expect(disabled(submit)).toBe(false)
    await card.get('textarea').setValue('保留\t两份')
    expect(disabled(submit)).toBe(true)
    expect(card.text()).toContain('备注不能包含控制字符（如制表符）')
    await card.get('textarea').setValue('保留\n两份')
    expect(disabled(submit)).toBe(false)
    expect(card.text()).not.toContain('控制字符')
  })

  it('is reachable from the Space page through a registered route', async () => {
    vi.mocked(readRelease).mockResolvedValue(spotRelease())
    const view = mount(EnterpriseSpace, {
      props: { spaceId: 'demo' },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
        stubs: { RouterLink: RouterLinkStub },
      },
    })
    views.push(view)
    await flushPromises()
    const links = view.findAllComponents(RouterLinkStub).map(link => link.props('to'))
    expect(links).toContainEqual({ name: 'enterpriseConfirmations', params: { spaceId: 'demo' } })
    expect(routerSource).toMatch(new RegExp([
      'path: "enterprise/:spaceId/confirmations",', 'name: "enterpriseConfirmations",',
      'component: \\(\\) => import\\("\\.\\./enterprise/EnterpriseConfirmations\\.vue"\\),',
    ].join('\\s*')))
  })

  it('words every confirmation text in all five locales', () => {
    type Messages = { enterpriseKnowledge: { confirm?: Record<string, unknown> } }
    const entries = (messages: unknown) => Object.entries((messages as Messages).enterpriseKnowledge.confirm ?? {})
    const keys = entries(zhCN).map(([key]) => key).sort()
    expect(keys.length).toBeGreaterThan(0)
    for (const messages of [zhCN, enUS, jaJP, koKR, ruRU]) {
      expect(entries(messages).map(([key]) => key).sort()).toEqual(keys)
      expect(entries(messages).every(([, text]) => typeof text === 'string' && text.trim() !== '')).toBe(true)
    }
  })
})
