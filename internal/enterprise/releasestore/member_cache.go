package releasestore

import (
	"container/list"
	"context"
	"errors"
	"fmt"
	"sync"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"golang.org/x/sync/singleflight"
)

type memberKey struct {
	Tenant  uint64
	Space   string
	Release string
}

type memberEntry struct {
	key     memberKey
	members []release.Member
}

// The production Store owns at most four decoded versions; headers are never cached.
type memberCache struct {
	mu      sync.Mutex
	entries map[memberKey]*list.Element
	recent  list.List
	flights singleflight.Group
}

var errMemberLoadCanceled = errors.New("member loader's request ended")

func (c *memberCache) get(key memberKey) ([]release.Member, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if e := c.entries[key]; e != nil {
		c.recent.MoveToFront(e)
		return e.Value.(memberEntry).members, true
	}
	return nil, false
}

func (c *memberCache) put(key memberKey, members []release.Member) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.entries == nil {
		c.entries = make(map[memberKey]*list.Element)
	}
	c.entries[key] = c.recent.PushFront(memberEntry{key, members})
	if c.recent.Len() > 4 {
		oldest := c.recent.Back()
		delete(c.entries, oldest.Value.(memberEntry).key)
		c.recent.Remove(oldest)
	}
}

func (c *memberCache) load(
	ctx context.Context, key memberKey, read func(context.Context) ([]release.Member, error),
) ([]release.Member, error) {
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if members, ok := c.get(key); ok {
			return copyMembers(members), nil
		}
		pending := c.flights.DoChan(fmt.Sprintf("%d:%q:%q", key.Tenant, key.Space, key.Release), func() (any, error) {
			// A previous flight may have completed between the lookup and joining.
			if members, ok := c.get(key); ok {
				return members, nil
			}
			members, err := read(ctx)
			if ctx.Err() != nil {
				return nil, errMemberLoadCanceled
			}
			if err != nil {
				return nil, err
			}
			c.put(key, members)
			return members, nil
		})
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case result := <-pending:
			if err := ctx.Err(); err != nil {
				return nil, err
			}
			if errors.Is(result.Err, errMemberLoadCanceled) {
				// Another caller owned the canceled database query. A live waiter
				// retries with its own context rather than inheriting that failure.
				continue
			}
			if result.Err != nil {
				return nil, result.Err
			}
			return copyMembers(result.Val.([]release.Member)), nil
		}
	}
}

func copyMembers(members []release.Member) []release.Member {
	out := make([]release.Member, len(members))
	for i, member := range members {
		out[i] = member
		out[i].Payload = append([]byte(nil), member.Payload...)
		out[i].EvidenceRefs = append([]string(nil), member.EvidenceRefs...)
	}
	return out
}
