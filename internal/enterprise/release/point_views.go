package release

import (
	"context"
	"errors"
	"sort"
	"time"
)

// PointVerdict is the public audit summary of a point decision.
type PointVerdict struct {
	Outcome   string    `json:"outcome"`
	Reason    string    `json:"reason"`
	Subject   string    `json:"subject"`
	CreatedAt time.Time `json:"created_at"`
}

// ReviewPoint presents the fixed point identity and its current review state.
type ReviewPoint struct {
	Slug      string        `json:"slug"`
	Kind      string        `json:"kind"`
	Status    string        `json:"status"`
	Decision  *PointVerdict `json:"decision"`
	ReleaseID *string       `json:"release_id"`
	Blocker   string        `json:"blocker"`
}

type reviewPoints struct {
	latestRelease string
	base          map[string]string
	kinds         map[string]string
	changed       map[string]Member
	accompanying  []Member
	decisions     map[string]PointDecision
}

type pointReads struct {
	service   *Service
	principal Principal
	space     string
	releases  map[string]Release
	bases     map[string]map[string]string
}

func newPointReads(s *Service, p Principal, space string) *pointReads {
	return &pointReads{s, p, space, map[string]Release{}, map[string]map[string]string{}}
}

func (r *pointReads) base(ctx context.Context, id string) (map[string]string, error) {
	if id == "" {
		return nil, nil
	}
	if value, ok := r.bases[id]; ok {
		return value, nil
	}
	value, err := r.service.store.MembersOf(ctx, r.principal.TenantID, r.space, id)
	if err == nil {
		r.bases[id] = value
	}
	return value, err
}

func (r *pointReads) release(ctx context.Context, id string) (Release, error) {
	if id == "" {
		return Release{}, nil
	}
	if value, ok := r.releases[id]; ok {
		return value, nil
	}
	value, err := r.service.publisher.ReleaseByID(ctx, r.principal.TenantID, r.space, id)
	if err == nil {
		r.releases[id] = value
	}
	return value, err
}

func (r *pointReads) head(ctx context.Context) (Head, Release, error) {
	h, err := r.service.store.Head(ctx, r.principal.TenantID, r.space)
	if err != nil {
		return h, Release{}, err
	}
	active, err := r.release(ctx, h.ReleaseID)
	return h, active, err
}

func (r *pointReads) load(ctx context.Context, e QueueEntry, b Bundle) (*reviewPoints, error) {
	base, err := r.base(ctx, b.BaseReleaseID)
	if err != nil {
		return nil, err
	}
	out := &reviewPoints{
		base: base, kinds: map[string]string{},
		changed: map[string]Member{}, decisions: map[string]PointDecision{},
	}
	for _, m := range b.Members {
		previous, existed := out.base[m.LogicalSlug]
		if existed && previous == m.MemberDigest {
			continue
		}
		if m.Kind != "claim" && !existed {
			out.accompanying = append(out.accompanying, m)
			continue
		}
		kind := "member"
		if m.Kind == "claim" {
			kind = "claim"
		}
		out.kinds[m.LogicalSlug], out.changed[m.LogicalSlug] = kind, m
	}
	for _, slug := range b.Removals {
		out.kinds[slug] = "removal"
	}
	store := r.service.publisher.(PointStore)
	decisions, err := store.PointDecisions(ctx, r.principal.TenantID, r.space, e.Candidate.ID)
	if err != nil {
		return nil, err
	}
	if err := out.setDecisions(e.Candidate, decisions); err != nil {
		return nil, err
	}
	var latest Release
	for _, d := range decisions {
		if d.ReleaseID == "" {
			continue
		}
		published, err := r.release(ctx, d.ReleaseID)
		if err != nil {
			return nil, err
		}
		if published.Epoch > latest.Epoch {
			latest = published
		}
	}
	out.latestRelease = latest.ID
	return out, nil
}

func (p *reviewPoints) setDecisions(c Candidate, decisions []PointDecision) error {
	p.decisions = map[string]PointDecision{}
	for _, d := range decisions {
		if d.TenantID != c.TenantID || d.SpaceID != c.SpaceID || d.CandidateID != c.ID ||
			(d.Outcome != "approve" && d.Outcome != "reject") || (d.Outcome == "approve") != (d.ReleaseID != "") {
			return errors.New("point store returned an inconsistent decision")
		}
		if _, ok := p.kinds[d.Slug]; !ok {
			return errors.New("point store returned an unknown point")
		}
		if _, ok := p.decisions[d.Slug]; ok {
			return errors.New("point store returned a duplicate point")
		}
		p.decisions[d.Slug] = d
	}
	return nil
}

