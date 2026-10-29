package tools

import "context"

// Native Wiki write tools ask the service for release custody first
// (CheckWikiWrite). Upstream's v0.9.0 fakes model unmanaged knowledge bases,
// so they allow every write; kept here so upstream's test files stay unpatched.

func (*flagIssueWikiService) CheckWikiWrite(context.Context, string) error { return nil }

func (*sourceRefWikiService) CheckWikiWrite(context.Context, string) error { return nil }

func (*replaceTextWikiService) CheckWikiWrite(context.Context, string) error { return nil }
