// S5b-3a acceptance: generic confirmation items — a submitter offers options as opaque text, a
// person picks one, answers only append, and the submitter closes an item once (Spec
// docs/design/slices/S5b-3a-通用待确认项.md §2.2, §3). Protected file: written by Claude.
//
// The service is exercised with an in-memory Store that keeps the Store contract (identity
// dedup, latest answer by append order, atomic closed and stale checks), so only the service's
// rules are covered here. PostgreSQL storage, the migration and the routes are the implementer's
// tests. RED until S5b-3a implements the package.
package confirm_test

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const space = "space-1"

type stored struct {
	tenant uint64
	item   confirm.Item
}

type storedAnswer struct {
	tenant uint64
	space  string
	answer confirm.Answer
}

type memStore struct {
	items    []stored
	answers  []storedAnswer
	closures map[string]confirm.Closure
}

func newStore() *memStore { return &memStore{closures: map[string]confirm.Closure{}} }

func (m *memStore) InsertItems(_ context.Context, tenantID uint64, in []confirm.Item) ([]confirm.Item, error) {
	out := make([]confirm.Item, 0, len(in))
	for _, it := range in {
		found := false
		for _, kept := range m.items {
			if kept.tenant == tenantID && kept.item.SpaceID == it.SpaceID && kept.item.Subject == it.Subject &&
				kept.item.Revision == it.Revision && kept.item.ContentDigest == it.ContentDigest {
				out, found = append(out, m.view(tenantID, kept.item)), true
				break
			}
		}
		if !found {
			m.items = append(m.items, stored{tenantID, it})
			out = append(out, it)
		}
	}
	return out, nil
}

func (m *memStore) latest(tenant uint64, itemID string) *confirm.Answer {
	var last *confirm.Answer
	for i := range m.answers {
		if m.answers[i].tenant == tenant && m.answers[i].answer.ItemID == itemID {
			a := m.answers[i].answer
			last = &a
		}
	}
	return last
}

func (m *memStore) view(tenant uint64, it confirm.Item) confirm.Item {
	it.Answer = m.latest(tenant, it.ID)
	if c, ok := m.closures[fmt.Sprintf("%d/%s", tenant, it.ID)]; ok {
		closure := c
		it.Closure = &closure
	}
	return it
}

func (m *memStore) ListItems(
	_ context.Context, tenantID uint64, spaceID string, f confirm.Filter,
) ([]confirm.Item, error) {
	var out []confirm.Item
	for _, s := range m.items {
		if s.tenant != tenantID || s.item.SpaceID != spaceID {
			continue
		}
		it := m.view(tenantID, s.item)
		if (f.Status == "open" && it.Closure != nil) || (f.Status == "closed" && it.Closure == nil) {
			continue
		}
		out = append(out, it)
	}
	return out, nil
}

func (m *memStore) ItemByID(_ context.Context, tenantID uint64, spaceID, id string) (confirm.Item, bool, error) {
	for _, s := range m.items {
		if s.tenant == tenantID && s.item.SpaceID == spaceID && s.item.ID == id {
			return m.view(tenantID, s.item), true, nil
		}
	}
	return confirm.Item{}, false, nil
}

func (m *memStore) AppendAnswer(_ context.Context, tenantID uint64, spaceID string, a confirm.Answer) error {
	if _, closed := m.closures[fmt.Sprintf("%d/%s", tenantID, a.ItemID)]; closed {
		return &release.Error{Code: "CONFIRMATION_CLOSED", Detail: "closed"}
	}
	m.answers = append(m.answers, storedAnswer{tenantID, spaceID, a})
	return nil
}

func (m *memStore) CloseItem(_ context.Context, tenantID uint64, _ string, itemID string, c confirm.Closure) error {
	k := fmt.Sprintf("%d/%s", tenantID, itemID)
	if _, closed := m.closures[k]; closed {
		return &release.Error{Code: "CONFIRMATION_CLOSED", Detail: "closed"}
	}
	if c.Reason == "applied" {
		if last := m.latest(tenantID, itemID); last == nil || last.ID != c.AnswerID {
			return &release.Error{Code: "ANSWER_STALE", Detail: "stale"}
		}
	}
	m.closures[k] = c
	return nil
}

