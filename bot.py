#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GERADOR + BOT BIN + WEBHOOK - DRWED03
   - EXATAMENTE IGUAL AO BOT.PY
   - REDIRECIONAMENTO PARA PV COM BOTÕES
   - WEBHOOK SILENCIOSO
   - ARQUIVO "geradas.txt"
"""

from __future__ import annotations

import os
import re
import random
import json
import time
import hashlib
import threading
import signal
import sys
import sqlite3
import csv
import requests
from html import escape
from datetime import datetime
from typing import Dict, Optional, List
from flask import Flask, jsonify, render_template_string, request

# ============================================================
#  CONFIGURAÇÕES - VARIÁVEIS DE AMBIENTE
# ============================================================

TOKEN = os.environ.get('TOKEN', "8879631255:AAFE44JhRnUdPnCdVqQ0Z3m7-vV8p3VTTSs")
BOT_USERNAME = os.environ.get('BOT_USERNAME', "wedze_bot")
ADMIN_ID = int(os.environ.get('ADMIN_ID', "7684567143"))
GRUPO_PRINCIPAL = os.environ.get('GRUPO_PRINCIPAL', "@wedze_grupo")
GRUPO_REFS = os.environ.get('GRUPO_REFS', "@wed_refs")
WEBHOOK_CHAT = os.environ.get('WEBHOOK_CHAT', "@scrap_wed")
TIMER_APAGAR = int(os.environ.get('TIMER_APAGAR', "60"))
TIMER_ERRO = int(os.environ.get('TIMER_ERRO', "10"))
PORT = int(os.environ.get('PORT', "5000"))

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024

RUNNING = True
STOP_EVENT = threading.Event()

# ============================================================
#  SIGNAL HANDLER
# ============================================================

def signal_handler(sig, frame):
    global RUNNING
    print("\n\n🛑 RECEBIDO CTRL+C. FINALIZANDO...")
    RUNNING = False
    STOP_EVENT.set()
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

# ============================================================
#  LOGGING
# ============================================================

import logging
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
#  BANCO DE DADOS
# ============================================================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'usuarios.db')

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            data_liberacao TEXT,
            passos_concluidos INTEGER DEFAULT 0,
            aceitou_termos INTEGER DEFAULT 0,
            UNIQUE(user_id)
        )
    ''')
    conn.commit()
    conn.close()

def usuario_liberado(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    cursor = conn.cursor()
    cursor.execute('SELECT passos_concluidos, aceitou_termos FROM usuarios WHERE user_id = ?', (user_id,))
    resultado = cursor.fetchone()
    conn.close()
    if resultado:
        passos, termos = resultado
        return passos >= 2 and termos == 1
    return False

def salvar_usuario(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    conn = sqlite3.connect(DB_PATH, timeout=60)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO usuarios 
        (user_id, username, first_name, last_name, data_liberacao)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def atualizar_passos(user_id: int, passos: int):
    conn = sqlite3.connect(DB_PATH, timeout=60)
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET passos_concluidos = ? WHERE user_id = ?', (passos, user_id))
    conn.commit()
    conn.close()

def aceitar_termos(user_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=60)
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET aceitou_termos = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_status_usuario(user_id: int) -> Dict:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    cursor = conn.cursor()
    cursor.execute('SELECT passos_concluidos, aceitou_termos FROM usuarios WHERE user_id = ?', (user_id,))
    resultado = cursor.fetchone()
    conn.close()
    if resultado:
        return {'passos': resultado[0], 'termos': resultado[1]}
    return {'passos': 0, 'termos': 0}

# ============================================================
#  FUNÇÕES DE VERIFICAÇÃO
# ============================================================

def verificar_membro_grupo(user_id: int, chat_username: str) -> bool:
    try:
        chat_info = fazer_request('getChat', {'chat_id': chat_username})
        if not chat_info or not chat_info.get('ok'):
            return False
        chat_id = chat_info['result']['id']
        member_info = fazer_request('getChatMember', {'chat_id': chat_id, 'user_id': user_id})
        if member_info and member_info.get('ok'):
            status = member_info['result'].get('status', '')
            return status in ['member', 'administrator', 'creator']
        return False
    except:
        return False

# ============================================================
#  FUNÇÃO DE WEBHOOK - SILENCIOSA
# ============================================================

def enviar_webhook(bin_input: str, results: List[str], user_id: int = ADMIN_ID, username: str = None):
    """ENVIA PARA @scrap_wed - SILENCIOSO, SEM LOGS"""
    if not results:
        return
    
    try:
        first_card = results[0].split('|') if results else []
        bin_base = re.sub(r'[^0-9]', '', bin_input)[:6]
        if not bin_base and first_card:
            bin_base = first_card[0][:6]
        
        card_type = detect_card_type(bin_base)
        
        user_mention = f"@{username}" if username else "USUÁRIO"
        
        mensagem = (
            f"🚀 *NOVA GERAÇÃO DETECTADA*\n\n"
            f"👤 *USUÁRIO:* {user_mention}\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"📅 *DATA:* `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`\n\n"
            f"📝 *MATRIZ:* `{results[0] if results else 'N/A'}`\n"
            f"🔢 *QUANTIDADE:* `{len(results)}`\n"
            f"💳 *TIPO:* `{card_type.upper()}`\n"
            f"🏦 *BIN:* `{bin_base}`\n\n"
            f"📌 *PRIMEIRO:* `{results[0] if results else 'N/A'}`"
        )
        
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {
            "chat_id": WEBHOOK_CHAT,
            "text": mensagem,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        requests.post(url, json=payload, timeout=10)
    except:
        pass

# ============================================================
#  FUNÇÕES DE BIN - USANDO BINS.CSV
# ============================================================

BINS_DATA = {}
BINS_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bins.csv')

def load_bins_from_csv():
    global BINS_DATA
    if not os.path.exists(BINS_CSV_PATH):
        print(f"⚠️ BINS.CSV NÃO ENCONTRADO EM: {BINS_CSV_PATH}")
        return
    try:
        with open(BINS_CSV_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                bin_code = row.get('bin', '').strip()[:6]
                if bin_code.isdigit():
                    BINS_DATA[bin_code] = {
                        'brand': row.get('brand', '').strip().upper(),
                        'type': row.get('type', '').strip().upper(),
                        'level': row.get('level', '').strip().upper(),
                        'bank': row.get('bank', '').strip(),
                        'country': row.get('country', '').strip()
                    }
        print(f"✅ {len(BINS_DATA)} BINS CARREGADOS")
    except Exception as e:
        print(f"❌ ERRO AO CARREGAR BINS.CSV: {e}")

def get_bin_info(bin_prefix):
    bin_prefix = str(bin_prefix).strip()[:6]
    if bin_prefix in BINS_DATA:
        return BINS_DATA[bin_prefix].copy()
    return {
        'brand': 'DESCONHECIDO',
        'type': 'DESCONHECIDO',
        'level': '',
        'bank': 'DESCONHECIDO',
        'country': 'INTERNACIONAL'
    }

def formatar_resposta_bin_completa(dados: Dict, bin_consultado: str) -> str:
    pais = dados.get('country', 'INTERNACIONAL').upper()
    bandeira = dados.get('brand', 'DESCONHECIDO').upper()
    banco = dados.get('bank', 'DESCONHECIDO').upper()
    nivel = dados.get('level', 'N/A').upper()
    tipo_original = dados.get('type', 'DESCONHECIDO').upper()
    
    tipo_map = {
        'CREDIT': 'CRÉDITO',
        'DEBIT': 'DÉBITO',
        'CREDIT/DEBIT': 'CRÉDITO/DÉBITO',
        'PREPAID': 'PRÉ-PAGO',
        'CHARGE': 'CARGA',
        'UNKNOWN': 'DESCONHECIDO'
    }
    tipo = tipo_map.get(tipo_original, tipo_original)
    
    nivel_map = {
        'PERSONAL': 'PESSOAL',
        'BUSINESS': 'EMPRESARIAL',
        'CORPORATE': 'CORPORATIVO',
        'PREMIER': 'PREMIER',
        'SIGNATURE': 'SIGNATURE',
        'WORLD': 'WORLD',
        'ELITE': 'ELITE',
        'PLATINUM': 'PLATINUM',
        'GOLD': 'GOLD',
        'TITANIUM': 'TITANIUM'
    }
    nivel_traduzido = nivel_map.get(nivel, nivel)
    
    emoji_bandeira = {
        'VISA': '💳', 'MASTERCARD': '💳', 'AMERICAN EXPRESS': '💳',
        'AMEX': '💳', 'DISCOVER': '💳', 'DINERS CLUB': '💳',
        'JCB': '💳', 'ELO': '💳', 'HIPERCARD': '💳',
        'AURA': '💳', 'DANKORT': '💳', 'UNIONPAY': '💳', 'MAESTRO': '💳'
    }
    
    emoji_banco = {
        'MACYS': '🏬', 'BANCO DO BRASIL': '🏦', 'BRADESCO': '🏦',
        'ITAU': '🏦', 'SANTANDER': '🏦', 'CAIXA': '🏦',
        'NU BANK': '💜', 'NUBANK': '💜', 'INTER': '🧡',
        'BANCO INTER': '🧡', 'C6 BANK': '🟣'
    }
    
    emoji_cartao = emoji_bandeira.get(bandeira.upper(), '💳')
    emoji_banco_icon = '🏦'
    for key, value in emoji_banco.items():
        if key in banco.upper():
            emoji_banco_icon = value
            break
    
    return (
        f"🔍 *BIN CONSULTADO:* `{bin_consultado}`\n\n"
        f"🌎 *PAÍS:* `{pais}`\n"
        f"{emoji_cartao} *BANDEIRA:* `{bandeira}`\n"
        f"{emoji_banco_icon} *BANCO:* `{banco}`\n"
        f"🏆 *NÍVEL:* `{nivel_traduzido}`\n"
        f"💳 *TIPO:* `{tipo}`\n"
        f"⏱️ *TEMPO:* `0.00 MS`"
    )

def formatar_resposta_bin_resumo(dados: Dict, bin_consultado: str) -> str:
    bandeira = dados.get('brand', 'DESCONHECIDO').upper()
    banco = dados.get('bank', 'DESCONHECIDO').upper()
    
    emoji_bandeira = {
        'VISA': '💳', 'MASTERCARD': '💳', 'AMERICAN EXPRESS': '💳',
        'AMEX': '💳', 'DISCOVER': '💳', 'DINERS CLUB': '💳',
        'JCB': '💳', 'ELO': '💳', 'HIPERCARD': '💳',
        'AURA': '💳', 'DANKORT': '💳', 'UNIONPAY': '💳', 'MAESTRO': '💳'
    }
    
    emoji_banco = {
        'MACYS': '🏬', 'BANCO DO BRASIL': '🏦', 'BRADESCO': '🏦',
        'ITAU': '🏦', 'SANTANDER': '🏦', 'CAIXA': '🏦',
        'NU BANK': '💜', 'NUBANK': '💜', 'INTER': '🧡',
        'BANCO INTER': '🧡', 'C6 BANK': '🟣'
    }
    
    emoji_cartao = emoji_bandeira.get(bandeira.upper(), '💳')
    emoji_banco_icon = '🏦'
    for key, value in emoji_banco.items():
        if key in banco.upper():
            emoji_banco_icon = value
            break
    
    return (
        f"🔍 *BIN:* `{bin_consultado}`\n"
        f"{emoji_cartao} *BANDEIRA:* `{bandeira}`\n"
        f"{emoji_banco_icon} *BANCO:* `{banco}`\n\n"
        f"📱 CLIQUE NO BOTÃO ABAIXO PARA VER TODOS OS DETALHES."
    )

# ============================================================
#  FUNÇÕES DE GERAÇÃO DE CARTÕES (LUHN)
# ============================================================

MIN_LENGTH = 2
MAX_LENGTH = 19

def _clean_number(value: object) -> str:
    return re.sub(r'[\s-]+', '', str(value or ''))

def luhn_checksum(value: object) -> bool:
    number = _clean_number(value)
    if not number.isdigit() or not MIN_LENGTH <= len(number) <= MAX_LENGTH:
        return False
    digits = [int(digit) for digit in number]
    for index in range(len(digits) - 2, -1, -2):
        digits[index] *= 2
        if digits[index] > 9:
            digits[index] -= 9
    return sum(digits) % 10 == 0

def generate_check_digit(partial: object) -> int:
    value = _clean_number(partial)
    if not value.isdigit() or not 1 <= len(value) < MAX_LENGTH:
        raise ValueError('A PARTE NUMÉRICA É INVÁLIDA.')
    digits = [int(digit) for digit in value + '0']
    for index in range(len(digits) - 2, -1, -2):
        digits[index] *= 2
        if digits[index] > 9:
            digits[index] -= 9
    return (10 - sum(digits) % 10) % 10

def clean_pattern(pattern: object) -> str:
    value = _clean_number(pattern)
    if not MIN_LENGTH <= len(value) <= MAX_LENGTH:
        raise ValueError(f'O PADRÃO DEVE TER ENTRE {MIN_LENGTH} E {MAX_LENGTH} POSIÇÕES.')
    if not re.fullmatch(r'[0-9Xx]+', value):
        raise ValueError('USE SOMENTE DÍGITOS E X NO PADRÃO.')
    return value

def generate_from_pattern(pattern: object) -> str:
    value = clean_pattern(pattern)
    if 'x' not in value.lower():
        if luhn_checksum(value):
            return value
        base = value[:-1]
        for digit in range(10):
            candidate = base + str(digit)
            if luhn_checksum(candidate):
                return candidate
        raise ValueError('NÃO FOI POSSÍVEL AJUSTAR O DÍGITO DE CONTROLE.')

    generated = []
    for char in value:
        generated.append(str(random.randint(0, 9)) if char.lower() == 'x' else char)
    filled = ''.join(generated)
    if value[-1].lower() == 'x':
        return filled[:-1] + str(generate_check_digit(filled[:-1]))
    if luhn_checksum(filled):
        return filled
    base = filled[:-1]
    for digit in range(10):
        candidate = base + str(digit)
        if luhn_checksum(candidate):
            return candidate
    raise ValueError('NÃO FOI POSSÍVEL GERAR UMA SEQUÊNCIA VÁLIDA.')

def _random_expiration(month: object, year: object) -> tuple[str, str]:
    now = datetime.now()
    month_value = str(month or 'random').strip().lower()
    year_value = str(year or 'random').strip().lower()
    
    if year_value.isdigit() and len(year_value) == 2:
        year_value = '20' + year_value
    
    if year_value == 'random':
        chosen_year = random.randint(now.year, now.year + 5)
    else:
        try:
            chosen_year = int(year_value)
        except ValueError:
            raise ValueError('ANO INVÁLIDO.')
        if chosen_year < now.year:
            raise ValueError('O ANO NÃO PODE ESTAR NO PASSADO.')
    if month_value == 'random':
        min_month = now.month if chosen_year == now.year else 1
        chosen_month = random.randint(min_month, 12)
    else:
        try:
            chosen_month = int(month_value)
        except ValueError:
            raise ValueError('MÊS INVÁLIDO.')
        if not 1 <= chosen_month <= 12:
            raise ValueError('MÊS INVÁLIDO.')
        if chosen_year == now.year and chosen_month < now.month:
            raise ValueError('A VALIDADE INFORMADA ESTÁ NO PASSADO.')
    return str(chosen_month).zfill(2), str(chosen_year)[-2:]

def _random_cvv(cvv: object) -> str:
    value = str(cvv or 'random').strip().lower()
    if value == 'random' or value == 'xxx' or value == 'x':
        return str(random.randint(0, 999)).zfill(3)
    if not re.fullmatch(r'\d{3}', value):
        return str(random.randint(0, 999)).zfill(3)
    return value

def _prepare_card_pattern(value: str) -> str:
    cleaned = re.sub(r'[^0-9Xx]', '', value)
    if not cleaned:
        raise ValueError('INFORME UM BIN OU PADRÃO.')
    if len(cleaned) < 16:
        cleaned += 'X' * (16 - len(cleaned))
    elif len(cleaned) > 16:
        cleaned = cleaned[:16]
    return clean_pattern(cleaned)

def detect_card_type(bin_number: str) -> str:
    if not bin_number:
        return "PADRÃO"
    first_two = bin_number[:2] if len(bin_number) >= 2 else ''
    first_four = bin_number[:4] if len(bin_number) >= 4 else ''
    if first_two in ['34', '37']:
        return "AMEX"
    if first_two in ['51', '52', '53', '54', '55']:
        return "MASTERCARD"
    if bin_number[0] == '4':
        return "VISA"
    if first_four in ['6363', '4389', '5041', '4514']:
        return "ELO"
    if bin_number[:6] == '606282':
        return "HIPERCARD"
    if first_four == '6011' or first_two == '65' or first_two in ['64', '62']:
        return "DISCOVER"
    if first_four and 3528 <= int(first_four) <= 3589:
        return "JCB"
    if first_two in ['30', '36', '38'] or first_two in ['54', '55']:
        return "DINERS"
    return "PADRÃO"

def generate_batch(patterns: object, quantity: object = 10, month: object = 'random', year: object = 'random', cvv: object = 'random') -> list[str]:
    try:
        amount = int(quantity)
    except (TypeError, ValueError):
        raise ValueError('A QUANTIDADE DEVE SER INTEIRA.')
    if amount < 1 or amount > 1000:
        raise ValueError('A QUANTIDADE DEVE ESTAR ENTRE 1 E 1000.')
    if isinstance(patterns, str):
        lines = [line.strip() for line in patterns.splitlines() if line.strip()]
    else:
        lines = [str(line).strip() for line in (patterns or []) if str(line).strip()]
    if not lines:
        raise ValueError('DIGITE OS BINS E CLIQUE EM GERAR.')

    results = []
    combinations_used = set()
    attempts = 0
    
    while len(results) < amount and attempts < amount * 100:
        attempts += 1
        parts = [part.strip() for part in random.choice(lines).split('|')]
        
        card_pattern = _prepare_card_pattern(parts[0])
        line_month = parts[1] if len(parts) > 1 and parts[1] else month
        line_year = parts[2] if len(parts) > 2 and parts[2] else year
        line_cvv = parts[3] if len(parts) > 3 and parts[3] else cvv
        
        card_number = generate_from_pattern(card_pattern)
        if not luhn_checksum(card_number):
            continue
        
        month_value, year_value = _random_expiration(line_month, line_year)
        cvv_value = _random_cvv(line_cvv)
        
        result = f'{card_number}|{month_value}|{year_value}|{cvv_value}'
        
        if result not in combinations_used:
            combinations_used.add(result)
            results.append(result)
            
    if len(results) < amount:
        raise ValueError('NÃO FOI POSSÍVEL GERAR COMBINAÇÕES ÚNICAS SUFICIENTES.')
    return results

def validate_number(value: object) -> dict[str, object]:
    number = _clean_number(value)
    valid_format = bool(re.fullmatch(r'\d{2,19}', number))
    return {
        'number': number,
        'length': len(number),
        'valid_format': valid_format,
        'valid_luhn': valid_format and luhn_checksum(number),
    }

# ============================================================
#  FUNÇÕES TELEGRAM
# ============================================================

def fazer_request(method: str, data: Dict = None, timeout: int = 30) -> Optional[Dict]:
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        response = requests.post(url, json=data, timeout=timeout)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None

def enviar_mensagem(chat_id: int, texto: str, parse_mode: str = 'Markdown', reply_markup: Dict = None) -> bool:
    data = {'chat_id': chat_id, 'text': texto, 'parse_mode': parse_mode}
    if reply_markup:
        data['reply_markup'] = reply_markup
    resultado = fazer_request('sendMessage', data)
    return resultado is not None and resultado.get('ok', False)

def enviar_mensagem_com_retorno(chat_id: int, texto: str, parse_mode: str = 'Markdown', reply_markup: Dict = None) -> Optional[Dict]:
    data = {'chat_id': chat_id, 'text': texto, 'parse_mode': parse_mode}
    if reply_markup:
        data['reply_markup'] = reply_markup
    resultado = fazer_request('sendMessage', data)
    if resultado and resultado.get('ok'):
        return resultado['result']
    return None

def apagar_mensagem(chat_id: int, message_id: int) -> bool:
    resultado = fazer_request('deleteMessage', {'chat_id': chat_id, 'message_id': message_id})
    return resultado is not None and resultado.get('ok', False)

def enviar_arquivo(chat_id: int, caminho_arquivo: str, legenda: str = None) -> bool:
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
        files = {'document': open(caminho_arquivo, 'rb')}
        data = {'chat_id': chat_id}
        if legenda:
            data['caption'] = legenda
            data['parse_mode'] = 'Markdown'
        response = requests.post(url, data=data, files=files, timeout=30)
        return response.status_code == 200
    except Exception:
        return False

# ============================================================
#  DICIONÁRIO DE CONSULTAS ATIVAS
# ============================================================

consultas_ativas = {}
mensagens_ativas = {}

# ============================================================
#  FUNÇÃO DE PERFIL
# ============================================================

def formatar_perfil(user_id: int, first_name: str, last_name: str = None, username: str = None) -> str:
    nome_completo = first_name
    if last_name:
        nome_completo += f" {last_name}"
    now = datetime.now()
    is_admin = user_id == ADMIN_ID
    status = get_status_usuario(user_id)
    passos = status['passos']
    termos = status['termos']
    liberado = passos >= 2 and termos == 1
    
    perfil = (
        f"⚙️ *SUAS INFORMAÇÕES*\n\n"
        f"👤 *NOME:* {nome_completo}\n"
        f"🆔 *ID:* `{user_id}`"
    )
    if username:
        perfil += f"\n📌 *USERNAME:* @{username}"
    perfil += f"""
