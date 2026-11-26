import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
import requests
import json
import os
import io
import zipfile
import random
import smtplib
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
import hmac
import hashlib
import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from streamlit_sortables import sort_items
    HAS_SORTABLES = True
except Exception:
    HAS_SORTABLES = False
from xml.sax.saxutils import escape as xml_escape

st.set_page_config(
    page_title="Finapp",
    layout="wide",
    page_icon="🐷",
    initial_sidebar_state="expanded"
)

DATA_FILE = "datos_finanzas.json"
TZ_SYDNEY = ZoneInfo("Australia/Sydney")


def _obtener_password_secreto():
    try:
        if hasattr(st, "secrets") and "app_password" in st.secrets:
            return str(st.secrets["app_password"])
    except Exception:
        pass
    return os.environ.get("FINAPP_PASSWORD", "")


def _obtener_up_token():
    try:
        if hasattr(st, "secrets") and "up_bank_token" in st.secrets:
            return str(st.secrets["up_bank_token"]).strip()
    except Exception:
        pass
    return os.environ.get("UP_BANK_TOKEN", "").strip()


def _obtener_gemini_key():
    try:
        if hasattr(st, "secrets") and "gemini_api_key" in st.secrets:
            return str(st.secrets["gemini_api_key"]).strip()
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", "").strip()


def _obtener_gcal_url():
    try:
        if hasattr(st, "secrets") and "gcal_ics_url" in st.secrets:
            return str(st.secrets["gcal_ics_url"]).strip()
    except Exception:
        pass
    return os.environ.get("GCAL_ICS_URL", "").strip()


def _obtener_gcal_webhook_url():
    try:
        if hasattr(st, "secrets") and "gcal_reminder_webhook" in st.secrets:
            return str(st.secrets["gcal_reminder_webhook"]).strip()
    except Exception:
        pass
    return os.environ.get("GCAL_REMINDER_WEBHOOK", "").strip()


def _notificar_reset_recordatorio_90d(ahora_syd, days=90, force=False):
    url = _obtener_gcal_webhook_url()
    if not url or int(days) <= 0:
        return
    try:
        now_epoch = time.time()
        last_ping = float(st.session_state.get("_last_gcal_reminder_ping", 0.0) or 0.0)
        if not force and (now_epoch - last_ping < 60):
            return
        st.session_state["_last_gcal_reminder_ping"] = now_epoch
        requests.post(
            url,
            json={"saved_at": ahora_syd.isoformat(), "days": int(days)},
            timeout=4,
        )
    except Exception:
        pass


def _parse_ics_dt(val_str):
    v = (val_str or "").strip()
    if not v:
        return None, True
    if len(v) == 8 and v.isdigit():
        return datetime.strptime(v, "%Y%m%d").replace(tzinfo=TZ_SYDNEY), True
    if v.endswith("Z"):
        dt_utc = datetime.strptime(v[:15], "%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo("UTC"))
        return dt_utc.astimezone(TZ_SYDNEY), False
    if "T" in v:
        return datetime.strptime(v[:15], "%Y%m%dT%H%M%S").replace(tzinfo=TZ_SYDNEY), False
    return None, True


def _extraer_monto_evento(texto):
    import re
    t = texto or ""
    # Match explicit signed amount (+450, -$450, +$450) or $-prefixed amount ($450)
    m = re.search(r'([+-])\s*(?:AUD\s*)?\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)', t, re.IGNORECASE)
    if not m:
        m = re.search(r'()(?:AUD\s*)?\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)', t, re.IGNORECASE)
    if not m:
        return None
    signo = (m.group(1) or "").strip()
    num = float(m.group(2).replace(",", ""))
    if signo == "-":
        return -num
    if signo == "+":
        return num
    low = t.lower()
    is_house_cost = any(k in low for k in ["house rent", "wifi", "charge", "bill", "electricity", "water", "gas", "internet", "rego", "insurance"])
    if not is_house_cost and any(k in low for k in ["payday", "salary", "wage", "income", "deposit", "refund", "rent from", "contribution", "andy", "juan"]):
        return num
    return -num


@st.cache_data(ttl=180, show_spinner=False)
def obtener_eventos_gcal(ics_url, days_ahead=30, refresh_nonce=0):
    if not ics_url:
        return [], None
    try:
        r = requests.get(ics_url, timeout=12)
        if r.status_code != 200:
            return [], f"Calendar sync error ({r.status_code})."
        raw_lines = r.text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        unfolded = []
        for ln in raw_lines:
            if ln.startswith((" ", "\t")) and unfolded:
                unfolded[-1] += ln[1:]
            else:
                unfolded.append(ln)

        ahora = datetime.now(TZ_SYDNEY)
        hoy = ahora.date()
        fin = hoy + timedelta(days=int(days_ahead))

        eventos = []
        cur = None
        for ln in unfolded:
            if ln == "BEGIN:VEVENT":
                cur = {}
            elif ln == "END:VEVENT":
                if cur and cur.get("DTSTART"):
                    dt0, is_all_day = _parse_ics_dt(cur["DTSTART"])
                    if dt0 is not None:
                        summary = cur.get("SUMMARY", "Scheduled Event").replace("\\,", ",").replace("\\n", " ").strip()
                        desc = cur.get("DESCRIPTION", "").replace("\\,", ",").replace("\\n", " ").strip()
                        rrule = cur.get("RRULE", "")
                        fechas_occ = []
                        if not rrule:
                            if hoy <= dt0.date() <= fin:
                                fechas_occ.append(dt0)
                        else:
                            parts = dict(p.split("=", 1) for p in rrule.split(";") if "=" in p)
                            freq = parts.get("FREQ", "")
                            interval = int(parts.get("INTERVAL", "1") or "1")
                            until_dt = None
                            if "UNTIL" in parts:
                                until_dt, _ = _parse_ics_dt(parts["UNTIL"])
                            cur_dt = dt0
                            guard = 0
                            while cur_dt.date() <= fin and guard < 400:
                                guard += 1
                                if until_dt and cur_dt > until_dt:
                                    break
                                if cur_dt.date() >= hoy:
                                    fechas_occ.append(cur_dt)
                                if freq == "WEEKLY":
                                    cur_dt = cur_dt + timedelta(days=7 * interval)
                                elif freq == "DAILY":
                                    cur_dt = cur_dt + timedelta(days=interval)
                                elif freq == "MONTHLY":
                                    m_new = cur_dt.month - 1 + interval
                                    y_new = cur_dt.year + m_new // 12
                                    m_new = m_new % 12 + 1
                                    import calendar as _cal
                                    d_new = min(cur_dt.day, _cal.monthrange(y_new, m_new)[1])
                                    cur_dt = cur_dt.replace(year=y_new, month=m_new, day=d_new)
                                elif freq == "YEARLY":
                                    try:
                                        cur_dt = cur_dt.replace(year=cur_dt.year + interval)
                                    except ValueError:
                                        cur_dt = cur_dt.replace(year=cur_dt.year + interval, day=28)
                                else:
                                    break

                        monto_est = _extraer_monto_evento(f"{summary} {desc}")
                        for occ in fechas_occ:
                            dias_f = (occ.date() - hoy).days
                            if dias_f == 0:
                                cuando = "Today"
                            elif dias_f == 1:
                                cuando = "Tomorrow"
                            else:
                                cuando = f"In {dias_f} days"
                            eventos.append({
                                "date": occ.date(),
                                "date_str": occ.strftime("%a %d %b"),
                                "when": cuando,
                                "days_left": dias_f,
                                "title": summary,
                                "amount_aud": monto_est,
                            })
                cur = None
            elif cur is not None and ":" in ln:
                k_raw, val = ln.split(":", 1)
                k = k_raw.split(";")[0].upper()
                cur[k] = val

        eventos.sort(key=lambda x: (x["date"], x["title"]))
        return eventos, None
    except Exception as e:
        return [], f"Calendar read error: {e}"


def _html_piggy_mascot(width=126):
    return f"""
<div style="display:flex; justify-content:center; align-items:center; margin: 2px auto 4px auto;">
<style>
@keyframes pigBreathe {{
0%, 100% {{ transform: translateY(0px) scale(1, 1); }}
50% {{ transform: translateY(-2.5px) scale(1.015, 0.99); }}
}}
@keyframes pigHeadTilt {{
0%, 100% {{ transform: rotate(0deg); }}
25% {{ transform: rotate(-2.2deg); }}
75% {{ transform: rotate(2.2deg); }}
}}
@keyframes pigBlink {{
0%, 44%, 48%, 100% {{ transform: scaleY(1); }}
46% {{ transform: scaleY(0.12); }}
}}
@keyframes pigSnout {{
0%, 100% {{ transform: translateY(0px) scale(1); }}
50% {{ transform: translateY(-1px) scale(1.03); }}
}}
@keyframes pigWave {{
0%, 72%, 100% {{ transform: rotate(0deg); }}
78% {{ transform: rotate(-16deg); }}
84% {{ transform: rotate(8deg); }}
90% {{ transform: rotate(-12deg); }}
}}
.pig-body-anim {{ transform-origin: 100px 115px; animation: pigBreathe 3.4s ease-in-out infinite; }}
.pig-head-anim {{ transform-origin: 100px 92px; animation: pigHeadTilt 5.5s ease-in-out infinite; }}
.pig-eye-anim {{ transform-origin: center; transform-box: fill-box; animation: pigBlink 4.6s ease-in-out infinite; }}
.pig-snout-anim {{ transform-origin: 100px 106px; animation: pigSnout 2.8s ease-in-out infinite; }}
.pig-wave-anim {{ transform-origin: 145px 114px; animation: pigWave 6s ease-in-out infinite; }}
</style>
<svg width="{width}" viewBox="0 0 200 165" xmlns="http://www.w3.org/2000/svg">
<defs>
<radialGradient id="pigBodyGrad" cx="42%" cy="35%" r="65%">
<stop offset="0%" stop-color="#FBCFE8"/>
<stop offset="55%" stop-color="#F472B6"/>
<stop offset="100%" stop-color="#DB2777"/>
</radialGradient>
<linearGradient id="metaLens" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#38BDF8" stop-opacity="0.32"/>
<stop offset="50%" stop-color="#0F172A" stop-opacity="0.18"/>
<stop offset="100%" stop-color="#818CF8" stop-opacity="0.35"/>
</linearGradient>
</defs>
<ellipse cx="100" cy="150" rx="54" ry="8" fill="#CBD5E1" opacity="0.55"/>
<g class="pig-body-anim">
<path d="M 42 104 Q 26 96 31 84 Q 36 74 44 82 Q 49 88 41 94" fill="none" stroke="#EC4899" stroke-width="5" stroke-linecap="round"/>
<rect x="64" y="128" width="16" height="20" rx="7" fill="#DB2777"/>
<rect x="118" y="128" width="16" height="20" rx="7" fill="#DB2777"/>
<g class="pig-wave-anim">
<rect x="142" y="106" width="22" height="13" rx="6.5" fill="#F472B6" stroke="#DB2777" stroke-width="1.5"/>
</g>
<ellipse cx="100" cy="100" rx="60" ry="46" fill="url(#pigBodyGrad)"/>
<rect x="82" y="54" width="36" height="7" rx="3.5" fill="#831843"/>
<rect x="85" y="55.5" width="30" height="2" rx="1" fill="#FDE047" opacity="0.75"/>
<g class="pig-head-anim">
<path d="M 54 68 Q 42 40 68 52 Z" fill="#F472B6" stroke="#DB2777" stroke-width="1.5"/>
<path d="M 56 64 Q 49 48 65 55 Z" fill="#FBCFE8"/>
<path d="M 146 68 Q 158 40 132 52 Z" fill="#F472B6" stroke="#DB2777" stroke-width="1.5"/>
<path d="M 144 64 Q 151 48 135 55 Z" fill="#FBCFE8"/>
<g class="pig-eye-anim">
<circle cx="78" cy="84" r="5.5" fill="#1E293B"/>
<circle cx="76.5" cy="82.2" r="2" fill="#FFFFFF"/>
<circle cx="122" cy="84" r="5.5" fill="#1E293B"/>
<circle cx="120.5" cy="82.2" r="2" fill="#FFFFFF"/>
</g>
<rect x="57" y="73" width="39" height="22" rx="7" fill="url(#metaLens)" stroke="#0F172A" stroke-width="3.6"/>
<rect x="104" y="73" width="39" height="22" rx="7" fill="url(#metaLens)" stroke="#0F172A" stroke-width="3.6"/>
<path d="M 96 81 Q 100 78 104 81" fill="none" stroke="#0F172A" stroke-width="3.6" stroke-linecap="round"/>
<line x1="48" y1="80" x2="57" y2="80" stroke="#0F172A" stroke-width="3.5" stroke-linecap="round"/>
<line x1="143" y1="80" x2="152" y2="80" stroke="#0F172A" stroke-width="3.5" stroke-linecap="round"/>
<circle cx="140" cy="77" r="2.2" fill="#38BDF8"/>
<line x1="63" y1="77" x2="72" y2="77" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" opacity="0.65"/>
<line x1="110" y1="77" x2="119" y2="77" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" opacity="0.65"/>
<g class="pig-snout-anim">
<ellipse cx="100" cy="108" rx="22" ry="15" fill="#FBCFE8" stroke="#EC4899" stroke-width="2"/>
<ellipse cx="92" cy="108" rx="3.6" ry="5.2" fill="#9D174D"/>
<ellipse cx="108" cy="108" rx="3.6" ry="5.2" fill="#9D174D"/>
</g>
<path d="M 88 127 Q 100 135 112 127" fill="none" stroke="#9D174D" stroke-width="2.6" stroke-linecap="round"/>
</g>
</g>
</svg>
</div>
    """


def _obtener_binance_keys():
    k, s, r_url, r_sec = "", "", "", ""
    try:
        if hasattr(st, "secrets"):
            k = str(st.secrets.get("binance_api_key", "")).strip()
            s = str(st.secrets.get("binance_api_secret", "")).strip()
            r_url = str(st.secrets.get("binance_relay_url", "")).strip()
            r_sec = str(st.secrets.get("binance_relay_secret", "")).strip()
    except Exception:
        pass
    if not k:
        k = os.environ.get("BINANCE_API_KEY", "").strip()
    if not s:
        s = os.environ.get("BINANCE_API_SECRET", "").strip()
    if not r_url:
        r_url = os.environ.get("BINANCE_RELAY_URL", "").strip()
    if not r_sec:
        r_sec = os.environ.get("BINANCE_RELAY_SECRET", "").strip()
    return k, s, r_url, r_sec


def _binance_signed_get(path, api_key, api_secret, params=None, relay_url="", relay_secret=""):
    q = dict(params or {})
    q["timestamp"] = int(time.time() * 1000)
    q["recvWindow"] = 10000
    query_str = urllib.parse.urlencode(q)
    sig = hmac.new(api_secret.encode("utf-8"), query_str.encode("utf-8"), hashlib.sha256).hexdigest()
    full_qs = f"{query_str}&signature={sig}"
    headers = {"X-MBX-APIKEY": api_key}

    if relay_url:
        try:
            r_headers = dict(headers)
            if relay_secret:
                r_headers["x-relay-secret"] = relay_secret
            r = requests.get(
                relay_url.rstrip("/"),
                params={"path": path, "qs": full_qs},
                headers=r_headers,
                timeout=15,
            )
            if r.status_code == 200:
                return r.json(), None
            try:
                msg = r.json().get("msg") or r.json().get("error") or r.text[:160]
            except Exception:
                msg = r.text[:160]
            return None, f"Binance relay error ({r.status_code}): {msg}"
        except Exception as e:
            return None, f"Binance relay connection error: {e}"

    base_urls = [
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
    ]

    last_err = "Could not connect to Binance."
    for base in base_urls:
        try:
            r = requests.get(f"{base}{path}?{full_qs}", headers=headers, timeout=12)
            if r.status_code == 200:
                return r.json(), None
            if r.status_code == 451:
                last_err = (
                    "Binance returned HTTP 451 (region block from Streamlit Cloud's US server). "
                    "Your API key is safe, but Streamlit Cloud's server location is blocked by Binance."
                )
                continue
            try:
                msg = r.json().get("msg", r.text[:160])
            except Exception:
                msg = r.text[:160]
            return None, f"Binance API error ({r.status_code}): {msg}"
        except Exception as e:
            last_err = f"Binance connection error: {e}"
    return None, last_err


@st.cache_data(ttl=120, show_spinner=False)
def obtener_binance_portfolio(api_key, api_secret, usd_to_aud_rate=1.55, refresh_nonce=0, relay_url="", relay_secret=""):
    if not api_key or not api_secret:
        return [], "Missing Binance API credentials."

    holdings = {}  # (asset, wallet_label) -> qty

    # 1. Spot Wallet (skip LD* wrapped Simple Earn tokens to avoid double counting)
    spot_data, err = _binance_signed_get("/api/v3/account", api_key, api_secret, {"omitZeroBalances": "true"}, relay_url=relay_url, relay_secret=relay_secret)
    if err:
        return [], err
    for bal in (spot_data or {}).get("balances", []):
        asset = str(bal.get("asset", "")).upper().strip()
        qty = float(bal.get("free", 0) or 0) + float(bal.get("locked", 0) or 0)
        if not asset or qty <= 0 or (asset.startswith("LD") and len(asset) > 3):
            continue
        key = (asset, "Binance Spot")
        holdings[key] = holdings.get(key, 0.0) + qty

    # 2. Simple Earn Flexible (best-effort)
    flex_data, _ = _binance_signed_get("/sapi/v1/simple-earn/flexible/position", api_key, api_secret, {"size": 100}, relay_url=relay_url, relay_secret=relay_secret)
    for row in (flex_data or {}).get("rows", []):
        asset = str(row.get("asset", "")).upper().strip()
        qty = float(row.get("totalAmount", 0) or 0)
        if asset and qty > 0:
            key = (asset, "Binance Earn (Flex)")
            holdings[key] = holdings.get(key, 0.0) + qty

    # 3. Simple Earn Locked (best-effort)
    lock_data, _ = _binance_signed_get("/sapi/v1/simple-earn/locked/position", api_key, api_secret, {"size": 100}, relay_url=relay_url, relay_secret=relay_secret)
    for row in (lock_data or {}).get("rows", []):
        asset = str(row.get("asset", "")).upper().strip()
        qty = float(row.get("amount", 0) or 0)
        if asset and qty > 0:
            key = (asset, "Binance Earn (Locked)")
            holdings[key] = holdings.get(key, 0.0) + qty

    if not holdings:
        return [], None

    # 4. Live USD prices from Binance public ticker (with data-api fallback)
    price_map = {}
    for ticker_url in [
        "https://data-api.binance.vision/api/v3/ticker/price",
        "https://api.binance.com/api/v3/ticker/price",
    ]:
        try:
            pr = requests.get(ticker_url, timeout=10)
            if pr.status_code == 200:
                for item in pr.json():
                    price_map[item["symbol"]] = float(item["price"])
                break
        except Exception:
            continue

    stables = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI", "USDP", "USD"}
    btc_usd = price_map.get("BTCUSDT", 0.0)

    resultados = []
    for (asset, wallet_lbl), qty in holdings.items():
        if asset == "AUD":
            precio_aud = 1.0
            quote_str = "1 AUD = $1.00 AUD"
        elif asset in stables:
            precio_aud = float(usd_to_aud_rate)
            quote_str = f"1 {asset} = ${precio_aud:,.2f} AUD"
        elif f"{asset}USDT" in price_map:
            p_usd = price_map[f"{asset}USDT"]
            precio_aud = p_usd * float(usd_to_aud_rate)
            quote_str = f"1 {asset} = ${precio_aud:,.2f} AUD"
        elif f"{asset}USDC" in price_map:
            p_usd = price_map[f"{asset}USDC"]
            precio_aud = p_usd * float(usd_to_aud_rate)
            quote_str = f"1 {asset} = ${precio_aud:,.2f} AUD"
        elif f"{asset}BTC" in price_map and btc_usd > 0:
            p_usd = price_map[f"{asset}BTC"] * btc_usd
            precio_aud = p_usd * float(usd_to_aud_rate)
            quote_str = f"1 {asset} = ${precio_aud:,.2f} AUD"
        else:
            precio_aud = 0.0
            quote_str = f"⚠️ No quote for {asset}"

        val_aud = qty * precio_aud
        resultados.append({
            "asset": asset,
            "wallet": wallet_lbl,
            "qty": qty,
            "price_aud": precio_aud,
            "val_aud": val_aud,
            "quote_str": quote_str,
        })

    resultados.sort(key=lambda x: x["val_aud"], reverse=True)
    return resultados, None


@st.cache_data(ttl=3600, show_spinner=False)
def _listar_modelos_gemini(api_key):
    modelos = ["gemini-2.5-flash-lite", "gemini-2.0-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash"]
    try:
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
            timeout=10,
        )
        if r.status_code == 200:
            lites, flashes = [], []
            for m in r.json().get("models", []):
                nombre = (m.get("name") or "").replace("models/", "")
                metodos = m.get("supportedGenerationMethods", [])
                nl = nombre.lower()
                if "generateContent" in metodos and "flash" in nl and "image" not in nl and "tts" not in nl:
                    if "lite" in nl:
                        lites.append(nombre)
                    else:
                        flashes.append(nombre)
            lites.sort(reverse=True)
            flashes.sort(reverse=True)
            combinados = lites + flashes
            if combinados:
                return combinados + [x for x in modelos if x not in combinados]
    except Exception:
        pass
    return modelos


def consultar_chatbot_finanzas(pregunta, historial, contexto_financiero, api_key):
    if not api_key:
        return "Missing `gemini_api_key` in Streamlit Secrets. Add it under Settings → Secrets to activate the chatbot."

    system_prompt = (
        "You are Finapp AI Advisor, Julian's personal Australian finance assistant. "
        "All amounts are in AUD unless explicitly noted. Be concise, practical, and accurate. "
        "Use the pre-calculated figures and live snapshot below to answer with exact numbers.\n\n"
        f"{contexto_financiero}"
    )

    contents = []
    for msg in historial[-4:]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": pregunta}]})

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600},
    }

    ultimo_error = "Could not reach Gemini API."
    for modelo in _listar_modelos_gemini(api_key)[:3]:
        try:
            url_m = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
            hdrs_m = {"Content-Type": "application/json", "x-goog-api-key": api_key}
            resp = requests.post(url_m, headers=hdrs_m, json=payload, timeout=20)
            if resp.status_code == 429:
                time.sleep(2.0)
                resp = requests.post(url_m, headers=hdrs_m, json=payload, timeout=20)
                if resp.status_code == 429:
                    return "AI limit reached, try again in a minute."
            if resp.status_code == 200:
                data = resp.json()
                cands = data.get("candidates", [])
                if cands:
                    parts = cands[0].get("content", {}).get("parts", [])
                    texto = "".join(p.get("text", "") for p in parts).strip()
                    if texto:
                        return texto
            elif resp.status_code == 404:
                ultimo_error = f"Model {modelo} unavailable (404)."
                continue
            else:
                ultimo_error = "AI service temporarily unavailable. Please try again shortly."
                break
        except Exception as e:
            ultimo_error = f"Connection error: {e}"
            break
    return ultimo_error


@st.cache_data(ttl=120, show_spinner=False)
def obtener_cuentas_up_bank(token, refresh_nonce=0):
    if not token:
        return [], "Missing Up Bank token"
    try:
        resp = requests.get(
            "https://api.up.com.au/api/v1/accounts",
            headers={"Authorization": f"Bearer {token}"},
            params={"page[size]": 50},
            timeout=12,
        )
        if resp.status_code == 401:
            return [], "Invalid or expired Up Bank Personal Access Token (401 Unauthorized)."
        if resp.status_code != 200:
            return [], f"Up Bank API error ({resp.status_code})."
        data = resp.json().get("data", [])
        cuentas = []
        for acc in data:
            attrs = acc.get("attributes", {})
            bal = attrs.get("balance", {})
            cuentas.append({
                "id": acc.get("id"),
                "name": attrs.get("displayName", "Up Account"),
                "type": attrs.get("accountType", "TRANSACTIONAL"),
                "ownership": attrs.get("ownershipType", "INDIVIDUAL"),
                "balance_aud": float(bal.get("value", 0.0)),
            })
        return cuentas, None
    except Exception as e:
        return [], f"Connection error: {e}"


@st.cache_data(ttl=120, show_spinner=False)
def obtener_transacciones_up_bank(token, days_back=30, refresh_nonce=0, max_pages=20):
    if not token:
        return [], "Missing Up Bank token"
    try:
        url = "https://api.up.com.au/api/v1/transactions"
        params = {"page[size]": 100}
        if days_back is not None:
            since_dt = (datetime.now(TZ_SYDNEY) - timedelta(days=int(days_back))).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            params["filter[since]"] = since_dt.isoformat()
        headers = {"Authorization": f"Bearer {token}"}
        transacciones = []
        paginas = 0
        while url and paginas < max_pages:
            resp = requests.get(url, headers=headers, params=params if paginas == 0 else None, timeout=15)
            if resp.status_code == 401:
                return [], "Invalid or expired Up Bank Personal Access Token (401 Unauthorized)."
            if resp.status_code != 200:
                return [], f"Up Bank API error ({resp.status_code})."
            payload = resp.json()
            transacciones.extend(payload.get("data", []))
            url = payload.get("links", {}).get("next")
            paginas += 1
        return transacciones, None
    except Exception as e:
        return [], f"Connection error: {e}"


def clasificar_transaccion_up(tx, own_account_ids=None, own_account_names=None):
    attrs = tx.get("attributes", {})
    rels = tx.get("relationships", {})
    desc = (attrs.get("description") or "").strip()
    msg = (attrs.get("message") or "").strip()
    tx_type = (attrs.get("transactionType") or "").strip().lower()

    amt_obj = attrs.get("amount", {})
    amount_aud = float(amt_obj.get("value", 0.0))
    status = attrs.get("status", "SETTLED")
    created_raw = attrs.get("createdAt") or attrs.get("settledAt") or ""
    try:
        dt_syd = datetime.fromisoformat(created_raw.replace("Z", "+00:00")).astimezone(TZ_SYDNEY)
    except Exception:
        dt_syd = datetime.now(TZ_SYDNEY)

    # Verify internal transfer ownership via Up API relationships.transferAccount, transactionType, or own account names
    transfer_data = (rels.get("transferAccount") or {}).get("data")
    needs_review = False
    is_internal_up = False
    desc_low = desc.lower()

    if tx_type in ("transfer", "internal transfer"):
        is_internal_up = True
    elif isinstance(transfer_data, dict) and transfer_data.get("id"):
        target_id = transfer_data.get("id")
        if own_account_ids is None or target_id in own_account_ids:
            is_internal_up = True
        else:
            needs_review = True
    elif own_account_names and (desc_low.startswith("transfer from ") or desc_low.startswith("transfer to ")):
        counterparty = desc_low.replace("transfer from ", "", 1).replace("transfer to ", "", 1).strip()
        if any(counterparty == nm or nm in counterparty for nm in own_account_names if nm):
            is_internal_up = True

    up_cat = (rels.get("category", {}).get("data") or {}).get("id") or ""

    if is_internal_up:
        tag = "🔄 Internal Up Transfer"
    elif needs_review:
        tag = "⚠️ Review Transfer"
    elif up_cat:
        prefix = "💵" if amount_aud > 0 else "💳"
        tag = f"{prefix} {up_cat.replace('-', ' ').title()}"
    elif amount_aud > 0:
        tag = "💵 Incoming Payment"
    else:
        tag = "💳 Outgoing Expense"

    return {
        "Date": dt_syd.strftime("%d/%m/%Y %H:%M"),
        "Date_Sort": dt_syd,
        "Description": desc or "Transaction",
        "Note": msg,
        "Tag": tag,
        "Status": status,
        "Amount (AUD)": amount_aud,
        "is_internal_up": is_internal_up,
        "needs_review": needs_review,
    }


def calcular_resumen_cashflow_up(df_txs, date_from=None, date_to=None, search_text="", hoy_date=None):
    hoy_d = hoy_date or datetime.now(TZ_SYDNEY).date()
    if df_txs is None or df_txs.empty:
        return pd.DataFrame(), {
            "count": 0, "total": 0.0, "avg_tx": 0.0,
            "avg_day": 0.0, "avg_week": 0.0, "avg_month": 0.0,
            "d_from": date_from or hoy_d, "d_to": date_to or hoy_d, "n_days": 1,
        }
    df_m = df_txs.copy()
    df_m["_dt_date"] = pd.to_datetime(df_m["Date_Sort"]).dt.date
    if date_from is not None:
        df_m = df_m[df_m["_dt_date"] >= date_from]
    if date_to is not None:
        df_m = df_m[df_m["_dt_date"] <= date_to]
    if search_text and search_text.strip():
        q_low = search_text.strip().lower()
        df_m = df_m[
            df_m["Description"].str.lower().str.contains(q_low, na=False)
            | df_m["Note"].str.lower().str.contains(q_low, na=False)
            | df_m["Tag"].str.lower().str.contains(q_low, na=False)
        ]

    d_to = date_to if date_to is not None else hoy_d
    if date_from is not None:
        d_from = date_from
    elif not df_m.empty:
        d_from = min(df_m["_dt_date"])
    else:
        d_from = d_to

    n_days = max(1, (d_to - d_from).days + 1)
    n_weeks = n_days / 7.0
    n_months = n_days / 30.4375
    n_tx = int(len(df_m))
    total = float(df_m["Amount (AUD)"].sum()) if n_tx > 0 else 0.0

    return df_m, {
        "count": n_tx,
        "total": total,
        "avg_tx": (total / n_tx) if n_tx > 0 else 0.0,
        "avg_day": total / n_days,
        "avg_week": total / n_weeks,
        "avg_month": total / n_months,
        "d_from": d_from,
        "d_to": d_to,
        "n_days": n_days,
    }


def calcular_top_tags_up(df_period, mode="Costs", date_from=None, date_to=None, hoy_date=None):
    hoy_d = hoy_date or datetime.now(TZ_SYDNEY).date()
    if df_period is None or df_period.empty:
        return pd.DataFrame(), {"total": 0.0, "avg_week": 0.0, "avg_month": 0.0, "count": 0}

    df_t = df_period.copy()
    if "_dt_date" not in df_t.columns:
        df_t["_dt_date"] = pd.to_datetime(df_t["Date_Sort"]).dt.date

    d_to = date_to if date_to is not None else hoy_d
    d_from = date_from if date_from is not None else min(df_t["_dt_date"])
    n_days = max(1, (d_to - d_from).days + 1)
    n_weeks = n_days / 7.0
    n_months = n_days / 30.4375

    if mode == "Costs":
        df_t = df_t[df_t["Amount (AUD)"] < 0].copy()
        df_t["_mag"] = df_t["Amount (AUD)"].abs()
    else:
        df_t = df_t[df_t["Amount (AUD)"] > 0].copy()
        df_t["_mag"] = df_t["Amount (AUD)"]

    if df_t.empty:
        return pd.DataFrame(), {"total": 0.0, "avg_week": 0.0, "avg_month": 0.0, "count": 0}

    grp = df_t.groupby("Tag", as_index=False).agg(
        Total=("_mag", "sum"),
        Count=("_mag", "count"),
    )
    grand_tot = float(grp["Total"].sum()) or 1.0
    grp["Avg_Week"] = grp["Total"] / n_weeks
    grp["Avg_Month"] = grp["Total"] / n_months
    grp["Share_Pct"] = (grp["Total"] / grand_tot) * 100.0
    grp = grp.sort_values("Avg_Month", ascending=False).reset_index(drop=True)

    tot_row = {
        "total": float(grp["Total"].sum()),
        "avg_week": float(grp["Total"].sum()) / n_weeks,
        "avg_month": float(grp["Total"].sum()) / n_months,
        "count": int(grp["Count"].sum()),
    }
    return grp, tot_row


PALETA_PASTEL = [
    "#16A34A",
    "#DC2626",
    "#0284C7",
    "#CA8A04",
    "#7C3AED",
    "#EA580C",
    "#0D9488",
    "#B91C1C",
    "#15803D",
    "#4F46E5",
    "#D97706",
    "#0369A1"
]

PALETA_COSTOS = [
    "#DC2626", "#F97316", "#EAB308", "#EC4899", "#7C3AED", "#92400E"
]

PALETA_INGRESOS = [
    "#16A34A", "#0D9488", "#0284C7", "#84CC16", "#059669", "#06B6D4"
]

