package doc

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/cli/internal/cmdutil"
	"github.com/Tencent/WeKnora/cli/internal/iostreams"
	sdk "github.com/Tencent/WeKnora/client"
	"github.com/spf13/cobra"
)

type revisionSourceBackfillStub struct {
	calls   int
	gotID   string
	attempt int64
}

func (s *revisionSourceBackfillStub) BackfillKnowledgeRevisionSource(
	_ context.Context, id string, attempt int64,
) (*sdk.KnowledgeRevisionSource, error) {
	s.calls++
	s.gotID = id
	s.attempt = attempt
	return &sdk.KnowledgeRevisionSource{
		Contract: "knowledge-revision-source.v1", KnowledgeID: id,
		ParseAttempt: attempt, PageCount: 39,
	}, nil
}

func TestRevisionSourceBackfillUsesExactAttemptAndJSONReceipt(t *testing.T) {
	out, _ := iostreams.SetForTest(t)
	stub := &revisionSourceBackfillStub{}
	err := runRevisionSourceBackfill(
		context.Background(),
		&RevisionSourceBackfillOptions{Attempt: 2},
		&cmdutil.FormatOptions{Mode: cmdutil.FormatJSON},
		stub,
		"knowledge-1",
	)
	if err != nil {
		t.Fatal(err)
	}
	if stub.calls != 1 || stub.gotID != "knowledge-1" || stub.attempt != 2 {
		t.Fatalf("unexpected call: calls=%d id=%q attempt=%d", stub.calls, stub.gotID, stub.attempt)
	}
	var envelope struct {
		OK   bool                        `json:"ok"`
		Data sdk.KnowledgeRevisionSource `json:"data"`
	}
	if err := json.Unmarshal(out.Bytes(), &envelope); err != nil {
		t.Fatal(err)
	}
	if !envelope.OK || envelope.Data.ParseAttempt != 2 {
		t.Fatalf("unexpected envelope: %+v", envelope)
	}
}

func TestRevisionSourceBackfillDryRunMakesZeroClientCalls(t *testing.T) {
	out, _ := iostreams.SetForTest(t)
	factory := &cmdutil.Factory{Client: func() (*sdk.Client, error) {
		t.Fatal("dry-run path called the SDK client")
		return nil, nil
	}}
	command := NewCmdRevisionSourceBackfill(factory)
	root := &cobra.Command{Use: "weknora"}
	root.PersistentFlags().String("format", "", "")
	root.PersistentFlags().String("jq", "", "")
	root.AddCommand(command)
	root.SetArgs([]string{
		command.Name(), "knowledge-1", "--attempt", "2", "--dry-run", "--format", "json",
	})
	root.SetContext(context.Background())
	if err := root.Execute(); err != nil {
		t.Fatal(err)
	}
	var envelope struct {
		OK   bool `json:"ok"`
		Meta struct {
			DryRun bool `json:"dry_run"`
			Plan   struct {
				Action string         `json:"action"`
				Args   map[string]any `json:"args"`
			} `json:"plan"`
		} `json:"meta"`
	}
	if err := json.Unmarshal(out.Bytes(), &envelope); err != nil {
		t.Fatal(err)
	}
	if !envelope.OK || !envelope.Meta.DryRun ||
		envelope.Meta.Plan.Action != "doc.revision-source-backfill" ||
		envelope.Meta.Plan.Args["attempt"] != float64(2) {
		t.Fatalf("unexpected dry-run envelope: %+v", envelope)
	}
}
