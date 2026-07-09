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
)

for service in "${SERVICES[@]}"; do
    status=$(systemctl is-active "$service")
    if [ "$status" != "active" ]; then
        msg="🚨 NOVA ALERT%0A%0AService DOWN: $service%0AStatus: $status%0ATime: $(date '+%d/%m/%Y %H:%M')"
        curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN_SIGNAL}/sendMessage?chat_id=${ADMIN_CHAT_ID}&text=$msg" > /dev/null
        systemctl restart "$service"
        sleep 3
        new_status=$(systemctl is-active "$service")
        msg2="🔄 NOVA ALERT%0A%0AService RESTARTED: $service%0ANew status: $new_status%0ATime: $(date '+%d/%m/%Y %H:%M')"
        curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN_SIGNAL}/sendMessage?chat_id=${ADMIN_CHAT_ID}&text=$msg2" > /dev/null
    fi
done

# Log rotation
LOG=/root/tradingbot/monitor.log
if [ -f "$LOG" ] && [ $(wc -l < "$LOG") -gt 1000 ]; then
    tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
