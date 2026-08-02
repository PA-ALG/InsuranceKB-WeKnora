package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/infrastructure/docparser"
)

func TestRunTwoSourceCaptureUsesFixedSequenceAndSanitizedOutput(t *testing.T) {
	repositoryRoot := copyFrozenCaptureSources(t, false)
	outputRoot := absentPrivateOutput(t)
	secret := "must-never-appear"
	var stdout bytes.Buffer
	var requests []docparser.MinerUArtifactCaptureRequest
	deps := runnerDependencies{
		lookupEnv: func(key string) (string, bool) {
			if key != "MINERU_API_KEY" {
				t.Fatalf("unexpected environment key: %s", key)
			}
			return secret, true
		},
		capture: func(_ context.Context, req docparser.MinerUArtifactCaptureRequest) (string, error) {
			requests = append(requests, req)
			if err := os.Mkdir(req.OutputDir, 0o700); err != nil {
				return "", err
			}
			payload := []byte(fmt.Sprintf("evidence-%d\n", len(requests)))
			artifact := filepath.Join(req.OutputDir, "mineru-native-structure.json")
			if err := os.WriteFile(artifact, payload, 0o600); err != nil {
				return "", err
			}
			return artifact, nil
		},
		stdout: &stdout,
	}

	if err := runTwoSourceCapture(context.Background(), repositoryRoot, outputRoot, deps); err != nil {
		t.Fatal(err)
	}
	if len(requests) != 2 {
		t.Fatalf("capture count=%d, want 2", len(requests))
	}
	wantPaths := []string{
		filepath.Join(repositoryRoot, "dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", "保险条款.pdf"),
		filepath.Join(repositoryRoot, "dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", "费率表.pdf"),
	}
	wantHashes := []string{
		"88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
		"7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
	}
	for index, req := range requests {
		if req.SourcePath != wantPaths[index] || req.SourceSHA256 != wantHashes[index] ||
			req.ParserOverrides["mineru_cloud_model"] != "pipeline" {
			t.Fatalf("request %d drifted: %#v", index, req)
		}
	}
	info, err := os.Stat(outputRoot)
	if err != nil || info.Mode().Perm() != 0o700 {
		t.Fatalf("output root mode: info=%v err=%v", info, err)
	}
	lines := strings.Split(strings.TrimSpace(stdout.String()), "\n")
	if len(lines) != 2 || !strings.Contains(lines[0], "role=t***s") ||
		!strings.Contains(lines[0], "artifact=terms/mineru-native-structure.json") ||
		!strings.Contains(lines[1], "role=r**e") ||
		!strings.Contains(lines[1], "artifact=rate/mineru-native-structure.json") {
		t.Fatalf("stdout sequence drifted: %q", stdout.String())
	}
	for index, role := range []string{"terms", "rate"} {
		artifact := filepath.Join(outputRoot, role, "mineru-native-structure.json")
		info, err := os.Stat(artifact)
		if err != nil || info.Mode().Perm() != 0o600 {
			t.Fatalf("artifact mode: role=%s info=%v err=%v", role, info, err)
		}
		if !strings.Contains(lines[index], "sha256="+fileSHA256(t, artifact)) {
			t.Fatalf("stdout artifact hash drifted: %q", lines[index])
		}
	}
	for _, forbidden := range []string{secret, repositoryRoot, outputRoot, "平安e生保", "http://", "https://", "evidence-1"} {
		if strings.Contains(stdout.String(), forbidden) {
			t.Fatalf("stdout leaked %q: %s", forbidden, stdout.String())
		}
	}
}

func TestRunTwoSourceCaptureRejectsNonPrivateArtifactMode(t *testing.T) {
	repositoryRoot := copyFrozenCaptureSources(t, false)
	outputRoot := absentPrivateOutput(t)
	calls := 0
	err := runTwoSourceCapture(context.Background(), repositoryRoot, outputRoot, runnerDependencies{
		lookupEnv: func(string) (string, bool) { return "in-memory-secret", true },
		capture: func(_ context.Context, req docparser.MinerUArtifactCaptureRequest) (string, error) {
			calls++
			return writeFakeCaptureArtifact(t, req, 0o644), nil
		},
		stdout: &bytes.Buffer{},
	})
	if !errors.Is(err, ErrMinerUTwoSourceCaptureFailed) || calls != 1 {
		t.Fatalf("non-private artifact was not rejected: calls=%d err=%v", calls, err)
	}
}

func TestRunTwoSourceCaptureFailsAllPreflightBeforeCapture(t *testing.T) {
	tests := []struct {
		name         string
		mutateRepo   bool
		rateMutation string
		credential   bool
		makeOutput   bool
	}{
		{name: "source-sha-drift", mutateRepo: true, credential: true},
		{name: "rate-source-missing", rateMutation: "missing", credential: true},
		{name: "rate-source-sha-drift", rateMutation: "sha-drift", credential: true},
		{name: "credential-missing"},
		{name: "output-root-exists", credential: true, makeOutput: true},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			repositoryRoot := copyFrozenCaptureSources(t, tc.mutateRepo)
			mutateFrozenRateSource(t, repositoryRoot, tc.rateMutation)
			outputRoot := absentPrivateOutput(t)
			if tc.makeOutput {
				if err := os.Mkdir(outputRoot, 0o700); err != nil {
					t.Fatal(err)
				}
			}
			calls := 0
			err := runTwoSourceCapture(context.Background(), repositoryRoot, outputRoot, runnerDependencies{
				lookupEnv: func(string) (string, bool) { return "in-memory-secret", tc.credential },
				capture: func(context.Context, docparser.MinerUArtifactCaptureRequest) (string, error) {
					calls++
					return "", nil
				},
				stdout: &bytes.Buffer{},
			})
			if !errors.Is(err, ErrMinerUTwoSourcePreflight) || calls != 0 {
				t.Fatalf("preflight was not fail-before-capture: calls=%d err=%v", calls, err)
			}
			if !tc.makeOutput {
				if _, statErr := os.Stat(outputRoot); !errors.Is(statErr, os.ErrNotExist) {
					t.Fatalf("preflight created output: %v", statErr)
				}
			}
		})
	}
}

