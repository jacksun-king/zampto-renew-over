#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 续期 v7 - Headed + xvfb + uc_gui_click_captcha
"""

import os, re, time, json, requests
from seleniumbase import SB

COOKIE_STR = (os.environ.get("ZAMTO_COOKIE") or "").strip()
SERVER_ID = os.environ.get("SERVER_ID") or "13420"
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY = os.environ.get("ALL_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
BASE_URL = "https://dash.zampto.net"
_shot_no = 0

def send_tg(msg, icon="ℹ️"):
    if not (TG_BOT_TOKEN and TG_CHAT_ID): return
    try:
        p = {"http": PROXY, "https": PROXY} if PROXY else None
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 8*3600))
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": f"{icon} Zampto 续期\n\n{msg}\n⏱️ {t}"}, timeout=15, proxies=p)
    except: pass

def shot(sb, tag):
    global _shot_no; _shot_no += 1
    try: sb.save_screenshot(f"{_shot_no:02d}_{tag}.png")
    except: pass

def log(msg):
    t = time.strftime("%H:%M:%S", time.gmtime(time.time() + 8*3600))
    print(f"[{t}] {msg}", flush=True)

def extract_ts(text):
    m = re.search(r'(\w{3}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s+(?:AM|PM)\s+\w+)', text)
    return m.group(1) if m else ""

def main():
    log("="*40)
    log("Zampto 续期 v7 (Headed + xvfb)")
    log("="*40)
    if not COOKIE_STR: log("❌ 无 Cookie"); send_tg("配置缺失","❌"); return

    with SB(uc=True, headed=True, incognito=False) as sb:
        log("🚀 浏览器启动 (headed + xvfb)")
        log(f"📌 代理: {PROXY or '直连'}")

        # 1. 打开首页设置 Cookie
        log("🍪 注入 Cookie...")
        try:
            sb.open(BASE_URL)
            time.sleep(3)
        except: pass

        # 注入 Cookie
        for pair in COOKIE_STR.split(";"):
            pair = pair.strip()
            if "=" not in pair: continue
            n, v = pair.split("=", 1); n, v = n.strip(), v.strip()
            for d in [".zampto.net", "dash.zampto.net"]:
                try:
                    sb.add_cookie({"name": n, "value": v, "domain": d, "path": "/"})
                    break
                except: pass

        # 2. 打开服务器页面
        url = f"{BASE_URL}/server?id={SERVER_ID}"
        log(f"🌐 打开: {url}")
        try:
            sb.open(url)
            time.sleep(8)
        except: pass

        shot(sb, "server_page")
        cur_url = sb.get_current_url()
        log(f"📌 URL: {cur_url}")

        # 用 JS 获取页面内容
        try:
            text = sb.execute_script("return document.body.innerText;") or ""
            log(f"📄 页面长度: {len(text)}")
            log(f"📄 页面内容(前200): {text[:200]}")
        except: pass

        # 如果被重定向到登录页，说明 Cookie 失效
        if "login" in cur_url.lower() or "auth" in cur_url.lower():
            log("❌ Cookie 失效，被重定向到登录页")
            send_tg("Cookie 已失效，请重新获取", "⚠️")
            return

        # 获取续期前时间戳
        body = sb.get_text("body") or ""
        last_ts = ""
        for l in body.split("\n"):
            if "last renewed" in l.lower() or "上次续期" in l:
                last_ts = extract_ts(l)
                log(f"📋 续期前: {l.strip()}")
        log(f"📋 时间戳: {last_ts or '未找到'}")

        # 如果 body 为空，尝试用 JS 获取
        if not body.strip():
            body = sb.execute_script("return document.body.innerText;") or ""
            for l in body.split("\n"):
                if "last renewed" in l.lower() or "上次续期" in l:
                    last_ts = extract_ts(l)
                    log(f"📋 (JS)续期前: {l.strip()}")

        # 查找续期按钮
        log("🔍 查找续期按钮...")
        btn = None
        for sel in ['button:contains("Renew Server")', 'button:contains("Renew")',
                    'button:contains("renew")', 'button:contains("Extend")']:
            try:
                for e in sb.find_elements(sel):
                    if "renew" in (e.text or "").lower():
                        btn = e; break
                if btn: break
            except: pass
        if not btn:
            for b in sb.find_elements("button"):
                if "renew" in (b.text or "").strip().lower():
                    btn = b; break

        if not btn:
            log("❌ 未找到续期按钮")
            shot(sb, "no_btn")
            # 页面截图
            try:
                html = sb.execute_script("return document.body.innerHTML;") or ""
                log(f"📄 HTML片段: {html[:500]}")
            except: pass
            send_tg("续期失败：未找到按钮", "❌")
            return

        # 点击续期
        log(f"🖱️ 点击 '{btn.text.strip()}'")
        try:
            sb.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(1)
            sb.execute_script("arguments[0].click()", btn)
            log("  ✅ 已点击")
        except Exception as e:
            log(f"❌ 点击失败: {e}")
            return

        # 等待续期/处理 Turnstile
        log("⏳ 等待续期...")
        renewed = False

        for i in range(30):  # 150 秒
            time.sleep(5)

            # 检查 Turnstile 弹窗
            try:
                txt = (sb.get_text("body") or "").lower()
                if not txt.strip():
                    txt = (sb.execute_script("return document.body.innerText;") or "").lower()
                if "security verification" in txt or "complete the security" in txt or "turnstile" in txt:
                    log(f"⏳ Turnstile (第{i+1}次)")
                    # uc_gui_click_captcha 在 xvfb 下可用
                    try:
                        sb.uc_gui_click_captcha()
                        log("  ✅ uc_gui_click_captcha 成功")
                        time.sleep(3)
                    except Exception as e:
                        log(f"  ⚠️ uc_gui_click_captcha 失败: {e}")
                    continue
            except: pass

            # 检查续期结果
            try:
                txt = sb.get_text("body") or ""
                if not txt.strip():
                    txt = sb.execute_script("return document.body.innerText;") or ""
                new_ts = ""
                for l in txt.split("\n"):
                    if "last renewed" in l.lower() or "上次续期" in l:
                        new_ts = extract_ts(l)
                        if new_ts and new_ts != last_ts:
                            log(f"📋 续期后: {l.strip()}")
                            log(f"🎉 续期成功! {new_ts}")
                            renewed = True
                        break
                if renewed: break
                if "just renewed" in txt.lower() or "successfully renewed" in txt.lower():
                    log("🎉 续期成功提示"); renewed = True; break
            except: pass

        if renewed:
            log("✅ 续期成功"); send_tg("续期成功 ✅", "✅")
        else:
            log("❌ 续期失败")
            shot(sb, "fail")
            send_tg("续期失败，请检查面板", "❌")

if __name__ == "__main__":
    main()