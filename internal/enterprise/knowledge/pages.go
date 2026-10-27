package knowledge

import (
	"bytes"
	"context"
	"encoding/json"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// Page is a model-written native Wiki page found in one release, with its own evidence.
type Page struct {
	ReleaseID, Slug, EntityID, EntityName, Title, Summary, Excerpt string
	Evidence                                                       []Evidence
}

const (
	defaultPageLimit = 5
	// excerptRunes bounds what one page adds to the model context; pages run to several thousand.
	excerptRunes = 800
)

var (
	wikiLink      = regexp.MustCompile(`\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]`)
	paragraphGaps = regexp.MustCompile(`\n[ \t\r]*\n`)
)

type wikiPagePayload struct {
	Key      string   `json:"page_key"`
	Entities []string `json:"entity_refs"`
	Title    string   `json:"title"`
	Type     string   `json:"page_type"`
	Summary  string   `json:"summary"`
	Content  string   `json:"content"`
	Aliases  []string `json:"aliases"`
	Origin   string   `json:"origin"`
	// Entries are read one by one: an invalid entry is skipped, never the page or the release.
	Evidence []json.RawMessage `json:"evidence"`
}

type pageEvidence struct {
	Quote     string `json:"quote"`
	SourceRef string `json:"source_ref"`
	Locator   struct {
		Page json.RawMessage `json:"page"`
	} `json:"locator"`
}

var positiveInteger = regexp.MustCompile(`^[1-9][0-9]{0,8}$`)

// validEvidence accepts an entry with a quote and a page that is a positive JSON integer; a
// fraction, string or out-of-range page is not truncated into a page number.
func validEvidence(raw json.RawMessage) (pageEvidence, int, bool) {
	var entry pageEvidence
	if json.Unmarshal(raw, &entry) != nil || strings.TrimSpace(entry.Quote) == "" {
		return entry, 0, false
	}
	text := string(bytes.TrimSpace(entry.Locator.Page))
	if !positiveInteger.MatchString(text) {
		return entry, 0, false
	}
	page, err := strconv.Atoi(text)
	return entry, page, err == nil
}

type indexedPage struct {
	slug, entity, content string
	payload               wikiPagePayload
}

// indexedWikiPage keeps a page only when its slug, type and provenance agree with the S6c
// contract (page_key is opaque); anything else is never searchable, so it can never be cited.
func indexedWikiPage(slug string, payload wikiPagePayload) (indexedPage, bool) {
	if (payload.Type != "concept" && payload.Type != "entity") || strings.TrimSpace(payload.Key) == "" ||
		payload.Origin != "MODEL_GENERATED" || strings.TrimSpace(payload.Title) == "" {
		return indexedPage{}, false
	}
	for _, entity := range payload.Entities {
		if entity != "" && slug == "wiki/"+entity+"/"+payload.Key {
			return indexedPage{slug: slug, entity: entity, content: linkFree(payload.Content), payload: payload}, true
		}
	}
	return indexedPage{}, false
}

// linkFree keeps a link's label (or the last segment of its target): targets are markup, not text.
func linkFree(content string) string {
	return wikiLink.ReplaceAllStringFunc(content, func(link string) string {
		parts := wikiLink.FindStringSubmatch(link)
		if label := strings.TrimSpace(parts[2]); label != "" {
			return label
		}
		target := strings.TrimSpace(parts[1])
		return target[strings.LastIndex(target, "/")+1:]
	})
}

// SearchPages finds the pages holding every query term, optionally of one product.
// It returns at most limit pages (5 when limit <= 0) and the number that matched.
func (s *Service) SearchPages(
	ctx context.Context, tenantID uint64, spaceID, releaseID, query, entityID string, limit int,
) ([]Page, int, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, 0, err
	}
	return index.searchPages(ctx, query, entityID, limit)
}

