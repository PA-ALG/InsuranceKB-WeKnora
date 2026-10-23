// S7d-2c-1 acceptance (protected, written by Claude): the first-parse capture kernel moves into
// this package without changing what is on disk. testdata/first-parse.sealed.json was written by
// the pre-move service code (G3FirstParseStore.save) from testdata/first-parse.inputs.json with the
// ed25519 seed 32×0x72 under key id "citation-key"; ed25519 signing is deterministic, so the same
// inputs must produce the same bytes (Spec docs/design/slices/S7d-2c-1-首次解析采集迁入企业包.md §4).
// RED until S7d-2c-1: package capture does not exist.
package capture_test

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

type inputs struct {
	Identity capture.Identity               `json:"identity"`
	Key      string                         `json:"key"`
	Markdown string                         `json:"markdown"`
	Native   *types.NativeStructureArtifact `json:"native"`
	Chunks   []types.ParsedChunk            `json:"chunks"`
}

func load(t *testing.T) (inputs, []byte) {
	t.Helper()
	raw, err := os.ReadFile("testdata/first-parse.inputs.json")
	require.NoError(t, err)
	var in inputs
	require.NoError(t, json.Unmarshal(raw, &in))
	sealed, err := os.ReadFile("testdata/first-parse.sealed.json")
	require.NoError(t, err)
	return in, sealed
}

func testKeys() *capture.Keys {
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x72}, ed25519.SeedSize))
	return capture.NewKeys("citation-key", map[string]ed25519.PrivateKey{"citation-key": key})
}

func result(in inputs) *types.ReadResult {
	return &types.ReadResult{MarkdownContent: in.Markdown, NativeStructure: in.Native}
}

func seeded(t *testing.T, in inputs, sealed []byte) string {
	t.Helper()
	root := t.TempDir()
	require.NoError(t, os.WriteFile(filepath.Join(root, in.Key+".json"), sealed, 0o600))
	return root
}

func requireUnavailable(t *testing.T, err error) {
	t.Helper()
	require.ErrorIs(t, err, capture.ErrUnavailable)
}

func TestTheSealedFormatIsUnchanged(t *testing.T) {
	in, sealed := load(t)
	key, err := capture.Key(in.Identity)
	require.NoError(t, err)
	require.Equal(t, in.Key, key)

	root := t.TempDir()
	require.NoError(t, capture.NewStore(root, testKeys()).Save(in.Identity, result(in), in.Chunks, nil))
	written, err := os.ReadFile(filepath.Join(root, in.Key+".json"))
	require.NoError(t, err)
	require.Equal(t, sealed, written, "a capture written after the move must be byte-identical")

	base := t.TempDir()
	t.Setenv("LOCAL_STORAGE_BASE_DIR", base)
	require.Equal(t, filepath.Join(base, ".concept-source-reuse-v1"), capture.DefaultRoot())
}

func TestACaptureWrittenBeforeTheMoveIsRead(t *testing.T) {
	in, sealed := load(t)
	record, err := capture.NewStore(seeded(t, in, sealed), testKeys()).Read(in.Identity)
	require.NoError(t, err)
	require.Equal(t, capture.Contract, record.Contract)
	require.Equal(t, in.Identity, record.Identity)
	require.Equal(t, in.Markdown, record.Markdown)
	require.Equal(t, in.Native.SanitizedSHA256, record.Native.SanitizedSHA256)
	require.Len(t, record.Chunks, 1)
	require.Equal(t, 0, record.Chunks[0].Start)
	require.Equal(t, len([]rune(in.Markdown)), record.Chunks[0].End)
}

func TestReadFailsClosed(t *testing.T) {
	in, sealed := load(t)
	root := seeded(t, in, sealed)

	_, err := capture.NewStore(t.TempDir(), testKeys()).Read(in.Identity)
	require.ErrorIs(t, err, os.ErrNotExist)
	_, err = capture.NewStore(t.TempDir(), nil).Read(in.Identity)
	require.ErrorIs(t, err, os.ErrNotExist, "a missing capture is reported before any key check")

	for _, change := range []func(*capture.Identity){
		func(id *capture.Identity) { id.ParseAttempt++ },
		func(id *capture.Identity) { id.TenantID++ },
	} {
		other := in.Identity
		change(&other)
		_, err = capture.NewStore(root, testKeys()).Read(other)
		require.ErrorIs(t, err, os.ErrNotExist)
	}

	var seal map[string]any
	require.NoError(t, json.Unmarshal(sealed, &seal))
	seal["signature"] = "AAAA"
	tampered, err := json.Marshal(seal)
	require.NoError(t, err)
	_, err = capture.NewStore(seeded(t, in, tampered), testKeys()).Read(in.Identity)
	requireUnavailable(t, err)

	other := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x11}, ed25519.SeedSize))
	foreign := capture.NewKeys("other-key", map[string]ed25519.PrivateKey{"other-key": other})
	_, err = capture.NewStore(root, foreign).Read(in.Identity)
	requireUnavailable(t, err)
}

