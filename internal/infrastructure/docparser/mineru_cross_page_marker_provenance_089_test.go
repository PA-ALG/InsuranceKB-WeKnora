package docparser

import (
	"bytes"
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

func TestProjectMinerUCrossPageMarkerProvenanceBindsKindAndNativePath(t *testing.T) {
	t.Parallel()
	middle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
		`{"page_idx":0,"para_blocks":[{"type":"table","index":9,"lines":[{"type":"line","spans":[` +
		`{"type":"text"},{"type":"text","content":"private body",` +
		`"vendor_url":"https://private.example.invalid","cross_page":true,"lines_deleted":true}]}]}]},` +
		`{"page_idx":1,"para_blocks":[]}]}`
	zipData := crossPageFixtureZip(t, []crossPageFixtureEntry{{"private/result_middle.json", middle}})

	got, err := projectMinerUCrossPageMarkerProvenanceZip(zipData, minerURatesSourceSHA256)
	if err != nil {
		t.Fatal(err)
	}
	if got.Contract != minerUCrossPageMarkerProvenanceContract || got.MarkerCount != 2 ||
		got.SourceSHA256 != minerURatesSourceSHA256 || got.ParserModel != "pipeline" ||
		got.MinerUVersion != "3.4.4" || !validLowerSHA256(got.RawZIPSHA256) ||
		!validLowerSHA256(got.NativeMemberSHA256) || !validLowerSHA256(got.ReplayDigestSHA256) {
		t.Fatalf("marker provenance identity is incomplete: %#v", got)
	}
	if got.Markers[0].MarkerKind != "cross_page" || got.Markers[1].MarkerKind != "lines_deleted" ||
		got.Markers[0].MarkerSHA256 == got.Markers[1].MarkerSHA256 {
		t.Fatalf("native marker kinds collided: %#v", got.Markers)
	}
	for _, marker := range got.Markers {
		if marker.PageIndex != 0 || marker.NodeType != "text" || marker.LocalIndex != 1 ||
			marker.StructuralPath != "p0/b0/lines/0/spans/1" ||
			!validLowerSHA256(marker.StructuralPathSHA256) || !validLowerSHA256(marker.MarkerSHA256) {
			t.Fatalf("marker lost native structural identity: %#v", marker)
		}
	}
	serialized, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{
		"private body", "private.example", "result_middle", "para_blocks", "vendor_url",
		"source_page", "target_page", "relation", "endpoint", "ADMIT",
	} {
		if bytes.Contains(serialized, []byte(forbidden)) {
			t.Fatalf("companion leaked or exceeded authority with %q: %s", forbidden, serialized)
		}
	}

	legacy, err := projectMinerUCrossPageZip(zipData, minerURatesSourceSHA256)
	if err != nil {
		t.Fatal(err)
	}
	legacyJSON, err := json.Marshal(legacy)
	if err != nil {
		t.Fatal(err)
	}
	if legacy.Contract != "mineru-native-cross-page-facts.v1" ||
		legacy.Status != minerUCrossPageAmbiguous || legacy.AmbiguousMarkerCount != 2 ||
		bytes.Contains(legacyJSON, []byte("marker_kind")) ||
		bytes.Contains(legacyJSON, []byte(minerUCrossPageMarkerProvenanceContract)) {
		t.Fatalf("089 mutated the 062 v1 envelope: %s", legacyJSON)
	}
}

func TestReplayMinerUCrossPageMarkerProvenanceRejectsEveryCustodyDrift(t *testing.T) {
	t.Parallel()
	middle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
		`{"page_idx":0,"para_blocks":[{"type":"text","cross_page":true}]},` +
		`{"page_idx":1,"para_blocks":[]}]}`
	zipData := crossPageFixtureZip(t, []crossPageFixtureEntry{{"result_middle.json", middle}})
	valid, err := projectMinerUCrossPageMarkerProvenanceZip(zipData, minerUTermsSourceSHA256)
	if err != nil {
		t.Fatal(err)
	}
	if err := replayMinerUCrossPageMarkerProvenanceZip(zipData, minerUTermsSourceSHA256, valid); err != nil {
		t.Fatalf("valid companion did not replay: %v", err)
	}

	mutations := map[string]func(*minerUCrossPageMarkerProvenance){
		"contract":     func(value *minerUCrossPageMarkerProvenance) { value.Contract = "foreign" },
		"source":       func(value *minerUCrossPageMarkerProvenance) { value.SourceSHA256 = minerURatesSourceSHA256 },
		"parser":       func(value *minerUCrossPageMarkerProvenance) { value.ParserModel = "foreign" },
		"version":      func(value *minerUCrossPageMarkerProvenance) { value.MinerUVersion = "3.4.5" },
		"raw":          func(value *minerUCrossPageMarkerProvenance) { value.RawZIPSHA256 = strings.Repeat("b", 64) },
		"member":       func(value *minerUCrossPageMarkerProvenance) { value.NativeMemberSHA256 = strings.Repeat("c", 64) },
		"kind":         func(value *minerUCrossPageMarkerProvenance) { value.Markers[0].MarkerKind = "lines_deleted" },
		"unknown-kind": func(value *minerUCrossPageMarkerProvenance) { value.Markers[0].MarkerKind = "future_marker" },
		"page":         func(value *minerUCrossPageMarkerProvenance) { value.Markers[0].PageIndex = 1 },
		"path": func(value *minerUCrossPageMarkerProvenance) {
			value.Markers[0].StructuralPathSHA256 = strings.Repeat("d", 64)
		},
		"path-preimage": func(value *minerUCrossPageMarkerProvenance) {
			value.Markers[0].StructuralPath = "p0/b9"
		},
		"type":        func(value *minerUCrossPageMarkerProvenance) { value.Markers[0].NodeType = "table" },
		"local-index": func(value *minerUCrossPageMarkerProvenance) { value.Markers[0].LocalIndex = 1 },
		"marker-hash": func(value *minerUCrossPageMarkerProvenance) { value.Markers[0].MarkerSHA256 = strings.Repeat("e", 64) },
		"replay-hash": func(value *minerUCrossPageMarkerProvenance) { value.ReplayDigestSHA256 = strings.Repeat("f", 64) },
		"duplicate": func(value *minerUCrossPageMarkerProvenance) {
			value.Markers = append(value.Markers, value.Markers[0])
			value.MarkerCount = len(value.Markers)
		},
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			candidate := *valid
			candidate.Markers = append([]minerUCrossPageMarkerEvidence(nil), valid.Markers...)
			mutate(&candidate)
			if name != "marker-hash" && name != "replay-hash" {
				for index := range candidate.Markers {
					candidate.Markers[index].MarkerSHA256 = minerUCrossPageMarkerSHA256(
						candidate.SourceSHA256,
						candidate.NativeMemberSHA256,
						candidate.Markers[index],
					)
				}
				sealMinerUCrossPageMarkerProvenance(&candidate)
			}
			if err := replayMinerUCrossPageMarkerProvenanceZip(
				zipData, minerUTermsSourceSHA256, &candidate,
			); !errors.Is(err, ErrMinerUCrossPageMarkerProvenanceInvalid) {
				t.Fatalf("custody drift was not typed: %v", err)
			}
		})
	}

	changedZIP := crossPageFixtureZip(t, []crossPageFixtureEntry{{"result_middle.json", strings.Replace(middle, "cross_page", "lines_deleted", 1)}})
	if err := replayMinerUCrossPageMarkerProvenanceZip(
		changedZIP, minerUTermsSourceSHA256, valid,
	); !errors.Is(err, ErrMinerUCrossPageMarkerProvenanceInvalid) {
		t.Fatalf("raw native member drift was not rejected: %v", err)
	}
}

func TestProjectMinerUCrossPageMarkerProvenanceFailsClosedOnMalformedMarkerNode(t *testing.T) {
	t.Parallel()
	for name, middle := range map[string]string{
		"wrong-marker-type": `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[{"page_idx":0,"para_blocks":[{"type":"text","cross_page":"true"}]}]}`,
		"missing-node-type": `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[{"page_idx":0,"para_blocks":[{"cross_page":true}]}]}`,
		"private-node-type": `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[{"page_idx":0,"para_blocks":[{"type":"secret_token","cross_page":true}]}]}`,
		"bad-page":          `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[{"page_idx":-1,"para_blocks":[{"type":"text","cross_page":true}]}]}`,
	} {
		t.Run(name, func(t *testing.T) {
			zipData := crossPageFixtureZip(t, []crossPageFixtureEntry{{"result_middle.json", middle}})
			if _, err := projectMinerUCrossPageMarkerProvenanceZip(
				zipData, minerUTermsSourceSHA256,
			); !errors.Is(err, ErrMinerUCrossPageMarkerProvenanceInvalid) {
				t.Fatalf("malformed marker node was not typed: %v", err)
			}
		})
	}
}
