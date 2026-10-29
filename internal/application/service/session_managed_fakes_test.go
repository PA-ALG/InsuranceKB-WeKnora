package service

import "context"

// Upstream's v0.9.0 SearchKnowledge tests use an in-package knowledge base
// fake. Production wraps the knowledge base service in the release-custody
// decorator (managed.DecorateKnowledgeBaseService), which answers native-read
// checks; this answers them for the fake as an unmanaged library, the case
// those tests cover, so upstream's file stays byte-identical (U-1).
func (s *searchKBService) CheckNativeRead(context.Context, string) error { return nil }

// The same for upstream's shared-knowledge-base chat fixture.
func (s *sharedChatKBs) CheckNativeRead(context.Context, string) error { return nil }
