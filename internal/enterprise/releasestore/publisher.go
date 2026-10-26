package releasestore

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"

	"gorm.io/gorm"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// memberEnvelope is what wiki_release_members.content holds for an enterprise member:
// the exact payload text (JSONB would reformat it) plus the fields the release table
// has no columns for. The payload column keeps a JSONB copy for search only.
type memberEnvelope struct {
	Version      int      `json:"v"`
	Payload      string   `json:"payload"`
	EvidenceRefs []string `json:"evidence_refs,omitempty"`
	AccessScope  string   `json:"access_scope,omitempty"`
}

// releaseManifest is stored on the preparation so a release can be traced back
// to the candidate and decision that produced it.
type releaseManifest struct {
	CandidateID    string      `json:"candidate_id"`
	DecisionID     string      `json:"decision_id"`
	DecisionDigest string      `json:"decision_digest"`
	BundleDigest   string      `json:"bundle_digest"`
	Members        [][2]string `json:"members"`
}

// Head returns the active release of a Space, or an empty Head before the first one.
func (s *Store) Head(ctx context.Context, tenantID uint64, spaceID string) (release.Head, error) {
	scope, err := s.spaces.Scope(tenantID, spaceID)
	if err != nil {
		return release.Head{}, err
	}
	head, err := s.activeHead(ctx, scope)
	if errors.Is(err, repository.ErrWikiReleaseNotFound) {
		return release.Head{}, nil
	}
	if err != nil {
		return release.Head{}, err
	}
	return release.Head{ReleaseID: head.ActiveReleaseID, Epoch: head.ActivationEpoch}, nil
}

// activeHead reads the Head of the (tenant, Space) and checks it serves the configured knowledge
// bases (S4c-2a Spec §3.2). A Head bound to other KBs is a configuration error, never "no release yet".
func (s *Store) activeHead(ctx context.Context, scope types.WikiReleaseScope) (*types.WikiReleaseHead, error) {
	head, err := s.releases.GetHeadForSpace(ctx, scope.TenantID, scope.SpaceID)
	if err != nil {
		return nil, err
	}
	if head.WikiReleaseScope != scope {
		return nil, &release.Error{
			Code:   release.ErrorServiceUnavailable,
			Detail: "the Space's published releases belong to other knowledge bases than its configuration",
		}
	}
	return head, nil
}

// MembersOf returns slug -> member digest of one release of the Space.
func (s *Store) MembersOf(ctx context.Context, tenantID uint64, spaceID, releaseID string) (map[string]string, error) {
	scope, err := s.spaces.Scope(tenantID, spaceID)
	if err != nil {
		return nil, err
	}
	snapshots, err := s.releases.GetReleaseMembers(ctx, scope, releaseID)
	if err != nil {
		return nil, err
	}
	out := make(map[string]string, len(snapshots))
	for _, m := range snapshots {
		out[m.LogicalSlug] = m.MemberDigest
	}
	return out, nil
}

// ReleaseByID reads a complete release (the active one for an empty ID) and verifies
// every member's payload against its digest before returning it.
func (s *Store) ReleaseByID(ctx context.Context, tenantID uint64, spaceID, releaseID string) (release.Release, error) {
	scope, err := s.spaces.Scope(tenantID, spaceID)
	if err != nil {
		return release.Release{}, err
	}
	header, err := s.releaseHeader(ctx, scope, releaseID)
	if err != nil {
		return release.Release{}, err
	}
	key := memberKey{Tenant: tenantID, Space: spaceID, Release: header.ID}
	header.Members, err = s.members.load(ctx, key, func(ctx context.Context) ([]release.Member, error) {
		snapshots, err := s.releases.GetReleaseMembers(ctx, scope, header.ID)
		if err != nil {
			return nil, err
		}
		members := make([]release.Member, 0, len(snapshots))
		for _, snapshot := range snapshots {
			m, err := decodeMember(snapshot)
			if err != nil {
				return nil, fmt.Errorf("release %s member %s: %w", header.ID, snapshot.LogicalSlug, err)
			}
			members = append(members, m)
		}
		return members, nil
	})
	if err != nil {
		return release.Release{}, err
	}
	return header, nil
}

