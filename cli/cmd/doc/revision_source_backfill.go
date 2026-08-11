package doc

import (
	"context"
	"fmt"
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

type RevisionSourceBackfillOptions struct {
	Attempt int64
	DryRun  bool
}

type RevisionSourceBackfillService interface {
	BackfillKnowledgeRevisionSource(
		context.Context, string, int64,
	) (*sdk.KnowledgeRevisionSource, error)
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
