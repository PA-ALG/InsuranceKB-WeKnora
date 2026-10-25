package confirm

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/google/uuid"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const (
	maxBatch   = 200
	maxOptions = 50
	maxTitle   = 200
	maxDetail  = 2000
	maxLabel   = 200
	maxNote    = 1000
)

var (
	subjectPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$`)
	optionPattern  = regexp.MustCompile(`^[a-z0-9][a-z0-9:._-]{0,127}$`)
)

// Service validates complete item batches, appends attributed answers and closes items once.
type Service struct {
	store Store
	clock func() time.Time
	ids   func() string
}

// ServiceOption configures the service clock or identifier generation.
type ServiceOption func(*Service)

// WithClock supplies creation, answer and closure timestamps.
func WithClock(clock func() time.Time) ServiceOption {
	return func(s *Service) {
		if clock != nil {
			s.clock = clock
		}
	}
}

// WithIDs supplies identifiers for items and answers.
func WithIDs(ids func() string) ServiceOption {
	return func(s *Service) {
		if ids != nil {
			s.ids = ids
		}
	}
}

// NewService connects item storage, defaulting to system time and random identifiers.
func NewService(store Store, opts ...ServiceOption) *Service {
	s := &Service{store: store, clock: time.Now, ids: uuid.NewString}
	for _, opt := range opts {
		opt(s)
	}
	return s
}

// Submit validates every item before inserting any; the same content is the same item.
func (s *Service) Submit(ctx context.Context, p release.Principal, spaceID string, in []ItemInput) ([]Item, error) {
	if err := checkAccess(p, spaceID); err != nil {
		return nil, err
	}
	items, err := validItems(in)
	if err != nil {
		return nil, err
	}
	if err := s.available(ctx); err != nil {
		return nil, err
	}
	now := s.clock()
	for i := range items {
		items[i].ID, items[i].SpaceID, items[i].CreatedBy, items[i].CreatedAt = s.ids(), spaceID, p.Subject, now
	}
	return s.store.InsertItems(ctx, p.TenantID, items)
}

// List returns the Space's items, open, closed or all, oldest first.
func (s *Service) List(ctx context.Context, p release.Principal, spaceID string, f Filter) ([]Item, error) {
	if err := checkAccess(p, spaceID); err != nil {
		return nil, err
	}
	if f.Status != "" && f.Status != "open" && f.Status != "closed" {
		return nil, failure(ErrorConfirmationInvalid, "status must be open or closed")
	}
	if err := s.available(ctx); err != nil {
		return nil, err
	}
	items, err := s.store.ListItems(ctx, p.TenantID, spaceID, f)
	if err != nil {
		return nil, err
	}
	out := make([]Item, len(items)) // never nil: an empty list encodes as []
	copy(out, items)
	sort.SliceStable(out, func(i, j int) bool {
		if !out[i].CreatedAt.Equal(out[j].CreatedAt) {
			return out[i].CreatedAt.Before(out[j].CreatedAt)
		}
		return out[i].ID < out[j].ID
	})
	return out, nil
}

// Answer appends a person's choice of one of the item's options.
func (s *Service) Answer(
	ctx context.Context, p release.Principal, spaceID, itemID, optionKey, note string,
) (Answer, error) {
	if err := checkAccess(p, spaceID); err != nil {
		return Answer{}, err
	}
	note = strings.TrimSpace(note)
	if utf8.RuneCountInString(note) > maxNote || !printable(note, true) {
		return Answer{}, failure(ErrorAnswerInvalid, "note is invalid")
	}
	item, err := s.item(ctx, p, spaceID, itemID)
	if err != nil {
		return Answer{}, err
	}
	if !offers(item, optionKey) {
		return Answer{}, failure(ErrorAnswerInvalid, "the answer is not one of the options")
	}
	if item.Closure != nil {
		return Answer{}, failure(ErrorConfirmationClosed, "the item is closed")
	}
	a := Answer{
		ID: s.ids(), ItemID: item.ID, OptionKey: optionKey, Note: note,
		Answerer: p.Subject, AnsweredAt: s.clock(),
	}
	if err := ctx.Err(); err != nil {
		return Answer{}, err
	}
	if err := s.store.AppendAnswer(ctx, p.TenantID, spaceID, a); err != nil {
		return Answer{}, err
	}
	return a, nil
}

// Close ends an item once: applied names the latest answer, obsolete names none.
func (s *Service) Close(
	ctx context.Context, p release.Principal, spaceID, itemID, reason, answerID string,
) (Closure, error) {
	if err := checkAccess(p, spaceID); err != nil {
		return Closure{}, err
	}
	if (reason != "applied" && reason != "obsolete") || (reason == "applied") != (answerID != "") {
		return Closure{}, failure(ErrorConfirmationInvalid, "an applied closure names its answer, an obsolete one none")
	}
	item, err := s.item(ctx, p, spaceID, itemID)
	if err != nil {
		return Closure{}, err
	}
	if item.Closure != nil {
		return Closure{}, failure(ErrorConfirmationClosed, "the item is closed")
	}
	if reason == "applied" && (item.Answer == nil || item.Answer.ID != answerID) {
		return Closure{}, failure(ErrorAnswerStale, "the answer is not the latest one")
	}
	c := Closure{Reason: reason, AnswerID: answerID, ClosedBy: p.Subject, ClosedAt: s.clock()}
	if err := ctx.Err(); err != nil {
		return Closure{}, err
	}
	if err := s.store.CloseItem(ctx, p.TenantID, spaceID, item.ID, c); err != nil {
		return Closure{}, err
	}
	return c, nil
}

func (s *Service) item(ctx context.Context, p release.Principal, spaceID, itemID string) (Item, error) {
	if err := s.available(ctx); err != nil {
		return Item{}, err
	}
	item, found, err := s.store.ItemByID(ctx, p.TenantID, spaceID, itemID)
	if err != nil {
		return Item{}, err
	}
	if !found {
		return Item{}, failure(ErrorConfirmationNotFound, "the item was not found")
	}
	return item, nil
}

func validItems(in []ItemInput) ([]Item, error) {
	if len(in) == 0 || len(in) > maxBatch {
		return nil, failure(ErrorConfirmationInvalid, "a batch holds 1 to 200 items")
	}
	seen := map[string]bool{}
	out := make([]Item, 0, len(in))
	for _, raw := range in {
		item, ok := validItem(raw)
		if !ok {
			return nil, failure(ErrorConfirmationInvalid, "an item is invalid")
		}
		identity := item.Subject + "\x00" + item.Revision + "\x00" + item.ContentDigest
		if seen[identity] {
			return nil, failure(ErrorConfirmationInvalid, "an item appears twice in the batch")
		}
		seen[identity] = true
		out = append(out, item)
	}
	return out, nil
}

func validItem(raw ItemInput) (Item, bool) {
	title, detail := strings.TrimSpace(raw.Title), strings.TrimSpace(raw.Detail)
	if !subjectPattern.MatchString(raw.Subject) || !subjectPattern.MatchString(raw.Revision) ||
		title == "" || utf8.RuneCountInString(title) > maxTitle || !printable(title, false) ||
		utf8.RuneCountInString(detail) > maxDetail || !printable(detail, true) ||
		len(raw.Options) == 0 || len(raw.Options) > maxOptions {
		return Item{}, false
	}
	options := make([]Option, 0, len(raw.Options))
	keys := map[string]bool{}
	for _, o := range raw.Options {
		label := strings.TrimSpace(o.Label)
		if !optionPattern.MatchString(o.Key) || keys[o.Key] || label == "" ||
			utf8.RuneCountInString(label) > maxLabel || !printable(label, false) {
			return Item{}, false
		}
		keys[o.Key] = true
		options = append(options, Option{Key: o.Key, Label: label})
	}
	item := Item{Subject: raw.Subject, Revision: raw.Revision, Title: title, Detail: detail, Options: options}
	item.ContentDigest = contentDigest(item)
	return item, true
}

// contentDigest is the SHA-256 of the canonical JSON of title, detail and options: struct fields
// encode in declaration order, so the digest depends on the content and its option order only.
func contentDigest(item Item) string {
	type canonical struct {
		Detail  string   `json:"detail"`
		Options []Option `json:"options"`
		Title   string   `json:"title"`
	}
	data, _ := json.Marshal(canonical{Detail: item.Detail, Options: item.Options, Title: item.Title})
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func printable(text string, newlines bool) bool {
	if !utf8.ValidString(text) {
		return false
	}
	for _, r := range text {
		if unicode.IsControl(r) && (!newlines || r != '\n') {
			return false
		}
	}
	return true
}

func offers(item Item, key string) bool {
	for _, o := range item.Options {
		if o.Key == key {
			return true
		}
	}
	return false
}

func checkAccess(p release.Principal, spaceID string) error {
	if p.TenantID == 0 || strings.TrimSpace(p.Subject) == "" || strings.TrimSpace(spaceID) == "" {
		return failure(release.ErrorReleaseAccessDenied, "tenant, subject and Space are required")
	}
	return nil
}

func (s *Service) available(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if s == nil || s.store == nil {
		return failure(release.ErrorServiceUnavailable, "confirmations are not configured")
	}
	return nil
}

func failure(code, detail string) error { return &release.Error{Code: code, Detail: detail} }
