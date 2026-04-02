import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
from ultralytics import YOLO

DEFAULT_CATEGORY_THRESHOLDS = {
    "person": 0.25,
    "vehicle": 0.25,
    "weapon": 0.20,
    "other": 0.25,
}

# Project-level mapping from raw detector labels to evidence tags.
LABEL_TO_EVIDENCE = {
    "person": "person",
    "bicycle": "vehicle",
    "car": "vehicle",
    "motorcycle": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
    "train": "vehicle",
    "knife": "weapon",
    "gun": "weapon",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visual evidence tagging with YOLO. Outputs JSON."
    )
    parser.add_argument("input_path", help="Path to input image (or video file).")
    parser.add_argument(
        "--model",
        default="yolov8n.pt",
        help="YOLO model path/name (default: yolov8n.pt).",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Confidence threshold (default: 0.25).",
    )
    parser.add_argument(
        "--frame-step",
        type=int,
        default=10,
        help="For videos, process every Nth frame (default: 10).",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional path to write JSON output file.",
    )
    parser.add_argument("--conf-person", type=float, default=None)
    parser.add_argument("--conf-vehicle", type=float, default=None)
    parser.add_argument("--conf-weapon", type=float, default=None)
    parser.add_argument("--conf-other", type=float, default=None)
    return parser.parse_args()


def error_result(code: str, message: str, input_path: str) -> Dict:
    return {
        "success": False,
        "error_code": code,
        "message": message,
        "input_file": input_path,
        "tags": [],
        "detections": [],
    }


def is_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def map_label(raw_label: str) -> str:
    return LABEL_TO_EVIDENCE.get(raw_label, raw_label)


def to_bbox_xyxy(box) -> List[int]:
    x1, y1, x2, y2 = box.xyxy[0].tolist()
    return [int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))]


def category_for_label(label: str) -> str:
    if label == "person":
        return "person"
    if label == "vehicle":
        return "vehicle"
    if label == "weapon":
        return "weapon"
    return "other"


def passes_threshold(label: str, conf: float, thresholds: Dict[str, float]) -> bool:
    category = category_for_label(label)
    return conf >= thresholds.get(category, thresholds["other"])


def parse_overrides(args: argparse.Namespace) -> Dict[str, float]:
    thresholds = dict(DEFAULT_CATEGORY_THRESHOLDS)
    if args.conf_person is not None:
        thresholds["person"] = args.conf_person
    if args.conf_vehicle is not None:
        thresholds["vehicle"] = args.conf_vehicle
    if args.conf_weapon is not None:
        thresholds["weapon"] = args.conf_weapon
    if args.conf_other is not None:
        thresholds["other"] = args.conf_other
    return thresholds


def detect_on_frame(
    model: YOLO,
    frame,
    conf: float,
    timestamp_sec: float,
    thresholds: Dict[str, float],
) -> Tuple[List[str], List[Dict]]:
    result = model.predict(source=frame, conf=conf, verbose=False)[0]
    names = result.names

    tags: List[str] = []
    detections: List[Dict] = []
    for box in result.boxes:
        class_id = int(box.cls.item())
        raw_label = names.get(class_id, str(class_id))
        mapped_label = map_label(raw_label)
        score = float(box.conf.item())
        if not passes_threshold(mapped_label, score, thresholds):
            continue

        tags.append(mapped_label)
        detections.append(
            {
                "label": mapped_label,
                "raw_label": raw_label,
                "confidence": round(score, 4),
                "bbox_xyxy": to_bbox_xyxy(box),
                "timestamp_sec": round(timestamp_sec, 3),
            }
        )
    return tags, detections


def run_detection(
    input_path: Path,
    model_name: str = "yolov8n.pt",
    conf: float = 0.25,
    frame_step: int = 10,
    category_thresholds: Dict[str, float] = None,
) -> Dict:
    if not input_path.exists():
        return error_result("INPUT_NOT_FOUND", f"Input not found: {input_path}", str(input_path))

    if frame_step <= 0:
        return error_result("BAD_ARGUMENT", "--frame-step must be >= 1", str(input_path))

    thresholds = category_thresholds or dict(DEFAULT_CATEGORY_THRESHOLDS)

    try:
        model = YOLO(model_name)
    except Exception as exc:
        return error_result("MODEL_LOAD_FAILED", str(exc), str(input_path))

    all_tags: List[str] = []
    all_detections: List[Dict] = []

    if is_video(input_path):
        cap = cv2.VideoCapture(str(input_path))
        if not cap.isOpened():
            return error_result("READ_FAILED", "Could not open video file.", str(input_path))

        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frame_idx = 0
        processed_frames = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % frame_step == 0:
                timestamp = frame_idx / fps if fps > 0 else 0.0
                tags, detections = detect_on_frame(
                    model=model,
                    frame=frame,
                    conf=conf,
                    timestamp_sec=timestamp,
                    thresholds=thresholds,
                )
                all_tags.extend(tags)
                all_detections.extend(detections)
                processed_frames += 1
            frame_idx += 1
        cap.release()

        return {
            "success": True,
            "error_code": "",
            "message": "ok",
            "input_file": str(input_path),
            "input_type": "video",
            "frame_step": frame_step,
            "processed_frames": processed_frames,
            "tags": sorted(set(all_tags)),
            "detections": all_detections,
            "total_detections": len(all_detections),
        }

    image = cv2.imread(str(input_path))
    if image is None:
        return error_result("READ_FAILED", "Could not read input as image.", str(input_path))

    tags, detections = detect_on_frame(
        model=model,
        frame=image,
        conf=conf,
        timestamp_sec=0.0,
        thresholds=thresholds,
    )
    return {
        "success": True,
        "error_code": "",
        "message": "ok",
        "input_file": str(input_path),
        "input_type": "image",
        "frame_step": 1,
        "processed_frames": 1,
        "tags": sorted(set(tags)),
        "detections": detections,
        "total_detections": len(detections),
    }


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_path)
    thresholds = parse_overrides(args)

    output = run_detection(
        input_path=input_path,
        model_name=args.model,
        conf=args.conf,
        frame_step=args.frame_step,
        category_thresholds=thresholds,
    )

    text = json.dumps(output, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if output.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
