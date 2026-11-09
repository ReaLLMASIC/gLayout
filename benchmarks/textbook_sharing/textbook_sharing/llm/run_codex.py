"""Run model sessions with an OpenAI model through the official Codex CLI (`codex exec`, non-interactive).

Isolation: every call runs in an empty temporary directory with the shell tool and every other tool family disabled,
web search disabled, user configuration and rules ignored, and no session files kept (ephemeral).  The model therefore
sees only the prompt text.  The JSONL event log of every call is stored and checked: any item other than a message or
reasoning (for example a command execution) marks the call as an isolation breach and the session is flagged.
The CLI must already be logged in; this script never reads or writes credentials.
Conversation: each proposal is a fresh, stateless call whose prompt contains the interface, the worked examples, the
task and every earlier proposal with its tool report.  Budget per session: max_proposals (rejected and repeated
proposals count).  After each proposal the evaluator (llm/evaluate.py) builds and verifies the plan and writes the
report that goes into the next prompt.

usage: python -m textbook_sharing.llm.run_codex <config.json>
config keys: model, model_tag, effort, max_proposals, reps, parallel (default 3), interface ("sharing" | "base"),
  examples (path to examples.md), only (optional list of task ids), reps_only (optional list of repetition numbers),
  codex (optional path of the CLI, default "codex" on PATH),
  evaluator_cmd (optional; default runs the evaluator in this Python; use e.g.
  "scripts/run_in_container.sh 'python -m textbook_sharing.llm.evaluate {session} {k}'" when the EDA tools live in the
  container)."""
import json, shlex, subprocess, sys, tempfile, time, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from textbook_sharing import paths

DISABLE = ["shell_tool", "apps", "plugins", "browser_use", "browser_use_external", "computer_use", "in_app_browser", "image_generation", "skill_search", "sleep_tool"]
lock = threading.Lock()


def call_codex(codex, prompt, model, effort, logdir, tag):
    with tempfile.TemporaryDirectory(prefix="codex_iso_") as tmp:
        cmd = [codex, "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "-s", "read-only", "-C", tmp,
               "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-c", 'web_search="disabled"', "--json"]
        for f in DISABLE:
            cmd += ["--disable", f]
        cmd += ["-"]
        t0 = time.time()
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=1800, cwd=tmp)
        dt = time.time() - t0
    (logdir / f"{tag}_events.jsonl").write_text(r.stdout); (logdir / f"{tag}_stderr.txt").write_text(r.stderr[-20000:])
    msg = ""; usage = None; kinds = {}; breach = False
    for line in r.stdout.splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        it = e.get("item") or {}
        if it.get("type"):
            kinds[it["type"]] = kinds.get(it["type"], 0) + 1
        if it.get("type") == "agent_message":
            msg = it.get("text", "")
        elif it.get("type") and it.get("type") not in ("agent_message", "reasoning"):
            breach = True
        if e.get("type") == "turn.completed":
            usage = e.get("usage")
    return {"answer": msg, "usage": usage, "item_kinds": kinds, "isolation_breach": breach, "rc": r.returncode, "seconds": round(dt, 1)}


def evaluate(cfg, sd, k):
    tmpl = cfg.get("evaluator_cmd")
    if tmpl:
        cmd = tmpl.format(session=shlex.quote(str(sd)), k=k)
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(paths.ROOT))
    else:
        r = subprocess.run([sys.executable, "-m", "textbook_sharing.llm.evaluate", str(sd), str(k)], capture_output=True, text=True, cwd=str(paths.ROOT))
    fb = sd / f"p{k}_feedback.txt"
    return fb.read_text() if fb.exists() and fb.read_text().strip() else f"(evaluator error: {r.stderr[-400:]})"


def run_session(cfg, task, rep):
    model, tag = cfg["model"], cfg["model_tag"]
    sd = paths.MODEL_RUNS / tag / task["task_id"] / f"r{rep}"; sd.mkdir(parents=True, exist_ok=True)
    if (sd / "session_done.json").exists():
        return json.load(open(sd / "session_done.json"))
    tdir = paths.MODEL_TASKS / task["task_id"]
    interface = Path(__file__).with_name("interface_base.md" if cfg.get("interface") == "base" else "interface_sharing.md").read_text()
    taskmd = (tdir / "task.md").read_text(); examples = Path(cfg["examples"]).read_text()
    sess = {"task_id": task["task_id"], "case_dir": task["case_dir"], "model_tag": tag, "model": model, "rep": rep, "entry": "codex-cli exec (OpenAI)",
            "reasoning_effort": cfg["effort"], "max_proposals": cfg["max_proposals"], "interface": cfg.get("interface", "sharing"),
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    json.dump(sess, open(sd / "session.json", "w"), indent=1)
    history = []; calls = []
    for k in range(1, cfg["max_proposals"] + 1):
        hist = "".join(f"\n## Your proposal {h['k']}\n{h['answer']}\n\n## Tool report for proposal {h['k']}\n{h['feedback']}\n" for h in history)
        prompt = (f"{interface}\n\n# Worked examples (development circuits, not the task circuit)\n{examples}\n\n{taskmd}\n{hist}\n"
                  f"Now give proposal {k} of at most {cfg['max_proposals']} (remaining after this one: {cfg['max_proposals'] - k}). "
                  "Reply with exactly one ```python block containing `plans = {...}`, or with the single word FINAL to stop.")
        (sd / f"p{k}_prompt.md").write_text(prompt)
        c = call_codex(cfg.get("codex", "codex"), prompt, model, cfg["effort"], sd, f"p{k}")
        calls.append({"k": k, **{x: c[x] for x in ("usage", "item_kinds", "isolation_breach", "rc", "seconds")}, "prompt_chars": len(prompt), "answer_chars": len(c["answer"])})
        (sd / f"p{k}_answer.md").write_text(c["answer"])
        if c["answer"].strip().upper().startswith("FINAL") and "```" not in c["answer"]:
            break
        fb = evaluate(cfg, sd, k)
        history.append({"k": k, "answer": c["answer"], "feedback": fb})
        with lock:
            print(tag, task["task_id"], f"r{rep}", f"p{k}", fb.splitlines()[0][:150] if fb else "", c["seconds"], "s", flush=True)
    done = {"task_id": task["task_id"], "rep": rep, "model_tag": tag, "n_proposals": len(history), "calls": calls,
            "isolation_breach_any": any(x["isolation_breach"] for x in calls), "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    json.dump(done, open(sd / "session_done.json", "w"), indent=1)
    return done


def main():
    cfg = json.load(open(sys.argv[1]))
    tasks = json.load(open(paths.MODEL_TASKS / "tasks.json"))["tasks"]
    if cfg.get("only"):
        tasks = [t for t in tasks if t["task_id"] in cfg["only"]]
    jobs = [(t, rep) for rep in range(1, cfg["reps"] + 1) for t in tasks]
    if cfg.get("reps_only"):
        jobs = [(t, rep) for t, rep in jobs if rep in cfg["reps_only"]]
    with ThreadPoolExecutor(cfg.get("parallel", 3)) as ex:
        for d in ex.map(lambda tr: run_session(cfg, *tr), jobs):
            print("DONE", d["task_id"], d["rep"], d["n_proposals"], "breach" if d["isolation_breach_any"] else "", flush=True)


if __name__ == "__main__":
    main()
