package service

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
)

func TestCandidateWikiManifest076PythonVectorMatchesUnchangedGoCanonicalizer(t *testing.T) {
	t.Helper()
	raw, err := os.ReadFile("testdata/076_candidate_wiki_manifest_vector.json")
	if err != nil {
		t.Fatal(err)
	}
	var vector struct {
		Members          []types.WikiReleaseMemberSnapshot `json:"members"`
		ExpectedManifest string                            `json:"expected_manifest_utf8"`
		ExpectedDigest   string                            `json:"expected_manifest_digest"`
	}
	if err := json.Unmarshal(raw, &vector); err != nil {
		t.Fatal(err)
	}
	manifest, _, err := canonicalWikiReleaseManifest(vector.Members)
	if err != nil {
		t.Fatal(err)
	}
	if string(manifest) != vector.ExpectedManifest {
		t.Fatalf("manifest bytes drifted\nwant: %s\n got: %s", vector.ExpectedManifest, manifest)
	}
	if got := digestWikiReleaseBytes(manifest); got != vector.ExpectedDigest {
		t.Fatalf("manifest digest drifted: want %s got %s", vector.ExpectedDigest, got)
	}
}
