# Changelog

All notable changes to `daq-cli` are documented in this file.

Each version is tagged as `v<version>` on the `main` branch. The detailed
snapshot of the v0.1.x line (commands, firmware contract, architecture,
release flow) is archived in `docs/version-snapshot-v0.1.4.md`.

## [v0.4.0] - 2026-10-28

多板采集原生化（采集内核 + 输出格式字节级兼容）+ 可部署 exe。

### Added

- GUI/exe 启动时自动发现 profile：`DAQ_PROFILE` 环境变量 → exe 同级
  `daq-profile.yaml` / `profile.yaml` → `profiles/` 下唯一的 YAML。
  便于把 exe 和一份配置拷到新电脑后直接双击运行。
- 两个入口（`daq-gui` / `daq`）在启动最前面调用
  `multiprocessing.freeze_support()`，修复 PyInstaller onefile 下
  spawn 后端（JSON/TXT 解码、波形 watch）重复执行入口的问题。
- GUI 标题显示当前版本号。
- `infrastructure/rbcp.py`：原生 SiTCP RBCP（UDP）客户端，线格式与
  vendored `lib/rbcp.py` 逐字节一致（8 字节头、packet_id 回环、bus-error
  位、毫秒超时）。
- `infrastructure/multi_board_acquire/`：原生多板采集内核（TCM 对齐、
  每板接收线程、按 `timestamp`/`event_count` 聚合、聚合写盘、monitor
  jsonl、run_meta 状态机）。落盘格式与 `multi_board_acquire.py` 字节级相同。
- `infrastructure/adapters/multi_capture_runner.py` +
  `multi_board_watch.py` + `multi_board_decode_backend.py`：原生 runner、
  波形 watch 发布器/后端进程、tail-read 解码后端。
- `DAQ_MULTI_VENDOR=1` 环境变量：临时切回 vendored 多板路径，便于上机
  A/B 对比；该路径计划删除。

### Changed

- 相对 `output_dir` 的解析：profile 位于 `profiles/` 目录时保持原行为
  （`<profile>/../out`）；profile 不在 `profiles/` 下时改为解析到 profile
  同级目录，方便 exe 部署。
- `_TcpSentRawStreamReader` 增加 `adc_length` 参数与 `read_frame()`（返回
  解析出的头部字段），`read_packet()` 行为不变。多板接收此前无法正确解析
  `adc_length != 256` 的配置（历史 run 中实测有 64）。
- watch 路径不再重编码帧：直接把接收到的原始 wire 字节交给
  `decode_tcp_sent_packet`，删除了 `_legacy_frame_to_tcp_sent_packet`。
- `multi_board_decode.py` 新增 `INDEX_ENTRY_FMT`/`INDEX_ENTRY_SIZE`，writer
  与 reader 共用同一份 struct 定义。

### Fixed

- 多板 watch publisher 在多个接收线程并发调用下会无锁改字典（可能触发
  `dictionary changed size during iteration`）；现已加锁。

## [v0.3.2] - 2026-08-12

缪子成像测试驱动的 GUI 与稳定性改进。

### Added

- GUI mode 9 面板：每通道新增**偏移量输入框**（标定基线 ± 值，偏移优先
  于绝对阈值），自动标定后填入建议偏移，无需重跑标定即可微调阈值。

### Fixed

- `measure_tcm_link` 的 mode/send_mode 切换加 RBCP 重试（SiTCP UDP 丢包
  曾使自动标定整体失败）。
- `calibrate_from_stream` TCP 连接失败重建 socket 重试（复用超时 socket
  触发 WSAEISCONN）。

## [v0.3.1] - 2026-08-12

TCM 触发链路修复与 GUI 配置流程改进（四板联调实测驱动）。

### Fixed

- **TCM 链路阈值字节序**：固件 `RBCP.v` 的 `TCM_THR = {x64..x46,x45}` 拼接使
  0x45 落在低字节（0x46=高字节），与早期文档"高字节在前"相反。此前所有
  经 daq-cli/手动 RBCP 配置的阈值都错位（写 1700 实际 0xA406=42054）→
  负极性恒满足 → hit 恒 1 → 无上升沿 → M21 永无脉冲。`read/write_tcm_link_config`
  已按实测字节序修复（mask/polarity/debounce 仍为高字节在前）。
- **`write_tcm_link_config` RBCP 写入重试**：16 通道×2 字节=32 次连续写入，
  偶发 UDP 丢包曾导致整个配置中止；现每字节写重试 3 次（带 backoff）。
- **GUI 板卡 tab mode 9 面板默认值**：`Trigger_position` 5→74（实测标定：
  窗口 256 采样/512 值下信号居中）；`mask`/`polarity` 0x0003/0x0000 →
  **0x0FFF**（ch0..ch11 或逻辑，负脉冲 SiPM）。
- **GUI 配置流程**：应用全部前检查阈值全 0（负极性永不触发）并提示先
  自动标定；面板加推荐配置顺序提示（固件重烧后先配 ADC/时钟 → 标定 → 应用）。

### Changed

- `profiles/example.template.yaml` 更新为四板生产模板（dev1-4 + TCM、
  `four_board` 组、`adc_length: 256`、`trigger_position: 74`、timestamp
  聚合放行无 ack）。
- 陷阱文档 `docs/2026-08-12_tcm-link-config-traps.md` 补充实测字节序与
  Trigger_position 标定表。

## [v0.3.0] - 2026-08-10

Desktop GUI console (tkinter, zero new dependencies) wrapping the full CLI
surface.

### Added

- `daq-gui` dedicated entry point (selects the TkAgg matplotlib backend
  before any pyplot import) and a `daq gui` subcommand.
