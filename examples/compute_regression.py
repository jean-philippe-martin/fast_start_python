"""Simple OLS regression — prints fitted coefficients and metrics.

    uv run fspython.py run examples/compute_regression.py
"""

import numpy as np
import statsmodels.api as sm

# y = 2.5 * x + 1.0 + noise
RNG = np.random.default_rng(42)
X_RAW = np.arange(20, dtype=float)
Y = 2.5 * X_RAW + 1.0 + RNG.normal(0, 1.5, size=X_RAW.shape)
X = sm.add_constant(X_RAW)


def main() -> None:
    model = sm.OLS(Y, X).fit()

    print("Observations:", len(Y))
    print(f"Intercept: {model.params[0]:.4f}  (true ≈ 1.0)")
    print(f"Slope:     {model.params[1]:.4f}  (true ≈ 2.5)")
    print(f"R-squared: {model.rsquared:.4f}")
    print(f"Std err:   {model.bse[1]:.4f}")
    print()
    print("Predictions for x = 0, 5, 10:")
    for x_val in (0, 5, 10):
        pred = model.predict([1.0, x_val])[0]
        print(f"  x={x_val:2d}  y_hat={pred:.2f}")


if __name__ == "__main__":
    main()
