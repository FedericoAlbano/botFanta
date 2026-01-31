#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot Telegram per Gestione Asta Fantacalcio
Libreria: python-telegram-bot v20+ (asincrona)

REQUISITI:
pip install python-telegram-bot --upgrade

CONFIGURAZIONE:
1. Inserisci il TOKEN del bot nella variabile BOT_TOKEN
2. Inserisci l'ID del canale nella variabile CHANNEL_ID
3. Assicurati che il bot sia amministratore sia nel canale che nel gruppo
"""

import re
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from telegram import Update, Message
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
    CallbackContext
)
from telegram.error import TelegramError

# ============================================================================
# CONFIGURAZIONE - MODIFICA QUESTI VALORI
# ============================================================================

BOT_TOKEN = "8308395407:AAE8vVWDcmmLDVTC_iIgbpyslWnGysGLhmY"  # Token del bot
CHANNEL_ID = -1002961437586  # ID del canale

# ============================================================================
# CONFIGURAZIONE LOGGING
# ============================================================================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURAZIONE ASTA
# ============================================================================

AUCTION_DURATION_HOURS = 12  # Durata asta in ore
DATA_FILE = "auctions_data.json"  # File per persistenza dati

# ============================================================================
# GESTIONE PERSISTENZA DATI
# ============================================================================

def load_auctions() -> Dict:
    """Carica i dati delle aste dal file JSON"""
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.info("File dati non trovato, creazione nuovo database")
        return {}
    except json.JSONDecodeError:
        logger.error("Errore nel parsing del JSON, creazione nuovo database")
        return {}


def save_auctions(auctions: Dict) -> None:
    """Salva i dati delle aste nel file JSON"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(auctions, f, ensure_ascii=False, indent=2)
        logger.info("Dati salvati correttamente")
    except Exception as e:
        logger.error(f"Errore nel salvataggio dei dati: {e}")


# ============================================================================
# PARSING OFFERTA
# ============================================================================

def parse_offer(text: str) -> Optional[Tuple[int, str]]:
    """
    Estrae l'offerta e lo svincolo dal testo del messaggio.
    
    Formati supportati:
    - "15 svincolo Belotti"
    - "10 per Lukaku svincolo Zaza"
    - "20 svincolo nessuno"
    
    Returns:
        Tuple[int, str] con (cifra, nome_svincolo) oppure None se non trovato
    """
    # Pattern per trovare: numero + "svincolo" + nome
    # Supporta "X svincolo Y" oppure "X per Z svincolo Y"
    pattern = r'(\d+).*?svincolo\s+(.+?)(?:\s|$)'
    
    match = re.search(pattern, text.lower())
    
    if match:
        try:
            cifra = int(match.group(1))
            svincolo = match.group(2).strip().title()
            
            # Rimuove eventuali punteggiatura finale
            svincolo = re.sub(r'[.,!?]$', '', svincolo)
            
            logger.info(f"Offerta parsata: {cifra} crediti, svincolo: {svincolo}")
            return (cifra, svincolo)
        except ValueError:
            logger.warning(f"Valore numerico non valido nel testo: {text}")
            return None
    
    logger.warning(f"Nessuna offerta trovata nel testo: {text}")
    return None


# ============================================================================
# FORMATTAZIONE DIDASCALIA
# ============================================================================

def format_caption(cifra: int, username: str, svincolo: str, scadenza: datetime) -> str:
    """
    Formatta la didascalia del messaggio nel canale.
    
    Args:
        cifra: Offerta attuale
        username: Nome dell'utente che ha fatto l'offerta
        svincolo: Nome del giocatore da svincolare
        scadenza: Data e ora di scadenza dell'asta
    
    Returns:
        Stringa formattata per la caption
    """
    scadenza_str = scadenza.strftime("%d/%m %H:%M")
    
    caption = (
        f"💰 Offerta attuale: {cifra}\n"
        f"👤 Fantallenatore: {username}\n"
        f"🔄 Svincolo: {svincolo}\n"
        f"⏳ Scadenza: {scadenza_str}"
    )
    
    return caption


