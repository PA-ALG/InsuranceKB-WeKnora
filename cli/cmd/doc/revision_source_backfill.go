package doc

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/spf13/cobra"

	"github.com/Tencent/WeKnora/cli/internal/cmdutil"
	"github.com/Tencent/WeKnora/cli/internal/iostreams"
	sdk "github.com/Tencent/WeKnora/client"
)

var revisionSourceBackfillFields = []string{
	"contract", "knowledge_id", "parse_attempt", "revision_source_id",
	"file_sha256", "object_sha256", "size", "mime_type", "page_count",
	"manifest_algorithm", "manifest_digest", "chunk_count", "binding_digest",
	"retention_state",
}

var revisionSourceExact3BackfillFields = []string{
	"contract", "dry_run", "validated_roles", "sources",
}

type RevisionSourceBackfillOptions struct {
	Attempt int64
	DryRun  bool
}

type RevisionSourceBackfillService interface {
	BackfillKnowledgeRevisionSource(
		context.Context, string, int64,
	) (*sdk.KnowledgeRevisionSource, error)
}

type RevisionSourceExact3BackfillService interface {
	BackfillKnowledgeRevisionSourcesExact3(
		context.Context,
		string,
		sdk.KnowledgeRevisionSourceExact3RequestV1,
	) (*sdk.KnowledgeRevisionSourceExact3ResultV1, error)
}

type RevisionSourceExact3BackfillOptions struct {
	Manifest string
	DryRun   bool
}

func NewCmdRevisionSourceBackfill(f *cmdutil.Factory) *cobra.Command {
	opts := &RevisionSourceBackfillOptions{}
	cmd := &cobra.Command{
		Use:   "revision-source-backfill <doc-id>",
		Short: "Seal the exact completed PDF revision source",
		Args:  cobra.ExactArgs(1),
		RunE: func(c *cobra.Command, args []string) error {
			if strings.TrimSpace(args[0]) == "" || opts.Attempt <= 0 {
				return cmdutil.NewError(
					cmdutil.CodeInputInvalidArgument,
					"document id and --attempt greater than zero are required",
				)
			}
			fopts, err := cmdutil.CheckFormatFlag(c)
			if err != nil {
				return err
			}
			fopts.ResolveDefault(iostreams.IO.IsStdoutTTY())
			if handled, err := cmdutil.HandleDryRun(c, opts.DryRun, cmdutil.DryRunPlan{
				Action: "doc.revision-source-backfill",
				Args: map[string]any{
					"doc": args[0], "attempt": opts.Attempt,
				},
			}); handled {
				return err
			}
			client, err := f.Client()
			if err != nil {
				return err
			}
			return runRevisionSourceBackfill(
				c.Context(), opts, fopts, client, args[0],
			)
		},
	}
	cmd.Flags().Int64Var(&opts.Attempt, "attempt", 0, "Exact completed parse attempt")
	cmdutil.AddDryRunFlag(cmd, &opts.DryRun)
	cmdutil.AddFormatFlag(cmd, revisionSourceBackfillFields...)
	cmdutil.AddIgnoredKBFlag(cmd)
	cmdutil.SetAgentHelp(cmd, cmdutil.AgentHelp{
		UsedFor:       "seal one exact completed PDF revision source",
		RequiredFlags: []string{"<doc-id> (positional)", "--attempt"},
		Examples: []string{
			"weknora doc revision-source-backfill doc_abc --attempt 2 --dry-run",
			"weknora doc revision-source-backfill doc_abc --attempt 2 --format json",
		},
		Output: "dry-run emits a no-write plan; execution emits the sealed KnowledgeRevisionSource with exact revision, object, page-count, and binding digests",
	})
	return cmd
}

func runRevisionSourceBackfill(
	ctx context.Context,
	opts *RevisionSourceBackfillOptions,
	fopts *cmdutil.FormatOptions,
	service RevisionSourceBackfillService,
	knowledgeID string,
) error {
	source, err := service.BackfillKnowledgeRevisionSource(ctx, knowledgeID, opts.Attempt)
	if err != nil {
		return cmdutil.WrapHTTP(err, "backfill revision source for document %s", knowledgeID)
	}
	if fopts.WantsJSON() {
		return fopts.Emit(iostreams.IO.Out, source, nil)
	}
	_, err = fmt.Fprintf(
		iostreams.IO.Out,
		"revision source sealed: %s attempt=%d pages=%d binding=%s\n",
		source.KnowledgeID, source.ParseAttempt, source.PageCount, source.BindingDigest,
	)
	return err
}

