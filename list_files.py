import os

exclude = ['venv', '__pycache__', '.pytest_cache', '.git']

for dp, dn, fn in os.walk('.'):
    # Skip excluded directories
    dn[:] = [d for d in dn if d not in exclude]

    for f in sorted(fn):
        if not f.endswith('.pyc'):
            path = os.path.join(dp, f).replace('.\\', '')
            print(path)
