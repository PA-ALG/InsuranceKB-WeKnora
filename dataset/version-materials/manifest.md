# 平安 e生保 family — official version-hunt manifest

Retrieved: 2026-07-27 (curl, proxies unset). Staging only — controller reviews before adoption into dataset/.
All files verified: `%PDF` header, size > 50KB, page count via pdfinfo, product name confirmed in first-page pdftotext output.

Sources (all official Ping An):
- **A. 平安人寿官网 互联网保险信息披露** — listing page: https://life.pingan.com/gongkaixinxipilu/wangxiaoguifan.jsp ; PDFs served by the official clause API `https://life.pingan.com/ilife-home/product/getPlanClausePdf?planCode=&versionNo=&attachmentType=` (attachmentType 1=条款, 7=产品说明书). Invalid versionNo returns JSON `{"responseSts":{"flag":"-1","message":"程序异常"}}` — used to confirm which versions exist.
- **B. 平安健康保险官网 (m.health.pingan.com)** — provision PDFs linked from product pages `https://m.health.pingan.com/share/products/{esb,esb2017,esb_guarantee}.html`.

## Group 1 — Golden product & 2025 siblings (承保人: 中国平安人寿保险股份有限公司)

| File | Product / version | 备案号 | Pages | Source URL | Status |
|---|---|---|---|---|---|
| esb_zunxiang_596-1_tiaokuan.pdf | 平安e生保（尊享版）医疗保险 条款 (planCode 596, ver 596-1) — **GOLDEN** | 平安人寿〔2025〕医疗保险172号 | 39 | A: planCode=596&versionNo=596-1&attachmentType=1 | OK |
| esb_zunxiang_596-1_shuomingshu.pdf | 同上 产品说明书 | — (同产品) | 27 | A: 596/596-1/type=7 | OK |
| esb_jiaxiang_595-1_tiaokuan.pdf | 平安e生保（加享版）医疗保险 条款 | 平安人寿〔2025〕医疗保险171号 | 94 | A: 595/595-1/type=1 | OK |
| esb_huixiang_594-1_tiaokuan.pdf | 平安e生保（惠享版）长期医疗保险（费率可调） 条款 | 平安人寿〔2025〕医疗保险170号 | 44 | A: 594/594-1/type=1 | OK |
| esb_huixiang_594-1_shuomingshu.pdf | 同上 产品说明书 | — (同产品) | 17 | A: 594/594-1/type=7 | OK |

Note: 596-2 probed → does not exist; 596-1 is the only filed version of the golden product on life.pingan.com.

## Group 2 — SAME product, four sequential 备案 revisions (强 cross-version pair)

平安e生保长期医疗保险（费率可调）, planCode 1072, 承保人 平安人寿:

| File | versionNo | 备案号 | Pages | sha-distinct | Status |
|---|---|---|---|---|---|
| esb_changqi_1072-1_tiaokuan.pdf | 1072-1 | 平安人寿[2020]医疗保险168号 | 35 | yes | OK |
| esb_changqi_1072-2_tiaokuan.pdf | 1072-2 | 平安人寿〔2021〕医疗保险079号 | 35 | yes | OK |
| esb_changqi_1072-3_tiaokuan.pdf | 1072-3 | 平安人寿〔2021〕医疗保险155号 | 40 | yes | OK |
| esb_changqi_1072-4_tiaokuan.pdf | 1072-4 | 平安人寿〔2021〕医疗保险155号 (re-issue, larger) | 46 | yes | OK |

Source URLs: A: planCode=1072&versionNo=1072-{1..4}&attachmentType=1

## Group 3 — Name-collision variant (different product also named 尊享版)

| File | Product | 备案号 | Pages | Source | Status |
|---|---|---|---|---|---|
| esb_fujia_zunxiang_2609-1_tiaokuan.pdf | 平安附加e生保（尊享版）长期医疗保险（费率可调） 条款 (planCode 2609) | 平安人寿〔2021〕医疗保险129号 | 41 | A: 2609/2609-1/type=1 | OK |

## Group 4 — Historical 平安健康 e生保 lineage (承保人: 平安健康保险股份有限公司)

