"""On-demand ML prediction prompt: train, evaluate, and forecast future values."""

PREDICT_PROMPT = """The user wants to PREDICT FUTURE VALUES using machine learning.

Request (the value "auto" means you decide from the data):
- target column: {target}
- horizon (number of future periods to predict): {horizon}
- frequency / period hint: {frequency}
- preferred model: {model}  (one of RandomForest / GradientBoosting / Linear, or "auto")

<data_profile>
{profile_json}
</data_profile>

Call execute_python with scikit-learn code that builds a proper, honestly-evaluated model from
DATA_DIR + '/cleaned.parquet'. Be flexible to whatever this dataset is:

1. Choose the target: use the requested column if it exists; otherwise pick the most relevant
   numeric column. Decide the MODE honestly:
   - TIME SERIES (a genuine date/time column exists): sort by it and forecast the next {horizon}
     periods from lag features.
   - TABULAR (no time column): predict the target from the OTHER columns. There are no future
     periods here, so report held-out accuracy and predicted-vs-actual instead of fake dates.
   Never coerce a numeric id/measure column into dates.
2. Engineer features: time series -> lag / rolling-mean / calendar features; tabular -> the other
   columns (one-hot encode low-cardinality categoricals, impute numerics).
3. Hold out 20% for evaluation (time series: the most recent slice; tabular: a random split with
   random_state=42). Train RandomForest + GradientBoosting + a Linear baseline; evaluate each.
4. SAVE the accuracy of the chosen model with save_value("prediction_metrics", {{
     "model": "<winning model>", "mape": <holdout MAPE %>, "rmse": <n>, "mae": <n>, "r2": <n>,
     "train_rows": <n>, "test_rows": <n>, "horizon": {horizon}, "target": "<column>",
     "is_time_series": <true|false>, "mode": "forecast|regression",
     "features_used": [<top features>], "feature_importances": {{"<feature>": <0..1 share>}} }}).
   Round numbers (mape/r2 to 2 dp). If a preferred model other than "auto" is given, use it.
5. SAVE the result table with save_table("prediction_values", df):
   - forecast mode: columns period (future date), predicted, lower, upper;
   - regression mode: columns actual, predicted (on the held-out rows).
6. SAVE a chart with save_chart("prediction_chart", fig, title=...): forecast mode -> history +
   forecast line + interval band; regression mode -> predicted vs actual on the holdout.

Then reply in {language_name}: the mode and why, the chosen model and its accuracy (cite mape/r2),
and the headline result. Use ONLY numbers from the execution results. If the data cannot support
either mode (too few rows, no usable target), say so honestly and explain what is needed."""


