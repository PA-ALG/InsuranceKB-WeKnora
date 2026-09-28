package database

import "github.com/Tencent/WeKnora/deploy/upstream"

// releasedOfficial75Checkpoint is the official migration head shipped with
// the product immediately before the fixed WeKnora v0.8.2 adoption target.
// Every clean ledger version from this checkpoint through the packaged head is
// a resumable point in the same immutable golang-migrate chain.
const releasedOfficial75Checkpoint int64 = 75

func enterpriseVersionKnownAtOfficialCheckpoint(
	officialVersion int64,
	enterpriseVersion int64,
) bool {
	if enterpriseVersion == 1 {
		return true
	}
	if enterpriseVersion <= 1 || enterpriseVersion > int64(packagedEnterpriseMigrationHead) {
		return false
	}
	return officialVersion >= releasedOfficial75Checkpoint &&
		officialVersion <= upstream.OfficialMigrationHead()
}
