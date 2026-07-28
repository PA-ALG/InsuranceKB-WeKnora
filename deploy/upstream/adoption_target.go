package upstream

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed weknora-adoption-target.json
var adoptionTargetJSON []byte

type AdoptionTarget struct {
	SchemaVersion         int   `json:"schema_version"`
	OfficialMigrationHead int64 `json:"official_migration_head"`
}

var adoptionTarget = mustParseAdoptionTarget()

func Must() AdoptionTarget {
	return adoptionTarget
}

func OfficialMigrationHead() int64 {
	return adoptionTarget.OfficialMigrationHead
}

func mustParseAdoptionTarget() AdoptionTarget {
	var target AdoptionTarget
	if err := json.Unmarshal(adoptionTargetJSON, &target); err != nil {
		panic(fmt.Sprintf("parse embedded WeKnora adoption target: %v", err))
	}
	if target.SchemaVersion != 1 {
		panic(fmt.Sprintf(
			"unsupported WeKnora adoption target schema_version %d",
			target.SchemaVersion,
		))
	}
	if target.OfficialMigrationHead <= 0 {
		panic("WeKnora adoption target official_migration_head must be positive")
	}
	return target
}
