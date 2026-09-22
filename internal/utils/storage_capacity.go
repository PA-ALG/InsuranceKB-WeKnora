package utils

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/shirou/gopsutil/v3/disk"
)

var ErrDocumentStorageCapacity = errors.New("document storage capacity unavailable")

// The reserve belongs to the deployment, not to a product/document count limit.
// An unset reserve preserves existing deployments without a local storage mount.
func CheckDocumentStorageCapacity(incomingBytes int64) error {
	raw := strings.TrimSpace(os.Getenv("DOCUMENT_STORAGE_MIN_FREE_BYTES"))
	if raw == "" {
		return nil
	}
	reserve, err := strconv.ParseUint(raw, 10, 64)
	if err != nil || reserve == 0 || incomingBytes < 0 {
		return fmt.Errorf("invalid document storage reserve configuration")
	}
	base := strings.TrimSpace(os.Getenv("LOCAL_STORAGE_BASE_DIR"))
	if base == "" {
		base = "/data/files"
	}
	for _, path := range []string{base, os.TempDir()} {
		usage, err := disk.Usage(path)
		if err != nil {
			return fmt.Errorf("%w: cannot inspect storage", ErrDocumentStorageCapacity)
		}
		// Subtraction avoids overflow for a large reserve or incoming upload.
		if usage.Free < reserve || uint64(incomingBytes) > usage.Free-reserve {
			return fmt.Errorf("%w: free=%d reserve=%d incoming=%d", ErrDocumentStorageCapacity, usage.Free, reserve, incomingBytes)
		}
	}
	return nil
}

// A claimed parse waits before executing its handler. This does not restart an
// in-flight provider request or consume a retry while waiting for local space.
func WaitForDocumentStorageCapacity(ctx context.Context) error {
	return waitForDocumentStorageCapacity(ctx, func() error { return CheckDocumentStorageCapacity(0) }, 30*time.Second)
}

func waitForDocumentStorageCapacity(ctx context.Context, check func() error, interval time.Duration) error {
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		err := check()
		if err == nil || !errors.Is(err, ErrDocumentStorageCapacity) {
			return err
		}
		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
}
