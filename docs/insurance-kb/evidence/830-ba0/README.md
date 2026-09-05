# 830 BA0 · 本地构建复用 Evidence Pack

> 当前状态：`PASS`
> 范围：`BA0_LOCAL_BUILD_REUSE`
> 产品 Goal：`NONE`
> G2：`LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION`

2026-09-05 完成：恢复构建 PASS/build=1、同身份复用 PASS/build=0、D3 PASS/build=0/pull=0。
累计真实构建为 **2/2**（旧失败1 + 用户追加授权恢复成功1）。closeout v1 的 `build_budget`
仅记录恢复 identity 窗口 1/1；完整累计历史见
[recovery-authorization.md](recovery-authorization.md) 与原始失败收据
[failed-initialization-build.json](d2/failed-initialization-build.json)。

本包只证明 BA0 工程门：同一 app artifact identity 的首次请求真实构建不超过一次，第二次
请求严格复用同一 image ID 且 build=0；D3 仅运行该 exact image 的 standalone
`CONTAINER_ARTIFACT_SMOKE`，build/pull 与所有业务、网络、生产、Provider 和 G2 effects 均为 0。
它不证明 WeKnora HTTP application health，也不授权 G2。

## 预定文件

- `d2/initialization-build.json`：首次请求的 selector、identity、image ID 和 build count；
- `d2/same-identity-reuse.json`：同一 identity 的第二次 exact reuse，build=0；
- `d3/exact-image-smoke.json`：同一 image ID 的只读 standalone artifact smoke；
- `ba0-closeout.json`：输入、commit/tree、receipt hash、预算、cache 非 authority、G1 历史、
  measurement 和零 effects 的 canonical self-hash 总账；
- `tools/verify_ba0_evidence.py`：只读重算上述证据及 canonical artifact identity；它会执行本地
  Git/Go dependency resolution，但不调用 Docker、Provider、数据库或服务。

## 身份与 self-hash

manifest 与 dependency lock 的 SHA-256 使用和 artifact identity 相同的 canonical JSON：UTF-8、
key 排序、紧凑分隔符且不追加换行。closeout 的 `self_sha256` 复用 B0 模式：先把该字段置为
`null`，再对同样的 canonical JSON 加一个末尾换行计算 SHA-256。三个执行 receipt 另以原始文件
SHA-256 绑定，修改内容后必须同步 closeout 并重新计算 self-hash。

`ba0-closeout.json` 分列 origin/main frozen base/tree、implementation head/tree、D2
build-source head/tree、执行时 integration head、artifact identity 和 image ID，避免把文档集成
身份误当作镜像输入身份。最终 branch head 不写入自指文件，由 verifier 运行结果与最终复核绑定。

## 测量与边界

exact lookup 和自然增量构建若没有可审计样本，必须记录 `NOT_MEASURED` 和非空 reason；不得为
补测制造第二个 identity 或消耗额外 build。cache probe 仅证明两个 Go RUN 的共享持久 cache
合同，不是正确性 authority。G1 历史必须保持未改，BA0 PASS 后仍须清空授权并返回用户，G2
保持 `LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION`。
