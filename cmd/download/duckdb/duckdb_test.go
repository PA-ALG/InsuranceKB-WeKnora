package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
)

const lockedDependencyPath = "../../../deploy/local-build/app-external-dependencies.v1.json"

type extensionLockFixture struct {
	SchemaVersion int `json:"schema_version"`
	Platform      struct {
		OS     string `json:"os"`
		Arch   string `json:"arch"`
		DuckDB string `json:"duckdb"`
	} `json:"platform"`
	Downloads struct {
		DuckDB struct {
			Version    string `json:"version"`
			Extensions map[string]struct {
				Platform string `json:"platform"`
				Origin   string `json:"origin"`
				SHA256   string `json:"sha256"`
			} `json:"extensions"`
		} `json:"duckdb"`
	} `json:"downloads"`
}

type expectedExtension struct {
	Name     string
	Version  string
	GOOS     string
	GOARCH   string
	Platform string
	Origin   string
	SHA256   string
}

func duckDBVersionFromGoMod(t *testing.T) string {
	t.Helper()
	content, err := os.ReadFile("../../../go.mod")
	if err != nil {
		t.Fatalf("read go.mod: %v", err)
	}
	match := regexp.MustCompile(`github\.com/duckdb/duckdb-go/v2\s+v2\.([0-9])([0-9]{2})([0-9]{2})\.[0-9]+`).FindSubmatch(content)
	if match == nil {
		t.Fatal("go.mod does not pin a decodable duckdb-go/v2 release")
	}
	parts := make([]int, 3)
	for index, value := range match[1:] {
		parts[index], err = strconv.Atoi(string(value))
		if err != nil {
			t.Fatalf("decode DuckDB binding version: %v", err)
		}
	}
	return fmt.Sprintf("v%d.%d.%d", parts[0], parts[1], parts[2])
}

func loadExtensionLockFixture(t *testing.T) (extensionLockFixture, []byte) {
	t.Helper()
	raw, err := os.ReadFile(filepath.Clean(lockedDependencyPath))
	if err != nil {
		t.Fatalf("read versioned dependency lock: %v", err)
	}
	var fixture extensionLockFixture
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatalf("decode versioned dependency lock: %v", err)
	}
	if fixture.SchemaVersion != 1 {
		t.Fatalf("dependency lock schema_version = %d, want 1", fixture.SchemaVersion)
	}
	if fixture.Platform.OS == "" || fixture.Platform.Arch == "" || fixture.Platform.DuckDB == "" {
		t.Fatal("dependency lock has an incomplete target platform")
	}
	if fixture.Downloads.DuckDB.Version != duckDBVersionFromGoMod(t) {
		t.Fatalf("DuckDB lock version %q does not match go.mod", fixture.Downloads.DuckDB.Version)
	}
	if len(fixture.Downloads.DuckDB.Extensions) != 2 {
		t.Fatalf("locked extension count = %d, want exactly spatial and excel", len(fixture.Downloads.DuckDB.Extensions))
	}
	for _, name := range []string{"spatial", "excel"} {
		extension, ok := fixture.Downloads.DuckDB.Extensions[name]
		if !ok {
			t.Fatalf("versioned lock is missing %q", name)
		}
		if extension.Platform != fixture.Platform.DuckDB {
			t.Fatalf("%s extension platform %q does not match lock target %q", name, extension.Platform, fixture.Platform.DuckDB)
		}
		origin, err := url.Parse(extension.Origin)
		if err != nil || origin.String() == "" {
			t.Fatalf("parse %s locked origin %q: %v", name, extension.Origin, err)
		}
		if origin.User != nil || origin.RawQuery != "" || origin.Fragment != "" {
			t.Fatalf("%s origin contains mutable/credential material: %q", name, extension.Origin)
		}
		for _, value := range []string{fixture.Downloads.DuckDB.Version, fixture.Platform.DuckDB, name} {
			if !strings.Contains(origin.Path, value) {
				t.Fatalf("%s origin %q does not bind lock value %q", name, extension.Origin, value)
			}
		}
		if extension.SHA256 != strings.ToLower(extension.SHA256) {
			t.Fatalf("%s content SHA-256 is not lowercase", name)
		}
		decoded, err := hex.DecodeString(extension.SHA256)
		if err != nil || len(decoded) != sha256.Size {
			t.Fatalf("%s content SHA-256 is invalid: %v", name, err)
		}
		if extension.SHA256 == strings.Repeat("0", sha256.Size*2) {
			t.Fatalf("%s content SHA-256 is unresolved", name)
		}
	}
	return fixture, raw
}

