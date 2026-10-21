package chatsource

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestQ2bKnowledgeNoticeOnlyAppendsEnterpriseRequirement(t *testing.T) {
	const original = "已发布知识优先：先用 knowledge_find_entity、knowledge_get_fields、" +
		"knowledge_search_fields、knowledge_get_concept 查询本轮固定发布版本。" +
		"回答产品事实时引用当前工具返回的字段句柄；查不到或 unknown 时如实说明，不将未知说成明确没有。" +
		"absent_explicitly 表示材料明确没有。没有 Evidence 的内容不标审核过、不制造出处。" +
		"概念定义、说明和概括是模型补充（概念说明），与已举证的产品字段分开，不把模型补充当审核事实。" +
		"字段查不到时，可用 knowledge_search_pages 查延伸阅读页面；页面是模型整理（未逐条审核），" +
		"回答中如实标注，不当作审核过的事实；与字段冲突时以字段为准。"
	const rawNotice = "已发布知识查不到时可用原文检索补充；原文仅限本轮固定材料，" +
		"明确标注原文检索（未经编译审核），不能混淆两种来源。"
	const requirement = `回答中的每一条产品事实都必须在同一行带上支撑它的来源句柄（如 <ref id="c1"/>）；` +
		"找不到可引用来源的产品事实不要写，改为说明未找到。"

	for _, tc := range []struct {
		name string
		turn Turn
		want string
	}{
		{name: "ordinary", want: ""},
		{name: "raw only", turn: Turn{RawKnowledge: map[string]string{"doc": "space"}}, want: ""},
		{name: "wiki", turn: Turn{WikiSpaces: []string{"space"}}, want: original + requirement},
		{name: "wiki and raw", turn: Turn{
			WikiSpaces: []string{"space"}, RawKnowledge: map[string]string{"doc": "space"},
		}, want: original + rawNotice + requirement},
	} {
		t.Run(tc.name, func(t *testing.T) {
			require.Equal(t, tc.want, KnowledgeNotice(tc.turn))
		})
	}
}
