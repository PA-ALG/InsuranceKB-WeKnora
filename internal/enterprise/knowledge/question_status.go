package knowledge

import "context"

// StatusLine is the sale status of a product a sales question names (PV-5 Spec §1.1). Slug is the
// product's Entity member; the status comes from its published lifecycle, not from a material, so a
// line has no evidence to open.
type StatusLine struct {
	EntityID, Slug, Title, Text string
}

// QuestionStatuses returns, for a sales question, one status line per product it names, in
// navigation order. A product without version data is stated as unknown: a field label is easy to
// pass over, and a sales answer must not present a product without saying whether it sells. Other
// questions get none, so their answers are unchanged.
func (s *Service) QuestionStatuses(
	ctx context.Context, tenantID uint64, spaceID, releaseID, question string,
) ([]StatusLine, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return nil, err
	}
	return index.statusLines(question), ctx.Err()
}

func (index *releaseIndex) statusLines(question string) []StatusLine {
	out := []StatusLine{}
	intent, products := index.questionScope(question)
	if intent != intentSales {
		return out
	}
	for _, product := range products {
		if product.placeholder || product.slug == "" {
			continue // a claim subject without an Entity member has no member to pin
		}
		out = append(out, StatusLine{
			EntityID: product.EntityID, Slug: product.slug, Title: product.Name + " · 销售状态",
			Text: product.Name + " · " + index.versionParts(product.Entity, true),
		})
	}
	return out
}

// RawScope is what raw retrieval reads of a question from one release: the products it names
// (QuestionProducts) and, for a sales question naming none, the materials to leave out
// (OffSaleMaterials).
type RawScope struct {
	Products []NamedProduct
	OffSale  map[string]bool
}

// QuestionRawScope reads the release once for both parts of a question's raw retrieval scope.
func (s *Service) QuestionRawScope(
	ctx context.Context, tenantID uint64, spaceID, releaseID, question string,
) (RawScope, error) {
	index, err := s.read(ctx, tenantID, spaceID, releaseID)
	if err != nil {
		return RawScope{}, err
	}
	return index.rawScope(ctx, question)
}

// OffSaleMaterials returns, for a sales question that names no product, the knowledge IDs cited only
// by products that are discontinued or not yet on sale on the read's day (PV-5 Spec §2.2), so raw
// retrieval compares what may be sold, as published fields do (forSale). A material any other
// product cites, and an unattributed one, stays. A named product is never dropped.
func (s *Service) OffSaleMaterials(
	ctx context.Context, tenantID uint64, spaceID, releaseID, question string,
) (map[string]bool, error) {
	scope, err := s.QuestionRawScope(ctx, tenantID, spaceID, releaseID, question)
	return scope.OffSale, err
}

func (index *releaseIndex) rawScope(ctx context.Context, question string) (RawScope, error) {
	intent, products := index.questionScope(question)
	scope := RawScope{Products: make([]NamedProduct, 0, len(products)), OffSale: map[string]bool{}}
	for _, product := range products {
		if err := ctx.Err(); err != nil {
			return RawScope{}, err
		}
		scope.Products = append(scope.Products, NamedProduct{
			EntityID: product.EntityID, Name: product.Name, Materials: index.productMaterials(product.EntityID),
		})
	}
	if intent != intentSales || len(products) > 0 {
		return scope, ctx.Err()
	}
	cited, selling := map[string]bool{}, map[string]bool{}
	for _, entity := range index.productEntities() {
		if err := ctx.Err(); err != nil {
			return RawScope{}, err
		}
		for _, id := range index.productMaterials(entity.EntityID) {
			cited[id] = true
			selling[id] = selling[id] || !notOnSale(entity)
		}
	}
	for id := range cited {
		if !selling[id] {
			scope.OffSale[id] = true
		}
	}
	return scope, ctx.Err()
}
