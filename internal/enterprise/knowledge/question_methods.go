package knowledge

import (
	"sort"
	"strings"
)

// intentMethod is the navigation question intent of how to sell or explain (SK-3 Spec §6.1). It is
// independent of the sales and service intents, which only narrow product versions.
const intentMethod = "method"

// methodFields picks, for a method question, the evidenced fields of the methods it is about,
// at most limit of them (SK-3 Spec §6.2): methods it names (3), methods related to the products it
// names (2), methods in a navigation group it names (1); with none of those, methods sharing at
// least two bigrams with the question outside the intent words. Ties keep navigation order.
func (index *releaseIndex) methodFields(question, termQuestion string, products []indexedEntity, limit int) []Field {
	if index.navigation == nil || limit <= 0 {
		return nil
	}
	var intentTerms []string
	for _, group := range index.navigation.QuestionIntents[intentMethod] {
		terms := normalizedQuestionGroup(group)
		if containsQuestionTerms(termQuestion, terms) {
			intentTerms = append(intentTerms, terms...)
		}
	}
	if len(intentTerms) == 0 {
		return nil
	}
	methods := index.methodEntities()
	scores := make([]int, len(methods))
	for i, method := range methods {
		scores[i] = index.methodScore(method, question, products)
	}
	if !positive(scores) {
		asked := questionBigrams(termQuestion, intentTerms)
		for i, method := range methods {
			if shared := sharedBigrams(asked, index.methodBigrams(method)); shared >= 2 {
				scores[i] = shared
			}
		}
	}
	order := make([]int, len(methods))
	for i := range order {
		order[i] = i
	}
	sort.SliceStable(order, func(a, b int) bool { return scores[order[a]] > scores[order[b]] })
	out := []Field{}
	for _, i := range order {
		if scores[i] <= 0 {
			break
		}
		for _, field := range index.fields(methods[i]) {
			if len(field.Evidence) == 0 {
				continue
			}
			if len(out) == limit {
				return out
			}
			out = append(out, field)
		}
	}
	return out
}

func (index *releaseIndex) methodScore(method indexedEntity, question string, products []indexedEntity) int {
	score := 0
	for _, name := range method.Names {
		if namedIn(question, name) {
			score += 3
			break
		}
	}
	for _, product := range products {
		if relatedMethod(method.Entity, product.Entity) {
			score += 2
			break
		}
	}
	for _, domain := range index.navigation.Domains {
		for _, group := range domain.Groups {
			if namedIn(question, group.Title) && intersects(group.Labels, method.Labels) {
				return score + 1
			}
		}
	}
	return score
}

// methodBigrams are the bigrams of a method's names and published values, each text on its own.
func (index *releaseIndex) methodBigrams(method indexedEntity) map[string]bool {
	texts := append([]string{}, method.Names...)
	for _, claim := range index.claims[method.EntityID] {
		if claim.payload.State == "present" {
			texts = append(texts, valueText(claim.payload.Value))
		}
	}
	out := map[string]bool{}
	for _, text := range texts {
		for pair := range bigrams(normalizeQuestionTerm(text)) {
			out[pair] = true
		}
	}
	return out
}

// questionBigrams are the question's bigrams outside the matched intent words.
func questionBigrams(termQuestion string, intentTerms []string) map[string]bool {
	for _, term := range intentTerms {
		termQuestion = strings.ReplaceAll(termQuestion, term, "\x00")
	}
	out := map[string]bool{}
	for _, part := range strings.Split(termQuestion, "\x00") {
		for pair := range bigrams(part) {
			out[pair] = true
		}
	}
	return out
}

func positive(scores []int) bool {
	for _, score := range scores {
		if score > 0 {
			return true
		}
	}
	return false
}