ICONOS_DISPONIBLES = [
    "🧾", "💡", "🚗", "👗", "🏠", "🛒", "🩺", "🏊‍♀️", "🧘‍♀️", "✈️",
    "📺", "🐾", "📚", "🎁", "💳", "💼", "💵", "👵", "📈", "📁",
    "💎", "🛠️", "🧹", "🍽️", "📱", "⛽", "📌",
    "🔨", "🧰", "🖌️", "🐜", "🚚", "🔑", "🛋️", "🛏️", "🖼️",
    "🧺", "🚨", "🚿", "❄️", "🌡️", "☀️", "🍎", "🥩", "🥖", "☕",
    "🧴", "🫧", "👕", "🧻", "🧽", "🪥", "🧼", "🚆", "🚕",
    "🏍️", "🛡️", "📋", "🔧", "🛞", "🅿️", "🏥", "🦷", "💊", "🧪",
    "🩻", "👓", "🦵", "🧠", "🥗", "🧥", "🕶️", "⌚", "🪡", "🎒",
    "💍", "💰", "🏦", "🪙", "📊", "🎓", "🎭", "🐶", "🐱"
]


# ----------------- SMART ICON PREDICTION -----------------
def predecir_icono_categoria(nombre, tipo="costo"):
    n = (nombre or "").upper().strip()
    reglas = [
        (["TAX", "ATO", "IMPUESTO", "MONOTRIBUTO", "AFIP", "ARBA", "RENTAS", "INMOBILIARIO", "CISI", "TASA"], "🧾"),
        (["UTILITY", "UTILITIES", "SERVICIO", "ELECTRIC", "POWER", "WATER", "GAS", "INTERNET", "WIFI", "PHONE", "MOBILE", "LUZ", "AGUA", "CLARO"], "💡"),
        (["CAR", "VEHICLE", "PETROL", "FUEL", "AUTO", "VEHICULO", "NAFTA", "REGO", "INSURANCE", "PARKING", "UBER", "TAXI", "TRANSPORT"], "🚗"),
        (["BEAUTY", "CLOTHES", "FASHION", "HAIR", "BELLEZA", "ESTETICA", "ROPA", "INDUMENTARIA"], "👗"),
        (["HEALTH", "MEDICAL", "PHARMACY", "DOCTOR", "DENTIST", "SALUD", "MEDICO", "FARMACIA"], "🩺"),
        (["SPORT", "GYM", "SWIM", "YOGA", "PADEL", "CLUB", "FITNESS", "DEPORTE", "GIMNASIO", "NATACION"], "🏊‍♀️"),
        (["GROCERY", "GROCERIES", "SUPERMARKET", "FOOD", "COLES", "WOOLWORTHS", "ALDI", "SUPERMERCADO", "COMIDA", "VERDURA"], "🛒"),
        (["HOME", "HOUSE", "RENT", "CLEANING", "MAINTENANCE", "CASA", "HOGAR", "ALQUILER", "LIMPIEZA", "ARREGLO"], "🏠"),
        (["STUDIO", "CLINIC", "OFFICE", "WORKSHOP", "GABINETE", "CONSULTORIO"], "🧘‍♀️"),
        (["HOLIDAY", "VACATION", "TRAVEL", "TRIP", "FLIGHT", "HOTEL", "VACACION", "VIAJE"], "✈️"),
        (["SUBSCRIPTION", "NETFLIX", "SPOTIFY", "DISNEY", "YOUTUBE", "AMAZON", "HBO", "SUSCRIPCION"], "📺"),
        (["PET", "DOG", "CAT", "VET", "MASCOTA", "PERRO", "GATO"], "🐾"),
        (["EDUCATION", "COURSE", "BOOK", "UNI", "COLLEGE", "EDUCACION", "CURSO", "LIBRO"], "📚"),
        (["GIFT", "BIRTHDAY", "DINING", "RESTAURANT", "CAFE", "COFFEE", "CINEMA", "REGALO", "SALIDA"], "🎁"),
        (["CARD", "CREDIT", "BANK", "LOAN", "DEBT", "TARJETA", "CREDITO", "BANCO", "PRESTAMO"], "💳"),
        (["WORK", "SALARY", "WAGE", "PAY", "JOB", "TRABAJO", "SUELDO", "SALARIO", "HONORARIO"], "💼"),
        (["PENSION", "RETIREMENT", "JUBILACION"], "👵"),
        (["INVEST", "DIVIDEND", "INTEREST", "RENTA", "INVERSION"], "📈"),
        (["OTHER", "MISC", "EXTRA", "OTRO", "VARIOS"], "💵" if tipo == "ingreso" else "📌"),
    ]
    for palabras, icono in reglas:
        if any(p in n for p in palabras):
            return icono
    return "💵" if tipo == "ingreso" else "📌"


# ----------------- INTERACTIVITY: DYNAMIC STYLES, PIE LEADERS & ANTI-POPUP -----------------
def activar_interactividad_avanzada(cats_costos=None, cats_ingresos=None, ubicaciones_guardadas=None, tooltip_cantidad=None):
    ubicaciones_json = json.dumps((ubicaciones_guardadas or [])[:8], ensure_ascii=False)
    tooltip_cant_json = json.dumps(tooltip_cantidad or "", ensure_ascii=False)
    js_code = r"""
    <script>
    (function() {
        const win = window.parent;
        const doc = win.document;
        const ubicacionesRecientes = __UBICACIONES_JSON__;
        const textoTooltipCantidad = __TOOLTIP_CANT_JSON__;

        // 0. Float the AI Advisor popover at bottom-right of the viewport
        function posicionarChatbotFlotante() {
            const popovers = doc.querySelectorAll('[data-testid="stPopover"]');
            popovers.forEach(pop => {
                const btn = pop.querySelector('button');
                if (btn && btn.innerText && btn.innerText.includes('AI Advisor')) {
                    pop.style.setProperty('position', 'fixed', 'important');
                    pop.style.setProperty('bottom', '62px', 'important');
                    pop.style.setProperty('right', '20px', 'important');
                    pop.style.setProperty('z-index', '999999', 'important');
                    pop.style.setProperty('width', 'auto', 'important');

                    btn.style.setProperty('border-radius', '999px', 'important');
                    btn.style.setProperty('background', 'linear-gradient(135deg, #0C4A6E, #0284C7)', 'important');
                    btn.style.setProperty('color', '#FFFFFF', 'important');
                    btn.style.setProperty('border', 'none', 'important');
                    btn.style.setProperty('padding', '12px 20px', 'important');
                    btn.style.setProperty('box-shadow', '0 8px 24px rgba(12, 74, 110, 0.30)', 'important');
                    btn.style.setProperty('font-weight', '700', 'important');
                    const ps = btn.querySelectorAll('p, span');
                    ps.forEach(el => el.style.setProperty('color', '#FFFFFF', 'important'));
                }
            });
        }

        // 1. Align "⇄" cycle-tabs button right after the last tab on desktop (or pinned right on mobile scroll)
        function estilizarSolapas() {
            const tabLists = doc.querySelectorAll('[data-baseweb="tab-list"]');
            if (tabLists.length > 0) {
                const tl = tabLists[0];
                const mainTabBtns = tl.querySelectorAll('button[data-baseweb="tab"]');
                if (mainTabBtns.length > 0) {
                    const lastTab = mainTabBtns[mainTabBtns.length - 1];
                    const tlRect = tl.getBoundingClientRect();
                    const lastRect = lastTab.getBoundingClientRect();
                    doc.querySelectorAll('button').forEach(btn => {
                        if ((btn.innerText || '').trim() === '⇄') {
                            const elemCont = btn.closest('[data-testid="stElementContainer"]') || btn.closest('[data-testid="element-container"]');
                            if (elemCont) {
                                const hostRect = elemCont.getBoundingClientRect();
                                const fitsDesktop = (tl.scrollWidth <= tl.clientWidth + 4) && (lastRect.right + 48 < tlRect.right);
                                if (fitsDesktop && lastRect.width > 0 && hostRect.width > 0) {
                                    btn.style.setProperty('left', Math.round(lastRect.right - hostRect.left + 10) + 'px', 'important');
                                    btn.style.setProperty('right', 'auto', 'important');
                                } else {
                                    btn.style.setProperty('left', 'auto', 'important');
                                    btn.style.setProperty('right', '2px', 'important');
                                }
                            }
                        }
                    });
                }
            }
        }

        // 2. Hide "Press Enter to apply" and shield inputs against password manager popups
        function limpiarInputsYPopups() {
            const instrucciones = doc.querySelectorAll('[data-testid="InputInstructions"]');
            instrucciones.forEach(el => {
                el.style.display = 'none';
                el.style.visibility = 'hidden';
            });

            const sidebar = doc.querySelector('[data-testid="stSidebar"]');
            const inputs = doc.querySelectorAll('input');
            inputs.forEach((inp, idx) => {
                const enSidebar = sidebar && sidebar.contains(inp);
                if (inp.getAttribute('data-clean-autofill') !== 'true') {
                    inp.setAttribute('data-clean-autofill', 'true');
                    inp.setAttribute('autocomplete', enSidebar ? 'one-time-code' : 'off');
                    inp.setAttribute('autocorrect', 'off');
                    inp.setAttribute('autocapitalize', 'off');
                    inp.setAttribute('spellcheck', 'false');
                    inp.setAttribute('data-ddg-inputtype', 'unknown');
                    inp.setAttribute('data-1p-ignore', 'true');
                    inp.setAttribute('data-lpignore', 'true');
                    inp.setAttribute('data-bwignore', 'true');
                    inp.setAttribute('data-form-type', 'other');
                }

                if (enSidebar && inp.type !== 'checkbox') {
                    inp.setAttribute('autocomplete', 'one-time-code');
                    inp.setAttribute('name', 'finapp_cfg_field_' + idx);
                    const ariaLbl = (inp.getAttribute('aria-label') || '');
                    if (ariaLbl.includes('App Password') || ariaLbl.includes('API Key')) {
                        inp.style.webkitTextSecurity = 'disc';
                    }
                    if (inp.getAttribute('data-readonly-shield') !== 'true') {
                        inp.setAttribute('data-readonly-shield', 'true');
                        if (doc.activeElement !== inp) {
                            inp.readOnly = true;
                        }
                        inp.addEventListener('pointerdown', function() {
                            inp.readOnly = false;
                        });
                        inp.addEventListener('focus', function() {
                            setTimeout(() => { inp.readOnly = false; }, 15);
                        });
                        inp.addEventListener('blur', function() {
                            inp.readOnly = true;
                        });
                    }
                }
            });

            const extNodes = doc.querySelectorAll('ddg-autofill, [data-ddg-autofill], .fx-relay-icon, firefox-private-relay-addon-data');
            extNodes.forEach(n => n.remove());
        }

        // 3. Highlight "+ ADD NEW CATEGORY" and compact ▲ / ▼ buttons
        function estilizarSolapasYBotonesOrden() {
            const todosDetails = Array.from(doc.querySelectorAll('details'));
            todosDetails.forEach(det => {
                const sum = det.querySelector('summary');
                if (!sum) return;
                const txt = (sum.innerText || sum.textContent || '').toUpperCase();

                if (txt.includes('ADD NEW COST CATEGORY')) {
                    det.setAttribute('data-add-cat', 'costo');
                    det.style.setProperty('background-color', '#FFF2EE', 'important');
                    det.style.setProperty('border', '2px solid #E07A5F', 'important');
                    det.style.setProperty('border-radius', '16px', 'important');
                    det.style.setProperty('margin-bottom', '14px', 'important');
                    det.style.setProperty('box-shadow', '0 4px 12px rgba(224, 122, 95, 0.16)', 'important');
                    sum.style.setProperty('background-color', '#FADBD8', 'important');
                    sum.style.setProperty('color', '#922B21', 'important');
                    sum.style.setProperty('font-weight', '800', 'important');
                    sum.style.setProperty('border-radius', '14px', 'important');
                    sum.style.setProperty('padding', '12px 16px', 'important');
                    sum.querySelectorAll('p, span, svg').forEach(el => {
                        el.style.setProperty('color', '#922B21', 'important');
                        el.style.setProperty('fill', '#922B21', 'important');
                        el.style.setProperty('font-weight', '800', 'important');
                    });
                } else if (txt.includes('ADD NEW INCOME CATEGORY')) {
                    det.setAttribute('data-add-cat', 'ingreso');
                    det.style.setProperty('background-color', '#ECFDF5', 'important');
                    det.style.setProperty('border', '2px solid #48C9B0', 'important');
                    det.style.setProperty('border-radius', '16px', 'important');
                    det.style.setProperty('margin-bottom', '14px', 'important');
                    det.style.setProperty('box-shadow', '0 4px 12px rgba(72, 201, 176, 0.16)', 'important');
                    sum.style.setProperty('background-color', '#D1F2EB', 'important');
                    sum.style.setProperty('color', '#0E6251', 'important');
                    sum.style.setProperty('font-weight', '800', 'important');
                    sum.style.setProperty('border-radius', '14px', 'important');
                    sum.style.setProperty('padding', '12px 16px', 'important');
                    sum.querySelectorAll('p, span, svg').forEach(el => {
                        el.style.setProperty('color', '#0E6251', 'important');
                        el.style.setProperty('fill', '#0E6251', 'important');
                        el.style.setProperty('font-weight', '800', 'important');
                    });
                }
            });

            const botones = Array.from(doc.querySelectorAll('button'));
            botones.forEach(btn => {
                const t = (btn.innerText || btn.textContent || '').trim();
                if (t === '▲' || t === '▼') {
                    btn.classList.add('btn-flecha-cat');
                    btn.style.setProperty('height', '21px', 'important');
                    btn.style.setProperty('min-height', '21px', 'important');
                    btn.style.setProperty('max-height', '21px', 'important');
                    btn.style.setProperty('width', '28px', 'important');
                    btn.style.setProperty('min-width', '28px', 'important');
                    btn.style.setProperty('padding', '0px', 'important');
                    btn.style.setProperty('margin', '0px', 'important');
                    btn.style.setProperty('border-radius', '6px', 'important');
                    btn.style.setProperty('line-height', '1', 'important');
                    btn.querySelectorAll('p, span, div').forEach(ch => {
                        ch.style.setProperty('font-size', '0.68rem', 'important');
                        ch.style.setProperty('line-height', '1', 'important');
                        ch.style.setProperty('margin', '0px', 'important');
                        ch.style.setProperty('padding', '0px', 'important');
                    });
                    const col = btn.closest('[data-testid="stColumn"]');
                    if (col && !col.querySelector('[data-testid="stColumn"]')) {
                        const innerVb = col.querySelector('[data-testid="stVerticalBlock"]');
                        if (innerVb) {
                            innerVb.style.setProperty('gap', '2px', 'important');
                        }
                    }
                } else if (t === '+') {
                    btn.classList.add('btn-mas-trebol');
                    btn.setAttribute('title', 'Add category');
                    btn.style.setProperty('background', '#38BDF8', 'important');
                    btn.style.setProperty('background-color', '#38BDF8', 'important');
                    btn.style.setProperty('border', '1.5px solid #0284C7', 'important');
                    btn.style.setProperty('color', '#FFFFFF', 'important');
                    btn.style.setProperty('width', '38px', 'important');
                    btn.style.setProperty('min-width', '38px', 'important');
                    btn.style.setProperty('max-width', '38px', 'important');
                    btn.style.setProperty('height', '38px', 'important');
                    btn.style.setProperty('min-height', '38px', 'important');
                    btn.style.setProperty('padding', '0px', 'important');
                    btn.style.setProperty('border-radius', '10px', 'important');
                    btn.style.setProperty('display', 'inline-flex', 'important');
                    btn.style.setProperty('align-items', 'center', 'important');
                    btn.style.setProperty('justify-content', 'center', 'important');
                    btn.querySelectorAll('p, span, div').forEach(ch => {
                        ch.style.setProperty('color', '#FFFFFF', 'important');
                        ch.style.setProperty('font-size', '1.35rem', 'important');
                        ch.style.setProperty('font-weight', '800', 'important');
                        ch.style.setProperty('line-height', '1', 'important');
                        ch.style.setProperty('margin', '0px', 'important');
                        ch.style.setProperty('padding', '0px', 'important');
                    });
                } else if (t === '🗑️' && (btn.getAttribute('title') === 'Delete category' || btn.closest('.contenedor-del-cat-vacia'))) {
                    btn.classList.add('btn-eliminar-cat-vacia');
                    btn.setAttribute('title', 'Delete category');
                    btn.style.setProperty('display', 'inline-flex', 'important');
                    btn.style.setProperty('align-items', 'center', 'important');
                    btn.style.setProperty('justify-content', 'center', 'important');
                    btn.style.setProperty('width', '46px', 'important');
                    btn.style.setProperty('min-width', '46px', 'important');
                    btn.style.setProperty('max-width', '46px', 'important');
                    btn.style.setProperty('height', '44px', 'important');
                    btn.style.setProperty('min-height', '44px', 'important');
                    btn.style.setProperty('padding', '0px', 'important');
                    btn.style.setProperty('border-radius', '10px', 'important');
                    btn.style.setProperty('background-color', '#FFF5F5', 'important');
                    btn.style.setProperty('border', '1.5px solid #F5B7B1', 'important');
                    btn.querySelectorAll('p, span, div').forEach(ch => {
                        ch.style.setProperty('font-size', '1.5rem', 'important');
                        ch.style.setProperty('line-height', '1', 'important');
                        ch.style.setProperty('margin', '0px', 'important');
                        ch.style.setProperty('padding', '0px', 'important');
                    });
                }
            });
        }

        // 4. Ensure leader lines on all outside pie chart labels
        function asegurarLineasConectorasTortas() {
            const pieLayers = doc.querySelectorAll('g.pielayer');
            pieLayers.forEach(layer => {
                const traces = layer.querySelectorAll('g.trace');
                traces.forEach(trace => {
                    const slices = Array.from(trace.querySelectorAll('g.slice'));
                    if (slices.length === 0) return;

                    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
                    slices.forEach(sl => {
                        const surf = sl.querySelector('path.surface');
                        if (!surf || !surf.getBBox) return;
                        try {
                            const b = surf.getBBox();
                            if (b.width > 0 && b.height > 0) {
                                minX = Math.min(minX, b.x);
                                minY = Math.min(minY, b.y);
                                maxX = Math.max(maxX, b.x + b.width);
                                maxY = Math.max(maxY, b.y + b.height);
                            }
                        } catch (e) {}
                    });

                    if (!isFinite(minX) || !isFinite(maxX)) return;
                    const cx = (minX + maxX) / 2;
                    const cy = (minY + maxY) / 2;
                    const R = Math.max(maxX - minX, maxY - minY) / 2;
                    if (R <= 10) return;

                    slices.forEach(sl => {
                        const existingLine = sl.querySelector('path.textline:not(.jardin-leader-line)');
                        if (existingLine && (existingLine.getAttribute('d') || '').trim().length > 0) {
                            existingLine.style.stroke = '#1F2937';
                            existingLine.style.strokeWidth = '1.5px';
                            const oldCustom = sl.querySelector('path.jardin-leader-line');
                            if (oldCustom) oldCustom.remove();
                            return;
                        }

                        const stext = sl.querySelector('g.slicetext');
                        if (!stext || !stext.getBBox) return;
                        try {
                            const tb = stext.getBBox();
                            if (tb.width === 0 && tb.height === 0) return;
                            const tx = tb.x + tb.width / 2;
                            const ty = tb.y + tb.height / 2;
                            const dist = Math.hypot(tx - cx, ty - cy);

                            if (dist > R * 0.96) {
                                const angle = Math.atan2(ty - cy, tx - cx);
                                const sx = cx + (R - 2) * Math.cos(angle);
                                const sy = cy + (R - 2) * Math.sin(angle);
                                const ex = cx + (R + 10) * Math.cos(angle);
                                const ey = cy + (R + 10) * Math.sin(angle);
                                const dirX = tx >= cx ? 1 : -1;
                                const endX = ex + dirX * 6;
                                const endY = ey;

                                let customLine = sl.querySelector('path.jardin-leader-line');
                                if (!customLine) {
                                    customLine = doc.createElementNS('http://www.w3.org/2000/svg', 'path');
                                    customLine.setAttribute('class', 'textline jardin-leader-line');
                                    customLine.style.fill = 'none';
                                    customLine.style.stroke = '#1F2937';
                                    customLine.style.strokeWidth = '1.5px';
                                    customLine.style.strokeOpacity = '1';
                                    sl.insertBefore(customLine, stext);
                                }
                                customLine.setAttribute(
                                    'd',
                                    'M' + sx.toFixed(1) + ',' + sy.toFixed(1) +
                                    'L' + ex.toFixed(1) + ',' + ey.toFixed(1) +
                                    'L' + endX.toFixed(1) + ',' + endY.toFixed(1)
                                );
                            } else {
                                const oldLine = sl.querySelector('path.jardin-leader-line');
                                if (oldLine) oldLine.remove();
                            }
                        } catch (e) {}
                    });
                });
            });
        }

        // 5. Tooltip on "3. Quantity Held" & clean Refresh button in sidebar
        function configurarTooltipCantidadYBotones() {
            const oldMenu = doc.getElementById('jardin-ubicacion-dropdown');
            if (oldMenu) oldMenu.remove();

            const inpCant = doc.querySelector('input[aria-label="3. Quantity Held"]');
            if (inpCant) {
                inpCant.removeAttribute('title');
                const stInputBox = inpCant.closest('[data-testid="stTextInput"]') || inpCant.parentElement;
                if (stInputBox && textoTooltipCantidad) {
                    stInputBox.classList.add('jardin-cant-tooltip-wrap');
                    stInputBox.setAttribute('data-tooltip', textoTooltipCantidad);
                    stInputBox.querySelectorAll('[title]').forEach(el => el.removeAttribute('title'));
                    const helpTarget = stInputBox.querySelector('[data-testid="stTooltipHoverTarget"]');
                    if (helpTarget) {
                        helpTarget.style.pointerEvents = 'none';
                    }
                }
            }

            const sidebar = doc.querySelector('[data-testid="stSidebar"]');
            if (sidebar) {
                sidebar.querySelectorAll('button').forEach(btn => {
                    const txt = (btn.innerText || btn.textContent || '').trim();
                    if (txt.includes('Refresh')) {
                        btn.style.setProperty('background', '#E0F2FE', 'important');
                        btn.style.setProperty('background-color', '#E0F2FE', 'important');
                        btn.style.setProperty('border', '1.5px solid #7DD3FC', 'important');
                        btn.style.setProperty('color', '#0C4A6E', 'important');
                        btn.style.setProperty('font-weight', '700', 'important');
                        btn.style.setProperty('border-radius', '12px', 'important');
                        btn.querySelectorAll('p, span, div').forEach(ch => {
                            ch.style.setProperty('color', '#0C4A6E', 'important');
                            ch.style.setProperty('font-weight', '700', 'important');
                        });
                    }
                });
            }
        }

        function actualizarInterfaz() {
            function actualizarRelojGuardado() {
            const el = doc.getElementById('finapp-last-saved');
            if (!el) return;
            const iso = el.getAttribute('data-saved-ts');
            if (!iso) return;
            const savedMs = Date.parse(iso);
            if (isNaN(savedMs)) return;
            const now = new Date();
            const diffSec = Math.max(0, Math.floor((now.getTime() - savedMs) / 1000));
            const savedDate = new Date(savedMs);
            const dayDiff = Math.floor((new Date(now.getFullYear(), now.getMonth(), now.getDate()) - new Date(savedDate.getFullYear(), savedDate.getMonth(), savedDate.getDate())) / 86400000);
            let txt = 'Last saved just now';
            if (diffSec < 60) {
                txt = 'Last saved just now';
            } else if (diffSec < 3600) {
                const m = Math.floor(diffSec / 60);
                txt = 'Last saved ' + (m === 1 ? '1 minute ago' : m + ' minutes ago');
            } else if (dayDiff <= 0) {
                const h = Math.floor(diffSec / 3600);
                txt = 'Last saved ' + (h === 1 ? '1 hour ago' : h + ' hours ago');
            } else if (dayDiff === 1) {
                txt = 'Last saved yesterday';
            } else {
                txt = 'Last saved ' + dayDiff + ' days ago';
            }
            if (el.textContent !== txt) el.textContent = txt;
        }
        actualizarRelojGuardado();
        if (!win._finappLastSavedTimer) {
            win._finappLastSavedTimer = win.setInterval(actualizarRelojGuardado, 15000);
        }
        function sincronizarTemaOscuro() {
            let isDark = false;
            try {
                const candidates = [
                    doc.querySelector('[data-testid="stAppViewContainer"]'),
                    doc.querySelector('.stApp'),
                    doc.body,
                    doc.documentElement
                ];
                for (const el of candidates) {
                    if (!el) continue;
                    const bgStr = win.getComputedStyle(el).backgroundColor || '';
                    const m = bgStr.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/i);
                    if (m) {
                        const alpha = m[4] !== undefined ? parseFloat(m[4]) : 1.0;
                        if (alpha > 0.1) {
                            const lum = (0.299 * parseInt(m[1], 10) + 0.587 * parseInt(m[2], 10) + 0.114 * parseInt(m[3], 10)) / 255;
                            isDark = lum < 0.5;
                            break;
                        }
                    }
                }
            } catch (e) {}
            doc.documentElement.setAttribute('data-finapp-theme', isDark ? 'dark' : 'light');

            const inkCol = isDark ? '#F3F4F6' : '#1F2937';
            const pieOutCol = isDark ? '#F3F4F6' : '#111828';
            const lineCol = isDark ? '#CBD5E1' : '#1F2937';
            doc.querySelectorAll('.js-plotly-plot svg').forEach(svg => {
                svg.querySelectorAll('.bartext, .ytick text, .xtick text, .gtitle').forEach(t => {
                    t.style.setProperty('fill', inkCol, 'important');
                });
                svg.querySelectorAll('.pie .slicetext text').forEach(t => {
                    const curFill = (t.style.fill || t.getAttribute('fill') || '').toLowerCase();
                    if (curFill === '#111828' || curFill === 'rgb(17, 24, 40)' || curFill === '#f3f4f6' || curFill === 'rgb(243, 244, 246)') {
                        t.style.setProperty('fill', pieOutCol, 'important');
                    }
                });
                svg.querySelectorAll('path.jardin-leader-line, .pie path.textline').forEach(p => {
                    p.style.setProperty('stroke', lineCol, 'important');
                });
            });
        }
        sincronizarTemaOscuro();
        posicionarChatbotFlotante();
            estilizarSolapas();
            limpiarInputsYPopups();
            estilizarSolapasYBotonesOrden();
            asegurarLineasConectorasTortas();
            configurarTooltipCantidadYBotones();
        }

        if (win.__jardinCleanupListeners) {
            try { win.__jardinCleanupListeners(); } catch (e) {}
        }

        const abortCtrl = new AbortController();
        const sig = abortCtrl.signal;

        doc.addEventListener('keydown', function(e) {
            const active = doc.activeElement;
            if (!active || active.tagName !== 'INPUT') return;

            if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                const inputs = Array.from(
                    doc.querySelectorAll(
                        'input:not([disabled]):not([type="hidden"]):not([type="checkbox"])'
                    )
                ).filter(el => el.offsetParent !== null);

                const idx = inputs.indexOf(active);
                if (idx !== -1) {
                    e.preventDefault();
                    e.stopPropagation();
                    const nextIdx = e.key === 'ArrowDown' ? idx + 1 : idx - 1;
                    if (nextIdx >= 0 && nextIdx < inputs.length) {
                        inputs[nextIdx].focus();
                        if (inputs[nextIdx].select) {
                            inputs[nextIdx].select();
                        }
                    }
                }
            }
        }, { capture: true, signal: sig });

        doc.addEventListener('click', function() {
            setTimeout(estilizarSolapas, 30);
        }, { capture: true, signal: sig });

        let timerObs = null;
        const obs = new MutationObserver(() => {
            clearTimeout(timerObs);
            timerObs = setTimeout(actualizarInterfaz, 90);
        });
        obs.observe(doc.body, { childList: true, subtree: true });

        win.__jardinCleanupListeners = function() {
            abortCtrl.abort();
            obs.disconnect();
        };

        actualizarInterfaz();
        setTimeout(actualizarInterfaz, 150);
        setTimeout(actualizarInterfaz, 450);
    })();
    </script>
    """
    js_final = js_code.replace("__UBICACIONES_JSON__", ubicaciones_json).replace("__TOOLTIP_CANT_JSON__", tooltip_cant_json)
    components.html(js_final, height=0, width=0)


# ----------------- FINANCIAL HEALTH SUMMARY CARD (AUD ONLY) -----------------
def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(rgb[0])))),
        max(0, min(255, int(round(rgb[1])))),
        max(0, min(255, int(round(rgb[2]))))
    )


def _lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, float(t)))
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex((r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t))


def _multi_color(stops, score):
    s = max(0.0, min(1.0, float(score)))
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if p0 <= s <= p1:
            local_t = (s - p0) / (p1 - p0) if p1 > p0 else 0.0
            return _lerp_color(c0, c1, local_t)
    return stops[-1][1]


def construir_html_panel_patrimonio(
    total_patrimonio_aud,
    cant_activos_contemplados,
    cant_activos_totales,
    ingreso_mensual_aud,
    costo_mensual_aud,
    datos_faltantes=False
):
    if datos_faltantes or (ingreso_mensual_aud <= 0 and costo_mensual_aud <= 0):
        score = 0.5
        mensaje_salud = "Add your income and costs to see your financial health"
    else:
        monthly_saving = float(ingreso_mensual_aud) - float(costo_mensual_aud)

        if abs(monthly_saving) < 0.005:
            score = 1.0
            mensaje_salud = "Balanced: your monthly savings are $0 AUD and your net worth stays intact."
        elif monthly_saving > 0:
            score = 1.0
            mensaje_salud = (
                f"Great shape: you save ${monthly_saving:,.0f} AUD/month and your net worth is growing."
            )
        else:
            perdida_mensual = abs(monthly_saving)
            if total_patrimonio_aud <= 0:
                score = 0.0
                mensaje_salud = "Alert: at this spending rate you have 0 months of runway left."
            else:
                months_left = float(total_patrimonio_aud) / float(perdida_mensual)
                meses_int = max(0, int(round(months_left)))
                anios_s = meses_int // 12
                meses_rem = meses_int % 12

                if meses_int <= 12:
                    tiempo_str = f"{meses_int} months"
                else:
                    tiempo_str = f"{anios_s} years and {meses_rem} months"

                if months_left >= 60.0:
                    score = 1.0
                elif months_left <= 12.0:
                    score = 0.0
                else:
                    score = (months_left - 12.0) / (60.0 - 12.0)

                if months_left <= 12.0:
                    mensaje_salud = f"Alert: at this rate you have {tiempo_str} of runway left."
                else:
                    mensaje_salud = (
                        f"Negative monthly savings (−${perdida_mensual:,.0f} AUD): "
                        f"at this rate your net worth lasts {tiempo_str}."
                    )

    border_col = _multi_color([
        (0.0, "#EF4444"),
        (0.35, "#F59E0B"),
        (0.70, "#84CC16"),
        (1.0, "#0EA5E9")
    ], score)
    pct_salud = int(round(score * 100))
    badge_bg = _multi_color([
        (0.0, "#FEE2E2"),
        (0.35, "#FEF3C7"),
        (0.75, "#DCFCE7"),
        (1.0, "#E0F2FE")
    ], score)
    badge_text = _multi_color([
        (0.0, "#991B1B"),
        (0.35, "#92400E"),
        (0.75, "#166534"),
        (1.0, "#0C4A6E")
    ], score)

    return f"""
    <div style="background: #F8FAFC; border: 2px solid {border_col}; border-left: 8px solid {border_col};
                border-radius: 16px; padding: 18px 22px; margin-bottom: 1.1rem;
                box-shadow: 0 4px 14px rgba(0, 0, 0, 0.06);">
        <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px;">
            <div>
                <div style="font-size: 1.05rem; font-weight: 700; color: #334155;">Total Net Worth</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: #0F172A; line-height: 1.15;">${total_patrimonio_aud:,.2f} AUD</div>
                <div style="font-size: 0.9rem; font-weight: 600; color: #475569; margin-top: 4px;">
                    {cant_activos_contemplados} of {cant_activos_totales} assets included
                </div>
            </div>
            <div style="flex: 1; min-width: 260px; max-width: 540px; background: {badge_bg}; color: {badge_text};
                        border: 1.5px solid {border_col}; border-radius: 12px; padding: 12px 16px;">
                <div style="font-size: 0.95rem; font-weight: 800; line-height: 1.35;">{mensaje_salud}</div>
                <div class="jardin-health-bar-track" style="margin-top: 8px;">
                    <div class="jardin-health-bar-fill" style="width: {pct_salud}%; background: {border_col};"></div>
                </div>
            </div>
        </div>
    </div>
    """


