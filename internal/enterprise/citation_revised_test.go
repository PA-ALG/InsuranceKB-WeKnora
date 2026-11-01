package enterprise_test

// SK-3 acceptance (Spec docs/design/slices/SK-3-销售方法阅读与问答.md §4.3): PDF and Office citations
// carry source.revised_at, the time the cited revision was read completely (RFC 3339, UTC), and omit
// it when the capture does not know it. Protected file: written by Claude. Reuses the citation worlds.
// RED until SK-3.

import (
	"net/http"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestCitationsCarryTheRevisionTimeOfTheirSource(t *testing.T) {
	revised := time.Date(2026, 10, 29, 16, 30, 0, 0, time.FixedZone("UTC+8", 8*3600))

	world := newCitationWorld(t)
	world.pages.artifact.RevisedAt = revised
	w := get(world.router(t, machineKey()), citation("1828/waiting_period", "0"))
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	require.Equal(t, "2026-10-29T08:30:00Z", data(t, w.Body.Bytes())["source"].(map[string]any)["revised_at"])

	deck := deckArtifact(t)
	deck.RevisedAt = revised
	office := officeWorld(t, deck, officeEvidence(slideOne, 1, 6, 11, "保障𠮷全面"))
	w = get(office.router(t, machineKey()), citation("1828/highlights", "0"))
	require.Equal(t, http.StatusOK, w.Code, w.Body.String())
	require.Equal(t, "2026-10-29T08:30:00Z", data(t, w.Body.Bytes())["source"].(map[string]any)["revised_at"])

	plain := newCitationWorld(t)
	w = get(plain.router(t, machineKey()), citation("1828/waiting_period", "0"))
	require.NotContains(t, data(t, w.Body.Bytes())["source"], "revised_at", "an unknown time is left out")
}
