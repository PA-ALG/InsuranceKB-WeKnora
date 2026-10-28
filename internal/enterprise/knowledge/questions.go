package knowledge

import (
	"context"
	"strings"
	"unicode/utf8"
)

// defaultQuestionLimit bounds what one quick answer adds ahead of raw retrieval.
const defaultQuestionLimit = 12

// QuestionFields finds the published fields a quick question asks about, without a model:
// a field when its title is in the question; a product using QuestionProducts' strict matching.
// Fields alone compare every product. Named products supply overview fields when no title is
// asked, or when an asked title is also part of a named product's name.
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
	asked := func(field Field) bool {
		title := normalize(field.FieldTitle)
		return utf8.RuneCountInString(title) >= 2 && strings.Contains(question, title)
	}
	fieldsAsked, supplementOverview := false, false
	for _, entity := range entities {
		for _, field := range index.fields(entity) {
			if !asked(field) {
				continue
			}
			fieldsAsked = true
			for _, product := range products {
				for _, name := range product.Names {
					title := normalizeProductText(field.FieldTitle)
					if title != "" && strings.Contains(normalizeProductText(name), title) {
						supplementOverview = true
					}
				}
			}
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
				if asked(field) && !add(field) {
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

// FieldText is the text a published field contributes to a prompt, shared by tools and answers.
func FieldText(field Field) string { return fieldText(field) }
