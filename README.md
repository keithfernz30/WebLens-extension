# WebLens - See Beyond the Page

A Chrome extension that provides AI-powered intelligent analysis for any webpage. WebLens leverages Google Gemini or OpenAI APIs to deliver comprehensive content analysis, including summarization, explanation, extraction, translation, quiz generation, fact-checking, and visual object detection.

## Features

- **Summarize**: Generate concise or detailed summaries of webpage content
- **Explain**: Get simple explanations for complex topics
- **Extract**: Extract structured information (title, summary, key points, entities)
- **Translate**: Translate content into multiple languages
- **Quiz**: Generate quiz questions and answers from page content
- **Fact Check**: Verify claims and assess confidence levels
- **Action Items**: Extract actionable next steps from content
- **Visual Analysis**: Detect objects in images and videos using YOLOv8
- **Multi-language Support**: Supports Hindi and other languages
- **Result Caching**: Smart caching to reduce API calls and improve response time
- **Rate Limiting**: Built-in rate limiting for API protection
- **Fallback Mode**: Local fallback processing when AI provider is unavailable

## Project Structure

```
weblens-extension/
├── chrome-extension/              # Chrome extension files
│   ├── background.js             # Service worker
│   ├── content.js                # Content script for page text extraction
│   ├── sidepanel.html            # Side panel UI
│   ├── sidepanel.js              # Side panel logic
│   ├── styles.css                # UI styles
│   └── manifest.json             # Extension manifest
├── weblens-backend/              # FastAPI backend server
│   ├── main.py                   # FastAPI application
│   ├── .env                      # Environment configuration
│   ├── requirements.txt          # Python dependencies
│   └── tests/
│       └── test_main.py          # Backend tests
├── detect.py                     # Visual object detection module (YOLOv8)
├── requirements.txt              # Root requirements
└── README.md                     # This file
```

## Installation

### Prerequisites
- Python 3.8+
- Chrome/Chromium browser
- Google Gemini API key OR OpenAI API key

### Backend Setup

1. **Clone the repository**
```bash
git clone https://github.com/keithfernz30/WebLens-extension.git
cd WebLens-extension/weblens-backend
```

2. **Create and activate virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment variables**
```bash
cp .env.example .env
# Edit .env and add your API keys
```

5. **Start the backend server**
```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### Chrome Extension Setup

1. **Load the extension in Chrome**
   - Open `chrome://extensions/`
   - Enable "Developer mode"
   - Click "Load unpacked"
   - Select the `chrome-extension/` directory

2. **Verify backend connection**
   - The extension looks for backend at `http://127.0.0.1:8000` or `http://localhost:8000`

## Configuration

### Environment Variables (`.env`)

```env
# AI Provider: "gemini" or "openai"
WEBLENS_AI_PROVIDER=gemini

# API Keys
GEMINI_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_api_key

# Model Selection
WEBLENS_GEMINI_MODEL=gemini-2.5-flash
WEBLENS_OPENAI_MODEL=gpt-4o-mini

# Content Limits
WEBLENS_MAX_CONTENT_CHARS=6000
WEBLENS_MODEL_TIMEOUT_SEC=20

# Rate Limiting
WEBLENS_RATE_LIMIT_PER_MIN=30
WEBLENS_CACHE_TTL_SEC=300
WEBLENS_CACHE_MAX_ITEMS=200

# API Security
WEBLENS_API_KEY=optional_api_key_for_security
```

## API Endpoints

### Text Analysis
```bash
POST /analyze
Content-Type: application/json

{
  "mode": "summarize|explain|extract|translate|quiz|action_items|fact_check",
  "task": "optional task description",
  "content": "webpage content",
  "language": "Hindi",
  "detail": "short|detailed"
}
```

**Supported Modes:**
- `summarize` - Generate content summary
- `explain` - Simple explanation
- `extract` - Structured data extraction
- `translate` - Translate to target language
- `quiz` - Generate quiz questions
- `action_items` - Extract actionable items
- `fact_check` - Verify claims

