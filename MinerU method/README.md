# MinerU 分模块抽取实验

面向使用者的最新版中文流程与 Skill 说明见
[`CURRENT_WORKFLOW_AND_SKILLS_CN.md`](CURRENT_WORKFLOW_AND_SKILLS_CN.md)。

这是一个独立实验目录，用于验证以下链路，不改变现有 Harness：

1. PDF 经 MinerU 转为 Markdown；
2. 按 Abstract/Introduction、Methods、Results/Tables 路由上下文；
3. 分别用 Pydantic 模型抽取元数据、STRICTA/干预、偏倚风险；Results 表格先由独立 LLM
（默认 `gpt-5.6-luna`）进行整表语义分类，再做确定性表头/列/行解析，按表、按目标行分块交给 LLM
识别结局、时间点和组间比较，保留全部原始记录；
4. 对已抽取的结局再执行一次独立 LLM 后处理：只添加规范化、重复组和金标准冲突标记，原始结局值逐条保留，不用金标准反向填值；随后基于论文证据生成独立 `outcomes.canonical.json`，重复/冲突来源进入 `conflict_groups`，不删除原始记录；
5. 将 Figure 1 所在页渲染为图片，交给 VLM 抽取 CONSORT 样本流；
6. 对文本、表格和流程图中的随机数/脱落数进行交叉核对。

## 混合解析与证据链（新增）

`--parser auto` 会先调用 PyMuPDF 做入口审计，并把决策保存为
`pdf_text_layer.json`、`parser_route.json`：原生文本层完整、编码健康、公式较少的文档优先
Docling；扫描件、文本层不完整、多栏混排或公式密集文档优先 MinerU Pipeline/VLM。
Docling/MinerU 未安装或运行失败时只回退到带明确警告的 PyMuPDF，不会把回退结果标成第三方
引擎。也可以用 `--force-backend docling|mineru|pymupdf` 做可重复 A/B 测试。

```powershell
python "MinerU method/run.py" --pdf "Datas/articles/2015/-2015-01.pdf" --parser auto --no-vlm
```

核心项目中的 `article_agent.document_pipeline` 还会生成
`normalized_document.json`：

`run.py --parser auto|docling` 也会在文章输出目录直接生成该文件，便于在不重新调用 API 的情况下检查布局、公式和表格拓扑。

- block 级坐标、章节和阅读顺序（可选 RT-DETR/DocLayout-YOLO；未安装时使用可审计的 bbox 规则）；
- 公式原文/LaTeX 保留（可选 UniMERNet；没有模型时标记 `unavailable`，不猜测）；
- HTML + OTSL 表格拓扑，以及同列头相邻跨页表的 `stitched_from` 关系；
- 重复页眉、页脚、页码和水印在规范化视图中剔除，原始 `article.md` 与分片响应不删除。

`article_agent.evidence_engine` 提供 PaperQA 风格的 RCS 流程：Crossref、Semantic Scholar、
Unpaywall 元数据可作为 header 注入每个 chunk；候选池硬上限为 1000，先稀疏向量/BM25，再对
每个候选做可选 LLM 二次评分和 query-specific contextual summary；引用遍历和矛盾检测均保留
所有来源；生成器要求 `[cite: DOI/Chunk_ID]` inline 引用。`search_pdf_rcs` 和
`answer_pdf_question` 可直接被上层 Agent 调用。

结构化抽取优先支持 `baml_src/clinical_extraction.baml` 生成的 BAML 客户端；未配置
`ARTICLE_AGENT_BAML_CLIENT_MODULE` 时，`BamlExtractor` 使用同一 Pydantic 模型和 OpenAI-
compatible JSON 请求作为兼容回退。可选依赖见 `requirements-baml.txt`。

模型字段使用 `registry/legacy-excel/*.json` 中的 canonicalFieldId，并在输出
`excel_bindings.json` 中保留 Sheet、列、中文表头和代码本。每个结论必须携带原文引文；
没有证据时返回 `NR`/未报告枚举，禁止猜测。

## 环境

所有命令必须使用项目的 `Agent` conda 环境。

```powershell
conda activate Agent
pip install uv
python -m uv pip install -r "MinerU method/requirements-mineru.txt"
```

MinerU 较大，因此未加入项目的默认依赖。安装后 CLI 会自动寻找 `mineru` 或旧版
`magic-pdf` 命令。不同 MinerU 版本的 CLI 参数可能变化，可先单独生成 Markdown，再用
`--markdown` 运行后续抽取。

Docling 与 BAML 也作为可选依赖单独固定版本：

```powershell
D:\Application\Anaconda\envs\Agent\python.exe -m pip install -r "MinerU method/requirements-docling.txt"
D:\Application\Anaconda\envs\Agent\python.exe -m pip install -r "MinerU method/requirements-baml.txt"
D:\Application\Anaconda\envs\Agent\Scripts\baml-cli.exe generate
```

生成 BAML 客户端不会自动改变现有 API 抽取；设置
`ARTICLE_AGENT_STRUCTURED_BACKEND=baml` 或 `ARTICLE_AGENT_BAML_CLIENT_MODULE` 后才启用。

当前 Windows 安装默认显式使用兼容性更好的 `pipeline` 后端。若已正确安装 CUDA Torch，
可用环境变量 `ARTICLE_AGENT_MINERU_BACKEND=hybrid-engine` 切换。若 Hugging Face 下载失败，
可在首次运行前设置 `MINERU_MODEL_SOURCE=modelscope`；成功下载后 MinerU 3.4 会持久化模型源。

