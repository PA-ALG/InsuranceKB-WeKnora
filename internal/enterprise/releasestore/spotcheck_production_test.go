package releasestore

import (
	"testing"

	"github.com/stretchr/testify/require"
	"go.uber.org/dig"
	"gorm.io/gorm"

	appservice "github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/spotcheck"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

func TestRegisterDisablesSpotChecksWithPublishing(t *testing.T) {
	t.Setenv(SpacesEnv, "")
	container := dig.New()
	require.NoError(t, container.Provide(func() *config.Config { return &config.Config{} }))
	require.NoError(t, container.Provide(func() *gorm.DB { return &gorm.DB{} }))
	require.NoError(t, container.Provide(func() interfaces.KnowledgeRepository { return nil }))
	require.NoError(t, container.Provide(func() *appservice.G3FirstParseStore { return nil }))
	require.NoError(t, Register(container))
	require.NoError(t, container.Invoke(func(service *spotcheck.Service) {
		require.Nil(t, service)
	}))
}
