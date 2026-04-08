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
from fastapi.responses import HTMLResponse, Response, JSONResponse
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
        {"name": "Shad Nagar", "state": "Telangana"},
        {"name": "Karimnagar", "state": "Telangana"},
        {"name": "Nizamabad", "state": "Telangana"},
        {"name": "Medak", "state": "Telangana"},
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
    
    # Clean phone number - Exotel wants 10 digits for Indian numbers
    to_number = to_number.replace(" ", "").replace("-", "").replace("+91", "").replace("+", "")
    if to_number.startswith("0"):
        to_number = to_number[1:]
    # Now to_number should be 10 digits like 9849270361
    
    call_id = f"call_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{to_number[-4:]}"
    
    active_calls[call_id] = {
        "to_number": to_number,
        "language": language,
        "state": CallState.GREETING,
        "decline_reason": None,
        "transcript": [],
        "started_at": datetime.now().isoformat(),
    }
    
    api_url = f"https://{CONFIG['EXOTEL_SUBDOMAIN']}/v1/Accounts/{CONFIG['EXOTEL_ACCOUNT_SID']}/Calls/connect.json"
    status_url = f"{APP_BASE_URL}/exotel/status/{call_id}"
    
    # Use Exotel internal flow URL - Connect applet will call our server
    flow_url = "http://my.exotel.com/enixta1/exoml/start_voice/1222663"
    
    print(f"=== INITIATING CALL ===")
    print(f"To Number (10 digit): {to_number}")
    print(f"Caller ID: {caller_id}")
    print(f"Flow URL: {flow_url}")
    print(f"Status URL: {status_url}")
    print(f"API URL: {api_url}")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            api_url,
            auth=(CONFIG["EXOTEL_API_KEY"], CONFIG["EXOTEL_API_TOKEN"]),
            data={
                "From": to_number,
                "CallerId": caller_id,
                "Url": flow_url,
                "CallType": "trans",
                "StatusCallback": status_url,
            },
            timeout=30.0
        )
        
        print(f"Exotel API Response: {response.status_code}")
        print(f"Exotel Response Body: {response.text[:1000]}")
        
        if response.status_code in [200, 201]:
            result = response.json()
            active_calls[call_id]["exotel_sid"] = result.get("Call", {}).get("Sid")
            print(f"Call initiated successfully: {call_id}, Exotel SID: {active_calls[call_id]['exotel_sid']}")
            return {"success": True, "call_id": call_id}
        else:
            del active_calls[call_id]
            return {"success": False, "error": response.text}

def generate_exoml_play_gather(audio_file: str, call_id: str, next_action: str, digits: int = 1) -> str:
    audio_url = f"{APP_BASE_URL}/audio/{audio_file}"
    action_url = f"{APP_BASE_URL}/exotel/{next_action}/{call_id}"
    
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{action_url}" method="GET" numDigits="{digits}" timeout="10">
        <Play>{audio_url}</Play>
    </Gather>
    <Redirect method="GET">{APP_BASE_URL}/exotel/no_input/{call_id}</Redirect>
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

@app.middleware("http")
async def log_all_requests(request: Request, call_next):
    """Log every incoming request for debugging"""
    print(f">>> INCOMING: {request.method} {request.url.path}")
    print(f">>> Query: {dict(request.query_params)}")
    print(f">>> Headers: {dict(request.headers)}")
    response = await call_next(request)
    print(f"<<< RESPONSE: {response.status_code}")
    return response

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

@app.get("/acquink_logo.png")
async def serve_logo():
    logo_path = Path(__file__).parent / "acquink_logo.png"
    if not logo_path.exists():
        raise HTTPException(status_code=404, detail="Logo not found")
    return Response(content=logo_path.read_bytes(), media_type="image/png")

# Store mapping of Exotel CallSid to our call_id
exotel_to_local: Dict[str, str] = {}

@app.api_route("/exotel/status/{call_id}", methods=["GET", "POST"])
async def exotel_status_callback(call_id: str, request: Request):
    """Log call status updates from Exotel"""
    all_params = dict(request.query_params)
    
    # Try to read raw body
    try:
        body = await request.body()
        print(f"=== STATUS CALLBACK for {call_id} ===")
        print(f"Method: {request.method}")
        print(f"Raw Body: {body}")
        print(f"Query Params: {all_params}")
    except Exception as e:
        print(f"Error reading body: {e}")
    
    if request.method == "POST":
        try:
            form = await request.form()
            all_params.update(dict(form))
            print(f"Form Params: {dict(form)}")
        except Exception as e:
            print(f"Error reading form: {e}")
    
    print(f"Status: {all_params.get('Status', 'unknown')}")
    print(f"CallSid: {all_params.get('CallSid', 'unknown')}")
    
    return Response(content="OK", media_type="text/plain")

