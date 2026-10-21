import { getCurrentInstance, type App } from 'vue'

type Expansion = Partial<Record<'schema' | 'wiki', boolean>>
// One app session, across route component lifetimes. No Release or other business data is stored.
// Weak ownership lets the entire memory disappear when the app is destroyed.
const sessions = new WeakMap<App, Map<string, Expansion>>()

export function useNavigationMemory() {
  const app = getCurrentInstance()!.appContext.app
  let memory = sessions.get(app)
  if (!memory) { memory = new Map(); sessions.set(app, memory) }
  return {
    read: (key: string): Expansion => memory.get(key) ?? {},
    write(key: string, group: keyof Expansion, open: boolean) {
      memory.set(key, { ...memory.get(key), [group]: open })
    },
  }
}
