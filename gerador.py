#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GERADOR + BOT BIN + WEBHOOK - DRWED03
   - APAGA COMANDO NO GRUPO
   - @MENÇÃO DO USUÁRIO NO WEBHOOK
   - ACEITA QUALQUER PADRÃO (/gen 512267 40)
   - MATRIZ EXATA
   - UMA MENSAGEM COM ARQUIVO ANEXADO NO PV
   - ABA VERIFICADOR DE BINS (VERIFICAR + BUSCA AVANÇADA)
   - SUPORTE AMEX 15 DÍGITOS E CVV 4
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
#  CONFIGURAÇÕES
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
#  FUNÇÃO DE WEBHOOK - COM @MENÇÃO CORRETA
# ============================================================

def enviar_webhook(bin_input: str, results: List[str], user_id: int = ADMIN_ID, username: str = None, origem: str = 'bot'):
    """ENVIA PARA @scrap_wed - COM @MENÇÃO CORRETA"""
    if not results:
        return
    
    try:
        matriz_exata = bin_input if bin_input else results[0] if results else 'N/A'
        bin_base = re.sub(r'[^0-9]', '', matriz_exata)[:6]
        if not bin_base:
            bin_base = re.sub(r'[^0-9]', '', results[0])[:6] if results else 'N/A'
        
        card_type = detect_card_type(bin_base)
        data_hora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        user_mention = f"@{username}" if username else "Usuário"
        
        if origem == 'site':
            mensagem = (
                f"🚀 *NOVA GERAÇÃO SITE DETECTADA*\n\n"
                f"📅 *Data:* `{data_hora}`\n"
                f"📝 *Matriz:* `{matriz_exata}`\n"
                f"🔢 *Quantidade:* `{len(results)}`\n"
                f"💳 *Tipo:* `{card_type}`\n"
                f"🏦 *BIN:* `{bin_base}`"
            )
        else:
            mensagem = (
                f"🚀 *NOVA GERAÇÃO DETECTADA*\n\n"
                f"👤 *Usuário:* {user_mention}\n"
                f"🆔 *ID:* `{user_id}`\n"
                f"📅 *Data:* `{data_hora}`\n"
                f"📝 *Matriz:* `{matriz_exata}`\n"
                f"🔢 *Quantidade:* `{len(results)}`\n"
                f"💳 *Tipo:* `{card_type}`\n"
                f"🏦 *BIN:* `{bin_base}`"
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
        return BINS_DATA[bin_prefix].copy(), None
    return {'brand': 'DESCONHECIDO', 'type': 'DESCONHECIDO', 'level': '', 'bank': 'DESCONHECIDO', 'country': 'INTERNACIONAL'}, None

# ============================================================
#  FORMATADORES
# ============================================================

def formatar_resposta_bin_completa(dados: Dict, bin_consultado: str) -> str:
    if not dados:
        return f"❌ *BIN NÃO ENCONTRADO:* `{bin_consultado}`"
    
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
        f"🔍 *BIN Consultada:* `{bin_consultado}`\n\n"
        f"🌎 *País:* `{pais}`\n"
        f"{emoji_cartao} *Bandeira:* `{bandeira}`\n"
        f"{emoji_banco_icon} *Banco:* `{banco}`\n"
        f"🏆 *Nível:* `{nivel_traduzido}`\n"
        f"💳 *Tipo:* `{tipo}`\n"
        f"⏱️ *Tempo:* `0.00 ms`"
    )

def formatar_resposta_bin_resumo(dados: Dict, bin_consultado: str) -> str:
    if not dados:
        return f"❌ *BIN NÃO ENCONTRADO:* `{bin_consultado}`"
    
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
        f"{emoji_cartao} *Bandeira:* `{bandeira}`\n"
        f"{emoji_banco_icon} *Banco:* `{banco}`\n\n"
        f"📱 Clique para ver todos os detalhes."
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

def detect_card_type(bin_number: str) -> str:
    """Detecta a bandeira do cartão baseado no BIN"""
    if not bin_number:
        return "PADRÃO"
    first_two = bin_number[:2] if len(bin_number) >= 2 else ''
    first_four = bin_number[:4] if len(bin_number) >= 4 else ''
    first_six = bin_number[:6] if len(bin_number) >= 6 else ''
    
    # AMEX: 34 ou 37
    if first_two in ['34', '37']:
        return "AMEX"
    
    # MASTERCARD: 51-55
    if first_two in ['51', '52', '53', '54', '55']:
        return "MASTERCARD"
    
    # VISA: começa com 4
    if bin_number[0] == '4':
        return "VISA"
    
    # ELO
    if first_four in ['6363', '4389', '5041', '4514'] or first_six in ['636368', '636369', '504175', '451416']:
        return "ELO"
    
    # HIPERCARD: 606282
    if first_six == '606282':
        return "HIPERCARD"
    
    # DISCOVER: 6011, 65, 64-65
    if first_four == '6011' or first_two == '65' or first_two in ['64', '62']:
        return "DISCOVER"
    
    # JCB: 3528-3589
    if first_four and 3528 <= int(first_four) <= 3589:
        return "JCB"
    
    # DINERS: 30, 36, 38 ou 54, 55
    if first_two in ['30', '36', '38'] or first_two in ['54', '55']:
        return "DINERS"
    
    return "PADRÃO"

def get_card_length(bin_number: str) -> int:
    """Retorna o número de dígitos do cartão baseado na bandeira"""
    card_type = detect_card_type(bin_number)
    if card_type == "AMEX":
        return 15
    return 16

def _prepare_card_pattern(value: str) -> str:
    """Prepara o padrão do cartão com o tamanho correto para cada bandeira"""
    cleaned = re.sub(r'[^0-9Xx]', '', value)
    if not cleaned:
        raise ValueError('INFORME UM BIN OU PADRÃO.')
    
    # Detecta a bandeira baseado nos primeiros dígitos
    bin_prefix = cleaned[:6] if len(cleaned) >= 6 else cleaned
    target_length = get_card_length(bin_prefix)
    
    if len(cleaned) < target_length:
        cleaned += 'X' * (target_length - len(cleaned))
    elif len(cleaned) > target_length:
        cleaned = cleaned[:target_length]
    
    return clean_pattern(cleaned)

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
    """Gera CVV com 3 ou 4 dígitos dependendo da bandeira"""
    value = str(cvv or 'random').strip().lower()
    
    # Se for AMEX (cvv com 4 dígitos)
    if value in ['random', 'xxxx', 'x']:
        # Vamos detectar a bandeira pelo contexto, mas por padrão geramos 3 dígitos
        # O tamanho será ajustado na geração do cartão
        return str(random.randint(0, 9999)).zfill(4) if value in ['xxxx', 'x'] else str(random.randint(0, 999)).zfill(3)
    
    if not re.fullmatch(r'\d{3,4}', value):
        return str(random.randint(0, 999)).zfill(3)
    return value

def _get_cvv_length(card_number: str) -> int:
    """Retorna o tamanho do CVV baseado na bandeira"""
    card_type = detect_card_type(card_number)
    if card_type == "AMEX":
        return 4
    return 3

def _random_cvv_by_card(card_number: str, cvv_input: object) -> str:
    """Gera CVV com o tamanho correto para a bandeira"""
    value = str(cvv_input or 'random').strip().lower()
    cvv_len = _get_cvv_length(card_number)
    
    if value == 'random' or value == 'x' * cvv_len or value == 'x':
        return str(random.randint(0, 10**cvv_len - 1)).zfill(cvv_len)
    
    if re.fullmatch(r'\d{' + str(cvv_len) + r'}', value):
        return value
    
    # Se o CVV fornecido não tem o tamanho correto, gera um aleatório
    return str(random.randint(0, 10**cvv_len - 1)).zfill(cvv_len)

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
        cvv_value = _random_cvv_by_card(card_number, line_cvv)
        
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
#  ENVIAR COM BOTÃO REDIRECIONAR
# ============================================================

def enviar_com_botao_redirecionar(chat_id, user_id, texto, comando, dados, qtd=None):
    """ENVIA MENSAGEM COM BOTÃO"""
    consulta_id = f"{user_id}_{int(time.time())}_{hashlib.md5(str(user_id).encode()).hexdigest()[:6]}"
    
    consultas_ativas[consulta_id] = {
        'user_id': user_id,
        'chat_id': chat_id,
        'comando': comando,
        'dados': dados,
        'qtd': qtd,
        'message_id': None,
        'timestamp': time.time()
    }
    
    link_pv = f"https://t.me/{BOT_USERNAME}?start=result_{consulta_id}"
    
    markup = {"inline_keyboard": [[{"text": "📱 VER RESULTADO NO PV", "url": link_pv}]]}
    
    msg = enviar_mensagem_com_retorno(
        chat_id,
        texto,
        parse_mode="Markdown",
        reply_markup=markup
    )
    
    if msg:
        consultas_ativas[consulta_id]['message_id'] = msg['message_id']
        
        def apagar_depois():
            time.sleep(TIMER_APAGAR)
            try:
                apagar_mensagem(chat_id, msg['message_id'])
            except:
                pass
        
        threading.Thread(target=apagar_depois, daemon=True).start()
    
    return msg

# ============================================================
#  ENVIAR RESULTADO PV
# ============================================================

def enviar_resultado_pv(user_id, comando, dados, qtd=None, chat_id_grupo=None, message_id_grupo=None):
    """ENVIA RESULTADO NO PV"""
    try:
        if comando == 'gen':
            cards = dados.get('cards', [])
            caption = dados.get('caption', '✅ Cartões gerados com sucesso!')
            
            if cards:
                nome_arquivo = "geradas.txt"
                with open(nome_arquivo, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(cards))
                
                enviar_arquivo(
                    user_id,
                    nome_arquivo,
                    caption
                )
                os.remove(nome_arquivo) if os.path.exists(nome_arquivo) else None
            else:
                enviar_mensagem(user_id, "❌ Nenhum cartão gerado.", parse_mode="Markdown")
                
        elif comando == 'help':
            texto = dados.get('texto', '')
            if texto:
                enviar_mensagem(user_id, texto, parse_mode="Markdown")
            
        elif comando == 'bin':
            texto = dados.get('texto', '')
            if texto:
                enviar_mensagem(user_id, texto, parse_mode="Markdown")
            
        elif comando == 'perfil':
            texto = dados.get('texto', '')
            if texto:
                enviar_mensagem(user_id, texto, parse_mode="Markdown")
            
        else:
            enviar_mensagem(user_id, "❌ Comando não reconhecido.", parse_mode="Markdown")
        
        if chat_id_grupo and message_id_grupo:
            time.sleep(0.5)
            apagar_mensagem(chat_id_grupo, message_id_grupo)
        
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar no PV: {e}")
        return False

