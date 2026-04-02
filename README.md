# LookBack Visual Evidence Tagging (Member 4)

## What this module does
`detect.py` detects objects in image/video evidence and outputs structured JSON for pipeline integration.

## Install
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run (Image)
```bash
python detect.py path/to/input.jpg
```

## Run (Video)
```bash
python detect.py path/to/input.mp4 --frame-step 10
```

## Save output JSON file
```bash
python detect.py path/to/input.jpg --out detect_output.json
```

## Optional confidence tuning
```bash
python detect.py path/to/input.jpg --conf-person 0.4 --conf-vehicle 0.3 --conf-weapon 0.2 --conf-other 0.25
```

## Output JSON schema
```json
{
  "success": true,
  "error_code": "",
  "message": "ok",
  "input_file": "path/to/input.jpg",
  "input_type": "image",
  "frame_step": 1,
  "processed_frames": 1,
  "tags": ["person", "vehicle"],
  "detections": [
    {
      "label": "vehicle",
      "raw_label": "car",
      "confidence": 0.9132,
      "bbox_xyxy": [110, 56, 487, 322],
      "timestamp_sec": 0.0
    }
  ],
  "total_detections": 1
}
```

## Evidence label mapping
- `car`, `bus`, `truck`, `motorcycle`, `train`, `bicycle` -> `vehicle`
- `knife`, `gun` -> `weapon`
- `person` -> `person`
- Others remain unchanged

## Integration with `pipeline.py`
Use CLI:
```bash
python detect.py <input_path> --out vision_output.json
```

Or import function directly:
```python
from pathlib import Path
from detect import run_detection

result = run_detection(Path("input.jpg"))
```
