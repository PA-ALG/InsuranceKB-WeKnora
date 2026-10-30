type Tree = { [key: string]: unknown }

const isTree = (value: unknown): value is Tree =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

// Deep-merges our strings onto an upstream bundle. Our keys never overlap
// upstream keys (checked when they were moved, U-1), so the result type is the
// intersection of both bundles.
export function mergeMessages<B extends object, E extends object>(base: B, extra: E): B & E {
  const merged: Tree = { ...(base as Tree) }
  for (const [key, value] of Object.entries(extra)) {
    const current = merged[key]
    merged[key] = isTree(current) && isTree(value) ? mergeMessages(current, value) : value
  }
  return merged as B & E
}
