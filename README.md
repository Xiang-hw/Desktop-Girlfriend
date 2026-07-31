# 一图桌宠（OnePic Desktop Pet）

上传一张角色图片，让 Agent 帮助生成、配置并优化一个可以在 Windows 桌面上跑动、休息、互动和自拍的桌面宠物。

当前项目是仅加载已确认专属女孩素材的私有版本，公开演示角色及其动作素材已经移除。

## 当前功能

- 透明无边框窗口、桌面置顶和多显示器 DPI 适配；
- 站立、跑动、坐下、入睡、醒来、拖拽和自拍连续动画；
- 摸头、分区点击、连续戳击、悬停注视和情绪反馈；
- 跑动结束后随机站立、坐下或自拍；
- 默认 5 分钟无互动后坐下、10 分钟后入睡；
- 右键尺寸调整、暂停跑动、隐藏和退出；
- 用户可在本地放入自己的自拍成片，不提交到 Git；
- 原图登记后自动作为自拍成片，保持原始像素尺寸；
- 标准角色形象和走路 GIF 必须分别得到用户确认；
- 表情符号由程序独立绘制，换角色后仍可显示闪光、爱心、惊叹号、疑问号、怒气、Zzz 和汗滴；
- PyInstaller Windows 打包脚本。

## 最快体验

未来正式 Release 会提供可直接运行的 Windows 版本，不需要安装 Python。当前本地候选版请先执行：

```powershell
.\scripts\check_environment.ps1
.\scripts\setup_environment.ps1
.\Start-CodexPet.ps1
```

环境脚本只在项目内创建 `.venv` 并安装依赖，不会自动安装 Python、Git，不会修改系统环境变量，也不会申请管理员权限。缺少 Python 3.12 时会停止并给出提示。

`Start-CodexPet.ps1` 是当前私有版的推荐入口。它会安静启动桌宠本体；如果 CodexPet 已经在运行，则不会重复启动。需要强制重启时运行：

```powershell
.\Start-CodexPet.ps1 -Restart
```

## 从一张图片开始

完成环境安装后，先登记最初上传的图片：

```powershell
.\scripts\start_onepic.ps1 -SourceImage "图片的完整路径"
```

该命令会在 `user_assets/source/` 保留原始文件副本，并生成同分辨率的 `user_assets/selfie.png`。原图、自拍图和流程状态全部被 Git 忽略。

接下来先选择生成风格：`preserve_original`（保留原画风，默认）、`light_chibi`（轻度 Q 版）或 `full_chibi`（完整 Q 版）。Agent 只能先生成一张标准角色形象，登记人物特色并交给用户确认：

```powershell
.\.venv\Scripts\python.exe .\tools\onepic_workflow.py character-candidate `
  --image "标准角色候选图路径" `
  --style preserve_original `
  --feature "有辨识度的脸型和眼型" `
  --feature "原图中的发型、服装和标志性配饰"
```

随后必须打开确认窗口。只有用户亲自查看候选图并点击“符合，这就是我要的角色”后，动作门禁才会通过：

```powershell
.\.venv\Scripts\python.exe .\tools\onepic_workflow.py approve-character
```

生成动作后还必须生成并查看走路 GIF：

```powershell
.\.venv\Scripts\python.exe .\tools\onepic_workflow.py walk-review
.\.venv\Scripts\python.exe .\tools\onepic_workflow.py approve-walk --yes
```

没有完成两个确认，程序不会加载私有角色，个人版本打包也会被阻止。

更换角色后应直接启动私有版本，逐项检查全部表情和互动动作。

## 自定义自拍照片

把照片命名为下列任意一种形式：

```text
user_assets/selfie.png
user_assets/selfie.jpg
user_assets/selfie.jpeg
```

通常不需要手动复制：`start_onepic.ps1` 会自动把最初上传的原图转换为全分辨率 `selfie.png`。`user_assets/` 中的图片默认被 Git 忽略。没有提供原图时，自拍动作仍会播放，但不会用生成动画末帧冒充原照片。

## 测试与打包

```powershell
.\scripts\test.ps1
.\scripts\build.ps1
```

项目仅支持私有版本打包。角色和走路均确认后运行 `.\scripts\build.ps1`，构建结果会包含
`user_assets/`。

打包结果位于：

```text
dist/OnePicDesktopPet/OnePicDesktopPet.exe
```

## 一图制作流程

Agent 应先检查环境，再建立项目、处理原图、生成动作、检查多头多腿和裁切问题、接入行为状态机、运行测试，最后在用户验收后打包。详细流程见：

- [Agent 执行入口](agent-guide/AGENT_GUIDE.md)
- [一图桌宠执行说明书](agent-guide/一图桌宠执行说明书.md)
- [素材规范](docs/素材规范.md)
- [角色与走路验收清单](docs/角色与走路验收清单.md)
- [隐私说明](docs/隐私说明.md)
- [私有分发清单](docs/发布清单.md)

## 当前状态

本工作区已经改为私有专用版，只加载 `user_assets/pet/manifest.json`，不再提供或回退到公开演示角色。

## 授权

- 程序代码和项目文档：MIT License；
- `user_assets/`：本机私有素材，不属于 MIT License 范围，未经素材所有者明确授权不得公开。

详细范围和署名方式见 [素材授权说明](ASSETS_LICENSE.md)。
