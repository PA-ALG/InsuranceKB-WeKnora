// Synthetic Office files and S11d citation responses for the S11e browser check. Every byte is
// generated here; no business document is read or embedded.
import JSZip from 'jszip'
import * as XLSX from 'xlsx'

const NS = {
  a: 'http://schemas.openxmlformats.org/drawingml/2006/main',
  r: 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
  p: 'http://schemas.openxmlformats.org/presentationml/2006/main',
  rel: 'http://schemas.openxmlformats.org/package/2006/relationships',
  types: 'http://schemas.openxmlformats.org/package/2006/content-types',
  w: 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
}
const REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const PML = 'application/vnd.openxmlformats-officedocument.presentationml'
const XMLNS = `xmlns:a="${NS.a}" xmlns:r="${NS.r}" xmlns:p="${NS.p}"`
const GROUP = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'

function rels(entries: [string, string, string][]): string {
  return `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="${NS.rel}">${entries
    .map(([id, type, target]) => `<Relationship Id="${id}" Type="${REL}/${type}" Target="${target}"/>`).join('')}</Relationships>`
}

function textBox(id: number, paragraphs: string[]): string {
  const body = paragraphs.map(text => `<a:p><a:r><a:rPr lang="zh-CN" sz="2400"/><a:t>${text}</a:t></a:r></a:p>`).join('')
  return `<p:sp><p:nvSpPr><p:cNvPr id="${id}" name="Text ${id}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>`
    + '<p:spPr><a:xfrm><a:off x="457200" y="457200"/><a:ext cx="8229600" cy="2743200"/></a:xfrm>'
    + '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
    + `<p:txBody><a:bodyPr wrap="square"/><a:lstStyle/>${body}</p:txBody></p:sp>`
}

const THEME = `<?xml version="1.0" encoding="UTF-8"?><a:theme xmlns:a="${NS.a}" name="Synthetic"><a:themeElements>`
  + '<a:clrScheme name="Synthetic"><a:dk1><a:srgbClr val="000000"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
  + '<a:dk2><a:srgbClr val="1F497D"/></a:dk2><a:lt2><a:srgbClr val="EEECE1"/></a:lt2>'
  + ['4F81BD', 'C0504D', '9BBB59', '8064A2', '4BACC6', 'F79646'].map((c, i) => `<a:accent${i + 1}><a:srgbClr val="${c}"/></a:accent${i + 1}>`).join('')
  + '<a:hlink><a:srgbClr val="0000FF"/></a:hlink><a:folHlink><a:srgbClr val="800080"/></a:folHlink></a:clrScheme>'
  + '<a:fontScheme name="Synthetic"><a:majorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
  + '<a:minorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
  + '<a:fmtScheme name="Synthetic">'
  + `<a:fillStyleLst>${'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'.repeat(3)}</a:fillStyleLst>`
  + `<a:lnStyleLst>${'<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'.repeat(3)}</a:lnStyleLst>`
  + `<a:effectStyleLst>${'<a:effectStyle><a:effectLst/></a:effectStyle>'.repeat(3)}</a:effectStyleLst>`
  + `<a:bgFillStyleLst>${'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'.repeat(3)}</a:bgFillStyleLst>`
  + '</a:fmtScheme></a:themeElements></a:theme>'