func TestSaveNeverOverwrites(t *testing.T) {
	in, _ := load(t)
	root := t.TempDir()
	store := capture.NewStore(root, testKeys())
	require.NoError(t, store.Save(in.Identity, result(in), in.Chunks, nil))
	require.NoError(t, store.Save(in.Identity, result(in), in.Chunks, nil), "the same record may be saved again")

	shifted := append([]types.ParsedChunk(nil), in.Chunks...)
	shifted[0].Start, shifted[0].Content = 1, string([]rune(in.Markdown)[1:])
	requireUnavailable(t, store.Save(in.Identity, result(in), shifted, nil))

	blocked := filepath.Join(t.TempDir(), "file")
	require.NoError(t, os.WriteFile(blocked, []byte("not a directory"), 0o600))
	require.Error(t, capture.NewStore(blocked, testKeys()).Save(in.Identity, result(in), in.Chunks, nil))
}

type knowledgeRepo struct {
	knowledge *types.Knowledge
	revision  *types.KnowledgeRevision
}

func (r knowledgeRepo) GetKnowledgeByID(_ context.Context, _ uint64, id string) (*types.Knowledge, error) {
	if r.knowledge == nil || r.knowledge.ID != id {
		return nil, repository.ErrKnowledgeNotFound
	}
	return r.knowledge, nil
}

func (r knowledgeRepo) GetRevision(_ context.Context, id string, attempt int64) (*types.KnowledgeRevision, error) {
	if r.revision == nil || r.revision.KnowledgeID != id || r.revision.ParseAttempt != attempt {
		return nil, repository.ErrKnowledgeNotFound
	}
	return r.revision, nil
}

func TestReadSourceArtifactChecksOwnershipBeforeTheCapture(t *testing.T) {
	in, sealed := load(t)
	id := in.Identity
	scope := types.WikiReleaseScope{TenantID: id.TenantID, SpaceID: "space-1", RawKBID: id.RawKBID, WikiKBID: "wiki-1"}
	repo := knowledgeRepo{
		knowledge: &types.Knowledge{
			ID: id.KnowledgeID, TenantID: id.TenantID, KnowledgeBaseID: id.RawKBID, FileName: "条款.pdf",
		},
		revision: &types.KnowledgeRevision{
			KnowledgeID: id.KnowledgeID, ParseAttempt: id.ParseAttempt, FileSHA256: id.SourceSHA256,
		},
	}
	ctx := context.Background()

	artifact, err := capture.ReadSourceArtifact(ctx, capture.NewStore(seeded(t, in, sealed), testKeys()), repo,
		scope, id.KnowledgeID, id.ParseAttempt)
	require.NoError(t, err)
	require.Equal(t, "条款.pdf", artifact.FileName)
	require.Equal(t, id.SourceSHA256, artifact.FileSHA256)
	require.Equal(t, in.Markdown, artifact.Markdown)
	require.Equal(t, in.Native.SanitizedJSON, artifact.NativeJSON)
	require.NotEmpty(t, artifact.ParserIdentitySHA256)

	_, err = capture.ReadSourceArtifact(ctx, capture.NewStore(t.TempDir(), testKeys()), repo,
		scope, id.KnowledgeID, id.ParseAttempt)
	require.ErrorIs(t, err, source.ErrNotCaptured)

	elsewhere := repo
	moved := *repo.knowledge
	moved.KnowledgeBaseID = "raw-other"
	elsewhere.knowledge = &moved
	_, err = capture.ReadSourceArtifact(ctx, capture.NewStore(seeded(t, in, sealed), testKeys()), elsewhere,
		scope, id.KnowledgeID, id.ParseAttempt)
	require.True(t, errors.Is(err, source.ErrNotFound), "%v", err)

	_, err = capture.ReadSourceArtifact(ctx, capture.NewStore(seeded(t, in, sealed), testKeys()), repo,
		scope, id.KnowledgeID, id.ParseAttempt+1)
	require.True(t, errors.Is(err, source.ErrNotFound), "%v", err)
}
