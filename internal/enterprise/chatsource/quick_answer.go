package chatsource

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
)

type answerDirectory interface {
	KnowledgeBases(uint64, string) (raw string, wiki string, ok bool)
}

// addAnswerRaw only expands quick answers, after explicit targets have fixed the
// turn's releases. The native selection authorizer grants access, not the directory.
func (r *Resolver) addAnswerRaw(
	ctx context.Context, tenant uint64, original types.SearchTargets, turn *Turn,
	authorize func(context.Context, string) bool,
) error {
	directory, ok := r.spaces.(answerDirectory)
	if !ok || authorize == nil {
		return nil
	}
	selected := map[string]bool{}
	for _, target := range original {
		if target != nil {
			selected[target.KnowledgeBaseID] = true
		}
	}
	for _, space := range turn.WikiSpaces {
		raw, wiki, ok := directory.KnowledgeBases(tenant, space)
		if !ok || raw == "" || !selected[wiki] || selected[raw] {
			continue
		}
		rawSpace, role, ok := r.SpaceOf(tenant, raw)
		if !ok || rawSpace != space || role != RoleRaw {
			continue
		}
		wikiSpace, role, ok := r.SpaceOf(tenant, wiki)
		if !ok || wikiSpace != space || role != RoleWiki || !authorize(ctx, raw) {
			continue
		}
		available, err := r.availablePins(ctx, tenant, space, turn.Releases[space])
		if err != nil {
			return err
		}
		if len(available) == 0 {
			continue
		}
		turn.Targets = append(turn.Targets, &types.SearchTarget{
			Type: types.SearchTargetTypeKnowledge, KnowledgeBaseID: raw,
			TenantID: tenant, KnowledgeIDs: sortedIDs(available),
		})
		for id, attempt := range available {
			turn.RawKnowledge[id], turn.RawAttempts[id] = space, attempt
		}
	}
	// The materials added here need product labels as well (QA1 §2.2).
	r.labelRaw(ctx, tenant, turn)
	return nil
}

func (r *Resolver) availablePins(ctx context.Context, tenant uint64, space, release string) (map[string]int64, error) {
	pins, err := r.pins.ReleaseSources(ctx, tenant, space, release)
	if err != nil {
		return nil, err
	}
	available := uniqueAttempts(pins)
	if len(available) == 0 {
		return available, nil
	}
	current, err := r.attempts.CurrentAttempts(ctx, tenant, sortedIDs(available))
	if err != nil {
		return nil, err
	}
	for id, attempt := range available {
		if now, ok := current[id]; !ok || now != attempt {
			delete(available, id)
		}
	}
	return available, nil
}
