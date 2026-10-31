package cmd

// The revision-source backfill commands are ours (cli/cmd/doc/revision_source_backfill.go). They
// mutate server state, so they must register --dry-run. Declaring them here keeps the upstream
// drift guard (dryrun_coverage_test.go) byte-identical to WeKnora; package-level variables are
// initialised before init runs, so the map exists when these entries are added.
func init() {
	dryRunExpectation["doc revision-source-backfill"] = true
	dryRunExpectation["doc revision-source-exact3-backfill"] = true
}
