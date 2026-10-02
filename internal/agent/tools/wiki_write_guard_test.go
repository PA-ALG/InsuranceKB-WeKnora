package tools

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

// Return stored pointers so the denied-path tests also catch edits made before
// the service's persistence methods, not only calls to those methods.
type writeGuardWikiService struct {
	interfaces.WikiPageService
	pages   map[string]*types.WikiPage
	issues  []*types.WikiPageIssue
	effects []string
}

func newWriteGuardWikiService() *writeGuardWikiService {
	return &writeGuardWikiService{
		pages: map[string]*types.WikiPage{
			"concept/target": {
				TenantID: 42, KnowledgeBaseID: "kb-target", Slug: "concept/target",
				Title: "Original", Summary: "Original summary", Content: "old text",
				PageType: "concept", InLinks: types.StringArray{"concept/referrer"},
			},
			"concept/referrer": {
				TenantID: 42, KnowledgeBaseID: "kb-target", Slug: "concept/referrer",
				Content: "See [[concept/target]] and [[concept/target|Target]].",
			},
		},
		issues: []*types.WikiPageIssue{{
			ID: "issue-1", TenantID: 42, KnowledgeBaseID: "kb-target", Slug: "concept/target", Status: "pending",
		}},
	}
}

func (s *writeGuardWikiService) GetPageBySlug(_ context.Context, kbID, slug string) (*types.WikiPage, error) {
	if kbID != "kb-target" {
		return nil, nil
	}
	return s.pages[slug], nil
}

func (s *writeGuardWikiService) record(effect, kbID string) {
	s.effects = append(s.effects, effect+":"+kbID)
}

func (s *writeGuardWikiService) RepairContentLinks(_ context.Context, kbID, _, content string) (string, bool, error) {
	s.record("repair", kbID)
	return content, false, nil
}

func (s *writeGuardWikiService) CreatePage(_ context.Context, page *types.WikiPage) (*types.WikiPage, error) {
	s.record("create", page.KnowledgeBaseID)
	s.pages[page.Slug] = page
	return page, nil
}

func (s *writeGuardWikiService) UpdatePage(_ context.Context, page *types.WikiPage) (*types.WikiPage, error) {
	s.record("update", page.KnowledgeBaseID)
	s.pages[page.Slug] = page
	return page, nil
}

func (s *writeGuardWikiService) UpdateAutoLinkedContent(_ context.Context, page *types.WikiPage) error {
	s.record("rewrite-link", page.KnowledgeBaseID)
	s.pages[page.Slug] = page
	return nil
}

func (s *writeGuardWikiService) DeletePage(_ context.Context, kbID, slug string) error {
	s.record("delete", kbID)
	delete(s.pages, slug)
	return nil
}

func (s *writeGuardWikiService) InjectCrossLinks(_ context.Context, kbID string, _ []string) {
	s.record("cross-links", kbID)
}

func (s *writeGuardWikiService) RebuildIndexPage(_ context.Context, kbID string) error {
	s.record("index", kbID)
	return nil
}

func (s *writeGuardWikiService) ListIssues(_ context.Context, kbID, _, _ string) ([]*types.WikiPageIssue, error) {
	if kbID != "kb-target" {
		return nil, nil
	}
	return s.issues, nil
}

func (s *writeGuardWikiService) CreateIssue(
	_ context.Context, issue *types.WikiPageIssue,
) (*types.WikiPageIssue, error) {
	s.record("create-issue", issue.KnowledgeBaseID)
	s.issues = append(s.issues, issue)
	return issue, nil
}

func (s *writeGuardWikiService) UpdateIssueStatus(_ context.Context, kbID, issueID, status string) error {
	s.record("update-issue", kbID)
	for _, issue := range s.issues {
		if issue.ID == issueID {
			issue.Status = status
		}
	}
	return nil
}

type writeGuardClassifier struct {
	role  managed.Role
	err   error
	kbID  string
	calls int
}

func (c *writeGuardClassifier) Classify(_ context.Context, tenantID uint64, kbID string) (managed.Role, error) {
	if tenantID != 42 {
		return managed.Role{}, errors.New("wrong tenant")
	}
	c.kbID = kbID
	c.calls++
	return c.role, c.err
}

type writeGuardKBLookup struct{ calls []string }

func (l *writeGuardKBLookup) GetKnowledgeBaseByIDOnly(_ context.Context, kbID string) (*types.KnowledgeBase, error) {
	l.calls = append(l.calls, kbID)
	return &types.KnowledgeBase{ID: kbID, TenantID: 42}, nil
}

type wikiWriteGuardCase struct {
	name string
	args string
	tool func(interfaces.WikiPageService, []string, *WikiRouteResolver) types.Tool
	want []string
}

