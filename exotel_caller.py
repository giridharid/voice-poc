"""
Fusion Finance Voice POC - Exotel Integration
Makes real outbound calls with pre-recorded audio and DTMF capture

Usage:
1. Update parameter.txt with your credentials
2. Run: python exotel_caller.py
3. Open http://localhost:8000
4. Enter phone number and click "Call"
"""

import os
import json
import asyncio
import base64
import configparser
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
import uvicorn

# ============================================================================
# Configuration - Read from parameter.txt
# ============================================================================

def load_config():
    """
    Load config from environment variables (Railway) or parameter.txt (local)
    Environment variables take priority.
    """
    config = configparser.ConfigParser()
    param_file = Path(__file__).parent / "parameter.txt"
    
    if param_file.exists():
        config.read(param_file)
    
    def get_value(key):
        # Environment variable takes priority (for Railway)
        env_val = os.getenv(key)
        if env_val:
            return env_val
        # Fall back to parameter.txt
        if "API_KEYS" in config and key in config["API_KEYS"]:
            return config["API_KEYS"][key]
        return ""
    
    return {
        "SARVAM_API_KEY": get_value("SARVAM_API_KEY"),
        "EXOTEL_API_KEY": get_value("EXOTEL_API_KEY"),
        "EXOTEL_API_TOKEN": get_value("EXOTEL_API_TOKEN"),
        "EXOTEL_ACCOUNT_SID": get_value("EXOTEL_ACCOUNT_SID"),
        "EXOTEL_SUBDOMAIN": get_value("EXOTEL_SUBDOMAIN") or "api.exotel.com",
        "EXOTEL_CALLER_ID": get_value("EXOTEL_CALLER_ID"),
        "EXOTEL_CALLER_ID_MOBILE": get_value("EXOTEL_CALLER_ID_MOBILE"),
    }

CONFIG = load_config()

# Audio files directory
AUDIO_DIR = Path(__file__).parent / "audio"

# App base URL - auto-detect Railway or use environment variable
def get_base_url():
    # Railway provides RAILWAY_PUBLIC_DOMAIN
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if railway_domain:
        return f"https://{railway_domain}"
    # Fallback to env var or localhost
    return os.getenv("APP_BASE_URL", "http://localhost:8000")

APP_BASE_URL = get_base_url()

# ============================================================================
# Call State Management
# ============================================================================

class CallState:
    GREETING = "greeting"
    WAIT_AVAILABILITY = "wait_availability"
    ASK_REASON = "ask_reason"
    WAIT_REASON = "wait_reason"
    RESCHEDULE_CONFIRM = "reschedule_confirm"
    COMPLETED = "completed"

# Store active calls
active_calls: Dict[str, dict] = {}

# WebSocket connections for UI updates
ui_connections = []

# DTMF to decline reason mapping
DTMF_REASONS = {
    "1": "Travel / Market",
    "2": "Health Issue",
    "3": "Financial Stress",
    "4": "Work / Office",
    "5": "Family Event",
    "6": "Crop / Agriculture",
}

# ============================================================================
# Exotel API Integration
# ============================================================================

async def make_exotel_call(to_number: str, language: str = "hi-IN") -> dict:
    """
    Initiate outbound call via Exotel API
    """
    
    if not all([CONFIG["EXOTEL_API_KEY"], CONFIG["EXOTEL_API_TOKEN"], CONFIG["EXOTEL_ACCOUNT_SID"]]):
        raise HTTPException(status_code=500, detail="Exotel credentials not configured")
    
    caller_id = CONFIG["EXOTEL_CALLER_ID_MOBILE"] or CONFIG["EXOTEL_CALLER_ID"]
    if not caller_id:
        raise HTTPException(status_code=500, detail="No Exotel caller ID configured")
    
    # Clean phone number
    to_number = to_number.replace(" ", "").replace("-", "")
    if not to_number.startswith("+"):
        if to_number.startswith("0"):
            to_number = "+91" + to_number[1:]
        elif len(to_number) == 10:
            to_number = "+91" + to_number
    
    # Generate unique call ID
    call_id = f"call_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{to_number[-4:]}"
    
    # Store call state
    active_calls[call_id] = {
        "to_number": to_number,
        "language": language,
        "state": CallState.GREETING,
        "decline_reason": None,
        "transcript": [],
        "started_at": datetime.now().isoformat(),
    }
    
    # Exotel API endpoint
    url = f"https://{CONFIG['EXOTEL_SUBDOMAIN']}/v1/Accounts/{CONFIG['EXOTEL_ACCOUNT_SID']}/Calls/connect.json"
    
    # Callback URL for call flow
    callback_url = f"{APP_BASE_URL}/exotel/callback/{call_id}"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            auth=(CONFIG["EXOTEL_API_KEY"], CONFIG["EXOTEL_API_TOKEN"]),
            data={
                "From": to_number,
                "CallerId": caller_id,
                "Url": callback_url,
                "CallType": "trans",  # Transactional call
            },
            timeout=30.0
        )
        
        if response.status_code in [200, 201]:
            result = response.json()
            active_calls[call_id]["exotel_sid"] = result.get("Call", {}).get("Sid")
            return {"success": True, "call_id": call_id, "exotel_response": result}
        else:
            del active_calls[call_id]
            return {"success": False, "error": response.text}


