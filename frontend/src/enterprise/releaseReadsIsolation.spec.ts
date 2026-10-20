import { afterEach, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({ get: vi.fn(), post: vi.fn() }))
import { get } from '@/utils/request'
import { readRelease } from './enterpriseApi'

afterEach(() => { vi.resetAllMocks(); vi.unstubAllGlobals() })

it('does not coalesce pending reads across a login or tenant change', async () => {
  const session = new Map([['weknora_token', 'first'], ['weknora_selected_tenant_id', '7']])
  vi.stubGlobal('localStorage', { getItem: (key: string) => session.get(key) ?? null })
  const finish: Array<(value: any) => void> = []
  vi.mocked(get).mockImplementation(() => new Promise(resolve => finish.push(resolve)))
  const first = readRelease('demo', 'rel-9')
  session.set('weknora_token', 'second')
  const second = readRelease('demo', 'rel-9')
  session.set('weknora_selected_tenant_id', '8')
  const third = readRelease('demo', 'rel-9')
  expect(get).toHaveBeenCalledTimes(3)
  finish.forEach((resolve, i) => resolve({ success: true, data: { id: `result-${i}`, members: [] } }))
  expect((await Promise.all([first, second, third])).map(r => r.id)).toEqual(['result-0', 'result-1', 'result-2'])
})

it('shares a pending rejection, then retries and observes a later permission denial', async () => {
  vi.mocked(get).mockRejectedValueOnce({ code: 'REQUEST_FAILED' })
    .mockResolvedValueOnce({ success: true, data: { id: 'r', members: [] } } as any)
    .mockResolvedValueOnce({ success: false, code: 'RELEASE_ACCESS_DENIED' } as any)
  const failures = await Promise.allSettled([readRelease('demo', 'r'), readRelease('demo', 'r')])
  expect(failures.every(result => result.status === 'rejected')).toBe(true)
  expect(get).toHaveBeenCalledTimes(1)
  await expect(readRelease('demo', 'r')).resolves.toMatchObject({ id: 'r' })
  await expect(readRelease('demo', 'r')).rejects.toMatchObject({ code: 'RELEASE_ACCESS_DENIED' })
  expect(get).toHaveBeenCalledTimes(3)
})
