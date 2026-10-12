#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析代理节点，生成 mihomo (clash-meta) 配置。
本地 mixed 监听 127.0.0.1:1080（socks5+http 通用），续期脚本无需改动。

支持两种输入（GOST_PROXY 环境变量）：
  1. ss:// 单节点链接 → 单节点配置
  2. http(s):// 订阅 URL → 下载订阅，提取全部台湾节点，生成多节点配置
     （workflow 会逐个切换节点测出口 IP，自动选中华电信住宅 IP）

用法：
  GOST_PROXY="ss://..." python3 parse_mihomo.py
  GOST_PROXY="https://...glados.yaml" python3 parse_mihomo.py
"""
import base64
import os
import sys
import urllib.parse
import urllib.request

try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

LOCAL_PORT = int(os.environ.get("LOCAL_PROXY_PORT", "1080"))


def b64decode(s: str) -> str:
    s = s.strip()
    if not s:
        return ""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    try:
        return base64.b64decode(s).decode("utf-8")
    except Exception:
        return ""


def parse_ss(uri: str) -> dict:
    """解析 ss:// 链接。"""
    body = uri[len("ss://"):]
    name = ""
    if "#" in body:
        body, name = body.split("#", 1)
    qs_str = ""
    if "?" in body:
        body, qs_str = body.split("?", 1)
    qs = urllib.parse.parse_qs(qs_str) if qs_str else {}
    if "@" not in body:
        raise SystemExit("❌ ss:// 链接缺少 @，无法解析 server")
    userinfo, hostport = body.rsplit("@", 1)
    hostport = hostport.rstrip("/")
    if ":" in hostport:
        server, port_str = hostport.rsplit(":", 1)
        port = int(port_str) if port_str.isdigit() else 443
    else:
        server, port = hostport, 443
    method, password = "", ""
    decoded = b64decode(userinfo)
    if ":" in decoded:
        method, password = decoded.split(":", 1)
    elif ":" in userinfo:
        method, password = userinfo.split(":", 1)
    if not method or not password:
        raise SystemExit(f"❌ 无法解析 ss:// userinfo: {userinfo}")
    plugin_opts = qs.get("plugin", [None])[0]
    return {"name": urllib.parse.unquote(name) or "ss-node",
            "server": server, "port": port,
            "method": method, "password": password,
            "plugin_opts": plugin_opts}


def plugin_to_mihomo(plugin_opts: str) -> dict:
    """把 plugin=obfs%3Btls%3Bhost%3Dxxx 转成 mihomo plugin 块。"""
    out = {}
    if not plugin_opts:
        return out
    parts = urllib.parse.unquote(plugin_opts).split(";")
    kind = parts[0] if parts else ""
    if kind == "obfs":
        out["plugin"] = "obfs"
        opts = {}
        for p in parts[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                opts[k] = v
        mode = opts.get("mode", "tls")
        host = opts.get("host", "")
        out["plugin-opts"] = {"mode": mode, "host": host} if host else {"mode": mode}
    return out


def build_ss_proxy(node: dict) -> dict:
    """把 parse_ss 结果转成 mihomo proxies 项。"""
    p = {"name": node["name"], "type": "ss",
         "server": node["server"], "port": node["port"],
         "cipher": node["method"], "password": node["password"]}
    p.update(plugin_to_mihomo(node.get("plugin_opts")))
    return p


def fetch_subscription(url: str) -> list:
    """下载 mihomo/clash 订阅，返回 proxies 列表。"""
    if not HAVE_YAML:
        raise SystemExit("❌ 订阅模式需要 PyYAML，请在 workflow 里 pip install pyyaml")
    req = urllib.request.Request(url, headers={"User-Agent": "clash-verge/v2.0.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    d = yaml.safe_load(data)
    proxies = d.get("proxies", [])
    if not proxies:
        raise SystemExit("❌ 订阅中未找到 proxies")
    return proxies


def filter_taiwan_nodes(proxies: list) -> list:
    """提取台湾相关节点（TW/Fast 开头）。"""
    tw = []
    for p in proxies:
        name = p.get("name", "").upper()
        if name.startswith("TW") or name.startswith("FAST"):
            tw.append(p)
    if not tw:
        # 没有台湾节点就用全部
        print("⚠️ 订阅中无 TW/Fast 开头的台湾节点，使用全部节点")
        return proxies
    return tw


def build_config(proxies: list) -> dict:
    """生成 mihomo 多节点配置：mode=global + proxy-groups 包含全部节点。"""
    names = [p["name"] for p in proxies]
    return {
        "mixed-port": LOCAL_PORT,
        "allow-lan": False,
        "mode": "global",
        "log-level": "error",
        "external-controller": "127.0.0.1:9090",
        "proxies": proxies,
        "proxy-groups": [
            {"name": "GLOBAL", "type": "select",
             "proxies": names + ["DIRECT"]},
        ],
    }


def main():
    proxy = os.environ.get("GOST_PROXY", "")
    if not proxy:
        raise SystemExit("❌ 未设置 GOST_PROXY")

    if proxy.startswith("http"):
        # 订阅 URL 模式
        print(f"📥 下载订阅: {proxy[:60]}...")
        all_proxies = fetch_subscription(proxy)
        tw_proxies = filter_taiwan_nodes(all_proxies)
        print(f"📋 订阅共 {len(all_proxies)} 个节点，提取台湾节点 {len(tw_proxies)} 个")
        for p in tw_proxies:
            print(f"   - {p['name']} ({p.get('server')}:{p.get('port')})")
        cfg = build_config(tw_proxies)
    elif proxy.startswith("ss://"):
        # 单节点模式
        node = parse_ss(proxy)
        cfg = build_config([build_ss_proxy(node)])
        print(f"📋 单节点: {node['name']} → {node['server']}:{node['port']}")
    else:
        raise SystemExit(f"❌ 不支持的 GOST_PROXY 格式: {proxy[:30]}...")

    if not HAVE_YAML:
        raise SystemExit("❌ 需要 PyYAML 来写配置，请 pip install pyyaml")

    with open("mihomo_config.yaml", "w", encoding="utf-8") as f:
        f.write("# generated by parse_mihomo.py\n")
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"✅ mihomo_config.yaml 已生成（{len(cfg['proxies'])} 个节点）")


if __name__ == "__main__":
    main()
