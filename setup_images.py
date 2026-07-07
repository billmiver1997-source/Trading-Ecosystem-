"""Run once on the server to download bot images: python3 setup_images.py"""
import os
import requests

IMAGES_DIR = "/root/tradingbot/images"
os.makedirs(IMAGES_DIR, exist_ok=True)

IMAGES = {
    # Channel / editorial
    "news.jpg":       "https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=1200&q=85&auto=format&fit=crop",
    "sentiment.jpg":  "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=1200&q=85&auto=format&fit=crop",
    "tips.jpg":       "https://images.unsplash.com/photo-1434626881859-194d67b2b86f?w=1200&q=85&auto=format&fit=crop",
    "psychology.jpg": "https://images.unsplash.com/photo-1489659831163-682b5af42225?w=1200&q=85&auto=format&fit=crop",
    "weekly.jpg":     "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=1200&q=85&auto=format&fit=crop",
    # Signal opening — 5 rotating images
    "signals.jpg":    "https://images.unsplash.com/photo-1642790106117-e829e14a795f?w=1200&q=85&auto=format&fit=crop",
    "signals_2.jpg":  "https://images.unsplash.com/photo-1611532736597-de2d4265fba3?w=1200&q=85&auto=format&fit=crop",
    "signals_3.jpg":  "https://images.unsplash.com/photo-1535320903710-d993d3d77d29?w=1200&q=85&auto=format&fit=crop",
    "signals_4.jpg":  "https://images.unsplash.com/photo-1569025690938-a00729c9e1f9?w=1200&q=85&auto=format&fit=crop",
    "signals_5.jpg":  "https://images.unsplash.com/photo-1559526324-593bc073d938?w=1200&q=85&auto=format&fit=crop",
    # Trade results
    "win.jpg":        "https://images.unsplash.com/photo-1579621970795-87facc2f976d?w=1200&q=85&auto=format&fit=crop",
    "loss.jpg":       "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?w=1200&q=85&auto=format&fit=crop",
    "be.jpg":         "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=1200&q=85&auto=format&fit=crop",
}

headers = {"User-Agent": "Mozilla/5.0"}

for filename, url in IMAGES.items():
    path = os.path.join(IMAGES_DIR, filename)
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        print(f"✓ {filename} already exists ({os.path.getsize(path)//1024}KB)")
        continue
    try:
        r = requests.get(url, timeout=30, headers=headers)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        print(f"✓ Downloaded {filename} ({len(r.content)//1024}KB)")
    except Exception as e:
        print(f"✗ Failed {filename}: {e}")

print("\nDone! Images saved to", IMAGES_DIR)
