package releasestore

import (
	"context"
	"fmt"
	"os"
	"runtime"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

// The full tier measures the public Publisher transaction, not just memo hashing.
// No machine-specific duration threshold is asserted; production read budgets are separate.
func TestPostgresMemoActivationMeasurement(t *testing.T) {
	n := 375
	switch os.Getenv("ST1_MEMO_MEASURE") {
	case "":
	case "37500":
		n = 37500
	default:
		t.Fatal("invalid measurement tier")
	}
	db := memberStorageDB(t)
	referenceFixtureScope(t, db)
	s := New(db, testSpaces(t))
	members := make([]release.Member, n)
	for i := range members {
		members[i] = paddedStorageMember(t, i, 0)
	}
	storagePublish(t, s, "memo-measure-initial", members)
	for i := 0; i < 3; i++ {
		w := activation(t, s, fmt.Sprintf("memo-measure-%d", i))
		w.Members = members
		w.BundleDigest = digestOf([]byte(w.Nonce))
		runtime.GC()
		started := time.Now()
		got, err := s.Activate(context.Background(), w)
		elapsed := time.Since(started)
		require.NoError(t, err)
		require.Len(t, got.Members, n)
		t.Logf("PUBLIC_ACTIVATION n=%d sample=%d elapsed_ns=%d", n, i, elapsed.Nanoseconds())
	}
}
