# 017 · WeKnora SourceDocument Bridge 与证据血缘

## 为什么做

当前 Compiler 从本地目录扫描 PDF；`WeKnoraClient.list_chunks()` 虽已存在但没有进入编译主链。生产文档在 WeKnora，若继续运行本地旁路，就无法继承 tenant/KB ACL，也无法把 Evidence 稳定关联到 knowledge、chunk 和来源修订。

## 做什么

1. 扩充 adapter 对 knowledge/chunk 的消费字段，并支持下载原文件；
2. 建立 `DocumentSource` 协议和不可变 `SourceDocument`；
3. Compiler 生产模式只接受 `WeKnoraDocumentSource`，本地目录作为显式 replay 模式；
4. 将 evidence page/quote 与 chunk 做可解释映射，冻结 source revision；
5. source reparse/update 后把旧 Evidence 标 stale 并生成 recompile ChangeSet；
6. 增加 mock 契约测试和真实 WeKnora live E2E。

## 不做什么

- 不复制 WeKnora docreader 的通用解析逻辑；
- 不以 chunk 位置猜测 PDF 页码；
- 不修改 WeKnora 核心表或队列。

## 影响面与文件域

- 组件：`adapters/weknora/`、Compiler load 边界、Evidence/importer；
- 硬边界：WeKnora API 路径/响应只出现在 adapter；Compiler 只依赖 `DocumentSource` 协议；
- Schema/Golden：不改字段 schema；Directory source 保证 Golden/replay 入口兼容；
- 主要文件域：`adapters/weknora/`、新 `sources/`、`compiler/pipeline.py` 的 load 边界、`knowledge/importer.py` 与 Evidence migration；
- 与其他 change：依赖 016；与 018 在 `knowledge/tables.py`/migration 编号上串行协调。

## 验收故事

在 tenant A 的 KB-RAW 上传 PDF，等待解析完成；Harness 按 knowledge_id 下载同一原件、取得 chunks、运行 Compiler，产出的每条 Evidence 至少可回到原 PDF 页，唯一命中时还能回到 chunk。更换文件并 reparse 后，旧 source revision 被识别为 stale，触发可审计重编译而不是静默沿用。
