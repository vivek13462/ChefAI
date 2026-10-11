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

    lines = [f"{PROJECT} — today's shipment", "-" * 78]
    for row in items:
        lines.append(
            f"{row['item']:<22} {row['vendor']:<24} "
            f"qty {row['qty']:>3}  @ ${row['unit_price']:>6.2f}  = ${row['line_total']:>7.2f}"
        )
    lines.append("-" * 78)
    lines.append(f"TODAY TOTAL: ${total:.2f}")
    return "\n".join(lines), total


def ask_chef(key, model, report_text):
    prompt = (
        "Here is today's delivery for our restaurant kitchen. The math is already computed; "
        "do not recalculate it.\n\n"
        f"{report_text}\n\n"
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
    report_text, _ = build_report(SHIPMENT)
    print(report_text)
    print()

    key = os.getenv("LLM_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if not key:
        print("LLM skipped: LLM_API_KEY is not set in the environment.")
        return

    try:
        answer = ask_chef(key, model, report_text)
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
