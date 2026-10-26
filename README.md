# 家电管家 · Appliance Assistant

基于 Open WebUI 的家电客户服务智能体，将选购、产品对比、订购、使用指导和预约报修串联起来。覆盖洗衣机、空调和冰箱，新增界面沿用 Open WebUI 的极简样式。

## 功能

- **商城**：产品图片、参数筛选、型号对比，选定后进入原生对话继续订购。
- **订单与售后**：查看订单和报修记录，修改或取消安排；地址簿支持新增、编辑、默认地址及删除。
- **陪我操作**：选择准确型号或已购订单，根据说明书、现场图片和反馈，一次提供一步指导，保留操作记录和资料依据。
- **一起做方案**：根据预算、容量、烘干、匹数等条件计算跨品类组合，支持保留型号和调整需求。
- **计划调整**：识别生活安排变化影响的订单及预约，核对原表单后确认变更。
- **空间预览**：结合房间照片与商品参考图生成摆放效果，支持查看历史与下载。项目内默认每分钟一张、串行生成。

## 实现

应用复用 Open WebUI v0.12.3 的界面、聊天、工具交互、记忆、文件及图片编辑接口。LiteLLM 负责文字模型路由和后备切换，图片理解使用 Gemini；云端知识检索使用 Vertex AI Search。组合金额、库存和业务记录由程序处理，模型负责理解需求和解释结果。

`openwebui-slim/` 保存应用代码、素材、配置示例和测试。`open-webui.patch` 保存对上游已有文件的修改，`webui-overlay/` 保存新增界面。`prepare_webui.py` 按固定提交恢复上游源码并应用修改，避免重复分发完整上游仓库。

## 配置与运行

当前启动脚本面向 macOS、Homebrew 和 Conda，使用 Node.js 22、PostgreSQL 18 与 Python 3.12。脚本中保留了 Homebrew/Conda 的默认安装位置，其他环境需要调整路径。此仓库不包含已安装依赖、数据库、云资源或任何可直接使用的认证信息。

1. 复制 `openwebui-slim/.env.example` 为 `.env`，填写自己的模型密钥、随机应用密钥、数据库密码和 Google Cloud 配置。文件只供本机使用，不提交 Git。
2. 准备 Conda 环境 `jiadian-webui`、`jiadian-litellm`，分别安装 `requirements-slim.txt`、`requirements-litellm.txt`。在 WebUI 环境另外安装 `open-webui==0.12.3`（使用 `--no-deps`，依赖已由 slim 清单提供）。
3. 执行 `python3 openwebui-slim/prepare_webui.py` 恢复固定版本源码；在 `webui-src` 下安装前端依赖，执行 `python3 openwebui-slim/build_frontend.py` 构建。构建复用已安装 Open WebUI 包内的 Pyodide 资产。
4. 按 `services.py` 的连接约定初始化 PostgreSQL：数据目录 `openwebui-slim/data/postgres`，端口 `54329`，角色 `jiadian`，数据库 `knowledge`，并启用 pgvector 扩展。密码必须与 `.env` 一致。启动脚本复用这些资源，不自动创建角色或数据库。
5. 按自己的 Google Cloud 项目修改 `cloud-rag.json` 中的 `YOUR_PROJECT_ID`，创建自己的 Vertex AI Search 数据存储与检索引擎，再对应调整 `litellm.yaml`。服务账号文件由自己提供，不能放入仓库。
6. 执行 `python3 openwebui-slim/services.py`；本机访问 `http://127.0.0.1:3000`。执行 `install_shop.py` 注册商城工具、素材和模型预设，执行 `configure_images.py` 配置图片接口后重启 WebUI。该脚本会给原生图片编辑请求补上 Vertex 所需的 `role=user` 字段。
7. 按 Open WebUI 的外部工具服务设置接入 `cloud-rag-openapi.json` 所描述的 LiteLLM 检索接口；配置自己的服务认证。执行 `sync_knowledge.py` 将源文档同步到自己的存储与知识库。

外部请求按现有脚本经 `127.0.0.1:7897` HTTP 代理；本机服务间通信绕过代理。没有该代理的环境需要调整相关脚本。文字模型名和接口取决于自己的供应商，配置中的名称是可调整的部署别名。

启动配置使用仅监听本机的免登录模式，适用于个人本机运行；部署到网络环境请按 Open WebUI 文档启用登录并配置服务访问权限。

## 数据与验证

JG 系列为自建的虚构产品资料，图片为生成式视觉素材，价格、库存和履约状态属于本项目数据，不能冒充真实品牌商品或实际履约。保留的厂家资料链接与自建资料分别标明来源。订单、报修提交前使用事实说明是否收款、发货或派人。

仓库不附带聊天历史、地址、订单、工单、记忆、运行日志、截图或个人云资源配置。应用运行时会在忽略的本地数据目录中生成这些内容。

测试使用 Python unittest。在 `openwebui-slim` 目录下，可针对每个 `tests/test_*.py` 单独运行 `python -m unittest discover -s tests -p <文件名>`。夹具会替换部分运行依赖，建议逐文件启动独立进程。最近本地验证中，四项生活助手功能及原订单、地址、售后相关的 84 项测试通过；模型与云服务结果仍取决于部署者的配置。

## 来源与许可

上游项目：[Open WebUI](https://github.com/open-webui/open-webui)，固定提交 `91ea4e3421d1d8069f13d4a463fcb5986d94ea60`。保留 Open WebUI 品牌和许可证要求。参见 `NOTICE`、`OPEN_WEBUI_LICENSE` 与 `OPEN_WEBUI_LICENSE_HISTORY`；不能将整个项目误标为 MIT。第三方资料及依赖继续适用各自权利和许可。
