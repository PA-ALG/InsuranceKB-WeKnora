package chatsource

import (
	"context"
	"strings"
	"sync"

	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/Tencent/WeKnora/internal/types"
)

const (
	// entityNamesKey holds a raw passage's product names, "" when the release cites it for none.
	// It is always written from the turn's mapping: a value a result arrives with is untrusted.
	entityNamesKey = "entity_names"
	unidentified   = "所属产品未识别"
)

// rawTitles remembers the title each raw passage had when the turn first labelled it, so every
// later pass derives the same labelled title (QA1 §2.3). The pipeline copies results between
// passes and a result's own metadata is untrusted, so the record is the turn's, keyed by the
// material and passage IDs. Copies of a Turn share it.
type rawTitles struct {
	mu     sync.Mutex
	titles map[string]string
}

// original returns the title first seen for the passage, recording it on first sight. Without
// a record (a Turn built by hand) or a passage ID the current title is used.
func (r *rawTitles) original(result *types.SearchResult) string {
	if r == nil || result.ID == "" {
		return result.KnowledgeTitle
	}
	key := result.KnowledgeID + "\x00" + result.ID
	r.mu.Lock()
	defer r.mu.Unlock()
	if title, ok := r.titles[key]; ok {
		return title
	}
	r.titles[key] = result.KnowledgeTitle
	return result.KnowledgeTitle
}

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
		turn.titles = &rawTitles{titles: map[string]string{}}
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

// rawTier is the quick-answer label of a raw passage. The product names come from the turn's
// own mapping for the passage's material, never from the result's metadata.
func rawTier(ctx context.Context, result *types.SearchResult) string {
	const tier = "原文检索（未经编译审核）"
	turn, ok := TurnFromContext(ctx)
	if !ok {
		return tier
	}
	if _, raw := turn.RawKnowledge[result.KnowledgeID]; !raw {
		return tier
	}
	names, labelled := turn.rawLabel(result.KnowledgeID)
	switch {
	case !labelled:
		return tier
	case names == "":
		return tier + "｜" + unidentified
	default:
		return tier + "｜所属产品：" + names
	}
}
