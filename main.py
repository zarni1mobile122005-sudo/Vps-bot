

import os
import sys
import time
import json
import logging
import subprocess
import threading
import platform
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify

# Setup logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Try to load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.info("Environment variables loaded successfully")
except ImportError:
    logger.warning("python-dotenv not installed, using system environment")

# --- CONFIGURATION ---
# Load from environment variables for security
API_TOKEN = os.getenv('BOT_TOKEN', ' 8847534009:AAEWHzsdgC8b1a4TdAvKeOgReTJPB_ODUsc')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', '@mgzan201')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '7592705124')

# Flask app for health checks
app = Flask(__name__)

# Directory Setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_DIR = os.path.join(BASE_DIR, "hosted_bots")
if not os.path.exists(HOST_DIR):
    os.makedirs(HOST_DIR)
    logger.info(f"Created hosted_bots directory at {HOST_DIR}")

# Global Trackers
running_processes = {}
start_times = {}
file_names = {}
user_selected_slot = {}

# Database Memory Trackers
registered_users = set()        # All users who have used the bot
user_usernames = {}            # { uid: username }
user_time_balance = {}         # { uid: datetime_object }
referred_tracker = set()       # Prevent duplicate referrals
pro_users = set()              # VIP Unlimited users

# Initialize bot
try:
    import telebot
    from telebot import types
    bot = telebot.TeleBot(API_TOKEN)
    logger.info("TeleBot initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize TeleBot: {e}")
    sys.exit(1)

# --- Helper Functions ---
def count_active_bots(uid):
    """Count active bot instances for a user"""
    if uid not in running_processes:
        return 0
    return sum(1 for pid in running_processes[uid].values() if pid.poll() is None)

def has_remaining_time(uid):
    """Check if user has remaining runtime"""
    if uid == ADMIN_CHAT_ID or uid in pro_users:
        return True
    if uid not in user_time_balance:
        return False
    return datetime.now() < user_time_balance[uid]

def get_time_balance_string(uid):
    """Get formatted time balance string"""
    if uid == ADMIN_CHAT_ID:
        return "♾️ Unlimited (Administrator Free)"
    if uid in pro_users:
        return "💎 Unlimited (VIP PRO Mode)"
    if uid not in user_time_balance or datetime.now() >= user_time_balance[uid]:
        return "❌ 0m (No Time Left - Please invite friends!)"
    diff = user_time_balance[uid] - datetime.now()
    days = diff.days
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60
    return f"⏳ {days}d {hours}h {minutes}m remaining"

def load_data():
    """Load data from JSON files"""
    try:
        data_files = ['registered_users.json', 'user_usernames.json', 'user_time_balance.json', 'pro_users.json']
        for file in data_files:
            if os.path.exists(file):
                with open(file, 'r') as f:
                    data = json.load(f)
                    if file == 'registered_users.json':
                        registered_users.update(data)
                    elif file == 'user_usernames.json':
                        user_usernames.update(data)
                    elif file == 'user_time_balance.json':
                        # Convert string back to datetime
                        for uid, time_str in data.items():
                            user_time_balance[uid] = datetime.fromisoformat(time_str)
                    elif file == 'pro_users.json':
                        pro_users.update(data)
        logger.info("Data loaded successfully")
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def save_data():
    """Save data to JSON files"""
    try:
        # Save registered users
        with open('registered_users.json', 'w') as f:
            json.dump(list(registered_users), f)
        
        # Save usernames
        with open('user_usernames.json', 'w') as f:
            json.dump(user_usernames, f)
        
        # Save time balances (convert datetime to string)
        time_data = {}
        for uid, dt in user_time_balance.items():
            time_data[uid] = dt.isoformat()
        with open('user_time_balance.json', 'w') as f:
            json.dump(time_data, f)
        
        # Save pro users
        with open('pro_users.json', 'w') as f:
            json.dump(list(pro_users), f)
        
        logger.info("Data saved successfully")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

