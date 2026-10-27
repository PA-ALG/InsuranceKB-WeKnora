package chatsource

import (
	"context"
	"strings"

	"github.com/Tencent/WeKnora/internal/logger"
)

const (
	// entityNamesKey holds a raw passage's product names, "" when the release cites it for none.
	entityNamesKey = "entity_names"
	unidentified   = "所属产品未识别"
)

// labelRaw records, for every raw material of the turn not yet labelled, the names of the
// entities whose published members cite it (QA1 §2.2). Most products name their terms file
// alike, so without this a passage of one product reads as another's. A failed lookup labels
// the Space's materials as unidentified rather than failing the turn: the label is an aid, and
// "unidentified" tells the model not to attribute the passage.
func (r *Resolver) labelRaw(ctx context.Context, tenant uint64, turn *Turn) {
	if r.published == nil || len(turn.RawKnowledge) == 0 {
		return
	}
	if turn.RawEntities == nil {
		turn.RawEntities = make(map[string][]string, len(turn.RawKnowledge))
	}
	bySpace := map[string]map[string][]string{}
	for id, space := range turn.RawKnowledge {
		if _, done := turn.RawEntities[id]; done {
			continue
		}
		cited, loaded := bySpace[space]
		if !loaded {
			var err error
			cited, err = r.published.SourceEntities(ctx, tenant, space, turn.Releases[space])
			if err != nil {
				logger.Warnf(ctx, "enterprise raw passages of Space %s stay unattributed: %v", space, err)
			}
			bySpace[space] = cited
		}
		turn.RawEntities[id] = append([]string{}, cited[id]...)
	}
}

// rawLabel is the entity_names value of a material; ok is false when the turn labels nothing.
func (t Turn) rawLabel(knowledgeID string) (names string, ok bool) {
	if t.RawEntities == nil {
		return "", false
	}
	return strings.Join(t.RawEntities[knowledgeID], "、"), true
}

// labelledTitle puts the product names, or that they are unidentified, before a passage title.
func labelledTitle(names, title string) string {
	if names == "" {
		names = unidentified
	}
	return names + " · " + title
}

// rawTier is the quick-answer label of a raw passage, naming its products once it is labelled.
func rawTier(metadata map[string]string) string {
	const tier = "原文检索（未经编译审核）"
	names, labelled := metadata[entityNamesKey]
	switch {
	case !labelled:
		return tier
	case names == "":
		return tier + "｜" + unidentified
	default:
		return tier + "｜所属产品：" + names
	}
}
