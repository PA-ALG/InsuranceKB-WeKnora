// S11e (Spec §3.2a, review R1): an Office package reaches the renderer only after an allow-list
// rebuild — no embedded HTML, code, controls or external fetches — and anything unreadable is refused.
import JSZip from 'jszip'
import { describe, expect, it, vi } from 'vitest'
import { rawZip } from './__tests__/rawZip'
import { OFFICE_PACKAGE_LIMITS, OfficePackageRejected, sanitizeOfficePackage } from './officePackage'

const REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const MS_REL = 'http://schemas.microsoft.com/office/2006/relationships'
const OOXML = 'application/vnd.openxmlformats-officedocument'
const W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const MAIN = {
  docx: `${OOXML}.wordprocessingml.document.main+xml`,
  pptx: `${OOXML}.presentationml.presentation.main+xml`,
  xlsx: `${OOXML}.spreadsheetml.sheet.main+xml`,
}

type Rel = [id: string, type: string, target: string, external?: boolean]
interface Spec {
  parts: Record<string, string | Uint8Array>
  rels: Record<string, Rel[]>
  overrides: Record<string, string>
  defaults?: Record<string, string>
}

function relsXml(list: Rel[]): string {
  return `<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${list
    .map(([id, type, target, external]) => `<Relationship Id="${id}" Type="${type}" Target="${target}"${external ? ' TargetMode="External"' : ''}/>`)
    .join('')}</Relationships>`
}

function relsName(part: string): string {
  if (!part) return '_rels/.rels'
  const slash = part.lastIndexOf('/')
  return `${part.slice(0, slash + 1)}_rels/${part.slice(slash + 1)}.rels`
}

async function build(spec: Spec, extra: (zip: JSZip) => void = () => {}): Promise<ArrayBuffer> {
  const zip = new JSZip()
  const defaults = { rels: 'application/vnd.openxmlformats-package.relationships+xml', xml: 'application/xml', png: 'image/png', ...spec.defaults }
  zip.file('[Content_Types].xml', `<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">${
    Object.entries(defaults).map(([ext, type]) => `<Default Extension="${ext}" ContentType="${type}"/>`).join('')}${
    Object.entries(spec.overrides).map(([part, type]) => `<Override PartName="/${part}" ContentType="${type}"/>`).join('')}</Types>`)
  for (const [source, list] of Object.entries(spec.rels)) zip.file(relsName(source), relsXml(list))
  for (const [name, data] of Object.entries(spec.parts)) zip.file(name, data)
  extra(zip)
  return zip.generateAsync({ type: 'arraybuffer', compression: 'DEFLATE' })
}

const BODY = `<w:p><w:r><w:t>第一段</w:t></w:r></w:p><w:p/><w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>被引段</w:t></w:r></w:p>`
const PNG = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3])

