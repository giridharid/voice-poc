"""
Fusion Finance Voice Intelligence POC
Smaartbrand UI Theme - Orange/Blue
Real Exotel calls + Intelligence Dashboard

Run: python exotel_caller.py
"""

import os
import json
import asyncio
import base64
import configparser
import random
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict
from collections import defaultdict

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
import uvicorn

# ============================================================================
# Configuration
# ============================================================================

def load_config():
    config = configparser.ConfigParser()
    param_file = Path(__file__).parent / "parameter.txt"
    
    if param_file.exists():
        config.read(param_file)
    
    def get_value(key):
        env_val = os.getenv(key)
        if env_val:
            return env_val
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
AUDIO_DIR = Path(__file__).parent / "audio"

def get_base_url():
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if railway_domain:
        return f"https://{railway_domain}"
    return os.getenv("APP_BASE_URL", "http://localhost:8000")

APP_BASE_URL = get_base_url()

# ============================================================================
# Call State & Data
# ============================================================================

class CallState:
    GREETING = "greeting"
    WAIT_AVAILABILITY = "wait_availability"
    ASK_REASON = "ask_reason"
    WAIT_REASON = "wait_reason"
    COMPLETED = "completed"

active_calls: Dict[str, dict] = {}
ui_connections = []

DTMF_REASONS = {
    "1": ("Travel / Market", "TRAVEL_MARKET"),
    "2": ("Health Issue", "HEALTH"),
    "3": ("Financial Stress", "FINANCIAL_STRESS"),
    "4": ("Work / Office", "WORK_CONFLICT"),
    "5": ("Family Event", "FAMILY_EVENT"),
    "6": ("Crop / Agriculture", "CROP_AGRICULTURE"),
}

LANGUAGE_NAMES = {
    "hi-IN": ("Hindi", "हिंदी"),
    "te-IN": ("Telugu", "తెలుగు"),
    "ta-IN": ("Tamil", "தமிழ்"),
    "kn-IN": ("Kannada", "ಕನ್ನಡ"),
    "mr-IN": ("Marathi", "मराठी"),
    "en-IN": ("English", "English"),
}

RO_NAMES = {
    "hi-IN": "Amit ji",
    "te-IN": "Srinivas garu",
    "ta-IN": "Suresh sir",
    "kn-IN": "Shetty sir",
    "mr-IN": "Patil saheb",
    "en-IN": "Amit sir",
}

# ============================================================================
# Mock Intelligence Data
# ============================================================================

def generate_mock_intelligence():
    clusters = [
        {"name": "Warangal Rural", "state": "Telangana"},
        {"name": "Guntur District", "state": "Andhra Pradesh"},
        {"name": "Dharwad", "state": "Karnataka"},
        {"name": "Salem", "state": "Tamil Nadu"},
        {"name": "Nashik Rural", "state": "Maharashtra"},
    ]
    
    borrowers = []
    for i in range(500):
        cluster = random.choice(clusters)
        is_frequent = random.random() < 0.12
        
        decline_reasons = []
        if is_frequent:
            primary = random.choices(
                ["FINANCIAL_STRESS", "TRAVEL_MARKET", "HEALTH", "CROP_AGRICULTURE"],
                weights=[40, 20, 15, 25]
            )[0]
            for _ in range(random.randint(3, 6)):
                decline_reasons.append(primary)
        
        borrowers.append({
            "id": f"BRW{10000+i}",
            "cluster": cluster["name"],
            "state": cluster["state"],
            "persona": random.choice(["FARMER", "TRADER", "SALARIED", "SELF_EMPLOYED", "DAILY_WAGE"]),
            "decline_count": len(decline_reasons),
            "decline_reasons": decline_reasons,
            "is_frequent": is_frequent,
            "risk_score": min(100, len(decline_reasons) * 15 + (40 if "FINANCIAL_STRESS" in decline_reasons else 0)),
            "loan_amount": random.randint(20000, 80000),
        })
    
    reason_counts = defaultdict(int)
    for b in borrowers:
        for r in b["decline_reasons"]:
            reason_counts[r] += 1
    
    cluster_stats = {}
    for cluster in clusters:
        cb = [b for b in borrowers if b["cluster"] == cluster["name"]]
        avg_risk = sum(b["risk_score"] for b in cb) / len(cb) if cb else 0
        freq = len([b for b in cb if b["is_frequent"]])
        fin_stress = len([b for b in cb if "FINANCIAL_STRESS" in b["decline_reasons"]])
        
        cluster_stats[cluster["name"]] = {
            "state": cluster["state"],
            "total": len(cb),
            "avg_risk": round(avg_risk, 1),
            "frequent": freq,
            "financial_stress": fin_stress,
            "alert": "HIGH" if avg_risk > 40 or fin_stress > 10 else ("MEDIUM" if avg_risk > 25 else "LOW"),
        }
    
    persona_counts = defaultdict(int)
    for b in borrowers:
        persona_counts[b["persona"]] += 1
    
    frequent_decliners = sorted([b for b in borrowers if b["is_frequent"]], key=lambda x: -x["risk_score"])[:10]
    
    return {
        "summary": {
            "total_calls": 1247,
            "connected": 1089,
            "connection_rate": 87.3,
            "confirmed": 734,
            "confirmation_rate": 67.4,
            "declined": 355,
            "borrowers_profiled": 500,
        },
        "decline_reasons": dict(reason_counts),
        "clusters": cluster_stats,
        "personas": dict(persona_counts),
        "frequent_decliners": frequent_decliners,
        "early_warnings": [
            {"cluster": "Warangal Rural", "type": "CLUSTER_STRESS", "message": "23% increase in financial stress declines", "level": "HIGH"},
            {"cluster": "Nashik Rural", "type": "CROP_SIGNAL", "message": "Spike in crop/agriculture reasons", "level": "MEDIUM"},
            {"cluster": "Guntur District", "type": "FREQUENT_DECLINER", "message": "8 new frequent decliners this month", "level": "MEDIUM"},
        ],
        "npa": {
            "current": 2.8,
            "predicted": 3.4,
            "at_risk": "4.2 Cr",
            "savings": "1.8 Cr",
        },
    }

