#!/usr/bin/env python3
"""A fake Ollama (stdlib only) for the Ubuntu checks: answers /api/chat with canned English JSON that
validates against esbi-cli's schemas, echoing the source title it finds in the prompt.
Also answers /api/tags, /api/version, /api/show (what `sb doctor` asks). Port 11434."""

import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open("/tmp/fake_ollama.log", "a")


def reply_for(schema: dict, user: str) -> dict:
    props = set(schema.get("properties", {}))
    m = re.search(r'title=("(?:[^"\\]|\\.)*")', user)
    title = json.loads(m.group(1)) if m else "Untitled source"
    page = re.findall(r'<page title="([^"]+)"', user)
    words = " ".join(re.sub(r"<[^>]+>", " ", user).split()[:40])
    if {"paragraphs", "insights"} <= props:  # Digest
        para = (
            f"The source titled {title} describes a harness that manages context and tools for an agent, "
            "and it explains how that layer verifies the results of each step before going on."
        )
        return {
            "paragraphs": [para, para + " It also covers memory.", para + " It ends with limits."],
            "insights": [
                {
                    "idea": "The harness manages the context of the agent.",
                    "why": "Without it the agent forgets what it was doing.",
                }
            ],
            "open_questions": ["How is the harness tested for the user?"],
        }
    if "answer" in props and "cited_pages" in props:  # AnswerPlan
        t = page[0] if page else "Nothing"
        return {
            "title": "Answer from the wiki",
            "one_liner": "A short answer taken from the wiki pages.",
            "answer": f"The source says: {words[:120]} [[{t}]]",
            "cited_pages": [t] if page else [],
        }
    if "one_liner" in props and "key_points" in props:  # EditPlan
        return {
            "title": title,
            "one_liner": "How a code harness manages an AI agent for the user.",
            "summary": "The article explains that a code harness organises the context and the tools of an agent.",
            "abstract": "This is the detailed summary of the article, written for the checks. " * 8,
            "insights": [
                {"idea": "The harness manages the context.", "why": "Without it the agent forgets its task."}
            ],
            "terms": [{"term": "harness", "definition": "The code layer that surrounds the model."}],
            "relations": [],
            "open_questions": ["How is the harness tested for the user?"],
            "key_points": ["Manages context", "Verifies results", "Runs the tools"],
            "tags": ["agents"],
            "concepts": [
                {
                    "title": "Code harness",
                    "aliases": [],
                    "description": "A code layer that surrounds the model and runs the tools.",
                }
            ],
            "entities": [],
            "related_pages": [],
            "contradictions": [],
        }
    if "connections" in props:
        return {"connections": []}
    if "points" in props:  # ChunkNotes / SectionNotes
        return {"points": ["The chunk discusses a harness for agents.", "It manages context.", "It runs tools."]}
    if "terms" in props:  # SearchTerms
        return {"terms": ["harness", "agent", "context"]}
    raise SystemExit(f"fake_ollama: unknown schema {sorted(props)}")


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        LOG.write(fmt % args + "\n")
        LOG.flush()

    def _send(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/version"):
            return self._send({"version": "0.99.0"})
        if self.path.startswith("/api/tags"):
            return self._send({"models": [{"name": "llama3.2:latest", "model": "llama3.2:latest"}]})
        self._send({}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path.startswith("/api/show"):
            return self._send({"details": {}, "model_info": {}})
        if self.path.startswith("/api/chat"):
            time.sleep(float(os.environ.get("DELAY", "0")))
            user = next((m["content"] for m in reversed(body["messages"]) if m["role"] == "user"), "")
            out = json.dumps(reply_for(body.get("format") or {}, user))
            return self._send({"message": {"role": "assistant", "content": out}, "prompt_eval_count": 10, "eval_count": 10})
        self._send({}, 404)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "11434"))), H).serve_forever()
