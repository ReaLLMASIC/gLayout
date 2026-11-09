"""Model sessions run through an agent interface (used for the Anthropic model).

Each session is a folder that holds only README.md (the session rules), interface.md, examples.md, task.md and
submit.sh.  The agent writes p<k>_answer.md and runs `bash submit.sh <k>`, which hands the answer to the evaluator
(llm/evaluate.py, the same evaluator as for the Codex sessions) and prints the tool report.  The agent is started with
LAUNCH_TEXT (folder filled in); nothing else is given to it.  Afterwards every tool call in the agent transcripts is
audited: allowed are Read/Write/Edit of a file inside the session folder and `bash submit.sh <k>` run inside it.

  prepare <config.json>
      config keys: model_tag, workspace (folder for the agent-side session folders), reps, max_proposals (default 8),
      interface ("sharing" | "base"), examples (path to examples.md), only (optional task ids), model (optional),
      evaluator_cmd (optional; '{session}' and '{k}' are filled in, default runs the evaluator in this Python).
      Creates <workspace>/<model_tag>/<task>/r<rep>/ and the evaluator-side <runs>/models/<model_tag>/<task>/r<rep>/
      session.json, and writes <workspace>/<model_tag>/sessions.json (the list of agent-side folders).
  launch <session folder>
      prints the text to start the agent with.
  audit <map.json> <transcript dir> <out.json>
      map.json: agent id -> session folder; transcripts are JSONL files agent-<id>.jsonl in which every assistant
      message lists its tool calls as content items {"type": "tool_use", "name", "input"}.
      Classes of a flagged call: in_folder_edit (text processing of the session's own files: a protocol deviation that
      gives the agent no outside information) and isolation_breach (anything else: outside paths, listing or search,
      network).  Flagged sessions are then reviewed by hand."""
import json, re, shlex, sys
from pathlib import Path
from textbook_sharing import paths

RULES = """# Session rules
You are the model under test in a controlled experiment.  Work ONLY with the files in this folder:
read README.md, interface.md, examples.md and task.md; write your proposals as p1_answer.md, p2_answer.md, ...
(each containing exactly one ```python block with `plans = {{...}}`, as interface.md describes); after writing
p<k>_answer.md run exactly `bash submit.sh <k>` (k = proposal number) and read the tool report it prints.
You have at most {max_proposals} proposals; rejected and repeated proposals also count.  You may stop early.
Do not open, list or search any other file or directory, and do not run any other command.
When you stop, reply with one line: the number of the proposal you consider best.
"""

LAUNCH_TEXT = """You are the model under test in a controlled analog-layout experiment. Your session folder is:
{folder}

Read README.md in that folder first and follow it exactly. Use only the files in that folder (README.md, interface.md, examples.md, task.md). Write each proposal with the Write tool as p<k>_answer.md in that folder, then run exactly this Bash command (with k replaced by the proposal number) to submit it and read the tool report:
cd {folder} && bash submit.sh k
Do not open, list or search any other file or directory, and do not run any other command. Run the submit command in the foreground and wait for its report. You have at most {max_proposals} proposals. When you stop, reply with one line: the number of the proposal you consider best."""

SUBMIT = """#!/bin/bash
# sends p$1_answer.md to the evaluator and prints the tool report (the only command the model may run)
set -e
k=$1; [ -f "p${{k}}_answer.md" ] || {{ echo "missing p${{k}}_answer.md"; exit 1; }}
cp "p${{k}}_answer.md" {session}/"p${{k}}_answer.md"
(cd {root} && {evaluator}) >/dev/null 2>&1 || true
cat {session}/"p${{k}}_feedback.txt"
"""


