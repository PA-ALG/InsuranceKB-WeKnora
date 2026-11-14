package releasestore

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/Tencent/WeKnora/internal/enterprise/memberstore"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
)

// ReleaseSummary resolves the single Head, then verifies that version's header.
func (s *Store) ReleaseSummary(ctx context.Context, tenantID uint64, spaceID string) (release.Release, error) {
	scope, err := s.spaces.Scope(tenantID, spaceID)
	if err != nil {
		return release.Release{}, err
	}
	head, err := s.Head(ctx, tenantID, spaceID)
	if err != nil {
		return release.Release{}, err
	}
	if head.ReleaseID == "" {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound, Detail: "no active release"}
	}
	record, err := s.releases.GetRelease(ctx, scope, head.ReleaseID)
	if err != nil {
		s.storage.RecordReadFailure(ctx, s.db, scope, head.ReleaseID, err)
		return release.Release{}, fmt.Errorf("active release header: %w", err)
	}
	var out release.Release
	var refused error
	err = s.storage.ValidateRead(ctx, s.db, scope, head.ReleaseID, func(ctx context.Context) error {
		out, _, err = s.memberReadHeader(ctx, scope, record)
		if isMemberReadLimit(err) {
			refused = err
			return nil
		}
		if err == nil && out.Epoch != head.Epoch {
			return memberstore.ErrIntegrity
		}
		return err
	})
	if err != nil {
		return release.Release{}, err
	}
	return out, refused
}

// MemberIndex checks the ownership projection against an immutable release manifest.
func (s *Store) MemberIndex(ctx context.Context, tenantID uint64, spaceID, id string) (
	release.Release, []release.Member, error,
) {
	return s.fixedMembers(ctx, tenantID, spaceID, id, nil)
}

// LookupMembers returns verified bodies for the selected keys of a fixed Release.
func (s *Store) LookupMembers(ctx context.Context, tenantID uint64, spaceID, id string, slugs []string) (
	release.Release, []release.Member, error,
) {
	if len(slugs) == 0 || len(slugs) > release.MaxMemberLookup {
		return release.Release{}, nil, &release.Error{Code: release.ErrorInvalidRequest, Detail: "invalid lookup size"}
	}
	return s.fixedMembers(ctx, tenantID, spaceID, id, slugs)
}

func (s *Store) fixedMembers(ctx context.Context, tenantID uint64, spaceID, id string, slugs []string) (
	out release.Release, members []release.Member, failure error,
) {
	if id == "" || id == "active" {
		return out, nil, &release.Error{Code: release.ErrorInvalidRequest, Detail: "a fixed release is required"}
	}
	scope, err := s.spaces.Scope(tenantID, spaceID)
	if err != nil {
		return out, nil, err
	}
	record, _, err := s.releaseRecord(ctx, scope, id)
	if err != nil {
		s.storage.RecordReadFailure(ctx, s.db, scope, id, err)
		return out, nil, err
	}
	var tooLarge bool
	failure = s.storage.ValidateRead(ctx, s.db, scope, id, func(ctx context.Context) error {
		var want map[string]string
		out, want, err = s.memberReadHeader(ctx, scope, record)
		if err != nil {
			tooLarge = isMemberReadLimit(err)
			if tooLarge {
				return nil
			}
			return err
		}
		selected, err := s.storage.Select(ctx, s.db, scope, id, release.MaxMemberIndex, slugs)
		if err != nil {
			if errors.Is(err, memberstore.ErrReadLimit) {
				tooLarge = true
				return nil
			}
			return err
		}
		members, err = verifiedSelection(want, selected, slugs)
		return err
	})
	if failure != nil {
		return release.Release{}, nil, failure
	}
	if tooLarge {
		return release.Release{}, nil, release.MemberReadLimit()
	}
	return out, members, nil
}

func isMemberReadLimit(err error) bool {
	var typed *release.Error
	return errors.As(err, &typed) && typed.Code == release.ErrorReleaseReadLimit
}

