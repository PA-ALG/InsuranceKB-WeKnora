package chatsource

// Updated by Claude in the QA1 RED commit (Spec docs/design/slices/QA1-问答来源标注与范围说明.md §4.2):
// the absence rule replaces the old unknown/absent_explicitly sentence and raw passages name
// their product. The Q2b requirement at the end is unchanged.

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestQ2bKnowledgeNoticeOnlyAppendsEnterpriseRequirement(t *testing.T) {
	const original = "已发布知识优先：先用 knowledge_find_entity、knowledge_get_fields、" +
		"knowledge_search_fields、knowledge_get_concept 查询本轮固定发布版本。" +
		"回答产品事实时引用当前工具返回的字段句柄。" +
		"只有字段为“材料明确没有”时，才能说该产品没有这项规定；字段为“已发布知识未收录”、搜索没有命中或页面没有结果，" +
		"都不代表材料没有，只能说已发布知识未收录（不代表材料没有）。" +
		"要说某个产品没有某项规定，先用 knowledge_get_fields 读取该产品的这一项。" +
		"没有 Evidence 的内容不标审核过、不制造出处。" +
		"概念定义、说明和概括是模型补充（概念说明），与已举证的产品字段分开，不把模型补充当审核事实。" +
		"字段查不到时，可用 knowledge_search_pages 查延伸阅读页面；页面是模型整理（未逐条审核），" +
		"回答中如实标注，不当作审核过的事实；与字段冲突时以字段为准。"
	const rawNotice = "已发布知识查不到时可用原文检索补充；原文仅限本轮固定材料，" +
		"明确标注原文检索（未经编译审核），不能混淆两种来源。" +
		"原文片段标题前标有所属产品，只能用于该产品；所属产品未识别的片段，不能当作任何具体产品的规定。"
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