INTELLIGENCE_DATA = generate_mock_intelligence()

# ============================================================================
# Exotel Integration
# ============================================================================

async def make_exotel_call(to_number: str, language: str = "hi-IN") -> dict:
    if not all([CONFIG["EXOTEL_API_KEY"], CONFIG["EXOTEL_API_TOKEN"], CONFIG["EXOTEL_ACCOUNT_SID"]]):
        return {"success": False, "error": "Exotel credentials not configured"}
    
    caller_id = CONFIG["EXOTEL_CALLER_ID_MOBILE"] or CONFIG["EXOTEL_CALLER_ID"]
    if not caller_id:
        return {"success": False, "error": "No caller ID configured"}
    
    to_number = to_number.replace(" ", "").replace("-", "")
    if not to_number.startswith("+"):
        if to_number.startswith("0"):
            to_number = "+91" + to_number[1:]
        elif len(to_number) == 10:
            to_number = "+91" + to_number
    
    call_id = f"call_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{to_number[-4:]}"
    
    active_calls[call_id] = {
        "to_number": to_number,
        "language": language,
        "state": CallState.GREETING,
        "decline_reason": None,
        "transcript": [],
        "started_at": datetime.now().isoformat(),
    }
    
    url = f"https://{CONFIG['EXOTEL_SUBDOMAIN']}/v1/Accounts/{CONFIG['EXOTEL_ACCOUNT_SID']}/Calls/connect.json"
    callback_url = f"{APP_BASE_URL}/exotel/callback/{call_id}"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            auth=(CONFIG["EXOTEL_API_KEY"], CONFIG["EXOTEL_API_TOKEN"]),
            data={
                "From": to_number,
                "CallerId": caller_id,
                "Url": callback_url,
                "CallType": "trans",
            },
            timeout=30.0
        )
        
        if response.status_code in [200, 201]:
            result = response.json()
            active_calls[call_id]["exotel_sid"] = result.get("Call", {}).get("Sid")
            return {"success": True, "call_id": call_id}
        else:
            del active_calls[call_id]
            return {"success": False, "error": response.text}

def generate_exoml_play_gather(audio_file: str, call_id: str, next_action: str, digits: int = 1) -> str:
    audio_url = f"{APP_BASE_URL}/audio/{audio_file}"
    action_url = f"{APP_BASE_URL}/exotel/{next_action}/{call_id}"
    
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{action_url}" method="POST" numDigits="{digits}" timeout="10">
        <Play>{audio_url}</Play>
    </Gather>
    <Redirect method="POST">{APP_BASE_URL}/exotel/no_input/{call_id}</Redirect>
</Response>"""

def generate_exoml_play_hangup(audio_file: str) -> str:
    audio_url = f"{APP_BASE_URL}/audio/{audio_file}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Hangup/>
</Response>"""

