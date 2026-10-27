// Package chatsource fixes enterprise retrieval scopes once per chat turn.
package chatsource

import (
	"context"
	"errors"
	"reflect"
	"sort"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// Role identifies a knowledge base's configured purpose in a Space.
type Role string

const (
	// RoleRaw identifies the Space's original materials.
	RoleRaw Role = "raw"
	// RoleWiki identifies the Space's compiled knowledge base.
	RoleWiki Role = "wiki"
	// ErrorSourcesUnavailable reports an empty fixed-material selection.
	ErrorSourcesUnavailable = "RELEASE_SOURCES_UNAVAILABLE"
)

// Spaces identifies configured enterprise knowledge bases without granting access.
type Spaces interface {
	SpaceOf(uint64, string) (string, Role, bool)
}

// A complete directory classifies any configured KB, including references from
// an earlier turn executed under a different tenant. It grants no read access.
type spaceOwnerDirectory interface {
	SpaceOwner(string) (uint64, string, Role, bool)
}

// Heads reads the authoritative active release of a Space.
type Heads interface {
	ActiveRelease(context.Context, uint64, string) (string, error)
}

// Pin binds one source material to its released parse attempt.
type Pin struct {
	KnowledgeID  string
	ParseAttempt int64
}

// Pins lists live sources of an exact release without selecting a newer release.
type Pins interface {
	ReleaseSources(context.Context, uint64, string, string) ([]Pin, error)
}

// Attempts reads the current parse attempts of tenant-owned source materials.
type Attempts interface {
	CurrentAttempts(context.Context, uint64, []string) (map[string]int64, error)
}

// Resolver holds stateless dependencies for resolving and checking chat sources.
type Resolver struct {
	spaces    Spaces
	heads     Heads
	pins      Pins
	attempts  Attempts
	published *knowledge.Service // optional: quick answers read published fields (Q1b-2)
}

// NewResolver constructs a resolver whose resolved state remains local to each turn.
func NewResolver(spaces Spaces, heads Heads, pins Pins, attempts Attempts) *Resolver {
	return &Resolver{spaces: spaces, heads: heads, pins: pins, attempts: attempts}
}

// Turn carries a request's fixed retrieval scope and source provenance. RawEntities maps every
// raw material to the entities its release cites it for (an empty list when none); it is nil
// when the resolver has no published knowledge, and then raw passages carry no product label.
type Turn struct {
	Targets      types.SearchTargets
	Releases     map[string]string
	WikiSpaces   []string
	RawKnowledge map[string]string
	RawAttempts  map[string]int64
	RawEntities  map[string][]string

	titles *rawTitles // set with RawEntities: original titles of the labelled raw passages
}

// SpaceOf exposes configuration identification to admission checks; it grants no ACL.
func (r *Resolver) SpaceOf(tenantID uint64, kbID string) (string, Role, bool) {
	if r == nil || missing(r.spaces) {
		return "", "", false
	}
	return r.spaces.SpaceOf(tenantID, kbID)
}

// Resolve narrows every explicitly selected enterprise target or fails the whole turn.
func (r *Resolver) Resolve(ctx context.Context, tenantID uint64, targets types.SearchTargets) (Turn, error) {
	if r == nil || missing(r.spaces) {
		return Turn{}, errors.New("chat source configuration is unavailable")
	}
	turn := Turn{Releases: map[string]string{}, RawKnowledge: map[string]string{}, RawAttempts: map[string]int64{}}
	searchable := map[string]map[string]int64{}
	wikis := map[string]bool{}
	for _, target := range targets {
		if target == nil {
			turn.Targets = append(turn.Targets, target)
			continue
		}
		space, role, ok := r.SpaceOf(target.TenantID, target.KnowledgeBaseID)
		if directory, complete := r.spaces.(spaceOwnerDirectory); complete {
			owner, configuredSpace, configuredRole, enterprise := directory.SpaceOwner(target.KnowledgeBaseID)
			if enterprise {
				if owner != tenantID || target.TenantID != owner {
					return Turn{}, &release.Error{Code: release.ErrorReleaseAccessDenied}
				}
				space, role, ok = configuredSpace, configuredRole, true
			}
		}
		if !ok {
			space, role, ok = r.SpaceOf(tenantID, target.KnowledgeBaseID)
		}
		if !ok {
			turn.Targets = append(turn.Targets, target)
			continue
		}
		if target.TenantID != tenantID {
			return Turn{}, &release.Error{
				Code: release.ErrorReleaseAccessDenied, Detail: "enterprise chat sources require the executing tenant",
			}
		}
		if missing(r.heads) || missing(r.pins) || missing(r.attempts) {
			return Turn{}, errors.New("enterprise chat source dependencies are unavailable")
		}
		if _, fixed := turn.Releases[space]; !fixed {
			id, err := r.heads.ActiveRelease(ctx, tenantID, space)
			if err != nil {
				return Turn{}, err
			}
			if id == "" {
				return Turn{}, &release.Error{
					Code: release.ErrorReleaseNotFound, Detail: "the Space has no active release",
				}
			}
			turn.Releases[space] = id
		}
		switch role {
		case RoleWiki:
			if !wikis[space] {
				turn.WikiSpaces = append(turn.WikiSpaces, space)
				wikis[space] = true
			}
		case RoleRaw:
			available, loaded := searchable[space]
			if !loaded {
				var err error
				available, err = r.availablePins(ctx, tenantID, space, turn.Releases[space])
				if err != nil {
					return Turn{}, err
				}
				searchable[space] = available
			}
			selected := available
			if target.Type == types.SearchTargetTypeKnowledge {
				selected = map[string]int64{}
				for _, id := range target.KnowledgeIDs {
					if attempt, ok := available[id]; ok {
						selected[id] = attempt
					}
				}
			} else if target.Type != types.SearchTargetTypeKnowledgeBase {
				return Turn{}, sourcesUnavailable()
			}
			if len(selected) == 0 {
				return Turn{}, sourcesUnavailable()
			}
			narrowed := *target
			narrowed.Type, narrowed.KnowledgeIDs = types.SearchTargetTypeKnowledge, sortedIDs(selected)
			turn.Targets = append(turn.Targets, &narrowed)
			for id, attempt := range selected {
				turn.RawKnowledge[id], turn.RawAttempts[id] = space, attempt
			}
		default:
			return Turn{}, errors.New("enterprise chat source role is invalid")
		}
	}
	r.labelRaw(ctx, tenantID, &turn)
	return turn, nil
}

// Label copies metadata before adding provenance so shared metadata maps are safe. Product
// labels come only from the turn's mapping: an entity_names value a result arrives with is
// replaced, or dropped when the turn labels nothing. The same result can sit in several lists
// and the pipeline runs twice on copies, so the title is always rebuilt from the original title
// the turn recorded, never prefixed twice.
func (t Turn) Label(results []*types.SearchResult) {
	for _, result := range results {
		if result == nil {
			continue
		}
		space, ok := t.RawKnowledge[result.KnowledgeID]
		if !ok {
			continue
		}
		metadata := make(map[string]string, len(result.Metadata)+3)
		for key, value := range result.Metadata {
			metadata[key] = value
		}
		metadata["source_tier"], metadata["release_id"] = "raw_text", t.Releases[space]
		delete(metadata, entityNamesKey)
		if names, ok := t.rawLabel(result.KnowledgeID); ok {
			metadata[entityNamesKey] = names
			result.KnowledgeTitle = labelledTitle(names, t.titles.original(result))
		}
		result.Metadata = metadata
	}
}

func uniqueAttempts(pins []Pin) map[string]int64 {
	out, conflicts := map[string]int64{}, map[string]bool{}
	for _, pin := range pins {
		if pin.KnowledgeID == "" || pin.ParseAttempt <= 0 {
			continue
		}
		if previous, ok := out[pin.KnowledgeID]; ok && previous != pin.ParseAttempt {
			conflicts[pin.KnowledgeID] = true
		}
		out[pin.KnowledgeID] = pin.ParseAttempt
	}
	for id := range conflicts {
		delete(out, id)
	}
	return out
}

func sortedIDs(attempts map[string]int64) []string {
	ids := make([]string, 0, len(attempts))
	for id := range attempts {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func sourcesUnavailable() error {
	return &release.Error{
		Code: ErrorSourcesUnavailable, Detail: "no selected material is available at the fixed release parse attempt",
	}
}

func missing(value any) bool {
	if value == nil {
		return true
	}
	v := reflect.ValueOf(value)
	switch v.Kind() {
	case reflect.Chan, reflect.Func, reflect.Interface, reflect.Map, reflect.Pointer, reflect.Slice:
		return v.IsNil()
	}
	return false
}
