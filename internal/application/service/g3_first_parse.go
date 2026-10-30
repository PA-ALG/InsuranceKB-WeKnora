package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	werrors "github.com/Tencent/WeKnora/internal/errors"
	"github.com/Tencent/WeKnora/internal/logger"
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

// captureOffice seals the Office structure of one parse of an enterprise RAW upload, next to the
// upstream parse of the same bytes (S11b). The parse itself is never changed: when the structure
// cannot be extracted or sealed, the knowledge is processed as usual and its source pages report the
// revision as not captured. Only the typed code is logged, never document text.
func (s *knowledgeService) captureOffice(
	ctx context.Context, k *types.Knowledge, p types.DocumentProcessPayload, fileType string, data []byte,
) {
	if k == nil || p.URL != "" || p.FileURL != "" || !ooxml.Supports(fileType) ||
		s.captureScope == nil || !s.captureScope.RawKB(k.TenantID, k.KnowledgeBaseID) {
		return
	}
	sum := sha256.Sum256(data)
	if p.Revision == nil || p.Revision.ParseAttempt != k.CurrentParseAttempt ||
		(p.ParseAttempt > 0 && p.Revision.ParseAttempt != p.ParseAttempt) ||
		p.Revision.FileSHA256 != hex.EncodeToString(sum[:]) {
		logger.Warnf(ctx, "[office capture] not saved knowledge=%s reason=REVISION_BINDING", k.ID)
		return
	}
	result, chunks, err := capture.Office(fileType, data)
	if err == nil {
		err = s.firstParse.save(capture.Identity{
			TenantID: k.TenantID, RawKBID: k.KnowledgeBaseID, KnowledgeID: k.ID,
			ParseAttempt: p.Revision.ParseAttempt, SourceSHA256: p.Revision.FileSHA256,
		}, result, chunks)
	}
	if err != nil {
		reason := "CAPTURE_UNAVAILABLE"
		var failure *ooxml.Error
		if errors.As(err, &failure) {
			reason = failure.Code
		}
		logger.Warnf(ctx, "[office capture] not saved knowledge=%s reason=%s", k.ID, reason)
	}
}
