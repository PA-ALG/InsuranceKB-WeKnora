package handler

import (
	"context"
	"errors"
	"net/http"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

type entityPageGraphHTTPService830G1 interface {
	ReadCurrentEntityPage830G1(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		service.EntityPageGraphSelector830G1,
	) (*service.EntityPageGraphRead830G1, error)
	ReadPinnedEntityPage830G1(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		service.EntityPageGraphSelector830G1,
	) (*service.EntityPageGraphRead830G1, error)
	ReadPreparationEntityPage830G1(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		service.EntityPageGraphSelector830G1,
	) (*service.EntityPageGraphRead830G1, error)
}

type EntityPageGraphHandler830G1 struct {
	service entityPageGraphHTTPService830G1
}

func NewEntityPageGraphHandler830G1(schemaHandler *SchemaWikiHandler) *EntityPageGraphHandler830G1 {
	handler := &EntityPageGraphHandler830G1{}
	if schemaHandler == nil || schemaHandler.schemaService == nil {
		return handler
	}
	source, ok := schemaHandler.schemaService.(service.EntityPageGraphReleaseSource830G1)
	if !ok {
		return handler
	}
	handler.service = service.NewEntityPageGraphService830G1(source)
	return handler
}

func (h *EntityPageGraphHandler830G1) ReadOverview(c *gin.Context) {
	h.read(c, "overview", "overview")
}

func (h *EntityPageGraphHandler830G1) ReadSection(c *gin.Context) {
	h.read(c, "section", strings.TrimSpace(c.Param("section_key")))
}

func (h *EntityPageGraphHandler830G1) ReadField(c *gin.Context) {
	h.read(c, "field", strings.TrimSpace(c.Param("field_key")))
}

func (h *EntityPageGraphHandler830G1) ReadFreeWiki(c *gin.Context) {
	h.read(c, "free_wiki", "free-wiki")
}

func (h *EntityPageGraphHandler830G1) read(c *gin.Context, pageKind, stableKey string) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	if err != nil {
		writeEntityPageGraphError830G1(c, service.ErrEntityPageGraphForbidden830G1)
		return
	}
	if h == nil || h.service == nil {
		writeEntityPageGraphError830G1(c, service.ErrEntityPageGraphIntegrity830G1)
		return
	}
	selector := service.EntityPageGraphSelector830G1{
		EntityID:  strings.TrimSpace(c.Param("entity_id")),
		PageKind:  pageKind,
		StableKey: stableKey,
	}
	query := c.Request.URL.Query()
	releaseIDs, hasReleaseID := query["release_id"]
	preparationIDs, hasPreparationID := query["preparation_id"]
	var read *service.EntityPageGraphRead830G1
	if len(query) == 0 {
		read, err = h.service.ReadCurrentEntityPage830G1(c.Request.Context(), principal, scope, selector)
	} else if len(query) == 1 && hasReleaseID && !hasPreparationID {
		if len(releaseIDs) != 1 || releaseIDs[0] == "" || releaseIDs[0] != strings.TrimSpace(releaseIDs[0]) ||
			strings.EqualFold(releaseIDs[0], "current") || strings.EqualFold(releaseIDs[0], "latest") {
			writeEntityPageGraphError830G1(c, service.ErrEntityPageGraphIntegrity830G1)
			return
		}
		releaseID := releaseIDs[0]
		read, err = h.service.ReadPinnedEntityPage830G1(c.Request.Context(), principal, scope, releaseID, selector)
	} else if len(query) == 1 && hasPreparationID && !hasReleaseID {
		if len(preparationIDs) != 1 || preparationIDs[0] == "" ||
			preparationIDs[0] != strings.TrimSpace(preparationIDs[0]) ||
			strings.EqualFold(preparationIDs[0], "current") ||
			strings.EqualFold(preparationIDs[0], "latest") {
			writeEntityPageGraphError830G1(c, service.ErrEntityPageGraphIntegrity830G1)
			return
		}
		read, err = h.service.ReadPreparationEntityPage830G1(
			c.Request.Context(), principal, scope, preparationIDs[0], selector,
		)
	} else {
		writeEntityPageGraphError830G1(c, service.ErrEntityPageGraphIntegrity830G1)
		return
	}
	if err != nil {
		writeEntityPageGraphError830G1(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": read})
}

func writeEntityPageGraphError830G1(c *gin.Context, err error) {
	status := http.StatusServiceUnavailable
	code := "ENTITY_PAGE_GRAPH_INTEGRITY_FAILURE"
	message := "entity page graph integrity failure"
	switch {
	case errors.Is(err, service.ErrEntityPageGraphNotFound830G1):
		status = http.StatusNotFound
		code = "ENTITY_PAGE_GRAPH_NOT_FOUND"
		message = "entity page graph not found"
	case errors.Is(err, service.ErrEntityPageGraphForbidden830G1):
		status = http.StatusForbidden
		code = "ENTITY_PAGE_GRAPH_FORBIDDEN"
		message = "entity page graph forbidden"
	}
	c.JSON(status, gin.H{
		"success": false,
		"error":   gin.H{"code": code, "message": message},
	})
}
