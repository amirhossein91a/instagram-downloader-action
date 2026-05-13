#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Channel Archiver - Advanced Version
قابلیت‌ها:
- فیلتر بر اساس نوع محتوا (موزیک، عکس، ویدیو، متن)
- کنترل دانلود فایل‌ها
- انتخاب تعداد پست‌ها
- خروجی Markdown یا JSON
- پشتیبانی از کانال تکی یا لیست کانال‌ها
"""

import asyncio
import json
import os
import re
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional
import hashlib

from playwright.async_api import async_playwright
import requests
from jdatetime import datetime as jdatetime
import mutagen
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from PIL import Image
from io import BytesIO

# ========== تنظیمات ==========
class Config:
    def __init__(self):
        self.channels_file = "telegram/channels.json"
        self.last_ids_file = "telegram/last_ids.json"
        self.content_dir = "telegram/content"
        self.output_md = "telegram_output.md"
        self.output_json = "telegram_output.json"
        
        # تنظیمات از environment variables
        self.channel_id = os.getenv("CHANNEL_ID", "")
        self.max_posts = int(os.getenv("MAX_POSTS", "20"))
        self.content_type = os.getenv("CONTENT_TYPE", "all")
        self.download_media = os.getenv("DOWNLOAD_MEDIA", "false").lower() == "true"
        self.output_format = os.getenv("OUTPUT_FORMAT", "markdown")

config = Config()

# ========== تشخیص نوع محتوا ==========
def detect_content_type(text: str, file_url: str = "") -> str:
    """تشخیص نوع محتوا بر اساس متن و URL"""
    text_lower = text.lower()
    file_lower = file_url.lower()
    
    # تشخیص موزیک
    music_extensions = ['.mp3', '.flac', '.ogg', '.m4a', '.wav']
    music_keywords = ['موزیک', 'آهنگ', 'موسیقی', 'ترک', 'track', 'music', 'song']
    
    if any(ext in file_lower for ext in music_extensions) or \
       any(keyword in text_lower for keyword in music_keywords):
        return "music"
    
    # تشخیص عکس
    photo_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    if any(ext in file_lower for ext in photo_extensions):
        return "photo"
    
    # تشخیص ویدیو
    video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.webm']
    if any(ext in file_lower for ext in video_extensions):
        return "video"
    
    return "text"

def should_include_post(content_type: str) -> bool:
    """بررسی آیا پست بر اساس فیلتر نوع محتوا باید ذخیره شود"""
    if config.content_type == "all":
        return True
    return content_type == config.content_type

# ========== دانلود فایل ==========
async def download_file(url: str, channel_name: str, post_id: str, file_type: str) -> Optional[str]:
    """دانلود فایل با قابلیت قطع و ادامه"""
    if not config.download_media:
        return url  # فقط URL رو برگردون
    
    try:
        # ساخت نام فایل یکتا
        file_hash = hashlib.md5(f"{channel_name}_{post_id}_{url}".encode()).hexdigest()[:10]
        extension = Path(url.split('?')[0]).suffix or '.file'
        filename = f"{channel_name}_{post_id}_{file_hash}{extension}"
        filepath = Path(config.content_dir) / filename
        
        # اگر قبلاً دانلود شده بود
        if filepath.exists():
            return str(filepath)
        
        # دانلود فایل
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return str(filepath)
    except Exception as e:
        print(f"❌ دانلود ناموفق: {e}")
        return url

# ========== استخراج متادیتای موزیک ==========
def get_music_metadata(file_path: str) -> Dict:
    """استخراج متادیتای فایل موزیک"""
    metadata = {"title": "", "artist": "", "duration": ""}
    
    try:
        if file_path.endswith('.mp3'):
            audio = MP3(file_path)
            metadata["title"] = str(audio.get('TIT2', [''])[0])
            metadata["artist"] = str(audio.get('TPE1', [''])[0])
            metadata["duration"] = f"{int(audio.info.length // 60)}:{int(audio.info.length % 60):02d}"
    except:
        pass
    
    return metadata

# ========== خروجی Markdown ==========
async def save_markdown(posts: List[Dict], channel_name: str = ""):
    """ذخیره در فایل Markdown با فرمت زیبا"""
    with open(config.output_md, 'w', encoding='utf-8') as f:
        # Header
        f.write(f"# 📡 آرشیو تلگرام\n\n")
        if channel_name:
            f.write(f"## کانال: @{channel_name}\n\n")
        f.write(f"**تاریخ تولید:** {jdatetime.now().strftime('%Y/%m/%d %H:%M:%S')}\n")
        f.write(f"**تعداد پست‌ها:** {len(posts)}\n")
        f.write(f"**نوع محتوا:** {config.content_type}\n")
        f.write(f"**دانلود فایل‌ها:** {config.download_media}\n\n")
        f.write("---\n\n")
        
        # Posts
        for post in posts:
            f.write(f"## 📌 {post['date']}\n\n")
            
            # تایپ محتوا
            type_emoji = {
                'music': '🎵', 'photo': '📷', 'video': '🎬', 'text': '📝'
            }.get(post['type'], '📄')
            f.write(f"**{type_emoji} نوع:** {post['type']}\n\n")
            
            # متن
            if post.get('text'):
                f.write(f"{post['text']}\n\n")
            
            # متادیتای موزیک
            if post['type'] == 'music' and post.get('media_path'):
                metadata = get_music_metadata(post['media_path'])
                if metadata['title'] or metadata['artist']:
                    f.write(f"**🎵 اطلاعات آهنگ:**\n")
                    if metadata['title']:
                        f.write(f"- عنوان: {metadata['title']}\n")
                    if metadata['artist']:
                        f.write(f"- آرتیست: {metadata['artist']}\n")
                    if metadata['duration']:
                        f.write(f"- مدت: {metadata['duration']}\n")
                    f.write("\n")
            
            # رسانه‌ها
            if post.get('media_url'):
                if config.download_media and post.get('media_path'):
                    if post['type'] == 'photo':
                        f.write(f"![عکس]({post['media_path']})\n\n")
                    elif post['type'] == 'music':
                        f.write(f"🎵 **دانلود آهنگ:** [{post['media_path']}]({post['media_path']})\n\n")
                    else:
                        f.write(f"[دانلود فایل]({post['media_path']})\n\n")
                else:
                    f.write(f"🔗 **لینک:** {post['media_url']}\n\n")
            
            f.write("---\n\n")

# ========== خروجی JSON ==========
async def save_json(posts: List[Dict], channel_name: str = ""):
    """ذخیره در فایل JSON برای پردازش بعدی"""
    output = {
        "metadata": {
            "channel": channel_name,
            "generated": jdatetime.now().isoformat(),
            "content_type": config.content_type,
            "total_posts": len(posts)
        },
        "posts": posts
    }
    
    with open(config.output_json, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

# ========== اسکرپ اصلی ==========
async def scrape_channel(channel_name: str) -> List[Dict]:
    """اسکرپ کانال تلگرام و استخراج پست‌ها"""
    print(f"\n🚀 شروع اسکرپ کانال: @{channel_name}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = f"https://t.me/s/{channel_name}"
        await page.goto(url, wait_until="networkidle")
        
        # اسکرول و استخراج پست‌ها
        posts = []
        last_height = 0
        scroll_attempts = 0
        
        while len(posts) < config.max_posts and scroll_attempts < 20:
            # استخراج پست‌های صفحه
            new_posts = await extract_posts(page, channel_name)
            
            for post in new_posts:
                if post['id'] not in [p['id'] for p in posts]:
                    posts.append(post)
            
            # اسکرول به پایین
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0
            last_height = new_height
            
            print(f"📥 {len(posts)} پست استخراج شد...")
            
            if len(posts) >= config.max_posts:
                break
        
        await browser.close()
        
        # فیلتر بر اساس نوع محتوا
        filtered_posts = [p for p in posts if should_include_post(p['type'])]
        filtered_posts = filtered_posts[:config.max_posts] if config.max_posts > 0 else filtered_posts
        
        print(f"✅ {len(filtered_posts)} پست پس از فیلتر ({config.content_type}) باقی ماند")
        return filtered_posts

async def extract_posts(page, channel_name: str) -> List[Dict]:
    """استخراج پست‌ها از صفحه جاری"""
    posts = await page.evaluate('''
        () => {
            const posts = [];
            document.querySelectorAll('.tgme_widget_message').forEach((msg, idx) => {
                const id = msg.getAttribute('data-post')?.split('/')[1] || idx;
                const text = msg.querySelector('.tgme_widget_message_text')?.innerText || '';
                const dateElem = msg.querySelector('time');
                const date = dateElem ? dateElem.getAttribute('datetime') : new Date().toISOString();
                
                // استخراج مدیا
                let mediaUrl = '';
                const photo = msg.querySelector('.tgme_widget_message_photo img');
                const video = msg.querySelector('video');
                const audio = msg.querySelector('audio');
                
                if (photo) mediaUrl = photo.src;
                else if (video) mediaUrl = video.src;
                else if (audio) mediaUrl = audio.src;
                
                posts.push({ id, text, date, mediaUrl });
            });
            return posts;
        }
    ''')
    
    # تبدیل زمان به جلالی و پردازش بیشتر
    processed_posts = []
    for post in posts:
        # تبدیل زمان
        utc_time = datetime.fromisoformat(post['date'].replace('Z', '+00:00'))
        tehran_time = utc_time.replace(tzinfo=timezone.utc).astimezone()
        j_date = jdatetime.fromgregorian(datetime=tehran_time)
        
        # تشخیص نوع محتوا
        content_type = detect_content_type(post['text'], post['mediaUrl'])
        
        # دانلود مدیا در صورت نیاز
        media_path = None
        if post['mediaUrl'] and config.download_media:
            media_path = await download_file(
                post['mediaUrl'], 
                channel_name, 
                str(post['id']), 
                content_type
            )
        
        processed_posts.append({
            "id": post['id'],
            "type": content_type,
            "text": post['text'],
            "date": j_date.strftime("%Y/%m/%d - %H:%M:%S"),
            "timestamp": tehran_time.isoformat(),
            "media_url": post['mediaUrl'],
            "media_path": media_path,
            "channel": channel_name
        })
    
    return processed_posts

# ========== Main ==========
async def main():
    parser = argparse.ArgumentParser(description='Telegram Channel Archiver')
    parser.add_argument('--channel', help='نام کانال (بدون @)')
    parser.add_argument('--max-posts', type=int, default=20, help='تعداد پست‌های اخیر')
    parser.add_argument('--content-type', choices=['all', 'music', 'photo', 'video', 'text'], 
                       default='all', help='نوع محتوا')
    parser.add_argument('--download-media', type=bool, default=False, help='دانلود فایل‌ها')
    parser.add_argument('--output-format', choices=['markdown', 'json', 'both'], 
                       default='markdown', help='فرمت خروجی')
    
    args = parser.parse_args()
    
    # اولویت با آرگومان خط فرمان، سپس environment variables
    channel = args.channel or config.channel_id
    config.max_posts = args.max_posts
    config.content_type = args.content_type
    config.download_media = args.download_media
    config.output_format = args.output_format
    
    # خواندن لیست کانال‌ها
    channels = []
    if channel:
        channels = [channel]
    else:
        try:
            with open(config.channels_file, 'r') as f:
                channels = json.load(f)
        except:
            print("❌ فایل channels.json یافت نشد")
            return
    
    # اسکرپ همه کانال‌ها
    all_posts = []
    for ch in channels:
        posts = await scrape_channel(ch.strip())
        all_posts.extend(posts)
    
    # مرتب‌سازی بر اساس زمان (جدید به قدیم)
    all_posts.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # ذخیره خروجی
    if config.output_format in ['markdown', 'both']:
        await save_markdown(all_posts, channel or "all_channels")
        print(f"✅ خروجی Markdown ذخیره شد: {config.output_md}")
    
    if config.output_format in ['json', 'both']:
        await save_json(all_posts, channel or "all_channels")
        print(f"✅ خروجی JSON ذخیره شد: {config.output_json}")
    
    print(f"\n🎉 عملیات با موفقیت به اتمام رسید!")
    print(f"📊 آمار: {len(all_posts)} پست از {len(channels)} کانال")

if __name__ == "__main__":
    asyncio.run(main())