func alice() release.Principal { return release.Principal{TenantID: 7, Subject: "user:alice"} }

func service(store *memStore) *confirm.Service {
	ids := 0
	return confirm.NewService(store,
		confirm.WithClock(func() time.Time { return time.Date(2026, 10, 25, 12, 0, 0, 0, time.UTC) }),
		confirm.WithIDs(func() string { ids++; return fmt.Sprintf("id-%d", ids) }),
	)
}

func codeOf(t *testing.T, err error) string {
	t.Helper()
	var failure *release.Error
	require.True(t, errors.As(err, &failure), "want *release.Error, got %v", err)
	return failure.Code
}

func input(subject string) confirm.ItemInput {
	return confirm.ItemInput{
		Subject: subject, Revision: "1:" + strings.Repeat("a", 64), Title: "材料 " + subject,
		Detail:  "说明",
		Options: []confirm.Option{{Key: "assign:p-1", Label: "归入 甲"}, {Key: "ignore", Label: "忽略"}},
	}
}

func submitOne(t *testing.T, s *confirm.Service, subject string) confirm.Item {
	t.Helper()
	got, err := s.Submit(context.Background(), alice(), space, []confirm.ItemInput{input(subject)})
	require.NoError(t, err)
	require.Len(t, got, 1)
	return got[0]
}

// --- Submit ----------------------------------------------------------------------------------

func TestSubmitStoresItemsAndIsIdempotentPerContent(t *testing.T) {
	store := newStore()
	s := service(store)
	first := submitOne(t, s, "k-1")
	require.Equal(t, space, first.SpaceID)
	require.Equal(t, "user:alice", first.CreatedBy)
	require.Len(t, first.ContentDigest, 64)
	again := submitOne(t, s, "k-1")
	require.Equal(t, first.ID, again.ID, "the same content is the same item")
	require.Len(t, store.items, 1)

	changed := input("k-1")
	changed.Options = []confirm.Option{changed.Options[1], changed.Options[0]}
	got, err := s.Submit(context.Background(), alice(), space, []confirm.ItemInput{changed})
	require.NoError(t, err)
	require.NotEqual(t, first.ContentDigest, got[0].ContentDigest, "option order is content")
	require.NotEqual(t, first.ID, got[0].ID)
}

func TestSubmitRejectsAnyInvalidItemAndWritesNothing(t *testing.T) {
	long := func(n int) string { return strings.Repeat("长", n) }
	cases := map[string]func(*confirm.ItemInput){
		"empty subject":     func(i *confirm.ItemInput) { i.Subject = "" },
		"bad subject":       func(i *confirm.ItemInput) { i.Subject = "-x" },
		"long subject":      func(i *confirm.ItemInput) { i.Subject = strings.Repeat("a", 129) },
		"empty revision":    func(i *confirm.ItemInput) { i.Revision = "" },
		"blank title":       func(i *confirm.ItemInput) { i.Title = "  " },
		"long title":        func(i *confirm.ItemInput) { i.Title = long(201) },
		"long detail":       func(i *confirm.ItemInput) { i.Detail = long(2001) },
		"control character": func(i *confirm.ItemInput) { i.Title = "a\x00b" },
		"no options":        func(i *confirm.ItemInput) { i.Options = nil },
		"bad option key":    func(i *confirm.ItemInput) { i.Options[0].Key = "Assign" },
		"blank label":       func(i *confirm.ItemInput) { i.Options[0].Label = " " },
		"long label":        func(i *confirm.ItemInput) { i.Options[0].Label = long(201) },
		"repeated key":      func(i *confirm.ItemInput) { i.Options[1].Key = i.Options[0].Key },
		"too many options": func(i *confirm.ItemInput) {
			for n := 0; n < 50; n++ {
				i.Options = append(i.Options, confirm.Option{Key: fmt.Sprintf("o%d", n), Label: "x"})
			}
		},
	}
	for name, breakIt := range cases {
		t.Run(name, func(t *testing.T) {
			store := newStore()
			bad := input("k-2")
			bad.Options = append([]confirm.Option(nil), bad.Options...)
			breakIt(&bad)
			batch := []confirm.ItemInput{input("k-1"), bad}
			_, err := service(store).Submit(context.Background(), alice(), space, batch)
			require.Equal(t, "CONFIRMATION_INVALID", codeOf(t, err))
			require.Empty(t, store.items)
		})
	}
	store := newStore()
	_, err := service(store).Submit(context.Background(), alice(), space, nil)
	require.Equal(t, "CONFIRMATION_INVALID", codeOf(t, err), "an empty batch")
	twice := []confirm.ItemInput{input("k-1"), input("k-1")}
	_, err = service(store).Submit(context.Background(), alice(), space, twice)
	require.Equal(t, "CONFIRMATION_INVALID", codeOf(t, err), "the same item twice in one batch")
	batch := make([]confirm.ItemInput, 201)
	for n := range batch {
		batch[n] = input(fmt.Sprintf("k-%d", n))
	}
	_, err = service(store).Submit(context.Background(), alice(), space, batch)
	require.Equal(t, "CONFIRMATION_INVALID", codeOf(t, err), "more than 200 items")
	require.Empty(t, store.items)
}

