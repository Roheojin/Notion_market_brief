# -*- coding: utf-8 -*-
"""텔레그램 알림 — 게시 성공/실패·휴장일 스킵을 알려 줍니다.

환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID가 없으면 아무것도 하지 않습니다.
알림 실패가 본 작업을 막지 않도록 예외를 밖으로 던지지 않습니다.
"""
import os


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    try:
        import requests

        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat_id, "text": text[:4000]},
                          timeout=15)
        return r.ok
    except Exception as e:
        print(f"  (텔레그램 알림 실패: {e})")
        return False
