package knowledge

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

type entityPayload struct {
	ID        string     `json:"entity_id"`
	Type      string     `json:"entity_type"`
	Names     []string   `json:"names"`
	Labels    []string   `json:"classification_labels"`
	Lifecycle *Lifecycle `json:"lifecycle"`
	Family    *Family    `json:"product_family"`
}

type claimPayload struct {
	Subject   string `json:"subject_ref"`
	Predicate string `json:"predicate"`
	State     string `json:"state"`
	Value     any    `json:"value"`
	Origin    string `json:"origin"`
	Review    struct {
		Mode string `json:"mode"`
	} `json:"review"`
	Evidence []struct {
		Quote     string `json:"quote"`
		SourceRef string `json:"source_ref"`
		Locator   struct {
			Page int `json:"page"`
		} `json:"locator"`
	} `json:"evidence"`
}

type profilePayload struct {
	Labels   []string `json:"classification_labels"`
	Sections []struct {
		Fields []struct {
			Key   string `json:"field_key"`
			Title string `json:"short_title"`
		} `json:"fields"`
	} `json:"sections"`
}

type navigationPayload struct {
	OverviewFields  []string              `json:"overview_fields"`
	QuestionTerms   map[string][][]string `json:"question_terms,omitempty"`
	QuestionIntents map[string][][]string `json:"question_intents,omitempty"`
	Domains         []struct {
		Types  []string `json:"entity_types"`
		Groups []struct {
			Key    string   `json:"group_key"`
			Labels []string `json:"classification_labels"`
		} `json:"groups"`
	} `json:"domains"`
}

type conceptPayload struct {
	Key         string            `json:"concept_key"`
	Title       string            `json:"title"`
	Definition  string            `json:"definition"`
	Explanation string            `json:"explanation"`
	Statements  []Statement       `json:"statements"`
	BasedOn     map[string]string `json:"based_on"`
}

type indexedEntity struct {
	Entity
	kind string
	// placeholder marks an entry made for a claim subject without a visible Entity member.
	placeholder bool
}

type indexedClaim struct {
	member  release.Member
	payload claimPayload
}

type releaseIndex struct {
	id          string
	entities    []indexedEntity
	entityByID  map[string]int
	claims      map[string][]indexedClaim
	claimBySlug map[string]indexedClaim
	profiles    []profilePayload
	navigation  *navigationPayload
	concepts    []conceptPayload
	pages       []indexedPage
}

func indexRelease(ctx context.Context, r release.Release) (*releaseIndex, error) {
	index := &releaseIndex{
		id: r.ID, entityByID: map[string]int{}, claims: map[string][]indexedClaim{},
		claimBySlug: map[string]indexedClaim{},
	}
	var relations []relationPayload
	for _, member := range r.Members {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		switch member.Kind {
		case "entity":
			var payload entityPayload
			if err := decodeMember(member, &payload); err != nil {
				return nil, err
			}
			if strings.TrimSpace(payload.ID) == "" {
				return nil, malformed(member, "entity ID is required")
			}
			if _, exists := index.entityByID[payload.ID]; exists {
				continue
			}
			name := payload.ID
			if len(payload.Names) > 0 && payload.Names[0] != "" {
				name = payload.Names[0]
			}
			if payload.Family != nil && strings.TrimSpace(payload.Family.Key) == "" {
				payload.Family = nil
			}
			index.entityByID[payload.ID] = len(index.entities)
			index.entities = append(index.entities, indexedEntity{Entity: Entity{
				EntityID: payload.ID, Name: name, Names: payload.Names, Labels: payload.Labels,
				Lifecycle: payload.Lifecycle, Family: payload.Family,
			}, kind: payload.Type})
		case "relation":
			// A relation only adds version links: one that does not decode loses its link, not the read.
			var payload relationPayload
			if decodeMember(member, &payload) == nil {
				relations = append(relations, payload)
			}
		case "claim":
			var payload claimPayload
			if err := decodeMember(member, &payload); err != nil {
				return nil, err
			}
			if member.LogicalSlug == "" || strings.TrimSpace(payload.Subject) == "" ||
				strings.TrimSpace(payload.Predicate) == "" {
				return nil, malformed(member, "claim identity is required")
			}
			if payload.State != "present" && payload.State != "unknown" && payload.State != "absent_explicitly" {
				return nil, malformed(member, "invalid claim state")
			}
			if _, exists := index.claimBySlug[member.LogicalSlug]; exists {
				return nil, malformed(member, "duplicate claim slug")
			}
			claim := indexedClaim{member: member, payload: payload}
			index.claims[payload.Subject] = append(index.claims[payload.Subject], claim)
			index.claimBySlug[member.LogicalSlug] = claim
		case "presentation_profile":
			var payload profilePayload
			if err := decodeMember(member, &payload); err != nil {
				return nil, err
			}
			index.profiles = append(index.profiles, payload)
		case "navigation":
			var payload navigationPayload
			if err := decodeMember(member, &payload); err != nil {
				return nil, err
			}
			if index.navigation == nil {
				index.navigation = &payload
			}
		case "concept":
			var payload conceptPayload
			if err := decodeMember(member, &payload); err != nil {
				return nil, err
			}
			if strings.TrimSpace(payload.Key) == "" || strings.TrimSpace(payload.Title) == "" {
				return nil, malformed(member, "concept key and title are required")
			}
			for _, statement := range payload.Statements {
				if strings.TrimSpace(statement.Text) == "" || len(statement.Refs) == 0 {
					return nil, malformed(member, "statement text and refs are required")
				}
			}
			index.concepts = append(index.concepts, payload)
		case "wiki_page":
			var payload wikiPagePayload
			if err := decodeMember(member, &payload); err != nil {
				var typed *release.Error
				if errors.As(err, &typed) {
					return nil, err
				}
				return nil, malformed(member, "payload is not a valid page object")
			}
			if page, ok := indexedWikiPage(member.LogicalSlug, payload); ok {
				index.pages = append(index.pages, page)
			}
		}
	}
	// The published UI also retains Claims whose Entity member is unavailable. Their
	// subject identity is sufficient for a generic entry, without inventing a name.
	for _, member := range r.Members {
		if member.Kind != "claim" {
			continue
		}
		subject := index.claimBySlug[member.LogicalSlug].payload.Subject
		if _, exists := index.entityByID[subject]; exists {
			continue
		}
		index.entityByID[subject] = len(index.entities)
		index.entities = append(index.entities, indexedEntity{
			Entity: Entity{EntityID: subject, Name: subject}, placeholder: true,
		})
	}
	index.linkVersions(relations)
	return index, ctx.Err()
}

func decodeMember(member release.Member, target any) error {
	if !bytes.HasPrefix(bytes.TrimSpace(member.Payload), []byte("{")) {
		return malformed(member, "payload must be an object")
	}
	decoder := json.NewDecoder(bytes.NewReader(member.Payload))
	decoder.UseNumber()
	if err := decoder.Decode(target); err != nil {
		return fmt.Errorf("decode %s member %q: %w", member.Kind, member.LogicalSlug, err)
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return malformed(member, "trailing payload data")
	}
	return nil
}

func malformed(member release.Member, detail string) error {
	return &release.Error{
		Code:   release.ErrorInvalidRequest,
		Detail: fmt.Sprintf("invalid %s member %q: %s", member.Kind, member.LogicalSlug, detail),
	}
}