func (s *Store) memberReadHeader(ctx context.Context, scope types.WikiReleaseScope, r *types.WikiRelease) (
	release.Release, map[string]string, error,
) {
	var p types.WikiReleasePreparation
	fields := []string{
		"preparation_id", "tenant_id", "space_id", "raw_kb_id", "wiki_kb_id", "candidate_digest",
		"manifest_digest", "review_decision_digest", "review_policy_id", "expected_release_id",
		"expected_activation_epoch", "status", "manifest",
	}
	err := s.db.WithContext(ctx).Select(fields).
		Where("preparation_id = ? AND tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?",
			r.PreparationID, scope.TenantID, scope.SpaceID, scope.RawKBID, scope.WikiKBID).Take(&p).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return release.Release{}, nil, memberstore.ErrIntegrity
	}
	if err != nil {
		return release.Release{}, nil, err
	}
	manifest, err := readIndexManifest(*r, p)
	if err != nil {
		return release.Release{}, nil, err
	}
	retired, err := s.retiredAt(ctx, scope, r.ID)
	if err != nil {
		return release.Release{}, nil, err
	}
	out := release.Release{
		ID: r.ID, Epoch: r.BaseActivationEpoch + 1, BaseReleaseID: r.BaseReleaseID,
		CandidateID: manifest.CandidateID, DecisionDigest: manifest.DecisionDigest, RetiredAt: retired,
	}
	want := make(map[string]string, len(manifest.Members))
	for _, item := range manifest.Members {
		if _, exists := want[item[0]]; exists || item[0] == "" || item[1] == "" {
			return release.Release{}, nil, memberstore.ErrIntegrity
		}
		want[item[0]] = item[1]
	}
	return out, want, nil
}

func readIndexManifest(r types.WikiRelease, p types.WikiReleasePreparation) (releaseManifest, error) {
	var manifest releaseManifest
	if len(p.Manifest) > release.MaxMemberReadBytes {
		return manifest, release.MemberReadLimit()
	}
	if json.Unmarshal(p.Manifest, &manifest) != nil {
		return manifest, memberstore.ErrIntegrity
	}
	if len(manifest.Members) > release.MaxMemberIndex {
		return manifest, release.MemberReadLimit()
	}
	canonical, err := json.Marshal(manifest)
	if err != nil || r.PreparationID != p.ID || r.WikiReleaseScope != p.WikiReleaseScope ||
		p.Status != types.WikiReleasePreparationReady || r.CandidateDigest != p.CandidateDigest ||
		r.ManifestDigest != p.ManifestDigest || digestOf(canonical) != p.ManifestDigest ||
		p.ExpectedReleaseID != r.BaseReleaseID || p.ExpectedActivationEpoch != r.BaseActivationEpoch ||
		manifest.BundleDigest != r.CandidateDigest || manifest.DecisionID != p.ReviewPolicyID ||
		manifest.DecisionDigest != p.ReviewDecisionDigest || manifest.CandidateID == "" {
		return manifest, memberstore.ErrIntegrity
	}
	return manifest, nil
}

func verifiedSelection(want map[string]string, in memberstore.MemberSelection, slugs []string) (
	[]release.Member, error,
) {
	if in.Pairs != nil && !verifiedPairs(want, in.Pairs) {
		return nil, memberstore.ErrIntegrity
	}
	if slugs == nil && !verifiedPairs(want, in.Members) {
		return nil, memberstore.ErrIntegrity
	}
	needed := make(map[string]bool, len(slugs))
	for _, slug := range slugs {
		if _, found := want[slug]; found {
			needed[slug] = true
		}
	}
	out := make([]release.Member, 0, len(in.Members))
	for _, row := range in.Members {
		if slugs == nil {
			out = append(out, release.Member{
				Kind: row.Kind, LogicalSlug: row.LogicalSlug,
				MemberDigest: row.MemberDigest, Payload: row.Payload,
			})
			continue
		}
		if !needed[row.LogicalSlug] || want[row.LogicalSlug] != row.MemberDigest {
			return nil, memberstore.ErrIntegrity
		}
		delete(needed, row.LogicalSlug)
		member, err := decodeMember(row)
		if err != nil {
			return nil, memberstore.ErrIntegrity
		}
		out = append(out, member)
	}
	if len(needed) != 0 {
		return nil, memberstore.ErrIntegrity
	}
	return out, nil
}

func verifiedPairs(want map[string]string, rows []types.WikiReleaseMemberSnapshot) bool {
	if len(want) != len(rows) {
		return false
	}
	seen := make(map[string]bool, len(rows))
	for _, row := range rows {
		if seen[row.LogicalSlug] || want[row.LogicalSlug] != row.MemberDigest || row.MemberDigest == "" {
			return false
		}
		seen[row.LogicalSlug] = true
	}
	return true
}
