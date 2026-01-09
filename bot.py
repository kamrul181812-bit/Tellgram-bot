import os
import logging
import sqlite3
import re
from datetime import datetime
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    ContextTypes, 
    filters
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ✅ IMPORTANT: Render.com এর জন্য Environment Variable থেকে টোকেন নিবে
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ✅ টোকেন না পেলে error দিবে
if not BOT_TOKEN:
    logger.error("❌ ERROR: BOT_TOKEN environment variable not set!")
    logger.error("💡 Please set BOT_TOKEN in Render.com dashboard")
    exit(1)

# Database setup
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    # Warnings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS warnings (
            chat_id INTEGER,
            user_id INTEGER,
            warnings INTEGER DEFAULT 0,
            last_warned TIMESTAMP,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    
    # Chat settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id INTEGER PRIMARY KEY,
            warn_mode TEXT DEFAULT 'mute',
            warn_limit INTEGER DEFAULT 3,
            warn_time TEXT DEFAULT 'off',
            welcome_msg TEXT,
            rules_msg TEXT
        )
    ''')
    
    # Custom commands table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_commands (
            chat_id INTEGER,
            command TEXT,
            response TEXT,
            PRIMARY KEY (chat_id, command)
        )
    ''')
    
    # Banned users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS banned_users (
            chat_id INTEGER,
            user_id INTEGER,
            banned_by INTEGER,
            ban_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Helper function to check admin
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None):
    chat_id = update.effective_chat.id
    if user_id is None:
        user_id = update.effective_user.id
    
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ['administrator', 'creator']
    except:
        return False

# Database functions
def get_user_warnings(chat_id, user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT warnings FROM warnings WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def update_user_warnings(chat_id, user_id, warnings):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO warnings (chat_id, user_id, warnings, last_warned)
        VALUES (?, ?, ?, ?)
    ''', (chat_id, user_id, warnings, datetime.now()))
    conn.commit()
    conn.close()

def get_chat_settings(chat_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM chat_settings WHERE chat_id = ?', (chat_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'warn_mode': result[1],
            'warn_limit': result[2],
            'warn_time': result[3],
            'welcome_msg': result[4],
            'rules_msg': result[5]
        }
    else:
        # Default settings
        default_settings = {
            'warn_mode': 'mute',
            'warn_limit': 3,
            'warn_time': 'off',
            'welcome_msg': None,
            'rules_msg': None
        }
        set_chat_settings(chat_id, default_settings)
        return default_settings

def set_chat_settings(chat_id, settings):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO chat_settings 
        (chat_id, warn_mode, warn_limit, warn_time, welcome_msg, rules_msg)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (chat_id, settings['warn_mode'], settings['warn_limit'], 
          settings['warn_time'], settings['welcome_msg'], settings['rules_msg']))
    conn.commit()
    conn.close()

def add_custom_command(chat_id, command, response):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO custom_commands (chat_id, command, response)
        VALUES (?, ?, ?)
    ''', (chat_id, command.lower(), response))
    conn.commit()
    conn.close()

def get_custom_command(chat_id, command):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT response FROM custom_commands WHERE chat_id = ? AND command = ?', 
                   (chat_id, command.lower()))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_all_custom_commands(chat_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT command, response FROM custom_commands WHERE chat_id = ?', (chat_id,))
    results = cursor.fetchall()
    conn.close()
    return results

def delete_custom_command(chat_id, command):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM custom_commands WHERE chat_id = ? AND command = ?', 
                   (chat_id, command.lower()))
    conn.commit()
    conn.close()

