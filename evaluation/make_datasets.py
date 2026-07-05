"""Generate the 15 evaluation datasets plus expected ground-truth values.

Ground truth (expected/*.json) holds aggregates computed directly with pandas;
run_eval.py later checks that every expected number can be found in the
agent's results JSON / report.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATASETS = HERE / "datasets"
EXPECTED = HERE / "expected"
rng = np.random.default_rng(42)


def save_expected(name: str, df: pd.DataFrame, numeric_cols: list[str] | None = None) -> None:
    numeric_cols = numeric_cols or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    expected = {"n_rows": int(len(df)), "aggregates": {}}
    for c in numeric_cols:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(s):
            expected["aggregates"][c] = {
                "sum": round(float(s.sum()), 2),
                "mean": round(float(s.mean()), 2),
                "min": round(float(s.min()), 2),
                "max": round(float(s.max()), 2),
            }
    (EXPECTED / f"{name}.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False))


def sales(n=730):
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    trend = np.linspace(1000, 1800, n)
    season = 200 * np.sin(2 * np.pi * dates.dayofyear / 365.25)
    revenue = (trend + season + rng.normal(0, 80, n)).round(2)
    return pd.DataFrame({
        "date": dates,
        "region": rng.choice(["North", "South", "East", "West"], n),
        "product": rng.choice(["Alpha", "Beta", "Gamma", "Delta", "Epsilon"], n),
        "units": rng.integers(1, 60, n),
        "revenue": revenue,
    })


def main() -> None:
    DATASETS.mkdir(exist_ok=True)
    EXPECTED.mkdir(exist_ok=True)

    # 1. clean daily sales with trend + seasonality (forecastable)
    df = sales()
    df.to_csv(DATASETS / "01_clean_sales.csv", index=False)
    save_expected("01_clean_sales", df)

    # 2. messy CSV: windows-1256 encoding, mixed-case categories, blanks
    m = sales(200)
    m["region"] = m["region"].str.lower()
    m.loc[rng.choice(200, 30, replace=False), "revenue"] = np.nan
    m["note"] = "ملاحظة"
    (DATASETS / "02_messy_cp1256.csv").write_bytes(m.to_csv(index=False).encode("windows-1256"))
    save_expected("02_messy_cp1256", m)

    # 3. Arabic column names
    a = pd.DataFrame({
        "التاريخ": pd.date_range("2024-01-01", periods=120, freq="D"),
        "المدينة": rng.choice(["عمان", "إربد", "الزرقاء"], 120),
        "المبيعات": rng.integers(100, 900, 120),
    })
    a.to_csv(DATASETS / "03_arabic_columns.csv", index=False, encoding="utf-8-sig")
    save_expected("03_arabic_columns", a)

    # 4. large file 120K rows
    big = sales(730).sample(120_000, replace=True, random_state=1).reset_index(drop=True)
    big.to_csv(DATASETS / "04_large_120k.csv", index=False)
    save_expected("04_large_120k", big)

    # 5. no time column
    nt = pd.DataFrame({
        "department": rng.choice(["HR", "IT", "Sales", "Ops"], 300),
        "headcount": rng.integers(1, 40, 300),
        "budget": (rng.random(300) * 90_000 + 10_000).round(2),
    })
    nt.to_csv(DATASETS / "05_no_time_column.csv", index=False)
    save_expected("05_no_time_column", nt)

    # 6. single column
    pd.DataFrame({"value": rng.normal(50, 12, 400).round(3)}).to_csv(
        DATASETS / "06_single_column.csv", index=False)
    save_expected("06_single_column", pd.read_csv(DATASETS / "06_single_column.csv"))

    # 7. heavy duplicates (40%)
    d = sales(300)
    dup = pd.concat([d, d.sample(200, random_state=2)], ignore_index=True)
    dup.to_csv(DATASETS / "07_heavy_duplicates.csv", index=False)
    save_expected("07_heavy_duplicates", dup)

    # 8. mixed date formats in one column
    base = sales(150).drop(columns="date")
    fmts = ["%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y", "%d %b %Y"]
    dates = pd.date_range("2024-01-01", periods=150, freq="D")
    base.insert(0, "order_date", [d.strftime(fmts[i % 4]) for i, d in enumerate(dates)])
    base.to_csv(DATASETS / "08_mixed_dates.csv", index=False)
    save_expected("08_mixed_dates", base)

    # 9. financial data
    fin = pd.DataFrame({
        "month": pd.date_range("2021-01-01", periods=48, freq="MS"),
        "revenue": (rng.random(48) * 400_000 + 600_000).round(2),
        "cogs": (rng.random(48) * 250_000 + 300_000).round(2),
        "opex": (rng.random(48) * 120_000 + 150_000).round(2),
    })
    fin["net_income"] = (fin.revenue - fin.cogs - fin.opex).round(2)
    fin.to_csv(DATASETS / "09_financial.csv", index=False)
    save_expected("09_financial", fin)

    # 10. HR data
    hr = pd.DataFrame({
        "employee_id": range(1, 501),
        "department": rng.choice(["Engineering", "Sales", "Support", "Finance"], 500),
        "tenure_years": (rng.random(500) * 12).round(1),
        "salary": (rng.random(500) * 60_000 + 30_000).round(0),
        "attrition": rng.choice(["yes", "no"], 500, p=[0.18, 0.82]),
    })
    hr.to_csv(DATASETS / "10_hr.csv", index=False)
    save_expected("10_hr", hr, ["tenure_years", "salary"])

    # 11. inventory
    inv = pd.DataFrame({
        "sku": [f"SKU-{i:04d}" for i in range(400)],
        "warehouse": rng.choice(["A", "B", "C"], 400),
        "on_hand": rng.integers(0, 500, 400),
        "reorder_point": rng.integers(20, 120, 400),
        "unit_cost": (rng.random(400) * 90 + 5).round(2),
    })
    inv.to_csv(DATASETS / "11_inventory.csv", index=False)
    save_expected("11_inventory", inv, ["on_hand", "reorder_point", "unit_cost"])

    # 12. customer data with missing values
    cust = pd.DataFrame({
        "customer_id": range(1, 1001),
        "country": rng.choice(["JO", "SA", "AE", "EG", None], 1000, p=[0.3, 0.25, 0.2, 0.2, 0.05]),
        "lifetime_value": (rng.random(1000) * 4000).round(2),
        "orders": rng.integers(1, 50, 1000),
    })
    cust.loc[rng.choice(1000, 80, replace=False), "lifetime_value"] = np.nan
    cust.to_csv(DATASETS / "12_customers.csv", index=False)
    save_expected("12_customers", cust, ["lifetime_value", "orders"])

    # 13. outlier-heavy sensor data
    sens = pd.DataFrame({
        "timestamp": pd.date_range("2024-03-01", periods=500, freq="h"),
        "temperature": rng.normal(22, 1.5, 500).round(2),
    })
    sens.loc[rng.choice(500, 12, replace=False), "temperature"] = rng.choice([95.0, -40.0], 12)
    sens.to_csv(DATASETS / "13_outliers.csv", index=False)
    save_expected("13_outliers", sens, ["temperature"])

    # 14. minimal data (<50 rows)
    mini = sales(30)
    mini.to_csv(DATASETS / "14_minimal.csv", index=False)
    save_expected("14_minimal", mini)

    # 15. multi-sheet XLSX
    with pd.ExcelWriter(DATASETS / "15_multisheet.xlsx") as writer:
        s = sales(180)
        s.to_excel(writer, sheet_name="sales", index=False)
        pd.DataFrame({"k": ["a"], "v": [1]}).to_excel(writer, sheet_name="lookup", index=False)
    save_expected("15_multisheet", s)

    print(f"wrote {len(list(DATASETS.iterdir()))} datasets, "
          f"{len(list(EXPECTED.iterdir()))} expected files")


if __name__ == "__main__":
    main()
