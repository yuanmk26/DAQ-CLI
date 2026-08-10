# daq-cli v0.3.0 GUI 控制台计划

> 状态：**已全部实现（2026-08-10）**，含 G0~G5。落笔时间：2026-08-10。
> 偏差记录：监视 tab 未嵌入多板 demo（多板查看保留在 CLI `daq monitor
> multi-demo`）；单板波形嵌入已完整实现。
> 前置：v0.2.0（28B 帧格式 + TCM 触发链路）已完成并推送。

## 1. 背景与目标

用户需要一个**完整 GUI 控制台**：设备/组管理、板卡配置（含 TCM 链路）、
单/多板采集控制、实时波形监视、TCM 板配置——即 CLI 的图形化全集。

已确认决策：

- 框架：**tkinter**（stdlib，环境已有 8.6；matplotlib 3.11.1 的 TkAgg 后端直接可用）
- 零新依赖 → 离线发布流程（wheelhouse）不变
- 版本号：**v0.3.0**

## 2. 架构设计

### 2.1 分层（GUI 只做薄壳）

```
src/daq_cli/presentation/gui/
  app.py              # 主窗口 Tk + profile 选择 + Notebook + 底部日志面板
  threads.py          # 后台任务调度：线程 + queue + root.after() 轮询（复用 wave_monitor 的 producer/drain 模式）
  boards_tab.py       # 板卡配置/回读/寄存器
  acquire_tab.py      # 单板/多板采集控制 + 进度
  monitor_tab.py      # 实时波形监视（matplotlib 嵌入）
  tcm_tab.py          # TCM 板配置/状态
  formatting.py       # 表单值 → service 参数、结果 → 可读文本（纯函数，可单测）
```

新增 CLI 入口 `daq gui`（`cli/gui.py`），app.py 注册。

**业务逻辑全部走现有 service 层**（board_service / acquire_service /
monitor_service / tcm_service / telemetry_service），application/infrastructure
**零改动**（除 §3.5 的一个可选增强）。GUI 只负责：收集参数、调用 service、
展示结果。

### 2.2 线程模型（关键）

- service 的阻塞操作（采集、live 监视、回读）在**后台线程**运行
- GUI 线程通过 `root.after()` 定时轮询 queue 取结果（复用现有
  `_drain_latest_frame` / producer → queue 模式，见
  `src/daq_cli/infrastructure/wave_monitor.py` 的 producer 类）
- **matplotlib 只在 GUI 线程更新**（FigureCanvasTkAgg 的限制）；波形帧经
  queue 送达后由 after 回调渲染
- 采集进度：`capture_single` 已有 `progress_callback`
  （`acquire_service.py`）——回调发生在工作线程，转 queue 再经 after 更新
  进度条
- **后端选择顺序（硬约束）**：`cli/gui.py` 入口必须在**任何
  `import matplotlib.pyplot` 之前**调用 `matplotlib.use("TkAgg")`——
  `wave_monitor_viewer.py` 模块顶部就 import pyplot，一旦被 import 后端就
  锁死，无法再改
- **波形循环复用纯函数层，不调用阻塞入口**：复用 `WaveMonitorFigure.update` /
  `_advance_loop_state` / `_drain_latest_frame`（by `after()` 驱动），
  **不要**调用 `run_wave_monitor_viewer` / `run_multi_board_wave_viewer`
  （它们是 `plt.ion()` + `plt.pause()` 的阻塞循环）
- 每 tab 单操作互斥：运行时禁用该 tab 按钮；跨 tab 并发（如 live 监视持
  send_mode=1 时再跑 board config）记日志提示，不强制阻止

### 2.3 主窗口布局

```
┌──────────────────────────────────────────────────────┐
│  [profile 路径] [加载]         设备/组状态栏           │
├──────────┬───────────────────────────────────────────┤
│ Notebook │                                           │
│  板卡    │  (每个 tab 自己的表单 + 结果区)             │
│  采集    │                                           │
│  监视    │                                           │
│  TCM     │                                           │
├──────────┴───────────────────────────────────────────┤
│  共享日志面板（Text widget，append-only）              │
└──────────────────────────────────────────────────────┘
```

界面文案用中文（实验操作员使用），控件命名遵循 CLI 选项语义。
**全局字体必须显式设置** `("Microsoft YaHei", 9)`（tkinter 默认字体不含
中文字形，否则中文显示为豆腐块）。

## 3. 组件清单

### G0. 入口与骨架

- `cli/gui.py`：`daq gui [--profile PATH]` 命令；**第一个动作**是
  `matplotlib.use("TkAgg")`（在任何 presentation import 之前）
- `gui/app.py`：主窗口、profile 加载（文件对话框/命令行参数）、Notebook、
  共享日志面板（**行数上限**，截断保留尾部，防长 capture log 撑爆）、
  关闭时清理后台线程（stop_event 模式）；**重新加载 profile 时刷新所有
  tab 的下拉（设备/组/TCM）并清空结果区**
- `gui/threads.py`：`run_in_background(fn, on_done)` 封装——线程执行 +
  结果/异常入队 + 轮询回调 GUI 线程；提供取消信号。**模块不 import
  tkinter**，通过注入的 `schedule(callback)`（=root.after）调度，保证可
  单测

### G1. 板卡 tab（对应 `daq board *`）

- 设备下拉（profile.devices）
- 操作按钮：`info` / `sysmon` / `trigger-show` / `tcp-mode2-show` /
  `config-show` / `tcm-link-show`
- 配置表单（`board config`）：step 开关（ADC/时钟/触发/TCP-mode2）、触发
  参数（mode/position/4 阈值/时间戳清零/外部触发/send-mode）
