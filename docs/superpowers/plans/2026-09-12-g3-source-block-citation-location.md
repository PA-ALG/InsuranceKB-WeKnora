# G3 来源块引用定位实施计划（CFG42）

**目标：** 让实际代表候选通过原文来源校验，并打开引用实际所在的 PDF 页；保持已有模型结果、Candidate 和冻结 G2 行为不变。

**架构：** 复用已验真 native index 和已与数据库逐字核对的来源块。增加 G3 专用、带版本的定位说明，绑定原证据及实际物理页。原证据页号保留为原记录；不能继续把它未经定位地解释为引用物理页。用户已授权持续修复 G3，优先复用、保留证据、不逐字段补齐；本修复不新增模型调用、信任公钥或内容审批。

**依据：** 真实 Candidate `c22dee77ade903097d160b04e85e010b3f6557fd0792045e6ebfe81cae0423a8` 首次 APP POST 44.37 秒返回来源校验503。DocReader 同次解析成功。归档 native 重放：305 唯一引用包含 17 个走旧证据链的历史引用；288 个 native 引用中277通过旧定位，3个标题同页重复、8个引用记录页号不符。完整来源块在全文件中唯一匹配后，282个可直接定位，另6个历史引用可沿用原严格页内唯一路径。实际11个失败均能定位到单一物理页且字符框完整。

## 设计与兼容约束

1. 只有通过固定 release 的真实 G3 manifest 识别、或真实 G3 草稿来源校验入口，才能启用新定位。不能由请求参数或 token 声明自行决定 G3 权限；重开 token 时重新识别固定 release。
2. native index 已完成原文件哈希、parser identity、全文/页文本和字符框验证。来源块必须保持数据库读取到的完整原文，禁止 strip、模糊匹配、第一次匹配或改模型引用。唯一全文 block 起点加 Unicode start/end 得到绝对引用范围；该范围必须逐字匹配 quote，且完整落在一页并具有合法字符框。
3. 现有严格页内唯一定位继续作为独立可用路径，覆盖6个历史 native 引用；17个原 G2 legacy 证据继续走现有证明链。不能把无法定位的输入静默判为成功。对于同时存在的完整block定位和旧定位，核对一致性，实际来源块位置优先；保留真实页差异。
4. 冻结 G2 authority v1 字节/摘要及 token 验证保持不变。新增 `concept-citation-content-authority.830.g3.v1`，仅该版本允许新增 `source_locator`；G2序列化用 `omitempty` 不带它。顶层 `page_number` 仍绑定原 evidence/citation ID 页号；`source_locator.actual_page_number` 用于 PDF 实际渲染。
5. `source_locator` 精确字段：`contract`=`concept-source-block-locator.830.g3.v1`、`source_block_sha256`、`source_page_number`、`start`、`end`、`block_global_start`、`global_start`、`global_end`、`actual_page_number`。相对/绝对范围均为 Unicode code point；global_start=block_global_start+start，global_end=block_global_start+end，原页/范围/quote与唯一Candidate citation严格绑定，实际页在文件页数内。整个定位说明进入 authority 摘要和已签 token，重开时重新生成并精确比较。
6. 前端同时接受冻结 G2 authority 和严格闭集 G3 authority；G3原页/offset等仍与原证据核对，只有实际物理页交给 PDF renderer。G3入口按钮显示“查看原文”，草稿不将原记录页号误标为已校验物理页；实际打开后显示真实页码。不影响 G2 展示。
7. 新增定位不增加或更改信任密钥，不绕过最终内容审批。原 Candidate、493字段、136次调用和所有原始PDF/模型产物原封保留。

## 实施与验证

- [ ] 后端：在 `internal/application/service/concept_source_authority_830_g2.go` 及独立G3定位文件补真实重复标题/错误页的失败测试；保留未提供可信G3标志的原路径拒绝；覆盖完整block重复、文本错位、quote跨页、缺字符框和篡改 locator/token。
- [ ] 后端：把固定manifest识别出的isG3显式传入issue和content reopen，G3草稿校验只启用相同定位规则；可复用原native index及内部解析结果，不做大范围重构。
- [ ] 前端：在 `conceptCitationAuthority830G2.spec.ts` 先写G3新authority实际页不同于原页的失败测试；最小新增闭集解析与原证据绑定；修改viewer显示实际页，保留G2旧向量测试。
- [ ] 真实只读重放全部288 native引用，核对282完整block定位和6旧路径；17 legacy沿原证明链，不能伪造新native通过。
- [ ] 使用已存在缓存构建、来源冻结和部署流程，只重建有变更的APP/UI；不改DB、原文或模型运行源。
- [ ] 新APP部署后首先回读已有首款草稿，再明确重提同一代表Candidate到未创建成功的编号（或新唯一编号）；成功后真实引用实际页回读与UI验收，更新整包预览实际页说明。

本计划不引入跨页单引用多高亮输出、无Schema全链路或千文件吞吐新承诺；本轮真实引用均可定位单页。实际发布与人审签名仍须最终整包明确确认。