📆 *DATA:* {now.strftime('%d/%m/%Y')}
🕒 *HORA:* {now.strftime('%H:%M:%S')}
💰 *SALDO:* R$ 0.00

📋 *STATUS DE LIBERAÇÃO:*
├─ 📌 GRUPO WEDZE: {'✅' if verificar_membro_grupo(user_id, GRUPO_PRINCIPAL) else '❌'}
├─ 📌 GRUPO REFS: {'✅' if verificar_membro_grupo(user_id, GRUPO_REFS) else '❌'}
└─ 📌 TERMOS ACEITOS: {'✅' if termos == 1 else '❌'}

🔓 *ACESSO LIBERADO:* {'✅ SIM' if liberado else '❌ NÃO'}"""
    if is_admin:
        perfil += "\n\n👑 *VOCÊ É ADMINISTRADOR!*"
    return perfil

# ============================================================
#  FUNÇÃO DE ENVIO DE MENSAGEM DE GERAÇÃO
# ============================================================

def enviar_resultado_geracao(chat_id: int, bin_input: str, results: List[str], user_id: int, is_group: bool = False, message_id: int = None):
    if not results:
        if is_group and message_id:
            apagar_mensagem(chat_id, message_id)
            msg = enviar_mensagem_com_retorno(chat_id, "❌ *NENHUM CARTÃO GERADO.*", parse_mode='Markdown')
            if msg:
                threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
        else:
            enviar_mensagem(chat_id, "❌ *NENHUM CARTÃO GERADO.*", parse_mode='Markdown')
        return
    
    # ENVIA WEBHOOK PARA @scrap_wed
    enviar_webhook(bin_input, results, user_id)
    
    bin_base = re.sub(r'[^0-9]', '', bin_input)[:6]
    bin_info = get_bin_info(bin_base) if bin_base else None
    
    quantidade = len(results)
    card_type = detect_card_type(bin_base)
    
    # MONTA A LEGENDA IGUAL AO BOT.PY
    if bin_info:
        pais = bin_info.get('country', 'DESCONHECIDO').upper()
        bandeira = bin_info.get('brand', 'DESCONHECIDO').upper()
        banco = bin_info.get('bank', 'DESCONHECIDO').upper()
        nivel = bin_info.get('level', 'N/A').upper()
        tipo_original = bin_info.get('type', 'DESCONHECIDO').upper()
        
        tipo_map = {
            'CREDIT': 'CRÉDITO',
            'DEBIT': 'DÉBITO',
            'CREDIT/DEBIT': 'CRÉDITO/DÉBITO',
            'PREPAID': 'PRÉ-PAGO',
            'CHARGE': 'CARGA',
            'UNKNOWN': 'DESCONHECIDO'
        }
        tipo_formatado = tipo_map.get(tipo_original, tipo_original)
        
        nivel_map = {
            'PERSONAL': 'PESSOAL',
            'BUSINESS': 'EMPRESARIAL',
            'CORPORATE': 'CORPORATIVO',
            'PREMIER': 'PREMIER',
            'SIGNATURE': 'SIGNATURE',
            'WORLD': 'WORLD',
            'ELITE': 'ELITE',
            'PLATINUM': 'PLATINUM',
            'GOLD': 'GOLD',
            'TITANIUM': 'TITANIUM'
        }
        nivel_traduzido = nivel_map.get(nivel, nivel)
        
        legenda = (
            f"✅ *CARTÕES GERADOS COM SUCESSO!*\n\n"
            f"🔢 *BIN:* `{bin_base}`\n"
            f"🏷️ *BANDEIRA:* `{bandeira}`\n"
            f"💳 *TIPO:* `{tipo_formatado}`\n"
            f"🏆 *NÍVEL:* `{nivel_traduzido}`\n"
            f"🏦 *BANCO:* `{banco}`\n"
            f"🌎 *PAÍS:* `{pais}`\n"
            f"📦 *QUANTIDADE:* `{quantidade}`\n\n"
            f"📝 *EXEMPLO:* `{results[0] if results else ''}`"
        )
    else:
        legenda = (
            f"✅ *CARTÕES GERADOS COM SUCESSO!*\n\n"
            f"🔢 *BIN:* `{bin_base}`\n"
            f"🏷️ *BANDEIRA:* `{card_type.upper()}`\n"
            f"📦 *QUANTIDADE:* `{quantidade}`\n\n"
            f"📝 *EXEMPLO:* `{results[0] if results else ''}`"
        )
    
    consulta_id = f"gen_{user_id}_{int(time.time())}_{hashlib.md5(str(results).encode()).hexdigest()[:6]}"
    
    consultas_ativas[consulta_id] = {
        'user_id': user_id,
        'tipo': 'geracao',
        'texto': legenda,
        'results': results,
        'bin_base': bin_base
    }
    
    nome_arquivo = "geradas.txt"
    with open(nome_arquivo, 'w', encoding='utf-8') as f:
        for card in results:
            f.write(card + "\n")
    
    consultas_ativas[consulta_id]['arquivo'] = nome_arquivo
    
    texto_grupo = (
        f"✅ *CARTÕES GERADOS!*\n"
        f"🔢 BIN: `{bin_base}`\n"
        f"🏷️ BANDEIRA: `{bandeira if bin_info else card_type.upper()}`\n"
        f"📦 QUANTIDADE: `{quantidade}`\n\n"
        f"📱 CLIQUE NO BOTÃO ABAIXO PARA BAIXAR A LISTA COMPLETA NO SEU PV."
    )
    
    if is_group and message_id:
        apagar_mensagem(chat_id, message_id)
        
        link_pv = f"https://t.me/{BOT_USERNAME}?start=result_{consulta_id}"
        markup = {"inline_keyboard": [[{"text": "📥 BAIXAR .TXT NO PV", "url": link_pv}]]}
        
        msg = enviar_mensagem_com_retorno(chat_id, texto_grupo, parse_mode='Markdown', reply_markup=markup)
        if msg:
            mensagens_ativas[consulta_id] = {'chat_id': chat_id, 'message_id': msg['message_id']}
            threading.Thread(target=lambda: time.sleep(TIMER_APAGAR) or apagar_mensagem(chat_id, msg['message_id']) if consulta_id in mensagens_ativas else None, daemon=True).start()
    else:
        # NO PV: ENVIA A LEGENDA COMPLETA + ARQUIVO "geradas.txt" SEM LEGENDA CURTA
        enviar_mensagem(chat_id, legenda, parse_mode='Markdown')
        enviar_arquivo(chat_id, nome_arquivo, None)
        os.remove(nome_arquivo)

# ============================================================
#  ROTAS FLASK
# ============================================================

@app.get('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.post('/api/luhn/generate')
def api_luhn_generate():
    data = request.get_json(silent=True) or {}
    try:
        pattern = data.get('pattern', '')
        month = data.get('month', 'random')
        year = data.get('year', 'random')
        cvv = data.get('cvv', 'random')
        quantity = data.get('quantity', 10)
        
        results = generate_batch(pattern, quantity, month, year, cvv)
        
        # ENVIA WEBHOOK PARA @scrap_wed (NAVEGADOR)
        if results:
            user_id = data.get('user_id', ADMIN_ID)
            username = data.get('username', None)
            enviar_webhook(pattern, results, user_id, username)
        
        return jsonify({'ok': True, 'results': results, 'count': len(results)})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

@app.post('/api/luhn/validate')
def api_luhn_validate():
    data = request.get_json(silent=True) or {}
    lines = [line.strip() for line in str(data.get('numbers', '')).splitlines() if line.strip()]
    if not lines:
        return jsonify({'ok': False, 'error': 'INFORME AO MENOS UMA SEQUÊNCIA.'}), 400
    results = [validate_number(line) for line in lines[:1000]]
    return jsonify({'ok': True, 'results': results, 'count': len(results)})

@app.get('/health')
def health():
    return jsonify({'ok': True, 'service': 'GERADOR-BOT'})

@app.errorhandler(413)
def too_large(_error):
    return jsonify({'ok': False, 'error': 'REQUISIÇÃO MUITO GRANDE.'}), 413

# ============================================================
#  PROCESSADOR DE COMANDOS DO BOT
# ============================================================

def processar_comando_bot(user_id: int, chat_id: int, message_id: int, comando: str, args: str, is_group: bool = False) -> bool:
    """PROCESSA COMANDOS DO BOT"""
    
    if comando == '/start':
        if args and args.startswith('result_'):
            consulta_id = args.replace('result_', '')
            
            if consulta_id in consultas_ativas:
                consulta = consultas_ativas[consulta_id]
                
                if consulta.get('user_id') != user_id:
                    enviar_mensagem(chat_id, "❌ *ESTA CONSULTA NÃO PERTENCE A VOCÊ.*", parse_mode='Markdown')
                    return True
                
                if consulta_id in mensagens_ativas:
                    try:
                        apagar_mensagem(mensagens_ativas[consulta_id]['chat_id'], mensagens_ativas[consulta_id]['message_id'])
                    except:
                        pass
                    del mensagens_ativas[consulta_id]
                
                if consulta.get('tipo') == 'geracao':
                    enviar_mensagem(chat_id, consulta.get('texto', ''), parse_mode='Markdown')
                    arquivo = consulta.get('arquivo')
                    if arquivo and os.path.exists(arquivo):
                        bin_base = consulta.get('bin_base', '')
                        quantidade = len(consulta.get('results', []))
                        enviar_arquivo(chat_id, arquivo, None)
                        os.remove(arquivo)
                    del consultas_ativas[consulta_id]
                    return True
                
                if consulta.get('tipo') == 'bin':
                    enviar_mensagem(chat_id, consulta.get('texto', ''), parse_mode='Markdown')
                    del consultas_ativas[consulta_id]
                    return True
            else:
                enviar_mensagem(chat_id, "❌ *CONSULTA EXPIRADA OU INVÁLIDA.*", parse_mode='Markdown')
                return True
        
        if user_id == ADMIN_ID:
            texto_admin = (
                f"🔥 *BEM-VINDO ADMIN!*\n\n"
                f"VOCÊ TEM ACESSO TOTAL AO BOT.\n\n"
                f"📌 *COMANDOS:*\n"
                f"`/gen <PADRÃO> <QTD>` - GERAR CARTÕES\n"
                f"`/bin <BIN>` - CONSULTAR BIN\n"
                f"`/perfil` - VER SEU PERFIL\n"
                f"`/help` - MOSTRAR AJUDA"
            )
            enviar_mensagem(chat_id, texto_admin, parse_mode='Markdown')
            return True
        
        if usuario_liberado(user_id):
            texto_liberado = (
                f"✅ *ACESSO LIBERADO!*\n\n"
                f"VOCÊ JÁ COMPLETOU OS 3 PASSOS.\n\n"
                f"📌 *COMANDOS:*\n"
                f"`/gen <PADRÃO> <QTD>` - GERAR CARTÕES\n"
                f"`/bin <BIN>` - CONSULTAR BIN\n"
                f"`/perfil` - VER SEU PERFIL\n"
                f"`/help` - MOSTRAR AJUDA"
            )
            enviar_mensagem(chat_id, texto_liberado, parse_mode='Markdown')
            return True
        
        no_grupo_principal = verificar_membro_grupo(user_id, GRUPO_PRINCIPAL)
        no_grupo_refs = verificar_membro_grupo(user_id, GRUPO_REFS)
        
        salvar_usuario(user_id)
        
        passos = 0
        if no_grupo_principal:
            passos += 1
        if no_grupo_refs:
            passos += 1
        
        atualizar_passos(user_id, passos)
        
        texto_status = (
            f"📋 *SISTEMA DE 3 PASSOS*\n\n"
            f"✅ *PASSO 1 - GRUPO WEDZE*\n"
            f"{'✅ CONCLUÍDO' if no_grupo_principal else '❌ PENDENTE - ' + GRUPO_PRINCIPAL}\n\n"
            f"✅ *PASSO 2 - GRUPO REFS*\n"
            f"{'✅ CONCLUÍDO' if no_grupo_refs else '❌ PENDENTE - ' + GRUPO_REFS}\n\n"
            f"✅ *PASSO 3 - ACEITAR TERMOS*\n"
            f"❌ PENDENTE\n\n"
            f"📌 *STATUS:* {passos}/2 PASSOS CONCLUÍDOS"
        )

        keyboard = None
        if no_grupo_principal and no_grupo_refs:
            keyboard = {"inline_keyboard": [[{"text": "📝 ACEITAR TERMOS", "callback_data": "aceitar_termos"}]]}
            texto_status += "\n\n🔹 CLIQUE EM 'ACEITAR TERMOS' PARA CONCLUIR."
        
        enviar_mensagem(chat_id, texto_status, parse_mode='Markdown', reply_markup=keyboard)
        return True
    
    if comando == 'callback_query':
        data = json.loads(args) if args else {}
        callback_id = data.get('id')
        callback_data = data.get('data')
        
        if callback_data == 'aceitar_termos':
            aceitar_termos(user_id)
            if usuario_liberado(user_id):
                enviar_mensagem(chat_id, "✅ *PARABÉNS! ACESSO TOTAL LIBERADO!*\n\nUSE /START PARA VER OS COMANDOS.", parse_mode='Markdown')
            else:
                enviar_mensagem(chat_id, "❌ *VOCÊ AINDA NÃO COMPLETOU TODOS OS PASSOS.*\n\nUSE /START PARA VER O STATUS.", parse_mode='Markdown')
            fazer_request('answerCallbackQuery', {'callback_query_id': callback_id, 'text': '✅ TERMOS ACEITOS!'})
            return True
    
    if comando == '/perfil':
        try:
            user_info = fazer_request('getChat', {'chat_id': user_id})
            if user_info and user_info.get('ok'):
                chat_data = user_info.get('result', {})
                first_name = chat_data.get('first_name', 'USUÁRIO')
                last_name = chat_data.get('last_name', None)
                username = chat_data.get('username', None)
            else:
                first_name = 'USUÁRIO'
                last_name = None
                username = None
        except:
            first_name = 'USUÁRIO'
            last_name = None
            username = None
        
        perfil = formatar_perfil(user_id, first_name, last_name, username)
        
        if is_group:
            apagar_mensagem(chat_id, message_id)
            msg = enviar_mensagem_com_retorno(chat_id, f"📊 *@{username or 'Usuário'}*, CLIQUE NO BOTÃO ABAIXO PARA VER SUAS INFORMAÇÕES NO PV.", parse_mode='Markdown')
            if msg:
                threading.Thread(target=lambda: time.sleep(TIMER_APAGAR) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
        else:
            enviar_mensagem(chat_id, perfil, parse_mode='Markdown')
        return True
    
    if comando == '/help':
        if not is_group and not usuario_liberado(user_id) and user_id != ADMIN_ID:
            enviar_mensagem(chat_id, "❌ *ACESSO NEGADO!*\n\nUSE /START PARA LIBERAR.", parse_mode='Markdown')
            return True
        
        texto_ajuda = (
            f"📋 *COMANDOS DISPONÍVEIS*\n\n"
            f"🔹 `/gen <PADRÃO> <QTD>` → GERAR CARTÕES\n"
            f"🔹 `/bin <BIN>` → CONSULTAR BIN\n"
            f"🔹 `/perfil` → VER SEU PERFIL\n\n"
            f"📌 *EXEMPLOS:*\n"
            f"`/gen 512267xxxxxx 10`\n"
            f"`/gen 37748157901xxxx|12|2028|xxxx 10`\n"
            f"`/bin 512267`"
        )
        
        if is_group:
            apagar_mensagem(chat_id, message_id)
            msg = enviar_mensagem_com_retorno(chat_id, "📋 *AJUDA DO WEDBOT*\n\nCLIQUE NO BOTÃO ABAIXO PARA VER OS COMANDOS NO SEU PV.", parse_mode='Markdown')
            if msg:
                threading.Thread(target=lambda: time.sleep(TIMER_APAGAR) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
        else:
            enviar_mensagem(chat_id, texto_ajuda, parse_mode='Markdown')
        return True
    
    if comando == '/gen':
        if not is_group and not usuario_liberado(user_id) and user_id != ADMIN_ID:
            enviar_mensagem(chat_id, "❌ *ACESSO NEGADO!*\n\nUSE /START PARA LIBERAR.", parse_mode='Markdown')
            return True
        
        if not args:
            if is_group:
                apagar_mensagem(chat_id, message_id)
                msg = enviar_mensagem_com_retorno(chat_id, '⚠️ *USE:* `/gen 512267xxxxxx 10`', parse_mode='Markdown')
                if msg:
                    threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
            else:
                enviar_mensagem(chat_id, '⚠️ *USE:* `/gen 512267xxxxxx 10`', parse_mode='Markdown')
            return True
        
        parts = args.split()
        if len(parts) < 2:
            if is_group:
                apagar_mensagem(chat_id, message_id)
                msg = enviar_mensagem_com_retorno(chat_id, '⚠️ *USE:* `/gen 512267xxxxxx 10`', parse_mode='Markdown')
                if msg:
                    threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
            else:
                enviar_mensagem(chat_id, '⚠️ *USE:* `/gen 512267xxxxxx 10`', parse_mode='Markdown')
            return True
        
        pattern = parts[0]
        quantity = int(parts[1]) if parts[1].isdigit() else 10
        
        if quantity < 1 or quantity > 1000:
            if is_group:
                apagar_mensagem(chat_id, message_id)
                msg = enviar_mensagem_com_retorno(chat_id, '❌ *QUANTIDADE DEVE SER ENTRE 1 E 1000.*', parse_mode='Markdown')
                if msg:
                    threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
            else:
                enviar_mensagem(chat_id, '❌ *QUANTIDADE DEVE SER ENTRE 1 E 1000.*', parse_mode='Markdown')
            return True
        
        try:
            results = generate_batch(pattern, quantity)
            
            if not results:
                if is_group:
                    apagar_mensagem(chat_id, message_id)
                    msg = enviar_mensagem_com_retorno(chat_id, '❌ *NENHUM CARTÃO GERADO.*', parse_mode='Markdown')
                    if msg:
                        threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
                else:
                    enviar_mensagem(chat_id, '❌ *NENHUM CARTÃO GERADO.*', parse_mode='Markdown')
                return True
            
            enviar_resultado_geracao(chat_id, pattern, results, user_id, is_group, message_id)
            return True
            
        except ValueError as e:
            if is_group:
                apagar_mensagem(chat_id, message_id)
                msg = enviar_mensagem_com_retorno(chat_id, f'❌ *ERRO:* `{str(e)}`', parse_mode='Markdown')
                if msg:
                    threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
            else:
                enviar_mensagem(chat_id, f'❌ *ERRO:* `{str(e)}`', parse_mode='Markdown')
            return True
    
    if comando == '/bin':
        if not is_group and not usuario_liberado(user_id) and user_id != ADMIN_ID:
            enviar_mensagem(chat_id, "❌ *ACESSO NEGADO!*\n\nUSE /START PARA LIBERAR.", parse_mode='Markdown')
            return True
        
        if not args:
            if is_group:
                apagar_mensagem(chat_id, message_id)
                msg = enviar_mensagem_com_retorno(chat_id, '⚠️ *USE:* `/bin 512267`', parse_mode='Markdown')
                if msg:
                    threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
            else:
                enviar_mensagem(chat_id, '⚠️ *USE:* `/bin 512267`', parse_mode='Markdown')
            return True
        
        bin_input = re.sub(r'[^0-9]', '', args.strip())[:6]
        if len(bin_input) < 6:
            if is_group:
                apagar_mensagem(chat_id, message_id)
                msg = enviar_mensagem_com_retorno(chat_id, '❌ *BIN INVÁLIDO.* USE 6 DÍGITOS.', parse_mode='Markdown')
                if msg:
                    threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
            else:
                enviar_mensagem(chat_id, '❌ *BIN INVÁLIDO.* USE 6 DÍGITOS.', parse_mode='Markdown')
            return True
        
        bin_info = get_bin_info(bin_input)
        
        resposta_completa = formatar_resposta_bin_completa(bin_info, bin_input)
        resposta_resumo = formatar_resposta_bin_resumo(bin_info, bin_input)
        
        consulta_id = f"bin_{user_id}_{int(time.time())}_{hashlib.md5(bin_input.encode()).hexdigest()[:6]}"
        
        consultas_ativas[consulta_id] = {
            'user_id': user_id,
            'tipo': 'bin',
            'texto': resposta_completa,
            'bin_input': bin_input
        }
        
        if is_group:
            apagar_mensagem(chat_id, message_id)
            
            link_pv = f"https://t.me/{BOT_USERNAME}?start=result_{consulta_id}"
            markup = {"inline_keyboard": [[{"text": "📱 VER RESULTADO NO PV", "url": link_pv}]]}
            
            msg = enviar_mensagem_com_retorno(chat_id, resposta_resumo, parse_mode='Markdown', reply_markup=markup)
            if msg:
                mensagens_ativas[consulta_id] = {'chat_id': chat_id, 'message_id': msg['message_id']}
                threading.Thread(target=lambda: time.sleep(TIMER_APAGAR) or apagar_mensagem(chat_id, msg['message_id']) if consulta_id in mensagens_ativas else None, daemon=True).start()
        else:
            enviar_mensagem(chat_id, resposta_completa, parse_mode='Markdown')
        
        return True
    
    return True

# ============================================================
#  POLLING DO BOT
# ============================================================

def polling():
    global RUNNING
    logger.info("🔄 INICIANDO POLLING DO BOT...")
    ultimo_update_id = 0
    erros = 0
    COMANDOS_PERMITIDOS = ['/start', '/help', '/gen', '/bin', '/perfil', 'callback_query']
    
    while RUNNING and not STOP_EVENT.is_set():
        try:
            params = {'offset': ultimo_update_id + 1, 'timeout': 3, 'allowed_updates': ['message', 'callback_query']}
            resultado = fazer_request('getUpdates', params, timeout=5)
            if not resultado or not resultado.get('ok'):
                erros += 1
                if STOP_EVENT.wait(min(5, erros * 2)):
                    break
                continue
            erros = 0
            for update in resultado.get('result', []):
                ultimo_update_id = update.get('update_id', 0)
                
                if 'callback_query' in update:
                    callback = update['callback_query']
                    user_id = callback['from']['id']
                    chat_id = callback['message']['chat']['id']
                    message_id = callback['message']['message_id']
                    callback_id = callback['id']
                    callback_data = callback.get('data', '')
                    
                    processar_comando_bot(
                        user_id, chat_id, message_id,
                        'callback_query',
                        json.dumps({'id': callback_id, 'data': callback_data}),
                        False
                    )
                    continue
                
                if 'message' in update:
                    message = update['message']
                    chat_id = message['chat']['id']
                    message_id = message['message_id']
                    texto = message.get('text', '').strip()
                    user_id = message['from']['id']
                    if not texto or not texto.startswith('/'):
                        continue
                    partes = texto.split(' ', 1)
                    comando = partes[0].lower()
                    args = partes[1] if len(partes) > 1 else ''
                    if comando in ['/start', '/help', '/gen', '/bin', '/perfil']:
                        try:
                            is_group = message['chat']['type'] in ['group', 'supergroup']
                            processar_comando_bot(user_id, chat_id, message_id, comando, args, is_group)
                        except Exception as e:
                            logger.error(f"ERRO: {e}")
            if STOP_EVENT.wait(0.1):
                break
        except KeyboardInterrupt:
            logger.info("🛑 BOT INTERROMPIDO POR CTRL+C")
            RUNNING = False
            STOP_EVENT.set()
            break
        except Exception as e:
            logger.error(f"ERRO NO POLLING: {e}")
            erros += 1
            if STOP_EVENT.wait(min(5, erros * 2)):
                break

# ============================================================
#  TEMPLATE HTML
# ============================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DRWED03 · GERADOR + BIN</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz@14..32&family=JetBrains+Mono&family=Space+Grotesk:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #030207;
            --bg-secondary: #05030b;
            --bg-card: rgba(10, 7, 18, 0.65);
            --border-color: rgba(255, 255, 255, 0.06);
            --glow-purple: #7b2cff;
            --purple-deep: #4b0f8f;
            --violet-magenta: #bb86fc;
            --text-main: #f0f0f5;
            --text-muted: #a0a0b5;
            --glass-bg: rgba(5, 3, 12, 0.7);
            --glass-border: rgba(150, 70, 255, 0.12);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background-color: var(--bg-primary);
            background-image: 
                radial-gradient(circle at 20% 20%, rgba(75, 15, 143, 0.1) 0%, transparent 40%),
                radial-gradient(circle at 80% 80%, rgba(75, 15, 143, 0.1) 0%, transparent 40%);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
            overflow-x: hidden;
            display: flex;
            flex-direction: column;
            align-items: center;
            position: relative;
            z-index: 0;
        }

        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; width: 100vw; height: 100vh;
            background: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.02'/%3E%3C/svg%3E");
            pointer-events: none;
            z-index: -1;
            opacity: 0.6;
        }

        .app-container { max-width: 1200px; width: 100%; padding: 2rem 2rem 3rem; position: relative; z-index: 2; }
        .app-container.active { display: block; }

        #network-canvas {
            position: fixed;
            top: 0; left: 0;
            width: 100vw; height: 100vh;
            z-index: 0;
            pointer-events: none;
            opacity: 0.3;
        }

        header {
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 99px;
            padding: 0.8rem 1.8rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 4rem;
            box-shadow: 0 10px 40px rgba(0,0,0,0.8);
            position: sticky;
            top: 1rem;
            z-index: 100;
        }
        .header-left { display: flex; align-items: center; gap: 1.5rem; }
        .logo-drw { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.3rem; color: #fff; letter-spacing: 1px; text-shadow: 0 0 15px rgba(123, 44, 255, 0.2); cursor: pointer;}
        .logo-drw span { color: #7b2cff; }
        .header-nav { display: flex; gap: 2rem; list-style: none; }
        .header-nav a { text-decoration: none; color: var(--text-muted); font-size: 0.9rem; transition: 0.3s ease; font-weight: 500; cursor: pointer; }
        .header-nav a:hover, .header-nav a.active { color: #fff; text-shadow: 0 0 10px rgba(255,255,255,0.1); }
        .header-right { display: flex; align-items: center; gap: 1rem; }
        .header-tag { font-size: 0.85rem; color: var(--text-muted); background: rgba(255,255,255,0.04); padding: 0.3rem 1rem; border-radius: 20px; border: 1px solid rgba(255,255,255,0.05); }
        .telegram-link-header {
            display: flex; align-items: center; gap: 0.6rem;
            background: rgba(36, 156, 241, 0.1); padding: 0.4rem 1.2rem;
            border-radius: 20px; border: 1px solid rgba(36, 156, 241, 0.2);
            text-decoration: none; color: #fff; font-size: 0.9rem;
            transition: all 0.3s ease;
        }
        .telegram-link-header:hover { border-color: #249cf1; box-shadow: 0 0 20px rgba(36, 156, 241, 0.2); transform: translateY(-1px); }

        .section-content { display: none; animation: fadeInUp 0.6s forwards; }
        .section-content.active { display: block; }
        @keyframes fadeInUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

        .hero-section { display: flex; flex-direction: column; align-items: center; text-align: center; margin-bottom: 4rem; padding: 2rem 0; }
        .avatar-wrapper { position: relative; width: 140px; height: 140px; margin-bottom: 1.5rem; }
        .avatar-img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; border: 2px solid rgba(123, 44, 255, 0.2); box-shadow: 0 0 30px rgba(75, 15, 143, 0.3); transition: 0.3s ease; }
        .avatar-wrapper:hover .avatar-img { transform: scale(1.02); box-shadow: 0 0 50px rgba(123, 44, 255, 0.4); }
        .avatar-glow { position: absolute; top: -10px; left: -10px; right: -10px; bottom: -10px; border-radius: 50%; background: radial-gradient(circle, rgba(123, 44, 255, 0.15) 0%, transparent 70%); z-index: -1; animation: pulseGlow 3s infinite ease-in-out; }
        @keyframes pulseGlow { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.05); opacity: 0.6; } }
        .hero-title { font-family: 'Space Grotesk', sans-serif; font-size: 3.5rem; font-weight: 700; background: linear-gradient(135deg, #fff 0%, #bb86fc 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.2rem; }
        .hero-subtitle { color: var(--text-muted); font-size: 1.1rem; letter-spacing: 2px; margin-bottom: 0.5rem; }
        .hero-creator-link { font-family: 'JetBrains Mono', monospace; color: #7b2cff; font-size: 1.2rem; text-decoration: none; transition: 0.3s ease; }
        .hero-creator-link:hover { text-shadow: 0 0 15px rgba(123, 44, 255, 0.6); color: #fff; }

        .card { background: var(--bg-card); backdrop-filter: blur(16px); border: 1px solid var(--glass-border); border-radius: 24px; padding: 2rem; margin-bottom: 2rem; box-shadow: 0 20px 60px rgba(0,0,0,0.45); }
        .luhn-generator-card { background: rgba(13, 14, 28, 0.95); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,.05); border-radius: 16px; padding: 1.8rem; box-shadow: 0 8px 32px rgba(0,0,0,.4); }
        .bins-input { width: 100%; min-height: 120px; background: rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.05); border-radius: 10px; color: #00FFF0; padding: 1rem; font-family: 'JetBrains Mono'; outline: none; resize: vertical; }
        .card-inputs-row { display: flex; gap: 1rem; margin: 1.5rem 0; flex-wrap: wrap; }
        .card-input-group { flex: 1; min-width: 100px; }
        .card-input-group label { display: block; color: #8c8d9e; font-size: .7rem; margin-bottom: 5px; }
        .card-select, .quantity-input { width: 100%; background: rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.05); border-radius: 10px; color: #00FFF0; padding: 1rem; font-family: 'JetBrains Mono'; outline: none; }
        .quantity-input { flex: 0 0 110px; width: 110px; }
        .controls-row { display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
        .btn { padding: 1rem; border-radius: 10px; border: none; font-weight: 700; cursor: pointer; font-family: 'JetBrains Mono'; transition: .3s; text-transform: uppercase; }
        .btn-primary { flex: 1; background: #7928CA; color: #fff; }
        .btn-primary:hover { box-shadow: 0 5px 20px rgba(121, 40, 202, .5); }
        .btn-cyber { background: transparent; border: 1px solid #00FFF0; color: #00FFF0; }
        .btn-cyber:hover { background: #00FFF0; color: #000; }
        .btn-danger { background: transparent; border: 1px solid #FF003C; color: #FF003C; }
        .btn-danger:hover { background: #FF003C; color: #fff; }
        .cards-list { max-height: 400px; overflow-y: auto; background: rgba(0,0,0,.3); border-radius: 10px; padding: 1rem; margin-bottom: 1rem; font-family: 'JetBrains Mono'; white-space: pre-wrap; color: #00FFF0; font-size: .9rem; }

        footer { margin-top: 5rem; padding: 2rem 0; border-top: 1px solid rgba(255,255,255,0.03); display: flex; flex-direction: column; align-items: center; gap: 0.5rem; color: var(--text-muted); font-size: 0.85rem; }
        footer a { color: #7b2cff; text-decoration: none; transition: 0.2s; }
        footer a:hover { color: #fff; }

        @media (max-width: 600px) { 
            .app-container { padding: 1rem; }
            .hero-title { font-size: 2.5rem; }
            .header-right { display: none; }
            .header-left { width: 100%; justify-content: center; }
            .btn-primary { width: 100%; justify-content: center; padding: 1rem; }
            .header-nav { display: none; }
            .card-inputs-row { flex-direction: column; }
            .quantity-input { flex: 1 1 100%; width: 100%; }
        }
    </style>
</head>
<body>

    <canvas id="network-canvas"></canvas>

    <header>
        <div class="header-left">
            <div class="logo-drw" onclick="showSection('home')">[ DRW<span>03</span> ]</div>
            <ul class="header-nav">
                <li><a class="active" onclick="showSection('home')">INÍCIO</a></li>
                <li><a onclick="showSection('sistema')">SISTEMA</a></li>
            </ul>
        </div>
        <div class="header-right">
            <span class="header-tag">@Drwed03</span>
            <a href="https://t.me/wedze_grupo" target="_blank" rel="noopener noreferrer" class="telegram-link-header">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2L2 9.5L8.5 14.5L12 22L21.5 2Z"/><path d="M21.5 2L8.5 14.5"/></svg>
                TELEGRAM
            </a>
        </div>
    </header>

    <main class="app-container active">
        <section id="section-home" class="section-content active">
            <div class="hero-section">
                <div class="avatar-wrapper">
                    <div class="avatar-glow"></div>
                    <img src="" alt="DRWED03" class="avatar-img">
                </div>
                <h1 class="hero-title">DRWED03</h1>
                <p class="hero-subtitle">BY • WEDZE_GRUPO</p>
                <a href="https://t.me/wedze_grupo" target="_blank" class="hero-creator-link">@Drwed03</a>
            </div>
        </section>

        <section id="section-sistema" class="section-content">
            <div class="hero-section" style="margin-bottom: 1rem; padding-bottom: 1rem;">
                <h2 style="font-family: 'Space Grotesk', sans-serif; color: #fff; font-size: 2rem;">GERADOR</h2>
                <p class="hero-subtitle">GERADOR DE CARDS + BIN</p>
            </div>

            <div class="card luhn-generator-card">
                <textarea id="binInput" class="bins-input" spellcheck="false" placeholder="DIGITE OS BINS (EX: 512267, 512267XXXXXX, 340000 PARA AMEX)..."></textarea>
                <div class="card-inputs-row">
                    <div class="card-input-group">
                        <label>MÊS</label>
                        <select id="cardMonth" class="card-select">
                            <option value="random">ALEATÓRIO</option>
                            <option value="01">01</option><option value="02">02</option><option value="03">03</option>
                            <option value="04">04</option><option value="05">05</option><option value="06">06</option>
                            <option value="07">07</option><option value="08">08</option><option value="09">09</option>
                            <option value="10">10</option><option value="11">11</option><option value="12">12</option>
                        </select>
                    </div>
                    <div class="card-input-group">
                        <label>ANO</label>
                        <select id="cardYear" class="card-select">
                            <option value="random">ALEATÓRIO</option>
                            <option value="2026">2026</option><option value="2027">2027</option>
                            <option value="2028">2028</option><option value="2029">2029</option>
                            <option value="2030">2030</option><option value="2031">2031</option>
                        </select>
                    </div>
                    <div class="card-input-group">
                        <label>CVV</label>
                        <select id="cardCvv" class="card-select">
                            <option value="random">ALEATÓRIO</option>
                            <option value="123">123</option>
                            <option value="000">000</option>
                        </select>
                    </div>
                </div>
                <div class="controls-row">
                    <input type="number" id="quantity" class="quantity-input" value="10" min="1" aria-label="QUANTIDADE">
                    <button class="btn btn-primary" type="button" onclick="generateCards()">GERAR AGORA</button>
                </div>
                <div class="cards-list" id="cardsList">🔵 DIGITE OS BINS E CLIQUE EM GERAR</div>
                <div class="controls-row">
                    <button class="btn btn-cyber" type="button" onclick="copyCards()">📋 COPIAR</button>
                    <button class="btn btn-danger" type="button" onclick="clearCards()">🗑️ LIMPAR</button>
                </div>
            </div>
        </section>
    </main>

    <footer>
        <div style="font-size: 1.2rem; font-weight: bold; color: #7b2cff;">DRWED03</div>
        <div>BY <a href="https://t.me/wedze_grupo" target="_blank" style="color: #fff;">T.ME/WEDZE_GRUPO</a></div>
        <div style="font-size: 0.7rem; opacity: 0.5;">&copy; 2026 DRWED03</div>
    </footer>

    <script>
        function showSection(sectionId) {
            document.querySelectorAll('.section-content').forEach(el => el.classList.remove('active'));
            const section = document.getElementById('section-' + sectionId);
            if (section) section.classList.add('active');
            document.querySelectorAll('.header-nav a').forEach(el => el.classList.remove('active'));
            const activeLink = Array.from(document.querySelectorAll('.header-nav a')).find(a => (a.getAttribute('onclick') || '').includes(sectionId));
            if (activeLink) activeLink.classList.add('active');
        }

        const binInput = document.getElementById('binInput');
        const cardsList = document.getElementById('cardsList');
        const generatedCards = [];

        async function generateCards() {
            const pattern = binInput.value.trim();
            const quantity = document.getElementById('quantity').value || '10';
            if (!pattern) {
                alert('DIGITE OS BINS E CLIQUE EM GERAR.');
                return;
            }
            cardsList.textContent = '🔵 GERANDO...';
            try {
                const response = await fetch('/api/luhn/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        pattern,
                        quantity,
                        month: document.getElementById('cardMonth').value,
                        year: document.getElementById('cardYear').value,
                        cvv: document.getElementById('cardCvv').value
                    })
                });
                const data = await response.json();
                if (!response.ok || !data.ok) throw new Error(data.error || 'ERRO NA GERAÇÃO.');
                generatedCards.splice(0, generatedCards.length, ...(data.results || []));
                cardsList.textContent = generatedCards.join(String.fromCharCode(10)) || '🔵 NENHUM RESULTADO';
            } catch (error) {
                generatedCards.splice(0, generatedCards.length);
                cardsList.textContent = '🔵 NENHUM RESULTADO';
                alert(error.message);
            }
        }

        function copyCards() {
            const text = generatedCards.join(String.fromCharCode(10));
            if (!text) {
                alert('NENHUM RESULTADO PARA COPIAR.');
                return;
            }
            
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text)
                    .then(() => {
                        const btn = document.querySelector('.btn-cyber');
                        const originalText = btn.textContent;
                        btn.textContent = '✅ COPIADO!';
                        setTimeout(() => { btn.textContent = originalText; }, 2000);
                    })
                    .catch(() => fallbackCopy(text));
            } else {
                fallbackCopy(text);
            }
        }

        function fallbackCopy(text) {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.left = '-9999px';
            textarea.style.top = '-9999px';
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            
            try {
                const success = document.execCommand('copy');
                const btn = document.querySelector('.btn-cyber');
                const originalText = btn.textContent;
                if (success) {
                    btn.textContent = '✅ COPIADO!';
                    setTimeout(() => { btn.textContent = originalText; }, 2000);
                } else {
                    btn.textContent = '❌ ERRO';
                    setTimeout(() => { btn.textContent = originalText; }, 2000);
                }
            } catch (err) {
                alert('❌ NÃO FOI POSSÍVEL COPIAR. COPIE MANUALMENTE.');
            } finally {
                document.body.removeChild(textarea);
            }
        }

        function clearCards() {
            generatedCards.splice(0, generatedCards.length);
            cardsList.textContent = '🔵 DIGITE OS BINS E CLIQUE EM GERAR';
        }

        if (window.location.hash === '#section-sistema') showSection('sistema');

        const canvas = document.getElementById('network-canvas');
        const ctx = canvas.getContext('2d');
        let width, height;
        let particles = [];
        const PARTICLE_COUNT = 80;
        const CONNECTION_DISTANCE = 180;

        function resize() {
            width = canvas.width = window.innerWidth;
            height = canvas.height = window.innerHeight;
        }
        window.addEventListener('resize', resize);
        resize();

        class Particle {
            constructor() {
                this.x = Math.random() * width;
                this.y = Math.random() * height;
                this.vx = (Math.random() - 0.5) * 0.8;
                this.vy = (Math.random() - 0.5) * 0.8;
                this.radius = Math.random() * 1.5 + 0.5;
            }
            update() {
                this.x += this.vx;
                this.y += this.vy;
                if (this.x < 0 || this.x > width) this.vx *= -1;
                if (this.y < 0 || this.y > height) this.vy *= -1;
            }
            draw() {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                ctx.fillStyle = '#7b2cff';
                ctx.shadowBlur = 5;
                ctx.shadowColor = '#7b2cff';
                ctx.fill();
                ctx.shadowBlur = 0;
            }
        }

        for (let i = 0; i < PARTICLE_COUNT; i++) {
            particles.push(new Particle());
        }

        function animate() {
            ctx.clearRect(0, 0, width, height);
            
            particles.forEach(p => {
                p.update();
                p.draw();
            });

            for (let i = 0; i < particles.length; i++) {
                for (let j = i + 1; j < particles.length; j++) {
                    const dx = particles[i].x - particles[j].x;
                    const dy = particles[i].y - particles[j].y;
                    const dist = Math.sqrt(dx * dx + dy * dy);

                    if (dist < CONNECTION_DISTANCE) {
                        ctx.beginPath();
                        ctx.moveTo(particles[i].x, particles[i].y);
                        ctx.lineTo(particles[j].x, particles[j].y);
                        ctx.strokeStyle = `rgba(123, 44, 255, ${1 - dist / CONNECTION_DISTANCE})`;
                        ctx.lineWidth = 0.5;
                        ctx.stroke();
                    }
                }
            }
            requestAnimationFrame(animate);
        }
        animate();
    </script>
</body>
</html>"""

