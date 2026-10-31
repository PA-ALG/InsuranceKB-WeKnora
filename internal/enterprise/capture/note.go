package capture

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

// NoteContract names the layout of a capture note: why one parse of one revision was not captured
// (S11f). It is part of every note key, so a note can never open as a capture or the other way round.
const NoteContract = "enterprise-capture-note.v1"

// note is the signed payload of a capture note. Only typed fields: never parser text.
type note struct {
	Contract string   `json:"contract"`
	Identity Identity `json:"identity"`
	Reason   string   `json:"reason"`
	Page     int      `json:"page_number,omitempty"`
}

// notes keeps notes beside the captures, in "<root>-notes": the capture directory itself only ever
// holds captures (a scanned PDF writes no first-parse record, S4c-2c §3.3).
func (s *Store) notes() *Store { return &Store{root: s.root + "-notes", keys: s.keys} }

func noteKey(id Identity) (string, error) {
	if _, err := Key(id); err != nil {
		return "", err
	}
	data, err := canonicalJSON(id)
	if err != nil {
		return "", err
	}
	return "note-" + sha256Hex(append([]byte(NoteContract+"\x00"), data...)), nil
}

// A note records a cause found while parsing; the other reasons are decided when reading.
func validNote(reason string, page int) bool {
	switch reason {
	case source.NotCapturedScannedPage:
		return page >= 1
	case source.NotCapturedOfficeUnreadable:
		return page == 0
	}
	return false
}

// SaveNote records why this parse was not captured. Like a capture it is written once: the same
// note again succeeds, a different one under the same identity fails.
func (s *Store) SaveNote(id Identity, reason string, page int) error {
	if s == nil || !validNote(reason, page) {
		return ErrUnavailable
	}
	key, err := noteKey(id)
	if err != nil {
		return err
	}
	data, err := json.Marshal(note{Contract: NoteContract, Identity: id, Reason: reason, Page: page})
	if err != nil {
		return err
	}
	notes := s.notes()
	existing, err := notes.readSealed(key)
	if err == nil {
		if !bytes.Equal(existing, data) {
			return ErrUnavailable
		}
		return nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return notes.publish(key, data)
}

// readNote returns the verified note of one parse; a missing note is os.ErrNotExist.
func (s *Store) readNote(id Identity) (*source.NotCaptured, error) {
	key, err := noteKey(id)
	if err != nil {
		return nil, err
	}
	data, err := s.notes().readSealed(key)
	if err != nil {
		return nil, err
	}
	var n note
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&n) != nil || !atEOF(decoder) || n.Contract != NoteContract || n.Identity != id ||
		!validNote(n.Reason, n.Page) {
		return nil, ErrUnavailable
	}
	return &source.NotCaptured{Reason: n.Reason, Page: n.Page}, nil
}

// notCaptured explains a missing capture: the parse-time note if there is one, otherwise whether the
// file type is captured at all. A note that fails verification fails closed.
func notCaptured(store *Store, id Identity, fileType string) error {
	reason, err := store.readNote(id)
	switch {
	case err == nil:
		return reason
	case errors.Is(err, os.ErrNotExist):
		if strings.EqualFold(strings.TrimSpace(fileType), "pdf") || ooxml.Supports(fileType) {
			return &source.NotCaptured{Reason: source.NotCapturedNotRecorded}
		}
		return &source.NotCaptured{Reason: source.NotCapturedUnsupportedFormat}
	case errors.Is(err, ErrUnavailable):
		return &source.Error{Code: source.ErrorIntegrity, Detail: "capture note failed integrity verification"}
	default:
		return err
	}
}
