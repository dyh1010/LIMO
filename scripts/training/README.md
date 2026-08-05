# 农夫山泉瓶检测训练流水线

运行环境：`~/robotics/train/venv`（torch 2.11.0+cu128，ultralytics 8.4.115）。

## 使用顺序

```bash
source ~/robotics/train/venv/bin/activate

# 1. 自动预标注（COCO 预训练模型，未检出的照片会列出来需手标）
python prelabel.py \
  --images /mnt/c/Users/DYH/Desktop/limo_graphtest/original_graph/bottle/nf_bottle \
  --labels ~/robotics/train/work/labels

# 2. 人工检查预标注（重点看 missed 和 multiple boxes 列表）

# 3. 整理数据集并拆分 train/val（输出到 WSL 本地盘，训练更快）
python prepare_dataset.py \
  --images /mnt/c/Users/DYH/Desktop/limo_graphtest/original_graph/bottle/nf_bottle \
  --labels ~/robotics/train/work/labels \
  --out ~/robotics/train/datasets/nongfu_real

# 4. 训练 + 验证 + 导出 ONNX，权重拷贝回 Windows 数据集目录
python train_nongfu.py \
  --data ~/robotics/train/datasets/nongfu_real/data.yaml \
  --epochs 100 --patience 20 \
  --export-to /mnt/c/Users/DYH/Desktop/limo_graphtest/models
```

## 说明

- 类别固定为单类 `plastic_bottle`（ID 0），与 ROS 链路白名单一致。
- `prelabel.py` 可自动识别 COCO `bottle` 或单类别
  `plastic_bottle` 模型的来源类别；也可用 `--source-class` 显式指定。
- 每张图片只有一个目标时可传 `--max-boxes 1`，只保留最高置信度框。
- 引导训练或依赖尚未安装时可给 `train_nongfu.py` 传
  `--skip-onnx`，脚本仍会先保存并复制 `best.pt`。
- 预标注权重 yolov8n.pt 首次使用会自动下载（约 6 MB，来自 GitHub；
  慢的话先 `export https_proxy=http://127.0.0.1:7897`）。
- 首版只用 500 ml 农夫山泉同一实物，验证集指标会偏乐观，
  泛化到其他瓶子/场地需要后续补数据。
- 数据集与模型权重不进 Git（datasets/、models/ 已忽略）。
