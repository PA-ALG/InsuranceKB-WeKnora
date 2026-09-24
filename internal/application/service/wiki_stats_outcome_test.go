package service

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"testing"
)

type wikiOutcomeStatsRepo struct{ interfaces.WikiPageRepository }

func (wikiOutcomeStatsRepo) CountByType(context.Context, string) (map[string]int64, error) {
	return map[string]int64{}, nil
}
func (wikiOutcomeStatsRepo) CountOrphans(context.Context, string) (int64, error) { return 0, nil }
func (wikiOutcomeStatsRepo) ListAll(context.Context, string) ([]*types.WikiPage, error) {
	return nil, nil
}
func (wikiOutcomeStatsRepo) List(context.Context, *types.WikiPageListRequest) ([]*types.WikiPage, int64, error) {
	return nil, 0, nil
}
func (wikiOutcomeStatsRepo) ListIssues(context.Context, string, string, string) ([]*types.WikiPageIssue, error) {
	return nil, nil
}

type wikiOutcomeCounter struct {
	interfaces.TaskPendingOpsRepository
	interfaces.TaskPendingOpsExecutionStore
	err error
}

func (*wikiOutcomeCounter) PendingCount(context.Context, string, string, string) (int64, error) {
	return 0, nil
}
func (c *wikiOutcomeCounter) FailedOperationCount(_ context.Context, tenant uint64, taskType, scope, kb string) (int64, error) {
	if tenant != 7 || taskType != wikiTaskType || scope != wikiTaskScope || kb != "kb" {
		return 0, errors.New("wrong failure count scope")
	}
	return 3, c.err
}
func TestWikiStatsSeparatesFailedGeneration(t *testing.T) {
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
	counter := &wikiOutcomeCounter{}
	svc := &wikiPageService{repo: wikiOutcomeStatsRepo{}, taskPendingRepo: counter}
	stats, err := svc.GetStats(ctx, "kb")
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(stats)
	var fields map[string]interface{}
	_ = json.Unmarshal(raw, &fields)
	if fields["failed_operations"] != float64(3) {
		t.Fatalf("completed parse/pending=0 must not hide failed Wiki: %s", raw)
	}
	counter.err = errors.New("failure status unavailable")
	if _, err := svc.GetStats(ctx, "kb"); err == nil {
		t.Fatal("failed status read cannot be reported as zero/healthy")
	}
}
