package types

import (
	"os"
	"testing"
)

// Replays an explicitly supplied real candidate through the Go admission parser.
// No request, provider call, or serving write is performed by this diagnostic.
func TestG3SuccessorCandidateReplay(t *testing.T) {
	path := os.Getenv("G3_SUCCESSOR_CANDIDATE")
	if path == "" {
		t.Skip("explicit real successor candidate required")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	bundle, _, err := CanonicalBatchConceptCandidateBundle830G3(raw)
	if err != nil {
		t.Fatal(err)
	}
	rows, err := bundle.SnapshotMembers()
	if err != nil {
		t.Fatal(err)
	}
	for _, binding := range bundle.Request.EntityBindings {
		if binding.ResolutionDisposition != "MATCH" {
			t.Fatal("expected exact existing-product reuse")
		}
	}
	t.Logf("candidate=%s products=%d fields=%d members=%d bytes=%d", bundle.CandidateHash, len(bundle.Request.EntityBindings), len(bundle.CompileResult.Output.Fields), len(rows), len(raw))
}
