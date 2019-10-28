#!/bin/bash

if [[ -f venv/bin/activate ]]; then
	source venv/bin/activate
fi

export FLASK_APP=ref

python3 -m "flask" db init || true
python3 -m "flask" db migrate || true
python3 -m "flask" db upgrade || true
