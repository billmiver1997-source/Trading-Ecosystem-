#!/bin/bash
source /root/tradingbot/.env

SERVICES=(
    "tradingbot"
    "nova_listener"
    "nova_signal_strategy"
    "nova_performance_tracker"
    "nova_news_bot"
    "nova_calendar_bot"
    "nova_sentiment_bot"
    "nova_backtest"
    "nova_earnings_bot"
    "nova_session_alerts"
    "nova_updates_bot"
    "nova_newsbot"
    "nova_volatility_alert"
    "nova_correlation_bot"
    "nova_watchlist_scanner"
    "nova_weekly_digest"
    "nova_calendar_alerts"
    "nova_daily_poll"
    "nova_market_regime"
)

for service in "${SERVICES[@]}"; do
    status=$(systemctl is-active "$service")
    if [ "$status" != "active" ]; then
        _date_str=$(date '+%d/%m/%Y %H:%M')
        # Use POST with a JSON body so emoji and special characters are correctly encoded
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN_SIGNAL}/sendMessage" \
            -H "Content-Type: application/json" \
            -d "{\"chat_id\":\"${ADMIN_CHAT_ID}\",\"text\":\"🚨 NOVA ALERT\n\nService DOWN: ${service}\nStatus: ${status}\nTime: ${_date_str}\"}" > /dev/null
        systemctl restart "$service"
        sleep 3
        new_status=$(systemctl is-active "$service")
        _date_str=$(date '+%d/%m/%Y %H:%M')
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN_SIGNAL}/sendMessage" \
            -H "Content-Type: application/json" \
            -d "{\"chat_id\":\"${ADMIN_CHAT_ID}\",\"text\":\"🔄 NOVA ALERT\n\nService RESTARTED: ${service}\nNew status: ${new_status}\nTime: ${_date_str}\"}" > /dev/null
    fi
done

# Log rotation
LOG=/root/tradingbot/monitor.log
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 1000 ]; then
    tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
