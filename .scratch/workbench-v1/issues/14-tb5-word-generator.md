# TB-5 · Word 成品（模板机制）

Status: closed — 已实现（待编排者提交）
规格：08-v1-unified-spec.md
阻塞边：TB-3（12）；与 TB-6（15）互不阻塞

## 窄路径（四层触点）

- **schema**：生成记录（任务、方案、格式、产物位置、所用模板、时间）；模板登记（名称、格式、是否默认）。
- **API**：对已确认方案触发生成；模板缺失 / 损坏时明确报错，绝不静默退回空白生成；按格式维护全局默认模板与任务级临时覆盖。
- **UI**：生成入口、进度状态、产物打开入口；模板选择（默认与临时覆盖的区分不混淆）。
- **测试**：产物可被文档库打开、标题级别与正文样式映射正确；负测——模板缺失报错路径。

## 关键决策落地

- 内置最小默认模板保证开箱可用；用户模板放入模板目录即可替换，机制不变；每次生成记录实际所用模板。

## 演示证据

确认方案 → 生成 .docx → 用 Word 打开样式映射正确；换一份用户模板再生成一次，样式随模板变化。

## 验收

产物打开与样式映射证据；模板报错负测绿。

## Comments

- 2026-10-19 后端实现者（deepseek-v4.1-flash，TDD red-green-refactor）：本单 **后端窄路径** 已实现。前端（生成面板 / 成品卡 / 设置页「默认模板」整区）不在本单范围，**未触碰 `frontend/**`**。

### 实现摘要（写了什么）

- **schema**（`backend/app/db/database.py`）
  - `generations` 严格按规格 §4：`id, task_id, plan_id, format, file_path, template_used, created_at`；`format` 限 `docx|html`；索引 `idx_generations_task`。
  - **模板登记表（自行定名，工单要求「名称、格式、是否默认」）**：`templates(id, name, format, is_default, created_at)`。`name` = 相对 `templates/` 的 posix 相对路径；`is_default` 同格式互斥。**任务级临时覆盖不落本表**（只落 `generations.template_used`），这正是「临时选择不改变全局默认」在数据层的表达。
- **生成入口做真**（`backend/app/api/routes/generations.py`）：`POST /api/tasks/{id}/generations` 从 501 接到真实 Word 管线，闸门判定**逐字保留**（无方案 / `draft` / 有未处置待确认事项 → 409；任务不存在 → 404）。新增 `GET /api/tasks/{id}/generations` 供成品卡列记录。
- **Word 管线**（新包 `backend/app/generation/`）
  - `plan_document.py`：结构化方案 Markdown → 块序列（标题 / 正文 / 列表 / 表格），`####+` 夹到 3 级（内置模板只定义到 `Heading 3`）；解析不了的整行按正文处理，不丢内容。
  - `templates.py`：内置最小默认模板、登记校验、模板解析（临时覆盖 > 全局默认 > 内置默认）。
  - `word.py`：写入 + **回读完整性检查**（US 22）。先写 `.part` 再原子替换，不留半成品。
  - `service.py`：编排「解析模板 → 写入 → 完整性检查 → 落库」，**先确认产物合格再落库**；检查未过则 `unlink` 产物并抛错。
- **模板管理 API**（`backend/app/api/routes/templates.py`）：`GET /api/templates`（清单：目录实际情况 + 是否默认 / 内置 / 可用 / 已登记 / 文件已缺失）、`POST /api/templates`（登记）、`PUT /api/templates/{name}/default`（设全局默认）。
- **安全边界**：`templates/` 与 `data/`（成品落 `data/deliverables/{task_id}/`）为白名单；模板名统一 `_normalize_relative` + `_resolve_within`，`..` / 绝对路径 / 盘符一律拒（`../secret.docx` → 400「越出」）。
- **可配置目录**：`create_app(..., data_dir=, templates_dir=)` 供测试指向临时目录；`config.py` 新增 `TEMPLATES_DIR` / `DELIVERABLES_SUBDIR`。运行时默认仍是仓库 `data/`、`templates/`。

### 内置模板产出方式与理由（取舍）