# ============================================================================
# Exotel Callback Handlers (ExoML)
# ============================================================================

def generate_exoml_play_and_gather(audio_file: str, call_id: str, next_action: str, num_digits: int = 1) -> str:
    """
    Generate ExoML to play audio and gather DTMF input
    """
    audio_url = f"{APP_BASE_URL}/audio/{audio_file}"
    action_url = f"{APP_BASE_URL}/exotel/{next_action}/{call_id}"
    
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{action_url}" method="POST" numDigits="{num_digits}" timeout="10">
        <Play>{audio_url}</Play>
    </Gather>
    <Redirect method="POST">{APP_BASE_URL}/exotel/no_input/{call_id}</Redirect>
</Response>"""


def generate_exoml_play_and_hangup(audio_file: str) -> str:
    """
    Generate ExoML to play audio and end call
    """
    audio_url = f"{APP_BASE_URL}/audio/{audio_file}"
    
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Hangup/>
</Response>"""


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(title="Fusion Finance Voice POC - Exotel Integration")


@app.on_event("startup")
async def startup():
    # Re-detect base URL at startup (Railway domain may be set now)
    global APP_BASE_URL
    APP_BASE_URL = get_base_url()
    
    print("=" * 60)
    print("Fusion Finance Voice POC - Exotel Integration")
    print("=" * 60)
    print(f"Account SID: {CONFIG['EXOTEL_ACCOUNT_SID']}")
    print(f"Caller ID: {CONFIG['EXOTEL_CALLER_ID']}")
    print(f"Mobile Caller ID: {CONFIG['EXOTEL_CALLER_ID_MOBILE']}")
    print(f"Callback URL: {APP_BASE_URL}")
    print("=" * 60)


# Serve audio files
@app.get("/audio/{language}/{filename}")
async def serve_audio(language: str, filename: str):
    """Serve pre-recorded audio files"""
    audio_path = AUDIO_DIR / language / filename
    
    if not audio_path.exists():
        # Fallback to Hindi
        audio_path = AUDIO_DIR / "hi-IN" / filename
    
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {filename}")
    
    return Response(
        content=audio_path.read_bytes(),
        media_type="audio/wav"
    )


# Initial callback when call connects
@app.post("/exotel/callback/{call_id}")
async def exotel_callback(call_id: str, request: Request):
    """Initial callback - play greeting and gather availability"""
    
    if call_id not in active_calls:
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    call = active_calls[call_id]
    language = call.get("language", "hi-IN")
    
    # Log to transcript
    await add_to_transcript(call_id, "Agent", "Greeting - asking availability", "01_greeting.wav")
    
    # Play greeting and gather DTMF (1=Yes, 2=No)
    exoml = generate_exoml_play_and_gather(
        audio_file=f"{language}/01_greeting.wav",
        call_id=call_id,
        next_action="availability",
        num_digits=1
    )
    
    call["state"] = CallState.WAIT_AVAILABILITY
    return Response(content=exoml, media_type="application/xml")


# Handle availability response
@app.post("/exotel/availability/{call_id}")
async def handle_availability(call_id: str, request: Request):
    """Handle DTMF response for availability"""
    
    if call_id not in active_calls:
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    form_data = await request.form()
    digits = form_data.get("digits", "")
    
    call = active_calls[call_id]
    language = call.get("language", "hi-IN")
    
    await add_to_transcript(call_id, "Borrower", f"Pressed: {digits}", None, dtmf=digits)
    
    if digits == "1":
        # Available - confirm and hang up
        await add_to_transcript(call_id, "Agent", "Confirmed - RO will visit", "02_confirmed.wav")
        call["state"] = CallState.COMPLETED
        call["outcome"] = "AVAILABLE"
        
        exoml = generate_exoml_play_and_hangup(f"{language}/02_confirmed.wav")
        
    elif digits == "2":
        # Not available - ask for reason
        await add_to_transcript(call_id, "Agent", "Asking for decline reason", "03_ask_reason.wav")
        call["state"] = CallState.WAIT_REASON
        
        exoml = generate_exoml_play_and_gather(
            audio_file=f"{language}/03_ask_reason.wav",
            call_id=call_id,
            next_action="reason",
            num_digits=1
        )
    else:
        # Unclear - repeat
        await add_to_transcript(call_id, "Agent", "Unclear input - repeating", "05_unclear.wav")
        
        exoml = generate_exoml_play_and_gather(
            audio_file=f"{language}/05_unclear.wav",
            call_id=call_id,
            next_action="availability",
            num_digits=1
        )
    
    return Response(content=exoml, media_type="application/xml")


