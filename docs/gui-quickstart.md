# GUI 取数快速指南（四板 + TCM 重合触发）

从安装到取出四板符合事件波形，全部操作在 GUI 内完成。
目标触发逻辑：(dev1|dev2) AND (dev3|dev4)。

## 0. 安装（新电脑二选一）

**方案 A：exe（推荐，免 Python）**

```text
1. 拷贝 daq-gui-0.4.0.exe + profiles/daq.yaml（或整个 daq-gui-0.4.0-win64 目录）
   到新电脑
2. 按需修改 profiles/daq.yaml 里的 IP（默认 192.168.10.10/.12/.13/.14 + TCM .16）
3. 双击 daq-gui-0.4.0.exe
4. 启动后自动加载 profiles/daq.yaml；若未加载，点顶部 [加载 Profile] 手动选择
```

**方案 B：zip（Python 3.12）**

```text
1. 安装 Python 3.12（勾选 Add to PATH）
2. 解压 zip → 运行 install_offline.ps1（右键 PowerShell 执行）
3. 复制 example.template.yaml → profiles/<你的配置>.yaml（改 IP）
4. 运行：daq-gui --profile profiles/<你的配置>.yaml
```

## 1. 板卡 tab — 配置四块板（每块重复）

### 1.1 先配 ADC + 时钟（固件重烧/断电后必须！）

```text
1. 设备下拉选 dev1
2. 『板卡配置』勾选：☑ ADC  ☑ 时钟   （触发/TCP-mode2 不勾）
3. 点 [配置板卡]，等它跑完（每块约 1 分钟，3 次重试自动）
```

> ⚠️ 不做这步 ADC 数据全 0 → 标定无效、TCM 链路 hit 恒 1 无脉冲。
> 四块板都做完再继续。

### 1.2 TCM 触发链路（mode 9 面板）

面板默认值已按生产配置预置，核对即可：

| 字段 | 默认 | 含义 |
|---|---|---|
| 0x10 Trigger_model | 9 | TCM 触发返回 |
| 0x19 Trigger_position | **74** | 实测标定：信号居中 |
| 0x65~66 mask | **0x0FFF** | ch0..ch11 或逻辑（12 通道） |
| 0x67~68 polarity | **0x0FFF** | 全部负脉冲（SiPM） |
| 0x69~6A debounce | 200 | 1μs |
| 0x6C width | 20 | M21 脉冲 100ns |
| 0x6B enable | ☑ | 过阈脉冲输出 |

操作顺序：

```text
1. 确认 mask/polarity（上面默认值，不用改）
2. 点 [自动标定]（秒数 5、偏移量 100 = 基线-100）→ 16 通道建议阈值填入表单
3. 点 [应用全部并回读验证] → 结果区显示回读一致
4. 换下一块设备，重复 1.1 + 1.2
```

> 标定要点：每块板基线不同（约 1940-2040），自动标定按各自基线生成阈值；
> 阈值全 0 时应用会被拒绝并提示先标定。

### 1.3 验证单板链路（可选）

TCM tab → show → 看 sticky/最近触发通道；或用示波器看 M21 脉冲。

## 2. TCM tab — 配置重合触发

```text
1. 确认 TCM 下拉是 main
2. 配置：
   enable       ☑
   mask         (任意，重合模式不用 OR)
   pulse_width  32
   debounce     20
   重合使能     ☑
   组数         2
   窗口         4
   组0 mask     0x03   (dev1|dev2)
   组1 mask     0x0C   (dev3|dev4)
   组0/1 N      1, 1   (每组至少 1 板触发)
3. 写配置 → 回读验证
4. show → 看 GRP_OK / sticky
```

## 3. 采集 tab — 取数

```text
1. 多板采集
2. 组: four_board
3. ☑ 无 ack 放行（默认开——TCM MISO ack 链路未全通时不会卡）
4. 聚合 key: timestamp、匹配窗口 10
5. ☑ JSON（解码事件） ☑ raw（原始帧）
6. 点 [开始采集]，看 busy 指示；完成后结果区显示 complete/partial 事件数
```

## 4. 结果检查

```text
输出目录：out/multi/<组名>_NNNNN/
  raw/           每板原始事件帧（complete_events.dat）
  decoded/       聚合解码 JSON（boards_present_mask=15 = 四板齐全）
  logs/          monitor.jsonl（事件率/fps）
```

判断"四板同事件"：JSON 里 `boards_present_mask: 15`（全 4 板）且
`event_kind: complete`。

## 5. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 标定采到全 0 | 固件重烧后 ADC/时钟未配 | 回到 1.1 |
| 应用全部后 TCM 无触发 | 阈值全 0 / 字节序旧版 | 重新标定；确认用 v0.4.0 包 |
| TCM show 无 sticky | M21 未连 TCM / 阈值没穿越 | 查线缆；看板卡 tab 自动标定值 |
| 多板采集卡在 align | ack 不全但放行没开 | 勾选 ☑ 无 ack 放行 |
| 信号不在窗口中间 | Trigger_position 不对 | 换拓扑后重新标定（见 traps §1.5） |

## 6. 参考

- 配置陷阱细节（字节序/标定表）：`docs/hardware-notes/2026-08-12_tcm-link-config-traps.md`
- CLI 命令用法：`docs/usage.md`
