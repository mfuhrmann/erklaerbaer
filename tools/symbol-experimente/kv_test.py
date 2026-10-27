# kv_test.py <label> [model] : answer quality and speed (KV cache type or another model)
# Same prompt and sampling as the app; each question 3x without history.
import json, re, sys, time
import httpx

sys.path.insert(0, "/home/mf1045/projects/erklaerbaer")
from tools.ask import MODEL, SYSTEM_PROMPT

TESTS = [
    ("gunsen", "Wie verhält sich der Blutwert in Kämpfen?", r"tötet"),
    ("gunsen", "Wie viele Würfel darf man höchstens werfen?", r"\b6\b|sechs"),
    ("gunsen", "Wer gewinnt, wenn zwei Klane gleichzeitig ihren 7. Erfolg erzielen?", r"am Zug"),
    ("star-trek-captains-chair", "Was passiert, wenn der Zwischenfall-Stapel leer ist?", r"sofort|Brand"),
    ("star-trek-captains-chair", "Was passiert bei Gleichstand in der Endwertung?", r"beide"),
]
model = sys.argv[2] if len(sys.argv) > 2 else MODEL
results = []
with httpx.Client(timeout=900) as client:
    for game, question, expected in TESTS:
        rules = open(f"/home/mf1045/projects/erklaerbaer/regelwerke/{game}.md", encoding="utf-8").read()
        for run in range(3):
            t = time.time()
            payload = {
                "model": model, "stream": False, "keep_alive": -1,
                "options": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "num_predict": 1024},
                "messages": [{"role": "system", "content": SYSTEM_PROMPT.format(rules=rules)},
                             {"role": "user", "content": question}]}
            if model.startswith("gemma4"):
                payload["think"] = False  # thinking models: answer directly, like the app needs
            r = client.post("http://localhost:11434/api/chat", json=payload).json()
            if "error" in r:
                sys.exit(f"Fehler: {r['error']}")
            answer = r["message"]["content"].strip()
            ok = bool(re.search(expected, answer, re.IGNORECASE))
            results.append({"spiel": game, "frage": question, "lauf": run, "richtig": ok,
                            "sekunden": round(time.time() - t, 1), "prompt_tokens": r.get("prompt_eval_count"),
                            "einlesen_s": round(r.get("prompt_eval_duration", 0) / 1e9, 1),
                            "tok_s": round(r["eval_count"] / (r["eval_duration"] / 1e9), 1), "antwort": answer})
            print(f"{'✅' if ok else '❌'} {game[:10]:10} {question[:45]:45} {time.time() - t:5.1f}s  {answer[:90]!r}", flush=True)
json.dump(results, open(f"/tmp/claude-1000/kv-{sys.argv[1]}.json", "w"), ensure_ascii=False, indent=1)
right = sum(r["richtig"] for r in results)
print(f"== {sys.argv[1]}: {right}/{len(results)} richtig")
