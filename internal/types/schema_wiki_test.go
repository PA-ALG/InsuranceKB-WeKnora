package types

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func loadSchemaWikiContractVector(t *testing.T) (SchemaWikiContractVectorV1, []byte) {
	t.Helper()
	path := filepath.Join("..", "application", "service", "testdata", "schema_wiki_contract_vector.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var vector SchemaWikiContractVectorV1
	if err := json.Unmarshal(raw, &vector); err != nil {
		t.Fatal(err)
	}
	return vector, raw
}

func TestSchemaWikiCrossLanguageVector(t *testing.T) {
	t.Parallel()

	vector, raw := loadSchemaWikiContractVector(t)
	if err := ValidateSchemaWikiContractVector(vector, raw); err != nil {
		t.Fatal(err)
	}
}

func TestSchemaWikiVectorRejectsMutation(t *testing.T) {
	t.Parallel()

	vector, raw := loadSchemaWikiContractVector(t)
	vector.Release.CandidateSHA256 = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
	if err := ValidateSchemaWikiContractVector(vector, raw); err == nil {
		t.Fatal("mutated vector unexpectedly validated")
	}
}

func TestSchemaWikiGoValidationRejectsActiveDraftAndInvalidCitation(t *testing.T) {
	t.Parallel()

	valid, _ := loadSchemaWikiContractVector(t)
	active := valid
	active.Release.ReleaseState = "active"
	if err := ValidateKnowledgeWikiRelease(active.Release, active.SchemaPack); err == nil {
		t.Fatal("draft claiming active unexpectedly validated")
	}

	badPage := valid
	badPage.Citations[0].PageNumber = 0
	if err := ValidateCitationTarget(badPage.Citations[0]); err == nil {
		t.Fatal("page zero unexpectedly validated")
	}

	fullPage := valid
	fullPage.Citations[0].BBox.X0 = 0
	fullPage.Citations[0].BBox.Y0 = 0
	fullPage.Citations[0].BBox.X1 = fullPage.Citations[0].BBox.PageWidth
	fullPage.Citations[0].BBox.Y1 = fullPage.Citations[0].BBox.PageHeight
	if err := ValidateCitationTarget(fullPage.Citations[0]); err == nil {
		t.Fatal("full-page bbox unexpectedly validated")
	}
}

func TestSchemaWikiGoTopologyUsesPackCardinality(t *testing.T) {
	t.Parallel()

	vector, _ := loadSchemaWikiContractVector(t)
	if got, want := len(vector.Release.Members), 1+len(vector.SchemaPack.Sections)+len(vector.SchemaPack.OrderedFieldIDs); got != want {
		t.Fatalf("member count = %d, want %d", got, want)
	}
	if len(vector.SchemaPack.Sections) == 7 || len(vector.SchemaPack.OrderedFieldIDs) == 67 {
		t.Fatal("synthetic vector accidentally blesses medical cardinality")
	}
	if err := ValidateKnowledgeWikiRelease(vector.Release, vector.SchemaPack); err != nil {
		t.Fatal(err)
	}
}

func TestSchemaWikiGoRejectsNonNFCText(t *testing.T) {
	t.Parallel()

	vector, _ := loadSchemaWikiContractVector(t)
	domain := vector.Release.Domain
	domain.DisplayName = "Cafe\u0301"
	digest, _, err := schemaWikiHashWithout(domain.Contract, domain, "domain_sha256")
	if err == nil {
		domain.DomainSHA256 = digest
	}
	if err == nil && validateKnowledgeDomain(domain) == nil {
		t.Fatal("decomposed Unicode unexpectedly validated")
	}
}
