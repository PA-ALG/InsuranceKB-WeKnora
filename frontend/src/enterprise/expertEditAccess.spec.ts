// S9b implementer test: the edit form is offered to administrators and owners only, and to
// nobody when no store is active (Spec docs/design/slices/S9b-专家编辑界面.md §2.2).
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

const access = vi.hoisted(() => ({ role: '' }))
vi.mock('@/stores/auth', () => {
  const level: Record<string, number> = { viewer: 10, contributor: 20, admin: 30, owner: 40 }
  return { useAuthStore: () => ({ hasRole: (min: string) => (level[access.role] ?? 0) >= level[min] }) }
})

import { canOfferExpertEdit } from './expertEditAccess'

afterEach(() => { setActivePinia(undefined) })

describe('canOfferExpertEdit', () => {
  it('offers nothing without an active store', () => {
    access.role = 'owner'
    setActivePinia(undefined)
    expect(canOfferExpertEdit()).toBe(false)
  })

  it.each([
    ['viewer', false],
    ['contributor', false],
    ['admin', true],
    ['owner', true],
  ])('%s → %s', (role, offered) => {
    access.role = role
    setActivePinia(createPinia())
    expect(canOfferExpertEdit()).toBe(offered)
  })
})
