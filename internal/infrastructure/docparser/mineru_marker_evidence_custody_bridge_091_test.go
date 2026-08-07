package docparser

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
)

type markerCustodyFakeReader struct {
	*fakeMinerUCaptureReader
	marker *minerUCrossPageMarkerProvenance
}

func (f *markerCustodyFakeReader) captureCrossPageMarkerProvenance() *minerUCrossPageMarkerProvenance {
	return f.marker
}

func TestExtractMinerUZipBytesWithCustodyUsesOneZIPForFactsAndMarkers(t *testing.T) {
	t.Parallel()
	middle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
		`{"page_idx":0,"para_blocks":[{"type":"text","cross_page":true,"lines_deleted":true}]},` +
		`{"page_idx":1,"para_blocks":[]}]}`
	zipData := crossPageFixtureZip(t, []crossPageFixtureEntry{
		{"result.md", "presentation"},
		{"result_content_list.json", `[{"type":"text","page_idx":0,"bbox":[0,0,1,1],"text":"safe"}]`},
		{"result_middle.json", middle},
	})

	_, _, _, facts, markers, err := extractMinerUZipBytesWithCustody(
		zipData, minerUTermsSourceSHA256, "pipeline", true,
	)
	if err != nil {
		t.Fatal(err)
	}
	if facts == nil || markers == nil || markers.MarkerCount != 2 ||
		facts.SourceSHA256 != markers.SourceSHA256 ||
		facts.ParserModel != markers.ParserModel ||
		facts.MinerUVersion != markers.MinerUVersion ||
		facts.RawZIPSHA256 != markers.RawZIPSHA256 ||
		facts.NativeMemberSHA256 != markers.NativeMemberSHA256 {
		t.Fatalf("same-read custody was not closed: facts=%#v markers=%#v", facts, markers)
	}
	if markers.Markers[0].MarkerSHA256 == markers.Markers[1].MarkerSHA256 {
		t.Fatal("cross_page and lines_deleted marker evidence collided")
	}
}

func TestMarkerCustodyRetainsBodyFreeNativeHierarchyFromSameMiddleMember(t *testing.T) {
	t.Parallel()
	middle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
		`{"page_idx":0,"para_blocks":[` +
		`{"type":"text","text_level":1,"bbox":[0,0,100,20],"text":"private heading"},` +
		`{"type":"text","cross_page":true,"bbox":[0,21,100,80],"text":"private body"}]},` +
		`{"page_idx":1,"para_blocks":[{"type":"text","bbox":[0,0,100,80],"text":"private continuation"}]}]}`
	zipData := crossPageFixtureZip(t, []crossPageFixtureEntry{
		{"result.md", "presentation"},
		{"result_content_list.json", `[{"type":"text","page_idx":0,"bbox":[0,0,1,1],"text":"safe"}]`},
		{"result_middle.json", middle},
	})

	_, _, sanitized, _, markers, err := extractMinerUZipBytesWithCustody(
		zipData, minerUTermsSourceSHA256, "pipeline", true,
	)
	if err != nil {
		t.Fatal(err)
	}
	if sanitized == nil || !bytes.Contains(sanitized.SanitizedJSON, []byte(`"contract":"mineru-native-structure.v1"`)) {
		t.Fatalf("canonical structure contract drifted: %s", sanitized)
	}
	if markers == nil || markers.NativeHierarchy == nil {
		t.Fatal("same-read native hierarchy was not retained")
	}
	hierarchy := markers.NativeHierarchy
	if hierarchy.Status != minerUNativeHierarchyCaptured || hierarchy.HierarchyFieldCount != 1 ||
		hierarchy.NodeCount != 3 || hierarchy.Nodes[0].TextLevel == nil ||
		*hierarchy.Nodes[0].TextLevel != 1 || hierarchy.Nodes[1].StructuralPath != "p0/b1" ||
		hierarchy.Nodes[2].ReadingOrder != 2 {
		t.Fatalf("native hierarchy facts drifted: %#v", hierarchy)
	}
	wire, err := json.Marshal(hierarchy)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"private heading", "private body", "private continuation"} {
		if bytes.Contains(wire, []byte(forbidden)) {
			t.Fatalf("native hierarchy leaked source body via %q", forbidden)
		}
	}
}

