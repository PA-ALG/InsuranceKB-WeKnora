package handler

import (
	"context"
	"net/http"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

type conceptFreeWikiHTTPService830G2 interface {
	ReadConceptPage830G2(
		context.Context,
		types.WikiReleasePrincipal,
		types.WikiReleaseScope,
		string,
		string,
	) (*service.ConceptPageRead830G2, error)
}

type ConceptFreeWikiHandler830G2 struct {
	service conceptFreeWikiHTTPService830G2
}

func NewConceptFreeWikiHandler830G2(source any) *ConceptFreeWikiHandler830G2 {
	var reader conceptFreeWikiHTTPService830G2
	switch value := source.(type) {
	case conceptFreeWikiHTTPService830G2:
		reader = value
	case *SchemaWikiHandler:
		if value != nil {
			reader, _ = value.schemaService.(conceptFreeWikiHTTPService830G2)
		}
	}
	return &ConceptFreeWikiHandler830G2{service: reader}
}

func (h *ConceptFreeWikiHandler830G2) ReadPage(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	memberID := strings.TrimSpace(c.Param("member_id"))
	if err != nil || memberID == "" {
		if err == nil {
			err = service.ErrWikiReleaseNotFound
		}
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.service == nil {
		writeSchemaWikiError(c, service.ErrNoSchemaWikiActiveRelease)
		return
	}
	read, err := h.service.ReadConceptPage830G2(
		c.Request.Context(), principal, scope, memberID,
		strings.TrimSpace(c.Query("release_id")),
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": read})
}

func (h *ConceptFreeWikiHandler830G2) PreviewCitation(c *gin.Context) {
	principal, scope, err := (&WikiReleaseHandler{}).requestIdentity(c)
	memberID := strings.TrimSpace(c.Param("member_id"))
	citationID := strings.TrimSpace(c.Param("citation_id"))
	releaseID := strings.TrimSpace(c.Query("release_id"))
	if err != nil || memberID == "" || citationID == "" || releaseID == "" {
		if err == nil {
			err = service.ErrSchemaWikiCitationUnavailable
		}
		writeSchemaWikiError(c, err)
		return
	}
	if h == nil || h.service == nil {
		writeSchemaWikiError(c, service.ErrSchemaWikiCitationUnavailable)
		return
	}
	read, err := h.service.ReadConceptPage830G2(
		c.Request.Context(), principal, scope, memberID, releaseID,
	)
	if err != nil {
		writeSchemaWikiError(c, err)
		return
	}
	for _, citation := range read.Citations {
		if citation.CitationID == citationID {
			writeSchemaWikiError(c, service.ErrSchemaWikiCitationUnavailable)
			return
		}
	}
	writeSchemaWikiError(c, service.ErrWikiReleaseNotFound)
}
