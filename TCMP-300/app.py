"""Small PyQt5 desktop app for classifying TCMP-300 plant images."""

import csv
import re
import sys
from pathlib import Path

import torch
from PIL import Image, ImageFile, ImageOps
from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from torch import nn
from torchvision import models, transforms


ROOT = Path(__file__).resolve().parent
CHECKPOINT = ROOT / "runs" / "resnet50_7030_baseline" / "best.pt"
if not CHECKPOINT.is_file():
    CHECKPOINT = ROOT / "runs" / "resnet50_all300_old" / "best.pt"
CLASS_INFO = ROOT / "data" / "author_tcmp_300" / "tcmp-info-20250329.csv"
ImageFile.LOAD_TRUNCATED_IMAGES = True
PREPROCESS = transforms.Compose(
    [
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ]
)


def load_chinese_labels(classes):
    def normalize_latin(name):
        return re.sub(r"[^a-z0-9]", "", name.lower())

    with CLASS_INFO.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    by_number = {int(row["No"]): row for row in rows}
    if len(rows) != len(classes) or len(by_number) != len(classes):
        raise ValueError("类别信息 CSV 与模型的类别数量不一致")

    chinese_labels = []
    for label in classes:
        number, separator, latin_name = label.partition(".")
        if not separator or not number.isdigit() or int(number) not in by_number:
            raise ValueError(f"模型类别无法匹配 CSV：{label}")
        row = by_number[int(number)]
        if normalize_latin(latin_name) != normalize_latin(row["Latin Name"]):
            raise ValueError(f"模型类别与 CSV 学名不一致：{label}")
        chinese_name = row["Chinese Name"].strip()
        if not chinese_name:
            raise ValueError(f"CSV 缺少中文名：{label}")
        chinese_labels.append(chinese_name)
    return chinese_labels


class PredictionWorker(QThread):
    prediction_ready = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, checkpoint: Path):
        super().__init__()
        self.checkpoint = checkpoint
        self.image_path = None
        self.model = None
        self.classes = None
        self.chinese_labels = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def run(self):
        try:
            if self.model is None:
                saved = torch.load(self.checkpoint, map_location="cpu", weights_only=True)
                self.classes = saved["classes"]
                self.chinese_labels = load_chinese_labels(self.classes)
                self.model = models.resnet50(weights=None)
                self.model.fc = nn.Linear(self.model.fc.in_features, len(self.classes))
                self.model.load_state_dict(saved["model"])
                self.model.to(self.device).eval()

            with Image.open(self.image_path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                tensor = PREPROCESS(image).unsqueeze(0).to(self.device)

            with torch.inference_mode():
                scores = self.model(tensor).softmax(dim=1)[0]
                probabilities, indices = scores.topk(3)

            results = [
                (self.chinese_labels[index], probability)
                for index, probability in zip(indices.tolist(), probabilities.tolist())
            ]
            self.prediction_ready.emit(results)
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TCMP-300 中草药图像识别")
        self.resize(900, 560)
        self.image_path = None
        self.original_pixmap = None
        self.worker = PredictionWorker(CHECKPOINT)
        self.worker.prediction_ready.connect(self.show_prediction)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self.enable_buttons)

        self.preview = QLabel("请选择一张植物图片")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(460, 390)
        self.preview.setStyleSheet("background: #f0f4f0; border: 1px solid #d1dbd1; border-radius: 8px;")

        self.file_label = QLabel("尚未选择图片")
        self.file_label.setWordWrap(True)
        self.choose_button = QPushButton("选择图片")
        self.choose_button.clicked.connect(self.choose_image)
        self.predict_button = QPushButton("开始识别")
        self.predict_button.setEnabled(False)
        self.predict_button.clicked.connect(self.predict)

        self.status_label = QLabel("选择图片后开始识别")
        self.status_label.setWordWrap(True)
        self.result_title = QLabel("预测结果（前 3 类）")
        self.result_title.setStyleSheet("font-size: 17px; font-weight: bold;")
        self.results = QListWidget()
        self.results.setStyleSheet("font-size: 14px;")

        left = QVBoxLayout()
        left.addWidget(self.preview, 1)
        left.addWidget(self.file_label)

        right = QVBoxLayout()
        right.addWidget(self.choose_button)
        right.addWidget(self.predict_button)
        right.addSpacing(20)
        right.addWidget(self.result_title)
        right.addWidget(self.results, 1)
        right.addWidget(self.status_label)

        layout = QHBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)
        layout.addLayout(left, 3)
        layout.addLayout(right, 2)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择植物图片",
            "",
            "图片 (*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff)",
        )
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "无法打开", "无法预览这张图片，请选择其他文件。")
            return
        self.image_path = Path(path)
        self.original_pixmap = pixmap
        self.update_preview()
        self.file_label.setText(self.image_path.name)
        self.results.clear()
        self.status_label.setText("图片已选择，点击“开始识别”")
        self.predict_button.setEnabled(True)

    def update_preview(self):
        if self.original_pixmap is not None:
            self.preview.setPixmap(
                self.original_pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_preview()

    def predict(self):
        if self.image_path is None:
            return
        if not CHECKPOINT.is_file():
            QMessageBox.warning(self, "模型不存在", f"找不到模型文件：\n{CHECKPOINT}")
            return
        self.results.clear()
        self.status_label.setText(f"正在使用 {self.worker.device} 识别，请稍候…")
        self.choose_button.setEnabled(False)
        self.predict_button.setEnabled(False)
        self.worker.image_path = self.image_path
        self.worker.start()

    def show_prediction(self, predictions):
        for rank, (label, score) in enumerate(predictions, 1):
            self.results.addItem(f"{rank}. {label}   {score:.2%}")
        self.status_label.setText("识别完成。百分比为模型输出分数，仅供参考。")

    def show_error(self, message):
        self.status_label.setText("识别失败")
        QMessageBox.critical(self, "识别失败", message)

    def enable_buttons(self):
        self.choose_button.setEnabled(True)
        self.predict_button.setEnabled(self.image_path is not None)

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.worker.wait()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
