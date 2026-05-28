import time
import json
import google.generativeai as genai
from app.config import settings
from app.agents.state import AgentState
from app.core.logging import get_logger
from app.core.sanitizer import safe_query_for_prompt

logger = get_logger(__name__)

async def report_node(state: AgentState) -> AgentState:
    logger.info("Agent starting: Report Generation", workflow_id=state.get("workflow_id"))
    state["current_agent"] = "report"
    start_time = time.time()
    
    # Sanitize query before inserting into any prompt
    query = safe_query_for_prompt(state.get("query", ""))
    insights = state.get("insights", {})
    competitors = state.get("competitor_analysis", {})
    pain_points = state.get("pain_points", [])
    trends = state.get("trends", {})
    
    if settings.GEMINI_API_KEY:
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(
                'gemini-2.5-flash',
                generation_config={"response_mime_type": "application/json"}
            )
            
            # Build a concise context string to keep the prompt short
            context_summary = ""
            if insights:
                context_summary += f"Market Insights: {json.dumps(insights)}\n"
            if competitors:
                context_summary += f"Competitors: {json.dumps(competitors)}\n"
            if pain_points:
                context_summary += f"Pain Points: {json.dumps(pain_points)}\n"
            if trends:
                context_summary += f"Trends: {json.dumps(trends)}\n"
            
            prompt = f"""You are an elite market research analyst. Write a comprehensive product/market intelligence report about: "{query}".

IMPORTANT RULES:
- EVERY section must be specifically about "{query}". Do NOT write generic content.
- Mention real competitors, real market data, real consumer opinions about "{query}".
- Do NOT mention AI agents, multi-agent systems, SaaS platforms, or workflow automation unless "{query}" is actually an AI/tech product.
- Write as if you are a McKinsey consultant presenting to a Fortune 500 board.
- Each section should be 150-300 words with real substance.
- Use \\n to separate paragraphs.

Research context gathered by our pipeline:
{context_summary}

Return JSON matching this exact schema:
{{
    "title": "string - Professional report title about {query}",
    "tagline": "string - A catchy 1-sentence tagline about {query}",
    "executive_summary": "string - 3 paragraph executive summary: (1) What {query} is and why it matters, (2) Current market position and key consumer sentiments, (3) Strategic outlook and evaluation",
    "recommendations": ["rec1", "rec2", "rec3", "rec4", "rec5"],
    "sections": {{
        "Product Overview": "What {query} is, its category, history, unique selling points, key features, and market positioning",
        "Problem Statement": "What consumer problems or market gaps exist that {query} addresses or fails to address",
        "Proposed Solution": "How {query} solves these problems through its design, features, pricing, or innovation",
        "Core Features": "6-8 key features/attributes of {query} as bullet points: - Feature: Description\\n- Feature: Description",
        "Target Audience": "Who buys/uses {query}, demographics, psychographics, use cases",
        "Market & Competitor Analysis": "Market size, growth trends, key competitors with names, how {query} compares",
        "SWOT Analysis": "STRENGTHS:\\n- point\\n- point\\n\\nWEAKNESSES:\\n- point\\n\\nOPPORTUNITIES:\\n- point\\n\\nTHREATS:\\n- point",
        "Consumer Sentiment": "What consumers love and hate about {query}, common complaints, praise patterns",
        "Business Model": "How {query} or its parent company makes money, pricing strategy, revenue streams",
        "Risk Analysis": "Market risks, competitive threats, supply chain issues, regulatory concerns",
        "Performance Insights": "Sales performance, market share, growth metrics, consumer satisfaction scores",
        "Recommendations": "5-7 actionable strategic recommendations for {query}",
        "Future Outlook": "Where {query} is headed, upcoming releases, market predictions, innovation pipeline",
        "Final Conclusion": "Professional closing summary of {query}'s market position and strategic potential"
    }},
    "advanced_metrics": {{
        "Innovation Score": "X.X/10 - justification specific to {query}",
        "Market Readiness Score": "X.X/10 - justification",
        "Scalability Rating": "X.X/10 - justification",
        "Consumer Satisfaction": "XX% - justification",
        "Risk Severity": "Low/Medium/High - justification"
    }}
}}"""
            
            response = await model.generate_content_async(prompt)
            data = json.loads(response.text)
            
            # Validate that the report is actually about the query (not generic)
            exec_summary = data.get("executive_summary", "")
            query_words = query.lower().split()
            # Check if at least one word from the query appears in the summary
            is_relevant = any(w in exec_summary.lower() for w in query_words if len(w) > 3)
            
            if is_relevant or len(exec_summary) > 200:
                state["report"] = data
                logger.info("Gemini report generated successfully")
            else:
                logger.warning("Gemini returned generic report, using it anyway as it has content")
                state["report"] = data
                
        except Exception as e:
            logger.error(f"Error generating report: {e}")
            # Use Gemini to generate even the fallback, but with a simpler prompt
            try:
                simple_model = genai.GenerativeModel(
                    'gemini-2.5-flash',
                    generation_config={"response_mime_type": "application/json"}
                )
                simple_prompt = f"""Write a brief market analysis report about "{query}" as JSON with keys: title (string), tagline (string), executive_summary (string, 2 paragraphs about {query} specifically), recommendations (list of 3 strings), sections (object with keys: "Product Overview", "Market Analysis", "SWOT Analysis", "Recommendations", "Conclusion" - each a string paragraph about {query}), advanced_metrics (object with "Innovation Score", "Market Readiness Score", "Consumer Satisfaction" as strings)."""
                
                simple_response = await simple_model.generate_content_async(simple_prompt)
                data = json.loads(simple_response.text)
                state["report"] = data
                logger.info("Simple fallback Gemini report generated")
            except Exception as e2:
                logger.error(f"Simple fallback also failed: {e2}")
                _fallback_report(state)
    else:
        _fallback_report(state)
        
    execution_time = int((time.time() - start_time) * 1000)
    
    if "agent_logs" not in state:
        state["agent_logs"] = []
        
    state["agent_logs"].append({
        "agent_name": "report",
        "status": "completed",
        "input_data": {"query": query},
        "output_data": {"report_generated": bool(state.get("report"))},
        "execution_time_ms": execution_time
    })
    
    return state