### Visual Analysis
```bash
POST /analyze-visual
Content-Type: application/json

{
  "input_path": "/path/to/image.jpg",
  "model": "yolov8n.pt",
  "conf": 0.25,
  "frame_step": 10
}
```

### Health Check
```bash
GET /
```

### Debug Configuration
```bash
GET /debug-config
```

### List Available Models
```bash
GET /models
```

## Usage

### Via Chrome Extension
1. Open any webpage
2. Click the WebLens icon in the toolbar
3. Select analysis mode from the dropdown
4. Click "Analyze"
5. View results in the side panel

### Via cURL (Backend)
```bash
curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "summarize",
    "task": "",
    "content": "Your webpage content here",
    "language": "Hindi",
    "detail": "short"
  }'
```

## Visual Object Detection

Detect objects in images and videos:

```bash
python detect.py path/to/image.jpg
```

**Options:**
```bash
python detect.py input.jpg --model yolov8n.pt --conf 0.25 --out output.json
python detect.py video.mp4 --frame-step 10 --out output.json

# Custom confidence thresholds
python detect.py input.jpg --conf-person 0.4 --conf-vehicle 0.3 --conf-weapon 0.2
```

**Supported Labels:**
- `person` → person
- `car`, `bus`, `truck`, `motorcycle`, `train`, `bicycle` → vehicle
- `knife`, `gun` → weapon
- Others remain unchanged

## Testing

Run backend tests:
```bash
cd weblens-backend
python -m pytest tests/test_main.py -v
```

## Architecture

### Frontend (Chrome Extension)
- **content.js**: Extracts main text content from webpages
- **background.js**: Handles side panel behavior and tab communication
- **sidepanel.js**: Manages UI interactions and API calls
- **styles.css**: Responsive styling with light/dark theme support

### Backend (FastAPI)
- **main.py**: Core API server with:
  - Request validation using Pydantic
  - Rate limiting per IP address
  - Result caching with TTL
  - AI provider abstraction (Gemini/OpenAI)
  - Graceful fallback to local processing
  - Request ID tracking
  - Configurable timeouts

### Detection Module
- **detect.py**: YOLOv8-based visual detection
  - Image and video support
  - Confidence thresholding
  - Bounding box extraction
  - JSON output schema

## Performance & Caching

- **Response Caching**: Results are cached for 5 minutes (configurable)
- **In-Memory Storage**: Up to 200 items cached (configurable)
- **Rate Limiting**: 30 requests per minute per IP (configurable)
- **Model Timeout**: 20 seconds per request (configurable)
- **Content Truncation**: 6000 characters max (configurable)

## Security

- API key validation (optional via environment variable)
- Rate limiting to prevent abuse
- Input sanitization
- Secure API key masking in debug endpoints
- CORS headers for cross-origin requests

## Troubleshooting

### Connection Issues
```bash
# Test backend is running
curl http://127.0.0.1:8000/

# Check configuration
curl http://127.0.0.1:8000/debug-config
```

### API Key Errors
- Ensure `GEMINI_API_KEY` or `OPENAI_API_KEY` is set in `.env`
- Verify Gemini keys start with "AIza"
- Restart the backend after updating `.env`

### Extension Not Working
1. Verify backend is running on port 8000
2. Check Chrome console for errors (DevTools → Extensions)
3. Reload the extension (chrome://extensions/)
4. Clear extension storage if needed

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Write tests for new features
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues, questions, or suggestions, please open an issue on [GitHub](https://github.com/keithfernz30/WebLens-extension/issues)

## Changelog

### v1.1
- Enhanced caching system
- Improved error handling with friendly messages
- Support for detailed vs. short responses
- Multi-language translation support
- Visual object detection integration

### v1.0
- Initial release
- Core AI analysis modes
- Chrome extension UI
- FastAPI backend
