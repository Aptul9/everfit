"""Finta API di Gemini per le prove: risposte con schema (prova della chiave, parere, foto), l'assistente (testo piu'
azioni, scelte da qualche parola della domanda), elenco dei modelli e un modello "sparito" per provare il ripiego.

    finta_gemini2.py <porta> [modello che risponde 404]

Parole che fanno fare qualcosa all'assistente finto: pizza, gelato, acqua, camminata, "peso 62,5", salmone (cambia la
cena del giovedi'), ripristina, "piatto nuovo", "togli la voce", "elimina il piatto", rotto (un'azione che non sta in
piedi), prova400 (rifiuta lo schema: il server deve riprovare chiedendo solo JSON).
Limiti: limite429 (pieno il modello principale, risponde quello "lite"), limitetutti (pieni tutti i modelli di Gemini,
riprovare tra 7 secondi), limitegiorno (finita la quota del giorno), sovraccarico (503 dal modello principale),
giututto (503 da tutti i modelli di Gemini),
appeso (il modello principale non risponde per 5 secondi: chi chiede deve stancarsi prima), servetutto (con le istruzioni di base risponde
che gli servono i dati completi).
Azioni semplici per il piano: "obiettivo calorie", "quantita riso", "orario cena". "dice fatto": risponde che ha fatto
senza mandare azioni. C'e' anche una finta Ollama (/api/chat): lento (ci mette un secondo e mezzo), nopensa (rifiuta
"think").
Sulla stessa porta c'e' anche una finta Mistral (/v1/chat/completions, /v1/models): mistralpieno (pieno il modello
principale, risponde quello leggero), mistralpienotutto (pieni tutti), mistralchiusi (i modelli grandi hanno un limite
di zero richieste al minuto, come con il piano gratuito: rispondono solo i "ministral"), mistraltier (il modello
principale risponde 403 "non compreso nel piano"), mistralsenzapiano (limite zero su tutti), mistralgrandipieni
(pieni, non chiusi, i modelli grandi), mistralconv (i grandi chiusi per chat/completions ma aperti per l'altra strada,
/v1/conversations: e' quello che fa il piano gratuito vero).
"""
import io
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHIAVE_BUONA = "AQ.finta-chiave_di_prova_1234567890abcdef"
SPARITO = sys.argv[2] if len(sys.argv) > 2 else None
CHIAVE_MISTRAL = "finta0chiave0di0mistral0123456789"
MODELLI_MISTRAL = ["mistral-medium-latest", "mistral-small-latest", "mistral-large-latest", "codestral-latest", "ministral-14b-latest", "ministral-8b-latest"]


def limite(quota, attesa):
    dettagli = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaMetric": "generativelanguage.googleapis.com/x", "quotaId": quota}]}]
    if attesa:
        dettagli.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": attesa})
    return {"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.", "status": "RESOURCE_EXHAUSTED", "details": dettagli}}


MODELLI = ["gemini-3.8-flash", "gemini-4.0-flash", "gemini-4.0-flash-lite", "gemini-4.5-flash-preview-09", "gemini-4.0-pro", "gemini-4.0-flash-image"]


