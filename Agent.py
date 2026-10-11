# ChefAI step 1 — today's expenses
import datetime
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MCP_SERVER_PY = r"C:\InvoiceMCP\server.py"
MCP_HTTP_URL = "http://127.0.0.1:8765/mcp"

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


# ---------------------------------------------------------------- MCP client
# Minimal MCP client over the standard library (no pip packages).

PROTOCOL_VERSION = "2025-06-18"
MAX_ROUNDS = 5
INVOICE_GOAL = (
    "Generate the three HTML invoices for latest_delivery, year_to_date, and last_year. "
    "Use the MCP tools. Do not skip any of the three periods."
)

PLANNER_RULES = """Query rules:
- Map calendar language to period. If the current year is {year}: "{last_year}" or "last year" or
  "all spending in {last_year}" = period last_year. "this year" or "YTD" = year_to_date.
  "latest delivery" = latest_delivery. Do not use year_to_date for a past calendar year.
- item is optional. Blank or omit item when the question is about all items or vendors.
- item is a case-insensitive substring, not an exact phrase.
- Normalize singular and plural before choosing item. Example: loaf, loaves, sourdough, bread ->
  item "loaf" or "sourdough" so "Sourdough loaves" matches. tomato / tomatoes -> "tomato". oil -> "oil".
- Prefer query_expenses first when the user wants totals, counts, vendors, or a filtered spend.
  Use generate_invoice only when they ask for an invoice/report file.
- After data returns, do not emit another tool with name null. Emit {{"done": true}} if the sample
  answers the question."""

OUTPUT_FORMAT = (
    'Reply with JSON only. Either {"tool": "<exact tool name>", "arguments": {...}}, or an array of '
    'such objects to run several tools, or {"done": true, "reason": "..."} when finished. '
    "Never use null or an empty string for tool."
)


class McpError(Exception):
    pass


class StdioMcp:
    """Launches server.py with this machine's Python and talks newline-delimited JSON-RPC."""

    def __init__(self, server_py):
        env = dict(os.environ, PYTHONUTF8="1")
        self.proc = subprocess.Popen(
            [sys.executable, server_py],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(os.path.abspath(server_py)),
            text=True,
            encoding="utf-8",
            env=env,
        )
        self.lines = queue.Queue()
        self.next_id = 0
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _send(self, message):
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except OSError as e:
            raise McpError(f"server process is not accepting input ({e})")

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params:
            message["params"] = params
        self._send(message)

    def request(self, method, params=None, timeout=60):
        self.next_id += 1
        rid = self.next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                raise McpError(f"timed out waiting for {method}")
            if line is None:
                raise McpError("server process exited")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") == rid:
                if "error" in message:
                    raise McpError(str(message["error"].get("message", message["error"])))
                return message.get("result") or {}

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


class HttpMcp:
    """Streamable HTTP MCP client using urllib (JSON or SSE responses)."""

    def __init__(self, url):
        self.url = url
        self.session = None
        self.version = None
        self.next_id = 0

    def _post(self, payload, timeout):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.version:
            headers["MCP-Protocol-Version"] = self.version
        url = self.url
        data = json.dumps(payload).encode("utf-8")
        for _ in range(3):
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                response = urllib.request.urlopen(request, timeout=timeout)
                break
            except urllib.error.HTTPError as e:
                location = e.headers.get("Location") if e.code in (307, 308) else None
                if not location:
                    raise
                url = urllib.parse.urljoin(url, location)
        else:
            raise McpError("too many redirects")
        with response:
            self.session = response.headers.get("Mcp-Session-Id") or self.session
            body = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")
        if not body.strip():
            return []
        if content_type.startswith("text/event-stream"):
            messages = []
            for event in re.split(r"\r?\n\r?\n", body):
                data_lines = [
                    ln[5:].lstrip() for ln in event.splitlines() if ln.startswith("data:")
                ]
                if data_lines:
                    try:
                        messages.append(json.loads("\n".join(data_lines)))
                    except ValueError:
                        pass
            return messages
        parsed = json.loads(body)
        return parsed if isinstance(parsed, list) else [parsed]

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params:
            message["params"] = params
        self._post(message, 30)

    def request(self, method, params=None, timeout=60):
        self.next_id += 1
        rid = self.next_id
        messages = self._post(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}, timeout
        )
        for message in messages:
            if isinstance(message, dict) and message.get("id") == rid:
                if "error" in message:
                    raise McpError(str(message["error"].get("message", message["error"])))
                return message.get("result") or {}
        raise McpError(f"no response to {method}")

    def close(self):
        pass


