# Visual Evidence Tagging (Member 4)

## What this module does
`detect.py` detects objects in an input image (or first frame of a video) and returns JSON tags.

## Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
python detect.py input_image.jpg
```

Optional:
```bash
python detect.py input_image.jpg --model yolov8n.pt --conf 0.25
```

## Output format
```json
{
  "tags": ["person", "car"],
  "detections": [
    { "label": "person", "confidence": 0.91 },
    { "label": "car", "confidence": 0.87 }
  ],
  "input_file": "input_image.jpg"
}
```

## Integration in pipeline.py
- `pipeline.py` should run this module as a subprocess:
  - `python detect.py <input_path>`
- Read stdout JSON and merge under a key like `"vision"`.
