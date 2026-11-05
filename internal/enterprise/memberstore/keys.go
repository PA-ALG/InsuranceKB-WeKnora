package memberstore

import (
	"database/sql/driver"

	"gorm.io/gorm"
)

// A packed binary key parameter keeps PostgreSQL plans independent of collection size.
// Table/column expressions below come only from this package, never request input.
func byDigests(db *gorm.DB, table string, scopeID int64, keys [][]byte) *gorm.DB {
	packed := make([]byte, 0, len(keys)*32)
	seen := make(map[string]bool, len(keys))
	count := 0
	for _, key := range keys {
		if !seen[string(key)] {
			seen[string(key)] = true
			packed = append(packed, key...)
			count++
		}
	}
	return db.Table(table+" AS c").Joins("JOIN (SELECT substring(?::bytea FROM i*32+1 FOR 32) AS digest\n FR"+
		"OM generate_series(0,?::int-1) AS positions(i)) AS wanted ON want"+
		"ed.digest=c.digest",
		binaryParameter(packed), count,
	).
		Where("c.scope_id = ?", scopeID).Select("c.*")
}

// GORM otherwise expands a byte slice immediately after '(' as an SQL argument list.
type binaryParameter []byte

func (value binaryParameter) Value() (driver.Value, error) { return []byte(value), nil }
