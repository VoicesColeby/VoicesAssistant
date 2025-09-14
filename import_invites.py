import os
import sys
import csv
import re
import time
import subprocess
from typing import List, Tuple


def info(msg: str):
    print(f"[i] {msg}", flush=True)


def ok(msg: str):
    print(f"[✓] {msg}", flush=True)


def warn(msg: str):
    print(f"[!] {msg}", flush=True)


def err(msg: str):
    print(f"[x] {msg}", flush=True)


def read_env(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default


def parse_usernames_from_csv(csv_path: str) -> List[str]:
    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise RuntimeError("CSV has no header row")
        fieldmap = { (c or '').strip().lower(): c for c in reader.fieldnames }
        ucol = fieldmap.get('username')
        if not ucol:
            raise RuntimeError("Could not find a 'username' column in the CSV")
        vals = []
        for row in reader:
            v = (row.get(ucol) or '').strip()
            if v:
                vals.append(v)
        return vals


def choose_invite_script() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    cdp = os.path.join(base, 'invite_to_job_cdp.py')
    if os.path.exists(cdp):
        return 'invite_to_job_cdp.py'
    return 'invite_to_job.py'


def main() -> int:
    csv_path = read_env('CSV_PATH').strip()
    job_query = read_env('JOB_QUERY').strip()

    if not csv_path or not os.path.exists(csv_path):
        err("CSV_PATH missing or file not found. Provide CSV_PATH to a CSV with a 'username' column.")
        return 2
    if not job_query:
        err("JOB_QUERY missing. Provide the numeric Job # to invite to.")
        return 2
    job_digits = re.sub(r"\D", "", job_query)
    if not job_digits:
        err("JOB_QUERY must contain digits (e.g., 805775)")
        return 2

    try:
        usernames = parse_usernames_from_csv(csv_path)
    except Exception as e:
        err(f"CSV Error: {e}")
        return 2

    if not usernames:
        warn("No usernames found in the CSV.")
        return 0

    info(f"Importing {len(usernames)} usernames from CSV…")

    base_env = os.environ.copy()
    if not base_env.get('DEBUG_URL'):
        base_env['DEBUG_URL'] = 'http://127.0.0.1:9222'

    # Navigate to each profile URL explicitly
    base_env['USE_CURRENT_PAGE'] = '0'
    base_env['JOB_QUERY'] = job_digits

    # Speed settings for downstream script
    speed_val = 5.0
    try:
        speed_val = float(read_env('SPEED', '5.0'))
    except Exception:
        speed_val = 5.0
    base_env['SPEED'] = f"{max(1.0, min(5.0, speed_val)):.2f}"
    # Forward live speed file if present
    if read_env('SPEED_FILE'):
        base_env['SPEED_FILE'] = read_env('SPEED_FILE')

    invite_script = choose_invite_script()

    successes: List[str] = []
    failures: List[Tuple[str, int]] = []

    for idx, username in enumerate(usernames, start=1):
        profile_url = f"https://www.voices.com/profile/{username}"
        info(f"({idx} of {len(usernames)}) Inviting: {username}")

        run_env = base_env.copy()
        run_env['START_URL'] = profile_url
        run_env['PYTHONUNBUFFERED'] = '1'
        run_env['PYTHONIOENCODING'] = 'utf-8'

        try:
            proc = subprocess.Popen(
                [sys.executable, invite_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=run_env,
                creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
            )
        except FileNotFoundError:
            err(f"Script not found: {invite_script}")
            return 2

        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                # Pass-through child output to GUI console
                print(line, end="", flush=True)
        finally:
            proc.wait()

        rc = proc.returncode or 0
        if rc == 0:
            successes.append(username)
            ok(f"Invited: {username}")
        else:
            failures.append((username, rc))
            err(f"Failed to invite: {username} (code={rc})")

        # Pacing based on SPEED (1 slow .. 5 fast)
        try:
            spd = max(1.0, min(5.0, float(base_env.get('SPEED', '5.0'))))
        except Exception:
            spd = 5.0
        delay = max(0.0, (6.0 - spd) * 0.4)
        if delay > 0:
            time.sleep(delay)

    info(f"Import invites finished. {len(successes)} succeeded, {len(failures)} failed.")

    if failures:
        try:
            base, _ = os.path.splitext(csv_path)
            out_path = base + "_failures.csv"
            with open(out_path, 'w', encoding='utf-8', newline='') as f:
                w = csv.writer(f)
                w.writerow(["username", "code"]) 
                for (u, code) in failures:
                    w.writerow([u, code])
            info(f"Wrote failures CSV: {out_path}")
        except Exception as e:
            err(f"Failed to write failures CSV: {e}")

    # Return non-zero if any failures occurred
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())

