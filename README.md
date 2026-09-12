# Article Agent

面向医学随机对照试验（RCT）的证据优先信息提取流程。当前实现以 MinerU/Docling 将 PDF 转为结构化 Markdown，再通过 Pydantic 或 BAML 约束的 LLM 调用提取元数据、STRICTA 针灸干预、偏倚风险、CONSORT 样本流和统计结局。

## 当前流程特点

- 按章节路由 Abstract、Methods、Results 与 Tables。
- 结局表先分类，再保留完整多级表头并逐表、逐行抽取。
- 每条结果保存 `table_id`、`row_id`、arm、comparison、analysis set、record role 和原文证据。
- 整表响应不完整时自动降级为行级重试，不静默丢行。
- 原始结果、冲突组和 canonical outcome dataset 分层保存。
- 允许证据唯一支持的可复现推导，禁止猜测和依据金标准反向修改。
- API 密钥、主地址及故障切换地址只从本地环境变量读取。

详细说明见 [MinerU 流程文档](MinerU%20method/README.md) 和 [中文流程与 Skill 介绍](MinerU%20method/CURRENT_WORKFLOW_AND_SKILLS_CN.md)。

## 安装

项目开发使用 `Agent` conda 环境：

```powershell
conda activate Agent
python -m pip install -e .
python -m pip install -r "MinerU method/requirements-mineru.txt"
python -m pip install -r "MinerU method/requirements-docling.txt"
python -m pip install -r "MinerU method/requirements-baml.txt"
```

复制 `.env.example` 为 `.env`，填入自己的 OpenAI-compatible API 配置。`.env`、原始论文、Excel 标签、模型缓存和运行输出均已由 `.gitignore` 排除。

### API 协议

默认使用 `ARTICLE_AGENT_API_MODE=chat_completions`。如需使用 Responses，在本地 `.env` 中设置：

```dotenv
ARTICLE_AGENT_API_BASE_URL=https://api.lvping.cloud/v1
ARTICLE_AGENT_API_MODE=responses
```

客户端会请求 `/v1/responses`，将文本和图片转换为 Responses 的 `input`，使用 `text.format` 保留 JSON 输出约束。完整输入不会被裁剪，服务端截断关闭，不完整或拒绝响应会作为失败处理。配置的备用地址沿用同一协议，不会自动回退到 Chat Completions。该选项不更改模型、提取提示词或评分逻辑；原生 BAML 客户端不经过此适配器。

## 运行

```powershell
python "MinerU method/run.py" --pdf "path/to/article.pdf" --parser auto --use-api
```

也可以直接处理已经生成的 Markdown：

```powershell
python "MinerU method/run.py" --pdf "path/to/article.pdf" --markdown "path/to/article.md" --use-api
```

## 数据政策

仓库不包含原始 PDF、`Datas/` 中的数据、Excel 金标准、API 密钥或本地运行结果。评分脚本保留在源码中，但需要使用者自行提供有权限使用的本地标签文件。
