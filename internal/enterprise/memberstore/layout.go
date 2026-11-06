package memberstore

import (
	"crypto/sha256"
	"encoding/binary"
)

const (
	layoutMinEntries = 32
	layoutMaxEntries = 128
)

type layoutWindow struct{ first, last int }

// buildLayout maintains parent boundaries. Only real key edits open rechunking
// windows; changed values outside those windows remain in their original block.
func buildLayout(entries []layoutEntry, parent []layoutChunk, mode string) ([]layoutChunk, error) {
	if mode != "slug_asc" && mode != "legacy_sequence" {
		return nil, ErrIntegrity
	}
	if !validLayoutEntries(entries, mode == "slug_asc") {
		return nil, ErrIntegrity
	}
	if len(parent) == 0 || mode == "legacy_sequence" {
		return scanLayout(entries, true)
	}
	var previous []layoutEntry
	var previousBlocks []int
	for block, chunk := range parent {
		count := len(chunk.Entries)
		if count < 1 || count > layoutMaxEntries || (block < len(parent)-1 && count < layoutMinEntries) {
			return nil, ErrIntegrity
		}
		previous = append(previous, chunk.Entries...)
		for range chunk.Entries {
			previousBlocks = append(previousBlocks, block)
		}
	}
	if !validLayoutEntries(previous, true) {
		return nil, ErrIntegrity
	}
	windows, assignments := editedLayoutWindows(entries, previous, previousBlocks, len(parent))
	offsets := make([]int, len(parent)+1)
	for _, block := range assignments {
		offsets[block+1]++
	}
	for index := 1; index < len(offsets); index++ {
		offsets[index] += offsets[index-1]
	}
	result := make([]layoutChunk, 0, len(parent))
	for block, windowIndex := 0, 0; block < len(parent); {
		if windowIndex < len(windows) && windows[windowIndex].first == block {
			window := windows[windowIndex]
			chunks, err := scanLayout(entries[offsets[block]:offsets[window.last+1]], window.last == len(parent)-1)
			if err != nil {
				return nil, err
			}
			result = append(result, chunks...)
			block, windowIndex = window.last+1, windowIndex+1
			continue
		}
		result = append(result, layoutChunk{Entries: entries[offsets[block]:offsets[block+1]]})
		block++
	}
	return result, nil
}

func validLayoutEntries(entries []layoutEntry, sorted bool) bool {
	seen := make(map[string]bool)
	for index, entry := range entries {
		if len(entry.Digest) != sha256.Size {
			return false
		}
		if sorted {
			if index > 0 && entries[index-1].Slug >= entry.Slug {
				return false
			}
		} else {
			if seen[entry.Slug] {
				return false
			}
			seen[entry.Slug] = true
		}
	}
	return true
}

// One merge diff against the original parent separates edit runs at every
// surviving key. Insertions map to the first greater original key's block.
func editedLayoutWindows(
	entries, previous []layoutEntry, previousBlocks []int, blockCount int,
) ([]layoutWindow, []int) {
	assignments := make([]int, len(entries))
	windows := make([]layoutWindow, 0)
	run := layoutWindow{-1, -1}
	finishRun := func() {
		if run.first < 0 {
			return
		}
		window := layoutWindow{max(0, run.first-1), min(blockCount-1, run.last+1)}
		if len(windows) > 0 && window.first <= windows[len(windows)-1].last {
			windows[len(windows)-1].last = max(windows[len(windows)-1].last, window.last)
		} else {
			windows = append(windows, window)
		}
		run = layoutWindow{-1, -1}
	}
	for oldIndex, newIndex := 0, 0; oldIndex < len(previous) || newIndex < len(entries); {
		if oldIndex < len(previous) && newIndex < len(entries) && previous[oldIndex].Slug == entries[newIndex].Slug {
			finishRun()
			assignments[newIndex] = previousBlocks[oldIndex]
			oldIndex++
			newIndex++
			continue
		}
		block := blockCount - 1
		if oldIndex < len(previous) {
			block = previousBlocks[oldIndex]
		}
		if run.first < 0 {
			run.first = block
		}
		run.last = block
		if newIndex == len(entries) || (oldIndex < len(previous) && previous[oldIndex].Slug < entries[newIndex].Slug) {
			oldIndex++
		} else {
			assignments[newIndex] = block
			newIndex++
		}
	}
	finishRun()
	return windows, assignments
}

func scanLayout(entries []layoutEntry, globalLast bool) ([]layoutChunk, error) {
	chunks := make([]layoutChunk, 0, len(entries)/layoutMinEntries+1)
	start := 0
	for index, entry := range entries {
		count := index - start + 1
		if count >= layoutMinEntries && (count == layoutMaxEntries || naturalLayoutBoundary(entry.Slug)) {
			chunks = append(chunks, layoutChunk{Entries: entries[start : index+1]})
			start = index + 1
		}
	}
	if start < len(entries) {
		chunks = append(chunks, layoutChunk{Entries: entries[start:]})
	}
	if !globalLast && len(chunks) > 0 && len(chunks[len(chunks)-1].Entries) < layoutMinEntries {
		if len(chunks) < 2 {
			return nil, ErrIntegrity
		}
		count := len(chunks[len(chunks)-2].Entries) + len(chunks[len(chunks)-1].Entries)
		tail := entries[len(entries)-count:]
		chunks = chunks[:len(chunks)-2]
		if count <= layoutMaxEntries {
			chunks = append(chunks, layoutChunk{Entries: tail})
		} else {
			middle := (count + 1) / 2
			chunks = append(chunks, layoutChunk{Entries: tail[:middle]}, layoutChunk{Entries: tail[middle:]})
		}
	}
	return chunks, nil
}

func naturalLayoutBoundary(slug string) bool {
	digest := sha256.New()
	digest.Write([]byte("enterprise-member-boundary.v1\x00"))
	writeCodecString(digest, slug)
	return binary.BigEndian.Uint64(digest.Sum(nil)[:8])&63 == 0
}