def azioni_per(domanda, istruzioni):
    d = domanda.lower()
    fuori = []
    if "pizza" in d:
        fuori.append({"tipo": "mangiato", "pasto": "cena", "nome": "Pizza margherita", "quantita": "1 pizza", "kcal": 820, "proteine": 33,
                      "carboidrati": 105, "grassi": 28, "al_posto": "tutto", "foto_di": "cena-libera"})
    if "gelato" in d:
        fuori.append({"tipo": "mangiato", "pasto": "fuori", "nome": "Gelato", "quantita": "2 gusti", "kcal": 250, "proteine": 4, "carboidrati": 32, "grassi": 11, "al_posto": "niente"})
    if "acqua" in d:
        fuori.append({"tipo": "acqua", "ml": 500})
    if "camminat" in d:
        fuori.append({"tipo": "movimento", "attivita": "camminata", "minuti": 30})
    peso = re.search(r"peso (\d+(?:[.,]\d+)?)", d)
    if peso:
        fuori.append({"tipo": "peso", "kg": float(peso.group(1).replace(",", "."))})
    if "salmone" in d and "piatto nuovo" not in d:
        fuori.append({"tipo": "cambia_pasto", "giorni": [3], "pasto": "cena", "ricetta": "salmone-patate"})
    if "ripristina" in d:
        fuori.append({"tipo": "ripristina_pasto", "giorni": [3], "pasto": "cena"})
    if "piatto nuovo" in d:
        fuori.append({"tipo": "nuovo_piatto", "nome": "Riso, salmone e ceci", "pasto": "cena", "minuti": 20, "foto_di": "salmone-riso", "giorni": [1],
                      "ingredienti": [{"cibo": "riso", "grammi": 90, "grammi_palestra": 110}, {"cibo": "salmone", "grammi": 150, "grammi_palestra": 150},
                                      {"cibo": "", "nome": "Ceci in scatola", "reparto": "Dispensa", "grammi": 120, "grammi_palestra": 120, "kcal": 120, "proteine": 7, "carboidrati": 15, "grassi": 2.5}],
                      "passi": ["Cuoci il riso.", "Scotta il salmone in padella 3 minuti per lato.", "Scola i ceci e unisci tutto."]})
    if "togli la voce" in d:
        voce = re.search(r"Voci del diario di oggi \(identificativo: cosa\): ([a-z0-9]+):", istruzioni)
        fuori.append({"tipo": "togli_voce", "voce": voce.group(1) if voce else "inesistente"})
    if "elimina il piatto" in d:
        piatto = re.search(r"- (mio-[a-z0-9-]+):", istruzioni)
        fuori.append({"tipo": "togli_piatto", "ricetta": piatto.group(1) if piatto else "mio-inesistente"})
    if "rotto" in d:
        fuori.append({"tipo": "cambia_pasto", "giorni": [2], "pasto": "cena", "ricetta": "ricetta-che-non-esiste"})
        fuori.append({"tipo": "cancella_tutto"})
    # i grammi di un ingrediente solo per oggi, una voce del diario con un'altra quantita', un pasto mangiato in parte
    if "dose pollo" in d:
        fuori.append({"tipo": "dose", "pasto": "pranzo", "cibo": "pollo", "grammi": 137})
        fuori.append({"tipo": "dose", "pasto": "pranzo", "cibo": "riso"})   # senza grammi: non passa
    if "cambia voce" in d:
        fuori.append({"tipo": "cambia_voce", "voce": "abc123", "quantita": "35 g"})
        fuori.append({"tipo": "cambia_voce", "voce": "abc123", "quantita": "tanta"})   # senza numero: non passa
    if "solo pasta" in d:
        fuori.append({"tipo": "pasto_fatto", "pasto": "pranzo", "fatto": True, "solo": ["pasta"], "senza": []})
    # ---- la modifica libera: l'assistente riscrive direttamente i dati
    mod = lambda descrizione, *ops: fuori.append({"tipo": "modifica", "descrizione": descrizione, "operazioni": list(ops)})
    metti = lambda percorso, valore: {"op": "metti", "percorso": percorso, "valore": valore}
    if "calorie a 2500" in d:
        mod("Giorni di palestra: 2.500 kcal", metti(["mie", "obiettivi", "train", "kcal"], 2500))
    if "pasta a 150" in d:
        mod("Pasta al tonno: 150 g di pasta anche a riposo", metti(["mie", "ricette", "pasta-tonno", "ing"], [["pasta", 150, 150], ["tonno", 168, 168], ["pomodorini", 150, 150], ["olio", 10, 10]]))
    if "cambia la scheda" in d:
        mod("Scheda A: panca piana al posto delle spinte, 5 serie", metti(["mie", "schede", "A", "es"], [["bench-press", 5, "6-8", 150], ["lat-pulldown", 4, "8-12", 120], ["leg-press", 3, "8-12", 150]]))
    if "nascondi l'acqua" in d:
        mod("Oggi senza l'acqua; cena alle 21:00", metti(["opzioni", "casa", "acqua"], False), metti(["mie", "momenti", "cena", "ora"], {"rest": "21:00", "train": "21:00"}))
    if "seduta di ieri" in d:
        ieri = re.search(r"Ieri: (\d{4}-\d{2}-\d{2})", istruzioni)
        mod("Seduta di ieri: scheda A", {"op": "aggiungi", "percorso": ["sedute"], "valore": {"d": ieri.group(1) if ieri else "2026-10-10", "w": "A", "voci": [
            {"es": "incline-db-press", "serie": [{"kg": 22, "rip": 8}, {"kg": 22, "rip": 8}, {"kg": 22, "rip": 7}]}]}})
    if "togli la sera" in d:
        mod("Domenica senza lo spuntino dopo cena", metti(["mie", "settimana", "6", "pasti", "sera"], None))
    if "spuntino nuovo" in d:
        mod("Uno spuntino a meta' mattina il lunedi'", metti(["mie", "momenti", "spuntino"], {"n": "Spuntino", "tipo": "merenda", "ora": {"rest": "10:30", "train": "10:30"}}),
            metti(["mie", "settimana", "0", "pasti", "spuntino"], "uova-gallette"))
    if "giorni di allenamento" in d:
        mod("Allenamenti: martedi' al posto del lunedi'", metti(["mie", "settimana", "0", "tipo"], "rest"), metti(["mie", "settimana", "1", "tipo"], "train"), metti(["mie", "settimana", "1", "scheda"], "A"))
    if "modifica sbagliata" in d:
        mod("Un piatto con un cibo che non esiste", metti(["mie", "ricette", "mio-finto"], {"n": "Finto", "tipo": "pasto", "ing": [["cibo-che-non-esiste", 100, 100]]}))
    if "modifica vietata" in d:
        mod("La conversazione", metti(["chat", 0, "t"], "ciao"))
    if "obiettivo calorie" in d:
        fuori.append({"tipo": "obiettivo", "giorni": "palestra", "kcal": 2000})
    if "obiettivo pieno" in d:   # come fa a volte un modello piccolo: riscrive anche i numeri che nessuno ha chiesto di cambiare
        fuori.append({"tipo": "obiettivo", "giorni": "palestra", "kcal": 2000, "proteine": 150, "carboidrati": 200, "grassi": 55})
    if "quantita riso" in d:
        fuori.append({"tipo": "quantita", "ricetta": "pollo-riso", "cibo": "riso", "grammi": 100, "grammi_palestra": 120})
    if "orario cena" in d:
        fuori.append({"tipo": "orario", "pasto": "cena", "ora": "21.00"})
    if "birre storte" in d:   # conti che non tornano: 340 kcal con 40 g di grassi. Alla seconda richiesta ("Controlla i numeri") li sistema
        giusti = "controlla i numeri" in d and "non sistemare" not in d
        fuori.append({"tipo": "mangiato", "pasto": "fuori", "nome": "Birra media", "quantita": "2 birre", "kcal": 340, "proteine": 2, "carboidrati": 28,
                      "grassi": 0 if giusti else 40, "al_posto": "tutto"})
    if "tema chiaro" in d:
        fuori.append({"tipo": "tema", "aspetto": "chiaro"})
    if "misure" in d:
        fuori.append({"tipo": "misure", "cm": {"vita": 78.5, "collo": 37}})
    return fuori


