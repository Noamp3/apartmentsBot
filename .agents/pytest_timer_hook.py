import sys
import json
import os
import re

def main():
    try:
        # Read hook input from stdin
        input_data = json.loads(sys.stdin.read())
    except Exception:
        # If stdin is not valid JSON, exit with empty response
        print(json.dumps({}))
        return

    transcript_path = input_data.get("transcriptPath")
    if not transcript_path or not os.path.exists(transcript_path):
        print(json.dumps({}))
        return

    # Read the transcript file
    steps = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    steps.append(json.loads(line))
    except Exception:
        print(json.dumps({}))
        return

    # 1. Find the latest model step that called pytest
    last_pytest_step_idx = -1
    
    for i, step in enumerate(steps):
        tool_calls = step.get("tool_calls") or []
        for tool_call in tool_calls:
            if tool_call.get("name") == "run_command":
                cmd = tool_call.get("args", {}).get("CommandLine", "")
                if "pytest" in cmd:
                    last_pytest_step_idx = i

    if last_pytest_step_idx == -1:
        # No pytest command found in the transcript
        print(json.dumps({}))
        return

    # 2. Check if the latest pytest task is finished
    task_id = None
    task_finished = False

    # Search forward from last_pytest_step_idx to extract task ID
    for step in steps[last_pytest_step_idx:]:
        content = step.get("content", "") or ""
        match = re.search(r"task id:\s*([a-zA-Z0-9\-_/]+)", content, re.IGNORECASE)
        if not match:
            match = re.search(r"Task:\s*([a-zA-Z0-9\-_/]+)", content, re.IGNORECASE)
        if match:
            task_id = match.group(1)
            break

    if task_id:
        # We found a background task ID. Check if it completed or cancelled.
        for step in steps[last_pytest_step_idx:]:
            content = step.get("content", "") or ""
            if task_id in content:
                # Check for completion/cancellation messages
                if any(x in content.lower() for x in ["completed", "cancelled", "canceled", "finished", "terminated"]):
                    task_finished = True
                    break
    else:
        # If no background task ID was found, we assume it was run synchronously and finished
        task_finished = True

    if task_finished:
        print(json.dumps({}))
        return

    # 3. Task is still running. Count scheduled vs fired timers since last_pytest_step_idx.
    timer_prompt = "[Antigravity Timer] Check pytest results"
    num_scheduled = 0
    num_fired = 0

    for step in steps[last_pytest_step_idx:]:
        tool_calls = step.get("tool_calls") or []
        for tool_call in tool_calls:
            if tool_call.get("name") == "schedule":
                prompt_arg = tool_call.get("args", {}).get("Prompt", "")
                if timer_prompt in prompt_arg:
                    num_scheduled += 1
        
        # Count fired notifications (source is not MODEL)
        content = step.get("content", "") or ""
        if timer_prompt in content:
            if step.get("source") != "MODEL":
                num_fired += 1

    # 4. Decide whether to schedule a new timer
    if num_scheduled <= num_fired:
        # Either no timer scheduled yet, or the last one fired. Schedule a new one.
        response = {
            "injectSteps": [
                {
                  "toolCall": {
                    "name": "schedule",
                    "args": {
                      "DurationSeconds": "15",
                      "Prompt": timer_prompt
                    }
                  }
                }
            ]
        }
        print(json.dumps(response))
    else:
        # A timer is already pending, don't schedule a duplicate
        print(json.dumps({}))

if __name__ == "__main__":
    main()