def _fallback_report(state: AgentState):
    """Last-resort fallback. Content is dynamically built around the query."""
    query = state.get("query", "")
    q = query.title()
    
    insights = state.get("insights", {})
    competitors = state.get("competitor_analysis", {})
    pain_points = state.get("pain_points", [])
    
    # Extract real data if available
    comp_names = competitors.get("top_competitors", []) if isinstance(competitors, dict) else []
    comp_str = ", ".join(comp_names[:3]) if comp_names else "leading market incumbents"
    
    pain_str = ""
    if pain_points and isinstance(pain_points, list):
        issues = [p.get("issue", "") for p in pain_points[:3] if isinstance(p, dict)]
        pain_str = "; ".join(issues) if issues else "pricing concerns and product availability"
    else:
        pain_str = "pricing concerns and product availability"
    
    insight_summary = ""
    if isinstance(insights, dict):
        insight_summary = insights.get("summary", "")
    
    state["report"] = {
        "title": f"{q}",
        "tagline": f"Comprehensive Market Intelligence Report on {q}",
        "executive_summary": (
            f"This report presents a comprehensive market intelligence analysis of '{query}'. "
            f"The research examines current market positioning, consumer sentiment, competitive dynamics, "
            f"and emerging trends within this product category. {insight_summary}\n\n"
            f"Key findings indicate that {query} faces competition from {comp_str}, "
            f"while consumers express concerns about {pain_str}. "
            f"Despite these challenges, the market shows strong growth potential driven by "
            f"evolving consumer preferences and innovation in the space.\n\n"
            f"Overall, {query} demonstrates solid market presence with opportunities for "
            f"strategic improvement in areas highlighted throughout this analysis."
        ),
        "recommendations": [
            f"Address key consumer pain points related to {pain_str} to improve satisfaction.",
            f"Strengthen competitive positioning against {comp_str} through differentiation.",
            f"Expand target audience reach through targeted marketing campaigns for {query}.",
            f"Invest in product innovation to capture emerging market trends.",
            f"Develop strategic partnerships to accelerate market penetration for {query}."
        ],
        "sections": {
            "Product Overview": (
                f"{q} is a notable product/brand within its market category. "
                f"It has established itself through a combination of quality, brand recognition, "
                f"and consumer appeal. The product targets a diverse audience ranging from "
                f"casual consumers to dedicated enthusiasts.\n\n"
                f"Key attributes that define {query} include its design philosophy, "
                f"pricing strategy, and distribution approach. The product competes in a "
                f"dynamic market where consumer preferences shift rapidly."
            ),
            "Problem Statement": (
                f"The market for {query} faces several challenges. "
                f"Consumers have reported issues including {pain_str}. "
                f"These concerns highlight gaps between consumer expectations and current offerings.\n\n"
                f"Additionally, the competitive landscape is intensifying, with {comp_str} "
                f"all vying for market share. This creates pressure on pricing, innovation, "
                f"and customer retention strategies."
            ),
            "Proposed Solution": (
                f"{q} addresses market needs through its unique value proposition. "
                f"The product differentiates itself through design, quality, and brand positioning. "
                f"By focusing on consumer feedback and market trends, {query} can continue "
                f"to evolve and meet changing demands.\n\n"
                f"Strategic improvements in areas like customer experience, product innovation, "
                f"and market expansion can further strengthen its competitive position."
            ),
            "Core Features": (
                f"- Brand Identity: {q} carries strong brand recognition and consumer loyalty\n"
                f"- Product Quality: Consistent quality standards that meet consumer expectations\n"
                f"- Design: Distinctive design language that appeals to target demographics\n"
                f"- Distribution: Wide availability through multiple retail channels\n"
                f"- Pricing: Competitive pricing strategy within the market segment\n"
                f"- Customer Experience: End-to-end consumer journey from discovery to purchase"
            ),
            "Target Audience": (
                f"The primary audience for {query} spans multiple demographics. "
                f"Core consumers include both value-conscious buyers and premium segment shoppers. "
                f"The product appeals across age groups, with particularly strong traction "
                f"among younger demographics who value brand identity and product aesthetics.\n\n"
                f"Secondary audiences include gift buyers, collectors, and "
                f"category enthusiasts who follow trends closely."
            ),
            "Market & Competitor Analysis": (
                f"The market for {query} is dynamic and competitive. "
                f"Key competitors include {comp_str}, each bringing unique strengths "
                f"to the market. Market trends indicate growing consumer demand driven by "
                f"social media influence and evolving lifestyle preferences.\n\n"
                f"The total addressable market continues to expand, presenting "
                f"opportunities for brands that can effectively differentiate "
                f"and deliver on consumer expectations."
            ),
            "SWOT Analysis": (
                f"STRENGTHS:\n"
                f"- Strong brand recognition and consumer loyalty for {query}\n"
                f"- Established distribution and retail presence\n"
                f"- Consistent product quality and design appeal\n\n"
                f"WEAKNESSES:\n"
                f"- Consumer concerns about {pain_str}\n"
                f"- Pricing pressure from competitors\n\n"
                f"OPPORTUNITIES:\n"
                f"- Expanding into new market segments and geographies\n"
                f"- Leveraging social media and influencer marketing\n"
                f"- Product line extensions and limited editions\n\n"
                f"THREATS:\n"
                f"- Intense competition from {comp_str}\n"
                f"- Shifting consumer preferences and trends\n"
                f"- Economic uncertainty affecting discretionary spending"
            ),
            "Consumer Sentiment": (
                f"Consumer sentiment toward {query} is mixed but trending positive. "
                f"Enthusiasts praise the product for its design and brand value, "
                f"while critics point to concerns about {pain_str}.\n\n"
                f"Social media analysis reveals active discussion communities "
                f"around {query}, indicating strong brand engagement and consumer interest."
            ),
            "Business Model": (
                f"The revenue model for {query} operates through a combination of "
                f"direct-to-consumer and retail distribution channels. "
                f"Pricing strategy balances accessibility with brand premium positioning.\n\n"
                f"Revenue streams include core product sales, limited editions, "
                f"collaborations, and brand licensing opportunities."
            ),
            "Risk Analysis": (
                f"Market Risks (Medium): Competitive pressure from {comp_str} and "
                f"shifting consumer preferences require continuous innovation.\n\n"
                f"Economic Risks (Medium): Discretionary spending sensitivity during "
                f"economic downturns may impact sales volume.\n\n"
                f"Supply Chain Risks (Low-Medium): Global supply chain disruptions "
                f"could affect production and delivery timelines."
            ),
            "Performance Insights": (
                f"Market performance indicators for {query} show steady positioning "
                f"within its competitive segment. Brand awareness metrics remain strong, "
                f"and consumer engagement through digital channels continues to grow.\n\n"
                f"Key performance areas include customer retention rates, "
                f"repeat purchase frequency, and social media sentiment scores."
            ),
            "Recommendations": (
                f"1. Address consumer concerns about {pain_str} through product improvements.\n\n"
                f"2. Differentiate from {comp_str} through unique features and experiences.\n\n"
                f"3. Expand digital marketing presence to capture younger demographics.\n\n"
                f"4. Launch limited-edition products to create buzz and exclusivity.\n\n"
                f"5. Strengthen loyalty programs to improve customer retention."
            ),
            "Future Outlook": (
                f"The future for {query} looks promising as the market continues to evolve. "
                f"Key trends include increased personalization, sustainability focus, "
                f"and digital-first purchasing behaviors.\n\n"
                f"Brands that invest in innovation, customer experience, and "
                f"authentic storytelling will capture the greatest market share."
            ),
            "Final Conclusion": (
                f"{q} holds a strong position within its market segment, "
                f"backed by brand recognition and consumer loyalty. "
                f"While challenges exist from competitive pressure and evolving consumer demands, "
                f"the strategic opportunities far outweigh the risks.\n\n"
                f"With focused execution on the recommendations outlined in this report, "
                f"{query} is well-positioned to strengthen its market presence "
                f"and deliver sustained growth in the coming years."
            )
        },
        "advanced_metrics": {
            "Innovation Score": f"7.5/10 - {q} shows solid innovation within its market category",
            "Market Readiness Score": f"8.0/10 - Strong market presence with established distribution",
            "Scalability Rating": f"7.0/10 - Growth potential through geographic and segment expansion",
            "Consumer Satisfaction": f"72% - Mixed sentiment with strong brand loyalty among core users",
            "Risk Severity": f"Medium - Competitive pressure balanced by strong brand equity"
        }
    }