async def add_transcript(call_id: str, speaker: str, text: str, dtmf: str = None, reason: str = None):
    if call_id not in active_calls:
        return
    
    entry = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "speaker": speaker,
        "text": text,
        "dtmf": dtmf,
        "reason": reason,
    }
    active_calls[call_id]["transcript"].append(entry)
    
    for ws in ui_connections[:]:
        try:
            await ws.send_json({"type": "transcript", "call_id": call_id, "entry": entry})
        except:
            ui_connections.remove(ws)

# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(title="Fusion Finance Voice Intelligence")

@app.on_event("startup")
async def startup():
    global APP_BASE_URL
    APP_BASE_URL = get_base_url()
    print("=" * 60)
    print("Fusion Finance Voice Intelligence")
    print(f"Callback URL: {APP_BASE_URL}")
    print("=" * 60)

@app.get("/audio/{language}/{filename}")
async def serve_audio(language: str, filename: str):
    audio_path = AUDIO_DIR / language / filename
    if not audio_path.exists():
        audio_path = AUDIO_DIR / "hi-IN" / filename
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return Response(content=audio_path.read_bytes(), media_type="audio/wav")

@app.post("/exotel/callback/{call_id}")
async def exotel_callback(call_id: str):
    if call_id not in active_calls:
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    call = active_calls[call_id]
    lang = call.get("language", "hi-IN")
    
    await add_transcript(call_id, "Agent", f"Greeting - {RO_NAMES.get(lang, 'RO')} tomorrow")
    
    exoml = generate_exoml_play_gather(f"{lang}/01_greeting.wav", call_id, "availability")
    call["state"] = CallState.WAIT_AVAILABILITY
    return Response(content=exoml, media_type="application/xml")

@app.post("/exotel/availability/{call_id}")
async def handle_availability(call_id: str, request: Request):
    if call_id not in active_calls:
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    form = await request.form()
    digits = form.get("digits", "")
    call = active_calls[call_id]
    lang = call.get("language", "hi-IN")
    
    await add_transcript(call_id, "Borrower", f"Pressed {digits}", dtmf=digits)
    
    if digits == "1":
        await add_transcript(call_id, "Agent", "Confirmed - visit tomorrow")
        call["state"] = CallState.COMPLETED
        call["outcome"] = "AVAILABLE"
        return Response(content=generate_exoml_play_hangup(f"{lang}/02_confirmed.wav"), media_type="application/xml")
    
    elif digits == "2":
        await add_transcript(call_id, "Agent", "Asking decline reason")
        call["state"] = CallState.WAIT_REASON
        return Response(content=generate_exoml_play_gather(f"{lang}/03_ask_reason.wav", call_id, "reason"), media_type="application/xml")
    
    else:
        await add_transcript(call_id, "Agent", "Unclear - repeating")
        return Response(content=generate_exoml_play_gather(f"{lang}/05_unclear.wav", call_id, "availability"), media_type="application/xml")

@app.post("/exotel/reason/{call_id}")
async def handle_reason(call_id: str, request: Request):
    if call_id not in active_calls:
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    form = await request.form()
    digits = form.get("digits", "")
    call = active_calls[call_id]
    lang = call.get("language", "hi-IN")
    
    reason_label, reason_code = DTMF_REASONS.get(digits, ("Other", "OTHER"))
    call["decline_reason"] = reason_code
    
    await add_transcript(call_id, "Borrower", f"Reason: {reason_label}", dtmf=digits, reason=reason_code)
    await add_transcript(call_id, "Agent", "Rescheduled to next week")
    
    call["state"] = CallState.COMPLETED
    call["outcome"] = "RESCHEDULED"
    
    return Response(content=generate_exoml_play_hangup(f"{lang}/04_reschedule_confirm.wav"), media_type="application/xml")

@app.post("/exotel/no_input/{call_id}")
async def handle_no_input(call_id: str):
    if call_id not in active_calls:
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    call = active_calls[call_id]
    lang = call.get("language", "hi-IN")
    
    await add_transcript(call_id, "System", "No input - repeating")
    return Response(content=generate_exoml_play_gather(f"{lang}/05_unclear.wav", call_id, "availability"), media_type="application/xml")

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

class CallRequest(BaseModel):
    phone: str
    language: str = "hi-IN"

@app.post("/api/call")
async def initiate_call(request: CallRequest):
    return await make_exotel_call(request.phone, request.language)

