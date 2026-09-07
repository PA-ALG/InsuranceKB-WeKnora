# G3 新材料上传与来源封存执行设计（待审）

状态：DESIGN_ONLY / NOT RUN。适用既有 G3-R3/R4 来源准备。复用已授权 G3 隔离环境、现有上传/W1 revision/source backfill 路由，不新增产品服务。此文档不代表用户已批准外发。

## 必要输入与前置

- 新来源固定为 corpus-files-v4 的 07/08/09/11/12/13/14/17/18/19/21 共11件，顺序按material_id；原4件01—04不重传、不主动重解析。
- 必须先取得审查通过的source-runtime provision实际PASS回执，重新核target container/image/DB/RAW KB/model、关闭摘要/问题/图谱/Wiki派生任务及独立Redis配置；来源G2和生产不改动。
- 外发仅消费用户对 embedding-external-preview.md 所列11个完整请求的真实批准；精确manifest SHA固定为75b40ece28a4219965a6a86be616bb90f17af53252afad6c2243dedb9e377225。与G2授权不混用。
- Guard源码、manifest、11请求文件和runner自身冻结SHA；全部以regular file复制至新APP私有执行目录并逐字核验，不改镜像、不安装依赖。Python只用既有stdlib。
- 重新human login，任何POST前核tenant10003及Admin身份。密码/token不入日志；HTTP仅固定loopback18294、不用环境代理、不接受redirect、不自动retry。

## 一次窗口与持久账本

1. root先创建唯一O_EXCL本地执行回执；保存输入identity、11材料状态NOT_STARTED、preflight摘要。每个POST在发送前持久化STARTED，失败/超时状态为失败或结果不明，禁止自动重发。
2. 在APP内启动已审guard，绑定上述固定manifest SHA和全新不可复用ledger；验证仅127.0.0.1:19030监听、ledger attempts为空且既有embedding model base_url指向此端口。不向guard发送测试POST，不消耗真实材料预算。
3. 仅在外发已获批准时接入预先冻结的有界egress网络，source runtime内部网络仍保留；不对G2/prod增删网络。执行窗口只允许11个exact embedding body、每件一次、总11次含失败，首次provider失败停止全批。
4. 每材料使用既有 `POST /api/v1/knowledge-bases/:id/knowledge/file`。multipart fileName=冻结corpus basename；file bytes/size/SHA发送前再核。process_config来自已审offline embedding preparation的exact配置：builtin native capture、legacy2048/80、parent_child=false、multimodal/graph/qgen=false。不沿用KB隐式默认值。
5. 逐件上传并等待该knowledge完成，才发送下一件；轮询只读GET有总截止时间、间隔和最大次数，无reparse/重传/整轮retry。duplicate409、knowledge失败、guard停止、body SHA不匹配、截止时间到或结果不明均STOP。
6. 上传响应只接受exact tenant/KB/file SHA/title与新knowledge ID。保存实际knowledge/attempt；W1 revision committed后分页读取exact revision chunks，重算manifest，前后descriptor一致。metadata/native parser身份必须与冻结配置相容，不能使用预检输出假装新的SourceRevision。
7. 使用现有human Admin `POST /api/v1/knowledge/:id/revisions/:attempt/source/backfill`，逐件发送前写账本。保存实际source receipt并核原件SHA/size/pagecount/attempt/manifest/retention。新11件及旧4件各自封存；旧3已封存须返回原revision_source_id，旧02缺口只在G3新库补齐。不调用语义不同的exact3批接口，不手写source_id或DB row。
8. SourceRevision构建消费actual W1 descriptor/chunks/backfill receipt与已保存native捕获分别绑定的hash。native捕获只是独立已核解析制品；其hash不得替代W1 manifest或source seal identity。来源真值最终仍由既有服务器source authority重开。
9. 每件完成即持久化全部原始HTTP响应与账本引用SHA。最终15来源统计分别列upload、parse、W1 manifest、source seal和未执行项；11次向量结果与15来源分母不能互相替代。

## 停止与收尾

任何失败或结果不明，立即阻止后续上传、停止guard并断开仅本窗口新增的egress连接，验证进程/网络实际状态；无法确认则STOP_INCOMPLETE。先保护已有响应/ledger，再停止本次APP/docreader以阻止后台继续派生，不删除任何部分knowledge/DB/volume，不恢复重跑。是否需要停止Redis按同一冻结runner规则明确，不能清队列。

成功也关闭guard并断开新增egress；记录实际provider attempt总数、每body一次、无遗漏/额外发送和source/runtime readback。网络失败不通过改hosts/proxy、重新请求或更换provider绕过，保留现场后回到有界恢复设计。

本次仅来源准备。产品classifier/compiler/reviewer、Draft、Review、Activate均为独立后续步骤；SOURCE_PASS不等于G3 FLOW或质量通过。

## runner验证要求

实现前用fake HTTP/container runner覆盖：无/错外发授权拒绝；脚本/manifest/raw漂移拒绝；STARTED落盘失败不POST；duplicate/timeout/provider失败不重试且不发送后项；后台未停止报告STOP_INCOMPLETE；descriptor前后漂移/错manifest/错source seal拒绝；旧3source ID保持；第02仅G3补封；全部fake不触发真实HTTP。一个集中review修复轮后仍有同域基础问题则回设计。
