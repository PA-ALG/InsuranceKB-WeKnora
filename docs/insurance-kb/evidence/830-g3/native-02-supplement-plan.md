# 既有说明书 02：补存独立 native capture

适用 G3-R4 已授权来源准备。只对实际 PDF `dataset/version-materials/esb_zunxiang_596-1_shuomingshu.pdf`（SHA-256 `5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279`，27 页）调用既有本机 Docreader 内置 PDF parser 一次，保存真实返回字节。当前完整 capture 缺失，不能用 C5 哈希或 W1 chunks 反造。

执行复用既有 `native_preflight.py` 的同一调用方式，先核实 Docreader 容器运行及 image `sha256:ac944d934fcd30c77e4ff28d19f1b4d6dd147012a6553c4678274c1f0be35868`；仅写唯一容器 `/tmp` 目录，子进程禁用网络连接，builtin-pdfium-charbox-v1，不调用模型、知识上传或重解析 API。先持久 STARTED，失败即保存失败，不自动重跑。

这里补做独立本机解析留档；来源暂存方案中“原4件不重传/重解析”继续约束 WeKnora upload/reparse 和已有 W1 attempt。既有 knowledge/revision/chunk/source rows 不变。该 capture 不替代当前服务 source receipt，02 的隔离库 backfill 仍待来源暂存执行器处理。不得由此宣称 C 真实输入闭合或 G3 FLOW 通过。
