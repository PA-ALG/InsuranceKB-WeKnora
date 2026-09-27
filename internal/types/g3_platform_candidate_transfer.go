package types

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
)

const (
	G3CandidateTransferContract = "g3-platform-candidate-transfer.830.v1"
	MaxG3CandidateTransferBytes = 8 << 20
	MaxG3CandidateDeltaBytes    = 64 << 20
	MaxG3CandidateExpandedBytes = 128 << 20
)

var ErrG3CandidateTransfer = errors.New("invalid or oversized candidate transfer")

// Base identifies the outer published snapshot, not the projection's parent.
type G3CandidateTransferBase struct {
	Scope           WikiReleaseScope `json:"scope"`
	ReleaseID       string           `json:"release_id"`
	ActivationEpoch uint64           `json:"activation_epoch"`
	CandidateSHA256 string           `json:"candidate_sha256"`
	ManifestDigest  string           `json:"manifest_digest"`
}

type G3CandidateTransfer struct {
	Contract       string                  `json:"contract"`
	Base           G3CandidateTransferBase `json:"base"`
	ManifestSHA256 string                  `json:"manifest_sha256"`
	Encoding       string                  `json:"encoding"`
	DecodedBytes   int                     `json:"decoded_bytes"`
	PayloadSHA256  string                  `json:"payload_sha256"`
	Payload        string                  `json:"payload"`
}

func ParseG3CandidateTransfer(raw []byte) (*G3CandidateTransfer, error) {
	var value G3CandidateTransfer
	if len(raw) > MaxG3CandidateTransferBytes || strictConceptDecode830G2(raw, &value) != nil || !validG3CandidateTransfer(&value) {
		return nil, ErrG3CandidateTransfer
	}
	return &value, nil
}

func validG3CandidateTransfer(value *G3CandidateTransfer) bool {
	return value != nil && value.Contract == G3CandidateTransferContract && value.Encoding == "gzip+base64" &&
		value.DecodedBytes > 0 && value.DecodedBytes <= MaxG3CandidateDeltaBytes && len(value.Payload) <= MaxG3CandidateTransferBytes &&
		validHash830G3(value.PayloadSHA256) && validHash830G3(value.ManifestSHA256) &&
		validHash830G3(value.Base.CandidateSHA256) && validHash830G3(value.Base.ManifestDigest) &&
		value.Base.ReleaseID != "" && value.Base.ActivationEpoch > 0 && value.Base.Scope.TenantID > 0 &&
		value.Base.Scope.SpaceID != "" && value.Base.Scope.RawKBID != "" && value.Base.Scope.WikiKBID != "" &&
		value.Base.Scope.RawKBID != value.Base.Scope.WikiKBID
}

func transferDigest(raw []byte) string {
	digest := sha256.Sum256(raw)
	return hex.EncodeToString(digest[:])
}

// There is no caller supplied path or general patch interpreter.
var candidateTransferSlots = []struct{ name, kind, parent string }{
	{"sources", "sources", "base_request"},
	{"existing_definitions", "definitions", "base_request"},
	{"existing_fields", "fields", "base_request"},
	{"existing_pages", "pages", "base_request"},
	{"definitions", "definitions", "output"},
	{"fields", "fields", "output"},
	{"pages", "pages", "output"},
}

func transferObject(raw json.RawMessage) (map[string]json.RawMessage, error) {
	if len(bytes.TrimSpace(raw)) == 0 || bytes.TrimSpace(raw)[0] != '{' {
		return nil, ErrG3CandidateTransfer
	}
	var value map[string]json.RawMessage
	if json.Unmarshal(raw, &value) != nil || value == nil {
		return nil, ErrG3CandidateTransfer
	}
	return value, nil
}

// Only the existing optional collection slots have null/empty compatibility.
// This adapter never normalizes scalar values or modifies the stored projection.
func transferPublishedMember(raw json.RawMessage, kind string) (json.RawMessage, error) {
	keys := map[string][]string{
		"definitions": {"aliases"},
		"fields":      {"evidence", "concept_ids", "conditions", "exceptions"},
		"pages":       {"concept_ids", "conditions", "exceptions"},
	}[kind]
	if len(keys) == 0 {
		return raw, nil
	}
	row, err := transferObject(raw)
	if err != nil {
		return nil, err
	}
	for _, key := range keys {
		if bytes.Equal(bytes.TrimSpace(row[key]), []byte("null")) {
			row[key] = json.RawMessage("[]")
		}
	}
	return transferJSON(row)
}

func transferJSON(value any) ([]byte, error) {
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(buffer.Bytes(), []byte("\n")), nil
}