@app.get("/api/calls")
async def list_calls():
    return active_calls

@app.get("/api/intelligence")
async def get_intelligence():
    return INTELLIGENCE_DATA

@app.get("/api/config")
async def get_config():
    return {
        "account_sid": CONFIG["EXOTEL_ACCOUNT_SID"],
        "caller_id": CONFIG["EXOTEL_CALLER_ID"],
        "caller_id_mobile": CONFIG["EXOTEL_CALLER_ID_MOBILE"],
        "callback_url": APP_BASE_URL,
        "api_configured": bool(CONFIG["EXOTEL_API_KEY"] and CONFIG["EXOTEL_API_TOKEN"]),
    }

# ============================================================================
# UI - Smaartbrand Theme
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smaartbrand Voice | Fusion Finance</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { font-family: 'Inter', sans-serif; }
        body { background: #0d0f1a; min-height: 100vh; }
        
        .glass { background: rgba(255,255,255,0.03); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.08); }
        .glass-dark { background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.05); }
        
        .gradient-text { background: linear-gradient(135deg, #f97316 0%, #8b5cf6 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .gradient-orange { background: linear-gradient(135deg, #f97316 0%, #ea580c 100%); }
        .gradient-purple { background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%); }
        
        .tab-btn { transition: all 0.3s; border-radius: 8px; }
        .tab-btn.active { background: linear-gradient(135deg, #f97316 0%, #ea580c 100%); color: white; }
        .tab-btn:not(.active):hover { background: rgba(255,255,255,0.05); }
        
        .stat-card { transition: all 0.3s; }
        .stat-card:hover { transform: translateY(-4px); box-shadow: 0 10px 40px rgba(249, 115, 22, 0.15); }
        
        .alert-high { border-left: 3px solid #ef4444; background: rgba(239, 68, 68, 0.1); }
        .alert-medium { border-left: 3px solid #f59e0b; background: rgba(245, 158, 11, 0.1); }
        .alert-low { border-left: 3px solid #22c55e; background: rgba(34, 197, 94, 0.1); }
        
        .message.agent { background: rgba(139, 92, 246, 0.15); border-left: 3px solid #8b5cf6; }
        .message.borrower { background: rgba(249, 115, 22, 0.15); border-left: 3px solid #f97316; }
        
        .lang-btn.active { background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%); border-color: #8b5cf6; color: white; }
        
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.2); }
        ::-webkit-scrollbar-thumb { background: #8b5cf6; border-radius: 3px; }
        
        /* Acquink Logo SVG */
        .acquink-logo {
            width: 40px;
            height: 40px;
        }
    </style>
</head>
<body class="text-white flex flex-col min-h-screen">
    <!-- Header - Matching Smaartbrand Moto -->
    <header class="px-6 py-4 border-b border-white/10">
        <div class="max-w-7xl mx-auto flex items-center justify-between">
            <div class="flex items-center gap-3">
                <!-- Acquink Logo -->
                <svg class="acquink-logo" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M20 25 L20 75 Q20 85 30 85 L50 85" stroke="url(#grad1)" stroke-width="12" stroke-linecap="round" fill="none"/>
                    <path d="M80 15 L80 65 Q80 75 70 75 L45 75" stroke="url(#grad2)" stroke-width="12" stroke-linecap="round" fill="none"/>
                    <circle cx="80" cy="85" r="8" fill="#3b82f6"/>
                    <defs>
                        <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" style="stop-color:#8b5cf6"/>
                            <stop offset="100%" style="stop-color:#3b82f6"/>
                        </linearGradient>
                        <linearGradient id="grad2" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" style="stop-color:#f97316"/>
                            <stop offset="100%" style="stop-color:#8b5cf6"/>
                        </linearGradient>
                    </defs>
                </svg>
                <div>
                    <h1 class="text-xl font-semibold gradient-text">Smaartbrand Voice</h1>
                    <p class="text-xs text-gray-500">Pre-Collection Intelligence</p>
                </div>
            </div>
            
            <div class="flex items-center gap-6">
                <!-- Tabs - Matching Smaartbrand style -->
                <div class="flex items-center gap-1 glass rounded-lg p-1">
                    <button class="tab-btn active px-4 py-2 text-sm font-medium" onclick="showTab('calls')">Live Calls</button>
                    <button class="tab-btn px-4 py-2 text-sm font-medium" onclick="showTab('intel')">Intelligence</button>
                </div>
                
                <!-- SmaartAnalyst button -->
                <button class="flex items-center gap-2 glass px-4 py-2 rounded-lg text-sm hover:bg-white/5">
                    <span>💬</span>
                    <span>SmaartAnalyst</span>
                </button>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto p-6">
        <!-- Live Calls Tab -->
        <div id="callsTab" class="tab-panel">
            <div class="grid grid-cols-3 gap-6">
                <!-- Call Controls -->
                <div class="col-span-1 space-y-4">
                    <div class="glass rounded-2xl p-6">
                        <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Make a Call</h3>
                        
                        <div class="space-y-4">
                            <div>
                                <label class="text-xs text-gray-500 mb-1 block">Phone Number</label>
                                <input type="tel" id="phone" placeholder="9876543210" class="w-full glass-dark rounded-lg px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500">
                            </div>
                            
                            <div>
                                <label class="text-xs text-gray-500 mb-2 block">Language</label>
                                <div class="grid grid-cols-3 gap-2">
                                    <button class="lang-btn active glass rounded-lg py-2 text-xs border border-transparent" data-lang="hi-IN">हिंदी</button>
                                    <button class="lang-btn glass rounded-lg py-2 text-xs border border-transparent" data-lang="te-IN">తెలుగు</button>
                                    <button class="lang-btn glass rounded-lg py-2 text-xs border border-transparent" data-lang="ta-IN">தமிழ்</button>
                                    <button class="lang-btn glass rounded-lg py-2 text-xs border border-transparent" data-lang="kn-IN">ಕನ್ನಡ</button>
                                    <button class="lang-btn glass rounded-lg py-2 text-xs border border-transparent" data-lang="mr-IN">मराठी</button>
                                    <button class="lang-btn glass rounded-lg py-2 text-xs border border-transparent" data-lang="en-IN">English</button>
                                </div>
                            </div>
                            
                            <button id="callBtn" onclick="makeCall()" class="w-full gradient-orange text-white font-semibold py-3 rounded-xl hover:opacity-90 transition">
                                📞 Call Now
                            </button>
                            
                            <div id="callStatus" class="text-center text-sm text-gray-400"></div>
                        </div>
                    </div>
                    
                    <div class="glass rounded-2xl p-6">
                        <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Configuration</h3>
                        <div id="configInfo" class="space-y-2 text-xs"></div>
                    </div>
                </div>
                
                <!-- Live Transcript -->
                <div class="col-span-2">
                    <div class="glass rounded-2xl p-6 h-[600px] flex flex-col">
                        <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Live Transcript</h3>
                        <div id="transcript" class="flex-1 overflow-y-auto space-y-3">
                            <div class="text-center text-gray-500 py-20">
                                <div class="text-4xl mb-4">🎙️</div>
                                <p>Make a call to see the live transcript</p>
                                <p class="text-xs mt-2">DTMF responses and decline reasons will appear here</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Intelligence Dashboard Tab -->
        <div id="intelTab" class="tab-panel hidden">
            <!-- Stats Row -->
            <div class="grid grid-cols-5 gap-4 mb-6">
                <div class="stat-card glass rounded-xl p-5 text-center">
                    <div class="text-3xl font-bold text-orange-500" id="statCalls">1,247</div>
                    <div class="text-xs text-gray-400 mt-1">Total Calls</div>
                </div>
                <div class="stat-card glass rounded-xl p-5 text-center">
                    <div class="text-3xl font-bold text-blue-400" id="statConnected">87.3%</div>
                    <div class="text-xs text-gray-400 mt-1">Connection Rate</div>
                </div>
                <div class="stat-card glass rounded-xl p-5 text-center">
                    <div class="text-3xl font-bold text-green-400" id="statConfirmed">67.4%</div>
                    <div class="text-xs text-gray-400 mt-1">Confirmed</div>
                </div>
                <div class="stat-card glass rounded-xl p-5 text-center">
                    <div class="text-3xl font-bold text-red-400" id="statDecliners">12.4%</div>
                    <div class="text-xs text-gray-400 mt-1">Frequent Decliners</div>
                </div>
                <div class="stat-card glass rounded-xl p-5 text-center">
                    <div class="text-3xl font-bold text-purple-400" id="statBorrowers">500</div>
                    <div class="text-xs text-gray-400 mt-1">Profiled</div>
                </div>
            </div>
            
            <!-- Main Grid -->
            <div class="grid grid-cols-2 gap-6 mb-6">
                <!-- Decline Reasons -->
                <div class="glass rounded-2xl p-6">
                    <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">📊 Decline Reason Distribution</h3>
                    <div id="reasonsList" class="space-y-3"></div>
                </div>
                
                <!-- Cluster Risk -->
                <div class="glass rounded-2xl p-6">
                    <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">📍 Cluster Risk Monitor</h3>
                    <div id="clustersList" class="space-y-3"></div>
                </div>
            </div>
            
            <!-- Early Warnings -->
            <div class="glass rounded-2xl p-6 mb-6">
                <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">⚠️ Early Warning Signals</h3>
                <div id="warningsList" class="grid grid-cols-3 gap-4"></div>
            </div>
            
            <!-- Bottom Row -->
            <div class="grid grid-cols-2 gap-6 mb-6">
                <!-- Frequent Decliners -->
                <div class="glass rounded-2xl p-6">
                    <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">🚨 Frequent Decliners (Top 10)</h3>
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-gray-500 text-xs">
                                <th class="text-left py-2">ID</th>
                                <th class="text-left py-2">Cluster</th>
                                <th class="text-left py-2">Declines</th>
                                <th class="text-left py-2">Reason</th>
                                <th class="text-left py-2">Risk</th>
                            </tr>
                        </thead>
                        <tbody id="declinersTbody"></tbody>
                    </table>
                </div>
                
                <!-- Persona Distribution -->
                <div class="glass rounded-2xl p-6">
                    <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">👥 Borrower Personas</h3>
                    <div id="personaGrid" class="grid grid-cols-5 gap-3"></div>
                </div>
            </div>
            
            <!-- NPA Prediction -->
            <div class="glass rounded-2xl p-6 border border-orange-500/30">
                <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">🎯 NPA Prediction & Early Intervention Value</h3>
                <div class="grid grid-cols-4 gap-6">
                    <div class="text-center">
                        <div class="text-xs text-gray-500 mb-2">Current NPA</div>
                        <div class="text-3xl font-bold text-green-400">2.8%</div>
                    </div>
                    <div class="text-center">
                        <div class="text-xs text-gray-500 mb-2">Predicted (60 days)</div>
                        <div class="text-3xl font-bold text-yellow-400">3.4%</div>
                    </div>
                    <div class="text-center">
                        <div class="text-xs text-gray-500 mb-2">At-Risk Portfolio</div>
                        <div class="text-3xl font-bold text-red-400">₹4.2 Cr</div>
                    </div>
                    <div class="text-center">
                        <div class="text-xs text-gray-500 mb-2">Early Intervention Saves</div>
                        <div class="text-3xl font-bold text-orange-500">₹1.8 Cr</div>
                    </div>
                </div>
            </div>
        </div>
    </main>
    
    <!-- Footer - Matching Smaartbrand Moto -->
    <footer class="mt-auto px-6 py-4 border-t border-white/10">
        <div class="max-w-7xl mx-auto flex items-center justify-between">
            <div class="flex items-center gap-3">
                <svg class="w-6 h-6" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M20 25 L20 75 Q20 85 30 85 L50 85" stroke="url(#grad1f)" stroke-width="12" stroke-linecap="round" fill="none"/>
                    <path d="M80 15 L80 65 Q80 75 70 75 L45 75" stroke="url(#grad2f)" stroke-width="12" stroke-linecap="round" fill="none"/>
                    <circle cx="80" cy="85" r="8" fill="#3b82f6"/>
                    <defs>
                        <linearGradient id="grad1f" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" style="stop-color:#8b5cf6"/>
                            <stop offset="100%" style="stop-color:#3b82f6"/>
                        </linearGradient>
                        <linearGradient id="grad2f" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" style="stop-color:#f97316"/>
                            <stop offset="100%" style="stop-color:#8b5cf6"/>
                        </linearGradient>
                    </defs>
                </svg>
                <span class="text-sm text-gray-500">© 2026 Acquink Technologies</span>
            </div>
            <div class="text-sm text-gray-500">
                Powered by <span class="text-purple-400 font-medium">MASI</span> Technology
            </div>
        </div>
    </footer>

    <script>
        let ws;
        let selectedLang = 'hi-IN';
        let intelData = null;
        
        // Tab switching
        function showTab(tab) {
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(tab + 'Tab').classList.remove('hidden');
            event.target.classList.add('active');
            
            if (tab === 'intel' && !intelData) loadIntelligence();
        }
        
        // Language selection
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                selectedLang = btn.dataset.lang;
            });
        });
        
        // WebSocket
        function connectWS() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${location.host}/ws`);
            
            ws.onopen = () => {
                document.getElementById('wsStatus').className = 'px-3 py-1 rounded-full text-xs font-medium bg-green-500/20 text-green-400';
                document.getElementById('wsStatus').textContent = 'Connected';
            };
            
            ws.onclose = () => {
                document.getElementById('wsStatus').className = 'px-3 py-1 rounded-full text-xs font-medium bg-red-500/20 text-red-400';
                document.getElementById('wsStatus').textContent = 'Disconnected';
                setTimeout(connectWS, 3000);
            };
            
            ws.onmessage = (e) => {
                const msg = JSON.parse(e.data);
                if (msg.type === 'transcript') addTranscriptEntry(msg.entry);
            };
        }
        
        function addTranscriptEntry(entry) {
            const box = document.getElementById('transcript');
            if (box.querySelector('.text-gray-500')) box.innerHTML = '';
            
            const isAgent = entry.speaker === 'Agent';
            let tags = '';
            if (entry.dtmf) tags += `<span class="px-2 py-0.5 rounded text-xs bg-blue-500/20 text-blue-300 ml-2">DTMF: ${entry.dtmf}</span>`;
            if (entry.reason) tags += `<span class="px-2 py-0.5 rounded text-xs bg-orange-500/20 text-orange-300 ml-2">${entry.reason}</span>`;
            
            box.insertAdjacentHTML('beforeend', `
                <div class="message ${isAgent ? 'agent' : 'borrower'} rounded-xl p-4">
                    <div class="flex justify-between items-center mb-2">
                        <span class="font-semibold text-sm ${isAgent ? 'text-blue-400' : 'text-orange-400'}">${entry.speaker}</span>
                        <span class="text-xs text-gray-500">${entry.timestamp}</span>
                    </div>
                    <div class="text-sm">${entry.text}${tags}</div>
                </div>
            `);
            box.scrollTop = box.scrollHeight;
        }
        
        async function makeCall() {
            const phone = document.getElementById('phone').value;
            if (!phone) { alert('Enter phone number'); return; }
            
            const btn = document.getElementById('callBtn');
            btn.disabled = true;
            btn.textContent = '📞 Calling...';
            document.getElementById('callStatus').textContent = 'Initiating...';
            document.getElementById('transcript').innerHTML = '<div class="text-center text-gray-500 py-10">Connecting...</div>';
            
            const resp = await fetch('/api/call', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone, language: selectedLang })
            });
            const result = await resp.json();
            
            if (result.success) {
                document.getElementById('callStatus').textContent = `Call ID: ${result.call_id}`;
            } else {
                document.getElementById('callStatus').textContent = `Error: ${result.error}`;
            }
            
            btn.disabled = false;
            btn.textContent = '📞 Call Now';
        }
        
        async function loadConfig() {
            const resp = await fetch('/api/config');
            const cfg = await resp.json();
            
            document.getElementById('configInfo').innerHTML = `
                <div class="flex justify-between py-1 border-b border-white/5">
                    <span class="text-gray-500">Account</span>
                    <span class="text-gray-300">${cfg.account_sid || 'Not set'}</span>
                </div>
                <div class="flex justify-between py-1 border-b border-white/5">
                    <span class="text-gray-500">Caller ID</span>
                    <span class="text-gray-300">${cfg.caller_id || cfg.caller_id_mobile || 'Not set'}</span>
                </div>
                <div class="flex justify-between py-1 border-b border-white/5">
                    <span class="text-gray-500">API</span>
                    <span class="${cfg.api_configured ? 'text-green-400' : 'text-red-400'}">${cfg.api_configured ? '✓ Configured' : '✗ Missing'}</span>
                </div>
                <div class="flex justify-between py-1">
                    <span class="text-gray-500">Callback</span>
                    <span class="text-gray-300 text-xs truncate max-w-[150px]">${cfg.callback_url}</span>
                </div>
            `;
        }
        
        async function loadIntelligence() {
            const resp = await fetch('/api/intelligence');
            intelData = await resp.json();
            renderIntelligence();
        }
        
        function renderIntelligence() {
            const d = intelData;
            
            // Stats
            document.getElementById('statCalls').textContent = d.summary.total_calls.toLocaleString();
            document.getElementById('statConnected').textContent = d.summary.connection_rate + '%';
            document.getElementById('statConfirmed').textContent = d.summary.confirmation_rate + '%';
            
            // Decline reasons
            const reasons = Object.entries(d.decline_reasons).sort((a,b) => b[1] - a[1]);
            const maxR = Math.max(...reasons.map(r => r[1]));
            const reasonIcons = {
                'FINANCIAL_STRESS': '💰', 'TRAVEL_MARKET': '🚗', 'HEALTH': '🏥',
                'CROP_AGRICULTURE': '🌾', 'WORK_CONFLICT': '💼', 'FAMILY_EVENT': '👨‍👩‍👧'
            };
            
            document.getElementById('reasonsList').innerHTML = reasons.slice(0, 6).map(([k, v]) => `
                <div class="flex items-center gap-3">
                    <span class="text-xl">${reasonIcons[k] || '❓'}</span>
                    <div class="flex-1">
                        <div class="flex justify-between text-sm mb-1">
                            <span>${k.replace(/_/g, ' ')}</span>
                            <span class="text-gray-400">${v}</span>
                        </div>
                        <div class="h-2 bg-white/10 rounded-full overflow-hidden">
                            <div class="h-full gradient-orange rounded-full" style="width: ${(v/maxR)*100}%"></div>
                        </div>
                    </div>
                </div>
            `).join('');
            
            // Clusters
            document.getElementById('clustersList').innerHTML = Object.entries(d.clusters).map(([name, c]) => `
                <div class="alert-${c.alert.toLowerCase()} rounded-lg p-3">
                    <div class="flex justify-between items-center">
                        <div>
                            <div class="font-medium">${name}</div>
                            <div class="text-xs text-gray-400">${c.state}</div>
                        </div>
                        <div class="flex gap-4 text-xs">
                            <div class="text-center">
                                <div class="font-bold">${c.total}</div>
                                <div class="text-gray-500">Borrowers</div>
                            </div>
                            <div class="text-center">
                                <div class="font-bold">${c.avg_risk}</div>
                                <div class="text-gray-500">Avg Risk</div>
                            </div>
                            <div class="text-center">
                                <div class="font-bold">${c.frequent}</div>
                                <div class="text-gray-500">Freq Dec</div>
                            </div>
                        </div>
                        <span class="px-2 py-1 rounded text-xs font-bold ${c.alert === 'HIGH' ? 'bg-red-500/20 text-red-400' : c.alert === 'MEDIUM' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-green-500/20 text-green-400'}">${c.alert}</span>
                    </div>
                </div>
            `).join('');
            
            // Warnings
            document.getElementById('warningsList').innerHTML = d.early_warnings.map(w => `
                <div class="alert-${w.level.toLowerCase()} rounded-lg p-4">
                    <div class="font-medium mb-1">${w.cluster}</div>
                    <div class="text-sm text-gray-300 mb-2">${w.message}</div>
                    <div class="text-xs text-orange-400">→ Recommend intervention</div>
                </div>
            `).join('');
            
            // Frequent decliners
            document.getElementById('declinersTbody').innerHTML = d.frequent_decliners.map(b => `
                <tr class="border-b border-white/5">
                    <td class="py-2 text-gray-300">${b.id}</td>
                    <td class="py-2 text-gray-400">${b.cluster}</td>
                    <td class="py-2">${b.decline_count}</td>
                    <td class="py-2 text-xs">${(b.decline_reasons[0] || '-').replace(/_/g, ' ')}</td>
                    <td class="py-2"><span class="px-2 py-0.5 rounded text-xs ${b.risk_score >= 60 ? 'bg-red-500/20 text-red-400' : b.risk_score >= 40 ? 'bg-yellow-500/20 text-yellow-400' : 'bg-green-500/20 text-green-400'}">${b.risk_score}</span></td>
                </tr>
            `).join('');
            
            // Personas
            const personaIcons = { 'FARMER': '👨‍🌾', 'TRADER': '🏪', 'SALARIED': '💼', 'SELF_EMPLOYED': '🔧', 'DAILY_WAGE': '🏗️' };
            const totalP = Object.values(d.personas).reduce((a, b) => a + b, 0);
            document.getElementById('personaGrid').innerHTML = Object.entries(d.personas).map(([k, v]) => `
                <div class="glass rounded-xl p-4 text-center">
                    <div class="text-2xl mb-2">${personaIcons[k] || '👤'}</div>
                    <div class="text-xs text-gray-400 mb-1">${k.replace(/_/g, ' ')}</div>
                    <div class="text-xl font-bold text-orange-400">${Math.round(v/totalP*100)}%</div>
                </div>
            `).join('');
        }
        
        connectWS();
        loadConfig();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
