#!/usr/bin/env python3
import os
import sys
import argparse
import logging
from pathlib import Path

# Add project root to sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Force stdout/stderr to UTF-8 to support Windows console logging
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from btc_scraper.collectors.parsebot_farside_collector import ParsebotFarsideETFCollector

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("fetch_parsebot_etf_jobs")

def fetch_parsebot_etf_recent_job(dry_run=False):
    logger.info("Starting job: fetch_parsebot_etf_recent")
    symbols = [s.strip() for s in os.getenv("SUPPORTED_ETF_RECENT_SYMBOLS", "BTC,ETH,SOL").split(",") if s.strip()]
    
    if dry_run:
        logger.info(f"[DRY-RUN] Would fetch recent ETF flows for symbols: {symbols}")
        return
        
    collector = ParsebotFarsideETFCollector()
    for symbol in symbols:
        logger.info(f"Fetching recent ETF flow for {symbol}...")
        result = collector.fetch(symbol=symbol, mode="recent")
        logger.info(f"Fetch completed for {symbol}. Status: {result.get('status')}, Error: {result.get('error')}")

def fetch_parsebot_etf_all_job(dry_run=False):
    logger.info("Starting job: fetch_parsebot_etf_all")
    symbols = [s.strip() for s in os.getenv("SUPPORTED_ETF_ALL_SYMBOLS", "BTC,ETH").split(",") if s.strip()]
    
    if dry_run:
        logger.info(f"[DRY-RUN] Would fetch all historical ETF flows for symbols: {symbols}")
        return
        
    collector = ParsebotFarsideETFCollector()
    for symbol in symbols:
        logger.info(f"Fetching all historical ETF flows for {symbol}...")
        result = collector.fetch(symbol=symbol, mode="all")
        logger.info(f"Fetch completed for {symbol}. Status: {result.get('status')}, Error: {result.get('error')}")

def fetch_parsebot_fund_info_job(dry_run=False):
    logger.info("Starting job: fetch_parsebot_fund_info")
    
    if dry_run:
        logger.info("[DRY-RUN] Would fetch Farside fund info")
        return
        
    collector = ParsebotFarsideETFCollector()
    logger.info("Fetching Farside fund info...")
    result = collector.fetch(symbol="FUND", mode="info")
    logger.info(f"Fetch completed for FUND. Status: {result.get('status')}, Error: {result.get('error')}")

def main():
    parser = argparse.ArgumentParser(description="Run Parse.bot ETF Flow collector jobs")
    parser.add_argument(
        "--job",
        choices=["recent", "all", "fund", "run-all"],
        required=True,
        help="The specific scheduled job to execute"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without calling external API"
    )
    
    args = parser.parse_args()
    
    # Load environment variables if .env file exists
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
        
    if args.job == "recent":
        fetch_parsebot_etf_recent_job(dry_run=args.dry_run)
    elif args.job == "all":
        fetch_parsebot_etf_all_job(dry_run=args.dry_run)
    elif args.job == "fund":
        fetch_parsebot_fund_info_job(dry_run=args.dry_run)
    elif args.job == "run-all":
        fetch_parsebot_etf_recent_job(dry_run=args.dry_run)
        fetch_parsebot_etf_all_job(dry_run=args.dry_run)
        fetch_parsebot_fund_info_job(dry_run=args.dry_run)

if __name__ == "__main__":
    main()
