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

func TestRunThreeSourceCaptureUsesFixedSequenceAndSanitizedOutput(t *testing.T) {
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

	if err := runThreeSourceCapture(context.Background(), repositoryRoot, outputRoot, deps); err != nil {
		t.Fatal(err)
	}
	if len(requests) != 3 {
		t.Fatalf("capture count=%d, want 3", len(requests))
	}
	wantPaths := []string{
		filepath.Join(repositoryRoot, "dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", "保险条款.pdf"),
		filepath.Join(repositoryRoot, "dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", "产品说明书.pdf"),
		filepath.Join(repositoryRoot, "dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", "费率表.pdf"),
	}
	wantHashes := []string{
		"88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
		"5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
		"7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
	}
	for index, req := range requests {
		if req.SourcePath != wantPaths[index] || req.SourceSHA256 != wantHashes[index] ||
			req.AttemptNumber != 2 || req.AttemptRole != "bounded_upgrade" ||
			req.Generation == nil || *req.Generation != 0 ||
			req.ParserOverrides["mineru_cloud_model"] != "pipeline" {
			t.Fatalf("request %d drifted: %#v", index, req)
		}
	}
	info, err := os.Stat(outputRoot)
	if err != nil || info.Mode().Perm() != 0o700 {
		t.Fatalf("output root mode: info=%v err=%v", info, err)
	}
	lines := strings.Split(strings.TrimSpace(stdout.String()), "\n")
	if len(lines) != 3 || !strings.Contains(lines[0], "role=t***s") ||
		!strings.Contains(lines[0], "artifact=terms/mineru-native-structure.json") ||
		!strings.Contains(lines[1], "role=b******e") ||
		!strings.Contains(lines[1], "artifact=brochure/mineru-native-structure.json") ||
		!strings.Contains(lines[2], "role=r**e") ||
		!strings.Contains(lines[2], "artifact=rate/mineru-native-structure.json") {
		t.Fatalf("stdout sequence drifted: %q", stdout.String())
	}
	for index, role := range []string{"terms", "brochure", "rate"} {
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

func TestRunThreeSourceCaptureReusesExactTermsCustodyAndCallsOnlyRemainingSources(
	t *testing.T,
) {
	repositoryRoot := copyFrozenCaptureSources(t, false)
	outputRoot := absentPrivateOutput(t)
	failureDir := filepath.Join(t.TempDir(), "terms")
	if err := os.Mkdir(failureDir, 0o700); err != nil {
		t.Fatal(err)
	}
	var recovered []docparser.MinerUArtifactCaptureRequest
	var captured []docparser.MinerUArtifactCaptureRequest
	deps := runnerDependencies{
		lookupEnv: func(string) (string, bool) { return "in-memory-secret", true },
		recover: func(req docparser.MinerUArtifactCaptureRequest, gotFailureDir string) (string, error) {
			recovered = append(recovered, req)
			if gotFailureDir != failureDir {
				t.Fatalf("failure custody drifted: %s", gotFailureDir)
			}
			return writeFakeCaptureArtifact(t, req, 0o600), nil
		},
		capture: func(_ context.Context, req docparser.MinerUArtifactCaptureRequest) (string, error) {
			captured = append(captured, req)
			return writeFakeCaptureArtifact(t, req, 0o600), nil
		},
		stdout: &bytes.Buffer{},
	}

	if err := runThreeSourceCaptureWithRecoveredTerms(
		context.Background(), repositoryRoot, outputRoot, failureDir, deps,
	); err != nil {
		t.Fatal(err)
	}
	if len(recovered) != 1 || filepath.Base(recovered[0].SourcePath) != "保险条款.pdf" {
		t.Fatalf("terms custody was not reused exactly once: %#v", recovered)
	}
	if len(captured) != 2 || filepath.Base(captured[0].SourcePath) != "产品说明书.pdf" ||
		filepath.Base(captured[1].SourcePath) != "费率表.pdf" {
		t.Fatalf("provider sequence was not brochure then rate: %#v", captured)
	}
}

func TestRunThreeSourceCaptureRejectsNonPrivateArtifactMode(t *testing.T) {
	repositoryRoot := copyFrozenCaptureSources(t, false)
	outputRoot := absentPrivateOutput(t)
	calls := 0
	err := runThreeSourceCapture(context.Background(), repositoryRoot, outputRoot, runnerDependencies{
		lookupEnv: func(string) (string, bool) { return "in-memory-secret", true },
		capture: func(_ context.Context, req docparser.MinerUArtifactCaptureRequest) (string, error) {
			calls++
			return writeFakeCaptureArtifact(t, req, 0o644), nil
		},
		stdout: &bytes.Buffer{},
	})
	if !errors.Is(err, ErrMinerUThreeSourceCaptureFailed) || calls != 1 {
		t.Fatalf("non-private artifact was not rejected: calls=%d err=%v", calls, err)
	}
}

func TestRunThreeSourceCaptureFailsAllPreflightBeforeCapture(t *testing.T) {
	tests := []struct {
		name           string
		mutateRepo     bool
		sourceMutation string
		credential     bool
		makeOutput     bool
	}{
		{name: "source-sha-drift", mutateRepo: true, credential: true},
		{name: "brochure-source-missing", sourceMutation: "brochure:missing", credential: true},
		{name: "brochure-source-sha-drift", sourceMutation: "brochure:sha-drift", credential: true},
		{name: "rate-source-missing", sourceMutation: "rate:missing", credential: true},
		{name: "rate-source-sha-drift", sourceMutation: "rate:sha-drift", credential: true},
		{name: "credential-missing"},
		{name: "output-root-exists", credential: true, makeOutput: true},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			repositoryRoot := copyFrozenCaptureSources(t, tc.mutateRepo)
			mutateFrozenSource(t, repositoryRoot, tc.sourceMutation)
			outputRoot := absentPrivateOutput(t)
			if tc.makeOutput {
				if err := os.Mkdir(outputRoot, 0o700); err != nil {
					t.Fatal(err)
				}
			}
			calls := 0
			err := runThreeSourceCapture(context.Background(), repositoryRoot, outputRoot, runnerDependencies{
				lookupEnv: func(string) (string, bool) { return "in-memory-secret", tc.credential },
				capture: func(context.Context, docparser.MinerUArtifactCaptureRequest) (string, error) {
					calls++
					return "", nil
				},
				stdout: &bytes.Buffer{},
			})
			if !errors.Is(err, ErrMinerUThreeSourcePreflight) || calls != 0 {
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

func TestRunThreeSourceCaptureStopsAndPreservesBoundedPartialCustody(t *testing.T) {
	for _, failAt := range []int{1, 2, 3} {
		t.Run(fmt.Sprintf("failure-%d", failAt), func(t *testing.T) {
			repositoryRoot := copyFrozenCaptureSources(t, false)
			outputRoot := absentPrivateOutput(t)
			calls := 0
			err := runThreeSourceCapture(context.Background(), repositoryRoot, outputRoot, runnerDependencies{
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
			want := ErrMinerUThreeSourceCaptureFailed
			if failAt > 1 {
				want = ErrMinerUThreeSourceCapturePartial
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
			brochure := filepath.Join(outputRoot, "brochure", "mineru-native-structure.json")
			_, brochureErr := os.Stat(brochure)
			if failAt == 3 && brochureErr != nil {
				t.Fatalf("third failure lost brochure evidence: %v", brochureErr)
			}
		})
	}
}

func TestRunCLIRejectsCredentialFlagsWithoutEchoingValue(t *testing.T) {
	var stdout bytes.Buffer
	secret := "must-never-echo"
	err := runCLI(context.Background(), []string{"--api-key=" + secret}, ".", runnerDependencies{stdout: &stdout})
	if !errors.Is(err, ErrMinerUThreeSourcePreflight) || strings.Contains(stdout.String(), secret) ||
		strings.Contains(err.Error(), secret) {
		t.Fatalf("credential CLI boundary drifted: stdout=%q err=%v", stdout.String(), err)
	}
}

func TestRunThreeSourceCaptureRetainsFixedReasonAcrossPrefixAndLogFormat(t *testing.T) {
	for _, tc := range []struct {
		name   string
		failAt int
		prefix string
	}{
		{name: "terms", failAt: 1, prefix: "MinerU terms capture failed"},
		{name: "partial", failAt: 2, prefix: "MinerU capture failed after earlier evidence was preserved"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("LOG_FORMAT", "json")
			repositoryRoot := copyFrozenCaptureSources(t, false)
			outputRoot := absentPrivateOutput(t)
			calls := 0
			err := runThreeSourceCapture(context.Background(), repositoryRoot, outputRoot, runnerDependencies{
				lookupEnv: func(string) (string, bool) { return "in-memory-secret", true },
				capture: func(_ context.Context, req docparser.MinerUArtifactCaptureRequest) (string, error) {
					calls++
					if calls == tc.failAt {
						return "", fmt.Errorf("%w: provider secret https://signed.invalid", docparser.ErrMinerUAllocationFailed)
					}
					return writeFakeCaptureArtifact(t, req, 0o600), nil
				},
				stdout: &bytes.Buffer{},
			})
			stable := stableRunnerError(err)
			want := tc.prefix + ": ALLOCATION_FAILED"
			if stable == nil || stable.Error() != want || calls != tc.failAt {
				t.Fatalf("runner reason drifted: calls=%d got=%v want=%s", calls, stable, want)
			}
			for _, forbidden := range []string{"provider secret", "signed.invalid", "in-memory-secret"} {
				if strings.Contains(stable.Error(), forbidden) {
					t.Fatalf("runner leaked %q: %v", forbidden, stable)
				}
			}
		})
	}
}

func TestStableRunnerErrorUsesClosedReasonCodes(t *testing.T) {
	tests := []struct {
		reason error
		code   string
	}{
		{docparser.ErrMinerUAllocationFailed, "ALLOCATION_FAILED"},
		{docparser.ErrMinerUUploadFailed, "UPLOAD_FAILED"},
		{docparser.ErrMinerUStatusFailed, "STATUS_FAILED"},
		{docparser.ErrMinerUProviderTaskFailed, "PROVIDER_TASK_FAILED"},
		{docparser.ErrMinerUCloudPollBudgetExceeded, "STATUS_BUDGET_EXCEEDED"},
		{docparser.ErrMinerUDownloadURLInvalid, "DOWNLOAD_URL_INVALID"},
		{docparser.ErrMinerUZIPDownloadFailed, "ZIP_DOWNLOAD_FAILED"},
		{docparser.ErrMinerUNativeStructureUnavailable, "NATIVE_STRUCTURE_UNAVAILABLE"},
		{docparser.ErrMinerUCrossPageProjectionInvalid, "CROSS_PAGE_PROJECTION_INVALID"},
		{docparser.ErrMinerUArtifactCustodyInvalid, "ARTIFACT_CUSTODY_INVALID"},
		{docparser.ErrMinerUContentCustodyInvalid, "CONTENT_CUSTODY_INVALID"},
		{errors.New("unrecognized provider secret"), "CAPTURE_STAGE_UNDETERMINED"},
	}
	for _, tc := range tests {
		t.Run(tc.code, func(t *testing.T) {
			err := captureFailure(0, fmt.Errorf("%w: provider secret https://signed.invalid", tc.reason))
			stable := stableRunnerError(err)
			want := ErrMinerUThreeSourceCaptureFailed.Error() + ": " + tc.code
			if stable.Error() != want {
				t.Fatalf("reason=%q, want %q", stable, want)
			}
			if strings.Contains(stable.Error(), "provider secret") || strings.Contains(stable.Error(), "signed.invalid") {
				t.Fatalf("raw detail escaped: %v", stable)
			}
		})
	}
}

func TestStableRunnerErrorHidesSafeZIPDeadlineSentinel(t *testing.T) {
	err := captureFailure(0, fmt.Errorf("%w: %w", docparser.ErrMinerUZIPDownloadFailed, context.DeadlineExceeded))
	stable := stableRunnerError(err)
	want := ErrMinerUThreeSourceCaptureFailed.Error() + ": ZIP_DOWNLOAD_FAILED"
	if stable == nil || stable.Error() != want {
		t.Fatalf("runner deadline reason drifted: got=%v want=%s", stable, want)
	}
	if strings.Contains(stable.Error(), context.DeadlineExceeded.Error()) {
		t.Fatalf("runner exposed internal deadline detail: %v", stable)
	}
}

func copyFrozenCaptureSources(t *testing.T, mutateTerms bool) string {
	t.Helper()
	repositoryRoot := t.TempDir()
	realRoot, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	for index, name := range []string{"保险条款.pdf", "产品说明书.pdf", "费率表.pdf"} {
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

func mutateFrozenSource(t *testing.T, repositoryRoot, mutation string) {
	t.Helper()
	if mutation == "" {
		return
	}
	parts := strings.Split(mutation, ":")
	if len(parts) != 2 {
		t.Fatalf("invalid source mutation: %s", mutation)
	}
	fileName := map[string]string{"brochure": "产品说明书.pdf", "rate": "费率表.pdf"}[parts[0]]
	path := filepath.Join(
		repositoryRoot, "dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", fileName,
	)
	if parts[1] == "missing" {
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
