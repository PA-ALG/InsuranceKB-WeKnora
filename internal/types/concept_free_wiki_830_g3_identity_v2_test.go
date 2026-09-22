package types

import (
	"encoding/json"
	"os"
	"testing"
)

// The vector contains original frozen model receipts and a locally replayed
// v2 resolution, so it verifies the independent Python and Go implementations.
func TestEvidenceIdentityV2ActualReplay830G3(t *testing.T) {
	path := os.Getenv("G3_P2_IDENTITY_VECTOR")
	if path == "" {
		t.Skip("set G3_P2_IDENTITY_VECTOR to the local replay vector")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var wire struct {
		Catalog    SchemaPackCatalog830G3     `json:"catalog"`
		Inputs     BatchResolutionInputs830G3 `json:"inputs"`
		Resolution json.RawMessage            `json:"resolution"`
	}
	if err := json.Unmarshal(data, &wire); err != nil {
		t.Fatal(err)
	}
	typed, err := decodeResolutionInputs830G3(wire.Inputs, wire.Resolution)
	if err != nil {
		t.Fatal(err)
	}
	if err := validateResolutionReplay830G3(wire.Catalog, wire.Inputs, typed); err != nil {
		t.Fatal(err)
	}
}
