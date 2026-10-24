package service

import (
	"context"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	werrors "github.com/Tencent/WeKnora/internal/errors"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

// G3FirstParseStore keeps the first-parse captures of enterprise Space PDFs (internal/enterprise/capture).
// It never calls a parser. Each call opens the captures under root with keys, so a test may point
// root elsewhere.
type G3FirstParseStore struct {
	root string
	keys *capture.Keys
}

// NewG3FirstParseStore keeps captures in the deployment's capture directory, sealed with keys from
// the citation token signing ring.
func NewG3FirstParseStore(keys *capture.Keys) *G3FirstParseStore {
	return &G3FirstParseStore{root: capture.DefaultRoot(), keys: keys}
}

func (s *G3FirstParseStore) captures() *capture.Store { return capture.NewStore(s.root, s.keys) }

// ReadSourceArtifact reads an exact historical capture. The caller must resolve
// an authorized Space/RAW scope; this method independently checks Knowledge's
// tenant and RAW ownership before opening any signed artifact. It never parses.
func (s *G3FirstParseStore) ReadSourceArtifact(
	ctx context.Context, repo interfaces.KnowledgeRepository, scope types.WikiReleaseScope,
	knowledgeID string, attempt int64,
) (*source.Artifact, error) {
	var store *capture.Store
	if s != nil {
		store = s.captures()
	}
	reader, _ := repo.(capture.KnowledgeReader)
	return capture.ReadSourceArtifact(ctx, store, reader, scope, knowledgeID, attempt)
}

// save seals the first parse of one exact source revision.
func (s *G3FirstParseStore) save(id capture.Identity, result *types.ReadResult, chunks []types.ParsedChunk) error {
	if s == nil {
		return capture.ErrUnavailable
	}
	return s.captures().Save(id, result, chunks, nil)
}

func (s *knowledgeService) failG3FirstParse(ctx context.Context, knowledge *types.Knowledge, cause error) error {
	s.failStage(ctx, knowledge.ID, types.StageDocReader, werrors.ErrCodeDocReaderParseFailed,
		"G3 first parse artifact unavailable", cause)
	_, err := s.failKnowledge(ctx, knowledge, true, "G3_FIRST_PARSE_ARTIFACT_UNAVAILABLE: %v", cause)
	return err
}
