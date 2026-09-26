package types

import "strings"

// ProductConceptRelation is a typed facet of an atomic G3 release page. The page
// owns subject/version, conditions and Evidence; no second relationship store exists.
type ProductConceptRelation struct {
	Contract               string `json:"contract"`
	SubjectType            string `json:"subject_type"`
	ObjectType             string `json:"object_type"`
	Predicate              string `json:"predicate"`
	ObjectConceptID        string `json:"object_concept_id"`
	ObjectDefinitionSHA256 string `json:"object_definition_sha256"`
}

func validateProductConceptRelationPage(page ConceptFreeWikiPage830G2) error {
	relation := page.BusinessRelation
	if relation == nil {
		return nil
	}
	if relation.Contract != "product-concept-relation.830.v1" || relation.SubjectType != "PRODUCT" ||
		relation.ObjectType != "CONCEPT" || relation.Predicate != "benefit_reduced_by_advance_payment" ||
		!strings.HasPrefix(relation.ObjectConceptID, "concept_") || !conceptHash830G2(strings.TrimPrefix(relation.ObjectConceptID, "concept_")) ||
		!conceptHash830G2(relation.ObjectDefinitionSHA256) || strings.TrimSpace(page.EntityVersion) == "" ||
		len(page.ConceptIDs) != 1 || page.ConceptIDs[0] != relation.ObjectConceptID {
		return ErrConceptCandidateBundle830G3
	}
	identity, err := conceptDigest830G2("product-concept-relation-identity", []string{
		page.SpaceID, page.EntityID, relation.Predicate, relation.ObjectConceptID,
	})
	if err != nil || page.StableKey != "relation_"+identity || len(page.Evidence) == 0 || page.ContentProvenance == nil {
		return ErrConceptCandidateBundle830G3
	}
	for _, segment := range page.ContentProvenance.Segments {
		if segment.Origin != "SOURCE_SUPPORTED" {
			return ErrConceptCandidateBundle830G3
		}
	}
	return nil
}

func validateProductConceptRelationTargets(definitions []ConceptDefinition830G2, pages []ConceptFreeWikiPage830G2) error {
	targets := map[string]ConceptDefinition830G2{}
	for _, definition := range definitions {
		id, err := conceptDefinitionID830G2(definition)
		if err != nil {
			return err
		}
		targets[id] = definition
	}
	for _, page := range pages {
		relation := page.BusinessRelation
		if relation == nil {
			continue
		}
		target, exists := targets[relation.ObjectConceptID]
		if !exists || target.SpaceID != page.SpaceID {
			return ErrConceptCandidateBundle830G3
		}
		revision, err := conceptDefinitionHash830G3(target)
		if err != nil || revision != relation.ObjectDefinitionSHA256 {
			return ErrConceptCandidateBundle830G3
		}
	}
	return nil
}