func (index *releaseIndex) searchPages(ctx context.Context, query, entityID string, limit int) ([]Page, int, error) {
	terms := searchTerms(query)
	if len(terms) == 0 {
		return []Page{}, 0, nil
	}
	if limit <= 0 {
		limit = defaultPageLimit
	}
	order := map[string]int{}
	for i, entity := range index.orderedEntities() {
		order[entity.EntityID] = i
	}
	rank := func(entity string) int {
		if i, ok := order[entity]; ok {
			return i
		}
		return len(order)
	}
	type hit struct {
		page   indexedPage
		titled bool
	}
	var hits []hit
	for _, page := range index.pages {
		if err := ctx.Err(); err != nil {
			return nil, 0, err
		}
		if entityID != "" && page.entity != entityID {
			continue
		}
		heading := searchFold(strings.Join(append([]string{page.payload.Title}, page.payload.Aliases...), "\n"))
		body := heading + "\n" + searchFold(page.payload.Summary) + "\n" + searchFold(page.content)
		matched, titled := true, true
		for _, term := range terms {
			if !strings.Contains(body, term) {
				matched = false
				break
			}
			titled = titled && strings.Contains(heading, term)
		}
		if matched {
			hits = append(hits, hit{page: page, titled: titled})
		}
	}
	sort.SliceStable(hits, func(i, j int) bool {
		a, b := hits[i], hits[j]
		if a.titled != b.titled {
			return a.titled
		}
		if ra, rb := rank(a.page.entity), rank(b.page.entity); ra != rb {
			return ra < rb
		}
		if a.page.payload.Type != b.page.payload.Type {
			return a.page.payload.Type == "concept"
		}
		if a.page.payload.Title != b.page.payload.Title {
			return a.page.payload.Title < b.page.payload.Title
		}
		return a.page.slug < b.page.slug
	})
	out := make([]Page, 0, min(limit, len(hits)))
	for _, hit := range hits[:min(limit, len(hits))] {
		out = append(out, index.page(hit.page, terms))
	}
	return out, len(hits), ctx.Err()
}

func (index *releaseIndex) page(page indexedPage, terms []string) Page {
	name := page.entity
	if i, ok := index.entityByID[page.entity]; ok {
		name = index.entities[i].Name
	}
	out := Page{
		ReleaseID: index.id, Slug: page.slug, EntityID: page.entity, EntityName: name,
		Title: page.payload.Title, Summary: page.payload.Summary, Excerpt: excerpt(page.content, terms),
		Evidence: []Evidence{},
	}
	for i, raw := range page.payload.Evidence {
		// Invalid entries are skipped without renumbering: the index names the stored evidence.
		if evidence, pageNumber, ok := validEvidence(raw); ok {
			out.Evidence = append(out.Evidence, Evidence{
				Index: i, Quote: evidence.Quote, Page: pageNumber, SourceRef: evidence.SourceRef,
			})
		}
	}
	return out
}

// excerpt takes the paragraphs holding a term (or, if none does, the page from its start) up to
// excerptRunes; a paragraph cut short ends with "…".
func excerpt(content string, terms []string) string {
	var paragraphs, picked []string
	for _, paragraph := range paragraphGaps.Split(content, -1) {
		if paragraph = strings.TrimSpace(paragraph); paragraph != "" {
			paragraphs = append(paragraphs, paragraph)
		}
	}
	for _, paragraph := range paragraphs {
		folded := searchFold(paragraph)
		for _, term := range terms {
			if strings.Contains(folded, term) {
				picked = append(picked, paragraph)
				break
			}
		}
	}
	if len(picked) == 0 {
		picked = paragraphs
	}
	var b strings.Builder
	used := 0
	for _, paragraph := range picked {
		if used > 0 {
			if used+2 >= excerptRunes {
				break
			}
			b.WriteString("\n\n")
			used += 2
		}
		runes := []rune(paragraph)
		if room := excerptRunes - used; len(runes) > room {
			b.WriteString(string(runes[:room]))
			b.WriteString("…")
			break
		}
		b.WriteString(paragraph)
		used += len(runes)
	}
	return b.String()
}
