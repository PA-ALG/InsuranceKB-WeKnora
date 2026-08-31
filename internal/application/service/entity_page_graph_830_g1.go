package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"reflect"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
)

var (
	ErrEntityPageGraphNotFound830G1  = errors.New("entity page graph 830 g1 not found")
	ErrEntityPageGraphForbidden830G1 = errors.New("entity page graph 830 g1 forbidden")
	ErrEntityPageGraphIntegrity830G1 = errors.New("entity page graph 830 g1 integrity failure")
)

type EntityPageGraphReleaseSnapshot830G1 struct {
	ReleaseID       string
	ActivationEpoch uint64
	Manifest        json.RawMessage
	Members         []types.WikiReleaseMemberSnapshot
}

type EntityPageGraphReleaseSource830G1 interface {
	LoadCurrentEntityPageGraphRelease830G1(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
	) (EntityPageGraphReleaseSnapshot830G1, error)
	LoadPinnedEntityPageGraphRelease830G1(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
	) (EntityPageGraphReleaseSnapshot830G1, error)
}

type EntityPageGraphSelector830G1 struct {
	EntityID  string
	PageKind  string
	StableKey string
}

type EntityPageGraphRead830G1 struct {
	Contract        string                                   `json:"contract"`
	ReadMode        string                                   `json:"read_mode"`
	ReleaseID       string                                   `json:"release_id"`
	ActivationEpoch uint64                                   `json:"activation_epoch"`
	ManifestSHA256  string                                   `json:"manifest_sha256"`
	EntityID        string                                   `json:"entity_id"`
	EntityVersionID string                                   `json:"entity_version_id"`
	DisplayName     string                                   `json:"display_name"`
	Classification  string                                   `json:"classification_display_name"`
	Profile         types.EntityPagePresentationProfile830G1 `json:"profile"`
	Member          types.EntityPageMember830G1              `json:"member"`
}

type EntityPageGraphService830G1 struct {
	source EntityPageGraphReleaseSource830G1
}

func NewEntityPageGraphService830G1(source EntityPageGraphReleaseSource830G1) *EntityPageGraphService830G1 {
	return &EntityPageGraphService830G1{source: source}
}

func (s *EntityPageGraphService830G1) ReadCurrentEntityPage830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	selector EntityPageGraphSelector830G1,
) (*EntityPageGraphRead830G1, error) {
	if s == nil || s.source == nil {
		return nil, ErrEntityPageGraphIntegrity830G1
	}
	snapshot, err := s.source.LoadCurrentEntityPageGraphRelease830G1(ctx, principal, scope)
	if err != nil {
		return nil, mapEntityPageGraphSourceError830G1(err)
	}
	return readEntityPageGraphSnapshot830G1(scope, snapshot, selector, "current")
}

func (s *EntityPageGraphService830G1) ReadPinnedEntityPage830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	selector EntityPageGraphSelector830G1,
) (*EntityPageGraphRead830G1, error) {
	releaseID = strings.TrimSpace(releaseID)
	if s == nil || s.source == nil {
		return nil, ErrEntityPageGraphIntegrity830G1
	}
	if releaseID == "" || releaseID == "current" || releaseID == "latest" {
		return nil, ErrEntityPageGraphNotFound830G1
	}
	snapshot, err := s.source.LoadPinnedEntityPageGraphRelease830G1(ctx, principal, scope, releaseID)
	if err != nil {
		return nil, mapEntityPageGraphSourceError830G1(err)
	}
	if snapshot.ReleaseID != releaseID {
		return nil, ErrEntityPageGraphIntegrity830G1
	}
	return readEntityPageGraphSnapshot830G1(scope, snapshot, selector, "pinned")
}

