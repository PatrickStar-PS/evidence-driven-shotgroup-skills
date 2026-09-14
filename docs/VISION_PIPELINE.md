# 视觉证据方案：实现与库

这部分对应 [README 的 10 秒实图案例](../README.md)。五类主证据页是 `range_boundaries`、`action_events`、`high_motion_triplets`、`shot_space`、`person_trajectory`；复杂范围可加 `multi_person_geometry`。它们是给多模态分析的**证据页**，并非 CV 自动生成的最终镜头结论。[证据组织示意图](assets/evidence-map.svg)保留作流程参考。

| 阶段 | 实现方式 | 主要库 / 命令 | 对应代码 |
| --- | --- | --- | --- |
| 原片探测与候选切点 | 用 `ffprobe` 取时长等元数据；FFmpeg `scene_score` 逐帧评分后做峰值聚类，得到候选边界 | FFmpeg / FFprobe、Python 标准库 | [边界检测](../skills/adaptive-evidence-clipped-shot-groups/scripts/detect_video_shot_boundaries.py) |
| 范围剪辑 | 按候选边界划分逻辑核心，首尾加入重叠上下文；缓存校验视频与编码指纹 | FFmpeg、Python 标准库 | [范围规划](../skills/adaptive-evidence-clipped-shot-groups/scripts/plan_analysis_ranges.py)、[剪辑缓存](../skills/adaptive-evidence-clipped-shot-groups/scripts/clip_analysis_ranges.py) |
| 镜头空间页 | 抽帧后用 Haar 正面/侧面人脸、HOG 人体框产生候选；记录边缘接触、相对框位置、清晰度与光流等几何信息 | OpenCV、NumPy、Pillow | [几何分析](../skills/adaptive-evidence-clipped-shot-groups/scripts/cv_geometry.py)、[证据页](../skills/adaptive-evidence-clipped-shot-groups/scripts/build_context_sheet.py) |
| 动作帧与高运动三联帧 | 以相邻帧灰度差衡量运动，结合 MediaPipe Pose Lite 关键点变化挑选事件帧与前后帧；Pose Lite 初始化失败时退化为纯画面运动 | OpenCV、NumPy、MediaPipe | [动作证据](../skills/adaptive-evidence-clipped-shot-groups/scripts/build_pose_evidence.py) |
| 人物轨迹页 | 在镜头分区内按时间采样，YOLO 检测 person 类，BoT-SORT 关联轨迹；每个候选切点重置 ID，绘制落脚点路径 | Ultralytics YOLO、BoT-SORT、OpenCV、NumPy、Pillow | [轨迹脚本](../skills/person-trajectory-evidence/scripts/track_people.py)、[轨迹页](../skills/adaptive-evidence-clipped-shot-groups/scripts/assemble_trajectory_page.py) |
| 可选多人姿态 | 根据多人、画面边缘、框重叠等信号计算复杂度；启用时可把 JointBDOE 身体候选与逐人裁切的 MediaPipe Pose Lite 骨架融合 | MediaPipe、OpenCV、NumPy；外部 JointBDOE 模型 | [门控](../skills/adaptive-evidence-clipped-shot-groups/scripts/score_pose_complexity.py)、[融合](../skills/adaptive-evidence-clipped-shot-groups/scripts/fuse_jointbdoe_mediapipe.py) |
| 证据包封装 | 按角色拷贝 JPG，写入尺寸、字节数和 SHA-256；检查必需页与姿态门控是否一致 | Pillow、Python 标准库 | [证据包](../skills/adaptive-evidence-clipped-shot-groups/scripts/assemble_adaptive_evidence_pack.py) |

## PyTorch 在哪里

**这份仓库没有直接 `import torch`，没有自定义 PyTorch 网络、训练代码或微调。** 人物轨迹脚本调用 `ultralytics.YOLO(...).track(...)`，因此 YOLO 推理通过 Ultralytics 的深度学习栈**间接使用 PyTorch**；默认权重名是 `yolo11n.pt`，权重不随仓库分发。其余镜头切点、几何、帧差和证据拼版主要是 FFmpeg / OpenCV / NumPy / Pillow；MediaPipe 负责姿态关键点。

JointBDOE-S 是**可选的外部姿态模型**：仓库有消费其检测结果并与 MediaPipe 融合的脚本，但没有附模型权重或完整的 JointBDOE 推理入口。当前打包的前置命令清单使用 `build_pose_evidence.py` 生成的姿态证据页；要把 JointBDOE 融合接入实际运行，还需自行提供模型、推理输出与命令编排，并先核查许可。不要把它理解成默认流程已经开箱运行的 PyTorch 模块。

## 为什么不给 CV 最终裁决权

小人物、遮挡、虚焦和镜头重构都可能让检测框或轨迹不稳定。脚本因此把轨迹 ID 限定在单个镜头候选分区内，使用中点原帧作轨迹底图，并在证据包中保留来源和时间。多模态模型仍需看原片，逐一核对可见人物、动作和空间关系；本地校验可发出警告，但不自动改写身份、切点、台词或道具状态。
