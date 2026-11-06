package releasestore

import (
	"os"
	"testing"
)

type storageScale struct {
	sizes                                 [2]int
	products, updatedPerRound, localStart int
	rootDeltaLimit                        int64
}

// Both tiers run the same properties and predicates. The complete tier remains a
// required pre-merge acceptance, while the normal PG job stays within its budget.
func storageAcceptanceScale(t *testing.T) storageScale {
	t.Helper()
	switch os.Getenv("ST1_SCALE") {
	case "":
		return storageScale{[2]int{375, 3750}, 30, 3, 64, 4248}
	case "1":
		return storageScale{[2]int{3600, 37500}, 300, 30, 500, 42192}
	default:
		t.Fatal("ST1_SCALE must be absent or exactly 1")
		return storageScale{}
	}
}