# Handle reason response
@app.post("/exotel/reason/{call_id}")
async def handle_reason(call_id: str, request: Request):
    """Handle DTMF response for decline reason"""
    
    if call_id not in active_calls:
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    form_data = await request.form()
    digits = form_data.get("digits", "")
    
    call = active_calls[call_id]
    language = call.get("language", "hi-IN")
    
    reason = DTMF_REASONS.get(digits, "Other")
    call["decline_reason"] = reason
    
    await add_to_transcript(call_id, "Borrower", f"Reason: {reason}", None, dtmf=digits, decline_reason=reason)
    
    # Confirm reschedule and hang up
    await add_to_transcript(call_id, "Agent", "Confirming reschedule", "04_reschedule_confirm.wav")
    call["state"] = CallState.COMPLETED
    call["outcome"] = "RESCHEDULED"
    
    exoml = generate_exoml_play_and_hangup(f"{language}/04_reschedule_confirm.wav")
    return Response(content=exoml, media_type="application/xml")


# Handle no input timeout
@app.post("/exotel/no_input/{call_id}")
async def handle_no_input(call_id: str, request: Request):
    """Handle timeout - no DTMF received"""
    
    if call_id not in active_calls:
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    call = active_calls[call_id]
    language = call.get("language", "hi-IN")
    
    await add_to_transcript(call_id, "System", "No input received - repeating", None)
    
    # Repeat unclear prompt
    exoml = generate_exoml_play_and_gather(
        audio_file=f"{language}/05_unclear.wav",
        call_id=call_id,
        next_action="availability",
        num_digits=1
    )
    
    return Response(content=exoml, media_type="application/xml")


# Call status callback
@app.post("/exotel/status/{call_id}")
async def call_status(call_id: str, request: Request):
    """Receive call status updates from Exotel"""
    
    form_data = await request.form()
    status = form_data.get("Status", "")
    
    if call_id in active_calls:
        active_calls[call_id]["status"] = status
        active_calls[call_id]["ended_at"] = datetime.now().isoformat()
        
        await broadcast_update({
            "type": "call_status",
            "call_id": call_id,
            "status": status,
        })
    
    return {"status": "ok"}


# ============================================================================
# Transcript and UI Updates
# ============================================================================

async def add_to_transcript(call_id: str, speaker: str, text: str, audio_file: str = None, 
                           dtmf: str = None, decline_reason: str = None):
    """Add entry to call transcript and broadcast to UI"""
    
    if call_id not in active_calls:
        return
    
    entry = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "speaker": speaker,
        "text": text,
        "audio_file": audio_file,
        "dtmf": dtmf,
        "decline_reason": decline_reason,
    }
    
    active_calls[call_id]["transcript"].append(entry)
    
    await broadcast_update({
        "type": "transcript",
        "call_id": call_id,
        "entry": entry,
    })


async def broadcast_update(message: dict):
    """Send update to all connected UI clients"""
    dead = []
    for ws in ui_connections:
        try:
            await ws.send_json(message)
        except:
            dead.append(ws)
    for ws in dead:
        ui_connections.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ui_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in ui_connections:
            ui_connections.remove(websocket)


# ============================================================================
# API Endpoints
# ============================================================================

class CallRequest(BaseModel):
    phone: str
    language: str = "hi-IN"
    borrower_name: str = "Borrower"
    ro_name: str = "RO"


@app.post("/api/call")
async def initiate_call(request: CallRequest):
    """Initiate outbound call"""
    result = await make_exotel_call(request.phone, request.language)
    return result


@app.get("/api/calls")
async def list_calls():
    """List all calls"""
    return active_calls


@app.get("/api/call/{call_id}")
async def get_call(call_id: str):
    """Get call details"""
    if call_id not in active_calls:
        raise HTTPException(status_code=404, detail="Call not found")
    return active_calls[call_id]


