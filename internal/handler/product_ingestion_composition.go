package handler

import (
	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/config"
	"time"
)

func NewConfiguredProductIngestionHandler(cfg *config.Config, knowledge *KnowledgeHandler) (*ProductIngestionHandler, error) {
	if cfg == nil || cfg.ProductIngestion == nil || !cfg.ProductIngestion.Enabled {
		return NewProductIngestionHandler(knowledge, nil), nil
	}
	binding := cfg.ProductIngestion
	bridge, err := service.NewProductIngestionHTTPBridge(service.ProductIngestionBridgeOptions{
		BaseURL: binding.BaseURL, Credential: binding.Credential,
		Scope: service.ProductIngestionScope{TenantID: binding.TenantID, SpaceID: binding.SpaceID,
			RawKnowledgeBaseID: binding.RawKBID, WikiKnowledgeBaseID: binding.WikiKBID},
		Timeout:          time.Duration(binding.TimeoutSeconds) * time.Second,
		MaxResponseBytes: binding.MaxResponseBytes, MaxUploadFiles: binding.MaxUploadFiles,
		MaxUploadBytes: binding.MaxUploadBytes,
	})
	if err != nil {
		return nil, err
	}
	return NewProductIngestionHandler(knowledge, bridge), nil
}
