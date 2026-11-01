import type { OfficeFormat } from './officeCitation'

// What may reach each upstream renderer (S11e Spec §3.2a): the relationship types it follows and
// the content types of the parts it reads. Everything else is dropped before rendering. The lists
// come from the renderers pinned in frontend/package-lock.json:
// - docx-preview 0.3.7 `dist/docx-preview.mjs`: `RelationshipTypes` (the parts `loadRelationshipPart`
//   loads: document, styles, numbering, fontTable, theme, settings, footnotes, endnotes, header,
//   footer, comments, commentsExtended, the three property parts) and the images, embedded fonts and
//   external hyperlinks it resolves through `loadResource`. Transitional URIs only: it compares
//   relationship types literally and has no Strict variants.
// - @vue-office/pptx 1.0.1 `lib/v3/vue-office-pptx.mjs`: `[Content_Types].xml` overrides for theme,
//   tableStyles, slideMaster, slideLayout and slide; per-slide relationships slideLayout, image,
//   audio, video, media, diagramData/Layout/Colors/Drawing and chart; `ppt/presentation.xml` and
//   `docProps/thumbnail.jpeg` by path. It does not follow hyperlinks.
// - SheetJS 0.20.2 `xlsx.mjs`: `ct2type` and `RELS` — workbook, worksheets (also the Strict
//   relationship it lists), chartsheets, dialogsheets, sharedStrings, styles, theme and properties;
//   `sheet_to_html` renders cells only. Strict workbooks share the transitional content types.

export interface FormatPolicy {
  /** Content type of the main part. */
  main: string
  /** Full relationship type URIs that may be kept. */
  relationships: ReadonlySet<string>
  /** Content types a kept internal target may have, spelled as the renderers compare them. */
  contentTypes: ReadonlySet<string>
  /** Elements of the main part whose relationship must survive, or the package is refused. */
  required: readonly string[]
}

/** The only relationship that may keep an external target, and only to these protocols. */
export const HYPERLINK = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'
export const FOLLOWABLE_PROTOCOLS: ReadonlySet<string> = new Set(['http:', 'https:', 'mailto:'])

const T = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
const STRICT = 'http://purl.oclc.org/ooxml/officeDocument/relationships/'
const PACKAGE = 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/'
const MS2007 = 'http://schemas.microsoft.com/office/2007/relationships/'
const MS2011 = 'http://schemas.microsoft.com/office/2011/relationships/'
const OOXML = 'application/vnd.openxmlformats-officedocument.'

const PROPERTY_RELATIONSHIPS = [`${PACKAGE}core-properties`, `${T}extended-properties`, `${T}custom-properties`]
const PROPERTY_TYPES = [
  'application/vnd.openxmlformats-package.core-properties+xml',
  `${OOXML}extended-properties+xml`, `${OOXML}custom-properties+xml`,
]
const IMAGE_TYPES = [
  'image/png', 'image/jpeg', 'image/gif', 'image/bmp', 'image/tiff', 'image/x-emf', 'image/x-wmf',
  'image/svg+xml', 'image/webp', 'image/vnd.ms-photo',
]
const MEDIA_TYPES = [
  'audio/mpeg', 'audio/mp4', 'audio/x-m4a', 'audio/wav', 'audio/x-wav', 'audio/x-ms-wma',
  'video/mp4', 'video/mpeg', 'video/quicktime', 'video/x-ms-wmv', 'video/x-msvideo', 'video/webm',
]

export const POLICIES: Record<OfficeFormat, FormatPolicy> = {
  docx: {
    main: `${OOXML}wordprocessingml.document.main+xml`,
    relationships: new Set([
      `${T}officeDocument`, ...PROPERTY_RELATIONSHIPS,
      ...['styles', 'numbering', 'fontTable', 'theme', 'settings', 'footnotes', 'endnotes', 'header', 'footer',
        'comments', 'image', 'font', 'hyperlink'].map(type => T + type),
      `${MS2011}commentsExtended`,
    ]),
    contentTypes: new Set([
      ...['document.main', 'styles', 'numbering', 'fontTable', 'settings', 'footnotes', 'endnotes', 'header', 'footer',
        'comments', 'commentsExtended'].map(part => `${OOXML}wordprocessingml.${part}+xml`),
      `${OOXML}theme+xml`, ...PROPERTY_TYPES, ...IMAGE_TYPES,
      `${OOXML}obfuscatedFont`, 'application/x-fontdata', 'application/x-font-ttf',
    ]),
    required: [],
  },
  pptx: {
    main: `${OOXML}presentationml.presentation.main+xml`,
    relationships: new Set([
      `${T}officeDocument`, ...PROPERTY_RELATIONSHIPS, `${PACKAGE}thumbnail`,
      ...['slide', 'slideMaster', 'slideLayout', 'theme', 'tableStyles', 'image', 'audio', 'video', 'chart',
        'diagramData', 'diagramLayout', 'diagramColors'].map(type => T + type),
      `${MS2007}media`, `${MS2007}diagramDrawing`,
    ]),
    contentTypes: new Set([
      ...['presentation.main', 'slide', 'slideMaster', 'slideLayout', 'tableStyles']
        .map(part => `${OOXML}presentationml.${part}+xml`),
      ...['chart', 'diagramData', 'diagramLayout', 'diagramColors'].map(part => `${OOXML}drawingml.${part}+xml`),
      'application/vnd.ms-office.drawingml.diagramDrawing+xml',
      `${OOXML}theme+xml`, ...PROPERTY_TYPES, ...IMAGE_TYPES, ...MEDIA_TYPES,
    ]),
    required: ['sldId', 'sldMasterId'],
  },
  xlsx: {
    main: `${OOXML}spreadsheetml.sheet.main+xml`,
    relationships: new Set([
      ...PROPERTY_RELATIONSHIPS,
      ...['officeDocument', 'worksheet', 'chartsheet', 'dialogsheet', 'sharedStrings', 'styles', 'theme']
        .flatMap(type => [T + type, STRICT + type]),
    ]),
    contentTypes: new Set([
      ...['sheet.main', 'worksheet', 'chartsheet', 'dialogsheet', 'sharedStrings', 'styles']
        .map(part => `${OOXML}spreadsheetml.${part}+xml`),
      `${OOXML}theme+xml`, ...PROPERTY_TYPES,
    ]),
    required: ['sheet'],
  },
}

// The text view (S11h Spec §2.2) reads text and renders nothing: it also follows speaker notes,
// which the platform captures under their slide's locator.
export const TEXT_POLICIES: Record<OfficeFormat, FormatPolicy> = {
  ...POLICIES,
  pptx: {
    ...POLICIES.pptx,
    relationships: new Set([...POLICIES.pptx.relationships, `${T}notesSlide`]),
    contentTypes: new Set([...POLICIES.pptx.contentTypes, `${OOXML}presentationml.notesSlide+xml`]),
  },
}