def initialize_and_list_tools(client):
    result = client.request("initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "chefai-agent", "version": "1.0"},
    })
    client.version = result.get("protocolVersion", PROTOCOL_VERSION) if isinstance(client, HttpMcp) else None
    client.notify("notifications/initialized")
    tools, cursor = [], None
    while True:
        page = client.request("tools/list", {"cursor": cursor} if cursor else {})
        tools += [t for t in page.get("tools", []) if isinstance(t, dict)]
        cursor = page.get("nextCursor")
        if not cursor:
            return tools


def result_text(result):
    parts = [
        c.get("text", "") for c in result.get("content", [])
        if isinstance(c, dict) and c.get("type") == "text"
    ]
    text = "\n".join(parts)
    if not text and result.get("structuredContent") is not None:
        text = json.dumps(result["structuredContent"])
    return ("TOOL ERROR: " + text) if result.get("isError") else text


# ---------------------------------------------------------------- planner

def llm_chat(key, model, prompt):
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def ask_llm(key, model, prompt):
    try:
        return llm_chat(key, model, prompt)
    except urllib.error.HTTPError as e:
        print(f"LLM error: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        print(f"LLM error: {e.reason}")
    except (KeyError, IndexError, ValueError, OSError) as e:
        print(f"LLM error: {type(e).__name__}")
    return None


def extract_json_values(text):
    text = text.strip()
    for candidate in (text, "[" + text + "]"):
        try:
            return json.loads(candidate)
        except ValueError:
            pass
    values, decoder, i = [], json.JSONDecoder(), 0
    while i < len(text):
        if text[i] in "{[":
            try:
                value, end = decoder.raw_decode(text, i)
                values.append(value)
                i = end
                continue
            except ValueError:
                pass
        i += 1
    return values


def flatten_objects(value):
    if isinstance(value, list):
        for item in value:
            yield from flatten_objects(item)
    elif isinstance(value, dict):
        yield value


def parse_plan(text, valid_names):
    """Return (valid_calls, skipped_names). Null/missing/empty tool means done, never a call."""
    calls, skipped = [], []
    for item in flatten_objects(extract_json_values(text)):
        tool = item.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            continue
        tool = tool.strip()
        if tool not in valid_names:
            skipped.append(tool)
            continue
        arguments = item.get("arguments")
        calls.append({"tool": tool, "arguments": arguments if isinstance(arguments, dict) else {}})
    return calls, skipped


def summarize(value):
    if isinstance(value, list):
        return {"count": len(value), "first": [summarize(v) for v in value[:5]]}
    if isinstance(value, dict):
        return {k: summarize(v) for k, v in value.items()}
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "..."
    return value


def collect_facts(value, facts, key=""):
    lk = key.lower()
    if isinstance(value, dict):
        for k, v in value.items():
            collect_facts(v, facts, k)
    elif isinstance(value, list):
        facts["counts"][key or "list"] = len(value)
        for v in value:
            collect_facts(v, facts, key)
    elif isinstance(value, str):
        if "item" in lk and value not in facts["items"] and len(facts["items"]) < 15:
            facts["items"].append(value)
        elif ("vendor" in lk or "supplier" in lk) and value not in facts["vendors"] and len(facts["vendors"]) < 15:
            facts["vendors"].append(value)
        elif ("path" in lk or "file" in lk or value.lower().endswith(".html")) and value not in facts["paths"]:
            facts["paths"].append(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "total" in lk or "count" in lk:
            facts["totals"][key] = value


def build_sample(results):
    sample = []
    for r in results:
        facts = {"items": [], "vendors": [], "counts": {}, "totals": {}, "paths": []}
        collect_facts(r["data"], facts)
        sample.append({
            "tool": r["tool"],
            "arguments": r["arguments"],
            "facts": facts,
            "summary": summarize(r["data"]),
        })
    return json.dumps(sample)[:8000]


def describe_tools(tools):
    return json.dumps([
        {"name": t.get("name"), "description": t.get("description", ""), "inputSchema": t.get("inputSchema", {})}
        for t in tools
    ])


def detect_year_range(results):
    years = [
        int(y) for r in results for y in re.findall(r"\b(20\d\d)-\d\d-\d\d\b", r["text"])
    ]
    return f"{min(years)}-{max(years)}" if years else None


def planning_prompt(goal, tools, ctx):
    today = datetime.date.today()
    rules = PLANNER_RULES.format(year=today.year, last_year=today.year - 1)
    return (
        f"You plan MCP tool calls for a restaurant expense assistant.\n"
        f"User question: {goal}\n"
        f"Today's date: {today.isoformat()}\n"
        f"CSV year range: {ctx.get('years') or 'unknown'}\n"
        f"Live tools with argument schemas: {describe_tools(tools)}\n\n"
        f"{rules}\n\n{OUTPUT_FORMAT}"
    )


def review_prompt(goal, tools, results):
    return (
        f"You plan MCP tool calls for a restaurant expense assistant.\n"
        f"Original question: {goal}\n"
        f"Today's date: {datetime.date.today().isoformat()}\n"
        f"Live tools with argument schemas: {describe_tools(tools)}\n"
        f"Data sample from tool results so far: {build_sample(results)}\n\n"
        "Is this enough to answer the question completely (every part of the question covered)? "
        'If yes, return {"done": true}. Otherwise return the next tool call(s) still needed. '
        "Do not repeat a call that already ran.\n\n" + OUTPUT_FORMAT
    )


def call_valid_tool(client, names, tool, arguments):
    """Only calls MCP for a non-empty string name present in the live tool list."""
    if not isinstance(tool, str) or not tool.strip() or tool not in names:
        return None
    print(f"Tool: {tool}  arguments: {json.dumps(arguments)}")
    try:
        text = result_text(client.request("tools/call", {"name": tool, "arguments": arguments}, timeout=120))
    except (McpError, OSError) as e:
        text = f"TOOL ERROR: {e}"
    try:
        data = json.loads(text)
    except ValueError:
        data = text
    shown = json.dumps(summarize(data)) if isinstance(data, (dict, list)) else text
    print("Result:", shown if len(shown) <= 800 else shown[:800] + " ...")
    return {"tool": tool, "arguments": arguments, "text": text, "data": data}


def run_goal(client, tools, goal, key, model, ctx):
    names = {t["name"] for t in tools if isinstance(t.get("name"), str) and t["name"]}
    print(f"Goal: {goal}")
    results, seen = [], set()
    for round_no in range(MAX_ROUNDS):
        prompt = planning_prompt(goal, tools, ctx) if round_no == 0 else review_prompt(goal, tools, results)
        reply = ask_llm(key, model, prompt)
        if reply is None:
            break
        calls, skipped = parse_plan(reply, names)
        for name in skipped:
            print(f"Skipped invalid tool name: {name!r}")
        fresh = []
        for call in calls:
            signature = (call["tool"], json.dumps(call["arguments"], sort_keys=True))
            if signature not in seen:
                seen.add(signature)
                fresh.append(call)
        if not fresh:
            print("Planner finished.")
            break
        for call in fresh:
            outcome = call_valid_tool(client, names, call["tool"], call["arguments"])
            if outcome:
                results.append(outcome)
        ctx["years"] = detect_year_range(results) or ctx.get("years")
    return results


def chef_says_loop(goal, results, key, model):
    if not results:
        print("Chef says (loop): no tool results to talk about.")
        return
    prompt = (
        f"Question: {goal}\n"
        f"Real tool results: {build_sample(results)}\n\n"
        "Write exactly two sentences a chef would say about these results. "
        "Use only numbers that appear in the results; do not invent totals."
    )
    answer = ask_llm(key, model, prompt)
    if answer:
        print("Chef says (loop):")
        print(answer)


def handle_goal(client, tools, goal, key, model, ctx):
    results = run_goal(client, tools, goal, key, model, ctx)
    chef_says_loop(goal, results, key, model)
    return results


# ---------------------------------------------------------------- MCP section

def connect_stdio():
    path = MCP_SERVER_PY
    if not path or "PUT-THE-MCP-FOLDER-HERE" in path or not os.path.isfile(path):
        print(f"MCP_SERVER_PY is missing or the file does not exist: {path}")
        print("Edit MCP_SERVER_PY at the top of Agent.py. Skipping MCP.")
        return None
    client = None
    try:
        client = StdioMcp(path)
        return client, initialize_and_list_tools(client)
    except (McpError, OSError, ValueError) as e:
        print(f"MCP error: {e}")
        if client:
            client.close()
        return None


def connect_http():
    client = HttpMcp(MCP_HTTP_URL)
    try:
        return client, initialize_and_list_tools(client)
    except urllib.error.HTTPError as e:
        print(f"MCP error: HTTP {e.code} {e.reason}")
    except urllib.error.URLError:
        print("HTTP MCP is not running. In the server folder run: python server.py --http")
    except (McpError, OSError, ValueError) as e:
        print(f"MCP error: {e}")
    return None


def read_line(prompt=""):
    try:
        return input(prompt)
    except EOFError:
        return "q"


def mcp_section(key, model):
    print()
    print("=" * 60)
    print("Connect to MCP server")
    print("1. STDIO (start the local server process)")
    print(f"2. HTTP ({MCP_HTTP_URL})")
    choice = read_line("Choose 1 or 2: ").strip()

    if choice == "1":
        connected = connect_stdio()
    elif choice == "2":
        connected = connect_http()
    else:
        print("Invalid choice. Skipping MCP.")
        return
    if not connected:
        return

    client, tools = connected
    try:
        print()
        print("Connected. Tools:")
        for tool in tools:
            description = (tool.get("description") or "").strip().splitlines()
            print(f"- {tool.get('name')}: {description[0] if description else ''}")

        if not key:
            print("LLM skipped: LLM_API_KEY is not set in the environment.")
            return

        ctx = {}
        print()
        print("=" * 60)
        print("Dynamic agent loop — LLM picks the MCP tool.")
        results = handle_goal(client, tools, INVOICE_GOAL, key, model, ctx)
        paths = []
        for r in results:
            facts = {"items": [], "vendors": [], "counts": {}, "totals": {}, "paths": []}
            collect_facts(r["data"], facts)
            paths += [p for p in facts["paths"] if p not in paths]
        print("Invoice paths:" if paths else "No invoice paths were returned.")
        for p in paths:
            print(f"- {p}")

        print()
        while True:
            print("Three invoices are done. Any other question? (Q = quit)")
            question = read_line().strip()
            if not question:
                print("Enter a question, or Q to quit.")
                continue
            if question in ("Q", "q"):
                print("Loop ended.")
                break
            handle_goal(client, tools, question, key, model, ctx)
            print()
    finally:
        client.close()


def run_steps_1_2():
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


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    load_env_file()
    run_steps_1_2()
    try:
        mcp_section(os.getenv("LLM_API_KEY"), os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    except Exception as e:
        print(f"MCP error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
