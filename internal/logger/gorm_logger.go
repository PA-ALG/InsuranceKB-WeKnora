package logger

import (
	"context"
	"log"
	"os"
	"time"

	gormlogger "gorm.io/gorm/logger"
)

const defaultGORMSlowThreshold = 200 * time.Millisecond

// NewSensitiveGORMLogger preserves GORM's default warning/error visibility
// while preventing bound values from being interpolated into SQL logs.
func NewSensitiveGORMLogger() gormlogger.Interface {
	return newSensitiveGORMLogger(
		log.New(os.Stdout, "\r\n", log.LstdFlags),
		defaultGORMSlowThreshold,
	)
}

func newSensitiveGORMLogger(writer gormlogger.Writer, slowThreshold time.Duration) gormlogger.Interface {
	delegate := gormlogger.New(writer, gormlogger.Config{
		SlowThreshold:             slowThreshold,
		LogLevel:                  gormlogger.Warn,
		IgnoreRecordNotFoundError: false,
		Colorful:                  true,
		ParameterizedQueries:      true,
	})
	return &sensitiveGORMLogger{delegate: delegate}
}

type sensitiveGORMLogger struct {
	delegate gormlogger.Interface
}

func (l *sensitiveGORMLogger) LogMode(level gormlogger.LogLevel) gormlogger.Interface {
	return &sensitiveGORMLogger{delegate: l.delegate.LogMode(level)}
}

func (l *sensitiveGORMLogger) Info(ctx context.Context, msg string, data ...interface{}) {
	l.delegate.Info(ctx, msg, data...)
}

func (l *sensitiveGORMLogger) Warn(ctx context.Context, msg string, data ...interface{}) {
	l.delegate.Warn(ctx, msg, data...)
}

func (l *sensitiveGORMLogger) Error(ctx context.Context, msg string, data ...interface{}) {
	l.delegate.Error(ctx, msg, data...)
}

func (l *sensitiveGORMLogger) Trace(
	ctx context.Context,
	begin time.Time,
	fc func() (sql string, rowsAffected int64),
	err error,
) {
	if err != nil {
		err = redactedGORMError{cause: err}
	}
	l.delegate.Trace(ctx, begin, fc, err)
}

func (l *sensitiveGORMLogger) ParamsFilter(
	_ context.Context,
	sql string,
	_ ...interface{},
) (string, []interface{}) {
	return sql, nil
}

type redactedGORMError struct {
	cause error
}

func (e redactedGORMError) Error() string {
	return "[database error details redacted]"
}

func (e redactedGORMError) Unwrap() error {
	return e.cause
}
