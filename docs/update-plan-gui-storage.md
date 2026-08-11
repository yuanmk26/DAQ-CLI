# GUI 存储配置计划（输出目录 + run 名前缀）

> 状态：计划文档，尚未开始实现。落笔时间：2026-08-10。
> 决策：方案 A——单板/多板采集页各加「存储」一行（目录 + 前缀），并修复
> GUI 绕过 profile 存储配置的缺口。

## 1. 背景与现状

存储目录结构：

```
<base_dir>                       ← profile defaults.output_dir（默认 out/）
  └─ single/ 或 multi/           ← 采集类型叶子（service 拼接）
      └─ <前缀>_00001/           ← run 目录（allocate_next_run_dir 递增）
          ├─ raw/event_00000.bin
          ├─ decoded/event_00000.json
          ├─ text/events_00001.txt（分段，max_events_per_file）
          ├─ logs/capture.log
          └─ capture_info.txt / run_meta.json
```

现有缺口：

1. GUI 采集页无目录控制——只能落默认 `out/single`、`out/multi`
2. **GUI 构造的 `outputs` 绕过 profile 存储配置**：GUI 传
   `AcquireOutputsConfig(dir=None)` 时 service 直接使用，profile 里配的输出
   子目录、`max_events_per_file`、`waveform_layout` 全部失效（CLI 尊重
   profile，GUI 不尊重）
3. run 名前缀固定 = 设备/组名，GUI 不可改

## 2. 改动点

### 2.1 service 层（小改）

- `AcquireService.capture_single` / `capture_multi` 增加
  `run_name_prefix: str | None = None` 透传：
  - multi：`LegacyMultiCaptureConfig.run_name_prefix`（字段已存在，直接接）
  - single：runner `capture_single` 增加同名字段 →
    `prefix=run_name_prefix or device.name`（runner 的 `_make_output_dir`
    调用处，`legacy_capture_runner.py`）
- `capture_single` 已有 `output_base_dir` 参数；`capture_multi` 已有
  `output_base_dir` ✓（无需新增）

### 2.2 formatting.py（纯函数，可单测）

- `default_output_base_dir(profile) -> Path`：复制 service
  `_default_output_base_dir` 的解析逻辑（`defaults.output_dir` 相对 profile
  根解析）——GUI 显示默认值时用；留空时仍然走 service 默认（行为不变）
- `merge_outputs_config(profile, page, raw/json/text/log 开关) ->
  AcquireOutputsConfig`：构造 outputs 时并入
  `profile.defaults.acquire_single|acquire_multi.outputs` 的
  `dir / max_events_per_file / waveform_layout`——GUI 开关只控制 enabled，
  存储细节回归 profile 配置（修缺口 2）

### 2.3 acquire_tab.py

单板/多板表单各加一行「存储」：

```
输出目录: [out/____________] [浏览…]   留空=profile 默认
run 名前缀: [dev1________]            留空=设备/组名
```

- 目录：`filedialog.askdirectory` 选择，Entry 显示；初始值 =
  `default_output_base_dir(profile)` 解析值（只读提示用，留空即默认）
- 前缀：Entry，默认设备/组名；切换设备/组时自动更新（仅当用户未手动改过）
- `_run_single` / `_run_multi`：填了目录就传 `output_base_dir`；前缀传
  `run_name_prefix`；outputs 改用 `merge_outputs_config`

### 2.4 测试

- formatting：`merge_outputs_config`（profile 目录/参数并入、开关独立）、
  `default_output_base_dir`（相对/绝对解析）
- service：`run_name_prefix` 透传（mock runner 断言 config 值，single 与
  multi 各一）
- GUI 冒烟：默认值显示、目录选择 mock、前缀修改 → mock service 断言参数

### 2.5 文档

- usage.md 采集章节补充「存储」行说明（目录/前缀语义、留空行为）

## 3. 验证

- `python -m pytest` 全量回归（149 现有 + 新增）
- GUI 冒烟：单板/多板页存储行显示默认值、改目录/前缀后 mock 断言透传
- 板级（文档提示）：真实采集后检查 run 目录落在所选位置、命名符合前缀

## 4. 明确不做

- 输出类型级子目录选择（方案 B 内容）——保持 profile 配置
- text 分段参数表单化——保持 profile 配置
- run 目录不递增、固定命名——保持 `allocate_next_run_dir` 语义
