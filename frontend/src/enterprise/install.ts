// The enterprise module's one entry into the upstream app (U-5a). main.ts calls it once, right after
// Pinia and before the router's first navigation, so upstream's route table, sidebar menu store and
// i18n setup stay byte-identical to the pinned release on every upgrade.
import type { Pinia } from 'pinia'
import type { Router } from 'vue-router'
import { useMenuStore } from '@/stores/menu'
import { ENTERPRISE_MESSAGES } from './i18n/index.ts'
import { ENTERPRISE_ROUTE_PARENT, ENTERPRISE_ROUTES } from './routes.ts'

const MENU_ENTRY = { titleKey: 'menu.enterpriseKnowledge', icon: 'enterprise', path: 'enterprise' }
// Right after the knowledge-base list, where the entry sat inside upstream's menu array.
const MENU_ANCHOR = 'knowledge-bases'

// The part of vue-i18n's global composer the entry uses.
interface UIStrings {
  global: {
    readonly availableLocales: string[]
    mergeLocaleMessage(locale: string, message: object): void
    t(key: string): string
  }
}

export interface EnterpriseHost {
  router: Router
  i18n: UIStrings
  pinia: Pinia
}

export function installEnterprise({ router, i18n, pinia }: EnterpriseHost): void {
  const menu = useMenuStore(pinia)
  const anchor = menu.menuArr.findIndex(item => item.path === MENU_ANCHOR)
  // Check both hook points before registering anything. An upgrade that renames one fails loudly
  // here (appEntry.spec.ts runs this against the real router and menu store) instead of quietly
  // shipping an app without the enterprise pages.
  if (!router.hasRoute(ENTERPRISE_ROUTE_PARENT)) {
    throw new Error(`enterprise: upstream route "${ENTERPRISE_ROUTE_PARENT}" not found`)
  }
  if (anchor < 0) {
    throw new Error(`enterprise: upstream menu entry "${MENU_ANCHOR}" not found`)
  }

  for (const locale of i18n.global.availableLocales) {
    const messages = ENTERPRISE_MESSAGES[locale]
    if (messages) i18n.global.mergeLocaleMessage(locale, messages)
  }
  for (const route of ENTERPRISE_ROUTES) {
    if (!router.hasRoute(route.name)) router.addRoute(ENTERPRISE_ROUTE_PARENT, route)
  }
  // The menu store's own locale watch keeps this title current, as for upstream's entries.
  if (!menu.menuArr.some(item => item.path === MENU_ENTRY.path)) {
    menu.menuArr.splice(anchor + 1, 0, { ...MENU_ENTRY, title: i18n.global.t(MENU_ENTRY.titleKey) })
  }
}