@app.api_route("/exotel/greeting", methods=["GET", "POST", "HEAD"])
async def exotel_dynamic_greeting(request: Request):
    """
    Return dynamic text for Greeting applet TTS.
    Exotel will convert text to speech.
    """
    # Handle HEAD request
    if request.method == "HEAD":
        return Response(content="", media_type="text/plain")
    
    all_params = dict(request.query_params)
    
    if request.method == "POST":
        try:
            form = await request.form()
            all_params.update(dict(form))
        except:
            pass
    
    print(f"=== DYNAMIC GREETING ===")
    print(f"Method: {request.method}")
    print(f"All Params: {all_params}")
    
    call_sid = all_params.get("CallSid", "")
    caller_from = all_params.get("From", "")
    
    print(f"CallSid: {call_sid}")
    print(f"From: {caller_from}")
    
    # Find the language from our active calls
    lang = "hi-IN"  # default
    for cid, call in active_calls.items():
        call_phone = call.get("to_number", "")[-10:]
        from_phone = caller_from.replace("+91", "").replace("+", "")[-10:]
        if call_phone == from_phone:
            lang = call.get("language", "hi-IN")
            print(f"Found call {cid}, language: {lang}")
            break
    
    # TTS text by language
    greetings = {
        "hi-IN": "नमस्ते, यह फ्यूजन फाइनेंस से एक महत्वपूर्ण कॉल है। कल आपकी EMI जमा करने की तारीख है। कृपया पुष्टि करने के लिए एक दबाएं, या पुनर्निर्धारित करने के लिए दो दबाएं।",
        "ta-IN": "வணக்கம், இது ஃபியூஷன் ஃபைனான்ஸிலிருந்து ஒரு முக்கியமான அழைப்பு. நாளை உங்கள் EMI செலுத்த வேண்டிய தேதி. உறுதிப்படுத்த ஒன்றை அழுத்தவும், அல்லது மறுதிட்டமிட இரண்டை அழுத்தவும்.",
        "te-IN": "నమస్కారం, ఇది ఫ్యూజన్ ఫైనాన్స్ నుండి ఒక ముఖ్యమైన కాల్. రేపు మీ EMI చెల్లింపు తేదీ. నిర్ధారించడానికి ఒకటి నొక్కండి, లేదా పునర్నిర్ణయించడానికి రెండు నొక్కండి.",
        "kn-IN": "ನಮಸ್ಕಾರ, ಇದು ಫ್ಯೂಷನ್ ಫೈನಾನ್ಸ್‌ನಿಂದ ಪ್ರಮುಖ ಕರೆ. ನಾಳೆ ನಿಮ್ಮ EMI ಪಾವತಿ ದಿನಾಂಕ. ದೃಢೀಕರಿಸಲು ಒಂದು ಒತ್ತಿ, ಅಥವಾ ಮರುನಿಗದಿಪಡಿಸಲು ಎರಡು ಒತ್ತಿ.",
        "mr-IN": "नमस्कार, हा फ्यूजन फायनान्सकडून एक महत्त्वाचा कॉल आहे. उद्या तुमची EMI भरण्याची तारीख आहे. पुष्टी करण्यासाठी एक दाबा, किंवा पुन्हा शेड्यूल करण्यासाठी दोन दाबा.",
        "en-IN": "Hello, this is an important call from Fusion Finance. Tomorrow is your EMI payment date. Press one to confirm, or press two to reschedule."
    }
    
    text = greetings.get(lang, greetings["en-IN"])
    print(f"Returning TTS text for {lang}: {text[:50]}...")
    
    # Return plain text for TTS
    return Response(content=text, media_type="text/plain")

