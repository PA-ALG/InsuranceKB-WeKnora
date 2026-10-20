package releasestore

import (
	"context"
	"testing"

	appservice "github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/stretchr/testify/require"
)

func TestEnterpriseCitationPagesRequireCaptureServiceAndConfiguredSpace(t *testing.T) {
	spaces, err := ParseSpaces(oneSpace)
	require.NoError(t, err)
	require.Nil(t, enterprisePages(spaces, nil, nil))

	pages := enterprisePages(spaces, nil, &appservice.G3FirstParseStore{})
	require.NotNil(t, pages)
	for _, scope := range []source.Scope{
		{TenantID: 7, SpaceID: "outside"},
		{TenantID: 8, SpaceID: "space-1"},
	} {
		_, err := pages.Pages(context.Background(), scope, "source", 1)
		var missing *source.Error
		require.ErrorAs(t, err, &missing)
		require.Equal(t, source.ErrorSourceNotFound, missing.Code, "unconfigured scope must not fall back to G3")
	}
}