def ban_user(chat_id, user_id, banned_by):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO banned_users (chat_id, user_id, banned_by, ban_time)
        VALUES (?, ?, ?, ?)
    ''', (chat_id, user_id, banned_by, datetime.now()))
    conn.commit()
    conn.close()

def unban_user(chat_id, user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM banned_users WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0

def is_user_banned(chat_id, user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM banned_users WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_banned_users(chat_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, banned_by, ban_time FROM banned_users WHERE chat_id = ?', (chat_id,))
    results = cursor.fetchall()
    conn.close()
    return results

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Add to me your chat..!", url="http://t.me/your_bot_username?startgroup=true"),
            InlineKeyboardButton("All Update", url="https://t.me/your_channel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Hey there! My name is SPECIAL CONTROLLER- I'm here to help you manage your groups! "
        "Use /help to find out how to use me to my full potential.\n\n"
        "Join my news channel to get information on all the latest updates.",
        reply_markup=reply_markup
    )

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
*Admin Commands:*

*Warning System:*
- /warn <reason>: Warn a user.
- /dwarn <reason>: Warn a user by reply, and delete their message.
- /swarn <reason>: Silently warn a user, and delete your message.
- /warns: See a user's warnings.
- /rmwarn: Remove a user's latest warning.
- /resetwarn: Reset all of a user's warnings to 0.
- /resetallwarns: Delete all the warnings in a chat.
- /warnings: Get the chat's warning settings.
- /warnmode <ban/mute/kick>: View or set the chat's warn mode.
- /warnlimit <number>: View or set the warning limit.
- /warntime <time>: View or set warn expiration time.

*Ban Management:*
- /ban @user: Ban a user from the chat.
- /banlist: Show list of banned users.
- /unban @user: Unban a user from the chat.

*Chat Settings:*
- /welcome <message>: Set welcome message
- /rulesset <message>: Set rules message
- /cmd <trigger>: Add custom command (interactive)
  Example: /cmd hi
- /delcmd <trigger>: Delete custom command
- /cmds: List all custom commands

*User Commands:*
- /rules: View chat rules
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Custom command handler - INTERACTIVE VERSION ✅
async def set_custom_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set custom commands!")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /cmd <trigger>\nExample: /cmd hi")
        return
    
    trigger = context.args[0].strip()
    
    # Remove leading slash if present
    if trigger.startswith('/'):
        trigger = trigger[1:]
    
    if not trigger:
        await update.message.reply_text("Trigger cannot be empty!")
        return
    
    # Check if command already exists
    existing = get_custom_command(chat_id, trigger)
    if existing:
        await update.message.reply_text(
            f"⚠️ Command `{trigger}` already exists!\n"
            f"Current response: {existing}\n\n"
            "Do you want to overwrite it? Reply with 'yes' or 'no'"
        )
        # Store trigger in context for later use
        context.user_data['cmd_trigger'] = trigger
        context.user_data['waiting_for_response'] = True
        return
    
    # Ask for response
    await update.message.reply_text(
        f"✅ Trigger set: `{trigger}`\n\n"
        "Now please send the response message for this command.\n"
        "You can send *any length* of text, media, or even multiple messages.\n"
        "When done, reply with *!done* to save the command."
    )
    
    # Store trigger in context for later use
    context.user_data['cmd_trigger'] = trigger
    context.user_data['waiting_for_response'] = True
    context.user_data['response_parts'] = []

# Helper function to save custom command
def save_custom_command_from_context(chat_id, context):
    trigger = context.user_data.get('cmd_trigger')
    response_parts = context.user_data.get('response_parts', [])
    
    if trigger and response_parts:
        # Combine all response parts
        response = "\n".join(response_parts)
        add_custom_command(chat_id, trigger, response)
        
        # Clear context
        context.user_data.pop('cmd_trigger', None)
        context.user_data.pop('waiting_for_response', None)
        context.user_data.pop('response_parts', None)
        
        return trigger, response
    return None, None

# Handle response collection for custom commands
async def handle_cmd_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if we're waiting for command response
    if context.user_data.get('waiting_for_response'):
        message_text = update.message.text or ""
        
        # Check if user wants to finish
        if message_text.strip().lower() == '!done':
            trigger, response = save_custom_command_from_context(chat_id, context)
            
            if trigger and response:
                await update.message.reply_text(
                    f"✅ Custom command saved successfully!\n\n"
                    f"Trigger: `{trigger}`\n"
                    f"Response: {response[:200]}..." if len(response) > 200 else f"Response: {response}"
                )
            else:
                await update.message.reply_text("❌ No response collected. Command not saved.")
            return
        
        # Check for cancel
        if message_text.strip().lower() in ['cancel', '!cancel']:
            context.user_data.pop('cmd_trigger', None)
            context.user_data.pop('waiting_for_response', None)
            context.user_data.pop('response_parts', None)
            await update.message.reply_text("❌ Command setup cancelled.")
            return
        
        # Collect response part
        if update.message.text:
            response_part = update.message.text
        elif update.message.caption:
            response_part = update.message.caption
        else:
            response_part = "[Media message]"
        
        context.user_data.setdefault('response_parts', []).append(response_part)
        
        # Show progress
        parts_count = len(context.user_data['response_parts'])
        await update.message.reply_text(
            f"📝 Part {parts_count} added.\n"
            f"Send more or reply with *!done* to save."
        )

# Delete custom command
async def delete_custom_command_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can delete custom commands!")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /delcmd <trigger>")
        return
    
    trigger = context.args[0].strip()
    if trigger.startswith('/'):
        trigger = trigger[1:]
    
    if get_custom_command(chat_id, trigger):
        delete_custom_command(chat_id, trigger)
        await update.message.reply_text(f"✅ Command `{trigger}` deleted successfully!")
    else:
        await update.message.reply_text(f"❌ Command `{trigger}` not found!")

# List custom commands
async def list_custom_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    commands = get_all_custom_commands(chat_id)
    if not commands:
        await update.message.reply_text("No custom commands set for this chat.")
        return
    
    commands_text = "📋 *Custom Commands:*\n\n"
    for i, (cmd, response) in enumerate(commands, 1):
        response_preview = response[:50] + "..." if len(response) > 50 else response
        commands_text += f"{i}. `{cmd}`\n   ➤ {response_preview}\n\n"
    
    await update.message.reply_text(commands_text, parse_mode='Markdown')

# Welcome command
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set welcome message!")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /welcome <message>\n\nYou can use:\n{mention} - User mention\n{title} - Chat title")
        return
    
    welcome_msg = ' '.join(context.args)
    settings = get_chat_settings(chat_id)
    settings['welcome_msg'] = welcome_msg
    set_chat_settings(chat_id, settings)
    
    await update.message.reply_text("✅ Welcome message set successfully!")

# Rules set command (admin)
async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set rules!")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /rulesset <rules message>")
        return
    
    rules_msg = ' '.join(context.args)
    settings = get_chat_settings(chat_id)
    settings['rules_msg'] = rules_msg
    set_chat_settings(chat_id, settings)
    
    await update.message.reply_text("✅ Rules set successfully!")

# Rules command (user)
async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    settings = get_chat_settings(chat_id)
    
    if settings['rules_msg']:
        await update.message.reply_text(f"📜 *Chat Rules:*\n\n{settings['rules_msg']}", parse_mode='Markdown')
    else:
        await update.message.reply_text("No rules have been set for this chat yet.")

# Ban command
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can ban users!")
        return
    
    # Check if replying to a message
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        username = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
        reason = ' '.join(context.args) if context.args else "No reason provided"
    elif context.args:
        # Try to get user from mention
        try:
            mention = context.args[0]
            if mention.startswith('@'):
                # We need to extract user from mention - simplified approach
                # In production, you'd need to parse the user_id from mention properly
                await update.message.reply_text("Please reply to the user's message to ban them, or use user ID.")
                return
            elif mention.isdigit():
                user_id = int(mention)
                username = f"user_{user_id}"
                reason = ' '.join(context.args[1:]) if len(context.args) > 1 else "No reason provided"
            else:
                await update.message.reply_text("Usage: /ban @user OR reply to user's message")
                return
        except (ValueError, IndexError):
            await update.message.reply_text("Usage: /ban @user OR reply to user's message")
            return
    else:
        await update.message.reply_text("Usage: /ban @user OR reply to user's message")
        return
    
    # Don't allow banning admins
    if await is_admin(update, context, user_id):
        await update.message.reply_text("Cannot ban an admin!")
        return
    
    try:
        # Ban the user
        await context.bot.ban_chat_member(chat_id, user_id)
        
        # Store in database
        ban_user(chat_id, user_id, admin_id)
        
        ban_message = f"✅ User {username} has been banned!"
        if reason and reason != "No reason provided":
            ban_message += f"\nReason: {reason}"
        
        await update.message.reply_text(ban_message)
    except Exception as e:
        logger.error(f"Error banning user: {e}")
        await update.message.reply_text("Failed to ban user. Make sure I have admin permissions.")

# Unban command
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can unban users!")
        return
    
    if context.args:
        try:
            # Extract user from argument
            user_arg = context.args[0]
            if user_arg.startswith('@'):
                # This is simplified - in production, parse username properly
                await update.message.reply_text("Please use user ID to unban, or reply to their message if available.")
                return
            elif user_arg.isdigit():
                user_id = int(user_arg)
            else:
                await update.message.reply_text("Please provide user ID to unban")
                return
        except (ValueError, IndexError):
            await update.message.reply_text("Usage: /unban user_id")
            return
    else:
        await update.message.reply_text("Usage: /unban user_id")
        return
    
    try:
        # Unban the user
        await context.bot.unban_chat_member(chat_id, user_id)
        
        # Remove from database
        if unban_user(chat_id, user_id):
            await update.message.reply_text(f"✅ User {user_id} has been unbanned!")
        else:
            await update.message.reply_text("User was not found in ban list.")
    except Exception as e:
        logger.error(f"Error unbanning user: {e}")
        await update.message.reply_text("Failed to unban user.")

# Banlist command
async def banlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can view ban list!")
        return
    
    banned_users = get_banned_users(chat_id)
    
    if not banned_users:
        await update.message.reply_text("No users are currently banned in this chat.")
        return
    
    ban_list_text = "📋 *Banned Users:*\n\n"
    for i, (user_id, banned_by, ban_time) in enumerate(banned_users, 1):
        ban_list_text += f"{i}. User ID: `{user_id}`\n   Banned by: {banned_by}\n   Time: {ban_time}\n\n"
    
    await update.message.reply_text(ban_list_text, parse_mode='Markdown')

# Handle custom commands when users type them
async def handle_custom_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message_text = update.message.text.strip()
    
    # Check if we're collecting response for /cmd
    if context.user_data.get('waiting_for_response'):
        await handle_cmd_response(update, context)
        return
    
    # Check if it's a custom command (not starting with /)
    if message_text and not message_text.startswith('/'):
        # Check if this matches any custom command
        custom_commands = get_all_custom_commands(chat_id)
        
        for command, response in custom_commands:
            # Check if message matches the command (case insensitive)
            if message_text.lower() == command.lower():
                await update.message.reply_text(response)
                return
    
    # Also handle commands with slash
    elif message_text.startswith('/'):
        # Extract command without slash and parameters
        cmd = message_text[1:].split()[0].lower()
        
        # Check if it's a custom command
        response = get_custom_command(chat_id, cmd)
        if response:
            await update.message.reply_text(response)
            return

# Warn system functions (unchanged from your code, but with admin check)
async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, reason: str, delete_message: bool = False, silent: bool = False):
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("You need to be an admin to use this command.")
        return
    
    current_warnings = get_user_warnings(chat_id, user_id)
    new_warnings = current_warnings + 1
    
    update_user_warnings(chat_id, user_id, new_warnings)
    
    settings = get_chat_settings(chat_id)
    warn_limit = settings['warn_limit']
    
    # Delete messages if required
    if delete_message and update.message.reply_to_message:
        await update.message.reply_to_message.delete()
    if silent:
        await update.message.delete()
    
    if not silent:
        warning_msg = f"User warned! Current warnings: {new_warnings}/{warn_limit}"
        if reason:
            warning_msg += f"\nReason: {reason}"
        await update.message.reply_text(warning_msg)
    
    # Check if warn limit reached
    if new_warnings >= warn_limit:
        await execute_warn_action(update, context, user_id, settings['warn_mode'])

async def execute_warn_action(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, action: str):
    chat_id = update.effective_chat.id
    
    try:
        if action == 'ban':
            await context.bot.ban_chat_member(chat_id, user_id)
            ban_user(chat_id, user_id, update.effective_user.id)
            action_msg = "banned"
        elif action == 'kick':
            await context.bot.ban_chat_member(chat_id, user_id)
            await context.bot.unban_chat_member(chat_id, user_id)
            action_msg = "kicked"
        elif action == 'mute':
            # Restrict user's permissions
            permissions = {
                'can_send_messages': False,
                'can_send_media_messages': False,
                'can_send_polls': False,
                'can_send_other_messages': False,
                'can_add_web_page_previews': False,
                'can_change_info': False,
                'can_invite_users': False,
                'can_pin_messages': False
            }
            await context.bot.restrict_chat_member(chat_id, user_id, permissions)
            action_msg = "muted"
        else:
            action_msg = "punished"
        
        await context.bot.send_message(
            chat_id,
            f"User has reached the warning limit and has been {action_msg}."
        )
        
        # Reset warnings after punishment
        update_user_warnings(chat_id, user_id, 0)
        
    except Exception as e:
        logger.error(f"Error executing warn action: {e}")

# Warning commands (keeping your existing functions)
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text("Usage: /warn <reason> OR reply to a message")
        return
    
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        reason = ' '.join(context.args) if context.args else "No reason provided"
    else:
        reason = ' '.join(context.args) if context.args else "No reason provided"
        await update.message.reply_text("Please reply to the user's message to warn them")
        return
    
    await warn_user(update, context, user_id, reason)

async def dwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to use /dwarn")
        return
    
    reason = ' '.join(context.args) if context.args else "No reason provided"
    user_id = update.message.reply_to_message.from_user.id
    await warn_user(update, context, user_id, reason, delete_message=True)

async def swarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to use /swarn")
        return
    
    reason = ' '.join(context.args) if context.args else "No reason provided"
    user_id = update.message.reply_to_message.from_user.id
    await warn_user(update, context, user_id, reason, silent=True)

async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        username = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
    else:
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
    
    warning_count = get_user_warnings(chat_id, user_id)
    await update.message.reply_text(f"⚠️ @{username} has {warning_count} warnings.")

async def rmwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can remove warnings!")
        return
    
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
    else:
        await update.message.reply_text("Reply to a user to remove their latest warning.")
        return
    
    current_warnings = get_user_warnings(chat_id, user_id)
    if current_warnings > 0:
        update_user_warnings(chat_id, user_id, current_warnings - 1)
        await update.message.reply_text("✅ Latest warning removed.")
    else:
        await update.message.reply_text("User has no warnings to remove.")

async def resetwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can reset warnings!")
        return
    
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
    else:
        await update.message.reply_text("Reply to a user to reset their warnings.")
        return
    
    update_user_warnings(chat_id, user_id, 0)
    await update.message.reply_text("✅ User warnings reset to 0.")

async def resetallwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can reset all warnings!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM warnings WHERE chat_id = ?', (chat_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ All warnings in this chat have been reset.")

async def warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    settings = get_chat_settings(chat_id)
    
    warnings_text = f"""
*⚠️ Warning Settings for this chat:*
• Warn Mode: `{settings['warn_mode']}`
• Warn Limit: `{settings['warn_limit']}`
• Warn Time: `{settings['warn_time']}`
    """
    await update.message.reply_text(warnings_text, parse_mode='Markdown')

async def warnmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can change warn mode!")
        return
    
    settings = get_chat_settings(chat_id)
    
    if context.args:
        new_mode = context.args[0].lower()
        if new_mode in ['ban', 'mute', 'kick']:
            settings['warn_mode'] = new_mode
            set_chat_settings(chat_id, settings)
            await update.message.reply_text(f"✅ Warn mode set to: `{new_mode}`", parse_mode='Markdown')
        else:
            await update.message.reply_text("Invalid mode. Use: ban/mute/kick")
    else:
        await update.message.reply_text(f"Current warn mode: `{settings['warn_mode']}`", parse_mode='Markdown')

async def warnlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can change warning limit!")
        return
    
    settings = get_chat_settings(chat_id)
    
    if context.args:
        try:
            new_limit = int(context.args[0])
            if new_limit < 1:
                await update.message.reply_text("Warning limit must be at least 1")
                return
            settings['warn_limit'] = new_limit
            set_chat_settings(chat_id, settings)
            await update.message.reply_text(f"✅ Warning limit set to: `{new_limit}`", parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("Please provide a valid number")
    else:
        await update.message.reply_text(f"Current warning limit: `{settings['warn_limit']}`", parse_mode='Markdown')

async def warntime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if user is admin
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can change warn time!")
        return
    
    settings = get_chat_settings(chat_id)
    
    if context.args:
        new_time = context.args[0].lower()
        if new_time == 'off':
            settings['warn_time'] = 'off'
            set_chat_settings(chat_id, settings)
            await update.message.reply_text("✅ Warn time disabled - warnings will not expire")
        else:
            settings['warn_time'] = new_time
            set_chat_settings(chat_id, settings)
            await update.message.reply_text(f"✅ Warn time set to: `{new_time}`", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"Current warn time: `{settings['warn_time']}`", parse_mode='Markdown')

# Auto-remove links
async def auto_remove_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if we're collecting response for /cmd
    if context.user_data.get('waiting_for_response'):
        return
    
    # Check if user is admin
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    try:
        if await is_admin(update, context):
            return  # Admins can post links
        
        # Check for links in message
        message_text = update.message.text or update.message.caption or ""
        link_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        
        if re.search(link_pattern, message_text):
            await update.message.delete()
            warning_msg = await update.message.reply_text("⚠️ Links are not allowed for non-admins!")
            # Delete warning after 5 seconds
            await context.bot.delete_message(chat_id, warning_msg.message_id)
            
    except Exception as e:
        logger.error(f"Error in auto_remove_links: {e}")

# New chat member handler
async def new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    settings = get_chat_settings(chat_id)
    
    if settings['welcome_msg']:
        for member in update.message.new_chat_members:
            if member.id == context.bot.id:
                # Bot added to group
                await update.message.reply_text("Thanks for adding me! Use /help to see my commands.")
            else:
                # Regular user joined
                welcome_text = settings['welcome_msg']
                welcome_text = welcome_text.replace('{mention}', f"@{member.username}" if member.username else member.first_name)
                welcome_text = welcome_text.replace('{title}', update.effective_chat.title)
                await update.message.reply_text(welcome_text)

# Main function with Render.com compatibility
def main():
    # Initialize database
    init_db()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Warning system handlers
    application.add_handler(CommandHandler("warn", warn))
    application.add_handler(CommandHandler("dwarn", dwarn))
    application.add_handler(CommandHandler("swarn", swarn))
    application.add_handler(CommandHandler("warns", warns))
    application.add_handler(CommandHandler("rmwarn", rmwarn))
    application.add_handler(CommandHandler("resetwarn", resetwarn))
    application.add_handler(CommandHandler("resetallwarns", resetallwarns))
    application.add_handler(CommandHandler("warnings", warnings))
    application.add_handler(CommandHandler("warnmode", warnmode))
    application.add_handler(CommandHandler("warnlimit", warnlimit))
    application.add_handler(CommandHandler("warntime", warntime))
    
    # New admin commands
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("banlist", banlist_command))
    application.add_handler(CommandHandler("unban", unban_command))
    
    # Chat settings commands
    application.add_handler(CommandHandler("welcome", set_welcome))
    application.add_handler(CommandHandler("rulesset", set_rules))
    application.add_handler(CommandHandler("cmd", set_custom_command))
    application.add_handler(CommandHandler("delcmd", delete_custom_command_cmd))
    application.add_handler(CommandHandler("cmds", list_custom_commands))
    
    # User commands
    application.add_handler(CommandHandler("rules", show_rules))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_commands))
    application.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, auto_remove_links))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_members))
    
    # ✅ Render.com compatibility
    import os
    port = int(os.environ.get('PORT', 8443))
    
    # Start the bot
    print("🤖 Bot is starting...")
    print(f"🌐 Render.com Port: {port}")
    
    # Run with polling (Render.com compatible)
    application.run_polling()

if __name__ == '__main__':
    main()
