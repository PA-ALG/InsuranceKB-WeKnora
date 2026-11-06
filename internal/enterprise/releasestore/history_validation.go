package releasestore

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"reflect"

	"github.com/Tencent/WeKnora/internal/enterprise/memberstore"
	"github.com/Tencent/WeKnora/internal/types"
)

// NewMemberStorage wires the same business validation for publication and migration.
// The low-level store cannot certify an unknown content protocol on its own.
func NewMemberStorage() *memberstore.Store { return memberstore.New(verifyHistoricalMembers) }

func verifyHistoricalMembers(r types.WikiRelease, p types.WikiReleasePreparation,
	members []types.WikiReleaseMemberSnapshot,
) error {
	if r.PreparationID != p.ID || r.WikiReleaseScope != p.WikiReleaseScope ||
		p.Status != types.WikiReleasePreparationReady || r.CandidateDigest != p.CandidateDigest ||
		r.ManifestDigest != p.ManifestDigest || r.BaseReleaseID != p.ExpectedReleaseID ||
		r.BaseActivationEpoch != p.ExpectedActivationEpoch {
		return memberstore.ErrIntegrity
	}
	var manifest releaseManifest
	if json.Unmarshal(p.Manifest, &manifest) != nil {
		return memberstore.ErrIntegrity
	}
	canonical, err := json.Marshal(manifest)
	if err != nil || digestOf(canonical) != p.ManifestDigest ||
		manifest.BundleDigest != p.CandidateDigest || manifest.DecisionID != p.ReviewPolicyID ||
		manifest.DecisionDigest != p.ReviewDecisionDigest || manifest.CandidateID == "" {
		return memberstore.ErrIntegrity
	}
	expected := digestOf([]byte(fmt.Sprintf("%s|%s|%s|%s|%d",
		p.ID, p.ManifestDigest, p.ReviewDecisionDigest, p.ExpectedReleaseID,
		p.ExpectedActivationEpoch)))
	if expected != p.PreparationDigest || len(manifest.Members) != len(p.Members) || len(members) != len(p.Members) {
		return memberstore.ErrIntegrity
	}
	prepared := make(map[string]types.WikiReleaseMemberSnapshot, len(p.Members))
	for i, m := range p.Members {
		if m.LogicalSlug == "" || manifest.Members[i] != [2]string{m.LogicalSlug, m.MemberDigest} {
			return memberstore.ErrIntegrity
		}
		if _, ok := prepared[m.LogicalSlug]; ok {
			return memberstore.ErrIntegrity
		}
		if err := validHistoricalMember(m); err != nil {
			return err
		}
		if m.Kind == "" {
			m.Kind = "page"
		}
		prepared[m.LogicalSlug] = m
	}
	for _, m := range members {
		old, ok := prepared[m.LogicalSlug]
		if !ok {
			return memberstore.ErrIntegrity
		}
		delete(prepared, m.LogicalSlug)
		if err := validHistoricalMember(m); err != nil {
			return err
		}
		if m.Kind != old.Kind || m.RevisionID != old.RevisionID ||
			m.MemberDigest != old.MemberDigest || m.Title != old.Title ||
			m.Content != old.Content || !equalJSON(m.Payload, old.Payload) {
			return memberstore.ErrIntegrity
		}
	}
	return nil
}

func validHistoricalMember(m types.WikiReleaseMemberSnapshot) error {
	member, err := decodeMember(m)
	if err != nil || !equalJSON(member.Payload, m.Payload) {
		return memberstore.ErrIntegrity
	}
	return nil
}

// JSONB projection equality must not round large numbers through float64. The frozen
// business MemberDigest itself still uses its original release.MemberDigest algorithm.
func equalJSON(a, b []byte) bool {
	decode := func(raw []byte) (any, error) {
		d := json.NewDecoder(bytes.NewReader(raw))
		d.UseNumber()
		var v any
		err := d.Decode(&v)
		if err != nil {
			return nil, err
		}
		if d.Decode(new(any)) != io.EOF {
			return nil, fmt.Errorf("trailing JSON")
		}
		return normalizedJSON(v), nil
	}
	x, e := decode(a)
	if e != nil {
		return false
	}
	y, e := decode(b)
	return e == nil && reflect.DeepEqual(x, y)
}

type exactJSONNumber struct{ Value string }

func normalizedJSON(v any) any {
	switch x := v.(type) {
	case json.Number:
		r, ok := new(big.Rat).SetString(string(x))
		if ok {
			return exactJSONNumber{r.RatString()}
		}
		return x
	case []any:
		for i := range x {
			x[i] = normalizedJSON(x[i])
		}
	case map[string]any:
		for k := range x {
			x[k] = normalizedJSON(x[k])
		}
	}
	return v
}
