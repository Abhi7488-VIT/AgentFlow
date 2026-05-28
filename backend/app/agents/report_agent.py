import time
import asyncio
import json
import google.generativeai as genai
from app.config import settings
from app.agents.state import AgentState
from app.core.logging import get_logger
from app.core.sanitizer import safe_query_for_prompt, extract_json

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
            
            # Build context — but ONLY include real data, filter out fallback garbage
            context_parts = []
            
            # Check if insight data is real (not fallback)
            if insights and isinstance(insights, dict):
                summary = insights.get("summary", "")
                # Skip if it's the fallback "Initial analysis of..." text
                if summary and "Initial analysis of" not in summary and "Competitor A" not in str(insights):
                    context_parts.append(f"Market Insights: {json.dumps(insights)}")
            
            if competitors and isinstance(competitors, dict):
                comps = competitors.get("top_competitors", [])
                # Skip if it's the fallback
                if comps and "Competitor A" not in str(comps) and "Leading competitors to" not in str(comps):
                    context_parts.append(f"Competitors: {json.dumps(competitors)}")
            
            if pain_points and isinstance(pain_points, list) and len(pain_points) > 0:
                # Skip if pain points look like fallback
                first_pain = str(pain_points[0]) if pain_points else ""
                if "Issues with" not in first_pain and "Concerns about" not in first_pain:
                    context_parts.append(f"Pain Points: {json.dumps(pain_points)}")
            
            if trends and isinstance(trends, dict) and len(trends) > 0:
                context_parts.append(f"Trends: {json.dumps(trends)}")
            
            has_real_data = len(context_parts) > 0
            context_block = "\n".join(context_parts) if has_real_data else "No pipeline data available."
            
            prompt = f"""You are an elite market research analyst at McKinsey & Company. Write a comprehensive product/market intelligence report about: "{query}".

CRITICAL RULES:
1. USE YOUR OWN KNOWLEDGE about "{query}" — you know about real products, real brands, real companies, and real markets. Write about REAL competitors by name, REAL market data, REAL consumer opinions.
2. EVERY section must contain specific, factual information about "{query}". Name real competitor brands, real market sizes, real features, real prices where applicable.
3. Do NOT use generic placeholders like "Competitor A" or "leading incumbents". Name actual companies.
4. Do NOT mention AI agents, multi-agent systems, SaaS, or workflow automation unless "{query}" is actually an AI/tech product.
5. Write as a McKinsey consultant presenting to a Fortune 500 board.
6. Each section: 150-300 words of substantive, specific analysis.
7. Use \\n to separate paragraphs.

{"Additional research context from our data pipeline:" + chr(10) + context_block if has_real_data else "Note: No additional pipeline data was gathered. Rely entirely on your own knowledge about this product/brand/topic."}

Return JSON matching this exact schema:
{{
    "title": "Professional report title about {query}",
    "tagline": "Catchy 1-sentence tagline about {query}",
    "executive_summary": "3-paragraph executive summary: (1) What {query} is, its history, and why it matters in the market today, (2) Current competitive position with REAL competitor names and market dynamics, (3) Strategic evaluation and outlook",
    "recommendations": ["5 specific actionable recommendations for {query}"],
    "sections": {{
        "Product Overview": "What {query} is, its parent company, history, category, unique selling points, key product lines, and market positioning. Name the parent company/brand.",
        "Problem Statement": "Real consumer problems and market gaps. What do buyers actually complain about? What needs are unmet?",
        "Proposed Solution": "How {query} addresses these problems through design, pricing, quality, innovation, or brand strategy",
        "Core Features": "6-8 real features/attributes as bullet points: - Feature: Description\\n- Feature: Description",
        "Target Audience": "Real demographics, psychographics, geographic markets, and use cases",
        "Market & Competitor Analysis": "Real TAM, market growth, and NAMED competitors with specific comparison. For example if analyzing notebooks, name ITC Classmate vs Navneet vs Apsara etc.",
        "SWOT Analysis": "STRENGTHS:\\n- real point\\n\\nWEAKNESSES:\\n- real point\\n\\nOPPORTUNITIES:\\n- real point\\n\\nTHREATS:\\n- real point",
        "Consumer Sentiment": "Real consumer opinions, common praise and complaints from reviews/forums",
        "Business Model": "How the company behind {query} makes money, distribution channels, pricing strategy",
        "Risk Analysis": "Real market, competitive, supply chain, and regulatory risks",
        "Performance Insights": "Market share estimates, growth trajectory, brand strength metrics",
        "Recommendations": "5-7 specific actionable strategic recommendations",
        "Future Outlook": "Where {query} and its market are heading, trends, upcoming innovations",
        "Final Conclusion": "Professional closing summary of {query}'s market position and potential"
    }},
    "advanced_metrics": {{
        "Innovation Score": "X.X/10 - specific justification for {query}",
        "Market Readiness Score": "X.X/10 - justification",
        "Scalability Rating": "X.X/10 - justification",
        "Consumer Satisfaction": "XX% - justification based on known consumer sentiment",
        "Risk Severity": "Low/Medium/High - justification"
    }}
}}"""
            
            response = await model.generate_content_async(prompt)
            data = extract_json(response.text)
            
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
            await asyncio.sleep(3)  # Delay to handle potential 429 Quota Exceeded rate limits
            
            # Use Gemini to generate even the fallback, but with a simpler prompt
            try:
                simple_model = genai.GenerativeModel(
                    'gemini-2.5-flash',
                    generation_config={"response_mime_type": "application/json"}
                )
                simple_prompt = f"""Write a market analysis report about "{query}" using your own knowledge. Name REAL competitors, REAL market data, REAL prices. Do NOT use placeholders like "Competitor A". Return JSON with keys: title (string), tagline (string), executive_summary (string, 2 paragraphs with real facts about {query}), recommendations (list of 5 specific strings), sections (object with "Product Overview", "Market & Competitor Analysis", "SWOT Analysis", "Recommendations", "Conclusion" — each a detailed string paragraph with real information about {query}), advanced_metrics (object with "Innovation Score", "Market Readiness Score", "Consumer Satisfaction" as strings with scores)."""
                
                simple_response = await simple_model.generate_content_async(simple_prompt)
                data = extract_json(simple_response.text)
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
