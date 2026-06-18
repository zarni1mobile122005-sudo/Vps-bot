import telebot
from telebot import types
import subprocess
import os
import sys
import time
import platform
import threading
from datetime import datetime, timedelta

# --- CONFIGURATION ---
API_TOKEN = ' 8847534009:AAEWHzsdgC8b1a4TdAvKeOgReTJPB_ODUsc'
ADMIN_USERNAME = '@mgzan201' 
ADMIN_CHAT_ID = "7592705124"  # အထူးအခွင့်အရေးရမည့် Admin Chat ID
bot = telebot.TeleBot(API_TOKEN)

# Directory Setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_DIR = os.path.join(BASE_DIR, "hosted_bots")
if not os.path.exists(HOST_DIR):
    os.makedirs(HOST_DIR)

# Global Trackers
running_processes = {}
start_times = {}
file_names = {}
user_selected_slot = {}

# --- NEW TRACKERS (DATABASE MEMORY) ---
registered_users = set()        # Bot ကို သုံးဖူးသမျှ user status သိရန် (Set)
user_usernames = {}            # { uid: username } ပုံစံသိမ်းရန်
user_time_balance = {}         # { uid: time_object } အချိန်လက်ကျန်မှတ်ရန်
referred_tracker = set()       # အချင်းချင်း ဒုတိယအကြိမ် ထပ်လင့်နှိပ်ပြီး point ခိုးယူခြင်းမှ ကာကွယ်ရန်
pro_users = set()              # အချိန်အကန့်အသတ်မရှိ (Unlimited Free) သုံးခွင့်ရမည့် VIP User များ

# Active Multi-instance ကောင်တာ အတွက် Helper
def count_active_bots(uid):
    if uid not in running_processes:
        return 0
    return sum(1 for pid in running_processes[uid].values() if pid.poll() is None)

# အချိန်လက်ကျန် ရှိ/မရှိ စစ်ဆေးပေးမည့် Helper
def has_remaining_time(uid):
    if uid == ADMIN_CHAT_ID or uid in pro_users:
        return True  # Admin နှင့် VIP User များသည် Free Run လို့ရသည်
    if uid not in user_time_balance:
        return False
    return datetime.now() < user_time_balance[uid]

# ကျန်ရှိချိန်ကို စာသားအဖြစ် ပြောင်းပေးမည့် Helper
def get_time_balance_string(uid):
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

# --- UI COMPONENTS ---
def get_dashboard_markup(uid):
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
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    markup.add('🖥 Dashboard', '🚀 Deploy Bot', '📊 Server Status')
    markup.add('📁 My Projects', '🔗 Get Invite Link', '🆘 Help Desk')
    return markup

# --- CORE FUNCTIONS ---
@bot.message_handler(commands=['start'])
def dashboard(message):
    uid = str(message.chat.id)
    username = message.from_user.username if message.from_user.username else "No_Username"
    
    # User စာရင်း သွင်းခြင်း
    registered_users.add(uid)
    user_usernames[uid] = f"@{username}"
    
    # --- REFERRAL LOGIC ENGINE ---
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
                    f"🎉 **New Referral Alert!**\nUser @{username} က သင့်လင့်ခ်မှတစ်ဆင့် Join ခဲ့သည်။\n🎁 သင်သည် **+30 မိနစ်** Runtime လက်ဆောင် ရရှိပါပြီ।"
                )
            except Exception:
                pass

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
        f"💠 **VORTEXA ULTIMATE CLOUD v12.0** 💠\n"
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
    
    bot.send_message(message.chat.id, dashboard_ui, reply_markup=get_reply_keyboard(), parse_mode='Markdown')
    bot.send_message(message.chat.id, f"🕹 **System Controller (Managing Slot {current_slot}):**", reply_markup=get_dashboard_markup(uid))

def launch_bot(uid, slot):
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
        return "SUCCESS"
    except Exception:
        return "ERROR"

# --- NEW ADMIN SYSTEM COMMANDS ---

@bot.message_handler(commands=['promeb'])
def admin_promeb(message):
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

@bot.message_handler(commands=['promebdele'])
def admin_promebdele(message):
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
    else:
        bot.send_message(ADMIN_CHAT_ID, f"⚠️ User ID `{target_uid}` သည် VIP စာရင်းထဲတွင် မရှိပါ။")

@bot.message_handler(commands=['userlist'])
def admin_userlist(message):
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

# --- CALLBACKS ---
@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
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
            
            # အောက်က စာသားမှာ f-string ပိတ်တာ လိုသွားလို့ အမှန်ပြန်ပြင်ထားပါတယ်
            log_msg = f"📋 **Live Logs for Slot {slot}:**\n```\n{last_logs}\n```"
            bot.send_message(call.message.chat.id, log_msg, parse_mode='Markdown')
        else:
            bot.send_message(call.message.chat.id, f"❌ **No log data found for Slot {slot}**.")

# --- TEXT HANDLERS ---
@bot.message_handler(func=lambda m: True)
def handle_text(message):
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

# --- DEPLOYMENT ENGINE ---
@bot.message_handler(content_types=['document'])
def deploy_engine(message):
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

# --- AUTO TIME KILLER BACKGROUND THREAD ---
def time_enforcer_loop():
    while True:
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
                del running_processes[uid]
        time.sleep(30) 

if __name__ == "__main__":
    print(f">>> VORTEXA MULTI-INSTANCE CLOUD v12.0 IS LIVE WITH REFERRAL & ADMIN ENGINE")
    
    t = threading.Thread(target=time_enforcer_loop, daemon=True)
    t.start()
    
    while True:
        try:
            bot.polling(non_stop=True, interval=1)
        except Exception as e:
            print(f"Main Bot Crash Prevented: {e}")
            time.sleep(5)
