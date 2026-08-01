package logger

import (
	"bytes"
	"context"
	"errors"
	"log"
	"strings"
	"testing"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	gormlogger "gorm.io/gorm/logger"
)

const (
	syntheticAuthToken = "synthetic.jwt.auth-token-secret"
	syntheticHeader    = `{"Authorization":"Bearer synthetic-header-secret"}`
	syntheticVector    = "[0.125,-0.5,0.75]"
)

type syntheticSensitiveRow struct {
	ID        uint `gorm:"primaryKey"`
	Token     string
	Headers   string
	Embedding string
}

func TestRootCauseDefaultGORMLoggerInterpolatesSensitiveBindings(t *testing.T) {
	var output bytes.Buffer
	unsafeLogger := gormlogger.New(log.New(&output, "", 0), gormlogger.Config{
		SlowThreshold:        200 * time.Millisecond,
		LogLevel:             gormlogger.Error,
		ParameterizedQueries: false,
	})
	db, err := gorm.Open(sqlite.Open("file:055-root-cause?mode=memory&cache=shared"), &gorm.Config{
		Logger: unsafeLogger,
	})
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	if err := db.AutoMigrate(&syntheticSensitiveRow{}); err != nil {
		t.Fatalf("auto migrate: %v", err)
	}
	row := syntheticSensitiveRow{
		ID:        1,
		Token:     syntheticAuthToken,
		Headers:   syntheticHeader,
		Embedding: syntheticVector,
	}
	if err := db.Create(&row).Error; err != nil {
		t.Fatalf("seed row: %v", err)
	}
	if err := db.Create(&row).Error; err == nil {
		t.Fatal("duplicate insert unexpectedly succeeded")
	}

	got := output.String()
	for _, sensitive := range []string{syntheticAuthToken, "synthetic-header-secret", syntheticVector} {
		if !strings.Contains(got, sensitive) {
			t.Fatalf("root-cause reproduction did not expose %q in GORM error log: %s", sensitive, got)
		}
	}
}

func TestGORMLoggerRedactsBindingsOnFailedInsert(t *testing.T) {
	db, output := openSensitiveLogTestDB(t, 200*time.Millisecond)
	row := syntheticSensitiveRow{
		ID:        1,
		Token:     syntheticAuthToken,
		Headers:   syntheticHeader,
		Embedding: syntheticVector,
	}
	if err := db.Create(&row).Error; err != nil {
		t.Fatalf("seed row: %v", err)
	}
	output.Reset()

	insertErr := db.Create(&row).Error
	if insertErr == nil {
		t.Fatal("duplicate insert unexpectedly succeeded")
	}
	if !strings.Contains(insertErr.Error(), "UNIQUE constraint failed") {
		t.Fatalf("caller error was changed by log redaction: %v", insertErr)
	}

	assertParameterizedSensitiveLog(t, output.String(), "INSERT INTO")
}

func TestGORMLoggerRedactsSensitiveDatabaseErrorMessage(t *testing.T) {
	var output bytes.Buffer
	redactingLogger := newSensitiveGORMLogger(log.New(&output, "", 0), 200*time.Millisecond)
	providerErr := errors.New(
		"duplicate key contains " + syntheticAuthToken + " " + syntheticHeader + " " + syntheticVector,
	)

	redactingLogger.Trace(
		context.Background(),
		time.Now(),
		func() (string, int64) {
			return "INSERT INTO sensitive_rows(token, headers, embedding) VALUES (?, ?, ?)", -1
		},
		providerErr,
	)

	got := output.String()
	if !strings.Contains(got, "[database error details redacted]") {
		t.Fatalf("GORM log missing fixed error marker: %s", got)
	}
	for _, sensitive := range []string{syntheticAuthToken, "synthetic-header-secret", syntheticVector} {
		if strings.Contains(got, sensitive) {
			t.Errorf("GORM error log leaked %q: %s", sensitive, got)
		}
	}
}

func TestGORMLoggerRedactsSlowSQLWithoutChangingStoredValues(t *testing.T) {
	db, output := openSensitiveLogTestDB(t, time.Nanosecond)
	row := syntheticSensitiveRow{
		ID:        7,
		Token:     syntheticAuthToken,
		Headers:   syntheticHeader,
		Embedding: syntheticVector,
	}
	if err := db.Create(&row).Error; err != nil {
		t.Fatalf("create row: %v", err)
	}

	assertParameterizedSensitiveLog(t, output.String(), "SLOW SQL")

	var stored syntheticSensitiveRow
	if err := db.Session(&gorm.Session{Logger: gormlogger.Discard}).First(&stored, row.ID).Error; err != nil {
		t.Fatalf("read stored row: %v", err)
	}
	if stored.Token != row.Token || stored.Headers != row.Headers || stored.Embedding != row.Embedding {
		t.Fatalf("stored row changed by log redaction: got %#v, want %#v", stored, row)
	}
}

func openSensitiveLogTestDB(t *testing.T, slowThreshold time.Duration) (*gorm.DB, *bytes.Buffer) {
	t.Helper()
	var output bytes.Buffer
	redactingLogger := newSensitiveGORMLogger(log.New(&output, "", 0), slowThreshold)
	db, err := gorm.Open(sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"), &gorm.Config{
		Logger: redactingLogger,
	})
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	if err := db.AutoMigrate(&syntheticSensitiveRow{}); err != nil {
		t.Fatalf("auto migrate: %v", err)
	}
	output.Reset()
	return db, &output
}

func assertParameterizedSensitiveLog(t *testing.T, got string, expectedMarker string) {
	t.Helper()
	for _, want := range []string{expectedMarker, "synthetic_sensitive_rows", "?"} {
		if !strings.Contains(got, want) {
			t.Errorf("parameterized GORM log missing %q: %s", want, got)
		}
	}
	for _, sensitive := range []string{syntheticAuthToken, "synthetic-header-secret", syntheticVector} {
		if strings.Contains(got, sensitive) {
			t.Errorf("parameterized GORM log leaked %q: %s", sensitive, got)
		}
	}
}