func NewCmdRevisionSourceExact3Backfill(f *cmdutil.Factory) *cobra.Command {
	opts := &RevisionSourceExact3BackfillOptions{}
	cmd := &cobra.Command{
		Use:   "revision-source-exact3-backfill",
		Short: "Server-verify and seal the exact terms, brochure, and rate sources",
		Args:  cobra.NoArgs,
		RunE: func(c *cobra.Command, _ []string) error {
			if strings.TrimSpace(opts.Manifest) == "" {
				return cmdutil.NewError(
					cmdutil.CodeInputInvalidArgument, "--manifest is required",
				)
			}
			fopts, err := cmdutil.CheckFormatFlag(c)
			if err != nil {
				return err
			}
			fopts.ResolveDefault(iostreams.IO.IsStdoutTTY())
			manifest, err := readRevisionSourceExact3Manifest(opts.Manifest)
			if err != nil {
				return err
			}
			manifest.DryRun = opts.DryRun
			client, err := f.Client()
			if err != nil {
				return err
			}
			kbID, err := f.ResolveKB(c)
			if err != nil {
				return err
			}
			return runRevisionSourceExact3Backfill(
				c.Context(), fopts, client, kbID, manifest,
			)
		},
	}
	cmd.Flags().StringVar(&opts.Manifest, "manifest", "", "Closed exact3 JSON manifest")
	cmdutil.AddKBFlag(cmd)
	cmdutil.AddDryRunFlag(cmd, &opts.DryRun)
	cmdutil.AddFormatFlag(cmd, revisionSourceExact3BackfillFields...)
	cmdutil.SetAgentHelp(cmd, cmdutil.AgentHelp{
		UsedFor:       "server-verify and seal the exact terms, brochure, and rate revision sources",
		RequiredFlags: []string{"--manifest"},
		Examples: []string{
			"weknora doc revision-source-exact3-backfill --manifest exact3.json --kb kb_abc --dry-run",
			"weknora doc revision-source-exact3-backfill --manifest exact3.json --kb kb_abc --format json",
		},
		Output: "dry-run emits the safe exact3 classification receipt; execution emits the strict serial seal result with validated roles and write counts",
	})
	return cmd
}

func readRevisionSourceExact3Manifest(
	path string,
) (sdk.KnowledgeRevisionSourceExact3RequestV1, error) {
	var request sdk.KnowledgeRevisionSourceExact3RequestV1
	data, err := os.ReadFile(path)
	if err != nil {
		return request, cmdutil.NewError(
			cmdutil.CodeInputInvalidArgument, "exact3 manifest is unreadable",
		)
	}
	decoder := json.NewDecoder(io.LimitReader(bytes.NewReader(data), 32<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		return request, cmdutil.NewError(
			cmdutil.CodeInputInvalidArgument, "exact3 manifest is invalid",
		)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return request, cmdutil.NewError(
			cmdutil.CodeInputInvalidArgument, "exact3 manifest is invalid",
		)
	}
	if request.Contract != sdk.KnowledgeRevisionSourceExact3ContractV1 ||
		len(request.Sources) != 3 {
		return request, cmdutil.NewError(
			cmdutil.CodeInputInvalidArgument, "exact3 manifest contract is invalid",
		)
	}
	return request, nil
}

func runRevisionSourceExact3Backfill(
	ctx context.Context,
	fopts *cmdutil.FormatOptions,
	service RevisionSourceExact3BackfillService,
	knowledgeBaseID string,
	request sdk.KnowledgeRevisionSourceExact3RequestV1,
) error {
	result, err := service.BackfillKnowledgeRevisionSourcesExact3(
		ctx, knowledgeBaseID, request,
	)
	if err != nil {
		return cmdutil.WrapHTTP(err, "backfill exact3 revision sources")
	}
	if fopts.WantsJSON() {
		return fopts.Emit(iostreams.IO.Out, result, nil)
	}
	_, err = fmt.Fprintf(
		iostreams.IO.Out,
		"exact3 revision sources verified: dry_run=%t roles=%s planned=%d duplicate=%d conflict=%d writes=%d\n",
		result.DryRun, strings.Join(result.ValidatedRoles, ","), result.PlannedRows,
		result.DuplicateRows, result.ConflictRows, result.Writes,
	)
	return err
}