// Activate publishes the complete member set in one repository transaction:
// Ready preparation, release, members, Head CAS and receipt. Identifiers derive from
// the nonce, so a retry finds the committed receipt instead of activating twice.
func (s *Store) Activate(ctx context.Context, w release.ActivationWrite) (release.Release, error) {
	scope, err := s.spaces.Scope(w.TenantID, w.SpaceID)
	if err != nil {
		return release.Release{}, err
	}
	if committed, ok, err := s.committed(ctx, scope, w); ok || err != nil {
		return committed, err
	}
	if committed, ok, err := s.PublishedCandidate(ctx, w.TenantID, w.SpaceID, w.BundleDigest); ok || err != nil {
		return committed, err
	}
	snapshots, manifest, err := snapshotsOf(w)
	if err != nil {
		return release.Release{}, err
	}
	key := shortDigest(w.Nonce)
	now := s.now()
	preparation := types.WikiReleasePreparation{
		ID: "prep_" + key, WikiReleaseScope: scope, CandidateDigest: w.BundleDigest,
		ManifestDigest: digestOf(manifest), ReadyReceiptDigest: w.Nonce, ReviewDecisionDigest: w.DecisionDigest,
		ReviewPolicyID: w.DecisionID, ExpectedReleaseID: w.Expected.ReleaseID,
		ExpectedActivationEpoch: w.Expected.Epoch, Status: types.WikiReleasePreparationReady,
		Manifest: manifest, Members: snapshots, CreatedAt: now,
	}
	preparation.PreparationDigest = digestOf([]byte(fmt.Sprintf("%s|%s|%s|%s|%d",
		preparation.ID, preparation.ManifestDigest, w.DecisionDigest, w.Expected.ReleaseID, w.Expected.Epoch)))
	rel := types.WikiRelease{
		ID: "rel_" + key, WikiReleaseScope: scope, CandidateDigest: w.BundleDigest,
		ManifestDigest: preparation.ManifestDigest, BaseReleaseID: w.Expected.ReleaseID,
		BaseActivationEpoch: w.Expected.Epoch, PreparationID: preparation.ID, CreatedAt: now, ActivatedAt: now,
	}
	publishedID := rel.ID
	err = s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := lockCandidate(tx, w); err != nil {
			return err
		}
		id, err := candidateReleaseID(tx, w.TenantID, w.SpaceID, w.BundleDigest)
		if err != nil {
			return err
		}
		if id != "" {
			publishedID = id
			return nil
		}
		refs, err := sourceRefs(w.Members)
		if err != nil {
			return err
		}
		if err := lockSourceKnowledges(tx, w.TenantID, refs); err != nil {
			return err
		}
		releases := repository.NewWikiReleaseRepository(tx)
		if _, err := releases.GetReceipt(ctx, scope, w.Nonce); err == nil {
			return repository.ErrWikiReleaseConflict
		} else if !errors.Is(err, repository.ErrWikiReleaseNotFound) {
			return err
		}
		if err := repository.PinRevisionSources(tx, w.TenantID, refs); err != nil {
			return err
		}
		if _, err := lockHead(tx, scope); err != nil {
			return err
		}
		_, err = releases.Activate(ctx, repository.WikiReleaseActivationWrite{
			Preparation: &preparation, Release: &rel, Members: snapshots,
			ExpectedReleaseID: w.Expected.ReleaseID, ExpectedActivationEpoch: w.Expected.Epoch,
			Nonce: w.Nonce, AuthorizationDigest: w.DecisionDigest, ActivatedBy: w.Subject, ActivatedAt: now,
			ActivationReceiptID: "rcpt_" + key, ExpectedPreparationID: preparation.ID,
			ExpectedPreparationDigest: preparation.PreparationDigest,
			// A first release must not take over a wiki KB that another Head already serves.
			RequireInitialWikiKBUnbound: w.Expected.ReleaseID == "",
		})
		if err != nil {
			return err
		}
		return storeSourceLinks(tx, w, rel.ID, refs)
	})
	if err != nil {
		// A concurrent retry of the same activation may have committed first.
		if committed, ok, lookupErr := s.committed(ctx, scope, w); ok || lookupErr != nil {
			return committed, lookupErr
		}
		committed, ok, lookupErr := s.PublishedCandidate(ctx, w.TenantID, w.SpaceID, w.BundleDigest)
		if ok || lookupErr != nil {
			return committed, lookupErr
		}
		if errors.Is(err, repository.ErrRevisionSourceUnavailable) {
			return release.Release{}, &release.Error{
				Code: release.ErrorSourceUnavailable, Detail: "a cited source is unavailable",
			}
		}
		if errors.Is(err, repository.ErrWikiReleaseConflict) {
			return release.Release{}, &release.Error{
				Code: release.ErrorReleaseConflict, Detail: "the active release changed",
			}
		}
		return release.Release{}, err
	}
	return s.ReleaseByID(ctx, w.TenantID, w.SpaceID, publishedID)
}