# ----------------- 2D PIE CHART WITH 1 DECIMAL & NO POPUPS -----------------
def formatear_etiqueta_torta(texto, usar_minusculas=False):
    t = str(texto or "").strip()
    if not t:
        return t
    if usar_minusculas:
        return t[0].upper() + t[1:].lower()
    return t


def _detectar_tema_oscuro():
    try:
        ctx_theme = getattr(getattr(st, "context", None), "theme", None)
        t_type = getattr(ctx_theme, "type", None)
        if isinstance(t_type, str) and t_type.lower() in ("dark", "light"):
            return t_type.lower() == "dark"
    except Exception:
        pass
    return False


def crear_torta_2d(df, col_valores, col_nombres, tamano="mediano", usar_minusculas=False, paleta=None):
    valores = df[col_valores].tolist()
    nombres = [formatear_etiqueta_torta(nom, usar_minusculas=usar_minusculas) for nom in df[col_nombres].tolist()]
    total = sum(valores) if sum(valores) > 0 else 1.0
    n = len(valores)

    _pal_usar = paleta if paleta else PALETA_PASTEL
    colores = [_pal_usar[i % len(_pal_usar)] for i in range(n)]
    colores_claros = {"#EAB308", "#84CC16", "#FACC15", "#FDE047"}
    inside_text_cols = ["#111827" if c.upper() in colores_claros else "#FFFFFF" for c in colores]

    textos_torta = [
        f"{nom}<br>{((v / total) * 100):.1f}%"
        for nom, v in zip(nombres, valores)
    ]

    umbral_externo = 0.09 if tamano == "grande" else 0.08
    posiciones = [
        "outside" if (v / total) < umbral_externo else "inside"
        for v in valores
    ]

    if tamano == "grande":
        altura = 550
        tam_fuente = 14
        min_fuente = 12
        agujero = 0.32
        margenes = dict(t=50, b=50, l=55, r=55)
    elif tamano == "chico":
        altura = 350
        tam_fuente = 14
        min_fuente = 12
        agujero = 0.38
        margenes = dict(t=42, b=42, l=50, r=50)
    else:
        altura = 430
        tam_fuente = 14
        min_fuente = 12
        agujero = 0.36
        margenes = dict(t=40, b=40, l=40, r=40)

    fig = go.Figure(data=[go.Pie(
        labels=nombres,
        values=valores,
        text=textos_torta,
        textinfo="text",
        hoverinfo="skip",
        hovertemplate=None,
        hole=agujero,
        sort=True,
        direction="clockwise",
        textposition=posiciones,
        insidetextorientation="horizontal",
        pull=[0.012] * n,
        automargin=True,
        insidetextfont=dict(
            size=tam_fuente,
            color=inside_text_cols,
            family="Arial, sans-serif"
        ),
        outsidetextfont=dict(
            size=tam_fuente,
            color="#F3F4F6" if _detectar_tema_oscuro() else "#111828",
            family="Arial, sans-serif"
        ),
        marker=dict(
            colors=colores,
            line=dict(color="#FFFFFF", width=2)
        ),
        showlegend=False
    )])

    fig.update_layout(
        uniformtext=dict(minsize=min_fuente, mode="show"),
        height=altura,
        margin=margenes,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        dragmode=False,
        hovermode=False
    )
    return fig


# ----------------- CLEAN HORIZONTAL BAR CHART (AUD) -----------------
def crear_barras_horizontales(df, col_valores, col_nombres, color_barra=None):
    df_ord = df.sort_values(by=col_valores, ascending=True).copy()
    valores = df_ord[col_valores].tolist()
    nombres = df_ord[col_nombres].tolist()
    total = sum(valores) if sum(valores) > 0 else 1.0
    max_val = max(valores) if valores else 1.0
    n = len(valores)

    if color_barra:
        colores = [color_barra for _ in valores]
    else:
        colores = ["#DC2626" if (idx_b + 1) / max(n, 1) > 0.5 else "#16A34A" for idx_b, _ in enumerate(valores)]

    textos = [f"  ${v:,.0f} AUD ({(v / total) * 100:.1f}%)" for v in valores]

    fig = go.Figure(data=[go.Bar(
        x=valores,
        y=nombres,
        orientation="h",
        text=textos,
        textposition="outside",
        cliponaxis=False,
        textfont=dict(
            size=14,
            color="#F3F4F6" if _detectar_tema_oscuro() else "#1F2937",
            family="Arial, sans-serif"
        ),
        marker=dict(
            color=colores,
            line=dict(color="#6B7280", width=1.2)
        ),
        hoverinfo="skip"
    )])

    altura_dinamica = max(300, n * 48 + 40)

    fig.update_layout(
        height=altura_dinamica,
        margin=dict(t=15, b=15, l=10, r=140),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        dragmode=False,
        xaxis=dict(
            visible=False,
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            showline=False,
            title="",
            range=[0, max_val * 1.48]
        ),
        yaxis=dict(
            showgrid=False,
            zeroline=False,
            showline=False,
            title="",
            automargin=True,
            tickfont=dict(
                size=13,
                color="#F3F4F6" if _detectar_tema_oscuro() else "#1F2937",
                family="Arial, sans-serif"
            )
        )
    )
    return fig


def formatear_cant(valor):
    try:
        num = float(valor)
        if num.is_integer():
            return str(int(num))
        return f"{num:.6f}".rstrip("0").rstrip(".")
    except Exception:
        return str(valor)


def clasificar_costo_existente(nombre):
    n = (nombre or "").upper().strip()
    if any(k in n for k in ["TAX", "INMOBILIARIO", "CISI", "COSI", "AUTOMOTOR", "IMPUESTO"]):
        return "TAXES"
    if any(k in n for k in ["SAT", "EDET", "GAS", "CLARO", "LIGHT", "WATER", "INTERNET", "UTILITY"]):
        return "UTILITIES"
    if any(k in n for k in ["NETFLIX", "DISNEY", "SPOTIFY", "FLOW", "YOUTUBE"]):
        return "SUBSCRIPTIONS"
    if any(k in n for k in ["PETROL", "FUEL", "NAFTA", "INSURANCE", "SEGURO", "CAR", "AUTO", "REGO"]):
        return "TRANSPORT"
    return "HOME & OTHERS"


# ----------------- TOP 100 STOCKS, TOP 100 CRYPTOS, BONDS & PLATFORMS -----------------
ACCIONES_100_BASE = [
    "AAPL (Apple)", "MSFT (Microsoft)", "NVDA (Nvidia)", "GOOGL (Alphabet / Google)",
    "AMZN (Amazon)", "META (Meta Platforms)", "TSLA (Tesla)", "BRK-B (Berkshire Hathaway)",
    "MELI (MercadoLibre)", "KO (Coca-Cola)", "SPY (S&P 500 ETF)", "QQQ (Nasdaq 100 ETF)",
    "DIA (Dow Jones ETF)", "YPFD (YPF)", "GGAL (Grupo Financiero Galicia)", "BMA (Banco Macro)",
    "PAM (Pampa Energía)", "VIST (Vista Energy)", "TGS (Transportadora de Gas del Sur)",
    "CEPU (Central Puerto)", "GLOB (Globant)", "LLY (Eli Lilly)", "AVGO (Broadcom)",
    "JPM (JPMorgan Chase)", "V (Visa)", "WMT (Walmart)", "XOM (Exxon Mobil)",
    "MA (Mastercard)", "UNH (UnitedHealth)", "COST (Costco)", "PG (Procter & Gamble)",
    "JNJ (Johnson & Johnson)", "HD (Home Depot)", "NFLX (Netflix)", "ABBV (AbbVie)",
    "BAC (Bank of America)", "CRM (Salesforce)", "ORCL (Oracle)", "CVX (Chevron)",
    "MRK (Merck)", "AMD (Advanced Micro Devices)", "PEP (PepsiCo)", "TMO (Thermo Fisher)",
    "LIN (Linde)", "CSCO (Cisco Systems)", "ACN (Accenture)", "ADBE (Adobe)",
    "WFC (Wells Fargo)", "MCD (McDonald's)", "ABT (Abbott Laboratories)", "DIS (Walt Disney)",
    "PM (Philip Morris)", "IBM (IBM)", "GE (General Electric)", "INTU (Intuit)",
    "CAT (Caterpillar)", "VZ (Verizon)", "QCOM (Qualcomm)", "TXN (Texas Instruments)",
    "NOW (ServiceNow)", "AMGN (Amgen)", "PFE (Pfizer)", "ISRG (Intuitive Surgical)",
    "UBER (Uber Technologies)", "GS (Goldman Sachs)", "MS (Morgan Stanley)",
    "AXP (American Express)", "RTX (Raytheon)", "SPGI (S&P Global)", "NEE (NextEra Energy)",
    "HON (Honeywell)", "UNP (Union Pacific)", "BKNG (Booking Holdings)", "LOW (Lowe's)",
    "T (AT&T)", "COP (ConocoPhillips)", "BLK (BlackRock)", "SYK (Stryker)",
    "TJX (TJX Companies)", "PGR (Progressive)", "C (Citigroup)", "SCHW (Charles Schwab)",
    "BA (Boeing)", "INTC (Intel)", "NKE (Nike)", "SBUX (Starbucks)", "DE (John Deere)",
    "LMT (Lockheed Martin)", "MDLZ (Mondelez)", "ADP (Automatic Data Processing)",
    "GILD (Gilead Sciences)", "BMY (Bristol-Myers Squibb)", "MU (Micron Technology)",
    "PANW (Palo Alto Networks)", "PLTR (Palantir Technologies)", "SHOP (Shopify)",
    "PYPL (PayPal)", "COIN (Coinbase)", "ABNB (Airbnb)", "TSM (Taiwan Semiconductor)",
    "ASML (ASML Holding)", "NVO (Novo Nordisk)", "TM (Toyota Motor)", "BABA (Alibaba)",
    "SONY (Sony Group)", "PBR (Petrobras)", "VALE (Vale)", "NU (Nu Holdings / Nubank)"
]

CRIPTOS_100_BASE = [
    "BTC (Bitcoin)", "ETH (Ethereum)", "USDT (Tether)", "BNB (BNB / Binance Coin)",
    "SOL (Solana)", "USDC (USD Coin)", "XRP (Ripple)", "DOGE (Dogecoin)",
    "TON (Toncoin)", "ADA (Cardano)", "TRX (TRON)", "AVAX (Avalanche)",
    "SHIB (Shiba Inu)", "LINK (Chainlink)", "DOT (Polkadot)", "BCH (Bitcoin Cash)",
    "NEAR (NEAR Protocol)", "LTC (Litecoin)", "MATIC (Polygon)", "POL (Polygon Ecosystem)",
    "DAI (Dai)", "UNI (Uniswap)", "ICP (Internet Computer)", "APT (Aptos)",
    "KAS (Kaspa)", "ETC (Ethereum Classic)", "XMR (Monero)", "STX (Stacks)",
    "FET (Fetch.ai / ASI)", "XLM (Stellar)", "OKB (OKB)", "FIL (Filecoin)",
    "SUI (Sui)", "ARB (Arbitrum)", "ATOM (Cosmos)", "IMX (Immutable)",
    "RENDER (Render)", "HBAR (Hedera)", "MNT (Mantle)", "CRO (Cronos)",
    "OP (Optimism)", "VET (VeChain)", "INJ (Injective)", "MKR (Maker)",
    "AAVE (Aave)", "GRT (The Graph)", "TAO (Bittensor)", "PEPE (Pepe)",
    "WIF (dogwifhat)", "FLOKI (Floki)", "BONK (Bonk)", "THETA (Theta Network)",
    "RUNE (THORChain)", "AR (Arweave)", "ALGO (Algorand)", "FTM (Fantom)",
    "SEI (Sei)", "FLOW (Flow)", "TIA (Celestia)", "LDO (Lido DAO)",
    "PYTH (Pyth Network)", "QNT (Quant)", "EGLD (MultiversX)", "AXS (Axie Infinity)",
    "SAND (The Sandbox)", "MANA (Decentraland)", "GALA (Gala)", "EOS (EOS)",
    "XTZ (Tezos)", "NEO (Neo)", "KAVA (Kava)", "CHZ (Chiliz)",
    "MINA (Mina Protocol)", "IOTA (IOTA)", "CFX (Conflux)", "JASMY (JasmyCoin)",
    "SNX (Synthetix)", "PENDLE (Pendle)", "STRK (Starknet)", "WLD (Worldcoin)",
    "JUP (Jupiter)", "ENA (Ethena)", "ONDO (Ondo)", "BEAM (Beam)",
    "DYDX (dYdX)", "CRV (Curve DAO)", "1INCH (1inch)", "COMP (Compound)",
    "ENS (Ethereum Name Service)", "CAKE (PancakeSwap)", "ZEC (Zcash)", "DASH (Dash)",
    "ROSE (Oasis Network)", "ZIL (Zilliqa)", "ENJ (Enjin Coin)", "BAT (Basic Attention Token)",
    "LRC (Loopring)", "QTUM (Qtum)", "CELO (Celo)", "ANKR (Ankr)"
]

BONOS_BASE = [
    "AL30 (Bonar 2030 Ley Arg.)", "GD30 (Global 2030 Ley NY)",
    "AL29 (Bonar 2029 Ley Arg.)", "GD29 (Global 2029 Ley NY)",
    "AL35 (Bonar 2035 Ley Arg.)", "GD35 (Global 2035 Ley NY)",
    "AE38 (Bonar 2038 Ley Arg.)", "GD38 (Global 2038 Ley NY)",
    "AL41 (Bonar 2041 Ley Arg.)", "GD41 (Global 2041 Ley NY)",
    "GD46 (Global 2046 Ley NY)", "BPY26 (Bopreal Serie 1 2026)",
    "BPJ25 (Bopreal Serie 2 2025)", "BPO27 (Bopreal Serie 3 2027)",
    "TX26 (Boncer 2026 CER)", "TX28 (Boncer 2028 CER)",
    "TZX26 (Boncer Cero 2026)", "TZX27 (Boncer Cero 2027)",
    "TZX28 (Boncer Cero 2028)", "DICP (Discount Pesos CER)",
    "PARP (Par Pesos CER)", "CUAP (Cuasipar Pesos CER)",
    "PR17 (Bono Consolidación)", "TVPP (Cupón PBI Pesos)",
    "TVPA (Cupón PBI USD Ley Arg.)", "TVPY (Cupón PBI USD Ley NY)",
    "S31E5 (Lecap Enero)", "S28F5 (Lecap Febrero)",
    "S31M5 (Lecap Marzo)", "S30J5 (Lecap Junio)",
    "S30S5 (Lecap Septiembre)", "T15D5 (Boncap Diciembre)",
    "YCA6O (ON YPF 2025)", "YMCHO (ON YPF 2026)",
    "MRCAO (ON Genneia)", "IRCFO (ON IRSA)",
    "TLCTO (ON Telecom)", "PNDCO (ON Pan American Energy)",
    "MGCHO (ON Pampa Energía)", "CS38O (ON Cresud)",
    "SHY (US Treasury 1-3Y)", "IEF (US Treasury 7-10Y)",
    "TLT (US Treasury 20+Y)", "TIP (US TIPS Inflation)"
]

UBICACIONES_BASE = [
    "Up Bank", "CommBank", "Macquarie", "Binance",
    "Nexo", "IOL", "Stake", "Mercado Pago"
]


def normalizar_tipo_activo_inv(tipo_raw):
    t = str(tipo_raw or "").strip()
    if t in ["Cash AUD", "A - Cash AUD", "AUD", "Efectivo / Banco"]:
        return "Cash AUD"
    if t in ["Pesos ARS", "A - Pesos ARS", "B - Pesos ARS"]:
        return "Cash AUD"
    if t in ["Dólares USD", "B - Dólares USD", "Dólar Billete", "A - Dólar Billete"]:
        return "Cash USD"
    if t in ["C - Stocks", "C - Acciones", "Stocks", "Acciones", "Acciones / CEDEARs"]:
        return "Stocks"
    if t in ["D - Cryptos", "Cryptos", "D - Criptomonedas", "Criptomonedas"]:
        return "Cryptos"
    if t in ["E - Bonds", "E - Bonos", "Bonds", "Bonos"]:
        return "Bonds"
    if t in ["F - FCI", "FCI"]:
        return "FCI"
    return "Others"


def reparar_inversiones_corruptas(inversiones):
    modificado = False
    for inv in (inversiones or []):
        inv.setdefault("activo_inv", True)
        tipo_norm = normalizar_tipo_activo_inv(inv.get("tipo", "Others"))
        if inv.get("tipo") != tipo_norm:
            inv["tipo"] = tipo_norm
            modificado = True
        if tipo_norm in ["Cryptos", "Stocks", "Bonds"]:
            det_str = str(inv.get("activo", "")).strip()
            det_ticker = det_str.split(" ")[0].upper()
            if det_ticker and det_ticker not in ["USD", "ARS", "AUD"] and inv.get("simbolo") != det_ticker:
                inv["simbolo"] = det_ticker
                modificado = True
    return modificado


def parsear_numero_flexible(texto):
    s = str(texto or "").strip().replace(" ", "")
    if not s:
        return 0.0
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def normalizar_lista_activos_con_base(lista_guardada, lista_base):
    mapa_base = {item.split(" ")[0].upper(): item for item in lista_base}
    resultado = list(lista_base)
    vistos = {item.split(" ")[0].upper() for item in resultado}
    for item in (lista_guardada or []):
        limpio = str(item or "").strip()
        if not limpio:
            continue
        ticker = limpio.split(" ")[0].upper()
        if ticker in mapa_base:
            continue
        if ticker not in vistos:
            resultado.append(limpio if "(" in limpio else limpio.upper())
            vistos.add(ticker)
    return resultado


def registrar_ubicacion_guardada(datos, nueva_ubicacion):
    loc = str(nueva_ubicacion or "").strip()
    if not loc or loc.lower() in ["sin especificar", "unspecified"]:
        return
    actuales = datos.get("ubicaciones_guardadas", list(UBICACIONES_BASE))
    filtradas = [u for u in actuales if str(u).strip() and str(u).strip().lower() != loc.lower()]
    filtradas.insert(0, loc)
    for ub in UBICACIONES_BASE:
        if not any(ub.lower() == u.lower() for u in filtradas):
            filtradas.append(ub)
    datos["ubicaciones_guardadas"] = filtradas
    ult = datos.setdefault("ultimas_selecciones_inv", {})
    ult["ubicacion"] = loc


# ----------------- DATA MANAGEMENT & PERSISTENCE -----------------
def cargar_datos():
    criptos_base = list(CRIPTOS_100_BASE)
    acciones_base = list(ACCIONES_100_BASE)
    hoy_sydney_str = datetime.now(TZ_SYDNEY).strftime("%Y-%m-%d")

    datos_por_defecto = {
        "ultima_actualizacion": hoy_sydney_str,
        "seguridad": {
            "usuario": "Julian",
            "password_actual": _obtener_password_secreto(),
            "passwords_validas": [_obtener_password_secreto()] if _obtener_password_secreto() else [],
            "email_recuperacion": "julianherrero.jh@gmail.com",
            "telefono_recuperacion": "+61493680014",
            "smtp_app_password": "",
            "whatsapp_apikey": ""
        },
        "categorias_costos": [
            "HOUSING",
            "UTILITIES",
            "TRANSPORT",
            "GROCERIES",
            "SUBSCRIPTIONS",
            "HOME & OTHERS"
        ],
        "iconos_costos": {
            "HOUSING": "🏠",
            "UTILITIES": "💡",
            "TRANSPORT": "🚗",
            "GROCERIES": "🛒",
            "SUBSCRIPTIONS": "📺",
            "HOME & OTHERS": "📌"
        },
        "costos": [
            {"grupo": "HOUSING", "categoria": "RENT", "monto": 1200, "activo": True},
            {"grupo": "UTILITIES", "categoria": "ELECTRICITY", "monto": 120, "activo": True},
            {"grupo": "UTILITIES", "categoria": "INTERNET", "monto": 75, "activo": True},
            {"grupo": "GROCERIES", "categoria": "SUPERMARKET", "monto": 400, "activo": True}
        ],
        "categorias_ingresos": [
            "Work",
            "Other Income"
        ],
        "iconos_ingresos": {
            "Work": "💼",
            "Other Income": "💵"
        },
        "ingresos": [
            {"grupo": "Work", "concepto": "SALARY", "monto": 3600, "activo": True}
        ],
        "criptos_guardadas": criptos_base,
        "acciones_guardadas": acciones_base,
        "bonos_guardadas": list(BONOS_BASE),
        "ubicaciones_guardadas": list(UBICACIONES_BASE),
        "ultimas_selecciones_inv": {
            "tipo": "A - Cash AUD",
            "accion": "AAPL (Apple)",
            "cripto": "BTC (Bitcoin)",
            "bono": "AL30 (Bonar 2030 Ley Arg.)",
            "ubicacion": "Up Bank"
        },
        "inversiones": [
            {
                "tipo": "Cryptos",
                "activo": "BTC",
                "simbolo": "BTC",
                "cantidad": 0.5,
                "plataforma": "Binance",
                "activo_inv": True
            }
        ],
        "historial_cierres": []
    }

    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            data.setdefault("ultima_actualizacion", hoy_sydney_str)

            seg = data.get("seguridad", {})
            seg["usuario"] = "Julian"
            pw_sec = _obtener_password_secreto()
            if pw_sec:
                seg["password_actual"] = pw_sec
            pw_val = [p for p in seg.get("passwords_validas", []) if p not in ["Finanzasmama123", "terapias123", "salchichudo22"]]
            if pw_sec and pw_sec not in pw_val:
                pw_val.append(pw_sec)
            seg["passwords_validas"] = pw_val
            if not seg.get("email_recuperacion"):
                seg["email_recuperacion"] = "julianherrero.jh@gmail.com"
            if not seg.get("telefono_recuperacion"):
                seg["telefono_recuperacion"] = "+61493680014"
            seg.setdefault("smtp_app_password", "")
            seg.setdefault("whatsapp_apikey", "")
            data["seguridad"] = seg

            for c in data.get("costos", []):
                c.setdefault("activo", True)
                if "grupo" not in c or not c["grupo"]:
                    c["grupo"] = clasificar_costo_existente(c.get("categoria", ""))

            for ing in data.get("ingresos", []):
                ing.setdefault("activo", True)
                if "grupo" not in ing or not ing["grupo"]:
                    nom_low = ing.get("concepto", "").lower()
                    if any(k in nom_low for k in ["salary", "wage", "sueldo", "sac", "work"]):
                        ing["grupo"] = "Work"
                    else:
                        ing["grupo"] = "Other Income"

            cats_c = list(dict.fromkeys(
                data.get("categorias_costos", datos_por_defecto["categorias_costos"])
                + [c["grupo"] for c in data.get("costos", [])]
            ))
            data["categorias_costos"] = cats_c

            cats_i = list(dict.fromkeys(
                data.get("categorias_ingresos", datos_por_defecto["categorias_ingresos"])
                + [i["grupo"] for i in data.get("ingresos", [])]
            ))
            data["categorias_ingresos"] = cats_i

            iconos_c = data.get("iconos_costos", {})
            for cat in cats_c:
                if cat not in iconos_c or not iconos_c[cat]:
                    iconos_c[cat] = predecir_icono_categoria(cat, "costo")
            data["iconos_costos"] = iconos_c

            iconos_i = data.get("iconos_ingresos", {})
            for cat in cats_i:
                if cat not in iconos_i or not iconos_i[cat]:
                    iconos_i[cat] = predecir_icono_categoria(cat, "ingreso")
            data["iconos_ingresos"] = iconos_i

            reparar_inversiones_corruptas(data.get("inversiones", []))

            criptos_guardadas_raw = data.get("criptos_guardadas", criptos_base)
            for inv in data.get("inversiones", []):
                if inv.get("tipo") == "Cryptos":
                    sim = inv.get("simbolo", "").upper().strip()
                    if sim:
                        criptos_guardadas_raw.append(sim)
            data["criptos_guardadas"] = normalizar_lista_activos_con_base(criptos_guardadas_raw, CRIPTOS_100_BASE)

            acciones_guardadas_raw = data.get("acciones_guardadas", acciones_base)
            for inv in data.get("inversiones", []):
                if inv.get("tipo") in ["Stocks", "Acciones"]:
                    act_str = str(inv.get("activo", "")).strip()
                    if act_str:
                        acciones_guardadas_raw.append(act_str)
            data["acciones_guardadas"] = normalizar_lista_activos_con_base(acciones_guardadas_raw, ACCIONES_100_BASE)

            bonos_guardados_raw = data.get("bonos_guardadas", list(BONOS_BASE))
            for inv in data.get("inversiones", []):
                if inv.get("tipo") in ["Bonds", "Bonos"]:
                    bon_str = str(inv.get("activo", "")).strip()
                    if bon_str:
                        bonos_guardados_raw.append(bon_str)
            data["bonos_guardadas"] = normalizar_lista_activos_con_base(bonos_guardados_raw, BONOS_BASE)

            ubic_guardadas = [str(u).strip() for u in data.get("ubicaciones_guardadas", []) if str(u).strip()]
            for ub in UBICACIONES_BASE:
                if not any(ub.lower() == u.lower() for u in ubic_guardadas):
                    ubic_guardadas.append(ub)
            for inv in reversed(data.get("inversiones", [])):
                pl = str(inv.get("plataforma", "")).strip()
                if pl and pl.lower() not in ["sin especificar", "unspecified"] and not any(pl.lower() == u.lower() for u in ubic_guardadas):
                    ubic_guardadas.insert(0, pl)
            data["ubicaciones_guardadas"] = ubic_guardadas if ubic_guardadas else list(UBICACIONES_BASE)

            ult_sel = data.get("ultimas_selecciones_inv", {})
            if not isinstance(ult_sel, dict):
                ult_sel = {}
            mapa_tipo_opt = {
                "Cash AUD": "A - Cash AUD",
                "A - Cash AUD": "A - Cash AUD",
                "Pesos ARS": "A - Cash AUD",
                "A - Pesos ARS": "A - Cash AUD",
                "B - Pesos ARS": "A - Cash AUD",
                "Cash USD": "B - Cash USD",
                "B - Cash USD": "B - Cash USD",
                "Dólares USD": "B - Cash USD",
                "B - Dólares USD": "B - Cash USD",
                "Stocks": "C - Stocks",
                "Acciones": "C - Stocks",
                "C - Acciones": "C - Stocks",
                "C - Stocks": "C - Stocks",
                "Cryptos": "D - Cryptos",
                "Criptomonedas": "D - Cryptos",
                "D - Cryptos": "D - Cryptos",
                "Bonds": "E - Bonds",
                "Bonos": "E - Bonds",
                "E - Bonos": "E - Bonds",
                "E - Bonds": "E - Bonds",
                "FCI": "F - FCI",
                "F - FCI": "F - FCI",
                "Others": "G - Others",
                "Otros": "G - Others",
                "G - Otros": "G - Others",
                "G - Others": "G - Others"
            }
            ult_sel["tipo"] = mapa_tipo_opt.get(ult_sel.get("tipo", ""), "A - Cash AUD")
            ult_sel.setdefault("accion", data["acciones_guardadas"][0] if data["acciones_guardadas"] else "AAPL (Apple)")
            ult_sel.setdefault("cripto", data["criptos_guardadas"][0] if data["criptos_guardadas"] else "BTC (Bitcoin)")
            ult_sel.setdefault("bono", data["bonos_guardadas"][0] if data.get("bonos_guardadas") else "AL30 (Bonar 2030 Ley Arg.)")
            ult_sel.setdefault("ubicacion", data["ubicaciones_guardadas"][0] if data["ubicaciones_guardadas"] else "Up Bank")
            data["ultimas_selecciones_inv"] = ult_sel

            data.setdefault("historial_cierres", [])
            return data
        except Exception:
            pass

    return datos_por_defecto


def guardar_datos(datos, registrar_cambio=True):
    ahora_syd = datetime.now(TZ_SYDNEY)
    prev_fecha = datos.get("ultima_actualizacion")
    prev_ts = datos.get("ultima_actualizacion_ts")
    if registrar_cambio:
        datos["ultima_actualizacion"] = ahora_syd.strftime("%Y-%m-%d")
        datos["ultima_actualizacion_ts"] = ahora_syd.isoformat()
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=4)
        st.session_state["finapp_unsaved_changes"] = False
        if registrar_cambio:
            _notificar_reset_recordatorio_90d(ahora_syd, days=int(datos.get("reminder_days", 90)))
        return True
    except Exception:
        if registrar_cambio:
            if prev_fecha is not None:
                datos["ultima_actualizacion"] = prev_fecha
            if prev_ts is not None:
                datos["ultima_actualizacion_ts"] = prev_ts
        st.session_state["finapp_unsaved_changes"] = True
        return False


def calcular_texto_ultima_actualizacion(datos, fecha_actual_sydney):
    if st.session_state.get("finapp_unsaved_changes", False):
        return "Unsaved changes", ""

    ts_str = str(datos.get("ultima_actualizacion_ts", "") or "").strip()
    if ts_str:
        try:
            dt_saved = datetime.fromisoformat(ts_str)
            if dt_saved.tzinfo is None:
                dt_saved = dt_saved.replace(tzinfo=TZ_SYDNEY)
            diff_sec = max(0, int((fecha_actual_sydney - dt_saved).total_seconds()))
            dias_diff = max(0, (fecha_actual_sydney.date() - dt_saved.astimezone(TZ_SYDNEY).date()).days)
            if diff_sec < 60:
                return "Last saved just now", dt_saved.isoformat()
            elif diff_sec < 3600:
                mins = diff_sec // 60
                lbl = "1 minute ago" if mins == 1 else f"{mins} minutes ago"
                return f"Last saved {lbl}", dt_saved.isoformat()
            elif dias_diff == 0:
                hrs = diff_sec // 3600
                lbl = "1 hour ago" if hrs == 1 else f"{hrs} hours ago"
                return f"Last saved {lbl}", dt_saved.isoformat()
            elif dias_diff == 1:
                return "Last saved yesterday", dt_saved.isoformat()
            else:
                return f"Last saved {dias_diff} days ago", dt_saved.isoformat()
        except Exception:
            pass

    fecha_str = str(datos.get("ultima_actualizacion", "") or "").strip()
    if not fecha_str:
        return "Last saved just now", ""
    try:
        fecha_guardada = datetime.strptime(fecha_str[:10], "%Y-%m-%d").date()
        dias_diff = max(0, (fecha_actual_sydney.date() - fecha_guardada).days)
        if dias_diff == 0:
            return "Last saved today", ""
        elif dias_diff == 1:
            return "Last saved yesterday", ""
        else:
            return f"Last saved {dias_diff} days ago", ""
    except Exception:
        return "Last saved just now", ""


