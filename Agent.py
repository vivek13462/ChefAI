# ChefAI step 1 — today's expenses
import json
import os
import urllib.error
import urllib.request

PROJECT = "ChefAI"
API_URL = "https://api.openai.com/v1/chat/completions"

SHIPMENT = [
    {"item": "Roma tomatoes", "vendor": "FreshFarm Produce", "qty": 12, "unit_price": 1.25},
    {"item": "Basil bunches", "vendor": "GreenLeaf Herbs", "qty": 6, "unit_price": 2.40},
    {"item": "Olive oil 1L", "vendor": "Mediterranean Oils Co", "qty": 2, "unit_price": 18.50},
    {"item": "Chicken breasts 5lb", "vendor": "Hillside Poultry", "qty": 3, "unit_price": 14.75},
    {"item": "Sourdough loaves", "vendor": "Dawn Bakery", "qty": 8, "unit_price": 4.10},
    {"item": "Heavy cream pints", "vendor": "Meadow Dairy", "qty": 4, "unit_price": 3.85},
]


def load_env_file(path=".env"):
    """Load simple KEY=VALUE lines from .env without overriding the real environment."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip())


def build_report(items):
    for row in items:
        row["line_total"] = row["qty"] * row["unit_price"]
    total = sum(row["line_total"] for row in items)

    lines = [f"{PROJECT} — today's shipment"]
    for row in items:
        lines.append(
            f"{row['item']} | {row['vendor']} | qty {row['qty']} | "
            f"${row['unit_price']:.2f} | ${row['line_total']:.2f}"
        )
    lines.append(f"TODAY TOTAL: ${total:.2f}")
    return "\n".join(lines), total


def format_table(items, total):
    """Apply the format-expense-table skill: formatting only, numbers come from Python."""
    headers = ["Item", "Vendor", "Qty", "Unit price", "Line total"]
    rows = [
        [r["item"], r["vendor"], str(r["qty"]), f"${r['unit_price']:.2f}", f"${r['line_total']:.2f}"]
        for r in items
    ]
    total_row = ["TOTAL", "", "", "", f"${total:.2f}"]
    right = {2, 3, 4}

    widths = [
        max(len(line[i]) for line in [headers] + rows + [total_row])
        for i in range(len(headers))
    ]

    def fmt(cells):
        return " | ".join(
            c.rjust(widths[i]) if i in right else c.ljust(widths[i])
            for i, c in enumerate(cells)
        )

    separator = "-+-".join("-" * w for w in widths)
    lines = [f"{PROJECT} — today's shipment (formatted)", fmt(headers), separator]
    lines += [fmt(r) for r in rows]
    lines.append(fmt(total_row))
    return "\n".join(lines)


def ask_chef(key, model, table_text, skill_text):
    prompt = (
        "Here is today's delivery for our restaurant kitchen, already formatted using this skill:\n\n"
        f"{skill_text}\n\n"
        "The numbers are final; do not recalculate or change them.\n\n"
        f"{table_text}\n\n"
        "In two sentences, say what a chef would say about today's delivery spend."
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def main():
    load_env_file()
    report_text, total = build_report(SHIPMENT)
    print(report_text)

    print()
    print("=" * 60)
    print("Applying the skill now.")
    print("=" * 60)
    print()

    skill_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SKILL.md")
    try:
        with open(skill_path, encoding="utf-8") as f:
            skill_text = f.read()
    except OSError:
        print("SKILL.md not found next to Agent.py; skipping the formatted table.")
        return

    table_text = format_table(SHIPMENT, total)
    print(table_text)
    print()

    key = os.getenv("LLM_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if not key:
        print("LLM skipped: LLM_API_KEY is not set in the environment.")
        return

    try:
        answer = ask_chef(key, model, table_text, skill_text)
        print("Chef says:")
        print(answer)
    except urllib.error.HTTPError as e:
        print(f"LLM error: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        print(f"LLM error: {e.reason}")
    except (KeyError, IndexError, ValueError, OSError) as e:
        print(f"LLM error: {type(e).__name__}")


if __name__ == "__main__":
    main()
