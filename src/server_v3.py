"""
Fusion Finance Voice POC v3 - Intelligence Layer Demo

What Gnani does: Voice calls, multi-language, basic collection reminders
What Acquink adds: Intelligence extraction from voice data

Key differentiators demonstrated:
1. Structured decline reason taxonomy (not free text)
2. Real-time English transcript with intent tags
3. Borrower persona classification
4. Frequent decliner identification
5. Cluster/village level risk signals
6. Mock intelligence dashboard showing what 1000 calls reveal

This POC proves: The call is the data collection mechanism. 
The value is the intelligence layer on top.
"""

import os
import json
import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# ============================================================================
# Configuration & Enums
# ============================================================================

class Language(str, Enum):
    HINDI = "hi-IN"
    TELUGU = "te-IN"
    TAMIL = "ta-IN"
    KANNADA = "kn-IN"
    MARATHI = "mr-IN"
    ENGLISH = "en-IN"

LANGUAGE_NAMES = {
    Language.HINDI: ("Hindi", "हिंदी"),
    Language.TELUGU: ("Telugu", "తెలుగు"),
    Language.TAMIL: ("Tamil", "தமிழ்"),
    Language.KANNADA: ("Kannada", "ಕನ್ನಡ"),
    Language.MARATHI: ("Marathi", "मराठी"),
    Language.ENGLISH: ("English", "English"),
}


