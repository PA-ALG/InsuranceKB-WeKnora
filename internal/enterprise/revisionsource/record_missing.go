package revisionsource

import (
	"context"
	"crypto/sha256"
	"encoding/hex"

	"github.com/Tencent/WeKnora/internal/types"
)

// knowledgeRevisionSourceRecorder is the repository capability that records (or plans) the
// commit-time source row of an already committed attempt (S11g).
type knowledgeRevisionSourceRecorder interface {
	RecordMissingRevisionSource(
		context.Context, uint64, string, int64, bool,
	) (*types.KnowledgeRevisionSource, types.RevisionSourceRecordOutcome, error)
}

// RecordMissingSource records the released, unsealed source row that the current completed
// attempt should have received at commit, for attempts committed before their format recorded
// one (Office before S11g). Only a human tenant admin may call it, as for the sealed backfill.
// The stored object's bytes are hashed against the committed revision before the repository is
// asked; dryRun returns the planned row and writes nothing. It never seals, pins or replaces.
func (s *KnowledgeRevisionSourceService) RecordMissingSource(
	ctx context.Context,
	knowledgeID string,
	parseAttempt int64,
	dryRun bool,
) (*types.KnowledgeRevisionSource, types.RevisionSourceRecordOutcome, error) {
	tenantID, err := s.authorizeBackfill(ctx)
	if err != nil {
		return nil, "", err
	}
	if s.recorder == nil {
		return nil, "", ErrRevisionSourceBackfillDisabled
	}
	if knowledgeID == "" || parseAttempt <= 0 {
		return nil, "", ErrRevisionSourceMismatch
	}
	knowledge, current, _, err := s.repo.GetRevisionState(ctx, knowledgeID)
	if err != nil || knowledge == nil || current == nil || knowledge.DeletedAt.Valid ||
		knowledge.TenantID != tenantID || knowledge.ID != knowledgeID ||
		knowledge.ParseStatus != types.ParseStatusCompleted ||
		knowledge.CurrentParseAttempt != parseAttempt || current.ParseAttempt != parseAttempt ||
		current.KnowledgeID != knowledgeID || current.FileSHA256 == "" ||
		current.FileSHA256 != knowledge.FileSHA256 {
		return nil, "", ErrRevisionSourceMismatch
	}
	resource, err := s.resources.Resolve(ctx, knowledge.FilePath)
	if err != nil || resource == nil || resource.TenantID != tenantID ||
		resource.State != types.ResourceStateActive ||
		resource.Lifecycle != types.ResourceLifecyclePersistent || resource.Size <= 0 {
		return nil, "", ErrRevisionSourceMismatch
	}
	if _, supported := types.RevisionSourceMIME(resource.MimeType, resource.OriginalName); !supported {
		return nil, "", ErrRevisionSourceMismatch
	}
	data, err := s.readResourceObject(ctx, resource)
	if err != nil || int64(len(data)) != resource.Size {
		return nil, "", ErrRevisionSourceMismatch
	}
	digest := sha256.Sum256(data)
	objectSHA256 := hex.EncodeToString(digest[:])
	if objectSHA256 != current.FileSHA256 ||
		(resource.ContentHash != "" && resource.ContentHash != objectSHA256) {
		return nil, "", ErrRevisionSourceMismatch
	}
	source, outcome, err := s.recorder.RecordMissingRevisionSource(
		ctx, tenantID, knowledgeID, parseAttempt, dryRun,
	)
	if err != nil || source == nil {
		return nil, "", ErrRevisionSourceMismatch
	}
	return source, outcome, nil
}