def format_closed_caption(cifra: int, username: str, svincolo: str) -> str:
    """Formatta la didascalia per un'asta chiusa"""
    caption = (
        f"🔴 ASTA CHIUSA\n\n"
        f"💰 Offerta vincente: {cifra}\n"
        f"👤 Vinto da: {username}\n"
        f"🔄 Svincolo: {svincolo}"
    )
    
    return caption


# ============================================================================
# COMANDI BOT
# ============================================================================

async def cmd_asta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Comando /asta per creare una nuova asta.
    Il bot pubblica automaticamente il messaggio nel canale.
    Uso: /asta Ronaldo 1 svincolo Belotti
    """
    message = update.message
    
    # Verifica che ci siano argomenti
    if not context.args:
        await message.reply_text(
            "❌ **Formato non valido!**\n\n"
            "**Uso:** `/asta [testo]`\n\n"
            "**Esempio:**\n"
            "`/asta Ronaldo 1 svincolo Belotti`"
        )
        return
    
    # Ricostruisci il testo dell'asta
    auction_text = ' '.join(context.args)
    
    try:
        # Pubblica il messaggio nel canale
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=auction_text
        )
        
        channel_message_id = channel_message.message_id
        
        # Aspetta un momento per dare tempo a Telegram di inoltrare il messaggio al gruppo
        await asyncio.sleep(2)
        
        # Il messaggio verrà inoltrato automaticamente nel gruppo
        # Salva l'asta con scadenza iniziale
        auctions = load_auctions()
        
        # Usiamo l'ID del canale come chiave principale
        auction_key = f"channel_{channel_message_id}"
        
        scadenza = datetime.now() + timedelta(hours=AUCTION_DURATION_HOURS)
        
        auctions[auction_key] = {
            'channel_message_id': channel_message_id,
            'original_text': auction_text,
            'current_offer': 0,
            'username': 'Nessuno',
            'svincolo': 'Da definire',
            'active': True,
            'deadline': scadenza.isoformat(),
            'message_id': channel_message_id,
            'created_by': message.from_user.username or message.from_user.first_name
        }
        
        save_auctions(auctions)
        
        await message.reply_text(
            f"✅ **Asta creata con successo!**\n\n"
            f"📝 Testo: {auction_text}\n"
            f"⏳ Scadenza: {scadenza.strftime('%d/%m %H:%M')}\n\n"
            f"🎯 Gli utenti possono fare offerte nei commenti del canale!"
        )
        
        logger.info(f"Asta creata - ID Canale: {channel_message_id}")
        
        # Pianifica la chiusura dell'asta (se JobQueue è disponibile)
        if context.job_queue:
            job_name = f"close_auction_{auction_key}"
            context.job_queue.run_once(
                close_auction,
                when=AUCTION_DURATION_HOURS * 3600,
                data={'auction_key': auction_key},
                name=job_name
            )
            logger.info(f"Job di chiusura pianificato per {scadenza}")
        else:
            logger.warning("JobQueue non disponibile - chiusura automatica disabilitata")
        
    except TelegramError as e:
        logger.error(f"Errore nella creazione dell'asta: {e}")
        await message.reply_text(
            f"❌ **Errore nella pubblicazione:**\n{str(e)}\n\n"
            "Verifica che il bot sia amministratore del canale con permesso di pubblicare messaggi."
        )
    except Exception as e:
        logger.error(f"Errore imprevisto: {e}")
        await message.reply_text(f"❌ Errore: {e}")


async def cmd_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Mostra il tempo rimanente per l'asta.
    Deve essere usato come risposta al messaggio dell'asta.
    """
    message = update.message
    
    if not message.reply_to_message:
        await message.reply_text(
            "❌ **Rispondi al messaggio dell'asta** per vedere il tempo rimanente!\n\n"
            "Oppure usa `/aste` per vedere tutte le aste attive."
        )
        return
    
    replied_message = message.reply_to_message
    
    # Verifica che provenga dal canale
    if not (replied_message.is_automatic_forward and replied_message.sender_chat and replied_message.sender_chat.id == CHANNEL_ID):
        await message.reply_text("❌ Questo non è un messaggio di asta dal canale!")
        return
    
    # Cerca l'asta
    auctions = load_auctions()
    auction_found = None
    auction_key = None
    
    # Cerca per tutti i possibili ID
    for key, auction in auctions.items():
        if auction.get('active') and str(replied_message.message_id) in key:
            auction_found = auction
            auction_key = key
            break
    
    # Prova anche con channel_message_id
    if not auction_found:
        for key, auction in auctions.items():
            if auction.get('active'):
                # Potrebbe essere mappato tramite l'ID del canale
                auction_found = auction
                auction_key = key
                break
    
    if not auction_found:
        await message.reply_text("❌ Asta non trovata o non ancora inizializzata!")
        return
    
    try:
        deadline = datetime.fromisoformat(auction_found['deadline'])
        now = datetime.now()
        
        if deadline <= now:
            await message.reply_text("⏱️ **Asta scaduta!** Chiusura in corso...")
            return
        
        time_remaining = deadline - now
        hours = int(time_remaining.total_seconds() // 3600)
        minutes = int((time_remaining.total_seconds() % 3600) // 60)
        
        await message.reply_text(
            f"⏰ **Tempo rimanente:**\n\n"
            f"🕐 {hours}h {minutes}m\n"
            f"⏳ Scadenza: {deadline.strftime('%d/%m %H:%M')}\n\n"
            f"💰 Offerta attuale: {auction_found['current_offer']}\n"
            f"👤 Fantallenatore: {auction_found['username']}"
        )
        
    except Exception as e:
        logger.error(f"Errore nel calcolo del tempo: {e}")
        await message.reply_text(f"❌ Errore: {e}")


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Mostra informazioni dettagliate sull'asta.
    Deve essere usato come risposta al messaggio dell'asta.
    """
    message = update.message
    
    if not message.reply_to_message:
        await message.reply_text(
            "❌ **Rispondi al messaggio dell'asta** per vedere le informazioni!"
        )
        return
    
    replied_message = message.reply_to_message
    
    if not (replied_message.is_automatic_forward and replied_message.sender_chat and replied_message.sender_chat.id == CHANNEL_ID):
        await message.reply_text("❌ Questo non è un messaggio di asta dal canale!")
        return
    
    auctions = load_auctions()
    auction_found = None
    
    for key, auction in auctions.items():
        if auction.get('active'):
            auction_found = auction
            break
    
    if not auction_found:
        await message.reply_text("❌ Asta non trovata!")
        return
    
    try:
        deadline = datetime.fromisoformat(auction_found['deadline'])
        time_remaining = deadline - datetime.now()
        hours = int(time_remaining.total_seconds() // 3600)
        minutes = int((time_remaining.total_seconds() % 3600) // 60)
        
        status = "🟢 Attiva" if auction_found['active'] else "🔴 Chiusa"
        
        info_text = (
            f"📊 **INFORMAZIONI ASTA**\n\n"
            f"📝 Testo: {auction_found.get('original_text', 'N/A')}\n"
            f"💰 Offerta attuale: {auction_found['current_offer']} crediti\n"
            f"👤 Fantallenatore: {auction_found['username']}\n"
            f"🔄 Svincolo: {auction_found['svincolo']}\n"
            f"⏰ Tempo rimanente: {hours}h {minutes}m\n"
            f"⏳ Scadenza: {deadline.strftime('%d/%m/%Y %H:%M')}\n"
            f"📍 Stato: {status}"
        )
        
        await message.reply_text(info_text)
        
    except Exception as e:
        logger.error(f"Errore nel recupero info: {e}")
        await message.reply_text(f"❌ Errore: {e}")


async def cmd_chiudi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Chiude manualmente un'asta.
    Deve essere usato come risposta al messaggio dell'asta.
    """
    message = update.message
    
    # Verifica se l'utente è admin (opzionale, puoi rimuovere questo controllo)
    # Per ora lo lascio aperto a tutti
    
    if not message.reply_to_message:
        await message.reply_text(
            "❌ **Rispondi al messaggio dell'asta** che vuoi chiudere!"
        )
        return
    
    replied_message = message.reply_to_message
    
    if not (replied_message.is_automatic_forward and replied_message.sender_chat and replied_message.sender_chat.id == CHANNEL_ID):
        await message.reply_text("❌ Questo non è un messaggio di asta dal canale!")
        return
    
    auctions = load_auctions()
    auction_key = None
    auction_found = None
    
    for key, auction in auctions.items():
        if auction.get('active'):
            auction_found = auction
            auction_key = key
            break
    
    if not auction_found:
        await message.reply_text("❌ Asta non trovata o già chiusa!")
        return
    
    try:
        # Chiudi l'asta
        auction_found['active'] = False
        auctions[auction_key] = auction_found
        save_auctions(auctions)
        
        # Aggiorna la caption nel canale
        closed_caption = format_closed_caption(
            auction_found['current_offer'],
            auction_found['username'],
            auction_found['svincolo']
        )
        
        await context.bot.edit_message_caption(
            chat_id=CHANNEL_ID,
            message_id=auction_found['channel_message_id'],
            caption=closed_caption
        )
        
        # Rimuovi il job di chiusura automatica (se esiste)
        if context.job_queue:
            job_name = f"close_auction_{auction_key}"
            current_jobs = context.job_queue.get_jobs_by_name(job_name)
            for job in current_jobs:
                job.schedule_removal()
        
        await message.reply_text(
            f"✅ **Asta chiusa manualmente!**\n\n"
            f"🏆 Vincitore: {auction_found['username']}\n"
            f"💰 Offerta finale: {auction_found['current_offer']} crediti\n"
            f"🔄 Svincolo: {auction_found['svincolo']}"
        )
        
        logger.info(f"Asta {auction_key} chiusa manualmente")
        
    except Exception as e:
        logger.error(f"Errore nella chiusura manuale: {e}")
        await message.reply_text(f"❌ Errore: {e}")


async def cmd_aste(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Mostra la lista di tutte le aste attive.
    """
    message = update.message
    
    auctions = load_auctions()
    active_auctions = {k: v for k, v in auctions.items() if v.get('active', False)}
    
    if not active_auctions:
        await message.reply_text("📭 **Nessuna asta attiva al momento.**")
        return
    
    try:
        aste_text = "📋 **ASTE ATTIVE:**\n\n"
        
        for i, (key, auction) in enumerate(active_auctions.items(), 1):
            deadline = datetime.fromisoformat(auction['deadline'])
            time_remaining = deadline - datetime.now()
            hours = int(time_remaining.total_seconds() // 3600)
            minutes = int((time_remaining.total_seconds() % 3600) // 60)
            
            aste_text += (
                f"{i}. **{auction.get('original_text', 'N/A')[:30]}...**\n"
                f"   💰 {auction['current_offer']} crediti - {auction['username']}\n"
                f"   ⏰ {hours}h {minutes}m rimanenti\n\n"
            )
        
        await message.reply_text(aste_text)
        
    except Exception as e:
        logger.error(f"Errore nel recupero aste: {e}")
        await message.reply_text(f"❌ Errore: {e}")


async def cmd_classifica(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Mostra la classifica dei fantallenatori (chi ha vinto più aste).
    """
    message = update.message
    
    auctions = load_auctions()
    
    # Conta le vittorie per utente (solo aste chiuse)
    wins = {}
    total_spent = {}
    
    for auction in auctions.values():
        if not auction.get('active', True):  # Solo aste chiuse
            username = auction.get('username', 'Nessuno')
            if username != 'Nessuno':
                wins[username] = wins.get(username, 0) + 1
                total_spent[username] = total_spent.get(username, 0) + auction.get('current_offer', 0)
    
    if not wins:
        await message.reply_text("📊 **Nessuna asta completata ancora.**")
        return
    
    # Ordina per numero di vittorie
    sorted_wins = sorted(wins.items(), key=lambda x: x[1], reverse=True)
    
    classifica_text = "🏆 **CLASSIFICA FANTALLENATORI**\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    for i, (username, count) in enumerate(sorted_wins[:10], 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        spent = total_spent.get(username, 0)
        avg = spent // count if count > 0 else 0
        
        classifica_text += (
            f"{medal} **{username}**\n"
            f"   Aste vinte: {count}\n"
            f"   Crediti spesi: {spent}\n"
            f"   Media: {avg} crediti/asta\n\n"
        )
    
    await message.reply_text(classifica_text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Mostra la guida dei comandi disponibili.
    """
    help_text = (
        "🤖 **COMANDI DISPONIBILI**\n\n"
        
        "**📝 Gestione Aste:**\n"
        "`/asta [testo]` - Crea nuova asta\n"
        "   Es: `/asta Ronaldo 1 svincolo Belotti`\n\n"
        
        "`/time` - Tempo rimanente (rispondi al messaggio)\n"
        "`/info` - Dettagli asta (rispondi al messaggio)\n"
        "`/chiudi` - Chiudi asta manualmente (rispondi al messaggio)\n"
        "`/aste` - Lista aste attive\n\n"
        
        "**📊 Statistiche:**\n"
        "`/classifica` - Classifica fantallenatori\n\n"
        
        "**💰 Fare un'offerta:**\n"
        "Rispondi al messaggio dell'asta con:\n"
        "`[cifra] svincolo [giocatore]`\n"
        "Es: `15 svincolo Belotti`\n\n"
        
        "**ℹ️ Info:**\n"
        f"⏱️ Durata asta: {AUCTION_DURATION_HOURS} ore\n"
        "🔄 Ogni offerta resetta il timer\n"
        "🏆 Vince l'ultima offerta valida"
    )
    
    await update.message.reply_text(help_text)


# ============================================================================
# GESTIONE OFFERTE
# ============================================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Gestisce i messaggi nel gruppo, controlla se sono risposte a post del canale
    e processa le offerte.
    """
    message = update.message
    
    # Controlla se il messaggio è una risposta
    if not message.reply_to_message:
        return
    
    replied_message = message.reply_to_message
    
    # Verifica se il messaggio a cui si risponde proviene dal canale
    if replied_message.is_automatic_forward and replied_message.sender_chat and replied_message.sender_chat.id == CHANNEL_ID:
        logger.info(f"Rilevata risposta a post del canale da {message.from_user.username}")
        
        # Carica i dati delle aste
        auctions = load_auctions()
        
        # Cerca l'asta corrispondente
        auction_found = None
        auction_key = None
        channel_message_id = None
        
        # Il messaggio inoltrato potrebbe avere l'ID originale
        # Cerchiamo prima usando il testo del messaggio per matching
        replied_text = replied_message.text or replied_message.caption or ""
        
        logger.info(f"Cerco asta per messaggio: '{replied_text[:50]}...'")
        
        # Cerca tra tutte le aste attive
        for key, auction in auctions.items():
            if auction.get('active', False):
                # Match per testo originale
                if auction.get('original_text') == replied_text:
                    auction_found = auction
                    auction_key = key
                    channel_message_id = auction.get('channel_message_id')
                    logger.info(f"Asta trovata tramite match testo: {key}")
                    break
        
        # Se non trovata, prendi la prima asta attiva (fallback)
        if not auction_found:
            for key, auction in auctions.items():
                if auction.get('active', False):
                    auction_found = auction
                    auction_key = key
                    channel_message_id = auction.get('channel_message_id')
                    logger.warning(f"Usato fallback - prima asta attiva: {key}")
                    break
        
        # Verifica che l'asta sia stata trovata
        if not auction_found:
            await message.reply_text(
                "❌ **Asta non trovata!**\n\n"
                "Assicurati che l'asta sia stata creata con `/asta`"
            )
            return
        
        if not channel_message_id:
            logger.error(f"Asta {auction_key} non ha channel_message_id!")
            await message.reply_text("❌ Errore: ID del canale non trovato!")
            return
        
        logger.info(f"Asta trovata - Key: {auction_key}, Canale ID: {channel_message_id}")
        
        # Parsing dell'offerta
        offer_data = parse_offer(message.text)
        
        if not offer_data:
            await message.reply_text(
                "❌ Formato offerta non valido.\n"
                "Usa: [Cifra] svincolo [NomeGiocatore]\n"
                "Esempio: 15 svincolo Belotti"
            )
            return
        
        cifra, svincolo = offer_data
        username = message.from_user.username or message.from_user.first_name
        
        # Carica i dati delle aste
        auctions = load_auctions()
        auction_key = str(channel_message_id)
        
        # Validazione: controlla se l'offerta è superiore all'attuale
        if auction_key in auctions:
            current_offer = auctions[auction_key].get('current_offer', 0)
            if cifra <= current_offer:
                await message.reply_text(
                    f"❌ Offerta troppo bassa!\n"
                    f"L'offerta attuale è: {current_offer} crediti"
                )
                return
        
        # Calcola la nuova scadenza
        scadenza = datetime.now() + timedelta(hours=AUCTION_DURATION_HOURS)
        
        # Aggiorna i dati dell'asta (mantieni la chiave esistente)
        auction_found['current_offer'] = cifra
        auction_found['username'] = username
        auction_found['svincolo'] = svincolo
        auction_found['deadline'] = scadenza.isoformat()
        
        auctions[auction_key] = auction_found
        
        # Salva i dati
        save_auctions(auctions)
        
        # Formatta la nuova didascalia
        new_caption = format_caption(cifra, username, svincolo, scadenza)
        
        # Modifica la didascalia del messaggio nel canale
        try:
            logger.info(f"Tentativo di modifica caption - Channel ID: {CHANNEL_ID}, Message ID: {channel_message_id}")
            await context.bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=channel_message_id,
                caption=new_caption
            )
            logger.info(f"Didascalia aggiornata per l'asta {auction_key}")
            
            # Feedback positivo all'utente
            await message.set_reaction("👍")
            
            # Pianifica la chiusura dell'asta (se JobQueue disponibile)
            job_name = f"close_auction_{auction_key}"
            
            # Rimuovi eventuali job precedenti per questa asta
            if context.job_queue:
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
                
                # Pianifica nuovo job
                context.job_queue.run_once(
                    close_auction,
                    when=AUCTION_DURATION_HOURS * 3600,  # secondi
                    data={'auction_key': auction_key},
                    name=job_name
                )
                logger.info(f"Job di chiusura pianificato per {scadenza}")
            else:
                logger.warning("JobQueue non disponibile")
            
        except TelegramError as e:
            logger.error(f"Errore nell'aggiornamento della didascalia: {e}")
            logger.error(f"Dettagli errore - Type: {type(e).__name__}, Message: {str(e)}")
            await message.reply_text(
                f"⚠️ Errore nell'aggiornamento dell'asta.\n"
                f"Dettagli: {str(e)}\n\n"
                f"Verifica che il bot sia amministratore del canale con permesso 'Modifica messaggi'."
            )


# ============================================================================
# CHIUSURA ASTA
# ============================================================================

async def close_auction(context: CallbackContext) -> None:
    """
    Chiude l'asta quando scade il tempo.
    Viene eseguita dal JobQueue.
    """
    auction_key = context.job.data['auction_key']
    logger.info(f"Chiusura asta {auction_key}")
    
    # Carica i dati
    auctions = load_auctions()
    
    if auction_key not in auctions:
        logger.warning(f"Asta {auction_key} non trovata nei dati")
        return
    
    auction = auctions[auction_key]
    
    if not auction.get('active', False):
        logger.info(f"Asta {auction_key} già chiusa")
        return
    
    # Marca l'asta come chiusa
    auction['active'] = False
    auctions[auction_key] = auction
    save_auctions(auctions)
    
    # Formatta la didascalia di chiusura
    closed_caption = format_closed_caption(
        auction['current_offer'],
        auction['username'],
        auction['svincolo']
    )
    
    # Aggiorna la didascalia nel canale
    try:
        await context.bot.edit_message_caption(
            chat_id=CHANNEL_ID,
            message_id=auction['message_id'],
            caption=closed_caption
        )
        logger.info(f"Asta {auction_key} chiusa con successo")
    except TelegramError as e:
        logger.error(f"Errore nella chiusura dell'asta: {e}")


# ============================================================================
# RIAVVIO ASTE ATTIVE
# ============================================================================

async def restart_active_auctions(application: Application) -> None:
    """
    Riavvia i job di chiusura per le aste ancora attive dopo un riavvio del bot.
    """
    logger.info("Verifica aste attive da riavviare...")
    
    auctions = load_auctions()
    now = datetime.now()
    
    for auction_key, auction in auctions.items():
        if not auction.get('active', False):
            continue
        
        try:
            deadline = datetime.fromisoformat(auction['deadline'])
            
            if deadline <= now:
                # L'asta è già scaduta, chiudila immediatamente
                logger.info(f"Chiusura immediata asta scaduta {auction_key}")
                await close_auction_directly(application, auction_key, auction)
            else:
                # L'asta è ancora attiva, ripianifica il job
                time_remaining = (deadline - now).total_seconds()
                job_name = f"close_auction_{auction_key}"
                
                application.job_queue.run_once(
                    close_auction,
                    when=time_remaining,
                    data={'auction_key': auction_key},
                    name=job_name
                )
                logger.info(f"Job ripianificato per asta {auction_key}, scadenza: {deadline}")
        
        except Exception as e:
            logger.error(f"Errore nel riavvio asta {auction_key}: {e}")


async def close_auction_directly(application: Application, auction_key: str, auction: Dict) -> None:
    """Chiude direttamente un'asta senza usare il job"""
    auction['active'] = False
    auctions = load_auctions()
    auctions[auction_key] = auction
    save_auctions(auctions)
    
    closed_caption = format_closed_caption(
        auction['current_offer'],
        auction['username'],
        auction['svincolo']
    )
    
    try:
        await application.bot.edit_message_caption(
            chat_id=CHANNEL_ID,
            message_id=auction['message_id'],
            caption=closed_caption
        )
    except TelegramError as e:
        logger.error(f"Errore nella chiusura diretta dell'asta: {e}")


# ============================================================================
# MAIN - AVVIO BOT
# ============================================================================

def main() -> None:
    """Avvia il bot"""
    
    # Verifica configurazione
    if BOT_TOKEN == "IL_TUO_TOKEN_QUI":
        logger.error("ERRORE: Devi configurare il BOT_TOKEN!")
        return
    
    if CHANNEL_ID == -1001234567890:
        logger.error("ERRORE: Devi configurare il CHANNEL_ID!")
        return
    
    # Crea l'applicazione
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Aggiungi handler per i comandi
    application.add_handler(CommandHandler("asta", cmd_asta))
    application.add_handler(CommandHandler("time", cmd_time))
    application.add_handler(CommandHandler("info", cmd_info))
    application.add_handler(CommandHandler("chiudi", cmd_chiudi))
    application.add_handler(CommandHandler("aste", cmd_aste))
    application.add_handler(CommandHandler("classifica", cmd_classifica))
    application.add_handler(CommandHandler("help", cmd_help))
    
    # Aggiungi handler per i messaggi nel gruppo
    # Filtra solo messaggi testuali che sono risposte
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.REPLY & ~filters.COMMAND,
            handle_message
        )
    )
    
    # Riavvia aste attive dopo l'avvio
    application.post_init = restart_active_auctions
    
    # Avvia il bot
    logger.info("Bot avviato! In ascolto delle offerte...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()