package expert

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
	"time"
)

// refPrefix marks evidence references that cite an expert revision record rather than a
// source file: expert:v1:<revision id>:<record sha256>.
const refPrefix = "expert:v1:"

// LocatorKind is the contract locator kind of an expert revision citation.
const LocatorKind = "EXPERT_REVISION"

// SourceRef is the evidence reference of a revision record.
func SourceRef(r Revision) string { return refPrefix + r.ID + ":" + r.RecordSHA256 }

// ParseSourceRef splits an expert reference; ok is false for any other reference.
func ParseSourceRef(ref string) (id, sha string, ok bool) {
	rest, found := strings.CutPrefix(ref, refPrefix)
	if !found {
		return "", "", false
	}
	cut := strings.LastIndex(rest, ":")
	if cut <= 0 || cut == len(rest)-1 {
		return "", "", false
	}
	id, sha = rest[:cut], rest[cut+1:]
	if len(sha) != 64 || strings.ContainsAny(id, " \t\n") {
		return "", "", false
	}
	if _, err := hex.DecodeString(sha); err != nil {
		return "", "", false
	}
	return id, strings.ToLower(sha), true
}

// recordDigest is the SHA-256 of the contract ExpertRevision object of a record, encoded the
// way the release package digests JSON (decode into any, encode with sorted keys).
func recordDigest(r Revision) string {
	before, _ := json.Marshal(r.Before)
	after, _ := json.Marshal(r.After)
	contract := map[string]any{
		"revision_record_id": r.ID,
		"actor":              r.Actor,
		"role":               r.Role,
		"recorded_at":        r.RecordedAt.UTC().Format(time.RFC3339Nano),
		"target":             r.MemberSlug,
		"before":             string(before),
		"after":              string(after),
		"reason":             r.Reason,
		"attachments":        []string{},
	}
	raw, _ := json.Marshal(contract)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// citedQuote is the text an expert citation quotes: the new value, or for an explicit absence
// the reason the expert gave. Unknown edits carry no citation.
func citedQuote(r Revision) string {
	if r.After.State == "present" {
		if text, ok := r.After.Value.(string); ok {
			return text
		}
		return ""
	}
	return r.Reason
}