func TestNewlinesAreAllowedInDetail(t *testing.T) {
	item := input("k-1")
	item.Detail = "第一行\n第二行"
	_, err := service(newStore()).Submit(context.Background(), alice(), space, []confirm.ItemInput{item})
	require.NoError(t, err)
}

// --- List ------------------------------------------------------------------------------------

func TestListFiltersOpenAndClosedItems(t *testing.T) {
	store := newStore()
	s := service(store)
	a, b := submitOne(t, s, "k-a"), submitOne(t, s, "k-b")
	_, err := s.Close(context.Background(), alice(), space, a.ID, "obsolete", "")
	require.NoError(t, err)
	open, err := s.List(context.Background(), alice(), space, confirm.Filter{Status: "open"})
	require.NoError(t, err)
	require.Equal(t, []string{b.ID}, ids(open))
	closed, err := s.List(context.Background(), alice(), space, confirm.Filter{Status: "closed"})
	require.NoError(t, err)
	require.Equal(t, []string{a.ID}, ids(closed))
	require.NotNil(t, closed[0].Closure)
	all, err := s.List(context.Background(), alice(), space, confirm.Filter{})
	require.NoError(t, err)
	require.Equal(t, []string{a.ID, b.ID}, ids(all))
	_, err = s.List(context.Background(), alice(), space, confirm.Filter{Status: "answered"})
	require.Equal(t, "CONFIRMATION_INVALID", codeOf(t, err))
}

func ids(items []confirm.Item) []string {
	out := make([]string, 0, len(items))
	for _, it := range items {
		out = append(out, it.ID)
	}
	return out
}

// --- Answer ----------------------------------------------------------------------------------

func TestAnswersAppendAndTheLatestOneCounts(t *testing.T) {
	store := newStore()
	s := service(store)
	item := submitOne(t, s, "k-1")
	first, err := s.Answer(context.Background(), alice(), space, item.ID, "assign:p-1", "  依据条款  ")
	require.NoError(t, err)
	require.Equal(t, "依据条款", first.Note)
	require.Equal(t, "user:alice", first.Answerer)
	second, err := s.Answer(context.Background(), alice(), space, item.ID, "ignore", "")
	require.NoError(t, err)
	listed, err := s.List(context.Background(), alice(), space, confirm.Filter{Status: "open"})
	require.NoError(t, err)
	require.Equal(t, second.ID, listed[0].Answer.ID, "an answered item stays open until it is closed")
	require.Len(t, store.answers, 2)
}

func TestAnAnswerMustBeOneOfTheOptions(t *testing.T) {
	store := newStore()
	s := service(store)
	item := submitOne(t, s, "k-1")
	_, err := s.Answer(context.Background(), alice(), space, item.ID, "assign:p-2", "")
	require.Equal(t, "ANSWER_INVALID", codeOf(t, err))
	_, err = s.Answer(context.Background(), alice(), space, item.ID, "ignore", strings.Repeat("长", 1001))
	require.Equal(t, "ANSWER_INVALID", codeOf(t, err))
	require.Empty(t, store.answers)
}

