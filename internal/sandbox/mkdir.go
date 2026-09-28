package sandbox

import (
	"path"
	"strings"
)

// makeDirTree creates dir and every missing parent by calling mkdir once per
// path component. envd's MakeDir is not mkdir -p; Cube and E2B adapters wrap it
// with this instead of a single RPC so host-skill staging under
// /workspace/.skills/<name>/<revision>/... can create its tree.
func makeDirTree(dir string, mkdir func(path string) error) error {
	dir = path.Clean(strings.TrimSpace(dir))
	if dir == "" || dir == "." || dir == "/" {
		return nil
	}
	var current string
	if path.IsAbs(dir) {
		current = "/"
		dir = strings.TrimPrefix(dir, "/")
	}
	for _, part := range strings.Split(dir, "/") {
		if part == "" || part == "." {
			continue
		}
		switch current {
		case "/":
			current = "/" + part
		case "":
			current = part
		default:
			current += "/" + part
		}
		if err := ignoreExistingDir(mkdir(current)); err != nil {
			return err
		}
	}
	return nil
}
