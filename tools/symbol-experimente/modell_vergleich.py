# modell_vergleich.py <model> <label> [rulebook dir] : answer quality across many rulebooks
# Same prompt and sampling as the app; each question twice, without history.
# Expected answers were checked against the rulebooks by hand.
import json, re, sys, time
import httpx

sys.path.insert(0, "/home/mf1045/projects/erklaerbaer")
from tools.ask import SYSTEM_PROMPT

QUESTIONS = [
    ("colt-express", "Darf der Marshal aufs Dach klettern?", r"\bnein\b|niemals|\bnie\b|nicht aufs Dach|klettert (er )?nicht"),
    ("colt-express", "Darf der Marshal die Postkutsche betreten?", r"\bnein\b|niemals|\bnie\b|nicht"),
    ("colt-express", "Darf ich statt einer Aktionskarte nochmal 3 Karten ziehen, wenn ich 2 Aktionskarten spielen muss?", r"\bnein\b|nicht"),
    ("king-of-tokyo", "Wie viele Siegpunkte braucht man, um zu gewinnen?", r"\b20\b"),
    ("king-of-tokyo", "Darf ich mich heilen, wenn ich in Tokyo bin?", r"\bnein\b|nicht|außerhalb"),
    ("king-of-tokyo", "Was passiert mit Tokyo Bay, wenn weniger als 5 Spieler übrig sind?", r"verlassen"),
    ("codenames", "Was passiert, wenn wir auf einen unbeteiligten Zuschauer tippen?", r"endet|vorbei|beendet|anderen? Team"),
    ("codenames", "Was passiert, wenn ein Team auf den Attentäter tippt?", r"verlier|verloren"),
    ("6-nimmt-30-jahre-edition", "Wann endet das Spiel?", r"\b66\b"),
    ("6-nimmt-30-jahre-edition", "Wer gewinnt das Spiel?", r"wenigsten"),
    ("skull-king", "Wenn zwei Piraten-Karten im selben Stich gespielt werden, welche gewinnt?", r"zuerst|erste"),
    ("skull-king", "Wie viele Minuspunkte gibt es pro Stich, den man zu viel oder zu wenig hat?", r"\b10\b|zehn"),
    ("pandemic", "Wie viele Handkarten darf man maximal behalten?", r"\b7\b|sieben"),
    ("pandemic", "Was passiert, wenn bei einer Epidemie nicht mehr genug Würfel da sind?", r"Niederlage|verlier|verloren"),
    ("faraway", "Wie viele Runden hat eine Partie?", r"\b8\b|acht"),
    ("faraway", "Wer gewinnt bei Punktegleichstand?", r"kleinsten|niedrigsten|geringsten"),
    ("hellapagos", "Wie viele Rationen Essen oder Wasser kann man höchstens im Vorrat haben?", r"\b36\b"),
    ("hellapagos", "Darf man den Obstkorb als zusätzliche Ration benutzen, um aufs Floß zu gehen?", r"\bnein\b|nicht|cannot"),
    ("hellapagos", "Wer bekommt am Ende Punkte?", r"Floß|raft|an Bord|aboard"),
    ("sky-team", "Wie viele Kaffee-Marker darf man höchstens haben?", r"\b3\b|drei"),
    ("sky-team", "Was passiert, wenn der Achsenpfeil ein X-Feld erreicht?", r"verl(iert|oren)|lose|Trudel|spin|Absturz"),
    ("carnival-of-monsters", "Was passiert bei einem Gleichstand um eine Trophäe?", r"keine?r?\b|niemand|kein"),
    ("carnival-of-monsters", "Wofür kann man Traumlande-Länderkarten verwenden?", r"Traumlande-Monster"),
    ("gunsen", "Wie verhält sich der Blutwert in Kämpfen?", r"tötet|töten"),
    ("gunsen", "Wer gewinnt, wenn zwei Klane gleichzeitig ihren 7. Erfolg erzielen?", r"am Zug"),
    ("gunsen", "Wie viele Erfolge braucht man zum Sieg?", r"\b7\b|sieben"),
    ("star-trek-captains-chair", "Was passiert, wenn der Zwischenfall-Stapel leer ist?", r"sofort|Brand"),
    ("star-trek-captains-chair", "Was passiert bei Gleichstand in der Endwertung?", r"beide"),
]

model, label = sys.argv[1], sys.argv[2]
# Default: the converted rulebooks the app uses; another dir compares converters.
rules_dir = sys.argv[3] if len(sys.argv) > 3 else "/home/mf1045/projects/erklaerbaer/regelwerke"
results = []
started = time.time()
with httpx.Client(timeout=1200) as client:
    for game, question, expected in QUESTIONS:
        rules = open(f"{rules_dir}/{game}.md", encoding="utf-8").read()
        for run in range(2):
            payload = {"model": model, "stream": False, "keep_alive": -1,
                       "options": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "num_predict": 1024},
                       "messages": [{"role": "system", "content": SYSTEM_PROMPT.format(rules=rules)},
                                    {"role": "user", "content": question}]}
            if model.startswith("gemma4"):
                payload["think"] = False
            t = time.time()
            r = client.post("http://localhost:11434/api/chat", json=payload).json()
            answer = r["message"]["content"].strip()
            ok = bool(re.search(expected, answer, re.IGNORECASE))
            results.append({"spiel": game, "frage": question, "lauf": run, "richtig": ok,
                            "sekunden": round(time.time() - t, 1), "antwort": answer})
            print(f"{'✅' if ok else '❌'} {game[:12]:12} {question[:50]:50} {time.time() - t:5.1f}s  {answer[:100]!r}", flush=True)
json.dump(results, open(f"/home/mf1045/projects/erklaerbaer/tools/symbol-experimente/vergleich-{label}.json", "w"),
          ensure_ascii=False, indent=1)
print(f"== {label}: {sum(r['richtig'] for r in results)}/{len(results)} richtig in {(time.time() - started) / 60:.0f} min")
