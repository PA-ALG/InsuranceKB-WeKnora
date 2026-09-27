package router

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/hibiken/asynq"
)

func TestBackgroundTaskStorageWaitsBeforeParseAndAllowsMaintenance(t *testing.T) {
	t.Setenv("DOCUMENT_STORAGE_MIN_FREE_BYTES", "18446744073709551615")
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	called := false
	handler := backgroundTaskMiddleware()(asynq.HandlerFunc(func(context.Context, *asynq.Task) error { called = true; return nil }))
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	if err := handler.ProcessTask(ctx, asynq.NewTask(types.TypeDocumentProcess, nil)); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("expected wait cancellation, got %v", err)
	}
	if called {
		t.Fatal("parse handler started without capacity")
	}
	if err := handler.ProcessTask(context.Background(), asynq.NewTask("maintenance-probe", nil)); err != nil {
		t.Fatal(err)
	}
	if !called {
		t.Fatal("maintenance should remain available to release space")
	}
}
