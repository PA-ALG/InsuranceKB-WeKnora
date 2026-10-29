import { mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { vi } from 'vitest'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import { get } from '@/utils/request'
import EnterpriseReviews from '../EnterpriseReviews.vue'
import { pointDetail, pointItem } from './reviewPointFixtures'
import { release } from './s3eFixtures'

export const ok = (data: unknown) => ({ success: true, data, $httpStatus: 200 })
export function deferred<T = ReturnType<typeof ok>>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
export function transport() {
  vi.mocked(get).mockImplementation(async (url: string) => url.includes('/releases/') ? ok(release())
    : url.includes('?status=') ? ok({ items: url.endsWith('pending') ? [pointItem()] : [] }) : ok(pointDetail()))
}
export const views: ReturnType<typeof mount>[] = []
export function page() {
  const view = mount(EnterpriseReviews, { attachTo: document.body, props: { spaceId: 'demo' }, global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
    stubs: { RouterLink: RouterLinkStub },
  } })
  views.push(view)
  return view
}
export const pointCard = (view: ReturnType<typeof page>, slug = 'M1/waiting_period') => view.get(`[data-point="${slug}"]`)
export async function draft(view: ReturnType<typeof page>) {
  const card = pointCard(view)
  await card.findAll('button').find(button => button.text() === '填写理由')!.trigger('click')
  const input = card.get('textarea')
  ;(input.element as HTMLTextAreaElement).focus()
  await input.setValue('新的审核草稿')
  return input
}