# --- UI Components ---
def get_dashboard_markup(uid):
    """Create dashboard inline keyboard"""
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    slots_btns = []
    for i in range(1, 4):
        slot_str = str(i)
        is_running = False
        if uid in running_processes and slot_str in running_processes[uid]:
            if running_processes[uid][slot_str].poll() is None:
                is_running = True
        
        status_dot = "🟢" if is_running else "⚪"
        slots_btns.append(types.InlineKeyboardButton(f"{status_dot} Slot {i}", callback_data=f"select_slot_{i}"))
    
    markup.add(*slots_btns)
    
    current_slot = user_selected_slot.get(uid, "1")
    is_current_running = False
    if uid in running_processes and current_slot in running_processes[uid]:
        if running_processes[uid][current_slot].poll() is None:
            is_current_running = True
            
    has_file = os.path.exists(os.path.join(HOST_DIR, uid, current_slot, "main.py"))
    
    deploy_btn = types.InlineKeyboardButton(f"📤 Deploy to Slot {current_slot}", callback_data=f"deploy_{current_slot}")
    
    if is_current_running:
        action_btn = types.InlineKeyboardButton(f"🛑 Stop Slot {current_slot}", callback_data=f"stop_{current_slot}")
    else:
        action_btn = types.InlineKeyboardButton(f"🚀 Launch Slot {current_slot}", callback_data=f"launch_{current_slot}") if has_file else None

    if action_btn:
        markup.add(deploy_btn, action_btn)
    else:
        markup.add(deploy_btn)

    markup.add(
        types.InlineKeyboardButton(f"📋 Logs (Slot {current_slot})", callback_data=f"logs_{current_slot}"),
        types.InlineKeyboardButton("🔄 Refresh Data", callback_data="refresh")
    )
    
    markup.add(types.InlineKeyboardButton("🛠 Official Support", url=f"https://t.me/{ADMIN_USERNAME.replace('@', '')}"))
    return markup

