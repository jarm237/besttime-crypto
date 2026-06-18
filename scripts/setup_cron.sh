#!/bin/bash
# Install cron entry to run periodic_recalibration.py daily at 02:00
WORKDIR="/path/to/workspace"  # replace with actual path
CRON_LINE="0 2 * * * cd \"$WORKDIR\" && python3 scripts/periodic_recalibration.py >> \"$WORKDIR/logs/periodic_recalibration_cron.log\" 2>&1"
(crontab -l 2>/dev/null | grep -v -F "$CRON_LINE" ; echo "$CRON_LINE") | crontab -

echo "Cron entry installed (check with crontab -l)"
