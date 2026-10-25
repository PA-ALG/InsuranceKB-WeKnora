// Package confirm records items a person has to decide: the submitter offers options as opaque
// text, a person picks one, answers only append, and the submitter closes an item once. Nothing
// here interprets a title, detail, option key or label (S5b-3a Spec).
package confirm

import (
	"context"
	"time"
)

const (
	// ErrorConfirmationInvalid identifies an invalid item batch, list filter or closure.
	ErrorConfirmationInvalid = "CONFIRMATION_INVALID"
	// ErrorConfirmationNotFound hides missing items and items outside the caller's scope.
	ErrorConfirmationNotFound = "CONFIRMATION_NOT_FOUND"
	// ErrorAnswerInvalid identifies an answer that is not one of the item's options.
	ErrorAnswerInvalid = "ANSWER_INVALID"
	// ErrorConfirmationClosed rejects answers and closures once an item is closed.
	ErrorConfirmationClosed = "CONFIRMATION_CLOSED"
	// ErrorAnswerStale rejects applying an answer a person has since replaced.
	ErrorAnswerStale = "ANSWER_STALE"
)

// Option is one choice the submitter offers, as an opaque key and display label.
type Option struct {
	Key   string `json:"key"`
	Label string `json:"label"`
}

// Item is one decision a person has to make about a submitter's subject revision.
type Item struct {
	ID            string    `json:"id"`
	SpaceID       string    `json:"space_id"`
	Subject       string    `json:"subject"`
	Revision      string    `json:"revision"`
	ContentDigest string    `json:"content_digest"`
	Title         string    `json:"title"`
	Detail        string    `json:"detail"`
	Options       []Option  `json:"options"`
	CreatedBy     string    `json:"created_by"`
	CreatedAt     time.Time `json:"created_at"`
	Answer        *Answer   `json:"answer,omitempty"`
	Closure       *Closure  `json:"closure,omitempty"`
}

// Answer is an append-only, attributed choice of one option.
type Answer struct {
	ID         string    `json:"id"`
	ItemID     string    `json:"item_id"`
	OptionKey  string    `json:"option_key"`
	Note       string    `json:"note"`
	Answerer   string    `json:"answerer"`
	AnsweredAt time.Time `json:"answered_at"`
}

// Closure ends an item once: applied (naming the answer applied) or obsolete.
type Closure struct {
	Reason   string    `json:"reason"`
	AnswerID string    `json:"answer_id,omitempty"`
	ClosedBy string    `json:"closed_by"`
	ClosedAt time.Time `json:"closed_at"`
}

// ItemInput is what a submitter sends for one item.
type ItemInput struct {
	Subject, Revision, Title, Detail string
	Options                          []Option
}

// Filter restricts items to open or closed ones.
type Filter struct{ Status string }

// Store isolates every record by tenant and Space; failures are *release.Error codes.
type Store interface {
	// InsertItems keeps existing (tenant, Space, subject, revision, content digest) records,
	// including concurrent inserts, and returns the stored items in input order.
	InsertItems(ctx context.Context, tenantID uint64, items []Item) ([]Item, error)
	// ListItems includes each item's latest answer (by append order) and its closure,
	// ordered by CreatedAt, then ID.
	ListItems(ctx context.Context, tenantID uint64, spaceID string, f Filter) ([]Item, error)
	ItemByID(ctx context.Context, tenantID uint64, spaceID, id string) (Item, bool, error)
	// AppendAnswer fails with CONFIRMATION_CLOSED once the item is closed.
	AppendAnswer(ctx context.Context, tenantID uint64, spaceID string, a Answer) error
	// CloseItem closes once (CONFIRMATION_CLOSED afterwards); an applied closure fails with
	// ANSWER_STALE unless its answer is the item's latest one, judged atomically.
	CloseItem(ctx context.Context, tenantID uint64, spaceID, itemID string, c Closure) error
}
