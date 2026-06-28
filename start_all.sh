#!/bin/bash
# WARNING: Bots are managed by systemd
# Use: systemctl start/stop/restart <service_name>
# Do NOT run this script manually - use systemd instead

echo "⚠️  Bots are managed by systemd!"
echo ""
echo "To restart all: systemctl restart tradingbot nova_listener nova_signal_strategy nova_performance_tracker nova_news_bot nova_calendar_bot nova_sentiment_bot nova_backtest nova_earnings_bot nova_session_alerts nova_updates_bot nova_newsbot"
echo ""
echo "To check status: systemctl status nova_listener"
echo "To check logs: journalctl -u nova_listener -f"
