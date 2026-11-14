"""Local FastAPI bridge between React and TCMP-300 ResNet50."""
import csv
import io
import json
import logging
import os
import re
import threading
from time import perf_counter
from contextlib import asynccontextmanager
from pathlib import Path

import torch
from fastapi import APIRouter, FastAPI, File, Header, HTTPException, UploadFile, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
from torch import nn
from torchvision import models, transforms
import herb_catalog
import content_store
from content_api import router as content_router
import history_store
from auth_api import router as auth_router, request_history_owner
from admin_articles import router as admin_router
from auth_limits import AuthBodyLimitMiddleware
from history_api import router as history_router
from deepseek_chat import router as chat_router
from agent_service import router as agent_router
from upload_limits import BoundedUploadMiddleware, SingleImageUploadRoute

ROOT = Path(__file__).resolve().parent
DEFAULT_CHECKPOINT = ROOT / "runs/resnet50_7030_baseline/best.pt"
QUANTIZED_MODEL = ROOT / "experiment3/runs/frozen/Q.pt"
CLASS_INFO = ROOT / "data/author_tcmp_300/tcmp-info-20250329.csv"
TRAIN_IMAGES = ROOT / "data/author_tcmp_300/images/tcmp-300/train"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# One file plus a bounded multipart header/boundary budget.
MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_EDGE = 10_000
MAX_IMAGE_ASPECT_RATIO = 20
MAX_RESIZED_PIXELS = 1_000_000
PREPROCESS = transforms.Compose([
    transforms.Resize(256), transforms.CenterCrop(224), transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def normalize_latin(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def validate_image_dimensions(width, height):
    """Keep the original training transform safe, before decoding or resizing."""
    short, long = sorted((width, height))
    if short < 1 or width * height > MAX_IMAGE_PIXELS:
        raise HTTPException(413, "图片分辨率过大，请缩小至 2500 万像素以内")
    if long > MAX_IMAGE_EDGE or long > short * MAX_IMAGE_ASPECT_RATIO:
        raise HTTPException(413, "图片边长或长宽比过大，请缩小或裁剪后重试")
    # torchvision Resize(256) scales the shorter edge to 256 before CenterCrop.
    resized_long = int(256 * long / short)
    if 256 * resized_long > MAX_RESIZED_PIXELS:
        raise HTTPException(413, "图片长宽比过大，请裁剪后重试")


def allowed_frontend_origins():
    origins = ["http://localhost:5173", "http://127.0.0.1:5173",
               "http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8001", "http://127.0.0.1:8001",
               "http://localhost:4173", "http://127.0.0.1:4173"]
    custom = os.environ.get("TCMP_FRONTEND_ORIGIN", "").strip()
    if custom:
        match = re.fullmatch(r"http://(?:localhost|127\.0\.0\.1):([1-9]\d{0,4})", custom)
        if not match or int(match.group(1)) > 65535:
            raise ValueError("TCMP_FRONTEND_ORIGIN must be http://localhost:<port> or http://127.0.0.1:<port>")
        if custom not in origins:
            origins.append(custom)
    return origins


class Predictor:
    def __init__(self, checkpoint=DEFAULT_CHECKPOINT):
        checkpoint = Path(checkpoint).resolve()
        mode = os.environ.get("TCMP_MODEL", "int8")
        if mode not in {"int8", "original"}:
            raise ValueError("TCMP_MODEL must be int8 or original")
        if mode == "int8" and checkpoint != DEFAULT_CHECKPOINT.resolve():
            raise ValueError("INT8 model uses the experiment-2 class mapping; use TCMP_MODEL=original for another checkpoint")
        labels_path = ROOT / "model_labels.json"
        if mode == "int8" and labels_path.is_file():
            saved = json.loads(labels_path.read_text(encoding="utf-8"))
        else:
            saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
        classes = saved["classes"]
        if len(classes) != 300:
            raise ValueError("Expected a TCMP-300 checkpoint with 300 classes")
        rows = list(herb_catalog.rows().values())
        by_number = {int(row["No"]): row for row in rows}
        if len(rows) != 300 or len(by_number) != 300:
            raise ValueError("Class metadata must contain 300 unique classes")
        self.labels = []
        for label in classes:
            number, separator, latin = label.partition(".")
            row = by_number.get(int(number)) if number.isdigit() else None
            if not separator or not row or normalize_latin(latin) != normalize_latin(row["Latin Name"]):
                raise ValueError(f"Checkpoint class does not match metadata: {label}")
            if not row["Chinese Name"].strip():
                raise ValueError(f"Missing Chinese name: {label}")
            self.labels.append({"herb_id": f"tcmp-{int(number):03d}",
                "name": row["Chinese Name"].strip(), "latin_name": row["Latin Name"].strip(),
                "family": row["Family"].strip(), "class_id": int(number),
                **herb_catalog.identity_metadata(row)})
            if self.labels[-1]['identity_conflict']:
                self.labels[-1].update(name='无法确定植物名称', latin_name='', family='')
        torch.set_num_threads(min(4, os.cpu_count() or 4))
        if mode == "int8":
            engines = torch.backends.quantized.supported_engines
            engine = next((name for name in ("fbgemm", "x86", "onednn", "qnnpack") if name in engines), None)
            if engine is None:
                raise RuntimeError("No INT8 inference engine is available; use TCMP_MODEL=original")
            torch.backends.quantized.engine = engine
            self.device = torch.device("cpu")
            # A file object also supports the Chinese project path on Windows.
            with QUANTIZED_MODEL.open("rb") as file:
                self.model = torch.jit.load(file, map_location="cpu").eval()
        else:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model = models.resnet50(weights=None)
            self.model.fc = nn.Linear(self.model.fc.in_features, len(classes))
            self.model.load_state_dict(saved["model"])
            self.model.to(self.device).eval()
        self.lock = threading.Lock()
        self.info = {"name": "ResNet50 INT8 · TCMP-300" if mode == "int8" else "ResNet50 · TCMP-300",
                     "run": "experiment3/Q" if mode == "int8" else checkpoint.parent.name,
                     "epoch": saved["epoch"], "classes": len(classes), "device": self.device.type,
                     "optimization": mode}
        metrics_path = checkpoint.parent / "test_evaluation/test_metrics.json"
        # Only publish evaluation belonging to this checkpoint and split.
        if mode == "original" and metrics_path.is_file():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            if (Path(metrics["checkpoint"]).resolve() == checkpoint
                    and metrics["epoch"] == saved["epoch"]
                    and metrics.get("split_hash") == saved.get("split_hash")):
                self.info.update({"test_top1_accuracy": metrics["test_accuracy"],
                    "test_top5_accuracy": metrics["test_top5_accuracy"], "test_images": metrics["test_images"]})
        self.samples = {}
        # Real training images for demos; never use the held-out test set here.
        for label, metadata in zip(classes, self.labels):
            folder = TRAIN_IMAGES / label
            if folder.is_dir():
                candidate = next((p for p in sorted(folder.iterdir())
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}), None)
                if candidate:
                    self.samples[metadata["herb_id"]] = (metadata, candidate)
            if len(self.samples) == 4:
                break

    def predict(self, content):
        started = perf_counter()
        try:
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(415, "请选择 JPG、PNG 或 WEBP 图片")
                validate_image_dimensions(image.width, image.height)
                image = ImageOps.exif_transpose(image).convert("RGB")
                tensor = PREPROCESS(image).unsqueeze(0)
        except (UnidentifiedImageError, OSError, ValueError):
            raise HTTPException(400, "无法读取图片，请上传有效的 JPG、PNG 或 WEBP 文件")
        except Image.DecompressionBombError:
            raise HTTPException(413, "图片分辨率过大，请缩小后重试")
        preprocess_ms = (perf_counter() - started) * 1000
        with self.lock, torch.inference_mode():
            tensor = tensor.to(self.device)
            if self.device.type == "cuda":
                torch.cuda.synchronize()
            inference_started = perf_counter()
            logits = self.model(tensor)
            if self.device.type == "cuda":
                torch.cuda.synchronize()
            inference_ms = (perf_counter() - inference_started) * 1000
            probabilities, indices = logits.softmax(dim=1)[0].topk(5)
        top_k = [dict(self.labels[index], confidence=score)
                 for index, score in zip(indices.tolist(), probabilities.tolist())]
        return {"prediction": top_k[0], "top_k": top_k, "model": self.info,
                "timing_ms": {"preprocess": round(preprocess_ms, 2), "inference": round(inference_ms, 2),
                              "total": round((perf_counter() - started) * 1000, 2)}}


@asynccontextmanager
async def lifespan(app):
    app.state.predictor = await run_in_threadpool(Predictor, os.environ.get("TCMP_CHECKPOINT", str(DEFAULT_CHECKPOINT)))
    yield
    del app.state.predictor


app = FastAPI(title="TCMP-300 草药识别 API", lifespan=lifespan)


@app.exception_handler(StarletteHTTPException)
async def http_error(request, error):
    return JSONResponse({"code": error.status_code, "result": None, "msg": str(error.detail), "detail": error.detail},
                        status_code=error.status_code, headers=error.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    message = "请求参数无效，请检查文件或输入内容"
    detail = message
    if request.url.path.startswith(('/api/v1/auth/', '/api/v1/admin/')):
        # Never echo submitted passwords or complete draft bodies in validation responses.
        detail = [{key: value for key, value in item.items() if key in {'type', 'loc', 'msg'}} for item in error.errors()]
    return JSONResponse({"code": 422, "result": None, "msg": message, "detail": detail}, status_code=422)

app.include_router(chat_router)
app.include_router(agent_router)
app.include_router(history_router)
app.include_router(content_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.add_middleware(BoundedUploadMiddleware, path="/api/v1/predict", max_bytes=MAX_UPLOAD_REQUEST_BYTES)
app.add_middleware(BoundedUploadMiddleware, path="/api/v1/agent/chat", max_bytes=64*1024)
app.add_middleware(BoundedUploadMiddleware, path="/api/v1/agent/chat/stream", max_bytes=64*1024)
app.add_middleware(BoundedUploadMiddleware, path="/api/v1/text/classify", max_bytes=32*1024)
app.add_middleware(AuthBodyLimitMiddleware)
app.add_middleware(CORSMiddleware,
    allow_origins=allowed_frontend_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])


@app.get("/api/v1/health")
def health():
    database = history_store.health()
    content = content_store.health()
    return {"status": "degraded" if database['status'] == 'unavailable' or content['status'] == 'unavailable' else "ready",
            "model": app.state.predictor.info, "database": database, "content": content}


@app.get("/api/v1/herbs")
def herbs(q: str=Query("",max_length=200),family: str="",genus: str="",region: str="",effect: str="",
          property: str="",part: str="",sort: str="class",page: int=Query(1,ge=1),
          page_size: int=Query(24,ge=1,le=60),recent_ids: str=Query("",max_length=500)):
    return herb_catalog.list_herbs(q,family,genus,region,effect,property,part,sort,page,page_size,recent_ids)


@app.get("/api/v1/herbs/filters")
def herb_filters():
    return herb_catalog.filters()


@app.get("/api/v1/herbs/{herb_id}")
def herb_detail(herb_id: str):
    row=herb_catalog.rows().get(herb_id)
    herb = herb_catalog.serialize(row,detail=True) if row else None
    if herb is None:raise HTTPException(404,"该植物资料未公开或不存在")
    return herb


@app.get("/api/v1/herbs/{herb_id}/reference-image")
def herb_reference_image(herb_id: str):
    path=herb_catalog.reference_image(herb_id)
    if path is None:raise HTTPException(404,"该条目暂无参考图片")
    return FileResponse(path,headers={"Cache-Control":"public, max-age=3600"})


@app.get("/api/v1/recognition/samples")
def samples():
    return [dict(metadata, image_url=f"/api/v1/recognition/samples/{sample_id}/image")
            for sample_id, (metadata, _) in app.state.predictor.samples.items()
            if herb_catalog.reference_image(sample_id) is not None]


@app.get("/api/v1/recognition/samples/{sample_id}/image")
def sample_image(sample_id: str):
    sample = app.state.predictor.samples.get(sample_id)
    if sample is None or herb_catalog.reference_image(sample_id) is None:
        raise HTTPException(404, "示例图片不存在")
    return FileResponse(herb_catalog.reference_image(sample_id))


recognition_router = APIRouter(route_class=SingleImageUploadRoute)


class PredictionResponse(BaseModel):
    code: int = 200
    result: dict
    msg: str = "识别完成"


@recognition_router.post("/api/v1/predict", response_model=PredictionResponse,
                         summary="使用实验三 INT8 模型识别植物图片",
                         responses={400: {"description": "空文件或无效图片"},
                                    413: {"description": "图片大小、尺寸或请求体超限"},
                                    415: {"description": "不支持的图片格式"},
                                    500: {"description": "模型推理失败"}})
async def predict(request: Request, file: UploadFile = File(...), x_history_token: str | None = Header(default=None)):
    started = perf_counter()
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    if not content:
        raise HTTPException(400, "上传图片不能为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "图片大小不能超过 10MB")
    owner = await run_in_threadpool(request_history_owner, request, x_history_token) if history_store.enabled() else None
    try:
        result = await run_in_threadpool(app.state.predictor.predict, content)
    except HTTPException:
        raise
    except Exception:
        logging.exception("Model prediction failed")
        raise HTTPException(500, "模型识别失败，请稍后重试")
    if owner:
        with Image.open(io.BytesIO(content)) as image:
            image_format = image.format
        record_id = await run_in_threadpool(history_store.save_recognition, owner, file.filename, content, image_format, result)
        result = {**result, 'record_id': record_id, 'saved': True}
    result.setdefault("timing_ms", {})["api"] = round((perf_counter() - started) * 1000, 2)
    return PredictionResponse(result=result)


app.include_router(recognition_router)


WEB_DIR = ROOT / "web"
if WEB_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="web-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/herbs", include_in_schema=False)
    @app.get("/herbs/{herb_id}", include_in_schema=False)
    @app.get("/knowledge", include_in_schema=False)
    @app.get("/login", include_in_schema=False)
    @app.get("/profile", include_in_schema=False)
    @app.get("/admin/articles", include_in_schema=False)
    def frontend(herb_id: str | None = None):
        return FileResponse(WEB_DIR / "index.html")