def prepare(cfg):
    tag = cfg["model_tag"]; ws = Path(cfg["workspace"]).resolve(); nmax = cfg.get("max_proposals", 8)
    interface = Path(__file__).with_name("interface_base.md" if cfg.get("interface") == "base" else "interface_sharing.md").read_text()
    examples = Path(cfg["examples"]).read_text()
    tasks = json.load(open(paths.MODEL_TASKS / "tasks.json"))["tasks"]
    if cfg.get("only"):
        tasks = [t for t in tasks if t["task_id"] in cfg["only"]]
    made = []
    for rep in range(1, cfg["reps"] + 1):
        for t in tasks:
            sd = ws / tag / t["task_id"] / f"r{rep}"; sd.mkdir(parents=True, exist_ok=True)
            ev = (paths.MODEL_RUNS / tag / t["task_id"] / f"r{rep}").resolve(); ev.mkdir(parents=True, exist_ok=True)
            (sd / "README.md").write_text(RULES.format(max_proposals=nmax))
            (sd / "interface.md").write_text(interface); (sd / "examples.md").write_text(examples)
            (sd / "task.md").write_text((paths.MODEL_TASKS / t["task_id"] / "task.md").read_text())
            tmpl = cfg.get("evaluator_cmd") or f"{shlex.quote(sys.executable)} -m textbook_sharing.llm.evaluate {{session}} {{k}}"
            (sd / "submit.sh").write_text(SUBMIT.format(session=shlex.quote(str(ev)), root=shlex.quote(str(paths.ROOT)),
                                                        evaluator=tmpl.format(session=shlex.quote(str(ev)), k='"$k"')))
            sess = {"task_id": t["task_id"], "case_dir": t["case_dir"], "model_tag": tag, "rep": rep,
                    "entry": "agent session, file-scoped workspace, every tool call audited", "max_proposals": nmax,
                    "interface": cfg.get("interface", "sharing")}
            if cfg.get("model"):
                sess["model"] = cfg["model"]
            json.dump(sess, open(ev / "session.json", "w"), indent=1)
            made.append(str(sd))
    json.dump(made, open(ws / tag / "sessions.json", "w"), indent=1)
    print(len(made), "sessions prepared under", ws / tag)


def classify(cmd, folder):
    """Class of a Bash command that is not exactly `bash submit.sh <k>`."""
    roots = r"(?:Users|private|home|tmp|etc|var|opt|Applications|System|Library|usr|bin|dev|proc)"
    outside = [x for x in re.findall(rf"(?:^|(?<=[\s'\"=]))(/{roots}\b[^\s'\"<>|;&]*)", cmd) if not x.startswith(folder) and x != "/dev/null"]
    risky = re.search(r"\.\./|\bls\b|\bfind\b|\bgrep\s+-\w*[rR]|\bcat\s+/|\bcurl\b|\bwget\b|\bssh\b|\bscp\b|~/|\$HOME", cmd)
    return "isolation_breach" if (outside or risky) else "in_folder_edit"


def audit(amap, tdir):
    out = {}
    for aid, folder in amap.items():
        folder = folder.rstrip("/"); f = Path(tdir) / f"agent-{aid}.jsonl"
        if not f.exists():
            out[aid] = {"folder": folder, "error": "transcript not found"}; continue
        calls = []; flags = []
        for line in open(f):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            content = (e.get("message") or {}).get("content")
            for c in content if isinstance(content, list) else []:
                if c.get("type") != "tool_use":
                    continue
                name = c.get("name"); inp = c.get("input") or {}
                call = {"tool": name, "input": {k: str(v)[:200] for k, v in inp.items()}}; calls.append(call)
                if name in ("Read", "Write", "Edit"):
                    ok = str(inp.get("file_path", "")).startswith(folder + "/")
                elif name == "Bash":
                    cmd = str(inp.get("command", "")).strip()
                    ok = bool(re.fullmatch(rf"(cd {re.escape(folder)} && )?bash submit\.sh \d+", cmd))
                    if not ok:
                        call["class"] = classify(cmd, folder)
                else:
                    ok = False
                if not ok:
                    call.setdefault("class", "isolation_breach"); flags.append(call)
        out[aid] = {"folder": folder, "n_tool_calls": len(calls), "flagged": flags, "clean": not flags,
                    "tools": sorted({c["tool"] for c in calls}), "breach": any(x["class"] == "isolation_breach" for x in flags),
                    "in_folder_edits": sum(1 for x in flags if x["class"] == "in_folder_edit")}
    return out


def main():
    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare(json.load(open(sys.argv[2])))
    elif cmd == "launch":
        print(LAUNCH_TEXT.format(folder=Path(sys.argv[2]).resolve(), max_proposals=int(sys.argv[3]) if len(sys.argv) > 3 else 8))
    elif cmd == "audit":
        res = audit(json.load(open(sys.argv[2])), sys.argv[3]); json.dump(res, open(sys.argv[4], "w"), indent=1)
        print(sum(1 for v in res.values() if v.get("clean")), "clean of", len(res), "| flagged as breach",
              sum(1 for v in res.values() if v.get("breach")), "| sessions with in-folder edits", sum(1 for v in res.values() if v.get("in_folder_edits")))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
