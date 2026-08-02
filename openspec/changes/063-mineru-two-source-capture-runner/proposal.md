# 063 · MinerU exact two-source capture runner

## 状态

`STABLE CANDIDATE / PROVIDER NOT RUN / EXTERNAL REVIEW PENDING`

## 用户价值

061/062 已提供单份 PDF 的 bounded MinerU capture、私有原子 evidence 与 native
cross-page observation。当前缺口只是一个任务专用、可审计的组合入口：对 596-1
条款和费率表按固定顺序各调用一次既有 capture API，避免人工运行时错文件、重试或
混入说明书。

## 冻结输入与顺序

1. `dataset/shouxian_product/平安e生保（尊享版）医疗保险/保险条款.pdf`，SHA-256
   `88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc`；
2. `dataset/shouxian_product/平安e生保（尊享版）医疗保险/费率表.pdf`，SHA-256
   `7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb`。

Runner 必须先完成全部 preflight，再严格按 terms→rate 各调用一次
`docparser.CaptureMinerUNativeStructure`。首项失败时第二项调用数为零；第二项失败
时保留首项 evidence，并返回 typed partial failure。任何失败均不得自动重试或 fallback。

## 输出和凭据边界

- 唯一参数是调用方指定、尚不存在的 `/private/tmp` 直接子目录；runner 创建为0700；
- 每源 evidence 继续由既有库以0700目录/0600文件原子写入；
- `MINERU_API_KEY` 只由 process environment 进入既有库，runner仅在preflight检查
  非空，不接受CLI值，也不序列化、打印或散列；
- stdout 仅包含固定status、masked role、相对artifact名和artifact字节SHA-256；
  不包含正文、API base、完整本机路径或secret。

## 非目标

不修改docparser、061或062；不调用真实provider；不支持说明书、第三文件、重试、
fallback、并行capture、通用runner、DB、WeKnora、Golden或admission。

## 路径和停止条件

本change严格七路径：README、四个OpenSpec文件、一个task-local `main.go`和同目录
focused test。若实现需要第八路径、公共配置/API或修改既有capture库，立即停止。