**选了「首次运行时用 python-docx 幂等生成」到 `templates/_builtin/minimal-default.docx`，未随仓库附带二进制。** 理由：
1. `templates/` 在 `.gitignore` 里（运行时目录），附带二进制会与既有 `.gitignore` 约定冲突，或需要为一份几十 KB 的生成物开白名单例外；
2. 用 python-docx 自带 `default.docx` 为底再**显式重设**六类样式（`Heading 1/2/3` 20/16/14pt 加粗、`Normal` 11pt、`List Bullet`、`Table Grid`，并设 eastAsia 中文字形 `微软雅黑`），生成逻辑即模板内容的文档，可复现、可评审；
3. 幂等（已存在即返回，不重写），实测 mtime 不变由测试断言。

### 两个硬陷阱的处理方式（调研笔记 02-A2，源码级证据已复核）

1. **`.dotx` / `.dotm` / `.docm` 打不开**：本地复核 `docx/api.py:28` 确为 `document_part.content_type != CT.WML_DOCUMENT_MAIN → ValueError`。对策＝**后缀白名单只放 `.docx`**，且**登记时也真开一次** `Document(path)`——于是「把 .dotx 改名成 .docx」同样被拒，两种情形都返回 400「请在本机把该文件另存为 .docx 后再试」。测试用一个**主部件内容类型被改成 template.main+xml** 的真实 .docx 复现了改名场景（非 mock）。
2. **模板样式未定义会 `KeyError`**：写前逐块用 `name in document.styles` 探测；缺失则该块走**两段式回退**（标题＝加粗 + 字号；列表＝`• ` 前缀普通段落；表格＝无样式表格），并把该样式记入 `missing_styles`，产物元数据标 `template_style_applied: false`。降级**可见**，不静默。
3. **模板缺失 / 损坏绝不静默退回空白生成**（工单硬要求 + US 19）：`resolve_template` 对显式指定的模板与已登记的全局默认都只抛 `TemplateError`（→400），**不回落**到内置模板；全局默认文件被移走的场景有专门测试。

### 验证证据（真实输出）

```
> backend\.venv\Scripts\python.exe -m pip install python-docx
Requirement already satisfied: python-docx in .\backend\.venv\Lib\site-packages (1.2.0)
Requirement already satisfied: lxml>=3.1.0 in .\backend\.venv\Lib\site-packages (from python-docx) (6.1.3)
（首次安装输出：Successfully installed lxml-6.1.3 python-docx-1.2.0）

> backend\.venv\Scripts\python.exe -m pytest --no-header
180 passed in 23.05s

> backend\.venv\Scripts\python.exe -m ruff check backend
All checks passed!
```

- `python-docx>=1.1` 已写入根 `pyproject.toml`（依赖唯一来源，不另建 requirements.txt）。
- 测试文件：新增 `backend/tests/test_generation_word.py`（正测：产物可打开 + 标题级别 / 正文 / 列表 / 表格样式映射 + 记录实际所用模板 + 内置模板幂等）、`backend/tests/test_generation_templates.py`（模板机制与全部负测）。
- **测试敏感度自证**（防止同义反复）：故意把 `ALLOWED_TEMPLATE_SUFFIXES` 放开为 `.dotx`、把写前样式探测改成恒 `True`，`test_dotx_template_is_rejected_with_save_as_docx_hint` 与 `test_template_without_required_styles_falls_back_and_flags_it` 立刻转红；改动已还原。
- **闸门回归绿**：既有 `test_convergence / test_open_items / test_plan_revision` 的 409 判定未动；其中 4 处原本断言「放行后 501」的用例已按本单改为断言 201（并额外断言产物文件存在）——这是本单把 501 占位做成真的必然后果，非放宽。
- `test_history.py` 里「成品文件数是弱依赖」的用例原先在测试内自建 `generations` 表，现表已由本单落地，改为直接写真实表的两行验证计数口径。

### 演示记录（可复现）

脚本：`backend\scripts\demo_word_deliverable.py`（进程内 HTTP 接缝 + 内联脚本化模型替身，不起端口、不联网、零花费）。在仓库根运行：

