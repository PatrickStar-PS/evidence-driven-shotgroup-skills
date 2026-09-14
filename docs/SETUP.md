# 运行与依赖

## 安装 Skill

将需要的 `skills/<skill-name>` 目录复制到个人 Codex skills 目录，或在当前 Codex 环境中以该目录注册。运行主流程时，还需保留相邻的 `person-trajectory-evidence/scripts/track_people.py`。这个目录只是依赖脚本，不含 `SKILL.md`。

## 基础运行条件

- Python 3（建议 3.10+）、Node.js、FFmpeg 与 FFprobe。具体命令与参数以各 Skill 的 `SKILL.md` 为准。
- 按阶段安装 Python 包：`requests`、`openpyxl`、`Pillow`、`numpy`、`opencv-python`；人物轨迹阶段另需 `ultralytics`，姿态增强另需 `mediapipe` 与独立取得的 JointBDOE 资源。
- Excel 导出使用 `@oai/artifact-tool`，该依赖由特定 Codex runtime 提供；普通 Node 安装环境中需自行解决这个依赖或替换导出适配器。
- 模型相关阶段需自行提供 中转站 凭据；TOS 传输阶段需对应授权与环境配置。密钥只放环境变量或本地私有文件，不放在仓库、命令清单或示例中。
- 主流程需要本项目的原始视频、八列资产表、全集台词台账与边界 JSON。缺少这些输入时不应启动完整流水线。

压缩件用于模型传输时，建议用 `--keep-source` 保留原片，供本地视觉证据和快速切镜复核。压缩默认目标 10 MB、24 fps；若 60 fps 原片在多人镜头下压得太糊，可用 `--fps 20` 做同大小候选对比，并检查眼神、嘴部及快速切镜是否丢失时间细节。

## 建议验证顺序

1. 运行 `python3 -m compileall -q skills` 检查 Python 语法。
2. 运行纯本地契约测试，例如 `python3 skills/adaptive-evidence-clipped-shot-groups/scripts/test_adaptive_range_planner.py` 和 `node skills/adaptive-evidence-clipped-shot-groups/scripts/test_shot_content_contract.mjs`。
3. 准备自己有权处理的短视频与资产，仅运行一个范围的 canary，人工复核切点、可见人物、台词和连续性，再扩大到整集。

仓库中某些 `SKILL.md` 保留了原 Windows 项目的路径示例与具体输出目录约定。迁移到新环境时，需要按项目实际目录设置输入和输出；前置编排脚本中的相邻 Skill 默认路径已改为随仓库定位，Node 默认从 `PATH` 查找。`workbench-project-db-import` 以当前目录的 `project_configs.db` 为默认数据库，也可通过 `--db` 指定。
