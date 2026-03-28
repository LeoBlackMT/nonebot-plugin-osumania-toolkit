## 概述

`builder` 目录用于编译 ETT 管线所需的 `official_minacalc_runner` 可执行文件。

该 runner 直接调用 Etterna MinaCalc，能提供与官方更接近的 ETT 结果。当 Etterna MinaCalc 更新后，建议重新编译 runner，避免插件结果与新版本 Etterna 偏离。

## 目录约定

构建脚本默认查找以下目录（注意：`etterna-master` 需要放在 `builder` 目录内，而不是同级）：

```
nonebot_plugin_osumania_toolkit/
	builder/
		build_official_runner.cmd
		build_official_runner.sh
		build_official_runner_linux_docker.cmd
		official_minacalc_runner.cpp
		etterna-master/
			src/Etterna/MinaCalc/MinaCalc.cpp
			...
```

## 第一步：准备 Etterna 源码

在 `builder` 目录下执行：

```bash
git clone https://github.com/etterna/Etterna.git etterna-master
```

如果目录不是 `etterna-master`，请改名，否则脚本会报找不到 `MinaCalc.cpp`。

## 第二步：按平台构建

### Windows（MSVC）

前置条件：

- Visual Studio 2022（含 C++ 桌面开发工具）或可用的 `cl.exe`

执行：

```bat
cd builder
build_official_runner.cmd
```

成功后产物：

- `builder/official_minacalc_runner.exe`

### Linux / WSL（g++）

前置条件：

- `g++`（建议支持 C++20）

执行：

```bash
cd builder
chmod +x build_official_runner.sh
./build_official_runner.sh
```

成功后产物：

- `builder/official_minacalc_runner`

### Windows（Docker 构建 Linux runner）

前置条件：

- Docker Desktop 运行

执行：

```bat
cd builder
build_official_runner_linux_docker.cmd
```

可选：自定义镜像

```bat
set ETT_LINUX_BUILD_IMAGE=your/image:tag
build_official_runner_linux_docker.cmd
```

成功后产物：

- `builder/official_minacalc_runner`

## 第三步：放置产物到插件目录

将产物复制到：

- `nonebot_plugin_osumania_toolkit/algorithm/ett/official_minacalc_runner.exe`
- 或 `nonebot_plugin_osumania_toolkit/algorithm/ett/official_minacalc_runner`

注：
- ETT 管线会按操作系统自动选择 runner
- Linux 下确认文件有执行权限（`chmod +x official_minacalc_runner`）

## 第四步：运行验证

触发插件 `/ett` 分析任意 mania 谱面。