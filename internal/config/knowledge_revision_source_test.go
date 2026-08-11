package config

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestKnowledgeRevisionSourceConfigRejectsNegativeObjectLimit(t *testing.T) {
	require.Error(t, ValidateConfig(&Config{
		KnowledgeRevisionSource: &KnowledgeRevisionSourceConfig{MaxObjectBytes: -1},
	}))
	require.NoError(t, ValidateConfig(&Config{
		KnowledgeRevisionSource: &KnowledgeRevisionSourceConfig{
			BackfillEnabled: true,
			MaxObjectBytes:  128 << 20,
		},
	}))
}
