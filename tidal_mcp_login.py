#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仅启动 Tidal OAuth handoff，供 Agent 用 Cursor MCP 浏览器完成登录。

用法：
  python tidal_mcp_login.py                    # 使用 tidal_email.txt 第一个账号
  python tidal_mcp_login.py user@example.com   # 指定邮箱（密码从 tidal_email.txt 查找）
"""
import sys
from pathlib import Path

import main as m

base = Path(__file__).parent
accounts = m.load_tidal_accounts()
if not accounts:
    print(f"未找到账号，请检查 {m.TIDAL_EMAIL_FILE}")
    sys.exit(1)

email = sys.argv[1] if len(sys.argv) > 1 else accounts[0]["email"]
acc = next((a for a in accounts if a["email"].lower() == email.lower()), None)
if not acc:
    print(f"未找到邮箱: {email}")
    sys.exit(1)

session = m.login_tidal_with_mcp_handoff(acc["email"], acc["password"])
if session:
    print(f"登录成功: {acc['email']}")
    sys.exit(0)
print("登录失败")
sys.exit(1)
