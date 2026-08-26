# AutoOps RAG Demo

## 当前 React Demo

下面的图片来自当前 `frontend/` React + TypeScript 页面。它用于展示 workflow-level SSE、最终回答、实际引用、Evidence 和 Trace；不是 Token Streaming 截图。

![当前 React Demo](images/react-demo-current.png)

当前页面在 `completed` 事件后依据真实 Trace 展示：

- Planner attempted / applied / skipped / fallback；
- 结构化 Plan、steps 和 budget；
- Tool selected、executed、reused、deduplicated；
- Retrieval、Rewrite 和 Evidence Gate；
- Generation mode 与 Citation Guard action；
- Completed/Error、latency 和 stop reason。

运行方式见仓库根目录 `README.md` 和 `操作手册.md`。截图中的数据只说明一次真实演示链路，不作为正式指标来源；当前正式指标只读取 `reports/formal_evaluation.json` 与 `.md`。

## 当前 canonical evaluation

- Dataset：`formal_eval_v1`
- Hash：`3b33876cd584e6215ef03a8bb07d0566aa57371957e606196c37b6f26641a4d9`
- Split：`test`
- Cases：20
- Generation mode：`local_extractive`
- `LLM_ENABLED=false`

当前指标和分母见 `docs/current-status.md`。Retrieval Recall 不等于最终回答准确率。

## Historical / stale / 历史版本截图

以下六张图片保留用于说明旧原生页面和项目演进，不代表当前 React Demo、当前 corpus、当前测试数量或当前 canonical evaluation：

1. `images/01-首页问答.png`
2. `images/02-Trace页面.png`
3. `images/03-检索结果.png`
4. `images/04-安全拒答.png`
5. `images/05-测试与校验.png`
6. `images/06-评测指标.png`

这些旧图可能出现 16969 chunks、12035 表格行、1861 张表、53 passed、旧 `nDCG@5` 或旧原生页面布局。它们必须以 **Historical / stale / 历史版本结果** 阅读，不能复制到 README 作为当前结果。

## 截图维护规则

- README 只展示 `react-demo-current.png` 和当前 canonical evaluation 表格；
- 替换当前截图时必须使用当前 React 页面；
- 裁掉浏览器账号、用户目录、设备 IP 和本机隐私信息；
- 不得出现 `.env`、API Key、Authorization、Bearer、`sk-`、raw data 或数据库内容；
- Planner、SSE、LLM mode 和评测数字必须与截图对应的真实运行一致；
- 历史截图保留原文件名，并始终放在 historical 小节。