func readEntityPageGraphSnapshot830G1(
	scope types.WikiReleaseScope,
	snapshot EntityPageGraphReleaseSnapshot830G1,
	selector EntityPageGraphSelector830G1,
	readMode string,
) (*EntityPageGraphRead830G1, error) {
	manifest, err := types.ParseEntityPageManifest830G1(snapshot.Manifest)
	if err != nil || snapshot.ReleaseID != manifest.ReleaseID ||
		(readMode == "current" && snapshot.ActivationEpoch == 0) ||
		(snapshot.ActivationEpoch != 0 && snapshot.ActivationEpoch != manifest.ActivationEpoch) ||
		scope.SpaceID != manifest.SpaceID || scope.WikiKBID != manifest.WikiKBID ||
		len(snapshot.Members) != len(manifest.Members) {
		return nil, ErrEntityPageGraphIntegrity830G1
	}
	storedByPageID := make(map[string]types.WikiReleaseMemberSnapshot, len(snapshot.Members))
	for _, stored := range snapshot.Members {
		if stored.LogicalSlug == "" {
			return nil, ErrEntityPageGraphIntegrity830G1
		}
		if _, duplicate := storedByPageID[stored.LogicalSlug]; duplicate {
			return nil, ErrEntityPageGraphIntegrity830G1
		}
		storedByPageID[stored.LogicalSlug] = stored
	}
	for _, member := range manifest.Members {
		stored, exists := storedByPageID[member.PageID]
		if !exists {
			return nil, ErrEntityPageGraphIntegrity830G1
		}
		if stored.Kind != member.PageKind || stored.LogicalSlug != member.PageID ||
			stored.RevisionID != member.PayloadSHA256 || stored.MemberDigest != member.MemberDigest ||
			stored.Title != member.ShortTitle || !entityPageGraphJSONEqual830G1(stored.Payload, member.Payload) {
			return nil, ErrEntityPageGraphIntegrity830G1
		}
	}
	if !validEntityPageGraphSelector830G1(selector) || selector.EntityID != manifest.EntityID {
		return nil, ErrEntityPageGraphNotFound830G1
	}
	member, found := manifest.Member(selector.PageKind, selector.StableKey)
	if !found {
		return nil, ErrEntityPageGraphNotFound830G1
	}
	activationEpoch := snapshot.ActivationEpoch
	if activationEpoch == 0 {
		activationEpoch = manifest.ActivationEpoch
	}
	return &EntityPageGraphRead830G1{
		Contract: "entity-page-read.830.g1.v1", ReadMode: readMode,
		ReleaseID: manifest.ReleaseID, ActivationEpoch: activationEpoch,
		ManifestSHA256: manifest.ManifestSHA256, EntityID: manifest.EntityID,
		EntityVersionID: manifest.EntityVersionID, DisplayName: manifest.DisplayName,
		Classification: manifest.ClassificationDisplayName, Profile: manifest.Profile, Member: member,
	}, nil
}

func entityPageGraphJSONEqual830G1(left, right json.RawMessage) bool {
	decode := func(raw json.RawMessage) (any, bool) {
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		var value any
		if err := decoder.Decode(&value); err != nil {
			return nil, false
		}
		var trailing any
		if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
			return nil, false
		}
		return value, true
	}
	leftValue, leftOK := decode(left)
	rightValue, rightOK := decode(right)
	return leftOK && rightOK && reflect.DeepEqual(leftValue, rightValue)
}

func validEntityPageGraphSelector830G1(selector EntityPageGraphSelector830G1) bool {
	if strings.TrimSpace(selector.EntityID) == "" || strings.TrimSpace(selector.StableKey) == "" {
		return false
	}
	switch selector.PageKind {
	case "overview":
		return selector.StableKey == "overview"
	case "section", "field":
		return true
	case "free_wiki":
		return selector.StableKey == "free-wiki"
	default:
		return false
	}
}

func mapEntityPageGraphSourceError830G1(err error) error {
	switch {
	case errors.Is(err, ErrEntityPageGraphNotFound830G1), errors.Is(err, ErrWikiReleaseNotFound):
		return ErrEntityPageGraphNotFound830G1
	case errors.Is(err, ErrEntityPageGraphForbidden830G1), errors.Is(err, ErrWikiReleaseAccessDenied):
		return ErrEntityPageGraphForbidden830G1
	case errors.Is(err, ErrEntityPageGraphIntegrity830G1), errors.Is(err, ErrWikiReleaseInvalidAuthorization),
		errors.Is(err, ErrSchemaWikiPreparationInvalid):
		return ErrEntityPageGraphIntegrity830G1
	default:
		return ErrEntityPageGraphIntegrity830G1
	}
}

