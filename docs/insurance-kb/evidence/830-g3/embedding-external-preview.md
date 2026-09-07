# G3 新增材料发送预览

用途：让新增11份PDF在隔离知识库中形成可检索的文本记录，为后续产品识别与候选编译提供真实来源。当前仅准备，尚未发送。

接收方：阿里云 DashScope；模型：qwen3.7-text-embedding。发送内容是各材料标题及解析后的文本片段，共204段，11份请求合计693129字节。PDF本体保留在本机隔离环境；外部模型收到下表请求文件中的文本。

最多11次发送，每份材料最多一次；失败或结果不明也占用额度，首次失败后全批停止，不自动重试。现有四份已解析材料不在此发送清单内。此窗口只生成文本向量，不包含产品识别、摘要、独立审核或发布。

| 材料 | 文本段数 | 请求字节 | 可审阅的完整请求 |
|---|---:|---:|---|
| esb_changqi_1072-1_tiaokuan.pdf | 34 | 111744 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-07-request.json) |
| esb_changqi_1072-4_tiaokuan.pdf | 40 | 132644 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-08-request.json) |
| esb_2016_tiaokuan.pdf | 9 | 30198 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-09-request.json) |
| 保险条款.pdf | 9 | 30273 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-11-request.json) |
| 保险条款.pdf | 41 | 139337 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-12-request.json) |
| 保险条款.pdf | 11 | 43244 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-13-request.json) |
| 保险条款.pdf | 8 | 28851 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-14-request.json) |
| pingan-1828-anyoufu-quanneng-terms.pdf | 42 | 145110 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-17-request.json) |
| pingan-1828-anyoufu-quanneng-brochure.pdf | 6 | 21191 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-18-request.json) |
| pingan-anyoufu-unresolved-version-rate-table.pdf | 2 | 2798 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-19-request.json) |
| pingan-20101018-official-product-list.pdf | 2 | 7739 | [完整内容](/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests/g3-material-21-request.json) |

安佑福条款已核实为1828、平安人寿〔2025〕疾病保险174号；费率表因缺少“全能版”及代码/备案号，关联版本仍待确认。发送材料不等于批准其内容进入已发布知识。

冻结清单：`embedding-transport-manifest.json`，SHA-256 `75b40ece28a4219965a6a86be616bb90f17af53252afad6c2243dedb9e377225`。保护程序及独立检查见 `embedding-guard-independent-review-2.json`。

执行前仍须完成并复核新环境配置与一次性执行脚本。此预览本身不是用户外发授权。
