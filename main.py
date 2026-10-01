import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import os
import re
import hashlib

print("=" * 50)
print("🚀 TELEGRAM FORWARD BOT (Full Album + Dedup)")
print("=" * 50)

# ---------------------------------------------------------------
# Credentials — environment variables ONLY. Set these in Railway's
# Variables tab. Do not hardcode secrets here or commit them to git.
# ---------------------------------------------------------------
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")

missing = [name for name, val in [("API_ID", API_ID), ("API_HASH", API_HASH), ("STRING_SESSION", STRING_SESSION)] if not val]
if missing:
    print(f"❌ Missing required environment variable(s): {', '.join(missing)}")
    print("Set them in Railway → Variables, then redeploy.")
    exit(1)

API_ID = int(API_ID)

source_channels = [
    "TikvahUniversity",
    "seledadotio",
    "abiyselol",
    "zena24now",
]
target_channel = "EBC_News_Official"
your_link = "https://t.me/EBC_News_Official"

print(f"\n📡 Monitoring {len(source_channels)} channels:")
for ch in source_channels:
    print(f"   - @{ch}")
print(f"🎯 Forwarding to: @{target_channel}")

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
processed = set()          # For deduplication of single messages
processed_albums = set()   # For deduplication of albums (based on caption hash)

def clean_text(text):
    if not text:
        return ""
    for ch in source_channels:
        esc = re.escape(ch)
        # @mentions
        text = re.sub(rf'@{esc}\b', '', text, flags=re.IGNORECASE)
        # t.me / telegram.me links, with or without protocol, with optional /message_id
        text = re.sub(rf'(https?://)?(t\.me|telegram\.me)/{esc}(/\d+)?\b', '', text, flags=re.IGNORECASE)
        # tg://resolve?domain=channel links
        text = re.sub(rf'tg://resolve\?domain={esc}\S*', '', text, flags=re.IGNORECASE)
    # Safety net: strip any remaining telegram links (any channel), same as before
    text = re.sub(r'(https?://)?(t\.me|telegram\.me)/\S+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'tg://resolve\?domain=\S+', '', text, flags=re.IGNORECASE)
    # Collapse leftover blank lines
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

def get_text_hash(text):
    """Generate a hash of the cleaned text for deduplication."""
    cleaned = clean_text(text)
    # Use first 200 chars as a fingerprint (good enough for dedup)
    fingerprint = cleaned[:200] if cleaned else ""
    return hashlib.md5(fingerprint.encode()).hexdigest()

def split_message(text, max_len=4000):
    if len(text) <= max_len:
        return [text]
    chunks = []
    for i in range(0, len(text), max_len):
        chunks.append(text[i:i+max_len])
    return chunks

def create_full_message(cleaned):
    intro = "የቴሌግራም ቻናላችን join በማድረግ ወቅታዊ መረጃዎችን በቀላሉ ይከታተሉ!"
    if cleaned:
        return f"{cleaned}\n\n{intro}\n\n{your_link}\n{your_link}\n{your_link}\nሰላም ለእናንተ!"
    else:
        return f"{intro}\n\n{your_link}\n{your_link}\n{your_link}\nሰላም ለእናንተ!"

async def send_long(channel, message):
    chunks = split_message(message)
    if not chunks:
        return
    print(f"📝 Splitting into {len(chunks)} parts")
    first = await client.send_message(channel, chunks[0], parse_mode=None)
    for i, chunk in enumerate(chunks[1:], start=2):
        try:
            await client.send_message(channel, chunk, reply_to=first.id, parse_mode=None)
            print(f"📤 Part {i}/{len(chunks)} sent")
            await asyncio.sleep(0.3)
        except Exception:
            await client.send_message(channel, chunk, parse_mode=None)
    return len(chunks)

def get_source_username(chat):
    """Safely pull a username off a resolved chat object, or None."""
    username = getattr(chat, "username", None)
    return username

# ========== ALBUM HANDLER – Forwards ALL photos in the album ==========
@client.on(events.Album)
async def album_handler(event):
    try:
        chat = await event.get_chat()
        username = get_source_username(chat)
        if not username or username not in source_channels:
            return
        grouped_id = event.grouped_id
        if not grouped_id:
            return

        # Collect all media and captions
        media_list = []
        caption_parts = []
        for msg in event.messages:
            if msg.media:
                media_list.append(msg.media)
            if msg.raw_text:
                caption_parts.append(msg.raw_text)

        if not media_list:
            print("⚠️ No media in album, skipping.")
            return

        # Combine captions and clean
        combined_caption = "\n".join(caption_parts) if caption_parts else ""
        cleaned = clean_text(combined_caption)

        # DEDUPLICATION: Check if we've seen this content before
        caption_hash = get_text_hash(combined_caption)
        album_key = f"{chat.id}_album_{caption_hash}"

        if album_key in processed_albums:
            print(f"⏩ Skipping duplicate album from @{username} (content already forwarded)")
            return

        # Mark as processed
        processed_albums.add(album_key)
        if len(processed_albums) > 1000:
            processed_albums.clear()

        # Also mark individual message IDs to prevent double processing
        for msg in event.messages:
            msg_key = f"{chat.id}_{msg.id}"
            processed.add(msg_key)

        full = create_full_message(cleaned)

        print(f"\n📸 Album detected from @{username} ({len(media_list)} media items)")
        print(f"   Caption length: {len(full)} characters")

        # Send ALL media as a single album with the caption attached
        await client.send_file(
            target_channel,
            media_list,
            caption=full,
            parse_mode=None,
            album=True  # This preserves the album grouping!
        )
        print(f"✅ Album forwarded: {len(media_list)} media items with caption")

    except Exception as e:
        # Catches everything, including Telethon TypeNotFoundError from
        # unrecognized TL objects — logs it and moves on without crashing.
        print(f"❌ Album handler error: {e}")
        import traceback
        traceback.print_exc()

# ========== SINGLE MESSAGE HANDLER ==========
@client.on(events.NewMessage)
async def handler(event):
    try:
        # Skip messages that belong to an album (handled above)
        if event.message.grouped_id is not None:
            return

        chat = await event.get_chat()
        username = get_source_username(chat)
        if not username or username not in source_channels:
            return

        msg_id = f"{chat.id}_{event.id}"
        if msg_id in processed:
            return

        print(f"\n📨 From @{username} (single message)")

        original = event.raw_text or ""
        cleaned = clean_text(original)

        # DEDUPLICATION: Check if we've seen this content before
        caption_hash = get_text_hash(original)
        if caption_hash:
            single_key = f"{chat.id}_single_{caption_hash}"
            if single_key in processed_albums:
                print(f"⏩ Skipping duplicate single message from @{username}")
                return
            processed_albums.add(single_key)
            if len(processed_albums) > 1000:
                processed_albums.clear()

        processed.add(msg_id)
        if len(processed) > 1000:
            processed.clear()

        full = create_full_message(cleaned)

        if event.message.media:
            print("📎 Single media – sending with caption")
            await client.send_file(
                target_channel,
                event.message.media,
                caption=full,
                parse_mode=None
            )
            print("✅ Single media sent with caption")
        else:
            # Text-only – split if needed
            parts = await send_long(target_channel, full)
            print(f"✅ Done – {parts} parts sent")

    except Exception as e:
        # Catches everything, including Telethon TypeNotFoundError from
        # unrecognized TL objects — logs it and moves on without crashing.
        print(f"❌ Error in handler: {e}")
        import traceback
        traceback.print_exc()

async def main():
    print("\n🔌 Connecting...")
    await client.start()
    me = await client.get_me()
    print(f"✅ Connected as @{me.username}")
    print("🤖 Bot running\n")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