# Deterministic ML forecaster the agent runs if the model's own attempt doesn't
# produce the expected saves. Two honest modes: time-series forecast when a real
# date column exists, otherwise tabular regression (target from other features).
# Placeholders __TARGET__/__MODEL__/__HORIZON__ are substituted via replace().
FALLBACK_PREDICT_CODE = '''
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

df = pd.read_parquet(DATA_DIR + "/cleaned.parquet")
REQ_TARGET = __TARGET__
REQ_MODEL = __MODEL__
HORIZON = int(__HORIZON__)


def _mape(a, p):
    a = np.asarray(a, float); p = np.asarray(p, float)
    d = np.where(a == 0, np.nan, a)
    v = float(np.nanmean(np.abs((a - p) / d)) * 100)
    return v if np.isfinite(v) else 1e9


def _candidates():
    c = {"RandomForest": RandomForestRegressor(n_estimators=200, random_state=42),
         "GradientBoosting": GradientBoostingRegressor(random_state=42),
         "Linear": LinearRegression()}
    if REQ_MODEL and str(REQ_MODEL).lower() != "auto":
        c = {k: v for k, v in c.items() if k.lower() == str(REQ_MODEL).lower()} or c
    return c


def _fit_best(Xtr, ytr, Xte, yte):
    best, best_mape, stats, best_p = None, 1e18, {}, None
    for name, mdl in _candidates().items():
        mdl.fit(Xtr, ytr)
        p = mdl.predict(Xte)
        mp = _mape(yte, p)
        if mp < best_mape:
            best, best_mape, best_p = name, mp, p
            stats = {"rmse": float(np.sqrt(mean_squared_error(yte, p))),
                     "mae": float(mean_absolute_error(yte, p)), "r2": float(r2_score(yte, p))}
    return best, best_mape, stats, best_p


def _importances(model, names):
    if hasattr(model, "feature_importances_"):
        imp = np.asarray(model.feature_importances_, float)
    elif hasattr(model, "coef_"):
        imp = np.abs(np.asarray(model.coef_, float).ravel())
    else:
        imp = np.ones(len(names))
    imp = imp / (imp.sum() or 1.0)
    pairs = sorted(zip(names, imp), key=lambda kv: -kv[1])[:8]
    return {k: round(float(v), 3) for k, v in pairs}


# genuine datetime column only: existing datetime dtype, or a NON-numeric
# (string/object) column that parses as dates spanning >1 year. Numeric columns
# are never coerced to dates. pandas helpers are used (np.issubdtype raises on
# extension dtypes like StringDtype).
dt_col = None
for c in df.columns:
    if pd.api.types.is_datetime64_any_dtype(df[c]):
        dt_col = c
        break
if dt_col is None:
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            parsed = pd.to_datetime(df[c], errors="coerce")
            if parsed.notna().mean() > 0.8 and parsed.dt.year.nunique() > 1:
                df[c] = parsed
                dt_col = c
                break

num_cols = [c for c in df.select_dtypes("number").columns if c != dt_col]
if REQ_TARGET and REQ_TARGET in num_cols:
    target = REQ_TARGET
elif num_cols:
    target = max(num_cols, key=lambda c: float(np.nanvar(df[c].astype(float))) if df[c].notna().any() else 0.0)
else:
    target = None

if target is None:
    save_value("prediction_metrics", {"error": "no numeric column available to predict"})

elif dt_col is not None:
    # ---- TIME SERIES: forecast future periods from lag features ----
    ser = df[[dt_col, target]].dropna().groupby(dt_col)[target].sum().sort_index()
    y = ser.values.astype(float); idx = list(ser.index); n = len(y); LAGS = 3
    if n < LAGS + 10:
        save_value("prediction_metrics", {"error": "not enough time points for a forecast", "rows": int(n)})
    else:
        X = np.column_stack([np.roll(y, k) for k in range(1, LAGS + 1)])[LAGS:]
        yt = y[LAGS:]
        split = max(1, int(len(yt) * 0.8))
        best, best_mape, stats, best_p = _fit_best(X[:split], yt[:split], X[split:], yt[split:])
        model = _candidates()[best]; model.fit(X, yt)
        ci = 1.96 * float(np.std(yt - model.predict(X)))
        hist, preds = list(y), []
        for _ in range(HORIZON):
            feat = np.array([hist[-k] for k in range(1, LAGS + 1)]).reshape(1, -1)
            nxt = float(model.predict(feat)[0]); hist.append(nxt); preds.append(round(nxt, 2))
        delta = idx[-1] - idx[-2]
        periods = [str(pd.Timestamp(idx[-1] + delta * (i + 1)).date()) for i in range(HORIZON)]
        save_table("prediction_values", pd.DataFrame({
            "period": periods, "predicted": preds,
            "lower": [round(v - ci, 2) for v in preds], "upper": [round(v + ci, 2) for v in preds]}))
        names = ["lag_%d" % k for k in range(1, LAGS + 1)]
        save_value("prediction_metrics", {
            "model": best, "mape": round(best_mape, 2), "rmse": round(stats["rmse"], 2),
            "mae": round(stats["mae"], 2), "r2": round(stats["r2"], 2),
            "train_rows": int(split), "test_rows": int(len(yt) - split), "horizon": HORIZON,
            "target": target, "is_time_series": True, "mode": "forecast",
            "features_used": names, "feature_importances": _importances(model, names),
            "models_compared": list(_candidates().keys())})
        xh = [str(pd.Timestamp(d).date()) for d in idx[-min(n, 40):]]
        fig = go.Figure()
        fig.add_scatter(x=xh, y=[round(float(v), 2) for v in y[-min(n, 40):]], name="actual", mode="lines")
        fig.add_scatter(x=periods, y=preds, name="forecast", mode="lines+markers")
        fig.add_scatter(x=periods + periods[::-1],
                        y=[round(v + ci, 2) for v in preds] + [round(v - ci, 2) for v in preds][::-1],
                        fill="toself", name="95% interval", line=dict(width=0), opacity=0.25)
        test_idx = idx[LAGS + split:]
        if best_p is not None and len(test_idx) == len(best_p):
            fig.add_scatter(x=[str(pd.Timestamp(d).date()) for d in test_idx],
                            y=[round(float(v), 2) for v in best_p], name="backtest", mode="lines", line=dict(dash="dot"))
        save_chart("prediction_chart", fig, title="Forecast: %s (next %d)" % (target, HORIZON))
        save_value("prediction_summary", "Best model %s: MAPE %.2f%%, R2 %.2f on a %d/%d split; forecast next %d periods of %s."
                   % (best, best_mape, stats["r2"], split, len(yt) - split, HORIZON, target))

else:
    # ---- TABULAR: no time dimension -> predict the target from other features ----
    feats = [c for c in num_cols if c != target]
    cats = [c for c in df.columns if c not in num_cols and c != dt_col and df[c].nunique() <= 20]
    work = df[[target] + feats + cats].dropna()
    if len(feats) + len(cats) < 1 or len(work) < 30:
        save_value("prediction_metrics", {"error": "no time column to forecast, and too few usable features for a tabular model"})
    else:
        Xdf = work[feats + cats]
        if cats:
            Xdf = pd.get_dummies(Xdf, columns=cats, drop_first=True)
        names = list(Xdf.columns)
        X = Xdf.values.astype(float); yv = work[target].values.astype(float)
        Xtr, Xte, ytr, yte = train_test_split(X, yv, test_size=0.2, random_state=42)
        best, best_mape, stats, best_p = _fit_best(Xtr, ytr, Xte, yte)
        model = _candidates()[best]; model.fit(X, yv)
        save_table("prediction_values", pd.DataFrame({
            "actual": [round(float(v), 2) for v in yte[:20]],
            "predicted": [round(float(v), 2) for v in np.asarray(best_p)[:20]]}))
        save_value("prediction_metrics", {
            "model": best, "mape": round(best_mape, 2), "rmse": round(stats["rmse"], 2),
            "mae": round(stats["mae"], 2), "r2": round(stats["r2"], 2),
            "train_rows": int(len(ytr)), "test_rows": int(len(yte)), "horizon": 0,
            "target": target, "is_time_series": False, "mode": "regression",
            "features_used": names[:10], "feature_importances": _importances(model, names),
            "models_compared": list(_candidates().keys())})
        order = np.argsort(yte)
        fig = go.Figure()
        fig.add_scatter(y=[round(float(v), 2) for v in yte[order]], name="actual", mode="lines")
        fig.add_scatter(y=[round(float(v), 2) for v in np.asarray(best_p)[order]], name="predicted", mode="markers")
        save_chart("prediction_chart", fig, title="%s: predicted vs actual (held-out)" % target)
        save_value("prediction_summary",
                   "No time column, so this predicts %s from %d features (tabular regression). Best model %s: R2 %.2f, MAPE %.2f%% on a %d/%d holdout."
                   % (target, len(names), best, stats["r2"], best_mape, len(ytr), len(yte)))
'''