func (s *SchemaWikiService) LoadCurrentEntityPageGraphRelease830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	if s == nil || s.releaseAuthority == nil {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphNotFound830G1
	}
	pin, err := s.releaseAuthority.BeginPinnedRead(ctx, principal, scope)
	if err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, err
	}
	return s.loadEntityPageGraphRelease830G1(ctx, principal, scope, pin.ReleaseID(), pin.ActivationEpoch())
}

func (s *SchemaWikiService) LoadPinnedEntityPageGraphRelease830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	if s == nil || s.releaseAuthority == nil {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphNotFound830G1
	}
	return s.loadEntityPageGraphRelease830G1(ctx, principal, scope, releaseID, 0)
}

func (s *SchemaWikiService) loadEntityPageGraphRelease830G1(
	ctx context.Context,
	principal types.WikiReleasePrincipal,
	scope types.WikiReleaseScope,
	releaseID string,
	activationEpoch uint64,
) (EntityPageGraphReleaseSnapshot830G1, error) {
	if strings.TrimSpace(releaseID) == "" {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphNotFound830G1
	}
	if err := s.releaseAuthority.verifyAccess(ctx, principal, scope, "entity-page-graph-830-g1"); err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, err
	}
	members, err := s.releaseAuthority.repository.GetReleaseMembers(ctx, scope, releaseID)
	if err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, mapWikiReleaseRepositoryError(err)
	}
	release, err := s.releaseAuthority.repository.GetRelease(ctx, scope, releaseID)
	if err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, mapWikiReleaseRepositoryError(err)
	}
	preparation, err := s.releaseAuthority.repository.GetReadyPreparation(ctx, scope, release.PreparationID)
	if err != nil {
		return EntityPageGraphReleaseSnapshot830G1{}, mapWikiReleaseRepositoryError(err)
	}
	manifest, manifestErr := types.ParseEntityPageManifest830G1(preparation.Manifest)
	if manifestErr != nil || release.ID != releaseID || release.WikiReleaseScope != scope ||
		preparation.WikiReleaseScope != scope || preparation.ID != release.PreparationID ||
		preparation.Status != types.WikiReleasePreparationReady ||
		preparation.CandidateDigest != release.CandidateDigest ||
		preparation.ManifestDigest != release.ManifestDigest ||
		manifest.ManifestSHA256 != preparation.ManifestDigest ||
		digestWikiReleasePreparation(preparation) != preparation.PreparationDigest ||
		manifest.ReleaseID != releaseID || manifest.SpaceID != scope.SpaceID ||
		manifest.WikiKBID != scope.WikiKBID ||
		manifest.InputAuthority.CandidateSHA256 != release.CandidateDigest ||
		!entityPageGraphMemberSetsEqual830G1(preparation.Members, members) {
		return EntityPageGraphReleaseSnapshot830G1{}, ErrEntityPageGraphIntegrity830G1
	}
	return EntityPageGraphReleaseSnapshot830G1{
		ReleaseID: releaseID, ActivationEpoch: activationEpoch,
		Manifest: append(json.RawMessage(nil), preparation.Manifest...), Members: members,
	}, nil
}

func entityPageGraphMemberSetsEqual830G1(
	left []types.WikiReleaseMemberSnapshot,
	right []types.WikiReleaseMemberSnapshot,
) bool {
	if len(left) != len(right) {
		return false
	}
	rightBySlug := make(map[string]types.WikiReleaseMemberSnapshot, len(right))
	for _, member := range right {
		if member.LogicalSlug == "" {
			return false
		}
		if _, duplicate := rightBySlug[member.LogicalSlug]; duplicate {
			return false
		}
		rightBySlug[member.LogicalSlug] = member
	}
	for _, member := range left {
		stored, exists := rightBySlug[member.LogicalSlug]
		if !exists || member.Kind != stored.Kind || member.RevisionID != stored.RevisionID ||
			member.MemberDigest != stored.MemberDigest || member.Title != stored.Title ||
			member.Content != stored.Content || !entityPageGraphJSONEqual830G1(member.Payload, stored.Payload) {
			return false
		}
		delete(rightBySlug, member.LogicalSlug)
	}
	return len(rightBySlug) == 0
}
