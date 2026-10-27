"""Ask rule questions about a board game rulebook via Ollama.

Usage: python3 tools/ask.py RULEBOOK.md "Frage 1" ["Frage 2" ...]
"""
import json
import sys
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:30b-a3b-instruct-2507-q4_K_M"

SYSTEM_PROMPT = """Du bist ein Regel-Schiedsrichter für Brettspiele.
Beantworte Fragen ausschließlich anhand des folgenden Regelwerks.
- Spieler fragen oft umgangssprachlich oder mit anderen Begriffen als das
  Regelwerk (z. B. "angreifen", "schlagen" oder "Leben", wo das Regelwerk
  eigene Fachbegriffe benutzt), oder sie benennen Figuren und Spielmaterial
  anders (z. B. "Sheriff", "Polizist", "Wache" für eine Ordnungsfigur).
  Ordne die Frage dem passenden Regelbegriff zu und nenne ihn in der Antwort.
- Suche zuerst ALLE Stellen, die die Frage betreffen, auch Einschränkungen
  ("kann nicht", "darf nicht", "außer") und Beispiele. Allgemeine Regeln
  gelten nur, wenn keine speziellere Regel oder Einschränkung greift.
- Antworte so:
  Antwort: <kurz und präzise auf Deutsch>
  Regel: "<wörtliches Zitat, nur der entscheidende Satz>" (Abschnitt: <Überschrift aus dem Regelwerk>)
- Prüfe vor dem Antworten, ob dein Zitat die Antwort wirklich belegt. Wenn
  nicht, korrigiere die Antwort oder suche die passende Stelle.
- Nenne nur Überschriften, die wirklich im Regelwerk stehen. Erfinde keine
  Abschnittsnummern oder Seitenzahlen.
- Steht die Antwort nicht im Regelwerk, sage das deutlich und rate nicht.

<regelwerk>
{rules}
</regelwerk>"""


def ask(rules, question):
    payload = {
        "model": MODEL,
        "stream": False,
        "keep_alive": "30m",
        # Recommended Qwen3 instruct sampling; the token limit stops the
        # model from looping forever.
        "options": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "num_predict": 1024},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.format(rules=rules)},
            {"role": "user", "content": question},
        ],
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.load(response)


def main():
    with open(sys.argv[1], encoding="utf-8") as f:
        rules = f.read()
    for question in sys.argv[2:]:
        result = ask(rules, question)
        prompt_s = result["prompt_eval_duration"] / 1e9
        gen_s = result["eval_duration"] / 1e9
        print(f"### {question}\n")
        print(result["message"]["content"].strip(), "\n", flush=True)
        print(
            f"[Prompt: {result.get('prompt_eval_count', 0)} Tokens in {prompt_s:.1f}s | "
            f"Antwort: {result['eval_count']} Tokens, "
            f"{result['eval_count'] / gen_s:.1f} Tok/s | "
            f"gesamt {result['total_duration'] / 1e9:.1f}s]\n"
        )


if __name__ == "__main__":
    main()
