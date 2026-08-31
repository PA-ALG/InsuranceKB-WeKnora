package types

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
)

func loadEntityPageGraph830G1Vector(t *testing.T) []byte {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(
		"..", "..", "harness", "tests", "fixtures",
		"entity_page_graph_830_g1_contract_vector.json",
	))
	require.NoError(t, err)
	return raw
}

func TestParseEntityPageManifest830G1FrozenVectorAndTopology(t *testing.T) {
	t.Parallel()

	raw := loadEntityPageGraph830G1Vector(t)
	manifest, err := ParseEntityPageManifest830G1(raw)
	require.NoError(t, err)
	require.Equal(t, "entity-page-manifest.830.g1.v1", manifest.Contract)
	require.Equal(t, "3ae19c3254df73d9ed678a440404c9c2ec67319709c33c9bb8000c0a15da6a3c", manifest.ManifestSHA256)
	require.Len(t, manifest.Profile.Sections, 7)
	require.Len(t, manifest.Members, 76)
	require.Equal(t, 67, manifest.FieldAssertionCount)
	require.Equal(t, EntityPageTriStateDistribution830G1{
		Present: 2, AbsentExplicitly: 1, Unknown: 64,
	}, manifest.StateDistribution)
	require.Equal(t, "overview", manifest.Members[0].PageKind)
	require.Equal(t, "free_wiki", manifest.Members[len(manifest.Members)-1].PageKind)
	require.Equal(t, "free-wiki", manifest.Members[len(manifest.Members)-1].StableKey)

	seen := make(map[string]struct{}, len(manifest.Members))
	for _, member := range manifest.Members {
		require.NotContains(t, seen, member.PageID)
		seen[member.PageID] = struct{}{}
	}

	field, ok := manifest.Member("field", "cooling_off_period")
	require.True(t, ok)
	require.Equal(t, "犹豫期", field.ShortTitle)
	require.Equal(t,
		"urn:jlx:wiki:a8751a40-83ce-55c8-a160-079b283483ca:entity:ping-an-e-sheng-bao:field:cooling_off_period",
		field.Namespace,
	)
	payload, err := field.FieldAssertionPayload()
	require.NoError(t, err)
	require.Equal(t, "unknown", payload.State)
	require.Nil(t, payload.ValueSnapshot)
	require.Equal(t, "FIELD_UNKNOWN", valueOrEmpty(payload.UnknownReason))
	require.Empty(t, payload.Citations)
}

func TestParseEntityPageManifest830G1RejectsHashAndTopologyDrift(t *testing.T) {
	t.Parallel()

	var vector map[string]any
	require.NoError(t, json.Unmarshal(loadEntityPageGraph830G1Vector(t), &vector))
	members := vector["members"].([]any)
	members[8].(map[string]any)["short_title"] = "漂移标题"
	drifted, err := json.Marshal(vector)
	require.NoError(t, err)

	_, err = ParseEntityPageManifest830G1(drifted)
	require.ErrorIs(t, err, ErrEntityPageGraphContract830G1)
}

func TestEntityPageManifest830G1TopologyIsProfileDriven(t *testing.T) {
	t.Parallel()

	var manifest EntityPageManifest830G1
	require.NoError(t, json.Unmarshal(loadEntityPageGraph830G1Vector(t), &manifest))
	manifest.Profile.Sections = append([]EntityPagePresentationSection830G1(nil), manifest.Profile.Sections[:2]...)
	manifest.Profile.ProfileSHA256 = mustEntityPageHashWithout830G1(t, manifest.Profile.Contract, manifest.Profile, "profile_sha256")

	fieldKeys := make(map[string]struct{})
	fieldOrder := make([]string, 0)
	for _, section := range manifest.Profile.Sections {
		for _, field := range section.Fields {
			fieldKeys[field.FieldKey] = struct{}{}
			fieldOrder = append(fieldOrder, field.FieldKey)
		}
	}
	kept := make([]EntityPageMember830G1, 0, len(fieldOrder)+4)
	fieldMembers := make(map[string]EntityPageMember830G1, len(fieldOrder))
	for _, member := range manifest.Members {
		keep := member.PageKind == "overview" || member.PageKind == "free_wiki"
		if member.PageKind == "section" {
			keep = member.StableKey == manifest.Profile.Sections[0].SectionKey ||
				member.StableKey == manifest.Profile.Sections[1].SectionKey
		}
		if member.PageKind == "field" {
			_, keep = fieldKeys[member.StableKey]
			if keep {
				fieldMembers[member.StableKey] = member
			}
		}
		if keep {
			member.ProfileSHA256 = manifest.Profile.ProfileSHA256
			kept = append(kept, member)
		}
	}

	overview, err := kept[0].OverviewPayload()
	require.NoError(t, err)
	overview.OrderedSectionPageIDs = []string{kept[1].PageID, kept[2].PageID}
	overview.FieldAssertions = overview.FieldAssertions[:0]
	manifest.FieldAssertionPageIDs = manifest.FieldAssertionPageIDs[:0]
	manifest.StateDistribution = EntityPageTriStateDistribution830G1{}
	for _, fieldKey := range fieldOrder {
		member := fieldMembers[fieldKey]
		payload, payloadErr := member.FieldAssertionPayload()
		require.NoError(t, payloadErr)
		overview.FieldAssertions = append(overview.FieldAssertions, payload.Reference)
		manifest.FieldAssertionPageIDs = append(manifest.FieldAssertionPageIDs, member.PageID)
		switch payload.State {
		case "present":
			manifest.StateDistribution.Present++
		case "absent_explicitly":
			manifest.StateDistribution.AbsentExplicitly++
		case "unknown":
			manifest.StateDistribution.Unknown++
		}
	}
	kept[0].Payload = mustEntityPageJSON830G1(t, overview)
	kept[0].PayloadSHA256 = mustEntityPageSHA256830G1(t, overview.Contract, kept[0].Payload)
	for index := range kept {
		kept[index].MemberDigest = mustEntityPageHashWithout830G1(t, kept[index].Contract, kept[index], "member_digest")
	}
	manifest.Members = kept
	manifest.SectionCount = 2
	manifest.FieldAssertionCount = len(fieldOrder)
	manifest.ManifestSHA256 = mustEntityPageHashWithout830G1(t, manifest.Contract, manifest, "manifest_sha256")

	raw := mustEntityPageJSON830G1(t, manifest)
	parsed, err := ParseEntityPageManifest830G1(raw)
	require.NoError(t, err)
	require.Len(t, parsed.Profile.Sections, 2)
	require.Equal(t, 2, parsed.SectionCount)
}

func mustEntityPageJSON830G1(t *testing.T, value any) []byte {
	t.Helper()
	raw, err := json.Marshal(value)
	require.NoError(t, err)
	return raw
}

func mustEntityPageSHA256830G1(t *testing.T, contract string, value any) string {
	t.Helper()
	digest, _, err := entityPageSHA256830G1(contract, value)
	require.NoError(t, err)
	return digest
}

func mustEntityPageHashWithout830G1(t *testing.T, contract string, value any, key string) string {
	t.Helper()
	digest, _, err := entityPageHashWithout830G1(contract, value, key)
	require.NoError(t, err)
	return digest
}

func valueOrEmpty(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}
