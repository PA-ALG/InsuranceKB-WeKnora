package releasestore

// These tests require WEKNORA_TEST_POSTGRES_URL and use openSchema's fresh,
// disposable schema. A skip provides no PostgreSQL execution evidence.
import (
	"context"
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/confirm"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func confirmationSchema(t *testing.T) (*gorm.DB, *Store) {
	t.Helper()
	db := openSchema(t)
	require.NoError(t, db.Exec(migrationSQL(t, "000010_enterprise_confirmations.up.sql")).Error)
	spaces, err := ParseSpaces(`[
 {"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-1","wiki_kb_id":"wiki-1"},
 {"tenant_id":7,"space_id":"space-2","raw_kb_id":"raw-2","wiki_kb_id":"wiki-2"},
 {"tenant_id":8,"space_id":"space-1","raw_kb_id":"raw-3","wiki_kb_id":"wiki-3"}]`)
	require.NoError(t, err)
	return db, New(db, spaces)
}

var confirmationTime = time.Date(2026, 10, 25, 12, 0, 0, 0, time.UTC)

func confirmationItem(id, subject string) confirm.Item {
	return confirm.Item{
		ID: id, SpaceID: "space-1", Subject: subject, Revision: "1:rev", ContentDigest: "digest-" + subject,
		Title: "标题 " + subject, Detail: "说明\n第二行",
		Options:   []confirm.Option{{Key: "assign:p-1", Label: "归入 甲"}, {Key: "ignore", Label: "忽略"}},
		CreatedBy: "svc", CreatedAt: confirmationTime,
	}
}

func confirmationAnswer(id, itemID, key string) confirm.Answer {
	return confirm.Answer{
		ID: id, ItemID: itemID, OptionKey: key, Note: "依据", Answerer: "user:a", AnsweredAt: confirmationTime,
	}
}

func confirmationCode(t *testing.T, err error) string {
	t.Helper()
	var failure *release.Error
	require.True(t, errors.As(err, &failure), "want *release.Error, got %v", err)
	return failure.Code
}

func TestPostgresConfirmationKeepsTheFirstItemAndReturnsInputOrder(t *testing.T) {
	_, store := confirmationSchema(t)
	ctx := context.Background()
	input := []confirm.Item{confirmationItem("b", "k-b"), confirmationItem("a", "k-a")}
	got, err := store.InsertItems(ctx, 7, input)
	require.NoError(t, err)
	require.Equal(t, input, got)
	changed := input[1]
	changed.ID, changed.Title, changed.CreatedAt = "replacement", "changed", confirmationTime.Add(time.Hour)
	again, err := store.InsertItems(ctx, 7, []confirm.Item{changed, input[0]})
	require.NoError(t, err)
	require.Equal(t, []confirm.Item{input[1], input[0]}, again, "the same identity keeps the first row")
	listed, err := store.ListItems(ctx, 7, "space-1", confirm.Filter{})
	require.NoError(t, err)
	require.Len(t, listed, 2)
	require.Equal(t, []string{"a", "b"}, []string{listed[0].ID, listed[1].ID})
	newContent := confirmationItem("a-2", "k-a")
	newContent.ContentDigest = "digest-changed"
	next, err := store.InsertItems(ctx, 7, []confirm.Item{newContent})
	require.NoError(t, err)
	require.Equal(t, "a-2", next[0].ID, "new content is a new item")
}

func TestPostgresConfirmationConcurrentInsertsHaveOneWinner(t *testing.T) {
	_, store := confirmationSchema(t)
	ctx := context.Background()
	var wg sync.WaitGroup
	ids := make([]string, 8)
	errs := make([]error, 8)
	for n := range ids {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			got, err := store.InsertItems(ctx, 7, []confirm.Item{confirmationItem(fmt.Sprintf("id-%d", n), "k-1")})
			errs[n] = err
			if err == nil {
				ids[n] = got[0].ID
			}
		}(n)
	}
	wg.Wait()
	for n := range ids {
		require.NoError(t, errs[n])
		require.Equal(t, ids[0], ids[n])
	}
	listed, err := store.ListItems(ctx, 7, "space-1", confirm.Filter{})
	require.NoError(t, err)
	require.Len(t, listed, 1)
}

func TestPostgresConfirmationLatestAnswerAndClosures(t *testing.T) {
	_, store := confirmationSchema(t)
	ctx := context.Background()
	_, err := store.InsertItems(ctx, 7, []confirm.Item{confirmationItem("i-1", "k-1"), confirmationItem("i-2", "k-2")})
	require.NoError(t, err)
	require.NoError(t, store.AppendAnswer(ctx, 7, "space-1", confirmationAnswer("a-1", "i-1", "assign:p-1")))
	require.NoError(t, store.AppendAnswer(ctx, 7, "space-1", confirmationAnswer("a-0", "i-1", "ignore")))
	item, found, err := store.ItemByID(ctx, 7, "space-1", "i-1")
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "a-0", item.Answer.ID, "append order, not the identifier, defines the latest answer")

	stale := confirm.Closure{Reason: "applied", AnswerID: "a-1", ClosedBy: "svc", ClosedAt: confirmationTime}
	require.Equal(t, "ANSWER_STALE", confirmationCode(t, store.CloseItem(ctx, 7, "space-1", "i-1", stale)))
	applied := confirm.Closure{Reason: "applied", AnswerID: "a-0", ClosedBy: "svc", ClosedAt: confirmationTime}
	require.NoError(t, store.CloseItem(ctx, 7, "space-1", "i-1", applied))
	require.Equal(t, "CONFIRMATION_CLOSED", confirmationCode(t, store.CloseItem(ctx, 7, "space-1", "i-1", applied)))
	err = store.AppendAnswer(ctx, 7, "space-1", confirmationAnswer("a-late", "i-1", "ignore"))
	require.Equal(t, "CONFIRMATION_CLOSED", confirmationCode(t, err))

	open, err := store.ListItems(ctx, 7, "space-1", confirm.Filter{Status: "open"})
	require.NoError(t, err)
	require.Equal(t, []string{"i-2"}, []string{open[0].ID})
	closed, err := store.ListItems(ctx, 7, "space-1", confirm.Filter{Status: "closed"})
	require.NoError(t, err)
	require.Len(t, closed, 1)
	require.Equal(t, applied, *closed[0].Closure)
	require.Equal(t, "a-0", closed[0].Answer.ID)
}

