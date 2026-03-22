"""
메인 진입점 — Telegram Webhook + APScheduler
"""
import asyncio
import os
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters

from agents.graph import agent
from agents.state import AgentState
from config.settings import settings
from db.repository import init_db

log = structlog.get_logger()
PORT = int(os.environ.get("PORT", 8080))


async def run_scheduled_pipeline():
    log.info("scheduled_pipeline.start")
    state: AgentState = {
        "trigger": "schedule",
        "user_intent": None,
        "mail_items": [],
        "summaries": [],
        "telegram_messages": [],
        "fatal_error": None,
        "stats": {},
    }
    try:
        await agent.ainvoke(state)
        log.info("scheduled_pipeline.done")
    except Exception as e:
        log.error("scheduled_pipeline.failed", error=str(e))


async def handle_message(update: Update, context):
    text = update.message.text or ""
    log.info("telegram.received", text=text[:80])
    await update.message.reply_text("⏳ 처리 중...")
    state: AgentState = {
        "trigger": "telegram_command",
        "user_intent": {"action": "unknown", "params": {}, "raw_text": text},
        "mail_items": [],
        "summaries": [],
        "telegram_messages": [],
        "fatal_error": None,
        "stats": {},
    }
    try:
        await agent.ainvoke(state)
    except Exception as e:
        log.error("telegram_handler.failed", error=str(e))
        await update.message.reply_text(f"❌ 오류: {e}")


async def handle_help(update: Update, context):
    await update.message.reply_text(
        "📬 *뉴스레터 에이전트 도움말*\n\n"
        "`/summary` — 오늘 뉴스레터 요약\n"
        "`/search [검색어]` — 과거 아티클 검색\n"
        "`/skip [발신자]` — 특정 발신자 스킵\n"
        "`/resend [검색어]` — 과거 요약 재전송\n"
        "`/status` — 처리 현황\n\n"
        "자연어로도 가능합니다 😊",
        parse_mode="Markdown"
    )


async def post_init(application: Application):
    """Telegram 앱 초기화 완료 후 스케줄러 시작"""
    scheduler = AsyncIOScheduler(timezone=settings.schedule_timezone)
    scheduler.add_job(
        run_scheduled_pipeline,
        "cron",
        hour=settings.schedule_hour,
        minute=0,
        id="daily_newsletter",
        replace_existing=True,
    )
    scheduler.start()
    log.info("scheduler.started",
             hour=settings.schedule_hour,
             tz=settings.schedule_timezone)

    # DB 초기화
    await init_db()
    log.info("db.initialized")


def main():
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )

    for cmd in ["summary", "search", "skip", "settings", "resend", "status"]:
        app.add_handler(CommandHandler(cmd, handle_message))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    webhook_url = settings.telegram_webhook_url
    log.info("webhook.starting", url=webhook_url, port=PORT)

    # run_webhook은 자체 이벤트 루프를 관리 — asyncio.run() 없이 직접 호출
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=webhook_url,
        url_path="/webhook",
    )


if __name__ == "__main__":
    main()