func (s *Store) committed(
	ctx context.Context, scope types.WikiReleaseScope, w release.ActivationWrite,
) (release.Release, bool, error) {
	receipt, err := s.releases.GetReceipt(ctx, scope, w.Nonce)
	if errors.Is(err, repository.ErrWikiReleaseNotFound) {
		return release.Release{}, false, nil
	}
	if err != nil {
		return release.Release{}, false, err
	}
	r, err := s.ReleaseByID(ctx, w.TenantID, w.SpaceID, receipt.ReleaseID)
	return r, true, err
}

func snapshotsOf(w release.ActivationWrite) ([]types.WikiReleaseMemberSnapshot, json.RawMessage, error) {
	snapshots := make([]types.WikiReleaseMemberSnapshot, 0, len(w.Members))
	manifest := releaseManifest{
		CandidateID: w.CandidateID, DecisionID: w.DecisionID,
		DecisionDigest: w.DecisionDigest, BundleDigest: w.BundleDigest,
	}
	for _, m := range w.Members {
		envelope, err := json.Marshal(memberEnvelope{
			Version: 1, Payload: string(m.Payload), EvidenceRefs: m.EvidenceRefs, AccessScope: m.AccessScope,
		})
		if err != nil {
			return nil, nil, err
		}
		snapshots = append(snapshots, types.WikiReleaseMemberSnapshot{
			Kind: m.Kind, LogicalSlug: m.LogicalSlug, MemberDigest: m.MemberDigest,
			Content: string(envelope), Payload: append(json.RawMessage(nil), m.Payload...),
		})
		manifest.Members = append(manifest.Members, [2]string{m.LogicalSlug, m.MemberDigest})
	}
	raw, err := json.Marshal(manifest)
	return snapshots, raw, err
}

func decodeMember(snapshot types.WikiReleaseMemberSnapshot) (release.Member, error) {
	var envelope memberEnvelope
	if err := json.Unmarshal([]byte(snapshot.Content), &envelope); err != nil || envelope.Version != 1 {
		return release.Member{}, errors.New("member content is not an enterprise member")
	}
	payload := json.RawMessage(envelope.Payload)
	digest, err := release.MemberDigest(payload)
	if err != nil || digest != snapshot.MemberDigest {
		return release.Member{}, errors.New("member payload does not match its digest")
	}
	return release.Member{
		Kind: snapshot.Kind, LogicalSlug: snapshot.LogicalSlug, Payload: payload,
		MemberDigest: snapshot.MemberDigest, EvidenceRefs: envelope.EvidenceRefs, AccessScope: envelope.AccessScope,
	}, nil
}

func notFound(err error) error {
	if errors.Is(err, repository.ErrWikiReleaseNotFound) {
		return &release.Error{Code: release.ErrorReleaseNotFound, Detail: "no such release in this Space"}
	}
	return err
}

func digestOf(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}