# ============================================================
#  ROTAS FLASK - VERIFICADOR DE BINS
# ============================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>GERADOR · CAMBADA 🔥</title>
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
            --success-green: #00ff88;
            --danger-red: #ff3355;
            --card-bg: rgba(13, 14, 28, 0.95);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body {
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
            width: 100%;
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

        .app-container { max-width: 1200px; width: 100%; padding: 1rem 1rem 2rem; position: relative; z-index: 2; }
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
            padding: 0.6rem 1.2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            box-shadow: 0 10px 40px rgba(0,0,0,0.8);
            position: sticky;
            top: 0.5rem;
            z-index: 100;
            flex-wrap: wrap;
            gap: 0.5rem;
        }
        .header-left { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
        .logo-drw { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.1rem; color: #fff; letter-spacing: 1px; text-shadow: 0 0 15px rgba(123, 44, 255, 0.2); cursor: pointer; white-space: nowrap; }
        .logo-drw span { color: #7b2cff; }
        .header-nav { display: flex; gap: 0.5rem; list-style: none; flex-wrap: wrap; }
        .header-nav a { text-decoration: none; color: var(--text-muted); font-size: 0.75rem; transition: 0.3s ease; font-weight: 500; cursor: pointer; padding: 0.4rem 0.8rem; border-radius: 8px; white-space: nowrap; }
        .header-nav a:hover, .header-nav a.active { color: #fff; background: rgba(123, 44, 255, 0.15); }
        .header-right { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
        .header-tag { font-size: 0.7rem; color: var(--text-muted); background: rgba(255,255,255,0.04); padding: 0.2rem 0.8rem; border-radius: 20px; border: 1px solid rgba(255,255,255,0.05); }
        .telegram-link-header {
            display: flex; align-items: center; gap: 0.4rem;
            background: rgba(36, 156, 241, 0.1); padding: 0.3rem 0.8rem;
            border-radius: 20px; border: 1px solid rgba(36, 156, 241, 0.2);
            text-decoration: none; color: #fff; font-size: 0.7rem;
            transition: all 0.3s ease;
            white-space: nowrap;
        }
        .telegram-link-header:hover { border-color: #249cf1; box-shadow: 0 0 20px rgba(36, 156, 241, 0.2); }

        .section-content { display: none; animation: fadeInUp 0.6s forwards; }
        .section-content.active { display: block; }
        @keyframes fadeInUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

        .hero-section { display: flex; flex-direction: column; align-items: center; text-align: center; margin-bottom: 1.5rem; padding: 0.5rem 0; }
        .avatar-wrapper { position: relative; width: 80px; height: 80px; margin-bottom: 0.5rem; }
        .avatar-img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; border: 2px solid rgba(123, 44, 255, 0.2); box-shadow: 0 0 30px rgba(75, 15, 143, 0.3); }
        .avatar-glow { position: absolute; top: -10px; left: -10px; right: -10px; bottom: -10px; border-radius: 50%; background: radial-gradient(circle, rgba(123, 44, 255, 0.15) 0%, transparent 70%); z-index: -1; animation: pulseGlow 3s infinite ease-in-out; }
        @keyframes pulseGlow { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.05); opacity: 0.6; } }
        .hero-title { font-family: 'Space Grotesk', sans-serif; font-size: 2rem; font-weight: 700; background: linear-gradient(135deg, #fff 0%, #bb86fc 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .hero-subtitle { color: var(--text-muted); font-size: 0.8rem; letter-spacing: 2px; }

        .card { background: var(--bg-card); backdrop-filter: blur(16px); border: 1px solid var(--glass-border); border-radius: 16px; padding: 1rem; margin-bottom: 1.2rem; box-shadow: 0 20px 60px rgba(0,0,0,0.45); }
        .card-dark { background: var(--card-bg); border: 1px solid rgba(255,255,255,.05); }
        
        .bins-input { width: 100%; min-height: 80px; background: rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.05); border-radius: 10px; color: #00FFF0; padding: 0.8rem; font-family: 'JetBrains Mono'; outline: none; resize: vertical; font-size: 0.8rem; }
        .bins-input:focus { border-color: #7b2cff; box-shadow: 0 0 20px rgba(123, 44, 255, 0.1); }
        
        .card-inputs-row { display: flex; gap: 0.8rem; margin: 0.8rem 0; flex-wrap: wrap; }
        .card-input-group { flex: 1; min-width: 70px; }
        .card-input-group label { display: block; color: #8c8d9e; font-size: 0.6rem; margin-bottom: 3px; text-transform: uppercase; letter-spacing: 1px; }
        .card-select, .quantity-input { width: 100%; background: rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.05); border-radius: 8px; color: #00FFF0; padding: 0.6rem; font-family: 'JetBrains Mono'; outline: none; font-size: 0.8rem; }
        .quantity-input { flex: 0 0 70px; width: 70px; }
        
        .controls-row { display: flex; gap: 0.6rem; margin-bottom: 0.8rem; flex-wrap: wrap; }
        .btn { padding: 0.6rem 1.2rem; border-radius: 8px; border: none; font-weight: 700; cursor: pointer; font-family: 'JetBrains Mono'; transition: .3s; text-transform: uppercase; font-size: 0.7rem; }
        .btn-primary { flex: 1; background: #7928CA; color: #fff; min-width: 100px; }
        .btn-primary:hover { box-shadow: 0 5px 20px rgba(121, 40, 202, .5); transform: translateY(-1px); }
        .btn-cyber { background: transparent; border: 1px solid #00FFF0; color: #00FFF0; }
        .btn-cyber:hover { background: #00FFF0; color: #000; }
        .btn-danger { background: transparent; border: 1px solid #FF003C; color: #FF003C; }
        .btn-danger:hover { background: #FF003C; color: #fff; }
        .btn-success { background: transparent; border: 1px solid #00ff88; color: #00ff88; }
        .btn-success:hover { background: #00ff88; color: #000; }
        .btn-purple { background: transparent; border: 1px solid #7b2cff; color: #7b2cff; }
        .btn-purple:hover { background: #7b2cff; color: #fff; }
        .btn-sm { padding: 0.3rem 0.8rem; font-size: 0.6rem; }
        
        .cards-list { max-height: 250px; overflow-y: auto; background: rgba(0,0,0,.3); border-radius: 8px; padding: 0.6rem; margin-bottom: 0.8rem; font-family: 'JetBrains Mono'; white-space: pre-wrap; color: #00FFF0; font-size: 0.75rem; word-break: break-all; }
        .cards-list::-webkit-scrollbar { width: 3px; }
        .cards-list::-webkit-scrollbar-track { background: rgba(255,255,255,0.02); }
        .cards-list::-webkit-scrollbar-thumb { background: #7b2cff; border-radius: 3px; }

        /* VERIFICADOR */
        .bin-tabs { display: flex; gap: 0.3rem; margin-bottom: 0.8rem; flex-wrap: wrap; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 0.5rem; }
        .bin-tab-btn { padding: 0.4rem 1rem; border: none; background: transparent; color: var(--text-muted); cursor: pointer; font-family: 'Inter', sans-serif; font-weight: 600; font-size: 0.7rem; transition: 0.3s; border-radius: 6px; }
        .bin-tab-btn:hover { color: #fff; background: rgba(123, 44, 255, 0.1); }
        .bin-tab-btn.active { color: #fff; background: rgba(123, 44, 255, 0.2); }
        .bin-tab-content { display: none; padding: 0.5rem 0; }
        .bin-tab-content.active { display: block; }
        
        .bin-verify-input { width: 100%; background: rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.05); border-radius: 8px; color: #00FFF0; padding: 0.6rem 0.8rem; font-family: 'JetBrains Mono'; outline: none; font-size: 0.8rem; }
        .bin-verify-input:focus { border-color: #7b2cff; box-shadow: 0 0 20px rgba(123, 44, 255, 0.1); }
        
        .bin-search-row { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
        .bin-search-row select, .bin-search-row input { flex: 1; min-width: 100px; background: rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.05); border-radius: 8px; color: #00FFF0; padding: 0.5rem 0.6rem; font-family: 'JetBrains Mono'; outline: none; font-size: 0.7rem; }
        .bin-search-row select option { background: #1a1a2e; color: #fff; }
        .bin-search-row input::placeholder { color: #555; }
        
        .bin-result { background: rgba(0,0,0,.3); border-radius: 8px; padding: 0.8rem; font-family: 'JetBrains Mono'; color: #00FFF0; font-size: 0.8rem; min-height: 50px; max-height: 300px; overflow-y: auto; }
        .bin-result .label { color: #8c8d9e; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1px; }
        .bin-result .value { color: #fff; font-weight: 600; }
        .bin-result .error { color: #ff3355; }
        .bin-result-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.3rem 1rem; margin-top: 0.3rem; }
        .bin-result-grid .item { display: flex; justify-content: space-between; padding: 0.2rem 0; border-bottom: 1px solid rgba(255,255,255,0.03); font-size: 0.75rem; }
        .bin-result-list { max-height: 200px; overflow-y: auto; }
        .bin-result-list .item { padding: 0.2rem 0; border-bottom: 1px solid rgba(255,255,255,0.03); font-size: 0.7rem; display: flex; gap: 0.5rem; flex-wrap: wrap; }
        .bin-result-list .item .bin-code { color: #00FFF0; font-weight: 600; min-width: 60px; }
        .bin-result-list .item .bin-info { color: #8c8d9e; }
        .bin-count { color: #8c8d9e; font-size: 0.7rem; margin-bottom: 0.3rem; }

        footer { margin-top: 2rem; padding: 1rem 0; border-top: 1px solid rgba(255,255,255,0.03); display: flex; flex-direction: column; align-items: center; gap: 0.2rem; color: var(--text-muted); font-size: 0.7rem; text-align: center; }
        footer a { color: #7b2cff; text-decoration: none; }
        footer a:hover { color: #fff; }

        @media (max-width: 600px) { 
            .app-container { padding: 0.5rem; }
            .hero-title { font-size: 1.6rem; }
            .header-right { display: none; }
            .header-left { width: 100%; justify-content: center; flex-wrap: wrap; }
            .header-nav { justify-content: center; width: 100%; }
            .card-inputs-row { flex-direction: column; }
            .quantity-input { flex: 1 1 100%; width: 100%; }
            .card { padding: 0.6rem; }
            .bins-input { min-height: 60px; font-size: 0.7rem; }
            .btn { padding: 0.5rem 0.8rem; font-size: 0.6rem; }
            .controls-row { flex-direction: column; }
            .cards-list { font-size: 0.65rem; max-height: 150px; }
            .avatar-wrapper { width: 60px; height: 60px; }
            header { border-radius: 16px; padding: 0.4rem 0.6rem; margin-bottom: 1rem; }
            .bin-result-grid { grid-template-columns: 1fr; }
            .bin-search-row { flex-direction: column; }
            .bin-search-row select, .bin-search-row input { min-width: 100%; }
            .bin-tabs { justify-content: center; }
            .bin-tab-btn { padding: 0.3rem 0.6rem; font-size: 0.6rem; }
            .telegram-link-header span { display: none; }
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
                <li><a onclick="showSection('sistema')">GERADOR</a></li>
                <li><a onclick="showSection('verificador')">VERIFICADOR</a></li>
            </ul>
        </div>
        <div class="header-right">
            <span class="header-tag">@Drwed03</span>
            <a href="https://t.me/wedze_grupo" target="_blank" class="telegram-link-header">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2L2 9.5L8.5 14.5L12 22L21.5 2Z"/><path d="M21.5 2L8.5 14.5"/></svg>
                <span>TELEGRAM</span>
            </a>
        </div>
    </header>

    <main class="app-container">
        <!-- HOME -->
        <section id="section-home" class="section-content active">
            <div class="hero-section">
                <div class="avatar-wrapper">
                    <div class="avatar-glow"></div>
                    <img src="#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GERADOR + BOT BIN + WEBHOOK - DRWED03
   - APAGA COMANDO NO GRUPO
   - @MENÇÃO DO USUÁRIO NO WEBHOOK
   - ACEITA QUALQUER PADRÃO (/gen 512267 40)
   - MATRIZ EXATA
   - UMA MENSAGEM COM ARQUIVO ANEXADO NO PV
   - ABA VERIFICADOR DE BINS (VERIFICAR + BUSCA AVANÇADA)
   - SUPORTE AMEX 15 DÍGITOS E CVV 4
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
#  CONFIGURAÇÕES
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
#  FUNÇÃO DE WEBHOOK - COM @MENÇÃO CORRETA
# ============================================================

def enviar_webhook(bin_input: str, results: List[str], user_id: int = ADMIN_ID, username: str = None, origem: str = 'bot'):
    """ENVIA PARA @scrap_wed - COM @MENÇÃO CORRETA"""
    if not results:
        return
    
    try:
        matriz_exata = bin_input if bin_input else results[0] if results else 'N/A'
        bin_base = re.sub(r'[^0-9]', '', matriz_exata)[:6]
        if not bin_base:
            bin_base = re.sub(r'[^0-9]', '', results[0])[:6] if results else 'N/A'
        
        card_type = detect_card_type(bin_base)
        data_hora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        user_mention = f"@{username}" if username else "Usuário"
        
        if origem == 'site':
            mensagem = (
                f"🚀 *NOVA GERAÇÃO SITE DETECTADA*\n\n"
                f"📅 *Data:* `{data_hora}`\n"
                f"📝 *Matriz:* `{matriz_exata}`\n"
                f"🔢 *Quantidade:* `{len(results)}`\n"
                f"💳 *Tipo:* `{card_type}`\n"
                f"🏦 *BIN:* `{bin_base}`"
            )
        else:
            mensagem = (
                f"🚀 *NOVA GERAÇÃO DETECTADA*\n\n"
                f"👤 *Usuário:* {user_mention}\n"
                f"🆔 *ID:* `{user_id}`\n"
                f"📅 *Data:* `{data_hora}`\n"
                f"📝 *Matriz:* `{matriz_exata}`\n"
                f"🔢 *Quantidade:* `{len(results)}`\n"
                f"💳 *Tipo:* `{card_type}`\n"
                f"🏦 *BIN:* `{bin_base}`"
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
        return BINS_DATA[bin_prefix].copy(), None
    return {'brand': 'DESCONHECIDO', 'type': 'DESCONHECIDO', 'level': '', 'bank': 'DESCONHECIDO', 'country': 'INTERNACIONAL'}, None

# ============================================================
#  FORMATADORES
# ============================================================

def formatar_resposta_bin_completa(dados: Dict, bin_consultado: str) -> str:
    if not dados:
        return f"❌ *BIN NÃO ENCONTRADO:* `{bin_consultado}`"
    
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
        f"🔍 *BIN Consultada:* `{bin_consultado}`\n\n"
        f"🌎 *País:* `{pais}`\n"
        f"{emoji_cartao} *Bandeira:* `{bandeira}`\n"
        f"{emoji_banco_icon} *Banco:* `{banco}`\n"
        f"🏆 *Nível:* `{nivel_traduzido}`\n"
        f"💳 *Tipo:* `{tipo}`\n"
        f"⏱️ *Tempo:* `0.00 ms`"
    )

def formatar_resposta_bin_resumo(dados: Dict, bin_consultado: str) -> str:
    if not dados:
        return f"❌ *BIN NÃO ENCONTRADO:* `{bin_consultado}`"
    
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
        f"{emoji_cartao} *Bandeira:* `{bandeira}`\n"
        f"{emoji_banco_icon} *Banco:* `{banco}`\n\n"
        f"📱 Clique para ver todos os detalhes."
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

def detect_card_type(bin_number: str) -> str:
    """Detecta a bandeira do cartão baseado no BIN"""
    if not bin_number:
        return "PADRÃO"
    first_two = bin_number[:2] if len(bin_number) >= 2 else ''
    first_four = bin_number[:4] if len(bin_number) >= 4 else ''
    first_six = bin_number[:6] if len(bin_number) >= 6 else ''
    
    # AMEX: 34 ou 37
    if first_two in ['34', '37']:
        return "AMEX"
    
    # MASTERCARD: 51-55
    if first_two in ['51', '52', '53', '54', '55']:
        return "MASTERCARD"
    
    # VISA: começa com 4
    if bin_number[0] == '4':
        return "VISA"
    
    # ELO
    if first_four in ['6363', '4389', '5041', '4514'] or first_six in ['636368', '636369', '504175', '451416']:
        return "ELO"
    
    # HIPERCARD: 606282
    if first_six == '606282':
        return "HIPERCARD"
    
    # DISCOVER: 6011, 65, 64-65
    if first_four == '6011' or first_two == '65' or first_two in ['64', '62']:
        return "DISCOVER"
    
    # JCB: 3528-3589
    if first_four and 3528 <= int(first_four) <= 3589:
        return "JCB"
    
    # DINERS: 30, 36, 38 ou 54, 55
    if first_two in ['30', '36', '38'] or first_two in ['54', '55']:
        return "DINERS"
    
    return "PADRÃO"

def get_card_length(bin_number: str) -> int:
    """Retorna o número de dígitos do cartão baseado na bandeira"""
    card_type = detect_card_type(bin_number)
    if card_type == "AMEX":
        return 15
    return 16

def _prepare_card_pattern(value: str) -> str:
    """Prepara o padrão do cartão com o tamanho correto para cada bandeira"""
    cleaned = re.sub(r'[^0-9Xx]', '', value)
    if not cleaned:
        raise ValueError('INFORME UM BIN OU PADRÃO.')
    
    # Detecta a bandeira baseado nos primeiros dígitos
    bin_prefix = cleaned[:6] if len(cleaned) >= 6 else cleaned
    target_length = get_card_length(bin_prefix)
    
    if len(cleaned) < target_length:
        cleaned += 'X' * (target_length - len(cleaned))
    elif len(cleaned) > target_length:
        cleaned = cleaned[:target_length]
    
    return clean_pattern(cleaned)

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
    """Gera CVV com 3 ou 4 dígitos dependendo da bandeira"""
    value = str(cvv or 'random').strip().lower()
    
    # Se for AMEX (cvv com 4 dígitos)
    if value in ['random', 'xxxx', 'x']:
        # Vamos detectar a bandeira pelo contexto, mas por padrão geramos 3 dígitos
        # O tamanho será ajustado na geração do cartão
        return str(random.randint(0, 9999)).zfill(4) if value in ['xxxx', 'x'] else str(random.randint(0, 999)).zfill(3)
    
    if not re.fullmatch(r'\d{3,4}', value):
        return str(random.randint(0, 999)).zfill(3)
    return value

def _get_cvv_length(card_number: str) -> int:
    """Retorna o tamanho do CVV baseado na bandeira"""
    card_type = detect_card_type(card_number)
    if card_type == "AMEX":
        return 4
    return 3

def _random_cvv_by_card(card_number: str, cvv_input: object) -> str:
    """Gera CVV com o tamanho correto para a bandeira"""
    value = str(cvv_input or 'random').strip().lower()
    cvv_len = _get_cvv_length(card_number)
    
    if value == 'random' or value == 'x' * cvv_len or value == 'x':
        return str(random.randint(0, 10**cvv_len - 1)).zfill(cvv_len)
    
    if re.fullmatch(r'\d{' + str(cvv_len) + r'}', value):
        return value
    
    # Se o CVV fornecido não tem o tamanho correto, gera um aleatório
    return str(random.randint(0, 10**cvv_len - 1)).zfill(cvv_len)

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
        cvv_value = _random_cvv_by_card(card_number, line_cvv)
        
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
#  ENVIAR COM BOTÃO REDIRECIONAR
# ============================================================

def enviar_com_botao_redirecionar(chat_id, user_id, texto, comando, dados, qtd=None):
    """ENVIA MENSAGEM COM BOTÃO"""
    consulta_id = f"{user_id}_{int(time.time())}_{hashlib.md5(str(user_id).encode()).hexdigest()[:6]}"
    
    consultas_ativas[consulta_id] = {
        'user_id': user_id,
        'chat_id': chat_id,
        'comando': comando,
        'dados': dados,
        'qtd': qtd,
        'message_id': None,
        'timestamp': time.time()
    }
    
    link_pv = f"https://t.me/{BOT_USERNAME}?start=result_{consulta_id}"
    
    markup = {"inline_keyboard": [[{"text": "📱 VER RESULTADO NO PV", "url": link_pv}]]}
    
    msg = enviar_mensagem_com_retorno(
        chat_id,
        texto,
        parse_mode="Markdown",
        reply_markup=markup
    )
    
    if msg:
        consultas_ativas[consulta_id]['message_id'] = msg['message_id']
        
        def apagar_depois():
            time.sleep(TIMER_APAGAR)
            try:
                apagar_mensagem(chat_id, msg['message_id'])
            except:
                pass
        
        threading.Thread(target=apagar_depois, daemon=True).start()
    
    return msg

# ============================================================
#  ENVIAR RESULTADO PV
# ============================================================

def enviar_resultado_pv(user_id, comando, dados, qtd=None, chat_id_grupo=None, message_id_grupo=None):
    """ENVIA RESULTADO NO PV"""
    try:
        if comando == 'gen':
            cards = dados.get('cards', [])
            caption = dados.get('caption', '✅ Cartões gerados com sucesso!')
            
            if cards:
                nome_arquivo = "geradas.txt"
                with open(nome_arquivo, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(cards))
                
                enviar_arquivo(
                    user_id,
                    nome_arquivo,
                    caption
                )
                os.remove(nome_arquivo) if os.path.exists(nome_arquivo) else None
            else:
                enviar_mensagem(user_id, "❌ Nenhum cartão gerado.", parse_mode="Markdown")
                
        elif comando == 'help':
            texto = dados.get('texto', '')
            if texto:
                enviar_mensagem(user_id, texto, parse_mode="Markdown")
            
        elif comando == 'bin':
            texto = dados.get('texto', '')
            if texto:
                enviar_mensagem(user_id, texto, parse_mode="Markdown")
            
        elif comando == 'perfil':
            texto = dados.get('texto', '')
            if texto:
                enviar_mensagem(user_id, texto, parse_mode="Markdown")
            
        else:
            enviar_mensagem(user_id, "❌ Comando não reconhecido.", parse_mode="Markdown")
        
        if chat_id_grupo and message_id_grupo:
            time.sleep(0.5)
            apagar_mensagem(chat_id_grupo, message_id_grupo)
        
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar no PV: {e}")
        return False

# ============================================================
#  ROTAS FLASK - VERIFICADOR DE BINS
# ============================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>GERADOR · CAMBADA 🔥</title>
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
            --success-green: #00ff88;
            --danger-red: #ff3355;
            --card-bg: rgba(13, 14, 28, 0.95);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body {
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
            width: 100%;
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

        .app-container { max-width: 1200px; width: 100%; padding: 1rem 1rem 2rem; position: relative; z-index: 2; }
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
            padding: 0.6rem 1.2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            box-shadow: 0 10px 40px rgba(0,0,0,0.8);
            position: sticky;
            top: 0.5rem;
            z-index: 100;
            flex-wrap: wrap;
            gap: 0.5rem;
        }
        .header-left { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
        .logo-drw { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.1rem; color: #fff; letter-spacing: 1px; text-shadow: 0 0 15px rgba(123, 44, 255, 0.2); cursor: pointer; white-space: nowrap; }
        .logo-drw span { color: #7b2cff; }
        .header-nav { display: flex; gap: 0.5rem; list-style: none; flex-wrap: wrap; }
        .header-nav a { text-decoration: none; color: var(--text-muted); font-size: 0.75rem; transition: 0.3s ease; font-weight: 500; cursor: pointer; padding: 0.4rem 0.8rem; border-radius: 8px; white-space: nowrap; }
        .header-nav a:hover, .header-nav a.active { color: #fff; background: rgba(123, 44, 255, 0.15); }
        .header-right { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
        .header-tag { font-size: 0.7rem; color: var(--text-muted); background: rgba(255,255,255,0.04); padding: 0.2rem 0.8rem; border-radius: 20px; border: 1px solid rgba(255,255,255,0.05); }
        .telegram-link-header {
            display: flex; align-items: center; gap: 0.4rem;
            background: rgba(36, 156, 241, 0.1); padding: 0.3rem 0.8rem;
            border-radius: 20px; border: 1px solid rgba(36, 156, 241, 0.2);
            text-decoration: none; color: #fff; font-size: 0.7rem;
            transition: all 0.3s ease;
            white-space: nowrap;
        }
        .telegram-link-header:hover { border-color: #249cf1; box-shadow: 0 0 20px rgba(36, 156, 241, 0.2); }

        .section-content { display: none; animation: fadeInUp 0.6s forwards; }
        .section-content.active { display: block; }
        @keyframes fadeInUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

        .hero-section { display: flex; flex-direction: column; align-items: center; text-align: center; margin-bottom: 1.5rem; padding: 0.5rem 0; }
        .avatar-wrapper { position: relative; width: 80px; height: 80px; margin-bottom: 0.5rem; }
        .avatar-img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; border: 2px solid rgba(123, 44, 255, 0.2); box-shadow: 0 0 30px rgba(75, 15, 143, 0.3); }
        .avatar-glow { position: absolute; top: -10px; left: -10px; right: -10px; bottom: -10px; border-radius: 50%; background: radial-gradient(circle, rgba(123, 44, 255, 0.15) 0%, transparent 70%); z-index: -1; animation: pulseGlow 3s infinite ease-in-out; }
        @keyframes pulseGlow { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.05); opacity: 0.6; } }
        .hero-title { font-family: 'Space Grotesk', sans-serif; font-size: 2rem; font-weight: 700; background: linear-gradient(135deg, #fff 0%, #bb86fc 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .hero-subtitle { color: var(--text-muted); font-size: 0.8rem; letter-spacing: 2px; }

        .card { background: var(--bg-card); backdrop-filter: blur(16px); border: 1px solid var(--glass-border); border-radius: 16px; padding: 1rem; margin-bottom: 1.2rem; box-shadow: 0 20px 60px rgba(0,0,0,0.45); }
        .card-dark { background: var(--card-bg); border: 1px solid rgba(255,255,255,.05); }
        
        .bins-input { width: 100%; min-height: 80px; background: rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.05); border-radius: 10px; color: #00FFF0; padding: 0.8rem; font-family: 'JetBrains Mono'; outline: none; resize: vertical; font-size: 0.8rem; }
        .bins-input:focus { border-color: #7b2cff; box-shadow: 0 0 20px rgba(123, 44, 255, 0.1); }
        
        .card-inputs-row { display: flex; gap: 0.8rem; margin: 0.8rem 0; flex-wrap: wrap; }
        .card-input-group { flex: 1; min-width: 70px; }
        .card-input-group label { display: block; color: #8c8d9e; font-size: 0.6rem; margin-bottom: 3px; text-transform: uppercase; letter-spacing: 1px; }
        .card-select, .quantity-input { width: 100%; background: rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.05); border-radius: 8px; color: #00FFF0; padding: 0.6rem; font-family: 'JetBrains Mono'; outline: none; font-size: 0.8rem; }
        .quantity-input { flex: 0 0 70px; width: 70px; }
        
        .controls-row { display: flex; gap: 0.6rem; margin-bottom: 0.8rem; flex-wrap: wrap; }
        .btn { padding: 0.6rem 1.2rem; border-radius: 8px; border: none; font-weight: 700; cursor: pointer; font-family: 'JetBrains Mono'; transition: .3s; text-transform: uppercase; font-size: 0.7rem; }
        .btn-primary { flex: 1; background: #7928CA; color: #fff; min-width: 100px; }
        .btn-primary:hover { box-shadow: 0 5px 20px rgba(121, 40, 202, .5); transform: translateY(-1px); }
        .btn-cyber { background: transparent; border: 1px solid #00FFF0; color: #00FFF0; }
        .btn-cyber:hover { background: #00FFF0; color: #000; }
        .btn-danger { background: transparent; border: 1px solid #FF003C; color: #FF003C; }
        .btn-danger:hover { background: #FF003C; color: #fff; }
        .btn-success { background: transparent; border: 1px solid #00ff88; color: #00ff88; }
        .btn-success:hover { background: #00ff88; color: #000; }
        .btn-purple { background: transparent; border: 1px solid #7b2cff; color: #7b2cff; }
        .btn-purple:hover { background: #7b2cff; color: #fff; }
        .btn-sm { padding: 0.3rem 0.8rem; font-size: 0.6rem; }
        
        .cards-list { max-height: 250px; overflow-y: auto; background: rgba(0,0,0,.3); border-radius: 8px; padding: 0.6rem; margin-bottom: 0.8rem; font-family: 'JetBrains Mono'; white-space: pre-wrap; color: #00FFF0; font-size: 0.75rem; word-break: break-all; }
        .cards-list::-webkit-scrollbar { width: 3px; }
        .cards-list::-webkit-scrollbar-track { background: rgba(255,255,255,0.02); }
        .cards-list::-webkit-scrollbar-thumb { background: #7b2cff; border-radius: 3px; }

        /* VERIFICADOR */
        .bin-tabs { display: flex; gap: 0.3rem; margin-bottom: 0.8rem; flex-wrap: wrap; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 0.5rem; }
        .bin-tab-btn { padding: 0.4rem 1rem; border: none; background: transparent; color: var(--text-muted); cursor: pointer; font-family: 'Inter', sans-serif; font-weight: 600; font-size: 0.7rem; transition: 0.3s; border-radius: 6px; }
        .bin-tab-btn:hover { color: #fff; background: rgba(123, 44, 255, 0.1); }
        .bin-tab-btn.active { color: #fff; background: rgba(123, 44, 255, 0.2); }
        .bin-tab-content { display: none; padding: 0.5rem 0; }
        .bin-tab-content.active { display: block; }
        
        .bin-verify-input { width: 100%; background: rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.05); border-radius: 8px; color: #00FFF0; padding: 0.6rem 0.8rem; font-family: 'JetBrains Mono'; outline: none; font-size: 0.8rem; }
        .bin-verify-input:focus { border-color: #7b2cff; box-shadow: 0 0 20px rgba(123, 44, 255, 0.1); }
        
        .bin-search-row { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
        .bin-search-row select, .bin-search-row input { flex: 1; min-width: 100px; background: rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.05); border-radius: 8px; color: #00FFF0; padding: 0.5rem 0.6rem; font-family: 'JetBrains Mono'; outline: none; font-size: 0.7rem; }
        .bin-search-row select option { background: #1a1a2e; color: #fff; }
        .bin-search-row input::placeholder { color: #555; }
        
        .bin-result { background: rgba(0,0,0,.3); border-radius: 8px; padding: 0.8rem; font-family: 'JetBrains Mono'; color: #00FFF0; font-size: 0.8rem; min-height: 50px; max-height: 300px; overflow-y: auto; }
        .bin-result .label { color: #8c8d9e; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1px; }
        .bin-result .value { color: #fff; font-weight: 600; }
        .bin-result .error { color: #ff3355; }
        .bin-result-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.3rem 1rem; margin-top: 0.3rem; }
        .bin-result-grid .item { display: flex; justify-content: space-between; padding: 0.2rem 0; border-bottom: 1px solid rgba(255,255,255,0.03); font-size: 0.75rem; }
        .bin-result-list { max-height: 200px; overflow-y: auto; }
        .bin-result-list .item { padding: 0.2rem 0; border-bottom: 1px solid rgba(255,255,255,0.03); font-size: 0.7rem; display: flex; gap: 0.5rem; flex-wrap: wrap; }
        .bin-result-list .item .bin-code { color: #00FFF0; font-weight: 600; min-width: 60px; }
        .bin-result-list .item .bin-info { color: #8c8d9e; }
        .bin-count { color: #8c8d9e; font-size: 0.7rem; margin-bottom: 0.3rem; }

        footer { margin-top: 2rem; padding: 1rem 0; border-top: 1px solid rgba(255,255,255,0.03); display: flex; flex-direction: column; align-items: center; gap: 0.2rem; color: var(--text-muted); font-size: 0.7rem; text-align: center; }
        footer a { color: #7b2cff; text-decoration: none; }
        footer a:hover { color: #fff; }

        @media (max-width: 600px) { 
            .app-container { padding: 0.5rem; }
            .hero-title { font-size: 1.6rem; }
            .header-right { display: none; }
            .header-left { width: 100%; justify-content: center; flex-wrap: wrap; }
            .header-nav { justify-content: center; width: 100%; }
            .card-inputs-row { flex-direction: column; }
            .quantity-input { flex: 1 1 100%; width: 100%; }
            .card { padding: 0.6rem; }
            .bins-input { min-height: 60px; font-size: 0.7rem; }
            .btn { padding: 0.5rem 0.8rem; font-size: 0.6rem; }
            .controls-row { flex-direction: column; }
            .cards-list { font-size: 0.65rem; max-height: 150px; }
            .avatar-wrapper { width: 60px; height: 60px; }
            header { border-radius: 16px; padding: 0.4rem 0.6rem; margin-bottom: 1rem; }
            .bin-result-grid { grid-template-columns: 1fr; }
            .bin-search-row { flex-direction: column; }
            .bin-search-row select, .bin-search-row input { min-width: 100%; }
            .bin-tabs { justify-content: center; }
            .bin-tab-btn { padding: 0.3rem 0.6rem; font-size: 0.6rem; }
            .telegram-link-header span { display: none; }
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
                <li><a onclick="showSection('sistema')">GERADOR</a></li>
                <li><a onclick="showSection('verificador')">VERIFICADOR</a></li>
            </ul>
        </div>
        <div class="header-right">
            <span class="header-tag">@Drwed03</span>
            <a href="https://t.me/wedze_grupo" target="_blank" class="telegram-link-header">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2L2 9.5L8.5 14.5L12 22L21.5 2Z"/><path d="M21.5 2L8.5 14.5"/></svg>
                <span>TELEGRAM</span>
            </a>
        </div>
    </header>

    <main class="app-container">
        <!-- HOME -->
        <section id="section-home" class="section-content active">
            <div class="hero-section">
                <div class="avatar-wrapper">
                    <div class="avatar-glow"></div>
                    <img src="" alt="avatar" class="avatar-img">
                </div>
                <h1 class="hero-title">GERADOR · CAMBADA</h1>
                <p class="hero-subtitle">🔥 DRW03 • BINS • LUHN • WEBHOOK</p>
            </div>
            <div class="card">
                <p style="color: var(--text-muted); text-align: center; font-size: 0.9rem;">
                    ⚡ Gerador de cartões com validação LUHN<br>
                    Suporte AMEX (15 dígitos) • CVV 4 dígitos<br>
                    <span style="color: #7b2cff;">/gen 512267xxxxxx 10</span>
                </p>
            </div>
        </section>

        <!-- GERADOR -->
        <section id="section-sistema" class="section-content">
            <div class="card">
                <h2 style="margin-bottom: 0.8rem; font-size: 1.1rem;">🚀 GERADOR LUHN</h2>
                <textarea id="binsInput" class="bins-input" placeholder="Ex: 512267xxxxxx|random|random|xxx">512267xxxxxxxx</textarea>
                
                <div class="card-inputs-row">
                    <div class="card-input-group">
                        <label>MÊS</label>
                        <select id="monthSelect" class="card-select">
                            <option value="random">RANDOM</option>
                            <option value="01">01</option><option value="02">02</option>
                            <option value="03">03</option><option value="04">04</option>
                            <option value="05">05</option><option value="06">06</option>
                            <option value="07">07</option><option value="08">08</option>
                            <option value="09">09</option><option value="10">10</option>
                            <option value="11">11</option><option value="12">12</option>
                        </select>
                    </div>
                    <div class="card-input-group">
                        <label>ANO</label>
                        <select id="yearSelect" class="card-select">
                            <option value="random">RANDOM</option>
                            <option value="2025">2025</option>
                            <option value="2026">2026</option>
                            <option value="2027">2027</option>
                            <option value="2028">2028</option>
                            <option value="2029">2029</option>
                            <option value="2030">2030</option>
                        </select>
                    </div>
                    <div class="card-input-group">
                        <label>CVV</label>
                        <select id="cvvSelect" class="card-select">
                            <option value="random">RANDOM</option>
                            <option value="xxx">3 DÍGITOS</option>
                            <option value="xxxx">4 DÍGITOS</option>
                        </select>
                    </div>
                    <div class="card-input-group">
                        <label>QUANTIDADE</label>
                        <input type="number" id="quantityInput" class="quantity-input" value="10" min="1" max="1000">
                    </div>
                </div>

                <div class="controls-row">
                    <button class="btn btn-primary" onclick="gerarCartoes()">⚡ GERAR</button>
                    <button class="btn btn-cyber" onclick="copiarResultado()">📋 COPIAR</button>
                    <button class="btn btn-danger" onclick="limparResultado()">🗑️ LIMPAR</button>
                </div>

                <div id="cardsResult" class="cards-list" style="display:none;"></div>
                <div id="statusMessage" style="color: var(--text-muted); font-size: 0.8rem; margin-top: 0.5rem;"></div>
            </div>
        </section>

        <!-- VERIFICADOR -->
        <section id="section-verificador" class="section-content">
            <div class="card">
                <h2 style="margin-bottom: 0.8rem; font-size: 1.1rem;">🔍 VERIFICADOR DE BINS</h2>
                
                <div class="bin-tabs">
                    <button class="bin-tab-btn active" onclick="switchBinTab('verify', this)">VERIFICAR</button>
                    <button class="bin-tab-btn" onclick="switchBinTab('search', this)">BUSCA AVANÇADA</button>
                </div>

                <!-- Verificar BIN -->
                <div id="bin-tab-verify" class="bin-tab-content active">
                    <input type="text" id="binVerifyInput" class="bin-verify-input" placeholder="Digite o BIN (ex: 512267)" onkeypress="if(event.key==='Enter') verificarBin()">
                    <div class="controls-row" style="margin-top: 0.5rem;">
                        <button class="btn btn-primary" onclick="verificarBin()">🔍 VERIFICAR</button>
                    </div>
                    <div id="binResult" class="bin-result"></div>
                </div>

                <!-- Busca Avançada -->
                <div id="bin-tab-search" class="bin-tab-content">
                    <div class="bin-search-row">
                        <select id="searchBrand"><option value="">BANDEIRA</option></select>
                        <select id="searchCountry"><option value="">PAÍS</option></select>
                        <select id="searchType"><option value="">TIPO</option></select>
                        <select id="searchLevel"><option value="">NÍVEL</option></select>
                    </div>
                    <div class="bin-search-row">
                        <input type="text" id="searchBank" placeholder="Banco...">
                        <input type="text" id="searchBin" placeholder="BIN...">
                        <button class="btn btn-purple btn-sm" onclick="buscarBins()">🔍 BUSCAR</button>
                    </div>
                    <div id="searchResult" class="bin-result"></div>
                </div>
            </div>
        </section>

        <footer>
            <p>DRW03 · <a href="https://t.me/wedze_grupo" target="_blank">@wedze_grupo</a></p>
        </footer>
    </main>

    <script>
        // ============================================================
        //  NAVEGAÇÃO
        // ============================================================
        function showSection(id) {
            document.querySelectorAll('.section-content').forEach(el => el.classList.remove('active'));
            document.getElementById('section-' + id).classList.add('active');
            document.querySelectorAll('.header-nav a').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.header-nav a').forEach(el => {
                if (el.textContent.trim().toLowerCase() === 
                    (id === 'home' ? 'início' : id === 'sistema' ? 'gerador' : 'verificador')) {
                    el.classList.add('active');
                }
            });
        }

        // ============================================================
        //  GERADOR
        // ============================================================
        function gerarCartoes() {
            const pattern = document.getElementById('binsInput').value.trim();
            const month = document.getElementById('monthSelect').value;
            const year = document.getElementById('yearSelect').value;
            const cvv = document.getElementById('cvvSelect').value;
            const quantity = parseInt(document.getElementById('quantityInput').value) || 10;
            
            if (!pattern) {
                document.getElementById('statusMessage').textContent = '❌ Digite um padrão!';
                return;
            }
            
            document.getElementById('statusMessage').textContent = '⏳ Gerando...';
            
            fetch('/api/luhn/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pattern, month, year, cvv, quantity })
            })
            .then(res => res.json())
            .then(data => {
                const resultDiv = document.getElementById('cardsResult');
                const statusDiv = document.getElementById('statusMessage');
                
                if (data.ok) {
                    resultDiv.style.display = 'block';
                    resultDiv.textContent = data.results.join('\n');
                    statusDiv.textContent = `✅ ${data.count} cartões gerados!`;
                    statusDiv.style.color = 'var(--success-green)';
                } else {
                    statusDiv.textContent = '❌ ' + (data.error || 'Erro ao gerar');
                    statusDiv.style.color = 'var(--danger-red)';
                }
            })
            .catch(err => {
                document.getElementById('statusMessage').textContent = '❌ Erro na requisição';
            });
        }

        function copiarResultado() {
            const resultDiv = document.getElementById('cardsResult');
            if (resultDiv.textContent) {
                navigator.clipboard.writeText(resultDiv.textContent);
                document.getElementById('statusMessage').textContent = '📋 Copiado!';
            }
        }

        function limparResultado() {
            document.getElementById('cardsResult').style.display = 'none';
            document.getElementById('cardsResult').textContent = '';
            document.getElementById('statusMessage').textContent = '';
        }

        // ============================================================
        //  VERIFICADOR BIN
        // ============================================================
        function switchBinTab(tab, btn) {
            document.querySelectorAll('.bin-tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.bin-tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById('bin-tab-' + tab).classList.add('active');
            if (btn) btn.classList.add('active');
        }

        function verificarBin() {
            const bin = document.getElementById('binVerifyInput').value.trim();
            const resultDiv = document.getElementById('binResult');
            
            if (!bin || bin.length < 6) {
                resultDiv.innerHTML = '<span class="error">❌ Digite um BIN válido (mínimo 6 dígitos)</span>';
                return;
            }
            
            fetch('/api/check_bin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bin: bin })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success && data.data) {
                    const d = data.data;
                    resultDiv.innerHTML = `
                        <div class="bin-result-grid">
                            <div class="item"><span>🏷️ Bandeira</span><span class="value">${d.brand || 'DESCONHECIDO'}</span></div>
                            <div class="item"><span>💳 Tipo</span><span class="value">${d.type || 'DESCONHECIDO'}</span></div>
                            <div class="item"><span>🏆 Nível</span><span class="value">${d.level || 'N/A'}</span></div>
                            <div class="item"><span>🏦 Banco</span><span class="value">${d.bank || 'DESCONHECIDO'}</span></div>
                            <div class="item"><span>🌎 País</span><span class="value">${d.country || 'INTERNACIONAL'}</span></div>
                        </div>
                    `;
                } else {
                    resultDiv.innerHTML = `<span class="error">❌ BIN não encontrado</span>`;
                }
            })
            .catch(() => {
                resultDiv.innerHTML = `<span class="error">❌ Erro na consulta</span>`;
            });
        }

        function buscarBins() {
            const brand = document.getElementById('searchBrand').value;
            const country = document.getElementById('searchCountry').value;
            const type = document.getElementById('searchType').value;
            const level = document.getElementById('searchLevel').value;
            const bank = document.getElementById('searchBank').value.trim();
            const bin = document.getElementById('searchBin').value.trim();
            
            const resultDiv = document.getElementById('searchResult');
            resultDiv.innerHTML = '⏳ Buscando...';
            
            fetch('/api/search_bins', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ brand, country, type, level, bank, bin })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success && data.results) {
                    if (data.results.length === 0) {
                        resultDiv.innerHTML = '🔍 Nenhum BIN encontrado';
                        return;
                    }
                    let html = `<div class="bin-count">📊 ${data.results.length} BINS encontrados</div><div class="bin-result-list">`;
                    data.results.forEach(item => {
                        html += `<div class="item">
                            <span class="bin-code">${item.bin}</span>
                            <span class="bin-info">${item.brand} | ${item.type} | ${item.country}</span>
                        </div>`;
                    });
                    html += '</div>';
                    resultDiv.innerHTML = html;
                } else {
                    resultDiv.innerHTML = '❌ Erro na busca';
                }
            })
            .catch(() => {
                resultDiv.innerHTML = '❌ Erro na requisição';
            });
        }

        // ============================================================
        //  CARREGAR FILTROS
        // ============================================================
        function loadFilters() {
            fetch('/api/brands').then(r => r.json()).then(data => {
                const sel = document.getElementById('searchBrand');
                if (data.brands) data.brands.forEach(b => {
                    const opt = document.createElement('option');
                    opt.value = b; opt.textContent = b;
                    sel.appendChild(opt);
                });
            });
            
            fetch('/api/countries').then(r => r.json()).then(data => {
                const sel = document.getElementById('searchCountry');
                if (data.countries) data.countries.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c; opt.textContent = c;
                    sel.appendChild(opt);
                });
            });
            
            fetch('/api/types').then(r => r.json()).then(data => {
                const sel = document.getElementById('searchType');
                if (data.types) data.types.forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t; opt.textContent = t;
                    sel.appendChild(opt);
                });
            });
            
            fetch('/api/levels').then(r => r.json()).then(data => {
                const sel = document.getElementById('searchLevel');
                if (data.levels) data.levels.forEach(l => {
                    const opt = document.createElement('option');
                    opt.value = l; opt.textContent = l;
                    sel.appendChild(opt);
                });
            });
        }

        // ============================================================
        //  NETWORK CANVAS
        // ============================================================
        (function() {
            const canvas = document.getElementById('network-canvas');
            const ctx = canvas.getContext('2d');
            let width, height;
            const particles = [];
            const numParticles = 60;
            const maxDist = 120;

            function resize() {
                width = canvas.width = window.innerWidth;
                height = canvas.height = window.innerHeight;
            }
            window.addEventListener('resize', resize);
            resize();

            class Particle {
                constructor() {
                    this.reset();
                }
                reset() {
                    this.x = Math.random() * width;
                    this.y = Math.random() * height;
                    this.vx = (Math.random() - 0.5) * 0.6;
                    this.vy = (Math.random() - 0.5) * 0.6;
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
                    ctx.fillStyle = 'rgba(123, 44, 255, 0.4)';
                    ctx.fill();
                }
            }

            for (let i = 0; i < numParticles; i++) {
                particles.push(new Particle());
            }

            function drawLines() {
                for (let i = 0; i < particles.length; i++) {
                    for (let j = i + 1; j < particles.length; j++) {
                        const dx = particles[i].x - particles[j].x;
                        const dy = particles[i].y - particles[j].y;
                        const dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < maxDist) {
                            const opacity = 1 - (dist / maxDist);
                            ctx.beginPath();
                            ctx.moveTo(particles[i].x, particles[i].y);
                            ctx.lineTo(particles[j].x, particles[j].y);
                            ctx.strokeStyle = `rgba(123, 44, 255, ${opacity * 0.25})`;
                            ctx.lineWidth = 0.6;
                            ctx.stroke();
                        }
                    }
                }
            }

            function animate() {
                ctx.clearRect(0, 0, width, height);
                particles.forEach(p => { p.update(); p.draw(); });
                drawLines();
                requestAnimationFrame(animate);
            }
            animate();
        })();

        // Inicializar
        loadFilters();
    </script>
</body>
</html>
"""

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
        
        if results:
            user_id = data.get('user_id', ADMIN_ID)
            username = data.get('username', None)
            enviar_webhook(pattern, results, user_id, username, origem='site')
        
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

@app.route('/api/check_bin', methods=['POST'])
def check_bin():
    bin_num = request.json.get('bin', '')
    bin_clean = re.sub(r'[^0-9]', '', bin_num)
    info, _ = get_bin_info(bin_clean[:6])
    if info:
        return jsonify({'success': True, 'data': info})
    return jsonify({'success': False, 'message': 'BIN nao encontrada'})

@app.route('/api/search_bins', methods=['POST'])
def search_bins():
    filters = request.json
    brand = filters.get('brand', '').strip().upper()
    country = filters.get('country', '').strip().upper()
    bank = filters.get('bank', '').strip().upper()
    tipo = filters.get('type', '').strip().upper()
    level = filters.get('level', '').strip().upper()
    bin_search = filters.get('bin', '').strip()
    
    results = []
    for bin_code, info in BINS_DATA.items():
        match = True
        if brand and info.get('brand', '').upper() != brand:
            match = False
        if country and info.get('country', '').upper() != country:
            match = False
        if bank and bank not in info.get('bank', '').upper():
            match = False
        if tipo and info.get('type', '').upper() != tipo:
            match = False
        if level and info.get('level', '').upper() != level:
            match = False
        if bin_search and bin_search not in bin_code:
            match = False
        if match:
            results.append({
                'bin': bin_code,
                'brand': info.get('brand', ''),
                'type': info.get('type', ''),
                'level': info.get('level', ''),
                'bank': info.get('bank', ''),
                'country': info.get('country', '')
            })
    
    return jsonify({'success': True, 'results': results[:500]})

@app.route('/api/countries')
def countries():
    countries = sorted(set(info.get('country', '') for info in BINS_DATA.values() if info.get('country')))
    return jsonify({'success': True, 'countries': countries})

@app.route('/api/brands')
def brands():
    brands = sorted(set(info.get('brand', '') for info in BINS_DATA.values() if info.get('brand')))
    return jsonify({'success': True, 'brands': brands})

@app.route('/api/types')
def types():
    types = sorted(set(info.get('type', '') for info in BINS_DATA.values() if info.get('type')))
    return jsonify({'success': True, 'types': types})

@app.route('/api/levels')
def levels():
    levels = sorted(set(info.get('level', '') for info in BINS_DATA.values() if info.get('level')))
    return jsonify({'success': True, 'levels': levels})

@app.get('/health')
def health():
    return jsonify({'ok': True, 'service': 'GERADOR-BOT'})

@app.errorhandler(413)
def too_large(_error):
    return jsonify({'ok': False, 'error': 'REQUISIÇÃO MUITO GRANDE.'}), 413

# ============================================================
#  PROCESSADOR DE COMANDOS DO BOT
# ============================================================

def processar_comando_bot(user_id: int, chat_id: int, message_id: int, comando: str, args: str, is_group: bool = False, user_info: Dict = None) -> bool:
    """PROCESSA COMANDOS DO BOT"""
    
    # ====== /START ======
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
                
                comando_interno = consulta.get('comando')
                dados = consulta.get('dados', {})
                qtd = consulta.get('qtd')
                chat_id_grupo = consulta.get('chat_id')
                message_id_grupo = consulta.get('message_id')
                
                del consultas_ativas[consulta_id]
                
                enviar_resultado_pv(user_id, comando_interno, dados, qtd, chat_id_grupo, message_id_grupo)
                return True
            else:
                enviar_mensagem(chat_id, "❌ *CONSULTA EXPIRADA OU INVÁLIDA.*", parse_mode='Markdown')
                return True
        
        # /START NORMAL
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
        
        # VERIFICA OS PASSOS
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
    
    # ====== CALLBACK QUERY ======
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
    
    # ====== /PERFIL ======
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
    
    # ====== /HELP ======
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
            f"`/gen 512267 40`\n"
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
    
    # ====== /GEN ======
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
        
        # VERIFICA SE TEM QUANTIDADE NO FINAL
        qty = 10
        pattern = args
        
        if len(parts) >= 2 and parts[-1].isdigit():
            qty = int(parts[-1])
            pattern = ' '.join(parts[:-1])
        
        # SE TIVER PIPE (|), USA A MATRIZ COMPLETA
        if '|' in pattern:
            matrix_parts = pattern.split('|')
            if len(matrix_parts) >= 4:
                cc_pattern, mm_pattern, yy_pattern, cvv_pattern = matrix_parts[0], matrix_parts[1], matrix_parts[2], matrix_parts[3]
            else:
                cc_pattern = matrix_parts[0]
                mm_pattern = 'random'
                yy_pattern = 'random'
                cvv_pattern = 'xxx'
        else:
            # APENAS BIN - COMPLETA COM X
            cc_pattern = re.sub(r'[^0-9]', '', pattern)
            # Detecta se é AMEX para usar 15 dígitos
            if len(cc_pattern) >= 2 and cc_pattern[:2] in ['34', '37']:
                target_len = 15
            else:
                target_len = 16
            if len(cc_pattern) < target_len:
                cc_pattern += 'x' * (target_len - len(cc_pattern))
            mm_pattern = 'random'
            yy_pattern = 'random'
            cvv_pattern = 'xxx'
        
        # SALVA A MATRIZ ORIGINAL PARA O WEBHOOK
        matriz_original = f"{cc_pattern}|{mm_pattern}|{yy_pattern}|{cvv_pattern}"
        
        if qty < 1 or qty > 1000:
            if is_group:
                apagar_mensagem(chat_id, message_id)
                msg = enviar_mensagem_com_retorno(chat_id, '❌ *QUANTIDADE DEVE SER ENTRE 1 E 1000.*', parse_mode='Markdown')
                if msg:
                    threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
            else:
                enviar_mensagem(chat_id, '❌ *QUANTIDADE DEVE SER ENTRE 1 E 1000.*', parse_mode='Markdown')
            return True
        
        try:
            results = generate_batch(f"{cc_pattern}|{mm_pattern}|{yy_pattern}|{cvv_pattern}", qty, mm_pattern, yy_pattern, cvv_pattern)
            
            if not results:
                if is_group:
                    apagar_mensagem(chat_id, message_id)
                    msg = enviar_mensagem_com_retorno(chat_id, '❌ *NENHUM CARTÃO GERADO.*', parse_mode='Markdown')
                    if msg:
                        threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
                else:
                    enviar_mensagem(chat_id, '❌ *NENHUM CARTÃO GERADO.*', parse_mode='Markdown')
                return True
            
            # OBTÉM O USERNAME DO USUÁRIO
            username = None
            if user_info:
                username = user_info.get('username')
            if not username:
                try:
                    user_info_resp = fazer_request('getChat', {'chat_id': user_id})
                    if user_info_resp and user_info_resp.get('ok'):
                        username = user_info_resp['result'].get('username', None)
                except:
                    pass
            
            # ENVIA WEBHOOK (BOT) - COM @MENÇÃO
            enviar_webhook(matriz_original, results, user_id, username, origem='bot')
            
            info, _ = get_bin_info(cc_pattern[:6]) if cc_pattern[:6] else (None, None)
            
            if info:
                caption = (
                    f"✅ *Cartões gerados com sucesso!*\n\n"
                    f"🔢 *BIN:* `{cc_pattern[:6]}`\n"
                    f"🏷️ *Bandeira:* `{info['brand']}`\n"
                    f"💳 *Tipo:* `{info['type']}`\n"
                    f"🏆 *Nível:* `{info['level']}`\n"
                    f"🏦 *Banco:* `{info['bank']}`\n"
                    f"🌎 *País:* `{info['country']}`\n"
                    f"📦 *Quantidade:* `{qty}`\n\n"
                    f"📝 *Exemplo:* `{results[0] if results else ''}`"
                )
            else:
                card_type = detect_card_type(cc_pattern[:6])
                caption = (
                    f"✅ *Cartões gerados com sucesso!*\n\n"
                    f"🔢 *BIN:* `{cc_pattern[:6]}`\n"
                    f"🏷️ *Bandeira:* `{card_type}`\n"
                    f"📦 *Quantidade:* `{qty}`\n\n"
                    f"📝 *Exemplo:* `{results[0] if results else ''}`"
                )
            
            # CRIA CONSULTA PARA REDIRECIONAR
            consulta_id = f"{user_id}_{int(time.time())}_{hashlib.md5(str(results).encode()).hexdigest()[:6]}"
            
            consultas_ativas[consulta_id] = {
                'user_id': user_id,
                'chat_id': chat_id,
                'comando': 'gen',
                'dados': {'cards': results, 'caption': caption},
                'qtd': qty,
                'message_id': None,
                'timestamp': time.time()
            }
            
            if is_group:
                apagar_mensagem(chat_id, message_id)
                
                link_pv = f"https://t.me/{BOT_USERNAME}?start=result_{consulta_id}"
                markup = {"inline_keyboard": [[{"text": "📥 BAIXAR .TXT NO PV", "url": link_pv}]]}
                
                texto_grupo = (
                    f"✅ *Cartões gerados!*\n"
                    f"🔢 BIN: `{cc_pattern[:6]}`\n"
                    f"🏷️ Bandeira: `{info['brand'] if info else card_type}`\n"
                    f"📦 Quantidade: `{qty}`\n\n"
                    f"📱 Clique no botão abaixo para baixar a lista completa no seu PV."
                )
                
                msg = enviar_mensagem_com_retorno(chat_id, texto_grupo, parse_mode='Markdown', reply_markup=markup)
                if msg:
                    consultas_ativas[consulta_id]['message_id'] = msg['message_id']
                    threading.Thread(target=lambda: time.sleep(TIMER_APAGAR) or apagar_mensagem(chat_id, msg['message_id']) if consulta_id in consultas_ativas else None, daemon=True).start()
            else:
                nome_arquivo = "geradas.txt"
                with open(nome_arquivo, 'w', encoding='utf-8') as f:
                    for card in results:
                        f.write(card + "\n")
                enviar_arquivo(chat_id, nome_arquivo, caption)
                os.remove(nome_arquivo) if os.path.exists(nome_arquivo) else None
            
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
    
    # ====== /BIN ======
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
        
        info, _ = get_bin_info(bin_input)
        
        resposta_completa = formatar_resposta_bin_completa(info, bin_input)
        resposta_resumo = formatar_resposta_bin_resumo(info, bin_input)
        
        if is_group:
            apagar_mensagem(chat_id, message_id)
            
            enviar_com_botao_redirecionar(
                chat_id,
                user_id,
                resposta_resumo,
                'bin',
                {'texto': resposta_completa}
            )
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
                    user_info = {
                        'id': user_id,
                        'username': message['from'].get('username'),
                        'first_name': message['from'].get('first_name', ''),
                        'last_name': message['from'].get('last_name', '')
                    }
                    
                    if not texto or not texto.startswith('/'):
                        continue
                    partes = texto.split(' ', 1)
                    comando = partes[0].lower()
                    args = partes[1] if len(partes) > 1 else ''
                    if comando in ['/start', '/help', '/gen', '/bin', '/perfil']:
                        try:
                            is_group = message['chat']['type'] in ['group', 'supergroup']
                            processar_comando_bot(user_id, chat_id, message_id, comando, args, is_group, user_info)
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
#  MAIN
# ============================================================

if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════╗
    ║   🔥 GERADOR + BOT BIN + WEBHOOK        ║
    ║   DRW03 - AMEX 15 DÍGITOS - CVV 4       ║
    ╚══════════════════════════════════════════╝
    """)
    
    init_db()
    load_bins_from_csv()
    
    # Inicia o polling em thread separada
    thread_polling = threading.Thread(target=polling, daemon=True)
    thread_polling.start()
    
    # Inicia o servidor Flask
    app.run(host='0.0.0.0', port=PORT, debug=False)" alt="avatar" class="avatar-img">
                </div>
                <h1 class="hero-title">GERADOR · CAMBADA</h1>
                <p class="hero-subtitle">🔥 DRW03 • BINS • LUHN • WEBHOOK</p>
            </div>
            <div class="card">
                <p style="color: var(--text-muted); text-align: center; font-size: 0.9rem;">
                    ⚡ Gerador de cartões com validação LUHN<br>
                    Suporte AMEX (15 dígitos) • CVV 4 dígitos<br>
                    <span style="color: #7b2cff;">/gen 512267xxxxxx 10</span>
                </p>
            </div>
        </section>

        <!-- GERADOR -->
        <section id="section-sistema" class="section-content">
            <div class="card">
                <h2 style="margin-bottom: 0.8rem; font-size: 1.1rem;">🚀 GERADOR LUHN</h2>
                <textarea id="binsInput" class="bins-input" placeholder="Ex: 512267xxxxxx|random|random|xxx">512267xxxxxxxx</textarea>
                
                <div class="card-inputs-row">
                    <div class="card-input-group">
                        <label>MÊS</label>
                        <select id="monthSelect" class="card-select">
                            <option value="random">RANDOM</option>
                            <option value="01">01</option><option value="02">02</option>
                            <option value="03">03</option><option value="04">04</option>
                            <option value="05">05</option><option value="06">06</option>
                            <option value="07">07</option><option value="08">08</option>
                            <option value="09">09</option><option value="10">10</option>
                            <option value="11">11</option><option value="12">12</option>
                        </select>
                    </div>
                    <div class="card-input-group">
                        <label>ANO</label>
                        <select id="yearSelect" class="card-select">
                            <option value="random">RANDOM</option>
                            <option value="2025">2025</option>
                            <option value="2026">2026</option>
                            <option value="2027">2027</option>
                            <option value="2028">2028</option>
                            <option value="2029">2029</option>
                            <option value="2030">2030</option>
                        </select>
                    </div>
                    <div class="card-input-group">
                        <label>CVV</label>
                        <select id="cvvSelect" class="card-select">
                            <option value="random">RANDOM</option>
                            <option value="xxx">3 DÍGITOS</option>
                            <option value="xxxx">4 DÍGITOS</option>
                        </select>
                    </div>
                    <div class="card-input-group">
                        <label>QUANTIDADE</label>
                        <input type="number" id="quantityInput" class="quantity-input" value="10" min="1" max="1000">
                    </div>
                </div>

                <div class="controls-row">
                    <button class="btn btn-primary" onclick="gerarCartoes()">⚡ GERAR</button>
                    <button class="btn btn-cyber" onclick="copiarResultado()">📋 COPIAR</button>
                    <button class="btn btn-danger" onclick="limparResultado()">🗑️ LIMPAR</button>
                </div>

                <div id="cardsResult" class="cards-list" style="display:none;"></div>
                <div id="statusMessage" style="color: var(--text-muted); font-size: 0.8rem; margin-top: 0.5rem;"></div>
            </div>
        </section>

        <!-- VERIFICADOR -->
        <section id="section-verificador" class="section-content">
            <div class="card">
                <h2 style="margin-bottom: 0.8rem; font-size: 1.1rem;">🔍 VERIFICADOR DE BINS</h2>
                
                <div class="bin-tabs">
                    <button class="bin-tab-btn active" onclick="switchBinTab('verify', this)">VERIFICAR</button>
                    <button class="bin-tab-btn" onclick="switchBinTab('search', this)">BUSCA AVANÇADA</button>
                </div>

                <!-- Verificar BIN -->
                <div id="bin-tab-verify" class="bin-tab-content active">
                    <input type="text" id="binVerifyInput" class="bin-verify-input" placeholder="Digite o BIN (ex: 512267)" onkeypress="if(event.key==='Enter') verificarBin()">
                    <div class="controls-row" style="margin-top: 0.5rem;">
                        <button class="btn btn-primary" onclick="verificarBin()">🔍 VERIFICAR</button>
                    </div>
                    <div id="binResult" class="bin-result"></div>
                </div>

                <!-- Busca Avançada -->
                <div id="bin-tab-search" class="bin-tab-content">
                    <div class="bin-search-row">
                        <select id="searchBrand"><option value="">BANDEIRA</option></select>
                        <select id="searchCountry"><option value="">PAÍS</option></select>
                        <select id="searchType"><option value="">TIPO</option></select>
                        <select id="searchLevel"><option value="">NÍVEL</option></select>
                    </div>
                    <div class="bin-search-row">
                        <input type="text" id="searchBank" placeholder="Banco...">
                        <input type="text" id="searchBin" placeholder="BIN...">
                        <button class="btn btn-purple btn-sm" onclick="buscarBins()">🔍 BUSCAR</button>
                    </div>
                    <div id="searchResult" class="bin-result"></div>
                </div>
            </div>
        </section>

        <footer>
            <p>DRW03 · <a href="https://t.me/wedze_grupo" target="_blank">@wedze_grupo</a></p>
        </footer>
    </main>

    <script>
        // ============================================================
        //  NAVEGAÇÃO
        // ============================================================
        function showSection(id) {
            document.querySelectorAll('.section-content').forEach(el => el.classList.remove('active'));
            document.getElementById('section-' + id).classList.add('active');
            document.querySelectorAll('.header-nav a').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.header-nav a').forEach(el => {
                if (el.textContent.trim().toLowerCase() === 
                    (id === 'home' ? 'início' : id === 'sistema' ? 'gerador' : 'verificador')) {
                    el.classList.add('active');
                }
            });
        }

        // ============================================================
        //  GERADOR
        // ============================================================
        function gerarCartoes() {
            const pattern = document.getElementById('binsInput').value.trim();
            const month = document.getElementById('monthSelect').value;
            const year = document.getElementById('yearSelect').value;
            const cvv = document.getElementById('cvvSelect').value;
            const quantity = parseInt(document.getElementById('quantityInput').value) || 10;
            
            if (!pattern) {
                document.getElementById('statusMessage').textContent = '❌ Digite um padrão!';
                return;
            }
            
            document.getElementById('statusMessage').textContent = '⏳ Gerando...';
            
            fetch('/api/luhn/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pattern, month, year, cvv, quantity })
            })
            .then(res => res.json())
            .then(data => {
                const resultDiv = document.getElementById('cardsResult');
                const statusDiv = document.getElementById('statusMessage');
                
                if (data.ok) {
                    resultDiv.style.display = 'block';
                    resultDiv.textContent = data.results.join('\n');
                    statusDiv.textContent = `✅ ${data.count} cartões gerados!`;
                    statusDiv.style.color = 'var(--success-green)';
                } else {
                    statusDiv.textContent = '❌ ' + (data.error || 'Erro ao gerar');
                    statusDiv.style.color = 'var(--danger-red)';
                }
            })
            .catch(err => {
                document.getElementById('statusMessage').textContent = '❌ Erro na requisição';
            });
        }

        function copiarResultado() {
            const resultDiv = document.getElementById('cardsResult');
            if (resultDiv.textContent) {
                navigator.clipboard.writeText(resultDiv.textContent);
                document.getElementById('statusMessage').textContent = '📋 Copiado!';
            }
        }

        function limparResultado() {
            document.getElementById('cardsResult').style.display = 'none';
            document.getElementById('cardsResult').textContent = '';
            document.getElementById('statusMessage').textContent = '';
        }

        // ============================================================
        //  VERIFICADOR BIN
        // ============================================================
        function switchBinTab(tab, btn) {
            document.querySelectorAll('.bin-tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.bin-tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById('bin-tab-' + tab).classList.add('active');
            if (btn) btn.classList.add('active');
        }

        function verificarBin() {
            const bin = document.getElementById('binVerifyInput').value.trim();
            const resultDiv = document.getElementById('binResult');
            
            if (!bin || bin.length < 6) {
                resultDiv.innerHTML = '<span class="error">❌ Digite um BIN válido (mínimo 6 dígitos)</span>';
                return;
            }
            
            fetch('/api/check_bin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bin: bin })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success && data.data) {
                    const d = data.data;
                    resultDiv.innerHTML = `
                        <div class="bin-result-grid">
                            <div class="item"><span>🏷️ Bandeira</span><span class="value">${d.brand || 'DESCONHECIDO'}</span></div>
                            <div class="item"><span>💳 Tipo</span><span class="value">${d.type || 'DESCONHECIDO'}</span></div>
                            <div class="item"><span>🏆 Nível</span><span class="value">${d.level || 'N/A'}</span></div>
                            <div class="item"><span>🏦 Banco</span><span class="value">${d.bank || 'DESCONHECIDO'}</span></div>
                            <div class="item"><span>🌎 País</span><span class="value">${d.country || 'INTERNACIONAL'}</span></div>
                        </div>
                    `;
                } else {
                    resultDiv.innerHTML = `<span class="error">❌ BIN não encontrado</span>`;
                }
            })
            .catch(() => {
                resultDiv.innerHTML = `<span class="error">❌ Erro na consulta</span>`;
            });
        }

        function buscarBins() {
            const brand = document.getElementById('searchBrand').value;
            const country = document.getElementById('searchCountry').value;
            const type = document.getElementById('searchType').value;
            const level = document.getElementById('searchLevel').value;
            const bank = document.getElementById('searchBank').value.trim();
            const bin = document.getElementById('searchBin').value.trim();
            
            const resultDiv = document.getElementById('searchResult');
            resultDiv.innerHTML = '⏳ Buscando...';
            
            fetch('/api/search_bins', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ brand, country, type, level, bank, bin })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success && data.results) {
                    if (data.results.length === 0) {
                        resultDiv.innerHTML = '🔍 Nenhum BIN encontrado';
                        return;
                    }
                    let html = `<div class="bin-count">📊 ${data.results.length} BINS encontrados</div><div class="bin-result-list">`;
                    data.results.forEach(item => {
                        html += `<div class="item">
                            <span class="bin-code">${item.bin}</span>
                            <span class="bin-info">${item.brand} | ${item.type} | ${item.country}</span>
                        </div>`;
                    });
                    html += '</div>';
                    resultDiv.innerHTML = html;
                } else {
                    resultDiv.innerHTML = '❌ Erro na busca';
                }
            })
            .catch(() => {
                resultDiv.innerHTML = '❌ Erro na requisição';
            });
        }

        // ============================================================
        //  CARREGAR FILTROS
        // ============================================================
        function loadFilters() {
            fetch('/api/brands').then(r => r.json()).then(data => {
                const sel = document.getElementById('searchBrand');
                if (data.brands) data.brands.forEach(b => {
                    const opt = document.createElement('option');
                    opt.value = b; opt.textContent = b;
                    sel.appendChild(opt);
                });
            });
            
            fetch('/api/countries').then(r => r.json()).then(data => {
                const sel = document.getElementById('searchCountry');
                if (data.countries) data.countries.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c; opt.textContent = c;
                    sel.appendChild(opt);
                });
            });
            
            fetch('/api/types').then(r => r.json()).then(data => {
                const sel = document.getElementById('searchType');
                if (data.types) data.types.forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t; opt.textContent = t;
                    sel.appendChild(opt);
                });
            });
            
            fetch('/api/levels').then(r => r.json()).then(data => {
                const sel = document.getElementById('searchLevel');
                if (data.levels) data.levels.forEach(l => {
                    const opt = document.createElement('option');
                    opt.value = l; opt.textContent = l;
                    sel.appendChild(opt);
                });
            });
        }

        // ============================================================
        //  NETWORK CANVAS
        // ============================================================
        (function() {
            const canvas = document.getElementById('network-canvas');
            const ctx = canvas.getContext('2d');
            let width, height;
            const particles = [];
            const numParticles = 60;
            const maxDist = 120;

            function resize() {
                width = canvas.width = window.innerWidth;
                height = canvas.height = window.innerHeight;
            }
            window.addEventListener('resize', resize);
            resize();

            class Particle {
                constructor() {
                    this.reset();
                }
                reset() {
                    this.x = Math.random() * width;
                    this.y = Math.random() * height;
                    this.vx = (Math.random() - 0.5) * 0.6;
                    this.vy = (Math.random() - 0.5) * 0.6;
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
                    ctx.fillStyle = 'rgba(123, 44, 255, 0.4)';
                    ctx.fill();
                }
            }

            for (let i = 0; i < numParticles; i++) {
                particles.push(new Particle());
            }

            function drawLines() {
                for (let i = 0; i < particles.length; i++) {
                    for (let j = i + 1; j < particles.length; j++) {
                        const dx = particles[i].x - particles[j].x;
                        const dy = particles[i].y - particles[j].y;
                        const dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < maxDist) {
                            const opacity = 1 - (dist / maxDist);
                            ctx.beginPath();
                            ctx.moveTo(particles[i].x, particles[i].y);
                            ctx.lineTo(particles[j].x, particles[j].y);
                            ctx.strokeStyle = `rgba(123, 44, 255, ${opacity * 0.25})`;
                            ctx.lineWidth = 0.6;
                            ctx.stroke();
                        }
                    }
                }
            }

            function animate() {
                ctx.clearRect(0, 0, width, height);
                particles.forEach(p => { p.update(); p.draw(); });
                drawLines();
                requestAnimationFrame(animate);
            }
            animate();
        })();

        // Inicializar
        loadFilters();
    </script>
</body>
</html>
"""

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
        
        if results:
            user_id = data.get('user_id', ADMIN_ID)
            username = data.get('username', None)
            enviar_webhook(pattern, results, user_id, username, origem='site')
        
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

@app.route('/api/check_bin', methods=['POST'])
def check_bin():
    bin_num = request.json.get('bin', '')
    bin_clean = re.sub(r'[^0-9]', '', bin_num)
    info, _ = get_bin_info(bin_clean[:6])
    if info:
        return jsonify({'success': True, 'data': info})
    return jsonify({'success': False, 'message': 'BIN nao encontrada'})

@app.route('/api/search_bins', methods=['POST'])
def search_bins():
    filters = request.json
    brand = filters.get('brand', '').strip().upper()
    country = filters.get('country', '').strip().upper()
    bank = filters.get('bank', '').strip().upper()
    tipo = filters.get('type', '').strip().upper()
    level = filters.get('level', '').strip().upper()
    bin_search = filters.get('bin', '').strip()
    
    results = []
    for bin_code, info in BINS_DATA.items():
        match = True
        if brand and info.get('brand', '').upper() != brand:
            match = False
        if country and info.get('country', '').upper() != country:
            match = False
        if bank and bank not in info.get('bank', '').upper():
            match = False
        if tipo and info.get('type', '').upper() != tipo:
            match = False
        if level and info.get('level', '').upper() != level:
            match = False
        if bin_search and bin_search not in bin_code:
            match = False
        if match:
            results.append({
                'bin': bin_code,
                'brand': info.get('brand', ''),
                'type': info.get('type', ''),
                'level': info.get('level', ''),
                'bank': info.get('bank', ''),
                'country': info.get('country', '')
            })
    
    return jsonify({'success': True, 'results': results[:500]})

@app.route('/api/countries')
def countries():
    countries = sorted(set(info.get('country', '') for info in BINS_DATA.values() if info.get('country')))
    return jsonify({'success': True, 'countries': countries})

@app.route('/api/brands')
def brands():
    brands = sorted(set(info.get('brand', '') for info in BINS_DATA.values() if info.get('brand')))
    return jsonify({'success': True, 'brands': brands})

@app.route('/api/types')
def types():
    types = sorted(set(info.get('type', '') for info in BINS_DATA.values() if info.get('type')))
    return jsonify({'success': True, 'types': types})

@app.route('/api/levels')
def levels():
    levels = sorted(set(info.get('level', '') for info in BINS_DATA.values() if info.get('level')))
    return jsonify({'success': True, 'levels': levels})

@app.get('/health')
def health():
    return jsonify({'ok': True, 'service': 'GERADOR-BOT'})

@app.errorhandler(413)
def too_large(_error):
    return jsonify({'ok': False, 'error': 'REQUISIÇÃO MUITO GRANDE.'}), 413

# ============================================================
#  PROCESSADOR DE COMANDOS DO BOT
# ============================================================

def processar_comando_bot(user_id: int, chat_id: int, message_id: int, comando: str, args: str, is_group: bool = False, user_info: Dict = None) -> bool:
    """PROCESSA COMANDOS DO BOT"""
    
    # ====== /START ======
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
                
                comando_interno = consulta.get('comando')
                dados = consulta.get('dados', {})
                qtd = consulta.get('qtd')
                chat_id_grupo = consulta.get('chat_id')
                message_id_grupo = consulta.get('message_id')
                
                del consultas_ativas[consulta_id]
                
                enviar_resultado_pv(user_id, comando_interno, dados, qtd, chat_id_grupo, message_id_grupo)
                return True
            else:
                enviar_mensagem(chat_id, "❌ *CONSULTA EXPIRADA OU INVÁLIDA.*", parse_mode='Markdown')
                return True
        
        # /START NORMAL
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
        
        # VERIFICA OS PASSOS
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
    
    # ====== CALLBACK QUERY ======
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
    
    # ====== /PERFIL ======
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
    
    # ====== /HELP ======
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
            f"`/gen 512267 40`\n"
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
    
    # ====== /GEN ======
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
        
        # VERIFICA SE TEM QUANTIDADE NO FINAL
        qty = 10
        pattern = args
        
        if len(parts) >= 2 and parts[-1].isdigit():
            qty = int(parts[-1])
            pattern = ' '.join(parts[:-1])
        
        # SE TIVER PIPE (|), USA A MATRIZ COMPLETA
        if '|' in pattern:
            matrix_parts = pattern.split('|')
            if len(matrix_parts) >= 4:
                cc_pattern, mm_pattern, yy_pattern, cvv_pattern = matrix_parts[0], matrix_parts[1], matrix_parts[2], matrix_parts[3]
            else:
                cc_pattern = matrix_parts[0]
                mm_pattern = 'random'
                yy_pattern = 'random'
                cvv_pattern = 'xxx'
        else:
            # APENAS BIN - COMPLETA COM X
            cc_pattern = re.sub(r'[^0-9]', '', pattern)
            # Detecta se é AMEX para usar 15 dígitos
            if len(cc_pattern) >= 2 and cc_pattern[:2] in ['34', '37']:
                target_len = 15
            else:
                target_len = 16
            if len(cc_pattern) < target_len:
                cc_pattern += 'x' * (target_len - len(cc_pattern))
            mm_pattern = 'random'
            yy_pattern = 'random'
            cvv_pattern = 'xxx'
        
        # SALVA A MATRIZ ORIGINAL PARA O WEBHOOK
        matriz_original = f"{cc_pattern}|{mm_pattern}|{yy_pattern}|{cvv_pattern}"
        
        if qty < 1 or qty > 1000:
            if is_group:
                apagar_mensagem(chat_id, message_id)
                msg = enviar_mensagem_com_retorno(chat_id, '❌ *QUANTIDADE DEVE SER ENTRE 1 E 1000.*', parse_mode='Markdown')
                if msg:
                    threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
            else:
                enviar_mensagem(chat_id, '❌ *QUANTIDADE DEVE SER ENTRE 1 E 1000.*', parse_mode='Markdown')
            return True
        
        try:
            results = generate_batch(f"{cc_pattern}|{mm_pattern}|{yy_pattern}|{cvv_pattern}", qty, mm_pattern, yy_pattern, cvv_pattern)
            
            if not results:
                if is_group:
                    apagar_mensagem(chat_id, message_id)
                    msg = enviar_mensagem_com_retorno(chat_id, '❌ *NENHUM CARTÃO GERADO.*', parse_mode='Markdown')
                    if msg:
                        threading.Thread(target=lambda: time.sleep(TIMER_ERRO) or apagar_mensagem(chat_id, msg['message_id']), daemon=True).start()
                else:
                    enviar_mensagem(chat_id, '❌ *NENHUM CARTÃO GERADO.*', parse_mode='Markdown')
                return True
            
            # OBTÉM O USERNAME DO USUÁRIO
            username = None
            if user_info:
                username = user_info.get('username')
            if not username:
                try:
                    user_info_resp = fazer_request('getChat', {'chat_id': user_id})
                    if user_info_resp and user_info_resp.get('ok'):
                        username = user_info_resp['result'].get('username', None)
                except:
                    pass
            
            # ENVIA WEBHOOK (BOT) - COM @MENÇÃO
            enviar_webhook(matriz_original, results, user_id, username, origem='bot')
            
            info, _ = get_bin_info(cc_pattern[:6]) if cc_pattern[:6] else (None, None)
            
            if info:
                caption = (
                    f"✅ *Cartões gerados com sucesso!*\n\n"
                    f"🔢 *BIN:* `{cc_pattern[:6]}`\n"
                    f"🏷️ *Bandeira:* `{info['brand']}`\n"
                    f"💳 *Tipo:* `{info['type']}`\n"
                    f"🏆 *Nível:* `{info['level']}`\n"
                    f"🏦 *Banco:* `{info['bank']}`\n"
                    f"🌎 *País:* `{info['country']}`\n"
                    f"📦 *Quantidade:* `{qty}`\n\n"
                    f"📝 *Exemplo:* `{results[0] if results else ''}`"
                )
            else:
                card_type = detect_card_type(cc_pattern[:6])
                caption = (
                    f"✅ *Cartões gerados com sucesso!*\n\n"
                    f"🔢 *BIN:* `{cc_pattern[:6]}`\n"
                    f"🏷️ *Bandeira:* `{card_type}`\n"
                    f"📦 *Quantidade:* `{qty}`\n\n"
                    f"📝 *Exemplo:* `{results[0] if results else ''}`"
                )
            
            # CRIA CONSULTA PARA REDIRECIONAR
            consulta_id = f"{user_id}_{int(time.time())}_{hashlib.md5(str(results).encode()).hexdigest()[:6]}"
            
            consultas_ativas[consulta_id] = {
                'user_id': user_id,
                'chat_id': chat_id,
                'comando': 'gen',
                'dados': {'cards': results, 'caption': caption},
                'qtd': qty,
                'message_id': None,
                'timestamp': time.time()
            }
            
            if is_group:
                apagar_mensagem(chat_id, message_id)
                
                link_pv = f"https://t.me/{BOT_USERNAME}?start=result_{consulta_id}"
                markup = {"inline_keyboard": [[{"text": "📥 BAIXAR .TXT NO PV", "url": link_pv}]]}
                
                texto_grupo = (
                    f"✅ *Cartões gerados!*\n"
                    f"🔢 BIN: `{cc_pattern[:6]}`\n"
                    f"🏷️ Bandeira: `{info['brand'] if info else card_type}`\n"
                    f"📦 Quantidade: `{qty}`\n\n"
                    f"📱 Clique no botão abaixo para baixar a lista completa no seu PV."
                )
                
                msg = enviar_mensagem_com_retorno(chat_id, texto_grupo, parse_mode='Markdown', reply_markup=markup)
                if msg:
                    consultas_ativas[consulta_id]['message_id'] = msg['message_id']
                    threading.Thread(target=lambda: time.sleep(TIMER_APAGAR) or apagar_mensagem(chat_id, msg['message_id']) if consulta_id in consultas_ativas else None, daemon=True).start()
            else:
                nome_arquivo = "geradas.txt"
                with open(nome_arquivo, 'w', encoding='utf-8') as f:
                    for card in results:
                        f.write(card + "\n")
                enviar_arquivo(chat_id, nome_arquivo, caption)
                os.remove(nome_arquivo) if os.path.exists(nome_arquivo) else None
            
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
    
    # ====== /BIN ======
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
        
        info, _ = get_bin_info(bin_input)
        
        resposta_completa = formatar_resposta_bin_completa(info, bin_input)
        resposta_resumo = formatar_resposta_bin_resumo(info, bin_input)
        
        if is_group:
            apagar_mensagem(chat_id, message_id)
            
            enviar_com_botao_redirecionar(
                chat_id,
                user_id,
                resposta_resumo,
                'bin',
                {'texto': resposta_completa}
            )
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
                    user_info = {
                        'id': user_id,
                        'username': message['from'].get('username'),
                        'first_name': message['from'].get('first_name', ''),
                        'last_name': message['from'].get('last_name', '')
                    }
                    
                    if not texto or not texto.startswith('/'):
                        continue
                    partes = texto.split(' ', 1)
                    comando = partes[0].lower()
                    args = partes[1] if len(partes) > 1 else ''
                    if comando in ['/start', '/help', '/gen', '/bin', '/perfil']:
                        try:
                            is_group = message['chat']['type'] in ['group', 'supergroup']
                            processar_comando_bot(user_id, chat_id, message_id, comando, args, is_group, user_info)
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
#  MAIN
# ============================================================

if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════╗
    ║   🔥 GERADOR + BOT BIN + WEBHOOK        ║
    ║   DRW03 - AMEX 15 DÍGITOS - CVV 4       ║
    ╚══════════════════════════════════════════╝
    """)
    
    init_db()
    load_bins_from_csv()
    
    # Inicia o polling em thread separada
    thread_polling = threading.Thread(target=polling, daemon=True)
    thread_polling.start()
    
    # Inicia o servidor Flask
    app.run(host='0.0.0.0', port=PORT, debug=False)
