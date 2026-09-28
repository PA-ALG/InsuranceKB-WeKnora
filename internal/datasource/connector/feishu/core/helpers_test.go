package core

import (
	"encoding/json"
	"net/http"
	"os"
	"testing"

	secutils "github.com/Tencent/WeKnora/internal/utils"
)

func TestMain(m *testing.M) {
	if err := os.Setenv("SSRF_WHITELIST", "127.0.0.1,localhost,open.feishu.cn,open.larksuite.com"); err != nil {
		panic(err)
	}
	secutils.ResetSSRFWhitelistForTest()
	os.Exit(m.Run())
}

func writeJSON(w http.ResponseWriter, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		panic(err)
	}
}

func cellBlk(id string) DocxBlock {
	return DocxBlock{BlockID: id, BlockType: BlockTypeTableCell, Children: []string{id + "_txt"}}
}

func cellTextBlk(id, text string) DocxBlock {
	return DocxBlock{BlockID: id + "_txt", BlockType: BlockTypeText, Text: txt(text)}
}

func tableBlk(id string, cols int, cellIDs ...string) DocxBlock {
	b := DocxBlock{BlockID: id, BlockType: BlockTypeTable}
	b.Table = &BlockTable{Cells: cellIDs}
	b.Table.Property = &BlockTableProperty{ColumnSize: cols}
	return b
}
