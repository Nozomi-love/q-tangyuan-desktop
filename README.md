# Q弹汤圆 · Phase 1

本地离线桌宠与免费养成项目，使用 Python 3.10+、PySide6 6.8.3。当前已完成桌宠物理、四张元宝汤圆表情适配与固定位置记忆。

[GitHub 私有仓库](https://github.com/Nozomi-love/q-tangyuan-desktop) · [项目规范](docs/项目规范.md) · [开发日志](docs/开发日志.md) · [素材记录](docs/素材记录.md) · [目录说明](docs/目录说明.md)

![四种表情的实际渲染预览](docs/images/phase1-artwork.png)

## 运行

本机已在项目内的 .venv 安装依赖，PowerShell 执行：

    Set-Location -LiteralPath 'D:\Codex\Q弹汤圆'
    .\.venv\Scripts\python.exe main.py

已激活项目虚拟环境时，也可以执行 python main.py。新电脑首次安装：

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe main.py

资源相对于 main.py 定位。修改程序代码后请重启旧桌宠进程；只更换图片或 expressions.json 时，可使用“重新加载表情 PNG”。

## 固定位置

1. 右键桌宠或托盘，勾选“固定当前位置（可拖动调整）”。
2. 左键拖到想要的位置，松手后留在那里。
3. 固定时仍会呼吸、切换表情和果冻回弹，点击不再跳离固定锚点。
4. 取消勾选后恢复重力与抛投。
5. 固定开关和位置自动保存，下次启动会恢复。位置按所在显示器工作区比例记录，适配分辨率变化；显示器不存在时回退主屏并限制在可见区域。
6. “重置回主屏幕右下角”保留固定开关，将固定位置一起移到主屏右下角。

位置保存在 data/save_data.json，不上传 GitHub。写入时保留其他数据字段，校验失败或写入失败会在终端提示并保留原文件。测试脚本使用独立测试存档；启动冒烟模式不读写用户位置设置。

## 默认表情

原始图片保存在 assets/skins/default/，由同目录 expressions.json 映射：

| 状态 | 当前原始图片 | 触发条件 |
| --- | --- | --- |
| idle | ChatGPT 图像 2026年10月16日 14_01_36.png | 默认待机 |
| happy | ChatGPT 图像 2026年10月16日 14_01_42.png | 点击后 0.8 秒 |
| dizzy | ChatGPT 图像 2026年10月16日 14_01_47.png | 左键拖拽期间 |
| flat | ChatGPT 图像 2026年10月16日 14_01_53.png | 测试饿扁开启 |

当前四张原图均为 1254×1254、不带透明通道的白底 RGB PNG：
- 加载时在内存中去除与画布边缘连通的近白色背景，保留轮廓内的白色身体和碗内高光。
- 以最大连通主体对齐底部和显示比例；眩晕图的星星仍显示，但不会让主体缩小。
- 按主体比例等比缩放，保留元宝碗造型；饿扁由程序统一压至约 40% 高度。
- 原始图片没有被重命名、覆盖或重新编码；来源与 SHA-256 见素材记录。
- 托盘图标使用同一待机外观，热加载时同步更新。

仍兼容原有 idle.png、happy.png、dizzy.png、flat.png 文件名；同名标准文件存在时优先使用。没有对应图片时先回退 idle，最后使用无五官圆形兜底。损坏、全透明、超限图片会被跳过并提示。输入最长边上限 4096，渲染缓存最长边 768。

完整用户皮肤上传、GIF 与 manifest 动作包按 Phase 4 推进。

## 交互验收

1. 启动后观察透明、置顶、无边框窗口与托盘；汤圆应在主屏幕工作区右下角。
2. 静置：高度约 ±3.3% 呼吸，宽度反向补偿，碗底贴住工作区底边。
3. 单击：瞬间压扁变宽、轻跳和回弹；开心表情 0.8 秒后恢复。
4. 按住轻移不足 5 逻辑像素后松手仍算点击，超过阈值后才进入拖拽。
5. 拖到高处左右晃动：眩晕表情与星星可见，倾角平滑且不超过 ±18°。
6. 横向甩出后松手：保留部分惯性，重力下落，边缘反弹；高处落下应有更强落地压缩。
7. 拖动后停住约 0.2 秒再松手：不应沿用很早以前的甩动速度。
8. 托盘或右键切换饿扁，检查难受表情、40% 高度与贴地；再次切换后恢复。
9. 如有多屏，拖到另一屏再松手，检查该屏工作区；可修改缩放或任务栏占用区再检查落点。
10. 测试托盘复位、PNG 热加载与退出；退出后桌宠和托盘同时消失。

Phase 1 双击表现为连续戳一戳；后续主面板接入双击打开，空翻使用独立菜单。

## 模块

| 文件 | 职责 |
| --- | --- |
| main.py | 应用控制器、托盘、共享菜单、异常退出与启动诊断 |
| pet_engine.py | 状态、形变、弹簧、重力/碰撞、图片预处理和渲染 |
| pet_window.py | 透明 Tool 窗口、60 Hz 调度、Qt 坐标映射、多屏、固定位置与鼠标事件 |
| save_manager.py | 固定开关/位置持久化、原子写入、保留其他存档字段 |
| requirements.txt | 固定 Qt 依赖 |
| styles/theme.qss | 柔和菜单样式 |
| assets/skins/default/expressions.json | 默认表情文件名与加载方式 |
| tests/test_phase1.py | 51 项物理、渲染与交互回归测试 |
| tests/verify_native.py | Windows 原生属性、托盘动作与退出验证 |
| tests/verify_artwork.py | 四表情、去白底、白色身体、原图散列和预览验证 |
| tests/verify_pinning.py | 两个独立原生进程验证关闭/重启后的固定位置 |

后续核心模块为 models.py、dashboard.py。运行存档、虚拟环境、测试产物和备份不提交到 Git。

## 验证

    .\.venv\Scripts\python.exe -B tests\test_phase1.py
    .\.venv\Scripts\python.exe -B tests\verify_artwork.py
    .\.venv\Scripts\python.exe -B tests\verify_native.py
    .\.venv\Scripts\python.exe -B tests\verify_pinning.py
    .\.venv\Scripts\python.exe -B main.py --smoke-test

行为测试可设置 QT_QPA_PLATFORM=offscreen。原生验证适用于 Windows，自动打开本程序窗口并退出。测试产物保留于 tests/artifacts/。

实际验证环境：Windows、Python 3.12.6、Qt 6.8.3、单显示器、150% 缩放。34 项行为测试、实际素材验证及原生托盘验证通过。多块物理显示器、其他操作系统和 Python 3.10 尚未实测；负坐标工作区与多种更新频率已通过模拟验证。

目标更新频率 60 Hz，按实际时间推进；物理子步最多 1/240 秒，长停顿最多推进 0.1 秒。实际显示流畅度受系统负载与桌面合成影响。地面遵循系统 availableGeometry；任务栏自动隐藏时按系统报告的工作区处理。

## 持续开发记录

用户已授权在本项目后续开发任务结束后自行提交和推送经过验证的进展。每个阶段更新开发日志并保留清晰提交；初始 Phase 1 基线与本次素材适配分开记录。规则见 AGENTS.md。
