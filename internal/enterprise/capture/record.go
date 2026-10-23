// Package capture stores the first parse of a source document: the Markdown, its native PDF
// coordinate structure and the exact chunk ranges, signed and kept per (knowledge, parse
// attempt), so source pages and citations are read back without parsing again.
//
// The on-disk format predates this package (it was written by the G3 first-parse store) and is
// frozen: contract, key derivation, signing domain and JSON layout must not change, or captures
// already on disk stop opening (S7d-2c-1).
package capture

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
)

// Contract names the record layout; it is also part of every key.
const Contract = "g3-first-parse.830.v1"

// ErrUnavailable means a capture failed verification or cannot be produced. The message is the
// one the legacy service error carried, which now points at this value.
var ErrUnavailable = errors.New("concept source authority unavailable 830 g2")

// Identity names one parse of one knowledge in one RAW knowledge base.
type Identity struct {
	TenantID     uint64 `json:"tenant_id"`
	RawKBID      string `json:"raw_kb_id"`
	KnowledgeID  string `json:"knowledge_id"`
	ParseAttempt int64  `json:"parse_attempt"`
	SourceSHA256 string `json:"source_sha256"`
}

// Range is one chunk's exact code-point range in the captured Markdown.
type Range struct {
	Index         int    `json:"index"`
	Start         int    `json:"start"`
	End           int    `json:"end"`
	ContentSHA256 string `json:"content_sha256"`
}

// Record is the signed payload. Field order and tags are the frozen JSON layout.
type Record struct {
	OriginDocReader      *types.DocumentDocReaderReuseReference `json:"origin_docreader,omitempty"`
	Contract             string                                 `json:"contract"`
	Identity             Identity                               `json:"identity"`
	ParserIdentitySHA256 string                                 `json:"parser_identity_sha256"`
	Markdown             string                                 `json:"markdown"`
	Native               *types.NativeStructureArtifact         `json:"native"`
	Chunks               []Range                                `json:"chunks"`
}

// Key derives the file name of a capture from its identity.
func Key(id Identity) (string, error) {
	if id.TenantID == 0 || id.RawKBID == "" || id.KnowledgeID == "" || id.ParseAttempt <= 0 ||
		!ValidSHA256(id.SourceSHA256) {
		return "", ErrUnavailable
	}
	data, err := canonicalJSON(id)
	if err != nil {
		return "", err
	}
	return "first-" + sha256Hex(append([]byte(Contract+"\x00"), data...)), nil
}

// RecordSHA256 is the digest a later parse that reuses this capture names it by.
func RecordSHA256(record *Record) string {
	data, _ := json.Marshal(record)
	return sha256Hex(data)
}

// ReadResult views a record as the parse result it captured.
func ReadResult(record *Record) *types.ReadResult {
	return &types.ReadResult{MarkdownContent: record.Markdown, NativeStructure: record.Native}
}

// Validate checks a record against the identity it is stored under: contract, origin reference,
// native structure and every chunk range. Store.Read also reopens the origin capture.
func Validate(record *Record, id Identity) error {
	if record == nil || record.Contract != Contract || record.Identity != id || len(record.Chunks) == 0 ||
		!validOrigin(record.OriginDocReader, id) {
		return ErrUnavailable
	}
	if err := ValidateNative(ReadResult(record), id.SourceSHA256, record.ParserIdentitySHA256); err != nil {
		return err
	}
	runes := []rune(record.Markdown)
	seen := map[string]bool{}
	for _, r := range record.Chunks {
		key := fmt.Sprintf("%d:%s", r.Index, r.ContentSHA256)
		if r.Index < 0 || r.Start < 0 || r.End <= r.Start || r.End > len(runes) ||
			sha256Hex([]byte(string(runes[r.Start:r.End]))) != r.ContentSHA256 || seen[key] {
			return ErrUnavailable
		}
		seen[key] = true
	}
	return nil
}

// validOrigin accepts no origin, or a reference to an earlier parse of the same source bytes.
func validOrigin(ref *types.DocumentDocReaderReuseReference, id Identity) bool {
	return ref == nil || (ref.OriginParseAttempt > 0 && ref.OriginParseAttempt < id.ParseAttempt &&
		ref.OriginProcessingAttempt > 0 && ref.SourceSHA256 == id.SourceSHA256 && ValidSHA256(ref.ArtifactSHA256))
}

// ValidSHA256 accepts a lowercase hex SHA-256 digest.
func ValidSHA256(value string) bool {
	if len(value) != 64 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func sha256Hex(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}

// canonicalJSON encodes with sorted keys, exact numbers and no HTML escaping.
func canonicalJSON(value any) ([]byte, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	var tree any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(&tree) != nil || !atEOF(decoder) {
		return nil, ErrUnavailable
	}
	var output bytes.Buffer
	encoder := json.NewEncoder(&output)
	encoder.SetEscapeHTML(false)
	if encoder.Encode(tree) != nil {
		return nil, ErrUnavailable
	}
	return bytes.TrimSuffix(output.Bytes(), []byte("\n")), nil
}

func atEOF(decoder *json.Decoder) bool {
	var extra any
	return errors.Is(decoder.Decode(&extra), io.EOF)
}