func TestAClosedItemTakesNoAnswer(t *testing.T) {
	store := newStore()
	s := service(store)
	item := submitOne(t, s, "k-1")
	_, err := s.Close(context.Background(), alice(), space, item.ID, "obsolete", "")
	require.NoError(t, err)
	_, err = s.Answer(context.Background(), alice(), space, item.ID, "ignore", "")
	require.Equal(t, "CONFIRMATION_CLOSED", codeOf(t, err))
}

// --- Close -----------------------------------------------------------------------------------

func TestAnAppliedClosureNamesTheLatestAnswer(t *testing.T) {
	store := newStore()
	s := service(store)
	item := submitOne(t, s, "k-1")
	old, err := s.Answer(context.Background(), alice(), space, item.ID, "assign:p-1", "")
	require.NoError(t, err)
	latest, err := s.Answer(context.Background(), alice(), space, item.ID, "ignore", "")
	require.NoError(t, err)
	_, err = s.Close(context.Background(), alice(), space, item.ID, "applied", old.ID)
	require.Equal(t, "ANSWER_STALE", codeOf(t, err), "a person changed the answer meanwhile")
	closure, err := s.Close(context.Background(), alice(), space, item.ID, "applied", latest.ID)
	require.NoError(t, err)
	require.Equal(t, "applied", closure.Reason)
	require.Equal(t, latest.ID, closure.AnswerID)
	require.Equal(t, "user:alice", closure.ClosedBy)
	_, err = s.Close(context.Background(), alice(), space, item.ID, "applied", latest.ID)
	require.Equal(t, "CONFIRMATION_CLOSED", codeOf(t, err))
}

func TestClosureReasonsAndAnswersMustAgree(t *testing.T) {
	store := newStore()
	s := service(store)
	item := submitOne(t, s, "k-1")
	answer, err := s.Answer(context.Background(), alice(), space, item.ID, "ignore", "")
	require.NoError(t, err)
	for _, bad := range [][2]string{{"applied", ""}, {"obsolete", answer.ID}, {"done", ""}, {"", ""}} {
		_, err = s.Close(context.Background(), alice(), space, item.ID, bad[0], bad[1])
		require.Equal(t, "CONFIRMATION_INVALID", codeOf(t, err), bad)
	}
	require.Empty(t, store.closures)
}

// --- Isolation and availability ------------------------------------------------------------------

func TestEveryScopeIsIsolated(t *testing.T) {
	store := newStore()
	s := service(store)
	item := submitOne(t, s, "k-1")
	bob := release.Principal{TenantID: 8, Subject: "user:bob"}
	_, err := s.Answer(context.Background(), bob, space, item.ID, "ignore", "")
	require.Equal(t, "CONFIRMATION_NOT_FOUND", codeOf(t, err), "another tenant")
	_, err = s.Answer(context.Background(), alice(), "space-2", item.ID, "ignore", "")
	require.Equal(t, "CONFIRMATION_NOT_FOUND", codeOf(t, err), "another Space")
	_, err = s.Close(context.Background(), bob, space, item.ID, "obsolete", "")
	require.Equal(t, "CONFIRMATION_NOT_FOUND", codeOf(t, err))
	listed, err := s.List(context.Background(), bob, space, confirm.Filter{})
	require.NoError(t, err)
	require.Empty(t, listed)
	for _, p := range []release.Principal{{TenantID: 0, Subject: "user:x"}, {TenantID: 7, Subject: " "}} {
		_, err = s.List(context.Background(), p, space, confirm.Filter{})
		require.Equal(t, "RELEASE_ACCESS_DENIED", codeOf(t, err))
	}
	_, err = s.List(context.Background(), alice(), " ", confirm.Filter{})
	require.Equal(t, "RELEASE_ACCESS_DENIED", codeOf(t, err))
}

func TestAnUnconfiguredServiceIsUnavailable(t *testing.T) {
	var s *confirm.Service
	_, err := s.List(context.Background(), alice(), space, confirm.Filter{})
	require.Equal(t, "SERVICE_UNAVAILABLE", codeOf(t, err))
	_, err = s.Submit(context.Background(), alice(), space, []confirm.ItemInput{input("k-1")})
	require.Equal(t, "SERVICE_UNAVAILABLE", codeOf(t, err))
}