func TestRunTwoSourceCaptureStopsOnFirstAndPreservesFirstOnSecondFailure(t *testing.T) {
	for _, failAt := range []int{1, 2} {
		t.Run(fmt.Sprintf("failure-%d", failAt), func(t *testing.T) {
			repositoryRoot := copyFrozenCaptureSources(t, false)
			outputRoot := absentPrivateOutput(t)
			calls := 0
			err := runTwoSourceCapture(context.Background(), repositoryRoot, outputRoot, runnerDependencies{
				lookupEnv: func(string) (string, bool) { return "in-memory-secret", true },
				capture: func(_ context.Context, req docparser.MinerUArtifactCaptureRequest) (string, error) {
					calls++
					if calls == failAt {
						return "", errors.New("provider detail with in-memory-secret")
					}
					if err := os.Mkdir(req.OutputDir, 0o700); err != nil {
						return "", err
					}
					artifact := filepath.Join(req.OutputDir, "mineru-native-structure.json")
					return artifact, os.WriteFile(artifact, []byte("first-evidence\n"), 0o600)
				},
				stdout: &bytes.Buffer{},
			})
			want := ErrMinerUTwoSourceCaptureFailed
			if failAt == 2 {
				want = ErrMinerUTwoSourceCapturePartial
			}
			if !errors.Is(err, want) || calls != failAt || strings.Contains(err.Error(), "in-memory-secret") {
				t.Fatalf("failure contract drifted: calls=%d err=%v", calls, err)
			}
			first := filepath.Join(outputRoot, "terms", "mineru-native-structure.json")
			_, statErr := os.Stat(first)
			if failAt == 1 && !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("first failure left evidence: %v", statErr)
			}
			if failAt == 2 && statErr != nil {
				t.Fatalf("second failure lost first evidence: %v", statErr)
			}
		})
	}
}

func TestRunCLIRejectsCredentialFlagsWithoutEchoingValue(t *testing.T) {
	var stdout bytes.Buffer
	secret := "must-never-echo"
	err := runCLI(context.Background(), []string{"--api-key=" + secret}, ".", runnerDependencies{stdout: &stdout})
	if !errors.Is(err, ErrMinerUTwoSourcePreflight) || strings.Contains(stdout.String(), secret) ||
		strings.Contains(err.Error(), secret) {
		t.Fatalf("credential CLI boundary drifted: stdout=%q err=%v", stdout.String(), err)
	}
}

func copyFrozenCaptureSources(t *testing.T, mutateTerms bool) string {
	t.Helper()
	repositoryRoot := t.TempDir()
	realRoot, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	for index, name := range []string{"保险条款.pdf", "费率表.pdf"} {
		relative := filepath.Join("dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", name)
		payload, err := os.ReadFile(filepath.Join(realRoot, relative))
		if err != nil {
			t.Fatal(err)
		}
		if index == 0 && mutateTerms {
			payload = append(append([]byte(nil), payload...), 'x')
		}
		target := filepath.Join(repositoryRoot, relative)
		if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(target, payload, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return repositoryRoot
}

func mutateFrozenRateSource(t *testing.T, repositoryRoot, mutation string) {
	t.Helper()
	if mutation == "" {
		return
	}
	path := filepath.Join(
		repositoryRoot, "dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", "费率表.pdf",
	)
	if mutation == "missing" {
		if err := os.Remove(path); err != nil {
			t.Fatal(err)
		}
		return
	}
	payload, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, append(payload, 'x'), 0o600); err != nil {
		t.Fatal(err)
	}
}

func writeFakeCaptureArtifact(
	t *testing.T, req docparser.MinerUArtifactCaptureRequest, mode os.FileMode,
) string {
	t.Helper()
	if err := os.Mkdir(req.OutputDir, 0o700); err != nil {
		t.Fatal(err)
	}
	artifact := filepath.Join(req.OutputDir, "mineru-native-structure.json")
	if err := os.WriteFile(artifact, []byte("evidence\n"), mode); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(artifact, mode); err != nil {
		t.Fatal(err)
	}
	return artifact
}

func absentPrivateOutput(t *testing.T) string {
	t.Helper()
	seed, err := os.CreateTemp("/private/tmp", "063-output-seed-")
	if err != nil {
		t.Fatal(err)
	}
	path := seed.Name() + "-capture"
	if err := seed.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(seed.Name()); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(path) })
	return path
}

func fileSHA256(t *testing.T, path string) string {
	t.Helper()
	payload, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:])
}