## 运行

真正的 MinerU 路径：

```powershell
python "MinerU method/run.py" --pdf "Datas/articles/2015/-2015-01.pdf" --parser mineru --use-api
```

已有 MinerU Markdown：

```powershell
python "MinerU method/run.py" --pdf "Datas/articles/2015/-2015-01.pdf" --markdown article.md --use-api
```

仅用于验证路由和模型的显式回退基线：

```powershell
python "MinerU method/run.py" --pdf "Datas/articles/2015/-2015-01.pdf" --parser pymupdf --use-api
```

默认输出到 `outputs/mineru_method/<article-id>/`。`routed_context.json` 可直接检查每个
模块究竟收到了哪些章节；`raw_module_responses/outcomes.tablewise.manifest.json` 记录每张结果表的行数和调用状态，
`raw_module_responses/outcomes.table-classification-NNN.json` 保留整表语义分类响应，
`raw_module_responses/outcomes.table-NNN.part-MM.json` 保留逐表分块模型响应。

后处理结果写入 `outcomes.postprocessed.json`。每条记录包含 `source_index`、完整的
`source_outcome`、`conflict_status`（`none|conflict|unresolved|not_checked`）、
`conflict_fields`、`conflict_reason` 和 `value_preserved=true`；
`raw_module_responses/outcomes.postprocess.manifest.json` 记录后处理分片、缓存和失败状态。

每条 `OutcomeStatistic` 还携带以下来源身份字段：

- `table_id`、`row_id`：稳定回指 MinerU 表格和原始行；
- `arm`：所有明确出现的试验臂（标签、角色、n 和组内值）；
- `comparison`：实际比较关系及参与比较的臂；
- `analysis_set`：原文 FAS、PPS、LOCF、MMRM 等分析集/模型标签；
- `record_role`：`primary|secondary|safety|subgroup|sensitivity|baseline|administrative|other|NR`。

`outcomes.canonical.json` 是从这些来源记录和无损规范化注释生成的独立视图，包含
`records` 和 `conflict_groups`。canonical 代表行只是可复核的导出代表，不等于冲突已解决；
文件中 `gold_used=false`，因此不会依据 Excel 金标准改写任何论文值。

后处理批次可以通过以下环境变量调节：

```powershell
$env:ARTICLE_AGENT_OUTCOME_WORKERS = "1"
$env:ARTICLE_AGENT_OUTCOME_POSTPROCESS_BATCH_SIZE = "4"
$env:ARTICLE_AGENT_OUTCOME_POSTPROCESS_WORKERS = "1"
$env:ARTICLE_AGENT_OUTCOME_REQUEST_DELAY_SECONDS = "0.01"
$env:ARTICLE_AGENT_TABLE_CLASSIFIER_MODEL = "gpt-5.6-luna"
$env:ARTICLE_AGENT_BASIC_MATCH_MODEL = "gpt-5.6-luna"
$env:ARTICLE_AGENT_RETRY_MODEL = "gpt-5.6-sol"
$env:ARTICLE_AGENT_TABLE_CLASSIFIER_RETRIES = "1"
$env:ARTICLE_AGENT_TABLE_CLASSIFIER_MAX_CHARS = "0"  # 仅为兼容保留；分类输入不截断
$env:ARTICLE_AGENT_COMPACT_API_PROMPTS = "0"  # 关闭历史紧凑提示词；请求按完整表/行分片
$env:ARTICLE_AGENT_OUTCOME_WHOLE_TABLE_TIMEOUT = "15"  # 整表只作覆盖探测，随后按行补齐
$env:ARTICLE_AGENT_EVAL_OUTCOME_ROWS_PER_REQUEST = "4"  # 评价分片完整覆盖 source_index
$env:ARTICLE_AGENT_EVAL_MODEL = "gpt-5.6-sol"  # 可在评分失败时临时切换为 gpt-5.6-luna
$env:ARTICLE_AGENT_HTTP_TRANSPORT = "urllib"  # 当前网关环境避免 Schannel SEC_E_NO_CREDENTIALS
$env:ARTICLE_AGENT_TLS_VERIFY = "1"  # 仅在受控环境诊断自签名代理证书时临时设为0
$env:ARTICLE_AGENT_API_BASE_URL = "https://api.example.com/v1"
$env:ARTICLE_AGENT_API_FALLBACK_URLS = "https://backup-1.example.com/v1,https://backup-2.example.com/v1"
```

结局表分片和结局后处理默认均为串行发送（每次最多一个分片在途），每次实际 API 请求前等待 10ms；可通过上述环境变量调整。
Windows 上检测到 `curl.exe` 时，客户端默认使用 Schannel 传输，避免部分兼容网关与
Anaconda OpenSSL 发生 TLS renegotiation `record layer failure`；设置 `ARTICLE_AGENT_HTTP_TRANSPORT=urllib`
可显式恢复 Python urllib。API 请求按 `ARTICLE_AGENT_API_BASE_URL` 后接
`ARTICLE_AGENT_API_FALLBACK_URLS` 的顺序尝试；某个地址成功后会暂时提升为后续分片的首选，
下一个失败时再继续切换。地址可用逗号、分号或换行分隔，末尾是否带 `/v1` 均可。
