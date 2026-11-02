"""Generate a short daily market summary with an LLM and store it in PostgreSQL.

Design: Python calculates every number; the LLM only turns those numbers into
a few readable sentences. The model never sees raw data it could misread, and
the prompt tells it to use only the numbers given.

Needs ANTHROPIC_API_KEY in .env. One summary costs roughly one US cent.
Run from the project root:  python src/summary.py
"""
import json
import logging
from datetime import date, timedelta

import anthropic
import pandas as pd
from dotenv import load_dotenv

import transform
from load import PROJECT_ROOT, get_connection
from logging_setup import setup_logging

logger = logging.getLogger("summary")

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You write a short daily summary of the German day-ahead \
electricity market for a data dashboard.

Rules:
- Use only the numbers in the data you are given. Do not add facts, causes or forecasts.
- 3 to 4 sentences of plain English text. No headings, no lists, no markdown.
- Mention the average price, the cheapest and most expensive hour, and the \
solar + wind share of consumption.
- Compare with the previous 7 days if that data is given.
- If there were hours with negative prices, mention how many.
- Round prices to whole euros (€/MWh) and shares to whole percent."""


def latest_complete_day(df: pd.DataFrame) -> date:
    """The newest day that has data from 00:00 to 23:00 (German time).

    Today is usually incomplete, because generation data arrives with a delay.
    """
    for day in sorted(df["date"].unique(), reverse=True):
        hours = df.loc[df["date"] == day, "hour"]
        # 23 hours on the spring clock-change day, 24 normally, 25 in autumn
        if len(hours) >= 23 and hours.min() == 0 and hours.max() == 23:
            return day
    raise ValueError("No complete day in the data")


def share_pct(rows: pd.DataFrame, column: str) -> float:
    """Energy-weighted share of consumption, in percent."""
    return round(float(rows[column].sum() / rows["load_mwh"].sum() * 100), 1)


def daily_stats(df: pd.DataFrame, day: date) -> dict:
    """All numbers the summary may use, for one day and the 7 days before it.

    Values are plain Python floats/ints/strings (not numpy), so they turn into JSON.
    """
    rows = df[df["date"] == day].copy()
    rows["wind_mwh"] = rows["wind_onshore_mwh"] + rows["wind_offshore_mwh"]
    local_times = rows.index.tz_convert(transform.LOCAL_TZ)
    cheapest = rows["price_eur_mwh"].idxmin()
    priciest = rows["price_eur_mwh"].idxmax()

    stats = {
        "date": day.isoformat(),
        "weekday": str(rows["weekday"].iloc[0]),
        "average_price_eur_mwh": round(float(rows["price_eur_mwh"].mean()), 2),
        "cheapest_hour": {
            "time": local_times[rows.index.get_loc(cheapest)].strftime("%H:%M"),
            "price_eur_mwh": round(float(rows.loc[cheapest, "price_eur_mwh"]), 2),
        },
        "most_expensive_hour": {
            "time": local_times[rows.index.get_loc(priciest)].strftime("%H:%M"),
            "price_eur_mwh": round(float(rows.loc[priciest, "price_eur_mwh"]), 2),
        },
        "hours_with_negative_price": int((rows["price_eur_mwh"] < 0).sum()),
        "solar_and_wind_share_of_consumption_pct": share_pct(rows, "renewable_mwh"),
        "solar_share_pct": share_pct(rows, "solar_mwh"),
        "wind_share_pct": share_pct(rows, "wind_mwh"),
    }

    previous = df[(df["date"] < day) & (df["date"] >= day - timedelta(days=7))]
    if not previous.empty:
        stats["previous_7_days"] = {
            "average_price_eur_mwh": round(float(previous["price_eur_mwh"].mean()), 2),
            "solar_and_wind_share_of_consumption_pct": share_pct(previous, "renewable_mwh"),
        }
    return stats


def generate_summary(stats: dict, client: anthropic.Anthropic | None = None) -> str:
    """Ask the LLM to write the summary text for the given numbers."""
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    # The SDK retries rate limits (429) and server errors (5xx) automatically
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "Data for the day:\n" + json.dumps(stats, indent=2),
        }],
        # A short factual text needs little reasoning, so keep the effort low
        output_config={"effort": "low"},
        # If the model declines a request, the API retries it on a fallback model
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined to write the summary")

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise RuntimeError(f"Empty response (stop reason: {response.stop_reason})")
    logger.info("LLM used %d input and %d output tokens",
                response.usage.input_tokens, response.usage.output_tokens)
    return text


def save_summary(day: date, text: str) -> None:
    """Upsert: generating the summary for the same day again replaces it."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO daily_summary (date, summary, model) VALUES (%s, %s, %s)
            ON CONFLICT (date) DO UPDATE
                SET summary = EXCLUDED.summary, model = EXCLUDED.model, created_at = now()
            """,
            (day, text, MODEL),
        )


def run(df: pd.DataFrame | None = None) -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    if df is None:
        df = pd.read_parquet(transform.OUTPUT_FILE)

    day = latest_complete_day(df)
    stats = daily_stats(df, day)
    logger.info("Writing summary for %s", day)

    text = generate_summary(stats)
    save_summary(day, text)
    logger.info("Summary saved: %s", text)
    return text


if __name__ == "__main__":
    setup_logging()
    run()
