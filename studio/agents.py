"""
Agent system — Agent class, BLACKBOARD shared memory, roster helpers.
ai_respond is injected at call-time (Agent.run) to avoid circular imports.
"""
import json
import re

from studio.console import console
from studio.data import AGENT_ROSTER
from studio.project import format_project_context

BLACKBOARD: dict = {}


class Agent:
    def __init__(self, agent_id, state, project_ctx=None, blackboard=None):
        self.id          = agent_id
        info             = AGENT_ROSTER.get(agent_id, {})
        self.name        = info.get("name", agent_id.title())
        self.emoji       = info.get("emoji", "🤖")
        self.color       = info.get("color", "bold cyan")
        self.role        = info.get("role", "Agent")
        self.state       = state.copy()
        self.blackboard  = blackboard if blackboard is not None else BLACKBOARD
        self.state["system_prompt"] = info.get("persona", "You are a helpful AI agent.")
        if project_ctx and "error" not in project_ctx:
            self.state["system_prompt"] += (
                f"\n\nProject Context: {project_ctx.get('root', '')}"
                f"\nShared Blackboard: {json.dumps(self.blackboard)}"
                f"\nYou can delegate tasks to other agents using [AGENT:id]task[/AGENT]. "
                f"Available: {', '.join(AGENT_ROSTER.keys())}"
            )
        self.history     = []
        self.project_ctx = project_ctx

    def run(self, task, console_obj, ai_respond_fn):
        console_obj.print(
            f"\n[{self.color}]{self.emoji} {self.name}[/{self.color}] "
            f"[dim]{self.role} — working...[/dim]"
        )
        full_task = task
        if self.project_ctx and not self.history:
            ctx_str   = format_project_context(self.project_ctx, max_files=10)
            full_task = ctx_str + "\n\n---\n\nTask: " + task

        text, self.history = ai_respond_fn(self.state, full_task, self.history)
        if not text:
            return ""

        # AGENT MESH: check for handoff tags
        mesh_p = re.compile(r"\[AGENT:(.+?)\](.*?)\[/AGENT\]", re.DOTALL)
        for m in mesh_p.finditer(text):
            target_id = m.group(1).strip().lower()
            sub_task  = m.group(2).strip()
            if target_id in AGENT_ROSTER and target_id != self.id:
                console_obj.print(f"  [dim]↳ Handoff to [bold]{target_id}[/bold]...[/dim]")
                sub_agent = Agent(target_id, self.state, self.project_ctx, self.blackboard)
                sub_res   = sub_agent.run(sub_task, console_obj, ai_respond_fn)
                self.history.append({"role": "user", "text": f"Result from {target_id}: {sub_res}"})
                text, self.history = ai_respond_fn(
                    self.state, "Continue based on the result above.", self.history
                )

        return text or ""


def pick_best_agent(task):
    task_lower = task.lower()
    scores     = {
        aid: sum(1 for kw in info["specialties"] if kw in task_lower)
        for aid, info in AGENT_ROSTER.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "lucifer"


def auto_assign_agents(task):
    task_lower = task.lower()
    assigned   = [
        aid for aid, info in AGENT_ROSTER.items()
        if any(kw in task_lower for kw in info["specialties"])
    ]
    return (assigned or ["lucifer"])[:3]