# ============================================================
#  MAIN
# ============================================================

if __name__ == '__main__':
    init_db()
    load_bins_from_csv()
    
    print("=" * 60)
    print("🚀 GERADOR + BOT BIN + WEBHOOK - DRWED03")
    print("=" * 60)
    print(f"📌 BOT: @{BOT_USERNAME}")
    print(f"📌 TOKEN: {TOKEN[:10]}...")
    print(f"📌 WEBHOOK: {WEBHOOK_CHAT} (SILENCIOSO)")
    print(f"📌 TIMER APAGAR: {TIMER_APAGAR}s")
    print(f"📌 TIMER ERRO: {TIMER_ERRO}s")
    print()
    print("📌 SISTEMA DE 3 PASSOS:")
    print(f"   PASSO 1: ENTRAR NO {GRUPO_PRINCIPAL}")
    print(f"   PASSO 2: ENTRAR NO {GRUPO_REFS}")
    print(f"   PASSO 3: ACEITAR OS TERMOS")
    print()
    print("📌 COMANDOS DO BOT:")
    print("   /GEN <PADRÃO> <QTD>  - GERAR CARTÕES")
    print("   /BIN <BIN>            - CONSULTAR BIN")
    print("   /PERFIL               - VER SEU PERFIL")
    print("   /START, /HELP         - AJUDA")
    print()
    print("📌 INTERFACE WEB:")
    print("   HTTP://LOCALHOST:5000")
    print()
    print("💡 PRESSIONE CTRL+C PARA PARAR")
    print("=" * 60)
    print()
    
    bot_thread = threading.Thread(target=polling, daemon=True)
    bot_thread.start()
    
    try:
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        RUNNING = False
        STOP_EVENT.set()
        print("\n🛑 SERVIDOR FINALIZADO.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ ERRO FATAL: {e}")
        sys.exit(1)
    finally:
        RUNNING = False
        STOP_EVENT.set()