@app.api_route("/exotel/connect-playback", methods=["GET", "HEAD"])
async def exotel_connect_playback(request: Request):
    """
    Dynamic playback for Connect applet.
    Returns JSON with audio URL based on caller's language preference.
    """
    # Handle HEAD request (required by Exotel)
    if request.method == "HEAD":
        return Response(
            content="",
            media_type="application/json",
            headers={"Content-Type": "application/json"}
        )
    
    all_params = dict(request.query_params)
    
    print(f"=== CONNECT PLAYBACK ===")
    print(f"Method: {request.method}")
    print(f"All Params: {all_params}")
    
    call_sid = all_params.get("CallSid", "")
    caller_from = all_params.get("From", "")
    caller_to = all_params.get("To", "")
    dial_whom = all_params.get("DialWhomNumber", "")
    
    print(f"CallSid: {call_sid}")
    print(f"From: {caller_from}")
    print(f"To: {caller_to}")
    print(f"DialWhomNumber: {dial_whom}")
    
    # Find the language from our active calls based on phone number
    lang = "hi-IN"  # default
    for cid, call in active_calls.items():
        call_phone = call.get("to_number", "")[-10:]
        # Match against From or DialWhomNumber
        from_phone = caller_from.replace("+91", "").replace("+", "")[-10:]
        dial_phone = dial_whom.replace("+91", "").replace("+", "")[-10:] if dial_whom else ""
        
        if call_phone == from_phone or call_phone == dial_phone:
            lang = call.get("language", "hi-IN")
            print(f"Found call {cid}, language: {lang}")
            break
    
    audio_url = f"{APP_BASE_URL}/audio/{lang}/01_greeting.wav"
    print(f"Returning audio URL: {audio_url}")
    
    # Return JSON response as per Exotel spec
    response_data = {
        "start_call_playback": {
            "playback_to": "callee",
            "type": "audio_url",
            "value": audio_url
        }
    }
    
    return JSONResponse(content=response_data, media_type="application/json")

@app.api_route("/exotel/callback/", methods=["GET", "POST"])
async def exotel_passthru_callback(request: Request):
    """Handle Passthru callback from Exotel flow"""
    
    # Get ALL params for debugging
    all_params = dict(request.query_params)
    
    # Exotel might use different param names - try all variations
    exotel_sid = all_params.get("CallSid") or all_params.get("callsid") or all_params.get("call_sid") or ""
    caller_from = all_params.get("From") or all_params.get("from") or all_params.get("CallFrom") or ""
    caller_to = all_params.get("To") or all_params.get("to") or all_params.get("CallTo") or ""
    
    # If POST, also check form data
    if request.method == "POST":
        form = await request.form()
        form_dict = dict(form)
        print(f"Form data: {form_dict}")
        exotel_sid = exotel_sid or form_dict.get("CallSid", "") or form_dict.get("callsid", "")
        caller_from = caller_from or form_dict.get("From", "") or form_dict.get("from", "")
        caller_to = caller_to or form_dict.get("To", "") or form_dict.get("to", "")
    
    print(f"=== Exotel Callback ===")
    print(f"Method: {request.method}")
    print(f"ALL PARAMS: {all_params}")
    print(f"CallSid: {exotel_sid}")
    print(f"From: {caller_from}")
    print(f"To: {caller_to}")
    
    # STRATEGY 1: Match by CallSid (if we stored it from API response)
    call_id = None
    for cid, call in active_calls.items():
        stored_sid = call.get("exotel_sid", "")
        if stored_sid and stored_sid == exotel_sid:
            call_id = cid
            print(f"Match by CallSid: {call_id}")
            break
    
    # STRATEGY 2: Match by phone number if CallSid didn't work
    if not call_id:
        for cid, call in active_calls.items():
            call_phone = call.get("to_number", "").replace("+91", "").replace("+", "")[-10:]
            to_phone = caller_to.replace("+91", "").replace("+", "")[-10:] if caller_to else ""
            from_phone = caller_from.replace("+91", "").replace("+", "")[-10:] if caller_from else ""
            
            print(f"Comparing: call_phone={call_phone}, to_phone={to_phone}, from_phone={from_phone}, state={call.get('state')}")
            
            if call.get("state") == CallState.GREETING:
                if (to_phone and call_phone == to_phone) or (from_phone and call_phone == from_phone):
                    call_id = cid
                    exotel_to_local[exotel_sid] = call_id
                    print(f"Match by phone: {call_id}")
                    break
    
    # STRATEGY 3: If still no match but we have active calls in GREETING state, use the most recent one
    if not call_id:
        greeting_calls = [(cid, call) for cid, call in active_calls.items() if call.get("state") == CallState.GREETING]
        if greeting_calls:
            # Sort by started_at descending and take most recent
            greeting_calls.sort(key=lambda x: x[1].get("started_at", ""), reverse=True)
            call_id = greeting_calls[0][0]
            call = greeting_calls[0][1]
            print(f"Fallback to most recent GREETING call: {call_id}")
            if exotel_sid:
                active_calls[call_id]["exotel_sid"] = exotel_sid
                exotel_to_local[exotel_sid] = call_id
    
    if not call_id:
        print("No matching call found, playing default Hindi greeting")
        exoml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{APP_BASE_URL}/exotel/availability/default" method="GET" numDigits="1" timeout="10">
        <Play>{APP_BASE_URL}/audio/hi-IN/01_greeting.wav</Play>
    </Gather>
    <Play>{APP_BASE_URL}/audio/hi-IN/05_unclear.wav</Play>
    <Hangup/>