func wikiWriteGuardCases() []wikiWriteGuardCase {
	return []wikiWriteGuardCase{
		{
			name: "write-create",
			args: `{"slug":"concept/new","title":"New","summary":"Summary",` +
				`"content":"new text","page_type":"concept"}`,
			tool: func(s interfaces.WikiPageService, kbIDs []string, r *WikiRouteResolver) types.Tool {
				r.remember("concept/new", "kb-target")
				return NewWikiWritePageTool(s, kbIDs, nil, r)
			},
			want: []string{"repair:kb-target", "create:kb-target", "cross-links:kb-target", "index:kb-target"},
		},
		{
			name: "write-update",
			args: `{"slug":"concept/target","title":"New","summary":"Summary",` +
				`"content":"new text","page_type":"concept"}`,
			tool: func(s interfaces.WikiPageService, kbIDs []string, r *WikiRouteResolver) types.Tool {
				return NewWikiWritePageTool(s, kbIDs, nil, r)
			},
			want: []string{"repair:kb-target", "update:kb-target", "cross-links:kb-target", "index:kb-target"},
		},
		{
			name: "replace-text", args: `{"slug":"concept/target","old_text":"old","new_text":"new"}`,
			tool: func(s interfaces.WikiPageService, kbIDs []string, r *WikiRouteResolver) types.Tool {
				return NewWikiReplaceTextTool(s, kbIDs, nil, r)
			},
			want: []string{"update:kb-target"},
		},
		{
			name: "rename-page", args: `{"slug":"concept/target","new_slug":"concept/renamed"}`,
			tool: func(s interfaces.WikiPageService, kbIDs []string, r *WikiRouteResolver) types.Tool {
				return NewWikiRenamePageTool(s, kbIDs, r)
			},
			want: []string{
				"create:kb-target", "rewrite-link:kb-target", "delete:kb-target",
				"cross-links:kb-target", "index:kb-target",
			},
		},
		{
			name: "delete-page", args: `{"slug":"concept/target"}`,
			tool: func(s interfaces.WikiPageService, kbIDs []string, r *WikiRouteResolver) types.Tool {
				return NewWikiDeletePageTool(s, kbIDs, r)
			},
			want: []string{"rewrite-link:kb-target", "delete:kb-target"},
		},
		{
			name: "flag-issue", args: `{"slug":"concept/target","issue_type":"other","description":"Review"}`,
			tool: func(s interfaces.WikiPageService, kbIDs []string, r *WikiRouteResolver) types.Tool {
				return NewWikiFlagIssueTool(s, kbIDs, r)
			},
			want: []string{"create-issue:kb-target"},
		},
		{
			name: "update-issue", args: `{"issue_id":"issue-1","status":"resolved"}`,
			tool: func(s interfaces.WikiPageService, kbIDs []string, _ *WikiRouteResolver) types.Tool {
				return NewWikiUpdateIssueTool(s, kbIDs)
			},
			want: []string{"update-issue:kb-target"},
		},
	}
}

func TestWikiWriteToolsRejectManagedTargetsBeforeAnyMutation(t *testing.T) {
	for _, kind := range []managed.Kind{managed.KindWiki, managed.KindRaw} {
		for _, state := range []managed.State{managed.StatePending, managed.StateActive} {
			for _, test := range wikiWriteGuardCases() {
				t.Run(string(kind)+"/"+string(state)+"/"+test.name, func(t *testing.T) {
					classifier := &writeGuardClassifier{role: managed.Role{Kind: kind, State: state}}
					assertWikiWriteGuardRejects(t, test, classifier, true, managed.ErrorCodeReleaseManaged)
				})
			}
		}
	}
}

func TestWikiWriteToolsFailClosedWhenClassificationUnavailable(t *testing.T) {
	for _, failure := range []struct {
		name          string
		newClassifier func() managed.Classifier
		checker       bool
	}{
		{name: "classifier failure", newClassifier: func() managed.Classifier {
			return &writeGuardClassifier{err: errors.New("lookup failed")}
		}, checker: true},
		{name: "nil classifier", checker: true},
		{name: "missing checker"},
	} {
		for _, test := range wikiWriteGuardCases() {
			t.Run(failure.name+"/"+test.name, func(t *testing.T) {
				var classifier managed.Classifier
				if failure.newClassifier != nil {
					classifier = failure.newClassifier()
				}
				assertWikiWriteGuardRejects(
					t, test, classifier, failure.checker, managed.ErrorCodeClassificationUnavailable,
				)
			})
		}
	}
}

