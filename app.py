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
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape as xml_escape

st.set_page_config(
    page_title="Finapp",
    layout="wide",
    page_icon="🌿",
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


PALETA_PASTEL = [
    "#9B89B3",  # Pastel plum lilac
    "#F6A682",  # Pastel peach coral
    "#76C893",  # Pastel mint green
    "#72B0E8",  # Pastel sky blue
    "#F4D06F",  # Pastel warm yellow
    "#E58F9E",  # Pastel dusty rose
    "#64C2C7",  # Pastel turquoise
    "#C3A6A0",  # Pastel taupe
    "#A3C9A8",  # Pastel sage green
    "#D99B66",  # Soft terracotta
    "#8E9AAF",  # Pastel slate blue
    "#E2AFCF"   # Pastel orchid
]

ICONOS_DISPONIBLES = [
    "🧾", "💡", "🚗", "👗", "🏠", "🛒", "🩺", "🏊‍♀️", "🧘‍♀️", "✈️",
    "📺", "🐾", "📚", "🎁", "💳", "💼", "💵", "👵", "📈", "📁",
    "🌿", "💎", "🛠️", "🧹", "🍽️", "📱", "⛽", "📌",
    "🔨", "🧰", "🖌️", "🌱", "🐜", "🚚", "🔑", "🛋️", "🛏️", "🖼️",
    "🧺", "🚨", "🚿", "❄️", "🌡️", "☀️", "🍎", "🥩", "🥖", "☕",
    "🧴", "🫧", "👕", "🧻", "🧽", "🪥", "🧼", "🌸", "🚆", "🚕",
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

        // 1. Style main tabs with 🍀 and remove default bottom highlight line
        function estilizarTrebolesSolapas() {
            const highlights = doc.querySelectorAll('[data-baseweb="tab-highlight"], [data-baseweb="tab-border"]');
            highlights.forEach(el => {
                el.style.setProperty('display', 'none', 'important');
                el.style.setProperty('height', '0px', 'important');
                el.style.setProperty('background', 'transparent', 'important');
                el.style.setProperty('background-color', 'transparent', 'important');
                el.style.setProperty('border', 'none', 'important');
            });

            const tabLists = doc.querySelectorAll('[data-baseweb="tab-list"]');
            tabLists.forEach(tl => {
                tl.style.setProperty('height', 'auto', 'important');
                tl.style.setProperty('min-height', '72px', 'important');
                tl.style.setProperty('overflow', 'visible', 'important');
                tl.style.setProperty('padding', '8px 4px', 'important');
                tl.style.setProperty('gap', '16px', 'important');
                tl.style.setProperty('align-items', 'center', 'important');
                tl.style.setProperty('border', 'none', 'important');
            });

            const tabs = doc.querySelectorAll('button[data-baseweb="tab"]');
            tabs.forEach(tab => {
                const isSelected = tab.getAttribute('aria-selected') === 'true';
                tab.style.setProperty('border-radius', '999px', 'important');
                tab.style.setProperty('min-height', '58px', 'important');
                tab.style.setProperty('height', 'auto', 'important');
                tab.style.setProperty('padding', '12px 32px', 'important');
                tab.style.setProperty('transition', 'all 0.25s ease-in-out', 'important');
                tab.style.setProperty('overflow', 'visible', 'important');

                if (isSelected) {
                    tab.style.setProperty('background', '#E6F7EF', 'important');
                    tab.style.setProperty('background-color', '#E6F7EF', 'important');
                    tab.style.setProperty('border', '2px solid #A8DFC4', 'important');
                    tab.style.setProperty('box-shadow', '0 4px 14px rgba(45, 106, 79, 0.14)', 'important');
                } else {
                    tab.style.setProperty('background', '#F9FAFB', 'important');
                    tab.style.setProperty('background-color', '#F9FAFB', 'important');
                    tab.style.setProperty('border', '1.5px solid #D8ECE3', 'important');
                    tab.style.setProperty('box-shadow', '0 2px 6px rgba(0, 0, 0, 0.04)', 'important');
                }

                const p = tab.querySelector('[data-testid="stMarkdownContainer"] p') || tab.querySelector('p');
                if (p) {
                    p.style.setProperty('font-size', '1.22rem', 'important');
                    p.style.setProperty('font-weight', '800', 'important');
                    p.style.setProperty('color', isSelected ? '#1B4332' : '#4B5563', 'important');
                    p.style.setProperty('margin', '0px', 'important');
                    p.style.setProperty('display', 'inline-flex', 'important');
                    p.style.setProperty('align-items', 'center', 'important');
                    p.style.setProperty('gap', '8px', 'important');

                    let spanClover = p.querySelector('.trebol-tab-icon');
                    if (!spanClover && (p.textContent || '').includes('🍀')) {
                        const textoLimpio = (p.textContent || '').replace('🍀', '').trim();
                        p.innerHTML = '<span class="trebol-tab-icon">🍀</span><span>' + textoLimpio + '</span>';
                        spanClover = p.querySelector('.trebol-tab-icon');
                    }
                    if (spanClover) {
                        spanClover.style.setProperty('font-size', '1.3em', 'important');
                        spanClover.style.setProperty('line-height', '1', 'important');
                        spanClover.style.setProperty('vertical-align', 'middle', 'important');
                        spanClover.style.setProperty('display', 'inline-block', 'important');
                        spanClover.style.setProperty('transition', 'opacity 0.25s ease', 'important');
                        spanClover.style.setProperty('opacity', isSelected ? '1' : '0.5', 'important');
                    }
                }
            });
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
                    btn.style.setProperty('background', '#57CC99', 'important');
                    btn.style.setProperty('background-color', '#57CC99', 'important');
                    btn.style.setProperty('border', '1.5px solid #38A3A5', 'important');
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

        // 5. Tooltip on "3. Quantity Held" & green Refresh button in sidebar
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
                        btn.style.setProperty('background', '#D8F3DC', 'important');
                        btn.style.setProperty('background-color', '#D8F3DC', 'important');
                        btn.style.setProperty('border', '1.5px solid #74C69D', 'important');
                        btn.style.setProperty('color', '#1B4332', 'important');
                        btn.style.setProperty('font-weight', '700', 'important');
                        btn.style.setProperty('border-radius', '12px', 'important');
                        btn.querySelectorAll('p, span, div').forEach(ch => {
                            ch.style.setProperty('color', '#1B4332', 'important');
                            ch.style.setProperty('font-weight', '700', 'important');
                        });
                    }
                });
            }
        }

        function actualizarInterfaz() {
            estilizarTrebolesSolapas();
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
            setTimeout(estilizarTrebolesSolapas, 30);
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


# ----------------- 3D DYNAMIC FINANCIAL HEALTH PANEL -----------------
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
    """Continuously interpolates between a list of (pos, '#RRGGBB') tuples."""
    s = max(0.0, min(1.0, float(score)))
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if p0 <= s <= p1:
            local_t = (s - p0) / (p1 - p0) if p1 > p0 else 0.0
            return _lerp_color(c0, c1, local_t)
    return stops[-1][1]


def _construir_svg_canguro(score):
    """Builds the 3D kangaroo SVG: skeleton with flies at score=0, tired/sad in middle, happy/fed when high."""
    if score <= 0.02:
        return (
            '<svg class="jardin-char-svg" viewBox="0 0 170 150" style="overflow: visible;" xmlns="http://www.w3.org/2000/svg">'
            '<defs>'
            '<linearGradient id="bone3DK" x1="0%" y1="0%" x2="0%" y2="100%">'
            '<stop offset="0%" stop-color="#FEFCE8"/>'
            '<stop offset="55%" stop-color="#E7E5E4"/>'
            '<stop offset="100%" stop-color="#A8A29E"/>'
            '</linearGradient>'
            '<filter id="boneShadowK" x="-20%" y="-20%" width="140%" height="140%">'
            '<feDropShadow dx="0" dy="3" stdDeviation="2.5" flood-color="#000000" flood-opacity="0.38"/>'
            '</filter>'
            '</defs>'
            '<ellipse cx="86" cy="134" rx="68" ry="9" fill="#000000" opacity="0.28"/>'
            '<g filter="url(#boneShadowK)">'
            '<path d="M 10 130 Q 28 134 48 126" stroke="url(#bone3DK)" stroke-width="5.5" stroke-dasharray="6 3" stroke-linecap="round" fill="none"/>'
            '<ellipse cx="52" cy="122" rx="11" ry="8" fill="url(#bone3DK)" transform="rotate(-15 52 122)"/>'
            '<circle cx="52" cy="122" r="3.5" fill="#57534E"/>'
            '<line x1="50" y1="124" x2="30" y2="136" stroke="url(#bone3DK)" stroke-width="5.5" stroke-linecap="round"/>'
            '<circle cx="30" cy="136" r="3.8" fill="url(#bone3DK)"/>'
            '<line x1="30" y1="136" x2="56" y2="140" stroke="url(#bone3DK)" stroke-width="4.5" stroke-linecap="round"/>'
            '<line x1="56" y1="140" x2="78" y2="139" stroke="url(#bone3DK)" stroke-width="3.8" stroke-linecap="round"/>'
            '<path d="M 58 120 Q 84 110 112 122" stroke="url(#bone3DK)" stroke-width="6" stroke-dasharray="7 3" stroke-linecap="round" fill="none"/>'
            '<path d="M 68 117 Q 70 94 80 102" stroke="url(#bone3DK)" stroke-width="4" stroke-linecap="round" fill="none"/>'
            '<path d="M 77 115 Q 80 90 90 100" stroke="url(#bone3DK)" stroke-width="4" stroke-linecap="round" fill="none"/>'
            '<path d="M 86 115 Q 90 92 99 101" stroke="url(#bone3DK)" stroke-width="4" stroke-linecap="round" fill="none"/>'
            '<path d="M 95 117 Q 98 96 106 104" stroke="url(#bone3DK)" stroke-width="3.8" stroke-linecap="round" fill="none"/>'
            '<path d="M 103 119 Q 106 102 112 108" stroke="url(#bone3DK)" stroke-width="3.4" stroke-linecap="round" fill="none"/>'
            '<line x1="106" y1="121" x2="96" y2="136" stroke="url(#bone3DK)" stroke-width="4.2" stroke-linecap="round"/>'
            '<line x1="96" y1="136" x2="112" y2="139" stroke="url(#bone3DK)" stroke-width="3.5" stroke-linecap="round"/>'
            '<g transform="translate(116, 114) rotate(18)">'
            '<ellipse cx="10" cy="4" rx="14" ry="10" fill="url(#bone3DK)"/>'
            '<path d="M 18 -2 L 38 3 Q 40 7 35 9 L 16 9 Z" fill="url(#bone3DK)"/>'
            '<path d="M 14 9 L 33 12 L 31 15 L 12 13 Z" fill="#D6D3D1"/>'
            '<ellipse cx="14" cy="2" rx="4.5" ry="3.8" fill="#1C1917"/>'
            '<polygon points="33,4 37,5 34,7" fill="#1C1917"/>'
            '<line x1="20" y1="9" x2="32" y2="10" stroke="#78716C" stroke-width="1.4" stroke-dasharray="2 2"/>'
            '</g>'
            '</g>'
            '<g class="jardin-fly-1" transform="translate(78, 78)">'
            '<ellipse cx="-2.5" cy="-2.5" rx="3.2" ry="1.8" fill="#E0F2FE" opacity="0.85" transform="rotate(-25)"/>'
            '<ellipse cx="2.5" cy="-2.5" rx="3.2" ry="1.8" fill="#E0F2FE" opacity="0.85" transform="rotate(25)"/>'
            '<ellipse cx="0" cy="0" rx="3.2" ry="2.2" fill="#111827"/>'
            '</g>'
            '<g class="jardin-fly-2" transform="translate(122, 86)">'
            '<ellipse cx="-2.2" cy="-2.2" rx="2.8" ry="1.6" fill="#E0F2FE" opacity="0.85" transform="rotate(-25)"/>'
            '<ellipse cx="2.2" cy="-2.2" rx="2.8" ry="1.6" fill="#E0F2FE" opacity="0.85" transform="rotate(25)"/>'
            '<ellipse cx="0" cy="0" rx="2.8" ry="1.9" fill="#111827"/>'
            '</g>'
            '<g class="jardin-fly-3" transform="translate(46, 92)">'
            '<ellipse cx="-2.2" cy="-2.2" rx="2.8" ry="1.6" fill="#E0F2FE" opacity="0.85" transform="rotate(-25)"/>'
            '<ellipse cx="2.2" cy="-2.2" rx="2.8" ry="1.6" fill="#E0F2FE" opacity="0.85" transform="rotate(25)"/>'
            '<ellipse cx="0" cy="0" rx="2.8" ry="1.9" fill="#111827"/>'
            '</g>'
            '</svg>'
        )

    fat_scale_x = 0.74 + 0.32 * score
    posture_drop = (1.0 - score) * 12.0
    ear_droop = (1.0 - score) * 26.0
    ribs_opacity = max(0.0, min(0.75, (0.35 - score) / 0.35)) if score < 0.35 else 0.0
    euca_leaf_op = max(0.0, min(1.0, (score - 0.15) / 0.5))
    leaf_col = _multi_color([(0.0, "#A16207"), (0.5, "#EAB308"), (1.0, "#22C55E")], score)

    if score >= 0.65:
        anim_cls = "jardin-kanga-happy"
        mouth_d = "M 82 65 Q 90 73 97 64"
        eyes_svg = (
            '<circle cx="85" cy="50" r="4" fill="#1F2937"/>'
            '<circle cx="86.4" cy="48.6" r="1.4" fill="#FFFFFF"/>'
            '<circle cx="99" cy="50" r="3.6" fill="#1F2937"/>'
            '<circle cx="100.2" cy="48.6" r="1.2" fill="#FFFFFF"/>'
            '<ellipse cx="78" cy="57" rx="4.5" ry="2.5" fill="#F472B6" opacity="0.5"/>'
        )
    else:
        anim_cls = "jardin-animal-tired"
        mouth_d = "M 82 70 Q 90 63 97 70"
        eyes_svg = (
            '<circle cx="85" cy="52" r="3.6" fill="#1F2937"/>'
            '<path d="M 79 47 L 90 50" stroke="#451A03" stroke-width="2.1" stroke-linecap="round"/>'
            '<circle cx="99" cy="52" r="3.4" fill="#1F2937"/>'
            '<path d="M 94 50 L 104 47" stroke="#451A03" stroke-width="2.1" stroke-linecap="round"/>'
            '<path d="M 75 58 Q 73 65 75 68 Q 77 65 75 58 Z" fill="#38BDF8" opacity="0.85"/>'
        )

    return (
        '<svg class="jardin-char-svg" viewBox="0 0 160 220" style="overflow: visible;" xmlns="http://www.w3.org/2000/svg">'
        '<defs>'
        '<radialGradient id="kangaFur3D" cx="35%" cy="30%" r="70%">'
        '<stop offset="0%" stop-color="#F59E0B"/>'
        '<stop offset="55%" stop-color="#D97706"/>'
        '<stop offset="100%" stop-color="#92400E"/>'
        '</radialGradient>'
        '<linearGradient id="kangaBelly3D" x1="0%" y1="0%" x2="0%" y2="100%">'
        '<stop offset="0%" stop-color="#FEF3C7"/>'
        '<stop offset="100%" stop-color="#FDE68A"/>'
        '</linearGradient>'
        '<filter id="kangaShadow3D" x="-20%" y="-20%" width="140%" height="140%">'
        '<feDropShadow dx="0" dy="4" stdDeviation="3" flood-color="#000000" flood-opacity="0.25"/>'
        '</filter>'
        '</defs>'
        '<ellipse cx="82" cy="204" rx="42" ry="9" fill="#000000" opacity="0.22"/>'
        f'<g class="{anim_cls}" transform="translate(0, {posture_drop:.1f})" filter="url(#kangaShadow3D)">'
        '<path d="M 48 152 Q 12 160 10 134 Q 8 120 20 122 Q 30 126 54 138 Z" fill="url(#kangaFur3D)"/>'
        '<ellipse cx="62" cy="164" rx="18" ry="26" fill="url(#kangaFur3D)"/>'
        '<path d="M 48 188 L 96 188 Q 104 188 102 195 L 44 195 Q 38 191 48 188 Z" fill="url(#kangaFur3D)"/>'
        f'<g transform="translate(78, 120) scale({fat_scale_x:.2f}, 1)">'
        '<ellipse cx="0" cy="0" rx="31" ry="46" fill="url(#kangaFur3D)"/>'
        '<ellipse cx="5" cy="4" rx="20" ry="35" fill="url(#kangaBelly3D)"/>'
        '</g>'
        f'<g opacity="{ribs_opacity:.2f}" stroke="#FEF3C7" stroke-width="2.2" stroke-linecap="round" fill="none">'
        '<path d="M 66 102 Q 80 98 91 104"/>'
        '<path d="M 65 113 Q 80 109 92 115"/>'
        '<path d="M 66 124 Q 80 120 91 126"/>'
        '</g>'
        '<path d="M 70 82 L 79 42 L 98 46 L 92 86 Z" fill="url(#kangaFur3D)"/>'
        f'<ellipse cx="75" cy="28" rx="6.5" ry="20" fill="url(#kangaFur3D)" transform="rotate({-16 - ear_droop:.1f} 75 42)"/>'
        f'<ellipse cx="75" cy="28" rx="3.5" ry="13" fill="#FDE68A" transform="rotate({-16 - ear_droop:.1f} 75 42)"/>'
        f'<ellipse cx="95" cy="28" rx="6.5" ry="20" fill="url(#kangaFur3D)" transform="rotate({14 + ear_droop:.1f} 95 42)"/>'
        f'<ellipse cx="95" cy="28" rx="3.5" ry="13" fill="#FDE68A" transform="rotate({14 + ear_droop:.1f} 95 42)"/>'
        '<ellipse cx="88" cy="56" rx="20" ry="17" fill="url(#kangaFur3D)"/>'
        '<ellipse cx="100" cy="60" rx="11" ry="9" fill="url(#kangaBelly3D)"/>'
        '<circle cx="108" cy="57" r="4" fill="#1F2937"/>'
        + eyes_svg +
        f'<path d="{mouth_d}" stroke="#451A03" stroke-width="2.2" fill="none" stroke-linecap="round"/>'
        '<path d="M 84 94 Q 108 102 114 114" stroke="#D97706" stroke-width="7.5" stroke-linecap="round" fill="none"/>'
        f'<g opacity="{euca_leaf_op:.2f}" transform="translate(114, 112)">'
        '<path d="M 0 0 Q 14 -12 22 -20" stroke="#15803D" stroke-width="2.2" fill="none"/>'
        f'<ellipse cx="12" cy="-12" rx="7" ry="4" fill="{leaf_col}" transform="rotate(-30 12 -12)"/>'
        f'<ellipse cx="20" cy="-18" rx="7" ry="4" fill="{leaf_col}" transform="rotate(20 20 -18)"/>'
        '</g>'
        '</g>'
        '</svg>'
    )


def _construir_svg_koala(score):
    """Builds the 3D koala SVG: skeleton with flies at score=0, tired/sad in middle, happy/fed when high."""
    if score <= 0.02:
        return (
            '<svg class="jardin-char-svg" viewBox="0 0 170 150" style="overflow: visible;" xmlns="http://www.w3.org/2000/svg">'
            '<defs>'
            '<linearGradient id="bone3DKo" x1="0%" y1="0%" x2="0%" y2="100%">'
            '<stop offset="0%" stop-color="#FEFCE8"/>'
            '<stop offset="55%" stop-color="#E7E5E4"/>'
            '<stop offset="100%" stop-color="#A8A29E"/>'
            '</linearGradient>'
            '<filter id="boneShadowKo" x="-20%" y="-20%" width="140%" height="140%">'
            '<feDropShadow dx="0" dy="3" stdDeviation="2.5" flood-color="#000000" flood-opacity="0.38"/>'
            '</filter>'
            '</defs>'
            '<ellipse cx="86" cy="134" rx="62" ry="9" fill="#000000" opacity="0.28"/>'
            '<g filter="url(#boneShadowKo)">'
            '<ellipse cx="122" cy="123" rx="10" ry="7.5" fill="url(#bone3DKo)" transform="rotate(12 122 123)"/>'
            '<circle cx="122" cy="123" r="3" fill="#57534E"/>'
            '<line x1="124" y1="125" x2="142" y2="137" stroke="url(#bone3DKo)" stroke-width="5" stroke-linecap="round"/>'
            '<line x1="142" y1="137" x2="126" y2="140" stroke="url(#bone3DKo)" stroke-width="4" stroke-linecap="round"/>'
            '<path d="M 62 122 Q 92 112 118 122" stroke="url(#bone3DKo)" stroke-width="6" stroke-dasharray="6 3" stroke-linecap="round" fill="none"/>'
            '<path d="M 70 119 Q 72 95 80 103" stroke="url(#bone3DKo)" stroke-width="4" stroke-linecap="round" fill="none"/>'
            '<path d="M 79 117 Q 81 92 89 101" stroke="url(#bone3DKo)" stroke-width="4" stroke-linecap="round" fill="none"/>'
            '<path d="M 88 116 Q 90 93 98 102" stroke="url(#bone3DKo)" stroke-width="4" stroke-linecap="round" fill="none"/>'
            '<path d="M 97 117 Q 99 95 106 104" stroke="url(#bone3DKo)" stroke-width="3.8" stroke-linecap="round" fill="none"/>'
            '<path d="M 106 119 Q 108 99 114 107" stroke="url(#bone3DKo)" stroke-width="3.5" stroke-linecap="round" fill="none"/>'
            '<line x1="70" y1="122" x2="80" y2="137" stroke="url(#bone3DKo)" stroke-width="4.5" stroke-linecap="round"/>'
            '<line x1="80" y1="137" x2="64" y2="139" stroke="url(#bone3DKo)" stroke-width="3.8" stroke-linecap="round"/>'
            '<g transform="translate(44, 114) rotate(-16)">'
            '<ellipse cx="10" cy="4" rx="16" ry="13" fill="url(#bone3DKo)"/>'
            '<ellipse cx="2" cy="12" rx="11" ry="6" fill="#D6D3D1"/>'
            '<circle cx="5" cy="2" r="4.5" fill="#1C1917"/>'
            '<circle cx="16" cy="2" r="4.2" fill="#1C1917"/>'
            '<polygon points="9,6 6,12 13,12" fill="#1C1917"/>'
            '<line x1="3" y1="14" x2="14" y2="14" stroke="#78716C" stroke-width="1.5" stroke-dasharray="2 2"/>'
            '</g>'
            '</g>'
            '<g class="jardin-fly-2" transform="translate(52, 82)">'
            '<ellipse cx="-2.5" cy="-2.5" rx="3.2" ry="1.8" fill="#E0F2FE" opacity="0.85" transform="rotate(-25)"/>'
            '<ellipse cx="2.5" cy="-2.5" rx="3.2" ry="1.8" fill="#E0F2FE" opacity="0.85" transform="rotate(25)"/>'
            '<ellipse cx="0" cy="0" rx="3.2" ry="2.2" fill="#111827"/>'
            '</g>'
            '<g class="jardin-fly-1" transform="translate(96, 78)">'
            '<ellipse cx="-2.2" cy="-2.2" rx="2.8" ry="1.6" fill="#E0F2FE" opacity="0.85" transform="rotate(-25)"/>'
            '<ellipse cx="2.2" cy="-2.2" rx="2.8" ry="1.6" fill="#E0F2FE" opacity="0.85" transform="rotate(25)"/>'
            '<ellipse cx="0" cy="0" rx="2.8" ry="1.9" fill="#111827"/>'
            '</g>'
            '<g class="jardin-fly-3" transform="translate(124, 90)">'
            '<ellipse cx="-2.2" cy="-2.2" rx="2.8" ry="1.6" fill="#E0F2FE" opacity="0.85" transform="rotate(-25)"/>'
            '<ellipse cx="2.2" cy="-2.2" rx="2.8" ry="1.6" fill="#E0F2FE" opacity="0.85" transform="rotate(25)"/>'
            '<ellipse cx="0" cy="0" rx="2.8" ry="1.9" fill="#111827"/>'
            '</g>'
            '</svg>'
        )

    fat_scale_x = 0.74 + 0.32 * score
    posture_drop = (1.0 - score) * 12.0
    ear_droop = (1.0 - score) * 22.0
    ribs_opacity = max(0.0, min(0.75, (0.35 - score) / 0.35)) if score < 0.35 else 0.0
    euca_leaf_op = max(0.0, min(1.0, (score - 0.15) / 0.5))
    leaf_col = _multi_color([(0.0, "#A16207"), (0.5, "#EAB308"), (1.0, "#22C55E")], score)

    if score >= 0.65:
        anim_cls = "jardin-koala-happy"
        mouth_d = "M 72 78 Q 80 86 88 78"
        eyes_svg = (
            '<circle cx="68" cy="62" r="4.2" fill="#1F2937"/>'
            '<circle cx="69.4" cy="60.6" r="1.4" fill="#FFFFFF"/>'
            '<circle cx="92" cy="62" r="4.2" fill="#1F2937"/>'
            '<circle cx="93.4" cy="60.6" r="1.4" fill="#FFFFFF"/>'
            '<ellipse cx="61" cy="70" rx="5" ry="2.8" fill="#F472B6" opacity="0.55"/>'
            '<ellipse cx="99" cy="70" rx="5" ry="2.8" fill="#F472B6" opacity="0.55"/>'
        )
    else:
        anim_cls = "jardin-animal-tired"
        mouth_d = "M 72 84 Q 80 77 88 84"
        eyes_svg = (
            '<circle cx="68" cy="64" r="3.6" fill="#1F2937"/>'
            '<path d="M 62 58 L 73 61" stroke="#1F2937" stroke-width="2.1" stroke-linecap="round"/>'
            '<circle cx="92" cy="64" r="3.6" fill="#1F2937"/>'
            '<path d="M 87 61 L 98 58" stroke="#1F2937" stroke-width="2.1" stroke-linecap="round"/>'
            '<path d="M 56 70 Q 54 77 56 80 Q 58 77 56 70 Z" fill="#38BDF8" opacity="0.85"/>'
        )

    return (
        '<svg class="jardin-char-svg" viewBox="0 0 160 220" style="overflow: visible;" xmlns="http://www.w3.org/2000/svg">'
        '<defs>'
        '<radialGradient id="koalaFur3D" cx="35%" cy="30%" r="70%">'
        '<stop offset="0%" stop-color="#9CA3AF"/>'
        '<stop offset="60%" stop-color="#6B7280"/>'
        '<stop offset="100%" stop-color="#374151"/>'
        '</radialGradient>'
        '<linearGradient id="koalaBelly3D" x1="0%" y1="0%" x2="0%" y2="100%">'
        '<stop offset="0%" stop-color="#F3F4F6"/>'
        '<stop offset="100%" stop-color="#D1D5DB"/>'
        '</linearGradient>'
        '<linearGradient id="koalaTrunk3D" x1="0%" y1="0%" x2="100%" y2="0%">'
        '<stop offset="0%" stop-color="#78350F"/>'
        '<stop offset="50%" stop-color="#92400E"/>'
        '<stop offset="100%" stop-color="#451A03"/>'
        '</linearGradient>'
        '<filter id="koalaShadow3D" x="-20%" y="-20%" width="140%" height="140%">'
        '<feDropShadow dx="0" dy="4" stdDeviation="3" flood-color="#000000" flood-opacity="0.25"/>'
        '</filter>'
        '</defs>'
        '<ellipse cx="80" cy="204" rx="40" ry="9" fill="#000000" opacity="0.22"/>'
        '<path d="M 114 206 L 122 55 L 136 55 L 130 206 Z" fill="url(#koalaTrunk3D)" filter="url(#koalaShadow3D)"/>'
        '<path d="M 122 98 Q 96 82 68 88" stroke="#78350F" stroke-width="7" stroke-linecap="round" fill="none"/>'
        f'<g class="{anim_cls}" transform="translate(0, {posture_drop:.1f})" filter="url(#koalaShadow3D)">'
        f'<g transform="translate(80, 134) scale({fat_scale_x:.2f}, 1)">'
        '<ellipse cx="0" cy="0" rx="34" ry="42" fill="url(#koalaFur3D)"/>'
        '<ellipse cx="-2" cy="5" rx="22" ry="30" fill="url(#koalaBelly3D)"/>'
        '</g>'
        f'<g opacity="{ribs_opacity:.2f}" stroke="#F3F4F6" stroke-width="2.2" stroke-linecap="round" fill="none">'
        '<path d="M 66 116 Q 80 112 94 116"/>'
        '<path d="M 64 127 Q 80 123 96 127"/>'
        '<path d="M 66 138 Q 80 134 94 138"/>'
        '</g>'
        '<ellipse cx="56" cy="170" rx="13" ry="16" fill="url(#koalaFur3D)"/>'
        '<ellipse cx="102" cy="170" rx="13" ry="16" fill="url(#koalaFur3D)"/>'
        '<ellipse cx="52" cy="110" rx="12" ry="10" fill="url(#koalaFur3D)"/>'
        '<ellipse cx="108" cy="110" rx="12" ry="10" fill="url(#koalaFur3D)"/>'
        f'<circle cx="48" cy="{48 + int(ear_droop * 0.35)}" r="16" fill="url(#koalaFur3D)"/>'
        f'<circle cx="48" cy="{48 + int(ear_droop * 0.35)}" r="9" fill="#E5E7EB"/>'
        f'<circle cx="112" cy="{48 + int(ear_droop * 0.35)}" r="16" fill="url(#koalaFur3D)"/>'
        f'<circle cx="112" cy="{48 + int(ear_droop * 0.35)}" r="9" fill="#E5E7EB"/>'
        '<ellipse cx="80" cy="66" rx="29" ry="25" fill="url(#koalaFur3D)"/>'
        '<ellipse cx="80" cy="68" rx="8" ry="11.5" fill="#1F2937"/>'
        '<ellipse cx="77.5" cy="64.5" rx="2.6" ry="4" fill="#4B5563"/>'
        + eyes_svg +
        f'<path d="{mouth_d}" stroke="#1F2937" stroke-width="2.2" fill="none" stroke-linecap="round"/>'
        f'<g opacity="{euca_leaf_op:.2f}" transform="translate(44, 102)">'
        f'<ellipse cx="0" cy="0" rx="10" ry="5.5" fill="{leaf_col}" transform="rotate(-25)"/>'
        '</g>'
        '</g>'
        '</svg>'
    )


def construir_html_panel_patrimonio(
    total_patrimonio_ars,
    total_patrimonio_usd,
    cant_activos_contemplados,
    cant_activos_totales,
    ingreso_mensual_ars,
    costo_mensual_ars,
    dolar_b,
    hay_moneda_extranjera=False,
    datos_faltantes=False
):
    tasa_invalida = hay_moneda_extranjera and (dolar_b is None or float(dolar_b) <= 0)
    es_crecimiento = False

    if tasa_invalida:
        score = 0.5
        mensaje_salud = (
            "⚠️ Warning: Assets or costs in another currency were detected, "
            "but no exchange rate is available to convert to ARS."
        )
    elif datos_faltantes or (ingreso_mensual_ars <= 0 and costo_mensual_ars <= 0):
        score = 0.5
        mensaje_salud = "Add your income and costs to see your financial health"
    else:
        monthly_saving = float(ingreso_mensual_ars) - float(costo_mensual_ars)

        if abs(monthly_saving) < 0.005:
            score = 1.0
            mensaje_salud = "We're doing well financially: your monthly savings are zero and your net worth stays intact."
        elif monthly_saving > 0:
            score = 1.0
            es_crecimiento = True
            mensaje_salud = (
                f"We're doing great financially: you save {monthly_saving:,.0f} ARS/month and your net worth is growing."
            )
        else:
            perdida_mensual = abs(monthly_saving)
            if total_patrimonio_ars <= 0:
                score = 0.0
                mensaje_salud = "Finances on fire! At this rate you have 0 months of runway left."
            else:
                months_left = float(total_patrimonio_ars) / float(perdida_mensual)
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
                    mensaje_salud = f"Finances on fire! At this rate you have {tiempo_str} of runway left."
                else:
                    mensaje_salud = (
                        f"Your monthly savings are negative (−{perdida_mensual:,.0f} ARS): "
                        f"at this rate your net worth lasts {tiempo_str}."
                    )

    sky_top = "#0EA5E9" if es_crecimiento else _multi_color([
        (0.0, "#7F1D1D"),
        (0.25, "#C2410C"),
        (0.55, "#F59E0B"),
        (0.80, "#7DD3FC"),
        (1.0, "#38BDF8")
    ], score)
    sky_mid = "#A5F3FC" if es_crecimiento else _multi_color([
        (0.0, "#DC2626"),
        (0.25, "#EA580C"),
        (0.55, "#FDE68A"),
        (0.80, "#BAE6FD"),
        (1.0, "#CCFBF1")
    ], score)
    sky_bot = "#A7F3D0" if es_crecimiento else _multi_color([
        (0.0, "#F97316"),
        (0.25, "#FDBA74"),
        (0.55, "#FEF3C7"),
        (0.80, "#DCFCE7"),
        (1.0, "#BBF7D0")
    ], score)

    hill_back = _multi_color([
        (0.0, "#9A3412"),
        (0.30, "#B45309"),
        (0.60, "#A16207"),
        (0.85, "#4ADE80"),
        (1.0, "#10B981" if es_crecimiento else "#22C55E")
    ], score)
    hill_mid = _multi_color([
        (0.0, "#B45309"),
        (0.30, "#D97706"),
        (0.60, "#CA8A04"),
        (0.85, "#22C55E"),
        (1.0, "#059669" if es_crecimiento else "#16A34A")
    ], score)
    ground_front = _multi_color([
        (0.0, "#78350F"),
        (0.30, "#92400E"),
        (0.60, "#854D0E"),
        (0.85, "#15803D"),
        (1.0, "#047857" if es_crecimiento else "#166534")
    ], score)

    leaf_main = _multi_color([
        (0.0, "#78350F"),
        (0.25, "#A16207"),
        (0.55, "#EAB308"),
        (0.80, "#4ADE80"),
        (1.0, "#10B981" if es_crecimiento else "#16A34A")
    ], score)
    leaf_light = _multi_color([
        (0.0, "#92400E"),
        (0.25, "#CA8A04"),
        (0.55, "#FDE047"),
        (0.80, "#86EFAC"),
        (1.0, "#6EE7B7" if es_crecimiento else "#4ADE80")
    ], score)
    leaf_dark = _multi_color([
        (0.0, "#451A03"),
        (0.25, "#713F12"),
        (0.55, "#A16207"),
        (0.80, "#15803D"),
        (1.0, "#065F46" if es_crecimiento else "#14532D")
    ], score)

    border_col = _multi_color([
        (0.0, "#EF4444"),
        (0.35, "#F59E0B"),
        (0.70, "#84CC16"),
        (1.0, "#10B981" if es_crecimiento else "#22C55E")
    ], score)

    fire_opacity = max(0.0, min(1.0, ((1.0 - score) ** 1.35)))
    sun_radius = 16.0 + (1.0 - score) * 10.0
    sun_core_col = _multi_color([(0.0, "#FEF08A"), (0.4, "#FDE047"), (1.0, "#FEF9C3")], score)
    sun_outer_col = _multi_color([(0.0, "#DC2626"), (0.4, "#F97316"), (1.0, "#FBBF24")], score)
    tumbleweed_opacity = max(0.0, min(1.0, (0.38 - score) / 0.38)) if score < 0.38 else 0.0
    cracks_opacity = max(0.0, min(1.0, (0.45 - score) / 0.45)) if score < 0.45 else 0.0
    clouds_opacity = max(0.0, min(0.92, (score - 0.15) / 0.85))
    flowers_opacity = max(0.0, min(1.0, (score - 0.55) / 0.45))
    fruits_opacity = 1.0 if es_crecimiento else 0.0
    droop_deg = (1.0 - score) * 34.0

    def _plant_style(threshold):
        if score <= 0.02 or score <= threshold:
            return 0.0, 0.0
        sc = max(0.15, min(1.0, (score - threshold) / (1.0 - threshold)))
        op = max(0.0, min(1.0, (score - threshold) / max(0.18, 1.0 - threshold)))
        mult_s = 0.68 if es_crecimiento else 0.62
        return sc * mult_s, op

    t1_s, t1_o = _plant_style(0.04)
    t2_s, t2_o = _plant_style(0.18)
    t3_s, t3_o = _plant_style(0.35)
    t4_s, t4_o = _plant_style(0.52)
    t5_s, t5_o = _plant_style(0.68)

    pct_salud = int(round(score * 100))
    badge_bg = _multi_color([
        (0.0, "#FEE2E2"),
        (0.35, "#FEF3C7"),
        (0.75, "#DCFCE7"),
        (1.0, "#D1FAE5")
    ], score)
    badge_text = _multi_color([
        (0.0, "#991B1B"),
        (0.35, "#92400E"),
        (0.75, "#166534"),
        (1.0, "#065F46")
    ], score)

    svg_canguro = _construir_svg_canguro(score)
    svg_koala = _construir_svg_koala(score)

    frutas_arbol_grande = (
        f'<g opacity="{fruits_opacity:.2f}">'
        '<circle cx="-14" cy="-86" r="5.2" fill="#EF4444"/><circle cx="-15" cy="-87.5" r="1.5" fill="#FCA5A5"/>'
        '<circle cx="15" cy="-84" r="5.2" fill="#F97316"/><circle cx="13.5" cy="-85.5" r="1.5" fill="#FDBA74"/>'
        '<circle cx="0" cy="-66" r="5.2" fill="#EF4444"/><circle cx="-1.5" cy="-67.5" r="1.5" fill="#FCA5A5"/>'
        '<circle cx="-8" cy="-102" r="4.5" fill="#F43F5E"/>'
        '<circle cx="10" cy="-100" r="4.8" fill="#FB923C"/>'
        '<circle cx="-22" cy="-68" r="4.2" fill="#FDE047"/>'
        '<circle cx="22" cy="-68" r="4.2" fill="#F472B6"/>'
        '</g>'
    )
    frutas_arbol_mediano = (
        f'<g opacity="{fruits_opacity:.2f}">'
        '<circle cx="-10" cy="-66" r="4.8" fill="#EF4444"/>'
        '<circle cx="11" cy="-64" r="4.8" fill="#F97316"/>'
        '<circle cx="0" cy="-52" r="4.5" fill="#F43F5E"/>'
        '<circle cx="-14" cy="-52" r="3.8" fill="#FDE047"/>'
        '<circle cx="14" cy="-52" r="3.8" fill="#F472B6"/>'
        '</g>'
    )

    lineas_html = [
        f'<div class="jardin-health-scene" style="border-color: {border_col};">',
        f'<div class="jardin-info-panel" style="border-right-color: {border_col};">',
        '<div class="kpi-title" style="font-size: 1.05rem; color: #1F2937; margin-bottom: 1px;">Total Net Worth</div>',
        f'<div class="kpi-value" style="font-size: 1.72rem; color: #111827; line-height: 1.12;">{total_patrimonio_ars:,.0f} ARS</div>',
        f'<div class="kpi-usd" style="font-size: 0.96rem; color: #1F2937; background: rgba(255,255,255,0.92); margin-top: 3px; padding: 2px 9px;">{total_patrimonio_usd:,.2f} USD</div>',
        f'<div class="jardin-status-box" style="background: {badge_bg}; color: {badge_text}; border-color: {border_col};">',
        f'<div style="font-size: 0.84rem; font-weight: 800; line-height: 1.25;">{mensaje_salud}</div>',
        '<div class="jardin-health-bar-track">',
        f'<div class="jardin-health-bar-fill" style="width: {pct_salud}%; background: {border_col};"></div>',
        '</div>',
        '</div>',
        f'<div class="kpi-sub" style="color: #374151; font-weight: 700; font-size: 0.82rem; margin-top: 5px; margin-bottom: 0;">{cant_activos_contemplados} of {cant_activos_totales} assets included</div>',
        '</div>',
        '<div class="jardin-scene-panel">',
        '<svg class="jardin-scene-svg" viewBox="0 0 900 160" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">',
        '<defs>',
        '<linearGradient id="skyGrad" x1="0%" y1="0%" x2="0%" y2="100%">',
        f'<stop offset="0%" stop-color="{sky_top}"/>',
        f'<stop offset="55%" stop-color="{sky_mid}"/>',
        f'<stop offset="100%" stop-color="{sky_bot}"/>',
        '</linearGradient>',
        '<radialGradient id="sunGrad" cx="50%" cy="50%" r="50%">',
        f'<stop offset="0%" stop-color="{sun_core_col}"/>',
        f'<stop offset="65%" stop-color="{sun_outer_col}"/>',
        f'<stop offset="100%" stop-color="{sun_outer_col}" stop-opacity="0"/>',
        '</radialGradient>',
        '<linearGradient id="hillBackGrad" x1="0%" y1="0%" x2="0%" y2="100%">',
        f'<stop offset="0%" stop-color="{hill_back}"/>',
        f'<stop offset="100%" stop-color="{ground_front}"/>',
        '</linearGradient>',
        '<linearGradient id="hillMidGrad" x1="0%" y1="0%" x2="0%" y2="100%">',
        f'<stop offset="0%" stop-color="{hill_mid}"/>',
        f'<stop offset="100%" stop-color="{ground_front}"/>',
        '</linearGradient>',
        '<linearGradient id="foliage3D" x1="20%" y1="0%" x2="80%" y2="100%">',
        f'<stop offset="0%" stop-color="{leaf_light}"/>',
        f'<stop offset="55%" stop-color="{leaf_main}"/>',
        f'<stop offset="100%" stop-color="{leaf_dark}"/>',
        '</linearGradient>',
        '<linearGradient id="trunk3D" x1="0%" y1="0%" x2="100%" y2="0%">',
        '<stop offset="0%" stop-color="#78350F"/>',
        '<stop offset="45%" stop-color="#92400E"/>',
        '<stop offset="100%" stop-color="#451A03"/>',
        '</linearGradient>',
        '<filter id="softShadow3D" x="-20%" y="-20%" width="140%" height="140%">',
        '<feDropShadow dx="0" dy="3" stdDeviation="2.5" flood-color="#000000" flood-opacity="0.24"/>',
        '</filter>',
        '</defs>',
        '<rect x="0" y="0" width="900" height="160" fill="url(#skyGrad)"/>',
        f'<g class="jardin-sun-group" transform="translate(450, {34 + int((1.0 - score) * 10)})">',
        f'<circle cx="0" cy="0" r="{sun_radius * 2.1:.1f}" fill="url(#sunGrad)" opacity="{0.45 + 0.45 * fire_opacity:.2f}"/>',
        f'<g class="jardin-sun-flames" opacity="{fire_opacity:.2f}">',
        f'<polygon points="0,-{sun_radius*1.65:.1f} 8,-{sun_radius*0.85:.1f} -8,-{sun_radius*0.85:.1f}" fill="#EF4444"/>',
        f'<polygon points="0,{sun_radius*1.65:.1f} 8,{sun_radius*0.85:.1f} -8,{sun_radius*0.85:.1f}" fill="#EF4444"/>',
        f'<polygon points="-{sun_radius*1.65:.1f},0 -{sun_radius*0.85:.1f},8 -{sun_radius*0.85:.1f},-8" fill="#F97316"/>',
        f'<polygon points="{sun_radius*1.65:.1f},0 {sun_radius*0.85:.1f},8 {sun_radius*0.85:.1f},-8" fill="#F97316"/>',
        f'<polygon points="-{sun_radius*1.2:.1f},-{sun_radius*1.2:.1f} -{sun_radius*0.5:.1f},-{sun_radius*0.9:.1f} -{sun_radius*0.9:.1f},-{sun_radius*0.5:.1f}" fill="#DC2626"/>',
        f'<polygon points="{sun_radius*1.2:.1f},-{sun_radius*1.2:.1f} {sun_radius*0.5:.1f},-{sun_radius*0.9:.1f} {sun_radius*0.9:.1f},-{sun_radius*0.5:.1f}" fill="#DC2626"/>',
        f'<polygon points="-{sun_radius*1.2:.1f},{sun_radius*1.2:.1f} -{sun_radius*0.5:.1f},{sun_radius*0.9:.1f} -{sun_radius*0.9:.1f},{sun_radius*0.5:.1f}" fill="#F59E0B"/>',
        f'<polygon points="{sun_radius*1.2:.1f},{sun_radius*1.2:.1f} {sun_radius*0.5:.1f},{sun_radius*0.9:.1f} {sun_radius*0.9:.1f},{sun_radius*0.5:.1f}" fill="#F59E0B"/>',
        '</g>',
        f'<circle cx="0" cy="0" r="{sun_radius:.1f}" fill="{sun_core_col}" filter="url(#softShadow3D)"/>',
        '</g>',
        f'<g class="jardin-clouds" opacity="{clouds_opacity:.2f}" fill="#FFFFFF">',
        '<g transform="translate(230, 26) scale(0.75)" opacity="0.82">',
        '<ellipse cx="0" cy="0" rx="34" ry="14"/><ellipse cx="-20" cy="4" rx="20" ry="11"/><ellipse cx="22" cy="4" rx="22" ry="10"/>',
        '</g>',
        '<g transform="translate(670, 24) scale(0.75)" opacity="0.78">',
        '<ellipse cx="0" cy="0" rx="36" ry="15"/><ellipse cx="-22" cy="5" rx="22" ry="11"/><ellipse cx="22" cy="5" rx="20" ry="10"/>',
        '</g>',
        '</g>',
        '<path d="M 0 118 Q 180 86 360 110 T 660 104 T 900 116 L 900 160 L 0 160 Z" fill="url(#hillBackGrad)" opacity="0.88"/>',
        '<path d="M 0 128 Q 220 102 450 124 T 900 122 L 900 160 L 0 160 Z" fill="url(#hillMidGrad)" opacity="0.95"/>',
        f'<path d="M 0 138 Q 270 126 540 139 T 900 136 L 900 160 L 0 160 Z" fill="{ground_front}"/>',
        f'<g stroke="#451A03" stroke-width="1.5" fill="none" opacity="{cracks_opacity:.2f}">',
        '<path d="M 220 143 L 238 149 L 228 156 M 238 149 L 256 152"/>',
        '<path d="M 430 146 L 452 151 L 442 158 M 452 151 L 474 149"/>',
        '<path d="M 640 143 L 660 150 L 650 157 M 660 150 L 682 153"/>',
        '</g>',
        f'<g class="jardin-sway-tree" opacity="{t1_o:.2f}" transform="translate(215, 132) scale({t1_s:.2f}) rotate({droop_deg * 0.45:.1f})" filter="url(#softShadow3D)">',
        '<path d="M -7 0 L -4 -68 L 4 -68 L 7 0 Z" fill="url(#trunk3D)"/>',
        '<circle cx="0" cy="-82" r="34" fill="url(#foliage3D)"/>',
        '<circle cx="-22" cy="-68" r="25" fill="url(#foliage3D)"/>',
        '<circle cx="22" cy="-68" r="25" fill="url(#foliage3D)"/>',
        '<circle cx="0" cy="-104" r="24" fill="url(#foliage3D)"/>',
        frutas_arbol_grande,
        '</g>',
        f'<g class="jardin-sway-tree-alt" opacity="{t2_o:.2f}" transform="translate(295, 136) scale({t2_s:.2f}) rotate({droop_deg * 0.6:.1f})" filter="url(#softShadow3D)">',
        '<path d="M -5 0 L -3 -52 L 3 -52 L 5 0 Z" fill="url(#trunk3D)"/>',
        '<ellipse cx="0" cy="-64" rx="28" ry="24" fill="url(#foliage3D)"/>',
        '<circle cx="-16" cy="-54" r="18" fill="url(#foliage3D)"/>',
        '<circle cx="16" cy="-54" r="18" fill="url(#foliage3D)"/>',
        frutas_arbol_mediano,
        '</g>',
        f'<g class="jardin-sway-tree" opacity="{t3_o:.2f}" transform="translate(385, 134) scale({t3_s:.2f}) rotate({droop_deg * 0.5:.1f})" filter="url(#softShadow3D)">',
        '<path d="M -6 0 L -3 -58 L 3 -58 L 6 0 Z" fill="url(#trunk3D)"/>',
        '<circle cx="0" cy="-72" r="30" fill="url(#foliage3D)"/>',
        '<circle cx="-18" cy="-58" r="22" fill="url(#foliage3D)"/>',
        '<circle cx="18" cy="-58" r="22" fill="url(#foliage3D)"/>',
        frutas_arbol_mediano,
        '</g>',
        f'<g class="jardin-sway-tree-alt" opacity="{t3_o:.2f}" transform="translate(535, 134) scale({t3_s:.2f}) rotate(-{droop_deg * 0.55:.1f})" filter="url(#softShadow3D)">',
        '<path d="M -6 0 L -3 -58 L 3 -58 L 6 0 Z" fill="url(#trunk3D)"/>',
        '<circle cx="0" cy="-72" r="30" fill="url(#foliage3D)"/>',
        '<circle cx="-18" cy="-58" r="22" fill="url(#foliage3D)"/>',
        '<circle cx="18" cy="-58" r="22" fill="url(#foliage3D)"/>',
        frutas_arbol_mediano,
        '</g>',
        f'<g class="jardin-sway-tree" opacity="{t2_o:.2f}" transform="translate(650, 136) scale({t2_s:.2f}) rotate(-{droop_deg * 0.6:.1f})" filter="url(#softShadow3D)">',
        '<path d="M -5 0 L -3 -52 L 3 -52 L 5 0 Z" fill="url(#trunk3D)"/>',
        '<ellipse cx="0" cy="-64" rx="28" ry="24" fill="url(#foliage3D)"/>',
        '<circle cx="-16" cy="-54" r="18" fill="url(#foliage3D)"/>',
        '<circle cx="16" cy="-54" r="18" fill="url(#foliage3D)"/>',
        frutas_arbol_mediano,
        '</g>',
        f'<g class="jardin-sway-tree-alt" opacity="{t1_o:.2f}" transform="translate(765, 132) scale({t1_s:.2f}) rotate(-{droop_deg * 0.4:.1f})" filter="url(#softShadow3D)">',
        '<path d="M -7 0 L -4 -70 L 4 -70 L 7 0 Z" fill="url(#trunk3D)"/>',
        '<circle cx="0" cy="-86" r="35" fill="url(#foliage3D)"/>',
        '<circle cx="-24" cy="-70" r="25" fill="url(#foliage3D)"/>',
        '<circle cx="24" cy="-70" r="25" fill="url(#foliage3D)"/>',
        '<circle cx="0" cy="-108" r="24" fill="url(#foliage3D)"/>',
        frutas_arbol_grande,
        '</g>',
        f'<g class="jardin-sway-bush" opacity="{t4_o:.2f}" transform="translate(340, 140) scale({t4_s:.2f}) rotate({droop_deg * 0.7:.1f})">',
        '<ellipse cx="0" cy="-14" rx="22" ry="15" fill="url(#foliage3D)"/>',
        '<ellipse cx="-14" cy="-10" rx="16" ry="12" fill="url(#foliage3D)"/>',
        '<ellipse cx="14" cy="-10" rx="16" ry="12" fill="url(#foliage3D)"/>',
        '</g>',
        f'<g class="jardin-sway-bush" opacity="{t4_o:.2f}" transform="translate(460, 141) scale({t5_s:.2f}) rotate({droop_deg * 0.5:.1f})">',
        '<ellipse cx="0" cy="-16" rx="25" ry="16" fill="url(#foliage3D)"/>',
        '<ellipse cx="-15" cy="-11" rx="17" ry="12" fill="url(#foliage3D)"/>',
        '<ellipse cx="15" cy="-11" rx="17" ry="12" fill="url(#foliage3D)"/>',
        '</g>',
        f'<g class="jardin-sway-bush" opacity="{t4_o:.2f}" transform="translate(595, 140) scale({t4_s:.2f}) rotate(-{droop_deg * 0.7:.1f})">',
        '<ellipse cx="0" cy="-14" rx="22" ry="15" fill="url(#foliage3D)"/>',
        '<ellipse cx="-14" cy="-10" rx="16" ry="12" fill="url(#foliage3D)"/>',
        '<ellipse cx="14" cy="-10" rx="16" ry="12" fill="url(#foliage3D)"/>',
        '</g>',
        f'<g opacity="{flowers_opacity:.2f}">',
        '<circle cx="245" cy="144" r="3.8" fill="#F472B6"/><circle cx="245" cy="144" r="1.6" fill="#FEF08A"/>',
        '<circle cx="315" cy="147" r="3.8" fill="#A78BFA"/><circle cx="315" cy="147" r="1.6" fill="#FEF08A"/>',
        '<circle cx="405" cy="145" r="3.5" fill="#FB7185"/><circle cx="405" cy="145" r="1.5" fill="#FEF08A"/>',
        '<circle cx="515" cy="146" r="3.8" fill="#F472B6"/><circle cx="515" cy="146" r="1.6" fill="#FEF08A"/>',
        '<circle cx="620" cy="144" r="3.8" fill="#A78BFA"/><circle cx="620" cy="144" r="1.6" fill="#FEF08A"/>',
        '<circle cx="710" cy="147" r="3.5" fill="#FBBF24"/><circle cx="710" cy="147" r="1.5" fill="#FFFFFF"/>',
        '<circle cx="820" cy="145" r="3.8" fill="#FB7185"/><circle cx="820" cy="145" r="1.6" fill="#FEF08A"/>',
        '</g>',
        f'<g opacity="{tumbleweed_opacity:.2f}">',
        '<g class="jardin-tumbleweed-1">',
        '<circle cx="0" cy="0" r="12" fill="none" stroke="#78350F" stroke-width="1.8" stroke-dasharray="5 3"/>',
        '<ellipse cx="0" cy="0" rx="12" ry="7" fill="none" stroke="#92400E" stroke-width="1.4" transform="rotate(35)"/>',
        '<ellipse cx="0" cy="0" rx="12" ry="7" fill="none" stroke="#78350F" stroke-width="1.4" transform="rotate(-35)"/>',
        '<path d="M -8 -4 L 8 4 M -7 5 L 7 -5" stroke="#92400E" stroke-width="1.2"/>',
        '</g>',
        '<g class="jardin-tumbleweed-2">',
        '<circle cx="0" cy="0" r="10" fill="none" stroke="#78350F" stroke-width="1.6" stroke-dasharray="4 2.5"/>',
        '<ellipse cx="0" cy="0" rx="10" ry="6" fill="none" stroke="#92400E" stroke-width="1.3" transform="rotate(50)"/>',
        '<ellipse cx="0" cy="0" rx="10" ry="6" fill="none" stroke="#78350F" stroke-width="1.3" transform="rotate(-40)"/>',
        '</g>',
        '</g>',
        '</svg>',
        f'<div class="jardin-char-wrap jardin-char-left">{svg_canguro}</div>',
        f'<div class="jardin-char-wrap jardin-char-right">{svg_koala}</div>',
        '</div>',
        '</div>'
    ]
    return "\n".join(lineas_html)


# ----------------- 2D PIE CHART WITH 1 DECIMAL & NO POPUPS -----------------
def formatear_etiqueta_torta(texto, usar_minusculas=False):
    t = str(texto or "").strip()
    if not t:
        return t
    if usar_minusculas:
        return t[0].upper() + t[1:].lower()
    return t


def crear_torta_2d(df, col_valores, col_nombres, tamano="mediano", usar_minusculas=False):
    valores = df[col_valores].tolist()
    nombres = [formatear_etiqueta_torta(nom, usar_minusculas=usar_minusculas) for nom in df[col_nombres].tolist()]
    total = sum(valores) if sum(valores) > 0 else 1.0
    n = len(valores)

    colores = [PALETA_PASTEL[i % len(PALETA_PASTEL)] for i in range(n)]

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
        textfont=dict(
            size=tam_fuente,
            color="#1F2937",
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


# ----------------- CLEAN HORIZONTAL BAR CHART -----------------
def crear_barras_horizontales(df, col_valores, col_nombres):
    df_ord = df.sort_values(by=col_valores, ascending=True).copy()
    valores = df_ord[col_valores].tolist()
    nombres = df_ord[col_nombres].tolist()
    total = sum(valores) if sum(valores) > 0 else 1.0
    max_val = max(valores) if valores else 1.0
    n = len(valores)

    colores = []
    for idx_b, v in enumerate(valores):
        ratio = (idx_b + 1) / max(n, 1)
        if ratio > 0.66:
            colores.append("#F5B7B1")
        elif ratio > 0.33:
            colores.append("#F9E79F")
        else:
            colores.append("#ABEBC6")

    textos = [f"  {v:,.0f} ARS ({(v / total) * 100:.1f}%)" for v in valores]

    fig = go.Figure(data=[go.Bar(
        x=valores,
        y=nombres,
        orientation="h",
        text=textos,
        textposition="outside",
        cliponaxis=False,
        textfont=dict(
            size=14,
            color="#1F2937",
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
                color="#1F2937",
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
    "Binance", "Nexo", "IOL", "CommBank",
    "Up Bank", "Macquarie", "Mercado Pago", "Uala"
]


def reparar_inversiones_corruptas(inversiones):
    """Repairs rows whose detail is ARS or USD cash but got saved under another category."""
    modificado = False
    for inv in (inversiones or []):
        inv.setdefault("activo_inv", True)
        tipo_norm = normalizar_tipo_activo_inv(inv.get("tipo", "Others"))
        det_str = str(inv.get("activo", "")).strip()
        det_up = det_str.upper()
        sim_up = str(inv.get("simbolo", "")).strip().upper()

        if det_up in ["PESOS ARS", "PESOS", "A - PESOS ARS", "B - PESOS ARS", "EFECTIVO / BANCO", "ARS CASH"] or (
            sim_up == "ARS" and tipo_norm in ["Stocks", "Cryptos", "Bonds"]
        ):
            if inv.get("tipo") != "Pesos ARS" or inv.get("activo") != "Pesos ARS" or inv.get("simbolo") != "ARS":
                inv["tipo"] = "Pesos ARS"
                inv["activo"] = "Pesos ARS"
                inv["simbolo"] = "ARS"
                modificado = True
        elif det_up in ["DÓLARES USD", "DOLARES USD", "DÓLAR BILLETE", "DOLAR BILLETE", "A - DÓLAR BILLETE", "B - DÓLARES USD", "USD CASH"] or (
            sim_up == "USD" and tipo_norm in ["Stocks", "Cryptos", "Bonds"]
        ):
            if inv.get("tipo") != "Dólares USD" or inv.get("activo") != "Dólares USD" or inv.get("simbolo") != "USD":
                inv["tipo"] = "Dólares USD"
                inv["activo"] = "Dólares USD"
                inv["simbolo"] = "USD"
                modificado = True
        else:
            if inv.get("tipo") != tipo_norm:
                inv["tipo"] = tipo_norm
                modificado = True
            if tipo_norm in ["Cryptos", "Stocks", "Bonds"]:
                det_ticker = det_str.split(" ")[0].upper()
                if det_ticker and det_ticker not in ["USD", "ARS"] and inv.get("simbolo") != det_ticker:
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


def normalizar_tipo_activo_inv(tipo_raw):
    t = str(tipo_raw or "").strip()
    if t in ["A - Pesos ARS", "B - Pesos ARS", "Pesos ARS", "Efectivo / Banco"]:
        return "Pesos ARS"
    if t in ["B - Dólares USD", "Dólares USD", "Dólar Billete", "A - Dólar Billete"]:
        return "Dólares USD"
    if t in ["C - Stocks", "C - Acciones", "Stocks", "Acciones", "Acciones / CEDEARs"]:
        return "Stocks"
    if t in ["D - Cryptos", "Cryptos", "D - Criptomonedas", "Criptomonedas"]:
        return "Cryptos"
    if t in ["E - Bonds", "E - Bonos", "Bonds", "Bonos"]:
        return "Bonds"
    if t in ["F - FCI", "FCI"]:
        return "FCI"
    return "Others"


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
            "tipo": "A - Pesos ARS",
            "accion": "AAPL (Apple)",
            "cripto": "BTC (Bitcoin)",
            "bono": "AL30 (Bonar 2030 Ley Arg.)",
            "ubicacion": "Binance"
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
                "Pesos ARS": "A - Pesos ARS",
                "B - Pesos ARS": "A - Pesos ARS",
                "A - Pesos ARS": "A - Pesos ARS",
                "Dólares USD": "B - Dólares USD",
                "Dólar Billete": "B - Dólares USD",
                "A - Dólar Billete": "B - Dólares USD",
                "B - Dólares USD": "B - Dólares USD",
                "Stocks": "C - Stocks",
                "Acciones": "C - Stocks",
                "C - Acciones": "C - Stocks",
                "C - Stocks": "C - Stocks",
                "Cryptos": "D - Cryptos",
                "Criptomonedas": "D - Cryptos",
                "D - Criptomonedas": "D - Cryptos",
                "D - Cryptos": "D - Cryptos",
                "Bonds": "E - Bonds",
                "Bonos": "E - Bonds",
                "E - Bonos": "E - Bonds",
                "E - Bonds": "E - Bonds",
                "FCI": "F - FCI",
                "F - FCI": "F - FCI",
                "Others": "G - Others",
                "Otros": "G - Others",
                "E - Otros": "G - Others",
                "G - Otros": "G - Others",
                "G - Others": "G - Others"
            }
            ult_sel["tipo"] = mapa_tipo_opt.get(ult_sel.get("tipo", ""), "A - Pesos ARS")
            ult_sel.setdefault("accion", data["acciones_guardadas"][0] if data["acciones_guardadas"] else "AAPL (Apple)")
            ult_sel.setdefault("cripto", data["criptos_guardadas"][0] if data["criptos_guardadas"] else "BTC (Bitcoin)")
            ult_sel.setdefault("bono", data["bonos_guardadas"][0] if data.get("bonos_guardadas") else "AL30 (Bonar 2030 Ley Arg.)")
            ult_sel.setdefault("ubicacion", data["ubicaciones_guardadas"][0] if data["ubicaciones_guardadas"] else "Binance")
            data["ultimas_selecciones_inv"] = ult_sel

            data.setdefault("historial_cierres", [])
            return data
        except Exception:
            pass

    return datos_por_defecto


def guardar_datos(datos, registrar_cambio=True):
    if registrar_cambio:
        datos["ultima_actualizacion"] = datetime.now(TZ_SYDNEY).strftime("%Y-%m-%d")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)


def calcular_texto_ultima_actualizacion(datos, fecha_actual_sydney):
    fecha_str = str(datos.get("ultima_actualizacion", "") or "").strip()
    if not fecha_str:
        return "Last saved: Today"
    try:
        fecha_guardada = datetime.strptime(fecha_str[:10], "%Y-%m-%d").date()
        dias_diff = max(0, (fecha_actual_sydney.date() - fecha_guardada).days)
        if dias_diff == 0:
            return "Last saved: Today"
        elif dias_diff == 1:
            return "Last saved: 1 day ago"
        else:
            return f"Last saved: {dias_diff} days ago"
    except Exception:
        return "Last saved: Today"


# ----------------- EXCEL (.XLSX) EXPORT ON LOGOUT -----------------
def armar_dataframes_exportacion(datos, dolar_b, cotizaciones):
    fecha_actual = datetime.now(TZ_SYDNEY).strftime("%Y-%m-%d %H:%M")

    filas_mov = []
    for c in datos.get("costos", []):
        monto_ars = float(c.get("monto", 0))
        filas_mov.append({
            "Record Date": fecha_actual,
            "Type": "Cost",
            "Category": c.get("grupo", ""),
            "Subcategory / Item": c.get("categoria", ""),
            "Active": "Yes" if c.get("activo", True) else "No",
            "Amount (ARS)": monto_ars,
            "Amount (USD Blue)": round(monto_ars / dolar_b, 2) if dolar_b > 0 else 0.0
        })

    for i in datos.get("ingresos", []):
        monto_ars = float(i.get("monto", 0))
        filas_mov.append({
            "Record Date": fecha_actual,
            "Type": "Income",
            "Category": i.get("grupo", ""),
            "Subcategory / Item": i.get("concepto", ""),
            "Active": "Yes" if i.get("activo", True) else "No",
            "Amount (ARS)": monto_ars,
            "Amount (USD Blue)": round(monto_ars / dolar_b, 2) if dolar_b > 0 else 0.0
        })

    df_mov = pd.DataFrame(filas_mov) if filas_mov else pd.DataFrame(
        columns=["Record Date", "Type", "Category", "Subcategory / Item", "Active", "Amount (ARS)", "Amount (USD Blue)"]
    )

    filas_inv = []
    for inv in datos.get("inversiones", []):
        cant = float(inv.get("cantidad", 0))
        tipo = normalizar_tipo_activo_inv(inv.get("tipo", "Pesos ARS"))
        simbolo = str(inv.get("simbolo", "")).upper().strip().split(" ")[0]
        if tipo == "Dólares USD":
            val_usd = cant
            val_ars = cant * dolar_b
        elif tipo in ["Cryptos", "Stocks"]:
            precio_u = cotizaciones.get(simbolo, 1.0 if tipo == "Cryptos" else 100.0)
            val_usd = cant * precio_u
            val_ars = val_usd * dolar_b
        elif tipo == "Bonds":
            precio_u_ars = cotizaciones.get(f"BONO_ARS_{simbolo}", float(inv.get("precio_unitario_ars", 1120.0)))
            val_ars = cant * precio_u_ars
            val_usd = val_ars / dolar_b if dolar_b > 0 else 0.0
        else:
            precio_u_ars = float(inv.get("precio_unitario_ars", 1.0))
            if simbolo and simbolo not in ["ARS", "USD"] and simbolo in cotizaciones:
                precio_u_ars = cotizaciones[simbolo] * dolar_b
            val_ars = cant * precio_u_ars
            val_usd = val_ars / dolar_b if dolar_b > 0 else 0.0

        filas_inv.append({
            "Record Date": fecha_actual,
            "Asset Category": tipo,
            "Asset": inv.get("activo", ""),
            "Location / Platform": inv.get("plataforma", ""),
            "Quantity": cant,
            "Active in Portfolio": "Yes" if inv.get("activo_inv", True) else "No",
            "Estimated Value (ARS)": round(val_ars, 2),
            "Estimated Value (USD)": round(val_usd, 2)
        })

    df_inv = pd.DataFrame(filas_inv) if filas_inv else pd.DataFrame(
        columns=["Record Date", "Asset Category", "Asset", "Location / Platform", "Quantity", "Active in Portfolio", "Estimated Value (ARS)", "Estimated Value (USD)"]
    )

    df_hist = pd.DataFrame(datos.get("historial_cierres", []))
    return df_mov, df_inv, df_hist


def _generar_xlsx_fallback_zip(hojas_dict):
    """Native .xlsx generator without external dependencies if openpyxl is not installed."""
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


def generar_excel_bytes(datos, dolar_b, cotizaciones):
    df_mov, df_inv, df_hist = armar_dataframes_exportacion(datos, dolar_b, cotizaciones)
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


def registrar_snapshot_cierre(datos, dolar_b, cotizaciones):
    fecha_str = datetime.now(TZ_SYDNEY).strftime("%Y-%m-%d %H:%M")
    costos_act = sum(c["monto"] for c in datos.get("costos", []) if c.get("activo", True))
    ingresos_act = sum(i["monto"] for i in datos.get("ingresos", []) if i.get("activo", True))
    ahorro_act = ingresos_act - costos_act

    hist = datos.setdefault("historial_cierres", [])
    if not hist or hist[-1].get("Date") != fecha_str:
        hist.append({
            "Date": fecha_str,
            "Income ARS": round(ingresos_act, 2),
            "Costs ARS": round(costos_act, 2),
            "Savings ARS": round(ahorro_act, 2),
            "Blue Dollar": round(dolar_b, 2),
            "Savings USD": round(ahorro_act / dolar_b, 2) if dolar_b > 0 else 0.0
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
            msg["Subject"] = "🌿 Recovery Code - Finapp"
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
            "_subject": "🌿 Recovery Code - Finapp",
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
        f"🌿 Finapp: Your username is {usuario_actual} "
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


# ----------------- EXTERNAL MARKET QUOTES -----------------
@st.cache_data(ttl=180)
def obtener_cotizaciones(simbolos_acciones, simbolos_cripto, simbolos_bonos=()):
    cotiz = {
        "dolar_blue": 1575.0,
        "BTC": 82000.0,
        "ETH": 2600.0,
        "USDT": 1.0,
        "SOL": 150.0,
        "BNB": 580.0,
        "ADA": 0.75,
        "XRP": 1.10,
        "DOT": 6.50,
        "DOGE": 0.22,
        "AAPL": 230.0,
        "KO": 68.0,
        "MELI": 2050.0,
        "SPY": 580.0,
        "MSFT": 420.0,
        "GOOGL": 175.0,
        "AMZN": 200.0,
        "TSLA": 250.0,
        "NVDA": 135.0,
        "YPFD": 28.0,
        "BONO_ARS_AL30": 1120.0,
        "BONO_ARS_GD30": 1145.0,
        "BONO_ARS_AL29": 1160.0,
        "BONO_ARS_GD29": 1185.0,
        "BONO_ARS_AL35": 980.0,
        "BONO_ARS_GD35": 1010.0,
        "BONO_ARS_AE38": 1030.0,
        "BONO_ARS_GD38": 1065.0,
        "BONO_ARS_AL41": 940.0,
        "BONO_ARS_GD41": 970.0,
        "BONO_ARS_GD46": 995.0,
        "BONO_ARS_BPY26": 1320.0,
        "BONO_ARS_BPJ25": 1410.0,
        "BONO_ARS_BPO27": 1240.0,
        "BONO_ARS_TX26": 2150.0,
        "BONO_ARS_TX28": 1980.0,
        "BONO_ARS_TZX26": 2340.0,
        "BONO_ARS_TZX27": 2190.0,
        "BONO_ARS_TZX28": 2050.0,
        "BONO_ARS_DICP": 34500.0,
        "BONO_ARS_PARP": 16800.0,
        "BONO_ARS_CUAP": 22400.0,
        "BONO_ARS_PR17": 1850.0,
        "BONO_ARS_TVPP": 18.5,
        "BONO_ARS_TVPA": 420.0,
        "BONO_ARS_TVPY": 450.0,
        "BONO_ARS_S31E5": 1280.0,
        "BONO_ARS_S28F5": 1310.0,
        "BONO_ARS_S31M5": 1345.0,
        "BONO_ARS_S30J5": 1420.0,
        "BONO_ARS_S30S5": 1495.0,
        "BONO_ARS_T15D5": 1580.0,
        "BONO_ARS_YCA6O": 1590.0,
        "BONO_ARS_YMCHO": 1620.0,
        "BONO_ARS_MRCAO": 1550.0,
        "BONO_ARS_IRCFO": 1580.0,
        "BONO_ARS_TLCTO": 1540.0,
        "BONO_ARS_PNDCO": 1610.0,
        "BONO_ARS_MGCHO": 1595.0,
        "BONO_ARS_CS38O": 1530.0
    }

    try:
        url_dolar = "https://dolarapi.com/v1/dolares/blue"
        r_dolar = requests.get(url_dolar, timeout=4)
        if r_dolar.status_code == 200:
            venta = r_dolar.json().get("venta", cotiz["dolar_blue"])
            cotiz["dolar_blue"] = float(venta)
    except Exception:
        pass

    lista_c = set(["BTC", "ETH", "SOL", "BNB"] + list(simbolos_cripto))
    for cripto in lista_c:
        c_up = cripto.upper().strip()
        if not c_up:
            continue
        if c_up in ["USDT", "USDC", "DAI"]:
            cotiz[c_up] = 1.0
            continue
        try:
            par = f"{c_up}USDT"
            url_bin = f"https://api.binance.com/api/v3/ticker/price?symbol={par}"
            r_bin = requests.get(url_bin, timeout=3)
            if r_bin.status_code == 200:
                cotiz[c_up] = float(r_bin.json()["price"])
        except Exception:
            pass

    headers = {"User-Agent": "Mozilla/5.0"}
    for ticker in set(simbolos_acciones):
        t_clean = ticker.upper().strip().split(" ")[0]
        if not t_clean or t_clean in ["USD", "ARS"]:
            continue
        try:
            url_yf = f"https://query1.finance.yahoo.com/v8/finance/chart/{t_clean}?interval=1d&range=1d"
            r_yf = requests.get(url_yf, headers=headers, timeout=3)
            if r_yf.status_code == 200:
                res = r_yf.json()["chart"]["result"][0]["meta"]
                precio_vivo = float(res.get("regularMarketPrice", 0))
                if precio_vivo > 0:
                    cotiz[t_clean] = precio_vivo
        except Exception:
            pass

    for bono in set(simbolos_bonos or ()):
        b_clean = bono.upper().strip().split(" ")[0]
        if not b_clean or b_clean in ["USD", "ARS"]:
            continue
        try:
            url_ba = f"https://query1.finance.yahoo.com/v8/finance/chart/{b_clean}.BA?interval=1d&range=1d"
            r_ba = requests.get(url_ba, headers=headers, timeout=3)
            if r_ba.status_code == 200:
                res_ba = r_ba.json()["chart"]["result"][0]["meta"]
                p_ba = float(res_ba.get("regularMarketPrice", 0))
                currency_ba = str(res_ba.get("currency", "ARS")).upper()
                if p_ba > 0:
                    if b_clean[:2] in ["AL", "GD", "AE", "BP", "TX", "TZ"] and p_ba > 25000:
                        p_ba = p_ba / 100.0
                    cotiz[f"BONO_ARS_{b_clean}"] = p_ba if currency_ba == "ARS" else (p_ba * cotiz["dolar_blue"])
                    continue
        except Exception:
            pass
        try:
            url_us = f"https://query1.finance.yahoo.com/v8/finance/chart/{b_clean}?interval=1d&range=1d"
            r_us = requests.get(url_us, headers=headers, timeout=3)
            if r_us.status_code == 200:
                res_us = r_us.json()["chart"]["result"][0]["meta"]
                p_us = float(res_us.get("regularMarketPrice", 0))
                currency_us = str(res_us.get("currency", "USD")).upper()
                if p_us > 0:
                    cotiz[f"BONO_ARS_{b_clean}"] = (p_us * cotiz["dolar_blue"]) if currency_us == "USD" else p_us
        except Exception:
            pass

    return cotiz


# ----------------- RESPONSIVE CSS STYLES (LAPTOP + MOBILE) -----------------
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
        background: linear-gradient(145deg, #EAF6EE 0%, #F5F0FF 100%);
        border: 2px solid #95D5B2;
        border-radius: 22px;
        padding: 28px 24px 18px 24px;
        box-shadow: 0 8px 20px rgba(45, 106, 79, 0.08);
        text-align: center;
        margin-top: 10px;
        margin-bottom: 14px;
    }
    .jardin-login-title {
        color: #1B4332;
        font-weight: 800;
        font-size: 1.9rem;
        margin: 10px 0 6px 0;
    }
    .jardin-login-sub {
        color: #40916C;
        font-size: 1.05rem;
        font-weight: 500;
        margin-bottom: 4px;
    }
    div[data-testid="stFormSubmitButton"] button {
        background: linear-gradient(90deg, #40916C 0%, #2D6A4F 100%) !important;
        color: #FFFFFF !important;
        font-weight: 700 !important;
        border-radius: 12px !important;
        border: 2px solid #1B4332 !important;
        min-height: 46px !important;
    }
    div[data-testid="stFormSubmitButton"] button p,
    div[data-testid="stFormSubmitButton"] button span {
        color: #FFFFFF !important;
        font-weight: 700 !important;
    }
    details div[data-testid="stForm"] div[data-testid="stFormSubmitButton"] button,
    button.btn-mas-trebol {
        background: #57CC99 !important;
        background-color: #57CC99 !important;
        border: 1.5px solid #38A3A5 !important;
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
        box-shadow: 0 2px 6px rgba(87, 204, 153, 0.25) !important;
    }
    details div[data-testid="stForm"] div[data-testid="stFormSubmitButton"] button:hover,
    button.btn-mas-trebol:hover {
        background: #48B886 !important;
        background-color: #48B886 !important;
        border-color: #2D6A4F !important;
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

    .stTabs {
        overflow: visible !important;
    }
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"],
    div[data-baseweb="tab-highlight"],
    div[data-baseweb="tab-border"] {
        display: none !important;
        height: 0px !important;
        background: transparent !important;
        background-color: transparent !important;
        border: none !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 16px !important;
        margin-bottom: 1.25rem !important;
        padding: 8px 4px !important;
        height: auto !important;
        min-height: 72px !important;
        overflow: visible !important;
        background: transparent !important;
        border: none !important;
        align-items: center !important;
        flex-wrap: wrap !important;
    }
    .stTabs button[data-baseweb="tab"] {
        min-height: 58px !important;
        height: auto !important;
        padding: 12px 32px !important;
        background-color: #F9FAFB !important;
        border-radius: 999px !important;
        border: 1.5px solid #D8ECE3 !important;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04) !important;
        transition: all 0.25s ease-in-out !important;
        overflow: visible !important;
    }
    .stTabs button[data-baseweb="tab"]:hover {
        background-color: #F0FBF6 !important;
        border-color: #A8DFC4 !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 5px 12px rgba(45, 106, 79, 0.10) !important;
    }
    .stTabs button[data-baseweb="tab"][aria-selected="true"] {
        background-color: #E6F7EF !important;
        border: 2px solid #A8DFC4 !important;
        border-radius: 999px !important;
        box-shadow: 0 4px 14px rgba(45, 106, 79, 0.14) !important;
    }
    .stTabs button[data-baseweb="tab"] [data-testid="stMarkdownContainer"] p,
    .stTabs button[data-baseweb="tab"] p {
        font-size: 1.22rem !important;
        font-weight: 800 !important;
        color: #4B5563 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.4px !important;
        margin: 0 !important;
        display: inline-flex !important;
        align-items: center !important;
        gap: 8px !important;
        line-height: 1.2 !important;
    }
    .stTabs button[data-baseweb="tab"][aria-selected="true"] [data-testid="stMarkdownContainer"] p,
    .stTabs button[data-baseweb="tab"][aria-selected="true"] p {
        color: #1B4332 !important;
    }
    .stTabs button[data-baseweb="tab"] .trebol-tab-icon {
        font-size: 1.3em !important;
        line-height: 1 !important;
        vertical-align: middle !important;
        display: inline-block !important;
        opacity: 0.5 !important;
        transition: opacity 0.25s ease-in-out !important;
    }
    .stTabs button[data-baseweb="tab"][aria-selected="true"] .trebol-tab-icon {
        opacity: 1 !important;
    }

    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo),
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) {
        display: none !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details,
    details[data-add-cat="costo"] {
        background-color: #FFF2EE !important;
        border: 2px solid #E07A5F !important;
        border-radius: 16px !important;
        box-shadow: 0 4px 12px rgba(224, 122, 95, 0.14) !important;
        margin-bottom: 12px !important;
        overflow: hidden !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details > summary,
    details[data-add-cat="costo"] > summary {
        background-color: #FADBD8 !important;
        color: #922B21 !important;
        font-weight: 800 !important;
        padding: 12px 16px !important;
        border-radius: 14px !important;
        transition: background-color 0.2s ease !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details > summary:hover,
    details[data-add-cat="costo"] > summary:hover {
        background-color: #F5B7B1 !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details > summary p,
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details > summary span,
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-costo) + div[data-testid="stElementContainer"] details > summary svg,
    details[data-add-cat="costo"] > summary p,
    details[data-add-cat="costo"] > summary span,
    details[data-add-cat="costo"] > summary svg {
        color: #922B21 !important;
        fill: #922B21 !important;
        font-weight: 800 !important;
    }

    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details,
    details[data-add-cat="ingreso"] {
        background-color: #ECFDF5 !important;
        border: 2px solid #48C9B0 !important;
        border-radius: 16px !important;
        box-shadow: 0 4px 12px rgba(72, 201, 176, 0.14) !important;
        margin-bottom: 12px !important;
        overflow: hidden !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details > summary,
    details[data-add-cat="ingreso"] > summary {
        background-color: #D1F2EB !important;
        color: #0E6251 !important;
        font-weight: 800 !important;
        padding: 12px 16px !important;
        border-radius: 14px !important;
        transition: background-color 0.2s ease !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details > summary:hover,
    details[data-add-cat="ingreso"] > summary:hover {
        background-color: #A3E4D7 !important;
    }
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details > summary p,
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details > summary span,
    div[data-testid="stElementContainer"]:has(> div > .hook-agregar-ingreso) + div[data-testid="stElementContainer"] details > summary svg,
    details[data-add-cat="ingreso"] > summary p,
    details[data-add-cat="ingreso"] > summary span,
    details[data-add-cat="ingreso"] > summary svg {
        color: #0E6251 !important;
        fill: #0E6251 !important;
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
        padding: 1.35rem;
        border-radius: 16px;
        margin-bottom: 1rem;
        box-shadow: 0 2px 6px rgba(0,0,0,0.04);
    }
    .metric-card-costo {
        background-color: #FDEBD0;
        border: 1px solid #F5CBA7;
        border-left: 7px solid #E59866;
        color: #6E2C00;
    }
    .metric-card-ingreso {
        background-color: #E8F8F5;
        border: 1px solid #A3E4D7;
        border-left: 7px solid #76D7C4;
        color: #117864;
    }
    .metric-card-lila {
        background-color: #F3E8FF;
        border: 1px solid #D8B4FE;
        border-left: 7px solid #B794F4;
        color: #4A235A;
    }
    .metric-card-rojo-pastel {
        background-color: #FADBD8;
        border: 1px solid #F5B7B1;
        border-left: 7px solid #EC7063;
        color: #78281F;
    }
    .metric-card-neutro {
        background-color: #F3F4F6;
        border: 1px solid #D1D5DB;
        border-left: 7px solid #9CA3AF;
        color: #374151;
    }
    .kpi-title {
        font-size: 1.15rem;
        font-weight: 700;
        margin-bottom: 0.3rem;
    }
    .kpi-value {
        font-size: 2.1rem;
        font-weight: 800;
        line-height: 1.2;
    }
    .kpi-usd {
        font-size: 1.05rem;
        font-weight: 600;
        margin-top: 0.35rem;
        padding: 3px 10px;
        border-radius: 8px;
        background-color: rgba(255, 255, 255, 0.7);
        display: inline-block;
    }
    .kpi-sub {
        font-size: 0.95rem;
        font-weight: 600;
        opacity: 0.9;
        margin-top: 0.45rem;
    }
    .col-header {
        font-size: 0.82rem;
        font-weight: 700;
        color: #4B5563;
        text-transform: uppercase;
        letter-spacing: 0.3px;
        padding-bottom: 4px;
        border-bottom: 2px solid #D1D5DB;
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

    .jardin-health-scene {
        position: relative;
        width: 100%;
        max-width: 100%;
        margin: 0 0 1.1rem 0;
        border-radius: 18px;
        border: 3px solid #22C55E;
        overflow: hidden;
        box-shadow: 0 10px 24px rgba(0, 0, 0, 0.12);
        min-height: 142px;
        display: flex;
        flex-direction: row;
        align-items: stretch;
        padding: 0;
        box-sizing: border-box;
    }
    .jardin-info-panel {
        flex: 0 0 32%;
        width: 32%;
        min-width: 280px;
        background: #FDFBF7;
        border-right: 2px solid #22C55E;
        padding: 8px 14px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        box-sizing: border-box;
        z-index: 2;
    }
    .jardin-scene-panel {
        flex: 1 1 68%;
        width: 68%;
        position: relative;
        overflow: hidden;
        min-height: 142px;
        box-sizing: border-box;
    }
    .jardin-scene-svg {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        z-index: 1;
        pointer-events: none;
    }
    .jardin-char-wrap {
        position: absolute;
        bottom: 4px;
        width: 82px;
        height: 112px;
        z-index: 3;
        pointer-events: none;
        overflow: visible !important;
        display: flex;
        align-items: flex-end;
        justify-content: center;
    }
    .jardin-char-left {
        left: 10px;
    }
    .jardin-char-right {
        left: 92px;
        right: auto;
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
    .jardin-char-svg {
        width: 100%;
        height: 100%;
        overflow: visible !important;
    }
    .jardin-status-box {
        margin-top: 5px;
        padding: 6px 10px;
        border-radius: 10px;
        border: 1.5px solid;
        width: 100%;
        box-sizing: border-box;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
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

    @keyframes jardinKangaBounce {
        0%, 100% { transform: translateY(0px) scaleY(1); }
        45% { transform: translateY(-7px) scaleY(1.03); }
        55% { transform: translateY(-7px) scaleY(1.03); }
    }
    @keyframes jardinKoalaSway {
        0%, 100% { transform: translateY(0px) rotate(0deg); }
        50% { transform: translateY(-3px) rotate(-2.5deg); }
    }
    @keyframes jardinTiredBreath {
        0%, 100% { transform: translateY(4px) scaleY(0.98); }
        50% { transform: translateY(7px) scaleY(0.95); }
    }
    @keyframes jardinSunFireSpin {
        0% { transform: rotate(0deg) scale(1); }
        50% { transform: translateY(-1px) rotate(180deg) scale(1.09); }
        100% { transform: rotate(360deg) scale(1); }
    }
    @keyframes jardinTumbleweedRoll1 {
        0% { transform: translate(115px, 141px) rotate(0deg); }
        25% { transform: translate(295px, 131px) rotate(180deg); }
        50% { transform: translate(475px, 142px) rotate(360deg); }
        75% { transform: translate(640px, 132px) rotate(540deg); }
        100% { transform: translate(780px, 141px) rotate(720deg); }
    }
    @keyframes jardinTumbleweedRoll2 {
        0% { transform: translate(190px, 145px) rotate(0deg); }
        50% { transform: translate(470px, 135px) rotate(360deg); }
        100% { transform: translate(730px, 144px) rotate(720deg); }
    }
    @keyframes jardinFlyBuzz1 {
        0% { transform: translate(65px, 78px) rotate(0deg); }
        25% { transform: translate(82px, 66px) rotate(25deg); }
        50% { transform: translate(98px, 80px) rotate(-15deg); }
        75% { transform: translate(76px, 90px) rotate(20deg); }
        100% { transform: translate(65px, 78px) rotate(0deg); }
    }
    @keyframes jardinFlyBuzz2 {
        0% { transform: translate(112px, 86px) rotate(0deg); }
        33% { transform: translate(96px, 72px) rotate(-25deg); }
        66% { transform: translate(124px, 74px) rotate(18deg); }
        100% { transform: translate(112px, 86px) rotate(0deg); }
    }
    @keyframes jardinFlyBuzz3 {
        0% { transform: translate(44px, 90px) rotate(0deg); }
        33% { transform: translate(58px, 76px) rotate(22deg); }
        66% { transform: translate(36px, 78px) rotate(-20deg); }
        100% { transform: translate(44px, 90px) rotate(0deg); }
    }

    .jardin-kanga-happy {
        animation: jardinKangaBounce 2.4s ease-in-out infinite;
        transform-origin: 82px 195px;
    }
    .jardin-koala-happy {
        animation: jardinKoalaSway 2.8s ease-in-out infinite;
        transform-origin: 80px 180px;
    }
    .jardin-animal-tired {
        animation: jardinTiredBreath 3.4s ease-in-out infinite;
        transform-origin: center bottom;
    }
    .jardin-sun-flames {
        animation: jardinSunFireSpin 7s linear infinite;
    }
    .jardin-tumbleweed-1 {
        animation: jardinTumbleweedRoll1 7.5s linear infinite;
    }
    .jardin-tumbleweed-2 {
        animation: jardinTumbleweedRoll2 9.5s linear infinite;
    }
    .jardin-fly-1 {
        animation: jardinFlyBuzz1 1.3s ease-in-out infinite;
    }
    .jardin-fly-2 {
        animation: jardinFlyBuzz2 1.1s ease-in-out infinite;
    }
    .jardin-fly-3 {
        animation: jardinFlyBuzz3 1.5s ease-in-out infinite;
    }

    @media (prefers-reduced-motion: reduce) {
        .jardin-kanga-happy,
        .jardin-koala-happy,
        .jardin-animal-tired,
        .jardin-sun-flames,
        .jardin-tumbleweed-1,
        .jardin-tumbleweed-2,
        .jardin-fly-1,
        .jardin-fly-2,
        .jardin-fly-3 {
            animation: none !important;
        }
    }

    @media (max-width: 768px) {
        .jardin-health-scene {
            flex-direction: column !important;
            width: 100% !important;
            max-width: 100% !important;
            min-height: auto !important;
        }
        .jardin-info-panel {
            flex: 1 1 100% !important;
            width: 100% !important;
            max-width: 100% !important;
            min-width: 0 !important;
            border-right: none !important;
            border-bottom: 2px solid #D1D5DB !important;
            padding: 10px 12px !important;
        }
        .jardin-scene-panel {
            flex: 1 1 100% !important;
            width: 100% !important;
            max-width: 100% !important;
            height: 145px !important;
            min-height: 145px !important;
        }
        .jardin-char-wrap {
            width: 72px !important;
            height: 100px !important;
            bottom: 4px !important;
        }
        .jardin-char-left {
            left: 6px !important;
        }
        .jardin-char-right {
            left: 76px !important;
            right: auto !important;
        }
        .block-container {
            max-width: 100% !important;
            padding-top: 3.2rem !important;
            padding-left: 0.65rem !important;
            padding-right: 0.65rem !important;
        }
        .kpi-value {
            font-size: 1.65rem !important;
        }
        .stTabs button[data-baseweb="tab"] {
            padding: 10px 18px !important;
            min-height: 48px !important;
        }
        .stTabs button[data-baseweb="tab"] [data-testid="stMarkdownContainer"] p {
            font-size: 1.05rem !important;
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
        st.markdown("""
        <div class="jardin-login-box">
            <svg width="80" height="54" viewBox="0 0 80 54" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M40 50V18" stroke="#2D6A4F" stroke-width="3" stroke-linecap="round"/>
                <path d="M40 36C26 36 16 26 16 12C30 12 40 22 40 36Z" fill="#74C69D" stroke="#2D6A4F" stroke-width="2.2"/>
                <path d="M40 28C54 28 64 18 64 4C50 4 40 14 40 28Z" fill="#95D5B2" stroke="#2D6A4F" stroke-width="2.2"/>
                <circle cx="40" cy="12" r="4" fill="#D8B4FE" stroke="#5B4B8A" stroke-width="1.5"/>
            </svg>
            <div class="jardin-login-title">Sign in to Finapp</div>
            <div class="jardin-login-sub">Your personal space for financial clarity</div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            user = st.text_input("Username", value="Julian")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button(
                "🌿 Enter Finapp",
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
dolar_b = cotizaciones["dolar_blue"]

# ----------------- SIDEBAR, SYDNEY TIME, LAST SAVED, REFRESH & LOGOUT -----------------
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
hora_str = ahora.strftime('%H:%M')
fecha_hora_texto = f"Today is {dia_str}, {mes_str} {ahora.day} - {hora_str}"
ultima_act_texto = calcular_texto_ultima_actualizacion(datos, ahora)
stamp_archivo = ahora.strftime("%Y-%m-%d_%H-%M")

if "confirmar_cierre" not in st.session_state:
    st.session_state.confirmar_cierre = False


def finalizar_sesion():
    limpiar_token_sesion(datos)
    st.session_state.confirmar_cierre = False
    st.session_state.autenticado = False


with st.sidebar:
    st.markdown(
        "<h2 style='color: #2D6A4F;'>🌿 My Panel</h2>",
        unsafe_allow_html=True
    )
    st.markdown(f"🗓️ **{fecha_hora_texto}**")
    st.caption(f"🕒 {ultima_act_texto}")
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
    st.markdown("---")
    st.markdown(f"💵 **Blue Dollar:** `{dolar_b:,.0f} ARS`")
    st.markdown(f"🪙 **Bitcoin:** `{cotizaciones['BTC']:,.0f} USD`")
    st.markdown("---")

    with st.expander("🔐 Recovery Settings"):
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
        registrar_snapshot_cierre(datos, dolar_b, cotizaciones)
        st.session_state.confirmar_cierre = True
        st.rerun()

if st.session_state.confirmar_cierre:
    st.markdown("""
    <div style="background: linear-gradient(145deg, #EAF6EE 0%, #F3E8FF 100%);
                border: 2px solid #7E22CE; border-radius: 18px; padding: 20px; margin-bottom: 16px;
                box-shadow: 0 8px 24px rgba(126, 34, 206, 0.14);">
        <h3 style="color: #1B4332; margin-top: 0; margin-bottom: 8px;">✅ Your changes have been saved automatically!</h3>
        <p style="font-size: 1.15rem; color: #374151; font-weight: 700; margin-bottom: 0;">
            Would you like to download a spreadsheet backup before logging out?
        </p>
    </div>
    """, unsafe_allow_html=True)

    col_dl1, col_dl2 = st.columns(2, gap="medium")
    with col_dl1:
        st.download_button(
            label="📥 YES, DOWNLOAD & LOG OUT",
            data=generar_excel_bytes(datos, dolar_b, cotizaciones),
            file_name=f"Finapp_{stamp_archivo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            on_click=finalizar_sesion
        )
    with col_dl2:
        if st.button("🚪 NO, LOG OUT", use_container_width=True):
            finalizar_sesion()
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


# ----------------- MAIN TABS -----------------
pestana1, pestana2 = st.tabs([
    "🍀 COSTS & INCOME",
    "🍀 TOTAL NET WORTH"
])

# =========================================================================
# ============================= TAB 1 =====================================
# =========================================================================
with pestana1:
    total_items_costos = len(datos["costos"])
    costos_activos = [c for c in datos["costos"] if c.get("activo", True)]
    total_costos = sum(c["monto"] for c in costos_activos)

    total_items_ingresos = len(datos["ingresos"])
    ingresos_activos = [i for i in datos["ingresos"] if i.get("activo", True)]
    total_ingresos = sum(i["monto"] for i in ingresos_activos)

    saldo_neto = total_ingresos - total_costos

    costos_usd = total_costos / dolar_b if dolar_b > 0 else 0
    ingresos_usd = total_ingresos / dolar_b if dolar_b > 0 else 0
    saldo_usd = saldo_neto / dolar_b if dolar_b > 0 else 0

    if saldo_neto > 0:
        clase_saldo = "metric-card-lila"
        carita = "😊"
        sub_saldo = "Positive result (Gain / Savings)"
    elif saldo_neto == 0:
        clase_saldo = "metric-card-neutro"
        carita = "😐"
        sub_saldo = "Break-even (No gain or loss)"
    else:
        clase_saldo = "metric-card-rojo-pastel"
        carita = "😟"
        sub_saldo = "Negative result (Monthly deficit)"

    col_kpi1, col_kpi2, col_kpi3 = st.columns(3, gap="medium")
    with col_kpi1:
        st.markdown(f"""
        <div class="metric-card metric-card-costo">
            <div class="kpi-title">Monthly Costs</div>
            <div class="kpi-value">{total_costos:,.0f} ARS</div>
            <div class="kpi-usd">≈ {costos_usd:,.2f} USD</div>
            <div class="kpi-sub">{len(costos_activos)} active of {total_items_costos}</div>
        </div>
        """, unsafe_allow_html=True)

    with col_kpi2:
        st.markdown(f"""
        <div class="metric-card metric-card-ingreso">
            <div class="kpi-title">Monthly Income</div>
            <div class="kpi-value">{total_ingresos:,.0f} ARS</div>
            <div class="kpi-usd">≈ {ingresos_usd:,.2f} USD</div>
            <div class="kpi-sub">{len(ingresos_activos)} active of {total_items_ingresos}</div>
        </div>
        """, unsafe_allow_html=True)

    with col_kpi3:
        st.markdown(f"""
        <div class="metric-card {clase_saldo}">
            <div class="kpi-title">Monthly Savings {carita}</div>
            <div class="kpi-value">{saldo_neto:,.0f} ARS</div>
            <div class="kpi-usd">≈ {saldo_usd:,.2f} USD</div>
            <div class="kpi-sub">{sub_saldo}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    col_izq, col_der = st.columns(2, gap="medium")

    # ---------------- COSTS ----------------
    with col_izq:
        st.markdown("<h3 style='color: #A04000; margin-bottom: 6px;'>📉 My Monthly Costs</h3>", unsafe_allow_html=True)
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
            sub_ars = sum(i["monto"] for _, i in items_cat if i.get("activo", True))
            sub_usd = sub_ars / dolar_b if dolar_b > 0 else 0
            icono_cat = datos.get("iconos_costos", {}).get(cat_nombre, predecir_icono_categoria(cat_nombre, "costo"))

            titulo_cat = f"{icono_cat} **{cat_nombre}** — subt= **{sub_ars:,.0f} ARS** ({sub_usd:,.1f} USD)"
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
                    h3.markdown("<div class='col-header'>AMOUNT (ARS)</div>", unsafe_allow_html=True)
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
                            "Amount ARS",
                            placeholder="Amount ARS",
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
        st.markdown("<h3 style='color: #117864; margin-bottom: 6px;'>📈 My Monthly Income</h3>", unsafe_allow_html=True)
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
            sub_ars_i = sum(i["monto"] for _, i in items_cat_i if i.get("activo", True))
            sub_usd_i = sub_ars_i / dolar_b if dolar_b > 0 else 0
            icono_cat_i = datos.get("iconos_ingresos", {}).get(cat_nombre_i, predecir_icono_categoria(cat_nombre_i, "ingreso"))

            titulo_cat_i = f"{icono_cat_i} **{cat_nombre_i}** — subt= **{sub_ars_i:,.0f} ARS** ({sub_usd_i:,.1f} USD)"
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
                    hi3.markdown("<div class='col-header'>AMOUNT (ARS)</div>", unsafe_allow_html=True)
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
                            "Amount ARS",
                            placeholder="Amount ARS",
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
        "<h3 style='color: #5B4B8A;'>📊 Charts & Tables</h3>",
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
            "<h4 style='color: #A04000; text-align: center;'>Costs Breakdown</h4>",
            unsafe_allow_html=True
        )
        if costos_activos and total_costos > 0:
            df_c_raw = pd.DataFrame(costos_activos)
            if modo_grafico.startswith("By Category"):
                df_pie_c = df_c_raw.groupby("grupo", as_index=False)["monto"].sum().sort_values(by="monto", ascending=False)
                col_label_c = "grupo"
                titulo_col_c = "Category"
                fig_c = crear_torta_2d(df_pie_c, "monto", col_label_c, tamano="grande", usar_minusculas=True)
            else:
                df_pie_c = df_c_raw.sort_values(by="monto", ascending=False).copy()
                df_pie_c["etiqueta"] = df_pie_c["categoria"]
                col_label_c = "etiqueta"
                titulo_col_c = "Subcategory"
                fig_c = crear_barras_horizontales(df_pie_c, "monto", col_label_c)

            df_pie_c["USD"] = df_pie_c["monto"] / dolar_b
            df_pie_c["Percentage"] = (df_pie_c["monto"] / total_costos) * 100

            st.plotly_chart(fig_c, use_container_width=True, config={"displayModeBar": False})

            tabla_c = df_pie_c[[col_label_c, "monto", "USD", "Percentage"]].copy()
            tabla_c.columns = [titulo_col_c, "Subtotal (ARS)", "Subtotal (USD)", "% of Total"]
            tabla_c["Subtotal (ARS)"] = tabla_c["Subtotal (ARS)"].apply(lambda x: f"{x:,.0f} ARS")
            tabla_c["Subtotal (USD)"] = tabla_c["Subtotal (USD)"].apply(lambda x: f"{x:,.2f} USD")
            tabla_c["% of Total"] = tabla_c["% of Total"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(tabla_c, use_container_width=True, hide_index=True)
        else:
            st.info("No active costs to display.")

    with col_chart_i:
        st.markdown(
            "<h4 style='color: #117864; text-align: center;'>Income Breakdown</h4>",
            unsafe_allow_html=True
        )
        if ingresos_activos and total_ingresos > 0:
            df_i_raw = pd.DataFrame(ingresos_activos)
            if modo_grafico.startswith("By Category"):
                df_pie_i = df_i_raw.groupby("grupo", as_index=False)["monto"].sum().sort_values(by="monto", ascending=False)
                col_label_i = "grupo"
                titulo_col_i = "Category"
                fig_i = crear_torta_2d(df_pie_i, "monto", col_label_i, tamano="chico", usar_minusculas=True)
            else:
                df_pie_i = df_i_raw.sort_values(by="monto", ascending=False).copy()
                df_pie_i["etiqueta"] = df_pie_i["concepto"]
                col_label_i = "etiqueta"
                titulo_col_i = "Subcategory"
                fig_i = crear_barras_horizontales(df_pie_i, "monto", col_label_i)

            df_pie_i["USD"] = df_pie_i["monto"] / dolar_b
            df_pie_i["Percentage"] = (df_pie_i["monto"] / total_ingresos) * 100

            st.plotly_chart(fig_i, use_container_width=True, config={"displayModeBar": False})

            tabla_i = df_pie_i[[col_label_i, "monto", "USD", "Percentage"]].copy()
            tabla_i.columns = [titulo_col_i, "Subtotal (ARS)", "Subtotal (USD)", "% of Total"]
            tabla_i["Subtotal (ARS)"] = tabla_i["Subtotal (ARS)"].apply(lambda x: f"{x:,.0f} ARS")
            tabla_i["Subtotal (USD)"] = tabla_i["Subtotal (USD)"].apply(lambda x: f"{x:,.2f} USD")
            tabla_i["% of Total"] = tabla_i["% of Total"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(tabla_i, use_container_width=True, hide_index=True)
        else:
            st.info("No active income to display.")


# =========================================================================
# ============================= TAB 2 =====================================
# =========================================================================
with pestana2:
    inversiones = datos.get("inversiones", [])
    if reparar_inversiones_corruptas(inversiones):
        guardar_datos(datos, registrar_cambio=False)

    filas = []
    advertencias_precios = []

    for inv in inversiones:
        cant = float(inv.get("cantidad", 0))
        tipo = normalizar_tipo_activo_inv(inv.get("tipo", "Pesos ARS"))
        activo_nom = str(inv.get("activo", tipo)).strip()
        if activo_nom in ["Dólar Billete", "A - Dólar Billete"]:
            activo_nom = "Dólares USD"

        simbolo = str(inv.get("simbolo", "")).upper().strip().split(" ")[0]
        if tipo in ["Cryptos", "Stocks", "Bonds"]:
            det_t = activo_nom.split(" ")[0].upper()
            if det_t and det_t not in ["USD", "ARS"]:
                simbolo = det_t

        esta_activo = inv.get("activo_inv", True)
        precio_valido = True

        if tipo == "Pesos ARS":
            precio_unit_ars = 1.0
            val_ars = cant
            val_usd = cant / dolar_b if dolar_b > 0 else 0.0
            cotiz_actual_str = f"1 USD = {dolar_b:,.0f} ARS"
        elif tipo == "Dólares USD":
            precio_unit_ars = dolar_b
            val_usd = cant
            val_ars = cant * dolar_b
            cotiz_actual_str = f"1 USD = {dolar_b:,.0f} ARS"
        elif tipo == "Cryptos":
            precio_u = cotizaciones.get(simbolo)
            if precio_u is None or float(precio_u) <= 0:
                precio_valido = False
                precio_unit_ars = 0.0
                val_usd = 0.0
                val_ars = 0.0
                cotiz_actual_str = f"⚠️ No quote for {simbolo}"
                if esta_activo:
                    advertencias_precios.append(f"{activo_nom} ({tipo})")
            else:
                precio_u = float(precio_u)
                precio_unit_ars = precio_u * dolar_b
                val_usd = cant * precio_u
                val_ars = cant * precio_unit_ars
                cotiz_actual_str = f"1 {simbolo} = {precio_u:,.2f} USD ({precio_unit_ars:,.0f} ARS)"
        elif tipo == "Stocks":
            precio_u = cotizaciones.get(simbolo)
            if precio_u is None or float(precio_u) <= 0:
                precio_valido = False
                precio_unit_ars = 0.0
                val_usd = 0.0
                val_ars = 0.0
                cotiz_actual_str = f"⚠️ No quote for {simbolo}"
                if esta_activo:
                    advertencias_precios.append(f"{activo_nom} ({tipo})")
            else:
                precio_u = float(precio_u)
                precio_unit_ars = precio_u * dolar_b
                val_usd = cant * precio_u
                val_ars = cant * precio_unit_ars
                cotiz_actual_str = f"1 {simbolo} = {precio_u:,.2f} USD ({precio_unit_ars:,.0f} ARS)"
        elif tipo == "Bonds":
            precio_bono = cotizaciones.get(f"BONO_ARS_{simbolo}", inv.get("precio_unitario_ars"))
            if precio_bono is None or float(precio_bono) <= 0:
                precio_valido = False
                precio_unit_ars = 0.0
                val_ars = 0.0
                val_usd = 0.0
                cotiz_actual_str = f"⚠️ No quote for {simbolo}"
                if esta_activo:
                    advertencias_precios.append(f"{activo_nom} ({tipo})")
            else:
                precio_unit_ars = float(precio_bono)
                val_ars = cant * precio_unit_ars
                val_usd = val_ars / dolar_b if dolar_b > 0 else 0.0
                cotiz_actual_str = f"1 {simbolo} = {precio_unit_ars:,.0f} ARS ({precio_unit_ars / dolar_b if dolar_b > 0 else 0:,.2f} USD)"
        else:
            if simbolo and simbolo not in ["ARS", "USD"] and simbolo in cotizaciones and float(cotizaciones[simbolo]) > 0:
                precio_unit_ars = float(cotizaciones[simbolo]) * dolar_b
                cotiz_actual_str = f"1 {simbolo} = {precio_unit_ars:,.0f} ARS"
            elif f"BONO_ARS_{simbolo}" in cotizaciones and float(cotizaciones[f"BONO_ARS_{simbolo}"]) > 0:
                precio_unit_ars = float(cotizaciones[f"BONO_ARS_{simbolo}"])
                cotiz_actual_str = f"1 {simbolo} = {precio_unit_ars:,.0f} ARS"
            else:
                precio_unit_ars = float(inv.get("precio_unitario_ars", 1.0))
                if precio_unit_ars <= 0:
                    precio_valido = False
                    precio_unit_ars = 0.0
                    cotiz_actual_str = "⚠️ Invalid price"
                    if esta_activo:
                        advertencias_precios.append(f"{activo_nom} ({tipo})")
                else:
                    cotiz_actual_str = f"1 unit = {precio_unit_ars:,.0f} ARS" if precio_unit_ars != 1.0 else f"1 USD = {dolar_b:,.0f} ARS"
            val_ars = cant * precio_unit_ars if precio_valido else 0.0
            val_usd = (val_ars / dolar_b if dolar_b > 0 else 0.0) if precio_valido else 0.0

        filas.append({
            "Type": tipo,
            "Asset": activo_nom,
            "Symbol": simbolo,
            "Platform": inv.get("plataforma", ""),
            "Quantity_Num": cant,
            "Quantity": formatear_cant(cant),
            "Price_Unit_ARS": precio_unit_ars,
            "Price_Valid": precio_valido,
            "Live Quote": cotiz_actual_str,
            "Value (ARS)": val_ars,
            "Value (USD)": val_usd,
            "Active_Flag": esta_activo
        })

    if advertencias_precios:
        st.warning(
            "⚠️ No valid quote found for: "
            + ", ".join(advertencias_precios)
            + ". Excluded from total to avoid distorting Net Worth."
        )

    df_inv_todos = pd.DataFrame(filas)
    if not df_inv_todos.empty:
        df_inv_activos = df_inv_todos[df_inv_todos["Active_Flag"] == True]
    else:
        df_inv_activos = pd.DataFrame()

    total_patrimonio_ars = df_inv_activos["Value (ARS)"].sum() if not df_inv_activos.empty else 0
    total_patrimonio_usd = df_inv_activos["Value (USD)"].sum() if not df_inv_activos.empty else 0

    costos_activos_live = [c for c in datos.get("costos", []) if c.get("activo", True)]
    ingresos_activos_live = [i for i in datos.get("ingresos", []) if i.get("activo", True)]

    costo_mensual_vivir_ars = 0.0
    hay_costo_usd = False
    for c_item in costos_activos_live:
        monto_c = float(c_item.get("monto", 0))
        moneda_c = str(c_item.get("moneda", "ARS")).upper().strip()
        if moneda_c == "USD":
            hay_costo_usd = True
            costo_mensual_vivir_ars += monto_c * dolar_b if dolar_b and dolar_b > 0 else 0.0
        else:
            costo_mensual_vivir_ars += monto_c

    ingreso_mensual_vivir_ars = 0.0
    hay_ingreso_usd = False
    for i_item in ingresos_activos_live:
        monto_i = float(i_item.get("monto", 0))
        moneda_i = str(i_item.get("moneda", "ARS")).upper().strip()
        if moneda_i == "USD":
            hay_ingreso_usd = True
            ingreso_mensual_vivir_ars += monto_i * dolar_b if dolar_b and dolar_b > 0 else 0.0
        else:
            ingreso_mensual_vivir_ars += monto_i

    hay_activo_usd = any(
        inv.get("activo_inv", True) and normalizar_tipo_activo_inv(inv.get("tipo")) in ["Dólares USD", "Cryptos", "Stocks"]
        for inv in inversiones
    )
    hay_moneda_ext = hay_costo_usd or hay_ingreso_usd or hay_activo_usd
    datos_cyi_faltantes = (not costos_activos_live) or (not ingresos_activos_live)

    if not dolar_b or dolar_b <= 0:
        dolar_b = st.number_input(
            "USD to ARS Exchange Rate (required to unify currency in ARS):",
            min_value=1.0,
            value=1575.0,
            step=10.0,
            key="input_tasa_cambio_fallback"
        )

    html_panel_salud = construir_html_panel_patrimonio(
        total_patrimonio_ars=total_patrimonio_ars,
        total_patrimonio_usd=total_patrimonio_usd,
        cant_activos_contemplados=len(df_inv_activos),
        cant_activos_totales=len(inversiones),
        ingreso_mensual_ars=ingreso_mensual_vivir_ars,
        costo_mensual_ars=costo_mensual_vivir_ars,
        dolar_b=dolar_b,
        hay_moneda_extranjera=hay_moneda_ext,
        datos_faltantes=datos_cyi_faltantes
    )
    st.markdown(html_panel_salud, unsafe_allow_html=True)

    st.markdown("---")

    col_inv_izq, col_inv_der = st.columns([1.05, 1.85], gap="medium")

    # ---------------- ADD ASSET ----------------
    with col_inv_izq:
        st.markdown(
            "<h3 style='color: #5B4B8A;'>➕ Add Asset</h3>",
            unsafe_allow_html=True
        )
        opciones_tipo = [
            "A - Pesos ARS",
            "B - Dólares USD",
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
            "tipo": "A - Pesos ARS",
            "accion": "AAPL (Apple)",
            "cripto": "BTC (Bitcoin)",
            "bono": "AL30 (Bonar 2030 Ley Arg.)",
            "ubicacion": opciones_ubicacion[0]
        })

        if "_pending_inv_widget_sync" in st.session_state:
            for k_sync, v_sync in st.session_state.pop("_pending_inv_widget_sync").items():
                st.session_state[k_sync] = v_sync

        tipo_guardado = ult_sel.get("tipo", "A - Pesos ARS")
        if tipo_guardado not in opciones_tipo:
            tipo_guardado = "A - Pesos ARS"

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
        simbolo_elegido = "ARS"
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
                    "Not in the list? Type ticker manually to save it (e.g. DIS, V):",
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
                    "Fund name or ticker (e.g. Fima Premium):",
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

        if tipo_elegido == "A - Pesos ARS":
            tooltip_cant_actual = "Enter the amount in Argentine Pesos. e.g. 2500000"
        elif tipo_elegido == "B - Dólares USD":
            tooltip_cant_actual = "Enter the amount in US Dollars. e.g. 1500"
        else:
            tooltip_cant_actual = (
                "Enter the number of units, not the cash value. "
                "e.g. 2 or 5 (stocks/bonds), 0.0005 (BTC). Value is calculated automatically."
            )

        with st.form("form_guardar_activo_inv", clear_on_submit=True):
            cant_texto = st.text_input(
                "3. Quantity Held",
                placeholder="e.g. 40000 or 0.0005",
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

                    if tipo_momento_guardar == "A - Pesos ARS":
                        tipo_guardar = "Pesos ARS"
                        nombre_act = "Pesos ARS"
                        simbolo_final = "ARS"
                    elif tipo_momento_guardar == "B - Dólares USD":
                        tipo_guardar = "Dólares USD"
                        nombre_act = "Dólares USD"
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
                        simbolo_final = nombre_act.split(" ")[0].upper() if detalle_manual.strip() else "ARS"
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
        st.markdown(
            "<h3 style='color: #5B4B8A;'>📋 My Assets by Category</h3>",
            unsafe_allow_html=True
        )
        orden_categorias_inv = [
            "Pesos ARS",
            "Dólares USD",
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

                sub_inv_ars = sum(
                    filas[idx]["Value (ARS)"]
                    for idx, inv in items_cat_inv
                    if inv.get("activo_inv", True)
                )
                sub_inv_usd = sum(
                    filas[idx]["Value (USD)"]
                    for idx, inv in items_cat_inv
                    if inv.get("activo_inv", True)
                )

                titulo_exp_inv = (
                    f"📂 **{cat_inv}** — subt= "
                    f"**{sub_inv_ars:,.0f} ARS** ({sub_inv_usd:,.2f} USD)"
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
                            val_detalle_mostrar = "Dólares USD" if inv.get("activo", "") in ["Dólar Billete", "A - Dólar Billete"] else inv.get("activo", "")
                            st.text_input(
                                "Detail",
                                value=val_detalle_mostrar,
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

                            if cat_inv not in ["Pesos ARS", "Dólares USD"]:
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
                                    precio_u_ars_fila = float(filas[idx]["Price_Unit_ARS"])
                                    total_ars_fila = cant_num_actual * precio_u_ars_fila
                                    precio_u_fmt = (
                                        f"{precio_u_ars_fila:,.0f}"
                                        if precio_u_ars_fila >= 10 or precio_u_ars_fila.is_integer()
                                        else f"{precio_u_ars_fila:,.2f}"
                                    )
                                    st.markdown(
                                        f"<div style='font-size: 0.75rem; font-weight: 700; color: #4A235A; "
                                        f"background: #F5F3FF; border: 1px solid #DDD6FE; border-radius: 7px; "
                                        f"padding: 4px 7px; margin-top: -8px; margin-bottom: 6px; "
                                        f"white-space: normal; word-break: break-word; overflow-wrap: anywhere; "
                                        f"line-height: 1.25;'>"
                                        f"{cant_str_actual} × {precio_u_fmt} = {total_ars_fila:,.0f} ARS"
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

    st.markdown("---")

    st.markdown(
        "<h3 style='color: #5B4B8A;'>💼 Net Worth Breakdown</h3>",
        unsafe_allow_html=True
    )
    if not df_inv_activos.empty and total_patrimonio_ars > 0:
        col_g_inv1, col_g_inv2 = st.columns(2, gap="medium")

        with col_g_inv1:
            st.markdown(
                "<h4 style='color: #5B4B8A; text-align: center;'>By Asset Type</h4>",
                unsafe_allow_html=True
            )
            resumen_tipo = df_inv_activos.groupby("Type", as_index=False).agg({
                "Value (ARS)": "sum",
                "Value (USD)": "sum"
            }).sort_values(by="Value (ARS)", ascending=False)
            resumen_tipo["%"] = (resumen_tipo["Value (ARS)"] / total_patrimonio_ars) * 100

            fig_inv_tipo = crear_torta_2d(resumen_tipo, "Value (ARS)", "Type")
            st.plotly_chart(fig_inv_tipo, use_container_width=True, config={"displayModeBar": False})

            tabla_t = resumen_tipo.copy()
            tabla_t.columns = ["Category", "Subtotal (ARS)", "Subtotal (USD)", "%"]
            tabla_t["Subtotal (ARS)"] = tabla_t["Subtotal (ARS)"].apply(lambda x: f"{x:,.0f} ARS")
            tabla_t["Subtotal (USD)"] = tabla_t["Subtotal (USD)"].apply(lambda x: f"{x:,.2f} USD")
            tabla_t["%"] = tabla_t["%"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(tabla_t, use_container_width=True, hide_index=True)

        with col_g_inv2:
            st.markdown(
                "<h4 style='color: #5B4B8A; text-align: center;'>By Location</h4>",
                unsafe_allow_html=True
            )
            df_det = df_inv_activos.sort_values(by="Value (ARS)", ascending=False).copy()
            df_det["%"] = (df_det["Value (ARS)"] / total_patrimonio_ars) * 100

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
                "Value (ARS)": "sum",
                "Value (USD)": "sum"
            }).sort_values(by="Value (ARS)", ascending=False)
            resumen_ubic["%"] = (resumen_ubic["Value (ARS)"] / total_patrimonio_ars) * 100

            menores_2pct = resumen_ubic[resumen_ubic["%"] < 2.0]
            if len(menores_2pct) > 1:
                mayores_2pct = resumen_ubic[resumen_ubic["%"] >= 2.0].copy()
                fila_otras = pd.DataFrame([{
                    "Ubicacion_Final": "Other",
                    "Value (ARS)": menores_2pct["Value (ARS)"].sum(),
                    "Value (USD)": menores_2pct["Value (USD)"].sum(),
                    "%": menores_2pct["%"].sum()
                }])
                df_pie_ubic = pd.concat([mayores_2pct, fila_otras], ignore_index=True)
            else:
                df_pie_ubic = resumen_ubic.copy()

            fig_inv_det = crear_torta_2d(df_pie_ubic, "Value (ARS)", "Ubicacion_Final")
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
                "🔎 Filter by Asset or Location (e.g. BTC, Nexo, Binance):",
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
                "Live Quote", "Value (ARS)", "Value (USD)", "%"
            ]
            tabla_d = df_det_mostrar[cols_d].copy()
            tabla_d.columns = [
                "Category", "Asset", "Location", "Quantity",
                "Live Quote Used", "Value (ARS)", "Value (USD)", "%"
            ]
            tabla_d["Value (ARS)"] = tabla_d["Value (ARS)"].apply(lambda x: f"{x:,.0f} ARS")
            tabla_d["Value (USD)"] = tabla_d["Value (USD)"].apply(lambda x: f"{x:,.2f} USD")
            tabla_d["%"] = tabla_d["%"].apply(lambda x: f"{x:.1f}%")

            if filtro_sel != "All (show all)" and not df_det_mostrar.empty:
                sub_f_ars = df_det_mostrar["Value (ARS)"].sum()
                sub_f_usd = df_det_mostrar["Value (USD)"].sum()
                sub_f_pct = (sub_f_ars / total_patrimonio_ars) * 100 if total_patrimonio_ars > 0 else 0.0
                cant_f_total = df_det_mostrar["Quantity_Num"].sum()
                es_mismo_activo = df_det_mostrar["Asset"].nunique() == 1
                cant_f_str = formatear_cant(cant_f_total) if es_mismo_activo else f"{len(df_det_mostrar)} items"

                fila_subtotal = pd.DataFrame([{
                    "Category": "SUBTOTAL",
                    "Asset": filtro_sel,
                    "Location": "Filtered total",
                    "Quantity": cant_f_str,
                    "Live Quote Used": "—",
                    "Value (ARS)": f"{sub_f_ars:,.0f} ARS",
                    "Value (USD)": f"{sub_f_usd:,.2f} USD",
                    "%": f"{sub_f_pct:.1f}%"
                }])
                tabla_d = pd.concat([tabla_d, fila_subtotal], ignore_index=True)

                st.markdown(f"""
                <div style="background-color: #F3E8FF; border: 1.5px solid #C084FC; border-left: 6px solid #7E22CE;
                            border-radius: 12px; padding: 10px 14px; margin-bottom: 10px; color: #4A235A; font-size: 0.98rem;">
                    <b>Subtotal ({filtro_sel}):</b> <b>{sub_f_usd:,.2f} USD</b> &nbsp;|&nbsp;
                    <b>{sub_f_ars:,.0f} ARS</b> &nbsp;|&nbsp;
                    <b>{sub_f_pct:.1f}%</b> of total net worth
                </div>
                """, unsafe_allow_html=True)

            st.dataframe(tabla_d, use_container_width=True, hide_index=True)

activar_interactividad_avanzada(
    datos.get('categorias_costos', []),
    datos.get('categorias_ingresos', []),
    datos.get('ubicaciones_guardadas', []),
    tooltip_cant_actual
)