func TestCaptureMinerUNativeStructureCarriesMarkerCompanionAndBindsIdentity(t *testing.T) {
	t.Parallel()
	sourcePath, facts, marker, reader := markerCaptureFixture(t, minerUTermsSourceSHA256)
	parent := t.TempDir()
	reader.crossPageFacts = facts
	readerWithMarker := &markerCustodyFakeReader{fakeMinerUCaptureReader: reader, marker: marker}

	outputPath, err := captureMinerUNativeStructure(
		context.Background(),
		MinerUArtifactCaptureRequest{
			SourcePath: sourcePath, SourceSHA256: minerUTermsSourceSHA256,
			AttemptNumber: 2, AttemptRole: "bounded_upgrade", Generation: intPointer(0),
			OutputDir:       filepath.Join(parent, "evidence"),
			ParserOverrides: map[string]string{"mineru_cloud_model": "pipeline"},
		},
		func(string) (string, bool) { return "in-memory-secret", true },
		func(map[string]string) minerUCaptureReader { return readerWithMarker },
		fixedCaptureClock(time.Time{}, time.Millisecond),
	)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := os.ReadFile(outputPath)
	if err != nil {
		t.Fatal(err)
	}
	var envelope struct {
		Contract              string                           `json:"contract"`
		SourceSHA256          string                           `json:"source_sha256"`
		Attempt               minerUCaptureAttemptIdentity     `json:"attempt"`
		RawStructureSHA256    string                           `json:"raw_structure_sha256"`
		SanitizedSHA256       string                           `json:"sanitized_structure_sha256"`
		ContentSHA256         string                           `json:"content_snapshot_sha256"`
		CaptureIdentitySHA256 string                           `json:"capture_identity_sha256"`
		Parser                minerUCaptureParserLedger        `json:"parser"`
		Facts                 *minerUCrossPageProjection       `json:"cross_page_facts"`
		Markers               *minerUCrossPageMarkerProvenance `json:"cross_page_marker_provenance"`
	}
	if err := json.Unmarshal(payload, &envelope); err != nil {
		t.Fatal(err)
	}
	if envelope.Facts == nil || envelope.Markers == nil ||
		envelope.Facts.ProjectionSHA256 != facts.ProjectionSHA256 ||
		envelope.Markers.ReplayDigestSHA256 != marker.ReplayDigestSHA256 {
		t.Fatalf("capture lost cross-page custody: %#v", envelope)
	}
	preimage, err := json.Marshal(struct {
		Contract                     string                       `json:"contract"`
		SourceSHA256                 string                       `json:"source_sha256"`
		Attempt                      minerUCaptureAttemptIdentity `json:"attempt"`
		ParserConfigSHA256           string                       `json:"parser_config_sha256"`
		RawStructureSHA256           string                       `json:"raw_structure_sha256"`
		SanitizedStructureSHA256     string                       `json:"sanitized_structure_sha256"`
		ContentSnapshotSHA256        string                       `json:"content_snapshot_sha256"`
		CrossPageProjectionSHA256    string                       `json:"cross_page_projection_sha256,omitempty"`
		MarkerProvenanceReplaySHA256 string                       `json:"marker_provenance_replay_sha256,omitempty"`
	}{
		Contract: minerUCaptureContract, SourceSHA256: envelope.SourceSHA256,
		Attempt: envelope.Attempt, ParserConfigSHA256: envelope.Parser.ConfigSHA256,
		RawStructureSHA256:           envelope.RawStructureSHA256,
		SanitizedStructureSHA256:     envelope.SanitizedSHA256,
		ContentSnapshotSHA256:        envelope.ContentSHA256,
		CrossPageProjectionSHA256:    envelope.Facts.ProjectionSHA256,
		MarkerProvenanceReplaySHA256: envelope.Markers.ReplayDigestSHA256,
	})
	if err != nil {
		t.Fatal(err)
	}
	want := sha256.Sum256(preimage)
	if envelope.CaptureIdentitySHA256 != hex.EncodeToString(want[:]) {
		t.Fatalf("capture identity omitted projection/marker custody: %s", envelope.CaptureIdentitySHA256)
	}
	for _, forbidden := range []string{"in-memory-secret", "cross_page\":true"} {
		if strings.Contains(string(payload), forbidden) {
			t.Fatalf("custody leaked or widened authority with %q", forbidden)
		}
	}
	markerJSON, err := json.Marshal(envelope.Markers)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"source_page", "target_page", "endpoint", "relation", "ADMIT"} {
		if strings.Contains(string(markerJSON), forbidden) {
			t.Fatalf("marker companion widened authority with %q", forbidden)
		}
	}
}