func expectedExtensions(fixture extensionLockFixture) map[string]expectedExtension {
	expected := make(map[string]expectedExtension, len(fixture.Downloads.DuckDB.Extensions))
	for name, extension := range fixture.Downloads.DuckDB.Extensions {
		expected[name] = expectedExtension{
			Name:     name,
			Version:  fixture.Downloads.DuckDB.Version,
			GOOS:     fixture.Platform.OS,
			GOARCH:   fixture.Platform.Arch,
			Platform: extension.Platform,
			Origin:   extension.Origin,
			SHA256:   extension.SHA256,
		}
	}
	return expected
}

func writeSyntheticDigestLock(t *testing.T, raw []byte, payloads map[string][]byte) string {
	t.Helper()
	var document map[string]any
	if err := json.Unmarshal(raw, &document); err != nil {
		t.Fatalf("decode lock for digest fixture: %v", err)
	}
	downloads := document["downloads"].(map[string]any)
	duckdb := downloads["duckdb"].(map[string]any)
	extensions := duckdb["extensions"].(map[string]any)
	for name, payload := range payloads {
		extension := extensions[name].(map[string]any)
		digest := sha256.Sum256(payload)
		extension["sha256"] = hex.EncodeToString(digest[:])
	}
	path := filepath.Join(t.TempDir(), "app-external-dependencies.v1.json")
	encoded, err := json.Marshal(document)
	if err != nil {
		t.Fatalf("encode digest fixture lock: %v", err)
	}
	if err := os.WriteFile(path, encoded, 0o600); err != nil {
		t.Fatalf("write digest fixture lock: %v", err)
	}
	return path
}

func fixturePayloads(expected map[string]expectedExtension) map[string][]byte {
	payloads := make(map[string][]byte, len(expected))
	for name := range expected {
		payloads[name] = []byte("verified DuckDB extension fixture: " + name)
	}
	return payloads
}

func sortedStrings(values []string) []string {
	result := append([]string(nil), values...)
	sort.Strings(result)
	return result
}

func TestLockedExtensionOrigin(t *testing.T) {
	fixture, raw := loadExtensionLockFixture(t)
	expected := expectedExtensions(fixture)
	payloads := fixturePayloads(expected)
	lockPath := writeSyntheticDigestLock(t, raw, payloads)
	fetchedOrigins := make([]string, 0, len(expected))
	installed := make(map[string]lockedExtension)

	err := downloadExtensions(
		context.Background(),
		lockPath,
		fixture.Platform.OS,
		fixture.Platform.Arch,
		func(_ context.Context, origin string) ([]byte, error) {
			fetchedOrigins = append(fetchedOrigins, origin)
			for name, extension := range expected {
				if extension.Origin == origin {
					return append([]byte(nil), payloads[name]...), nil
				}
			}
			return nil, fmt.Errorf("origin was not loaded from the versioned lock: %q", origin)
		},
		func(_ context.Context, extension lockedExtension, verified []byte) error {
			installed[extension.Name] = extension
			if !reflect.DeepEqual(verified, payloads[extension.Name]) {
				return fmt.Errorf("%s installer did not receive verified content", extension.Name)
			}
			return nil
		},
	)
	if err != nil {
		t.Fatalf("download locked extensions: %v", err)
	}

	wantOrigins := make([]string, 0, len(expected))
	for name, want := range expected {
		wantOrigins = append(wantOrigins, want.Origin)
		got, ok := installed[name]
		if !ok {
			t.Fatalf("locked extension %q was not installed", name)
		}
		if got.Name != want.Name || got.Version != want.Version || got.Origin != want.Origin || got.Platform != want.Platform {
			t.Fatalf("installed %s lock = %+v, want origin/version/platform from lock %+v", name, got, want)
		}
	}
	if !reflect.DeepEqual(sortedStrings(fetchedOrigins), sortedStrings(wantOrigins)) {
		t.Fatalf("fetch origins = %q, want exact versioned-lock origins %q", fetchedOrigins, wantOrigins)
	}
}

