# Futures Risk Modeler

A local Streamlit dashboard for calculating futures position risk, reviewing trades, and tracking trading performance. The application includes predefined contract specifications for MES, MGC, MNQ, and M2K. It does not connect to a broker or execute orders.

## Features

| Area | Functionality |
| --- | --- |
| Risk calculator | Sizes a position using stop distance, contract tick value, commission, and assumed slippage |
| Pre-trade check | Flags daily-loss, position-size, drawdown-buffer, stop-distance, and risk/reward constraints |
| Trade journal | Adds and edits trades, with optional structured reviews and screenshots |
| Analytics | Calculates expectancy, win rate, profit factor, drawdown, and breakdowns by session or setup |
| Daily journal | Records pre-session plans and post-session reflections |
| Libraries | Maintains setup, mistake, and confluence categories |
| Excel companion | Generates a separate workbook for manual tracking with `build_excel.py` |

The analytics panel includes an **exploratory** one-sided t-test of mean R. Its result is not evidence of a reliable trading strategy unless the assumptions and trading process are independently examined; see [Limitations](#limitations).

## Requirements

- Python 3.10 or newer
- Dependencies listed in `requirements.txt`

Install and run from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Streamlit normally opens at `http://localhost:8501`.

### Try the example trades

The included CSV contains 15 sample trades in the earlier journal format. To try schema migration and the dashboard without entering your own trades:

```bash
cp data/sample_trades.csv data/trades.csv
streamlit run app.py
```

On startup, the application adds missing columns and backs up the original CSV. Existing field **values** are retained, including the literal text `None`. The source CSV may be rewritten in the updated column order.

The application stores records locally under `data/`. Do not commit personal journals, screenshot files, or backups; `.gitignore` excludes them.

## Tests

```bash
python -m unittest discover -s tests -v
```

The regression suite covers risk limits, position sizing, analytics calculations, tag serialization, validation, and preservation of older CSV values during migration.

## Project structure

```text
futures-risk-modeler/
├── app.py                     # Streamlit interface
├── modules/
│   ├── __init__.py
│   ├── analytics.py           # Performance summaries and exploratory inference
│   ├── position_sizer.py      # Contract sizing
│   ├── pre_trade_checker.py   # Risk-rule decisions
│   ├── prop_firm.py           # Simplified account-floor calculations
│   ├── journal.py             # Trade storage and editing
│   ├── daily_journal.py       # Session notes
│   ├── validation.py          # Trade input validation
│   ├── migration.py           # CSV schema updates
│   ├── backup_manager.py      # Backup retention
│   ├── media_manager.py       # Screenshot storage and metadata
│   ├── setup_manager.py       # Setup definitions
│   ├── library_manager.py     # Tag libraries
│   ├── tags.py                # Tag serialization
│   └── instruments.py         # Contract specifications
├── data/
│   └── sample_trades.csv      # Example data only
├── tests/
│   ├── test_risk_and_analytics.py
│   └── test_migration.py
├── build_excel.py             # Generates the workbook below
├── futures_risk_modeler.xlsx
├── example_config.json        # Illustrative account settings
├── requirements.txt
├── .gitignore
└── README.md
```

### Storage decisions

Trade and daily-journal records are stored as CSV. Setup libraries and image metadata are stored as JSON; screenshots are stored in per-trade directories. A trade is saved before its screenshots are attached, so a failed image upload does not erase the trade. Schema migrations back up the CSV before changing its columns. A standard edit creates at most one backup per day per file/reason; deletion and bulk edits trigger backups, with a 30-file retention limit.

This is a **local, single-user application**, not a multi-user database service. The calculation modules are plain Python and can be reused by another Python program. A Next.js application would need an HTTP service (for example FastAPI) or a separate TypeScript implementation; it cannot directly import Python modules as JavaScript.

## Account settings

The sidebar accepts starting balance, current balance, drawdown, daily loss limit, and related account assumptions. The JSON file contains **examples**, not verified current rules for the firms named there. The simplified models are:

- **Static:** floor = starting balance − maximum drawdown.
- **Trailing:** floor = supplied high-water mark − maximum drawdown.

Real prop-firm rules may use end-of-day or intraday trailing calculations, caps, liquidation thresholds, and separate daily rules. Verify the relevant account agreement rather than relying on the examples.

## Limitations

- The statistical test uses a Student t-distribution with `n − 1` degrees of freedom and a one-sided alternative (positive mean R). It assumes independent observations and does **not** correct for repeated testing, strategy selection, nonstationarity, or correlated trades. The 20-trade display threshold does not guarantee statistical power. A small p-value is not proof of a tradable edge.
- Position-risk calculations assume the entered stop distance, commission, and slippage. Gaps and extreme fills can cause losses greater than the estimate.
- The application does not implement backtesting, Monte Carlo simulation, predictive modeling, broker connectivity, or automated execution.
- Sidebar settings are not saved across browser reloads. Local image files will not persist if the application is deployed to a service with ephemeral storage without adding persistent storage.
- Only the predefined contracts are included. Validate contract specifications, exchange rules, and transaction costs before using another instrument.

The software is a research and journaling aid, not a guarantee that a trade or account satisfies an exchange's or provider's rules.
