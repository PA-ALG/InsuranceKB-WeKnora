package types

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func transferFixture(t *testing.T) (json.RawMessage, G3CandidateTransferBase, map[string][]json.RawMessage, json.RawMessage) {
	t.Helper()
	raw, err := os.ReadFile("testdata/g3_candidate_transfer_v1.json")
	require.NoError(t, err)
	var fixture struct {
		Candidate json.RawMessage
		Base      struct {
			G3CandidateTransferBase
			PublishedProjection map[string][]json.RawMessage `json:"published_projection"`
		}
		Transfer json.RawMessage
	}
	require.NoError(t, json.Unmarshal(raw, &fixture))
	return fixture.Transfer, fixture.Base.G3CandidateTransferBase, fixture.Base.PublishedProjection, fixture.Candidate
}

func TestG3CandidateTransferSharedPythonFixture(t *testing.T) {
	raw, base, members, expected := transferFixture(t)
	transfer, err := ParseG3CandidateTransfer(raw)
	require.NoError(t, err)
	actual, err := ExpandG3CandidateTransfer(transfer, base, members)
	require.NoError(t, err)
	canonical, err := batchConceptCanonicalWire830G3(expected)
	require.NoError(t, err)
	require.Equal(t, string(canonical), string(actual))
	members["fields"][0] = bytes.ReplaceAll(members["fields"][0], []byte(`"evidence":[]`), []byte(`"evidence":null`))
	normalized, err := ExpandG3CandidateTransfer(transfer, base, members)
	require.NoError(t, err)
	require.Equal(t, actual, normalized)
}

func TestG3CandidateTransferRejectsWrongBindingAndManifest(t *testing.T) {
	raw, base, members, _ := transferFixture(t)
	for _, mutate := range []func(*G3CandidateTransferBase){
		func(b *G3CandidateTransferBase) { b.Scope.SpaceID = "other" },
		func(b *G3CandidateTransferBase) { b.ActivationEpoch++ },
		func(b *G3CandidateTransferBase) { b.ReleaseID = "other" },
		func(b *G3CandidateTransferBase) { b.CandidateSHA256 = "changed" },
		func(b *G3CandidateTransferBase) { b.ManifestDigest = "changed" },
	} {
		changed := base
		mutate(&changed)
		transfer, err := ParseG3CandidateTransfer(raw)
		require.NoError(t, err)
		_, err = ExpandG3CandidateTransfer(transfer, changed, members)
		require.Error(t, err)
	}
	transfer, err := ParseG3CandidateTransfer(raw)
	require.NoError(t, err)
	transfer.ManifestSHA256 = base.CandidateSHA256
	_, err = ExpandG3CandidateTransfer(transfer, base, members)
	require.Error(t, err)
}

func TestG3CandidateTransferBoundsAndStrictEncoding(t *testing.T) {
	raw, base, members, _ := transferFixture(t)
	parsed, err := ParseG3CandidateTransfer(raw)
	require.NoError(t, err)
	compressed, err := base64.StdEncoding.DecodeString(parsed.Payload)
	require.NoError(t, err)
	for _, suffix := range [][]byte{[]byte("trailing"), compressed} {
		transfer := *parsed
		transfer.Payload = base64.StdEncoding.EncodeToString(append(append([]byte{}, compressed...), suffix...))
		_, err := ExpandG3CandidateTransfer(&transfer, base, members)
		require.Error(t, err)
	}
	transfer := *parsed
	transfer.DecodedBytes = 1
	_, err = ExpandG3CandidateTransfer(&transfer, base, members)
	require.Error(t, err)
	transfer = *parsed
	transfer.DecodedBytes = MaxG3CandidateDeltaBytes + 1
	_, err = ExpandG3CandidateTransfer(&transfer, base, members)
	require.Error(t, err)
	for _, body := range []string{
		`{"candidate":{},"candidate":{},"members":{}}`,
		`{"candidate":{"request":{"base_request":{}},"compile_result":{"output":{}}},"members":{"sources":[{"base_index":0},{"base_index":0}],"existing_definitions":[],"existing_fields":[],"existing_pages":[],"definitions":[],"fields":[],"pages":[]}}`,
		`{"candidate":{"request":{"base_request":{}},"compile_result":{"output":{}}},"members":{"sources":[{"base_index":999}],"existing_definitions":[],"existing_fields":[],"existing_pages":[],"definitions":[],"fields":[],"pages":[]}}`,
	} {
		var buf bytes.Buffer
		writer := gzip.NewWriter(&buf)
		_, err := writer.Write([]byte(body))
		require.NoError(t, err)
		require.NoError(t, writer.Close())
		transfer := *parsed
		transfer.Payload = base64.StdEncoding.EncodeToString(buf.Bytes())
		transfer.DecodedBytes = len(body)
		digest := sha256.Sum256([]byte(body))
		transfer.PayloadSHA256 = hex.EncodeToString(digest[:])
		_, err = ExpandG3CandidateTransfer(&transfer, base, members)
		require.Error(t, err)
	}
}
