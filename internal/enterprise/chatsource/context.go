package chatsource

import (
	"context"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type turnKey struct{}
type turnContext struct {
	turn   Turn
	tenant uint64
}

func ChunkReaderOf(service interfaces.ChunkService) ChunkReader {
	if service == nil {
		return nil
	}
	return service.GetRepository()
}

// LegacyScope prevents the older KB/ID fields from restoring a removed Wiki
// source. SearchTargets remain authoritative for thresholds and tag filters.
func LegacyScope(ctx context.Context, targets types.SearchTargets, kbIDs, ids []string) ([]string, []string) {
	turn, ok := TurnFromContext(ctx)
	if !ok || len(turn.Releases) == 0 {
		return kbIDs, ids
	}
	var knowledgeIDs []string
	for _, target := range targets {
		if target != nil {
			knowledgeIDs = append(knowledgeIDs, target.KnowledgeIDs...)
		}
	}
	return targets.GetAllKnowledgeBaseIDs(), knowledgeIDs
}

// WithTurn carries only a request's immutable scope; no service retains it.
func WithTurn(ctx context.Context, turn Turn, tenant ...uint64) context.Context {
	id, _ := types.TenantIDFromContext(ctx)
	if len(tenant) > 0 {
		id = tenant[0]
	}
	return context.WithValue(ctx, turnKey{}, turnContext{turn: turn, tenant: id})
}

func TurnFromContext(ctx context.Context) (Turn, bool) {
	v, ok := ctx.Value(turnKey{}).(turnContext)
	return v.turn, ok
}

func ResolveQuick(ctx context.Context, resolver *Resolver, tenant uint64, targets types.SearchTargets) (context.Context, types.SearchTargets, error) {
	if resolver == nil {
		return ctx, targets, nil
	}
	turn, err := resolver.Resolve(ctx, tenant, targets)
	if err != nil {
		return ctx, nil, err
	}
	if len(turn.Targets) == 0 && len(turn.WikiSpaces) > 0 {
		return ctx, nil, &release.Error{Code: "RELEASE_MANAGED_KB", Detail: "已发布知识问答即将提供，请先选择原始材料库"}
	}
	return WithTurn(ctx, turn, tenant), turn.Targets, nil
}

// FilterPipeline runs before prompt assembly and again before streaming references.
func FilterPipeline(ctx context.Context, resolver *Resolver, chunks ChunkReader, cm *types.ChatManage) error {
	v, ok := ctx.Value(turnKey{}).(turnContext)
	if !ok {
		return nil
	}
	var err error
	before := cm.MergeResult
	for _, rows := range []*[]*types.SearchResult{&cm.SearchResult, &cm.RerankResult, &cm.MergeResult} {
		*rows, err = resolver.Filter(ctx, v.tenant, v.turn, chunks, *rows)
		if err != nil {
			return err
		}
		v.turn.Label(*rows)
	}
	if !samePromptResults(before, cm.MergeResult) && cm.RenderedContexts != "" {
		// A later delivery check may invalidate text already rendered by the
		// native prompt stage. Remove that envelope; model-context rendering
		// reconstructs any retained results from the filtered MergeResult.
		cm.UserContent = strings.ReplaceAll(cm.UserContent, cm.RenderedContexts, "")
		cm.RenderedContexts = ""
	}
	return nil
}

func samePromptResults(before, after []*types.SearchResult) bool {
	if len(before) != len(after) {
		return false
	}
	for i, old := range before {
		now := after[i]
		if old == nil || now == nil {
			if old != now {
				return false
			}
			continue
		}
		if old.ID != now.ID || old.Content != now.Content || old.ImageInfo != now.ImageInfo {
			return false
		}
	}
	return true
}

// PromptConfig excludes live document metadata from enterprise retrieval. Raw
// text may enter the model only through the delivery-checked search results.
func PromptConfig(resolver *Resolver, config *types.AgentConfig, turn Turn) *types.AgentConfig {
	if len(turn.Releases) == 0 {
		return config
	}
	copy := *config
	copy.KnowledgeIDs = nil
	for _, id := range config.KnowledgeIDs {
		if _, raw := turn.RawKnowledge[id]; !raw {
			copy.KnowledgeIDs = append(copy.KnowledgeIDs, id)
		}
	}
	if copy.QuestionOrigin != nil {
		for _, target := range config.SearchTargets {
			if target != nil && target.KnowledgeBaseID == copy.QuestionOrigin.KnowledgeBaseID {
				if _, _, enterprise := resolver.SpaceOf(target.TenantID, target.KnowledgeBaseID); enterprise {
					copy.QuestionOrigin = nil
					break
				}
			}
		}
	}
	return &copy
}

func WikiUnavailableNotice(turn Turn) string {
	if len(turn.WikiSpaces) == 0 {
		return ""
	}
	return "已发布知识尚不可用：当前选择的企业 Wiki 库在 Q1b 提供查询前没有检索工具。不要声称已检索或审核这些知识；如已选择原始材料库，仅可检索本轮固定材料，来源为原文检索（未经编译审核）。"
}

// AgentTurn resolves once even when engine creation and tool registration both
// need the scope. The saved agent config and subsequent turns remain untouched.
func AgentTurn(ctx context.Context, resolver *Resolver, config *types.AgentConfig) (context.Context, *types.AgentConfig, Turn, error) {
	if turn, ok := TurnFromContext(ctx); ok {
		return ctx, config, turn, nil
	}
	if resolver == nil {
		return ctx, config, Turn{Targets: config.SearchTargets}, nil
	}
	tenant, _ := types.TenantIDFromContext(ctx)
	turn, err := resolver.Resolve(ctx, tenant, config.SearchTargets)
	if err != nil {
		return ctx, config, Turn{}, err
	}
	if len(turn.Releases) == 0 {
		return ctx, config, turn, nil
	}
	copy := *config
	copy.SearchTargets = turn.Targets
	copy.KnowledgeBases = turn.Targets.GetAllKnowledgeBaseIDs()
	copy.KnowledgeIDs = nil
	for _, target := range turn.Targets {
		if target != nil {
			copy.KnowledgeIDs = append(copy.KnowledgeIDs, target.KnowledgeIDs...)
		}
	}
	return WithTurn(ctx, turn, tenant), &copy, turn, nil
}

// OtherToolTargets removes enterprise sources from document, graph and data
// capabilities while leaving ordinary targets in their original order.
func OtherToolTargets(resolver *Resolver, targets types.SearchTargets) types.SearchTargets {
	if resolver == nil {
		return targets
	}
	var out types.SearchTargets
	for _, target := range targets {
		if target == nil {
			continue
		}
		if _, _, enterprise := resolver.SpaceOf(target.TenantID, target.KnowledgeBaseID); !enterprise {
			out = append(out, target)
		}
	}
	return out
}
