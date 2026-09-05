package main

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"

	_ "github.com/duckdb/duckdb-go/v2"
)

const maxExtensionBytes = 1 << 30

type dependencyLock struct {
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

type lockedExtension struct {
	Name     string
	Version  string
	GOOS     string
	GOARCH   string
	Platform string
	Origin   string
	SHA256   string
}

type extensionFetch func(context.Context, string) ([]byte, error)
type extensionInstall func(context.Context, lockedExtension, []byte) error

func loadLockedExtensions(lockPath, goos, goarch string) ([]lockedExtension, error) {
	raw, err := os.ReadFile(filepath.Clean(lockPath))
	if err != nil {
		return nil, fmt.Errorf("read dependency lock: %w", err)
	}
	var lock dependencyLock
	if err := json.Unmarshal(raw, &lock); err != nil {
		return nil, fmt.Errorf("decode dependency lock: %w", err)
	}
	if lock.SchemaVersion != 1 {
		return nil, fmt.Errorf("unsupported dependency lock schema %d", lock.SchemaVersion)
	}
	if lock.Platform.OS != goos || lock.Platform.Arch != goarch {
		return nil, fmt.Errorf(
			"target %s/%s is outside locked target %s/%s",
			goos, goarch, lock.Platform.OS, lock.Platform.Arch,
		)
	}
	if lock.Platform.DuckDB == "" || lock.Downloads.DuckDB.Version == "" {
		return nil, errors.New("DuckDB lock has an incomplete version or platform")
	}
	if len(lock.Downloads.DuckDB.Extensions) != 2 {
		return nil, errors.New("DuckDB lock must contain exactly spatial and excel")
	}

	names := make([]string, 0, len(lock.Downloads.DuckDB.Extensions))
	for name := range lock.Downloads.DuckDB.Extensions {
		names = append(names, name)
	}
	sort.Strings(names)
	if strings.Join(names, ",") != "excel,spatial" {
		return nil, errors.New("DuckDB lock must contain exactly spatial and excel")
	}

	extensions := make([]lockedExtension, 0, len(names))
	for _, name := range names {
		record := lock.Downloads.DuckDB.Extensions[name]
		if record.Platform != lock.Platform.DuckDB {
			return nil, fmt.Errorf("%s extension platform differs from locked target", name)
		}
		parsed, err := url.Parse(record.Origin)
		if err != nil || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") {
			return nil, fmt.Errorf("%s extension has an invalid locked origin", name)
		}
		if parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
			return nil, fmt.Errorf("%s extension origin contains mutable material", name)
		}
		digest, err := hex.DecodeString(record.SHA256)
		if err != nil || len(digest) != sha256.Size || record.SHA256 != strings.ToLower(record.SHA256) {
			return nil, fmt.Errorf("%s extension has an invalid SHA-256", name)
		}
		extensions = append(extensions, lockedExtension{
			Name:     name,
			Version:  lock.Downloads.DuckDB.Version,
			GOOS:     lock.Platform.OS,
			GOARCH:   lock.Platform.Arch,
			Platform: record.Platform,
			Origin:   record.Origin,
			SHA256:   record.SHA256,
		})
	}
	return extensions, nil
}

func downloadExtensions(
	ctx context.Context,
	lockPath string,
	goos string,
	goarch string,
	fetch extensionFetch,
	install extensionInstall,
) error {
	extensions, err := loadLockedExtensions(lockPath, goos, goarch)
	if err != nil {
		return err
	}
	if fetch == nil || install == nil {
		return errors.New("DuckDB fetch and install functions are required")
	}

	verified := make(map[string][]byte, len(extensions))
	for _, extension := range extensions {
		payload, err := fetch(ctx, extension.Origin)
		if err != nil {
			return fmt.Errorf("fetch %s extension: %w", extension.Name, err)
		}
		digest := sha256.Sum256(payload)
		if hex.EncodeToString(digest[:]) != extension.SHA256 {
			return fmt.Errorf("%s extension SHA-256 mismatch", extension.Name)
		}
		verified[extension.Name] = append([]byte(nil), payload...)
	}

	for _, extension := range extensions {
		if err := install(ctx, extension, verified[extension.Name]); err != nil {
			return fmt.Errorf("install %s extension: %w", extension.Name, err)
		}
	}
	return nil
}

func fetchExtension(ctx context.Context, origin string) ([]byte, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, origin, nil)
	if err != nil {
		return nil, err
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected HTTP status %s", response.Status)
	}
	payload, err := io.ReadAll(io.LimitReader(response.Body, maxExtensionBytes+1))
	if err != nil {
		return nil, err
	}
	if len(payload) == 0 || len(payload) > maxExtensionBytes {
		return nil, errors.New("extension payload is empty or too large")
	}
	return payload, nil
}

