#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Channel Archiver - Working Version
"""

import asyncio
import json
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional
import hashlib

from playwright.async_api import async_playwright
import requests
from jdatetime import datetime as jdatetime

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
    
    music_extensions = ['.mp3', '.flac', '.ogg', '.m4a', '.wav']
    music_keywords = ['موزیک', 'آهنگ', 'موسیقی', 'ترک', 'track', 'music', 'song']
    
    if any(ext in file_lower for ext in music_extensions) or \
       any(keyword in text_lower for keyword in music_keywords):
        return "music"
    
    photo_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    if any(ext in file_lower for ext in photo_extensions):
        return "photo"
    
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
        return url
    
    try:
        file_hash = hashlib.md5(f"{channel_name}_{post_id}_{url}".encode()).hexdigest()[:10]
        extension = Path(url.split('?')[0]).suffix or '.file'
        filename = f"{channel_name}_{post_id}_{file_hash}{extension}"
        filepath = Path(config.content_dir) / filename
        
        if filepath.exists():
            print(f"  ✅ قبلاً دانلود شده: {filename}")
            return str(filepath)
        
        print(f"  📥 دانلود: {filename}")
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print(f"  ✅ دانلود شد: {filename}")
        return str(filepath)
    except Exception as e:
        print(f"  ❌ دانلود ناموفق: {e}")
        return url

# ========== خروجی Markdown ==========
async def save_markdown(posts: List[Dict], channel_name: str = ""):
    """ذخیره در فایل Markdown با فرمت زیبا"""
    with open(config.output_md, 'w', encoding='utf-8') as f:
        f.write(f"# 📡 آرشیو تلگرام\n\n")
        if channel_name and channel_name != "all_channels":
            f.write(f"## کانال: @{channel_name}\n\n")
        f.write(f"**تاریخ تولید:** {jdatetime.now().strftime('%Y/%m/%d %H:%M:%S')}\n")
        f.write(f"**تعداد پست‌ها:** {len(posts)}\n")
        f.write(f"**نوع محتوا:** {config.content_type}\n")
        f.write(f"**دانلود فایل‌ها:** {config.download_media}\n\n")
        f.write("---\n\n")
        
        for post in posts:
            f.write(f"## 📌 {post['date']}\n\n")
            
            type_emoji = {
                'music': '🎵', 'photo': '📷', 'video': '🎬', 'text': '📝'
            }.get(post['type'], '📄')
            f.write(f"**{type_emoji} نوع:** {post['type']}\n\n")
            
            if post.get('text'):
                f.write(f"{post['text']}\n\n")
            
            if post.get('media_url'):
                if config.download_media and post.get('media_path') and post['media_path'] != post['media_url']:
                    if post['type'] == 'photo':
                        f.write(f"![عکس]({post['media_path']})\n\n")
                    elif post['type'] == 'music':
                        f.write(f"🎵 **دانلود آهنگ:** [فایل صوتی]({post['media_path']})\n\n")
                    else:
                        f.write(f"📎 **دانلود فایل:** [{post['media_path']}]({post['media_path']})\n\n")
                else:
                    f.write(f"🔗 **لینک:** {post['media_url']}\n\n")
            
            f.write("---\n\n")

# ========== خروجی JSON ==========
async def save_json(posts: List[Dict], channel_name: str = ""):
    """ذخیره در فایل JSON"""
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

# ========== استخراج پست‌ها ==========
async def extract_posts(page, channel_name: str) -> List[Dict]:
    """استخراج پست‌ها از صفحه جاری"""
    # اجرای جاوااسکریپت در مرورگر
    posts_data = await page.evaluate('''
        () => {
            const posts = [];
            const messageElements = document.querySelectorAll('.tgme_widget_message');
            
            for (const msg of messageElements) {
                // گرفتن ID پست
                const postLink = msg.querySelector('.tgme_widget_message_link');
                const postId = postLink ? postLink.getAttribute('href')?.split('/').pop() : null;
                
                // گرفتن متن
                const textElem = msg.querySelector('.tgme_widget_message_text');
                const text = textElem ? textElem.innerText : '';
                
                // گرفتن زمان
                const timeElem = msg.querySelector('time');
                const datetime = timeElem ? timeElem.getAttribute('datetime') : new Date().toISOString();
                
                // گرفتن مدیا
                let mediaUrl = '';
                const photoElem = msg.querySelector('.tgme_widget_message_photo img');
                const videoElem = msg.querySelector('video');
                const audioElem = msg.querySelector('audio');
                
                if (photoElem && photoElem.src) {
                    mediaUrl = photoElem.src;
                } else if (videoElem && videoElem.src) {
                    mediaUrl = videoElem.src;
                } else if (audioElem && audioElem.src) {
                    mediaUrl = audioElem.src;
                }
                
                posts.push({
                    id: postId || String(Date.now()),
                    text: text,
                    datetime: datetime,
                    mediaUrl: mediaUrl
                });
            }
            return posts;
        }
    ''')
    
    # پردازش پست‌ها
    processed_posts = []
    for post in posts_data:
        try:
            # تبدیل زمان
            utc_time = datetime.fromisoformat(post['datetime'].replace('Z', '+00:00'))
            tehran_time = utc_time.replace(tzinfo=timezone.utc).astimezone()
            j_date = jdatetime.fromgregorian(datetime=tehran_time)
            
            # تشخیص نوع محتوا
            content_type = detect_content_type(post['text'], post['mediaUrl'])
            
            # دانلود مدیا
            media_path = None
            if post['mediaUrl']:
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
        except Exception as e:
            print(f"  ⚠️ خطا در پردازش پست: {e}")
            continue
    
    return processed_posts

# ========== اسکرپ کانال ==========
async def scrape_channel(channel_name: str) -> List[Dict]:
    """اسکرپ کانال تلگرام"""
    print(f"\n🚀 شروع اسکرپ کانال: @{channel_name}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = f"https://t.me/s/{channel_name}"
        print(f"  🌐 باز کردن: {url}")
        await page.goto(url, wait_until="networkidle")
        
        # منتظر بارگذاری محتوا
        await page.wait_for_timeout(3000)
        
        # اسکرول و جمع‌آوری پست‌ها
        all_posts = []
        seen_ids = set()
        scroll_count = 0
        max_scroll = min(20, config.max_posts // 5 + 5) if config.max_posts > 0 else 20
        
        while len(all_posts) < config.max_posts and scroll_count < max_scroll:
            # استخراج پست‌های صفحه فعلی
            posts = await extract_posts(page, channel_name)
            
            # اضافه کردن پست‌های جدید
            new_posts = 0
            for post in posts:
                if post['id'] not in seen_ids:
                    seen_ids.add(post['id'])
                    all_posts.append(post)
                    new_posts += 1
            
            print(f"  📥 {len(all_posts)} پست جمع‌آوری شد (جدید: {new_posts})")
            
            if len(all_posts) >= config.max_posts:
                break
            
            # اسکرول به پایین
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            scroll_count += 1
        
        await browser.close()
        
        # فیلتر بر اساس نوع محتوا
        filtered_posts = [p for p in all_posts if should_include_post(p['type'])]
        
        if config.max_posts > 0:
            filtered_posts = filtered_posts[:config.max_posts]
        
        print(f"  ✅ {len(filtered_posts)} پست پس از فیلتر ({config.content_type})")
        return filtered_posts

# ========== Main ==========
async def main():
    parser = argparse.ArgumentParser(description='Telegram Channel Archiver')
    parser.add_argument('--channel', help='نام کانال (بدون @)')
    parser.add_argument('--max-posts', type=int, default=None, help='تعداد پست‌ها')
    parser.add_argument('--content-type', choices=['all', 'music', 'photo', 'video', 'text'], 
                       default=None, help='نوع محتوا')
    parser.add_argument('--download-media', type=str, default='false', help='دانلود فایل‌ها')
    parser.add_argument('--output-format', choices=['markdown', 'json', 'both'], 
                       default=None, help='فرمت خروجی')
    
    args = parser.parse_args()
    
    # اعمال آرگومان‌ها
    if args.channel:
        config.channel_id = args.channel
    if args.max_posts is not None:
        config.max_posts = args.max_posts
    if args.content_type:
        config.content_type = args.content_type
    if args.download_media == 'true':
        config.download_media = True
    if args.output_format:
        config.output_format = args.output_format
    
    # خواندن لیست کانال‌ها
    channels = []
    if config.channel_id:
        channels = [config.channel_id]
    else:
        try:
            with open(config.channels_file, 'r', encoding='utf-8') as f:
                channels = json.load(f)
            print(f"📋 لیست کانال‌ها: {channels}")
        except FileNotFoundError:
            print(f"❌ فایل {config.channels_file} یافت نشد")
            return
        except Exception as e:
            print(f"❌ خطا در خواندن channels.json: {e}")
            return
    
    if not channels:
        print("❌ هیچ کانالی برای اسکرپ وجود ندارد")
        return
    
    # اسکرپ همه کانال‌ها
    all_posts = []
    for ch in channels:
        posts = await scrape_channel(ch.strip())
        all_posts.extend(posts)
    
    if not all_posts:
        print("⚠️ هیچ پستی استخراج نشد")
        return
    
    # مرتب‌سازی
    all_posts.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # ذخیره خروجی
    output_name = config.channel_id if config.channel_id else "all_channels"
    
    if config.output_format in ['markdown', 'both']:
        await save_markdown(all_posts, output_name)
        print(f"✅ خروجی Markdown: {config.output_md}")
    
    if config.output_format in ['json', 'both']:
        await save_json(all_posts, output_name)
        print(f"✅ خروجی JSON: {config.output_json}")
    
    print(f"\n🎉 اتمام! {len(all_posts)} پست از {len(channels)} کانال")

if __name__ == "__main__":
    asyncio.run(main())