</Response>"""
        return Response(content=exoml, media_type="application/xml")
    
    call = active_calls[call_id]
    lang = call.get("language", "hi-IN")
    
    print(f"SUCCESS: Using call {call_id}, language={lang}")
    await add_transcript(call_id, "Agent", f"Greeting - {RO_NAMES.get(lang, 'RO')} tomorrow")
    
    exoml = generate_exoml_play_gather(f"{lang}/01_greeting.wav", call_id, "availability")
    call["state"] = CallState.WAIT_AVAILABILITY
    return Response(content=exoml, media_type="application/xml")


@app.api_route("/exotel/callback/{call_id}", methods=["GET", "POST"])
async def exotel_callback(call_id: str, request: Request):
    print(f"=== Per-call callback for {call_id} ===")
    print(f"Method: {request.method}")
    print(f"Query params: {dict(request.query_params)}")
    
    if call_id not in active_calls:
        print(f"Call ID {call_id} not found in active_calls")
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    call = active_calls[call_id]
    lang = call.get("language", "hi-IN")
    
    print(f"Found call, language={lang}")
    await add_transcript(call_id, "Agent", f"Greeting - {RO_NAMES.get(lang, 'RO')} tomorrow")
    
    exoml = generate_exoml_play_gather(f"{lang}/01_greeting.wav", call_id, "availability")
    call["state"] = CallState.WAIT_AVAILABILITY
    print(f"Returning ExoML greeting")
    return Response(content=exoml, media_type="application/xml")

@app.api_route("/exotel/availability/{call_id}", methods=["GET", "POST"])
async def handle_availability(call_id: str, request: Request):
    print(f"=== Availability callback for {call_id} ===")
    
    if call_id not in active_calls and call_id != "default":
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    # Get digits from query params (GET) or form (POST)
    digits = request.query_params.get("digits", "")
    if request.method == "POST":
        form = await request.form()
        digits = digits or form.get("digits", "")
    
    print(f"Digits received: {digits}")
    
    # Handle default case
    if call_id == "default":
        lang = "hi-IN"
        if digits == "1":
            return Response(content=generate_exoml_play_hangup(f"{lang}/02_confirmed.wav"), media_type="application/xml")
        elif digits == "2":
            return Response(content=generate_exoml_play_gather(f"{lang}/03_ask_reason.wav", "default", "reason"), media_type="application/xml")
        else:
            return Response(content=generate_exoml_play_gather(f"{lang}/05_unclear.wav", "default", "availability"), media_type="application/xml")
    
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

@app.api_route("/exotel/reason/{call_id}", methods=["GET", "POST"])
async def handle_reason(call_id: str, request: Request):
    print(f"=== Reason callback for {call_id} ===")
    
    if call_id not in active_calls and call_id != "default":
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    # Get digits from query params (GET) or form (POST)
    digits = request.query_params.get("digits", "")
    if request.method == "POST":
        form = await request.form()
        digits = digits or form.get("digits", "")
    
    # Handle default case
    if call_id == "default":
        return Response(content=generate_exoml_play_hangup("hi-IN/04_reschedule_confirm.wav"), media_type="application/xml")
    
    call = active_calls[call_id]
    lang = call.get("language", "hi-IN")
    
    reason_label, reason_code = DTMF_REASONS.get(digits, ("Other", "OTHER"))
    call["decline_reason"] = reason_code
    
    await add_transcript(call_id, "Borrower", f"Reason: {reason_label}", dtmf=digits, reason=reason_code)
    await add_transcript(call_id, "Agent", "Rescheduled to next week")
    
    call["state"] = CallState.COMPLETED
    call["outcome"] = "RESCHEDULED"
    
    return Response(content=generate_exoml_play_hangup(f"{lang}/04_reschedule_confirm.wav"), media_type="application/xml")

@app.api_route("/exotel/no_input/{call_id}", methods=["GET", "POST"])
async def handle_no_input(call_id: str):
    print(f"=== No input callback for {call_id} ===")
    
    if call_id not in active_calls and call_id != "default":
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    
    if call_id == "default":
        return Response(content=generate_exoml_play_gather("hi-IN/05_unclear.wav", "default", "availability"), media_type="application/xml")
    
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
    <link rel="icon" type="image/png" href="/acquink_logo.png">
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
                <img src="/acquink_logo.png" alt="Acquink" style="height: 40px; width: auto;">
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
                <button onclick="toggleChat()" class="flex items-center gap-2 glass px-4 py-2 rounded-lg text-sm hover:bg-white/5">
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
    
    <!-- SmaartAnalyst Chat Panel -->
    <div id="chatPanel" class="fixed right-0 top-0 h-full w-[420px] glass-dark z-50 flex flex-col transform translate-x-full transition-transform duration-300">
        <div class="flex items-center justify-between p-4 border-b border-white/10">
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 rounded-lg gradient-purple flex items-center justify-center">🤖</div>
                <div>
                    <h3 class="font-semibold text-sm">SmaartAnalyst</h3>
                    <p class="text-xs text-gray-400">Voice Intelligence AI</p>
                </div>
            </div>
            <button onclick="toggleChat()" class="p-2 hover:bg-white/10 rounded-lg">✕</button>
        </div>
        
        <div id="chatMessages" class="flex-1 overflow-y-auto p-4 space-y-4">
            <div class="flex gap-3">
                <div class="w-8 h-8 rounded-lg gradient-purple flex items-center justify-center flex-shrink-0 text-sm">🤖</div>
                <div class="glass rounded-xl p-3 max-w-[85%]">
                    <p class="text-sm">Hello! I'm SmaartAnalyst. Ask me about call patterns, decline reasons, or cluster risks. Try:</p>
                    <ul class="text-sm text-gray-400 mt-2 space-y-1">
                        <li>• Which cluster has highest risk?</li>
                        <li>• Top decline reasons this week?</li>
                        <li>• Who are frequent decliners?</li>
                    </ul>
                </div>
            </div>
        </div>
        
        <div class="p-3 border-t border-white/10">
            <div class="flex gap-2 flex-wrap mb-3">
                <button class="glass text-xs px-3 py-1.5 rounded-full hover:bg-white/10" onclick="askChat('What are the priority actions for today?')">🎯 Today's priorities</button>
                <button class="glass text-xs px-3 py-1.5 rounded-full hover:bg-white/10" onclick="askChat('Which cluster has highest risk?')">🔴 Risky clusters</button>
                <button class="glass text-xs px-3 py-1.5 rounded-full hover:bg-white/10" onclick="askChat('NPA prediction')">📈 NPA outlook</button>
            </div>
            <div class="flex gap-2">
                <input type="text" id="chatInput" placeholder="Ask about call intelligence..." class="flex-1 glass-dark rounded-lg px-4 py-2 text-sm focus:outline-none" onkeypress="if(event.key==='Enter')askChat()">
                <button onclick="askChat()" class="gradient-orange px-4 py-2 rounded-lg text-sm font-medium">Send</button>
            </div>
        </div>
    </div>
    
    <!-- Footer - Matching Smaartbrand Moto -->
    <footer class="mt-auto px-6 py-4 border-t border-white/10">
        <div class="max-w-7xl mx-auto flex items-center justify-between">
            <div class="flex items-center gap-3">
                <img src="/acquink_logo.png" alt="Acquink" style="height: 24px; width: auto;">
                <span class="text-sm text-gray-500">© 2026 Acquink</span>
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
        
        let isCallInProgress = false;
        
        async function makeCall() {
            if (isCallInProgress) {
                console.log('Call already in progress, ignoring');
                return;
            }
            
            const phone = document.getElementById('phone').value;
            if (!phone) { alert('Enter phone number'); return; }
            
            isCallInProgress = true;
            const btn = document.getElementById('callBtn');
            btn.disabled = true;
            btn.textContent = '📞 Calling...';
            btn.style.opacity = '0.5';
            document.getElementById('callStatus').textContent = 'Initiating...';
            document.getElementById('transcript').innerHTML = '<div class="text-center text-gray-500 py-10">Connecting...</div>';
            
            try {
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
            } catch (err) {
                document.getElementById('callStatus').textContent = `Error: ${err.message}`;
            }
            
            // Re-enable after 3 seconds to prevent rapid re-clicks
            setTimeout(() => {
                isCallInProgress = false;
                btn.disabled = false;
                btn.textContent = '📞 Call Now';
                btn.style.opacity = '1';
            }, 3000);
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
        
        // Chat toggle
        function toggleChat() {
            const panel = document.getElementById('chatPanel');
            const isOpening = panel.classList.contains('translate-x-full');
            panel.classList.toggle('translate-x-full');
            
            // Load intel data when opening chat
            if (isOpening && !intelData) {
                loadIntelligence();
            }
        }
        
        // Chat response (mock AI)
        function askChat(question) {
            const input = document.getElementById('chatInput');
            const q = question || input.value.trim();
            if (!q) return;
            input.value = '';
            
            const box = document.getElementById('chatMessages');
            
            // Add user message
            box.innerHTML += `
                <div class="flex gap-3 justify-end">
                    <div class="glass rounded-xl p-3 max-w-[85%] bg-orange-500/20">
                        <p class="text-sm">${q}</p>
                    </div>
                </div>
            `;
            
            // Generate response based on question
            let response = '';
            const ql = q.toLowerCase();
            
            if (!intelData) {
                response = 'Loading intelligence data... Please try again in a moment.';
            } else if (ql.includes('cluster') || ql.includes('risk') || ql.includes('village')) {
                const highRisk = Object.entries(intelData.clusters).filter(([k,v]) => v.alert === 'HIGH');
                const medRisk = Object.entries(intelData.clusters).filter(([k,v]) => v.alert === 'MEDIUM');
                response = `<strong>🔴 High Risk Clusters (${highRisk.length}):</strong><br>` + 
                    highRisk.map(([name, c]) => `• <strong>${name}</strong>: ${c.financial_stress} financial stress cases`).join('<br>') +
                    `<br><br><strong>🟡 Medium Risk (${medRisk.length}):</strong><br>` +
                    medRisk.map(([name, c]) => `• ${name}: ${c.frequent} frequent decliners`).join('<br>') +
                    `<br><br><strong>📋 Action Plan:</strong><br>` +
                    `• <em>Field Ops:</em> Deploy senior ROs to Warangal Rural immediately<br>` +
                    `• <em>Collections:</em> Prioritize 23 financial stress cases for restructuring discussion<br>` +
                    `• <em>Risk:</em> Flag these clusters for weekly monitoring`;
            } else if (ql.includes('decline') || ql.includes('reason')) {
                const reasons = Object.entries(intelData.decline_reasons).sort((a,b) => b[1] - a[1]);
                response = `<strong>📊 Decline Reason Analysis:</strong><br>` + 
                    reasons.map(([r, count]) => `• ${r.replace(/_/g, ' ')}: <strong>${count}</strong> (${Math.round(count/1247*100)}%)`).join('<br>') +
                    `<br><br><strong>📋 Department Actions:</strong><br>` +
                    `• <em>Collections:</em> Financial stress (312 cases) — initiate early restructuring conversations<br>` +
                    `• <em>Field Ops:</em> Travel/Market conflicts — adjust visit timing to evenings<br>` +
                    `• <em>Product:</em> Consider flexible payment dates for agricultural borrowers`;
            } else if (ql.includes('frequent') || ql.includes('decliner')) {
                const top = intelData.frequent_decliners.slice(0, 5);
                response = `<strong>🚨 Frequent Decliners (Top 5):</strong><br>` + 
                    top.map((b,i) => `${i+1}. <strong>${b.id}</strong> — ${b.decline_count}x declined, Risk Score: <span class="${b.risk_score >= 60 ? 'text-red-400' : 'text-yellow-400'}">${b.risk_score}</span><br>&nbsp;&nbsp;&nbsp;Cluster: ${b.cluster} | Reasons: ${b.decline_reasons.join(', ')}`).join('<br>') +
                    `<br><br><strong>📋 Recommended Actions:</strong><br>` +
                    `• <em>Relationship Manager:</em> Personal call to top 5 — understand root cause<br>` +
                    `• <em>Collections:</em> Offer EMI restructuring for financial stress cases<br>` +
                    `• <em>Risk:</em> Add to watchlist for 60-day NPA prediction`;
            } else if (ql.includes('npa') || ql.includes('predict') || ql.includes('portfolio')) {
                response = `<strong>📈 NPA Prediction (60-Day Outlook):</strong><br>` +
                    `• Current NPA: <strong>${intelData.npa.current}%</strong><br>` +
                    `• Predicted NPA: <strong class="text-red-400">${intelData.npa.predicted}%</strong> (+0.6%)<br>` +
                    `• At-Risk Amount: <strong>₹${intelData.npa.at_risk}</strong><br>` +
                    `• Saveable with intervention: <strong class="text-green-400">₹${intelData.npa.savings}</strong><br><br>` +
                    `<strong>📋 Department Priorities:</strong><br>` +
                    `• <em>CEO/CCO:</em> 154 borrowers in early warning — authorize early intervention budget<br>` +
                    `• <em>Collections Head:</em> Focus on 47 frequent decliners with financial stress<br>` +
                    `• <em>Field Ops:</em> Warangal and Karimnagar need additional RO support<br>` +
                    `• <em>Risk:</em> Weekly tracking of predicted-to-actual NPA conversion`;
            } else if (ql.includes('ro') || ql.includes('centre') || ql.includes('center') || ql.includes('affected') || ql.includes('branch') || ql.includes('shad') || ql.includes('warangal') || ql.includes('karimnagar') || ql.includes('nizamabad') || ql.includes('medak')) {
                // Check if asking about specific centre
                let specificCentre = null;
                const centreNames = Object.keys(intelData.clusters);
                for (const name of centreNames) {
                    if (ql.includes(name.toLowerCase().split(' ')[0])) {
                        specificCentre = [name, intelData.clusters[name]];
                        break;
                    }
                }
                
                if (specificCentre) {
                    const [name, c] = specificCentre;
                    const alertColor = c.alert === 'HIGH' ? 'text-red-400' : c.alert === 'MEDIUM' ? 'text-yellow-400' : 'text-green-400';
                    response = `<strong>🏢 ${name} Centre Insights:</strong><br><br>` +
                        `<strong>Status:</strong> <span class="${alertColor}">${c.alert} ALERT</span><br>` +
                        `<strong>State:</strong> ${c.state}<br>` +
                        `<strong>Total Borrowers:</strong> ${c.total}<br>` +
                        `<strong>Average Risk Score:</strong> ${c.avg_risk}<br>` +
                        `<strong>Frequent Decliners:</strong> ${c.frequent}<br>` +
                        `<strong>Financial Stress Cases:</strong> ${c.financial_stress}<br><br>` +
                        `<strong>📊 Key Patterns:</strong><br>` +
                        `• Peak decline reason: Financial stress (${Math.round(c.financial_stress/c.total*100)}%)<br>` +
                        `• ${c.frequent} borrowers declined 3+ times<br>` +
                        `• Avg collection efficiency: ${100 - c.avg_risk}%<br><br>` +
                        `<strong>📋 Actions for ${name}:</strong><br>` +
                        `• <em>Branch Manager:</em> Personal review of top 5 decliners this week<br>` +
                        `• <em>Collections:</em> Restructuring offers for ${c.financial_stress} financial stress cases<br>` +
                        `• <em>Field Ops:</em> ${c.alert === 'HIGH' ? 'Deploy senior RO for support' : 'Continue normal monitoring'}<br>` +
                        `• <em>Risk:</em> ${c.alert === 'HIGH' ? 'Weekly review' : 'Monthly review'} of this portfolio`;
                } else {
                    const sorted = Object.entries(intelData.clusters).sort((a,b) => b[1].avg_risk - a[1].avg_risk);
                    const worst = sorted[0];
                    const best = sorted[sorted.length-1];
                    response = `<strong>🏢 Centre Performance Analysis:</strong><br><br>` +
                        `<strong class="text-red-400">⬇️ Needs Attention:</strong><br>` +
                        `• <strong>${worst[0]}</strong> (${worst[1].state})<br>` +
                        `&nbsp;&nbsp;Risk: ${worst[1].avg_risk} | Decliners: ${worst[1].frequent} | Stress: ${worst[1].financial_stress}<br><br>` +
                        `<strong class="text-green-400">⬆️ Top Performer:</strong><br>` +
                        `• <strong>${best[0]}</strong> (${best[1].state})<br>` +
                        `&nbsp;&nbsp;Risk: ${best[1].avg_risk} | Decliners: ${best[1].frequent}<br><br>` +
                        `<strong>💡 Ask about specific centre:</strong><br>` +
                        `• "Shad Nagar centre insights"<br>` +
                        `• "Warangal Rural performance"<br>` +
                        `• "Karimnagar analysis"`;
                }
            } else if (ql.includes('action') || ql.includes('what should') || ql.includes('recommend') || ql.includes('priority')) {
                response = `<strong>🎯 Today's Priority Actions by Department:</strong><br><br>` +
                    `<strong>Collections Team:</strong><br>` +
                    `• Call 47 frequent decliners with financial stress today<br>` +
                    `• Prepare restructuring options for 23 high-risk cases<br><br>` +
                    `<strong>Field Operations:</strong><br>` +
                    `• Deploy backup RO to Warangal Rural (HIGH alert)<br>` +
                    `• Shift visit timing to evenings for market traders<br><br>` +
                    `<strong>Risk Management:</strong><br>` +
                    `• Update watchlist with 154 early warning borrowers<br>` +
                    `• Prepare weekly NPA projection report for CCO<br><br>` +
                    `<strong>Branch Managers:</strong><br>` +
                    `• Karimnagar: Review 8 consecutive decliners<br>` +
                    `• Nizamabad: Coordinate with agriculture extension for crop-related declines`;
            } else if (ql.includes('persona') || ql.includes('borrower') || ql.includes('type') || ql.includes('segment')) {
                response = `<strong>👥 Borrower Persona Analysis:</strong><br><br>` +
                    `• 👨‍🌾 <strong>Farmers (38%)</strong> — Crop cycle dependent, seasonal income<br>` +
                    `• 🏪 <strong>Traders (24%)</strong> — Market day conflicts, cash flow issues<br>` +
                    `• 💼 <strong>Salaried (18%)</strong> — Most reliable, work schedule conflicts<br>` +
                    `• 🔧 <strong>Self-Employed (12%)</strong> — Variable income, financial stress common<br>` +
                    `• 🏗️ <strong>Daily Wage (8%)</strong> — Highest risk, irregular availability<br><br>` +
                    `<strong>📋 Segment-Specific Actions:</strong><br>` +
                    `• <em>Farmers:</em> Align collection calls with harvest cycles<br>` +
                    `• <em>Traders:</em> Avoid market days (Mon/Thu in most areas)<br>` +
                    `• <em>Daily Wage:</em> Morning calls before they leave for work`;
            } else {
                response = `<strong>🤖 SmaartAnalyst — Voice Intelligence</strong><br><br>` +
                    `I can help you with:<br>` +
                    `• 📊 <em>"Decline reasons"</em> — Why are borrowers declining?<br>` +
                    `• 🔴 <em>"Cluster risk"</em> — Which villages need attention?<br>` +
                    `• 🚨 <em>"Frequent decliners"</em> — Who keeps declining?<br>` +
                    `• 📈 <em>"NPA prediction"</em> — Portfolio outlook<br>` +
                    `• 🏢 <em>"Centre performance"</em> — Branch analysis<br>` +
                    `• 🎯 <em>"Priority actions"</em> — What should each team do today?<br>` +
                    `• 👥 <em>"Borrower personas"</em> — Segment analysis<br><br>` +
                    `Try: <em>"What are the priority actions for today?"</em>`;
            }
            
            // Add AI response
            setTimeout(() => {
                box.innerHTML += `
                    <div class="flex gap-3">
                        <div class="w-8 h-8 rounded-lg gradient-purple flex items-center justify-center flex-shrink-0 text-sm">🤖</div>
                        <div class="glass rounded-xl p-3 max-w-[85%]">
                            <p class="text-sm">${response}</p>
                        </div>
                    </div>
                `;
                box.scrollTop = box.scrollHeight;
            }, 500);
            
            box.scrollTop = box.scrollHeight;
        }
        
        connectWS();
        loadConfig();
        loadIntelligence(); // Preload for chat
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