```
> backend\.venv\Scripts\python.exe backend\scripts\demo_word_deliverable.py
任务 6｜方案 3｜状态 confirmed｜确认时间 2026-10-19T11:43:12.320849+00:00

=== 1. 内置最小默认模板（开箱可用，未登记任何模板）===
{ "id": 4, "task_id": 6, "plan_id": 3, "format": "docx",
  "file_path": "E:\\AI-ThinkForge\\data\\deliverables\\6\\plan-3-20261019114312.docx",
  "template_used": "_builtin/minimal-default.docx",
  "created_at": "2026-10-19T11:43:12.376922+00:00",
  "template_style_applied": true, "missing_styles": [], "headings": 7, "integrity_ok": true }

[内置默认模板] 回读 data\deliverables\6\plan-3-20261019114312.docx
  标题数：7
    Heading 1  | 结构化方案
    Heading 2  | 目标
    Normal     | 让新员工在入职两周内掌握产品全貌。
    Heading 2  | 读者
    Normal     | 新入职员工。
    Heading 2  | 章节
    Heading 3  | 产品定位
    Normal     | 从场景切入，而非功能罗列。
    Heading 3  | 核心场景
    List Bullet | 早晨开工
    List Bullet | 日常答疑
    Heading 2  | 关键约束
    Normal     | 篇幅控制在十页以内。
    表格样式 Table Grid：项 | 值 / 篇幅 | 10 页

=== 2. 任务级临时覆盖：换成用户模板，样式随模板变化 ===
登记： {'template': {'name': '演示模板-大标题.docx', 'format': 'docx', 'is_default': False,
       'builtin': False, 'usable': True, 'registered': True, 'missing': False}, 'default_template': None}
生成： { "id": 5, "template_used": "演示模板-大标题.docx", "template_style_applied": true, ... }
[用户模板] 回读 …plan-3-20261019114312-2.docx（同 7 个标题 / 1 个表格，样式名一致）
产物的 Heading 1 字号：28.0 pt （内置默认模板为 20.0 pt）
模板清单（临时覆盖未改变全局默认）：
  [('演示模板-大标题.docx', False, False), ('演示模板-无标题样式.docx', False, False),
   ('演示模板.dotx', False, False), ('_builtin/minimal-default.docx', False, False)]

=== 3. 负测：模板缺失 / 非 .docx，明确报错且不产出成品 ===
缺失模板 → 400 模板文件不存在（任务级临时覆盖）：不存在的模板.docx
dotx 模板 → 400 只接受 .docx 模板（任务级临时覆盖：演示模板.dotx）；请在本机把该文件另存为 .docx 后再试

=== 4. 陷阱 2：模板缺 Heading 样式 → 回退 + template_style_applied=false ===
template_style_applied = False ｜missing_styles = ['Heading 1', 'Heading 2', 'Heading 3']
回退后的标题（加粗直接格式）： ['结构化方案', '目标', '读者']

已生成成品记录：3 份
产物目录：E:\AI-ThinkForge\data\deliverables\6
```

- 产物是标准 `.docx`，可直接双击用 Word 打开；本单的样式映射证据是**回读产物**（`python-docx`）而非只看文件存在——「用 Word 打开看」这一步属人工验收，见下「遗留」。
- 演示写入的是**真实运行时目录**（`data/deliverables/`、`templates/`，均 gitignore）：`templates/` 里留下的三个模板文件正是「用户模板放进 `templates/` 即可替换」的现场证据。

### 遗留 / 需要后续处理

1. **UI 未做**（本单范围外）：生成面板 / 成品卡 / 设置页「默认模板」整区属前端子单；后端已提供所需接口与数据（`GET/POST /api/templates`、`PUT /api/templates/{name}/default`、`GET /api/tasks/{id}/generations`、生成响应含 `template_style_applied` / `progress` 之外的元数据）。**侧栏脚额度进度条（TB-5/TB-6 缺口）数据源已就绪**（生成记录数），待前端接线。
2. **模板上传入口未做**：用户需自己把 `.docx` 放进 `templates/`，登记 API 只接受「已放入的文件名」。文件上传（`multipart`）与扩展名校验属 TB-7 的上传校验一并做，避免两套上传约定。
3. **`file_path` 存的是绝对路径**：个人本地工作台可接受且无歧义（`data_dir` 可配置，测试指向临时目录）；若日后要迁移 / 换机，需要「相对仓库根」的迁移脚本。已在 `generations.file_path` 注释里说明。
4. **「用 Word 打开」的人工验收未做**：自动化只做到「文档库可打开 + 回读样式映射正确」。建议验收时双击 `data/deliverables/6/*.docx` 目视确认（复杂模板的页眉页脚 / 页面布局保留边界遵循 ADR-0003「不承诺无损」口径）。
5. **未做**（本单范围外，勿误当已实现）：单文件 HTML 演示（TB-6，`format=html` 现返回 501）、PPTX、`docxtpl` 式模板填空、模板版本管理、模板删除（`templates` 表只增不删，删除留待有需求时补）。