// Expand consumes an already authorized, immutable published projection.
// The caller must still run the existing complete candidate/source/policy checks.
func ExpandG3CandidateTransfer(value *G3CandidateTransfer, base G3CandidateTransferBase, published map[string][]json.RawMessage) ([]byte, error) {
	if !validG3CandidateTransfer(value) || value.Base != base {
		return nil, ErrG3CandidateTransfer
	}
	compressed, err := base64.StdEncoding.Strict().DecodeString(value.Payload)
	if err != nil || base64.StdEncoding.EncodeToString(compressed) != value.Payload {
		return nil, ErrG3CandidateTransfer
	}
	stream := bytes.NewReader(compressed)
	reader, err := gzip.NewReader(stream)
	if err != nil {
		return nil, ErrG3CandidateTransfer
	}
	reader.Multistream(false)
	payload, readErr := io.ReadAll(io.LimitReader(reader, int64(value.DecodedBytes)+1))
	closeErr := reader.Close()
	if readErr != nil || closeErr != nil || stream.Len() != 0 || len(payload) != value.DecodedBytes || transferDigest(payload) != value.PayloadSHA256 {
		return nil, ErrG3CandidateTransfer
	}
	// Reject duplicate keys before extracting the closed delta envelope. No
	// canonicalization may silently discard ambiguous input, at any depth.
	if !conceptJSONUnicodeValid830G2(payload) || !conceptJSONUniqueKeys830G2(payload) {
		return nil, ErrG3CandidateTransfer
	}
	envelope, err := transferObject(payload)
	if err != nil || len(envelope) != 2 {
		return nil, ErrG3CandidateTransfer
	}
	candidate, err := transferObject(envelope["candidate"])
	if err != nil {
		return nil, err
	}
	members, err := transferObject(envelope["members"])
	if err != nil || len(members) != len(candidateTransferSlots) {
		return nil, ErrG3CandidateTransfer
	}
	request, err := transferObject(candidate["request"])
	if err != nil {
		return nil, err
	}
	baseRequest, err := transferObject(request["base_request"])
	if err != nil {
		return nil, err
	}
	compiled, err := transferObject(candidate["compile_result"])
	if err != nil {
		return nil, err
	}
	output, err := transferObject(compiled["output"])
	if err != nil {
		return nil, err
	}
	// Conservative accounting includes the delta and every referenced member
	// before allocating the expanded arrays. Inline values are already counted.
	expandedBudget := len(payload)
	for _, slot := range candidateTransferSlots {
		parent := baseRequest
		if slot.parent == "output" {
			parent = output
		}
		if _, exists := parent[slot.name]; exists {
			return nil, ErrG3CandidateTransfer
		}
		raw, exists := members[slot.name]
		if !exists || len(bytes.TrimSpace(raw)) == 0 || bytes.TrimSpace(raw)[0] != '[' {
			return nil, ErrG3CandidateTransfer
		}
		var items []map[string]json.RawMessage
		if json.Unmarshal(raw, &items) != nil {
			return nil, ErrG3CandidateTransfer
		}
		rows := make([]json.RawMessage, 0, len(items))
		used := map[int]bool{}
		for _, item := range items {
			if len(item) != 1 {
				return nil, ErrG3CandidateTransfer
			}
			if rawIndex, ok := item["base_index"]; ok {
				var index int
				if bytes.Equal(bytes.TrimSpace(rawIndex), []byte("null")) || json.Unmarshal(rawIndex, &index) != nil || index < 0 || index >= len(published[slot.kind]) || used[index] {
					return nil, ErrG3CandidateTransfer
				}
				used[index] = true
				// Charge raw bytes before even normalizing a potentially large member.
				stored := published[slot.kind][index]
				if len(stored) > MaxG3CandidateExpandedBytes-expandedBudget {
					return nil, ErrG3CandidateTransfer
				}
				expandedBudget += len(stored)
				row, err := transferPublishedMember(stored, slot.kind)
				if err != nil {
					return nil, err
				}
				// Marshaling can escape characters, so also account for expansion.
				if extra := len(row) - len(stored); extra > 0 {
					if extra > MaxG3CandidateExpandedBytes-expandedBudget {
						return nil, ErrG3CandidateTransfer
					}
					expandedBudget += extra
				}
				rows = append(rows, row)
			} else if row, ok := item["inline"]; ok {
				if _, err := transferObject(row); err != nil {
					return nil, err
				}
				rows = append(rows, row)
			} else {
				return nil, ErrG3CandidateTransfer
			}
		}
		parent[slot.name], err = transferJSON(rows)
		if err != nil {
			return nil, ErrG3CandidateTransfer
		}
	}
	request["base_request"], err = transferJSON(baseRequest)
	if err != nil {
		return nil, ErrG3CandidateTransfer
	}
	candidate["request"], err = transferJSON(request)
	if err != nil {
		return nil, ErrG3CandidateTransfer
	}
	compiled["output"], err = transferJSON(output)
	if err != nil {
		return nil, ErrG3CandidateTransfer
	}
	candidate["compile_result"], err = transferJSON(compiled)
	if err != nil {
		return nil, ErrG3CandidateTransfer
	}
	restored, err := transferJSON(candidate)
	if err != nil || len(restored) > MaxG3CandidateExpandedBytes {
		return nil, ErrG3CandidateTransfer
	}
	canonical, err := batchConceptCanonicalWire830G3(restored)
	if err != nil || len(canonical) > MaxG3CandidateExpandedBytes || transferDigest(canonical) != value.ManifestSHA256 {
		return nil, ErrG3CandidateTransfer
	}
	return canonical, nil
}
