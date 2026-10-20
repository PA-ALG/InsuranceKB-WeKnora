package container

import (
	"testing"

	"github.com/Tencent/WeKnora/internal/mcpserver"
	"github.com/stretchr/testify/require"
	"go.uber.org/dig"
)

func TestProductionMCPKnowledgeDependenciesResolve(t *testing.T) {
	t.Setenv("REDIS_ADDR", "")
	c := BuildContainer(dig.New(dig.DryRun(true)))
	require.NoError(t, c.Invoke(func(*mcpserver.Server) {}))
}