@app.get("/api/config")
async def get_config():
    """Get current configuration (masked)"""
    return {
        "account_sid": CONFIG["EXOTEL_ACCOUNT_SID"],
        "caller_id": CONFIG["EXOTEL_CALLER_ID"],
        "caller_id_mobile": CONFIG["EXOTEL_CALLER_ID_MOBILE"],
        "base_url": APP_BASE_URL,
        "api_key_set": bool(CONFIG["EXOTEL_API_KEY"]),
        "api_token_set": bool(CONFIG["EXOTEL_API_TOKEN"]),
    }


# ============================================================================
# UI
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Fusion Finance Voice POC - Live Calls</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a; 
            color: #e2e8f0;
            min-height: 100vh;
            padding: 40px;
        }
        .container { max-width: 800px; margin: 0 auto; }
        
        h1 { 
            font-size: 28px; 
            margin-bottom: 8px;
            color: #f97316;
        }
        .subtitle { color: #64748b; margin-bottom: 30px; }
        
        .card {
            background: #1e293b;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            border: 1px solid #334155;
        }
        .card h3 {
            font-size: 14px;
            text-transform: uppercase;
            color: #64748b;
            margin-bottom: 16px;
        }
        
        .form-row {
            display: flex;
            gap: 12px;
            margin-bottom: 12px;
        }
        input, select {
            flex: 1;
            padding: 12px 16px;
            border: 1px solid #334155;
            border-radius: 8px;
            background: #0f172a;
            color: #e2e8f0;
            font-size: 14px;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #f97316;
        }
        
        .btn {
            padding: 12px 24px;
            background: linear-gradient(135deg, #f97316, #ea580c);
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .btn:hover { transform: translateY(-2px); }
        .btn:disabled { 
            background: #475569; 
            cursor: not-allowed;
            transform: none;
        }
        
        .config-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #334155;
            font-size: 13px;
        }
        .config-item:last-child { border-bottom: none; }
        .config-label { color: #64748b; }
        .config-value { color: #22c55e; }
        .config-value.missing { color: #ef4444; }
        
        .transcript {
            max-height: 400px;
            overflow-y: auto;
        }
        .transcript-entry {
            padding: 12px;
            margin-bottom: 8px;
            border-radius: 8px;
            animation: slideIn 0.3s ease;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-10px); }
            to { opacity: 1; transform: translateX(0); }
        }
        .transcript-entry.agent {
            background: #1e3a5f;
            border-left: 3px solid #3b82f6;
        }
        .transcript-entry.borrower {
            background: #134e4a;
            border-left: 3px solid #14b8a6;
        }
        .transcript-entry.system {
            background: #3f3f46;
            border-left: 3px solid #a1a1aa;
        }
        
        .entry-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 6px;
            font-size: 12px;
        }
        .entry-speaker { font-weight: 600; }
        .entry-speaker.agent { color: #60a5fa; }
        .entry-speaker.borrower { color: #2dd4bf; }
        .entry-time { color: #64748b; }
        .entry-text { font-size: 14px; }
        
        .tag {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            margin-left: 8px;
        }
        .tag.dtmf { background: #164e63; color: #67e8f9; }
        .tag.reason { background: #7c2d12; color: #fed7aa; }
        
        .empty { 
            text-align: center; 
            padding: 40px; 
            color: #475569;
        }
        
        .status {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .status.connected { background: rgba(34,197,94,0.2); color: #22c55e; }
        .status.disconnected { background: rgba(239,68,68,0.2); color: #ef4444; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎙️ Fusion Finance Voice POC</h1>
        <p class="subtitle">Live Exotel Integration - Make real calls</p>
        
        <div class="card">
            <h3>Configuration</h3>
            <div id="config"></div>
        </div>
        
        <div class="card">
            <h3>Make a Call</h3>
            <div class="form-row">
                <input type="tel" id="phone" placeholder="Phone number (e.g., 9876543210)">
                <select id="language">
                    <option value="hi-IN">Hindi</option>
                    <option value="te-IN">Telugu</option>
                    <option value="ta-IN">Tamil</option>
                    <option value="kn-IN">Kannada</option>
                    <option value="mr-IN">Marathi</option>
                    <option value="en-IN">English</option>
                </select>
            </div>
            <button class="btn" id="callBtn" onclick="makeCall()">📞 Call Now</button>
            <span id="callStatus" style="margin-left: 16px;"></span>
        </div>
        
        <div class="card">
            <h3>Live Transcript <span id="wsStatus" class="status disconnected">Disconnected</span></h3>
            <div class="transcript" id="transcript">
                <div class="empty">Make a call to see the live transcript</div>
            </div>
        </div>
    </div>
    
    <script>
        let ws;
        
        async function loadConfig() {
            const resp = await fetch('/api/config');
            const config = await resp.json();
            
            document.getElementById('config').innerHTML = `
                <div class="config-item">
                    <span class="config-label">Account SID</span>
                    <span class="config-value">${config.account_sid || '<span class="missing">Not set</span>'}</span>
                </div>
                <div class="config-item">
                    <span class="config-label">Caller ID</span>
                    <span class="config-value">${config.caller_id || '<span class="missing">Not set</span>'}</span>
                </div>
                <div class="config-item">
                    <span class="config-label">Mobile Caller ID</span>
                    <span class="config-value">${config.caller_id_mobile || '<span class="missing">Not set</span>'}</span>
                </div>
                <div class="config-item">
                    <span class="config-label">API Key</span>
                    <span class="config-value ${config.api_key_set ? '' : 'missing'}">${config.api_key_set ? '✓ Set' : '✗ Missing'}</span>
                </div>
                <div class="config-item">
                    <span class="config-label">API Token</span>
                    <span class="config-value ${config.api_token_set ? '' : 'missing'}">${config.api_token_set ? '✓ Set' : '✗ Missing'}</span>
                </div>
                <div class="config-item">
                    <span class="config-label">Callback URL</span>
                    <span class="config-value">${config.base_url}</span>
                </div>
            `;
        }
        
        function connectWS() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${location.host}/ws`);
            
            ws.onopen = () => {
                document.getElementById('wsStatus').className = 'status connected';
                document.getElementById('wsStatus').textContent = 'Connected';
            };
            
            ws.onclose = () => {
                document.getElementById('wsStatus').className = 'status disconnected';
                document.getElementById('wsStatus').textContent = 'Disconnected';
                setTimeout(connectWS, 3000);
            };
            
            ws.onmessage = (e) => {
                const msg = JSON.parse(e.data);
                if (msg.type === 'transcript') {
                    addTranscriptEntry(msg.entry);
                } else if (msg.type === 'call_status') {
                    document.getElementById('callStatus').textContent = `Status: ${msg.status}`;
                }
            };
        }
        
        function addTranscriptEntry(entry) {
            const box = document.getElementById('transcript');
            const empty = box.querySelector('.empty');
            if (empty) empty.remove();
            
            const speakerClass = entry.speaker.toLowerCase();
            let tags = '';
            if (entry.dtmf) tags += `<span class="tag dtmf">DTMF: ${entry.dtmf}</span>`;
            if (entry.decline_reason) tags += `<span class="tag reason">${entry.decline_reason}</span>`;
            
            box.insertAdjacentHTML('beforeend', `
                <div class="transcript-entry ${speakerClass}">
                    <div class="entry-header">
                        <span class="entry-speaker ${speakerClass}">${entry.speaker}</span>
                        <span class="entry-time">${entry.timestamp}</span>
                    </div>
                    <div class="entry-text">${entry.text}${tags}</div>
                </div>
            `);
            box.scrollTop = box.scrollHeight;
        }
        
        async function makeCall() {
            const phone = document.getElementById('phone').value;
            const language = document.getElementById('language').value;
            
            if (!phone) {
                alert('Please enter a phone number');
                return;
            }
            
            const btn = document.getElementById('callBtn');
            btn.disabled = true;
            btn.textContent = '📞 Calling...';
            document.getElementById('callStatus').textContent = 'Initiating call...';
            
            // Clear transcript
            document.getElementById('transcript').innerHTML = '<div class="empty">Connecting...</div>';
            
            try {
                const resp = await fetch('/api/call', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone, language })
                });
                
                const result = await resp.json();
                
                if (result.success) {
                    document.getElementById('callStatus').textContent = `Call ID: ${result.call_id}`;
                } else {
                    document.getElementById('callStatus').textContent = `Error: ${result.error}`;
                    document.getElementById('transcript').innerHTML = `<div class="empty">Error: ${result.error}</div>`;
                }
            } catch (err) {
                document.getElementById('callStatus').textContent = `Error: ${err.message}`;
            }
            
            btn.disabled = false;
            btn.textContent = '📞 Call Now';
        }
        
        loadConfig();
        connectWS();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    print("\n⚠️  IMPORTANT: For Exotel callbacks to work, you need a public URL.")
    print("   Run: ngrok http 8000")
    print("   Then set: export APP_BASE_URL=https://your-ngrok-url.ngrok.io")
    print("   And restart this script.\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