func TestLockedExtensionPlatform(t *testing.T) {
	fixture, raw := loadExtensionLockFixture(t)
	expected := expectedExtensions(fixture)
	payloads := fixturePayloads(expected)
	lockPath := writeSyntheticDigestLock(t, raw, payloads)
	installed := make(map[string]lockedExtension)

	err := downloadExtensions(
		context.Background(), lockPath, fixture.Platform.OS, fixture.Platform.Arch,
		func(_ context.Context, origin string) ([]byte, error) {
			for name, extension := range expected {
				if extension.Origin == origin {
					return append([]byte(nil), payloads[name]...), nil
				}
			}
			return nil, fmt.Errorf("unknown locked origin %q", origin)
		},
		func(_ context.Context, extension lockedExtension, _ []byte) error {
			installed[extension.Name] = extension
			return nil
		},
	)
	if err != nil {
		t.Fatalf("download locked target extensions: %v", err)
	}
	for name, want := range expected {
		got := installed[name]
		if got.GOOS != want.GOOS || got.GOARCH != want.GOARCH || got.Platform != want.Platform {
			t.Fatalf("%s target = %s/%s %q, want lock target %s/%s %q", name, got.GOOS, got.GOARCH, got.Platform, want.GOOS, want.GOARCH, want.Platform)
		}
	}

	fetches, installs := 0, 0
	err = downloadExtensions(
		context.Background(), lockPath, fixture.Platform.OS+"-unsupported", fixture.Platform.Arch,
		func(context.Context, string) ([]byte, error) { fetches++; return nil, nil },
		func(context.Context, lockedExtension, []byte) error { installs++; return nil },
	)
	if err == nil {
		t.Fatal("target not present in the versioned lock did not fail closed")
	}
	if fetches != 0 || installs != 0 {
		t.Fatalf("unsupported target performed fetch/install mutations: fetch=%d install=%d", fetches, installs)
	}
}

func TestLockedExtensionDigestRejectsTampering(t *testing.T) {
	fixture, raw := loadExtensionLockFixture(t)
	expected := expectedExtensions(fixture)
	payloads := fixturePayloads(expected)
	lockPath := writeSyntheticDigestLock(t, raw, payloads)
	installCalls := 0

	err := downloadExtensions(
		context.Background(), lockPath, fixture.Platform.OS, fixture.Platform.Arch,
		func(_ context.Context, origin string) ([]byte, error) {
			for name, extension := range expected {
				if extension.Origin == origin {
					tampered := append([]byte(nil), payloads[name]...)
					tampered[len(tampered)-1] ^= 0x01
					return tampered, nil
				}
			}
			return nil, fmt.Errorf("unknown locked origin %q", origin)
		},
		func(context.Context, lockedExtension, []byte) error {
			installCalls++
			return nil
		},
	)
	if err == nil {
		t.Fatal("tampered DuckDB extension content was accepted")
	}
	if installCalls != 0 {
		t.Fatalf("tampered content reached installer %d time(s)", installCalls)
	}
}
