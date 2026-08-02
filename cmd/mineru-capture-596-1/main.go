package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/Tencent/WeKnora/internal/infrastructure/docparser"
)

const (
	minerUCredentialEnvironment = "MINERU_API_KEY"
	captureArtifactName         = "mineru-native-structure.json"
)

var (
	ErrMinerUThreeSourcePreflight      = errors.New("MinerU three-source capture preflight failed")
	ErrMinerUThreeSourceCaptureFailed  = errors.New("MinerU terms capture failed")
	ErrMinerUThreeSourceCapturePartial = errors.New(
		"MinerU capture failed after earlier evidence was preserved",
	)
)

type captureSource struct {
	role       string
	maskedRole string
	relative   string
	sha256     string
}

var frozenCaptureSources = []captureSource{
	{
		role: "terms", maskedRole: "t***s",
		relative: filepath.Join("dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", "保险条款.pdf"),
		sha256:   "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
	},
	{
		role: "brochure", maskedRole: "b******e",
		relative: filepath.Join("dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", "产品说明书.pdf"),
		sha256:   "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
	},
	{
		role: "rate", maskedRole: "r**e",
		relative: filepath.Join("dataset", "shouxian_product", "平安e生保（尊享版）医疗保险", "费率表.pdf"),
		sha256:   "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
	},
}

type captureFunction func(context.Context, docparser.MinerUArtifactCaptureRequest) (string, error)

type runnerDependencies struct {
	lookupEnv func(string) (string, bool)
	capture   captureFunction
	stdout    io.Writer
}

func main() {
	repositoryRoot, err := os.Getwd()
	if err == nil {
		err = runCLI(context.Background(), os.Args[1:], repositoryRoot, runnerDependencies{
			lookupEnv: os.LookupEnv,
			capture:   docparser.CaptureMinerUNativeStructure,
			stdout:    os.Stdout,
		})
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, stableRunnerError(err))
		os.Exit(2)
	}
}

func runCLI(ctx context.Context, args []string, repositoryRoot string, deps runnerDependencies) error {
	flags := flag.NewFlagSet("mineru-capture-596-1", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	outputRoot := flags.String("output-root", "", "new direct child of /private/tmp")
	if err := flags.Parse(args); err != nil || flags.NArg() != 0 || *outputRoot == "" {
		return ErrMinerUThreeSourcePreflight
	}
	return runThreeSourceCapture(ctx, repositoryRoot, *outputRoot, deps)
}

func runThreeSourceCapture(ctx context.Context, repositoryRoot, outputRoot string, deps runnerDependencies) error {
	sources, err := preflightThreeSourceCapture(repositoryRoot, outputRoot, deps.lookupEnv)
	if err != nil || deps.capture == nil {
		return ErrMinerUThreeSourcePreflight
	}
	if err := os.Mkdir(outputRoot, 0o700); err != nil {
		return ErrMinerUThreeSourcePreflight
	}

	stdout := deps.stdout
	if stdout == nil {
		stdout = io.Discard
	}
	generation := 0
	for index, source := range sources {
		artifact, captureErr := deps.capture(ctx, docparser.MinerUArtifactCaptureRequest{
			SourcePath:    source.path,
			SourceSHA256:  source.sha256,
			AttemptNumber: 2,
			AttemptRole:   "bounded_upgrade",
			Generation:    &generation,
			OutputDir:     filepath.Join(outputRoot, source.role),
			ParserOverrides: map[string]string{
				"mineru_cloud_model": "pipeline",
			},
		})
		if captureErr != nil {
			return captureFailure(index)
		}
		digest, relative, err := validateCapturedEvidence(outputRoot, source.role, artifact)
		if err != nil {
			return captureFailure(index)
		}
		if _, err := fmt.Fprintf(stdout, "status=completed role=%s artifact=%s sha256=%s\n",
			source.maskedRole, relative, digest); err != nil {
			return captureFailure(index)
		}
	}
	return nil
}

type admittedCaptureSource struct {
	role       string
	maskedRole string
	path       string
	sha256     string
}

func preflightThreeSourceCapture(
	repositoryRoot, outputRoot string,
	lookupEnv func(string) (string, bool),
) ([]admittedCaptureSource, error) {
	cleanOutput := filepath.Clean(outputRoot)
	if !filepath.IsAbs(cleanOutput) || filepath.Dir(cleanOutput) != "/private/tmp" ||
		filepath.Base(cleanOutput) == "." || cleanOutput != outputRoot {
		return nil, ErrMinerUThreeSourcePreflight
	}
	if _, err := os.Lstat(cleanOutput); !errors.Is(err, os.ErrNotExist) {
		return nil, ErrMinerUThreeSourcePreflight
	}
	if lookupEnv == nil {
		return nil, ErrMinerUThreeSourcePreflight
	}
	credential, ok := lookupEnv(minerUCredentialEnvironment)
	if !ok || strings.TrimSpace(credential) == "" {
		return nil, ErrMinerUThreeSourcePreflight
	}

	root, err := filepath.Abs(repositoryRoot)
	if err != nil {
		return nil, ErrMinerUThreeSourcePreflight
	}
	sources := make([]admittedCaptureSource, 0, len(frozenCaptureSources))
	for _, source := range frozenCaptureSources {
		path := filepath.Join(root, source.relative)
		info, err := os.Lstat(path)
		if err != nil || !info.Mode().IsRegular() {
			return nil, ErrMinerUThreeSourcePreflight
		}
		payload, err := os.ReadFile(path)
		if err != nil {
			return nil, ErrMinerUThreeSourcePreflight
		}
		digest := sha256.Sum256(payload)
		if hex.EncodeToString(digest[:]) != source.sha256 {
			return nil, ErrMinerUThreeSourcePreflight
		}
		sources = append(sources, admittedCaptureSource{
			role: source.role, maskedRole: source.maskedRole, path: path, sha256: source.sha256,
		})
	}
	return sources, nil
}

func validateCapturedEvidence(outputRoot, role, artifact string) (string, string, error) {
	expected := filepath.Join(outputRoot, role, captureArtifactName)
	if artifact != expected {
		return "", "", ErrMinerUThreeSourceCaptureFailed
	}
	info, err := os.Lstat(expected)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0o600 {
		return "", "", ErrMinerUThreeSourceCaptureFailed
	}
	payload, err := os.ReadFile(expected)
	if err != nil {
		return "", "", ErrMinerUThreeSourceCaptureFailed
	}
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:]), filepath.ToSlash(filepath.Join(role, captureArtifactName)), nil
}

func captureFailure(index int) error {
	if index == 0 {
		return ErrMinerUThreeSourceCaptureFailed
	}
	return ErrMinerUThreeSourceCapturePartial
}

func stableRunnerError(err error) error {
	switch {
	case errors.Is(err, ErrMinerUThreeSourceCapturePartial):
		return ErrMinerUThreeSourceCapturePartial
	case errors.Is(err, ErrMinerUThreeSourceCaptureFailed):
		return ErrMinerUThreeSourceCaptureFailed
	default:
		return ErrMinerUThreeSourcePreflight
	}
}
