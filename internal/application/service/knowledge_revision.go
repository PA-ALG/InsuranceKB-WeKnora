package service

import (
	"context"
	"fmt"
	"runtime/debug"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type revisionRepository interface {
	AllocateParseAttempt(
		context.Context, string, string, string,
	) (int64, error)
	CommitDirectRevision(
		context.Context, string, types.RevisionCommitBinding,
	) (*types.KnowledgeRevision, error)
	FinalizeSubtaskRevision(
		context.Context, string, types.RevisionCommitBinding,
	) (int, bool, error)
}

type finalizingRevisionRepository interface {
	SetFinalizingRevision(
		context.Context,
		string,
		int,
		types.RevisionCommitBinding,
	) (bool, error)
}

// RevisionBuildVersion and RevisionBuildCommit reuse the existing release
// build inputs via -ldflags; debug.ReadBuildInfo remains the local fallback.
var (
	RevisionBuildVersion = types.RevisionUnknownIdentity
	RevisionBuildCommit  = types.RevisionUnknownIdentity
)

func requireRevisionRepository(repo interfaces.KnowledgeRepository) (revisionRepository, error) {
	revisionRepo, ok := repo.(revisionRepository)
	if !ok {
		return nil, fmt.Errorf("%w: revision repository unavailable", repository.ErrRevisionCommitFailed)
	}
	return revisionRepo, nil
}

func finalizeRevisionSlot(
	ctx context.Context,
	repo interfaces.KnowledgeRepository,
	knowledgeID string,
	revision *types.RevisionCommitBinding,
) (int, bool, error) {
	if revision == nil {
		return repo.FinalizeSubtask(ctx, knowledgeID)
	}
	revisionRepo, err := requireRevisionRepository(repo)
	if err != nil {
		return 0, false, err
	}
	return revisionRepo.FinalizeSubtaskRevision(ctx, knowledgeID, *revision)
}

func setFinalizing(
	ctx context.Context,
	repo interfaces.KnowledgeRepository,
	knowledgeID string,
	expectedSubtasks int,
	revision *types.RevisionCommitBinding,
) (bool, error) {
	if revision == nil {
		return repo.SetFinalizing(ctx, knowledgeID, expectedSubtasks)
	}
	if !revision.Valid() {
		return false, fmt.Errorf("%w: invalid revision binding", repository.ErrRevisionCommitFailed)
	}
	revisionRepo, ok := repo.(finalizingRevisionRepository)
	if !ok {
		return false, fmt.Errorf(
			"%w: revision-aware finalizing unavailable",
			repository.ErrRevisionCommitFailed,
		)
	}
	return revisionRepo.SetFinalizingRevision(
		ctx,
		knowledgeID,
		expectedSubtasks,
		*revision,
	)
}

func commitDirectRevision(
	ctx context.Context,
	repo interfaces.KnowledgeRepository,
	knowledgeID string,
	revision *types.RevisionCommitBinding,
) error {
	if revision == nil {
		return fmt.Errorf("%w: missing revision binding", repository.ErrRevisionCommitFailed)
	}
	revisionRepo, err := requireRevisionRepository(repo)
	if err != nil {
		return err
	}
	_, err = revisionRepo.CommitDirectRevision(ctx, knowledgeID, *revision)
	return err
}

func newRevisionBinding(
	parseAttempt int64,
	fileSHA256 string,
	kb *types.KnowledgeBase,
	effective types.EffectiveProcessConfig,
	fileType string,
) *types.RevisionCommitBinding {
	if parseAttempt <= 0 || fileSHA256 == "" || kb == nil {
		return nil
	}
	appVersion, appCommit := revisionBuildIdentity()
	parserEngine := effective.ChunkingConfig.ResolveParserEngine(fileType)
	if parserEngine == "" {
		parserEngine = "builtin"
	}
	return &types.RevisionCommitBinding{
		ParseAttempt: parseAttempt,
		FileSHA256:   fileSHA256,
		ParserIdentity: types.NewRevisionParserIdentity(
			appVersion,
			appCommit,
			types.RevisionUnknownIdentity,
			parserEngine,
			kb.EmbeddingModelID,
			effective.ChunkingConfig,
		),
	}
}

func refreshRevisionBinding(
	binding *types.RevisionCommitBinding,
	kb *types.KnowledgeBase,
	effective types.EffectiveProcessConfig,
	fileType string,
) *types.RevisionCommitBinding {
	if binding == nil {
		return nil
	}
	return newRevisionBinding(
		binding.ParseAttempt, binding.FileSHA256, kb, effective, fileType,
	)
}

func revisionBuildIdentity() (string, string) {
	version := strings.TrimSpace(RevisionBuildVersion)
	commit := strings.TrimSpace(RevisionBuildCommit)
	if version == "" {
		version = types.RevisionUnknownIdentity
	}
	if commit == "" {
		commit = types.RevisionUnknownIdentity
	}
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return version, commit
	}
	if candidate := strings.TrimSpace(info.Main.Version); version == types.RevisionUnknownIdentity &&
		candidate != "" && candidate != "(devel)" {
		version = candidate
	}
	for _, setting := range info.Settings {
		if commit == types.RevisionUnknownIdentity &&
			setting.Key == "vcs.revision" && strings.TrimSpace(setting.Value) != "" {
			commit = setting.Value
			break
		}
	}
	return version, commit
}

func stampRevisionAttempt(chunks []*types.Chunk, binding *types.RevisionCommitBinding) {
	if binding == nil {
		return
	}
	stampParseAttempt(chunks, binding.ParseAttempt)
}

func stampParseAttempt(chunks []*types.Chunk, attempt int64) {
	if attempt <= 0 {
		return
	}
	for _, chunk := range chunks {
		if chunk != nil {
			chunk.ParseAttempt = attempt
		}
	}
}

func revisionPayloadMatchesKnowledge(
	knowledge *types.Knowledge,
	binding *types.RevisionCommitBinding,
	parseAttempt int64,
) bool {
	if knowledge == nil {
		return false
	}
	if binding == nil {
		if parseAttempt > 0 {
			return parseAttempt == knowledge.CurrentParseAttempt
		}
		return knowledge.CurrentParseAttempt == 0
	}
	if parseAttempt > 0 && parseAttempt != binding.ParseAttempt {
		return false
	}
	return binding.Valid() &&
		binding.ParseAttempt == knowledge.CurrentParseAttempt &&
		binding.FileSHA256 == knowledge.FileSHA256
}