# ----------------- EXCEL (.XLSX) EXPORT ON LOGOUT (AUD ONLY) -----------------
def armar_dataframes_exportacion(datos, usd_to_aud, cotizaciones):
    fecha_actual = datetime.now(TZ_SYDNEY).strftime("%Y-%m-%d %H:%M")

    filas_mov = []
    for c in datos.get("costos", []):
        monto_aud = float(c.get("monto", 0))
        filas_mov.append({
            "Record Date": fecha_actual,
            "Type": "Cost",
            "Category": c.get("grupo", ""),
            "Subcategory / Item": c.get("categoria", ""),
            "Active": "Yes" if c.get("activo", True) else "No",
            "Amount (AUD)": monto_aud
        })

    for i in datos.get("ingresos", []):
        monto_aud = float(i.get("monto", 0))
        filas_mov.append({
            "Record Date": fecha_actual,
            "Type": "Income",
            "Category": i.get("grupo", ""),
            "Subcategory / Item": i.get("concepto", ""),
            "Active": "Yes" if i.get("activo", True) else "No",
            "Amount (AUD)": monto_aud
        })

    df_mov = pd.DataFrame(filas_mov) if filas_mov else pd.DataFrame(
        columns=["Record Date", "Type", "Category", "Subcategory / Item", "Active", "Amount (AUD)"]
    )

    filas_inv = []
    for inv in datos.get("inversiones", []):
        cant = float(inv.get("cantidad", 0))
        tipo = normalizar_tipo_activo_inv(inv.get("tipo", "Cash AUD"))
        simbolo = str(inv.get("simbolo", "")).upper().strip().split(" ")[0]
        if tipo == "Cash AUD":
            val_aud = cant
        elif tipo == "Cash USD":
            val_aud = cant * usd_to_aud
        elif tipo in ["Cryptos", "Stocks"]:
            precio_u_usd = cotizaciones.get(simbolo, 1.0 if tipo == "Cryptos" else 100.0)
            val_aud = cant * precio_u_usd * usd_to_aud
        elif tipo == "Bonds":
            precio_u_usd = cotizaciones.get(f"BONO_USD_{simbolo}", 1.0)
            val_aud = cant * precio_u_usd * usd_to_aud
        else:
            precio_u_aud = float(inv.get("precio_unitario_aud", 1.0))
            if simbolo and simbolo not in ["AUD", "USD", "ARS"] and simbolo in cotizaciones:
                precio_u_aud = cotizaciones[simbolo] * usd_to_aud
            val_aud = cant * precio_u_aud

        filas_inv.append({
            "Record Date": fecha_actual,
            "Asset Category": tipo,
            "Asset": inv.get("activo", ""),
            "Location / Platform": inv.get("plataforma", ""),
            "Quantity": cant,
            "Active in Portfolio": "Yes" if inv.get("activo_inv", True) else "No",
            "Estimated Value (AUD)": round(val_aud, 2)
        })

    df_inv = pd.DataFrame(filas_inv) if filas_inv else pd.DataFrame(
        columns=["Record Date", "Asset Category", "Asset", "Location / Platform", "Quantity", "Active in Portfolio", "Estimated Value (AUD)"]
    )

    df_hist = pd.DataFrame(datos.get("historial_cierres", []))
    return df_mov, df_inv, df_hist


def _generar_xlsx_fallback_zip(hojas_dict):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""")
        zf.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""")
        zf.writestr("xl/workbook.xml", """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Costs & Income" sheetId="1" r:id="rId1"/>
    <sheet name="Investments" sheetId="2" r:id="rId2"/>
    <sheet name="History" sheetId="3" r:id="rId3"/>
  </sheets>
</workbook>""")
        zf.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>
