"""Minimal data-science script used to measure import and startup time."""

import matplotlib.pyplot as pyplot
import numpy as np
import openpyxl
import pandas as pd
import plotly
import polars as pl
import requests
import scipy
import seaborn as sns
import sklearn
import sqlalchemy
import statsmodels.api as sm

_ = np.arange(10).mean()
_ = pd.DataFrame({"x": [1, 2, 3]}).mean()
_ = pl.DataFrame({"x": [1, 2, 3]}).mean()
_ = scipy.stats.norm.cdf(0)
_ = sm.add_constant([1.0, 2.0])
_ = sklearn.__version__
_ = sqlalchemy.__version__
_ = openpyxl.__version__
_ = requests.__version__
_ = plotly.__version__
_ = sns.__version__
pyplot.figure()
pyplot.close()
