# MyFundedPerps Drawdown + Per-Trade Guard

A simple but effective risk guard for MyFundedPerps accounts.

## What it does

- **Daily loss limit** — Flattens the entire account if equity drops X% from the day's starting equity
- **Daily profit target** (optional) — Flattens when you hit a daily profit goal
- **Per-trade loss limit** — Closes individual positions that hit a loss %
- **Per-trade profit target** — Closes individual positions that hit a profit %

Perfect for protecting challenge accounts from one bad day or one runaway trade.

## Setup

1. Create a **Read & Trade** API key at https://myfundedperpetuals.com/settings?section=api-keys
2. Install dependency:
   ```bash
   pip install requests
   ```
3. Set your key:
   ```bash
   export FP_API_KEY="fp_live_..."
   ```

## Usage

```bash
python mfp_guard.py \
  --account-id YOUR_ACCOUNT_ID \
  --daily-loss 2.5 \
  --per-trade-loss 1.0 \
  --per-trade-profit 2.0 \
  --daily-profit 5.0
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--account-id` | Your challenge account ID (required) | — |
| `--daily-loss` | Daily loss % to flatten everything | 2.5 |
| `--daily-profit` | Daily profit % to lock profits (optional) | off |
| `--per-trade-loss` | Close a trade if it loses this % | off |
| `--per-trade-profit` | Close a trade if it gains this % | off |
| `--dry-run` | Log only, don't send any orders | off |

## Example runs

Protect against a 3% daily loss + 1% per-trade stop:
```bash
python mfp_guard.py --account-id abc123 --daily-loss 3 --per-trade-loss 1
```

Aggressive scalper mode (lock 1.5% winners, cut 0.75% losers):
```bash
python mfp_guard.py --account-id abc123 --per-trade-loss 0.75 --per-trade-profit 1.5
```

## Notes

- Uses polling every 5 seconds (good enough for most traders)
- Daily baseline resets at UTC midnight
- Per-trade PnL is estimated via live quotes
- Built for the MyFundedPerps Builders Program
- Always test with `--dry-run` first on a sandbox account

## Disclaimer

This is a tool to help manage risk. It does not guarantee you won't breach rules. You are still responsible for your trading.
