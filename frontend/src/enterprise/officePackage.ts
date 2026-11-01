import JSZip from 'jszip'
import type { OfficeFormat } from './officeCitation'
import { FOLLOWABLE_PROTOCOLS, HYPERLINK, POLICIES, TEXT_POLICIES, type FormatPolicy } from './officePackagePolicy'
import { readZipDirectory, ZipDirectoryRejected, type ZipEntry } from './officeZipDirectory'

// An Office file is untrusted active content (S11e Spec §3.2a). The upstream renderers act on what a
// package holds: docx-preview writes an altChunk's HTML into an unsandboxed iframe, and external
// targets make the browser fetch them. Before a cited file reaches the preview, its package is
// rebuilt default-deny: the ZIP directory is checked on the raw bytes, then only parts reachable
// from the package root through relationships the format's renderer follows, whose content types it
// reads (officePackagePolicy.ts), are kept; relationship and content-type parts are regenerated and
// altChunk elements removed. Anything we cannot read within the limits is refused, never shown as is.
// When the preview cannot show a citation, the text view reads the parts of the same rebuild
// (S11h Spec §2.2) instead of the raw file.

export type OfficePackageProblem = 'package' | 'size' | 'structure'

export class OfficePackageRejected extends Error {
  constructor(readonly problem: OfficePackageProblem) {
    super(`Office package rejected: ${problem}`)
    this.name = 'OfficePackageRejected'
  }
}

export interface OfficePackageLimits {
  /** Downloaded bytes. */
  bytes: number
  /** ZIP directory records, folders included. */
  entries: number
  /** Bytes of all entries once inflated, counted while inflating (declared sizes can lie). */
  inflated: number
}

export const OFFICE_PACKAGE_LIMITS: OfficePackageLimits = {
  bytes: 128 * 1024 * 1024,
  entries: 10_000,
  inflated: 256 * 1024 * 1024,
}

const RELATIONSHIPS_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
const CONTENT_TYPES_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
const CONTENT_TYPES = '[Content_Types].xml'

