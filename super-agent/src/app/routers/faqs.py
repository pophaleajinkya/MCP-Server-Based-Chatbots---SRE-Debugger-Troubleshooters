"""FAQs endpoint based on agent.json capabilities."""

import json
from pathlib import Path
from fastapi import APIRouter, Request

router = APIRouter(tags=["faqs"])

@router.get("/group/faqs", summary="Get How-To prompts based on agent skills")
async def get_faqs(request: Request):
    """Return a list of FAQs from faqs.json combined with dynamic MCP capabilities."""
    faqs = []
    
    # 1. Try reading a dedicated faqs.json (if provided by developer)
    faqs_json_path = Path(__file__).parents[2] / "agent" / "faqs.json"
    if faqs_json_path.exists():
        try:
            with faqs_json_path.open("r", encoding="utf-8") as f:
                faqs.extend(json.load(f))
        except Exception:
            pass
            
    # 2. Add dynamically generated FAQs from connected MCP servers
    dynamic_faqs = getattr(request.app.state, "dynamic_faqs", [])
    if dynamic_faqs:
        # Merge carefully to avoid duplicates if titles overlap
        existing_titles = {g.get("title") for g in faqs}
        for df in dynamic_faqs:
            if df.get("title") not in existing_titles:
                faqs.append(df)
            else:
                # Merge FAQs into existing group
                for existing_group in faqs:
                    if existing_group.get("title") == df.get("title"):
                        existing_group.setdefault("faqs", []).extend(df.get("faqs", []))
                        break
                        
    # 3. Fallback to old agent.json if no faqs at all
    if not faqs:
        agent_json_path = Path(__file__).parents[2] / "agent" / "agent.json"
        try:
            with agent_json_path.open("r", encoding="utf-8") as f:
                card_data = json.load(f)
            
            for skill in card_data.get("skills", []):
                examples = skill.get("examples", [])
                if examples:
                    faqs.append({
                        "title": skill.get("name", "Unknown Skill"),
                        "description": skill.get("description", ""),
                        "faqs": examples
                    })
        except Exception:
            pass
            
    return faqs
