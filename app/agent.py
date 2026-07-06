# ruff: noqa
import datetime
import json
import logging
import re
import sys
from typing import Any

from google.adk import Agent, Workflow
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.workflow import node, Edge, START, DEFAULT_ROUTE
from google.adk.tools import AgentTool, McpToolset
from google.genai import types
from mcp import StdioServerParameters

from app.config import config

logger = logging.getLogger("wardrobe_stylist.agent")

# --- MCP Toolset Configuration ---
# Connect to the local stdio MCP server using the current Python interpreter
mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"]
    )
)

# --- Function Nodes ---

@node
async def security_checkpoint(ctx, node_input: str) -> Event:
    """Checks user query for prompt injections, scrubs PII, and applies domain safety rules."""
    # 1. PII Scrubbing (Email, Phone, Credit Card)
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    phone_pattern = r'\b(?:\+?\d{1,3}[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b'
    cc_pattern = r'\b(?:\d[ -]*?){13,16}\b'
    
    scrubbed = node_input
    scrubbed, email_count = re.subn(email_pattern, "[EMAIL_REDACTED]", scrubbed)
    scrubbed, phone_count = re.subn(phone_pattern, "[PHONE_REDACTED]", scrubbed)
    scrubbed, cc_count = re.subn(cc_pattern, "[CREDIT_CARD_REDACTED]", scrubbed)
    
    # 2. Prompt Injection Detection
    injection_keywords = [
        "ignore previous instructions",
        "system prompt",
        "override instructions",
        "override rules",
        "forget all previous instructions",
        "forget everything",
        "you must now",
        "new instructions"
    ]
    lower_input = node_input.lower()
    matched_keywords = [kw for kw in injection_keywords if kw in lower_input]
    injection_detected = len(matched_keywords) > 0
    
    # 3. Domain-Specific Rule: Wardrobe styling query checks (no explicit/offensive keywords)
    offensive_pattern = r'\b(nude|naked|explicit|offensive_word_1|offensive_word_2)\b'
    domain_violation = re.search(offensive_pattern, lower_input) is not None
    
    # 4. Structured JSON Audit Log
    severity = "INFO"
    if injection_detected or domain_violation:
        severity = "CRITICAL"
    elif email_count > 0 or phone_count > 0 or cc_count > 0:
        severity = "WARNING"
        
    audit_log = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "severity": severity,
        "event_type": "security_audit",
        "pii_scrubbed": {
            "email_count": email_count,
            "phone_count": phone_count,
            "credit_card_count": cc_count
        },
        "injection_detected": injection_detected,
        "matched_injection_keywords": matched_keywords,
        "domain_violation": domain_violation
    }
    
    logger.info(json.dumps(audit_log))
    print(f"AUDIT_LOG: {json.dumps(audit_log)}")
    
    if injection_detected or domain_violation:
        return Event(
            route="SECURITY_EVENT", 
            output="Security Policy violation: The request has been flagged and rejected."
        )
        
    # Save the scrubbed query to context state
    ctx.state["query"] = scrubbed
    return Event(output=scrubbed)


@node
async def security_event_node(ctx, node_input: str) -> str:
    """Terminal node for handling security violations."""
    return f"Access Denied: {node_input}"


@node(rerun_on_resume=True)
async def human_confirmation(ctx, node_input: Any):
    """Prompts human-in-the-loop validation for outfit recommendations."""
    if not ctx.state.get("needs_human_confirmation"):
        yield node_input
        return
        
    interrupt_id = "human_style_confirm"
    user_confirm = ctx.resume_inputs.get(interrupt_id)
    
    if user_confirm is None:
        yield RequestInput(
            interrupt_id=interrupt_id,
            message="Please confirm if you approve this suggested outfit (yes/no):"
        )
        return
        
    user_decision = str(user_confirm).lower().strip()
    if "yes" in user_decision or "approve" in user_decision:
        ctx.state["needs_human_confirmation"] = False
        yield f"Approved outfit details:\n{node_input}"
    else:
        ctx.state["needs_human_confirmation"] = False
        ctx.state["retry_feedback"] = "The user rejected the suggestion. Please offer an alternative outfit."
        yield Event(
            route="RETRY", 
            output=f"Outfit rejected by human user. Feedback: {user_confirm}"
        )


@node
async def final_output(ctx, node_input: Any) -> str:
    """Terminal node presenting the final response."""
    return str(node_input)


# --- Specialized LLM Sub-agents ---
# Mode must be "chat" (default) for sub-agents executed via AgentTool,
# as AgentTool's inner runner executes them as a root agent.

wardrobe_manager = Agent(
    name="wardrobe_manager",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are the Wardrobe Manager. You are responsible for inventory management. "
        "You add new clothing items to the wardrobe catalog, delete items, search items, "
        "and track how often items are worn (wear frequency). "
        "Always use the available wardrobe database tools from the MCP toolset to perform these tasks."
    ),
    tools=[mcp_toolset],
    mode="chat"
)

stylist_advisor = Agent(
    name="stylist_advisor",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are the Stylist Advisor. You recommend outfit combinations based on weather, "
        "events (casual, formal, sport), and style guidelines. "
        "Check weather conditions using the weather tools and fetch appropriate clothing items from the wardrobe inventory. "
        "Suggest complete outfits (top, bottom, shoes, accessories) and explain why they match."
    ),
    tools=[mcp_toolset],
    mode="chat"
)

# --- Orchestrator Agent ---
# Mode must be "single_turn" since it is placed in the Workflow graph
# after the security_checkpoint function node.

wardrobe_orchestrator = Agent(
    name="wardrobe_orchestrator",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are the Wardrobe Stylist Orchestrator. "
        "Your task is to coordinate wardrobe catalog management and styling requests. "
        "For any request involving inventory, search, cataloging, adding or deleting clothing items, "
        "or wear count tracking, delegate it to the wardrobe_manager. "
        "For styling recommendations, matching, or coordinating outfits based on events or weather, "
        "delegate to the stylist_advisor. "
        "If you suggest a specific styling or outfit combination to the user, you MUST set 'needs_human_confirmation' to True in the session state so the user can approve/reject it. "
        "Keep the conversation concise and professional."
    ),
    tools=[
        AgentTool(agent=wardrobe_manager),
        AgentTool(agent=stylist_advisor)
    ],
    mode="single_turn"
)


# --- Graph & Workflow Setup ---

edges = [
    (START, security_checkpoint),
    Edge(from_node=security_checkpoint, to_node=security_event_node, route="SECURITY_EVENT"),
    Edge(from_node=security_checkpoint, to_node=wardrobe_orchestrator, route=DEFAULT_ROUTE),
    (wardrobe_orchestrator, human_confirmation),
    Edge(from_node=human_confirmation, to_node=wardrobe_orchestrator, route="RETRY"),
    Edge(from_node=human_confirmation, to_node=final_output, route=DEFAULT_ROUTE),
    (security_event_node, final_output)
]

wardrobe_workflow = Workflow(
    name="wardrobe_workflow",
    edges=edges
)

app = App(
    root_agent=wardrobe_workflow,
    name="app",
)
