// S3d-3a acceptance (protected, written by Claude): the session read routes of S3d-1, with
// encoded paths, unwrapped envelopes and typed failures (Spec §3.1).
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({ get: vi.fn() }))

import { get } from '@/utils/request'
import { EnterpriseError, listSpaces, readCitation, readRelease } from './enterpriseApi'

const ok = (data: unknown) => ({ success: true, data })

afterEach(() => { vi.resetAllMocks() })

describe('enterprise session reads', () => {
  it('lists the Space ids of the caller', async () => {
    vi.mocked(get).mockResolvedValue(ok({ spaces: [{ space_id: 'alpha' }, { space_id: 'demo' }] }) as any)
    await expect(listSpaces()).resolves.toEqual(['alpha', 'demo'])
    expect(vi.mocked(get).mock.calls[0][0]).toBe('/api/v1/enterprise/spaces')
  })

  it('reads the active release or a named one under the view path', async () => {
    const release = { id: 'rel/1', epoch: 2, members: [] }
    vi.mocked(get).mockResolvedValue(ok(release) as any)
    await expect(readRelease('demo space')).resolves.toEqual(release)
    await readRelease('demo', 'rel/1')
    expect(vi.mocked(get).mock.calls.map(call => call[0])).toEqual([
      '/api/v1/enterprise/spaces/demo%20space/view/releases/active',
      '/api/v1/enterprise/spaces/demo/view/releases/rel%2F1',
    ])
  })

  it('asks for one evidence of one member of an explicit release', async () => {
    vi.mocked(get).mockResolvedValue(ok({ quote: 'q' }) as any)
    await expect(readCitation('demo', 'rel-1', 'p1/term_a', 2)).resolves.toEqual({ quote: 'q' })
    expect(vi.mocked(get).mock.calls[0][0]).toBe(
      '/api/v1/enterprise/spaces/demo/view/releases/rel-1/citation?member=p1%2Fterm_a&evidence=2',
    )
  })

  it('turns refusals into typed errors with the platform code', async () => {
    vi.mocked(get).mockRejectedValueOnce({ status: 404, code: 'RELEASE_NOT_FOUND', message: 'no release' })
    const refused = readRelease('demo')
    await expect(refused).rejects.toBeInstanceOf(EnterpriseError)
    await expect(refused).rejects.toMatchObject({ code: 'RELEASE_NOT_FOUND', status: 404 })

    vi.mocked(get).mockRejectedValueOnce({ status: 0, message: 'Network Error' })
    await expect(listSpaces()).rejects.toMatchObject({ code: 'REQUEST_FAILED' })

    vi.mocked(get).mockResolvedValueOnce({ success: false, code: 'SOURCE_NOT_FOUND' } as any)
    await expect(readCitation('demo', 'rel-1', 'm', 0)).rejects.toMatchObject({ code: 'SOURCE_NOT_FOUND' })

    vi.mocked(get).mockResolvedValueOnce('<html>' as any)
    await expect(listSpaces()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' })
  })
})