def get_reply_keyboard():
    """Create reply keyboard"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    markup.add('🖥 Dashboard', '🚀 Deploy Bot', '📊 Server Status')
    markup.add('📁 My Projects', '🔗 Get Invite Link', '🆘 Help Desk')
    return markup

# --- Core Functions ---
def launch_bot(uid, slot):
    """Launch a bot in specified slot"""
    if not has_remaining_time(uid):
        return "NO_TIME"
        
    path = os.path.join(HOST_DIR, uid, slot, "main.py")
    log_path = os.path.join(HOST_DIR, uid, slot, "bot.log")
    if not os.path.exists(path):
        return "NO_FILE"
    try:
        if uid in running_processes and slot in running_processes[uid]:
            if running_processes[uid][slot].poll() is None:
                running_processes[uid][slot].kill()
        
        log_file = open(log_path, "a")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        process = subprocess.Popen(
            [sys.executable, path], 
            stderr=log_file, 
            stdout=log_file, 
            text=True,
            env=env
        )
        
        if uid not in running_processes:
            running_processes[uid] = {}
        if uid not in start_times:
            start_times[uid] = {}
            
        running_processes[uid][slot] = process
        start_times[uid][slot] = time.time()
        save_data()  # Save state
        return "SUCCESS"
    except Exception as e:
        logger.error(f"Error launching bot: {e}")
        return "ERROR"

# --- Bot Handlers ---
@bot.message_handler(commands=['start'])
def dashboard(message):
    """Handle /start command"""
    uid = str(message.chat.id)
    username = message.from_user.username if message.from_user.username else "No_Username"
    
    # Register user
    registered_users.add(uid)
    user_usernames[uid] = f"@{username}"
    
    # Handle referral
    msg_text = message.text
    if len(msg_text.split()) > 1 and msg_text.split()[1].startswith("ref_"):
        referrer_id = msg_text.split()[1].replace("ref_", "")
        
        if referrer_id != uid and uid not in referred_tracker:
            referred_tracker.add(uid)  
            
            if referrer_id not in user_time_balance or user_time_balance[referrer_id] < datetime.now():
                user_time_balance[referrer_id] = datetime.now() + timedelta(minutes=30)
            else:
                user_time_balance[referrer_id] += timedelta(minutes=30)
                
            try:
                bot.send_message(
                    referrer_id, 
                    f"🎉 **New Referral Alert!**\nUser @{username} က သင့်လင့်ခ်မှတစ်ဆင့် Join ခဲ့သည်။\n🎁 သင်သည် **+30 မိနစ်** Runtime လက်ဆောင် ရရှိပါပြီ။"
                )
            except Exception:
                pass
            save_data()

    if uid not in user_selected_slot:
        user_selected_slot[uid] = "1"
        
    current_slot = user_selected_slot[uid]
    
    is_live = False
    if uid in running_processes and current_slot in running_processes[uid]:
        if running_processes[uid][current_slot].poll() is None:
            is_live = True
            
    status_icon = "🟢 ACTIVE" if is_live else "🔴 OFFLINE"
    
    current_file = "No active project"
    if uid in file_names and current_slot in file_names[uid]:
        current_file = file_names[uid][current_slot]
    
    uptime = "0s"
    if is_live and uid in start_times and current_slot in start_times[uid]:
        diff = int(time.time() - start_times[uid][current_slot])
        days = diff // 86400
        hours = (diff % 86400) // 3600
        minutes = (diff % 3600) // 60
        seconds = diff % 60
        uptime = f"{days}d {hours}h {minutes}m {seconds}s"

    active_count = count_active_bots(uid)
    time_left_str = get_time_balance_string(uid)

    dashboard_ui = (
        f"💠 **VORTE XA ULTIMATE CLOUD v12.0** 💠\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 **Welcome Back, {message.from_user.first_name}!**\n"
        f"🆔 **Client ID:** `{uid}`\n"
        f"🎯 **Selected Workspace:** `Slot {current_slot}`\n"
        f"💰 **Runtime Balance:**\n`{time_left_str}`\n\n"
        f"🚀 **LIVE INSTANCE STATUS**\n"
        f"┣ Project: `📄 {current_file}`\n"
        f"┣ Status: {status_icon}\n"
        f"┣ Uptime: `{uptime}`\n"
        f"┗ Total Running Bots: `{active_count} / 3` 🔥\n\n"
        f"🖥 **SERVER ALLOCATION**\n"
        f"┣ Node: `Asia-Yangon-MZ1` 🇲🇲\n"
        f"┣ RAM Usage: `[■■■□□□□□□□] 30%`\n"
        f"┗ CPU Load: `[■□□□□□□□□□] 10%`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
    )
    
    try:
        bot.send_message(message.chat.id, dashboard_ui, reply_markup=get_reply_keyboard(), parse_mode='Markdown')
        bot.send_message(message.chat.id, f"🕹 **System Controller (Managing Slot {current_slot}):**", reply_markup=get_dashboard_markup(uid))
    except Exception as e:
        logger.error(f"Error sending dashboard: {e}")

# --- Admin Commands ---
@bot.message_handler(commands=['promeb'])
def admin_promeb(message):
    """Promote user to VIP PRO"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ You are not authorized to use this admin command.")
        return
        
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ **Usage:** `/promeb <user_chat_id>`")
        return
        
    target_uid = parts[1]
    pro_users.add(target_uid)
    registered_users.add(target_uid)  
    
    uname = user_usernames.get(target_uid, "Unknown User")
    bot.send_message(ADMIN_CHAT_ID, f"✅ **PRO Upgrade Success!**\nUser ID `{target_uid}` ({uname}) အား အချိန်အကန့်အသတ်မရှိ (Unlimited VIP PRO) သုံးစွဲခွင့် ပေးအပ်လိုက်ပါပြီ။")
    
    try:
        bot.send_message(target_uid, "🎉 **Congratulations!**\nAdmin မှ သင့်အား **Unlimited VIP PRO** အဆင့်သို့ တိုးမြှင့်ပေးလိုက်သဖြင့် ယခုမှစ၍ Bot ကို အချိန်အကန့်အသတ်မရှိ အခမဲ့ စိတ်ကြိုက် သုံးစွဲနိုင်ပါပြီ။")
    except Exception:
        pass
    save_data()

