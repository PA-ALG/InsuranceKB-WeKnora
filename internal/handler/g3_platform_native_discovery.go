package handler

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/service"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/gin-gonic/gin"
)

type G3PlatformNativeDiscoveryProducer interface {
	Process(context.Context, types.WikiReleaseScope, string, int64, service.G3NativeDiscoveryRequest) (*service.G3SignedNativeDiscoverySnapshot, error)
}

// NativeDiscovery is a pure producer adapter. The source capturer repeats
// machine authorization/current custody before any plan or snapshot is signed.
func (h *G3PlatformSnapshotsHandler) NativeDiscovery(c *gin.Context) {
	_, scope, ok := h.request(c, h != nil && h.native != nil)
	if !ok {
		return
	}
	knowledgeID := c.Param("knowledge_id")
	attempt, err := strconv.ParseInt(c.Param("attempt"), 10, 64)
	if err != nil || attempt <= 0 || !validG3PlatformPathID(knowledgeID) {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	raw, err := io.ReadAll(http.MaxBytesReader(c.Writer, c.Request.Body, 5<<20))
	if err != nil {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	canonical, err := types.CanonicalConceptMemberPayload830G2(raw)
	if err != nil {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	var request service.G3NativeDiscoveryRequest
	decoder := json.NewDecoder(strings.NewReader(string(canonical)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&request) != nil {
		writeG3PlatformSnapshotError(c, errG3PlatformSnapshotInvalidRequest)
		return
	}
	result, err := h.native.Process(c.Request.Context(), scope, knowledgeID, attempt, request)
	if err != nil || result == nil {
		if errors.Is(err, service.ErrG3NativeDiscoveryInvalid) {
			err = errG3PlatformSnapshotInvalidRequest
		}
		writeG3PlatformSnapshotError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": result})
}
