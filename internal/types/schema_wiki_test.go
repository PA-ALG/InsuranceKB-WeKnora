package types

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func resealSchemaWikiReleaseForTest(t *testing.T, release KnowledgeWikiReleaseV1) KnowledgeWikiReleaseV1 {
	t.Helper()
	for index := range release.Members {
		digest, _, err := schemaWikiHashWithout(
			release.Members[index].Contract,
			release.Members[index],
			"member_digest",
		)
		if err != nil {
			t.Fatal(err)
		}
		release.Members[index].MemberDigest = digest
	}
	manifest, err := schemaWikiManifestDigest(release.Members, release.CitationBindings)
	if err != nil {
		t.Fatal(err)
	}
	release.ManifestDigest = manifest
	releaseHash, _, err := schemaWikiHashWithout(release.Contract, release, "release_sha256")
	if err != nil {
		t.Fatal(err)
	}
	release.ReleaseSHA256 = releaseHash
	return release
}

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

func TestSchemaWikiGoMembersCarryExactClosedTypedPayloads(t *testing.T) {
	t.Parallel()

	vector, _ := loadSchemaWikiContractVector(t)
	wantContracts := []string{
		"schema-root-page.v1",
		"schema-section-page.v1",
		"schema-section-page.v1",
		"schema-field-page.v1",
		"schema-field-page.v1",
		"schema-field-page.v1",
	}
	if len(vector.Release.Members) != len(wantContracts) {
		t.Fatalf("member count = %d, want %d", len(vector.Release.Members), len(wantContracts))
	}
	for index, member := range vector.Release.Members {
		decoder := json.NewDecoder(bytes.NewReader(member.Payload))
		var envelope struct {
			Contract string `json:"contract"`
		}
		if err := decoder.Decode(&envelope); err != nil {
			t.Fatalf("member %d payload: %v", index, err)
		}
		if envelope.Contract != wantContracts[index] {
			t.Fatalf("member %d contract = %q, want %q", index, envelope.Contract, wantContracts[index])
		}
	}
	if err := ValidateKnowledgeWikiRelease(vector.Release, vector.SchemaPack); err != nil {
		t.Fatal(err)
	}
}

func TestSchemaWikiGoRejectsUnreviewedOrDriftedMemberPayload(t *testing.T) {
	t.Parallel()

	for _, mutation := range []string{
		"missing",
		"descriptor-only",
		"generic",
		"kind-swap",
		"foreign-field",
		"unknown-field",
		"noncanonical",
		"self-hash-drift",
	} {
		mutation := mutation
		t.Run(mutation, func(t *testing.T) {
			t.Parallel()
			vector, _ := loadSchemaWikiContractVector(t)
			member := &vector.Release.Members[3]
			switch mutation {
			case "missing", "descriptor-only":
				member.Payload = nil
			case "generic":
				member.Payload = json.RawMessage(`{"contract":"generic-wiki-page.v1","body":"caller-selected"}`)
			case "kind-swap":
				member.Payload = append(json.RawMessage(nil), vector.Release.Members[1].Payload...)
				member.PayloadSHA256 = vector.Release.Members[1].PayloadSHA256
			default:
				var payload map[string]any
				if err := json.Unmarshal(member.Payload, &payload); err != nil {
					t.Fatal(err)
				}
				switch mutation {
				case "foreign-field":
					payload["field_id"] = "field-b"
				case "unknown-field":
					payload["caller_authority"] = "forbidden"
				case "noncanonical":
					payload["value_snapshot"] = "Cafe\u0301"
				case "self-hash-drift":
					payload["field_page_sha256"] = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
				}
				mutated, err := json.Marshal(payload)
				if err != nil {
					t.Fatal(err)
				}
				member.Payload = mutated
				if claimed, ok := payload["field_page_sha256"].(string); ok {
					member.PayloadSHA256 = claimed
				}
			}
			if mutation == "noncanonical" {
				if err := ValidateKnowledgeWikiRelease(vector.Release, vector.SchemaPack); err == nil {
					t.Fatal("non-canonical payload unexpectedly validated")
				}
				return
			}
			forged := resealSchemaWikiReleaseForTest(t, vector.Release)
			if err := ValidateKnowledgeWikiRelease(forged, vector.SchemaPack); err == nil {
				t.Fatal("mutated payload unexpectedly validated")
			}
		})
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

func TestSchemaWikiGoRejectsEveryControlCharacter(t *testing.T) {
	t.Parallel()

	codepoints := make([]rune, 0, 33)
	for codepoint := rune(0); codepoint < 0x20; codepoint++ {
		codepoints = append(codepoints, codepoint)
	}
	codepoints = append(codepoints, 0x7f)
	for _, codepoint := range codepoints {
		codepoint := codepoint
		t.Run(fmt.Sprintf("U+%04X", codepoint), func(t *testing.T) {
			t.Parallel()
			_, err := schemaWikiCanonicalPreimage(
				"knowledge-domain.v1",
				map[string]any{"display_name": "医疗险" + string(codepoint) + "产品"},
			)
			if err == nil {
				t.Fatal("control character unexpectedly accepted")
			}
		})
	}

	preimage, err := schemaWikiCanonicalPreimage(
		"knowledge-domain.v1",
		map[string]any{"display_name": "医疗保险"},
	)
	if err != nil || len(preimage) == 0 {
		t.Fatalf("ordinary NFC Chinese text rejected: %v", err)
	}
}

func TestSchemaWikiVectorRejectsUnknownFieldAfterStandardUnmarshal(t *testing.T) {
	t.Parallel()

	vector, raw := loadSchemaWikiContractVector(t)
	var payload map[string]any
	if err := json.Unmarshal(raw, &payload); err != nil {
		t.Fatal(err)
	}
	payload["foreign_authority"] = "caller-selected"
	mutatedRaw, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}

	var silentlyTruncated SchemaWikiContractVectorV1
	if err := json.Unmarshal(mutatedRaw, &silentlyTruncated); err != nil {
		t.Fatal(err)
	}
	if silentlyTruncated.Contract != vector.Contract {
		t.Fatal("standard JSON fixture did not preserve the known vector")
	}
	if err := ValidateSchemaWikiContractVector(silentlyTruncated, mutatedRaw); err == nil {
		t.Fatal("unknown authority field escaped the typed closed-world boundary")
	}
}
