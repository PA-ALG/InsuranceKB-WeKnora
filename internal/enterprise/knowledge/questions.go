package knowledge

import (
	"context"
	"strings"
	"unicode/utf8"
)

// defaultQuestionLimit bounds what one quick answer adds ahead of raw retrieval.
const defaultQuestionLimit = 12

// QuestionFields finds the published fields a quick question asks about, without a model:
// a field when its title is in the question; a product when the question holds its ID or one of
// its names, or shares two distinctive name bigrams. Products and fields combine; fields alone
// compare every product; a product alone yields its navigation overview fields.
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
	products := questionProducts(entities, question)
	asked := func(field Field) bool {
		title := normalize(field.FieldTitle)
		return utf8.RuneCountInString(title) >= 2 && strings.Contains(question, title)
	}
	fieldsAsked := false
	for _, entity := range entities {
		for _, field := range index.fields(entity) {
			fieldsAsked = fieldsAsked || asked(field)
		}
	}
	out := []Field{}
	add := func(field Field) bool {
		out = append(out, field)
		return len(out) < limit
	}
	switch {
	case fieldsAsked:
		scope := products
		if len(scope) == 0 {
			scope = entities
		}
		for _, entity := range scope {
			for _, field := range index.fields(entity) {
				if asked(field) && !add(field) {
					return out, ctx.Err()
				}
			}
		}
	case len(products) > 0 && index.navigation != nil:
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

// questionProducts keeps product order. A name bigram is distinctive when at most a third of
// the products (and at least one) carry it, so words most product names share select nothing.
func questionProducts(entities []indexedEntity, question string) []indexedEntity {
	pairs := bigrams(question)
	carriers := map[string]int{}
	names := make([]map[string]bool, len(entities))
	for i, entity := range entities {
		names[i] = map[string]bool{}
		for _, name := range entity.Names {
			for pair := range bigrams(normalize(name)) {
				names[i][pair] = true
			}
		}
		for pair := range names[i] {
			carriers[pair]++
		}
	}
	distinctive := max(1, len(entities)/3)
	var out []indexedEntity
	for i, entity := range entities {
		direct := contained(question, entity.EntityID)
		for _, name := range entity.Names {
			direct = direct || contained(question, name)
		}
		shared := 0
		for pair := range names[i] {
			if pairs[pair] && carriers[pair] <= distinctive {
				shared++
			}
		}
		if direct || shared >= 2 {
			out = append(out, entity)
		}
	}
	return out
}

func contained(question, name string) bool {
	name = normalize(name)
	return utf8.RuneCountInString(name) >= 2 && strings.Contains(question, name)
}

// FieldText is the text a published field contributes to a prompt, shared by tools and answers.
func FieldText(field Field) string { return fieldText(field) }
