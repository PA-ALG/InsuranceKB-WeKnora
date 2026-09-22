package types

import (
	"encoding/json"
	"github.com/stretchr/testify/require"
	"os"
	"testing"
)

func TestIssuerAliasPolicyPythonVector830G3(t *testing.T) {
	raw, err := os.ReadFile("testdata/concept_identity_issuer_alias_830_g3_vector.json")
	require.NoError(t, err)
	var wire struct {
		Catalog    SchemaPackCatalog830G3      `json:"catalog"`
		Inputs     BatchResolutionInputs830G3  `json:"inputs"`
		Resolution json.RawMessage             `json:"resolution"`
		Bindings   []EntityCompileBinding830G3 `json:"bindings"`
	}
	require.NoError(t, json.Unmarshal(raw, &wire))
	typed, err := decodeResolutionInputs830G3(wire.Inputs, wire.Resolution)
	require.NoError(t, err)
	_, _, _, err = validateResolutionInputs830G3(wire.Inputs)
	require.NoError(t, err)
	require.NoError(t, validateResolutionReplay830G3(wire.Catalog, wire.Inputs, typed))
	require.NoError(t, validateBindingsAgainstResolution830G3(BatchConceptCompileRequest830G3{EntityBindings: wire.Bindings}, typed))
	require.Equal(t, 3, typed.Resolution.DispositionCounts.Create)
	require.Equal(t, "平安人寿", *typed.Proposals.Proposals[1].Entities[0].Issuer)
	require.Equal(t, "中国平安人寿保险股份有限公司", wire.Bindings[0].Issuer)
}

func TestIssuerAliasPolicyRejectsEmptyAndAmbiguousWire830G3(t *testing.T) {
	raw, err := os.ReadFile("testdata/concept_identity_issuer_alias_830_g3_vector.json")
	require.NoError(t, err)
	var wire struct {
		Inputs BatchResolutionInputs830G3 `json:"inputs"`
	}
	require.NoError(t, json.Unmarshal(raw, &wire))
	for _, value := range []string{"[]", "null"} {
		var shape map[string]json.RawMessage
		require.NoError(t, json.Unmarshal(wire.Inputs.Policy, &shape))
		shape["issuer_aliases"] = json.RawMessage(value)
		changed, err := json.Marshal(shape)
		require.NoError(t, err)
		var policy BatchResolutionPolicy830G3
		require.Error(t, exactTypedRaw830G3(changed, &policy))
	}
	var policy BatchResolutionPolicy830G3
	require.NoError(t, exactTypedRaw830G3(wire.Inputs.Policy, &policy))
	duplicate := policy.IssuerAliases[0]
	duplicate.CanonicalName = "另一个公司"
	require.False(t, validIssuerAliases830G3(append(policy.IssuerAliases, duplicate)))
	require.Equal(t, "平安人寿", policy.canonicalIssuer("平安人寿", "other-space"))
	require.Equal(t, "另一保险公司", policy.canonicalIssuer("另一保险公司", "space-g3"))
}

// Optional real recorded projection: read-only inputs exported from the platform.
func TestIssuerAliasRecordedProjection830G3(t *testing.T) {
	path := os.Getenv("G3_RECORDED_IDENTITY_PROJECTION")
	if path == "" {
		t.Skip("recorded inputs not supplied")
	}
	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	var wire struct {
		Catalog    SchemaPackCatalog830G3      `json:"catalog"`
		Inputs     BatchResolutionInputs830G3  `json:"inputs"`
		Resolution json.RawMessage             `json:"resolution"`
		Bindings   []EntityCompileBinding830G3 `json:"bindings"`
	}
	require.NoError(t, json.Unmarshal(raw, &wire))
	typed, err := decodeResolutionInputs830G3(wire.Inputs, wire.Resolution)
	require.NoError(t, err)
	_, _, _, err = validateResolutionInputs830G3(wire.Inputs)
	require.NoError(t, err)
	require.NoError(t, validateResolutionReplay830G3(wire.Catalog, wire.Inputs, typed))
	require.NoError(t, validateBindingsAgainstResolution830G3(BatchConceptCompileRequest830G3{EntityBindings: wire.Bindings}, typed))
}
