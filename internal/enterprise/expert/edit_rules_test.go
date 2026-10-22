package expert_test

// S9a implementer tests beyond the acceptance file: Spec rules it does not cover, and the
// citation read used by the browser source panel. Reuses that file's fixture.

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/expert"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

func TestAMemberThatIsNoLongerAClaimIsStale(t *testing.T) {
	f := setup(t)
	page := map[string]any{"title": "P", "body": "text"}
	raw, err := json.Marshal(map[string]any{
		"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test",
		"base_release_id": f.first.ID,
		"members": []any{map[string]any{
			"kind": "wiki_page", "logical_slug": "P/page", "payload": page,
			"member_digest": digestOf(t, page), "access_scope": "space",
		}},
	})
	require.NoError(t, err)
	ctx := context.Background()
	c, err := f.releases.Receive(ctx, harness, spaceID, raw)
	require.NoError(t, err)
	d, err := f.releases.Decide(ctx, harness, spaceID, c.ID, approve)
	require.NoError(t, err)
	second, err := f.releases.Activate(ctx, harness, spaceID, c.ID, d.ID)
	require.NoError(t, err)

	_, err = f.editor.Edit(ctx, admin, "admin", spaceID, expert.EditInput{
		BaseReleaseID: second.ID, MemberSlug: "P/page", BaseMemberDigest: memberOf(second, "P/page").MemberDigest,
		State: "present", Value: "1日", Reason: "r",
	})
	require.Equal(t, expert.ErrorStale, codeOf(t, err))
	require.Empty(t, f.revisions.rows)
	require.Equal(t, 2, f.platform.activations)
}

func TestAReasonLongerThanTheLimitIsInvalid(t *testing.T) {
	f := setup(t)
	_, err := edit(f, expert.EditInput{
		MemberSlug: "P/waiting", State: "present", Value: "1日", Reason: strings.Repeat("理", expert.MaxReasonRunes+1),
	})
	require.Equal(t, expert.ErrorInvalid, codeOf(t, err))
	require.Empty(t, f.revisions.rows)

	_, err = edit(f, expert.EditInput{
		MemberSlug: "P/waiting", State: "present", Value: "1日", Reason: strings.Repeat("理", expert.MaxReasonRunes),
	})
	require.NoError(t, err)
}

// PostgreSQL keeps microseconds; a record whose digested time had nanoseconds could never be
// re-derived from its stored row.
func TestRecordTimesKeepOnlyWhatTheStoreKeeps(t *testing.T) {
	f := setup(t)
	editor := expert.NewService(f.releases, f.revisions,
		expert.WithClock(func() time.Time { return fixedAt.Add(123456789 * time.Nanosecond) }),
		expert.WithIDs(func() string { return "rev-nanos" }))
	result, err := editor.Edit(context.Background(), admin, "admin", spaceID, expert.EditInput{
		BaseReleaseID: f.first.ID, MemberSlug: "P/waiting",
		BaseMemberDigest: memberOf(f.first, "P/waiting").MemberDigest,
		State: "present", Value: "180日", Reason: "r",
	})
	require.NoError(t, err)
	require.Equal(t, fixedAt.Add(123456*time.Microsecond), result.Revision.RecordedAt)
}

func TestACitationReadsTheRecordItQuotes(t *testing.T) {
	f := setup(t)
	result, err := edit(f, expert.EditInput{MemberSlug: "P/waiting", State: "absent_explicitly", Reason: "条款无此责任"})
	require.NoError(t, err)
	var ev release.Evidence
	raw, err := json.Marshal(payloadOf(t, memberOf(result.Release, "P/waiting"))["evidence"].([]any)[0])
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(raw, &ev))
	ctx := context.Background()

	record, err := f.editor.Citation(ctx, admin, spaceID, ev)
	require.NoError(t, err)
	require.Equal(t, result.Revision, record)

	_, err = f.editor.Citation(ctx, admin, "space-2", ev)
	require.Equal(t, release.ErrorEvidenceNotFound, codeOf(t, err), "a record of another Space is not found")
	_, err = f.editor.Citation(ctx, release.Principal{TenantID: 8, Subject: "admin-8"}, spaceID, ev)
	require.Equal(t, release.ErrorEvidenceNotFound, codeOf(t, err), "a record of another tenant is not found")

	altered := ev
	altered.Quote = "另一原因"
	_, err = f.editor.Citation(ctx, admin, spaceID, altered)
	require.Equal(t, release.ErrorEvidenceMismatch, codeOf(t, err))
	altered = ev
	altered.Locator.RevisionRecordID = "rev-other"
	_, err = f.editor.Citation(ctx, admin, spaceID, altered)
	require.Equal(t, release.ErrorEvidenceMismatch, codeOf(t, err))
	altered = ev
	altered.FileSHA256 = strings.Repeat("0", 64)
	_, err = f.editor.Citation(ctx, admin, spaceID, altered)
	require.Equal(t, release.ErrorEvidenceMismatch, codeOf(t, err))
}