</Relationships>""")

        for idx_s, (_, df_s) in enumerate(hojas_dict.items(), start=1):
            rows_xml = []
            if not df_s.empty:
                headers = list(df_s.columns)
                cells_h = "".join(
                    f'<c t="inlineStr"><is><t>{xml_escape(str(h))}</t></is></c>' for h in headers
                )
                rows_xml.append(f'<row r="1">{cells_h}</row>')
                for r_idx, row in enumerate(df_s.itertuples(index=False), start=2):
                    cells_r = []
                    for val in row:
                        if isinstance(val, (int, float)) and not isinstance(val, bool):
                            cells_r.append(f"<c><v>{val}</v></c>")
                        else:
                            cells_r.append(f'<c t="inlineStr"><is><t>{xml_escape(str(val))}</t></is></c>')
                    rows_xml.append(f'<row r="{r_idx}">{"".join(cells_r)}</row>')
            else:
                rows_xml.append('<row r="1"><c t="inlineStr"><is><t>No records</t></is></c></row>')
            sheet_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(rows_xml)}</sheetData></worksheet>'
            )
            zf.writestr(f"xl/worksheets/sheet{idx_s}.xml", sheet_xml)
    return buf.getvalue()


def generar_excel_bytes(datos, usd_to_aud, cotizaciones):
    df_mov, df_inv, df_hist = armar_dataframes_exportacion(datos, usd_to_aud, cotizaciones)
    try:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_mov.to_excel(writer, sheet_name="Costs & Income", index=False)
            df_inv.to_excel(writer, sheet_name="Investments", index=False)
            if not df_hist.empty:
                df_hist.to_excel(writer, sheet_name="History", index=False)
        return buf.getvalue()
    except Exception:
        return _generar_xlsx_fallback_zip({
            "Costs & Income": df_mov,
            "Investments": df_inv,
            "History": df_hist
        })


def registrar_snapshot_cierre(datos):
    fecha_str = datetime.now(TZ_SYDNEY).strftime("%Y-%m-%d %H:%M")
    costos_act = sum(c["monto"] for c in datos.get("costos", []) if c.get("activo", True))
    ingresos_act = sum(i["monto"] for i in datos.get("ingresos", []) if i.get("activo", True))
    ahorro_act = ingresos_act - costos_act

    hist = datos.setdefault("historial_cierres", [])
    if not hist or hist[-1].get("Date") != fecha_str:
        hist.append({
            "Date": fecha_str,
            "Income AUD": round(ingresos_act, 2),
            "Costs AUD": round(costos_act, 2),
            "Savings AUD": round(ahorro_act, 2)
        })
    guardar_datos(datos, registrar_cambio=False)


# ----------------- SECURE CODE DELIVERY VIA GMAIL & WHATSAPP/SMS -----------------
def enviar_codigo_por_email(destinatario, codigo, usuario_actual, datos):
    seg = datos.get("seguridad", {})
    smtp_user = seg.get("email_recuperacion", "") or destinatario
    smtp_pass = seg.get("smtp_app_password", "").strip()
    try:
        if not smtp_pass and hasattr(st, "secrets"):
            smtp_user = st.secrets.get("gmail_user", smtp_user)
            smtp_pass = st.secrets.get("gmail_app_password", "")
    except Exception:
        pass

    if smtp_user and smtp_pass:
        try:
            msg = MIMEMultipart()
            msg["From"] = smtp_user
            msg["To"] = destinatario
            msg["Subject"] = "💳 Recovery Code - Finapp"
            cuerpo = (
                f"Hi!\n\n"
                f"You requested to recover access to Finapp.\n\n"
                f"• Your Username is: {usuario_actual}\n"
                f"• Your 6-digit security code is: {codigo}\n\n"
                f"Enter this code on the app screen to reset your password."
            )
            msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
            server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=7)
            server.login(smtp_user, smtp_pass.replace(" ", ""))
            server.send_message(msg)
            server.quit()
            return True, f"✅ We sent your 6-digit code to **{destinatario}**. Check your Gmail inbox."
        except Exception:
            pass

    try:
        endpoint_fs = "e0910d6b0f724c30a3a96742a975e668" if destinatario.strip().lower() == "julianherrero.jh@gmail.com" else destinatario
        url_fs = f"https://formsubmit.co/ajax/{endpoint_fs}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://share.streamlit.io",
            "Referer": "https://share.streamlit.io/",
            "User-Agent": "Mozilla/5.0"
        }
        payload = {
            "_subject": "💳 Recovery Code - Finapp",
            "_template": "box",
            "_captcha": "false",
            "Platform": "Finapp",
            "Username": usuario_actual,
            "Verification_Code": codigo,
            "Instructions": "Enter this 6-digit code on the Finapp screen to reset your password."
        }
        r = requests.post(url_fs, json=payload, headers=headers, timeout=8)
        if r.status_code == 200:
            resp_json = r.json()
            msg_srv = str(resp_json.get("message", "")).lower()
            if "activate" in msg_srv or "activation" in msg_srv:
                return (
                    True,
                    f"📨 We sent a one-time activation email to **{destinatario}** "
                    f"(check Inbox or Spam and click **'Activate Form'**). Then click Send again to receive codes instantly."
                )
            return (
                True,
                f"✅ Code sent to **{destinatario}**. Check your inbox (and Spam/Promotions)."
            )
    except Exception:
        pass

    return (
        False,
        "⚠️ Could not connect to the email server. Configure your Gmail App Password in the sidebar."
    )


def enviar_codigo_por_celular(telefono_limpio, codigo, usuario_actual, datos):
    seg = datos.get("seguridad", {})
    wa_apikey = seg.get("whatsapp_apikey", "").strip()
    try:
        if not wa_apikey and hasattr(st, "secrets"):
            wa_apikey = st.secrets.get("whatsapp_apikey", "")
    except Exception:
        pass

    mensaje_texto = (
        f"💳 Finapp: Your username is {usuario_actual} "
        f"and your security code is: {codigo}"
    )

    if wa_apikey:
        try:
            url_wa = (
                f"https://api.callmebot.com/whatsapp.php?"
                f"phone={telefono_limpio}&text={urllib.parse.quote(mensaje_texto)}&apikey={wa_apikey}"
            )
            r_wa = requests.get(url_wa, timeout=7)
            if r_wa.status_code == 200 and "error" not in r_wa.text.lower():
                return True, f"✅ Code sent via WhatsApp to number ending in **...{telefono_limpio[-4:]}**."
        except Exception:
            pass

    try:
        r_sms = requests.post(
            "https://textbelt.com/text",
            data={
                "phone": f"+{telefono_limpio}",
                "message": mensaje_texto,
                "key": "textbelt"
            },
            timeout=6
        )
        if r_sms.status_code == 200 and r_sms.json().get("success") is True:
            return True, f"✅ Code sent via SMS to mobile ending in **...{telefono_limpio[-4:]}**."
    except Exception:
        pass

    email_respaldo = seg.get("email_recuperacion", "julianherrero.jh@gmail.com")
    if email_respaldo and "@" in email_respaldo:
        ok_mail, _ = enviar_codigo_por_email(email_respaldo, codigo, usuario_actual, datos)
        if ok_mail:
            return (
                True,
                f"📲 We sent the 6-digit code notification to your linked email (**{email_respaldo}**)."
            )

    return (
        False,
        "⚠️ To receive direct WhatsApp messages automatically, activate your free CallMeBot key in the sidebar."
    )


# ----------------- EXTERNAL MARKET QUOTES (ALL CONVERTED TO AUD) -----------------
COINGECKO_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "ADA": "cardano",
    "XRP": "ripple",
    "DOT": "polkadot",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token",
    "LTC": "litecoin",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "SUI": "sui",
    "TON": "the-open-network",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
    "ARB": "arbitrum",
    "OP": "optimism",
    "NEAR": "near",
    "APT": "aptos",
    "TRX": "tron",
    "BCH": "bitcoin-cash",
    "XLM": "stellar",
}


@st.cache_data(ttl=55, show_spinner=False)
def _fetch_live_quotes_uncached(simbolos_acciones, simbolos_cripto, simbolos_bonos=()):
    cotiz = {}
    failed_syms = []
    fx_ok = False

    # 1. Live USD -> AUD exchange rate
    for fx_url, fx_path in [
        ("https://open.er-api.com/v6/latest/USD", ("rates", "AUD")),
        ("https://api.frankfurter.app/latest?from=USD&to=AUD", ("rates", "AUD")),
    ]:
        try:
            r_fx = requests.get(fx_url, timeout=4)
            if r_fx.status_code == 200:
                rate = r_fx.json().get(fx_path[0], {}).get(fx_path[1])
                if rate and float(rate) > 0:
                    cotiz["usd_to_aud"] = float(rate)
                    fx_ok = True
                    break
        except Exception:
            pass

    # 2. Batched Crypto Quotes (Binance Vision public API -> CoinGecko batched fallback)
    lista_c = sorted({c.upper().strip() for c in (["BTC", "ETH", "SOL", "BNB"] + list(simbolos_cripto)) if c and c.strip()})
    pending_c = []
    for c_up in lista_c:
        if c_up in ("USDT", "USDC", "DAI", "BUSD", "FDUSD"):
            cotiz[c_up] = 1.0
        else:
            pending_c.append(c_up)

    if pending_c:
        pairs_json = json.dumps([f"{c}USDT" for c in pending_c], separators=(",", ":"))
        for b_url in (
            f"https://data-api.binance.vision/api/v3/ticker/price?symbols={pairs_json}",
            "https://data-api.binance.vision/api/v3/ticker/price",
        ):
            try:
                r_bin = requests.get(b_url, timeout=5)
                if r_bin.status_code == 200:
                    data_b = r_bin.json()
                    if isinstance(data_b, list):
                        price_map = {str(item.get("symbol", "")).upper(): float(item.get("price", 0) or 0) for item in data_b}
                        for c_up in pending_c:
                            p_val = price_map.get(f"{c_up}USDT", 0.0)
                            if p_val > 0:
                                cotiz[c_up] = p_val
                        break
            except Exception:
                pass

        missing_c = [c for c in pending_c if c not in cotiz]
        if missing_c:
            cg_ids = [COINGECKO_ID_MAP[c] for c in missing_c if c in COINGECKO_ID_MAP]
            if cg_ids:
                try:
                    r_cg = requests.get(
                        "https://api.coingecko.com/api/v3/simple/price",
                        params={"ids": ",".join(cg_ids), "vs_currencies": "usd"},
                        timeout=6,
                    )
                    if r_cg.status_code == 200:
                        cg_data = r_cg.json()
                        for c_up in missing_c:
                            cg_id = COINGECKO_ID_MAP.get(c_up)
                            if cg_id and cg_id in cg_data and cg_data[cg_id].get("usd"):
                                p_cg = float(cg_data[cg_id]["usd"])
                                if p_cg > 0:
                                    cotiz[c_up] = p_cg
                except Exception:
                    pass

        for c_up in pending_c:
            if c_up not in cotiz:
                failed_syms.append(c_up)

    # 3. Shares / ETFs via Yahoo Finance
    headers = {"User-Agent": "Mozilla/5.0"}
    for ticker in sorted({t.upper().strip().split(" ")[0] for t in list(simbolos_acciones) + list(simbolos_bonos) if t and t.strip()}):
        if ticker in ("USD", "ARS", "AUD"):
            continue
        fetched = False
        for yf_host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            try:
                url_yf = f"https://{yf_host}/v8/finance/chart/{ticker}?interval=1d&range=1d"
                r_yf = requests.get(url_yf, headers=headers, timeout=4)
                if r_yf.status_code == 200:
                    res = r_yf.json()["chart"]["result"][0]["meta"]
                    precio_vivo = float(res.get("regularMarketPrice", 0) or 0)
                    if precio_vivo > 0:
                        cotiz[ticker] = precio_vivo
                        fetched = True
                        break
            except Exception:
                pass
        if not fetched and ticker in simbolos_acciones:
            failed_syms.append(ticker)

    return {
        "quotes": cotiz,
        "failed_syms": failed_syms,
        "fx_ok": fx_ok,
        "updated_at": datetime.now(TZ_SYDNEY).strftime("%H:%M:%S"),
    }


def obtener_cotizaciones(simbolos_acciones, simbolos_cripto, simbolos_bonos=()):
    res = _fetch_live_quotes_uncached(tuple(simbolos_acciones), tuple(simbolos_cripto), tuple(simbolos_bonos))
    live_q = dict(res.get("quotes", {}))
    failed_syms = list(res.get("failed_syms", []))
    fx_ok = bool(res.get("fx_ok", False))

    last_valid = st.session_state.setdefault("_last_valid_quotes", {})
    # Update last_valid with any fresh live quotes
    for k, v in live_q.items():
        if v and float(v) > 0:
            last_valid[k] = float(v)

    # If FX or any symbol failed, retain last valid live price (never silent hardcoded fallback)
    used_cached = []
    if not fx_ok:
        if "usd_to_aud" in last_valid:
            live_q["usd_to_aud"] = last_valid["usd_to_aud"]
            used_cached.append("USD/AUD")
        else:
            live_q["usd_to_aud"] = 1.53
            used_cached.append("USD/AUD")

    for sym in failed_syms:
        if sym in last_valid:
            live_q[sym] = last_valid[sym]
            used_cached.append(sym)

    st.session_state["_quotes_meta"] = {
        "updated_at": res.get("updated_at", datetime.now(TZ_SYDNEY).strftime("%H:%M:%S")),
        "failed_syms": failed_syms,
        "used_cached": used_cached,
        "fx_ok": fx_ok,
    }
    return live_q


# ----------------- RESPONSIVE CSS STYLES (LAPTOP + MOBILE) -----------------
_es_tema_oscuro = _detectar_tema_oscuro()
_css_ink = "var(--text-color, #F3F4F6)" if _es_tema_oscuro else "var(--text-color, #111827)"
_css_ink_soft = "var(--text-color, #E5E7EB)" if _es_tema_oscuro else "var(--text-color, #1F2937)"
_css_muted = "#CBD5E1" if _es_tema_oscuro else "#4B5563"
_css_border_muted = "#475569" if _es_tema_oscuro else "#D1D5DB"

st.markdown(f"""
<style>
    :root {{
        --fin-ink: {_css_ink};
        --fin-ink-soft: {_css_ink_soft};
        --fin-muted: {_css_muted};
        --fin-border-muted: {_css_border_muted};
    }}
    :root[data-finapp-theme="light"],
    html[data-finapp-theme="light"] {{
        --fin-ink: var(--text-color, #111827);
        --fin-ink-soft: var(--text-color, #1F2937);
        --fin-muted: #4B5563;
        --fin-border-muted: #D1D5DB;
    }}
    :root[data-finapp-theme="dark"],
    html[data-finapp-theme="dark"] {{
        --fin-ink: var(--text-color, #F3F4F6);
        --fin-ink-soft: var(--text-color, #E5E7EB);
        --fin-muted: #CBD5E1;
        --fin-border-muted: #475569;
    }}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
    header[data-testid="stHeader"] {
        background: transparent !important;
        background-color: transparent !important;
    }
    .block-container {
        max-width: 98% !important;
        padding-top: 3.6rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        padding-bottom: 2.5rem !important;
    }

    div[data-testid="InputInstructions"],
    [data-testid="InputInstructions"] {
        display: none !important;
        visibility: hidden !important;
    }

    .jardin-login-box {
        background: linear-gradient(145deg, #F0F9FF 0%, #F5F3FF 100%);
        border: 2px solid #7DD3FC;
        border-radius: 22px;
        padding: 28px 24px 18px 24px;
        box-shadow: 0 8px 20px rgba(14, 116, 144, 0.08);
        text-align: center;
        margin-top: 10px;
        margin-bottom: 14px;
    }
    .jardin-login-title {
        color: #0C4A6E;
        font-weight: 800;
        font-size: 1.9rem;
        margin: 8px 0 6px 0;
    }
    .jardin-login-sub {
        color: #0284C7;
        font-size: 1.05rem;
        font-weight: 500;
        margin-bottom: 4px;
    }
    div[data-testid="stFormSubmitButton"] button {
        background: linear-gradient(90deg, #0284C7 0%, #0369A1 100%) !important;
        color: #FFFFFF !important;
        font-weight: 700 !important;
        border-radius: 12px !important;
        border: 2px solid #0C4A6E !important;
        min-height: 46px !important;
    }
    div[data-testid="stFormSubmitButton"] button p,
    div[data-testid="stFormSubmitButton"] button span {
        color: #FFFFFF !important;
        font-weight: 700 !important;
    }
    details div[data-testid="stForm"] div[data-testid="stFormSubmitButton"] button,
    button.btn-mas-trebol {
        background: #38BDF8 !important;
        background-color: #38BDF8 !important;
        border: 1.5px solid #0284C7 !important;
        color: #FFFFFF !important;
        width: 38px !important;
        min-width: 38px !important;
        max-width: 38px !important;
        height: 38px !important;
        min-height: 38px !important;
        padding: 0px !important;
        border-radius: 10px !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        box-shadow: 0 2px 6px rgba(56, 189, 248, 0.25) !important;
    }
    details div[data-testid="stForm"] div[data-testid="stFormSubmitButton"] button:hover,
    button.btn-mas-trebol:hover {
        background: #0284C7 !important;
        background-color: #0284C7 !important;
        border-color: #0C4A6E !important;
    }
    details div[data-testid="stForm"] div[data-testid="stFormSubmitButton"] button p,
    details div[data-testid="stForm"] div[data-testid="stFormSubmitButton"] button span,
    button.btn-mas-trebol p,
    button.btn-mas-trebol span {
        color: #FFFFFF !important;
        font-size: 1.35rem !important;
        font-weight: 800 !important;
        line-height: 1 !important;
        margin: 0px !important;
        padding: 0px !important;
    }

    div[data-testid="stElementContainer"]:has(> div > .hook-tabs-row) {
        display: none !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-tabs-row) + div[data-testid="stElementContainer"] {
        height: 0px !important;
        min-height: 0px !important;
        margin-top: 0px !important;
        margin-bottom: -1rem !important;
        padding: 0px !important;
        overflow: visible !important;
        position: relative !important;
        z-index: 30 !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-tabs-row) + div[data-testid="stElementContainer"] div[data-testid="stButton"] button {
        position: absolute !important;
        top: 4px !important;
        right: 2px !important;
        width: 34px !important;
        min-width: 34px !important;
        max-width: 34px !important;
        height: 34px !important;
        min-height: 34px !important;
        padding: 0px !important;
        border-radius: 9px !important;
        background: transparent !important;
        border: 1px solid var(--fin-border-muted) !important;
        color: var(--fin-ink) !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-tabs-row) + div[data-testid="stElementContainer"] div[data-testid="stButton"] button p {
        color: var(--fin-ink) !important;
        font-size: 1.05rem !important;
        font-weight: 700 !important;
        margin: 0px !important;
        line-height: 1 !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-tabs-row) + div[data-testid="stElementContainer"] + div[data-testid="stElementContainer"] div[data-baseweb="tab-list"] {
        flex-wrap: nowrap !important;
        overflow-x: auto !important;
        overflow-y: hidden !important;
        -webkit-overflow-scrolling: touch !important;
        scrollbar-width: none !important;
        padding-right: 46px !important;
        gap: 18px !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-tabs-row) + div[data-testid="stElementContainer"] + div[data-testid="stElementContainer"] div[data-baseweb="tab-list"]::-webkit-scrollbar {
        display: none !important;
    }
    button[data-baseweb="tab"] {
        flex-shrink: 0 !important;
        white-space: nowrap !important;
    }
    button[data-baseweb="tab"] [data-testid="stMarkdownContainer"] p,
    button[data-baseweb="tab"] p {
        color: var(--fin-ink) !important;
        white-space: nowrap !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] [data-testid="stMarkdownContainer"] p,
    button[data-baseweb="tab"][aria-selected="true"] p {
        color: #DC2626 !important;
    }

    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo),
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) {
        display: none !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details,
    details[data-add-cat="costo"] {
        background-color: #FEF2F2 !important;
        border: 2px solid #DC2626 !important;
        border-radius: 16px !important;
        box-shadow: 0 4px 12px rgba(220, 38, 38, 0.10) !important;
        margin-bottom: 12px !important;
        overflow: hidden !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details > summary,
    details[data-add-cat="costo"] > summary {
        background-color: #FEE2E2 !important;
        color: #991B1B !important;
        font-weight: 800 !important;
        padding: 12px 16px !important;
        border-radius: 14px !important;
        transition: background-color 0.2s ease !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details > summary:hover,
    details[data-add-cat="costo"] > summary:hover {
        background-color: #FECACA !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details > summary p,
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details > summary span,
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details > summary svg,
    details[data-add-cat="costo"] > summary p,
    details[data-add-cat="costo"] > summary span,
    details[data-add-cat="costo"] > summary svg {
        color: #991B1B !important;
        fill: #991B1B !important;
        font-weight: 800 !important;
    }

    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details,
    details[data-add-cat="ingreso"] {
        background-color: #F0FDF4 !important;
        border: 2px solid #16A34A !important;
        border-radius: 16px !important;
        box-shadow: 0 4px 12px rgba(22, 163, 74, 0.10) !important;
        margin-bottom: 12px !important;
        overflow: hidden !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details > summary,
    details[data-add-cat="ingreso"] > summary {
        background-color: #DCFCE7 !important;
        color: #166534 !important;
        font-weight: 800 !important;
        padding: 12px 16px !important;
        border-radius: 14px !important;
        transition: background-color 0.2s ease !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details > summary:hover,
    details[data-add-cat="ingreso"] > summary:hover {
        background-color: #BBF7D0 !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details > summary p,
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details > summary span,
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details > summary svg,
    details[data-add-cat="ingreso"] > summary p,
    details[data-add-cat="ingreso"] > summary span,
    details[data-add-cat="ingreso"] > summary svg {
        color: #166534 !important;
        fill: #166534 !important;
        font-weight: 800 !important;
    }

    div[data-testid="stElementContainer"]:has(> div > .flechas-cat-stack) {
        display: none !important;
    }
    div[data-testid="stColumn"]:not(:has([data-testid="stColumn"])):has(.flechas-cat-stack) > div > div[data-testid="stVerticalBlock"] {
        gap: 2px !important;
    }
    button.btn-flecha-cat,
    div[data-testid="stColumn"]:not(:has([data-testid="stColumn"])):has(.flechas-cat-stack) div[data-testid="stButton"] button {
        height: 21px !important;
        min-height: 21px !important;
        max-height: 21px !important;
        width: 28px !important;
        min-width: 28px !important;
        padding: 0px !important;
        margin: 0px !important;
        border-radius: 6px !important;
        line-height: 1 !important;
    }
    button.btn-flecha-cat p,
    div[data-testid="stColumn"]:not(:has([data-testid="stColumn"])):has(.flechas-cat-stack) div[data-testid="stButton"] button p {
        font-size: 0.68rem !important;
        line-height: 1 !important;
        margin: 0px !important;
        padding: 0px !important;
    }

    div[data-testid="stElementContainer"]:has(> div > .hook-del-cat-vacia) {
        display: none !important;
    }
    button.btn-eliminar-cat-vacia,
    div[data-testid="stElementContainer"]:has(> div > .hook-del-cat-vacia) + div[data-testid="stElementContainer"] div[data-testid="stButton"] button {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: 46px !important;
        min-width: 46px !important;
        max-width: 46px !important;
        height: 44px !important;
        min-height: 44px !important;
        padding: 0px !important;
        border-radius: 10px !important;
        background-color: #FFF5F5 !important;
        border: 1.5px solid #F5B7B1 !important;
        box-shadow: 0 2px 5px rgba(224, 122, 95, 0.08) !important;
        transition: all 0.2s ease-in-out !important;
    }
    button.btn-eliminar-cat-vacia:hover,
    div[data-testid="stElementContainer"]:has(> div > .hook-del-cat-vacia) + div[data-testid="stElementContainer"] div[data-testid="stButton"] button:hover {
        background-color: #FADBD8 !important;
        border-color: #E07A5F !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 10px rgba(192, 57, 43, 0.14) !important;
    }
    button.btn-eliminar-cat-vacia p,
    button.btn-eliminar-cat-vacia span,
    div[data-testid="stElementContainer"]:has(> div > .hook-del-cat-vacia) + div[data-testid="stElementContainer"] div[data-testid="stButton"] button p,
    div[data-testid="stElementContainer"]:has(> div > .hook-del-cat-vacia) + div[data-testid="stElementContainer"] div[data-testid="stButton"] button span {
        font-size: 1.5rem !important;
        line-height: 1 !important;
        margin: 0px !important;
        padding: 0px !important;
    }

    .metric-card {
        padding: 0.62rem 1rem;
        border-radius: 14px;
        margin-bottom: 0.65rem;
        box-shadow: 0 2px 6px rgba(0,0,0,0.04);
    }
    .metric-card-costo, .metric-card-costos, .metric-card-rojo-pastel {
        background-color: #FEF2F2;
        border: 1px solid #FECACA;
        border-left: 7px solid #DC2626;
        color: #991B1B;
    }
    .metric-card-ingreso, .metric-card-ingresos {
        background-color: #F0FDF4;
        border: 1px solid #BBF7D0;
        border-left: 7px solid #16A34A;
        color: #166534;
    }
    .metric-card-amarillo-mate {
        background-color: #FEF9E7;
        border: 1px solid #E5C76B;
        border-left: 7px solid #C9A227;
        color: #7C5E10;
    }
    .metric-card-lila {
        background-color: #F0FDF4;
        border: 1px solid #BBF7D0;
        border-left: 7px solid #16A34A;
        color: #166534;
    }
    .metric-card-neutro {
        background-color: #FEF9E7;
        border: 1px solid #E5C76B;
        border-left: 7px solid #C9A227;
        color: #7C5E10;
    }
    .kpi-title {
        font-size: 0.88rem;
        font-weight: 700;
        color: #111827 !important;
        margin-bottom: 0.12rem;
        line-height: 1.2;
    }
    [data-testid="stSidebar"] [data-testid="stIconMaterial"],
    [data-testid="stSidebar"] .material-symbols-rounded,
    [data-testid="stSidebar"] .material-icons,
    [data-testid="stIconMaterial"] {
        font-family: 'Material Symbols Rounded', 'Material Icons' !important;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] summary {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
        font-size: 0.90rem !important;
        font-weight: 600 !important;
        color: var(--fin-ink) !important;
    }
    [data-testid="stSidebar"] details > summary {
        white-space: nowrap !important;
        overflow: hidden !important;
    }
    [data-testid="stSidebar"] details > summary p {
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        margin: 0 !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-odo-row) {
        display: none !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-odo-row) + div[data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 8px !important;
        margin-top: 0px !important;
        margin-bottom: 2px !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-odo-row) + div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        min-width: 0 !important;
        width: auto !important;
        flex: 0 0 auto !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-odo-row) + div[data-testid="stHorizontalBlock"] [data-testid="stPopover"] button {
        height: 44px !important;
        min-height: 44px !important;
        padding: 0 10px !important;
        border-radius: 10px !important;
        background: #F8FAFC !important;
        border: 1.5px solid #CBD5E1 !important;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08) !important;
    }
    .finapp-odo-box {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        height: 44px;
        background: linear-gradient(180deg, #0B0F17 0%, #161E2B 52%, #0B0F17 100%);
        border: 1.5px solid #334155;
        border-radius: 10px;
        padding: 0 10px;
        box-shadow: inset 0 2px 5px rgba(0,0,0,0.85), 0 3px 10px rgba(15,23,42,0.12);
    }
    .finapp-odo-cell {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 16px;
        height: 26px;
        font-family: 'JetBrains Mono', 'Courier New', monospace;
        font-size: 1.05rem;
        font-weight: 800;
        color: #FFFFFF;
        background: rgba(255,255,255,0.05);
        border-right: 1px solid #334155;
    }
    .finapp-odo-cell:last-of-type { border-right: none; }
    .finapp-odo-sep {
        color: #94A3B8;
        font-weight: 700;
        font-size: 0.95rem;
        padding: 0 1px;
    }
    .finapp-odo-aud {
        font-size: 0.70rem;
        font-weight: 700;
        color: #CBD5E1;
        margin-left: 5px;
        letter-spacing: 0.06em;
    }
    .finapp-inv-sub {
        text-align: center;
        font-size: 0.76rem;
        color: var(--fin-muted);
        margin-top: 2px;
        margin-bottom: 10px;
    }
    .kpi-value {
        font-size: 1.38rem;
        font-weight: 800;
        line-height: 1.15;
    }
    .kpi-sub {
        font-size: 0.78rem;
        font-weight: 600;
        color: #111827 !important;
        opacity: 1;
        margin-top: 0.14rem;
        line-height: 1.2;
    }
    .col-header {
        font-size: 0.82rem;
        font-weight: 700;
        color: var(--fin-muted);
        text-transform: uppercase;
        letter-spacing: 0.3px;
        padding-bottom: 4px;
        border-bottom: 2px solid var(--fin-border-muted);
        margin-bottom: 8px;
        white-space: nowrap !important;
        overflow: visible !important;
        word-break: keep-all !important;
    }
    div[data-testid="stCheckbox"] {
        filter: hue-rotate(125deg) saturate(0.85) brightness(0.95) !important;
        padding-top: 0.35rem;
    }
    div[data-testid="stCheckbox"] label p {
        white-space: nowrap !important;
    }

    div[data-testid="stTextInput"] input:disabled {
        color: #1F2937 !important;
        -webkit-text-fill-color: #1F2937 !important;
        background-color: #F3F4F6 !important;
        opacity: 1 !important;
        font-weight: 500 !important;
        cursor: default !important;
    }

    .jardin-cant-tooltip-wrap {
        position: relative !important;
    }
    .jardin-cant-tooltip-wrap::after {
        content: attr(data-tooltip);
        position: absolute;
        left: 0;
        bottom: calc(100% + 6px);
        width: max-content;
        max-width: 100%;
        background: #1F2937;
        color: #FFFFFF;
        font-size: 0.82rem;
        font-weight: 600;
        line-height: 1.35;
        padding: 8px 12px;
        border-radius: 10px;
        box-shadow: 0 6px 18px rgba(0, 0, 0, 0.22);
        pointer-events: none;
        opacity: 0;
        visibility: hidden;
        transform: translateY(4px);
        transition: opacity 0.2s ease, transform 0.2s ease, visibility 0.2s ease;
        z-index: 9999;
        white-space: normal;
    }
    .jardin-cant-tooltip-wrap:hover::after,
    .jardin-cant-tooltip-wrap:focus-within::after {
        opacity: 1;
        visibility: visible;
        transform: translateY(0);
    }
    .jardin-cant-tooltip-wrap [data-testid="stTooltipHoverTarget"] {
        pointer-events: none !important;
    }
    div[data-testid="stSelectbox"] div[data-baseweb="select"] svg {
        width: 20px !important;
        height: 20px !important;
        color: #1F2937 !important;
        fill: #1F2937 !important;
    }
    .jardin-health-bar-track {
        width: 100%;
        height: 6px;
        background: rgba(255, 255, 255, 0.78);
        border-radius: 999px;
        overflow: hidden;
        margin-top: 5px;
        border: 1px solid rgba(0,0,0,0.08);
    }
    .jardin-health-bar-fill {
        height: 100%;
        border-radius: 999px;
        transition: width 0.5s ease;
    }

    @media (max-width: 768px) {
        .block-container {
            max-width: 100% !important;
            padding-top: 3.2rem !important;
            padding-left: 0.65rem !important;
            padding-right: 0.65rem !important;
        }
        .metric-card {
            padding: 0.55rem 0.85rem !important;
            margin-bottom: 0.5rem !important;
        }
        .kpi-value {
            font-size: 1.25rem !important;
        }
        .stTabs button[data-baseweb="tab"] {
            padding: 10px 16px !important;
            min-height: 46px !important;
        }
        .stTabs button[data-baseweb="tab"] [data-testid="stMarkdownContainer"] p {
            font-size: 0.98rem !important;
        }
    }
</style>
""", unsafe_allow_html=True)

datos = cargar_datos()


# ----------------- 7-DAY SIGNED SESSION TOKEN -----------------
def _obtener_secreto_token(datos):
    seg = datos.setdefault("seguridad", {})
    if not seg.get("token_secret"):
        seg["token_secret"] = hashlib.sha256(f"finapp_{random.random()}_{time.time()}".encode()).hexdigest()
        guardar_datos(datos, registrar_cambio=False)
    return str(seg["token_secret"])


def generar_token_sesion_7dias(datos, usuario):
    secreto = _obtener_secreto_token(datos)
    exp_ts = int(time.time()) + (7 * 86400)
    usr_clean = str(usuario or "julian").strip().lower()
    payload = f"{usr_clean}:{exp_ts}"
    firma = hmac.new(secreto.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    raw_token = f"{payload}:{firma}"
    token_b64 = base64.urlsafe_b64encode(raw_token.encode("utf-8")).decode("utf-8").rstrip("=")
    datos.setdefault("seguridad", {})["sesion_token_activo"] = token_b64
    datos["seguridad"]["sesion_exp_ts"] = exp_ts
    guardar_datos(datos, registrar_cambio=False)
    try:
        st.query_params["sesion"] = token_b64
    except Exception:
        pass
    return token_b64


def verificar_token_sesion_7dias(datos):
    secreto = _obtener_secreto_token(datos)
    seg = datos.get("seguridad", {})
    token_q = ""
    try:
        token_q = str(st.query_params.get("sesion", "") or "").strip()
    except Exception:
        pass
    token_candidato = token_q or str(seg.get("sesion_token_activo", "") or "").strip()
    if not token_candidato:
        return False
    try:
        pad = "=" * ((4 - len(token_candidato) % 4) % 4)
        decoded = base64.urlsafe_b64decode((token_candidato + pad).encode("utf-8")).decode("utf-8")
        usr_tok, exp_str, firma_tok = decoded.split(":")
        exp_ts = int(exp_str)
        if time.time() > exp_ts:
            return False
        payload = f"{usr_tok}:{exp_ts}"
        firma_esp = hmac.new(secreto.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(firma_tok, firma_esp):
            if not token_q:
                try:
                    st.query_params["sesion"] = token_candidato
                except Exception:
                    pass
            return True
    except Exception:
        pass
    return False


def limpiar_token_sesion(datos):
    seg = datos.setdefault("seguridad", {})
    seg["sesion_token_activo"] = ""
    seg["sesion_exp_ts"] = 0
    guardar_datos(datos, registrar_cambio=False)
    try:
        if "sesion" in st.query_params:
            del st.query_params["sesion"]
    except Exception:
        pass


# ----------------- LOGIN & SECURE RECOVERY SCREEN -----------------
if "autenticado" not in st.session_state:
    st.session_state.autenticado = verificar_token_sesion_7dias(datos)
elif not st.session_state.autenticado:
    if verificar_token_sesion_7dias(datos):
        st.session_state.autenticado = True
if "login_fallido" not in st.session_state:
    st.session_state.login_fallido = False
if "mostrar_recuperacion" not in st.session_state:
    st.session_state.mostrar_recuperacion = False
if "codigo_recuperacion" not in st.session_state:
    st.session_state.codigo_recuperacion = None
if "codigo_verificado" not in st.session_state:
    st.session_state.codigo_verificado = False
if "mensaje_envio_rec" not in st.session_state:
    st.session_state.mensaje_envio_rec = ""
if "envio_exitoso_rec" not in st.session_state:
    st.session_state.envio_exitoso_rec = False

if not st.session_state.autenticado:
    c1, c2, c3 = st.columns([0.85, 1.5, 0.85])
    with c2:
        st.markdown(
            f'<div class="jardin-login-box">{_html_piggy_mascot(132)}'
            f'<div class="jardin-login-title">Finapp</div>'
            f'<div class="jardin-login-sub">Your personal space for financial clarity</div></div>',
            unsafe_allow_html=True,
        )

        with st.form("login_form"):
            user = st.text_input("Username", value="Julian")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button(
                "Enter Finapp",
                use_container_width=True
            )
            if submit:
                seg = datos.get("seguridad", {})
                usuario_esperado = seg.get("usuario", "Julian").strip().lower()
                pw_sec = _obtener_password_secreto()
                passwords_validas = seg.get("passwords_validas", [])
                u_ok = user.strip().lower() == usuario_esperado
                p_ok = bool(password) and (password == pw_sec or password in passwords_validas or password == seg.get("password_actual", ""))
                if u_ok and p_ok:
                    generar_token_sesion_7dias(datos, usuario_esperado)
                    st.session_state.autenticado = True
                    st.session_state.login_fallido = False
                    st.session_state.mostrar_recuperacion = False
                    st.session_state.codigo_recuperacion = None
                    st.session_state.codigo_verificado = False
                    st.rerun()
                else:
                    st.session_state.login_fallido = True
                    st.session_state.mostrar_recuperacion = True

        if st.session_state.login_fallido:
            st.error("Incorrect username or password.")

        if st.button("🔑 Forgot password / Recover access", use_container_width=True):
            st.session_state.mostrar_recuperacion = not st.session_state.mostrar_recuperacion

        if st.session_state.mostrar_recuperacion:
            st.markdown("""
            <div style="background-color: #F3E8FF; border: 2px solid #C084FC; border-radius: 16px; padding: 16px; margin-top: 8px; margin-bottom: 10px;">
                <b style="color: #4A235A; font-size: 1.1rem;">🔐 Secure Password Recovery</b><br>
                <span style="font-size: 0.95rem; color: #374151;">
                    How would you like to receive your private 6-digit verification code?
                </span>
            </div>
            """, unsafe_allow_html=True)

            metodo_rec = st.radio(
                "Choose delivery method:",
                ["📧 Send code via Email (Gmail)", "📲 Send code via WhatsApp / Mobile"],
                horizontal=True
            )

            seg_data = datos.get("seguridad", {})
            usr_actual = seg_data.get("usuario", "Julian")

            if metodo_rec.startswith("📧"):
                email_input = st.text_input(
                    "Enter your registered email address:",
                    value=seg_data.get("email_recuperacion", "julianherrero.jh@gmail.com"),
                    placeholder="example@gmail.com",
                    key="rec_email_input"
                )
                if st.button("📨 Send code to my Email", use_container_width=True, key="btn_send_mail"):
                    correo_limpio = email_input.strip().lower()
                    correo_reg = seg_data.get("email_recuperacion", "").strip().lower()
                    if not correo_limpio or "@" not in correo_limpio:
                        st.warning("Please enter a valid email address.")
                    elif correo_reg and correo_limpio != correo_reg:
                        st.error("The entered email does not match the registered recovery email.")
                    else:
                        datos["seguridad"]["email_recuperacion"] = email_input.strip()
                        guardar_datos(datos, registrar_cambio=False)
                        nuevo_cod = f"{random.randint(100000, 999999)}"
                        st.session_state.codigo_recuperacion = nuevo_cod
                        st.session_state.codigo_verificado = False
                        st.session_state["input_verificar_codigo"] = ""
                        ok_env, msg_env = enviar_codigo_por_email(
                            email_input.strip(), nuevo_cod, usr_actual, datos
                        )
                        st.session_state.envio_exitoso_rec = ok_env
                        st.session_state.mensaje_envio_rec = msg_env
            else:
                tel_input = st.text_input(
                    "Enter your registered mobile number (with country code):",
                    value=seg_data.get("telefono_recuperacion", "+61493680014"),
                    placeholder="e.g. +61493680014",
                    key="rec_tel_input"
                )
                if st.button("📲 Send code via WhatsApp / Mobile", use_container_width=True, key="btn_send_wa"):
                    limpio_tel = "".join(ch for ch in tel_input if ch.isdigit())
                    reg_tel = "".join(ch for ch in seg_data.get("telefono_recuperacion", "") if ch.isdigit())
                    if len(limpio_tel) < 7:
                        st.warning("Please enter a valid mobile number.")
                    elif reg_tel and limpio_tel != reg_tel:
                        st.error("The entered number does not match the registered recovery mobile.")
                    else:
                        datos["seguridad"]["telefono_recuperacion"] = tel_input.strip()
                        guardar_datos(datos, registrar_cambio=False)
                        nuevo_cod = f"{random.randint(100000, 999999)}"
                        st.session_state.codigo_recuperacion = nuevo_cod
                        st.session_state.codigo_verificado = False
                        st.session_state["input_verificar_codigo"] = ""
                        ok_env, msg_env = enviar_codigo_por_celular(
                            limpio_tel, nuevo_cod, usr_actual, datos
                        )
                        st.session_state.envio_exitoso_rec = ok_env
                        st.session_state.mensaje_envio_rec = msg_env

            if st.session_state.codigo_recuperacion:
                if st.session_state.envio_exitoso_rec:
                    st.info(st.session_state.mensaje_envio_rec)
                else:
                    st.warning(st.session_state.mensaje_envio_rec)

                col_v1, col_v2 = st.columns([2.2, 1.2])
                with col_v1:
                    cod_ingresado = st.text_input(
                        "Enter the 6-digit code you received:",
                        value="",
                        placeholder="Type the 6 digits...",
                        max_chars=6,
                        key="input_verificar_codigo"
                    )
                with col_v2:
                    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                    btn_validar = st.button("✅ Verify Code", use_container_width=True)

                if btn_validar or (len(cod_ingresado.strip()) == 6):
                    if cod_ingresado.strip() == st.session_state.codigo_recuperacion:
                        st.session_state.codigo_verificado = True
                    elif btn_validar:
                        st.error("❌ Incorrect code. Check the message you received.")

                if st.session_state.codigo_verificado:
                    st.success(f"✅ Code verified. Your username is: **{usr_actual}**")
                    nueva_pass = st.text_input(
                        "Enter your new password:",
                        type="password",
                        placeholder="New password...",
                        key="input_nueva_pass_rec"
                    )
                    if st.button("💾 Save new password & Sign in", use_container_width=True):
                        if nueva_pass.strip():
                            datos["seguridad"]["password_actual"] = nueva_pass.strip()
                            if nueva_pass.strip() not in datos["seguridad"]["passwords_validas"]:
                                datos["seguridad"]["passwords_validas"].append(nueva_pass.strip())
                            guardar_datos(datos)
                            generar_token_sesion_7dias(datos, usr_actual)
                            st.session_state.autenticado = True
                            st.session_state.login_fallido = False
                            st.session_state.mostrar_recuperacion = False
                            st.session_state.codigo_recuperacion = None
                            st.session_state.codigo_verificado = False
                            st.rerun()
                        else:
                            st.warning("Please enter a new password.")
    activar_interactividad_avanzada()
    st.stop()


# ----------------- MAIN APP -----------------
tickers_acc = [
    str(inv.get("simbolo", "AAPL")).split(" ")[0].upper().strip()
    for inv in datos.get("inversiones", [])
    if normalizar_tipo_activo_inv(inv.get("tipo")) in ["Stocks", "FCI", "Others"]
]

tickers_cri = [
    str(inv.get("simbolo", "BTC")).split(" ")[0].upper().strip()
    for inv in datos.get("inversiones", [])
    if normalizar_tipo_activo_inv(inv.get("tipo")) == "Cryptos"
]

tickers_bon = [
    str(inv.get("simbolo", "AL30")).split(" ")[0].upper().strip()
    for inv in datos.get("inversiones", [])
    if normalizar_tipo_activo_inv(inv.get("tipo")) == "Bonds"
]

cotizaciones = obtener_cotizaciones(tuple(tickers_acc), tuple(tickers_cri), tuple(tickers_bon))
usd_to_aud = cotizaciones["usd_to_aud"]

# ----------------- SIDEBAR (DATE AT TOP, NO TIME, NO BTC/DOLLAR BLUE, NO "MY PANEL") -----------------
ahora = datetime.now(TZ_SYDNEY)
dias = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday"
}
meses = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December"
}
dia_str = dias[ahora.weekday()]
mes_str = meses[ahora.month]
fecha_texto = f"Today is {dia_str}, {mes_str} {ahora.day}"
ultima_act_texto, ultima_act_iso = calcular_texto_ultima_actualizacion(datos, ahora)
stamp_archivo = ahora.strftime("%Y-%m-%d_%H-%M")

if "confirmar_cierre" not in st.session_state:
    st.session_state.confirmar_cierre = False


def finalizar_sesion():
    limpiar_token_sesion(datos)
    st.session_state.confirmar_cierre = False
    st.session_state.autenticado = False


with st.sidebar:
    gcal_url = _obtener_gcal_url()
    if gcal_url:
        eventos_cal_raw, err_cal = obtener_eventos_gcal(gcal_url, days_ahead=30)
        eventos_cal = [
            ev for ev in (eventos_cal_raw or [])
            if "update finapp costs" not in str(ev.get("title", "")).lower()
        ]
        st.markdown("<div style='font-size:0.95rem; font-weight:700; color:var(--fin-ink); margin-bottom:8px;'>📅 Coming Payments</div>", unsafe_allow_html=True)
        if err_cal:
            st.caption(f"⚠️ {err_cal}")
        elif not eventos_cal:
            st.caption("No upcoming events in the next 30 days.")
        else:
            import re as _re_cp
            for ev in eventos_cal[:5]:
                amt = ev["amount_aud"]
                clean_title = _re_cp.sub(
                    r'(?:[+-]\s*(?:AUD\s*)?\$?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?|(?:AUD\s*)?\$\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)',
                    '',
                    str(ev['title']),
                    flags=_re_cp.IGNORECASE,
                ).strip(" -–·") or str(ev['title'])
                days_left_i = int(ev.get("days_left", 99))
                if days_left_i <= 7:
                    urg_col = "#16A34A" if (amt is not None and amt > 0) else "#DC2626"
                else:
                    urg_col = "#4B5563"
                if amt is not None:
                    amt_str = f"+${amt:,.0f}" if amt > 0 else f"-${abs(amt):,.0f}"
                    amt_html = f"<span style='color:{urg_col}; font-weight:700; white-space:nowrap;'>{amt_str}</span>"
                else:
                    amt_html = ""
                st.markdown(
                    f"<div style='background:#F8FAFC; border:1px solid #E2E8F0; border-radius:10px; "
                    f"padding:7px 10px; margin-bottom:6px; font-size:0.84rem; line-height:1.35;'>"
                    f"<div style='display:flex; justify-content:space-between; align-items:center; gap:8px;'>"
                    f"<span style='font-weight:700; color:{urg_col};'>{clean_title}</span>{amt_html}</div>"
                    f"<div style='color:#64748B; font-weight:400; margin-top:2px;'>{ev['date_str']} · {ev['when']}</div></div>",
                    unsafe_allow_html=True,
                )
            if len(eventos_cal) > 5:
                with st.expander(f"+ {len(eventos_cal) - 5} more upcoming"):
                    for ev in eventos_cal[5:15]:
                        amt = ev["amount_aud"]
                        amt_txt = (f" (+${amt:,.0f})" if amt > 0 else f" (-${abs(amt):,.0f})") if amt is not None else ""
                        st.caption(f"• {ev['date_str']}: {ev['title']}{amt_txt}")
    st.markdown("---")

    REMINDER_OPTIONS = [
        (1, "1 day"),
        (7, "1 week"),
        (30, "1 month"),
        (60, "2 months"),
        (90, "1 quarter (90 days)"),
        (180, "6 months"),
        (0, "Off"),
    ]
    dias_rec_actual = int(datos.get("reminder_days", 90))
    idx_rec = next((i for i, opt in enumerate(REMINDER_OPTIONS) if opt[0] == dias_rec_actual), 4)
    sel_rec = st.selectbox(
        "🔔 Cost Review Reminder",
        options=REMINDER_OPTIONS,
        index=idx_rec,
        format_func=lambda o: o[1],
        key="side_reminder_freq",
    )
    if sel_rec[0] != dias_rec_actual:
        datos["reminder_days"] = sel_rec[0]
        guardar_datos(datos, registrar_cambio=False)
        if sel_rec[0] > 0:
            _notificar_reset_recordatorio_90d(datetime.now(TZ_SYDNEY), days=sel_rec[0], force=True)
        st.toast(f"🔔 Reminder set to: {sel_rec[1]}")

    if st.button("🔄 Refresh", key="btn_sidebar_actualizar", use_container_width=True):
        st.cache_data.clear()
        for k_reset in [
            "inv_detalle_manual_acc",
            "inv_detalle_manual_cri",
            "inv_detalle_manual_bon",
            "inv_detalle_manual_fci",
            "inv_detalle_manual_otros",
            "inv_ubicacion_nueva_manual"
        ]:
            st.session_state.pop(k_reset, None)
        st.rerun()

    with st.expander("🔐 Recovery Pswrd"):
        seg_actual = datos.get("seguridad", {})
        em_conf = st.text_input(
            "Recovery Email:",
            value=seg_actual.get("email_recuperacion", "julianherrero.jh@gmail.com"),
            key="side_email_rec"
        )
        tel_conf = st.text_input(
            "Recovery Mobile:",
            value=seg_actual.get("telefono_recuperacion", "+61493680014"),
            key="side_tel_rec"
        )
        smtp_conf = st.text_input(
            "Gmail App Password (optional):",
            value=seg_actual.get("smtp_app_password", ""),
            help="16-character Google App Password (optional).",
            key="side_smtp_rec"
        )
        wa_conf = st.text_input(
            "WhatsApp CallMeBot API Key (optional):",
            value=seg_actual.get("whatsapp_apikey", ""),
            help="Send 'I allow callmebot to send me messages' to +34 644 52 74 88 on WhatsApp to get your free key.",
            key="side_wa_rec"
        )
        if (
            em_conf != seg_actual.get("email_recuperacion", "")
            or tel_conf != seg_actual.get("telefono_recuperacion", "")
            or smtp_conf != seg_actual.get("smtp_app_password", "")
            or wa_conf != seg_actual.get("whatsapp_apikey", "")
        ):
            datos["seguridad"]["email_recuperacion"] = em_conf.strip()
            datos["seguridad"]["telefono_recuperacion"] = tel_conf.strip()
            datos["seguridad"]["smtp_app_password"] = smtp_conf.strip()
            datos["seguridad"]["whatsapp_apikey"] = wa_conf.strip()
            guardar_datos(datos)
            st.toast("✅ Recovery settings updated")

    if st.button("🚪 Log Out", use_container_width=True):
        registrar_snapshot_cierre(datos)
        st.session_state.confirmar_cierre = True
        st.rerun()

    st.markdown(
        f"<div style='text-align: center; color: var(--fin-muted); font-size: 0.85rem; margin-top: 8px;'>🕒 "
        f"<span id='finapp-last-saved' data-saved-ts='{ultima_act_iso}'>{ultima_act_texto}</span></div>",
        unsafe_allow_html=True,
    )

if st.session_state.confirmar_cierre:
    st.markdown(
        "<div style='background:#F8FAFC; border:1px solid #E2E8F0; border-radius:10px; "
        "padding:10px 14px; margin-bottom:10px; color:#1F2937; font-size:0.95rem; font-weight:600;'>"
        "✅ Changes saved</div>",
        unsafe_allow_html=True,
    )
    col_lo1, col_lo2 = st.columns(2, gap="small")
    with col_lo1:
        if st.button("Log Out", key="btn_confirm_logout", use_container_width=True):
            finalizar_sesion()
            st.rerun()
    with col_lo2:
        if st.button("Cancel", key="btn_cancel_logout", use_container_width=True):
            st.session_state.confirmar_cierre = False
            st.rerun()


# ----------------- AUTO-SAVE CALLBACKS -----------------
def crear_categoria_costo_auto():
    nom = st.session_state.get("input_nueva_cat_costo", "").strip()
    if nom and nom not in datos["categorias_costos"]:
        datos["categorias_costos"].append(nom)
        datos.setdefault("iconos_costos", {})[nom] = predecir_icono_categoria(nom, "costo")
        guardar_datos(datos)
        st.session_state["input_nueva_cat_costo"] = ""


def crear_categoria_ingreso_auto():
    nom = st.session_state.get("input_nueva_cat_ingreso", "").strip()
    if nom and nom not in datos["categorias_ingresos"]:
        datos["categorias_ingresos"].append(nom)
        datos.setdefault("iconos_ingresos", {})[nom] = predecir_icono_categoria(nom, "ingreso")
        guardar_datos(datos)
        st.session_state["input_nueva_cat_ingreso"] = ""


def auto_editar_cat_costo(cat_idx, nombre_viejo):
    nuevo_icono = st.session_state.get(f"edit_ico_c_{nombre_viejo}")
    nuevo_nombre = st.session_state.get(f"edit_nom_c_{nombre_viejo}", "").strip()
    modificado = False

    if nuevo_icono:
        datos.setdefault("iconos_costos", {})[nombre_viejo] = nuevo_icono
        modificado = True

    if nuevo_nombre and nuevo_nombre != nombre_viejo:
        if nuevo_nombre not in datos["categorias_costos"]:
            datos["categorias_costos"][cat_idx] = nuevo_nombre
            ico_actual = datos.get("iconos_costos", {}).pop(nombre_viejo, predecir_icono_categoria(nuevo_nombre, "costo"))
            datos["iconos_costos"][nuevo_nombre] = nuevo_icono or ico_actual
            for c in datos.get("costos", []):
                if c.get("grupo") == nombre_viejo:
                    c["grupo"] = nuevo_nombre
            modificado = True

    if modificado:
        guardar_datos(datos)


def auto_editar_cat_ingreso(cat_idx_i, nombre_viejo_i):
    nuevo_icono = st.session_state.get(f"edit_ico_i_{nombre_viejo_i}")
    nuevo_nombre = st.session_state.get(f"edit_nom_i_{nombre_viejo_i}", "").strip()
    modificado = False

    if nuevo_icono:
        datos.setdefault("iconos_ingresos", {})[nombre_viejo_i] = nuevo_icono
        modificado = True

    if nuevo_nombre and nuevo_nombre != nombre_viejo_i:
        if nuevo_nombre not in datos["categorias_ingresos"]:
            datos["categorias_ingresos"][cat_idx_i] = nuevo_nombre
            ico_actual = datos.get("iconos_ingresos", {}).pop(nombre_viejo_i, predecir_icono_categoria(nuevo_nombre, "ingreso"))
            datos["iconos_ingresos"][nuevo_nombre] = nuevo_icono or ico_actual
            for i in datos.get("ingresos", []):
                if i.get("grupo") == nombre_viejo_i:
                    i["grupo"] = nuevo_nombre
            modificado = True

    if modificado:
        guardar_datos(datos)


def mover_categoria_costo(idx_actual, direccion):
    cats = datos.get("categorias_costos", [])
    nuevo_idx = idx_actual + direccion
    if 0 <= idx_actual < len(cats) and 0 <= nuevo_idx < len(cats):
        cats[idx_actual], cats[nuevo_idx] = cats[nuevo_idx], cats[idx_actual]
        datos["categorias_costos"] = cats
        guardar_datos(datos)


def mover_categoria_ingreso(idx_actual, direccion):
    cats = datos.get("categorias_ingresos", [])
    nuevo_idx = idx_actual + direccion
    if 0 <= idx_actual < len(cats) and 0 <= nuevo_idx < len(cats):
        cats[idx_actual], cats[nuevo_idx] = cats[nuevo_idx], cats[idx_actual]
        datos["categorias_ingresos"] = cats
        guardar_datos(datos)


# ----------------- DASHBOARD (CAR CLUSTER GAUGES) HELPERS -----------------
DASHBOARD_DEFAULT_GAUGES = [
    {"id": "essentials", "name": "ESSENTIALS", "max": 4000, "opt_start": 1600, "opt_end": 2200, "is_investments": False},
    {"id": "treat_yourself", "name": "TREAT YOURSELF", "max": 1000, "opt_start": 400, "opt_end": 550, "is_investments": False},
    {"id": "trips_goals", "name": "TRIPS & GOALS", "max": 12000, "opt_start": 4800, "opt_end": 6600, "is_investments": False},
    {"id": "fire_extinguisher", "name": "FIRE EXTINGUISHER", "max": 10000, "opt_start": 4000, "opt_end": 5500, "is_investments": False},
    {"id": "emergency", "name": "EMERGENCY", "max": 22000, "opt_start": 8800, "opt_end": 12100, "is_investments": False},
    {"id": "investments", "name": "INVESTMENTS", "max": 40000, "opt_start": 5000, "opt_end": 20000, "is_investments": True},
]


def _obtener_balances_dashboard(datos, usd_to_aud, cotizaciones):
    balances = {
        "essentials": 0.0,
        "treat_yourself": 0.0,
        "trips_goals": 0.0,
        "fire_extinguisher": 0.0,
        "emergency": 0.0,
        "investments": 0.0,
        "super": 0.0,
    }

    # 1. Live Up Bank account balances
    up_tok = _obtener_up_token() or st.session_state.get("up_temp_token", "")
    if up_tok:
        cuentas_up, err_up = obtener_cuentas_up_bank(up_tok, st.session_state.get("up_refresh_nonce", 0))
        if cuentas_up and not err_up:
            for acc in cuentas_up:
                nm = str(acc.get("name", "")).lower()
                tp = str(acc.get("type", "")).upper()
                ow = str(acc.get("ownership", "")).upper()
                bal = float(acc.get("balance_aud", 0.0) or 0.0)
                if tp == "TRANSACTIONAL":
                    if ow == "JOINT" or "2up" in nm or "essential" in nm:
                        balances["essentials"] += bal
                    else:
                        balances["treat_yourself"] += bal
                else:
                    if "trip" in nm or "goal" in nm or "smile" in nm:
                        balances["trips_goals"] += bal
                    elif "fire" in nm or "extinguisher" in nm:
                        balances["fire_extinguisher"] += bal
                    elif "emerg" in nm or "mojo" in nm or "sos" in nm:
                        balances["emergency"] += bal

    # 2. Investments (liquid) & Super (non-liquid) from Net Worth + Live Binance
    for inv in datos.get("inversiones", []):
        if not inv.get("activo_inv", True):
            continue
        cant = float(inv.get("cantidad", 0) or 0)
        tipo = normalizar_tipo_activo_inv(inv.get("tipo", "Cash AUD"))
        activo_nom = str(inv.get("activo", tipo)).strip()
        plat = str(inv.get("plataforma", "")).strip()
        simbolo = str(inv.get("simbolo", "")).upper().strip().split(" ")[0]
        if tipo in ["Cryptos", "Stocks", "Bonds"]:
            det_t = activo_nom.split(" ")[0].upper()
            if det_t and det_t not in ["USD", "ARS", "AUD"]:
                simbolo = det_t

        val_aud = 0.0
        if tipo == "Cash AUD":
            val_aud = cant
        elif tipo == "Cash USD":
            val_aud = cant * usd_to_aud
        elif tipo in ["Cryptos", "Stocks"]:
            p_usd = cotizaciones.get(simbolo)
            if p_usd is not None and float(p_usd) > 0:
                val_aud = cant * float(p_usd) * usd_to_aud
        else:
            if simbolo and simbolo not in ["AUD", "USD", "ARS"] and simbolo in cotizaciones and float(cotizaciones[simbolo]) > 0:
                val_aud = cant * float(cotizaciones[simbolo]) * usd_to_aud
            else:
                p_u = float(inv.get("precio_unitario_aud", 1.0) or 0)
                if p_u > 0:
                    val_aud = cant * p_u

        if tipo == "Cryptos" and val_aud < 2.0:
            continue

        es_super = any(k in f"{activo_nom} {plat}".lower() for k in ["super", "hostplus", "australiansuper"])
        if es_super:
            balances["super"] += val_aud
        elif tipo in ["Stocks", "Cryptos", "Bonds", "FCI", "Others"]:
            balances["investments"] += val_aud

    bn_k, bn_s, bn_ru, bn_rs = _obtener_binance_keys()
    if bn_k and bn_s:
        bn_rows, bn_err = obtener_binance_portfolio(bn_k, bn_s, usd_to_aud, relay_url=bn_ru, relay_secret=bn_rs)
        if bn_rows and not bn_err:
            for b in bn_rows:
                val_b = float(b.get("val_aud", 0.0) or 0.0)
                if val_b >= 2.0:
                    balances["investments"] += val_b

    return balances


def _calcular_zonas_gauge(val, cfg):
    max_val = max(1.0, float(cfg.get("max", 4000)))
    opt_start = float(cfg.get("opt_start", 0.4 * max_val))
    opt_end = float(cfg.get("opt_end", 0.55 * max_val))
    is_inv = bool(cfg.get("is_investments", False))

    if is_inv:
        dead_end = min(500.0, max_val * 0.25)
        low_end = max(dead_end, min(opt_start, max_val))
        ok_end = max(low_end, min(opt_end, max_val))
        zonas = [
            (0.0, dead_end, "#E53935", "DEAD"),
            (dead_end, low_end, "#FB8C00", "LOW"),
            (low_end, ok_end, "#FBC02D", "OK"),
            (ok_end, max_val, "#43A047", "NICE"),
        ]
        if val <= dead_end:
            estado, estado_col = "DEAD", "#E53935"
        elif val <= low_end:
            estado, estado_col = "LOW", "#FB8C00"
        elif val <= ok_end:
            estado, estado_col = "OK", "#FBC02D"
        else:
            estado, estado_col = "NICE", "#43A047"
    else:
        target = max_val / 2.0
        dead_end = min(0.05 * target, max_val * 0.25)
        o_start = max(dead_end, min(opt_start, max_val))
        o_end = max(o_start, min(opt_end, max_val))
        zonas = [
            (0.0, dead_end, "#E53935", "DEAD"),
            (dead_end, o_start, "#FBC02D", "LOW"),
            (o_start, o_end, "#43A047", "OPTIMAL"),
            (o_end, max_val, "#E53935", "EXCESS"),
        ]
        if val <= dead_end:
            estado, estado_col = "DEAD", "#E53935"
        elif val < o_start:
            estado, estado_col = "LOW", "#FBC02D"
        elif val <= o_end:
            estado, estado_col = "OPTIMAL", "#43A047"
        else:
            estado, estado_col = "EXCESS", "#E53935"

    return zonas, estado, estado_col, max_val


def _html_gauge_cluster_card(cfg, val_aud, idx=0, super_aud=None):
    import math as _m
    zonas, estado, estado_col, max_val = _calcular_zonas_gauge(val_aud, cfg)
    is_inv = bool(cfg.get("is_investments", False))
    val_int = max(0, int(round(val_aud)))
    target_int = int(round(max_val / 2.0))
    max_int = int(round(max_val))
    angle_target = max(0.0, min(180.0, (float(val_aud) / max_val) * 180.0))

    cx, cy, r = 150.0, 136.0, 104.0

    def pt(ang_deg, rad=r):
        rad_a = _m.radians(180.0 - ang_deg)
        return cx + rad * _m.cos(rad_a), cy - rad * _m.sin(rad_a)

    arc_paths = []
    for z_start, z_end, z_col, _ in zonas:
        if z_end <= z_start:
            continue
        a1 = (z_start / max_val) * 180.0
        a2 = (z_end / max_val) * 180.0
        x1, y1 = pt(a1)
        x2, y2 = pt(a2)
        large_arc = 1 if (a2 - a1) > 180 else 0
        arc_paths.append(
            f'<path d="M {x1:.2f} {y1:.2f} A {r} {r} 0 {large_arc} 1 {x2:.2f} {y2:.2f}" '
            f'fill="none" stroke="{z_col}" stroke-width="11" stroke-linecap="butt" '
            f'style="filter: drop-shadow(0 2px 5px {z_col}55);"/>'
        )

    ticks = []
    for t_i in range(0, 21):
        ang = t_i * 9.0
        is_maj = (t_i % 5 == 0)
        r_in = r - (16 if is_maj else 11)
        r_out = r - 7
        tx1, ty1 = pt(ang, r_in)
        tx2, ty2 = pt(ang, r_out)
        sw = "1.7" if is_maj else "0.9"
        cls_t = "tick-maj" if is_maj else "tick-min"
        ticks.append(f'<line class="{cls_t}" x1="{tx1:.1f}" y1="{ty1:.1f}" x2="{tx2:.1f}" y2="{ty2:.1f}" stroke-width="{sw}" stroke-linecap="round"/>')

    def fmt_k(n):
        if n >= 1000 and n % 1000 == 0:
            return f"{n // 1000}k"
        return f"{n:,}"

    mid_lbl = fmt_k(target_int)
    max_lbl = fmt_k(max_int) + ("+" if is_inv else "")

    uid = f"g_{cfg['id']}_{idx}"
    delay_ms = idx * 90
    _g_dark = _detectar_tema_oscuro()
    _g_title_col = "#F3F4F6" if _g_dark else "#111827"
    _g_scale_col = "#CBD5E1" if _g_dark else "#475569"
    _g_dial_bg = "#161B22" if _g_dark else "#F8FAFC"
    _g_dial_edge = "#334155" if _g_dark else "#E2E8F0"
    _g_track = "#262E3B" if _g_dark else "#E2E8F0"
    _g_tick_maj = "#94A3B8" if _g_dark else "#475569"
    _g_tick_min = "#475569" if _g_dark else "#CBD5E1"

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  :root {{
    --g-title: {_g_title_col};
    --g-scale: {_g_scale_col};
    --g-dial-bg: {_g_dial_bg};
    --g-dial-edge: {_g_dial_edge};
    --g-track: {_g_track};
    --g-tick-maj: {_g_tick_maj};
    --g-tick-min: {_g_tick_min};
  }}
  html[data-theme="dark"] {{
    --g-title: #F3F4F6;
    --g-scale: #CBD5E1;
    --g-dial-bg: #161B22;
    --g-dial-edge: #334155;
    --g-track: #262E3B;
    --g-tick-maj: #94A3B8;
    --g-tick-min: #475569;
  }}
  html[data-theme="light"] {{
    --g-title: #0F172A;
    --g-scale: #475569;
    --g-dial-bg: #F8FAFC;
    --g-dial-edge: #E2E8F0;
    --g-track: #E2E8F0;
    --g-tick-maj: #475569;
    --g-tick-min: #CBD5E1;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: transparent;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    overflow: hidden;
  }}
  .cluster-card {{
    background: transparent;
    padding: 4px 4px 0 4px;
    text-align: center;
  }}
  .gauge-head {{
    display: flex;
    justify-content: center;
    align-items: center;
    margin-bottom: 2px;
  }}
  .gauge-title {{
    font-size: 0.84rem;
    font-weight: 800;
    letter-spacing: 0.14em;
    color: var(--g-title);
    text-transform: uppercase;
  }}
  svg {{
    width: 100%;
    max-width: 280px;
    height: auto;
    display: block;
    margin: 0 auto;
    overflow: visible;
  }}
  .dial-bg {{ fill: var(--g-dial-bg); stroke: var(--g-dial-edge); stroke-width: 1.2; }}
  .dial-track {{ fill: none; stroke: var(--g-track); stroke-width: 12; }}
  .scale-lbl {{ fill: var(--g-scale); font-size: 10.5px; font-weight: 700; }}
  .tick-maj {{ stroke: var(--g-tick-maj); }}
  .tick-min {{ stroke: var(--g-tick-min); }}
</style>
</head>
<body>
  <div class="cluster-card" id="{uid}_card">
    <div class="gauge-head">
      <span class="gauge-title">{cfg['name']}</span>
    </div>
    <svg viewBox="0 0 300 154">
      <defs>
        <filter id="{uid}_shadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#0F172A" flood-opacity="0.32"/>
        </filter>
        <radialGradient id="{uid}_hub" cx="38%" cy="32%" r="68%">
          <stop offset="0%" stop-color="#64748B"/>
          <stop offset="55%" stop-color="#1E293B"/>
          <stop offset="100%" stop-color="#0F172A"/>
        </radialGradient>
      </defs>
      <path class="dial-bg" d="M 32 136 A 118 118 0 0 1 268 136 Z"/>
      <path class="dial-track" d="M 46 136 A 104 104 0 0 1 254 136"/>
      {''.join(arc_paths)}
      {''.join(ticks)}
      <text class="scale-lbl" x="20" y="150" text-anchor="middle">0</text>
      <text class="scale-lbl" x="150" y="15" text-anchor="middle">{mid_lbl}</text>
      <text class="scale-lbl" x="280" y="150" text-anchor="middle">{max_lbl}</text>
      <g id="{uid}_needle" transform="rotate(-90 150 136)" filter="url(#{uid}_shadow)">
        <polygon points="147.8,136 152.2,136 150.7,40 149.3,40" fill="#FF4D2A"/>
      </g>
      <circle cx="150" cy="136" r="11" fill="url(#{uid}_hub)" stroke="#CBD5E1" stroke-width="1.5"/>
    </svg>
  </div>
  <script>
    (function() {{
      try {{
        const cands = [
          window.parent.document.querySelector('[data-testid="stAppViewContainer"]'),
          window.parent.document.querySelector('.stApp'),
          window.parent.document.body
        ];
        for (const el of cands) {{
          if (!el) continue;
          const bg = window.parent.getComputedStyle(el).backgroundColor || '';
          const m = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/i);
          if (m) {{
            const alpha = m[4] !== undefined ? parseFloat(m[4]) : 1.0;
            if (alpha > 0.1) {{
              const lum = (0.299 * +m[1] + 0.587 * +m[2] + 0.114 * +m[3]);
              document.documentElement.setAttribute('data-theme', lum < 128 ? 'dark' : 'light');
              break;
            }}
          }}
        }}
      }} catch (e) {{}}

      const needle = document.getElementById('{uid}_needle');
      const targetAngle = {angle_target:.2f};
      let played = false;

      function easeOutBack(t) {{
        const c1 = 1.15;
        const c3 = c1 + 1;
        return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
      }}

      function playIgnition() {{
        const duration = 1800;
        const start = performance.now() + {delay_ms};
        function frame(now) {{
          if (now < start) {{
            requestAnimationFrame(frame);
            return;
          }}
          const p = Math.min(1, (now - start) / duration);
          const eased = easeOutBack(p);
          const curAng = Math.max(0, Math.min(182, targetAngle * eased));
          needle.setAttribute('transform', 'rotate(' + (curAng - 90).toFixed(2) + ' 150 136)');
          if (p < 1) {{
            requestAnimationFrame(frame);
          }} else {{
            needle.setAttribute('transform', 'rotate(' + (targetAngle - 90).toFixed(2) + ' 150 136)');
          }}
        }}
        requestAnimationFrame(frame);
      }}

      const obs = new IntersectionObserver((entries) => {{
        entries.forEach(en => {{
          if (en.isIntersecting && !played) {{
            played = true;
            playIgnition();
          }} else if (!en.isIntersecting) {{
            played = false;
            needle.setAttribute('transform', 'rotate(-90 150 136)');
          }}
        }});
      }}, {{ threshold: 0.15 }});
      obs.observe(document.getElementById('{uid}_card'));
    }})();
  </script>
</body>
</html>
"""


def _html_odometer_box(val_aud):
    val_int = max(0, int(round(val_aud)))
    val_str = f"{val_int:,}"
    cells_html = "".join(
        "<span class='finapp-odo-sep'>,</span>" if ch == "," else f"<span class='finapp-odo-cell'>{ch}</span>"
        for ch in val_str
    )
    return f"<div class='finapp-odo-box'>{cells_html}<span class='finapp-odo-aud'>AUD</span></div>"


# ----------------- MAIN TABS (REORDERABLE) -----------------
DEFAULT_TAB_ORDER = [
    "🕹️ DASHBOARD",
    "📊 COSTS & INCOME",
    "💼 TOTAL NET WORTH",
    "⚡ LIVE CASH FLOW"
]

orden_tabs_guardado = datos.get("tab_order", DEFAULT_TAB_ORDER)
if isinstance(orden_tabs_guardado, list) and any(t in ("🎛️ DASHBOARD", "⚙️ DASHBOARD", "DASHBOARD") for t in orden_tabs_guardado):
    orden_tabs_guardado = ["🕹️ DASHBOARD" if t in ("🎛️ DASHBOARD", "⚙️ DASHBOARD", "DASHBOARD") else t for t in orden_tabs_guardado]
    datos["tab_order"] = orden_tabs_guardado
    guardar_datos(datos, registrar_cambio=False)
if (
    not isinstance(orden_tabs_guardado, list)
    or set(orden_tabs_guardado) != set(DEFAULT_TAB_ORDER)
    or len(orden_tabs_guardado) != len(DEFAULT_TAB_ORDER)
):
    orden_tabs_guardado = list(DEFAULT_TAB_ORDER)

st.markdown("<div class='hook-tabs-row'></div>", unsafe_allow_html=True)
if st.button("⇄", key="btn_cycle_tabs_order", help="Switch tab order"):
    nuevo_orden = orden_tabs_guardado[1:] + orden_tabs_guardado[:1]
    datos["tab_order"] = nuevo_orden
    guardar_datos(datos, registrar_cambio=False)
    st.rerun()

tabs_creadas = st.tabs(orden_tabs_guardado)
mapa_tabs = dict(zip(orden_tabs_guardado, tabs_creadas))
pestana0 = mapa_tabs["🕹️ DASHBOARD"]
pestana1 = mapa_tabs["📊 COSTS & INCOME"]
pestana2 = mapa_tabs["💼 TOTAL NET WORTH"]
pestana3 = mapa_tabs["⚡ LIVE CASH FLOW"]

# =========================================================================
# ============================= TAB 0: DASHBOARD ==========================
# =========================================================================
with pestana0:
    dash_balances = _obtener_balances_dashboard(datos, usd_to_aud, cotizaciones)
    cfg_guardada = datos.setdefault("dashboard_gauges", {})

    # 3x2 grid on desktop (auto-stacks cleanly on mobile)
    for row_start in (0, 3):
        cols_dash = st.columns(3, gap="medium")
        for col_i in range(3):
            g_idx = row_start + col_i
            base_cfg = DASHBOARD_DEFAULT_GAUGES[g_idx]
            g_id = base_cfg["id"]
            g_cfg = cfg_guardada.setdefault(g_id, dict(base_cfg))
            for k_def, v_def in base_cfg.items():
                g_cfg.setdefault(k_def, v_def)

            val_actual = dash_balances.get(g_id, 0.0)
            sup_extra = dash_balances.get("super", 0.0) if g_cfg.get("is_investments") else None

            with cols_dash[col_i]:
                st.markdown("<div class='hook-odo-row' style='display:none;'></div>", unsafe_allow_html=True)
                c_gear, c_odo = st.columns([0.85, 3.15], gap="small")
                with c_odo:
                    st.markdown(_html_odometer_box(val_actual), unsafe_allow_html=True)
                with c_gear:
                    with st.popover("⚙️", help=f"Configure {g_cfg['name']} gauge"):
                        cur_max = int(g_cfg.get("max", base_cfg["max"]))
                        new_max = st.number_input(
                            "Max value (AUD)",
                            min_value=100,
                            max_value=5000000,
                            value=cur_max,
                            step=500,
                            key=f"dash_max_{g_id}",
                        )
                        cur_o1 = max(0, min(int(g_cfg.get("opt_start", base_cfg["opt_start"])), int(new_max)))
                        cur_o2 = max(cur_o1, min(int(g_cfg.get("opt_end", base_cfg["opt_end"])), int(new_max)))
                        lbl_rng = "OK / NICE range (AUD)" if g_cfg.get("is_investments") else "Optimal range (AUD)"
                        new_o1, new_o2 = st.slider(
                            lbl_rng,
                            min_value=0,
                            max_value=int(new_max),
                            value=(cur_o1, cur_o2),
                            step=50 if int(new_max) <= 5000 else 100,
                            key=f"dash_rng_{g_id}",
                        )
                        if new_max != cur_max or new_o1 != cur_o1 or new_o2 != cur_o2:
                            g_cfg["max"] = int(new_max)
                            g_cfg["opt_start"] = int(new_o1)
                            g_cfg["opt_end"] = int(new_o2)
                            guardar_datos(datos, registrar_cambio=False)
                            st.rerun()
                components.html(
                    _html_gauge_cluster_card(g_cfg, val_actual, idx=g_idx, super_aud=sup_extra),
                    height=188,
                )
                if g_cfg.get("is_investments") and sup_extra is not None:
                    _sup_i = max(0, int(round(sup_extra)))
                    _tot_i = max(0, int(round(val_actual))) + _sup_i
                    st.markdown(
                        f"<div class='finapp-inv-sub'>SUPER <b>{_sup_i:,} AUD</b> &nbsp;·&nbsp; TOTAL <b>{_tot_i:,} AUD</b></div>",
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    "<div style='height: 48px; display: flex; align-items: center;'>"
                    "<div style='width: 100%; border-top: 1px solid var(--fin-border-muted); opacity: 0.4;'></div>"
                    "</div>",
                    unsafe_allow_html=True,
                )


    tnw_total_aud = sum(
        float(dash_balances.get(k, 0.0) or 0.0)
        for k in ["essentials", "treat_yourself", "trips_goals", "fire_extinguisher", "emergency", "investments", "super"]
    )
    if "dash_tnw_visible" not in st.session_state:
        st.session_state["dash_tnw_visible"] = True

    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    c_tnw_sp1, c_tnw_txt, c_tnw_eye, c_tnw_sp2 = st.columns([3.0, 2.8, 0.65, 3.0])
    with c_tnw_txt:
        tnw_str = f"TNW = ${int(round(tnw_total_aud)):,} AUD" if st.session_state["dash_tnw_visible"] else "TNW = ••••••"
        st.markdown(
            f"<div style='text-align:right; font-size:1.30rem; font-weight:800; color:var(--fin-ink); "
            f"letter-spacing:0.04em; line-height:38px;'>{tnw_str}</div>",
            unsafe_allow_html=True,
        )
    with c_tnw_eye:
        eye_lbl = "👁" if st.session_state["dash_tnw_visible"] else "🙈"
        if st.button(eye_lbl, key="btn_toggle_tnw_vis", help="Show / hide Total Net Worth"):
            st.session_state["dash_tnw_visible"] = not st.session_state["dash_tnw_visible"]
            st.rerun()


# =========================================================================
# ============================= TAB 1 =====================================
# =========================================================================
with pestana1:
    try:
        ts_chk = str(datos.get("ultima_actualizacion_ts") or datos.get("ultima_actualizacion") or "").strip()
        if ts_chk:
            dt_chk = datetime.fromisoformat(ts_chk) if "T" in ts_chk else datetime.strptime(ts_chk[:10], "%Y-%m-%d").replace(tzinfo=TZ_SYDNEY)
            if dt_chk.tzinfo is None:
                dt_chk = dt_chk.replace(tzinfo=TZ_SYDNEY)
            dias_limite = int(datos.get("reminder_days", 90))
            dias_sin_act = (datetime.now(TZ_SYDNEY).date() - dt_chk.astimezone(TZ_SYDNEY).date()).days
            if dias_limite > 0 and dias_sin_act >= dias_limite:
                st.warning(
                    f"⚠️ **Cost Review Due ({dias_limite}-day target):** You haven't updated your costs in **{dias_sin_act} days**. "
                    "Review your bills and subscriptions to keep up with price changes and inflation."
                )
    except Exception:
        pass
    total_items_costos = len(datos["costos"])
    costos_activos = [c for c in datos["costos"] if c.get("activo", True)]
    total_costos = sum(c["monto"] for c in costos_activos)

    total_items_ingresos = len(datos["ingresos"])
    ingresos_activos = [i for i in datos["ingresos"] if i.get("activo", True)]
    total_ingresos = sum(i["monto"] for i in ingresos_activos)

    saldo_neto = total_ingresos - total_costos

    if saldo_neto > 0:
        clase_saldo = "metric-card-ingreso"
        carita = "😊"
        sub_saldo = "Positive savings"
    elif saldo_neto == 0 or (total_ingresos > 0 and abs(saldo_neto) < 0.10 * total_ingresos):
        clase_saldo = "metric-card-amarillo-mate"
        carita = "😐"
        sub_saldo = "Break-even" if saldo_neto == 0 else "Facing losses"
    else:
        clase_saldo = "metric-card-costo"
        carita = "😟"
        sub_saldo = "Facing losses"

    col_kpi1, col_kpi2, col_kpi3 = st.columns(3, gap="medium")
    with col_kpi1:
        st.markdown(f"""
        <div class="metric-card metric-card-costo">
            <div class="kpi-title">Weekly Costs</div>
            <div class="kpi-value">${total_costos:,.0f} AUD</div>
            <div class="kpi-sub">{len(costos_activos)} active of {total_items_costos}</div>
        </div>
        """, unsafe_allow_html=True)

    with col_kpi2:
        st.markdown(f"""
        <div class="metric-card metric-card-ingreso">
            <div class="kpi-title">Weekly Income</div>
            <div class="kpi-value">${total_ingresos:,.0f} AUD</div>
            <div class="kpi-sub">{len(ingresos_activos)} active of {total_items_ingresos}</div>
        </div>
        """, unsafe_allow_html=True)

    with col_kpi3:
        st.markdown(f"""
        <div class="metric-card {clase_saldo}">
            <div class="kpi-title">Weekly Savings {carita}</div>
            <div class="kpi-value">${saldo_neto:,.0f} AUD</div>
            <div class="kpi-sub">{sub_saldo}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    col_izq, col_der = st.columns(2, gap="medium")

    # ---------------- COSTS ----------------
    with col_izq:
        st.markdown("<h3 style='color: var(--fin-ink); margin-bottom: 6px;'>📉 My Weekly Costs</h3>", unsafe_allow_html=True)
        st.markdown("<div class='hook-agregar-costo' style='display:none;'></div>", unsafe_allow_html=True)

        with st.expander("➕ ADD NEW COST CATEGORY"):
            c_nc1, c_nc2 = st.columns([3.6, 0.45])
            with c_nc1:
                st.text_input(
                    "Category Name (e.g. HOUSING, UTILITIES, TRANSPORT)",
                    placeholder="Type category name...",
                    key="input_nueva_cat_costo",
                    on_change=crear_categoria_costo_auto
                )
            with c_nc2:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("+", key="btn_crear_cat_c", help="Add category"):
                    crear_categoria_costo_auto()
                    st.rerun()

        costos_modificados = False
        for cat_idx, cat_nombre in enumerate(list(datos["categorias_costos"])):
            items_cat = [
                (idx, item) for idx, item in enumerate(datos["costos"])
                if item.get("grupo", "HOME & OTHERS") == cat_nombre
            ]
            sub_aud = sum(i["monto"] for _, i in items_cat if i.get("activo", True))
            icono_cat = datos.get("iconos_costos", {}).get(cat_nombre, predecir_icono_categoria(cat_nombre, "costo"))

            titulo_cat = f"{icono_cat} **{cat_nombre}** — subt= **${sub_aud:,.0f} AUD**"
            col_exp_c, col_arrows_c = st.columns([0.94, 0.06], gap="small")
            with col_arrows_c:
                st.markdown("<div class='flechas-cat-stack'></div>", unsafe_allow_html=True)
                st.button(
                    "▲",
                    key=f"btn_up_c_{cat_nombre}",
                    disabled=(cat_idx == 0),
                    help=f"Move {cat_nombre} up",
                    on_click=mover_categoria_costo,
                    args=(cat_idx, -1)
                )
                st.button(
                    "▼",
                    key=f"btn_down_c_{cat_nombre}",
                    disabled=(cat_idx == len(datos["categorias_costos"]) - 1),
                    help=f"Move {cat_nombre} down",
                    on_click=mover_categoria_costo,
                    args=(cat_idx, 1)
                )
            with col_exp_c.expander(titulo_cat, expanded=False):
                editar_cat = st.checkbox(
                    "✏️ Edit category name or icon",
                    key=f"chk_edit_c_{cat_nombre}"
                )
                if editar_cat:
                    opciones_ico = list(dict.fromkeys([icono_cat] + ICONOS_DISPONIBLES))
                    ec1, ec2 = st.columns([1.0, 3.0])
                    with ec1:
                        st.selectbox(
                            "Icon",
                            options=opciones_ico,
                            index=0,
                            key=f"edit_ico_c_{cat_nombre}",
                            label_visibility="collapsed",
                            on_change=auto_editar_cat_costo,
                            args=(cat_idx, cat_nombre)
                        )
                    with ec2:
                        st.text_input(
                            "Category Name",
                            value=cat_nombre,
                            key=f"edit_nom_c_{cat_nombre}",
                            label_visibility="collapsed",
                            on_change=auto_editar_cat_costo,
                            args=(cat_idx, cat_nombre)
                        )

                if items_cat:
                    h1, h2, h3, h4 = st.columns([0.58, 2.35, 1.45, 0.55])
                    h1.markdown("<div class='col-header'>ACT.</div>", unsafe_allow_html=True)
                    h2.markdown("<div class='col-header'>SUBCATEGORY</div>", unsafe_allow_html=True)
                    h3.markdown("<div class='col-header'>AMOUNT (AUD)</div>", unsafe_allow_html=True)
                    h4.markdown("<div class='col-header'>DEL</div>", unsafe_allow_html=True)

                for idx, item in items_cat:
                    estado_check = item.get("activo", True)
                    c_box, c_nombre, c_monto, c_del = st.columns([0.58, 2.35, 1.45, 0.55])
                    with c_box:
                        nuevo_estado = st.checkbox(
                            "Active",
                            value=estado_check,
                            key=f"costo_check_{idx}",
                            label_visibility="collapsed"
                        )
                        if nuevo_estado != estado_check:
                            item["activo"] = nuevo_estado
                            costos_modificados = True
                    with c_nombre:
                        nuevo_nom = st.text_input(
                            "Subcategory",
                            value=item["categoria"],
                            key=f"costo_nom_{idx}",
                            label_visibility="collapsed",
                            disabled=not estado_check
                        )
                        if nuevo_nom != item["categoria"]:
                            item["categoria"] = nuevo_nom
                            costos_modificados = True
                    with c_monto:
                        monto_str = formatear_cant(item["monto"])
                        nuevo_val_str = st.text_input(
                            "Amount",
                            value=monto_str,
                            key=f"costo_val_{idx}",
                            label_visibility="collapsed",
                            disabled=not estado_check
                        )
                        try:
                            nuevo_val = float(nuevo_val_str.replace(",", "."))
                            if nuevo_val != float(item["monto"]):
                                item["monto"] = int(nuevo_val) if nuevo_val.is_integer() else nuevo_val
                                costos_modificados = True
                        except ValueError:
                            pass
                    with c_del:
                        if st.button("🗑️", key=f"costo_del_{idx}", help="Delete this item"):
                            datos["costos"].pop(idx)
                            guardar_datos(datos)
                            st.rerun()

                with st.form(f"form_sub_costo_{cat_nombre}", clear_on_submit=True):
                    sc1, sc2, sc3 = st.columns([2.55, 1.55, 0.5])
                    with sc1:
                        sub_nom_c = st.text_input(
                            "New subcategory",
                            placeholder=f"New item in {cat_nombre}...",
                            label_visibility="collapsed"
                        )
                    with sc2:
                        sub_val_c = st.text_input(
                            "Amount AUD",
                            placeholder="Amount AUD",
                            label_visibility="collapsed"
                        )
                    with sc3:
                        btn_sub_c = st.form_submit_button("+", help="Add item")
                        if btn_sub_c and sub_nom_c.strip():
                            try:
                                m_num = float(sub_val_c.strip().replace(",", ".")) if sub_val_c.strip() else 0
                            except ValueError:
                                m_num = 0
                            datos["costos"].append({
                                "grupo": cat_nombre,
                                "categoria": sub_nom_c.strip(),
                                "monto": int(m_num) if float(m_num).is_integer() else m_num,
                                "activo": True
                            })
                            guardar_datos(datos)
                            st.rerun()

                if not items_cat:
                    st.markdown("<div class='hook-del-cat-vacia'></div>", unsafe_allow_html=True)
                    if st.button(
                        "🗑️",
                        key=f"del_cat_c_{cat_nombre}",
                        help="Delete category"
                    ):
                        datos["categorias_costos"].remove(cat_nombre)
                        guardar_datos(datos)
                        st.rerun()

        if costos_modificados:
            guardar_datos(datos)
            st.rerun()

    # ---------------- INCOME ----------------
    with col_der:
        st.markdown("<h3 style='color: var(--fin-ink); margin-bottom: 6px;'>📈 My Weekly Income</h3>", unsafe_allow_html=True)
        st.markdown("<div class='hook-agregar-ingreso' style='display:none;'></div>", unsafe_allow_html=True)

        with st.expander("➕ ADD NEW INCOME CATEGORY"):
            c_ni1, c_ni2 = st.columns([3.6, 0.45])
            with c_ni1:
                st.text_input(
                    "Category Name (e.g. Work, Freelance, Other)",
                    placeholder="Type category name...",
                    key="input_nueva_cat_ingreso",
                    on_change=crear_categoria_ingreso_auto
                )
            with c_ni2:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("+", key="btn_crear_cat_i", help="Add category"):
                    crear_categoria_ingreso_auto()
                    st.rerun()

        ingresos_modificados = False
        for cat_idx_i, cat_nombre_i in enumerate(list(datos["categorias_ingresos"])):
            items_cat_i = [
                (idx, item) for idx, item in enumerate(datos["ingresos"])
                if item.get("grupo", "Other Income") == cat_nombre_i
            ]
            sub_aud_i = sum(i["monto"] for _, i in items_cat_i if i.get("activo", True))
            icono_cat_i = datos.get("iconos_ingresos", {}).get(cat_nombre_i, predecir_icono_categoria(cat_nombre_i, "ingreso"))

            titulo_cat_i = f"{icono_cat_i} **{cat_nombre_i}** — subt= **${sub_aud_i:,.0f} AUD**"
            col_exp_i, col_arrows_i = st.columns([0.94, 0.06], gap="small")
            with col_arrows_i:
                st.markdown("<div class='flechas-cat-stack'></div>", unsafe_allow_html=True)
                st.button(
                    "▲",
                    key=f"btn_up_i_{cat_nombre_i}",
                    disabled=(cat_idx_i == 0),
                    help=f"Move {cat_nombre_i} up",
                    on_click=mover_categoria_ingreso,
                    args=(cat_idx_i, -1)
                )
                st.button(
                    "▼",
                    key=f"btn_down_i_{cat_nombre_i}",
                    disabled=(cat_idx_i == len(datos["categorias_ingresos"]) - 1),
                    help=f"Move {cat_nombre_i} down",
                    on_click=mover_categoria_ingreso,
                    args=(cat_idx_i, 1)
                )
            with col_exp_i.expander(titulo_cat_i, expanded=False):
                editar_cat_i = st.checkbox(
                    "✏️ Edit category name or icon",
                    key=f"chk_edit_i_{cat_nombre_i}"
                )
                if editar_cat_i:
                    opciones_ico_i = list(dict.fromkeys([icono_cat_i] + ICONOS_DISPONIBLES))
                    ei1, ei2 = st.columns([1.0, 3.0])
                    with ei1:
                        st.selectbox(
                            "Icon",
                            options=opciones_ico_i,
                            index=0,
                            key=f"edit_ico_i_{cat_nombre_i}",
                            label_visibility="collapsed",
                            on_change=auto_editar_cat_ingreso,
                            args=(cat_idx_i, cat_nombre_i)
                        )
                    with ei2:
                        st.text_input(
                            "Category Name",
                            value=cat_nombre_i,
                            key=f"edit_nom_i_{cat_nombre_i}",
                            label_visibility="collapsed",
                            on_change=auto_editar_cat_ingreso,
                            args=(cat_idx_i, cat_nombre_i)
                        )

                if items_cat_i:
                    hi1, hi2, hi3, hi4 = st.columns([0.58, 2.35, 1.45, 0.55])
                    hi1.markdown("<div class='col-header'>ACT.</div>", unsafe_allow_html=True)
                    hi2.markdown("<div class='col-header'>SUBCATEGORY</div>", unsafe_allow_html=True)
                    hi3.markdown("<div class='col-header'>AMOUNT (AUD)</div>", unsafe_allow_html=True)
                    hi4.markdown("<div class='col-header'>DEL</div>", unsafe_allow_html=True)

                for idx, item in items_cat_i:
                    estado_check = item.get("activo", True)
                    c_box, c_nombre, c_monto, c_del = st.columns([0.58, 2.35, 1.45, 0.55])
                    with c_box:
                        nuevo_estado = st.checkbox(
                            "Active",
                            value=estado_check,
                            key=f"ing_check_{idx}",
                            label_visibility="collapsed"
                        )
                        if nuevo_estado != estado_check:
                            item["activo"] = nuevo_estado
                            ingresos_modificados = True
                    with c_nombre:
                        nuevo_nom = st.text_input(
                            "Concept",
                            value=item["concepto"],
                            key=f"ing_nom_{idx}",
                            label_visibility="collapsed",
                            disabled=not estado_check
                        )
                        if nuevo_nom != item["concepto"]:
                            item["concepto"] = nuevo_nom
                            ingresos_modificados = True
                    with c_monto:
                        monto_i_str = formatear_cant(item["monto"])
                        nuevo_val_i_str = st.text_input(
                            "Amount",
                            value=monto_i_str,
                            key=f"ing_val_{idx}",
                            label_visibility="collapsed",
                            disabled=not estado_check
                        )
                        try:
                            nuevo_val_i = float(nuevo_val_i_str.replace(",", "."))
                            if nuevo_val_i != float(item["monto"]):
                                item["monto"] = int(nuevo_val_i) if nuevo_val_i.is_integer() else nuevo_val_i
                                ingresos_modificados = True
                        except ValueError:
                            pass
                    with c_del:
                        if st.button("🗑️", key=f"ing_del_{idx}", help="Delete this income"):
                            datos["ingresos"].pop(idx)
                            guardar_datos(datos)
                            st.rerun()

                with st.form(f"form_sub_ing_{cat_nombre_i}", clear_on_submit=True):
                    si1, si2, si3 = st.columns([2.55, 1.55, 0.5])
                    with si1:
                        sub_nom_i = st.text_input(
                            "New income",
                            placeholder=f"New item in {cat_nombre_i}...",
                            label_visibility="collapsed"
                        )
                    with si2:
                        sub_val_i = st.text_input(
                            "Amount AUD",
                            placeholder="Amount AUD",
                            label_visibility="collapsed"
                        )
                    with si3:
                        btn_sub_i = st.form_submit_button("+", help="Add item")
                        if btn_sub_i and sub_nom_i.strip():
                            try:
                                mi_num = float(sub_val_i.strip().replace(",", ".")) if sub_val_i.strip() else 0
                            except ValueError:
                                mi_num = 0
                            datos["ingresos"].append({
                                "grupo": cat_nombre_i,
                                "concepto": sub_nom_i.strip(),
                                "monto": int(mi_num) if float(mi_num).is_integer() else mi_num,
                                "activo": True
                            })
                            guardar_datos(datos)
                            st.rerun()

                if not items_cat_i:
                    st.markdown("<div class='hook-del-cat-vacia'></div>", unsafe_allow_html=True)
                    if st.button(
                        "🗑️",
                        key=f"del_cat_i_{cat_nombre_i}",
                        help="Delete category"
                    ):
                        datos["categorias_ingresos"].remove(cat_nombre_i)
                        guardar_datos(datos)
                        st.rerun()

        if ingresos_modificados:
            guardar_datos(datos)
            st.rerun()

    st.markdown("---")

    st.markdown(
        "<h3 style='color: var(--fin-ink);'>📊 Charts & Tables</h3>",
        unsafe_allow_html=True
    )
    modo_grafico = st.radio(
        "Chart mode",
        ["By Category (Subtotals)", "Detailed by Subcategory"],
        horizontal=True,
        label_visibility="collapsed"
    )

    proporcion_cols_grafico = [1.4, 0.9] if modo_grafico.startswith("By Category") else [1, 1]
    col_chart_c, col_chart_i = st.columns(proporcion_cols_grafico, gap="medium")

    with col_chart_c:
        st.markdown(
            "<h4 style='color: var(--fin-ink); text-align: center;'>Costs Breakdown</h4>",
            unsafe_allow_html=True
        )
        if costos_activos and total_costos > 0:
            df_c_raw = pd.DataFrame(costos_activos)
            if modo_grafico.startswith("By Category"):
                df_pie_c = df_c_raw.groupby("grupo", as_index=False)["monto"].sum().sort_values(by="monto", ascending=False)
                col_label_c = "grupo"
                titulo_col_c = "Category"
                fig_c = crear_torta_2d(df_pie_c, "monto", col_label_c, tamano="grande", usar_minusculas=True, paleta=PALETA_COSTOS)
            else:
                df_pie_c = df_c_raw.sort_values(by="monto", ascending=False).copy()
                df_pie_c["etiqueta"] = df_pie_c["categoria"]
                col_label_c = "etiqueta"
                titulo_col_c = "Subcategory"
                fig_c = crear_barras_horizontales(df_pie_c, "monto", col_label_c, color_barra="#DC2626")

            df_pie_c["Percentage"] = (df_pie_c["monto"] / total_costos) * 100

            st.plotly_chart(fig_c, use_container_width=True, config={"displayModeBar": False})

            tabla_c = df_pie_c[[col_label_c, "monto", "Percentage"]].copy()
            tabla_c.columns = [titulo_col_c, "Subtotal (AUD)", "% of Total"]
            tabla_c["Subtotal (AUD)"] = tabla_c["Subtotal (AUD)"].apply(lambda x: f"${x:,.0f} AUD")
            tabla_c["% of Total"] = tabla_c["% of Total"].apply(lambda x: f"{x:.1f}%")
            if modo_grafico.startswith("By Category"):
                _cmap_c = {row_v: PALETA_COSTOS[idx_v % len(PALETA_COSTOS)] for idx_v, row_v in enumerate(tabla_c[titulo_col_c])}
                st.dataframe(
                    tabla_c.style.map(lambda v: f"color: {_cmap_c.get(v, '#F3F4F6' if _detectar_tema_oscuro() else '#111827')}; font-weight: 700;", subset=[titulo_col_c]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.dataframe(tabla_c, use_container_width=True, hide_index=True)
        else:
            st.info("No active costs to display.")

    with col_chart_i:
        st.markdown(
            "<h4 style='color: var(--fin-ink); text-align: center;'>Income Breakdown</h4>",
            unsafe_allow_html=True
        )
        if ingresos_activos and total_ingresos > 0:
            df_i_raw = pd.DataFrame(ingresos_activos)
            if modo_grafico.startswith("By Category"):
                df_pie_i = df_i_raw.groupby("grupo", as_index=False)["monto"].sum().sort_values(by="monto", ascending=False)
                col_label_i = "grupo"
                titulo_col_i = "Category"
                fig_i = crear_torta_2d(df_pie_i, "monto", col_label_i, tamano="chico", usar_minusculas=True, paleta=PALETA_INGRESOS)
            else:
                df_pie_i = df_i_raw.sort_values(by="monto", ascending=False).copy()
                df_pie_i["etiqueta"] = df_pie_i["concepto"]
                col_label_i = "etiqueta"
                titulo_col_i = "Subcategory"
                fig_i = crear_barras_horizontales(df_pie_i, "monto", col_label_i, color_barra="#16A34A")

            df_pie_i["Percentage"] = (df_pie_i["monto"] / total_ingresos) * 100

            st.plotly_chart(fig_i, use_container_width=True, config={"displayModeBar": False})

            tabla_i = df_pie_i[[col_label_i, "monto", "Percentage"]].copy()
            tabla_i.columns = [titulo_col_i, "Subtotal (AUD)", "% of Total"]
            tabla_i["Subtotal (AUD)"] = tabla_i["Subtotal (AUD)"].apply(lambda x: f"${x:,.0f} AUD")
            tabla_i["% of Total"] = tabla_i["% of Total"].apply(lambda x: f"{x:.1f}%")
            if modo_grafico.startswith("By Category"):
                _cmap_i = {row_v: PALETA_INGRESOS[idx_v % len(PALETA_INGRESOS)] for idx_v, row_v in enumerate(tabla_i[titulo_col_i])}
                st.dataframe(
                    tabla_i.style.map(lambda v: f"color: {_cmap_i.get(v, '#F3F4F6' if _detectar_tema_oscuro() else '#111827')}; font-weight: 700;", subset=[titulo_col_i]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.dataframe(tabla_i, use_container_width=True, hide_index=True)
        else:
            st.info("No active income to display.")


# =========================================================================
# ============================= TAB 2 =====================================
# =========================================================================
def _construir_patrimonio_vivo(datos):
    inversiones = datos.get("inversiones", [])
    t_acc, t_cri, t_bon = [], [], []
    for inv in inversiones:
        tp = normalizar_tipo_activo_inv(inv.get("tipo", "Cash AUD"))
        nom = str(inv.get("activo", tp)).strip()
        sim = str(inv.get("simbolo", "")).upper().strip().split(" ")[0]
        if tp in ["Cryptos", "Stocks", "Bonds"]:
            det_t = nom.split(" ")[0].upper()
            if det_t and det_t not in ["USD", "ARS", "AUD"]:
                sim = det_t
        if sim and sim not in ["USD", "ARS", "AUD"]:
            if tp == "Stocks":
                t_acc.append(sim)
            elif tp == "Cryptos":
                t_cri.append(sim)
            elif tp == "Bonds":
                t_bon.append(sim)
    cotiz_live = obtener_cotizaciones(tuple(t_acc), tuple(t_cri), tuple(t_bon))
    fx_live = float(cotiz_live.get("usd_to_aud", 1.53))
    q_meta = st.session_state.get("_quotes_meta", {})

    filas_l = []
    adv_l = []
    for inv in inversiones:
        cant = float(inv.get("cantidad", 0))
        tipo = normalizar_tipo_activo_inv(inv.get("tipo", "Cash AUD"))
        activo_nom = str(inv.get("activo", tipo)).strip()
        if activo_nom in ["Pesos ARS", "Dólar Billete", "A - Dólar Billete"]:
            activo_nom = "Cash AUD" if tipo == "Cash AUD" else "Cash USD"

        simbolo = str(inv.get("simbolo", "")).upper().strip().split(" ")[0]
        if tipo in ["Cryptos", "Stocks", "Bonds"]:
            det_t = activo_nom.split(" ")[0].upper()
            if det_t and det_t not in ["USD", "ARS", "AUD"]:
                simbolo = det_t

        esta_activo = inv.get("activo_inv", True)
        precio_valido = True

        if tipo == "Cash AUD":
            precio_unit_aud = 1.0
            val_aud = cant
            cotiz_actual_str = "1 AUD = 1.00 AUD"
        elif tipo == "Cash USD":
            precio_unit_aud = fx_live
            val_aud = cant * fx_live
            cotiz_actual_str = f"1 USD = {fx_live:,.2f} AUD"
        elif tipo in ["Cryptos", "Stocks"]:
            precio_u_usd = cotiz_live.get(simbolo)
            if precio_u_usd is None or float(precio_u_usd) <= 0:
                precio_valido = False
                precio_unit_aud = 0.0
                val_aud = 0.0
                cotiz_actual_str = f"⚠️ No quote for {simbolo}"
                if esta_activo:
                    adv_l.append(f"{activo_nom} ({tipo})")
            else:
                precio_unit_aud = float(precio_u_usd) * fx_live
                val_aud = cant * precio_unit_aud
                cotiz_actual_str = f"1 {simbolo} = ${precio_unit_aud:,.2f} AUD"
        else:
            if simbolo and simbolo not in ["AUD", "USD", "ARS"] and simbolo in cotiz_live and float(cotiz_live[simbolo]) > 0:
                precio_unit_aud = float(cotiz_live[simbolo]) * fx_live
                cotiz_actual_str = f"1 {simbolo} = ${precio_unit_aud:,.2f} AUD"
            else:
                precio_unit_aud = float(inv.get("precio_unitario_aud", 1.0))
                if precio_unit_aud <= 0:
                    precio_valido = False
                    precio_unit_aud = 0.0
                    cotiz_actual_str = "⚠️ Invalid price"
                    if esta_activo:
                        adv_l.append(f"{activo_nom} ({tipo})")
                else:
                    cotiz_actual_str = f"1 unit = ${precio_unit_aud:,.2f} AUD"
            val_aud = cant * precio_unit_aud if precio_valido else 0.0

        filas_l.append({
            "Type": tipo,
            "Asset": activo_nom,
            "Symbol": simbolo,
            "Platform": inv.get("plataforma", ""),
            "Quantity_Num": cant,
            "Quantity": formatear_cant(cant),
            "Price_Unit_AUD": precio_unit_aud,
            "Price_Valid": precio_valido,
            "Live Quote": cotiz_actual_str,
            "Value (AUD)": val_aud,
            "Active_Flag": esta_activo
        })

    bn_k, bn_s, bn_ru, bn_rs = _obtener_binance_keys()
    bn_err_msg = None
    if bn_k and bn_s and bool(st.session_state.get("tab2_sync_binance_live", True)):
        bn_rows, bn_err_msg = obtener_binance_portfolio(bn_k, bn_s, fx_live, relay_url=bn_ru, relay_secret=bn_rs)
        if not bn_err_msg:
            for b in bn_rows:
                val_b = float(b.get("val_aud", 0.0) or 0.0)
                if val_b < 2.0:
                    continue
                filas_l.append({
                    "Type": "Cryptos",
                    "Asset": f"{b['asset']} (Binance)",
                    "Symbol": b["asset"],
                    "Platform": b["wallet"],
                    "Quantity_Num": float(b["qty"] or 0.0),
                    "Quantity": formatear_cant(float(b["qty"] or 0.0)),
                    "Price_Unit_AUD": float(b["price_aud"] or 0.0),
                    "Price_Valid": float(b["price_aud"] or 0.0) > 0,
                    "Live Quote": b["quote_str"],
                    "Value (AUD)": val_b,
                    "Active_Flag": True,
                })

    df_all = pd.DataFrame(filas_l)
    if not df_all.empty:
        df_all["Value (AUD)"] = pd.to_numeric(df_all["Value (AUD)"], errors="coerce").fillna(0.0)
        df_act = df_all[
            (df_all["Active_Flag"] == True)
            & ~((df_all["Type"] == "Cryptos") & (df_all["Value (AUD)"] < 2.0))
        ].copy()
    else:
        df_act = pd.DataFrame()
    tot_aud = float(df_act["Value (AUD)"].sum()) if not df_act.empty else 0.0
    return filas_l, df_all, df_act, tot_aud, adv_l, bn_err_msg, q_meta, cotiz_live, fx_live


with pestana2:
    inversiones = datos.get("inversiones", [])
    if reparar_inversiones_corruptas(inversiones):
        guardar_datos(datos, registrar_cambio=False)

    if "tab2_sync_binance_live" not in st.session_state:
        st.session_state["tab2_sync_binance_live"] = True
    bn_key, bn_sec, bn_r_url, bn_r_sec = _obtener_binance_keys()

    filas, df_inv_todos, df_inv_activos, total_patrimonio_aud, advertencias_precios, _bn_err_init, _q_meta_init, _cotiz_init, _fx_init = _construir_patrimonio_vivo(datos)
    if _bn_err_init:
        st.warning(f"⚠️ {_bn_err_init}")
    if advertencias_precios:
        st.warning(
            "⚠️ No valid quote found for: "
            + ", ".join(advertencias_precios)
            + ". Excluded from total to avoid distorting Net Worth."
        )



    col_inv_izq, col_inv_der = st.columns([1.05, 1.85], gap="medium")

    # ---------------- ADD ASSET ----------------
    with col_inv_izq:
        st.markdown(
            "<h3 style='color: var(--fin-ink);'>➕ Add Asset</h3>",
            unsafe_allow_html=True
        )
        opciones_tipo = [
            "A - Cash AUD",
            "B - Cash USD",
            "C - Stocks",
            "D - Cryptos",
            "E - Bonds",
            "F - FCI",
            "G - Others"
        ]

        opciones_ubicacion = [str(u).strip() for u in datos.get("ubicaciones_guardadas", []) if str(u).strip()]
        for ub_def in UBICACIONES_BASE:
            if not any(ub_def.lower() == u.lower() for u in opciones_ubicacion):
                opciones_ubicacion.append(ub_def)
        if not opciones_ubicacion:
            opciones_ubicacion = list(UBICACIONES_BASE)
        datos["ubicaciones_guardadas"] = opciones_ubicacion

        ult_sel = datos.setdefault("ultimas_selecciones_inv", {
            "tipo": "A - Cash AUD",
            "accion": "AAPL (Apple)",
            "cripto": "BTC (Bitcoin)",
            "bono": "AL30 (Bonar 2030 Ley Arg.)",
            "ubicacion": opciones_ubicacion[0]
        })

        if "_pending_inv_widget_sync" in st.session_state:
            for k_sync, v_sync in st.session_state.pop("_pending_inv_widget_sync").items():
                st.session_state[k_sync] = v_sync

        tipo_guardado = ult_sel.get("tipo", "A - Cash AUD")
        if tipo_guardado not in opciones_tipo:
            tipo_guardado = "A - Cash AUD"

        if "inv_tipo_select" not in st.session_state or st.session_state["inv_tipo_select"] not in opciones_tipo:
            st.session_state["inv_tipo_select"] = tipo_guardado

        def on_cambio_tipo_inv():
            datos.setdefault("ultimas_selecciones_inv", {})["tipo"] = st.session_state["inv_tipo_select"]
            guardar_datos(datos, registrar_cambio=False)

        tipo_elegido = st.selectbox(
            "1. Asset Type",
            opciones_tipo,
            key="inv_tipo_select",
            on_change=on_cambio_tipo_inv
        )

        contenedor_selector_especifico = st.container()
        simbolo_elegido = "AUD"
        detalle_manual = ""

        with contenedor_selector_especifico:
            if tipo_elegido == "C - Stocks":
                lista_acc_actual = datos.get("acciones_guardadas", list(ACCIONES_100_BASE))
                acc_recordada = ult_sel.get("accion", lista_acc_actual[0])
                if acc_recordada not in lista_acc_actual:
                    coinc_acc = [a for a in lista_acc_actual if a.split(" ")[0].upper() == str(acc_recordada).split(" ")[0].upper()]
                    acc_recordada = coinc_acc[0] if coinc_acc else lista_acc_actual[0]

                if "inv_accion_select" not in st.session_state or st.session_state["inv_accion_select"] not in lista_acc_actual:
                    st.session_state["inv_accion_select"] = acc_recordada

                def on_cambio_accion_inv():
                    datos.setdefault("ultimas_selecciones_inv", {})["accion"] = st.session_state["inv_accion_select"]
                    guardar_datos(datos, registrar_cambio=False)

                simbolo_elegido = st.selectbox(
                    "Select Stock from list",
                    lista_acc_actual,
                    key="inv_accion_select",
                    on_change=on_cambio_accion_inv
                )
                detalle_manual = st.text_input(
                    "Not in the list? Type ticker manually to save it (e.g. VAS.AX, DIS):",
                    key="inv_detalle_manual_acc"
                )
            elif tipo_elegido == "D - Cryptos":
                lista_cri_actual = datos.get("criptos_guardadas", list(CRIPTOS_100_BASE))
                cri_recordada = ult_sel.get("cripto", lista_cri_actual[0])
                if cri_recordada not in lista_cri_actual:
                    coinc_cri = [c for c in lista_cri_actual if c.split(" ")[0].upper() == str(cri_recordada).split(" ")[0].upper()]
                    cri_recordada = coinc_cri[0] if coinc_cri else lista_cri_actual[0]

                if "inv_cripto_select" not in st.session_state or st.session_state["inv_cripto_select"] not in lista_cri_actual:
                    st.session_state["inv_cripto_select"] = cri_recordada

                def on_cambio_cripto_inv():
                    datos.setdefault("ultimas_selecciones_inv", {})["cripto"] = st.session_state["inv_cripto_select"]
                    guardar_datos(datos, registrar_cambio=False)

                simbolo_elegido = st.selectbox(
                    "Select Crypto from list",
                    lista_cri_actual,
                    key="inv_cripto_select",
                    on_change=on_cambio_cripto_inv
                )
                detalle_manual = st.text_input(
                    "Not in the list? Type ticker manually to save it (e.g. DFT, ADA):",
                    key="inv_detalle_manual_cri"
                )
            elif tipo_elegido == "E - Bonds":
                lista_bon_actual = datos.setdefault("bonos_guardadas", list(BONOS_BASE))
                bon_recordado = ult_sel.get("bono", lista_bon_actual[0])
                if bon_recordado not in lista_bon_actual:
                    coinc_bon = [b for b in lista_bon_actual if b.split(" ")[0].upper() == str(bon_recordado).split(" ")[0].upper()]
                    bon_recordado = coinc_bon[0] if coinc_bon else lista_bon_actual[0]

                if "inv_bono_select" not in st.session_state or st.session_state["inv_bono_select"] not in lista_bon_actual:
                    st.session_state["inv_bono_select"] = bon_recordado

                def on_cambio_bono_inv():
                    datos.setdefault("ultimas_selecciones_inv", {})["bono"] = st.session_state["inv_bono_select"]
                    guardar_datos(datos, registrar_cambio=False)

                simbolo_elegido = st.selectbox(
                    "Select Bond from list",
                    lista_bon_actual,
                    key="inv_bono_select",
                    on_change=on_cambio_bono_inv
                )
                detalle_manual = st.text_input(
                    "Not in the list? Type ticker manually to save it (e.g. AL30, GD35):",
                    key="inv_detalle_manual_bon"
                )
            elif tipo_elegido == "F - FCI":
                detalle_manual = st.text_input(
                    "Fund name or ticker:",
                    key="inv_detalle_manual_fci"
                )
            elif tipo_elegido == "G - Others":
                detalle_manual = st.text_input(
                    "Describe what it is (e.g. Term Deposit, Saver):",
                    key="inv_detalle_manual_otros"
                )

        ubic_recordada = str(ult_sel.get("ubicacion", opciones_ubicacion[0])).strip()
        coinc_u = [u for u in opciones_ubicacion if u.lower() == ubic_recordada.lower()]
        ubic_default_valida = coinc_u[0] if coinc_u else opciones_ubicacion[0]

        if "inv_ubicacion_select" not in st.session_state or st.session_state["inv_ubicacion_select"] not in opciones_ubicacion:
            st.session_state["inv_ubicacion_select"] = ubic_default_valida

        def on_cambio_ubicacion_select():
            val_sel = st.session_state.get("inv_ubicacion_select", opciones_ubicacion[0])
            if val_sel:
                datos.setdefault("ultimas_selecciones_inv", {})["ubicacion"] = val_sel
                guardar_datos(datos, registrar_cambio=False)

        plat_select = st.selectbox(
            "2. Location / Platform",
            options=opciones_ubicacion,
            key="inv_ubicacion_select",
            on_change=on_cambio_ubicacion_select
        )

        def on_enter_nueva_ubicacion():
            nueva_u = st.session_state.get("inv_ubicacion_nueva_manual", "").strip()
            if nueva_u:
                registrar_ubicacion_guardada(datos, nueva_u)
                guardar_datos(datos, registrar_cambio=False)
                st.session_state["inv_ubicacion_select"] = nueva_u
                st.session_state["inv_ubicacion_nueva_manual"] = ""

        nueva_ubic_manual = st.text_input(
            "Another location? Type it here to save it:",
            placeholder="e.g. Up Bank, CommSec, Stake...",
            key="inv_ubicacion_nueva_manual",
            on_change=on_enter_nueva_ubicacion
        )

        if tipo_elegido == "A - Cash AUD":
            tooltip_cant_actual = "Enter the amount in Australian Dollars (AUD). e.g. 2500"
        elif tipo_elegido == "B - Cash USD":
            tooltip_cant_actual = "Enter the amount in US Dollars. e.g. 1500"
        else:
            tooltip_cant_actual = (
                "Enter the number of units, not the cash value. "
                "e.g. 2 or 5 (stocks/bonds), 0.0005 (BTC). Value in AUD is calculated automatically."
            )

        with st.form("form_guardar_activo_inv", clear_on_submit=True):
            cant_texto = st.text_input(
                "3. Quantity Held",
                placeholder="e.g. 2500 or 0.0005",
                help=tooltip_cant_actual
            )
            btn_guardar_inv = st.form_submit_button(
                "Save Asset",
                use_container_width=True
            )

            if btn_guardar_inv:
                try:
                    cant_num = parsear_numero_flexible(cant_texto) if cant_texto.strip() else 0.0
                except ValueError:
                    cant_num = -1.0

                if cant_num > 0:
                    tipo_momento_guardar = st.session_state.get("inv_tipo_select", tipo_elegido)

                    if tipo_momento_guardar == "A - Cash AUD":
                        tipo_guardar = "Cash AUD"
                        nombre_act = "Cash AUD"
                        simbolo_final = "AUD"
                    elif tipo_momento_guardar == "B - Cash USD":
                        tipo_guardar = "Cash USD"
                        nombre_act = "Cash USD"
                        simbolo_final = "USD"
                    elif tipo_momento_guardar == "C - Stocks":
                        tipo_guardar = "Stocks"
                        if detalle_manual.strip():
                            nuevo_acc = detalle_manual.strip().upper()
                            if nuevo_acc not in datos["acciones_guardadas"]:
                                datos["acciones_guardadas"].append(nuevo_acc)
                            nombre_act = nuevo_acc
                            simbolo_final = nuevo_acc.split(" ")[0]
                            st.session_state["_pending_inv_widget_sync"] = {
                                "inv_accion_select": nuevo_acc,
                                "inv_detalle_manual_acc": ""
                            }
                        else:
                            nombre_act = simbolo_elegido
                            simbolo_final = simbolo_elegido.split(" ")[0].upper()
                        datos.setdefault("ultimas_selecciones_inv", {})["accion"] = nombre_act
                    elif tipo_momento_guardar == "D - Cryptos":
                        tipo_guardar = "Cryptos"
                        if detalle_manual.strip():
                            nueva_cri_raw = detalle_manual.strip().upper()
                            nueva_cri_sim = nueva_cri_raw.split(" ")[0]
                            coinc_c = [c for c in datos["criptos_guardadas"] if c.split(" ")[0].upper() == nueva_cri_sim]
                            if coinc_c:
                                item_lista_cri = coinc_c[0]
                            else:
                                item_lista_cri = nueva_cri_raw
                                datos["criptos_guardadas"].append(item_lista_cri)
                            nombre_act = nueva_cri_sim
                            simbolo_final = nueva_cri_sim
                            st.session_state["_pending_inv_widget_sync"] = {
                                "inv_cripto_select": item_lista_cri,
                                "inv_detalle_manual_cri": ""
                            }
                        else:
                            item_lista_cri = simbolo_elegido
                            simbolo_final = simbolo_elegido.split(" ")[0].upper().strip()
                            nombre_act = simbolo_final
                        datos.setdefault("ultimas_selecciones_inv", {})["cripto"] = item_lista_cri
                    elif tipo_momento_guardar == "E - Bonds":
                        tipo_guardar = "Bonds"
                        lista_b = datos.setdefault("bonos_guardadas", list(BONOS_BASE))
                        if detalle_manual.strip():
                            nuevo_bon = detalle_manual.strip().upper()
                            nuevo_bon_sim = nuevo_bon.split(" ")[0]
                            coinc_b = [b for b in lista_b if b.split(" ")[0].upper() == nuevo_bon_sim]
                            if coinc_b:
                                item_lista_bon = coinc_b[0]
                            else:
                                item_lista_bon = nuevo_bon
                                lista_b.append(item_lista_bon)
                            nombre_act = item_lista_bon
                            simbolo_final = nuevo_bon_sim
                            st.session_state["_pending_inv_widget_sync"] = {
                                "inv_bono_select": item_lista_bon,
                                "inv_detalle_manual_bon": ""
                            }
                        else:
                            item_lista_bon = simbolo_elegido
                            nombre_act = simbolo_elegido
                            simbolo_final = simbolo_elegido.split(" ")[0].upper().strip()
                        datos.setdefault("ultimas_selecciones_inv", {})["bono"] = item_lista_bon
                    elif tipo_momento_guardar == "F - FCI":
                        tipo_guardar = "FCI"
                        nombre_act = detalle_manual.strip() if detalle_manual.strip() else "FCI"
                        simbolo_final = nombre_act.split(" ")[0].upper()
                        if detalle_manual.strip():
                            st.session_state["_pending_inv_widget_sync"] = {
                                "inv_detalle_manual_fci": ""
                            }
                    else:
                        tipo_guardar = "Others"
                        nombre_act = detalle_manual.strip() if detalle_manual.strip() else "Others"
                        simbolo_final = nombre_act.split(" ")[0].upper() if detalle_manual.strip() else "AUD"
                        if detalle_manual.strip():
                            st.session_state["_pending_inv_widget_sync"] = {
                                "inv_detalle_manual_otros": ""
                            }

                    ubicacion_elegida_final = nueva_ubic_manual.strip() if nueva_ubic_manual.strip() else plat_select.strip()
                    if not ubicacion_elegida_final:
                        ubicacion_elegida_final = opciones_ubicacion[0]

                    registrar_ubicacion_guardada(datos, ubicacion_elegida_final)
                    sync_dict = st.session_state.get("_pending_inv_widget_sync", {})
                    sync_dict["inv_ubicacion_select"] = ubicacion_elegida_final
                    sync_dict["inv_ubicacion_nueva_manual"] = ""
                    st.session_state["_pending_inv_widget_sync"] = sync_dict

                    datos.setdefault("ultimas_selecciones_inv", {})["tipo"] = tipo_momento_guardar

                    datos["inversiones"].append({
                        "tipo": tipo_guardar,
                        "activo": nombre_act,
                        "simbolo": simbolo_final,
                        "cantidad": int(cant_num) if cant_num.is_integer() else cant_num,
                        "plataforma": ubicacion_elegida_final,
                        "activo_inv": True
                    })
                    guardar_datos(datos)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.warning("Please enter a valid quantity greater than 0.")

    # ---------------- MY ASSETS ----------------
    with col_inv_der:
        _frag_dec = st.fragment(run_every=60) if hasattr(st, "fragment") else (lambda fn: fn)

        @_frag_dec
        def _render_assets_y_breakdown():
            _f_rows, _df_t, _df_a, _tot_aud, _adv_p, _bn_e, _qm, cotizaciones, usd_to_aud = _construir_patrimonio_vivo(datos)
            _upd_lbl = _qm.get("updated_at", datetime.now(TZ_SYDNEY).strftime("%H:%M:%S"))
            _c_hdr_l, _c_hdr_r = st.columns([3.0, 1.6])
            with _c_hdr_l:
                st.markdown(
                    "<h3 style='color: var(--fin-ink); margin-bottom: 2px;'>📋 My Assets by Category</h3>",
                    unsafe_allow_html=True
                )
            with _c_hdr_r:
                st.markdown(
                    f"<div style='text-align:right; font-size:0.80rem; color:var(--fin-muted); padding-top:12px;'>"
                    f"🕒 Last updated: <b>{_upd_lbl}</b></div>",
                    unsafe_allow_html=True,
                )
            _failed_list = [s for s in (_qm.get("failed_syms") or [])]
            if not _qm.get("fx_ok", True):
                _failed_list.append("USD/AUD")
            if _failed_list:
                st.warning(
                    "⚠️ Live quote refresh failed for: "
                    + ", ".join(_failed_list)
                    + ". Keeping last valid price."
                )
            orden_categorias_inv = [
                "Cash AUD",
                "Cash USD",
                "Stocks",
                "Cryptos",
                "Bonds",
                "FCI",
                "Others"
            ]

            if inversiones:
                inv_cambios = False
                for cat_inv in orden_categorias_inv:
                    items_cat_inv = [
                        (idx, inv) for idx, inv in enumerate(inversiones)
                        if normalizar_tipo_activo_inv(inv.get("tipo", "Others")) == cat_inv
                    ]
                    if not items_cat_inv:
                        continue

                    sub_inv_aud = sum(
                        filas[idx]["Value (AUD)"]
                        for idx, inv in items_cat_inv
                        if inv.get("activo_inv", True)
                    )

                    titulo_exp_inv = (
                        f"📂 **{cat_inv}** — subt= "
                        f"**${sub_inv_aud:,.2f} AUD**"
                    )
                    with st.expander(titulo_exp_inv, expanded=True):
                        hc1, hc2, hc3, hc4, hc5 = st.columns([0.45, 1.15, 1.85, 1.10, 0.45])
                        hc1.markdown("<div class='col-header'>ACT.</div>", unsafe_allow_html=True)
                        hc2.markdown("<div class='col-header'>DETAIL</div>", unsafe_allow_html=True)
                        hc3.markdown("<div class='col-header'>QUANTITY</div>", unsafe_allow_html=True)
                        hc4.markdown("<div class='col-header'>LOCATION</div>", unsafe_allow_html=True)
                        hc5.markdown("<div class='col-header'>DEL</div>", unsafe_allow_html=True)

                        for idx, inv in items_cat_inv:
                            st_act = inv.get("activo_inv", True)
                            c_chk, c_nom, c_cant, c_plat, c_del = st.columns([0.45, 1.15, 1.85, 1.10, 0.45])

                            with c_chk:
                                nuevo_chk = st.checkbox(
                                    "Active",
                                    value=st_act,
                                    key=f"inv_chk_{idx}",
                                    label_visibility="collapsed"
                                )
                                if nuevo_chk != st_act:
                                    inv["activo_inv"] = nuevo_chk
                                    inv_cambios = True

                            with c_nom:
                                st.text_input(
                                    "Detail",
                                    value=filas[idx]["Asset"],
                                    key=f"inv_nom_{idx}",
                                    label_visibility="collapsed",
                                    disabled=True
                                )

                            with c_cant:
                                cant_num_actual = float(inv.get("cantidad", 0))
                                cant_str_actual = formatear_cant(cant_num_actual)
                                nueva_cant_str = st.text_input(
                                    "Quantity",
                                    value=cant_str_actual,
                                    key=f"inv_cant_{idx}",
                                    label_visibility="collapsed",
                                    disabled=not st_act
                                )
                                try:
                                    nueva_cant_val = parsear_numero_flexible(nueva_cant_str)
                                    if nueva_cant_val > 0 and abs(nueva_cant_val - cant_num_actual) > 1e-9:
                                        inv["cantidad"] = int(nueva_cant_val) if nueva_cant_val.is_integer() else nueva_cant_val
                                        cant_num_actual = nueva_cant_val
                                        cant_str_actual = formatear_cant(cant_num_actual)
                                        inv_cambios = True
                                except ValueError:
                                    pass

                                if cat_inv != "Cash AUD":
                                    if not filas[idx].get("Price_Valid", True):
                                        st.markdown(
                                            "<div style='font-size: 0.75rem; font-weight: 700; color: #991B1B; "
                                            "background: #FEF2F2; border: 1px solid #FECACA; border-radius: 7px; "
                                            "padding: 4px 7px; margin-top: -8px; margin-bottom: 6px; "
                                            "white-space: normal; word-break: break-word; line-height: 1.25;'>"
                                            "⚠️ Price invalid or unavailable"
                                            "</div>",
                                            unsafe_allow_html=True
                                        )
                                    else:
                                        precio_u_aud_fila = float(filas[idx]["Price_Unit_AUD"])
                                        total_aud_fila = cant_num_actual * precio_u_aud_fila
                                        precio_u_fmt = f"{precio_u_aud_fila:,.2f}"
                                        st.markdown(
                                            f"<div style='font-size: 0.75rem; font-weight: 700; color: #4A235A; "
                                            f"background: #F5F3FF; border: 1px solid #DDD6FE; border-radius: 7px; "
                                            f"padding: 4px 7px; margin-top: -8px; margin-bottom: 6px; "
                                            f"white-space: normal; word-break: break-word; overflow-wrap: anywhere; "
                                            f"line-height: 1.25;'>"
                                            f"{cant_str_actual} × ${precio_u_fmt} = ${total_aud_fila:,.2f} AUD"
                                            f"</div>",
                                            unsafe_allow_html=True
                                        )

                            with c_plat:
                                st.text_input(
                                    "Location",
                                    value=inv.get("plataforma", ""),
                                    key=f"inv_p_{idx}",
                                    label_visibility="collapsed",
                                    disabled=True
                                )

                            with c_del:
                                if st.button("🗑️", key=f"inv_del_{idx}", help="Delete this asset"):
                                    datos["inversiones"].pop(idx)
                                    guardar_datos(datos)
                                    st.rerun()

                if inv_cambios:
                    guardar_datos(datos)
                    st.rerun()
            else:
                st.info("No assets added yet.")

        _render_assets_y_breakdown()

    st.markdown("---")

    @_frag_dec
    def _render_networth_breakdown():
        _f_rows2, _df_t2, df_inv_activos, total_patrimonio_aud, _adv2, _bn_e2, _qm2, _c2, _fx2 = _construir_patrimonio_vivo(datos)
        st.markdown(
            f"<div style='display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:8px;'>"
            f"<h3 style='color: var(--fin-ink); margin:0;'>💼 Net Worth Breakdown</h3>"
            f"<span style='font-size:0.85rem; color:var(--fin-muted); font-weight:600;'>"
            f"Total Net Worth: <b style='color:var(--fin-ink);'>${total_patrimonio_aud:,.2f} AUD</b> · Last updated: {_qm2.get('updated_at', '')}</span>"
            f"</div>",
            unsafe_allow_html=True
        )
        if not df_inv_activos.empty and total_patrimonio_aud > 0:
            col_g_inv1, col_g_inv2 = st.columns(2, gap="medium")

            with col_g_inv1:
                st.markdown(
                    "<h4 style='color: var(--fin-ink); text-align: center;'>By Asset Type</h4>",
                    unsafe_allow_html=True
                )
                resumen_tipo = df_inv_activos.groupby("Type", as_index=False).agg({
                    "Value (AUD)": "sum"
                }).sort_values(by="Value (AUD)", ascending=False)
                resumen_tipo["%"] = (resumen_tipo["Value (AUD)"] / total_patrimonio_aud) * 100

                fig_inv_tipo = crear_torta_2d(resumen_tipo, "Value (AUD)", "Type")
                st.plotly_chart(fig_inv_tipo, use_container_width=True, config={"displayModeBar": False})

                tabla_t = resumen_tipo.copy()
                tabla_t.columns = ["Category", "Subtotal (AUD)", "%"]
                tabla_t["Subtotal (AUD)"] = tabla_t["Subtotal (AUD)"].apply(lambda x: f"${x:,.2f} AUD")
                tabla_t["%"] = tabla_t["%"].apply(lambda x: f"{x:.1f}%")
                st.dataframe(tabla_t, use_container_width=True, hide_index=True)

            with col_g_inv2:
                st.markdown(
                    "<h4 style='color: var(--fin-ink); text-align: center;'>By Location</h4>",
                    unsafe_allow_html=True
                )
                df_det = df_inv_activos.sort_values(by="Value (AUD)", ascending=False).copy()
                df_det["%"] = (df_det["Value (AUD)"] / total_patrimonio_aud) * 100

                df_ubic_grp = df_inv_activos.copy()
                df_ubic_grp["Ubicacion_Limpia"] = df_ubic_grp["Platform"].astype(str).str.strip()
                df_ubic_grp.loc[df_ubic_grp["Ubicacion_Limpia"] == "", "Ubicacion_Limpia"] = "Unspecified"

                mapa_ubic_display = {}
                for u_raw in df_ubic_grp["Ubicacion_Limpia"]:
                    u_key = u_raw.lower()
                    if u_key not in mapa_ubic_display or (u_raw != u_raw.upper() and mapa_ubic_display[u_key] == mapa_ubic_display[u_key].upper()):
                        mapa_ubic_display[u_key] = u_raw
                df_ubic_grp["Ubicacion_Final"] = df_ubic_grp["Ubicacion_Limpia"].apply(lambda x: mapa_ubic_display.get(x.lower(), x))

                resumen_ubic = df_ubic_grp.groupby("Ubicacion_Final", as_index=False).agg({
                    "Value (AUD)": "sum"
                }).sort_values(by="Value (AUD)", ascending=False)
                resumen_ubic["%"] = (resumen_ubic["Value (AUD)"] / total_patrimonio_aud) * 100

                menores_2pct = resumen_ubic[resumen_ubic["%"] < 2.0]
                if len(menores_2pct) > 1:
                    mayores_2pct = resumen_ubic[resumen_ubic["%"] >= 2.0].copy()
                    fila_otras = pd.DataFrame([{
                        "Ubicacion_Final": "Other",
                        "Value (AUD)": menores_2pct["Value (AUD)"].sum(),
                        "%": menores_2pct["%"].sum()
                    }])
                    df_pie_ubic = pd.concat([mayores_2pct, fila_otras], ignore_index=True)
                else:
                    df_pie_ubic = resumen_ubic.copy()

                fig_inv_det = crear_torta_2d(df_pie_ubic, "Value (AUD)", "Ubicacion_Final")
                st.plotly_chart(fig_inv_det, use_container_width=True, config={"displayModeBar": False})

                activos_unicos = list(dict.fromkeys(df_det["Asset"].dropna().astype(str).tolist()))
                ubicaciones_unicas = list(dict.fromkeys(df_det["Platform"].dropna().astype(str).tolist()))
                opciones_filtro = ["All (show all)"]
                for a_item in activos_unicos:
                    if a_item and a_item not in opciones_filtro:
                        opciones_filtro.append(a_item)
                for u_item in ubicaciones_unicas:
                    if u_item and u_item not in opciones_filtro:
                        opciones_filtro.append(u_item)

                filtro_sel = st.selectbox(
                    "🔎 Filter by Asset or Location (e.g. BTC, Up Bank, Binance):",
                    options=opciones_filtro,
                    key="filtro_tabla_final_inv"
                )

                if filtro_sel != "All (show all)":
                    f_low = filtro_sel.strip().lower()
                    mask_f = (
                        (df_det["Asset"].astype(str).str.lower() == f_low)
                        | (df_det["Symbol"].astype(str).str.lower() == f_low)
                        | (df_det["Platform"].astype(str).str.lower() == f_low)
                        | (df_det["Type"].astype(str).str.lower() == f_low)
                    )
                    df_det_mostrar = df_det[mask_f].copy()
                else:
                    df_det_mostrar = df_det.copy()

                cols_d = [
                    "Type", "Asset", "Platform", "Quantity",
                    "Live Quote", "Value (AUD)", "%"
                ]
                tabla_d = df_det_mostrar[cols_d].copy()
                tabla_d.columns = [
                    "Category", "Asset", "Location", "Quantity",
                    "Live Quote Used", "Value (AUD)", "%"
                ]
                tabla_d["Value (AUD)"] = tabla_d["Value (AUD)"].apply(lambda x: f"${x:,.2f} AUD")
                tabla_d["%"] = tabla_d["%"].apply(lambda x: f"{x:.1f}%")

                if filtro_sel != "All (show all)" and not df_det_mostrar.empty:
                    sub_f_aud = df_det_mostrar["Value (AUD)"].sum()
                    sub_f_pct = (sub_f_aud / total_patrimonio_aud) * 100 if total_patrimonio_aud > 0 else 0.0
                    cant_f_total = df_det_mostrar["Quantity_Num"].sum()
                    es_mismo_activo = df_det_mostrar["Asset"].nunique() == 1
                    cant_f_str = formatear_cant(cant_f_total) if es_mismo_activo else f"{len(df_det_mostrar)} items"

                    fila_subtotal = pd.DataFrame([{
                        "Category": "SUBTOTAL",
                        "Asset": filtro_sel,
                        "Location": "Filtered total",
                        "Quantity": cant_f_str,
                        "Live Quote Used": "—",
                        "Value (AUD)": f"${sub_f_aud:,.2f} AUD",
                        "%": f"{sub_f_pct:.1f}%"
                    }])
                    tabla_d = pd.concat([tabla_d, fila_subtotal], ignore_index=True)

                    st.markdown(f"""
                    <div style="background-color: #F3E8FF; border: 1.5px solid #C084FC; border-left: 6px solid #7E22CE;
                                border-radius: 12px; padding: 10px 14px; margin-bottom: 10px; color: #4A235A; font-size: 0.98rem;">
                        <b>Subtotal ({filtro_sel}):</b> <b>${sub_f_aud:,.2f} AUD</b> &nbsp;|&nbsp;
                        <b>{sub_f_pct:.1f}%</b> of total net worth
                    </div>
                    """, unsafe_allow_html=True)

                st.dataframe(tabla_d, use_container_width=True, hide_index=True)

    _render_networth_breakdown()

    if bn_key and bn_sec:
        st.checkbox(
            "🟡 Sync Live Binance (Spot + Simple Earn)",
            key="tab2_sync_binance_live",
        )


# =========================================================================
# ============================= TAB 3 =====================================
# =========================================================================
with pestana3:

    if "up_refresh_nonce" not in st.session_state:
        st.session_state["up_refresh_nonce"] = 0
    if "up_temp_token" not in st.session_state:
        st.session_state["up_temp_token"] = ""

    up_token_secreto = _obtener_up_token()
    up_token_activo = up_token_secreto or st.session_state["up_temp_token"]

    if not up_token_activo:
        st.info(
            "Connect your **Up Bank** account to stream live AUD balances, tap-and-pay expenses, "
            "and income deposits (**ME Group**, **CG Recruitment**, **Pinnacle People**, **Parkhount**, and flatmates)."
        )
        with st.expander("🔑 How to connect your Up Bank Personal Access Token", expanded=True):
            st.markdown(
                "1. Open the **Up** app on your phone, swipe right, and select **Data sharing**.\n"
                "2. Tap **Personal Access Token** → **Generate a token** (or visit `https://api.up.com.au/getting_started`).\n"
                "3. Copy the token (`up:yeah:...`) and add it to **Streamlit Cloud → App Settings → Secrets** as:\n"
                "```toml\nup_bank_token = \"up:yeah:your_token_here\"\n```"
            )
            temp_tok = st.text_input(
                "Or paste your token here to test right now (session only, not saved to GitHub):",
                type="password",
                key="up_token_temp_input",
            )
            if st.button("🔌 Connect Up Bank", type="primary"):
                if temp_tok.strip():
                    st.session_state["up_temp_token"] = temp_tok.strip()
                    st.rerun()
                else:
                    st.warning("Paste your `up:yeah:...` token first.")
    else:
        if "up_hide_internal" not in st.session_state:
            st.session_state["up_hide_internal"] = True

        hoy_syd = datetime.now(TZ_SYDNEY).date()
        if "up_range_mode" not in st.session_state:
            st.session_state["up_range_mode"] = "All"
        if "up_date_from" not in st.session_state:
            st.session_state["up_date_from"] = hoy_syd - timedelta(days=90)
        if "up_date_to" not in st.session_state:
            st.session_state["up_date_to"] = hoy_syd

        ocultar_internas_up = st.checkbox(
            "Exclude internal Up transfers",
            help="Excludes transfers between your own Up Bank accounts so every external dollar in or out is counted accurately.",
            key="up_hide_internal",
        )

        # Quick period buttons (shared by search averages & Top recurring costs)
        _quick_opts = [
            ("Last 7 days", 7),
            ("30 days", 30),
            ("90 days", 90),
            ("6 months", 183),
            ("This year", None),
            ("All", None),
        ]
        _q_cols = st.columns(len(_quick_opts))
        for _qi, (_qlbl, _qdays) in enumerate(_quick_opts):
            with _q_cols[_qi]:
                _is_act = st.session_state["up_range_mode"] == _qlbl
                if st.button(
                    _qlbl,
                    key=f"up_qbtn_{_qi}",
                    type="primary" if _is_act else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["up_range_mode"] = _qlbl
                    st.session_state["up_date_to"] = hoy_syd
                    if _qlbl == "This year":
                        st.session_state["up_date_from"] = hoy_syd.replace(month=1, day=1)
                    elif _qlbl == "All":
                        st.session_state["up_date_from"] = hoy_syd - timedelta(days=365)
                    elif _qdays is not None:
                        st.session_state["up_date_from"] = hoy_syd - timedelta(days=_qdays - 1)
                    st.rerun()

        c_df1, c_df2 = st.columns(2)
        with c_df1:
            _sel_from = st.date_input(
                "From",
                value=st.session_state["up_date_from"],
                format="DD/MM/YYYY",
                key="up_inp_from",
            )
        with c_df2:
            _sel_to = st.date_input(
                "To",
                value=st.session_state["up_date_to"],
                format="DD/MM/YYYY",
                key="up_inp_to",
            )

        if _sel_from != st.session_state["up_date_from"] or _sel_to != st.session_state["up_date_to"]:
            st.session_state["up_date_from"] = _sel_from
            st.session_state["up_date_to"] = _sel_to
            st.session_state["up_range_mode"] = "Custom"

        _modo_rng = st.session_state["up_range_mode"]
        _d_from_use = None if _modo_rng == "All" else min(_sel_from, _sel_to)
        _d_to_use = hoy_syd if _modo_rng == "All" else max(_sel_from, _sel_to)
        _days_fetch = None if _modo_rng == "All" else max(30, (hoy_syd - _d_from_use).days + 3)

        cuentas_up, err_cuentas = obtener_cuentas_up_bank(
            up_token_activo, st.session_state["up_refresh_nonce"]
        )
        txs_raw, err_txs = obtener_transacciones_up_bank(
            up_token_activo, _days_fetch, st.session_state["up_refresh_nonce"], max_pages=40
        )

        if err_cuentas or err_txs:
            st.error(err_cuentas or err_txs)
            if not up_token_secreto and st.button("Clear temporary token"):
                st.session_state["up_temp_token"] = ""
                st.rerun()
        else:
            own_up_ids = {c["id"] for c in (cuentas_up or []) if c.get("id")} if cuentas_up else None
            own_up_names = {str(c.get("name", "")).strip().lower() for c in (cuentas_up or []) if c.get("name")} if cuentas_up else set()
            own_up_names.update({"spending", "2up spending", "fire extinguisher", "trips & goals", "emergency", "essentials", "treat yourself"})
            filas_tx = [clasificar_transaccion_up(tx, own_up_ids, own_up_names) for tx in txs_raw]
            df_up = pd.DataFrame(filas_tx)

            if df_up.empty:
                st.info("No Up Bank transactions found.")
            else:
                df_filtrado = df_up.copy()
                if ocultar_internas_up:
                    df_filtrado = df_filtrado[~df_filtrado["is_internal_up"]]

                n_review = int(df_filtrado["needs_review"].sum()) if "needs_review" in df_filtrado.columns else 0
                if n_review > 0:
                    st.info(
                        f"⚠️ {n_review} transfer(s) could not be confirmed as your own Up Bank account and were kept in Cash Flow for your review."
                    )

                f_txt = st.text_input("🔎 Search transactions", key="up_search_tx")
                df_show, stats_up = calcular_resumen_cashflow_up(
                    df_filtrado,
                    date_from=_d_from_use,
                    date_to=_d_to_use,
                    search_text=f_txt,
                    hoy_date=hoy_syd,
                )
                df_period_all, stats_period_all = calcular_resumen_cashflow_up(
                    df_filtrado,
                    date_from=_d_from_use,
                    date_to=_d_to_use,
                    search_text="",
                    hoy_date=hoy_syd,
                )
                st.session_state["up_live_cashflow_stats"] = {
                    "search": f_txt.strip(),
                    "stats": stats_up,
                    "period_stats": stats_period_all,
                }

                def _fmt_signed_aud(v):
                    return f"+${v:,.2f} AUD" if v >= 0 else f"-${abs(v):,.2f} AUD"

                if f_txt.strip() or _modo_rng != "All":
                    _tot_col = "#16A34A" if stats_up["total"] >= 0 else "#DC2626"
                    _per_str = f"{stats_up['d_from'].strftime('%d/%m/%Y')} → {stats_up['d_to'].strftime('%d/%m/%Y')} ({stats_up['n_days']} days)"
                    _sum_suffix = f' — "{f_txt.strip()}"' if f_txt.strip() else ''
                    st.markdown(
                        f"<div style='border:1px solid var(--fin-border-muted); border-radius:12px; padding:10px 14px; margin:8px 0 12px 0;'>"
                        f"<div style='display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px; margin-bottom:8px;'>"
                        f"<b style='color:var(--fin-ink); font-size:0.95rem;'>📊 Period Summary{_sum_suffix}</b>"
                        f"<span style='color:var(--fin-muted); font-size:0.82rem;'>{_per_str}</span>"
                        f"</div>"
                        f"<div style='display:grid; grid-template-columns:repeat(auto-fit, minmax(120px, 1fr)); gap:8px; font-size:0.86rem;'>"
                        f"<div><span style='color:var(--fin-muted);'>Transactions</span><br><b style='color:var(--fin-ink);'>{stats_up['count']}</b></div>"
                        f"<div><span style='color:var(--fin-muted);'>Total</span><br><b style='color:{_tot_col};'>{_fmt_signed_aud(stats_up['total'])}</b></div>"
                        f"<div><span style='color:var(--fin-muted);'>Avg / transaction</span><br><b style='color:var(--fin-ink);'>{_fmt_signed_aud(stats_up['avg_tx'])}</b></div>"
                        f"<div><span style='color:var(--fin-muted);'>Avg / DAY</span><br><b style='color:var(--fin-ink);'>{_fmt_signed_aud(stats_up['avg_day'])}</b></div>"
                        f"<div><span style='color:var(--fin-muted);'>Avg / WEEK</span><br><b style='color:var(--fin-ink);'>{_fmt_signed_aud(stats_up['avg_week'])}</b></div>"
                        f"<div><span style='color:var(--fin-muted);'>Avg / MONTH</span><br><b style='color:var(--fin-ink);'>{_fmt_signed_aud(stats_up['avg_month'])}</b></div>"
                        f"</div></div>",
                        unsafe_allow_html=True,
                    )

                if not df_show.empty:
                    df_show = df_show.sort_values("Date_Sort", ascending=False)
                    tabla_up = df_show[["Date", "Description", "Tag", "Status", "Note", "Amount (AUD)"]].copy()
                    tabla_up["Amount (AUD)"] = tabla_up["Amount (AUD)"].apply(
                        lambda x: f"+${x:,.2f} AUD" if x >= 0 else f"-${abs(x):,.2f} AUD"
                    )
                    st.dataframe(tabla_up, use_container_width=True, hide_index=True)
                else:
                    st.info("No transactions match this search and date range.")

                # ---------------- TOP RECURRING COSTS / INCOMES PER TAG ----------------
                st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
                st.markdown("<h3 style='color: var(--fin-ink); margin-bottom:4px;'>Top recurring costs</h3>", unsafe_allow_html=True)
                _tag_mode = st.radio(
                    "Recurring type",
                    ["Costs", "Incomes"],
                    horizontal=True,
                    label_visibility="collapsed",
                    key="up_top_tags_mode",
                )
                df_tags, tags_tot = calcular_top_tags_up(
                    df_period_all,
                    mode=_tag_mode,
                    date_from=stats_period_all["d_from"],
                    date_to=stats_period_all["d_to"],
                    hoy_date=hoy_syd,
                )
                if df_tags.empty:
                    st.info(f"No {_tag_mode.lower()} found in this period.")
                else:
                    _bar_col = "#DC2626" if _tag_mode == "Costs" else "#16A34A"
                    _rows_html = []
                    for _, _tr in df_tags.iterrows():
                        _w_pct = max(2.0, min(100.0, float(_tr["Share_Pct"])))
                        _rows_html.append(
                            f"<tr style='border-bottom:1px solid var(--fin-border-muted);'>"
                            f"<td style='padding:7px 8px; color:var(--fin-ink); font-weight:600; white-space:nowrap;'>{_tr['Tag']}</td>"
                            f"<td style='padding:7px 8px; min-width:110px;'>"
                            f"<div style='display:flex; align-items:center; gap:6px;'>"
                            f"<div style='flex:1; height:8px; background:rgba(148,163,184,0.22); border-radius:999px; overflow:hidden;'>"
                            f"<div style='width:{_w_pct:.1f}%; height:100%; background:{_bar_col}; border-radius:999px;'></div></div>"
                            f"<span style='font-size:0.76rem; color:var(--fin-muted); min-width:38px; text-align:right;'>{_tr['Share_Pct']:.1f}%</span>"
                            f"</div></td>"
                            f"<td style='padding:7px 8px; text-align:right; color:var(--fin-ink); white-space:nowrap;'>${_tr['Total']:,.2f}</td>"
                            f"<td style='padding:7px 8px; text-align:right; color:var(--fin-ink); white-space:nowrap;'>${_tr['Avg_Week']:,.2f}</td>"
                            f"<td style='padding:7px 8px; text-align:right; color:var(--fin-ink); font-weight:700; white-space:nowrap;'>${_tr['Avg_Month']:,.2f}</td>"
                            f"<td style='padding:7px 8px; text-align:right; color:var(--fin-muted);'>{int(_tr['Count'])}</td>"
                            f"</tr>"
                        )
                    _tot_row_html = (
                        f"<tr style='border-top:2px solid var(--fin-border-muted); font-weight:800;'>"
                        f"<td style='padding:8px; color:var(--fin-ink);'>Total</td>"
                        f"<td style='padding:8px; color:var(--fin-muted); font-size:0.78rem;'>100%</td>"
                        f"<td style='padding:8px; text-align:right; color:{_bar_col}; white-space:nowrap;'>${tags_tot['total']:,.2f}</td>"
                        f"<td style='padding:8px; text-align:right; color:{_bar_col}; white-space:nowrap;'>${tags_tot['avg_week']:,.2f}</td>"
                        f"<td style='padding:8px; text-align:right; color:{_bar_col}; white-space:nowrap;'>${tags_tot['avg_month']:,.2f}</td>"
                        f"<td style='padding:8px; text-align:right; color:var(--fin-ink);'>{tags_tot['count']}</td>"
                        f"</tr>"
                    )
                    st.markdown(
                        f"<div style='overflow-x:auto; border:1px solid var(--fin-border-muted); border-radius:12px; margin-top:6px;'>"
                        f"<table style='width:100%; border-collapse:collapse; font-size:0.86rem;'>"
                        f"<thead><tr style='border-bottom:1.5px solid var(--fin-border-muted); text-align:left;'>"
                        f"<th style='padding:8px; color:var(--fin-muted);'>Tag</th>"
                        f"<th style='padding:8px; color:var(--fin-muted);'>Share</th>"
                        f"<th style='padding:8px; text-align:right; color:var(--fin-muted);'>Total (AUD)</th>"
                        f"<th style='padding:8px; text-align:right; color:var(--fin-muted);'>Avg / Week</th>"
                        f"<th style='padding:8px; text-align:right; color:var(--fin-muted);'>Avg / Month</th>"
                        f"<th style='padding:8px; text-align:right; color:var(--fin-muted);'>Tx</th>"
                        f"</tr></thead>"
                        f"<tbody>{''.join(_rows_html)}{_tot_row_html}</tbody>"
                        f"</table></div>",
                        unsafe_allow_html=True,
                    )


# =========================================================================
# ==================== FLOATING BOTTOM-RIGHT CHATBOT ======================
# =========================================================================
if "finapp_chat_history" not in st.session_state:
    st.session_state["finapp_chat_history"] = [
        {
            "role": "assistant",
            "content": "Hey Julian! Ask me anything about your AUD costs, income, net worth, or Up Bank transactions."
        }
    ]

with st.popover("💬 AI Advisor"):
    chat_box = st.container(height=360)
    with chat_box:
        for msg in st.session_state["finapp_chat_history"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    c_form_col, c_clr_col = st.columns([5.2, 0.9])
    with c_form_col:
        with st.form("finapp_floating_chat_form", clear_on_submit=True):
            c_inp, c_send = st.columns([4, 1.3])
            user_q = c_inp.text_input(
                "Ask about your finances...",
                placeholder="e.g. How much did ME Group pay me?",
                label_visibility="collapsed",
                key="finapp_chat_text_input",
            )
            submitted_q = c_send.form_submit_button("Send", type="primary", use_container_width=True)
    with c_clr_col:
        if st.button("🗑️", key="chat_clear_btn", help="Clear chat", use_container_width=True):
            st.session_state["finapp_chat_history"] = [
                {
                    "role": "assistant",
                    "content": "Chat cleared! What would you like to check in your finances?"
                }
            ]
            st.rerun()

    if submitted_q and user_q.strip():
        # Build live AUD financial snapshot for Gemini
        costos_act = [c for c in datos.get("costos", []) if c.get("activo", True)]
        ingresos_act = [i for i in datos.get("ingresos", []) if i.get("activo", True)]
        tot_c = sum(c.get("monto", 0) for c in costos_act)
        tot_i = sum(i.get("monto", 0) for i in ingresos_act)
        resumen_ctx = [
            f"Monthly Active Costs: ${tot_c:,.2f} AUD ({len(costos_act)} items)",
            f"Monthly Active Income: ${tot_i:,.2f} AUD ({len(ingresos_act)} items)",
            f"Monthly Net Savings: ${(tot_i - tot_c):,.2f} AUD",
            "Active Costs list: " + "; ".join(f"{c.get('nombre')} (${c.get('monto', 0):,.2f}, {c.get('categoria')})" for c in costos_act[:30]),
            "Active Income list: " + "; ".join(f"{i.get('nombre')} (${i.get('monto', 0):,.2f}, {i.get('categoria')})" for i in ingresos_act[:20]),
        ]

        inv_items = datos.get("inversiones", [])
        if inv_items:
            resumen_ctx.append(
                "Net Worth / Investments entries: " + "; ".join(
                    f"{x.get('nombre', x.get('activo', 'Asset'))} ({x.get('categoria', '')}, qty {x.get('cantidad', 0)})"
                    for x in inv_items[:30]
                )
            )

        bn_k_c, bn_s_c, bn_ru_c, bn_rs_c = _obtener_binance_keys()
        if bn_k_c and bn_s_c:
            bn_rows_c, bn_err_c = obtener_binance_portfolio(bn_k_c, bn_s_c, usd_to_aud, relay_url=bn_ru_c, relay_secret=bn_rs_c)
            if bn_rows_c and not bn_err_c:
                bn_vis = [x for x in bn_rows_c if float(x.get("val_aud", 0.0) or 0.0) >= 2.0]
                tot_bn = sum(x["val_aud"] for x in bn_vis)
                resumen_ctx.append(
                    f"Live Binance Portfolio Total: ${tot_bn:,.2f} AUD | "
                    + "; ".join(f"{x['asset']} ({x['wallet']}): {x['qty']} = ${x['val_aud']:,.2f} AUD" for x in bn_vis[:25])
                )

        gcal_c = _obtener_gcal_url()
        if gcal_c:
            ev_c, err_gc = obtener_eventos_gcal(gcal_c, days_ahead=30)
            if ev_c and not err_gc:
                resumen_ctx.append(
                    "Upcoming Google Calendar Payments (next 30d): "
                    + "; ".join(
                        f"{e['date_str']} ({e['when']}): {e['title']}"
                        + (f" [${e['amount_aud']:,.2f} AUD]" if e['amount_aud'] is not None else "")
                        for e in ev_c[:15]
                    )
                )

        up_tok = _obtener_up_token() or st.session_state.get("up_temp_token", "")
        if up_tok:
            cuentas_c, err_c = obtener_cuentas_up_bank(up_tok, st.session_state.get("up_refresh_nonce", 0))
            if cuentas_c and not err_c:
                resumen_ctx.append(
                    "Up Bank Accounts: " + "; ".join(f"{a['name']}: ${a['balance_aud']:,.2f} AUD" for a in cuentas_c)
                )
            _cf_cached = st.session_state.get("up_live_cashflow_stats")
            if _cf_cached and _cf_cached.get("search"):
                _cs = _cf_cached["stats"]
                resumen_ctx.append(
                    f"Active Live Cash Flow Filter ('{_cf_cached['search']}', {_cs['d_from'].strftime('%d/%m/%Y')} to {_cs['d_to'].strftime('%d/%m/%Y')}, {_cs['n_days']}d): "
                    f"tx={_cs['count']}, total=${_cs['total']:,.2f} AUD, avg_tx=${_cs['avg_tx']:,.2f}, "
                    f"avg_day=${_cs['avg_day']:,.2f}, avg_week=${_cs['avg_week']:,.2f}, avg_month=${_cs['avg_month']:,.2f}"
                )
            txs_c, err_t = obtener_transacciones_up_bank(up_tok, 180, st.session_state.get("up_refresh_nonce", 0), max_pages=20)
            if txs_c and not err_t:
                parsed_c = [clasificar_transaccion_up(t) for t in txs_c]
                parsed_c = [p for p in parsed_c if not p["is_internal_up"]]
                df_c_up = pd.DataFrame(parsed_c)
                if not df_c_up.empty:
                    hoy_c = datetime.now(TZ_SYDNEY).date()
                    _, _all_s = calcular_resumen_cashflow_up(df_c_up, hoy_date=hoy_c)
                    _n_days_c = max(1, _all_s["n_days"])
                    _n_wks_c = _n_days_c / 7.0
                    _n_mos_c = _n_days_c / 30.4375
                    _by_desc = df_c_up.groupby("Description", as_index=False).agg(Total=("Amount (AUD)", "sum"), Count=("Amount (AUD)", "count"))
                    _by_desc["Abs"] = _by_desc["Total"].abs()
                    _top_payees = _by_desc.sort_values("Abs", ascending=False).head(15)
                    resumen_ctx.append(
                        f"Pre-calculated Payee Averages ({_all_s['d_from'].strftime('%d/%m/%Y')} to {_all_s['d_to'].strftime('%d/%m/%Y')}, {_n_days_c}d): "
                        + "; ".join(
                            f"{r['Description']}: total=${r['Total']:,.2f}, avg/mo=${r['Total']/_n_mos_c:,.2f}, avg/wk=${r['Total']/_n_wks_c:,.2f} ({int(r['Count'])} tx)"
                            for _, r in _top_payees.iterrows()
                        )
                    )
                    _top_tags_c, _ = calcular_top_tags_up(df_c_up, mode="Costs", date_from=_all_s["d_from"], date_to=_all_s["d_to"], hoy_date=hoy_c)
                    if not _top_tags_c.empty:
                        resumen_ctx.append(
                            "Top Recurring Cost Tags: " + "; ".join(
                                f"{r['Tag']}: total=${r['Total']:,.2f}, avg/mo=${r['Avg_Month']:,.2f}, avg/wk=${r['Avg_Week']:,.2f}"
                                for _, r in _top_tags_c.head(10).iterrows()
                            )
                        )
                resumen_ctx.append(
                    "Latest 12 Up Bank Transactions: "
                    + "; ".join(f"{p['Date']} | {p['Description']} | {p['Tag']} | ${p['Amount (AUD)']:,.2f}" for p in parsed_c[:12])
                )

        gemini_k = _obtener_gemini_key()
        with st.spinner("Thinking..."):
            respuesta_ai = consultar_chatbot_finanzas(
                user_q.strip(),
                st.session_state["finapp_chat_history"],
                "\n".join(resumen_ctx),
                gemini_k,
            )

        st.session_state["finapp_chat_history"].append({"role": "user", "content": user_q.strip()})
        st.session_state["finapp_chat_history"].append({"role": "assistant", "content": respuesta_ai})
        st.rerun()


activar_interactividad_avanzada(
    datos.get('categorias_costos', []),
    datos.get('categorias_ingresos', []),
    datos.get('ubicaciones_guardadas', []),
    tooltip_cant_actual
)