func extensionInstaller(db *sql.DB) extensionInstall {
	return func(ctx context.Context, extension lockedExtension, verified []byte) error {
		home, err := os.UserHomeDir()
		if err != nil {
			return err
		}
		directory := filepath.Join(
			home, ".duckdb", "extensions", extension.Version, extension.Platform,
		)
		if err := os.MkdirAll(directory, 0o755); err != nil {
			return err
		}
		reader, err := gzip.NewReader(bytes.NewReader(verified))
		if err != nil {
			return fmt.Errorf("open verified gzip: %w", err)
		}
		decompressed, readErr := io.ReadAll(io.LimitReader(reader, maxExtensionBytes+1))
		closeErr := reader.Close()
		if readErr != nil {
			return readErr
		}
		if closeErr != nil {
			return closeErr
		}
		if len(decompressed) == 0 || len(decompressed) > maxExtensionBytes {
			return errors.New("decompressed extension is empty or too large")
		}
		destination := filepath.Join(directory, extension.Name+".duckdb_extension")
		temporary, err := os.CreateTemp(directory, "."+extension.Name+"-*")
		if err != nil {
			return err
		}
		temporaryName := temporary.Name()
		defer os.Remove(temporaryName)
		if err := temporary.Chmod(0o644); err != nil {
			temporary.Close()
			return err
		}
		if _, err := temporary.Write(decompressed); err != nil {
			temporary.Close()
			return err
		}
		if err := temporary.Close(); err != nil {
			return err
		}
		if err := os.Rename(temporaryName, destination); err != nil {
			return err
		}
		if _, err := db.ExecContext(ctx, "LOAD "+extension.Name); err != nil {
			return fmt.Errorf("load staged extension: %w", err)
		}
		return nil
	}
}

type expectedCLIValues struct {
	duckdbPlatform  string
	duckdbVersion   string
	spatialPlatform string
	spatialOrigin   string
	spatialSHA256   string
	excelPlatform   string
	excelOrigin     string
	excelSHA256     string
}

func verifyCLIValues(lockPath, goos, goarch string, expected expectedCLIValues) error {
	extensions, err := loadLockedExtensions(lockPath, goos, goarch)
	if err != nil {
		return err
	}
	for _, extension := range extensions {
		if extension.Platform != expected.duckdbPlatform || extension.Version != expected.duckdbVersion {
			return errors.New("DuckDB command values differ from the versioned lock")
		}
		if extension.Name == "spatial" &&
			(extension.Platform != expected.spatialPlatform || extension.Origin != expected.spatialOrigin || extension.SHA256 != expected.spatialSHA256) {
			return errors.New("spatial command values differ from the versioned lock")
		}
		if extension.Name == "excel" &&
			(extension.Platform != expected.excelPlatform || extension.Origin != expected.excelOrigin || extension.SHA256 != expected.excelSHA256) {
			return errors.New("excel command values differ from the versioned lock")
		}
	}
	return nil
}

func main() {
	lockPath := flag.String("lock", "deploy/local-build/app-external-dependencies.v1.json", "versioned dependency lock")
	goos := flag.String("goos", runtime.GOOS, "locked target operating system")
	goarch := flag.String("goarch", runtime.GOARCH, "locked target architecture")
	expected := expectedCLIValues{}
	flag.StringVar(&expected.duckdbPlatform, "duckdb-platform", "", "locked DuckDB platform")
	flag.StringVar(&expected.duckdbVersion, "duckdb-version", "", "locked DuckDB version")
	flag.StringVar(&expected.spatialPlatform, "spatial-platform", "", "locked spatial platform")
	flag.StringVar(&expected.spatialOrigin, "spatial-origin", "", "locked spatial origin")
	flag.StringVar(&expected.spatialSHA256, "spatial-sha256", "", "locked spatial SHA-256")
	flag.StringVar(&expected.excelPlatform, "excel-platform", "", "locked excel platform")
	flag.StringVar(&expected.excelOrigin, "excel-origin", "", "locked excel origin")
	flag.StringVar(&expected.excelSHA256, "excel-sha256", "", "locked excel SHA-256")
	flag.Parse()
	if err := verifyCLIValues(*lockPath, *goos, *goarch, expected); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	db, err := sql.Open("duckdb", ":memory:")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer db.Close()
	if err := downloadExtensions(
		context.Background(),
		*lockPath,
		*goos,
		*goarch,
		fetchExtension,
		extensionInstaller(db),
	); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
