package database

import (
	"context"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/stretchr/testify/require"
)

func TestInspectOfficialMigrationLedger(t *testing.T) {
	tests := []struct {
		name      string
		exists    bool
		exact     bool
		rows      *sqlmock.Rows
		wantExist bool
		wantVer   int64
		wantDirty bool
		wantErr   string
	}{
		{
			name:      "absent",
			wantExist: false,
		},
		{
			name:      "single clean row",
			exists:    true,
			exact:     true,
			rows:      sqlmock.NewRows([]string{"count", "version", "dirty"}).AddRow(1, 66, false),
			wantExist: true,
			wantVer:   66,
		},
		{
			name:      "empty constructor residue",
			exists:    true,
			exact:     true,
			rows:      sqlmock.NewRows([]string{"count", "version", "dirty"}).AddRow(0, 0, false),
			wantExist: true,
			wantVer:   -1,
		},
		{
			name:      "single dirty row",
			exists:    true,
			exact:     true,
			rows:      sqlmock.NewRows([]string{"count", "version", "dirty"}).AddRow(1, 66, true),
			wantExist: true,
			wantVer:   66,
			wantDirty: true,
		},
		{
			name:    "multiple rows",
			exists:  true,
			exact:   true,
			rows:    sqlmock.NewRows([]string{"count", "version", "dirty"}).AddRow(2, 66, false),
			wantErr: "exactly one row",
		},
		{
			name:    "bad structure",
			exists:  true,
			wantErr: "unexpected structure",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newBridgeSQLMock(t)
			mock.ExpectQuery(officialMigrationLedgerShapeSQL).
				WillReturnRows(sqlmock.NewRows([]string{"exists", "exact"}).AddRow(tt.exists, tt.exact))
			if tt.rows != nil {
				mock.ExpectQuery(officialMigrationLedgerStateSQL).WillReturnRows(tt.rows)
			}

			exists, version, dirty, err := inspectOfficialMigrationLedger(context.Background(), db)

			if tt.wantErr != "" {
				require.ErrorContains(t, err, tt.wantErr)
			} else {
				require.NoError(t, err)
				require.Equal(t, tt.wantExist, exists)
				require.Equal(t, tt.wantVer, version)
				require.Equal(t, tt.wantDirty, dirty)
			}
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestInspectEnterpriseMigrationLedgerUsesIndependentTable(t *testing.T) {
	db, mock := newBridgeSQLMock(t)
	mock.ExpectQuery(enterpriseMigrationLedgerShapeSQL).
		WillReturnRows(sqlmock.NewRows([]string{"exists", "exact"}).AddRow(true, true))
	mock.ExpectQuery(enterpriseMigrationLedgerStateSQL).
		WillReturnRows(sqlmock.NewRows([]string{"count", "version", "dirty"}).AddRow(1, 1, false))

	exists, version, dirty, err := inspectEnterpriseMigrationLedger(context.Background(), db)

	require.NoError(t, err)
	require.True(t, exists)
	require.EqualValues(t, 1, version)
	require.False(t, dirty)
	require.NoError(t, mock.ExpectationsWereMet())
}

func TestMigrationLedgerShapeSQLPinsExactConstraintInventory(t *testing.T) {
	for _, query := range []string{
		officialMigrationLedgerShapeSQL,
		enterpriseMigrationLedgerShapeSQL,
	} {
		require.Contains(t, query, "count(*) = 1")
		require.Contains(
			t,
			query,
			"count(*) FILTER (WHERE c.contype = 'p' AND c.convalidated AND NOT c.condeferrable)",
		)
	}
}

func TestInspectSpanNameFingerprint(t *testing.T) {
	tests := []struct {
		name      string
		table     bool
		column    bool
		dataType  string
		length    int64
		notNull   bool
		ordinary  bool
		noDefault bool
		wantState spanNameFingerprint
	}{
		{name: "absent", wantState: spanNameAbsent},
		{
			name: "legacy64", table: true, column: true,
			dataType: "character varying", length: 64, notNull: true,
			ordinary: true, noDefault: true, wantState: spanNameLegacy64,
		},
		{
			name: "expanded255", table: true, column: true,
			dataType: "character varying", length: 255, notNull: true,
			ordinary: true, noDefault: true, wantState: spanNameExpanded255,
		},
		{
			name: "unknown width", table: true, column: true,
			dataType: "character varying", length: 128, notNull: true,
			ordinary: true, noDefault: true, wantState: spanNameUnknown,
		},
		{
			name: "table without column", table: true,
			wantState: spanNameUnknown,
		},
		{
			name: "wrong type", table: true, column: true,
			dataType: "text", length: -1, notNull: true,
			ordinary: true, noDefault: true, wantState: spanNameUnknown,
		},
		{
			name: "nullable varchar64 is unknown", table: true, column: true,
			dataType: "character varying", length: 64,
			ordinary: true, noDefault: true, wantState: spanNameUnknown,
		},
		{
			name: "view is unknown", table: true, column: true,
			dataType: "character varying", length: 64, notNull: true,
			noDefault: true, wantState: spanNameUnknown,
		},
		{
			name: "default is unknown", table: true, column: true,
			dataType: "character varying", length: 64, notNull: true,
			ordinary: true, wantState: spanNameUnknown,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newBridgeSQLMock(t)
			mock.ExpectQuery(spanNameFingerprintSQL).WillReturnRows(
				sqlmock.NewRows([]string{
					"table_exists", "ordinary", "column_exists", "data_type",
					"length", "not_null", "no_default",
				}).AddRow(
					tt.table, tt.ordinary, tt.column, tt.dataType,
					tt.length, tt.notNull, tt.noDefault,
				),
			)

			got, err := inspectSpanNameFingerprint(context.Background(), db)

			require.NoError(t, err)
			require.Equal(t, tt.wantState, got)
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestInspectLegacyW1Fingerprint(t *testing.T) {
	tests := []struct {
		name         string
		presentCount int64
		exactCount   int64
		want         legacyW1Fingerprint
	}{
		{name: "all absent", want: legacyW1Absent},
		{name: "all exact", presentCount: 6, exactCount: 6, want: legacyW1Exact},
		{name: "partial presence", presentCount: 5, exactCount: 5, want: legacyW1Partial},
		{name: "all present but definition drift", presentCount: 6, exactCount: 5, want: legacyW1Partial},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newBridgeSQLMock(t)
			mock.ExpectQuery(legacyW1FingerprintSQL).WillReturnRows(
				sqlmock.NewRows([]string{"present_count", "exact_count"}).
					AddRow(tt.presentCount, tt.exactCount),
			)

			got, err := inspectLegacyW1Fingerprint(context.Background(), db)

			require.NoError(t, err)
			require.Equal(t, tt.want, got)
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestLegacyW1FingerprintSQLPinsEveryLegacyObjectDefinition(t *testing.T) {
	for _, fragment := range []string{
		"current_parse_attempt", "file_sha256", "parse_attempt",
		"knowledge_revisions", "knowledge_id", "parser_identity",
		"manifest_algorithm", "manifest_digest", "chunk_count", "completed_at",
		"PRIMARY KEY", "FOREIGN KEY", "ON DELETE CASCADE",
		"parse_attempt > 0", "^[0-9a-f]{64}$", "chunk_count >= 0",
		"idx_chunks_live_text_revision_ordinal", "knowledge_id, parse_attempt, chunk_index",
		"deleted_at IS NULL", "chunk_type", "idx_knowledge_revisions_completed",
		"knowledge_id, completed_at DESC",
	} {
		require.Contains(t, legacyW1FingerprintSQL, fragment)
	}
}

func TestFixedCatalogFingerprintSQLPinsStructuralExactness(t *testing.T) {
	for _, query := range []string{
		officialMigrationLedgerShapeSQL,
		enterpriseMigrationLedgerShapeSQL,
	} {
		require.Contains(t, query, "relkind = 'r'")
	}
	for _, fragment := range []string{
		"relkind = 'r'", "c.convalidated", "NOT c.condeferrable",
		"am.amname = 'btree'", "i.indislive", "i.indnkeyatts",
		"i.indnatts", "WITH ORDINALITY",
	} {
		require.Contains(t, legacyW1FingerprintSQL, fragment)
	}
	for _, fragment := range []string{"relkind = 'r'", "column_default IS NULL"} {
		require.Contains(t, spanNameFingerprintSQL, fragment)
	}
}

func TestLegacyW1FingerprintSQLPinsExactRevisionConstraintInventory(t *testing.T) {
	for _, fragment := range []string{
		"count(*) = 6",
		"count(*) FILTER (WHERE c.contype = 'p') = 1",
		"count(*) FILTER (WHERE c.contype = 'f') = 1",
		"count(*) FILTER (WHERE c.contype = 'c') = 4",
	} {
		require.Contains(t, legacyW1FingerprintSQL, fragment)
	}
}

func TestInspectDependencyAnchorFingerprint(t *testing.T) {
	tests := []struct {
		name         string
		presentCount int64
		exactCount   int64
		want         dependencyAnchorFingerprint
	}{
		{name: "both tables absent", want: dependencyAnchorsAbsent},
		{name: "both exact", presentCount: 2, exactCount: 2, want: dependencyAnchorsExact},
		{name: "half-created official schema", presentCount: 1, exactCount: 1, want: dependencyAnchorsPartial},
		{name: "definition drift", presentCount: 2, exactCount: 1, want: dependencyAnchorsPartial},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			db, mock := newBridgeSQLMock(t)
			mock.ExpectQuery(dependencyAnchorFingerprintSQL).WillReturnRows(
				sqlmock.NewRows([]string{"present_count", "exact_count"}).
					AddRow(tt.presentCount, tt.exactCount),
			)

			got, err := inspectDependencyAnchorFingerprint(context.Background(), db)

			require.NoError(t, err)
			require.Equal(t, tt.want, got)
			require.NoError(t, mock.ExpectationsWereMet())
		})
	}
}

func TestDependencyAnchorFingerprintSQLPinsOnlyW1Dependencies(t *testing.T) {
	for _, fragment := range []string{
		"knowledges", "relkind = 'r'", "id", "character varying", "36",
		"PRIMARY KEY (id)",
		"chunks", "knowledge_id", "chunk_index", "integer",
		"chunk_type", "20", "DEFAULT 'text'", "deleted_at",
		"timestamp with time zone",
	} {
		require.Contains(t, dependencyAnchorFingerprintSQL, fragment)
	}
}