func TestPostgresConfirmationAnswerAndClosureRaceOnOneSide(t *testing.T) {
	_, store := confirmationSchema(t)
	ctx := context.Background()
	for round := 0; round < 20; round++ {
		id := fmt.Sprintf("race-%d", round)
		_, err := store.InsertItems(ctx, 7, []confirm.Item{confirmationItem(id, "k-"+id)})
		require.NoError(t, err)
		var wg sync.WaitGroup
		var answerErr, closeErr error
		wg.Add(2)
		go func() {
			defer wg.Done()
			answerErr = store.AppendAnswer(ctx, 7, "space-1", confirmationAnswer("ans-"+id, id, "ignore"))
		}()
		go func() {
			defer wg.Done()
			closeErr = store.CloseItem(ctx, 7, "space-1", id,
				confirm.Closure{Reason: "obsolete", ClosedBy: "svc", ClosedAt: confirmationTime})
		}()
		wg.Wait()
		require.NoError(t, closeErr)
		item, _, err := store.ItemByID(ctx, 7, "space-1", id)
		require.NoError(t, err)
		require.NotNil(t, item.Closure)
		if answerErr != nil {
			require.Equal(t, "CONFIRMATION_CLOSED", confirmationCode(t, answerErr), "the answer came second")
			require.Nil(t, item.Answer)
		} else {
			require.NotNil(t, item.Answer, "the answer came first and is kept")
		}
	}
}

func TestPostgresConfirmationIsolatesTenantsAndSpaces(t *testing.T) {
	_, store := confirmationSchema(t)
	ctx := context.Background()
	_, err := store.InsertItems(ctx, 7, []confirm.Item{confirmationItem("i-1", "k-1")})
	require.NoError(t, err)
	for _, scope := range []struct {
		tenant uint64
		space  string
	}{{8, "space-1"}, {7, "space-2"}} {
		_, found, err := store.ItemByID(ctx, scope.tenant, scope.space, "i-1")
		require.NoError(t, err)
		require.False(t, found)
		listed, err := store.ListItems(ctx, scope.tenant, scope.space, confirm.Filter{})
		require.NoError(t, err)
		require.Empty(t, listed)
		err = store.AppendAnswer(ctx, scope.tenant, scope.space, confirmationAnswer("x", "i-1", "ignore"))
		require.Equal(t, "CONFIRMATION_NOT_FOUND", confirmationCode(t, err))
		err = store.CloseItem(ctx, scope.tenant, scope.space, "i-1",
			confirm.Closure{Reason: "obsolete", ClosedBy: "svc", ClosedAt: confirmationTime})
		require.Equal(t, "CONFIRMATION_NOT_FOUND", confirmationCode(t, err))
	}
	unknown := confirmationItem("u-1", "k-u")
	unknown.SpaceID = "space-9"
	_, err = store.InsertItems(ctx, 7, []confirm.Item{unknown})
	require.Error(t, err, "a Space outside the configuration is refused")
}

func TestPostgresConfirmationMigrationRoundTripAndConstraints(t *testing.T) {
	db, store := confirmationSchema(t)
	ctx := context.Background()
	_, err := store.InsertItems(ctx, 7, []confirm.Item{confirmationItem("i-1", "k-1")})
	require.NoError(t, err)
	err = db.Exec(`INSERT INTO enterprise_confirmation_closures
(confirmation_id, tenant_id, space_id, reason, answer_id, closed_by, closed_at)
VALUES ('i-1', 7, 'space-1', 'applied', NULL, 'svc', now())`).Error
	require.Error(t, err, "an applied closure names its answer")
	err = db.Exec(`INSERT INTO enterprise_confirmation_closures
(confirmation_id, tenant_id, space_id, reason, answer_id, closed_by, closed_at)
VALUES ('i-1', 7, 'space-1', 'done', NULL, 'svc', now())`).Error
	require.Error(t, err, "an unknown reason")
	require.NoError(t, db.Exec(migrationSQL(t, "000010_enterprise_confirmations.down.sql")).Error)
	var tables int64
	require.NoError(t, db.Raw(`SELECT count(*) FROM information_schema.tables
WHERE table_schema = current_schema() AND table_name LIKE 'enterprise_confirmation%'`).Scan(&tables).Error)
	require.Zero(t, tables)
	require.NoError(t, db.Exec(migrationSQL(t, "000010_enterprise_confirmations.up.sql")).Error)
}
