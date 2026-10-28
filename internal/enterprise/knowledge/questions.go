package knowledge

import (
	"context"
	"strings"
	"unicode"
	"unicode/utf8"
)

// defaultQuestionLimit bounds what one quick answer adds ahead of raw retrieval.
const defaultQuestionLimit = 12

// QuestionFields finds the published fields a quick question asks about, without a model:
// a field by its title or published question terms; a product using QuestionProducts' matching.
// Fields alone compare every product. Named products supply overview fields when no field is
// asked, or when a field matches only through a named product's name.
func (s *Service) QuestionFields(
	ctx context.Context, tenantID uint64, spaceID, releaseID, question string, limit int,
) ([]Field, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, err
	}
	question = normalize(question)
	if question == "" {
		return []Field{}, nil
	}
	if limit <= 0 {
		limit = defaultQuestionLimit
	}
	entities := index.orderedEntities()
	products := index.questionProducts(question)
	termQuestion := normalizeQuestionTerm(question)
	asked := map[string]bool{}
	fieldsAsked, supplementOverview := false, false
	for _, entity := range entities {
		for _, field := range index.fields(entity) {
			matched, nameOnly := index.questionFieldMatch(field, question, termQuestion, products)
			asked[field.Slug] = matched
			fieldsAsked = fieldsAsked || matched
			supplementOverview = supplementOverview || nameOnly
		}
	}
	out := []Field{}
	seen := map[string]bool{}
	add := func(field Field) bool {
		if !seen[field.Slug] {
			seen[field.Slug] = true
			out = append(out, field)
		}
		return len(out) < limit
	}
	if fieldsAsked {
		scope := products
		if len(scope) == 0 {
			scope = entities
		}
		for _, entity := range scope {
			for _, field := range index.fields(entity) {
				if asked[field.Slug] && !add(field) {
					return out, ctx.Err()
				}
			}
		}
	}
	if (!fieldsAsked || supplementOverview) && index.navigation != nil {
		for _, entity := range products {
			byKey := map[string][]Field{}
			for _, field := range index.fields(entity) {
				byKey[field.FieldKey] = append(byKey[field.FieldKey], field)
			}
			for _, key := range index.navigation.OverviewFields {
				for _, field := range byKey[key] {
					if !add(field) {
						return out, ctx.Err()
					}
				}
			}
		}
	}
	return out, ctx.Err()
}

// Only published fields reach this matcher; vocabulary keys alone cannot select a field.
func (index *releaseIndex) questionFieldMatch(
	field Field, question, termQuestion string, products []indexedEntity,
) (matched, nameOnly bool) {
	nameOnly = true
	title := normalize(field.FieldTitle)
	if utf8.RuneCountInString(title) >= 2 && strings.Contains(question, title) {
		matched = true
		inName := false
		for _, product := range products {
			for _, name := range product.Names {
				text := normalizeProductText(field.FieldTitle)
				inName = inName || (text != "" && strings.Contains(normalizeProductText(name), text))
			}
		}
		nameOnly = inName
	}
	if index.navigation != nil {
		for _, group := range index.navigation.QuestionTerms[field.FieldKey] {
			terms := normalizedQuestionGroup(group)
			if !containsQuestionTerms(termQuestion, terms) {
				continue
			}
			matched = true
			inName := false
			for _, product := range products {
				for _, name := range product.Names {
					inName = inName || containsQuestionTerms(normalizeQuestionTerm(name), terms)
				}
			}
			// Any matching alternative outside the name is an explicit field question.
			nameOnly = nameOnly && inName
		}
	}
	return matched, matched && nameOnly
}

func normalizeQuestionTerm(value string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsPunct(r) {
			return -1
		}
		return r
	}, normalize(value))
}

func normalizedQuestionGroup(group []string) []string {
	if len(group) == 0 || len(group) > 3 {
		return nil
	}
	terms := make([]string, 0, len(group))
	for _, term := range group {
		term = normalizeQuestionTerm(term)
		if utf8.RuneCountInString(term) < 2 {
			return nil
		}
		terms = append(terms, term)
	}
	return terms
}

func containsQuestionTerms(text string, terms []string) bool {
	if len(terms) == 0 {
		return false
	}
	for _, term := range terms {
		if !strings.Contains(text, term) {
			return false
		}
	}
	return true
}

// FieldText is the text a published field contributes to a prompt, shared by tools and answers.
func FieldText(field Field) string { return fieldText(field) }
