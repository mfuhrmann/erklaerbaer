"""Ask rule questions about a board game rulebook via Ollama.

Usage: python3 tools/ask.py RULEBOOK.md "Frage 1" ["Frage 2" ...]
"""
import json
import os
import sys
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
# Gemma 4 e4b: 55/56 vs 56/56 for qwen3:30b-a3b-instruct-2507-q4_K_M on 28 rule
# questions, but twice as fast and a quarter of the memory (NOTIZEN.md).
MODEL = os.environ.get("ERKLAERBAER_MODELL", "gemma4:e4b")


def can_think(ollama, model):
    """Whether the model thinks before answering (Gemma 4) and so needs think=false.

    Models without thinking reject the option, so ask Ollama instead of always sending it.
    """
    request = urllib.request.Request(f"{ollama}/api/show", data=json.dumps({"model": model}).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return "thinking" in json.load(response).get("capabilities", [])
    except OSError:
        return False

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
        **({"think": False} if THINKS else {}),
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


THINKS = None


def main():
    global THINKS
    THINKS = can_think(OLLAMA_URL.rsplit("/api/", 1)[0], MODEL)
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
