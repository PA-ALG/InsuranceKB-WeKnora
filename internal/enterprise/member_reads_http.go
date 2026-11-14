package enterprise

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/gin-gonic/gin"
)

func mountMemberReads(r gin.IRouter, service *release.Service) {
	r.GET("/releases/active/summary", func(c *gin.Context) {
		p, ok := publishingRequest(c, service)
		if !ok {
			return
		}
		out, err := service.ActiveSummary(c.Request.Context(), p, c.Param("space_id"))
		memberReadReply(c, headerData(out), err, maxControlBody)
	})
	r.GET("/releases/:release_id/member-index", func(c *gin.Context) {
		p, ok := publishingRequest(c, service)
		if !ok {
			return
		}
		h, members, err := service.FixedMemberIndex(c.Request.Context(), p, c.Param("space_id"), c.Param("release_id"))
		data := headerData(h)
		if err == nil {
			if len(members) > release.MaxMemberIndex {
				err = release.MemberReadLimit()
			} else {
				data["members"], err = indexEntries(members)
			}
		}
		memberReadReply(c, data, err, release.MaxMemberReadBytes)
	})
	r.POST("/releases/:release_id/member-lookup", func(c *gin.Context) {
		p, ok := publishingRequest(c, service)
		if !ok {
			return
		}
		slugs, err := lookupSlugs(c.Request.Body)
		if err != nil {
			writeError(c, err)
			return
		}
		h, members, err := service.FixedMemberLookup(
			c.Request.Context(), p, c.Param("space_id"), c.Param("release_id"), slugs,
		)
		data := headerData(h)
		if err == nil {
			data["members"], data["missing"] = members, missingSlugs(slugs, members)
		}
		memberReadReply(c, data, err, release.MaxMemberReadBytes)
	})
}

type indexEntry struct {
	Slug       string `json:"logical_slug"`
	Digest     string `json:"member_digest"`
	Kind       string `json:"kind"`
	Subject    string `json:"subject_ref,omitempty"`
	LogicalKey string `json:"logical_key,omitempty"`
	Entity     string `json:"entity_id,omitempty"`
}

func indexEntries(members []release.Member) ([]indexEntry, error) {
	out := make([]indexEntry, 0, len(members))
	for _, m := range members {
		var fields struct {
			Subject    string `json:"subject_ref"`
			LogicalKey string `json:"logical_key"`
			Entity     string `json:"entity_id"`
		}
		if err := json.Unmarshal(m.Payload, &fields); err != nil {
			return nil, err
		}
		out = append(out, indexEntry{
			Slug: m.LogicalSlug, Digest: m.MemberDigest, Kind: m.Kind,
			Subject: fields.Subject, LogicalKey: fields.LogicalKey, Entity: fields.Entity,
		})
	}
	return out, nil
}

func headerData(r release.Release) gin.H {
	out := gin.H{
		"id": r.ID, "epoch": r.Epoch, "base_release_id": r.BaseReleaseID,
		"candidate_id": r.CandidateID, "decision_digest": r.DecisionDigest,
	}
	if r.RetiredAt != nil {
		out["retired_at"] = r.RetiredAt
	}
	return out
}

func memberReadReply(c *gin.Context, data gin.H, err error, limit int) {
	if err != nil {
		writeError(c, err)
		return
	}
	raw, err := json.Marshal(gin.H{"success": true, "data": data})
	if err != nil {
		writeError(c, err)
		return
	}
	if len(raw) > limit {
		writeError(c, release.MemberReadLimit())
		return
	}
	c.Header("Cache-Control", "private, no-store")
	c.Data(http.StatusOK, "application/json; charset=utf-8", raw)
}

func lookupSlugs(reader io.Reader) ([]string, error) {
	invalid := &release.Error{Code: release.ErrorInvalidRequest, Detail: "invalid member lookup body"}
	raw, err := io.ReadAll(io.LimitReader(reader, maxControlBody+1))
	if err != nil || len(raw) > maxControlBody || !utf8.Valid(raw) {
		return nil, invalid
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	start, err := d.Token()
	if err != nil || start != json.Delim('{') {
		return nil, invalid
	}
	key, err := d.Token()
	if err != nil || key != "slugs" {
		return nil, invalid
	}
	var slugs []string
	if err := d.Decode(&slugs); err != nil {
		return nil, invalid
	}
	end, err := d.Token()
	if err != nil || end != json.Delim('}') || d.Decode(new(any)) != io.EOF {
		return nil, invalid
	}
	return slugs, nil
}

func missingSlugs(slugs []string, members []release.Member) []string {
	found := make(map[string]bool, len(members))
	for _, member := range members {
		found[member.LogicalSlug] = true
	}
	missing := make([]string, 0)
	for _, slug := range slugs {
		if !found[slug] {
			missing = append(missing, slug)
		}
	}
	return missing
}
