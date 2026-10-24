package capture

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
)

// Store keeps sealed captures as <key>.json under one root directory.
type Store struct {
	root string
	keys *Keys
}

// NewStore opens captures under root with the given signing ring.
func NewStore(root string, keys *Keys) *Store {
	return &Store{root: root, keys: keys}
}

// DefaultRoot is where deployments keep captures: $LOCAL_STORAGE_BASE_DIR (default /data/files)
// /.concept-source-reuse-v1. The directory name predates this package and is frozen with the format.
func DefaultRoot() string {
	base := strings.TrimSpace(os.Getenv("LOCAL_STORAGE_BASE_DIR"))
	if base == "" {
		base = "/data/files"
	}
	return filepath.Join(base, ".concept-source-reuse-v1")
}

func (s *Store) path(key string) string {
	return filepath.Join(s.root, key+".json")
}

// readSealed returns the verified payload. A missing file is reported as os.ErrNotExist before
// any key is consulted, so "never captured" stays distinguishable from "cannot be verified".
func (s *Store) readSealed(key string) ([]byte, error) {
	data, err := os.ReadFile(s.path(key))
	if err != nil {
		return nil, err
	}
	return s.keys.open(key, data)
}

// Read returns the verified capture of one parse. A capture that names an origin (a parse reused
// from an earlier attempt) is accepted only if that origin capture still opens and matches.
func (s *Store) Read(id Identity) (*Record, error) {
	if s == nil {
		return nil, ErrUnavailable
	}
	key, err := Key(id)
	if err != nil {
		return nil, err
	}
	data, err := s.readSealed(key)
	if err != nil {
		return nil, err
	}
	var record Record
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&record) != nil || !atEOF(decoder) {
		return nil, ErrUnavailable
	}
	if err := Validate(&record, id); err != nil {
		return nil, err
	}
	if err := s.checkOrigin(&record); err != nil {
		return nil, err
	}
	return &record, nil
}

// checkOrigin reopens the capture a reused parse points at: a digest-shaped reference alone is
// not provenance. The origin attempt is always earlier, so the recursion ends.
func (s *Store) checkOrigin(record *Record) error {
	if record.OriginDocReader == nil {
		return nil
	}
	id := record.Identity
	id.ParseAttempt = record.OriginDocReader.OriginParseAttempt
	origin, err := s.Read(id)
	if err != nil || RecordSHA256(origin) != record.OriginDocReader.ArtifactSHA256 ||
		origin.ParserIdentitySHA256 != record.ParserIdentitySHA256 || origin.Markdown != record.Markdown ||
		origin.Native.SanitizedSHA256 != record.Native.SanitizedSHA256 {
		return ErrUnavailable
	}
	return nil
}

// Save captures one parse and its chunk ranges. Blank chunks are not recorded. A capture is
// immutable: saving the same record again succeeds, anything else under the same key fails.
func (s *Store) Save(
	id Identity, result *types.ReadResult, chunks []types.ParsedChunk, origin *types.DocumentDocReaderReuseReference,
) error {
	if s == nil || result == nil || result.Error != "" || result.NativeStructure == nil ||
		len(result.ImageRefs) > 0 || result.IsAudio {
		return ErrUnavailable
	}
	key, err := Key(id)
	if err != nil {
		return err
	}
	parserIdentity, err := ParserIdentitySHA256(result)
	if err != nil {
		return err
	}
	ranges, err := chunkRanges(chunks)
	if err != nil {
		return err
	}
	record := Record{
		Contract: Contract, Identity: id, ParserIdentitySHA256: parserIdentity,
		Markdown: result.MarkdownContent, Native: result.NativeStructure, Chunks: ranges,
	}
	if origin != nil {
		reference := *origin
		record.OriginDocReader = &reference
	}
	if err := Validate(&record, id); err != nil {
		return err
	}
	if err := s.checkOrigin(&record); err != nil {
		return err
	}
	data, err := json.Marshal(record)
	if err != nil {
		return err
	}
	existing, err := s.readSealed(key)
	if err == nil {
		if !bytes.Equal(existing, data) {
			return ErrUnavailable
		}
		return nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return s.publish(key, data)
}

// chunkRanges records each distinct (index, content) once; the same pair at another range means
// the chunk plan is ambiguous and nothing is captured.
func chunkRanges(chunks []types.ParsedChunk) ([]Range, error) {
	ranges := []Range{}
	seen := map[string]Range{}
	for _, chunk := range chunks {
		if strings.TrimSpace(chunk.Content) == "" {
			continue
		}
		r := Range{
			Index: chunk.Seq, Start: chunk.Start, End: chunk.End, ContentSHA256: sha256Hex([]byte(chunk.Content)),
		}
		key := fmt.Sprintf("%d:%s", r.Index, r.ContentSHA256)
		if previous, ok := seen[key]; ok {
			if previous != r {
				return nil, ErrUnavailable
			}
			continue
		}
		seen[key] = r
		ranges = append(ranges, r)
	}
	return ranges, nil
}

// publish hard-links a fully written temporary file into place. A link never replaces an existing
// file, so concurrent writers in any process cannot overwrite a capture or expose a partial one;
// the loser compares and accepts only identical bytes.
func (s *Store) publish(key string, data []byte) error {
	encoded, err := s.keys.seal(key, data)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(s.root, 0o700); err != nil {
		return err
	}
	temp, err := os.CreateTemp(s.root, ".first-parse-*")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(temp.Name()) }()
	_, err = temp.Write(encoded)
	if err == nil {
		err = temp.Sync()
	}
	closeErr := temp.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err = os.Link(temp.Name(), s.path(key)); errors.Is(err, os.ErrExist) {
		existing, readErr := s.readSealed(key)
		if readErr != nil {
			return readErr
		}
		if !bytes.Equal(existing, data) {
			return ErrUnavailable
		}
		return nil
	}
	return err
}