func assertWikiWriteGuardRejects(
	t *testing.T,
	test wikiWriteGuardCase,
	classifier managed.Classifier,
	hasChecker bool,
	code string,
) {
	t.Helper()
	base := newWriteGuardWikiService()
	before, err := json.Marshal(struct {
		Pages  map[string]*types.WikiPage
		Issues []*types.WikiPageIssue
	}{base.pages, base.issues})
	if err != nil {
		t.Fatal(err)
	}
	var service interfaces.WikiPageService = base
	lookup := &writeGuardKBLookup{}
	if hasChecker {
		service = managed.WrapWikiService(base, classifier, lookup)
	}
	tool := test.tool(service, []string{"kb-first", "kb-target"}, NewWikiRouteResolver())
	// A shared KB belongs to tenant 42 while the caller belongs to tenant 7.
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
	result, err := tool.Execute(ctx, json.RawMessage(test.args))
	if err != nil || result == nil || result.Success || !strings.Contains(result.Error, code) {
		t.Errorf("expected %s denial, result=%+v err=%v", code, result, err)
	}
	if len(base.effects) != 0 {
		t.Errorf("denied tool performed side effects: %v", base.effects)
	}
	after, err := json.Marshal(struct {
		Pages  map[string]*types.WikiPage
		Issues []*types.WikiPageIssue
	}{base.pages, base.issues})
	if err != nil {
		t.Fatal(err)
	}
	if string(after) != string(before) {
		t.Error("denied tool mutated pages or issues")
	}
	if hasChecker && classifier != nil && !reflect.DeepEqual(lookup.calls, []string{"kb-target"}) {
		t.Errorf("KB lookups = %v, want only authoritative kb-target", lookup.calls)
	}
	if c, ok := classifier.(*writeGuardClassifier); ok && (c.kbID != "kb-target" || c.calls != 1) {
		t.Errorf("classified KB = %q calls=%d, want authoritative kb-target once", c.kbID, c.calls)
	}
}

func TestWikiWriteToolsPreserveUnmanagedBehavior(t *testing.T) {
	for _, test := range wikiWriteGuardCases() {
		t.Run(test.name, func(t *testing.T) {
			base := newWriteGuardWikiService()
			classifier := &writeGuardClassifier{
				role: managed.Role{Kind: managed.KindNone, State: managed.StateUnmanaged},
			}
			lookup := &writeGuardKBLookup{}
			service := managed.WrapWikiService(base, classifier, lookup)
			tool := test.tool(service, []string{"kb-first", "kb-target"}, NewWikiRouteResolver())
			ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(7))
			result, err := tool.Execute(ctx, json.RawMessage(test.args))
			if err != nil || result == nil || !result.Success {
				t.Fatalf("unmanaged write failed: result=%+v err=%v", result, err)
			}
			if classifier.kbID != "kb-target" || classifier.calls != 1 ||
				!reflect.DeepEqual(lookup.calls, []string{"kb-target"}) {
				t.Errorf(
					"wrong target: classified=%q calls=%d lookups=%v", classifier.kbID, classifier.calls, lookup.calls,
				)
			}
			if !reflect.DeepEqual(base.effects, test.want) {
				t.Errorf("effects = %v, want %v", base.effects, test.want)
			}
			assertUnmanagedWikiMutation(t, test.name, base)
		})
	}
}

func assertUnmanagedWikiMutation(t *testing.T, name string, service *writeGuardWikiService) {
	t.Helper()
	switch name {
	case "write-create":
		if page := service.pages["concept/new"]; page == nil || page.Content != "new text" || page.Title != "New" {
			t.Errorf("new page = %+v", page)
		}
	case "write-update":
		if page := service.pages["concept/target"]; page.Content != "new text" ||
			page.Title != "New" || page.Summary != "Summary" {
			t.Errorf("updated page = %+v", page)
		}
	case "replace-text":
		if got := service.pages["concept/target"].Content; got != "new text" {
			t.Errorf("replaced content = %q", got)
		}
	case "rename-page":
		if service.pages["concept/target"] != nil || service.pages["concept/renamed"] == nil {
			t.Error("rename did not move the page")
		}
		if got := service.pages["concept/referrer"].Content; got !=
			"See [[concept/renamed]] and [[concept/renamed|Target]]." {
			t.Errorf("renamed incoming links = %q", got)
		}
	case "delete-page":
		if service.pages["concept/target"] != nil {
			t.Error("deleted page is still present")
		}
		if got := service.pages["concept/referrer"].Content; got != "See target and Target." {
			t.Errorf("cleaned incoming links = %q", got)
		}
	case "flag-issue":
		if len(service.issues) != 2 || service.issues[1].Slug != "concept/target" ||
			service.issues[1].Status != "pending" {
			t.Errorf("flagged issues = %+v", service.issues)
		}
	case "update-issue":
		if got := service.issues[0].Status; got != "resolved" {
			t.Errorf("issue status = %q", got)
		}
	}
}
