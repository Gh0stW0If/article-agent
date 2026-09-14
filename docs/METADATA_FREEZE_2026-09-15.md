# Metadata 提取流程冻结记录

- 冻结日期：2026-09-15
- 冻结版本：metadata-freeze-2026-09-15
- 评估数据：2015 年 6 篇文章
- Gold 标准：`Datas/label/2015-6篇-0813.xlsx`
- 最新评分：35/36（97.22%）
- 验证测试：`tests/test_pipeline.py`、`tests/test_hybrid_evidence.py`，15 passed

## 冻结规则

1. 首页视觉识别优先，PDF 原文用于验证。
2. DOI 先清洗并验证；只有 Crossref DOI 与候选 DOI 一致时，Crossref 才具有最高置信度。
3. DOI 验证通过后，标题、期刊、首位作者和出版年份存在差异时，以 Crossref 为准。
4. 期刊来自 Crossref `container-title`、Europe PMC、出版社页面或 PDF；低置信度 PDF 候选可被已验证的 Crossref 覆盖。
5. PDF 标题提取跳过页眉、文章类型标签和作者单位；常见期刊缩写执行标准映射。
6. 邮箱去除编号、修复断行和空格；多个来源中任一邮箱匹配 Gold 即通过。
7. 无可靠来源时返回 `NR`，不得猜测。

## 当前已知差异

- 2015-04 联系邮箱仍与 Gold 不同：模型 `eujuki@gmail.com`，Gold `smchoi@kiom.re.kr`。

## 实现校验哈希

- `src/article_agent/metadata.py`：B78A02DC9AEEEAA0A2AA9B36C7BF11A13EA1C382F3CA2718EE9ABDE396E5ECC0
- `src/article_agent/extract.py`：794EDC2A21A901EA3B4EDD385F25CCAE429C8D7A453FFB69501FA29B1D987514

后续若需改变以上规则，应创建新的 metadata 版本并重新生成完整评分，不得覆盖本冻结基线。