/** A deck whose slides hold the given paragraphs, in presentation order. */
export async function pptxFixture(slides: string[][]): Promise<Blob> {
  const zip = new JSZip()
  const overrides = [
    ['/ppt/presentation.xml', `${PML}.presentation.main+xml`],
    ['/ppt/slideMasters/slideMaster1.xml', `${PML}.slideMaster+xml`],
    ['/ppt/slideLayouts/slideLayout1.xml', `${PML}.slideLayout+xml`],
    ['/ppt/theme/theme1.xml', 'application/vnd.openxmlformats-officedocument.theme+xml'],
    ...slides.map((_, i) => [`/ppt/slides/slide${i + 1}.xml`, `${PML}.slide+xml`]),
  ]
  zip.file('[Content_Types].xml', `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="${NS.types}">`
    + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    + '<Default Extension="xml" ContentType="application/xml"/>'
    + overrides.map(([part, type]) => `<Override PartName="${part}" ContentType="${type}"/>`).join('') + '</Types>')
  zip.file('_rels/.rels', rels([['rId1', 'officeDocument', 'ppt/presentation.xml']]))
  zip.file('ppt/presentation.xml', `<?xml version="1.0" encoding="UTF-8"?><p:presentation ${XMLNS}>`
    + '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
    + `<p:sldIdLst>${slides.map((_, i) => `<p:sldId id="${256 + i}" r:id="rId${i + 3}"/>`).join('')}</p:sldIdLst>`
    + '<p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>'
    // Office always writes a default text style; the renderer reads it.
    + '<p:defaultTextStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:defaultTextStyle></p:presentation>')
  zip.file('ppt/_rels/presentation.xml.rels', rels([
    ['rId1', 'slideMaster', 'slideMasters/slideMaster1.xml'],
    ['rId2', 'theme', 'theme/theme1.xml'],
    ...slides.map((_, i) => [`rId${i + 3}`, 'slide', `slides/slide${i + 1}.xml`] as [string, string, string]),
  ]))
  zip.file('ppt/theme/theme1.xml', THEME)
  zip.file('ppt/slideMasters/slideMaster1.xml', `<?xml version="1.0" encoding="UTF-8"?><p:sldMaster ${XMLNS}>`
    + `<p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree>${GROUP}</p:spTree></p:cSld>`
    + '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
    + 'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
    + '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
    + '<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>')
  zip.file('ppt/slideMasters/_rels/slideMaster1.xml.rels', rels([
    ['rId1', 'slideLayout', '../slideLayouts/slideLayout1.xml'], ['rId2', 'theme', '../theme/theme1.xml'],
  ]))
  zip.file('ppt/slideLayouts/slideLayout1.xml', `<?xml version="1.0" encoding="UTF-8"?><p:sldLayout ${XMLNS} type="blank">`
    + `<p:cSld name="Blank"><p:spTree>${GROUP}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>`)
  zip.file('ppt/slideLayouts/_rels/slideLayout1.xml.rels', rels([['rId1', 'slideMaster', '../slideMasters/slideMaster1.xml']]))
  slides.forEach((paragraphs, i) => {
    zip.file(`ppt/slides/slide${i + 1}.xml`, `<?xml version="1.0" encoding="UTF-8"?><p:sld ${XMLNS}>`
      + `<p:cSld><p:spTree>${GROUP}${textBox(2, paragraphs)}</p:spTree></p:cSld>`
      + '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
    zip.file(`ppt/slides/_rels/slide${i + 1}.xml.rels`, rels([['rId1', 'slideLayout', '../slideLayouts/slideLayout1.xml']]))
  })
  return zip.generateAsync({ type: 'blob', mimeType: `${PML}.presentation` })
}

/** A document whose body blocks are paragraphs (`''` is an empty paragraph) or tables (rows of cells). */
export async function docxFixture(blocks: (string | string[][])[]): Promise<Blob> {
  const zip = new JSZip()
  zip.file('[Content_Types].xml', `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="${NS.types}">`
    + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    + '<Default Extension="xml" ContentType="application/xml"/>'
    + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
  zip.file('_rels/.rels', rels([['rId1', 'officeDocument', 'word/document.xml']]))
  const paragraph = (text: string) => text ? `<w:p><w:r><w:t>${text}</w:t></w:r></w:p>` : '<w:p/>'
  const body = blocks.map(block => typeof block === 'string' ? paragraph(block)
    : `<w:tbl>${block.map(row => `<w:tr>${row.map(cell => `<w:tc>${paragraph(cell)}</w:tc>`).join('')}</w:tr>`).join('')}</w:tbl>`)
  zip.file('word/document.xml', `<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="${NS.w}"><w:body>${body.join('')}</w:body></w:document>`)
  return zip.generateAsync({ type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
}

/** A document with one paragraph and one external link whose target is `href`, as a file may carry it. */
export async function docxLinkFixture(text: string, label: string, href: string): Promise<Blob> {
  const zip = await JSZip.loadAsync(await (await docxFixture([text])).arrayBuffer())
  zip.file('word/_rels/document.xml.rels', `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="${NS.rel}">`
    + `<Relationship Id="rIdLink" Type="${REL}/hyperlink" Target="${href}" TargetMode="External"/></Relationships>`)
  const xml = await zip.file('word/document.xml')!.async('string')
  zip.file('word/document.xml', xml.replace('<w:document ', `<w:document xmlns:r="${NS.r}" `).replace('</w:body>',
    `<w:p><w:hyperlink r:id="rIdLink"><w:r><w:t>${label}</w:t></w:r></w:hyperlink></w:p></w:body>`))
  return zip.generateAsync({ type: 'blob' })
}

/**
 * `docxFixture(blocks)` with an altChunk before body block `before` (1-based): HTML that runs a script
 * as soon as a renderer writes it into the page, and an external image the browser would fetch.
 */
export async function docxAltChunkFixture(blocks: string[], before: number, flag: string): Promise<Blob> {
  const zip = await JSZip.loadAsync(await (await docxFixture(blocks)).arrayBuffer())
  zip.file('word/_rels/document.xml.rels', `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="${NS.rel}">`
    + `<Relationship Id="rIdChunk" Type="${REL}/aFChunk" Target="chunk.html"/>`
    + `<Relationship Id="rIdPixel" Type="${REL}/image" Target="https://external.invalid/pixel.png" TargetMode="External"/>`
    + '</Relationships>')
  zip.file('word/chunk.html', `<html><body><p>embedded</p><script>parent.${flag} = 1</script></body></html>`)
  const types = await zip.file('[Content_Types].xml')!.async('string')
  zip.file('[Content_Types].xml', types.replace('</Types>', '<Override PartName="/word/chunk.html" ContentType="text/html"/></Types>'))
  const xml = await zip.file('word/document.xml')!.async('string')
  const at = xml.split('<w:p').slice(0, before).join('<w:p').length
  zip.file('word/document.xml', (xml.slice(0, at) + '<w:altChunk r:id="rIdChunk"/>' + xml.slice(at))
    .replace('<w:document ', `<w:document xmlns:r="${NS.r}" `))
  return zip.generateAsync({ type: 'blob' })
}

/** A workbook with the given sheets, in order. */
export function xlsxFixture(sheets: [string, string[][]][]): Blob {
  const book = XLSX.utils.book_new()
  for (const [name, rows] of sheets) XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet(rows), name)
  return new Blob([XLSX.write(book, { type: 'array', bookType: 'xlsx' })])
}

export type Expectation =
  | { kind: 'text'; quote: string; within: string; index: number }
  | { kind: 'rows'; sheet: number; row: number; note: string }
  | { kind: 'not-located'; note: string }
  | { kind: 'no-viewer'; note: string }
  | { kind: 'blocked-link'; flag: string }
  | { kind: 'inert'; quote: string; within: string; index: number; flag: string }
  | { kind: 'rejected'; note: string }

export interface OfficeCase {
  name: string
  file: keyof typeof FILES
  citation: Record<string, unknown>
  expect: Expectation
}

const COARSE = '已标出引文所在的位置，未能逐字高亮'
const NOT_LOCATED = '未能在原文中定位这段引文，请对照上方引文'
const NO_VIEWER = '这类出处暂不支持打开原文，请对照上方引文'
const UNSAFE = '原文件含有无法安全显示的内容，未打开，请对照上方引文'
const BODY = ['总则：本合同由保险条款构成。', '', '等待期为九十日（重大疾病）。', '等待期为三十日（一般疾病）。']

// Each quote also occurs outside its cited place, so only the locator can pick the right one.
export const FILES = {
  deck: () => pptxFixture([['产品概览', '犹豫期为十五日'], ['适合人群', '犹豫期为十五日'], ['其他说明']]),
  manual: () => docxFixture([...BODY, [['项目', '说明'], ['等待期', '等待期为三十日']]]),
  chunked: () => docxAltChunkFixture(BODY, 4, '__officeAltChunkRan'),
  broken: async () => new Blob(['this is not an Office package']),
  linked: () => docxLinkFixture('链接说明：见下方链接。', '了解详情', 'javascript:window.__officeLinkFollowed=1'),
  rates: () => xlsxFixture([
    ['Notes', [['说明', '取值'], ['示例', '100 元'], ['示例', '180 元']]],
    ['Rates', [['年龄', '年保费'], ['18-30', '120 元'], ['31-40', '180 元']]],
  ]),
}
export const DOCUMENTS: Record<keyof typeof FILES, string> = {
  deck: '合成演示.pptx', manual: '合成手册.docx', linked: '合成链接.docx', rates: '合成费率.xlsx',
  chunked: '合成嵌入.docx', broken: '合成损坏.docx',
}

function citation(name: string, file: keyof typeof FILES, page: number, quote: string, locator?: Record<string, unknown>) {
  return {
    release_id: 'rel-1', member: name, evidence_index: 0, origin: 'SOURCE_SUPPORTED',
    source: { knowledge_id: file, parse_attempt: 1, document: DOCUMENTS[file], file_sha256: '0'.repeat(64) },
    page: { number: page }, start: 0, end: quote.length, quote,
    ...(locator ? { locator, block: { block_id: 'b0', start: 0, end: quote.length } } : {}),
    file: `/api/v1/enterprise/spaces/demo/view/releases/rel-1/sources/${file}/attempts/1/file`,
  }
}

export const CASES: OfficeCase[] = [
  {
    name: 'pptx-slide-2', file: 'deck',
    citation: citation('pptx-slide-2', 'deck', 2, '犹豫期为十五日', { kind: 'PPTX_SHAPE', slide: 2 }),
    expect: { kind: 'text', quote: '犹豫期为十五日', within: '.pptx-preview-slide-wrapper', index: 1 },
  },
  {
    name: 'docx-block-4', file: 'manual',
    citation: citation('docx-block-4', 'manual', 1, '等待期为三十日', { kind: 'DOCX_BLOCK', block_index: 3 }),
    expect: { kind: 'text', quote: '等待期为三十日', within: 'section > article > p, section > article > table', index: 3 },
  },
  {
    name: 'xlsx-rates-row-3', file: 'rates',
    citation: citation('xlsx-rates-row-3', 'rates', 2, '31-40\t180 元', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A3:XFD3' }),
    expect: { kind: 'rows', sheet: 1, row: 3, note: COARSE },
  },
  {
    name: 'docx-quote-missing', file: 'manual',
    citation: citation('docx-quote-missing', 'manual', 1, '等待期为四十五日', { kind: 'DOCX_BLOCK', block_index: 3 }),
    expect: { kind: 'not-located', note: NOT_LOCATED },
  },
  {
    name: 'docx-script-link', file: 'linked',
    citation: citation('docx-script-link', 'linked', 1, '链接说明', { kind: 'DOCX_BLOCK', block_index: 0 }),
    expect: { kind: 'blocked-link', flag: '__officeLinkFollowed' },
  },
  {
    name: 'docx-altchunk', file: 'chunked',
    citation: citation('docx-altchunk', 'chunked', 1, '等待期为三十日', { kind: 'DOCX_BLOCK', block_index: 3 }),
    expect: { kind: 'inert', quote: '等待期为三十日', within: 'section > article > p, section > article > table', index: 3, flag: '__officeAltChunkRan' },
  },
  {
    name: 'docx-not-a-package', file: 'broken',
    citation: citation('docx-not-a-package', 'broken', 1, '等待期为三十日', { kind: 'DOCX_BLOCK', block_index: 3 }),
    expect: { kind: 'rejected', note: UNSAFE },
  },
  {
    name: 'no-locator', file: 'deck',
    citation: citation('no-locator', 'deck', 2, '犹豫期为十五日'),
    expect: { kind: 'no-viewer', note: NO_VIEWER },
  },
]
