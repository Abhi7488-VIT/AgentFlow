import time
import json
import google.generativeai as genai
from app.config import settings
from app.agents.state import AgentState
from app.core.logging import get_logger

logger = get_logger(__name__)

async def insight_node(state: AgentState) -> AgentState:
    logger.info("Agent starting: Insight Generation", workflow_id=state.get("workflow_id"))
    state["current_agent"] = "insights"
    start_time = time.time()
    
    query = state.get("query", "")
    topics = state.get("topics", [])
    keywords = state.get("keywords", [])
    trends = state.get("trends", {})
    
    # Try Gemini if available
    if settings.GEMINI_API_KEY:
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(
                'gemini-2.5-flash',
                generation_config={"response_mime_type": "application/json"}
            )
            
            prompt = f"""
            Analyze the following market research data for query: "{query}"
            
            Topics Extracted: {json.dumps(topics, indent=2)}
            Keywords: {json.dumps(keywords, indent=2)}
            Trend Data: {json.dumps(trends, indent=2)}
            
            Generate a JSON response with the following structure:
            {{
                "insights": {{"summary": "Overall market summary", "key_trends": ["trend1", "trend2"]}},
                "competitor_analysis": {{"top_competitors": ["comp1", "comp2"], "strengths": ["s1", "s2"], "weaknesses": ["w1", "w2"]}},
                "pain_points": [{{"issue": "description", "severity": "High/Medium/Low", "frequency": "Common/Rare"}}]
            }}
            """
            
            response = await model.generate_content_async(prompt)
            data = json.loads(response.text)
            
            state["insights"] = data.get("insights", {})
            state["competitor_analysis"] = data.get("competitor_analysis", {})
            state["pain_points"] = data.get("pain_points", [])
            
        except Exception as e:
            logger.error(f"Error using Gemini for insights: {e}")
            _fallback_insights(state)
    else:
        _fallback_insights(state)
        
    execution_time = int((time.time() - start_time) * 1000)
    
    if "agent_logs" not in state:
        state["agent_logs"] = []
        
    state["agent_logs"].append({
        "agent_name": "insights",
        "status": "completed",
        "input_data": {"query": query},
        "output_data": {"pain_points_found": len(state.get("pain_points", []))},
        "execution_time_ms": execution_time
    })
    
    return state

def _fallback_insights(state: AgentState):
    # Basic rule-based fallback if LLM is unavailable
    query = state.get("query", "")
    keywords = state.get("keywords", [])
    
    top_words = [k["keyword"] for k in keywords[:5]] if keywords else ["battery", "price", "quality"]
    
    state["insights"] = {
        "summary": f"Initial analysis of '{query}' suggests discussion centers around {', '.join(top_words)}.",
        "key_trends": ["Mixed sentiment across platforms", "Focus on technical specifications"]
    }
    state["competitor_analysis"] = {
        "top_competitors": ["Competitor A", "Competitor B"],
        "strengths": ["Brand recognition", "Ecosystem"],
        "weaknesses": ["Price", "Battery life"]
    }
    state["pain_points"] = [
        {"issue": f"Issues with {top_words[0]}", "severity": "High", "frequency": "Common"},
        {"issue": f"Concerns about {top_words[1]}", "severity": "Medium", "frequency": "Common"}
    ] if len(top_words) >= 2 else []
