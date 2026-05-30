# Fast Start Python

The idea: a Python that starts quickly with a bunch of imports for data analysis. We pre-start a Python process with the right imports and it listens to a port and gets messages that specify a python file, and:

- it forks
- imports that python file
- runs it

Data analysis libraries it imports:

- numpy
- pandas
- scipy
- matplotlib.pyplot (as pyplot)
- seaborn
- plotly
- statsmodels
- scikit-learn (as sklearn)
- polars
- sqlalchemy
- openpyxl
- requests

Command line:

// start the listener process
uv run fspython.py serve

// connect to the server, run somefile.py
uv run fspython.py run somefile.py

Helpers:

This will start a fspython process, redirect the output to /tmp/fspython.log, background it.

./start-fspython.sh

This will kill the fspython process

./stop-fspython.sh

