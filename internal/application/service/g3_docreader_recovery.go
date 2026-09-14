package service

import (
	"context"
	"fmt"

	werrors "github.com/Tencent/WeKnora/internal/errors"
	"github.com/Tencent/WeKnora/internal/types"
)

func validG3DocReaderOrigin(ref *types.DocumentDocReaderReuseReference, id g3FirstParseIdentity) bool {
	return ref == nil || (ref.OriginParseAttempt > 0 && ref.OriginParseAttempt < id.ParseAttempt &&
		ref.OriginProcessingAttempt > 0 && ref.SourceSHA256 == id.SourceSHA256 && validServiceSHA256(ref.ArtifactSHA256))
}

// The reference is part of the new authenticated artifact. Reopen the old
// authenticated object too; a hash-shaped string is not sufficient provenance.
func (s *conceptSourceReuseStore830G3) validateDocReaderOrigin(record *g3FirstParseRecord) error {
	if record.OriginDocReader == nil {
		return nil
	}
	id := record.Identity
	id.ParseAttempt = record.OriginDocReader.OriginParseAttempt
	old, err := s.readFirstParse(id)
	if err != nil || g3FirstParseRecordSHA(old) != record.OriginDocReader.ArtifactSHA256 ||
		old.ParserIdentitySHA256 != record.ParserIdentitySHA256 || old.Markdown != record.Markdown ||
		old.Native.SanitizedSHA256 != record.Native.SanitizedSHA256 {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	return nil
}

// A closed old generation proves why this is a parser reuse, not an arbitrary
// cache read. Read the specified attempt: LatestAttempt changes on reparse.
func (s *knowledgeService) g3DocReaderRecoveryOrigin(ctx context.Context, k *types.Knowledge, parse int64, processing int) error {
	j, scope, enabled := s.g3ModelDispatchJournal(k)
	if !enabled || j == nil || parse <= 0 || processing <= 0 {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	rows, err := j.repo.ListByAttempt(ctx, k.ID, processing)
	if err != nil {
		return err
	}
	rootID := ""
	stages := map[string]bool{}
	markers := 0
	for _, row := range rows {
		if row.Kind == types.SpanKindRoot && row.ParentSpanID == "" {
			if rootID != "" || row.Status != types.SpanStatusFailed || row.FinishedAt == nil {
				return ErrConceptSourceAuthorityUnavailable830G2
			}
			rootID = row.SpanID
		}
	}
	for _, row := range rows {
		if row.Kind == types.SpanKindStage && row.ParentSpanID == rootID && row.FinishedAt != nil {
			switch row.Name {
			case types.StageDocReader, types.StageChunking:
				stages[row.Name] = row.Status == types.SpanStatusDone
			case types.StageEmbedding:
				stages[row.Name] = row.Status == types.SpanStatusFailed &&
					(row.ErrorCode == werrors.ErrCodeEmbeddingRateLimit || row.ErrorCode == werrors.ErrCodeVectorStoreWriteFailed)
			}
		}
		if row.Name == knowledgeModelDispatchMarkerName {
			var marker knowledgeModelDispatchMarker
			if row.ParentSpanID != rootID || row.Kind != types.SpanKindSubSpan || row.Status != types.SpanStatusDone ||
				decodeModelDispatchMap(row.Input, &marker) != nil || marker.Contract != knowledgeModelDispatchMarkerContract ||
				marker.Scope != scope || marker.KnowledgeID != k.ID || marker.ParseAttempt != parse || marker.ProcessingAttempt != processing {
				return ErrConceptSourceAuthorityUnavailable830G2
			}
			digest, err := modelDispatchDigest(marker.Contract, marker)
			if err != nil || digest != row.SpanID {
				return ErrConceptSourceAuthorityUnavailable830G2
			}
			markers++
		}
	}
	if rootID == "" || markers != 1 || !stages[types.StageDocReader] || !stages[types.StageChunking] || !stages[types.StageEmbedding] {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	return nil
}

func (s *knowledgeService) g3RecoveryPDFSHA(ctx context.Context, k *types.Knowledge, kb *types.KnowledgeBase) (string, error) {
	reader, err := s.resolveFileServiceForPath(ctx, kb, k.FilePath).GetFile(ctx, k.FilePath)
	if err != nil {
		return "", err
	}
	digest, readErr := calculateReaderSHA256(reader)
	closeErr := reader.Close()
	if readErr != nil {
		return "", readErr
	}
	return digest, closeErr
}

func (s *knowledgeService) selectG3DocReaderRecovery(ctx context.Context, k *types.Knowledge, overrides *types.KnowledgeProcessOverrides) (*types.DocumentDocReaderReuseReference, error) {
	if overrides != nil || !g3FirstParseScope(s.config, k, k.FileType) || k.ParseStatus != types.ParseStatusFailed || k.FilePath == "" {
		return nil, nil
	}
	if err := requireKnowledgeRevisionSourceReparseAllowed(ctx, s.repo, k.TenantID, k.ID); err != nil {
		return nil, err
	}
	processing := s.tracker().LatestAttempt(ctx, k.ID)
	if err := s.g3DocReaderRecoveryOrigin(ctx, k, k.CurrentParseAttempt, processing); err != nil {
		// An unrelated failure keeps the established full reparse behavior.
		return nil, nil
	}
	if s.firstParse == nil || s.firstParse.reuse == nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	kb, err := s.kbService.GetKnowledgeBaseByID(ctx, k.KnowledgeBaseID)
	if err != nil {
		return nil, err
	}
	digest, err := s.g3RecoveryPDFSHA(ctx, k, kb)
	if err != nil {
		return nil, err
	}
	if digest != k.FileSHA256 {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	id := g3FirstParseIdentity{TenantID: k.TenantID, RawKBID: k.KnowledgeBaseID, KnowledgeID: k.ID, ParseAttempt: k.CurrentParseAttempt, SourceSHA256: digest}
	old, err := s.firstParse.reuse.readFirstParse(id)
	if err != nil {
		return nil, err
	}
	return &types.DocumentDocReaderReuseReference{OriginParseAttempt: id.ParseAttempt, OriginProcessingAttempt: processing, SourceSHA256: digest, ArtifactSHA256: g3FirstParseRecordSHA(old)}, nil
}

func (s *knowledgeService) loadG3DocReaderRecovery(ctx context.Context, p types.DocumentProcessPayload, kb *types.KnowledgeBase, k *types.Knowledge) (*types.ReadResult, error) {
	ref := p.DocReaderReuse
	if ref == nil || s.firstParse == nil || s.firstParse.reuse == nil || !g3FirstParseScope(s.config, k, p.FileType) ||
		p.URL != "" || p.FileURL != "" || p.FilePath == "" || p.FilePath != k.FilePath ||
		p.TenantID != k.TenantID || p.KnowledgeBaseID != k.KnowledgeBaseID || p.KnowledgeID != k.ID || kb.ID != k.KnowledgeBaseID ||
		p.Revision == nil || p.ParseAttempt != p.Revision.ParseAttempt || p.ParseAttempt != k.CurrentParseAttempt ||
		p.Attempt <= ref.OriginProcessingAttempt || k.ParseStatus == types.ParseStatusDeleting || k.ParseStatus == types.ParseStatusCancelled {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	id := g3FirstParseIdentity{TenantID: p.TenantID, RawKBID: p.KnowledgeBaseID, KnowledgeID: p.KnowledgeID, ParseAttempt: p.ParseAttempt, SourceSHA256: p.Revision.FileSHA256}
	if !validG3DocReaderOrigin(ref, id) || ref.SourceSHA256 != k.FileSHA256 {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	if err := requireKnowledgeRevisionSourceReparseAllowed(ctx, s.repo, k.TenantID, k.ID); err != nil {
		return nil, err
	}
	if err := s.g3DocReaderRecoveryOrigin(ctx, k, ref.OriginParseAttempt, ref.OriginProcessingAttempt); err != nil {
		return nil, err
	}
	digest, err := s.g3RecoveryPDFSHA(ctx, k, kb)
	if err != nil || digest != ref.SourceSHA256 {
		return nil, fmt.Errorf("G3 DocReader reuse PDF binding invalid: %w", ErrConceptSourceAuthorityUnavailable830G2)
	}
	id.ParseAttempt = ref.OriginParseAttempt
	old, err := s.firstParse.reuse.readFirstParse(id)
	if err != nil || g3FirstParseRecordSHA(old) != ref.ArtifactSHA256 {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	p.Revision.ParserIdentity.DocReader = old.ParserIdentitySHA256
	return g3FirstParseResult(old), nil
}