- Main window: profile bar with file dialog, four-tab notebook, shared
  capped log panel, clean shutdown of background work.
- 板卡 tab: info / sysmon / trigger-show / tcp-mode2-show / config-show /
  tcm-link-show, board config form (steps, trigger params, thresholds,
  send-mode), TCM link config form, reg-read hex dump.
- 采集 tab: single capture with live progress bar (progress callback
  marshalled through a queue), multi capture with busy state and result
  summary (watch disabled; waveforms belong to the monitor tab).
- 监视 tab: live / demo / replay waveform monitoring embedded via
  `FigureCanvasTkAgg`, reusing `WaveMonitorFigure` and the pure loop state
  machine with RUN/STOP/SINGLE buttons; stopping restores the original
  `send_mode` through the existing session context.
- TCM tab: show config + status (sticky / pending / wide pulse / last
  trigger channels), config with readback verification and clear-sticky.
- GUI helpers (background task marshalling, result formatting) are
  tkinter-free pure functions with unit tests (19 new tests).

## [v0.3.0+] TCM coincidence trigger (unreleased)

4-group coincidence mode on the TCM board, matching FDU-TCM firmware
`5fc2bbc`+ (registers `0x27..0x2F`): `trigger = AND over enabled groups of
(group channel count >= N)`.

### Added

- `daq tcm config` options: `--coincidence/--no-coincidence`,
  `--coinc-groups` (0..4, 0 = default 2), `--coinc-window` (0..255,
  0 = default 4), `--coinc-masks` / `--coinc-ns` (4 comma-separated values).
- `daq tcm show` / `tcm config` readback: coincidence enable, group count,
  window, per-group masks/Ns, `grp_ok`, `collecting`, `collected_count`,
  `coinc_timeout_sticky`.
- GUI TCM tab: 符合触发 section with enable / group count / window /
  4× group mask + N entries, shown in readback.
- Tests extended for the new read/write paths (167 passing).

## [v0.2.0] - 2026-08-10

Frame format upgrade (28-byte header + fine timestamps) and TCM trigger-link
support. Requires ADC firmware `64c2885`+ (fine stamps) / `b02db46`+ (TCM
trigger link) for the new features; old 20-byte frames remain decodable.

### Added

- 28-byte TCP_SENT frame header support (format version in byte 19):
  `crossing_fine` / `accept_fine` fields and wrap-safe `delta_fine` on
  decoded events, JSON, and TXT outputs.
- Version-aware parsing everywhere (native decoder, live single capture,
  wave monitor, vendored multi-board script, aggregated files), so old and
  new firmware frames coexist during transitions.
- Aggregated format v2: board chunks carry fine fields; v1 files still read.
- `daq board tcm-link-show <device>` — read TCM trigger-link configuration
  (0x45..0x6C) without writing.
- `daq board tcm-link-config <device> --mask ... --thr ...` — write the TCM
  trigger-link configuration with readback verification (single-value
  broadcast or 16 threshold values).
- `Trigger_model = 9` support (TCM-trigger source) in `board config`.
- `daq tcm show <name>` / `daq tcm config <name>` — TCM board trigger-link
  configuration and status (0x20..0x25): enable, 8-bit mask, pulse width /
  debounce (20M cycles), sticky/pending/wide-pulse status, last trigger
  channels. Write path verifies by readback.
- TCM profile entries now load as typed `TcmConfig` (name/ip/rbcp_port).
- Vendored `FPGA_CTRL.py` synced from upstream (TCM config functions,
  trigger_model 0..9).

### Changed

- Vendored `multi_board_acquire.py` synced from upstream; FrameParser keeps a
  documented byte-19 version discrimination divergence.
- Text event outputs include `format_version` / `crossing_fine` /
  `accept_fine` / `delta_fine`.

## [v0.1.4] - 2026-08-10 (archived)

Archive point before the next development cycle. Contains everything from
`v0.1.3` plus the following unreleased commits.

### Added

- Configurable capture text outputs (`defaults.*.outputs.text`) with segmented
  TXT event files (`max_events_per_file`, `waveform_layout`).
- Indexed run directories via `allocate_next_run_dir` (`<prefix>_<NNNNN>`).

### Fixed

- Wave monitor viewer bug.
- Multi-board acquire viewer bug.
- Multi-board viewer bug.

## [v0.1.3] - 2026-06-15

### Fixed

- Bug in the multi-board acquire viewer.

## [v0.1.2] - 2026-06-15

### Changed

- Wave monitor viewer y-range handling.

## [v0.1.1] - 2026-06-14

### Added

- Vendored legacy scripts under `src/daq_cli/_vendor/fdu_legacy/` so the
  package no longer depends on the external hardware project at runtime.
- Offline Windows release packaging (`scripts/build_release.ps1`,
  `scripts/install_offline.ps1`).

## [v0.1.0] - 2026-06-09

### Added

- Project skeleton with layered architecture (cli / application / domain /
  infrastructure / presentation).
- Profile-driven device loading (`profiles/example.yaml`).
- `daq board` read-only config inspection commands:
  `trigger-show`, `tcp-mode2-show`, `config-show`, `reg-read`.
- `daq acquire multi <group>` wrapping the legacy `multi_board_acquire.py`
  workflow (TCM alignment, aggregation, decode, watch).
- `daq monitor wave <device>` waveform monitoring preview (live / demo /
  replay) with keyboard-driven `RUN` / `STOP` / `SINGLE`.
- `daq acquire single` decode, watch, and profile defaults.
- Streamed decode during multi-board capture.
- Release packaging guide (`docs/publish-release.md`).