func TestCaptureMinerUNativeStructureRequiresExactMarkerPairForTargetedSources(t *testing.T) {
	t.Parallel()
	sourcePath, facts, marker, reader := markerCaptureFixture(t, minerUTermsSourceSHA256)
	reader.crossPageFacts = facts
	for name, captureReader := range map[string]minerUCaptureReader{
		"missing-marker": reader,
		"marker-count-drift": &markerCustodyFakeReader{
			fakeMinerUCaptureReader: reader,
			marker: func() *minerUCrossPageMarkerProvenance {
				copy := *marker
				copy.Markers = nil
				copy.MarkerCount = 0
				sealMinerUCrossPageMarkerProvenance(&copy)
				return &copy
			}(),
		},
		"foreign-marker": &markerCustodyFakeReader{
			fakeMinerUCaptureReader: reader,
			marker: func() *minerUCrossPageMarkerProvenance {
				_, _, marker, _ := markerCaptureFixture(t, minerURatesSourceSHA256)
				return marker
			}(),
		},
	} {
		t.Run(name, func(t *testing.T) {
			outputDir := filepath.Join(t.TempDir(), "evidence")
			_, err := captureMinerUNativeStructure(
				context.Background(),
				MinerUArtifactCaptureRequest{
					SourcePath: sourcePath, SourceSHA256: minerUTermsSourceSHA256,
					AttemptNumber: 2, AttemptRole: "bounded_upgrade", Generation: intPointer(0),
					OutputDir:       outputDir,
					ParserOverrides: map[string]string{"mineru_cloud_model": "pipeline"},
				},
				func(string) (string, bool) { return "in-memory-secret", true },
				func(map[string]string) minerUCaptureReader { return captureReader },
				fixedCaptureClock(time.Time{}, time.Millisecond),
			)
			if !errors.Is(err, ErrMinerUCrossPageProjectionInvalid) {
				t.Fatalf("marker custody drift was not typed: %v", err)
			}
			if _, statErr := os.Lstat(outputDir); !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("failed capture left output: %v", statErr)
			}
		})
	}
}

func markerCaptureFixture(
	t *testing.T,
	sourceSHA string,
) (string, *minerUCrossPageProjection, *minerUCrossPageMarkerProvenance, *fakeMinerUCaptureReader) {
	t.Helper()
	roleFile := "保险条款.pdf"
	if sourceSHA == minerURatesSourceSHA256 {
		roleFile = "费率表.pdf"
	}
	repositoryPDF := filepath.Join("..", "..", "..", "dataset", "shouxian_product",
		"平安e生保（尊享版）医疗保险", roleFile)
	pdfBytes, err := os.ReadFile(repositoryPDF)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(pdfBytes)
	if hex.EncodeToString(digest[:]) != sourceSHA {
		t.Fatal("fixture source identity drifted")
	}
	sourcePath := filepath.Join(t.TempDir(), "source.pdf")
	if err := os.WriteFile(sourcePath, pdfBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	middle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
		`{"page_idx":0,"para_blocks":[{"type":"text","cross_page":true}]},` +
		`{"page_idx":1,"para_blocks":[]}]}`
	zipData := crossPageFixtureZip(t, []crossPageFixtureEntry{{"result_middle.json", middle}})
	facts, err := projectMinerUCrossPageZip(zipData, sourceSHA)
	if err != nil {
		t.Fatal(err)
	}
	marker, err := projectMinerUCrossPageMarkerProvenanceZip(zipData, sourceSHA)
	if err != nil {
		t.Fatal(err)
	}
	sanitized := []byte(`{"contract":"mineru-native-structure.v1","pages":[],"unsupported":[]}`)
	sanitizedHash := sha256.Sum256(sanitized)
	reader := &fakeMinerUCaptureReader{
		result: &types.ReadResult{
			MarkdownContent: "same-read safe snapshot",
			NativeStructure: &types.NativeStructureArtifact{
				SchemaVersion: minerUStructureSchema, SourceSHA256: sourceSHA,
				RawSHA256:       strings.Repeat("a", 64),
				SanitizedSHA256: hex.EncodeToString(sanitizedHash[:]),
				SanitizedJSON:   sanitized,
			},
		},
		calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
	}
	return sourcePath, facts, marker, reader
}
