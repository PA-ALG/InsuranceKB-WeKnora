package handler

import (
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/stretchr/testify/require"
	"testing"
)

func TestConfiguredProductIngestionRequiresExplicitScopeAndKeepsDefaultDisabled(t *testing.T) {
	disabled, err := NewConfiguredProductIngestionHandler(&config.Config{}, &KnowledgeHandler{})
	require.NoError(t, err)
	require.Nil(t, disabled.bridge)
	_, err = NewConfiguredProductIngestionHandler(&config.Config{
		ProductIngestion: &config.ProductIngestionConfig{Enabled: true},
	}, &KnowledgeHandler{})
	require.Error(t, err)
	configured, err := NewConfiguredProductIngestionHandler(&config.Config{
		ProductIngestion: &config.ProductIngestionConfig{Enabled: true,
			BaseURL: "http://harness-api:8090", Credential: "fixture-service-key",
			TenantID: 1, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki",
			TimeoutSeconds: 15, MaxResponseBytes: 1048576, MaxUploadFiles: 100, MaxUploadBytes: 52428800},
	}, &KnowledgeHandler{})
	require.NoError(t, err)
	require.Equal(t, "wiki", configured.bridge.Scope().WikiKnowledgeBaseID)
}