const ATTRIBUTE = /([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g
const ALT_CHUNK = /<(?:[\w.-]+:)?altChunk(?:\s+[\w:.-]+\s*=\s*(?:"[^"]*"|'[^']*'))*\s*(?:\/>|>[\s\S]*?<\/(?:[\w.-]+:)?altChunk\s*>)/g
const ALT_CHUNK_LEFT = /<(?:[\w.-]+:)?altChunk[\s/>]/

// @vue-office/pptx 1.0.1 renders only shapes, pictures and nested groups inside a group; on any
// other child — a graphic frame holding a chart, table or SmartArt — it appends `undefined` and the
// whole deck fails (S11h Spec §1). It renders the user-drawn shapes of layouts and masters the same
// way. pptx-preview 1.0.7 skips such children; the rebuild drops them alike until upstream's
// preview renders them (then remove this and its tests).
const RENDERED_SLIDE_PARTS = new Set(['slide', 'slideLayout', 'slideMaster']
  .map(part => `application/vnd.openxmlformats-officedocument.presentationml.${part}+xml`))
const GROUP_TAG = /<(\/?)(?:[\w.-]+:)?(grpSp|graphicFrame)(?:\s+[\w:.-]+\s*=\s*(?:"[^"]*"|'[^']*'))*\s*(\/?)>/g

interface Relationship { id: string; type: string; target: string; external: boolean }

function rejected(problem: OfficePackageProblem): OfficePackageRejected {
  return new OfficePackageRejected(problem)
}

export function decodeEntities(value: string): string {
  return value.replace(/&(#x[0-9a-f]+|#[0-9]+|amp|lt|gt|quot|apos);/gi, (raw, entity: string) => {
    const named: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" }
    if (!entity.startsWith('#')) return named[entity.toLowerCase()] ?? raw
    const point = entity[1].toLowerCase() === 'x' ? parseInt(entity.slice(2), 16) : parseInt(entity.slice(1), 10)
    return Number.isInteger(point) && point > 0 && point <= 0x10ffff ? String.fromCodePoint(point) : raw
  })
}

function escapeAttribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** Attributes of every element with the given local name, any prefix. */
function elements(xml: string, name: string): Record<string, string>[] {
  const found: Record<string, string>[] = []
  const pattern = new RegExp(`<(?:[\\w.-]+:)?${name}((?:\\s+[\\w:.-]+\\s*=\\s*(?:"[^"]*"|'[^']*'))*)\\s*/?>`, 'g')
  for (const match of xml.matchAll(pattern)) {
    const attributes: Record<string, string> = {}
    for (const [, key, double, single] of match[1].matchAll(ATTRIBUTE)) attributes[key] = decodeEntities(double ?? single)
    found.push(attributes)
  }
  return found
}

function extension(name: string): string {
  const base = name.slice(name.lastIndexOf('/') + 1)
  const dot = base.lastIndexOf('.')
  return dot < 0 ? '' : base.slice(dot + 1).toLowerCase()
}

function relationshipsPart(source: string): string {
  const slash = source.lastIndexOf('/')
  return `${source.slice(0, slash + 1)}_rels/${source.slice(slash + 1)}.rels`
}

/** The part a relative or absolute target names, or null if it leaves the package. */
function resolve(source: string, target: string): string | null {
  try {
    const base = `https://package.invalid/${source.slice(0, source.lastIndexOf('/') + 1)}`
    const url = new URL(target, base)
    if (url.origin !== 'https://package.invalid') return null
    return decodeURIComponent(url.pathname).replace(/^\/+/, '') || null
  } catch {
    return null
  }
}

function followable(target: string): boolean {
  try {
    return FOLLOWABLE_PROTOCOLS.has(new URL(target).protocol)
  } catch {
    return false
  }
}

type Stream = { on(event: string, callback: (...args: never[]) => void): Stream; pause(): Stream; resume(): Stream }

/** Inflates one entry, counting bytes, and stops as soon as `budget` is exceeded. */
function inflatedSize(file: JSZip.JSZipObject, budget: number): Promise<number> {
  return new Promise((resolve, reject) => {
    let size = 0
    // `internalStream` is public JSZip API (ZipObject#internalStream) missing from its typings.
    const stream = (file as unknown as { internalStream(type: 'uint8array'): Stream }).internalStream('uint8array')
    stream
      .on('data', (chunk: Uint8Array) => {
        size += chunk.length
        if (size > budget) {
          stream.pause()
          reject(rejected('size'))
        }
      })
      .on('error', () => reject(rejected('package')))
      .on('end', () => resolve(size))
      .resume()
  })
}

/** The XML with every graphic frame inside a group removed; refuses frames or groups left open. */
function withoutGroupedFrames(xml: string): string {
  let groups = 0
  let cut = -1
  let frames = 0
  let out = ''
  let last = 0
  for (const match of xml.matchAll(GROUP_TAG)) {
    const [tag, closing, name, empty] = match
    const at = match.index
    if (cut >= 0) {
      if (name === 'graphicFrame' && !empty) frames += closing ? -1 : 1
      if (frames === 0) {
        out += xml.slice(last, cut)
        last = at + tag.length
        cut = -1
      }
    } else if (name === 'grpSp') {
      if (!empty) groups += closing ? -1 : 1
    } else if (groups > 0 && !closing) {
      if (empty) {
        out += xml.slice(last, at)
        last = at + tag.length
      } else {
        cut = at
        frames = 1
      }
    }
  }
  if (cut >= 0 || groups !== 0) throw rejected('structure')
  return last ? out + xml.slice(last) : xml
}

/** A part the rebuild kept, and the internal relationships it kept for it. */
export interface OfficePartLink { id: string; type: string; name: string }

export interface OfficeParts {
  /** The main part, e.g. `ppt/presentation.xml`. */
  readonly main: string
  /** A kept part's XML as rebuilt, or null when the rebuild did not keep it. */
  text(name: string): Promise<string | null>
  /** The internal relationships the rebuild kept for a part, in document order. */
  related(source: string): OfficePartLink[]
}

interface Rebuilt {
  zip: JSZip
  entries: JSZip.JSZipObject[]
  keep: Set<string>
  rewritten: Map<string, string>
  main: string
  links: Map<string, OfficePartLink[]>
  part(name: string): JSZip.JSZipObject | null
  contentType(name: string): string | null
  read(name: string): Promise<string>
}

/**
 * Rebuilds an Office package so that only what the format's renderer reads reaches it. Throws
 * `OfficePackageRejected` when the file is not a readable package of `format` within `limits`.
 */
export async function sanitizeOfficePackage(
  data: ArrayBuffer, format: OfficeFormat, limits: OfficePackageLimits = OFFICE_PACKAGE_LIMITS,
): Promise<ArrayBuffer> {
  const { zip, entries, keep, rewritten, contentType, read } = await rebuild(data, format, POLICIES[format], limits)
  if (format === 'pptx') {
    for (const name of keep) {
      if (!RENDERED_SLIDE_PARTS.has(contentType(name) ?? '')) continue
      const xml = await read(name)
      if (!xml.includes('grpSp') || !xml.includes('graphicFrame')) continue
      const clean = withoutGroupedFrames(xml)
      if (clean !== xml) rewritten.set(name, clean)
    }
  }
  // Only files: removing a folder entry would also remove the kept parts under it.
  for (const file of entries) if (!keep.has(file.name)) zip.remove(file.name)
  for (const [name, xml] of rewritten) zip.file(name, xml)
  // Unchanged deflated parts are copied without inflating them again.
  return zip.generateAsync({ type: 'arraybuffer', compression: 'DEFLATE' })
}

/**
 * The parts of the same default-deny rebuild, for reading their text (S11h Spec §2.2): it follows
 * speaker notes too, and keeps grouped graphic frames, which only the renderer cannot take.
 */
export async function readOfficePackage(
  data: ArrayBuffer, format: OfficeFormat, limits: OfficePackageLimits = OFFICE_PACKAGE_LIMITS,
): Promise<OfficeParts> {
  const { keep, main, links, part, read } = await rebuild(data, format, TEXT_POLICIES[format], limits)
  return {
    main,
    async text(name) {
      const file = part(name)
      return file && keep.has(file.name) ? read(file.name) : null
    },
    related: source => [...(links.get(source) ?? [])],
  }
}

async function rebuild(
  data: ArrayBuffer, format: OfficeFormat, policy: FormatPolicy, limits: OfficePackageLimits,
): Promise<Rebuilt> {
  // Matched case-insensitively, written back in the spelling the renderers compare literally.
  const allowed = new Map([...policy.contentTypes].map(type => [type.toLowerCase(), type]))
  if (data.byteLength > limits.bytes) throw rejected('size')
  let directory: ZipEntry[]
  try {
    directory = readZipDirectory(data, limits.entries)
  } catch (error) {
    if (error instanceof ZipDirectoryRejected) throw rejected(error.problem)
    throw error
  }
  if (directory.reduce((sum, entry) => sum + entry.size, 0) > limits.inflated) throw rejected('size')
  let zip: JSZip
  try {
    // Without implied folders, JSZip's table holds exactly one object per directory record.
    zip = await JSZip.loadAsync(data, { createFolders: false })
  } catch {
    throw rejected('package')
  }
  // Use only what was checked: the library's table must be the checked directory, entry for entry.
  const loaded = Object.keys(zip.files)
  if (loaded.length !== directory.length
    || directory.some(entry => zip.files[entry.name]?.dir !== entry.directory)) throw rejected('structure')
  const entries = Object.values(zip.files).filter(file => !file.dir)
  let budget = limits.inflated
  for (const file of entries) budget -= await inflatedSize(file, budget)

  // The directory check refused names that differ only in case, so this lookup is unambiguous.
  const byName = new Map(entries.map(file => [file.name.toLowerCase(), file]))
  const part = (name: string) => zip.file(name) ?? byName.get(name.toLowerCase()) ?? null
  const text = async (file: JSZip.JSZipObject) => {
    try {
      return await file.async('string')
    } catch {
      throw rejected('package')
    }
  }

  const typesFile = part(CONTENT_TYPES)
  if (!typesFile) throw rejected('structure')
  const typesXml = await text(typesFile)
  const defaults = new Map(elements(typesXml, 'Default')
    .filter(d => d.Extension && d.ContentType).map(d => [d.Extension.toLowerCase(), d.ContentType]))
  const overrides = new Map(elements(typesXml, 'Override')
    .filter(o => o.PartName && o.ContentType).map(o => [o.PartName.replace(/^\/+/, '').toLowerCase(), o.ContentType]))
  /** The allowed content type of a part, or null when it has none the renderer reads. */
  const contentType = (name: string) =>
    allowed.get((overrides.get(name.toLowerCase()) ?? defaults.get(extension(name)) ?? '').split(';')[0].trim().toLowerCase()) ?? null

  // Walk relationships from the package root, default-deny: a relationship stays only if the
  // renderer follows its type and reads its target's content type; nothing else is reached.
  const keep = new Set<string>([typesFile.name])
  const rewritten = new Map<string, string>()
  const links = new Map<string, OfficePartLink[]>()
  const queue = ['']
  let main: { name: string; kept: Set<string> } | null = null
  while (queue.length) {
    const source = queue.shift()!
    const relsFile = part(source ? relationshipsPart(source) : '_rels/.rels')
    if (!relsFile) continue
    keep.add(relsFile.name)
    const kept: Relationship[] = []
    const internal: OfficePartLink[] = []
    let mainName: string | null = null
    for (const rel of elements(await text(relsFile), 'Relationship')) {
      const relationship = {
        id: rel.Id ?? '', type: rel.Type ?? '', target: rel.Target ?? '', external: rel.TargetMode?.toLowerCase() === 'external',
      }
      if (!relationship.id || !policy.relationships.has(relationship.type)) continue
      if (relationship.external) {
        // External targets are fetched by the renderer (a leaked request) or embed another file;
        // only links the reader may follow stay.
        if (relationship.type === HYPERLINK && followable(relationship.target)) kept.push(relationship)
        continue
      }
      const name = resolve(source, relationship.target)
      const file = name ? part(name) : null
      if (!file || !contentType(file.name)) continue
      kept.push(relationship)
      internal.push({ id: relationship.id, type: relationship.type, name: file.name })
      if (!source && relationship.type.endsWith('/officeDocument')) {
        if (mainName !== null) throw rejected('structure')
        mainName = file.name
      }
      if (!keep.has(file.name)) {
        keep.add(file.name)
        queue.push(file.name)
      }
    }
    links.set(source, internal)
    if (!source) {
      if (!mainName || contentType(mainName) !== policy.main) throw rejected('structure')
      main = { name: mainName, kept: new Set() }
    } else if (source === main?.name) {
      main.kept = new Set(kept.map(rel => rel.id))
    }
    rewritten.set(relsFile.name, `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="${RELATIONSHIPS_NS}">`
      + kept.map(rel => `<Relationship Id="${escapeAttribute(rel.id)}" Type="${escapeAttribute(rel.type)}" `
        + `Target="${escapeAttribute(rel.target)}"${rel.external ? ' TargetMode="External"' : ''}/>`).join('')
      + '</Relationships>')
  }
  if (!main) throw rejected('structure')

  // Slides, slide masters and sheets the main part lists through a relationship must have survived:
  // the renderer would otherwise read a document with holes. Elements that name no relationship
  // (a section's slide list holds slide ids only) refer to nothing here.
  if (policy.required.length) {
    const mainXml = await text(part(main.name)!)
    for (const element of policy.required) {
      for (const attributes of elements(mainXml, element)) {
        const id = Object.entries(attributes).find(([key]) => /^[\w.-]+:id$/.test(key))?.[1]
        if (id !== undefined && !main.kept.has(id)) throw rejected('structure')
      }
    }
  }

  // altChunk elements are body content, not blocks: upstream counts only paragraphs and tables,
  // so removing them leaves every cited block number unchanged.
  if (format === 'docx') {
    for (const name of keep) {
      if (!contentType(name)?.includes('wordprocessingml')) continue
      const xml = await text(part(name)!)
      if (!xml.includes('altChunk')) continue
      const clean = xml.replace(ALT_CHUNK, '')
      if (ALT_CHUNK_LEFT.test(clean)) throw rejected('structure')
      rewritten.set(name, clean)
    }
  }

  // Every kept part is declared again with its allowed type; nothing else is declared.
  const declaredParts = [...keep].filter(name => name !== typesFile.name && !name.toLowerCase().endsWith('.rels'))
  rewritten.set(typesFile.name, `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="${CONTENT_TYPES_NS}">`
    + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    + declaredParts.map(name => `<Override PartName="/${escapeAttribute(name)}" ContentType="${escapeAttribute(contentType(name)!)}"/>`).join('')
    + '</Types>')

  const read = async (name: string) => rewritten.get(name) ?? text(part(name)!)
  return { zip, entries, keep, rewritten, main: main.name, links, part, contentType, read }
}