class Intent(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNCLEAR = "UNCLEAR"


class DeclineReason(str, Enum):
    TRAVEL_MARKET = "TRAVEL_MARKET"
    HEALTH = "HEALTH"
    FINANCIAL_STRESS = "FINANCIAL_STRESS"
    WORK_CONFLICT = "WORK_CONFLICT"
    FAMILY_EVENT = "FAMILY_EVENT"
    CROP_AGRICULTURE = "CROP_AGRICULTURE"
    OTHER = "OTHER"


# Decline reason display info
DECLINE_REASON_INFO = {
    DeclineReason.TRAVEL_MARKET: {
        "label": "Travel / Market",
        "icon": "🚗",
        "risk_weight": 0.2,  # Low risk - legitimate reason
        "description": "Borrower traveling or at market"
    },
    DeclineReason.HEALTH: {
        "label": "Health Issue", 
        "icon": "🏥",
        "risk_weight": 0.3,
        "description": "Borrower or family health issue"
    },
    DeclineReason.FINANCIAL_STRESS: {
        "label": "Financial Stress",
        "icon": "💰",
        "risk_weight": 0.9,  # High risk signal
        "description": "Payment difficulty, salary delay"
    },
    DeclineReason.WORK_CONFLICT: {
        "label": "Work Conflict",
        "icon": "💼",
        "risk_weight": 0.2,
        "description": "Office, shop, work commitment"
    },
    DeclineReason.FAMILY_EVENT: {
        "label": "Family Event",
        "icon": "👨‍👩‍👧",
        "risk_weight": 0.3,
        "description": "Wedding, ceremony, family matter"
    },
    DeclineReason.CROP_AGRICULTURE: {
        "label": "Crop / Agriculture",
        "icon": "🌾",
        "risk_weight": 0.6,  # Medium-high - could indicate crop failure
        "description": "Farming, harvest, agricultural work"
    },
    DeclineReason.OTHER: {
        "label": "Other",
        "icon": "❓",
        "risk_weight": 0.5,
        "description": "Unclassified reason"
    },
}


class BorrowerPersona(str, Enum):
    FARMER = "FARMER"
    TRADER = "TRADER"
    SALARIED = "SALARIED"
    SELF_EMPLOYED = "SELF_EMPLOYED"
    DAILY_WAGE = "DAILY_WAGE"


PERSONA_INFO = {
    BorrowerPersona.FARMER: {"label": "Farmer", "icon": "👨‍🌾", "color": "#22c55e"},
    BorrowerPersona.TRADER: {"label": "Trader", "icon": "🏪", "color": "#3b82f6"},
    BorrowerPersona.SALARIED: {"label": "Salaried", "icon": "💼", "color": "#8b5cf6"},
    BorrowerPersona.SELF_EMPLOYED: {"label": "Self Employed", "icon": "🔧", "color": "#f59e0b"},
    BorrowerPersona.DAILY_WAGE: {"label": "Daily Wage", "icon": "🏗️", "color": "#ef4444"},
}


# ============================================================================
# Multi-Language Responses with DTMF
# ============================================================================

RESPONSES = {
    "GREETING": {
        Language.HINDI: (
            "नमस्ते, फ्यूजन फाइनेंस से बोल रहे हैं। कल {ro_name} जी आपके पास लोन कलेक्शन के लिए आएंगे। क्या आप उपलब्ध रहेंगे? हां के लिए 1 दबाएं, नहीं के लिए 2 दबाएं।",
            "Hello from Fusion Finance. {ro_name} will visit you tomorrow for loan collection. Will you be available? Press 1 for Yes, Press 2 for No."
        ),
        Language.TELUGU: (
            "నమస్కారం, ఫ్యూజన్ ఫైనాన్స్ నుండి మాట్లాడుతున్నాము. రేపు {ro_name} గారు లోన్ కలెక్షన్ కోసం వస్తారు. మీరు అందుబాటులో ఉంటారా? అవును కోసం 1 నొక్కండి, కాదు కోసం 2 నొక్కండి.",
            "Hello from Fusion Finance. {ro_name} will visit you tomorrow for loan collection. Will you be available? Press 1 for Yes, Press 2 for No."
        ),
        Language.TAMIL: (
            "வணக்கம், ஃப்யூஷன் ஃபைனான்ஸிலிருந்து பேசுகிறோம். நாளை {ro_name} கடன் வசூலுக்கு வருவார். நீங்கள் இருப்பீர்களா? ஆம் என்றால் 1 அழுத்தவும், இல்லை என்றால் 2 அழுத்தவும்.",
            "Hello from Fusion Finance. {ro_name} will visit you tomorrow for loan collection. Will you be available? Press 1 for Yes, Press 2 for No."
        ),
        Language.KANNADA: (
            "ನಮಸ್ಕಾರ, ಫ್ಯೂಷನ್ ಫೈನಾನ್ಸ್ ನಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇವೆ. ನಾಳೆ {ro_name} ಅವರು ಸಾಲ ಸಂಗ್ರಹಕ್ಕಾಗಿ ಬರುತ್ತಾರೆ. ನೀವು ಲಭ್ಯವಿರುತ್ತೀರಾ? ಹೌದು ಗಾಗಿ 1 ಒತ್ತಿ, ಇಲ್ಲ ಗಾಗಿ 2 ಒತ್ತಿ.",
            "Hello from Fusion Finance. {ro_name} will visit you tomorrow for loan collection. Will you be available? Press 1 for Yes, Press 2 for No."
        ),
        Language.MARATHI: (
            "नमस्कार, फ्यूजन फायनान्स मधून बोलत आहोत. उद्या {ro_name} लोन कलेक्शनसाठी येतील. तुम्ही उपलब्ध असाल का? हो साठी 1 दाबा, नाही साठी 2 दाबा.",
            "Hello from Fusion Finance. {ro_name} will visit you tomorrow for loan collection. Will you be available? Press 1 for Yes, Press 2 for No."
        ),
        Language.ENGLISH: (
            "Hello from Fusion Finance. {ro_name} will visit you tomorrow for loan collection. Will you be available? Press 1 for Yes, Press 2 for No.",
            "Hello from Fusion Finance. {ro_name} will visit you tomorrow for loan collection. Will you be available? Press 1 for Yes, Press 2 for No."
        ),
    },
    "CONFIRMED": {
        Language.HINDI: (
            "बहुत अच्छा। कल {ro_name} जी आएंगे। धन्यवाद, शुभ दिन।",
            "Great. {ro_name} will visit tomorrow. Thank you, have a good day."
        ),
        Language.TELUGU: (
            "చాలా బాగుంది. రేపు {ro_name} గారు వస్తారు. ధన్యవాదాలు.",
            "Great. {ro_name} will visit tomorrow. Thank you."
        ),
        Language.TAMIL: (
            "மிக நல்லது. நாளை {ro_name} வருவார். நன்றி.",
            "Great. {ro_name} will visit tomorrow. Thank you."
        ),
        Language.KANNADA: (
            "ತುಂಬಾ ಒಳ್ಳೆಯದು. ನಾಳೆ {ro_name} ಬರುತ್ತಾರೆ. ಧನ್ಯವಾದಗಳು.",
            "Great. {ro_name} will visit tomorrow. Thank you."
        ),
        Language.MARATHI: (
            "खूप छान. उद्या {ro_name} येतील. धन्यवाद.",
            "Great. {ro_name} will visit tomorrow. Thank you."
        ),
        Language.ENGLISH: (
            "Great. {ro_name} will visit tomorrow. Thank you, have a good day.",
            "Great. {ro_name} will visit tomorrow. Thank you, have a good day."
        ),
    },
    "ASK_REASON": {
        Language.HINDI: (
            "कोई बात नहीं। कृपया कारण बताएं। यात्रा या बाजार के लिए 1 दबाएं। तबीयत ठीक नहीं के लिए 2 दबाएं। पैसों की दिक्कत के लिए 3 दबाएं। काम या ऑफिस के लिए 4 दबाएं। घर में शादी या फंक्शन के लिए 5 दबाएं। खेती या फसल के लिए 6 दबाएं।",
            "No problem. Please tell the reason. Press 1 for Travel/Market. Press 2 for Health issue. Press 3 for Financial difficulty. Press 4 for Work/Office. Press 5 for Family event. Press 6 for Farming/Crop."
        ),
        Language.TELUGU: (
            "పర్వాలేదు. దయచేసి కారణం చెప్పండి. ప్రయాణం లేదా మార్కెట్ కోసం 1 నొక్కండి. ఆరోగ్య సమస్య కోసం 2 నొక్కండి. ఆర్థిక ఇబ్బంది కోసం 3 నొక్కండి. పని కోసం 4 నొక్కండి. కుటుంబ కార్యక్రమం కోసం 5 నొక్కండి. వ్యవసాయం కోసం 6 నొక్కండి.",
            "No problem. Please tell the reason. Press 1 for Travel/Market. Press 2 for Health issue. Press 3 for Financial difficulty. Press 4 for Work/Office. Press 5 for Family event. Press 6 for Farming/Crop."
        ),
        Language.TAMIL: (
            "பரவாயில்லை. தயவுசெய்து காரணம் சொல்லுங்கள். பயணம் அல்லது சந்தைக்கு 1 அழுத்தவும். உடல்நலம் சரியில்லை என்றால் 2 அழுத்தவும். பண சிக்கல் என்றால் 3 அழுத்தவும். வேலை என்றால் 4 அழுத்தவும். குடும்ப நிகழ்வு என்றால் 5 அழுத்தவும். விவசாயம் என்றால் 6 அழுத்தவும்.",
            "No problem. Please tell the reason. Press 1 for Travel/Market. Press 2 for Health issue. Press 3 for Financial difficulty. Press 4 for Work/Office. Press 5 for Family event. Press 6 for Farming/Crop."
        ),
        Language.KANNADA: (
            "ಪರವಾಗಿಲ್ಲ. ದಯವಿಟ್ಟು ಕಾರಣ ಹೇಳಿ. ಪ್ರಯಾಣ ಅಥವಾ ಮಾರುಕಟ್ಟೆಗೆ 1 ಒತ್ತಿ. ಆರೋಗ್ಯ ಸಮಸ್ಯೆಗೆ 2 ಒತ್ತಿ. ಹಣಕಾಸು ತೊಂದರೆಗೆ 3 ಒತ್ತಿ. ಕೆಲಸಕ್ಕೆ 4 ಒತ್ತಿ. ಕುಟುಂಬ ಕಾರ್ಯಕ್ರಮಕ್ಕೆ 5 ಒತ್ತಿ. ಕೃಷಿಗೆ 6 ಒತ್ತಿ.",
            "No problem. Please tell the reason. Press 1 for Travel/Market. Press 2 for Health issue. Press 3 for Financial difficulty. Press 4 for Work/Office. Press 5 for Family event. Press 6 for Farming/Crop."
        ),
        Language.MARATHI: (
            "काही हरकत नाही. कृपया कारण सांगा. प्रवास किंवा बाजारासाठी 1 दाबा. आरोग्य समस्येसाठी 2 दाबा. पैशाच्या अडचणीसाठी 3 दाबा. कामासाठी 4 दाबा. कौटुंबिक कार्यक्रमासाठी 5 दाबा. शेतीसाठी 6 दाबा.",
            "No problem. Please tell the reason. Press 1 for Travel/Market. Press 2 for Health issue. Press 3 for Financial difficulty. Press 4 for Work/Office. Press 5 for Family event. Press 6 for Farming/Crop."
        ),
        Language.ENGLISH: (
            "No problem. Please tell the reason. Press 1 for Travel or Market. Press 2 for Health issue. Press 3 for Financial difficulty. Press 4 for Work or Office. Press 5 for Family event. Press 6 for Farming or Crop.",
            "No problem. Please tell the reason. Press 1 for Travel/Market. Press 2 for Health issue. Press 3 for Financial difficulty. Press 4 for Work/Office. Press 5 for Family event. Press 6 for Farming/Crop."
        ),
    },
    "RESCHEDULE_CONFIRM": {
        Language.HINDI: (
            "समझ गया। {ro_name} जी की विजिट {new_date} को reschedule कर दी है। धन्यवाद।",
            "Understood. {ro_name}'s visit has been rescheduled to {new_date}. Thank you."
        ),
        Language.TELUGU: (
            "అర్థమైంది. {ro_name} గారి సందర్శన {new_date} కి మార్చబడింది. ధన్యవాదాలు.",
            "Understood. {ro_name}'s visit has been rescheduled to {new_date}. Thank you."
        ),
        Language.TAMIL: (
            "புரிந்தது. {ro_name} வருகை {new_date} க்கு மாற்றப்பட்டது. நன்றி.",
            "Understood. {ro_name}'s visit has been rescheduled to {new_date}. Thank you."
        ),
        Language.KANNADA: (
            "ಅರ್ಥವಾಯಿತು. {ro_name} ಅವರ ಭೇಟಿ {new_date} ಕ್ಕೆ ಮರುನಿಗದಿಯಾಗಿದೆ. ಧನ್ಯವಾದಗಳು.",
            "Understood. {ro_name}'s visit has been rescheduled to {new_date}. Thank you."
        ),
        Language.MARATHI: (
            "समजले. {ro_name} यांची भेट {new_date} ला पुन्हा शेड्यूल केली आहे. धन्यवाद.",
            "Understood. {ro_name}'s visit has been rescheduled to {new_date}. Thank you."
        ),
        Language.ENGLISH: (
            "Understood. {ro_name}'s visit has been rescheduled to {new_date}. Thank you.",
            "Understood. {ro_name}'s visit has been rescheduled to {new_date}. Thank you."
        ),
    },
}

# DTMF to Decline Reason mapping
DTMF_TO_REASON = {
    "1": DeclineReason.TRAVEL_MARKET,
    "2": DeclineReason.HEALTH,
    "3": DeclineReason.FINANCIAL_STRESS,
    "4": DeclineReason.WORK_CONFLICT,
    "5": DeclineReason.FAMILY_EVENT,
    "6": DeclineReason.CROP_AGRICULTURE,
}


# ============================================================================
# Mock Data Generator - Simulates 1000 calls for Intelligence Demo
# ============================================================================

def generate_mock_intelligence_data():
    """
    Generate realistic mock data showing what 1000 calls would reveal.
    This demonstrates the intelligence layer that Acquink builds.
    """
    
    # Clusters/Villages
    clusters = [
        {"name": "Warangal Rural", "state": "Telangana", "branches": 12},
        {"name": "Guntur District", "state": "Andhra Pradesh", "branches": 8},
        {"name": "Dharwad", "state": "Karnataka", "branches": 6},
        {"name": "Salem", "state": "Tamil Nadu", "branches": 10},
        {"name": "Nashik Rural", "state": "Maharashtra", "branches": 9},
    ]
    
    # Generate borrower data
    borrowers = []
    for i in range(500):
        cluster = random.choice(clusters)
        persona = random.choices(
            list(BorrowerPersona),
            weights=[35, 20, 15, 20, 10]  # Farmer heavy in rural
        )[0]
        
        # Behavior patterns
        is_frequent_decliner = random.random() < 0.12  # 12% are frequent decliners
        
        decline_reasons_history = []
        if is_frequent_decliner:
            # Frequent decliners have pattern
            primary_reason = random.choices(
                list(DeclineReason),
                weights=[15, 10, 40, 10, 10, 15, 0]  # Financial stress dominant
            )[0]
            for _ in range(random.randint(3, 6)):
                decline_reasons_history.append(primary_reason)
        else:
            # Normal borrowers - occasional declines
            for _ in range(random.randint(0, 2)):
                decline_reasons_history.append(random.choice(list(DeclineReason)))
        
        borrowers.append({
            "id": f"BRW{10000 + i}",
            "name": f"Borrower {i+1}",
            "cluster": cluster["name"],
            "state": cluster["state"],
            "persona": persona,
            "loan_amount": random.randint(20000, 80000),
            "decline_count": len(decline_reasons_history),
            "decline_reasons": decline_reasons_history,
            "is_frequent_decliner": is_frequent_decliner,
            "risk_score": min(100, len(decline_reasons_history) * 15 + 
                            (40 if DeclineReason.FINANCIAL_STRESS in decline_reasons_history else 0)),
            "call_response_rate": random.uniform(0.6, 0.95) if not is_frequent_decliner else random.uniform(0.3, 0.6),
        })
    
    # Aggregate statistics
    total_calls = 1247
    connected_calls = 1089
    confirmed_available = 734
    declined = 355
    
    # Decline reason distribution
    reason_counts = defaultdict(int)
    for b in borrowers:
        for r in b["decline_reasons"]:
            reason_counts[r] += 1
    
    # Cluster risk scores
    cluster_stats = {}
    for cluster in clusters:
        cluster_borrowers = [b for b in borrowers if b["cluster"] == cluster["name"]]
        avg_risk = sum(b["risk_score"] for b in cluster_borrowers) / len(cluster_borrowers) if cluster_borrowers else 0
        frequent_decliners = len([b for b in cluster_borrowers if b["is_frequent_decliner"]])
        financial_stress_count = len([b for b in cluster_borrowers if DeclineReason.FINANCIAL_STRESS in b["decline_reasons"]])
        
        cluster_stats[cluster["name"]] = {
            "state": cluster["state"],
            "total_borrowers": len(cluster_borrowers),
            "avg_risk_score": round(avg_risk, 1),
            "frequent_decliners": frequent_decliners,
            "financial_stress_signals": financial_stress_count,
            "alert_level": "HIGH" if avg_risk > 40 or financial_stress_count > 10 else ("MEDIUM" if avg_risk > 25 else "LOW"),
        }
    
    # Persona distribution
    persona_counts = defaultdict(int)
    for b in borrowers:
        persona_counts[b["persona"]] += 1
    
    # Frequent decliners list
    frequent_decliners = [b for b in borrowers if b["is_frequent_decliner"]]
    frequent_decliners.sort(key=lambda x: x["risk_score"], reverse=True)
    
    return {
        "summary": {
            "total_calls": total_calls,
            "connected": connected_calls,
            "connection_rate": round(connected_calls / total_calls * 100, 1),
            "confirmed_available": confirmed_available,
            "confirmation_rate": round(confirmed_available / connected_calls * 100, 1),
            "declined": declined,
            "decline_rate": round(declined / connected_calls * 100, 1),
            "avg_call_duration_sec": 127,
            "total_borrowers_profiled": len(borrowers),
        },
        "decline_reasons": {
            r.value: {
                "count": reason_counts.get(r, 0),
                "percentage": round(reason_counts.get(r, 0) / sum(reason_counts.values()) * 100, 1) if reason_counts else 0,
                "info": DECLINE_REASON_INFO[r],
            }
            for r in DeclineReason
        },
        "clusters": cluster_stats,
        "personas": {
            p.value: {
                "count": persona_counts.get(p, 0),
                "percentage": round(persona_counts.get(p, 0) / len(borrowers) * 100, 1),
                "info": PERSONA_INFO[p],
            }
            for p in BorrowerPersona
        },
        "frequent_decliners": {
            "count": len(frequent_decliners),
            "percentage": round(len(frequent_decliners) / len(borrowers) * 100, 1),
            "top_10": [
                {
                    "id": b["id"],
                    "cluster": b["cluster"],
                    "persona": b["persona"].value,
                    "decline_count": b["decline_count"],
                    "primary_reason": max(set(b["decline_reasons"]), key=b["decline_reasons"].count).value if b["decline_reasons"] else None,
                    "risk_score": b["risk_score"],
                    "loan_amount": b["loan_amount"],
                }
                for b in frequent_decliners[:10]
            ],
        },
        "early_warnings": [
            {
                "type": "CLUSTER_STRESS",
                "cluster": "Warangal Rural",
                "message": "23% increase in financial stress declines over last 2 weeks",
                "risk_level": "HIGH",
                "recommended_action": "Branch manager intervention recommended",
            },
            {
                "type": "CROP_FAILURE_SIGNAL",
                "cluster": "Nashik Rural", 
                "message": "Spike in crop/agriculture decline reasons - possible harvest delay",
                "risk_level": "MEDIUM",
                "recommended_action": "Monitor payment patterns next cycle",
            },
            {
                "type": "FREQUENT_DECLINER",
                "cluster": "Guntur District",
                "message": "8 new frequent decliners identified this month",
                "risk_level": "MEDIUM",
                "recommended_action": "Schedule branch-level review",
            },
        ],
        "npa_prediction": {
            "current_npa_rate": 2.8,
            "predicted_60_day": 3.4,
            "at_risk_portfolio": "₹4.2 Cr",
            "early_intervention_savings": "₹1.8 Cr",
        },
    }


# ============================================================================
# Session Management
# ============================================================================

@dataclass
class TranscriptEntry:
    timestamp: str
    speaker: str
    original_text: str
    english_text: str
    intent: Optional[str] = None
    decline_reason: Optional[str] = None
    dtmf: Optional[str] = None
    latency_ms: Optional[int] = None


@dataclass 
class CallSession:
    call_id: str
    borrower_name: str = "Borrower"
    borrower_phone: str = ""
    ro_name: str = "RO"
    language: Language = Language.HINDI
    state: str = "GREETING"
    transcript: list = field(default_factory=list)
    decline_reason: Optional[DeclineReason] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


sessions: Dict[str, CallSession] = {}
ui_connections: List[WebSocket] = []

# Pre-generate intelligence data
intelligence_data = generate_mock_intelligence_data()


async def broadcast_transcript(entry: TranscriptEntry):
    message = {
        "type": "transcript",
        "data": {
            "timestamp": entry.timestamp,
            "speaker": entry.speaker,
            "original": entry.original_text,
            "english": entry.english_text,
            "intent": entry.intent,
            "decline_reason": entry.decline_reason,
            "dtmf": entry.dtmf,
            "latency_ms": entry.latency_ms,
        }
    }
    
    dead = []
    for ws in ui_connections:
        try:
            await ws.send_json(message)
        except:
            dead.append(ws)
    for ws in dead:
        ui_connections.remove(ws)


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(title="Fusion Finance Voice POC v3 - Intelligence Layer")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Main UI with both call demo and intelligence dashboard"""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Acquink Voice Intelligence | Fusion Finance POC</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0f1a; 
            color: #e2e8f0;
            min-height: 100vh;
        }
        
        .header {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            padding: 20px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #334155;
        }
        .logo { 
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .logo-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, #f97316, #ea580c);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
        }
        .logo-text {
            font-size: 22px;
            font-weight: 700;
        }
        .logo-text span { color: #f97316; }
        
        .tabs {
            display: flex;
            gap: 8px;
        }
        .tab {
            padding: 10px 24px;
            border: none;
            border-radius: 8px;
            background: transparent;
            color: #94a3b8;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }
        .tab:hover { background: rgba(255,255,255,0.05); }
        .tab.active { 
            background: #f97316;
            color: white;
        }
        
        .container { max-width: 1400px; margin: 0 auto; padding: 30px; }
        
        .page { display: none; }
        .page.active { display: block; }
        
        /* Call Demo Styles */
        .demo-grid {
            display: grid;
            grid-template-columns: 1fr 1.5fr;
            gap: 24px;
        }
        
        .card {
            background: #1e293b;
            border-radius: 16px;
            padding: 24px;
            border: 1px solid #334155;
        }
        .card h3 {
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #64748b;
            margin-bottom: 20px;
        }
        
        .form-group { margin-bottom: 16px; }
        .form-group label {
            display: block;
            font-size: 12px;
            color: #94a3b8;
            margin-bottom: 6px;
        }
        input, select {
            width: 100%;
            padding: 12px 14px;
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
        
        .language-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .lang-pill {
            padding: 8px 14px;
            border: 2px solid #334155;
            border-radius: 20px;
            background: transparent;
            color: #94a3b8;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .lang-pill:hover { border-color: #f97316; }
        .lang-pill.active {
            border-color: #f97316;
            background: rgba(249,115,22,0.15);
            color: #f97316;
        }
        
        .btn-primary {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #f97316, #ea580c);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(249,115,22,0.3);
        }
        .btn-primary:disabled {
            background: #475569;
            transform: none;
            box-shadow: none;
            cursor: not-allowed;
        }
        
        .transcript-box {
            height: 450px;
            overflow-y: auto;
            padding-right: 8px;
        }
        .transcript-box::-webkit-scrollbar { width: 6px; }
        .transcript-box::-webkit-scrollbar-track { background: #0f172a; border-radius: 3px; }
        .transcript-box::-webkit-scrollbar-thumb { background: #475569; border-radius: 3px; }
        
        .message {
            margin-bottom: 16px;
            padding: 14px;
            border-radius: 10px;
            animation: slideIn 0.3s ease;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-10px); }
            to { opacity: 1; transform: translateX(0); }
        }
        .message.agent { 
            background: linear-gradient(135deg, #1e3a5f 0%, #172554 100%);
            border-left: 3px solid #3b82f6;
        }
        .message.borrower { 
            background: linear-gradient(135deg, #134e4a 0%, #0f3d3a 100%);
            border-left: 3px solid #14b8a6;
        }
        
        .msg-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 12px;
        }
        .msg-speaker { font-weight: 600; }
        .msg-speaker.agent { color: #60a5fa; }
        .msg-speaker.borrower { color: #2dd4bf; }
        .msg-time { color: #64748b; }
        .msg-latency {
            background: rgba(34,197,94,0.2);
            color: #22c55e;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            margin-left: 8px;
        }
        
        .msg-content { font-size: 14px; line-height: 1.6; }
        .msg-original { color: #94a3b8; font-style: italic; margin-bottom: 4px; }
        .msg-english { color: #e2e8f0; }
        
        .msg-tags {
            display: flex;
            gap: 8px;
            margin-top: 10px;
        }
        .tag {
            font-size: 10px;
            padding: 4px 10px;
            border-radius: 6px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .tag.intent { background: #312e81; color: #a5b4fc; }
        .tag.reason { background: #7c2d12; color: #fed7aa; }
        .tag.dtmf { background: #164e63; color: #67e8f9; }
        
        .empty-state {
            text-align: center;
            padding: 80px 20px;
            color: #475569;
        }
        .empty-state-icon {
            font-size: 48px;
            margin-bottom: 16px;
            opacity: 0.5;
        }
        
        /* Intelligence Dashboard Styles */
        .intel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }
        .intel-title {
            font-size: 24px;
            font-weight: 700;
        }
        .intel-subtitle {
            color: #64748b;
            font-size: 14px;
            margin-top: 4px;
        }
        .intel-badge {
            background: linear-gradient(135deg, #f97316, #ea580c);
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .stats-row {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }
        .stat-card {
            background: #1e293b;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            border: 1px solid #334155;
        }
        .stat-value {
            font-size: 32px;
            font-weight: 700;
            color: #f97316;
        }
        .stat-label {
            font-size: 11px;
            color: #64748b;
            text-transform: uppercase;
            margin-top: 4px;
        }
        
        .intel-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
            margin-bottom: 24px;
        }
        
        .section-title {
            font-size: 14px;
            font-weight: 600;
            color: #e2e8f0;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .section-title-icon {
            width: 24px;
            height: 24px;
            background: rgba(249,115,22,0.2);
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
        }
        
        .reason-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .reason-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px;
            background: #0f172a;
            border-radius: 8px;
        }
        .reason-icon {
            font-size: 20px;
            width: 36px;
            text-align: center;
        }
        .reason-info { flex: 1; }
        .reason-name { font-size: 13px; font-weight: 500; }
        .reason-count { font-size: 11px; color: #64748b; }
        .reason-bar {
            width: 80px;
            height: 6px;
            background: #334155;
            border-radius: 3px;
            overflow: hidden;
        }
        .reason-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, #f97316, #ea580c);
            border-radius: 3px;
        }
        
        .cluster-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .cluster-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 14px;
            background: #0f172a;
            border-radius: 8px;
            border-left: 3px solid transparent;
        }
        .cluster-item.high { border-left-color: #ef4444; }
        .cluster-item.medium { border-left-color: #f59e0b; }
        .cluster-item.low { border-left-color: #22c55e; }
        .cluster-name { font-weight: 500; }
        .cluster-state { font-size: 11px; color: #64748b; }
        .cluster-stats {
            display: flex;
            gap: 16px;
            font-size: 12px;
        }
        .cluster-stat {
            text-align: center;
        }
        .cluster-stat-value { font-weight: 600; }
        .cluster-stat-label { color: #64748b; font-size: 10px; }
        .alert-badge {
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
        }
        .alert-badge.high { background: rgba(239,68,68,0.2); color: #ef4444; }
        .alert-badge.medium { background: rgba(245,158,11,0.2); color: #f59e0b; }
        .alert-badge.low { background: rgba(34,197,94,0.2); color: #22c55e; }
        
        .decliner-table {
            width: 100%;
            border-collapse: collapse;
        }
        .decliner-table th {
            text-align: left;
            padding: 10px 12px;
            font-size: 11px;
            color: #64748b;
            text-transform: uppercase;
            border-bottom: 1px solid #334155;
        }
        .decliner-table td {
            padding: 12px;
            font-size: 13px;
            border-bottom: 1px solid #1e293b;
        }
        .risk-score {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
        }
        .risk-score.high { background: rgba(239,68,68,0.2); color: #ef4444; }
        .risk-score.medium { background: rgba(245,158,11,0.2); color: #f59e0b; }
        .risk-score.low { background: rgba(34,197,94,0.2); color: #22c55e; }
        
        .warning-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .warning-item {
            display: flex;
            gap: 14px;
            padding: 16px;
            background: #0f172a;
            border-radius: 10px;
            border-left: 3px solid #ef4444;
        }
        .warning-item.medium { border-left-color: #f59e0b; }
        .warning-icon {
            width: 40px;
            height: 40px;
            background: rgba(239,68,68,0.2);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
        }
        .warning-item.medium .warning-icon { background: rgba(245,158,11,0.2); }
        .warning-content { flex: 1; }
        .warning-title { font-weight: 600; margin-bottom: 4px; }
        .warning-message { font-size: 13px; color: #94a3b8; margin-bottom: 8px; }
        .warning-action {
            font-size: 12px;
            color: #f97316;
            display: flex;
            align-items: center;
            gap: 4px;
        }
        
        .persona-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 10px;
        }
        .persona-card {
            background: #0f172a;
            border-radius: 10px;
            padding: 16px;
            text-align: center;
        }
        .persona-icon {
            font-size: 28px;
            margin-bottom: 8px;
        }
        .persona-name {
            font-size: 12px;
            font-weight: 500;
            margin-bottom: 4px;
        }
        .persona-pct {
            font-size: 20px;
            font-weight: 700;
            color: #f97316;
        }
        .persona-count {
            font-size: 11px;
            color: #64748b;
        }
        
        .npa-card {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid #f97316;
            border-radius: 16px;
            padding: 24px;
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 24px;
        }
        .npa-item {
            text-align: center;
        }
        .npa-label {
            font-size: 11px;
            color: #64748b;
            text-transform: uppercase;
            margin-bottom: 8px;
        }
        .npa-value {
            font-size: 28px;
            font-weight: 700;
        }
        .npa-value.current { color: #22c55e; }
        .npa-value.predicted { color: #f59e0b; }
        .npa-value.risk { color: #ef4444; }
        .npa-value.savings { color: #f97316; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">
            <div class="logo-icon">🎙️</div>
            <div class="logo-text"><span>Acquink</span> Voice Intelligence</div>
        </div>
        <div class="tabs">
            <button class="tab active" onclick="showPage('demo')">📞 Live Call Demo</button>
            <button class="tab" onclick="showPage('intel')">📊 Intelligence Dashboard</button>
        </div>
    </div>
    
    <div class="container">
        <!-- Call Demo Page -->
        <div id="page-demo" class="page active">
            <div class="demo-grid">
                <div>
                    <div class="card" style="margin-bottom: 20px;">
                        <h3>Call Configuration</h3>
                        <div class="form-group">
                            <label>Phone Number</label>
                            <input type="tel" id="phoneNumber" placeholder="+91 98765 43210">
                        </div>
                        <div class="form-group">
                            <label>Borrower Name</label>
                            <input type="text" id="borrowerName" value="Ramesh Kumar">
                        </div>
                        <div class="form-group">
                            <label>RO Name</label>
                            <input type="text" id="roName" value="Amit Sharma">
                        </div>
                        <div class="form-group">
                            <label>Language</label>
                            <div class="language-pills">
                                <button class="lang-pill active" data-lang="hi-IN">हिंदी</button>
                                <button class="lang-pill" data-lang="te-IN">తెలుగు</button>
                                <button class="lang-pill" data-lang="ta-IN">தமிழ்</button>
                                <button class="lang-pill" data-lang="kn-IN">ಕನ್ನಡ</button>
                                <button class="lang-pill" data-lang="mr-IN">मराठी</button>
                                <button class="lang-pill" data-lang="en-IN">English</button>
                            </div>
                        </div>
                        <button class="btn-primary" id="callBtn" onclick="makeCall()">
                            📞 Start Demo Call
                        </button>
                    </div>
                    
                    <div class="card">
                        <h3>What This Demo Shows</h3>
                        <div style="font-size: 13px; color: #94a3b8; line-height: 1.8;">
                            <p><strong style="color: #f97316;">Gnani, Exotel, others do:</strong><br>
                            Voice calls, multi-language, basic reminders</p>
                            <p style="margin-top: 16px;"><strong style="color: #22c55e;">Acquink adds:</strong></p>
                            <ul style="margin-left: 20px; margin-top: 8px;">
                                <li>Structured decline reason taxonomy</li>
                                <li>Real-time English transcript</li>
                                <li>Intent tagging per turn</li>
                                <li>DTMF + Voice hybrid input</li>
                                <li>→ Feeds Intelligence Layer</li>
                            </ul>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <h3>Live Transcript (English)</h3>
                    <div class="transcript-box" id="transcript">
                        <div class="empty-state">
                            <div class="empty-state-icon">🎙️</div>
                            <p>Start a demo call to see the live transcript<br>with intent tagging and decline reason capture</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Intelligence Dashboard Page -->
        <div id="page-intel" class="page">
            <div class="intel-header">
                <div>
                    <div class="intel-title">Borrower Intelligence Dashboard</div>
                    <div class="intel-subtitle">What 1,247 calls reveal about your portfolio — powered by Acquink MASI</div>
                </div>
                <div class="intel-badge">DEMO DATA</div>
            </div>
            
            <div class="stats-row">
                <div class="stat-card">
                    <div class="stat-value" id="stat-calls">1,247</div>
                    <div class="stat-label">Total Calls</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="stat-connected">87.3%</div>
                    <div class="stat-label">Connection Rate</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="stat-confirmed">67.4%</div>
                    <div class="stat-label">Confirmed Available</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="stat-decliners">12.4%</div>
                    <div class="stat-label">Frequent Decliners</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="stat-borrowers">500</div>
                    <div class="stat-label">Borrowers Profiled</div>
                </div>
            </div>
            
            <div class="intel-grid">
                <div class="card">
                    <div class="section-title">
                        <div class="section-title-icon">📊</div>
                        Decline Reason Distribution
                    </div>
                    <div class="reason-list" id="reason-list"></div>
                </div>
                
                <div class="card">
                    <div class="section-title">
                        <div class="section-title-icon">📍</div>
                        Cluster Risk Monitor
                    </div>
                    <div class="cluster-list" id="cluster-list"></div>
                </div>
            </div>
            
            <div class="card" style="margin-bottom: 24px;">
                <div class="section-title">
                    <div class="section-title-icon">⚠️</div>
                    Early Warning Signals
                </div>
                <div class="warning-list" id="warning-list"></div>
            </div>
            
            <div class="intel-grid">
                <div class="card">
                    <div class="section-title">
                        <div class="section-title-icon">🚨</div>
                        Frequent Decliners (Top 10)
                    </div>
                    <table class="decliner-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Cluster</th>
                                <th>Persona</th>
                                <th>Declines</th>
                                <th>Primary Reason</th>
                                <th>Risk</th>
                            </tr>
                        </thead>
                        <tbody id="decliner-tbody"></tbody>
                    </table>
                </div>
                
                <div class="card">
                    <div class="section-title">
                        <div class="section-title-icon">👥</div>
                        Borrower Persona Distribution
                    </div>
                    <div class="persona-grid" id="persona-grid"></div>
                </div>
            </div>
            
            <div class="card">
                <div class="section-title">
                    <div class="section-title-icon">🎯</div>
                    NPA Prediction & Early Intervention Value
                </div>
                <div class="npa-card">
                    <div class="npa-item">
                        <div class="npa-label">Current NPA Rate</div>
                        <div class="npa-value current">2.8%</div>
                    </div>
                    <div class="npa-item">
                        <div class="npa-label">Predicted (60 days)</div>
                        <div class="npa-value predicted">3.4%</div>
                    </div>
                    <div class="npa-item">
                        <div class="npa-label">At-Risk Portfolio</div>
                        <div class="npa-value risk">₹4.2 Cr</div>
                    </div>
                    <div class="npa-item">
                        <div class="npa-label">Early Intervention Saves</div>
                        <div class="npa-value savings">₹1.8 Cr</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let ws;
        let selectedLang = 'hi-IN';
        let intelData = null;
        
        // Tab switching
        function showPage(page) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.getElementById('page-' + page).classList.add('active');
            event.target.classList.add('active');
            
            if (page === 'intel' && !intelData) {
                loadIntelligenceData();
            }
        }
        
        // Language selection
        document.querySelectorAll('.lang-pill').forEach(pill => {
            pill.addEventListener('click', () => {
                document.querySelectorAll('.lang-pill').forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                selectedLang = pill.dataset.lang;
            });
        });
        
        // WebSocket
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/ui`);
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if (msg.type === 'transcript') addTranscriptEntry(msg.data);
            };
            ws.onclose = () => setTimeout(connectWebSocket, 3000);
        }
        
        function addTranscriptEntry(data) {
            const box = document.getElementById('transcript');
            const empty = box.querySelector('.empty-state');
            if (empty) empty.remove();
            
            const isAgent = data.speaker === 'Agent';
            let tags = '';
            if (data.intent) tags += `<span class="tag intent">${data.intent}</span>`;
            if (data.decline_reason) tags += `<span class="tag reason">${data.decline_reason}</span>`;
            if (data.dtmf) tags += `<span class="tag dtmf">DTMF: ${data.dtmf}</span>`;
            
            const latency = data.latency_ms ? `<span class="msg-latency">${data.latency_ms}ms</span>` : '';
            
            box.insertAdjacentHTML('beforeend', `
                <div class="message ${isAgent ? 'agent' : 'borrower'}">
                    <div class="msg-header">
                        <span class="msg-speaker ${isAgent ? 'agent' : 'borrower'}">${data.speaker}</span>
                        <div>
                            ${latency}
                            <span class="msg-time">${data.timestamp}</span>
                        </div>
                    </div>
                    <div class="msg-content">
                        <div class="msg-original">${data.original}</div>
                        <div class="msg-english">${data.english}</div>
                    </div>
                    ${tags ? `<div class="msg-tags">${tags}</div>` : ''}
                </div>
            `);
            box.scrollTop = box.scrollHeight;
        }
        
        async function makeCall() {
            const btn = document.getElementById('callBtn');
            btn.disabled = true;
            btn.textContent = '📞 Calling...';
            
            // Clear transcript
            document.getElementById('transcript').innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📞</div>
                    <p>Connecting call...</p>
                </div>
            `;
            
            const response = await fetch('/api/call', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    phone: document.getElementById('phoneNumber').value || '+919876543210',
                    borrower_name: document.getElementById('borrowerName').value,
                    ro_name: document.getElementById('roName').value,
                    language: selectedLang
                })
            });
            
            const result = await response.json();
            btn.textContent = '📞 In Call';
            
            setTimeout(() => {
                btn.disabled = false;
                btn.textContent = '📞 Start Demo Call';
            }, 15000);
        }
        
        async function loadIntelligenceData() {
            const response = await fetch('/api/intelligence');
            intelData = await response.json();
            renderIntelligence();
        }
        
        function renderIntelligence() {
            if (!intelData) return;
            
            // Stats
            document.getElementById('stat-calls').textContent = intelData.summary.total_calls.toLocaleString();
            document.getElementById('stat-connected').textContent = intelData.summary.connection_rate + '%';
            document.getElementById('stat-confirmed').textContent = intelData.summary.confirmation_rate + '%';
            document.getElementById('stat-decliners').textContent = intelData.frequent_decliners.percentage + '%';
            document.getElementById('stat-borrowers').textContent = intelData.summary.total_borrowers_profiled;
            
            // Decline reasons
            const reasonList = document.getElementById('reason-list');
            reasonList.innerHTML = '';
            const reasons = Object.entries(intelData.decline_reasons)
                .sort((a, b) => b[1].count - a[1].count)
                .slice(0, 6);
            const maxCount = Math.max(...reasons.map(r => r[1].count));
            
            reasons.forEach(([key, data]) => {
                reasonList.insertAdjacentHTML('beforeend', `
                    <div class="reason-item">
                        <div class="reason-icon">${data.info.icon}</div>
                        <div class="reason-info">
                            <div class="reason-name">${data.info.label}</div>
                            <div class="reason-count">${data.count} occurrences (${data.percentage}%)</div>
                        </div>
                        <div class="reason-bar">
                            <div class="reason-bar-fill" style="width: ${(data.count / maxCount) * 100}%"></div>
                        </div>
                    </div>
                `);
            });
            
            // Clusters
            const clusterList = document.getElementById('cluster-list');
            clusterList.innerHTML = '';
            Object.entries(intelData.clusters).forEach(([name, data]) => {
                const level = data.alert_level.toLowerCase();
                clusterList.insertAdjacentHTML('beforeend', `
                    <div class="cluster-item ${level}">
                        <div>
                            <div class="cluster-name">${name}</div>
                            <div class="cluster-state">${data.state}</div>
                        </div>
                        <div class="cluster-stats">
                            <div class="cluster-stat">
                                <div class="cluster-stat-value">${data.total_borrowers}</div>
                                <div class="cluster-stat-label">Borrowers</div>
                            </div>
                            <div class="cluster-stat">
                                <div class="cluster-stat-value">${data.avg_risk_score}</div>
                                <div class="cluster-stat-label">Avg Risk</div>
                            </div>
                            <div class="cluster-stat">
                                <div class="cluster-stat-value">${data.frequent_decliners}</div>
                                <div class="cluster-stat-label">Freq. Decl.</div>
                            </div>
                        </div>
                        <span class="alert-badge ${level}">${data.alert_level}</span>
                    </div>
                `);
            });
            
            // Warnings
            const warningList = document.getElementById('warning-list');
            warningList.innerHTML = '';
            intelData.early_warnings.forEach(w => {
                const level = w.risk_level.toLowerCase();
                warningList.insertAdjacentHTML('beforeend', `
                    <div class="warning-item ${level}">
                        <div class="warning-icon">⚠️</div>
                        <div class="warning-content">
                            <div class="warning-title">${w.cluster}: ${w.type.replace(/_/g, ' ')}</div>
                            <div class="warning-message">${w.message}</div>
                            <div class="warning-action">→ ${w.recommended_action}</div>
                        </div>
                    </div>
                `);
            });
            
            // Frequent decliners
            const tbody = document.getElementById('decliner-tbody');
            tbody.innerHTML = '';
            intelData.frequent_decliners.top_10.forEach(d => {
                const riskClass = d.risk_score >= 60 ? 'high' : (d.risk_score >= 40 ? 'medium' : 'low');
                tbody.insertAdjacentHTML('beforeend', `
                    <tr>
                        <td>${d.id}</td>
                        <td>${d.cluster}</td>
                        <td>${d.persona}</td>
                        <td>${d.decline_count}</td>
                        <td>${d.primary_reason || '-'}</td>
                        <td><span class="risk-score ${riskClass}">${d.risk_score}</span></td>
                    </tr>
                `);
            });
            
            // Personas
            const personaGrid = document.getElementById('persona-grid');
            personaGrid.innerHTML = '';
            Object.entries(intelData.personas).forEach(([key, data]) => {
                personaGrid.insertAdjacentHTML('beforeend', `
                    <div class="persona-card">
                        <div class="persona-icon">${data.info.icon}</div>
                        <div class="persona-name">${data.info.label}</div>
                        <div class="persona-pct">${data.percentage}%</div>
                        <div class="persona-count">${data.count} borrowers</div>
                    </div>
                `);
            });
        }
        
        connectWebSocket();
    </script>
</body>
</html>
"""


@app.websocket("/ws/ui")
async def ui_websocket(websocket: WebSocket):
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
    borrower_name: str = "Borrower"
    ro_name: str = "RO"
    language: str = "hi-IN"


@app.post("/api/call")
async def initiate_call(request: CallRequest):
    """Initiate demo call with DTMF simulation"""
    
    call_id = f"demo_{int(time.time())}"
    language = Language(request.language) if request.language in [l.value for l in Language] else Language.HINDI
    
    session = CallSession(
        call_id=call_id,
        borrower_name=request.borrower_name,
        borrower_phone=request.phone,
        ro_name=request.ro_name,
        language=language
    )
    sessions[call_id] = session
    
    asyncio.create_task(simulate_full_conversation(session))
    
    return {"call_id": call_id, "status": "initiated", "language": language.value}


async def simulate_full_conversation(session: CallSession):
    """Simulate a complete call with DTMF and decline reason capture"""
    
    lang = session.language
    ro = session.ro_name
    
    await asyncio.sleep(1)
    
    # Turn 1: Agent greeting
    greeting_v, greeting_e = RESPONSES["GREETING"][lang]
    greeting_v = greeting_v.format(ro_name=ro)
    greeting_e = greeting_e.format(ro_name=ro)
    
    await broadcast_transcript(TranscriptEntry(
        timestamp=datetime.now().strftime("%H:%M:%S"),
        speaker="Agent",
        original_text=greeting_v,
        english_text=greeting_e,
        intent="GREETING",
        latency_ms=0
    ))
    
    await asyncio.sleep(3)
    
    # Turn 2: Borrower presses 2 (unavailable)
    await broadcast_transcript(TranscriptEntry(
        timestamp=datetime.now().strftime("%H:%M:%S"),
        speaker="Borrower",
        original_text="[DTMF: 2]",
        english_text="Pressed 2 - Not available",
        intent="UNAVAILABLE",
        dtmf="2",
        latency_ms=50
    ))
    
    await asyncio.sleep(1)
    
    # Turn 3: Agent asks for reason
    reason_v, reason_e = RESPONSES["ASK_REASON"][lang]
    
    await broadcast_transcript(TranscriptEntry(
        timestamp=datetime.now().strftime("%H:%M:%S"),
        speaker="Agent",
        original_text=reason_v,
        english_text=reason_e,
        latency_ms=35
    ))
    
    await asyncio.sleep(4)
    
    # Turn 4: Borrower presses 1 (travel/market)
    decline_reason = DeclineReason.TRAVEL_MARKET
    reason_info = DECLINE_REASON_INFO[decline_reason]
    
    await broadcast_transcript(TranscriptEntry(
        timestamp=datetime.now().strftime("%H:%M:%S"),
        speaker="Borrower",
        original_text="[DTMF: 1]",
        english_text=f"Pressed 1 - {reason_info['label']}",
        intent="REASON_GIVEN",
        decline_reason=decline_reason.value,
        dtmf="1",
        latency_ms=45
    ))
    
    await asyncio.sleep(1)
    
    # Turn 5: Agent confirms reschedule
    new_date = (datetime.now() + timedelta(days=3)).strftime("%A")
    confirm_v, confirm_e = RESPONSES["RESCHEDULE_CONFIRM"][lang]
    confirm_v = confirm_v.format(ro_name=ro, new_date=new_date)
    confirm_e = confirm_e.format(ro_name=ro, new_date=new_date)
    
    await broadcast_transcript(TranscriptEntry(
        timestamp=datetime.now().strftime("%H:%M:%S"),
        speaker="Agent",
        original_text=confirm_v,
        english_text=confirm_e,
        intent="CALL_COMPLETE",
        latency_ms=40
    ))
    
    session.state = "COMPLETED"
    session.decline_reason = decline_reason


@app.get("/api/intelligence")
async def get_intelligence():
    """Return mock intelligence data for dashboard"""
    return intelligence_data


@app.get("/api/sessions")
async def list_sessions():
    return {
        call_id: {
            "borrower": s.borrower_name,
            "language": s.language.value,
            "state": s.state,
            "decline_reason": s.decline_reason.value if s.decline_reason else None,
        }
        for call_id, s in sessions.items()
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
