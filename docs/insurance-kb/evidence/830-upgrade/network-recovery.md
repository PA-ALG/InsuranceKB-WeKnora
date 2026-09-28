# 2026-09-27 下载链路恢复

## 执行前冻结范围

用户明确要求“你看下有没办法解决这些网络下载之类的问题”。本切片属于既有
830-UPSTREAM-PLUGIN-BOUNDARY / UPG-08 的构建环境恢复，root 唯一写者。
目标是修复已复现的下载故障，并用认证后的固定摘要下载验证，不再用匿名401
代替实际下载成功。本轮不追加 App 构建，不改变源码/依赖锁，不重启 Docker、
Colima 或现有容器，不迁移/部署/调用 provider，不清理镜像/卷/缓存。

配置写域：现有 Clash `Proxy` 选择器的已配置线路选择；
`~/.colima/default/colima.yaml` 的 `docker.registry-mirrors`；客体
`/etc/docker/daemon.json` 同一字段。保留原配置以便回滚。只通过原生 API、
Colima 配置和 Docker SIGHUP 生效，不新增代理、镜像站、构建器或重试平台。
文档写域：本回执、HANDOFF、OpenSpec130 的 UPG-08 场景和状态、PR 正文。

执行前观察：三个配置镜像站 USTC/163/Baidu 均 curl35、HTTP000；当前日本H线路
的 daemon 代理路径完成三轮固定 frontend 下载时，1轮成功、2轮超时，其中一次
仅传完2193396/11235607字节，另一次manifest请求35秒超时。另一已配置日本D
线路对同一registry端点测试231ms；这只是候选筛选，尚不等于完整下载通过。
上述是环境故障复现，不记作产品代码 RED。

顺序：先完成旧线路基线；只切换现有代理线路并重复相同下载检查；改善后再删除
已失效镜像列表，验证配置语法、SIGHUP和持久化一致性；最后用 Docker 原生拉取
固定 frontend 摘要及检查锁定依赖下载，核对全部8个运行容器的身份/启动时间/PID。
每个变量独立验证；失败则保留证据并恢复该次配置，不以不断重试掩盖结果。
下载探针每请求连接预算10秒、总预算35秒、无自动重试、每路径3轮；仅写临时文件。

## 验证回执

线路通过标准：daemon-proxy 与 TUN/no-explicit-proxy 两路径各3/3成功；每轮
相同 linux/arm64 frontend 层11235607字节全部下载、SHA-256一致、无自动重试。
固定 index 为 `sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e`。
层摘要由该固定 index → arm64 manifest 的逐级摘要校验确定，认证 token/跳转
签名URL不输出；每轮临时文件随探针结束删除。线路已通过才允许修改 mirrors。

持久修改前保存原选择、两份原配置/摘要、daemon PID及8个容器启动身份。
SIGHUP 后必须检查 `docker info` 的实际 mirrors 为空；最终原生 pull 必须成功，
核对 RepoDigest/linux/arm64，并标明拉取前缓存情况。任一步失败恢复原选择及
本轮两份配置，再SIGHUP核对原SHA/实际mirrors/运行身份，全部成功才保留通过验证的候选线路及空mirrors。
锁定依赖探针仅直接curl下载lock中的BrowserSkill源码、pnpm、AnyDoc、pip和
Debian Release五项并校验原SHA，不调用pnpm/Cargo/Go构建，不执行下载内容。

候选日本D未通过：显式代理3/3通过，TUN路径1/3通过，另外两次35秒超时。已自动恢复日本H；尚未修改mirrors。下一候选为已配置的新加坡A国际专线（registry筛选287ms），沿完全相同的六轮完整下载标准，不放宽超时、不增加重试。

终态：`PASS_BOUNDED_NETWORK_RECOVERY`，详细脱敏回执见
`network-recovery.json`。原日本H两路径合计2/6成功；日本D合计4/6成功并自动
恢复；新加坡A两路径均3/3成功，六次层传输2.228—3.086秒，全部11235607字节
且摘要正确。五个锁定依赖全部HTTP200/摘要通过，单项0.441—3.156秒。

固定 arm64 manifest 为 `sha256:c8678869a83fab70232869ba24acc1c0be661f4d65135c0eeacb6a8e78420fdd`；
层为 `sha256:6e230fe0035dc5b9d8d5e65513d1f11ae3b25d14362031fb540a4c23bf862933`。
Docker 原生 `pull --platform linux/arm64 docker.io/docker/dockerfile@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e`
成功，1.847秒，RepoDigest/平台核对一致。拉取前 image inspect 未找到此镜像，
但底层BuildKit/containerd内容可能已缓存，因此不声称这次pull是冷下载；完整
传输证据来自六次curl下载。它也不等于App的BuildKit构建已经通过。

运行中daemon mirrors为空，Colima持久配置也为空；其他字段未变。
代理当前选择与Clash Verge原生UI保存的Proxy选择均为新加坡A，`store-selected`
原已开启。规则模式、GLOBAL备用选择及其他代理配置不变；未重启代理软件来
证明重启效果，仅核对运行值与保存值。daemon PID及8容器Id/StartedAt/Pid未变。

原配置备份位于宿主 `~/.colima/default/colima.yaml.network-recovery-20260927.bak`
与客体 `/etc/docker/daemon.json.network-recovery-20260927.bak`。
如需回滚：先核对本回执after SHA以防覆盖用户后续修改；恢复这两份备份，向
当前dockerd PID发送SIGHUP并核对docker info mirrors；在Clash规则组Proxy选择
原“日本 H - 基础节点 | 直连×0.2 | IPv6”。无需重启Colima或容器。

本轮App构建0，累计仍4，余量仍0；App源码及identity保持e71c72f7d/12d583e5…。
UPG-08网络恢复是局部PASS，App制品/六组CI/迁移/部署/业务验证未因此关闭。
不需要修改下载来源、降低TLS校验、放宽摘要、延长无限超时或增加重复构建。
网络仍可能随线路/上游状态变化；下次构建前应核对同一实际下载路径。

依据：Docker官方[dockerd热重载](https://docs.docker.com/reference/cli/dockerd/#configuration-reload-behavior)
支持registry-mirrors；[daemon代理配置](https://docs.docker.com/engine/daemon/proxy/)
与构建容器代理不同。本次未改需重启daemon的proxy字段。线路通过现有
[Mihomo选择器API](https://wiki.metacubex.one/en/api/)与Clash原生UI保存。


补充交叉核对：新加坡A线路下三个旧镜像站的实际frontend manifest地址仍全部
curl35/HTTP000（0.995/0.031/0.503秒），因此镜像站问题并非仅旧线路测试造成。
OpenSpec strict、git diff --check通过；migration_review独立复核七个冻结文件与
本地原始回执，0 BLOCKER/0 BACKLOG/0 REJECTED，明确确认无产品实现、不把环境
故障当产品RED、文档不触发App构建。