@bot.message_handler(commands=['promebdele'])
def admin_promebdele(message):
    """Remove VIP PRO status"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ You are not authorized to use this admin command.")
        return
        
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ **Usage:** `/promebdele <user_chat_id>`")
        return
        
    target_uid = parts[1]
    if target_uid in pro_users:
        pro_users.remove(target_uid)
        uname = user_usernames.get(target_uid, "Unknown User")
        bot.send_message(ADMIN_CHAT_ID, f"❌ **PRO Downgrade Success!**\nUser ID `{target_uid}` ({uname}) ၏ Unlimited VIP အခွင့်အရေးအား ပြန်လည်ရုပ်သိမ်းလိုက်ပါပြီ။")
        
        try:
            bot.send_message(target_uid, "⚠️ **Notice:** သင့်၏ VIP PRO အဆင့်ကို Admin မှ ပြန်လည်ရုပ်သိမ်းလိုက်ပြီ ဖြစ်ပါသည်။ ပုံမှန် Referral စနစ်ဖြင့် အချိန်ပြန်လည်စုဆောင်းနိုင်ပါသည်။")
        except Exception:
            pass
        save_data()
    else:
        bot.send_message(ADMIN_CHAT_ID, f"⚠️ User ID `{target_uid}` သည် VIP စာရင်းထဲတွင် မရှိပါ။")

@bot.message_handler(commands=['userlist'])
def admin_userlist(message):
    """Show all registered users"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ You are not authorized to use this admin command.")
        return
    
    if not registered_users:
        bot.send_message(ADMIN_CHAT_ID, "📊 **Registered Users:**\nNo users have registered yet.")
        return
        
    user_list_msg = "📊 **Registered Users List (Ordered):**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for idx, user_id in enumerate(sorted(registered_users), start=1):
        uname = user_usernames.get(user_id, "@No_Username")
        
        if user_id == ADMIN_CHAT_ID:
            status_tag = "👑 [OWNER]"
        elif user_id in pro_users:
            status_tag = "💎 [VIP PRO]"
        else:
            status_tag = "👤 [NORMAL]"
            
        user_list_msg += f"{idx}. ID: `{user_id}` | {uname} {status_tag}\n"
        
    bot.send_message(ADMIN_CHAT_ID, user_list_msg, parse_mode='Markdown')

