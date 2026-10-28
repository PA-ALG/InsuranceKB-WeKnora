package knowledge

import (
	"context"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

// NamedProduct is a product a question names, with the materials the release attributes to it.
type NamedProduct struct {
	EntityID  string
	Name      string   // the entity's first display name
	Materials []string // knowledge IDs cited by its claims and pages, sorted and unique
}

// QuestionProducts returns the products the question names, in navigation order. Only a pinned
// release is read, using the same recognition and read scope as QuestionFields.
func (s *Service) QuestionProducts(
	ctx context.Context, tenantID uint64, spaceID, releaseID, question string,
) ([]NamedProduct, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, err
	}
	products := index.questionProducts(question)
	out := make([]NamedProduct, 0, len(products))
	for _, product := range products {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		out = append(out, NamedProduct{
			EntityID: product.EntityID, Name: product.Name, Materials: index.productMaterials(product.EntityID),
		})
	}
	return out, ctx.Err()
}

// productMaterials follows SourceEntities' ownership rule without mapping through display
// names: different products may share a name, but must keep their own material attribution.
func (index *releaseIndex) productMaterials(entityID string) []string {
	seen := map[string]bool{}
	cite := func(sourceRef string) {
		if ref, ok := release.ParseSourceRef(sourceRef); ok {
			seen[ref.KnowledgeID] = true
		}
	}
	for _, claim := range index.claims[entityID] {
		for _, evidence := range claim.payload.Evidence {
			cite(evidence.SourceRef)
		}
	}
	if index.entityMember(entityID) {
		for _, page := range index.pages {
			if !intersects(page.payload.Entities, []string{entityID}) {
				continue
			}
			for _, raw := range page.payload.Evidence {
				if evidence, _, ok := validEvidence(raw); ok {
					cite(evidence.SourceRef)
				}
			}
		}
	}
	materials := make([]string, 0, len(seen))
	for id := range seen {
		materials = append(materials, id)
	}
	sort.Strings(materials)
	return materials
}

func normalizeProductText(value string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsPunct(r) || unicode.IsSymbol(r) {
			return -1
		}
		return r
	}, normalize(value))
}

type productMatch struct {
	names    []string
	direct   []string // longest full names or cores actually contained in the question
	id       bool
	fragment bool
}

// addDirect retains equally long matches, but a short alias cannot overrule a more specific
// full name or core that the same question also names.
func (match *productMatch) addDirect(name string) {
	if len(match.direct) > 0 {
		length, longest := utf8.RuneCountInString(name), utf8.RuneCountInString(match.direct[0])
		if length < longest {
			return
		}
		if length > longest {
			match.direct = nil
		}
	}
	match.direct = append(match.direct, name)
}

// questionProducts shares strict recognition between published fields and raw retrieval.
// Only fragment matches are excluded by profile titles; explicit names remain usable even
// when they contain a field title.
func (index *releaseIndex) questionProducts(question string) []indexedEntity {
	question = normalizeProductText(question)
	if question == "" {
		return nil
	}
	entities := index.orderedEntities()
	matches := make([]productMatch, len(entities))
	firstNames := []string{}
	for i, entity := range entities {
		for _, name := range entity.Names {
			matches[i].names = append(matches[i].names, normalizeProductText(name))
		}
		if len(matches[i].names) > 0 {
			firstNames = append(firstNames, matches[i].names[0])
		}
	}
	prefix := sharedNamePrefix(firstNames)
	titles := index.productExclusionTitles()
	for i, entity := range entities {
		match := &matches[i]
		id := normalizeProductText(entity.EntityID)
		match.id = utf8.RuneCountInString(id) >= 2 && strings.Contains(question, id)
		for _, name := range match.names {
			if name != "" && strings.Contains(question, name) {
				match.addDirect(name)
			}
		}
		if len(match.names) > 0 {
			core := strings.TrimPrefix(match.names[0], prefix)
			if utf8.RuneCountInString(core) >= 3 && strings.Contains(question, core) {
				match.addDirect(core)
			}
		}
		if !match.id && len(match.direct) == 0 {
			match.fragment = uniqueProductFragment(i, matches, titles, question)
		}
	}
	out := []indexedEntity{}
	for i, match := range matches {
		if (match.id || len(match.direct) > 0 || match.fragment) && !dominatedProduct(i, matches) {
			out = append(out, entities[i])
		}
	}
	return out
}

func sharedNamePrefix(names []string) string {
	if len(names) == 0 {
		return ""
	}
	prefix := []rune(names[0])
	for _, name := range names[1:] {
		runes, common := []rune(name), 0
		for common < len(prefix) && common < len(runes) && prefix[common] == runes[common] {
			common++
		}
		prefix = prefix[:common]
	}
	return string(prefix)
}

func (index *releaseIndex) productExclusionTitles() []string {
	var titles []string
	for _, profile := range index.profiles {
		for _, section := range profile.Sections {
			for _, field := range section.Fields {
				titles = append(titles, normalizeProductText(field.Title))
			}
		}
	}
	return titles
}

func uniqueProductFragment(product int, matches []productMatch, titles []string, question string) bool {
	for _, name := range matches[product].names {
		runes := []rune(name)
		for start := 0; start+3 <= len(runes); start++ {
			for end := len(runes); end >= start+3; end-- {
				fragment := string(runes[start:end])
				if !strings.Contains(question, fragment) {
					continue
				}
				if distinctiveProductFragment(fragment, product, matches, titles) {
					return true
				}
				// A shorter prefix of this shared fragment also occurs in that other name
				// or field title, so only the longest question match at this start matters.
				break
			}
		}
	}
	return false
}

func distinctiveProductFragment(fragment string, product int, matches []productMatch, titles []string) bool {
	for _, title := range titles {
		if strings.Contains(title, fragment) {
			return false
		}
	}
	for i, match := range matches {
		if i == product {
			continue
		}
		for _, name := range match.names {
			if strings.Contains(name, fragment) {
				return false
			}
		}
	}
	return true
}

func dominatedProduct(product int, matches []productMatch) bool {
	match := matches[product]
	for i, other := range matches {
		if i == product || len(other.direct) == 0 {
			continue
		}
		for _, shorter := range match.direct {
			for _, longer := range other.direct {
				if shorter != longer && strings.Contains(longer, shorter) {
					return true
				}
			}
		}
		if match.fragment {
			for _, name := range match.names {
				for _, otherName := range other.names {
					if name != "" && otherName != "" &&
						(strings.Contains(name, otherName) || strings.Contains(otherName, name)) {
						return true
					}
				}
			}
		}
	}
	return false
}