// materialize checks even when the base equals Head; it never treats CandidateID
// as a committed batch. Unchanged accompanying members are not touched again.
func (p *reviewPoints) materialize(slugs []string, active Release) ([]Member, error) {
	now := digestsBySlug(active.Members)
	delta := Bundle{}
	for _, slug := range slugs {
		if p.kinds[slug] == "removal" {
			delta.Removals = append(delta.Removals, slug)
		} else {
			delta.Members = append(delta.Members, p.changed[slug])
		}
	}
	for _, m := range p.accompanying {
		if now[m.LogicalSlug] != m.MemberDigest {
			delta.Members = append(delta.Members, m)
		}
	}
	return rebasePointDelta(p.base, delta, active)
}

func rebasePointDelta(base map[string]string, delta Bundle, active Release) ([]Member, error) {
	now := digestsBySlug(active.Members)
	touched := append([]string(nil), delta.Removals...)
	for _, m := range delta.Members {
		touched = append(touched, m.LogicalSlug)
	}
	for _, slug := range touched {
		if base[slug] != now[slug] {
			return nil, &Error{Code: ErrorNeedsRebase, Detail: "the Head changed a selected member"}
		}
	}
	return materialize(active.Members, delta)
}

func (p *reviewPoints) replay(slugs []string) string {
	id := ""
	for _, slug := range slugs {
		d, ok := p.decisions[slug]
		if !ok || d.Outcome != "approve" || (id != "" && id != d.ReleaseID) {
			return ""
		}
		id = d.ReleaseID
	}
	count := 0
	for _, d := range p.decisions {
		if d.ReleaseID == id {
			count++
		}
	}
	if count != len(slugs) {
		return ""
	}
	return id
}

// state returns the candidate status, pending count, latest release, latest decision time.
func (p *reviewPoints) state(e QueueEntry) (string, int, string, time.Time) {
	last := e.CreatedAt
	if e.Decision != nil {
		last = e.Decision.CreatedAt
	}
	if wholeReview(e) || len(p.kinds) == 0 {
		pending := 0
		if e.Candidate.Status == "pending" {
			pending = len(p.kinds)
		}
		return e.Candidate.Status, pending, e.ReleaseID, last
	}
	pending := len(p.kinds) - len(p.decisions)
	latest := PointDecision{}
	for _, d := range p.decisions {
		if d.CreatedAt.After(last) {
			last = d.CreatedAt
		}
		if d.ReleaseID != "" && (d.CreatedAt.After(latest.CreatedAt) ||
			(d.CreatedAt.Equal(latest.CreatedAt) && d.ID > latest.ID)) {
			latest = d
		}
	}
	status := "pending"
	if pending == 0 {
		status = "rejected"
		if latest.ReleaseID != "" {
			status = "released"
		}
	}
	id := latest.ReleaseID
	if p.latestRelease != "" {
		id = p.latestRelease
	}
	return status, pending, id, last
}

func (p *reviewPoints) summary(e QueueEntry, b Bundle) (ReviewSummary, time.Time, error) {
	item, err := reviewSummary(e, b)
	if err != nil {
		return item, time.Time{}, err
	}
	status, pending, id, last := p.state(e)
	item.Status, item.PointCount, item.PendingPoints, item.ReleaseID = status, len(p.kinds), pending, optionalString(id)
	return item, last, nil
}

func (p *reviewPoints) views(e QueueEntry, active Release) ([]ReviewPoint, error) {
	out := make([]ReviewPoint, 0, len(p.kinds))
	for slug, kind := range p.kinds {
		v := ReviewPoint{Slug: slug, Kind: kind, Status: "pending"}
		if wholeReview(e) {
			v.Status, v.ReleaseID = e.Candidate.Status, optionalString(e.ReleaseID)
			if d := e.Decision; d != nil {
				v.Decision = &PointVerdict{d.Outcome, d.Reason, d.Subject, d.CreatedAt}
			}
			if v.Status == "pending" {
				v.Blocker = ErrorCandidateDecided
			}
		} else if d, ok := p.decisions[slug]; ok {
			v.Status = "rejected"
			if d.Outcome == "approve" {
				v.Status = "released"
			}
			v.ReleaseID = optionalString(d.ReleaseID)
			v.Decision = &PointVerdict{d.Outcome, d.Reason, d.Subject, d.CreatedAt}
		} else if _, err := p.materialize([]string{slug}, active); err != nil {
			var failure *Error
			if !errors.As(err, &failure) {
				return nil, err
			}
			v.Blocker = failure.Code
		}
		out = append(out, v)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Slug < out[j].Slug })
	return out, nil
}
