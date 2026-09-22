# 来源上传执行器：首轮集中修复

状态：APPROVED_BOUNDED_REPAIR_AFTER_INDEPENDENT_REVIEW。唯一 Owner=g3_catalog_ui，适用 G3-R3/R4；原 v1 runner SHA `9873ea8bd0cab1148354242e20d65145cd96800a735944d262b614a7d5977ce3` 保留不可执行。独立复核7类可复现执行边界问题，证据见 source-upload-runner-independent-review-1.json。此为 upload 的首次修复，不重开 provision v3 或 guard。

1. 授权按动作绑定 exact 集合和次数：upload=new11/max11；embedding-external-send=new11/exact manifest/max11；source-backfill=all15，按new11后old01–04的执行顺序/max15。approved_at 为有效含时区时间字符串；不得用11份清单涵盖15次登记。实际用户回复到来前不得生成APPROVED授权。
2. 运行入口仅接受 `['colima','ssh','--profile','default','--','sudo','docker']`。live gate核 APP 127.0.0.1:18294→8080/tcp唯一发布端口、/data/files exact weknora-g3-830-files卷RW、APP/docreader共享exact weknora-g3-830-docreader-tmp→/tmp/docreader，APP RO/docreader RW；拒同destination额外挂载与G2卷。相关local storage/docreader env按provision v3 exact值，APP/Redis非空密码逐字一致且不输出。
3. 每份旧01/03/04 backfill返回后立即比较已冻结source ID，必须在PASS checkpoint和下一POST之前。02仅接当前actual严格绑定的response，不预写身份；最终map复核保留。
4. UploadExecutor seen IDs初始包含旧4知识ID；新response ID排旧/已见并立即登记。wait/descriptor/chunks均与requested knowledge ID及tenant/RAW KB/file/attempt绑定，不能以服务器返回另一ID形成看似一致的新闭包。
5. Guard ledger header严格匹配已有 contract/upstream/manifest/max_attempts=11/stopped=false；缺键或错值拒绝。
6. 旧输入通过硬编码 existing-chunk-capture.json SHA `3b14ef391cad1a215a8012acbfb385b0093425aef60c116eebbd0a0a81b54924` 固定；先验其contract/PASS/4 exact identity与capture path，逐件regular bytes hash等于其中capture_sha256，再读descriptor。不能将可变本地文件当冻结真值。
7. 不改guard1800秒寿命：启动guard成功时创建1440秒单一monotonic external deadline，保留360秒收尾余量。新11序列upload、poll、sleep、guard读取/下一件启动共用它，HTTP timeout不超过剩余时间，到期立即进入既有STOP。所有transport unknown继续占额度且不重试，旧4登记在guard/egress实际关闭后执行，不纳入外发时钟。不得通过延长guard或重启进程恢复批次。

Owner在原被冻结实现上新增正确期望的行为RED，保留原stub日志为REJECTED scaffold chronology，不覆盖。随后仅改新temporary runner/test/notes并独立复审，root复制为v2；原repo v1与provision/guard全保留。至少覆盖上述7类及现有21项，deadline使用可控时钟fake验证；实际HTTP/Docker/DB/provider/upload均0。授权一次性run identity的增强仅BACKLOG，不扩大本轮。