function docx(body = BODY, more: Partial<Spec> = {}): Spec {
  return {
    parts: {
      'word/document.xml': `<?xml version="1.0"?><w:document xmlns:w="${W}" xmlns:r="${REL}"><w:body>${body}</w:body></w:document>`,
      'word/styles.xml': `<w:styles xmlns:w="${W}"/>`,
      'word/media/image1.png': PNG,
      'docProps/core.xml': '<cp:coreProperties xmlns:cp="urn:core"/>',
      ...more.parts,
    },
    rels: {
      '': [['rId1', `${REL}/officeDocument`, 'word/document.xml'], ['rId2', 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties', 'docProps/core.xml']],
      'word/document.xml': [['rIdS', `${REL}/styles`, 'styles.xml'], ['rIdI', `${REL}/image`, 'media/image1.png']],
      ...more.rels,
    },
    overrides: {
      'word/document.xml': MAIN.docx, 'word/styles.xml': `${OOXML}.wordprocessingml.styles+xml`,
      'docProps/core.xml': 'application/vnd.openxmlformats-package.core-properties+xml', ...more.overrides,
    },
    defaults: more.defaults,
  }
}

function withDocRels(spec: Spec, extra: Rel[]): Spec {
  return { ...spec, rels: { ...spec.rels, 'word/document.xml': [...spec.rels['word/document.xml'], ...extra] } }
}

async function rebuilt(input: ArrayBuffer, format: 'docx' | 'pptx' | 'xlsx' = 'docx') {
  const zip = await JSZip.loadAsync(await sanitizeOfficePackage(input, format))
  const names = Object.values(zip.files).filter(f => !f.dir).map(f => f.name).sort()
  const text = (name: string) => zip.file(name)!.async('string')
  const relIds = async (source: string) => [...(await text(relsName(source))).matchAll(/Id="([^"]+)"/g)].map(m => m[1])
  return { zip, names, text, relIds }
}

async function rejection(input: ArrayBuffer, format: 'docx' | 'pptx' | 'xlsx' = 'docx', limits = OFFICE_PACKAGE_LIMITS) {
  try {
    await sanitizeOfficePackage(input, format, limits)
  } catch (error) {
    expect(error).toBeInstanceOf(OfficePackageRejected)
    return (error as OfficePackageRejected).problem
  }
  throw new Error('the package was accepted')
}

describe('an ordinary package', () => {
  it('keeps every reachable DOCX part, byte for byte', async () => {
    const out = await rebuilt(await build(docx()))
    expect(out.names).toEqual([
      '[Content_Types].xml', '_rels/.rels', 'docProps/core.xml', 'word/_rels/document.xml.rels',
      'word/document.xml', 'word/media/image1.png', 'word/styles.xml',
    ])
    expect(await out.text('word/document.xml')).toBe(docx().parts['word/document.xml'])
    expect([...await out.zip.file('word/media/image1.png')!.async('uint8array')]).toEqual([...PNG])
    expect(await out.relIds('word/document.xml')).toEqual(['rIdS', 'rIdI'])
    const types = await out.text('[Content_Types].xml')
    expect(types).toContain(`<Override PartName="/word/document.xml" ContentType="${MAIN.docx}"/>`)
    expect(types).toContain('<Override PartName="/word/media/image1.png" ContentType="image/png"/>')
  })

  it('keeps a deck and a workbook', async () => {
    const deck = await rebuilt(await build({
      parts: { 'ppt/presentation.xml': '<p:presentation/>', 'ppt/slides/slide1.xml': '<p:sld>幻灯片</p:sld>' },
      rels: { '': [['rId1', `${REL}/officeDocument`, 'ppt/presentation.xml']], 'ppt/presentation.xml': [['rId2', `${REL}/slide`, 'slides/slide1.xml']] },
      overrides: { 'ppt/presentation.xml': MAIN.pptx, 'ppt/slides/slide1.xml': `${OOXML}.presentationml.slide+xml` },
    }), 'pptx')
    expect(deck.names).toContain('ppt/slides/slide1.xml')
    expect(await deck.text('ppt/slides/slide1.xml')).toBe('<p:sld>幻灯片</p:sld>')
    const book = await rebuilt(await build({
      parts: { 'xl/workbook.xml': '<workbook/>', 'xl/worksheets/sheet1.xml': '<worksheet>行</worksheet>' },
      rels: { '': [['rId1', `${REL}/officeDocument`, 'xl/workbook.xml']], 'xl/workbook.xml': [['rId2', `${REL}/worksheet`, 'worksheets/sheet1.xml']] },
      overrides: { 'xl/workbook.xml': MAIN.xlsx, 'xl/worksheets/sheet1.xml': `${OOXML}.spreadsheetml.worksheet+xml` },
    }), 'xlsx')
    expect(await book.text('xl/worksheets/sheet1.xml')).toBe('<worksheet>行</worksheet>')
  })
})

describe('active and foreign content', () => {
  it('removes altChunk elements, their relationships and their HTML, leaving every block in place', async () => {
    // A quoted '>' inside an attribute does not end the element.
    const chunk = '<w:altChunk r:id="rIdHtml" w:note="a>b"/>'
    const header = `<w:hdr xmlns:w="${W}" xmlns:r="${REL}"><w:altChunk r:id="rIdHead"><w:altChunkPr><w:matchSrc/></w:altChunkPr></w:altChunk><w:p/></w:hdr>`
    const spec = docx(BODY.replace('<w:tbl>', `${chunk}<w:tbl>`) + chunk, {
      parts: { 'word/chunk.html': '<script>parent.x=1</script>', 'word/header1.xml': header, 'word/head.html': '<script/>' },
      rels: { 'word/header1.xml': [['rIdHead', `${REL}/aFChunk`, 'head.html']] },
      overrides: { 'word/chunk.html': 'text/html', 'word/header1.xml': `${OOXML}.wordprocessingml.header+xml` },
    })
    const out = await rebuilt(await build(withDocRels(spec, [
      ['rIdHtml', `${REL}/aFChunk`, 'chunk.html'], ['rIdH', `${REL}/header`, 'header1.xml'],
    ])))
    const document = await out.text('word/document.xml')
    expect(document).toBe(docx().parts['word/document.xml'])
    expect(await out.text('word/header1.xml')).toBe(`<w:hdr xmlns:w="${W}" xmlns:r="${REL}"><w:p/></w:hdr>`)
    expect(out.names).not.toContain('word/chunk.html')
    expect(out.names).not.toContain('word/head.html')
    expect(await out.relIds('word/document.xml')).toEqual(['rIdS', 'rIdI', 'rIdH'])
    expect(await out.relIds('word/header1.xml')).toEqual([])
    expect(await out.text('[Content_Types].xml')).not.toContain('html')
  })

  it.each([
    ['an OLE object', `${REL}/oleObject`, 'embeddings/oleObject1.bin', `${OOXML}.oleObject`],
    ['an ActiveX control', `${REL}/control`, 'activeX/activeX1.xml', 'application/vnd.ms-office.activeX+xml'],
    ['an ActiveX binary', `${MS_REL}/activeXControlBinary`, 'activeX/activeX1.bin', 'application/vnd.ms-office.activeX'],
    ['a VBA project', `${MS_REL}/vbaProject`, 'vbaProject.bin', 'application/vnd.ms-office.vbaProject'],
    ['VBA data', `${MS_REL}/wordVbaData`, 'vbaData.xml', 'application/vnd.ms-word.vbaData+xml'],
    ['key customizations', `${MS_REL}/keyMapCustomizations`, 'customizations.xml', 'application/vnd.ms-word.keyMapCustomizations+xml'],
    ['toolbars', `${MS_REL}/attachedToolbars`, 'attachedToolbars.bin', 'application/vnd.ms-word.attachedToolbars'],
    ['a UI extension', 'http://schemas.microsoft.com/office/2007/relationships/ui/extensibility', 'customUI.xml', 'application/xml'],
    ['an internal template', `${REL}/attachedTemplate`, 'template.dotx', 'application/xml'],
    ['a frame', `${REL}/frame`, 'frame.xml', 'application/xml'],
    ['a subdocument', `${REL}/subDocument`, 'sub.docx', 'application/xml'],
  ])('drops %s and the part it points to', async (_name, type, target, contentType) => {
    const part = `word/${target}`
    const spec = docx(BODY, { parts: { [part]: 'payload' }, overrides: { [part]: contentType } })
    const out = await rebuilt(await build(withDocRels(spec, [['rIdX', type, target]])))
    expect(out.names).not.toContain(part)
    expect(await out.relIds('word/document.xml')).toEqual(['rIdS', 'rIdI'])
    expect(await out.text('[Content_Types].xml')).not.toContain(part)
  })

  it.each([
    ['an external image (a leaked request)', `${REL}/image`, 'https://tracker.example/pixel.png', false],
    ['an external template', `${REL}/attachedTemplate`, 'https://example.com/t.dotm', false],
    ['an external subdocument', `${REL}/subDocument`, 'file:///c:/x.docx', false],
    ['a script link', `${REL}/hyperlink`, 'javascript:parent.x=1', false],
    ['a script link with a tab', `${REL}/hyperlink`, 'java&#9;script:parent.x=1', false],
    ['a data link', `${REL}/hyperlink`, 'data:text/html,x', false],
    ['a relative link', `${REL}/hyperlink`, 'other.docx', false],
    ['a web link', `${REL}/hyperlink`, 'https://example.com/a?b=1&amp;c=2', true],
    ['a mail link', `${REL}/hyperlink`, 'mailto:a@example.com', true],
  ])('decides on %s', async (_name, type, target, kept) => {
    const out = await rebuilt(await build(withDocRels(docx(), [['rIdE', type, target, true]])))
    expect((await out.relIds('word/document.xml')).includes('rIdE')).toBe(kept)
  })

  it.each([
    ['an HTML part reached as an image', 'media/page.html', { 'word/media/page.html': 'text/html' }, {}],
    ['an MHT part by its extension', 'media/page.mht', {}, {}],
    ['an XHTML part by its type', 'media/page.xml', { 'word/media/page.xml': 'application/xhtml+xml' }, {}],
    ['a binary part', 'media/printer.bin', {}, { bin: 'application/octet-stream' }],
  ])('drops %s', async (_name, target, overrides, defaults) => {
    const part = `word/${target}`
    const spec = docx(BODY, { parts: { [part]: '<script>parent.x=1</script>' }, overrides, defaults })
    const out = await rebuilt(await build(withDocRels(spec, [['rIdM', `${REL}/image`, target]])))
    expect(out.names).not.toContain(part)
    expect(await out.relIds('word/document.xml')).toEqual(['rIdS', 'rIdI'])
  })

  it('drops parts no kept relationship reaches', async () => {
    const out = await rebuilt(await build(docx(BODY, { parts: { 'word/orphan.xml': '<x/>', 'evil/page.html': '<script/>' } })))
    expect(out.names).not.toContain('word/orphan.xml')
    expect(out.names).not.toContain('evil/page.html')
  })

  it('drops OLE, controls, macros and external media from a deck, and external links and macros from a workbook', async () => {
    const deck = await rebuilt(await build({
      parts: {
        'ppt/presentation.xml': '<p:presentation/>', 'ppt/slides/slide1.xml': '<p:sld/>', 'ppt/vbaProject.bin': 'vba',
        'ppt/embeddings/oleObject1.bin': 'ole', 'ppt/activeX/activeX1.xml': '<ax/>',
      },
      rels: {
        '': [['rId1', `${REL}/officeDocument`, 'ppt/presentation.xml']],
        'ppt/presentation.xml': [['rId2', `${REL}/slide`, 'slides/slide1.xml'], ['rId3', `${MS_REL}/vbaProject`, 'vbaProject.bin']],
        'ppt/slides/slide1.xml': [
          ['rId4', `${REL}/oleObject`, '../embeddings/oleObject1.bin'], ['rId5', `${REL}/control`, '../activeX/activeX1.xml'],
          ['rId6', `${REL}/video`, 'https://example.com/v.mp4', true], ['rId7', `${REL}/hyperlink`, 'https://example.com/', true],
        ],
      },
      overrides: { 'ppt/presentation.xml': MAIN.pptx, 'ppt/slides/slide1.xml': `${OOXML}.presentationml.slide+xml` },
    }), 'pptx')
    expect(deck.names).toEqual(['[Content_Types].xml', '_rels/.rels', 'ppt/_rels/presentation.xml.rels',
      'ppt/presentation.xml', 'ppt/slides/_rels/slide1.xml.rels', 'ppt/slides/slide1.xml'])
    // The deck renderer follows no hyperlinks, so even a web link is not kept.
    expect(await deck.relIds('ppt/slides/slide1.xml')).toEqual([])
    const book = await rebuilt(await build({
      parts: { 'xl/workbook.xml': '<workbook/>', 'xl/externalLinks/externalLink1.xml': '<externalLink/>', 'xl/vbaProject.bin': 'vba' },
      rels: {
        '': [['rId1', `${REL}/officeDocument`, 'xl/workbook.xml']],
        'xl/workbook.xml': [['rId2', `${REL}/externalLink`, 'externalLinks/externalLink1.xml'], ['rId3', `${MS_REL}/vbaProject`, 'vbaProject.bin']],
      },
      overrides: { 'xl/workbook.xml': MAIN.xlsx },
    }), 'xlsx')
    expect(book.names).toEqual(['[Content_Types].xml', '_rels/.rels', 'xl/_rels/workbook.xml.rels', 'xl/workbook.xml'])
  })
})

describe('default deny', () => {
  it.each([
    ['custom XML', `${REL}/customXml`, 'item1.xml', 'application/xml'],
    ['an unknown type to an allowed image', 'urn:example:relationships/thing', 'media/thing.png', 'image/png'],
    ['a stylesWithEffects part the renderer does not load', 'http://schemas.microsoft.com/office/2007/relationships/stylesWithEffects', 'stylesWithEffects.xml', `${OOXML}.wordprocessingml.styles+xml`],
  ])('drops a relationship type outside the list: %s', async (_name, type, target, contentType) => {
    const part = `word/${target}`
    const spec = docx(BODY, { parts: { [part]: '<x/>' }, overrides: { [part]: contentType } })
    const out = await rebuilt(await build(withDocRels(spec, [['rIdU', type, target]])))
    expect(out.names).not.toContain(part)
    expect(await out.relIds('word/document.xml')).toEqual(['rIdS', 'rIdI'])
  })

  it.each([
    ['outside the list', { 'word/styles.xml': 'application/xml' }, {}],
    ['missing', {}, { xml: '' }],
  ])('drops a part whose content type is %s, with its relationship', async (_name, overrides, defaults) => {
    const spec = docx()
    const base = { ...spec.overrides }
    delete base['word/styles.xml']
    const out = await rebuilt(await build({ ...spec, overrides: { ...base, ...overrides }, defaults: { xml: 'application/xml', ...defaults } }))
    expect(out.names).not.toContain('word/styles.xml')
    expect(await out.relIds('word/document.xml')).toEqual(['rIdI'])
  })

  it('drops a part no content type names', async () => {
    const spec = docx(BODY, { parts: { 'word/media/picture.dat': PNG } })
    const out = await rebuilt(await build(withDocRels(spec, [['rIdD', `${REL}/image`, 'media/picture.dat']])))
    expect(out.names).not.toContain('word/media/picture.dat')
  })

  it('writes content types back in the spelling the renderers compare', async () => {
    const out = await rebuilt(await build({
      parts: { 'ppt/presentation.xml': '<p:presentation/>', 'ppt/slideMasters/slideMaster1.xml': '<p:sldMaster/>' },
      rels: { '': [['rId1', `${REL}/officeDocument`, 'ppt/presentation.xml']], 'ppt/presentation.xml': [['rId2', `${REL}/slideMaster`, 'slideMasters/slideMaster1.xml']] },
      overrides: { 'ppt/presentation.xml': MAIN.pptx.toUpperCase(), 'ppt/slideMasters/slideMaster1.xml': `${OOXML}.presentationml.slidemaster+xml` },
    }), 'pptx')
    const types = await out.text('[Content_Types].xml')
    expect(types).toContain(`ContentType="${OOXML}.presentationml.slideMaster+xml"`)
    expect(types).toContain(`ContentType="${MAIN.pptx}"`)
  })

  const STRICT = 'http://purl.oclc.org/ooxml/officeDocument/relationships'

  it('reads a Strict workbook, which the sheet renderer supports', async () => {
    const out = await rebuilt(await build({
      parts: { 'xl/workbook.xml': '<workbook><sheets><sheet name="A" sheetId="1" r:id="rId2"/></sheets></workbook>', 'xl/worksheets/sheet1.xml': '<worksheet/>' },
      rels: { '': [['rId1', `${STRICT}/officeDocument`, 'xl/workbook.xml']], 'xl/workbook.xml': [['rId2', `${STRICT}/worksheet`, 'worksheets/sheet1.xml']] },
      overrides: { 'xl/workbook.xml': MAIN.xlsx, 'xl/worksheets/sheet1.xml': `${OOXML}.spreadsheetml.worksheet+xml` },
    }), 'xlsx')
    expect(out.names).toContain('xl/worksheets/sheet1.xml')
  })

  it('refuses a Strict document or deck, which their renderers do not read', async () => {
    const strict = docx()
    expect(await rejection(await build({ ...strict, rels: { ...strict.rels, '': [['rId1', `${STRICT}/officeDocument`, 'word/document.xml']] } }))).toBe('structure')
    expect(await rejection(await build({
      parts: { 'ppt/presentation.xml': '<p:presentation/>' },
      rels: { '': [['rId1', `${STRICT}/officeDocument`, 'ppt/presentation.xml']] },
      overrides: { 'ppt/presentation.xml': MAIN.pptx },
    }), 'pptx')).toBe('structure')
  })

  it.each([
    ['a slide the deck lists', 'pptx', 'ppt/presentation.xml', '<p:presentation><p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst></p:presentation>',
      `${REL}/slide`, 'ppt/slides/slide1.xml', 'application/xml'],
    ['a slide master the deck lists', 'pptx', 'ppt/presentation.xml', '<p:presentation><p:sldMasterIdLst><p:sldMasterId id="1" r:id="rId2"/></p:sldMasterIdLst></p:presentation>',
      'urn:example:relationships/slideMaster', 'ppt/slideMasters/slideMaster1.xml', `${OOXML}.presentationml.slideMaster+xml`],
    ['a macro sheet the workbook lists', 'xlsx', 'xl/workbook.xml', '<workbook><sheets><sheet name="M" sheetId="1" r:id="rId2"/></sheets></workbook>',
      'http://schemas.microsoft.com/office/2006/relationships/xlMacrosheet', 'xl/macrosheets/sheet1.xml', 'application/vnd.ms-excel.macrosheet+xml'],
  ])('refuses a package that loses %s', async (_name, format, mainPart, mainXml, type, target, contentType) => {
    const input = await build({
      parts: { [mainPart]: mainXml, [target]: '<x/>' },
      rels: { '': [['rId1', `${REL}/officeDocument`, mainPart]], [mainPart]: [['rId2', type, target.slice(target.indexOf('/') + 1)]] },
      overrides: { [mainPart]: MAIN[format as 'pptx' | 'xlsx'], [target]: contentType },
    })
    expect(await rejection(input, format as 'pptx' | 'xlsx')).toBe('structure')
  })

  it('keeps a deck whose listed slides all survive; a section list names slides by id only', async () => {
    const sections = '<p:extLst><p:ext><p14:sectionLst><p14:section name="A"><p14:sldIdLst><p14:sldId id="256"/></p14:sldIdLst></p14:section></p14:sectionLst></p:ext></p:extLst>'
    const out = await rebuilt(await build({
      parts: { 'ppt/presentation.xml': `<p:presentation><p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>${sections}</p:presentation>`, 'ppt/slides/slide1.xml': '<p:sld/>' },
      rels: { '': [['rId1', `${REL}/officeDocument`, 'ppt/presentation.xml']], 'ppt/presentation.xml': [['rId2', `${REL}/slide`, 'slides/slide1.xml']] },
      overrides: { 'ppt/presentation.xml': MAIN.pptx, 'ppt/slides/slide1.xml': `${OOXML}.presentationml.slide+xml` },
    }), 'pptx')
    expect(out.names).toContain('ppt/slides/slide1.xml')
  })
})

describe('the zip library sees only the checked directory', () => {
  it('reads a package that has no folder records', async () => {
    const input = rawZip([
      { name: '[Content_Types].xml', data: `<Types><Override PartName="/word/document.xml" ContentType="${MAIN.docx}"/></Types>` },
      { name: '_rels/.rels', data: relsXml([['rId1', `${REL}/officeDocument`, 'word/document.xml']]) },
      { name: 'word/document.xml', data: `<w:document xmlns:w="${W}"><w:body><w:p/></w:body></w:document>` },
    ])
    const out = await rebuilt(input)
    expect(out.names).toEqual(['[Content_Types].xml', '_rels/.rels', 'word/document.xml'])
  })

  it.each([
    ['an extra entry', (zip: JSZip) => { zip.file('word/extra.xml', '<x/>', { createFolders: false }) }],
    ['a missing entry', (zip: JSZip) => { zip.remove('word/styles.xml') }],
    ['a file loaded as a folder', (zip: JSZip) => { zip.remove('word/styles.xml'); zip.folder('word/styles.xml') }],
  ])('refuses a loaded table with %s', async (_name, change) => {
    const load = JSZip.loadAsync.bind(JSZip)
    const spy = vi.spyOn(JSZip, 'loadAsync').mockImplementation(async (...args: Parameters<typeof JSZip.loadAsync>) => {
      const zip = await load(...args)
      change(zip)
      return zip
    })
    try {
      expect(await rejection(await build(docx()))).toBe('structure')
    } finally {
      spy.mockRestore()
    }
  })
})

describe('what cannot be read is refused', () => {
  it('refuses bytes that are not a package', async () => {
    expect(await rejection(new Uint8Array([80, 75, 3, 4, 1, 2]).buffer)).toBe('package')
  })

  it('refuses an encrypted zip', async () => {
    const bytes = new Uint8Array(await build(docx()))
    const view = new DataView(bytes.buffer)
    for (let i = 0; i + 4 <= bytes.length; i++) {
      if (view.getUint32(i, true) === 0x04034b50) bytes[i + 6] |= 1
      if (view.getUint32(i, true) === 0x02014b50) bytes[i + 8] |= 1
    }
    expect(await rejection(bytes.buffer)).toBe('package')
  })

  it('refuses a package over the byte, entry or inflated limit', async () => {
    const input = await build(docx())
    expect(await rejection(input, 'docx', { ...OFFICE_PACKAGE_LIMITS, bytes: input.byteLength - 1 })).toBe('size')
    expect(await rejection(input, 'docx', { ...OFFICE_PACKAGE_LIMITS, entries: 3 })).toBe('size')
    const bomb = await build(docx(), zip => { zip.file('word/media/zeros.png', new Uint8Array(1 << 20)) })
    expect(bomb.byteLength).toBeLessThan(1 << 16)
    expect(await rejection(bomb, 'docx', { ...OFFICE_PACKAGE_LIMITS, inflated: 1 << 19 })).toBe('size')
  })

  it.each([
    ['no content types', (spec: Spec) => spec, (zip: JSZip) => { zip.remove('[Content_Types].xml') }],
    ['no main part', (spec: Spec) => ({ ...spec, rels: { ...spec.rels, '': [] } }), () => {}],
    ['two main parts', (spec: Spec) => ({ ...spec, rels: { ...spec.rels, '': [...spec.rels[''], ['rId9', `${REL}/officeDocument`, 'word/styles.xml'] as Rel] } }), () => {}],
    ['a macro-enabled main part', (spec: Spec) => ({ ...spec, overrides: { ...spec.overrides, 'word/document.xml': 'application/vnd.ms-word.document.macroEnabled.main+xml' } }), () => {}],
    ['names that differ only in case', (spec: Spec) => spec, (zip: JSZip) => { zip.file('WORD/Document.xml', '<x/>') }],
    ['an altChunk that cannot be removed', (spec: Spec) => ({ ...spec, parts: { ...spec.parts, 'word/document.xml': `<w:document xmlns:w="${W}"><w:body><w:altChunk r:id="a"><w:p/></w:body></w:document>` } }), () => {}],
  ])('refuses a package with %s', async (_name, change, extra) => {
    expect(await rejection(await build(change(docx()), extra))).toBe('structure')
  })

  it('refuses a document opened as another format', async () => {
    expect(await rejection(await build(docx()), 'pptx')).toBe('structure')
  })
})
