package service

import (
	"context"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

type conceptManagedClassifier struct {
	role   managed.Role
	err    error
	calls  int
	tenant uint64
	kb     string
}

func (c *conceptManagedClassifier) Classify(_ context.Context, tenant uint64, kb string) (managed.Role, error) {
	c.calls++
	c.tenant = tenant
	c.kb = kb
	return c.role, c.err
}

func TestConceptAgentUsesInjectedCustodyClassification(t *testing.T) {
	for _, tc := range []struct {
		name string
		role managed.Role
		err  error
		deny bool
		raw  bool
	}{
		{name: "unmanaged", role: managed.Role{Kind: managed.KindNone, State: managed.StateUnmanaged}},
		{name: "pending wiki", role: managed.Role{Kind: managed.KindWiki, State: managed.StatePending}, deny: true},
		{name: "pending raw", role: managed.Role{Kind: managed.KindRaw, State: managed.StatePending}, raw: true},
		{name: "active raw", role: managed.Role{Kind: managed.KindRaw, State: managed.StateActive}, raw: true},
		{name: "classification failure", err: errors.New("custody unavailable"), deny: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := newWikiReleaseFixture(t, WikiReleaseFaults{})
			c := &conceptManagedClassifier{role: tc.role, err: tc.err}
			reader := NewConceptAgentService830G2(f.service, &conceptAgentKBServiceStub830G2{}, nil)
			reader.WithManagedClassifier(c)
			principal := types.Principal{Type: types.PrincipalWebUser, ID: "reader"}
			ctx := context.WithValue(types.WithPrincipal(context.Background(), principal),
				types.TenantIDContextKey, f.scope.TenantID)
			turn, err := reader.PinConceptAgentTurn830G2(ctx, conceptAgentWikiScopes830G2(f.scope))
			require.Equal(t, 1, c.calls)
			require.Equal(t, f.scope.TenantID, c.tenant)
			require.Equal(t, f.scope.WikiKBID, c.kb)
			if tc.deny {
				require.ErrorIs(t, err, ErrWikiReleaseAccessDenied)
				require.Nil(t, turn)
				return
			}
			require.NoError(t, err)
			require.Empty(t, turn.Releases)
			if tc.raw {
				require.Equal(t, []string{f.scope.WikiKBID}, turn.ManagedSourceKBIDs)
			} else {
				require.Empty(t, turn.ManagedSourceKBIDs)
			}
		})
	}
}