| File | Product / version | 备案号 | Pages | Direct PDF URL | Status |
|---|---|---|---|---|---|
| esb_2016_tiaokuan.pdf | 平安e生保医疗保险 条款 (2016版) | 平安健康〔2016〕医疗保险003号 | 10 | https://m.health.pingan.com/provision/esb_provision.pdf | OK |
| esb_2017_tiaokuan.pdf | 平安e生保（2017）医疗保险 条款 | 平安健康〔2019〕医疗保险002号 | 15 | https://m.health.pingan.com/provision/esb2017_provision.pdf | OK |
| esb_baozhengxubao_tiaokuan.pdf | 平安e生保（保证续保版）医疗保险 条款 | 平安健康〔2018〕医疗保险048号 | 15 | https://m.health.pingan.com/provision/esb_guarantee_provision.pdf | OK |
| esb_baozhengxubao_feilvbiao.pdf | 平安e生保（保证续保版）医疗保险 费率表 | — (同产品) | 4 | https://m.health.pingan.com/provision/rate/esb_guarantee_rate.pdf | OK |

Page URLs: https://m.health.pingan.com/share/products/esb.html (2016), .../esb2017.html, .../esb_guarantee.html

## sha256

```
734fe177e498de35ceb551eb02a770bb0de41d0e7bf03b163327e9afdc4118ec  esb_2016_tiaokuan.pdf
74c8670612f1caacbb8fcb14d3b2bf9b8d35166a6e7680b0767f6fcb9cccea2a  esb_2017_tiaokuan.pdf
a36e8bee99c18d9a6168f882a4891e11eb3bb5bb50c12d850e9a8bb777f66ff4  esb_baozhengxubao_feilvbiao.pdf
6b4cf9ddf9ca32b0e3c27410f3153687b96bdb673120e1758b668fbad8c9f5df  esb_baozhengxubao_tiaokuan.pdf
53eb3b5b6c2d66c09cea593f9cb40faa596182ad82523e72bd394f49466913cc  esb_changqi_1072-1_tiaokuan.pdf
e953bf8ddfa098f765a4960ae7f2cab258f93aa2b20b9ac60725d1fee3232d76  esb_changqi_1072-2_tiaokuan.pdf
fdf621070cf6ac4f9fdc8555671031ec9d276173f94b182d7329808dcfb91f44  esb_changqi_1072-3_tiaokuan.pdf
f043311c2257f6f5e5cd14120c4f418ed9ef2245dda21fc1eb80d75ae21f1079  esb_changqi_1072-4_tiaokuan.pdf
a6f214f96e73807a5c031932695ada7e1b28e19bc7c283c63255a253c02e1062  esb_fujia_zunxiang_2609-1_tiaokuan.pdf
3c7b24cd12e1c6bb04c714be511077f85fa6e5c820ed18dde3f025e9e71b320f  esb_huixiang_594-1_shuomingshu.pdf
7bfac182fe11866e9d4c6f2b970a3a56db79833476f51e83ddcafe127b4c9ce5  esb_huixiang_594-1_tiaokuan.pdf
b72df94a33b2e4a07908f2ffda52bcf1b839b547ef2c5e229313b3fe4551ac64  esb_jiaxiang_595-1_tiaokuan.pdf
5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279  esb_zunxiang_596-1_shuomingshu.pdf
88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc  esb_zunxiang_596-1_tiaokuan.pdf
```

## Key facts for G0v

1. Golden product 平安e生保（尊享版）医疗保险 is underwritten by **中国平安人寿保险股份有限公司** (per 条款/说明书 text), NOT 平安健康 — the task's assumption was wrong; correct in KB metadata.
2. Cleanest same-product version pair for cross-version acceptance: **1072-1 (2020-168号) vs 1072-4 (2021-155号)** — same product name, 35 vs 46 pages, different filing years.
3. Name-collision hazard: 附加e生保（尊享版）长期医疗（费率可调）(2609, 2021-129号) vs e生保（尊享版）医疗保险 (596, 2025-172号) — two distinct products sharing "尊享版".
4. Lower-trust note: none needed — all 14 files came from pingan.com official domains; no third-party mirrors used.
