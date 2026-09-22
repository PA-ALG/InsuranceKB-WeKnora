package utils

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestDocumentStorageCapacityConfiguredReserve(t *testing.T) {
	t.Setenv("DOCUMENT_STORAGE_MIN_FREE_BYTES", "18446744073709551615")
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	if err := CheckDocumentStorageCapacity(1); !errors.Is(err, ErrDocumentStorageCapacity) {
		t.Fatalf("expected insufficient capacity, got %v", err)
	}
	t.Setenv("DOCUMENT_STORAGE_MIN_FREE_BYTES", "1")
	if err := CheckDocumentStorageCapacity(1); err != nil {
		t.Fatal(err)
	}
}

func TestDocumentStorageWaitRecoversAndHonorsCancellation(t *testing.T) {
	checks := 0
	err := waitForDocumentStorageCapacity(context.Background(), func() error {
		checks++
		if checks == 1 {
			return ErrDocumentStorageCapacity
		}
		return nil
	}, time.Millisecond)
	if err != nil || checks != 2 {
		t.Fatalf("recovery: checks=%d error=%v", checks, err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	err = waitForDocumentStorageCapacity(ctx, func() error { cancel(); return ErrDocumentStorageCapacity }, time.Hour)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("cancellation: %v", err)
	}
}

func TestDocumentStorageCapacityInvalidPolicyFailsClosed(t *testing.T) {
	t.Setenv("DOCUMENT_STORAGE_MIN_FREE_BYTES", "invalid")
	if err := CheckDocumentStorageCapacity(1); err == nil {
		t.Fatal("invalid capacity policy accepted")
	}
}

func TestDocumentStorageCapacityDisabledDoesNotRequireLocalMount(t *testing.T) {
	t.Setenv("DOCUMENT_STORAGE_MIN_FREE_BYTES", "")
	t.Setenv("LOCAL_STORAGE_BASE_DIR", "/not-a-configured-mount")
	if err := CheckDocumentStorageCapacity(1); err != nil {
		t.Fatal(err)
	}
}