class Finta(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def rispondi(self, codice, obj, intestazioni=None):
        corpo = json.dumps(obj).encode()
        self.send_response(codice)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        for nome, valore in (intestazioni or {}).items():
            self.send_header(nome, valore)
        self.end_headers()
        self.wfile.write(corpo)

    def conversazioni(self, corpo):
        """L'altra strada dell'API di Mistral: la stessa finta, con richiesta e risposta scritte nell'altro modo."""
        ingressi = corpo.get("inputs")
        messaggi = [{"role": "system", "content": corpo["instructions"]}] if corpo.get("instructions") else []
        messaggi += [{"role": "user", "content": ingressi}] if isinstance(ingressi, str) else [{"role": v["role"], "content": v["content"]} for v in ingressi]
        return self.mistral({"model": corpo.get("model"), "messages": messaggi, "response_format": (corpo.get("completion_args") or {}).get("response_format")},
                            strada="conversations")

    def mistral(self, corpo, strada="chat"):
        if self.headers.get("Authorization") != "Bearer " + CHIAVE_MISTRAL:
            return self.rispondi(401, {"message": "Unauthorized", "request_id": "x"})
        modello = corpo.get("model")
        if modello == SPARITO or modello not in MODELLI_MISTRAL:
            return self.rispondi(400, {"object": "error", "message": "Invalid model: %s" % modello, "type": "invalid_model", "param": None, "code": "1500"})
        messaggi = corpo["messages"]
        istruzioni = messaggi[0]["content"] if messaggi[0]["role"] == "system" else ""
        ultimo = messaggi[-1]["content"]
        if isinstance(ultimo, list):
            foto = next((p["image_url"] for p in ultimo if p.get("type") == "image_url"), None)
            ultimo = next(p["text"] for p in ultimo if p.get("type") == "text")
            if foto:
                ultimo += " [foto %s, %d caratteri]" % (foto.split(";")[0].replace("data:", ""), len(foto.split(",", 1)[1]))
                if "segna" in ultimo.lower():
                    ultimo += " pizza"
        if ultimo.startswith("Controlla i numeri"):   # la seconda richiesta sui conti: vale anche la domanda di prima
            ultimo = " ".join(str(m["content"]) for m in messaggi if m["role"] == "user")
        # modelli che il piano non lascia usare: limite di zero richieste al minuto (tutti, o solo i grandi)
        grande = not modello.startswith("ministral")
        chiuso = "mistralsenzapiano" in ultimo or ("mistralchiusi" in ultimo and grande)
        if strada == "conversations" and (chiuso or ("mistraltier" in ultimo and modello == "mistral-medium-latest")):
            return self.rispondi(403, {"object": "Error", "message": "Model %s is not available in your subscription tier." % modello, "type": "invalid_request_error", "code": 3005})
        # "mistralconv": come con il piano gratuito vero, i grandi sono chiusi per chat/completions e aperti per conversations
        if chiuso or ("mistralconv" in ultimo and grande and strada == "chat"):
            return self.rispondi(429, {"object": "error", "message": "Rate limit exceeded", "type": "rate_limited", "param": None, "code": "1300"},
                                 {"x-ratelimit-limit-req-minute": "0", "x-ratelimit-remaining-req-minute": "0"})
        if "mistraltier" in ultimo and modello == "mistral-medium-latest":
            return self.rispondi(403, {"object": "error", "message": "This model is not available in your subscription tier", "type": "tier_not_allowed", "param": None, "code": "1910"})
        if ("mistralpieno" in ultimo and modello != "mistral-small-latest") or "mistralpienotutto" in ultimo or (
                "mistralgrandipieni" in ultimo and not modello.startswith("ministral")):
            return self.rispondi(429, {"message": "Requests rate limit exceeded"}, {"Retry-After": "3"})
        forma = (corpo.get("response_format") or {}).get("type")
        in_json = forma in ("json_object", "json_schema")
        ruoli = [m["role"] for m in messaggi]
        print("mistral (%s): modello %s, ruoli %s, %s" % (strada, modello, ruoli, "json con schema" if forma == "json_schema" else "json" if in_json else "testo"), flush=True)
        if "AZIONI" in istruzioni or not in_json:
            testo = "[%s] Hai chiesto: %s. %d messaggi%s%s%s." % (modello, ultimo, len(ruoli), ", con schema" if forma == "json_schema" else "",
                                                                 ", stato completo" if "STATO (JSON" in istruzioni else "",
                                                                 ", per conversations" if strada == "conversations" else "")
            if in_json:
                testo = json.dumps({"risposta": testo, "azioni": azioni_per(ultimo, istruzioni)})
        elif '"ok"' in istruzioni:
            testo = json.dumps({"ok": True})
        elif '"riassunto"' in istruzioni:
            testo = json.dumps({"riassunto": "Parere di Mistral.", "forti": ["uno"], "deboli": ["due"], "consigli": ["tre"]})
        else:
            testo = json.dumps({"piatto": "Riso con pollo", "voci": [{"nome": "Riso", "grammi": 250, "kcal": 325, "proteine": 7, "carboidrati": 70, "grassi": 1}], "sicurezza": "alta"})
        uso = {"prompt_tokens": len(json.dumps(messaggi)) // 4, "completion_tokens": len(testo) // 4}
        if strada == "conversations":
            return self.rispondi(200, {"object": "conversation.response", "conversation_id": "conv_x", "usage": uso, "outputs": [
                {"object": "entry", "type": "message.output", "role": "assistant", "model": modello, "content": [{"type": "text", "text": testo}]}]})
        self.rispondi(200, {"id": "x", "object": "chat.completion", "model": modello,
                            "choices": [{"index": 0, "message": {"role": "assistant", "content": testo}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": len(json.dumps(messaggi)) // 4, "completion_tokens": len(testo) // 4}})

    def ollama(self, corpo):
        messaggi = corpo["messages"]
        istruzioni = messaggi[0]["content"] if messaggi[0]["role"] == "system" else ""
        ultimo = messaggi[-1]["content"]
        if messaggi[-1].get("images"):
            ultimo += " [foto, %d caratteri]" % len(messaggi[-1]["images"][0])
            if "segna" in ultimo.lower():
                ultimo += " pizza"
        if ultimo.startswith("Controlla i numeri"):   # la seconda richiesta sui conti: vale anche la domanda di prima
            ultimo = " ".join(str(m["content"]) for m in messaggi if m["role"] == "user")
        if "nopensa" in ultimo and "think" in corpo:
            return self.rispondi(400, {"error": "registry.ollama.ai/library/%s does not support thinking" % corpo.get("model")})
        if "lento" in ultimo:
            time.sleep(1.5)
        forma = corpo.get("format")
        if os.environ.get("FINTA_SCARICA"):   # l'ultima richiesta resta in un file: serve a rifarla uguale altrove
            io.open(os.path.join(os.environ["FINTA_SCARICA"], "ultima_richiesta.json"), "w", encoding="utf-8").write(json.dumps(corpo, ensure_ascii=False))
        come = "con forma" if isinstance(forma, dict) else "senza forma"
        print("ollama: modello %s, %d messaggi, %s, fili %s" % (corpo.get("model"), len(messaggi), come, (corpo.get("options") or {}).get("num_thread")), flush=True)
        if "AZIONI" in istruzioni:
            testo = json.dumps({"azioni": azioni_per(ultimo, istruzioni), "risposta": "[%s] Hai chiesto: %s. %d messaggi, %s." % (corpo.get("model"), ultimo, len(messaggi) - 1, come)})
        elif isinstance(forma, dict) and "ok" in forma.get("properties", {}):
            testo = json.dumps({"ok": True})
        else:
            testo = json.dumps({"piatto": "Riso con pollo", "voci": [{"nome": "Riso", "grammi": 250, "kcal": 325, "proteine": 7, "carboidrati": 70, "grassi": 1}], "sicurezza": "alta"})
        self.rispondi(200, {"model": corpo.get("model"), "message": {"role": "assistant", "content": testo}, "done": True, "done_reason": "stop",
                            "prompt_eval_count": len(json.dumps(messaggi)) // 4, "prompt_eval_duration": 2000000000,
                            "eval_count": len(testo) // 4, "eval_duration": 1000000000, "total_duration": 3000000000})

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            if self.headers.get("Authorization") != "Bearer " + CHIAVE_MISTRAL:
                return self.rispondi(401, {"message": "Unauthorized", "request_id": "x"})
            return self.rispondi(200, {"object": "list", "data": [{"id": m, "object": "model", "capabilities": {"completion_chat": True, "vision": "codestral" not in m}}
                                                                  for m in MODELLI_MISTRAL if m != SPARITO]})
        if self.headers.get("x-goog-api-key") != CHIAVE_BUONA:
            return self.rispondi(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key."}})
        self.rispondi(200, {"models": [{"name": "models/" + m, "supportedGenerationMethods": ["generateContent", "countTokens"]} for m in MODELLI if m != SPARITO]})

    def do_POST(self):
        grezzo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        corpo = json.loads(grezzo) if grezzo else {}
        if self.path.startswith("/v1/chat/"):
            return self.mistral(corpo)
        if self.path.startswith("/v1/conversations"):
            if self.headers.get("Authorization") != "Bearer " + CHIAVE_MISTRAL:
                return self.rispondi(401, {"message": "Unauthorized", "request_id": "x"})
            return self.conversazioni(corpo)
        if self.path == "/api/chat":
            return self.ollama(corpo)
        if self.path.startswith("/spinta/"):   # il finto servizio di notifiche: conta le sveglie arrivate
            buona = self.headers.get("Authorization", "").startswith("vapid t=") and self.headers.get("TTL")
            print("spinta: %s %s" % (self.path, "firmata" if buona else "SENZA FIRMA"), flush=True)
            return self.rispondi(410 if "andata" in self.path else 201 if buona else 403, {})
        if self.path == "/api/generate":   # la richiesta vuota che tiene il modello in memoria
            print("ollama: tenuto sveglio %s" % corpo.get("model"), flush=True)
            return self.rispondi(200, {"model": corpo.get("model"), "response": "", "done": True, "done_reason": "load"})
        modello = self.path.split("/models/")[-1].split(":")[0]
        if self.headers.get("x-goog-api-key") != CHIAVE_BUONA:
            return self.rispondi(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}})
        if modello == SPARITO:
            return self.rispondi(404, {"error": {"code": 404, "message": "models/%s is not found for API version v1beta" % modello, "status": "NOT_FOUND"}})
        gc = corpo.get("generationConfig", {})
        campi = gc.get("response_schema", {}).get("properties", {})
        istruzioni = corpo.get("system_instruction", {}).get("parts", [{}])[0].get("text", "")
        in_json = gc.get("response_mime_type") == "application/json"
        if "azioni" in campi or (in_json and not campi and "AZIONI" in istruzioni) or not in_json:   # l'assistente (o la vecchia conversazione a testo libero)
            ruoli = [c.get("role") for c in corpo["contents"]]
            parti = corpo["contents"][-1]["parts"]
            ultima = next(p["text"] for p in parti if "text" in p)
            foto = next((p["inline_data"] for p in parti if "inline_data" in p), None)
            if foto:   # una foto con la domanda: l'assistente finto dice di averla vista (e "segna" quello che c'e')
                ultima += " [foto %s, %d caratteri]" % (foto["mime_type"], len(foto["data"]))
                if "segna" in ultima.lower():
                    ultima += " pizza"
            if "giututto" in ultima:   # Gemini sovraccarico con tutti i modelli: la domanda deve passare a un altro servizio
                return self.rispondi(503, {"error": {"code": 503, "message": "This model is currently experiencing high demand.", "status": "UNAVAILABLE"}})
            if "sovraccarico" in ultima and "lite" not in modello:
                return self.rispondi(503, {"error": {"code": 503, "message": "This model is currently experiencing high demand.", "status": "UNAVAILABLE"}})
            if "appeso" in ultima and "lite" not in modello:
                time.sleep(5)
                try:
                    return self.rispondi(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps({"risposta": "troppo tardi", "azioni": []})}]}, "finishReason": "STOP"}]})
                except OSError:
                    return None   # chi chiedeva se n'e' gia' andato
            if "limitegiorno" in ultima:
                return self.rispondi(429, limite("GenerateRequestsPerDayPerProjectPerModel-FreeTier", None))
            if "limitetutti" in ultima or ("limite429" in ultima and "lite" not in modello):
                return self.rispondi(429, limite("GenerateContentInputTokensPerModelPerMinute-FreeTier", "7s"))
            if '"serve"' in istruzioni and "servetutto" in ultima:
                print("assistente: chiede i dati completi", flush=True)
                return self.rispondi(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps({"serve": "tutto"})}]}, "finishReason": "STOP"}]})
            if "prova400" in ultima and campi:
                print("assistente: schema rifiutato apposta", flush=True)
                return self.rispondi(400, {"error": {"code": 400, "message": "The specified schema produces a constraint that has too many states for serving.", "status": "INVALID_ARGUMENT"}})
            ok = ruoli[0] == "user" and ruoli[-1] == "user" and "CONTESTO" in istruzioni
            testo = "[%s] Hai chiesto: %s. **Contesto** %s, %d messaggi, %d caratteri di istruzioni.\n- primo punto\n- secondo punto" % (
                modello, ultima, "presente" if ok else "MANCANTE", len(ruoli), len(istruzioni))
            print("chat: modello %s, ruoli %s, %s, catalogo %s" % (modello, ruoli, "con schema" if campi else "json a parole" if in_json else "testo",
                                                               "presente" if "CATALOGO" in istruzioni else "assente"), flush=True)
            if "dice fatto" in ultima:
                testo = "Fatto: ho segnato tutto."
            if in_json:
                testo = json.dumps({"risposta": testo, "azioni": azioni_per(ultima, istruzioni)})
            return self.rispondi(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": "penso...", "thought": True}, {"text": testo}]}, "finishReason": "STOP"}]})
        if "ok" in campi:
            esito = {"ok": True}
        elif "riassunto" in campi:
            esito = {"riassunto": "Parere di prova.", "forti": ["uno"], "deboli": ["due"], "consigli": ["tre"]}
        else:
            esito = {"piatto": "Riso con pollo", "voci": [{"nome": "Riso", "grammi": 250, "kcal": 325, "proteine": 7, "carboidrati": 70, "grassi": 1}], "sicurezza": "alta"}
        print("schema: modello %s, campi %s" % (modello, sorted(campi)), flush=True)
        self.rispondi(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(esito)}]}, "finishReason": "STOP"}]})


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Finta).serve_forever()
