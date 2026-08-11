package container

import (
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestContainerWiresKnowledgeRevisionSourceServiceAndHandler(t *testing.T) {
	raw, err := os.ReadFile("container.go")
	require.NoError(t, err)
	source := string(raw)
	require.Contains(t, source, "container.Provide(service.NewKnowledgeRevisionSourceService)")
	require.Contains(t, source, "container.Provide(handler.NewKnowledgeRevisionSourceHandler)")
}
