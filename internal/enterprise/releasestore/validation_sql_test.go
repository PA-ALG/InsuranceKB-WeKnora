package releasestore

import "github.com/DATA-DOG/go-sqlmock"

func expectValidationStart(mock sqlmock.Sqlmock) {
	mock.ExpectExec(`WITH admission AS MATERIALIZED`).
		WithArgs(sqlmock.AnyArg(), uint64(7), "space-1", "raw-1", "wiki-1", sqlmock.AnyArg()).
		WillReturnResult(sqlmock.NewResult(0, 1))
}

func expectValidationFinish(mock sqlmock.Sqlmock, kind string) {
	if kind == "" {
		mock.ExpectExec(`DELETE FROM enterprise_member_validation_pending`).
			WithArgs(uint64(7), "space-1", "raw-1", "wiki-1", sqlmock.AnyArg()).
			WillReturnResult(sqlmock.NewResult(0, 1))
	} else {
		mock.ExpectExec(`WITH recorded AS`).
			WithArgs(kind, uint64(7), "space-1", "raw-1", "wiki-1", sqlmock.AnyArg()).
			WillReturnResult(sqlmock.NewResult(0, 1))
	}
}
