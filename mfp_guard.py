#!/usr/bin/env python3
"""
MyFundedPerps Drawdown + Per-Trade Guard

Monitors an account and:
- Closes ALL positions if daily loss limit is hit
- Closes ALL positions if daily profit target is hit (optional)
- Closes individual positions if they hit per-trade loss or profit targets

Requires a Read & Trade API key.

Usage:
  export FP_API_KEY="fp_live_..."
  python guard.py --account-id YOUR_ACCOUNT_ID --daily-loss 2.5 --per-trade-loss 1.0 --per-trade-profit 2.0
"""

import os
import sys
import time
import argparse
import requests
from datetime import datetime, timezone
from typing import Optional

BASE_URL = "https://developers.myfundedperpetuals.com"
POLL_INTERVAL = 5  # seconds

class Guard:
    def __init__(self, api_key: str, account_id: str,
                 daily_loss_pct: float,
                 daily_profit_pct: Optional[float] = None,
                 per_trade_loss_pct: Optional[float] = None,
                 per_trade_profit_pct: Optional[float] = None,
                 dry_run: bool = False):
        self.api_key = api_key
        self.account_id = account_id
        self.daily_loss_pct = daily_loss_pct
        self.daily_profit_pct = daily_profit_pct
        self.per_trade_loss_pct = per_trade_loss_pct
        self.per_trade_profit_pct = per_trade_profit_pct
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })
        self.starting_equity = None
        self.day_start = datetime.now(timezone.utc).date()

    def log(self, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}")

    def get_account(self) -> dict:
        r = self.session.get(f"{BASE_URL}/v1/accounts/{self.account_id}")
        r.raise_for_status()
        return r.json()["data"]

    def get_open_positions(self) -> list:
        r = self.session.get(f"{BASE_URL}/v1/positions", params={
            "account_id": self.account_id,
            "status": "open"
        })
        r.raise_for_status()
        return r.json().get("data", [])

    def get_quote(self, market_id: str, side: str, size: float) -> Optional[dict]:
        try:
            r = self.session.get(
                f"{BASE_URL}/v1/markets/{requests.utils.quote(market_id)}/quote",
                params={"side": side, "size": size}
            )
            if r.status_code == 200:
                return r.json().get("data")
        except Exception:
            pass
        return None

    def close_all_positions(self, reason: str):
        self.log(f"🚨 CLOSING ALL POSITIONS — {reason}")
        if self.dry_run:
            self.log("[DRY RUN] Would close all positions")
            return
        idem = f"guard-close-all-{int(time.time())}"
        r = self.session.post(
            f"{BASE_URL}/v1/accounts/{self.account_id}/close-all-positions",
            headers={"Idempotency-Key": idem}
        )
        if r.status_code in (200, 202):
            self.log(f"Close-all submitted: {r.status_code}")
        else:
            self.log(f"Close-all failed: {r.status_code} {r.text}")

    def close_position(self, position_id: str, reason: str):
        self.log(f"🚨 CLOSING POSITION {position_id[:8]}... — {reason}")
        if self.dry_run:
            self.log("[DRY RUN] Would close position")
            return
        r = self.session.post(
            f"{BASE_URL}/v1/positions/{position_id}/close",
            json={"type": "market"}  # full market close
        )
        if r.status_code in (200, 201, 202):
            self.log(f"Position close submitted")
        else:
            self.log(f"Position close failed: {r.status_code} {r.text}")

    def estimate_position_pnl_pct(self, pos: dict) -> Optional[float]:
        """Rough unrealized PnL % based on entry vs current quote."""
        market_id = pos.get("market_id")
        side = pos.get("side")
        size = float(pos.get("size", 0))
        entry = float(pos.get("entry_price", 0))
        if not market_id or size <= 0 or entry <= 0:
            return None

        # Opposite side for closing quote
        close_side = "sell" if side == "long" else "buy"
        quote = self.get_quote(market_id, close_side, size)
        if not quote:
            return None

        mark = float(quote.get("estimated_fill_price") or quote.get("mid") or 0)
        if mark <= 0:
            return None

        if side == "long":
            pnl_pct = (mark - entry) / entry * 100
        else:
            pnl_pct = (entry - mark) / entry * 100
        return pnl_pct

    def run(self):
        self.log("🛡️  MyFundedPerps Guard started")
        self.log(f"Account: {self.account_id}")
        self.log(f"Daily loss limit: {self.daily_loss_pct}%")
        if self.daily_profit_pct:
            self.log(f"Daily profit target: {self.daily_profit_pct}%")
        if self.per_trade_loss_pct:
            self.log(f"Per-trade loss: {self.per_trade_loss_pct}%")
        if self.per_trade_profit_pct:
            self.log(f"Per-trade profit: {self.per_trade_profit_pct}%")
        if self.dry_run:
            self.log("DRY RUN MODE — no orders will be sent")

        while True:
            try:
                # New day reset
                today = datetime.now(timezone.utc).date()
                if today != self.day_start:
                    self.day_start = today
                    self.starting_equity = None
                    self.log("New UTC day — resetting daily baseline")

                account = self.get_account()
                equity = float(account.get("equity") or account.get("balance") or 0)
                if equity <= 0:
                    self.log("Warning: equity is 0 or missing")
                    time.sleep(POLL_INTERVAL)
                    continue

                if self.starting_equity is None:
                    self.starting_equity = equity
                    self.log(f"Daily baseline equity set: ${equity:,.2f}")

                daily_pnl_pct = (equity - self.starting_equity) / self.starting_equity * 100
                self.log(f"Equity: ${equity:,.2f} | Daily PnL: {daily_pnl_pct:+.2f}%")

                # Daily limits
                if daily_pnl_pct <= -abs(self.daily_loss_pct):
                    self.close_all_positions(f"Daily loss limit hit ({daily_pnl_pct:.2f}%)")
                    self.log("Guard triggered. Exiting (or remove this line to keep running).")
                    return

                if self.daily_profit_pct and daily_pnl_pct >= abs(self.daily_profit_pct):
                    self.close_all_positions(f"Daily profit target hit ({daily_pnl_pct:.2f}%)")
                    self.log("Daily target locked. Exiting.")
                    return

                # Per-trade checks
                positions = self.get_open_positions()
                for pos in positions:
                    pnl_pct = self.estimate_position_pnl_pct(pos)
                    if pnl_pct is None:
                        continue
                    pos_id = pos["id"]
                    symbol = pos.get("symbol") or pos.get("market_id", "")
                    self.log(f"  Position {symbol}: {pnl_pct:+.2f}%")

                    if self.per_trade_loss_pct and pnl_pct <= -abs(self.per_trade_loss_pct):
                        self.close_position(pos_id, f"Per-trade loss {pnl_pct:.2f}%")
                    elif self.per_trade_profit_pct and pnl_pct >= abs(self.per_trade_profit_pct):
                        self.close_position(pos_id, f"Per-trade profit {pnl_pct:.2f}%")

            except KeyboardInterrupt:
                self.log("Stopped by user.")
                return
            except Exception as e:
                self.log(f"Error: {e}")

            time.sleep(POLL_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="MyFundedPerps Drawdown + Per-Trade Guard")
    parser.add_argument("--account-id", required=True, help="Challenge account ID")
    parser.add_argument("--daily-loss", type=float, default=2.5, help="Daily loss %% to flatten (default 2.5)")
    parser.add_argument("--daily-profit", type=float, default=None, help="Daily profit %% to lock (optional)")
    parser.add_argument("--per-trade-loss", type=float, default=None, help="Per-trade loss %% to close")
    parser.add_argument("--per-trade-profit", type=float, default=None, help="Per-trade profit %% to close")
    parser.add_argument("--dry-run", action="store_true", help="Log only, don't send orders")
    args = parser.parse_args()

    api_key = os.getenv("FP_API_KEY")
    if not api_key:
        print("Error: Set FP_API_KEY environment variable")
        sys.exit(1)

    guard = Guard(
        api_key=api_key,
        account_id=args.account_id,
        daily_loss_pct=args.daily_loss,
        daily_profit_pct=args.daily_profit,
        per_trade_loss_pct=args.per_trade_loss,
        per_trade_profit_pct=args.per_trade_profit,
        dry_run=args.dry_run
    )
    guard.run()


if __name__ == "__main__":
    main()
