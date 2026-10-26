"""A shared visible memory: complete current source and all physical feedback."""
import copy

VERSION = "current_source_and_feedback_v1"


def current_state_request(packet, history, complete_sources):
    if set(complete_sources) != set(packet["visible_sources"]) or not all(isinstance(value, str) for value in complete_sources.values()):
        raise ValueError("Supply every complete visible source from the trusted gateway")
    task = copy.deepcopy(packet)
    task["visible_sources"] = copy.deepcopy(complete_sources)
    visible = []
    for event in history:
        row = copy.deepcopy(event)
        observation = row.get("observation", {})
        if (set(observation) == {"path", "content"} and observation["path"] in complete_sources
                and isinstance(observation["content"], str)):
            row["observation"] = {"path": observation["path"],
                "complete_current_source_in_task_packet": True,
                "historical_read_source_payload_superseded": True}
        action = row.get("action")
        if action and action.get("action") == "propose_patch":
            action.pop("patch")
            action["raw_patch_retained_in_trial_log"] = True
        visible.append(row)
    return {"task_packet": task, "visible_history": visible}
