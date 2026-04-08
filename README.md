# Fusion Finance Voice POC

Speech-to-Speech AI agent for loan collection pre-calls with real-time English transcript.

## What This Does

1. **Makes outbound call** via Exotel to borrower
2. **Streams audio** bidirectionally over WebSocket
3. **Transcribes** borrower speech (Hindi/Telugu/etc.) via Sarvam AI
4. **Processes** intent + generates response via Claude
5. **Speaks response** back to borrower via Sarvam TTS
6. **Displays live transcript** in English in the web UI

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Exotel    │────▶│  FastAPI    │────▶│  Sarvam AI  │
│  (Call +    │◀────│  Server     │◀────│  (STT/TTS)  │
│  WebSocket) │     │             │     │             │
└─────────────┘     └──────┬──────┘     └─────────────┘
                          │
                          ▼
                   ┌─────────────┐     ┌─────────────┐
                   │   Claude    │     │   Web UI    │
                   │  (Bedrock)  │     │ (Transcript)│
                   └─────────────┘     └─────────────┘
```

## Setup

### 1. Sign Up for APIs

**Sarvam AI** (required)
- Go to https://sarvam.ai
- Create account → Get API key from dashboard
- Free: ₹1,000 credits on signup

**Exotel** (required for real calls)
- Go to https://exotel.com
- Sign up for trial account
- Get API key, token, and virtual number from dashboard

**AWS Bedrock** (optional)
- Only needed for Claude integration
- POC works without it using mock responses

### 2. Install Dependencies

```bash
cd fusion-voice-poc
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 4. Run Server

```bash
# For local testing
python src/server.py

# For production
uvicorn src.server:app --host 0.0.0.0 --port 8000
```

### 5. Expose for Exotel (if running locally)

```bash
# Install ngrok: https://ngrok.com
ngrok http 8000
# Copy the https URL to .env as CALLBACK_URL
```

### 6. Configure Exotel App Bazaar

1. Go to Exotel Dashboard → App Bazaar
2. Create new flow with Voicebot applet
3. Set WebSocket URL: `wss://your-ngrok-url/ws/exotel`
4. Save and note the App ID

## Testing

### Without Exotel (Mock Mode)

The POC runs in mock mode if EXOTEL_API_KEY is not set:

1. Start server: `python src/server.py`
2. Open http://localhost:8000
3. Enter any phone number and click "Start Call"
4. Watch simulated conversation appear in transcript

### With Exotel (Real Calls)

1. Configure all API keys in .env
2. Start server with ngrok
3. Open http://localhost:8000
4. Enter YOUR phone number
5. Click "Start Call"
6. Answer the call and speak in Hindi
7. Watch real-time transcript appear

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI with transcript display |
| `/api/call` | POST | Initiate outbound call |
| `/api/sessions` | GET | List all call sessions |
| `/api/sessions/{id}` | GET | Get session with transcript |
| `/ws/ui` | WebSocket | UI transcript updates |
| `/ws/exotel` | WebSocket | Exotel audio stream |

## Conversation Flow

```
Agent: Namaste, I am calling from Fusion Finance. 
       Your RO will visit tomorrow. Will you be available?

Borrower: [Hindi] नहीं, कल नहीं। बाजार जाना है।

[Transcript shows]
Borrower: No, not tomorrow. I have to go to market.
[Intent: UNAVAILABLE] [Reason: TRAVEL]

Agent: Understood. Would next Monday work?
```

## Cost Estimate (per call)

| Component | Cost |
|-----------|------|
| Exotel (2.5 min call) | ₹2-3 |
| Sarvam STT (2.5 min) | ₹1.25 |
| Sarvam TTS (~500 chars) | ₹1.50 |
| Claude (if using) | ₹1-2 |
| **Total** | **₹5-8 per call** |

## Files

```
fusion-voice-poc/
├── src/
│   └── server.py      # Main FastAPI application
├── requirements.txt   # Python dependencies
├── .env.example       # Environment template
└── README.md          # This file
```

## Next Steps for Production

1. **Database**: Replace in-memory sessions with PostgreSQL/Redis
2. **Queue**: Add Celery for async call processing
3. **Auth**: Add API key authentication
4. **Monitoring**: Add logging, metrics, alerting
5. **Scale**: Deploy on Railway/AWS with auto-scaling
6. **Integration**: Connect to Fusion Finance CRM/LMS

---

**Acquink Technologies** | giri@acquink.com
