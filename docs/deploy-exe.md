# 把 daq-gui 部署到新电脑

目标：把打包好的 exe 和一份 profile 拷到目标机，双击即可运行，无需安装
Python，也无需外部 legacy 项目目录。

> `scripts\build_gui_exe.ps1` 会在打包完成后自动生成下面的部署目录
> （`dist\daq-gui-<version>-win64\`）。

## 1. 目标机要求

- 64 位 Windows 10 / 11
- exe 所在目录可写（不要放在 `C:\Program Files` 下）
- 与 DAQ 板卡处于同一网段（默认 `192.168.10.x`），并能访问板卡的
  UDP `4660`（RBCP）和 TCP `24`（数据流）

## 2. 部署目录

```
daq-gui-<version>-win64\
  daq-gui-<version>.exe
  profiles\
    daq.yaml          ← 你的配置，首次运行前编辑 IP
  out\                ← 首次采集时自动创建
```

## 3. 首次运行

1. 用文本编辑器打开 `profiles\daq.yaml`，修改：
   - `devices.*.ip`：各 ADC 板 IP
   - `tcm.<name>.ip`：TCM 板 IP
   - `groups.*`：参与采集的板卡
   - `defaults.output_dir`：输出根目录（可保持 `out`）
2. 双击 `daq-gui-<version>.exe`。
3. 窗口标题栏显示版本号，profile 栏应自动显示
   `...\profiles\daq.yaml`。日志面板出现
   `Profile 已加载: ...`。

如果 profile 没有自动加载，点右上角的 **加载 Profile** 手动选择。

## 4. profile 自动发现规则

启动时（未传 `--profile`）按以下顺序查找：

1. 环境变量 `DAQ_PROFILE` 指向的文件；
2. exe 同级的 `daq-profile.yaml` / `daq-profile.yml` /
   `profile.yaml` / `profile.yml`；
3. exe 同级 `profiles\` 下**恰好一个** `*.yaml` / `*.yml`。

第 3 条要求目录里只有一个 YAML；有多个时不会猜，GUI 以空配置启动，
需要手动选择。

也可以用快捷方式显式指定：

```
daq-gui-0.4.6.exe --profile "D:\daq\profiles\daq.yaml"
```

## 5. 输出位置

- `defaults.output_dir` 是相对路径时：
  - profile 在 `profiles\` 目录下 → 解析到 `profiles\..\out`
    （即部署根目录下的 `out`）；
  - profile 不在 `profiles\` 下 → 解析到 profile 同级目录。
- `defaults.acquire_*.outputs.{json,text,log}.dir` 是相对路径时按**当前
  工作目录**解析。双击 exe 时工作目录就是 exe 所在目录；如果用快捷方式，
  请把快捷方式的“起始位置”设为 exe 所在目录。

最稳妥的做法：在 profile 里把需要长期保留的输出目录写成绝对路径。

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| 双击后几秒内没反应 | onefile 需要先把约 130MB 解压到 `%TEMP%`，冷启动 5–15 秒；杀毒软件可能进一步延迟 |
| 杀毒软件报毒/拦截 | 无签名的 PyInstaller onefile 偶尔会被误报，加入信任即可 |
| profile 没自动加载 | 检查 `profiles\` 下是否多于一个 YAML，或改用 `--profile` |
| 采集报 TCP / RBCP 超时 | 检查板卡 IP、网线、网段；先用 `ping` 和 `daq board info` 验证 |
| 界面正常但没数据 | 检查 `trigger_mode`、TCM 链路 enable、板卡是否在发流 |
