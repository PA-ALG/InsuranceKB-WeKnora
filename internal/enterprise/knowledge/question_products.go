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
// release is read, using the same recognition, version selection and read scope as
// QuestionFields, so raw retrieval follows the versions the published fields answer for.
func (s *Service) QuestionProducts(
	ctx context.Context, tenantID uint64, spaceID, releaseID, question string,
) ([]NamedProduct, error) {
	scope, err := s.QuestionRawScope(ctx, tenantID, spaceID, releaseID, question)
	if err != nil {
		return nil, err
	}
	return scope.Products, nil
}

// ForeignMaterials returns the knowledge IDs the pinned release attributes to some product but to
// none of the named entity IDs, so a quick answer about the named products does not fill its
// context with another product's clauses (QA2b). Unattributed materials are not foreign.
func (s *Service) ForeignMaterials(
	ctx context.Context, tenantID uint64, spaceID, releaseID string, named []string,
) (map[string]bool, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, err
	}
	asked := map[string]bool{}
	for _, id := range named {
		asked[id] = true
	}
	owned, ownedByNamed := map[string]bool{}, map[string]bool{}
	for _, entity := range index.entities {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		for _, id := range index.productMaterials(entity.EntityID) {
			owned[id] = true
			if asked[entity.EntityID] {
				ownedByNamed[id] = true
			}
		}
	}
	foreign := map[string]bool{}
	for id := range owned {
		if !ownedByNamed[id] {
			foreign[id] = true
		}
	}
	return foreign, ctx.Err()
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
	fragment bool   // a fragment only this product's names carry
	shared   string // a series name at the start of 2-3 products' cores (QA2b)
}

// maxSeriesProducts bounds how many products one shared series name may name; a name shared
// more widely is too generic to point at products (QA2b Spec §1).
const maxSeriesProducts = 3

func (match productMatch) specific() bool {
	return match.id || len(match.direct) > 0 || match.fragment
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
	codes := normalize(question) // identifiers keep their joiners, as in 2635-1
	question = normalizeProductText(question)
	if question == "" {
		return nil
	}
	entities := index.productEntities()
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
		match.id = utf8.RuneCountInString(id) >= 2 && strings.Contains(question, id) ||
			namesIdentifier(codes, entity.identifiers)
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
			match.fragment, match.shared = productFragment(i, matches, titles, question, prefix)
		}
	}
	out := []indexedEntity{}
	for i, match := range matches {
		named := match.specific() && !dominatedProduct(i, matches)
		if !match.specific() && match.shared != "" {
			named = seriesNamed(match.shared, matches)
		}
		if named {
			out = append(out, entities[i])
		}
	}
	return out
}

// seriesNamed names every carrier of a shared series name unless the question already names one
// of them more specifically, as "安佑福全能版" names only that product of the 安佑福 series.
func seriesNamed(series string, matches []productMatch) bool {
	for _, match := range matches {
		if match.specific() && carries(match, series) {
			return false
		}
	}
	return true
}

func carries(match productMatch, fragment string) bool {
	for _, name := range match.names {
		if strings.Contains(name, fragment) {
			return true
		}
	}
	return false
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
		if profile.Class == classMethod {
			continue // method titles name no product field (SK-3 §3)
		}
		for _, section := range profile.Sections {
			for _, field := range section.Fields {
				titles = append(titles, normalizeProductText(field.Title))
			}
		}
	}
	return titles
}

// productFragment reads the longest question fragment (at least 3 runes, in no field title) at
// each start of the product's names. A fragment no other product carries names the product
// alone; one carried by 2-3 products that begins each carrier's core name is a series name
// (QA2b): category words such as 医疗保险 sit later in the names and name nothing.
func productFragment(
	product int, matches []productMatch, titles []string, question, prefix string,
) (unique bool, shared string) {
	for _, name := range matches[product].names {
		runes := []rune(name)
		for start := 0; start+3 <= len(runes); start++ {
			for end := len(runes); end >= start+3; end-- {
				fragment := string(runes[start:end])
				if !strings.Contains(question, fragment) {
					continue
				}
				// Shorter prefixes of this fragment occur wherever it occurs, so only the
				// longest question match at this start decides. Digits alone name nothing: in a
				// question they are dates or amounts, as 2025 against a name's (2026), and codes are
				// named by identifiers (PV-5 §3).
				if titledFragment(fragment, titles) || digitsOnly(fragment) {
					break
				}
				carriers := 0
				for _, match := range matches {
					if carries(match, fragment) {
						carriers++
					}
				}
				if carriers == 1 {
					return true, ""
				}
				if carriers <= maxSeriesProducts && seriesFragment(fragment, prefix, matches) &&
					utf8.RuneCountInString(fragment) > utf8.RuneCountInString(shared) {
					shared = fragment
				}
				break
			}
		}
	}
	return false, shared
}

func digitsOnly(fragment string) bool {
	for _, r := range fragment {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func titledFragment(fragment string, titles []string) bool {
	for _, title := range titles {
		if strings.Contains(title, fragment) {
			return true
		}
	}
	return false
}

// seriesFragment holds when, without the prefix all products share, the fragment is at least 3
// runes and begins the core name — the first name without that prefix (QA2 §3) — of every
// product that carries it. Aliases do not count (QA2b §2a.4).
func seriesFragment(fragment, prefix string, matches []productMatch) bool {
	series := strings.TrimPrefix(fragment, prefix)
	if utf8.RuneCountInString(series) < 3 {
		return false
	}
	for _, match := range matches {
		if !carries(match, fragment) {
			continue
		}
		if len(match.names) == 0 || !strings.HasPrefix(strings.TrimPrefix(match.names[0], prefix), series) {
			return false
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

// namesIdentifier reports whether the question carries one of the values as a whole token
// (PV-5 §3): not inside a longer number or code, so 2635 is named by 产品代码2635 but not by
// 26351 or 2635-0001.
func namesIdentifier(question string, values []string) bool {
	for _, value := range values {
		for offset := 0; offset < len(question); {
			found := strings.Index(question[offset:], value)
			if found < 0 {
				break
			}
			start := offset + found
			if wholeToken(question, start, start+len(value)) {
				return true
			}
			_, size := utf8.DecodeRuneInString(question[start:])
			offset = start + size
		}
	}
	return false
}