- TCM 链路配置表单（`tcm-link-config`）：mask/polarity/thr（单值广播或
  16 值）/debounce/width/enable
- `reg-read`：地址 + 长度 → hex 输出
- 结果渲染为只读文本框（复用 printers 的字段语义，纯文本即可）

### G2. 采集 tab（对应 `daq acquire single/multi`）

- 单板：设备、事件数、超时、send_mode、输出开关（raw/json/text/log）、
  `capture_single(progress_callback=...)` → 进度条（事件数/速率）+ 结果
  摘要 + 输出目录
- 多板：组、聚合 key（timestamp/event_count）、匹配窗口、TCM 无 ack 放行、
  输出开关、`capture_multi` → busy 指示 + 结果摘要（complete/partial 事件
  数）（multi 无 progress 回调，见 §3.5 可选增强）；**GUI 里固定关 watch**
  （`watch_waveforms=False`，否则 runner 会自己弹出独立 matplotlib 窗口，
  波形走监视 tab）
- 运行中按钮变"停止"：capture 无公开取消 API，停止只禁用控件、后台线程
  跑完自然结束（诚实语义写进界面提示）

### G3. 监视 tab（对应 `daq monitor wave` / `multi-demo`）

- 设备 + 源选择：live / demo / replay（文件选择）
- 波形区：`FigureCanvasTkAgg` 嵌入 `WaveMonitorFigure`（复用
  `presentation/wave_monitor_viewer.py` 的 update 逻辑）
- 控制按钮：RUN / STOP / SINGLE（替换原键盘事件）
- 复用 `MonitorService.open_live_wave_session` 等会话（frame_queue/
  stop_event 直接接线程模型）
- 多板 demo 按钮（复用 `open_multi_board_demo_wave_session`）

### G4. TCM tab（对应 `daq tcm show/config`）

- TCM 下拉（profile.tcm）
- show：配置 + 状态（sticky/pending/宽脉冲/最近触发通道）
- config：enable/mask/width/debounce + 清 sticky，回读验证结果展示

### G5. 测试与文档

- `tests/test_gui_formatting.py`：表单→参数构建、结果→文本渲染（纯函数）
- `tests/test_gui_threads.py`：queue/after 调度封装（不创建真实 Tk 窗口，
  只测调度逻辑）
- 现有 122 测试全绿
- 文档：usage.md 新章节（GUI 使用）、README 命令列表、CLAUDE.md、
  CHANGELOG v0.3.0、pyproject 版本

## 4. 可复用点清单（不重造轮子）

| 需求 | 复用 |
|---|---|
| 波形渲染 | `WaveMonitorFigure.update()`（matplotlib Figure，直接嵌 TkAgg） |
| 实时帧取用 | `MonitorService.open_*_wave_session` + `_drain_latest_frame` |
| 单板进度 | `AcquireService.capture_single(progress_callback=)` |
| 所有回读/配置 | `BoardService` / `TcmService` / `TelemetryService` 原样调用 |
| 多板聚合结果 | `MultiAcquireResult`（complete/partial 计数直接展示） |

## 5. 依赖与发布

- 零新依赖：tkinter 是 stdlib（Windows Python 默认自带，已确认 8.6），
  matplotlib 已有
- `build_release.ps1` 流程不变；离线包无需 wheelhouse 新增
- 版本 0.3.0：pyproject.toml + `__init__.py` + CHANGELOG

## 6. 测试策略

- GUI 薄壳原则：窗口代码保持薄，状态/参数/渲染逻辑下沉到纯函数（可单测）
- 不创建真实 Tk 窗口的单元测试（headless/CI 友好）；Tk 组件行为通过
  手动冒烟 + 板级联调验证
- 验证方式：`daq gui --profile profiles/example.yaml` 启动，逐个 tab 冒烟；
  demo/replay 源不需要硬件即可验证监视 tab

## 7. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 长任务冻结 UI | 所有 service 调用走后台线程 + after 轮询 |
| matplotlib 后端锁死/非 GUI 线程更新崩溃 | 入口强制 `matplotlib.use("TkAgg")` 前置；渲染只在 after 回调 |
| 误用阻塞 viewer 入口卡死主循环 | 只复用纯函数层（update/advance/drain），不调 `run_*_viewer` |
| 中文显示豆腐块 | 全局字体 Microsoft YaHei |
| capture 无法真正取消 | 停止=禁用控件等待完成；真取消需 runner 加可选参数（§8） |
| 同设备并发操作冲突 | 每 tab 单操作互斥；跨 tab 冲突记日志提示 |
| profile 重载后 tab 数据过期 | 加载按钮统一刷新各 tab 下拉并清结果区 |
| 长日志撑爆面板 | 日志面板行数上限截断 |
| capture_multi 无进度回调 | busy 指示 + 最终结果（可选增强见下） |
| Tk 组件的可测性差 | 逻辑下沉纯函数，窗口薄壳；threads.py 不 import tkinter |
| 关闭窗口时后台线程泄漏 | stop_event + join（带超时）模式复用 |

## 8. 可选增强（不阻塞主线）

- `capture_multi` 增加 `progress_callback`（仿 capture_single 模式，runner
  已写 monitor.jsonl，可在 GUI 尾部轮询展示事件率）——需要 application 层
  小改动，GUI 主线可以先不做
- capture_single/multi 增加可选 `cancel_event` 参数，让"停止"按钮真正中断
  采集（runner 内部循环轮询该 event）——需要 infra 层小改动

## 9. 实施顺序

```
G0（入口+骨架+线程封装）→ G1（板卡）→ G2（采集）→ G3（监视）→ G4（TCM）
→ G5（测试+文档+版本）
```

每步可独立提交、独立冒烟；G3 用 demo/replay 源即可无硬件验证。