@bot.message_handler(commands=['allmessage'])
def admin_broadcast(message):
    """Broadcast message to all users"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ You are not authorized to use this admin command.")
        return
        
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ **Usage:** `/allmessage <သင့်စာသား>`")
        return
        
    broadcast_text = parts[1]
    success_count = 0
    
    status_msg = bot.send_message(ADMIN_CHAT_ID, "📢 **Sending broadcast message to all users...**")
    
    for user_id in registered_users:
        try:
            bot.send_message(user_id, f"📢 **[GLOBAL ANNOUNCEMENT FROM ADMIN]**\n\n{broadcast_text}")
            success_count += 1
            time.sleep(0.05)  
        except Exception:
            continue
            
    bot.edit_message_text(f"✅ **Broadcast Completed!**\nSuccessfully sent to `{success_count}` users.", ADMIN_CHAT_ID, status_msg.message_id)

# --- Callback Handlers ---
@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    """Handle all callback queries"""
    uid = str(call.message.chat.id)
    
    if call.data.startswith("select_slot_"):
        slot = call.data.split("_")[-1]
        user_selected_slot[uid] = slot
        bot.answer_callback_query(call.id, f"Switched to Slot {slot}")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.delete_message(call.message.chat.id, call.message.message_id - 1)
        except Exception:
            pass
        dashboard(call.message)
        return

    current_slot = user_selected_slot.get(uid, "1")
    
    if call.data.startswith("stop_"):
        slot = call.data.split("_")[-1]
        if uid in running_processes and slot in running_processes[uid]:
            running_processes[uid][slot].kill()
            bot.send_message(call.message.chat.id, f"🛑 **Slot {slot} Terminated.** Bot has been stopped.")
            dashboard(call.message)
            
    elif call.data.startswith("launch_"):
        slot = call.data.split("_")[-1]
        result = launch_bot(uid, slot)
        if result == "SUCCESS":
            bot.answer_callback_query(call.id, f"🚀 Launching Slot {slot}...")
            dashboard(call.message)
        elif result == "NO_TIME":
            bot.answer_callback_query(call.id, "❌ Run failed! No remaining runtime balance.", show_alert=True)
            bot.send_message(call.message.chat.id, "⚠️ **သင့်မှာ Hosting Run ရန် အချိန်မရှိတော့ပါ။** ကျေးဇူးပြု၍ သူငယ်ချင်းများကို ဖိတ်ခေါ်ပြီး မိနစ်များ စုဆောင်းပါ။")
        else:
            bot.answer_callback_query(call.id, "❌ Launch failed.")
            
    elif call.data == "refresh":
        bot.answer_callback_query(call.id, "Syncing real-time data...")
        dashboard(call.message)
        
    elif call.data.startswith("deploy_"):
        slot = call.data.split("_")[-1]
        user_selected_slot[uid] = slot
        bot.send_message(call.message.chat.id, f"📤 **Please upload your Python (.py) script for [Slot {slot}].**")
        
    elif call.data.startswith("logs_"):
        slot = call.data.split("_")[-1]
        log_path = os.path.join(HOST_DIR, uid, slot, "bot.log")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                last_logs = "".join(lines[-30:]) if lines else "Log is empty but file exists."
            
            log_msg = f"📋 **Live Logs for Slot {slot}:**\n```\n{last_logs}\n```"
            bot.send_message(call.message.chat.id, log_msg, parse_mode='Markdown')
        else:
            bot.send_message(call.message.chat.id, f"❌ **No log data found for Slot {slot}**.")

# --- Text Handlers ---
@bot.message_handler(content_types=['text'])
def handle_text(message):
    """Handle text messages"""
    uid = str(message.chat.id)
    username = message.from_user.username if message.from_user.username else "No_Username"
    
    registered_users.add(uid)
    user_usernames[uid] = f"@{username}"

    if uid not in user_selected_slot:
        user_selected_slot[uid] = "1"
    current_slot = user_selected_slot[uid]
    
    if message.text in ['🖥 Dashboard', '⚙️ Control Center']:
        dashboard(message)
    elif message.text == '🚀 Deploy Bot':
        bot.send_message(message.chat.id, f"📤 **Ready for deployment.** Send your file for **[Slot {current_slot}]**.")
    elif message.text == '📊 Server Status':
        active_global = 0
        for u in running_processes:
            for s in running_processes[u]:
                if running_processes[u][s].poll() is None:
                    active_global += 1
        bot.send_message(message.chat.id, f"📊 **Network Node:** `Stable` ✅\n👥 **Global Instances:** `{active_global}` live globally.")
    elif message.text in ['📁 My Projects']:
        status_text = "📂 **Your Workspace Status:**\n\n"
        for i in range(1, 4):
            slot_str = str(i)
            name = "Empty Slot"
            if uid in file_names and slot_str in file_names[uid]:
                name = file_names[uid][slot_str]
                
            is_running = False
            if uid in running_processes and slot_str in running_processes[uid]:
                if running_processes[uid][slot_str].poll() is None:
                    is_running = True
            
            state = "🟢 RUNNING" if is_running else "🔴 STOPPED"
            status_text += f"**Slot {i}:** `{name}` | Status: {state}\n"
            
        bot.send_message(message.chat.id, status_text, parse_mode='Markdown')
    elif message.text in ['🔗 Get Invite Link', '/newmeb']:
        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
        
        invitation_msg = (
            f"🔗 **မြန်မာနိုင်ငံ၏ ပထမဆုံးသော အခမဲ့ Multi-Slot Bot Hosting Link**\n\n"
            f"ဤလင့်ခ်ကိုအသုံးပြုပြီး Bot တွင်ဝင်ရောက်အသုံးပြုပါက ဖိတ်ခေါ်သူသည် မိနစ် ၃၀ လုံးလုံး အခမဲ့ hosting သုံးစွဲခွင့်ရရှိမည်ဖြစ်ပါသည်။\n"
            f"👉 {ref_link}\n\n"
            f"👥 **ဆုကြေးအစီအစဉ်:**\n"
            f"• လူတစ်ယောက်ခေါ်လျှင် = `၃၀ မိနစ်` Runtime 🎁\n"
            f"• လူနှစ်ယောက်ခေါ်လျှင် = `၁ နာရီ` Runtime 🎁"
        )
        bot.send_message(uid, invitation_msg)
    elif message.text == '🆘 Help Desk':
        bot.send_message(uid, f"🆘 **Support Center:**\nContact {ADMIN_USERNAME} for assistance.")
    save_data()

# --- Deployment Engine ---
@bot.message_handler(content_types=['document'])
def deploy_engine(message):
    """Handle file uploads for deployment"""
    if message.document.file_name.endswith('.py'):
        uid = str(message.chat.id)
        
        if not has_remaining_time(uid):
            bot.reply_to(message, "❌ **Deployment Denied.** သင့်မှာ runtime အချိန်မကျန်တော့ပါ။ ကျေးဇူးပြု၍ သူငယ်ချင်းများကိုဖိတ်ခေါ်ပြီး အချိန်အရင်ယူပါ။")
            return
            
        if uid not in user_selected_slot:
            user_selected_slot[uid] = "1"
        current_slot = user_selected_slot[uid]
        
        if uid not in file_names:
            file_names[uid] = {}
        file_names[uid][current_slot] = message.document.file_name
        
        status_msg = bot.reply_to(message, f"⚙️ **Initializing Build Environment for Slot {current_slot}...**")
        
        file_info = bot.get_file(message.document.file_id)
        data = bot.download_file(file_info.file_path)
        
        path = os.path.join(HOST_DIR, uid, current_slot, "main.py")
        log_path = os.path.join(HOST_DIR, uid, current_slot, "bot.log")
        
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        if os.path.exists(log_path):
            os.remove(log_path)
            
        with open(path, 'wb') as f:
            f.write(data)

        result = launch_bot(uid, current_slot)
        if result == "SUCCESS":
            bot.edit_message_text(f"✅ **DEPLOYMENT SUCCESSFUL TO SLOT {current_slot}!**\nInstance node is now live.", message.chat.id, status_msg.message_id)
        elif result == "NO_TIME":
            bot.edit_message_text(f"❌ **BOOT ERROR.** Runtime balance မရှိတော့ပါ။", message.chat.id, status_msg.message_id)
        else:
            bot.edit_message_text(f"❌ **BOOT ERROR ON SLOT {current_slot}.** Please check your script code.", message.chat.id, status_msg.message_id)
        save_data()

# --- Auto Time Killer Background Thread ---
def time_enforcer_loop():
    """Background thread to enforce time limits"""
    while True:
        try:
            current_time = datetime.now()
            for uid in list(running_processes.keys()):
                if uid == ADMIN_CHAT_ID or uid in pro_users:
                    continue  
                    
                if uid in user_time_balance and current_time >= user_time_balance[uid]:
                    for slot in list(running_processes[uid].keys()):
                        if running_processes[uid][slot].poll() is None:
                            running_processes[uid][slot].kill()  
                            try:
                                bot.send_message(int(uid), f"⚠️ **Notice:** သင့်ရဲ့ အခမဲ့ သုံးစွဲခွင့် Runtime သက်တမ်း ကုန်ဆုံးသွားသဖြင့် **Slot {slot}** ရှိ Bot အား ခေတ္တရပ်ဆိုင်းလိုက်ရပါသည်။ ဆက်လက်သုံးစွဲရန် သူငယ်ချင်းများကို ထပ်မံဖိတ်ခေါ်ပေးပါ။")
                            except Exception:
                                pass
                    if uid in running_processes:
                        del running_processes[uid]
        except Exception as e:
            logger.error(f"Error in time enforcer: {e}")
        time.sleep(30)

# --- Flask Web Server Routes ---
@app.route('/')
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        'status': 'running',
        'version': '12.0',
        'uptime': time.time() - start_time,
        'users': len(registered_users),
        'active_bots': sum(count_active_bots(uid) for uid in running_processes)
    })

@app.route('/stats')
def stats():
    """Detailed statistics endpoint"""
    return jsonify({
        'registered_users': len(registered_users),
        'pro_users': len(pro_users),
        'active_slots': sum(count_active_bots(uid) for uid in running_processes),
        'total_slots': sum(len(running_processes[uid]) for uid in running_processes)
    })

def run_web_server():
    """Run Flask web server for health checks"""
    try:
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Web server error: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    start_time = time.time()
    
    # Load saved data
    load_data()
    
    # Print startup banner
    print("=" * 50)
    print("  VORTEXA ULTIMATE CLOUD v12.0")
    print("  PRODUCTION READY")
    print("=" * 50)
    print(f"  Bot Token: {'✓' if API_TOKEN else '✗'}")
    print(f"  Admin ID: {ADMIN_CHAT_ID}")
    print(f"  Registered Users: {len(registered_users)}")
    print(f"  VIP Users: {len(pro_users)}")
    print("=" * 50)
    
    # Start web server in background
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    logger.info("Web server started on port 8080")
    
    # Start time 
    time_thread = threading.Thread(target=time_enforcer_loop, daemon=True)
    time_thread.start()
    logger.info("Time enforcer started")
    
    # Start Telegram bot
    logger.info("Starting Telegram bot...")
    try:
        while True:
            try:
                bot.polling(non_stop=True, interval=1, timeout=30)
            except Exception as e:
                logger.error(f"Bot polling error: {e}")
                time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        sys.exit(0)

